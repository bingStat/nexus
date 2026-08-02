"""
Nexus REST API client with relay fallback and safe dashboard helpers.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

PRIMARY_API_URL = "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1"


def get_api_urls() -> List[str]:
    configured = os.getenv("NEXUS_API_URL", "").rstrip("/")
    urls: List[str] = []
    if configured:
        urls.append(configured)
    if PRIMARY_API_URL not in urls:
        urls.append(PRIMARY_API_URL)
    return urls


def get_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("NEXUS_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["apikey"] = api_key
    if extra:
        headers.update(extra)
    return headers


def _request(method: str, path: str, *, params=None, json=None, timeout: float = 8, headers=None):
    errors: List[str] = []
    for base in get_api_urls():
        try:
            response = requests.request(
                method,
                f"{base}/{path.lstrip('/')}",
                params=params,
                json=json,
                headers=headers or get_headers(),
                timeout=timeout,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            errors.append(f"{base}: {type(exc).__name__}")
    raise RuntimeError("All Nexus API paths failed: " + "; ".join(errors))


def list_devices() -> List[Dict[str, Any]]:
    return _request("GET", "devices", params={"select": "*", "order": "last_seen.desc"}).json()


def list_recent_commands(limit: int = 20) -> List[Dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    params = {
        "select": "id,target_device,status,created_at,updated_at",
        "order": "created_at.desc",
        "limit": str(safe_limit),
    }
    return _request("GET", "commands", params=params).json()


def get_device_status(device_id: str) -> Optional[Dict[str, Any]]:
    params = {"or": f"(device_id.eq.{device_id},name.eq.{device_id})", "select": "*"}
    data = _request("GET", "devices", params=params).json()
    return data[0] if data else None


def create_command(target_device: str, command_str: str, timeout_ms: int = 30000) -> Dict[str, Any]:
    payload = {
        "id": str(uuid.uuid4()),
        "target_device": target_device,
        "command": command_str,
        "status": "pending",
        "timeout_ms": timeout_ms,
    }
    response = _request(
        "POST",
        "commands",
        json=payload,
        headers=get_headers({"Prefer": "return=representation"}),
    )
    data = response.json()
    return data[0] if isinstance(data, list) and data else payload


def get_command_result(job_id: str) -> Optional[Dict[str, Any]]:
    data = _request("GET", "commands", params={"id": f"eq.{job_id}", "select": "*"}).json()
    return data[0] if data else None


def wait_for_command(job_id: str, max_wait_seconds: int = 10, poll_interval: float = 1.0) -> Dict[str, Any]:
    start = time.time()
    last = get_command_result(job_id)
    while time.time() - start < max_wait_seconds:
        if not last:
            break
        if last.get("status") in {"completed", "failed", "timeout", "expired", "cancelled"}:
            return last
        time.sleep(poll_interval)
        last = get_command_result(job_id)
    return last or {"id": job_id, "status": "unknown", "output": "Failed to retrieve status"}


def parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None
