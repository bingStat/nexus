from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import atomic_json, load_config, load_json, now_iso, parse_timestamp

UTC = timezone.utc
DEFAULT_HEALTH = Path("/var/lib/nexus/ops/health.json")
DEFAULT_STATE = Path("/var/lib/nexus/ops/alert-state.json")
DEFAULT_EVENTS = Path("/var/lib/nexus/ops/events.json")


def observations(health: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    current: dict[str, str] = {}
    labels: dict[str, str] = {}
    for device in health.get("devices") or []:
        key = f"device:{device.get('device_id')}"
        current[key] = str(device.get("runtime_status") or "unknown")
        labels[key] = str(device.get("hostname") or device.get("device_id"))
    for check in health.get("checks") or []:
        key = f"service:{check.get('id')}"
        current[key] = str(check.get("status") or "unknown")
        labels[key] = str(check.get("name") or check.get("id"))
    current["connection:tailscale"] = str((health.get("tailscale") or {}).get("status") or "unknown")
    labels["connection:tailscale"] = "Tailscale"
    return current, labels


def seed(current: dict[str, str], labels: dict[str, str]) -> dict[str, Any]:
    stamp = now_iso()
    return {"version": 3, "updated_at": stamp, "subjects": {
        key: {"label": labels.get(key, key), "stable_state": value, "observed_state": value,
              "consecutive": 1, "incident_open": False, "last_observed_at": stamp,
              "last_incident_at": None, "last_recovery_at": None}
        for key, value in current.items()
    }}


def event(key: str, label: str, kind: str, old: str, new: str, streak: int, low_priority: bool) -> dict[str, Any]:
    recovered = kind == "recovery"
    return {
        "id": f"{int(datetime.now(UTC).timestamp() * 1000)}-{key}-{kind}",
        "created_at": now_iso(), "kind": kind,
        "severity": "info" if recovered else ("warning" if low_priority else "critical"),
        "subject": key,
        "title": f"{label} {'recovered' if recovered else 'incident confirmed'}",
        "detail": f"{old} -> {new}; confirmed for {streak} checks",
        "old_state": old, "new_state": new, "confirmed_streak": streak,
    }


def main() -> None:
    config = load_config()
    policy = config.get("alerts") if isinstance(config.get("alerts"), dict) else {}
    health_path = Path(str(config.get("health_file") or DEFAULT_HEALTH))
    state_path = Path(str(policy.get("state_file") or DEFAULT_STATE))
    events_path = Path(str(policy.get("events_file") or DEFAULT_EVENTS))
    health = load_json(health_path, {"devices": [], "checks": []})
    current, labels = observations(health)
    state = load_json(state_path, {})
    events = load_json(events_path, [])
    max_events = int(policy.get("max_events") or 500)
    if state.get("version") != 3:
        atomic_json(state_path, seed(current, labels), 0o640)
        atomic_json(events_path, events[:max_events], 0o640)
        print(json.dumps({"mode": "seed", "subjects": len(current), "events_added": 0}))
        return

    failure_default = int(policy.get("service_failure_streak") or 3)
    device_failure = int(policy.get("device_failure_streak") or 5)
    low_failure = int(policy.get("low_priority_failure_streak") or 5)
    recovery_streak = int(policy.get("recovery_streak") or 3)
    reopen_streak = int(policy.get("reopen_streak") or 10)
    reopen_window = int(policy.get("reopen_window_seconds") or 1800)
    low_priority = {str(x) for x in (policy.get("low_priority") or [])}
    silenced = {str(x) for x in (policy.get("silenced") or [])}
    subjects = state.setdefault("subjects", {})
    added: list[dict[str, Any]] = []
    stamp = now_iso()
    for key, observed in current.items():
        rec = subjects.setdefault(key, {
            "label": labels.get(key, key), "stable_state": observed, "observed_state": observed,
            "consecutive": 0, "incident_open": False, "last_incident_at": None, "last_recovery_at": None,
        })
        rec["label"] = labels.get(key, rec.get("label") or key)
        if observed == rec.get("observed_state"):
            rec["consecutive"] = int(rec.get("consecutive") or 0) + 1
        else:
            rec["observed_state"], rec["consecutive"] = observed, 1
        rec["last_observed_at"] = stamp
        stable, streak = str(rec.get("stable_state") or "unknown"), int(rec.get("consecutive") or 0)
        if key in silenced or observed in {"unknown", "degraded"} or observed == stable:
            continue

        if observed == "offline":
            threshold = device_failure if key.startswith("device:") else (low_failure if key in low_priority else failure_default)
            recovered_at = parse_timestamp(rec.get("last_recovery_at"))
            if recovered_at and (datetime.now(UTC) - recovered_at).total_seconds() < reopen_window:
                threshold = max(threshold, reopen_streak)
            if streak >= threshold:
                rec["stable_state"], rec["incident_open"], rec["last_incident_at"] = "offline", True, stamp
                added.append(event(key, rec["label"], "incident", stable, "offline", streak, key in low_priority))
        elif observed == "online" and streak >= recovery_streak:
            was_open = bool(rec.get("incident_open"))
            rec["stable_state"], rec["incident_open"], rec["last_recovery_at"] = "online", False, stamp
            if was_open:
                added.append(event(key, rec["label"], "recovery", stable, "online", streak, key in low_priority))

    events = list(reversed(added)) + list(events)
    state["updated_at"] = stamp
    state["policy"] = {
        "service_failure_streak": failure_default, "device_failure_streak": device_failure,
        "low_priority_failure_streak": low_failure, "recovery_streak": recovery_streak,
        "reopen_streak": reopen_streak, "reopen_window_seconds": reopen_window,
        "degraded_notifications": False,
    }
    atomic_json(state_path, state, 0o640)
    atomic_json(events_path, events[:max_events], 0o640)
    print(json.dumps({"mode": "evaluate", "subjects": len(current), "events_added": len(added)}))


if __name__ == "__main__":
    main()
