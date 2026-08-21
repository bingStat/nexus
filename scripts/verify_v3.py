#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TERMINAL = {"completed", "failed", "timeout"}


def load_env(path: str) -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def request(method: str, url: str, key: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    req = Request(url, data=data, method=method)
    req.add_header("X-Nexus-Admin-Key", key)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"error": raw[:200]}
        return exc.code, payload


def broker_for(device: str) -> str:
    if device in {"thinkcenter", "n1", "ax3600"}:
        return os.getenv("NEXUS_V3_CN_BROKER_URL", "http://100.86.0.66:18120").rstrip("/")
    return os.getenv("NEXUS_V3_EU_BROKER_URL", "http://127.0.0.1:18102").rstrip("/")


def verify_device(device: str, key: str) -> dict:
    broker = broker_for(device)
    marker = f"nexus-v3-{device}-ok"
    code, job = request("POST", f"{broker}/v3/jobs", key, {
        "target_device": device,
        "command": f"printf {marker}",
        "timeout_ms": 30000,
    })
    if code != 201 or not job.get("id"):
        return {"device_id": device, "ok": False, "stage": "submit", "http_status": code, "response": job}
    job_id = job["id"]
    deadline = time.time() + 75
    current = job
    while time.time() < deadline:
        time.sleep(3)
        query = urlencode({"id": job_id})
        code, current = request("GET", f"{broker}/v3/jobs?{query}", key)
        if code == 200 and current.get("status") in TERMINAL:
            break
    output = str(current.get("output") or "").strip()
    ok = current.get("status") == "completed" and int(current.get("exit_code") or 0) == 0 and marker in output
    return {
        "device_id": device,
        "ok": ok,
        "job_id": job_id,
        "status": current.get("status"),
        "exit_code": current.get("exit_code"),
        "lease_owner": current.get("lease_owner"),
        "output": output[:200],
        "broker": broker,
    }


def main() -> int:
    load_env(os.getenv("NEXUS_V3_ENV_FILE", "/etc/nexus-v3.env"))
    key = os.getenv("NEXUS_V3_ADMIN_KEY", "")
    if not key:
        print("NEXUS_V3_ADMIN_KEY is unavailable", file=sys.stderr)
        return 2
    devices = sys.argv[1:] or ["oracle", "thinkcenter", "n1"]
    results = [verify_device(device, key) for device in devices]
    for result in results:
        print(json.dumps(result, ensure_ascii=False))
    return 0 if all(result["ok"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
