from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .common import json_dumps, utc_now

TERMINAL = {"completed", "failed", "timeout"}


class ExecutionLedger:
    """Durable per-device replay protection for broker jobs.

    A terminal job can be returned again without re-running the operation when a
    completion acknowledgement was lost. A conflicting or uncertain duplicate
    is rejected rather than executed twice.
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        try:
            self._initialize()
        except sqlite3.OperationalError:
            # HPC home directories are commonly backed by NFS/GPFS/Lustre where
            # SQLite locking or journal semantics can fail. Keep the durable path
            # when it works; otherwise fall back to a node-local runtime ledger so
            # the control agent remains available instead of crashing at startup.
            uid = os.getuid() if hasattr(os, "getuid") else os.getpid()
            self.path = Path(tempfile.gettempdir()) / f"nexus-agent-v3-{uid}" / path.name
            self._initialize()

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            # The agent is a single writer. Rollback-journal mode is sufficient
            # and is substantially more portable than WAL on network filesystems.
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA busy_timeout=10000")
            db.execute(
                """CREATE TABLE IF NOT EXISTS executions (
                    job_id TEXT PRIMARY KEY,
                    operation_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    exit_code INTEGER,
                    output TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            db.commit()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def digest(job: dict[str, Any]) -> str:
        material = {
            "operation": str(job.get("operation") or "shell.execute"),
            "input": job.get("input") if isinstance(job.get("input"), dict) else {},
        }
        return hashlib.sha256(json_dumps(material).encode("utf-8")).hexdigest()

    def begin(self, job: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        job_id = str(job["id"])
        digest = self.digest(job)
        now = utc_now()
        with self._lock, self.connect() as db:
            row = db.execute("SELECT * FROM executions WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO executions(job_id,operation_hash,status,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (job_id, digest, "running", now, now),
                )
                db.commit()
                return "new", None
            record = self.normalize(row)
        if record["operation_hash"] != digest:
            return "conflict", record
        if record["status"] in TERMINAL:
            return "terminal", record
        return "uncertain", record

    def finish(self, job_id: str, status: str, exit_code: int, output: str, result: dict[str, Any]) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                "UPDATE executions SET status=?,exit_code=?,output=?,result_json=?,updated_at=? WHERE job_id=?",
                (status, exit_code, output[-20000:], json_dumps(result), utc_now(), job_id),
            )
            db.commit()

    @staticmethod
    def normalize(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        try:
            out["result"] = json.loads(out.pop("result_json") or "{}")
        except json.JSONDecodeError:
            out["result"] = {}
        return out
