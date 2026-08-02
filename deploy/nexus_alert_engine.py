#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HEALTH = Path(os.getenv("NEXUS_HEALTH_FILE", "/var/lib/nexus/health.json"))
DEVICES_URL = os.getenv("NEXUS_DEVICES_URL", "http://127.0.0.1:8000/dashboard/devices")
STATE = Path(os.getenv("NEXUS_ALERT_STATE", "/var/lib/nexus/alert-state.json"))
EVENTS = Path(os.getenv("NEXUS_EVENTS_FILE", "/var/lib/nexus/events.json"))
WEBHOOK = os.getenv("NEXUS_ALERT_WEBHOOK", "").strip()
MAX_EVENTS = int(os.getenv("NEXUS_MAX_EVENTS", "500"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def fetch_devices() -> list[dict]:
    try:
        with urllib.request.urlopen(DEVICES_URL, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return []


def atomic_write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        name = handle.name
    os.chmod(name, 0o640)
    os.replace(name, path)


def notify(event: dict) -> None:
    if not WEBHOOK:
        return
    body = json.dumps({"content": f"[Nexus] {event['title']} — {event['detail']}"}, ensure_ascii=False).encode()
    request = urllib.request.Request(WEBHOOK, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(request, timeout=8).read()
    except Exception:
        pass


def main() -> None:
    previous = load_json(STATE, {})
    events = load_json(EVENTS, [])
    health = load_json(HEALTH, {"checks": []})
    current: dict[str, str] = {}
    labels: dict[str, str] = {}

    for device in fetch_devices():
        key = f"device:{device.get('device_id')}"
        current[key] = str(device.get("state") or "unknown")
        labels[key] = str(device.get("name") or device.get("device_id"))
    for check in health.get("checks") or []:
        key = f"service:{check.get('id')}"
        current[key] = str(check.get("status") or "unknown")
        labels[key] = str(check.get("name") or check.get("id"))
    current["connection:tailscale"] = str((health.get("tailscale") or {}).get("status") or "unknown")
    labels["connection:tailscale"] = "ThinkCenter Tailscale"

    for key, state in current.items():
        old = previous.get(key)
        if old is None or old == state:
            continue
        recovered = state == "online" and old != "online"
        event = {
            "id": f"{int(datetime.now().timestamp() * 1000)}-{key}",
            "created_at": now(),
            "kind": "recovery" if recovered else "state_change",
            "severity": "info" if recovered else ("critical" if state == "offline" else "warning"),
            "subject": key,
            "title": f"{labels.get(key, key)} {'恢复' if recovered else '状态变化'}",
            "detail": f"{old} → {state}",
            "old_state": old,
            "new_state": state,
        }
        events.insert(0, event)
        notify(event)

    atomic_write(STATE, current)
    atomic_write(EVENTS, events[:MAX_EVENTS])


if __name__ == "__main__":
    main()
