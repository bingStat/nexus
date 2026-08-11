#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def load_env(path: str) -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def request(method: str, url: str, key: str) -> tuple[int, dict]:
    req = Request(url, data=b"{}" if method == "POST" else None, method=method)
    req.add_header("X-Nexus-Admin-Key", key)
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"error": raw[:200]}
        return exc.code, payload


def main() -> int:
    load_env(os.getenv("NEXUS_V3_ENV_FILE", "/etc/nexus-v3.env"))
    key = os.getenv("NEXUS_V3_ADMIN_KEY", "")
    registry = os.getenv("NEXUS_V3_REGISTRY_URL", "http://127.0.0.1:18101").rstrip("/")
    if not key:
        print("NEXUS_V3_ADMIN_KEY is unavailable", file=sys.stderr)
        return 2
    devices = sys.argv[1:] or ["oracle", "thinkcenter", "n1"]
    failed = False
    for device in devices:
        code, payload = request("POST", f"{registry}/v3/admin/devices/{device}/approve", key)
        status = payload.get("status") if isinstance(payload, dict) else None
        key_id = payload.get("key_id") if isinstance(payload, dict) else None
        print(json.dumps({"device_id": device, "http_status": code, "status": status, "key_id": key_id}, ensure_ascii=False))
        if code not in {200, 201} or status != "approved":
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
