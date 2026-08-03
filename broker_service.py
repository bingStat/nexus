from __future__ import annotations

import hmac
import http.server
import json
import os
import socket
import sqlite3
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

VERSION = "2.5.0"
UTC = timezone.utc
TERMINAL = {"completed", "failed", "timeout", "expired", "cancelled"}
API_URL = os.getenv("NEXUS_API_URL", "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1").rstrip("/")
API_KEY = os.getenv("NEXUS_API_KEY", "")
BROKER_TOKEN = os.getenv("NEXUS_BROKER_TOKEN", API_KEY)
REGION = os.getenv("NEXUS_BROKER_REGION", "unknown").strip().lower() or "unknown"
TARGETS = {
    item.strip().lower()
    for item in os.getenv("NEXUS_BROKER_TARGETS", "").split(",")
    if item.strip()
}
DB_PATH = Path(os.getenv("NEXUS_BROKER_DB", "/var/lib/nexus-broker/broker.db"))
BIND = os.getenv("NEXUS_BROKER_BIND", "127.0.0.1")
PORT = int(os.getenv("NEXUS_BROKER_PORT", "18000"))
SCAN_SECONDS = max(1.0, float(os.getenv("NEXUS_BROKER_SCAN_SECONDS", "3")))
MAX_BODY = 2_000_000


def now() -> datetime:
    return datetime.now(UTC)


def now_iso() -> str:
    return now().isoformat()


def parse_time(value: Any) -> datetime:
    text = str(value or now_iso()).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def log(event: str, **fields: Any) -> None:
    print(json.dumps({"ts": now_iso(), "event": event, "region": REGION, **fields}, ensure_ascii=False, separators=(",", ":")), flush=True)


def api_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=2, connect=2, read=1, backoff_factor=0.2, status_forcelist=(502, 503, 504), allowed_methods=None)
    adapter = HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if API_KEY:
        session.headers.update({"Authorization": f"Bearer {API_KEY}", "apikey": API_KEY})
    session.headers.update({"Content-Type": "application/json", "Connection": "keep-alive"})
    return session


