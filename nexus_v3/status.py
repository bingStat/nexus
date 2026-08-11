from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc

DEFAULT_DEVICE_THRESHOLDS = {
    "default": {"online": 90, "offline": 300},
    "victus": {"online": 120, "offline": 300},
    "victus-wsl": {"online": 120, "offline": 300},
    "n1": {"online": 120, "offline": 360},
    "ax3600": {"online": 120, "offline": 360},
}


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def thresholds_for(device_id: str, overrides: dict[str, Any] | None = None) -> dict[str, int]:
    merged = {key: dict(value) for key, value in DEFAULT_DEVICE_THRESHOLDS.items()}
    for key, value in (overrides or {}).items():
        if isinstance(value, dict):
            merged[str(key).lower()] = {**merged.get(str(key).lower(), {}), **value}
    selected = merged.get(device_id.lower(), merged["default"])
    return {
        "online": max(1, int(selected.get("online", 90))),
        "offline": max(2, int(selected.get("offline", 300))),
    }


def annotate_device(
    row: dict[str, Any],
    *,
    now: datetime | None = None,
    threshold_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(row)
    device_id = str(out.get("device_id") or "").lower()
    thresholds = thresholds_for(device_id, threshold_overrides)
    observed = parse_timestamp(out.get("last_seen_at"))
    current = now or datetime.now(UTC)
    age = max(0, int((current - observed).total_seconds())) if observed else None
    approval = str(out.get("status") or "unknown")
    if approval != "approved":
        runtime_status = approval
    elif age is None:
        runtime_status = "unknown"
    elif age < thresholds["online"]:
        runtime_status = "online"
    elif age < thresholds["offline"]:
        runtime_status = "degraded"
    else:
        runtime_status = "offline"
    out["runtime_status"] = runtime_status
    out["age_seconds"] = age
    out["thresholds_seconds"] = thresholds
    return out


def annotate_device_payload(
    payload: dict[str, Any], threshold_overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    out = dict(payload)
    devices = payload.get("devices") if isinstance(payload, dict) else None
    if isinstance(devices, list):
        now = datetime.now(UTC)
        out["devices"] = [
            annotate_device(item, now=now, threshold_overrides=threshold_overrides)
            for item in devices if isinstance(item, dict)
        ]
    return out
