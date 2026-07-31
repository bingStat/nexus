from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

AGENT_VERSION = "2.1.0"
TERMINAL = {"completed", "failed", "timeout", "expired", "cancelled"}


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except (TypeError, ValueError):
        return None


def load_config() -> dict[str, Any]:
    path = Path(os.getenv("NEXUS_CONFIG_FILE", Path.home() / ".nexus-agent" / "config.json"))
    data: dict[str, Any] = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    aliases = data.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [item.strip() for item in aliases.split(",") if item.strip()]
    return {
        "api_url": os.getenv("NEXUS_API_URL") or data.get("api_url"),
        "api_token": os.getenv("NEXUS_API_TOKEN") or os.getenv("NEXUS_API_KEY") or data.get("api_token"),
        "device_token": os.getenv("NEXUS_DEVICE_TOKEN") or data.get("device_token"),
        "strict_rpc": str(os.getenv("NEXUS_STRICT_RPC", data.get("strict_rpc", True))).lower() not in {"0", "false", "no", "off"},
        "device_id": os.getenv("NEXUS_DEVICE_ID") or data.get("device_id") or socket.gethostname().lower(),
        "device_name": os.getenv("NEXUS_DEVICE_NAME") or data.get("device_name") or socket.gethostname(),
        "aliases": aliases,
        "poll_seconds": float(os.getenv("NEXUS_POLL_SECONDS", data.get("poll_seconds", 2))),
        "heartbeat_seconds": float(os.getenv("NEXUS_HEARTBEAT_SECONDS", data.get("heartbeat_seconds", 15))),
        "lease_seconds": int(os.getenv("NEXUS_LEASE_SECONDS", data.get("lease_seconds", 90))),
        "max_workers": int(os.getenv("NEXUS_MAX_WORKERS", data.get("max_workers", 2))),
        "lock_port": int(os.getenv("NEXUS_LOCK_PORT", data.get("lock_port", 49158 if os.name == "nt" else 49159))),
    }


def capabilities() -> dict[str, bool]:
    service_manager = bool(shutil.which("systemctl") or shutil.which("service"))
    if os.name == "nt":
        service_manager = True
    return {
        "shell": True,
        "ssh": shutil.which("ssh") is not None,
        "scp": shutil.which("scp") is not None,
        "rsync": shutil.which("rsync") is not None,
        "ping": shutil.which("ping") is not None,
        "service_manager": service_manager,
        "docker": shutil.which("docker") is not None,
        "powershell": shutil.which("powershell") is not None or shutil.which("pwsh") is not None,
    }


