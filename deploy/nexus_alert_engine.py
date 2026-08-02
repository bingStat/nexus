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
MAX_EVENTS = int(os.getenv("NEXUS_MAX_EVENTS", "500"))
RECOVERY_STREAK = int(os.getenv("NEXUS_RECOVERY_STREAK", "3"))
REOPEN_STREAK = int(os.getenv("NEXUS_REOPEN_STREAK", "10"))
REOPEN_WINDOW_SECONDS = int(os.getenv("NEXUS_REOPEN_WINDOW_SECONDS", "1800"))
SILENCED = {"service:elitebook"}
LOW_PRIORITY = {
    "service:v152", "service:v152-ssh", "service:v152-telnet",
    "service:ax3600", "service:ax3600-ssh", "service:n1",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat()


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def atomic_write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        temp_name = handle.name
    os.chmod(temp_name, 0o640)
    os.replace(temp_name, path)


def fetch_devices() -> list[dict]:
    try:
        with urllib.request.urlopen(DEVICES_URL, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return []


def observations() -> tuple[dict[str, str], dict[str, str]]:
    current: dict[str, str] = {}
    labels: dict[str, str] = {}
    for device in fetch_devices():
        key = f"device:{device.get('device_id')}"
        current[key] = str(device.get("state") or "unknown")
        labels[key] = str(device.get("name") or device.get("device_id"))
    health = load_json(HEALTH, {"checks": []})
    for check in health.get("checks") or []:
        key = f"service:{check.get('id')}"
        current[key] = str(check.get("status") or "unknown")
        labels[key] = str(check.get("name") or check.get("id"))
    current["connection:tailscale"] = str((health.get("tailscale") or {}).get("status") or "unknown")
    labels["connection:tailscale"] = "ThinkCenter Tailscale"
    return current, labels


def failure_threshold(key: str) -> int:
    if key.startswith("device:"):
        return 5
    if key in LOW_PRIORITY:
        return 5
    return 3


def make_event(key: str, label: str, kind: str, old: str, new: str, streak: int) -> dict:
    recovered = kind == "recovery"
    return {
        "id": f"{int(utcnow().timestamp() * 1000)}-{key}-{kind}",
        "created_at": iso_now(),
        "kind": kind,
        "severity": "info" if recovered else ("warning" if key in LOW_PRIORITY else "critical"),
        "subject": key,
        "title": f"{label} {'恢复确认' if recovered else '故障确认'}",
        "detail": f"{old} → {new}；连续确认 {streak} 次",
        "old_state": old,
        "new_state": new,
        "confirmed_streak": streak,
    }


def seed_state(current: dict[str, str], labels: dict[str, str]) -> dict:
    stamp = iso_now()
    return {
        "version": 2,
        "updated_at": stamp,
        "subjects": {
            key: {
                "label": labels.get(key, key),
                "stable_state": state,
                "observed_state": state,
                "consecutive": 1,
                "incident_open": False,
                "last_observed_at": stamp,
                "last_incident_at": None,
                "last_recovery_at": None,
            }
            for key, state in current.items()
        },
    }


def main() -> None:
    current, labels = observations()
    events = load_json(EVENTS, [])
    state = load_json(STATE, {})
    if state.get("version") != 2:
        atomic_write(STATE, seed_state(current, labels))
        atomic_write(EVENTS, events[:MAX_EVENTS])
        print(json.dumps({"mode": "seed", "subjects": len(current), "events_added": 0}))
        return

    subjects = state.setdefault("subjects", {})
    added: list[dict] = []
    stamp = iso_now()
    for key, observed in current.items():
        rec = subjects.setdefault(key, {
            "label": labels.get(key, key), "stable_state": observed,
            "observed_state": observed, "consecutive": 0,
            "incident_open": False, "last_incident_at": None,
            "last_recovery_at": None,
        })
        rec["label"] = labels.get(key, rec.get("label") or key)
        if observed == rec.get("observed_state"):
            rec["consecutive"] = int(rec.get("consecutive") or 0) + 1
        else:
            rec["observed_state"] = observed
            rec["consecutive"] = 1
        rec["last_observed_at"] = stamp

        stable = str(rec.get("stable_state") or "unknown")
        streak = int(rec.get("consecutive") or 0)
        if key in SILENCED or observed in {"unknown", "degraded"} or observed == stable:
            continue

        if observed == "offline":
            threshold = failure_threshold(key)
            recovered_at = parse_time(rec.get("last_recovery_at"))
            if recovered_at and (utcnow() - recovered_at).total_seconds() < REOPEN_WINDOW_SECONDS:
                threshold = max(threshold, REOPEN_STREAK)
            if streak >= threshold:
                rec["stable_state"] = "offline"
                rec["incident_open"] = True
                rec["last_incident_at"] = stamp
                added.append(make_event(key, rec["label"], "incident", stable, "offline", streak))

        elif observed == "online" and streak >= RECOVERY_STREAK:
            was_open = bool(rec.get("incident_open"))
            rec["stable_state"] = "online"
            rec["incident_open"] = False
            rec["last_recovery_at"] = stamp
            if was_open:
                added.append(make_event(key, rec["label"], "recovery", stable, "online", streak))

    for event in reversed(added):
        events.insert(0, event)
    state["updated_at"] = stamp
    state["policy"] = {
        "service_failure_streak": 3,
        "low_priority_failure_streak": 5,
        "device_failure_streak": 5,
        "recovery_streak": RECOVERY_STREAK,
        "reopen_streak": REOPEN_STREAK,
        "reopen_window_seconds": REOPEN_WINDOW_SECONDS,
        "degraded_notifications": False,
    }
    atomic_write(STATE, state)
    atomic_write(EVENTS, events[:MAX_EVENTS])
    print(json.dumps({"mode": "evaluate", "subjects": len(current), "events_added": len(added), "added": [e["subject"] for e in added]}))


if __name__ == "__main__":
    main()
