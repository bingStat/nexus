from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .common import load_config, load_json, now_iso

UTC = timezone.utc
DEFAULT_DB = Path("/var/lib/nexus/ops/state.db")
DEFAULT_HEALTH = Path("/var/lib/nexus/ops/health.json")
DEFAULT_EVENTS = Path("/var/lib/nexus/ops/events.json")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("CREATE TABLE IF NOT EXISTS snapshots(ts TEXT PRIMARY KEY, payload_json TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, created_at TEXT, kind TEXT, severity TEXT, subject TEXT, payload_json TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS devices(device_id TEXT PRIMARY KEY, runtime_status TEXT, last_seen_at TEXT, updated_at TEXT, payload_json TEXT NOT NULL)")
    return db


def main() -> None:
    config = load_config()
    state_cfg = config.get("state_store") if isinstance(config.get("state_store"), dict) else {}
    db_path = Path(str(state_cfg.get("db_file") or DEFAULT_DB))
    health = load_json(Path(str(config.get("health_file") or DEFAULT_HEALTH)), {})
    events = load_json(Path(str((config.get("alerts") or {}).get("events_file") or DEFAULT_EVENTS)), [])
    stamp = str(health.get("generated_at") or now_iso())
    db = connect(db_path)
    try:
        db.execute("INSERT OR REPLACE INTO snapshots(ts,payload_json) VALUES(?,?)", (stamp, json.dumps(health, ensure_ascii=False)))
        for item in health.get("devices") or []:
            device_id = str(item.get("device_id") or "")
            if not device_id:
                continue
            db.execute(
                "INSERT OR REPLACE INTO devices(device_id,runtime_status,last_seen_at,updated_at,payload_json) VALUES(?,?,?,?,?)",
                (device_id, str(item.get("runtime_status") or "unknown"), item.get("last_seen_at"), stamp, json.dumps(item, ensure_ascii=False)),
            )
        for item in events:
            event_id = str(item.get("id") or "")
            if not event_id:
                continue
            db.execute(
                "INSERT OR IGNORE INTO events(id,created_at,kind,severity,subject,payload_json) VALUES(?,?,?,?,?,?)",
                (event_id, item.get("created_at"), item.get("kind"), item.get("severity"), item.get("subject"), json.dumps(item, ensure_ascii=False)),
            )
        cutoff = (datetime.now(UTC) - timedelta(days=int(state_cfg.get("retention_days") or 30))).isoformat()
        db.execute("DELETE FROM snapshots WHERE ts < ?", (cutoff,))
        db.execute("DELETE FROM events WHERE created_at IS NOT NULL AND created_at < ?", (cutoff,))
        db.commit()
    finally:
        db.close()
    print(json.dumps({"stored_at": stamp, "devices": len(health.get("devices") or []), "events": len(events)}))


if __name__ == "__main__":
    main()
