from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from .common import Identity, json_dumps

VERSION = "3.0.1"


def config_path() -> Path:
    return Path(os.getenv("NEXUS_V3_CONFIG", "/etc/nexus-agent/v3.json"))


def load_config() -> dict:
    with config_path().open("r", encoding="utf-8") as fh:
        return json.load(fh)


def request_json(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    body: bytes = b"",
    timeout: int = 20,
) -> tuple[int, dict | None]:
    response = requests.request(method, url, headers=headers or {}, data=body if body else None, timeout=timeout)
    if response.status_code == 204:
        return response.status_code, None
    payload = response.json() if response.text else {}
    return response.status_code, payload


def require_success(code: int, payload: dict | None, operation: str, expected: set[int]) -> None:
    if code in expected:
        return
    detail = payload.get("error") if isinstance(payload, dict) else None
    raise RuntimeError(f"{operation} failed: HTTP {code}: {detail or 'unexpected response'}")


def command_argv(command: str) -> list[str]:
    if os.name == "nt":
        shell = os.getenv("NEXUS_WINDOWS_SHELL", "powershell").strip().lower()
        if shell in {"cmd", "cmd.exe"}:
            return ["cmd.exe", "/d", "/s", "/c", command]
        return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
    return ["/bin/sh", "-c", command]


def main() -> None:
    config = load_config()
    device_id = str(config["device_id"]).strip().lower()
    registry = str(config["registry_url"]).rstrip("/")
    broker = str(config["broker_url"]).rstrip("/")
    identity = Identity(
        Path(config.get("identity_key", "/etc/nexus-agent/identity_ed25519")),
        Path(config.get("identity_public_key", "/etc/nexus-agent/identity_ed25519.pub")),
    )
    agent_id = f"{device_id}:{socket.gethostname()}:{os.getpid()}"

    ssh_public_key = ""
    ssh_public_key_path = config.get("ssh_public_key")
    if ssh_public_key_path:
        path = Path(str(ssh_public_key_path))
        if path.exists():
            ssh_public_key = path.read_text(encoding="utf-8").strip()
    registration = identity.registration_payload(device_id, socket.gethostname(), platform.platform(), VERSION, ssh_public_key)
    response = requests.post(f"{registry}/v3/devices/register", json=registration, timeout=20)
    registration_payload = response.json() if response.text else {}
    require_success(response.status_code, registration_payload, "device registration", {200, 201, 202})
    print(
        json_dumps(
            {
                "event": "agent.registered",
                "device_id": device_id,
                "status": registration_payload.get("status", "unknown"),
                "key_id": identity.key_id,
            }
        ),
        flush=True,
    )

    while True:
        query = urlencode({"device_id": device_id, "agent_id": agent_id, "wait": int(config.get("wait_seconds", 20))})
        path = f"/v3/jobs/claim?{query}"
        headers = identity.sign_headers(device_id, "GET", path, b"")
        try:
            code, job = request_json("GET", broker + path, headers=headers, timeout=int(config.get("request_timeout", 35)))
            if code == 204:
                time.sleep(int(config.get("poll_seconds", 1)))
                continue
            require_success(code, job, "job claim", {200})
            if not job:
                raise RuntimeError("job claim returned an empty body")
            execute_and_complete(config, identity, device_id, broker, job)
        except Exception as exc:
            print(json_dumps({"event": "agent.error", "device_id": device_id, "error": str(exc)[:500]}), flush=True)
            time.sleep(5)


def execute_and_complete(config: dict, identity: Identity, device_id: str, broker: str, job: dict) -> None:
    timeout = max(1, int(job.get("timeout_ms") or 30000) // 1000)
    try:
        proc = subprocess.run(command_argv(str(job["command"])), text=True, capture_output=True, timeout=timeout)
        status = "completed" if proc.returncode == 0 else "failed"
        exit_code = proc.returncode
        output = (proc.stdout + proc.stderr)[-20000:]
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        exit_code = 124
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        output = (stdout + stderr + f"\ncommand timed out after {timeout}s")[-20000:]

    payload = {
        "id": job["id"],
        "status": status,
        "exit_code": exit_code,
        "output": output,
    }
    body = json_dumps(payload).encode("utf-8")
    headers = identity.sign_headers(device_id, "POST", "/v3/jobs/complete", body)
    headers["Content-Type"] = "application/json"
    code, response_payload = request_json(
        "POST",
        f"{broker}/v3/jobs/complete",
        headers=headers,
        body=body,
        timeout=int(config.get("request_timeout", 20)),
    )
    require_success(code, response_payload, "job completion", {200})
    print(
        json_dumps(
            {
                "event": "agent.job_finished",
                "device_id": device_id,
                "job_id": job["id"],
                "status": status,
                "exit_code": exit_code,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