class NexusAPI:
    def __init__(self, config: dict[str, Any]):
        api_url = str(config.get("api_url") or "").rstrip("/")
        token = str(config.get("api_token") or "")
        if not api_url or not token:
            raise RuntimeError("NEXUS_API_URL and NEXUS_API_TOKEN are required")
        self.base_url = api_url
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "apikey": token,
            "Content-Type": "application/json",
        })

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        response = self.session.request(method, f"{self.base_url}/{path.lstrip('/')}\", timeout=kwargs.pop("timeout", 10), **kwargs)
        response.raise_for_status()
        return response

    def heartbeat(self, config: dict[str, Any]) -> None:
        payload = {
            "device_id": config["device_id"],
            "name": config["device_name"],
            "status": "online",
            "last_seen": iso_now(),
            "platform": "windows" if os.name == "nt" else "posix",
            "agent_version": AGENT_VERSION,
            "capabilities": capabilities(),
        }
        try:
            self.request(
                "POST",
                "rpc/heartbeat_agent",
                json={
                    "p_device_id": config["device_id"],
                    "p_device_token": config.get("device_token"),
                    "p_name": config["device_name"],
                    "p_platform": payload["platform"],
                    "p_agent_version": AGENT_VERSION,
                    "p_capabilities": payload["capabilities"],
                },
            )
            return
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code not in {400, 404}:
                raise
            if config["strict_rpc"]:
                raise RuntimeError("heartbeat_agent RPC is required") from exc
        self.request("POST", "devices", json=payload, headers={**self.session.headers, "Prefer": "resolution=merge-duplicates"})

    def audit(self, event_type: str, config: dict[str, Any], command_id: str | None = None, details: dict[str, Any] | None = None) -> None:
        payload = {
            "p_device_id": config["device_id"],
            "p_device_token": config.get("device_token"),
            "p_event_type": event_type,
            "p_command_id": command_id,
            "p_details": details or {},
        }
        try:
            self.request("POST", "rpc/append_agent_audit", json=payload)
            return
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code not in {400, 404}:
                return
            if config["strict_rpc"]:
                return
        try:
            self.request(
                "POST",
                "audit_events",
                json={
                    "event_type": event_type,
                    "actor": f"agent:{config['device_id']}",
                    "device_id": config["device_id"],
                    "command_id": command_id,
                    "details": details or {},
                },
                headers={**self.session.headers, "Prefer": "return=minimal"},
            )
        except requests.RequestException as exc:
            print(f"audit fallback failed: {exc}", flush=True)

    def claim(self, config: dict[str, Any], lease_owner: str) -> dict[str, Any] | None:
        aliases = sorted({
            str(config["device_id"]),
            str(config["device_name"]),
            socket.gethostname(),
            socket.gethostname().lower(),
            "all",
            "broadcast",
            *[str(item) for item in config.get("aliases", [])],
        })
        body = {
            "p_device_id": config["device_id"],
            "p_aliases": aliases,
            "p_lease_owner": lease_owner,
            "p_lease_seconds": config["lease_seconds"],
            "p_device_token": config.get("device_token"),
        }
        try:
            data = self.request("POST", "rpc/claim_next_command", json=body).json()
            return data[0] if data else None
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code not in {400, 404}:
                raise
            if config["strict_rpc"]:
                raise RuntimeError("claim_next_command RPC is required") from exc
        terms = ",".join(f"target_device.ilike.{alias}" for alias in aliases)
        params = {"status": "eq.pending", "or": f"({terms})", "order": "created_at.asc", "limit": "1", "select": "*"}
        data = self.request("GET", "commands", params=params).json()
        if not data:
            return None
        task = data[0]
        lease_until = datetime.fromtimestamp(time.time() + config["lease_seconds"], UTC).isoformat()
        patch = {
            "status": "running",
            "lease_owner": lease_owner,
            "lease_expires_at": lease_until,
            "claimed_at": iso_now(),
            "started_at": iso_now(),
        }
        response = self.request(
            "PATCH",
            "commands",
            params={"id": f"eq.{task['id']}", "status": "eq.pending"},
            json=patch,
            headers={**self.session.headers, "Prefer": "return=representation"},
        )
        claimed = response.json()
        return claimed[0] if claimed else None

    def renew_lease(self, command_id: str, lease_owner: str, lease_seconds: int, config: dict[str, Any]) -> None:
        try:
            self.request(
                "POST",
                "rpc/renew_command_lease",
                json={"p_command_id": command_id, "p_lease_owner": lease_owner, "p_lease_seconds": lease_seconds, "p_device_id": config["device_id"], "p_device_token": config.get("device_token")},
            )
            return
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code not in {400, 404}:
                raise
            if config["strict_rpc"]:
                raise RuntimeError("renew_command_lease RPC is required") from exc
        lease_until = datetime.fromtimestamp(time.time() + lease_seconds, UTC).isoformat()
        self.request(
            "PATCH",
            "commands",
            params={"id": f"eq.{command_id}", "lease_owner": f"eq.{lease_owner}"},
            json={"lease_expires_at": lease_until},
        )

    def finish(self, task: dict[str, Any], lease_owner: str, status: str, stdout: str, stderr: str, exit_code: int | None, config: dict[str, Any]) -> None:
        combined = stdout
        if stderr:
            combined = f"{combined}\n[stderr]\n{stderr}" if combined else f"[stderr]\n{stderr}"
        payload = {
            "status": status,
            "stdout": stdout[-1_000_000:],
            "stderr": stderr[-1_000_000:],
            "output": combined[-1_000_000:],
            "exit_code": exit_code,
            "completed_at": iso_now(),
            "lease_owner": None,
            "lease_expires_at": None,
        }
        try:
            self.request(
                "POST",
                "rpc/complete_command",
                json={
                    "p_command_id": task["id"],
                    "p_device_id": config["device_id"],
                    "p_device_token": config.get("device_token"),
                    "p_lease_owner": lease_owner,
                    "p_status": status,
                    "p_stdout": payload["stdout"],
                    "p_stderr": payload["stderr"],
                    "p_exit_code": exit_code,
                },
            )
            return
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code not in {400, 404}:
                raise
            if config["strict_rpc"]:
                raise RuntimeError("complete_command RPC is required") from exc
        self.request(
            "PATCH",
            "commands",
            params={"id": f"eq.{task['id']}", "lease_owner": f"eq.{lease_owner}"},
            json=payload,
        )


def acquire_single_instance_lock(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as exc:
        raise RuntimeError("Another Nexus Agent instance is already running") from exc
    return sock


def command_argv(command: str) -> list[str]:
    if os.name == "nt":
        shell = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
    return ["/bin/sh", "-lc", command]


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.kill()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()


def execute_task(api: NexusAPI, config: dict[str, Any], task: dict[str, Any], lease_owner: str) -> None:
    task_id = str(task["id"])
    expires = parse_time(task.get("expires_at"))
    if expires and expires <= utc_now():
        api.finish(task, lease_owner, "expired", "", "Task expired before execution", None, config)
        api.audit("command.expired", config, task_id)
        return
    hop_count = int(task.get("hop_count") or 0)
    max_hops = int(task.get("max_hops") or 2)
    if hop_count > max_hops:
        api.finish(task, lease_owner, "failed", "", f"Route hop limit exceeded: {hop_count}>{max_hops}", 126, config)
        api.audit("command.hop_limit_rejected", config, task_id, {"hop_count": hop_count, "max_hops": max_hops})
        return
    command = str(task.get("command") or "").strip()
    if not command:
        api.finish(task, lease_owner, "failed", "", "Empty command", 127, config)
        return
    api.audit("command.started", config, task_id, {"action": task.get("action"), "hop_count": hop_count})
    timeout_seconds = max(1.0, float(task.get("timeout_ms") or 30_000) / 1000.0)
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name != "nt":
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command_argv(command), **kwargs)
    stop_renewal = threading.Event()

    def renew() -> None:
        interval = max(10, config["lease_seconds"] // 3)
        while not stop_renewal.wait(interval):
            try:
                api.renew_lease(task_id, lease_owner, config["lease_seconds"], config)
            except requests.RequestException as exc:
                print(f"lease renewal failed for {task_id}: {exc}", flush=True)

    renewer = threading.Thread(target=renew, daemon=True)
    renewer.start()
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        exit_code = process.returncode
        status = "completed" if exit_code == 0 else "failed"
    except subprocess.TimeoutExpired:
        stop_process(process)
        stdout, stderr = process.communicate()
        stderr = f"{stderr}\nCommand timed out after {timeout_seconds:.1f}s".strip()
        exit_code = 124
        status = "timeout"
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        stop_process(process)
        stdout, stderr, exit_code, status = "", str(exc), 125, "failed"
    finally:
        stop_renewal.set()
        renewer.join(timeout=1)
    api.finish(task, lease_owner, status, stdout.strip(), stderr.strip(), exit_code, config)
    api.audit("command.finished", config, task_id, {"status": status, "exit_code": exit_code})


def main() -> None:
    config = load_config()
    _instance_lock = acquire_single_instance_lock(config["lock_port"])
    api = NexusAPI(config)
    lease_owner = f"{config['device_id']}:{uuid.uuid4()}"
    executor = ThreadPoolExecutor(max_workers=config["max_workers"])
    last_heartbeat = 0.0
    print(f"Nexus Agent {AGENT_VERSION} starting as {config['device_id']}", flush=True)
    while True:
        now = time.monotonic()
        if now - last_heartbeat >= config["heartbeat_seconds"]:
            try:
                api.heartbeat(config)
                last_heartbeat = now
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                print(f"heartbeat failed: {exc}", flush=True)
        try:
            task = api.claim(config, lease_owner)
            if task:
                executor.submit(execute_task, api, config, task, lease_owner)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"poll failed: {exc}", flush=True)
        time.sleep(config["poll_seconds"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
