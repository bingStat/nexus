from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .status import annotate_device, annotate_device_payload

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

DEFAULT_BLOCKED_PATTERNS = [
    r"(^|[;&|]\s*)rm\s+-rf\s+/(?:\s|$)",
    r"\b(mkfs|fdisk|parted|wipefs)\b",
    r"\b(shutdown|poweroff|reboot|halt)\b",
    r"\b(passwd|chpasswd)\b",
    r"\b(iptables|nft|uci\s+set\s+network|uci\s+set\s+firewall)\b",
]

TERMINAL = {"completed", "failed", "timeout"}
WORKSPACE_OPERATIONS = {
    "workspace.open",
    "workspace.read",
    "workspace.apply_patch",
    "workspace.exec",
    "workspace.write_stdin",
}


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


def list_agent_presence(region: str) -> dict[str, Any]:
    normalized_region = region.strip().lower()
    if normalized_region not in {"eu", "cn"}:
        raise ValueError("region must be eu or cn")
    code, payload = request_json("GET", f"{broker_url(normalized_region)}/v3/agents")
    result = require_success(code, payload, {200})
    result["broker_region"] = normalized_region
    return result


def presence_map() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    merged: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for region in ("eu", "cn"):
        try:
            payload = list_agent_presence(region)
            for row in payload.get("agents", []):
                if not isinstance(row, dict):
                    continue
                device_id = str(row.get("device_id") or "").strip().lower()
                if not device_id:
                    continue
                merged[device_id] = {**row, "broker_region": region}
        except Exception as exc:
            errors[region] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return merged, errors


