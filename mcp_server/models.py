from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    read_only = "read_only"
    mutating = "mutating"
    privileged = "privileged"
    destructive = "destructive"


class DeviceState(str, Enum):
    online = "online"
    degraded = "degraded"
    offline = "offline"
    unknown = "unknown"


class ActionRequest(BaseModel):
    device: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=200)
    timeout_ms: int = Field(default=30_000, ge=1_000, le=900_000)


class ShellRequest(BaseModel):
    device: str = Field(min_length=1, max_length=64)
    command: str = Field(min_length=1, max_length=32_000)
    allow_privileged: bool = False
    allow_destructive: bool = False
    timeout_ms: int = Field(default=30_000, ge=1_000, le=900_000)


def derive_device_state(last_seen: str | None, now: datetime | None = None) -> DeviceState:
    if not last_seen:
        return DeviceState.unknown
    try:
        seen = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
    except ValueError:
        return DeviceState.unknown
    current = now or datetime.now(timezone.utc)
    age = max(0.0, (current - seen.astimezone(timezone.utc)).total_seconds())
    if age < 60:
        return DeviceState.online
    if age < 180:
        return DeviceState.degraded
    return DeviceState.offline
