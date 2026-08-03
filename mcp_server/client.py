"""Low-latency Nexus REST client with regional broker routing and failover."""
from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PRIMARY_API_URL = "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1"
TERMINAL = {"completed", "failed", "timeout", "expired", "cancelled"}
_LOCAL = threading.local()
_RETRY = Retry(total=1, connect=1, read=0, backoff_factor=0.05, status_forcelist=(502, 503, 504), allowed_methods=None)
_JOB_ROUTES: dict[str, tuple[str, str]] = {}
_JOB_ROUTES_LOCK = threading.Lock()
EU_DEVICES = {item.strip().lower() for item in os.getenv("NEXUS_BROKER_EU_DEVICES", "oracle,vsc,victus,elitebook").split(",") if item.strip()}
CN_DEVICES = {item.strip().lower() for item in os.getenv("NEXUS_BROKER_CN_DEVICES", "thinkcenter,n1,ax3600").split(",") if item.strip()}


def _session() -> requests.Session:
    session = getattr(_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=12, pool_maxsize=32, max_retries=_RETRY)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _LOCAL.session = session
    return session


def get_broker_headers() -> Dict[str, str]:
    token = os.getenv("NEXUS_BROKER_TOKEN") or os.getenv("NEXUS_API_KEY", "")
    headers = {"Content-Type": "application/json", "Connection": "keep-alive"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _broker_urls() -> dict[str, str]:
    return {
        "cn": os.getenv("NEXUS_BROKER_CN_URL", os.getenv("NEXUS_BROKER_URL", "http://127.0.0.1:18000")).rstrip("/"),
        "eu": os.getenv("NEXUS_BROKER_EU_URL", "https://nexus-eu-broker.bings.app").rstrip("/"),
    }


def region_for_device(device: str) -> str:
    normalized = str(device or "").strip().lower()
    if normalized in EU_DEVICES:
        return "eu"
    if normalized in CN_DEVICES:
        return "cn"
    return os.getenv("NEXUS_BROKER_DEFAULT_REGION", "cn").strip().lower() or "cn"


def broker_candidates(device: str) -> list[tuple[str, str]]:
    urls = _broker_urls()
    primary = region_for_device(device)
    secondary = "eu" if primary == "cn" else "cn"
    candidates = [(primary, urls[primary]), (secondary, urls[secondary])]
    result: list[tuple[str, str]] = []
    for region, url in candidates:
        if url and (region, url) not in result:
            result.append((region, url))
    return result


def _broker_request(base_url: str, method: str, path: str, *, params=None, json=None, timeout: float = 12) -> requests.Response:
    started = time.perf_counter()
    response = _session().request(
        method,
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        params=params,
        json=json,
        headers=get_broker_headers(),
        timeout=timeout,
    )
    response.raise_for_status()
    response.nexus_elapsed_ms = round((time.perf_counter() - started) * 1000, 1)  # type: ignore[attr-defined]
    return response


def get_api_urls() -> List[str]:
    configured = os.getenv("NEXUS_API_URL", "").rstrip("/")
    urls: List[str] = []
    if configured:
        urls.append(configured)
    if PRIMARY_API_URL not in urls:
        urls.append(PRIMARY_API_URL)
    return urls


def get_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    headers = {"Content-Type": "application/json", "Connection": "keep-alive"}
    api_key = os.getenv("NEXUS_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["apikey"] = api_key
    if extra:
        headers.update(extra)
    return headers


def _request(method: str, path: str, *, params=None, json=None, timeout: float = 6, headers=None) -> requests.Response:
    errors: List[str] = []
    for base in get_api_urls():
        started = time.perf_counter()
        try:
            response = _session().request(
                method,
                f"{base}/{path.lstrip('/')}",
                params=params,
                json=json,
                headers=headers or get_headers(),
                timeout=timeout,
            )
            response.raise_for_status()
            response.nexus_elapsed_ms = round((time.perf_counter() - started) * 1000, 1)  # type: ignore[attr-defined]
            response.nexus_base_url = base  # type: ignore[attr-defined]
            return response
        except requests.RequestException as exc:
            errors.append(f"{base}: {type(exc).__name__}")
    raise RuntimeError("All Nexus API paths failed: " + "; ".join(errors))


def list_devices() -> List[Dict[str, Any]]:
    return _request("GET", "devices", params={"select": "*", "order": "last_seen.desc"}).json()


def list_recent_commands(limit: int = 20) -> List[Dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    return _request("GET", "commands", params={
        "select": "id,target_device,status,created_at,updated_at",
        "order": "created_at.desc", "limit": str(safe_limit),
    }).json()


def get_device_status(device_id: str) -> Optional[Dict[str, Any]]:
    data = _request("GET", "devices", params={"or": f"(device_id.eq.{device_id},name.eq.{device_id})", "select": "*"}).json()
    return data[0] if data else None


def _remember_route(job_id: str, region: str, broker_url: str) -> None:
    with _JOB_ROUTES_LOCK:
        _JOB_ROUTES[job_id] = (region, broker_url)
        if len(_JOB_ROUTES) > 4096:
            for old in list(_JOB_ROUTES)[:1024]:
                _JOB_ROUTES.pop(old, None)


def _known_route(job_id: str) -> tuple[str, str] | None:
    with _JOB_ROUTES_LOCK:
        return _JOB_ROUTES.get(job_id)


def create_command(target_device: str, command_str: str, timeout_ms: int = 30000) -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    home_region = region_for_device(target_device)
    payload = {
        "id": job_id,
        "idempotency_key": job_id,
        "target_device": target_device,
        "command": command_str,
        "status": "pending",
        "timeout_ms": max(1000, int(timeout_ms)),
        "home_region": home_region,
        "origin_broker": home_region,
    }
    broker_errors: list[str] = []
    for region, broker_url in broker_candidates(target_device):
        try:
            response = _broker_request(broker_url, "POST", "submit", json=payload, timeout=3.5)
            record = response.json()
            record.update({
                "_submit_api_ms": getattr(response, "nexus_elapsed_ms", None),
                "_broker_managed": True,
                "_broker_url": broker_url,
                "_broker_region": region,
                "_home_region": home_region,
                "_broker_failover": region != home_region,
            })
            _remember_route(job_id, region, broker_url)
            return record
        except requests.RequestException as exc:
            broker_errors.append(f"{region}:{type(exc).__name__}")
    response = _request(
        "POST", "commands", json={key: payload[key] for key in ("id", "target_device", "command", "status", "timeout_ms")},
        headers=get_headers({"Prefer": "return=representation"}),
    )
    data = response.json()
    record = data[0] if isinstance(data, list) and data else payload
    record.update({
        "_submit_api_ms": getattr(response, "nexus_elapsed_ms", None),
        "_broker_managed": False,
        "_broker_errors": broker_errors,
        "_home_region": home_region,
    })
    return record


def _broker_lookup_candidates(job_id: str, device: str | None = None, preferred_url: str | None = None) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    known = _known_route(job_id)
    if known:
        result.append(known)
    if preferred_url:
        region = known[0] if known and known[1] == preferred_url else "unknown"
        if (region, preferred_url) not in result:
            result.append((region, preferred_url))
    candidates = broker_candidates(device or "") if device else [("cn", _broker_urls()["cn"]), ("eu", _broker_urls()["eu"])]
    for item in candidates:
        if item[1] and item not in result:
            result.append(item)
    return result


def get_command_result(job_id: str) -> Optional[Dict[str, Any]]:
    for region, broker_url in _broker_lookup_candidates(job_id):
        try:
            response = _broker_request(broker_url, "GET", "job", params={"id": job_id}, timeout=2.0)
            result = response.json()
            result.setdefault("broker_region", region)
            _remember_route(job_id, region, broker_url)
            return result
        except requests.RequestException:
            continue
    data = _request("GET", "commands", params={"id": f"eq.{job_id}", "select": "*"}).json()
    return data[0] if data else None


def _get_command_result_timed(job_id: str) -> Tuple[Optional[Dict[str, Any]], float]:
    response = _request("GET", "commands", params={"id": f"eq.{job_id}", "select": "*"})
    data = response.json()
    return (data[0] if data else None), float(getattr(response, "nexus_elapsed_ms", 0.0) or 0.0)


def parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _backend_total_ms(row: Dict[str, Any]) -> Optional[float]:
    created = parse_timestamp(row.get("created_at"))
    updated = parse_timestamp(row.get("updated_at"))
    if not created or not updated or updated < created:
        return None
    return round((updated - created).total_seconds() * 1000, 1)


def wait_for_command(
    job_id: str,
    max_wait_seconds: float = 10,
    started_monotonic: Optional[float] = None,
    submit_api_ms: Optional[float] = None,
    max_poll_interval: float = 0.4,
    broker_managed: bool = False,
    broker_url: str | None = None,
    broker_region: str | None = None,
    device: str | None = None,
) -> Dict[str, Any]:
    started = started_monotonic if started_monotonic is not None else time.perf_counter()
    deadline = started + max(0.0, float(max_wait_seconds))
    if broker_managed:
        for region, candidate_url in _broker_lookup_candidates(job_id, device=device, preferred_url=broker_url):
            remaining = max(0.0, deadline - time.perf_counter())
            if remaining <= 0:
                break
            try:
                response = _broker_request(
                    candidate_url, "GET", "wait",
                    params={"id": job_id, "wait": str(min(30.0, remaining))},
                    timeout=min(35.0, remaining + 3.0),
                )
                if response.status_code == 200 and response.content:
                    result = response.json()
                else:
                    state_response = _broker_request(candidate_url, "GET", "job", params={"id": job_id}, timeout=2.0)
                    result = state_response.json()
                _remember_route(job_id, region, candidate_url)
                client_total_ms = round((time.perf_counter() - started) * 1000, 1)
                result["_nexus_timing"] = {
                    "path": "regional-broker",
                    "broker_region": region if region != "unknown" else broker_region,
                    "broker_url": candidate_url,
                    "submit_api_ms": submit_api_ms,
                    "backend_total_ms": _backend_total_ms(result),
                    "client_total_ms": client_total_ms,
                    "result_delivery_ms": 0.0,
                    "status_polls": 0,
                    "status_api_ms": 0.0,
                }
                return result
            except requests.RequestException:
                continue
    polls = 0
    api_ms = 0.0
    running_seen_ms: Optional[float] = None
    delay = 0.0
    last: Optional[Dict[str, Any]] = None
    while time.perf_counter() <= deadline:
        if delay:
            time.sleep(min(delay, max(0.0, deadline - time.perf_counter())))
        last, request_ms = _get_command_result_timed(job_id)
        polls += 1
        api_ms += request_ms
        elapsed_ms = (time.perf_counter() - started) * 1000
        if not last:
            break
        status = str(last.get("status") or "unknown")
        if status == "running" and running_seen_ms is None:
            running_seen_ms = round(elapsed_ms, 1)
        if status in TERMINAL:
            break
        delay = min(max_poll_interval, 0.05 if polls < 3 else max(0.08, delay * 1.5))
    result = last or {"id": job_id, "status": "unknown", "output": "Failed to retrieve status"}
    client_total_ms = round((time.perf_counter() - started) * 1000, 1)
    backend_total_ms = _backend_total_ms(result)
    result["_nexus_timing"] = {
        "path": "supabase-fallback",
        "submit_api_ms": submit_api_ms,
        "first_running_observed_ms": running_seen_ms,
        "backend_total_ms": backend_total_ms,
        "client_total_ms": client_total_ms,
        "result_delivery_ms": round(max(0.0, client_total_ms - backend_total_ms), 1) if backend_total_ms is not None else None,
        "status_polls": polls,
        "status_api_ms": round(api_ms, 1),
    }
    return result
