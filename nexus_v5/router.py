from __future__ import annotations

import http.client
import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class Router:
    def __init__(self, routes_file: str | None = None, token_file: str | None = None):
        routes_path = Path(routes_file or os.getenv("NEXUS_V5_ROUTES", "/etc/nexus-v5/routes.json"))
        token_path = Path(token_file or os.getenv("NEXUS_V5_TOKEN_FILE", "/etc/nexus-v5/token"))
        self.routes = json.loads(routes_path.read_text(encoding="utf-8"))
        self.token = token_path.read_text(encoding="utf-8").strip()
        self.devices = {str(k).lower(): v for k, v in self.routes.get("devices", {}).items()}
        self.aliases = {str(k).lower(): str(v).lower() for k, v in self.routes.get("aliases", {}).items()}
        self.ssh_key = os.getenv("NEXUS_V5_SSH_KEY", "/home/ubuntu/.ssh/id_ed25519_oracle")
        self.known_hosts = os.getenv("NEXUS_V5_KNOWN_HOSTS", "/etc/nexus-v5/known_hosts")
        Path(self.known_hosts).parent.mkdir(parents=True, exist_ok=True)
        Path(self.known_hosts).touch(exist_ok=True)

    def resolve(self, device: str) -> tuple[str, dict[str, Any]]:
        name = str(device).strip().lower()
        name = self.aliases.get(name, name)
        route = self.devices.get(name)
        if not route:
            raise ValueError(f"unknown Nexus device: {name}")
        return name, route

    @staticmethod
    def _local(command: str, timeout_ms: int) -> dict[str, Any]:
        started = time.perf_counter()
        proc = subprocess.run(["/bin/sh", "-c", command], capture_output=True, text=True,
                              timeout=max(1, timeout_ms / 1000))
        output = (proc.stdout + proc.stderr)[-20000:]
        return {
            "status": "completed" if proc.returncode == 0 else "failed",
            "transport": "v5-local",
            "exit_code": proc.returncode,
            "output": output,
            "client_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    def _http(self, endpoint: str, path: str, payload: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
        parsed = urlparse(endpoint)
        if parsed.scheme != "http":
            raise RuntimeError("v5 direct endpoints must use tailnet HTTP")
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=0.35)
        started = time.perf_counter()
        conn.connect()
        if conn.sock:
            conn.sock.settimeout(max(2.0, timeout_ms / 1000 + 1.0))
        body = json.dumps(payload, separators=(",", ":"))
        conn.request("POST", path, body=body, headers={
            "Content-Type": "application/json",
            "X-Nexus-Key": self.token,
        })
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
        conn.close()
        data = json.loads(raw or "{}")
        if response.status != 200:
            raise RuntimeError(str(data.get("error") or f"HTTP {response.status}"))
        data["client_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return data

    def _ssh_argv(self, target: str, command: str) -> list[str]:
        return [
            "ssh", "-i", self.ssh_key,
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=2",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={self.known_hosts}",
            "-o", "ControlMaster=auto", "-o", "ControlPersist=600",
            "-o", "ControlPath=/tmp/nexus-v5-%C", target, command,
        ]

    def _ssh(self, device: str, route: dict[str, Any], command: str, timeout_ms: int) -> dict[str, Any]:
        target = str(route.get("ssh") or "")
        if not target:
            raise RuntimeError(f"SSH route unavailable for {device}")
        started = time.perf_counter()
        proc = subprocess.run(self._ssh_argv(target, command), capture_output=True, text=True,
                              timeout=max(3, timeout_ms / 1000 + 2))
        output = (proc.stdout + proc.stderr)[-20000:]
        return {
            "status": "completed" if proc.returncode == 0 else "failed",
            "device_id": device,
            "transport": "v5-ssh",
            "exit_code": proc.returncode,
            "output": output,
            "client_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    @staticmethod
    def _rescue_command(route: dict[str, Any]) -> str:
        configured = str(route.get("rescue") or "").strip()
        if configured:
            return configured
        return f"systemctl restart {str(route.get('worker_service') or 'nexus-v5-worker.service')}"

    def _restart_worker_async(self, route: dict[str, Any]) -> None:
        target = str(route.get("ssh") or "")
        if not target:
            return
        def run() -> None:
            try:
                subprocess.run(self._ssh_argv(target, self._rescue_command(route)),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True, name="nexus-v5-rescue").start()

    def execute(self, device: str, command: str, timeout_ms: int = 30000) -> dict[str, Any]:
        name, route = self.resolve(device)
        mode = str(route.get("mode") or "direct")
        if mode == "local":
            result = self._local(command, timeout_ms)
            result["device_id"] = name
            return result
        if mode == "ssh":
            return self._ssh(name, route, command, timeout_ms)
        if mode != "direct":
            raise RuntimeError(f"unsupported route mode: {mode}")
        endpoint = str(route.get("endpoint") or "").rstrip("/")
        try:
            return self._http(endpoint, "/v5/execute", {"command": command, "timeout_ms": timeout_ms}, timeout_ms)
        except Exception as direct_error:
            result = self._ssh(name, route, command, timeout_ms)
            result["fallback_from"] = "v5-direct"
            result["direct_error"] = str(direct_error)[:200]
            self._restart_worker_async(route)
            return result

    def runtime(self, device: str, operation: str, input_data: dict[str, Any], timeout_ms: int = 30000) -> dict[str, Any]:
        name, route = self.resolve(device)
        if str(route.get("mode") or "") != "direct":
            raise RuntimeError(f"{name} is SSH-only and has no DevSpace runtime")
        endpoint = str(route.get("endpoint") or "").rstrip("/")
        payload = {"operation": operation, "input": input_data, "timeout_ms": timeout_ms}
        try:
            return self._http(endpoint, "/v5/runtime", payload, timeout_ms)
        except Exception:
            target = str(route.get("ssh") or "")
            if not target:
                raise
            subprocess.run(self._ssh_argv(target, self._rescue_command(route)),
                           capture_output=True, text=True, timeout=8)
            return self._http(endpoint, "/v5/runtime", payload, timeout_ms)

    def list_devices(self) -> list[dict[str, Any]]:
        return [
            {"device_id": name, "mode": route.get("mode"), "devspace": bool(route.get("devspace"))}
            for name, route in sorted(self.devices.items())
        ]

    def _health_one(self, name: str, route: dict[str, Any]) -> dict[str, Any]:
        mode = str(route.get("mode") or "direct")
        if mode == "local":
            return {"device_id": name, "status": "online", "transport": "local"}
        if mode == "ssh":
            try:
                result = self._ssh(name, route, "true", 2000)
                return {"device_id": name, "status": "online" if result["exit_code"] == 0 else "offline", "transport": "ssh"}
            except Exception as exc:
                return {"device_id": name, "status": "offline", "transport": "ssh", "error": str(exc)[:120]}
        endpoint = str(route.get("endpoint") or "").rstrip("/")
        parsed = urlparse(endpoint)
        try:
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=0.7)
            conn.request("GET", "/v5/health")
            response = conn.getresponse()
            data = json.loads(response.read().decode() or "{}")
            conn.close()
            return {"device_id": name, "status": "online" if response.status == 200 else "offline",
                    "transport": "direct", "devspace": bool(data.get("devspace"))}
        except Exception as exc:
            return {"device_id": name, "status": "offline", "transport": "direct", "error": str(exc)[:120]}

    def health_all(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(self.devices)))) as pool:
            futures = {pool.submit(self._health_one, n, r): n for n, r in self.devices.items()}
            for future in as_completed(futures):
                results.append(future.result())
        return sorted(results, key=lambda row: row["device_id"])
