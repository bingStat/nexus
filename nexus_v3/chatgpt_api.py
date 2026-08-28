from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .remote_control import (
    apply_workspace_patch,
    exec_workspace_command,
    execute_batch,
    execute_command,
    fleet_status,
    get_device,
    get_job,
    list_devices,
    open_workspace,
    read_workspace,
    self_test,
    submit_operation,
    write_workspace_stdin,
)

VERSION = "3.2.2"


def chatgpt_api_key() -> str:
    value = os.getenv("NEXUS_CHATGPT_API_KEY", "")
    if not value:
        raise RuntimeError("NEXUS_CHATGPT_API_KEY is required")
    return value


def public_base_url() -> str:
    return os.getenv("NEXUS_CHATGPT_PUBLIC_BASE_URL", "http://127.0.0.1:18131").rstrip("/")


def _workspace_action_paths() -> dict[str, Any]:
    """OpenAPI mirrors of the five DevSpace tools exposed by the Nexus MCP server."""
    wait_seconds = {"type": "integer", "default": 20, "minimum": 0, "maximum": 120}
    return {
        "/api/workspaces/open": {
            "post": {
                "operationId": "openWorkspace",
                "summary": "Open an upstream DevSpace checkout or managed worktree on one named device",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "additionalProperties": False, "required": ["device_id", "path"],
                    "properties": {
                        "device_id": {"type": "string"},
                        "path": {"type": "string"},
                        "mode": {"type": "string", "enum": ["checkout", "worktree"], "default": "checkout"},
                        "base_ref": {"type": "string", "default": ""},
                        "wait_seconds": wait_seconds,
                    },
                }}}},
                "responses": {"200": {"description": "Workspace open result"}},
            }
        },
        "/api/workspaces/read": {
            "post": {
                "operationId": "readWorkspace",
                "summary": "Read a file through an opened upstream DevSpace workspace",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "additionalProperties": False,
                    "required": ["device_id", "workspace_id", "path"],
                    "properties": {
                        "device_id": {"type": "string"},
                        "workspace_id": {"type": "string"},
                        "path": {"type": "string"},
                        "offset": {"type": "integer", "minimum": 0},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20000},
                        "wait_seconds": wait_seconds,
                    },
                }}}},
                "responses": {"200": {"description": "Workspace read result"}},
            }
        },
        "/api/workspaces/apply-patch": {
            "post": {
                "operationId": "applyWorkspacePatch",
                "summary": "Apply a Codex-style patch through upstream DevSpace on one named device",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "additionalProperties": False,
                    "required": ["device_id", "workspace_id", "patch"],
                    "properties": {
                        "device_id": {"type": "string"},
                        "workspace_id": {"type": "string"},
                        "patch": {"type": "string"},
                        "wait_seconds": wait_seconds,
                    },
                }}}},
                "responses": {"200": {"description": "Workspace patch result"}},
            }
        },
        "/api/workspaces/exec": {
            "post": {
                "operationId": "execWorkspaceCommand",
                "summary": "Run a command inside an opened upstream DevSpace workspace",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "additionalProperties": False,
                    "required": ["device_id", "workspace_id", "command"],
                    "properties": {
                        "device_id": {"type": "string"},
                        "workspace_id": {"type": "string"},
                        "command": {"type": "string"},
                        "working_directory": {"type": "string", "default": ""},
                        "tty": {"type": "boolean", "default": False},
                        "yield_time_ms": {"type": "integer", "minimum": 0, "maximum": 300000},
                        "max_output_tokens": {"type": "integer", "minimum": 1, "maximum": 100000},
                        "wait_seconds": wait_seconds,
                    },
                }}}},
                "responses": {"200": {"description": "Workspace command result or process session"}},
            }
        },
        "/api/workspaces/stdin": {
            "post": {
                "operationId": "writeWorkspaceStdin",
                "summary": "Poll or interact with a running upstream DevSpace process session",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "additionalProperties": False,
                    "required": ["device_id", "workspace_id", "session_id"],
                    "properties": {
                        "device_id": {"type": "string"},
                        "workspace_id": {"type": "string"},
                        "session_id": {"type": "integer", "minimum": 1},
                        "chars": {"type": "string", "default": ""},
                        "yield_time_ms": {"type": "integer", "minimum": 0, "maximum": 300000},
                        "wait_seconds": wait_seconds,
                    },
                }}}},
                "responses": {"200": {"description": "Workspace process session result"}},
            }
        },
    }


