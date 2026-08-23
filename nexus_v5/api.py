from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import VERSION
from .router import Router


def api_key() -> str:
    value = os.getenv("NEXUS_CHATGPT_API_KEY", "")
    if not value:
        raise RuntimeError("NEXUS_CHATGPT_API_KEY is required")
    return value


def public_base_url() -> str:
    return os.getenv("NEXUS_CHATGPT_PUBLIC_BASE_URL", "http://127.0.0.1:18131").rstrip("/")


def openapi_document() -> dict[str, Any]:
    command_schema = {
        "type": "object", "additionalProperties": False,
        "required": ["device_id", "command"],
        "properties": {
            "device_id": {"type": "string"},
            "command": {"type": "string"},
            "timeout_ms": {"type": "integer", "default": 30000, "minimum": 1000, "maximum": 86400000},
        },
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Nexus",
            "version": VERSION,
            "description": "Minimal multi-device control plane. ChatGPT chooses the logical device; Nexus uses its cached route without per-command probing.",
        },
        "servers": [{"url": public_base_url()}],
        "security": [{"BearerAuth": []}],
        "paths": {
            "/api/devices": {"get": {"operationId": "listDevices", "summary": "List configured Nexus devices", "responses": {"200": {"description": "Device list"}}}},
            "/api/devices/{device_id}": {"get": {"operationId": "getDevice", "summary": "Get one Nexus device", "parameters": [{"name": "device_id", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "Device"}}}},
            "/api/self-test": {"get": {"operationId": "selfTest", "summary": "Check Nexus v5 route configuration and device reachability", "responses": {"200": {"description": "Self-test"}}}},
            "/api/status": {"get": {"operationId": "getFleetStatus", "summary": "Get explicit fleet health", "responses": {"200": {"description": "Fleet status"}}}},
            "/api/commands": {"post": {"operationId": "executeCommand", "summary": "Execute one command on one logical device", "requestBody": {"required": True, "content": {"application/json": {"schema": command_schema}}}, "responses": {"200": {"description": "Command result"}}}},
            "/api/commands/batch": {"post": {"operationId": "executeBatch", "summary": "Execute up to 16 commands concurrently", "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["jobs"], "properties": {"jobs": {"type": "array", "minItems": 1, "maxItems": 16, "items": command_schema}}}}}}, "responses": {"200": {"description": "Batch results"}}}},
            "/api/runtime": {"post": {"operationId": "executeRuntimeOperation", "summary": "Run a DevSpace workspace operation on a direct-capable device", "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["device_id", "operation", "input"], "properties": {"device_id": {"type": "string"}, "operation": {"type": "string", "enum": ["workspace.open", "workspace.read", "workspace.apply_patch", "workspace.exec", "workspace.write_stdin"]}, "input": {"type": "object"}, "timeout_ms": {"type": "integer", "default": 30000}}}}}}, "responses": {"200": {"description": "DevSpace result"}}}},
        },
        "components": {"securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer"}}},
    }


class Service:
    def __init__(self):
        self.router = Router()

    def list_devices(self) -> dict[str, Any]:
        return {"version": VERSION, "devices": self.router.list_devices()}

    def device(self, device_id: str) -> dict[str, Any]:
        name, route = self.router.resolve(device_id)
        return {"device_id": name, "mode": route.get("mode"), "devspace": bool(route.get("devspace"))}

    def status(self) -> dict[str, Any]:
        devices = self.router.health_all()
        return {
            "version": VERSION,
            "status": "ok" if all(row["status"] == "online" for row in devices) else "degraded",
            "devices": devices,
        }

    def execute_batch(self, jobs: list[dict[str, Any]]) -> dict[str, Any]:
        if not 1 <= len(jobs) <= 16:
            raise ValueError("jobs must contain 1 to 16 items")
        results: list[dict[str, Any]] = [{} for _ in jobs]
        with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
            futures = {
                pool.submit(self.router.execute, str(job["device_id"]), str(job["command"]), int(job.get("timeout_ms") or 30000)): index
                for index, job in enumerate(jobs)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as exc:
                    results[index] = {"status": "failed", "error": str(exc)[:500]}
        return {"results": results}


def make_handler(service: Service):
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

        def require_auth(self) -> None:
            header = self.headers.get("Authorization") or ""
            if not header.startswith("Bearer ") or header[7:].strip() != api_key():
                raise PermissionError("unauthorized")

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/health":
                    return self.send_json(200, {"status": "ok", "service": "nexus-v5", "version": VERSION})
                if parsed.path == "/openapi.json":
                    return self.send_json(200, openapi_document())
                self.require_auth()
                if parsed.path == "/api/devices":
                    _ = parse_qs(parsed.query)
                    return self.send_json(200, service.list_devices())
                if parsed.path.startswith("/api/devices/"):
                    return self.send_json(200, service.device(parsed.path.rsplit("/", 1)[-1]))
                if parsed.path in {"/api/status", "/api/self-test"}:
                    return self.send_json(200, service.status())
                return self.send_json(404, {"error": "not_found"})
            except PermissionError as exc:
                return self.send_json(401, {"error": str(exc)})
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            except Exception as exc:
                return self.send_json(502, {"error": str(exc)[:500]})

        def do_POST(self) -> None:
            try:
                self.require_auth()
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                payload = json.loads(raw.decode() or "{}")
                if self.path == "/api/commands":
                    return self.send_json(200, service.router.execute(
                        str(payload["device_id"]), str(payload["command"]), int(payload.get("timeout_ms") or 30000)))
                if self.path == "/api/commands/batch":
                    return self.send_json(200, service.execute_batch(payload["jobs"]))
                if self.path == "/api/runtime":
                    return self.send_json(200, service.router.runtime(
                        str(payload["device_id"]), str(payload["operation"]),
                        payload.get("input") if isinstance(payload.get("input"), dict) else {},
                        int(payload.get("timeout_ms") or 30000)))
                return self.send_json(404, {"error": "not_found"})
            except PermissionError as exc:
                return self.send_json(401, {"error": str(exc)})
            except (KeyError, ValueError) as exc:
                return self.send_json(400, {"error": str(exc)})
            except Exception as exc:
                return self.send_json(502, {"status": "failed", "error": str(exc)[:500]})

    return Handler


def main() -> None:
    bind = os.getenv("NEXUS_V5_API_BIND", "127.0.0.1")
    port = int(os.getenv("NEXUS_V5_API_PORT", "18131"))
    service = Service()
    ThreadingHTTPServer((bind, port), make_handler(service)).serve_forever(poll_interval=0.25)


if __name__ == "__main__":
    main()
