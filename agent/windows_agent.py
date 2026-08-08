from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

AGENT_VERSION = "2.6.0"
TERMINAL = {"completed", "failed", "timeout", "expired", "cancelled"}
UTC = timezone.utc
SIGNATURE_VERSION = "NEXUS-ED25519-V1"
REGISTRATION_VERSION = "NEXUS-REGISTER-V1"


def iso_now() -> str:
    return datetime.now(UTC).isoformat()


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def log(event: str, **fields: Any) -> None:
    print(json.dumps({"ts": iso_now(), "event": event, **fields}, ensure_ascii=False, separators=(",", ":")), flush=True)


def _unique_urls(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        url = str(value or "").strip().rstrip("/")
        if url and url not in result:
            result.append(url)
    return result


def default_identity_private_key_path() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("ProgramData", r"C:\ProgramData")) / "NexusAgent"
        return base / "identity_ed25519"
    return Path("/etc/nexus-agent/identity_ed25519")


@dataclass(frozen=True)
class DeviceIdentity:
    private_key_path: Path
    public_key_path: Path
    private_key: Ed25519PrivateKey
    public_key_pem: str
    key_id: str


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _public_key_id(public_key: Ed25519PublicKey) -> str:
    der = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    digest = hashes.Hash(hashes.SHA256())
    digest.update(der)
    return "sha256:" + digest.finalize().hex()


def _private_key_permissions(path: Path) -> None:
    if os.name != "nt":
        os.chmod(path, 0o600)
        os.chmod(path.parent, 0o700)


def ensure_identity_keypair(private_key_path: Path, public_key_path: Path | None = None) -> DeviceIdentity:
    public_key_path = public_key_path or private_key_path.with_name(private_key_path.name + ".pub")
    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    if not private_key_path.exists():
        private_key = Ed25519PrivateKey.generate()
        private_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        private_key_path.write_bytes(private_pem)
        _private_key_permissions(private_key_path)
    else:
        private_key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise RuntimeError(f"Nexus identity key is not Ed25519: {private_key_path}")
        _private_key_permissions(private_key_path)
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    if not public_key_path.exists() or public_key_path.read_text(encoding="utf-8", errors="replace") != public_pem:
        public_key_path.write_text(public_pem, encoding="utf-8")
        if os.name != "nt":
            os.chmod(public_key_path, 0o644)
    return DeviceIdentity(
        private_key_path=private_key_path,
        public_key_path=public_key_path,
        private_key=private_key,
        public_key_pem=public_pem,
        key_id=_public_key_id(public_key),
    )


def _body_sha256_hex(body: bytes | str | None) -> str:
    if body is None:
        body_bytes = b""
    elif isinstance(body, bytes):
        body_bytes = body
    else:
        body_bytes = body.encode("utf-8")
    return hashlib.sha256(body_bytes).hexdigest()


def canonical_signature_message(method: str, path_and_query: str, timestamp: str, nonce: str, device_id: str, body: bytes | str | None) -> bytes:
    value = "\n".join([
        SIGNATURE_VERSION,
        method.upper(),
        path_and_query or "/",
        timestamp,
        nonce,
        device_id,
        _body_sha256_hex(body),
    ])
    return value.encode("utf-8")