def openapi_document() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Nexus",
            "version": VERSION,
            "description": (
                "Canonical production interface for the Nexus-managed device fleet. If the user explicitly says Nexus or @Nexus, route through this API before any developer or fallback remote-control path. Tool availability is independent of backend health; use selfTest to diagnose the production control path. Commands and workspace operations always target one explicitly named device."
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
            "/api/self-test": {
                "get": {
                    "operationId": "selfTest",
                    "summary": "Test Registry, EU/CN Brokers, and Agent presence without executing on a device",
                    "responses": {"200": {"description": "Nexus control-path diagnostic"}},
                }
            },
            "/api/status": {
                "get": {
                    "operationId": "getFleetStatus",
                    "summary": "Get current device runtime states and Regional Broker health",
                    "responses": {"200": {"description": "Fleet status"}},
                }
            },
            "/api/commands/batch": {
                "post": {
                    "operationId": "executeBatch",
                    "summary": "Execute up to 16 shell jobs concurrently on explicitly named devices",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["jobs"], "properties": {"jobs": {"type": "array", "minItems": 1, "maxItems": 16, "items": {"type": "object", "required": ["device_id", "command"]}}, "wait_seconds": {"type": "integer", "default": 20}}}}}},
                    "responses": {"200": {"description": "Ordered batch results"}},
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
            **_workspace_action_paths(),
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


def dashboard_status() -> dict[str, Any]:
    full = fleet_status()
    allowed = {
        "device_id", "hostname", "platform", "runtime_status", "last_seen_at",
        "age_seconds", "broker_region", "presence_source", "roles", "capabilities",
    }
    devices = [
        {key: value for key, value in row.items() if key in allowed}
        for row in full.get("devices", []) if isinstance(row, dict)
    ]
    return {
        "devices": devices,
        "counts": full.get("counts", {}),
        "total": full.get("total", len(devices)),
        "brokers": full.get("brokers", {}),
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
            if parsed.path == "/api/dashboard-status":
                return self.send_json(200, dashboard_status())
            self.require_auth()
            if parsed.path == "/api/self-test":
                return self.send_json(200, self_test())
            if parsed.path == "/api/status":
                return self.send_json(200, fleet_status())
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
            if parsed.path == "/api/commands/batch":
                jobs = payload["jobs"]
                if not isinstance(jobs, list):
                    raise ValueError("jobs must be an array")
                return self.send_json(200, execute_batch(jobs, int(payload.get("wait_seconds") or 20)))
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
            if parsed.path == "/api/workspaces/open":
                return self.send_json(200, open_workspace(
                    payload["device_id"], payload["path"], payload.get("mode") or "checkout",
                    payload.get("base_ref") or None, int(payload.get("wait_seconds") or 20),
                ))
            if parsed.path == "/api/workspaces/read":
                return self.send_json(200, read_workspace(
                    payload["device_id"], payload["workspace_id"], payload["path"],
                    payload.get("offset"), payload.get("limit"), int(payload.get("wait_seconds") or 20),
                ))
            if parsed.path == "/api/workspaces/apply-patch":
                return self.send_json(200, apply_workspace_patch(
                    payload["device_id"], payload["workspace_id"], payload["patch"],
                    int(payload.get("wait_seconds") or 20),
                ))
            if parsed.path == "/api/workspaces/exec":
                return self.send_json(200, exec_workspace_command(
                    payload["device_id"], payload["workspace_id"], payload["command"],
                    payload.get("working_directory") or None, bool(payload.get("tty", False)),
                    payload.get("yield_time_ms"), payload.get("max_output_tokens"),
                    int(payload.get("wait_seconds") or 20),
                ))
            if parsed.path == "/api/workspaces/stdin":
                return self.send_json(200, write_workspace_stdin(
                    payload["device_id"], payload["workspace_id"], int(payload["session_id"]),
                    payload.get("chars") or "", payload.get("yield_time_ms"),
                    int(payload.get("wait_seconds") or 20),
                ))
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
