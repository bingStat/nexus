#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUTPUT = Path(os.getenv("NEXUS_HEALTH_OUTPUT", "/var/lib/nexus/health.json"))

HTTP_CHECKS = [
    ("nexus-api", "Nexus API", "http://127.0.0.1:8000/health"),
    ("media", "Jellyfin", "https://media.bings.app/"),
    ("openlist", "OpenList", "https://openlist.bings.app/"),
    ("v152", "V152", "http://192.168.1.1/"),
    ("ax3600", "AX3600", "http://192.168.1.2/"),
    ("n1", "N1", "http://192.168.1.88/"),
]

TCP_CHECKS = [
    ("v152-ssh", "V152 SSH", "192.168.1.1", 22),
    ("v152-telnet", "V152 Telnet", "192.168.1.1", 23),
    ("ax3600-ssh", "AX3600 SSH", "192.168.1.2", 22),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def http_check(check_id: str, name: str, url: str) -> dict:
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": "NexusHealth/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            code = int(response.status)
        status = "online" if code < 500 else "degraded"
        error = None
    except urllib.error.HTTPError as exc:
        code = int(exc.code)
        status = "online" if code in {401, 403} else "degraded"
        error = f"HTTP {code}"
    except Exception as exc:
        code = None
        status = "offline"
        error = type(exc).__name__
    return {
        "id": check_id,
        "name": name,
        "kind": "http",
        "target": url,
        "status": status,
        "http_code": code,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "error": error,
        "checked_at": now_iso(),
    }


def tcp_check(check_id: str, name: str, host: str, port: int) -> dict:
    started = time.monotonic()
    error = None
    try:
        with socket.create_connection((host, port), timeout=5):
            status = "online"
    except Exception as exc:
        status = "offline"
        error = type(exc).__name__
    return {
        "id": check_id,
        "name": name,
        "kind": "tcp",
        "target": f"{host}:{port}",
        "status": status,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "error": error,
        "checked_at": now_iso(),
    }


def tailscale_self() -> dict:
    try:
        result = subprocess.run(
            ["tailscale", "status", "--self", "--json"],
            text=True,
            capture_output=True,
            timeout=8,
            check=True,
        )
        payload = json.loads(result.stdout)
        self_data = payload.get("Self") or {}
        return {
            "status": "online" if self_data.get("Online", True) else "offline",
            "dns_name": self_data.get("DNSName"),
            "tailscale_ips": self_data.get("TailscaleIPs") or [],
        }
    except Exception as exc:
        return {"status": "offline", "error": type(exc).__name__}


def main() -> None:
    checks = [http_check(*item) for item in HTTP_CHECKS]
    checks.extend(tcp_check(*item) for item in TCP_CHECKS)
    payload = {"generated_at": now_iso(), "node": socket.gethostname(), "tailscale": tailscale_self(), "checks": checks}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=OUTPUT.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        temp_name = handle.name
    os.chmod(temp_name, 0o644)
    os.replace(temp_name, OUTPUT)


if __name__ == "__main__":
    main()
