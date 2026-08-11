from __future__ import annotations

import argparse
import json
import os
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from .common import json_dumps, read_json, utc_now, verify_http_signature

VERSION = "3.1.0"
TERMINAL = {"completed", "failed", "timeout"}


class BrokerStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    target_device TEXT NOT NULL,
                    command TEXT NOT NULL DEFAULT '',
                    operation TEXT NOT NULL DEFAULT 'shell.execute',
                    input_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    timeout_ms INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    output TEXT NOT NULL DEFAULT '',
                    exit_code INTEGER,
                    lease_owner TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(db, "operation", "TEXT NOT NULL DEFAULT 'shell.execute'")
            self._ensure_column(db, "input_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(db, "result_json", "TEXT NOT NULL DEFAULT '{}'")
            db.commit()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def _ensure_column(self, db: sqlite3.Connection, column: str, definition: str) -> None:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)").fetchall()}
        if column not in columns:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")

    @staticmethod
    def normalize(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        try:
            out["input"] = json.loads(out.pop("input_json", "{}") or "{}")
        except json.JSONDecodeError:
            out["input"] = {}
        try:
            out["result"] = json.loads(out.pop("result_json", "{}") or "{}")
        except json.JSONDecodeError:
            out["result"] = {}
        if out.get("operation") == "shell.execute" and not out["input"] and out.get("command"):
            out["input"] = {"command": out["command"]}
        return out

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        target = str(payload.get("target_device") or payload.get("device_id") or "").strip().lower()
        operation = str(payload.get("operation") or "shell.execute").strip()
        input_data = payload.get("input")
        if input_data is None:
            input_data = {}
        if not isinstance(input_data, dict):
            raise ValueError("input must be an object")
        command = str(payload.get("command") or input_data.get("command") or "")
        if operation == "shell.execute":
            if not command:
                raise ValueError("shell.execute requires command")
            input_data = {**input_data, "command": command}
        elif not operation.startswith("workspace."):
            raise ValueError(f"unsupported operation: {operation}")
        if not target:
            raise ValueError("target_device is required")

        now = utc_now()
        job = {
            "id": str(uuid.uuid4()),
            "target_device": target,
            "command": command,
            "operation": operation,
            "input_json": json_dumps(input_data),
            "result_json": "{}",
            "timeout_ms": int(payload.get("timeout_ms") or 30000),
            "status": "pending",
            "created_at": now,
            "updated_at": now,
            "output": "",
        }
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO jobs(
                    id,target_device,command,operation,input_json,result_json,
                    timeout_ms,status,output,created_at,updated_at
                ) VALUES(
                    :id,:target_device,:command,:operation,:input_json,:result_json,
                    :timeout_ms,:status,:output,:created_at,:updated_at
                )
                """,
                job,
            )
            db.commit()
        return self.normalize(job)

    def claim(self, device_id: str, lease_owner: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM jobs WHERE status='pending' AND target_device=? ORDER BY created_at LIMIT 1",
                (device_id,),
            ).fetchone()
            if not row:
                db.commit()
                return None
            db.execute(
                "UPDATE jobs SET status='running', lease_owner=?, updated_at=? WHERE id=?",
                (lease_owner, now, row["id"]),
            )
            db.commit()
            out = self.normalize(row)
            out["status"] = "running"
            out["lease_owner"] = lease_owner
            out["updated_at"] = now
            return out

    def complete(self, payload: dict[str, Any], device_id: str) -> dict[str, Any]:
        job_id = str(payload.get("id") or "")
        status = str(payload.get("status") or "")
        if status not in TERMINAL:
            raise ValueError("invalid terminal status")
        result = payload.get("result") or {}
        if not isinstance(result, dict):
            raise ValueError("result must be an object")
        output = str(payload.get("output") or "")
        if not output and result:
            output = json_dumps(result)[-20000:]
        now = utc_now()
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            if row["target_device"] != device_id:
                raise PermissionError("device cannot complete another device job")
            db.execute(
                """
                UPDATE jobs
                SET status=?, output=?, exit_code=?, result_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    status,
                    output[-20000:],
                    int(payload.get("exit_code") or 0),
                    json_dumps(result),
                    now,
                    job_id,
                ),
            )
            db.commit()
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            return self.normalize(row)


