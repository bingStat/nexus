from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
DEVICE_KEY_PREFIX = "nxk_"
DEVICE_KEY_BYTES = 32


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_json(body: bytes) -> Any:
    return json.loads(body.decode("utf-8") or "{}")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_device_key(value: str) -> str:
    key = str(value or "").strip()
    if not key.startswith(DEVICE_KEY_PREFIX) or len(key) < 40:
        raise ValueError("invalid device key")
    return key


def device_key_hash(value: str) -> str:
    key = validate_device_key(value)
    return "sha256:" + sha256_hex(key.encode("utf-8"))


def load_or_create_device_key(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        key = validate_device_key(path.read_text(encoding="ascii"))
    else:
        key = DEVICE_KEY_PREFIX + secrets.token_urlsafe(DEVICE_KEY_BYTES)
        path.write_text(key + "\n", encoding="ascii")
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
        os.chmod(path, 0o600)
    return key


class Identity:
    """Per-device opaque authentication key.

    Nexus device authentication intentionally uses a symmetric random key, not
    an SSH/private-key pair. SSH credentials are managed independently.
    """

    def __init__(self, key_path: Path):
        self.key_path = key_path
        self.key = load_or_create_device_key(key_path)
        self.key_id = device_key_hash(self.key)

    def auth_headers(self, device_id: str) -> dict[str, str]:
        return {
            "X-Nexus-Device": device_id,
            "X-Nexus-Device-Key": self.key,
        }

    def registration_payload(
        self,
        device_id: str,
        hostname: str,
        platform: str,
        agent_version: str,
        ssh_public_key: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "device_id": device_id,
            "device_key": self.key,
            "hostname": hostname,
            "platform": platform,
            "agent_version": agent_version,
        }
        if ssh_public_key:
            payload["ssh_public_key"] = ssh_public_key.strip()
        return payload


def verify_device_key(stored_hash: str, headers: dict[str, str]) -> str:
    device_id = str(headers.get("X-Nexus-Device") or "").strip().lower()
    supplied = str(headers.get("X-Nexus-Device-Key") or "").strip()
    if not device_id or not supplied:
        raise PermissionError("missing device authentication headers")
    try:
        actual_hash = device_key_hash(supplied)
    except ValueError as exc:
        raise PermissionError("invalid device key") from exc
    if not hmac.compare_digest(str(stored_hash or ""), actual_hash):
        raise PermissionError("device authentication failed")
    return device_id
