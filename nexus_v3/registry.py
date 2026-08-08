from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .common import json_dumps, read_json, utc_now, verify_registration_payload

VERSION = "3.0.0"
DEVICE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


class RegistryStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    key_id TEXT NOT NULL,
                    public_key_ed25519 TEXT NOT NULL,
                    hostname TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approved_at TEXT
                )
                """
            )
            db.commit()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def register(self, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = str(payload.get("device_id") or "").strip().lower()
        if not DEVICE_RE.match(device_id):
            raise ValueError("invalid device_id")
        verify_registration_payload(payload)
        now = utc_now()
        with self.connect() as db:
            row = db.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
            status = "pending"
            approved_at = None
            if row and row["key_id"] == payload["key_id"] and row["status"] == "approved":
                status = "approved"
                approved_at = row["approved_at"]
            db.execute(
                """
                INSERT INTO devices(device_id,key_id,public_key_ed25519,hostname,platform,agent_version,status,created_at,updated_at,approved_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(device_id) DO UPDATE SET
                  key_id=excluded.key_id,
                  public_key_ed25519=excluded.public_key_ed25519,
                  hostname=excluded.hostname,
                  platform=excluded.platform,
                  agent_version=excluded.agent_version,
                  status=excluded.status,
                  updated_at=excluded.updated_at,
                  approved_at=excluded.approved_at
                """,
                (
                    device_id,
                    payload["key_id"],
                    payload["public_key_ed25519"],
                    str(payload.get("hostname") or ""),
                    str(payload.get("platform") or ""),
                    str(payload.get("agent_version") or ""),
                    status,
                    row["created_at"] if row else now,
                    now,
                    approved_at,
                ),
            )
            db.commit()
            return self.get(device_id, include_key=False) | {"status": status}

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT device_id,key_id,hostname,platform,agent_version,status,created_at,updated_at,approved_at FROM devices"
        args: tuple[str, ...] = ()
        if status:
            sql += " WHERE status=?"
            args = (status,)
        sql += " ORDER BY updated_at DESC"
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args).fetchall()]

    def get(self, device_id: str, include_key: bool = True) -> dict[str, Any]:
        cols = "device_id,key_id,hostname,platform,agent_version,status,created_at,updated_at,approved_at"
        if include_key:
            cols += ",public_key_ed25519"
        with self.connect() as db:
            row = db.execute(f"SELECT {cols} FROM devices WHERE device_id=?", (device_id,)).fetchone()
            if not row:
                raise KeyError(device_id)
            return dict(row)

    def approve(self, device_id: str, status: str) -> dict[str, Any]:
        now = utc_now()
        approved_at = now if status == "approved" else None
        with self.connect() as db:
            cur = db.execute("UPDATE devices SET status=?, updated_at=?, approved_at=? WHERE device_id=?", (status, now, approved_at, device_id))
            if cur.rowcount == 0:
                raise KeyError(device_id)
            db.commit()
        return self.get(device_id, include_key=False)


def auth_admin(handler: BaseHTTPRequestHandler) -> None:
    expected = os.getenv("NEXUS_V3_ADMIN_KEY", "")
    if not expected:
        return
    supplied = handler.headers.get("X-Nexus-Admin-Key") or ""
    if supplied != expected:
        raise PermissionError("admin auth failed")


class Handler(BaseHTTPRequestHandler):
    store: RegistryStore

    def log_message(self, fmt: str, *args: Any) -> None:
        print(json_dumps({"ts": utc_now(), "service": "registry", "remote": self.client_address[0], "msg": fmt % args}), flush=True)

    def send_json(self, code: int, payload: Any) -> None:
        body = json_dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/v3/health":
                return self.send_json(200, {"status": "ok", "service": "nexus-v3-registry", "version": VERSION})
            if parsed.path == "/v3/admin/devices":
                auth_admin(self)
                query = dict(item.split("=", 1) for item in parsed.query.split("&") if "=" in item)
                return self.send_json(200, {"devices": self.store.list(query.get("status"))})
            match = re.fullmatch(r"/v3/devices/([^/]+)/public-key", parsed.path)
            if match:
                row = self.store.get(match.group(1).lower(), include_key=True)
                if row["status"] != "approved":
                    return self.send_json(403, {"error": "device_not_approved"})
                return self.send_json(200, row)
            self.send_json(404, {"error": "not_found"})
        except PermissionError as exc:
            self.send_json(403, {"error": str(exc)})
        except KeyError:
            self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            if parsed.path == "/v3/devices/register":
                return self.send_json(202, self.store.register(read_json(body)))
            match = re.fullmatch(r"/v3/admin/devices/([^/]+)/(approve|reject|revoke)", parsed.path)
            if match:
                auth_admin(self)
                status = {"approve": "approved", "reject": "rejected", "revoke": "revoked"}[match.group(2)]
                return self.send_json(200, self.store.approve(match.group(1).lower(), status))
            self.send_json(404, {"error": "not_found"})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except PermissionError as exc:
            self.send_json(401, {"error": str(exc)})
        except KeyError:
            self.send_json(404, {"error": "not_found"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default=os.getenv("NEXUS_V3_BIND", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("NEXUS_V3_REGISTRY_PORT", "18101")))
    parser.add_argument("--db", default=os.getenv("NEXUS_V3_REGISTRY_DB", "/var/lib/nexus-v3/registry.db"))
    args = parser.parse_args()
    Handler.store = RegistryStore(Path(args.db))
    ThreadingHTTPServer((args.bind, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
