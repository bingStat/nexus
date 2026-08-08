from __future__ import annotations

import json
import os
import re
import shlex
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_DEVICE_REGIONS = {
    "oracle": "eu",
    "vsc": "eu",
    "victus": "eu",
    "victus-wsl": "eu",
    "elitebook": "eu",
    "thinkcenter": "cn",
    "n1": "cn",
    "ax3600": "cn",
}

DEFAULT_MANAGED_TARGETS = {
    "n1": {"controller": "thinkcenter", "ssh": "root@100.90.67.12"},
    "ax3600": {"controller": "thinkcenter", "ssh": "root@192.168.1.1"},
}

DEFAULT_BLOCKED_PATTERNS = [
    r"(^|[;&|]\s*)rm\s+-rf\s+/(?:\s|$)",
    r"\b(mkfs|fdisk|parted|wipefs)\b",
    r"\b(shutdown|poweroff|reboot|halt)\b",
    r"\b(passwd|chpasswd)\b",
    r"\b(iptables|nft|uci\s+set\s+network|uci\s+set\s+firewall)\b",
]

TERMINAL = {"completed", "failed", "timeout"}


def env_json(name: str, default: Any) -> Any:
    raw = os.getenv(name)
    return default if not raw else json.loads(raw)


def admin_key() -> str:
    value = os.getenv("NEXUS_V3_ADMIN_KEY", "")
    if not value:
        raise RuntimeError("NEXUS_V3_ADMIN_KEY is required")
    return value


def registry_url() -> str:
    return os.getenv("NEXUS_V3_REGISTRY_URL", "http://127.0.0.1:18101").rstrip("/")


def broker_url(region: str) -> str:
    key = f"NEXUS_V3_{region.upper()}_BROKER_URL"
    default = "http://127.0.0.1:18102" if region == "eu" else "http://100.103.12.14:18120"
    return os.getenv(key, default).rstrip("/")


def device_regions() -> dict[str, str]:
    configured = env_json("NEXUS_V3_DEVICE_REGIONS", DEFAULT_DEVICE_REGIONS)
    return {str(key).lower(): str(value).lower() for key, value in configured.items()}


def resolve_region(device_id: str) -> str:
    device = device_id.strip().lower()
    region = device_regions().get(device)
    if region not in {"eu", "cn"}:
        raise ValueError(f"unknown Nexus device: {device}")
    return region


def managed_targets() -> dict[str, dict[str, str]]:
    configured = env_json("NEXUS_V3_MANAGED_TARGETS", DEFAULT_MANAGED_TARGETS)
    return {
        str(device).lower(): {"controller": str(config["controller"]).lower(), "ssh": str(config["ssh"])}
        for device, config in configured.items()
    }


def approved_device_exists(device_id: str) -> bool:
    device = device_id.strip().lower()
    code, _payload = request_json("GET", f"{registry_url()}/v3/devices/{device}/public-key")
    return code == 200


def dispatch_target(device_id: str, command: str) -> tuple[str, str, str | None]:
    device = device_id.strip().lower()
    if approved_device_exists(device):
        return device, command, None
    managed = managed_targets().get(device)
    if not managed:
        return device, command, None
    controller = managed["controller"]
    remote_command = (
        "ssh -o BatchMode=yes -o ConnectTimeout=10 "
        "-o StrictHostKeyChecking=accept-new "
        f"{shlex.quote(managed['ssh'])} -- sh -c {shlex.quote(command)}"
    )
    return controller, remote_command, device


def command_policy(command: str) -> None:
    if os.getenv("NEXUS_V3_ALLOW_DANGEROUS", "0") == "1":
        return
    patterns = env_json("NEXUS_V3_BLOCKED_COMMAND_PATTERNS", DEFAULT_BLOCKED_PATTERNS)
    for pattern in patterns:
        if re.search(str(pattern), command, flags=re.IGNORECASE):
            raise PermissionError("command rejected by Nexus safety policy")


def request_json(method: str, url: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={"X-Nexus-Admin-Key": admin_key(), "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"error": raw[:500]}
        return exc.code, payload


def require_success(code: int, payload: Any, expected: set[int]) -> Any:
    if code in expected:
        return payload
    detail = payload.get("error") if isinstance(payload, dict) else payload
    raise RuntimeError(f"Nexus API returned HTTP {code}: {detail}")


def list_devices(status: str = "approved") -> dict[str, Any]:
    code, payload = request_json("GET", f"{registry_url()}/v3/admin/devices?{urlencode({'status': status})}")
    return require_success(code, payload, {200})


def get_device(device_id: str) -> dict[str, Any]:
    device = device_id.strip().lower()
    code, payload = request_json("GET", f"{registry_url()}/v3/devices/{device}/public-key")
    return require_success(code, payload, {200})


def get_job(job_id: str, region: str) -> dict[str, Any]:
    normalized_region = region.strip().lower()
    if normalized_region not in {"eu", "cn"}:
        raise ValueError("region must be eu or cn")
    code, payload = request_json("GET", f"{broker_url(normalized_region)}/v3/jobs?{urlencode({'id': job_id})}")
    payload = require_success(code, payload, {200})
    payload["broker_region"] = normalized_region
    return payload


def execute_command(device_id: str, command: str, timeout_ms: int = 30000, wait_seconds: int = 20) -> dict[str, Any]:
    device = device_id.strip().lower()
    command_policy(command)
    target_device, target_command, managed_target = dispatch_target(device, command)
    region = resolve_region(target_device)
    base = broker_url(region)
    code, job = request_json(
        "POST",
        f"{base}/v3/jobs",
        {"target_device": target_device, "command": target_command, "timeout_ms": max(1000, min(timeout_ms, 86400000))},
    )
    job = require_success(code, job, {201})
    if managed_target:
        job["requested_device"] = device
        job["managed_target"] = managed_target
        job["controller_device"] = target_device
    deadline = time.time() + max(0, min(wait_seconds, 120))
    while wait_seconds > 0 and time.time() < deadline:
        time.sleep(1)
        code, current = request_json("GET", f"{base}/v3/jobs?{urlencode({'id': job['id']})}")
        current = require_success(code, current, {200})
        if current.get("status") in TERMINAL:
            current["broker_region"] = region
            if managed_target:
                current["requested_device"] = device
                current["managed_target"] = managed_target
                current["controller_device"] = target_device
            return current
    job["broker_region"] = region
    return job