class ReplayGuard:
    def __init__(self, ttl_seconds: int = 600):
        self.ttl_seconds = ttl_seconds
        self._seen: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def accept(self, device_id: str, nonce: str) -> None:
        now = time.time()
        key = (device_id, nonce)
        with self._lock:
            expired = [item for item, seen_at in self._seen.items() if now - seen_at > self.ttl_seconds]
            for item in expired:
                self._seen.pop(item, None)
            if key in self._seen:
                raise PermissionError("signature nonce already used")
            self._seen[key] = now


def admin_ok(handler: BaseHTTPRequestHandler) -> bool:
    expected = os.getenv("NEXUS_V3_ADMIN_KEY", "")
    return not expected or handler.headers.get("X-Nexus-Admin-Key") == expected


def fetch_public_key(device_id: str) -> str:
    registry = os.getenv("NEXUS_V3_REGISTRY_URL", "http://127.0.0.1:18101").rstrip("/")
    with urlopen(f"{registry}/v3/devices/{device_id}/public-key", timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))["public_key_ed25519"]


class Handler(BaseHTTPRequestHandler):
    store: BrokerStore
    replay_guard = ReplayGuard()

    def log_message(self, fmt: str, *args: Any) -> None:
        print(
            json_dumps({"ts": utc_now(), "service": "broker", "remote": self.client_address[0], "msg": fmt % args}),
            flush=True,
        )

    def send_json(self, code: int, payload: Any) -> None:
        body = json_dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def signed_device(self, body: bytes) -> str:
        parsed = urlparse(self.path)
        path_query = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        headers = {key: value for key, value in self.headers.items()}
        device_id = str(headers.get("X-Nexus-Device") or "").strip().lower()
        try:
            public_key = fetch_public_key(device_id)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise PermissionError(f"registry lookup failed for {device_id}: {exc}") from exc
        verified_device = verify_http_signature(public_key, headers, self.command, path_query, body)
        self.replay_guard.accept(verified_device, str(headers.get("X-Nexus-Nonce") or ""))
        return verified_device

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/v3/health":
                return self.send_json(
                    200,
                    {
                        "status": "ok",
                        "service": "nexus-v3-broker",
                        "version": VERSION,
                        "region": os.getenv("NEXUS_V3_REGION", "unknown"),
                    },
                )
            if parsed.path == "/v3/jobs":
                if not admin_ok(self):
                    return self.send_json(403, {"error": "admin auth failed"})
                job_id = parse_qs(parsed.query).get("id", [""])[0]
                return self.send_json(200, self.store.get(job_id))
            if parsed.path == "/v3/jobs/claim":
                device_id = self.signed_device(b"")
                query = parse_qs(parsed.query)
                lease_owner = query.get("agent_id", [device_id])[0]
                wait = min(int(query.get("wait", ["20"])[0] or 20), 30)
                deadline = time.time() + wait
                while True:
                    job = self.store.claim(device_id, lease_owner)
                    if job:
                        return self.send_json(200, job)
                    if time.time() >= deadline:
                        self.send_response(204)
                        self.end_headers()
                        return
                    time.sleep(1)
            self.send_json(404, {"error": "not_found"})
        except PermissionError as exc:
            self.send_json(403, {"error": str(exc)})
        except KeyError:
            self.send_json(404, {"error": "not_found"})
        except Exception as exc:
            self.send_json(502, {"error": f"broker dependency failed: {str(exc)[:200]}"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            if parsed.path == "/v3/jobs":
                if not admin_ok(self):
                    return self.send_json(403, {"error": "admin auth failed"})
                return self.send_json(201, self.store.submit(read_json(body)))
            if parsed.path == "/v3/jobs/complete":
                device_id = self.signed_device(body)
                return self.send_json(200, self.store.complete(read_json(body), device_id))
            self.send_json(404, {"error": "not_found"})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except PermissionError as exc:
            self.send_json(403, {"error": str(exc)})
        except KeyError:
            self.send_json(404, {"error": "not_found"})
        except Exception as exc:
            self.send_json(502, {"error": f"broker dependency failed: {str(exc)[:200]}"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default=os.getenv("NEXUS_V3_BIND", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("NEXUS_V3_BROKER_PORT", "18100")))
    parser.add_argument("--db", default=os.getenv("NEXUS_V3_BROKER_DB", "/var/lib/nexus-v3/broker.db"))
    args = parser.parse_args()
    Handler.store = BrokerStore(Path(args.db))
    ThreadingHTTPServer((args.bind, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
