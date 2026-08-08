from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from .common import Identity, json_dumps

VERSION = "3.0.0"


def config_path() -> Path:
    return Path(os.getenv("NEXUS_V3_CONFIG", "/etc/nexus-agent/v3.json"))


def load_config() -> dict:
    with config_path().open("r", encoding="utf-8") as fh:
        return json.load(fh)


def request_json(method: str, url: str, *, headers: dict | None = None, body: bytes = b"", timeout: int = 20) -> tuple[int, dict | None]:
    response = requests.request(method, url, headers=headers or {}, data=body if body else None, timeout=timeout)
    if response.status_code == 204:
        return response.status_code, None
    payload = response.json() if response.text else {}
    return response.status_code, payload


def main() -> None:
    config = load_config()
    device_id = str(config["device_id"]).strip().lower()
    registry = str(config["registry_url"]).rstrip("/")
    broker = str(config["broker_url"]).rstrip("/")
    identity = Identity(Path(config.get("identity_key", "/etc/nexus-agent/identity_ed25519")), Path(config.get("identity_public_key", "/etc/nexus-agent/identity_ed25519.pub")))
    agent_id = f"{device_id}:{socket.gethostname()}:{os.getpid()}"
    registration = identity.registration_payload(device_id, socket.gethostname(), platform.platform(), VERSION)
    requests.post(f"{registry}/v3/devices/register", json=registration, timeout=20)
    while True:
        query = urlencode({"device_id": device_id, "agent_id": agent_id, "wait": int(config.get("wait_seconds", 20))})
        path = f"/v3/jobs/claim?{query}"
        headers = identity.sign_headers(device_id, "GET", path, b"")
        try:
            code, job = request_json("GET", broker + path, headers=headers, timeout=int(config.get("request_timeout", 35)))
            if code == 204 or not job:
                time.sleep(int(config.get("poll_seconds", 1)))
                continue
            execute_and_complete(config, identity, device_id, broker, job)
        except Exception as exc:
            print(json_dumps({"event": "agent.error", "device_id": device_id, "error": str(exc)[:200]}), flush=True)
            time.sleep(5)


def execute_and_complete(config: dict, identity: Identity, device_id: str, broker: str, job: dict) -> None:
    timeout = max(1, int(job.get("timeout_ms") or 30000) // 1000)
    proc = subprocess.run(["/bin/sh", "-c", str(job["command"])], text=True, capture_output=True, timeout=timeout)
    status = "completed" if proc.returncode == 0 else "failed"
    payload = {
        "id": job["id"],
        "status": status,
        "exit_code": proc.returncode,
        "output": (proc.stdout + proc.stderr)[-20000:],
    }
    body = json_dumps(payload).encode("utf-8")
    headers = identity.sign_headers(device_id, "POST", "/v3/jobs/complete", body)
    headers["Content-Type"] = "application/json"
    requests.post(f"{broker}/v3/jobs/complete", headers=headers, data=body, timeout=int(config.get("request_timeout", 20)))


if __name__ == "__main__":
    main()