class Store:
    COLUMNS = {
        "idempotency_key": "TEXT NOT NULL DEFAULT ''",
        "home_region": "TEXT NOT NULL DEFAULT ''",
        "origin_broker": "TEXT NOT NULL DEFAULT ''",
        "lease_owner": "TEXT",
        "lease_expires_at": "TEXT",
        "attempt": "INTEGER NOT NULL DEFAULT 0",
    }

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.condition = threading.Condition()
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute("PRAGMA busy_timeout=10000")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    target_device TEXT NOT NULL,
                    command TEXT NOT NULL,
                    timeout_ms INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    output TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    claimed_at TEXT,
                    result_json TEXT,
                    source TEXT NOT NULL,
                    sync_needed INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            existing = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            for name, ddl in self.COLUMNS.items():
                if name not in existing:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")
            db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_target_created ON jobs(status,target_device,created_at)")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency ON jobs(idempotency_key) WHERE idempotency_key <> ''")

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        raw = result.pop("result_json", None)
        if raw:
            try:
                result.update(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                pass
        result.pop("sync_needed", None)
        result["_source"] = result.pop("source", None)
        result["broker_region"] = REGION
        return result

    def submit(self, payload: dict[str, Any], source: str, sync_needed: bool) -> dict[str, Any]:
        job_id = str(payload.get("id") or uuid.uuid4())
        idem = str(payload.get("idempotency_key") or job_id).strip()
        target = str(payload.get("target_device") or payload.get("device") or "").strip()
        command = str(payload.get("command") or "")
        if not target or not command:
            raise ValueError("target_device and command are required")
        created_at = str(payload.get("created_at") or now_iso())
        record = {
            "id": job_id,
            "idempotency_key": idem,
            "target_device": target,
            "command": command,
            "timeout_ms": max(1000, int(payload.get("timeout_ms") or 30000)),
            "status": str(payload.get("status") or "pending"),
            "output": str(payload.get("output") or ""),
            "created_at": created_at,
            "updated_at": str(payload.get("updated_at") or created_at),
            "home_region": str(payload.get("home_region") or REGION),
            "origin_broker": str(payload.get("origin_broker") or REGION),
        }
        with self.connect() as db:
            existing = db.execute("SELECT * FROM jobs WHERE id=? OR idempotency_key=? LIMIT 1", (job_id, idem)).fetchone()
            if existing is not None:
                if str(existing["target_device"]) != target or str(existing["command"]) != command:
                    raise ValueError("idempotency key conflicts with a different command")
                return self.row_dict(existing) or record
            db.execute(
                """
                INSERT INTO jobs
                (id,idempotency_key,target_device,command,timeout_ms,status,output,created_at,updated_at,
                 source,sync_needed,home_region,origin_broker,attempt)
                VALUES (:id,:idempotency_key,:target_device,:command,:timeout_ms,:status,:output,:created_at,:updated_at,
                        :source,:sync_needed,:home_region,:origin_broker,0)
                """,
                {**record, "source": source, "sync_needed": 1 if sync_needed else 0},
            )
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        with self.condition:
            self.condition.notify_all()
        return self.row_dict(row) or record

    def claim(self, aliases: set[str], agent_id: str) -> dict[str, Any] | None:
        normalized = sorted({alias.strip().lower() for alias in aliases if alias.strip()})
        if not normalized:
            return None
        placeholders = ",".join("?" for _ in normalized)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                f"SELECT * FROM jobs WHERE status='pending' AND lower(target_device) IN ({placeholders}) ORDER BY created_at LIMIT 1",
                normalized,
            ).fetchone()
            if row is None:
                db.execute("COMMIT")
                return None
            claimed_at = now()
            lease_expires = claimed_at + timedelta(seconds=max(90.0, float(row["timeout_ms"]) / 1000.0 + 60.0))
            changed = db.execute(
                """UPDATE jobs SET status='running',claimed_at=?,updated_at=?,lease_owner=?,lease_expires_at=?,
                   attempt=attempt+1,sync_needed=1 WHERE id=? AND status='pending'""",
                (claimed_at.isoformat(), claimed_at.isoformat(), agent_id, lease_expires.isoformat(), row["id"]),
            ).rowcount
            if changed != 1:
                db.execute("ROLLBACK")
                return None
            db.execute("COMMIT")
            claimed = db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
        result = self.row_dict(claimed)
        if result is not None:
            result["broker_managed"] = True
        return result

    def release_claim(self, job_id: str) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET status='pending',claimed_at=NULL,lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE id=? AND status='running'",
                (now_iso(), job_id),
            )
        with self.condition:
            self.condition.notify_all()

    def expire_claim(self, job_id: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='expired',updated_at=?,sync_needed=1 WHERE id=? AND status='running'", (now_iso(), job_id))

    def complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = str(payload.get("id") or payload.get("job_id") or "").strip()
        status = str(payload.get("status") or "failed")
        if not job_id or status not in TERMINAL:
            raise ValueError("valid id and terminal status are required")
        output = str(payload.get("output") or "")[-1_000_000:]
        updated_at = str(payload.get("updated_at") or now_iso())
        supplied_owner = str(payload.get("lease_owner") or "")
        with self.connect() as db:
            current = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if current is None:
                raise KeyError(job_id)
            if str(current["status"]) in TERMINAL:
                return self.row_dict(current) or dict(payload)
            current_owner = str(current["lease_owner"] or "")
            if supplied_owner and current_owner and supplied_owner != current_owner:
                raise PermissionError("lease owner mismatch")
            result = dict(payload)
            result.update({"id": job_id, "status": status, "output": output, "updated_at": updated_at})
            db.execute(
                """UPDATE jobs SET status=?,output=?,updated_at=?,result_json=?,sync_needed=1,
                   lease_expires_at=NULL WHERE id=?""",
                (status, output, updated_at, json.dumps(result, ensure_ascii=False), job_id),
            )
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        with self.condition:
            self.condition.notify_all()
        return self.row_dict(row) or result

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self.row_dict(row)

    def wait(self, job_id: str, timeout: float) -> dict[str, Any] | None:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            record = self.get(job_id)
            if record and record.get("status") in TERMINAL:
                return record
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return record
            with self.condition:
                self.condition.wait(min(remaining, 1.0))

    def wait_claim(self, aliases: set[str], agent_id: str, timeout: float) -> dict[str, Any] | None:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            record = self.claim(aliases, agent_id)
            if record:
                return record
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            with self.condition:
                self.condition.wait(min(remaining, 1.0))

    def sync_rows(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM jobs WHERE sync_needed=1 ORDER BY updated_at LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def mark_synced(self, job_id: str, updated_at: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE jobs SET sync_needed=0 WHERE id=? AND updated_at=?", (job_id, updated_at))

    def recover_stale(self) -> int:
        current = now()
        recovered = 0
        with self.connect() as db:
            rows = db.execute("SELECT id,lease_expires_at FROM jobs WHERE status='running'").fetchall()
            for row in rows:
                expires = parse_time(row["lease_expires_at"]) if row["lease_expires_at"] else current + timedelta(days=1)
                if current > expires:
                    recovered += db.execute(
                        """UPDATE jobs SET status='pending',claimed_at=NULL,lease_owner=NULL,lease_expires_at=NULL,
                           updated_at=?,sync_needed=1 WHERE id=? AND status='running'""",
                        (current.isoformat(), row["id"]),
                    ).rowcount
        if recovered:
            with self.condition:
                self.condition.notify_all()
        return recovered

    def stats(self) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute("SELECT status,count(*) AS n FROM jobs GROUP BY status").fetchall()
            total = db.execute("SELECT count(*) FROM jobs").fetchone()[0]
        return {"total": total, "by_status": {str(row["status"]): int(row["n"]) for row in rows}}


STORE = Store(DB_PATH)
_CLAIM_LOCAL = threading.local()


def claim_api_session() -> requests.Session:
    session = getattr(_CLAIM_LOCAL, "session", None)
    if session is None:
        session = api_session()
        _CLAIM_LOCAL.session = session
    return session


def confirm_external_claim(record: dict[str, Any]) -> bool:
    if not API_KEY:
        return False
    claimed_at = str(record.get("claimed_at") or record.get("updated_at") or now_iso())
    response = claim_api_session().patch(
        f"{API_URL}/commands",
        params={"id": f"eq.{record['id']}", "status": "eq.pending"},
        json={"status": "running", "updated_at": claimed_at},
        headers={**claim_api_session().headers, "Prefer": "return=representation"},
        timeout=8,
    )
    response.raise_for_status()
    return bool(response.json())


def claim_validated(aliases: set[str], agent_id: str, timeout: float) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        record = STORE.wait_claim(aliases, agent_id, min(remaining, 1.0))
        if record is None:
            continue
        source = record.pop("_source", None)
        if source != "supabase":
            return record
        try:
            if confirm_external_claim(record):
                return record
            STORE.expire_claim(str(record["id"]))
        except requests.RequestException as exc:
            STORE.release_claim(str(record["id"]))
            log("claim.verify_failed", job_id=record["id"], error=type(exc).__name__)
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


def sync_loop() -> None:
    session = api_session()
    while True:
        if not API_KEY:
            time.sleep(30)
            continue
        rows = STORE.sync_rows()
        if not rows:
            time.sleep(0.4)
            continue
        for row in rows:
            payload = {key: row[key] for key in ("id", "target_device", "command", "status", "output", "timeout_ms", "created_at", "updated_at")}
            try:
                response = session.post(
                    f"{API_URL}/commands",
                    params={"on_conflict": "id"},
                    json=payload,
                    headers={**session.headers, "Prefer": "resolution=merge-duplicates,return=minimal"},
                    timeout=8,
                )
                response.raise_for_status()
                STORE.mark_synced(str(row["id"]), str(row["updated_at"]))
            except requests.RequestException as exc:
                log("sync.failed", job_id=row["id"], error=type(exc).__name__)
                time.sleep(1.0)
                break


def scan_loop() -> None:
    session = api_session()
    while True:
        if API_KEY and TARGETS:
            try:
                response = session.get(
                    f"{API_URL}/commands",
                    params={"status": "eq.pending", "select": "*", "order": "created_at.asc", "limit": "100"},
                    timeout=8,
                )
                response.raise_for_status()
                added = 0
                for row in response.json():
                    if str(row.get("target_device") or "").strip().lower() not in TARGETS:
                        continue
                    before = STORE.get(str(row.get("id")))
                    STORE.submit(row, source="supabase", sync_needed=False)
                    added += int(before is None)
                if added:
                    log("scan.enqueued", count=added)
            except (requests.RequestException, ValueError, sqlite3.Error) as exc:
                log("scan.failed", error=type(exc).__name__)
        recovered = STORE.recover_stale()
        if recovered:
            log("lease.recovered", count=recovered)
        time.sleep(SCAN_SECONDS)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def authorized(self) -> bool:
        if not BROKER_TOKEN:
            return False
        return hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {BROKER_TOKEN}")

    def send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
            self.wfile.flush()

    def send_empty(self, status: int = 204) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > MAX_BODY:
            raise ValueError("invalid body length")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        return payload

    def parsed(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path, urllib.parse.parse_qs(parsed.query)

    def do_GET(self) -> None:
        path, query = self.parsed()
        if path == "/health":
            self.send_json(200, {"status": "ok", "service": "nexus-broker", "version": VERSION, "region": REGION, "targets": sorted(TARGETS), **STORE.stats()})
            return
        if not self.authorized():
            self.send_json(401, {"error": "unauthorized"})
            return
        try:
            if path == "/claim":
                device_id = (query.get("device_id") or [""])[0]
                agent_id = (query.get("agent_id") or [device_id])[0] or device_id
                aliases_text = (query.get("aliases") or [""])[0]
                wait_seconds = min(30.0, max(0.0, float((query.get("wait") or ["20"])[0])))
                record = claim_validated({device_id, *aliases_text.split(",")}, agent_id, wait_seconds)
                self.send_json(200, record) if record is not None else self.send_empty()
                return
            if path == "/wait":
                job_id = (query.get("id") or [""])[0]
                wait_seconds = min(30.0, max(0.0, float((query.get("wait") or ["10"])[0])))
                record = STORE.wait(job_id, wait_seconds)
                self.send_json(200, record) if record and record.get("status") in TERMINAL else self.send_empty()
                return
            if path == "/job":
                record = STORE.get((query.get("id") or [""])[0])
                self.send_json(200 if record else 404, record or {"error": "not found"})
                return
            if path == "/stats":
                self.send_json(200, {"region": REGION, "targets": sorted(TARGETS), **STORE.stats()})
                return
            self.send_json(404, {"error": "not found"})
        except PermissionError as exc:
            self.send_json(409, {"error": "lease_conflict", "detail": str(exc)})
        except (ValueError, KeyError, sqlite3.Error) as exc:
            self.send_json(400, {"error": type(exc).__name__, "detail": str(exc)[:240]})

    def do_POST(self) -> None:
        path, _query = self.parsed()
        if not self.authorized():
            self.send_json(401, {"error": "unauthorized"})
            return
        try:
            payload = self.body_json()
            if path == "/submit":
                record = STORE.submit(payload, source="broker", sync_needed=True)
                log("job.submitted", job_id=record["id"], target=record["target_device"], home_region=record.get("home_region"))
                self.send_json(201, record)
                return
            if path == "/enqueue":
                self.send_json(200, STORE.submit(payload, source="supabase", sync_needed=False))
                return
            if path == "/complete":
                record = STORE.complete(payload)
                log("job.completed", job_id=record["id"], status=record["status"], agent=payload.get("lease_owner"))
                self.send_json(200, record)
                return
            self.send_json(404, {"error": "not found"})
        except PermissionError as exc:
            self.send_json(409, {"error": "lease_conflict", "detail": str(exc)})
        except KeyError as exc:
            self.send_json(404, {"error": "not found", "detail": str(exc)})
        except (ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
            self.send_json(400, {"error": type(exc).__name__, "detail": str(exc)[:240]})
        except Exception as exc:
            log("request.failed", error=type(exc).__name__)
            self.send_json(500, {"error": type(exc).__name__})

    do_HEAD = do_GET


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def get_request(self):
        connection, address = super().get_request()
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return connection, address


def main() -> None:
    if not BROKER_TOKEN:
        raise RuntimeError("NEXUS_BROKER_TOKEN or NEXUS_API_KEY is required")
    threading.Thread(target=sync_loop, name="nexus-broker-sync", daemon=True).start()
    threading.Thread(target=scan_loop, name="nexus-broker-scan", daemon=True).start()
    log("broker.started", bind=BIND, port=PORT, db=str(DB_PATH), targets=sorted(TARGETS))
    Server((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