def annotate_with_presence(row: dict[str, Any], presence: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(row)
    if presence:
        merged["last_seen_at"] = presence.get("last_seen")
        merged["agent_id"] = presence.get("agent_id")
        merged["broker_region"] = presence.get("broker_region")
        merged["presence_source"] = "broker-long-poll"
    else:
        merged["last_seen_at"] = None
        merged["presence_source"] = "none"
    return annotate_device(merged)


def list_devices(status: str = "approved") -> dict[str, Any]:
    code, payload = request_json("GET", f"{registry_url()}/v3/admin/devices?{urlencode({'status': status})}")
    result = require_success(code, payload, {200})
    presences, errors = presence_map()
    devices = []
    for row in result.get("devices", []):
        if isinstance(row, dict):
            device_id = str(row.get("device_id") or "").strip().lower()
            devices.append(annotate_with_presence(row, presences.get(device_id)))
    return {**result, "devices": devices, "presence_errors": errors}


def get_device(device_id: str) -> dict[str, Any]:
    device = device_id.strip().lower()
    code, payload = request_json("GET", f"{registry_url()}/v3/devices/{device}/public-key")
    row = require_success(code, payload, {200})
    region = resolve_region(device)
    try:
        presence = next(
            (item for item in list_agent_presence(region).get("agents", []) if str(item.get("device_id") or "").lower() == device),
            None,
        )
    except Exception:
        presence = None
    if presence:
        presence = {**presence, "broker_region": region}
    return annotate_with_presence(row, presence)


def require_devspace_device(device_id: str) -> dict[str, Any]:
    device = get_device(device_id)
    capabilities = device.get("capabilities") if isinstance(device.get("capabilities"), dict) else {}
    if capabilities.get("runtime") != "devspace":
        raise RuntimeError(f"device '{device_id}' does not advertise the DevSpace workspace runtime")
    return device


def get_job(job_id: str, region: str) -> dict[str, Any]:
    normalized_region = region.strip().lower()
    if normalized_region not in {"eu", "cn"}:
        raise ValueError("region must be eu or cn")
    code, payload = request_json("GET", f"{broker_url(normalized_region)}/v3/jobs?{urlencode({'id': job_id})}")
    payload = require_success(code, payload, {200})
    payload["broker_region"] = normalized_region
    return payload


def list_jobs(region: str, limit: int = 50) -> dict[str, Any]:
    normalized_region = region.strip().lower()
    if normalized_region not in {"eu", "cn"}:
        raise ValueError("region must be eu or cn")
    code, payload = request_json("GET", f"{broker_url(normalized_region)}/v3/jobs?{urlencode({'limit': max(1, min(limit, 200))})}")
    result = require_success(code, payload, {200})
    result["broker_region"] = normalized_region
    return result


def wait_for_job(job: dict[str, Any], region: str, wait_seconds: int) -> dict[str, Any]:
    if wait_seconds <= 0:
        job["broker_region"] = region
        return job
    base = broker_url(region)
    deadline = time.time() + max(0, min(wait_seconds, 120))
    while time.time() < deadline:
        time.sleep(1)
        code, current = request_json("GET", f"{base}/v3/jobs?{urlencode({'id': job['id']})}")
        current = require_success(code, current, {200})
        if current.get("status") in TERMINAL:
            current["broker_region"] = region
            return current
    job["broker_region"] = region
    return job


def submit_operation(
    device_id: str,
    operation: str,
    input_data: dict[str, Any],
    timeout_ms: int = 30000,
    wait_seconds: int = 20,
) -> dict[str, Any]:
    device = device_id.strip().lower()
    if operation in WORKSPACE_OPERATIONS:
        require_devspace_device(device)
    region = resolve_region(device)
    code, job = request_json(
        "POST",
        f"{broker_url(region)}/v3/jobs",
        {
            "target_device": device,
            "operation": operation,
            "input": input_data,
            "timeout_ms": max(1000, min(timeout_ms, 86400000)),
        },
    )
    return wait_for_job(require_success(code, job, {201}), region, wait_seconds)


def execute_batch(jobs: list[dict[str, Any]], wait_seconds: int = 20) -> dict[str, Any]:
    if not 1 <= len(jobs) <= 16:
        raise ValueError("jobs must contain 1 to 16 items")
    results: list[dict[str, Any]] = [{} for _ in jobs]
    with ThreadPoolExecutor(max_workers=min(8, len(jobs)), thread_name_prefix="nexus-batch") as pool:
        futures = {}
        for index, job in enumerate(jobs):
            future = pool.submit(execute_command, str(job["device_id"]), str(job["command"]), int(job.get("timeout_ms") or 30000), int(job.get("wait_seconds", wait_seconds)))
            futures[future] = index
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                results[index] = {"status": "failed", "error": type(exc).__name__, "detail": str(exc)[:500]}
    return {"results": results}


def fleet_status() -> dict[str, Any]:
    devices = list_devices("approved").get("devices", [])
    counts = {key: 0 for key in ("online", "degraded", "offline", "unknown")}
    for device in devices:
        state = str(device.get("runtime_status") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    brokers = {}
    for region in ("eu", "cn"):
        try:
            code, health = request_json("GET", f"{broker_url(region)}/v3/health")
            brokers[region] = health if code == 200 else {"status": "offline", "http_status": code}
        except Exception as exc:
            brokers[region] = {"status": "offline", "error": type(exc).__name__}
    return {"devices": devices, "counts": counts, "total": len(devices), "brokers": brokers}


def execute_command(device_id: str, command: str, timeout_ms: int = 30000, wait_seconds: int = 20) -> dict[str, Any]:
    device = device_id.strip().lower()
    command_policy(command)
    region = resolve_region(device)
    code, job = request_json(
        "POST",
        f"{broker_url(region)}/v3/jobs",
        {
            "target_device": device,
            "operation": "shell.execute",
            "input": {"command": command},
            "command": command,
            "timeout_ms": max(1000, min(timeout_ms, 86400000)),
        },
    )
    return wait_for_job(require_success(code, job, {201}), region, wait_seconds)


def open_workspace(
    device_id: str,
    path: str,
    mode: str = "checkout",
    base_ref: str | None = None,
    wait_seconds: int = 20,
) -> dict[str, Any]:
    if mode not in {"checkout", "worktree"}:
        raise ValueError("mode must be checkout or worktree")
    payload: dict[str, Any] = {"path": path, "mode": mode}
    if base_ref:
        payload["baseRef"] = base_ref
    return submit_operation(device_id, "workspace.open", payload, wait_seconds=wait_seconds)


def read_workspace(
    device_id: str,
    workspace_id: str,
    path: str,
    offset: int | None = None,
    limit: int | None = None,
    wait_seconds: int = 20,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"workspaceId": workspace_id, "path": path}
    if offset is not None:
        payload["offset"] = offset
    if limit is not None:
        payload["limit"] = limit
    return submit_operation(device_id, "workspace.read", payload, wait_seconds=wait_seconds)


def apply_workspace_patch(
    device_id: str,
    workspace_id: str,
    patch: str,
    wait_seconds: int = 20,
) -> dict[str, Any]:
    return submit_operation(
        device_id,
        "workspace.apply_patch",
        {"workspaceId": workspace_id, "patch": patch},
        wait_seconds=wait_seconds,
    )


def exec_workspace_command(
    device_id: str,
    workspace_id: str,
    command: str,
    working_directory: str | None = None,
    tty: bool = False,
    yield_time_ms: int | None = None,
    max_output_tokens: int | None = None,
    wait_seconds: int = 20,
) -> dict[str, Any]:
    command_policy(command)
    payload: dict[str, Any] = {"workspaceId": workspace_id, "command": command, "tty": tty}
    if working_directory:
        payload["workingDirectory"] = working_directory
    if yield_time_ms is not None:
        payload["yieldTimeMs"] = yield_time_ms
    if max_output_tokens is not None:
        payload["maxOutputTokens"] = max_output_tokens
    return submit_operation(device_id, "workspace.exec", payload, wait_seconds=wait_seconds)


def write_workspace_stdin(
    device_id: str,
    workspace_id: str,
    session_id: int,
    chars: str = "",
    yield_time_ms: int | None = None,
    wait_seconds: int = 20,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workspaceId": workspace_id,
        "sessionId": session_id,
        "chars": chars,
    }
    if yield_time_ms is not None:
        payload["yieldTimeMs"] = yield_time_ms
    return submit_operation(device_id, "workspace.write_stdin", payload, wait_seconds=wait_seconds)
