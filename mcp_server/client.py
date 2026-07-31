"""Internal Nexus backend client.

Only the control plane imports this module. Browsers and MCP clients must never
write the database directly.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import httpx

from mcp_server.models import derive_device_state


def _base_url() -> str:
    value = os.environ.get("NEXUS_INTERNAL_API_URL") or os.environ.get("NEXUS_API_URL")
    if not value:
        raise RuntimeError("NEXUS_INTERNAL_API_URL is required")
    return value.rstrip("/")


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    token = os.environ.get("NEXUS_INTERNAL_API_TOKEN") or os.environ.get("NEXUS_API_KEY")
    if not token:
        raise RuntimeError("NEXUS_INTERNAL_API_TOKEN is required")
    headers = {
        "Authorization": f"Bearer {token}",
        "apikey": token,
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def list_devices() -> list[dict[str, Any]]:
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{_base_url()}/devices?select=*", headers=_headers())
        response.raise_for_status()
        devices = response.json()
    for device in devices:
        device["computed_state"] = derive_device_state(device.get("last_seen")).value
    return devices


def get_device_status(device_id: str) -> dict[str, Any] | None:
    devices = list_devices()
    wanted = device_id.casefold()
    return next(
        (
            item
            for item in devices
            if str(item.get("device_id", "")).casefold() == wanted
            or str(item.get("name", "")).casefold() == wanted
        ),
        None,
    )


def create_command(
    *,
    target_device: str,
    command_str: str,
    timeout_ms: int = 30_000,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "id": str(uuid.uuid4()),
        "target_device": target_device,
        "command": command_str,
        "status": "pending",
        "timeout_ms": timeout_ms,
    }
    if metadata:
        payload["metadata"] = metadata
    with httpx.Client(timeout=10) as client:
        response = client.post(
            f"{_base_url()}/commands",
            json=payload,
            headers=_headers({"Prefer": "return=representation"}),
        )
        response.raise_for_status()
        data = response.json()
    return data[0] if isinstance(data, list) and data else payload


def get_command_result(job_id: str) -> dict[str, Any] | None:
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{_base_url()}/commands?id=eq.{job_id}&select=*", headers=_headers()
        )
        response.raise_for_status()
        data = response.json()
    return data[0] if data else None


def wait_for_command(job_id: str, max_wait_seconds: int = 10) -> dict[str, Any]:
    deadline = time.monotonic() + max_wait_seconds
    result = get_command_result(job_id)
    while result and time.monotonic() < deadline:
        if result.get("status") in {"completed", "failed", "timeout", "cancelled"}:
            return result
        time.sleep(1)
        result = get_command_result(job_id)
    return result or {"id": job_id, "status": "unknown"}
