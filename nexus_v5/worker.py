from __future__ import annotations

import argparse
import json
import locale
import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from nexus_v3.devspace_runtime import DevSpaceRuntime

from . import VERSION


def command_argv(command: str) -> list[str]:
    if os.name == "nt":
        return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
    return ["/bin/sh", "-c", command]


def decode(data: bytes | None) -> str:
    if not data:
        return ""
    for encoding in ("utf-8", locale.getpreferredencoding(False), "cp1252"):
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            pass
    return data.decode("utf-8", errors="replace")


class Worker:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.device_id = str(config["device_id"]).strip().lower()
        self.token = Path(str(config["token_file"])).read_text(encoding="utf-8").strip()
        self.devspace: DevSpaceRuntime | None = None
        if config.get("devspace"):
            try:
                self.devspace = DevSpaceRuntime(config)
                self.devspace.info()
            except Exception:
                self.devspace = None

    def execute(self, command: str, timeout_ms: int) -> dict[str, Any]:
        started = time.perf_counter()
        proc = subprocess.run(
            command_argv(command),
            text=False,
            capture_output=True,
            timeout=max(1, int(timeout_ms) / 1000),
        )
        output = (decode(proc.stdout) + decode(proc.stderr))[-20000:]
        return {
            "status": "completed" if proc.returncode == 0 else "failed",
            "device_id": self.device_id,
            "transport": "v5-direct",
            "exit_code": proc.returncode,
            "output": output,
            "execution_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    def runtime(self, operation: str, input_data: dict[str, Any]) -> dict[str, Any]:
        if not self.devspace:
            raise RuntimeError("DevSpace runtime is not available on this device")
        return {
            "status": "completed",
            "device_id": self.device_id,
            "transport": "v5-direct-devspace",
            "result": self.devspace.call(operation, input_data),
        }


def make_handler(worker: Worker):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def send_json(self, code: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def authorized(self) -> bool:
            return self.headers.get("X-Nexus-Key", "") == worker.token

        def do_GET(self) -> None:
            if self.path == "/v5/health":
                return self.send_json(200, {
                    "status": "ok",
                    "version": VERSION,
                    "device_id": worker.device_id,
                    "devspace": bool(worker.devspace),
                })
            return self.send_json(404, {"error": "not_found"})

        def do_POST(self) -> None:
            if not self.authorized():
                return self.send_json(401, {"error": "unauthorized"})
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                payload = json.loads(raw.decode() or "{}")
                if self.path == "/v5/execute":
                    return self.send_json(200, worker.execute(
                        str(payload.get("command") or ""),
                        int(payload.get("timeout_ms") or 30000),
                    ))
                if self.path == "/v5/runtime":
                    return self.send_json(200, worker.runtime(
                        str(payload.get("operation") or ""),
                        payload.get("input") if isinstance(payload.get("input"), dict) else {},
                    ))
                return self.send_json(404, {"error": "not_found"})
            except subprocess.TimeoutExpired:
                return self.send_json(504, {"status": "failed", "error": "command_timeout"})
            except Exception as exc:
                return self.send_json(500, {"status": "failed", "error": str(exc)[:500]})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.getenv("NEXUS_V5_CONFIG", "/etc/nexus-v5/worker.json"))
    args = parser.parse_args()
    with open(args.config, "r", encoding="utf-8") as fh:
        config = json.load(fh)
    worker = Worker(config)
    server = ThreadingHTTPServer(
        (str(config.get("bind") or "127.0.0.1"), int(config.get("port") or 18505)),
        make_handler(worker),
    )
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        if worker.devspace:
            worker.devspace.close()


if __name__ == "__main__":
    main()
