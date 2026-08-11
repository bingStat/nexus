from __future__ import annotations

import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .common import api_key, atomic_json, fetch_json, load_config, now_iso

DEFAULT_OUTPUT = Path("/var/lib/nexus/ops/health.json")
DEFAULT_STATUS_URL = "http://127.0.0.1:18131/api/status"


def http_check(item: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        payload = fetch_json(str(item["url"]), bearer=str(item.get("bearer") or ""), timeout=float(item.get("timeout", 8)))
        state, error = "online", None
        detail = payload.get("status") if isinstance(payload, dict) else None
    except Exception as exc:
        state, error, detail = "offline", type(exc).__name__, None
    return {
        "id": str(item["id"]), "name": str(item.get("name") or item["id"]),
        "kind": "http", "target": str(item["url"]), "status": state,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "detail": detail, "error": error, "checked_at": now_iso(), "source": "nexus-ops",
    }


def tcp_check(item: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    host, port = str(item["host"]), int(item["port"])
    try:
        with socket.create_connection((host, port), timeout=float(item.get("timeout", 5))):
            state, error = "online", None
    except Exception as exc:
        state, error = "offline", type(exc).__name__
    return {
        "id": str(item["id"]), "name": str(item.get("name") or item["id"]),
        "kind": "tcp", "target": f"{host}:{port}", "status": state,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "error": error, "checked_at": now_iso(), "source": "nexus-ops",
    }


def tailscale_status() -> dict[str, Any]:
    try:
        run = subprocess.run(
            ["tailscale", "status", "--self", "--json"], text=True, capture_output=True, timeout=8, check=True
        )
        payload = __import__("json").loads(run.stdout)
        node = payload.get("Self") or {}
        return {
            "status": "online" if node.get("Online", True) else "offline",
            "dns_name": node.get("DNSName"), "tailscale_ips": node.get("TailscaleIPs") or [],
        }
    except Exception as exc:
        return {"status": "unknown", "error": type(exc).__name__}


def configured_checks(config: dict[str, Any]) -> list[dict[str, Any]]:
    checks = config.get("checks") if isinstance(config.get("checks"), dict) else {}
    work: list[tuple[str, dict[str, Any]]] = []
    for item in checks.get("http", []) or []:
        if isinstance(item, dict) and item.get("id") and item.get("url"):
            work.append(("http", item))
    for item in checks.get("tcp", []) or []:
        if isinstance(item, dict) and item.get("id") and item.get("host") and item.get("port"):
            work.append(("tcp", item))
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(work)))) as pool:
        futures = {pool.submit(http_check if kind == "http" else tcp_check, item): item for kind, item in work}
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda row: str(row.get("id")))


def main() -> None:
    config = load_config()
    output = Path(str(config.get("health_file") or DEFAULT_OUTPUT))
    status_url = str(config.get("status_url") or DEFAULT_STATUS_URL)
    try:
        fleet = fetch_json(status_url, bearer=api_key(), timeout=15)
        source_status, source_error = "online", None
    except Exception as exc:
        fleet, source_status, source_error = {}, "offline", type(exc).__name__
    checks = configured_checks(config)
    payload = {
        "generated_at": now_iso(),
        "node": socket.gethostname(),
        "source_status": source_status,
        "source_error": source_error,
        "ttl_seconds": int(config.get("health_ttl_seconds") or 900),
        "devices": fleet.get("devices", []) if isinstance(fleet, dict) else [],
        "counts": fleet.get("counts", {}) if isinstance(fleet, dict) else {},
        "brokers": fleet.get("brokers", {}) if isinstance(fleet, dict) else {},
        "tailscale": tailscale_status(),
        "checks": checks,
    }
    atomic_json(output, payload)


if __name__ == "__main__":
    main()
