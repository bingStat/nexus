from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .remote_control import execute_command, get_device, get_job, list_devices, submit_operation

VERSION = "3.1.0"


def chatgpt_api_key() -> str:
    value = os.getenv("NEXUS_CHATGPT_API_KEY", "")
    if not value:
        raise RuntimeError("NEXUS_CHATGPT_API_KEY is required")
    return value


def public_base_url() -> str:
    return os.getenv("NEXUS_CHATGPT_PUBLIC_BASE_URL", "http://127.0.0.1:18131").rstrip("/")


def openapi_document() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Nexus Distributed DevSpace API",
            "version": VERSION,
            "description": (
                "Nexus fleet control plane. Shell commands and structured DevSpace workspace operations always "
                "target one explicitly named device; workspace operations are never redirected to a substitute device."
            ),
        },
        "servers": [{"url": public_base_url()}],
        "security": [{"BearerAuth": []}],
        "paths": {
            "/api/devices": {
                "get": {
                    "operationId": "listDevices",
                    "summary": "List Nexus devices and runtime capabilities",
                    "parameters": [
                        {"name": "status", "in": "query", "required": False, "schema": {"type": "string", "default": "approved"}}
                    ],
                    "responses": {"200": {"description": "Device list"}},
                }
            },
            "/api/devices/{device_id}": {
                "get": {
                    "operationId": "getDevice",
                    "summary": "Get one Nexus device and runtime capabilities",
                    "parameters": [
                        {"name": "device_id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "Device identity"}},
                }
            },
            "/api/commands": {
                "post": {
                    "operationId": "executeCommand",
                    "summary": "Execute one shell command on one named Nexus device",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["device_id", "command"],
                                    "properties": {
                                        "device_id": {"type": "string"},
                                        "command": {"type": "string"},
                                        "timeout_ms": {"type": "integer", "default": 30000, "minimum": 1000, "maximum": 86400000},
                                        "wait_seconds": {"type": "integer", "default": 20, "minimum": 0, "maximum": 120},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "Job result or accepted job"}},
                }
            },
            "/api/runtime": {
                "post": {
                    "operationId": "executeRuntimeOperation",
                    "summary": "Run a structured DevSpace workspace operation on one named Nexus device",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["device_id", "operation", "input"],
                                    "properties": {
                                        "device_id": {"type": "string"},
                                        "operation": {
                                            "type": "string",
                                            "enum": [
                                                "workspace.open",
                                                "workspace.read",
                                                "workspace.apply_patch",
                                                "workspace.exec",
                                                "workspace.write_stdin"
                                            ],
                                        },
                                        "input": {"type": "object"},
                                        "timeout_ms": {"type": "integer", "default": 30000, "minimum": 1000, "maximum": 86400000},
                                        "wait_seconds": {"type": "integer", "default": 20, "minimum": 0, "maximum": 120},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "Workspace job result or accepted job"},
                        "502": {"description": "Target does not expose the DevSpace runtime or routing failed"},
                    },
                }
            },
            "/api/jobs/{region}/{job_id}": {
                "get": {
                    "operationId": "getJob",
                    "summary": "Read a Nexus job from an EU or CN Broker",
                    "parameters": [
                        {"name": "region", "in": "path", "required": True, "schema": {"type": "string", "enum": ["eu", "cn"]}},
                        {"name": "job_id", "in": "path", "required": True, "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"description": "Job status and structured result"}},
                }
            },
        },
        "components": {
            "schemas": {},
            "securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer"}},
        },
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def require_auth(self) -> None:
        expected = chatgpt_api_key()
        header = self.headers.get("Authorization") or ""
        prefix = "Bearer "
        if not header.startswith(prefix) or header[len(prefix):].strip() != expected:
            raise PermissionError("unauthorized")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/health":
                return self.send_json(200, {"status": "ok", "service": "nexus-chatgpt-remote", "version": VERSION})
            if parsed.path == "/openapi.json":
                return self.send_json(200, openapi_document())
            self.require_auth()
            if parsed.path == "/api/devices":
                status = parse_qs(parsed.query).get("status", ["approved"])[0]
                return self.send_json(200, list_devices(status))
            if parsed.path.startswith("/api/devices/"):
                device_id = parsed.path.rsplit("/", 1)[-1]
                return self.send_json(200, get_device(device_id))
            if parsed.path.startswith("/api/jobs/"):
                suffix = parsed.path[len("/api/jobs/"):]
                parts = suffix.split("/", 1)
                if len(parts) != 2:
                    raise ValueError("job path must be /api/jobs/{region}/{job_id}")
                region, job_id = parts
                return self.send_json(200, get_job(job_id, region))
            return self.send_json(404, {"error": "not_found"})
        except PermissionError as exc:
            return self.send_json(401, {"error": str(exc)})
        except ValueError as exc:
            return self.send_json(400, {"error": str(exc)})
        except RuntimeError as exc:
            return self.send_json(502, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            self.require_auth()
            payload = json.loads(body.decode("utf-8") or "{}")
            if parsed.path == "/api/commands":
                return self.send_json(
                    200,
                    execute_command(
                        payload["device_id"],
                        payload["command"],
                        int(payload.get("timeout_ms") or 30000),
                        int(payload.get("wait_seconds") or 20),
                    ),
                )
            if parsed.path == "/api/runtime":
                return self.send_json(
                    200,
                    submit_operation(
                        payload["device_id"],
                        payload["operation"],
                        payload["input"],
                        int(payload.get("timeout_ms") or 30000),
                        int(payload.get("wait_seconds") or 20),
                    ),
                )
            return self.send_json(404, {"error": "not_found"})
        except PermissionError as exc:
            return self.send_json(401, {"error": str(exc)})
        except KeyError as exc:
            return self.send_json(400, {"error": f"missing field: {exc.args[0]}"})
        except ValueError as exc:
            return self.send_json(400, {"error": str(exc)})
        except RuntimeError as exc:
            return self.send_json(502, {"error": str(exc)})


def main() -> None:
    bind = os.getenv("NEXUS_CHATGPT_BIND", "127.0.0.1")
    port = int(os.getenv("NEXUS_CHATGPT_PORT", "18131"))
    ThreadingHTTPServer((bind, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