def build_signed_headers(
    *,
    identity: DeviceIdentity,
    device_id: str,
    method: str,
    path_and_query: str,
    body: bytes | str | None,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    timestamp = timestamp or iso_now().replace("+00:00", "Z")
    nonce = nonce or _b64url(secrets.token_bytes(16))
    signature = identity.private_key.sign(canonical_signature_message(method, path_and_query, timestamp, nonce, device_id, body))
    return {
        "X-Nexus-Device": device_id,
        "X-Nexus-Key-Id": identity.key_id,
        "X-Nexus-Timestamp": timestamp,
        "X-Nexus-Nonce": nonce,
        "X-Nexus-Signature": _b64url(signature),
    }


def verify_signed_headers_for_test(public_key_pem: str, headers: dict[str, str], method: str, path_and_query: str, body: bytes | str | None) -> bool:
    public_key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    if not isinstance(public_key, Ed25519PublicKey):
        return False
    try:
        public_key.verify(
            _unb64url(headers["X-Nexus-Signature"]),
            canonical_signature_message(method, path_and_query, headers["X-Nexus-Timestamp"], headers["X-Nexus-Nonce"], headers["X-Nexus-Device"], body),
        )
        return True
    except (InvalidSignature, KeyError, ValueError):
        return False


def path_and_query(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "") or "/"


def registration_payload(config: dict[str, Any], identity: DeviceIdentity) -> dict[str, Any]:
    payload = {
        "device_id": config["device_id"],
        "public_key_ed25519": identity.public_key_pem,
        "key_id": identity.key_id,
        "hostname": socket.gethostname(),
        "platform": "windows" if os.name == "nt" else "posix",
        "agent_version": AGENT_VERSION,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["proof"] = _b64url(identity.private_key.sign((REGISTRATION_VERSION + "\n").encode("utf-8") + hashlib.sha256(canonical).hexdigest().encode("ascii")))
    return payload


def load_config() -> dict[str, Any]:
    path = Path(os.getenv("NEXUS_CONFIG_FILE", Path.home() / ".nexus-agent" / "config.json"))
    data: dict[str, Any] = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    aliases = data.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [item.strip() for item in aliases.split(",") if item.strip()]
    env_brokers = os.getenv("NEXUS_BROKER_URLS", "")
    configured_brokers: list[Any] = []
    if env_brokers:
        configured_brokers.extend(env_brokers.split(","))
    configured_brokers.extend(data.get("broker_urls") or [])
    configured_brokers.extend([
        os.getenv("NEXUS_PRIMARY_BROKER_URL") or data.get("primary_broker_url"),
        os.getenv("NEXUS_SECONDARY_BROKER_URL") or data.get("secondary_broker_url"),
        os.getenv("NEXUS_BROKER_URL") or data.get("broker_url"),
    ])
    return {
        "api_url": os.getenv("NEXUS_API_URL") or data.get("api_url"),
        "device_id": os.getenv("NEXUS_DEVICE_ID") or os.getenv("DEVICE_ID") or data.get("device_id") or socket.gethostname().lower(),
        "device_name": os.getenv("NEXUS_DEVICE_NAME") or os.getenv("DEVICE_NAME") or data.get("device_name") or socket.gethostname(),
        "identity_key_path": os.getenv("NEXUS_IDENTITY_KEY") or data.get("identity_key_path") or str(default_identity_private_key_path()),
        "identity_public_key_path": os.getenv("NEXUS_IDENTITY_PUBLIC_KEY") or data.get("identity_public_key_path"),
        "aliases": aliases,
        "poll_seconds": max(0.10, float(os.getenv("NEXUS_POLL_SECONDS", data.get("poll_seconds", 0.25)))),
        "heartbeat_seconds": max(10.0, float(os.getenv("NEXUS_HEARTBEAT_SECONDS", data.get("heartbeat_seconds", 30)))),
        "max_workers": max(1, int(os.getenv("NEXUS_MAX_WORKERS", data.get("max_workers", 2)))),
        "lock_port": int(os.getenv("NEXUS_LOCK_PORT", data.get("lock_port", 49158 if os.name == "nt" else 49159))),
        "request_timeout": max(2.0, float(os.getenv("NEXUS_REQUEST_TIMEOUT", data.get("request_timeout", 8)))),
        "broker_urls": _unique_urls(configured_brokers),
        "broker_wait_seconds": max(2.0, min(30.0, float(os.getenv("NEXUS_BROKER_WAIT_SECONDS", data.get("broker_wait_seconds", 20))))),
        "broker_failures_before_switch": max(1, int(data.get("broker_failures_before_switch", 2))),
        "broker_primary_probe_seconds": max(15.0, float(data.get("broker_primary_probe_seconds", 45))),
        "ledger_path": str(data.get("ledger_path") or (Path.home() / ".nexus-agent" / "execution_ledger.db")),
    }


def capabilities() -> dict[str, bool]:
    return {
        "shell": True,
        "ssh": shutil.which("ssh") is not None,
        "scp": shutil.which("scp") is not None,
        "rsync": shutil.which("rsync") is not None,
        "ping": shutil.which("ping") is not None,
        "docker": shutil.which("docker") is not None,
        "powershell": bool(shutil.which("pwsh") or shutil.which("powershell")),
        "regional_broker_failover": False,
        "execution_ledger": True,
    }


class ExecutionLedger:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                """CREATE TABLE IF NOT EXISTS executions (
                    id TEXT PRIMARY KEY,
                    command_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stdout TEXT NOT NULL DEFAULT '',
                    stderr TEXT NOT NULL DEFAULT '',
                    exit_code INTEGER,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def digest(command: str) -> str:
        return hashlib.sha256(command.encode("utf-8", errors="replace")).hexdigest()

    def begin(self, job_id: str, command: str) -> tuple[str, dict[str, Any] | None]:
        command_hash = self.digest(command)
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM executions WHERE id=?", (job_id,)).fetchone()
            if row is None:
                timestamp = iso_now()
                db.execute(
                    "INSERT INTO executions(id,command_hash,status,started_at,updated_at) VALUES(?,?,?,?,?)",
                    (job_id, command_hash, "running", timestamp, timestamp),
                )
                db.execute("COMMIT")
                return "new", None
            db.execute("COMMIT")
        result = dict(row)
        if result["command_hash"] != command_hash:
            return "conflict", result
        if result["status"] in TERMINAL:
            return "terminal", result
        return "running", result

    def finish(self, job_id: str, status: str, stdout: str, stderr: str, exit_code: int | None) -> None:
        with self.lock, self.connect() as db:
            db.execute(
                "UPDATE executions SET status=?,stdout=?,stderr=?,exit_code=?,updated_at=? WHERE id=?",
                (status, stdout[-1_000_000:], stderr[-1_000_000:], exit_code, iso_now(), job_id),
            )

    def wait_terminal(self, job_id: str, timeout: float) -> dict[str, Any] | None:
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            with self.connect() as db:
                row = db.execute("SELECT * FROM executions WHERE id=?", (job_id,)).fetchone()
            if row is not None and str(row["status"]) in TERMINAL:
                return dict(row)
            time.sleep(0.1)
        return None


class NexusAPI:
    def __init__(self, config: dict[str, Any]) -> None:
        self.base_url = str(config.get("api_url") or "").rstrip("/")
        private_key_path = Path(str(config["identity_key_path"]))
        public_key_path = Path(str(config.get("identity_public_key_path") or private_key_path.with_name(private_key_path.name + ".pub")))
        self.identity = ensure_identity_keypair(private_key_path, public_key_path)
        self.device_id = str(config["device_id"])
        self.timeout = float(config["request_timeout"])
        self.broker_urls = list(config.get("broker_urls") or [])
        self.broker_index = 0
        self.broker_failures = 0
        self.broker_failure_limit = int(config["broker_failures_before_switch"])
        self.primary_probe_seconds = float(config["broker_primary_probe_seconds"])
        self.last_primary_probe = 0.0
        self.local = threading.local()
        self.pool_lock = threading.Lock()
        if not self.base_url:
            raise RuntimeError("NEXUS_API_URL is required")

    def session(self) -> requests.Session:
        session = getattr(self.local, "session", None)
        if session is None:
            session = requests.Session()
            retry = Retry(total=1, connect=1, read=0, backoff_factor=0.05, status_forcelist=(502, 503, 504), allowed_methods=None)
            adapter = HTTPAdapter(pool_connections=6, pool_maxsize=12, max_retries=retry)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            session.headers.update({
                "Content-Type": "application/json",
                "Connection": "keep-alive",
            })
            self.local.session = session
        return session

    def send_signed(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        timeout = kwargs.pop("timeout", self.timeout)
        headers = dict(kwargs.pop("headers", {}) or {})
        params = kwargs.pop("params", None)
        json_payload = kwargs.pop("json", None)
        data = kwargs.pop("data", None)
        request = requests.Request(method, url, params=params, headers=headers, json=json_payload, data=data)
        prepared = self.session().prepare_request(request)
        body = prepared.body or b""
        if isinstance(body, str):
            body_bytes = body.encode("utf-8")
        else:
            body_bytes = body
        prepared.headers.update(build_signed_headers(
            identity=self.identity,
            device_id=self.device_id,
            method=method,
            path_and_query=path_and_query(prepared.url or url),
            body=body_bytes,
        ))
        response = self.session().send(prepared, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response

    def register_identity(self, config: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/api/device-identities/register"
        payload = registration_payload(config, self.identity)
        response = self.session().post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json() if response.content else {}
        log("identity.registered", status=data.get("status"), key_id=self.identity.key_id, public_key_path=str(self.identity.public_key_path))
        return data

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        return self.send_signed(method, f"{self.base_url}/{path.lstrip('/')}", **kwargs)

    def broker_request(self, broker_url: str, method: str, path: str, **kwargs: Any) -> requests.Response:
        return self.send_signed(
            method,
            f"{broker_url.rstrip('/')}/{path.lstrip('/')}",
            **kwargs,
        )

    @staticmethod
    def aliases(config: dict[str, Any]) -> list[str]:
        return [str(config["device_id"])]

    def _current_broker(self) -> str:
        with self.pool_lock:
            return self.broker_urls[self.broker_index]

    def _switch_broker(self) -> str:
        with self.pool_lock:
            if not self.broker_urls:
                raise RuntimeError("No broker URLs configured")
            self.broker_index = (self.broker_index + 1) % len(self.broker_urls)
            self.broker_failures = 0
            selected = self.broker_urls[self.broker_index]
        log("broker.switched", broker_url=selected, broker_index=self.broker_index)
        return selected

    def _record_broker_failure(self, broker_url: str) -> None:
        with self.pool_lock:
            if broker_url != self.broker_urls[self.broker_index]:
                return
            self.broker_failures += 1
            should_switch = len(self.broker_urls) > 1 and self.broker_failures >= self.broker_failure_limit
        if should_switch:
            self._switch_broker()

    def _probe_primary(self) -> None:
        if len(self.broker_urls) < 2:
            return
        with self.pool_lock:
            if self.broker_index == 0 or time.monotonic() - self.last_primary_probe < self.primary_probe_seconds:
                return
            self.last_primary_probe = time.monotonic()
            primary = self.broker_urls[0]
        try:
            response = self.session().get(f"{primary}/health", timeout=3)
            response.raise_for_status()
            with self.pool_lock:
                self.broker_index = 0
                self.broker_failures = 0
            log("broker.primary_restored", broker_url=primary)
        except requests.RequestException:
            return

    def broker_claim(self, config: dict[str, Any]) -> dict[str, Any] | None:
        if not self.broker_urls:
            raise RuntimeError("No broker URLs configured")
        self._probe_primary()
        broker_url = self._current_broker()
        wait_seconds = float(config["broker_wait_seconds"])
        agent_id = f"{config['device_id']}:{socket.gethostname()}:{os.getpid()}"
        try:
            response = self.broker_request(
                broker_url,
                "GET",
                "claim",
                params={
                    "device_id": config["device_id"],
                    "agent_id": agent_id,
                    "aliases": ",".join(self.aliases(config)),
                    "wait": str(wait_seconds),
                },
                timeout=wait_seconds + 5.0,
            )
        except requests.RequestException:
            self._record_broker_failure(broker_url)
            raise
        with self.pool_lock:
            self.broker_failures = 0
        if response.status_code == 204 or not response.content:
            return None
        task = response.json()
        task["broker_managed"] = True
        task["_broker_url"] = broker_url
        task["_lease_owner"] = task.get("lease_owner") or agent_id
        task["_claimed_at"] = task.get("claimed_at") or task.get("updated_at") or iso_now()
        return task

    def broker_finish(self, task: dict[str, Any], status: str, stdout: str, stderr: str, exit_code: int | None) -> None:
        combined = stdout
        if stderr:
            combined = f"{combined}\n[stderr]\n{stderr}" if combined else f"[stderr]\n{stderr}"
        payload = {
            "id": task["id"],
            "status": status,
            "output": combined[-1_000_000:],
            "updated_at": iso_now(),
            "exit_code": exit_code,
            "lease_owner": task.get("_lease_owner") or task.get("lease_owner"),
        }
        broker_url = str(task.get("_broker_url") or self._current_broker())
        self.broker_request(broker_url, "POST", "complete", json=payload, timeout=self.timeout)

    def heartbeat(self, config: dict[str, Any]) -> None:
        payload = {
            "device_id": config["device_id"],
            "name": config["device_name"],
            "status": "online",
            "last_seen": iso_now(),
            "platform": "windows" if os.name == "nt" else "posix",
            "agent_version": AGENT_VERSION,
            "capabilities": capabilities(),
        }
        headers = {**self.session().headers, "Prefer": "resolution=merge-duplicates,return=minimal"}
        if getattr(self, "expanded_devices", None) is not False:
            try:
                self.request("POST", "api/devices/heartbeat", json=payload, headers=headers)
                self.expanded_devices = True
                return
            except requests.HTTPError as exc:
                if exc.response is None or exc.response.status_code not in {400, 404}:
                    raise
                self.expanded_devices = False
        self.request("POST", "api/devices/heartbeat", json={
            "device_id": config["device_id"], "name": config["device_name"],
            "status": "online", "last_seen": payload["last_seen"],
        }, headers=headers)

    def claim(self, config: dict[str, Any]) -> dict[str, Any] | None:
        aliases = self.aliases(config)
        terms = ",".join(f"target_device.ilike.{alias}" for alias in aliases)
        rows = self.request("GET", "commands", params={
            "status": "eq.pending", "or": f"({terms})", "order": "created_at.asc", "limit": "1", "select": "*",
        }).json()
        if not rows:
            return None
        task = rows[0]
        claimed_at = iso_now()
        response = self.request(
            "PATCH", "commands",
            params={"id": f"eq.{task['id']}", "status": "eq.pending"},
            json={"status": "running", "updated_at": claimed_at},
            headers={**self.session().headers, "Prefer": "return=representation"},
        )
        claimed = response.json()
        return {**task, **claimed[0], "_claimed_at": claimed_at} if claimed else None

    def finish(self, task: dict[str, Any], status: str, stdout: str, stderr: str, exit_code: int | None) -> None:
        combined = stdout
        if stderr:
            combined = f"{combined}\n[stderr]\n{stderr}" if combined else f"[stderr]\n{stderr}"
        self.request(
            "PATCH", "commands",
            params={"id": f"eq.{task['id']}"},
            json={"status": status, "output": combined[-1_000_000:], "updated_at": iso_now()},
            headers={**self.session().headers, "Prefer": "return=minimal"},
        )


def acquire_single_instance_lock(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as exc:
        raise RuntimeError("Another Nexus Agent instance is already running") from exc
    return sock


def command_argv(command: str) -> list[str]:
    if os.name == "nt":
        shell = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
    return ["/bin/sh", "-c", command]


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()


def send_result(api: NexusAPI, task: dict[str, Any], status: str, stdout: str, stderr: str, exit_code: int | None) -> None:
    if task.get("broker_managed") and task.get("_broker_url"):
        try:
            api.broker_finish(task, status, stdout, stderr, exit_code)
            return
        except requests.RequestException as exc:
            log("broker.complete_failed", command_id=task.get("id"), broker_url=task.get("_broker_url"), error=type(exc).__name__)
    api.finish(task, status, stdout, stderr, exit_code)


def execute_task(api: NexusAPI, config: dict[str, Any], ledger: ExecutionLedger, task: dict[str, Any]) -> None:
    task_id = str(task["id"])
    command = str(task.get("command") or "").strip()
    if not command:
        send_result(api, task, "failed", "", "Empty command", 127)
        return
    state, cached = ledger.begin(task_id, command)
    if state == "conflict":
        send_result(api, task, "failed", "", "Duplicate job ID conflicts with a different command", 126)
        return
    if state == "terminal" and cached:
        log("command.replayed", command_id=task_id, status=cached["status"])
        send_result(api, task, str(cached["status"]), str(cached["stdout"]), str(cached["stderr"]), cached["exit_code"])
        return
    if state == "running":
        cached = ledger.wait_terminal(task_id, min(30.0, max(2.0, float(task.get("timeout_ms") or 30000) / 1000.0)))
        if cached:
            log("command.duplicate_wait_replayed", command_id=task_id, status=cached["status"])
            send_result(api, task, str(cached["status"]), str(cached["stdout"]), str(cached["stderr"]), cached["exit_code"])
        else:
            send_result(api, task, "failed", "", "Duplicate execution suppressed; original execution state is still running or uncertain", 125)
        return

    created = parse_time(task.get("created_at"))
    claimed = parse_time(task.get("_claimed_at"))
    queue_ms = round((claimed - created).total_seconds() * 1000, 1) if created and claimed else None
    timeout_seconds = max(1.0, float(task.get("timeout_ms") or 30000) / 1000.0)
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True,
        "encoding": "utf-8", "errors": "replace",
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    started = time.perf_counter()
    log("command.started", command_id=task_id, queue_ms=queue_ms, broker_url=task.get("_broker_url"), command=command[:160])
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(command_argv(command), **kwargs)
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        exit_code = process.returncode
        status = "completed" if exit_code == 0 else "failed"
    except subprocess.TimeoutExpired:
        assert process is not None
        stop_process(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            for stream in (process.stdout, process.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass
            stdout, stderr = "", "Process tree termination did not close inherited pipes within 5 seconds"
        stderr = f"{stderr}\nCommand timed out after {timeout_seconds:.1f}s".strip()
        exit_code, status = 124, "timeout"
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        if process is not None:
            stop_process(process)
        stdout, stderr, exit_code, status = "", str(exc), 125, "failed"
    stdout, stderr = stdout.strip(), stderr.strip()
    ledger.finish(task_id, status, stdout, stderr, exit_code)
    commit_started = time.perf_counter()
    send_result(api, task, status, stdout, stderr, exit_code)
    log(
        "command.finished", command_id=task_id, status=status, exit_code=exit_code,
        queue_ms=queue_ms, runtime_ms=round((time.perf_counter() - started) * 1000, 1),
        commit_ms=round((time.perf_counter() - commit_started) * 1000, 1), broker_url=task.get("_broker_url"),
    )


def main() -> None:
    config = load_config()
    if len(config["broker_urls"]) != 1:
        raise RuntimeError("Exactly one regional broker URL is required")
    _instance_lock = acquire_single_instance_lock(config["lock_port"])
    api = NexusAPI(config)
    api.register_identity(config)
    ledger = ExecutionLedger(config["ledger_path"])
    executor = ThreadPoolExecutor(max_workers=config["max_workers"], thread_name_prefix="nexus-worker")
    in_flight: set[Future[Any]] = set()
    in_flight_lock = threading.Lock()
    stop_event = threading.Event()

    def release_future(done: Future[Any]) -> None:
        with in_flight_lock:
            in_flight.discard(done)
        try:
            done.result()
        except Exception as exc:
            log("worker.failed", error=type(exc).__name__, detail=str(exc)[:300])

    def heartbeat_loop() -> None:
        while not stop_event.is_set():
            started = time.perf_counter()
            try:
                api.heartbeat(config)
                log("heartbeat.ok", elapsed_ms=round((time.perf_counter() - started) * 1000, 1))
            except requests.RequestException as exc:
                log("heartbeat.failed", error=type(exc).__name__, detail=str(exc)[:240])
            stop_event.wait(config["heartbeat_seconds"])

    threading.Thread(target=heartbeat_loop, name="nexus-heartbeat", daemon=True).start()
    error_backoff = config["poll_seconds"]
    log(
        "agent.started", version=AGENT_VERSION, device_id=config["device_id"],
        broker_urls=config["broker_urls"], poll_seconds=config["poll_seconds"],
        heartbeat_seconds=config["heartbeat_seconds"], ledger_path=config["ledger_path"],
        key_id=api.identity.key_id, public_key_path=str(api.identity.public_key_path),
    )
    while True:
        try:
            with in_flight_lock:
                capacity_available = len(in_flight) < config["max_workers"]
            if not capacity_available:
                stop_event.wait(0.05)
                continue
            task = api.broker_claim(config)
            error_backoff = config["poll_seconds"]
            if task:
                future = executor.submit(execute_task, api, config, ledger, task)
                with in_flight_lock:
                    in_flight.add(future)
                future.add_done_callback(release_future)
                continue
        except requests.RequestException as exc:
            log("poll.failed", error=type(exc).__name__, detail=str(exc)[:240], retry_seconds=round(error_backoff, 2))
            stop_event.wait(error_backoff)
            error_backoff = min(5.0, max(config["poll_seconds"], error_backoff * 1.8))
        except (RuntimeError, ValueError, sqlite3.Error) as exc:
            log("agent.error", error=type(exc).__name__, detail=str(exc)[:240])
            stop_event.wait(1.0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
