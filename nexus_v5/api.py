from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from . import VERSION
from .router import Router


def api_key() -> str:
    value = os.getenv("NEXUS_CHATGPT_API_KEY", "")
    if not value:
        raise RuntimeError("NEXUS_CHATGPT_API_KEY is required")
    return value


def public_base_url() -> str:
    return os.getenv("NEXUS_CHATGPT_PUBLIC_BASE_URL", "http://127.0.0.1:18131").rstrip("/")


def _workspace_action_paths() -> dict[str, Any]:
    """Dedicated Action operations mirroring the Nexus MCP DevSpace tools."""
    return {
        "/api/workspaces/open": {"post": {
            "operationId": "openWorkspace",
            "summary": "Open an upstream DevSpace checkout or managed worktree on one named device",
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "additionalProperties": False, "required": ["device_id", "path"],
                "properties": {
                    "device_id": {"type": "string"}, "path": {"type": "string"},
                    "mode": {"type": "string", "enum": ["checkout", "worktree"], "default": "checkout"},
                    "base_ref": {"type": "string", "default": ""},
                    "timeout_ms": {"type": "integer", "default": 30000, "minimum": 1000, "maximum": 86400000},
                },
            }}}}, "responses": {"200": {"description": "Workspace open result"}},
        }},
        "/api/workspaces/read": {"post": {
            "operationId": "readWorkspace",
            "summary": "Read a file through an opened upstream DevSpace workspace",
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "additionalProperties": False, "required": ["device_id", "workspace_id", "path"],
                "properties": {
                    "device_id": {"type": "string"}, "workspace_id": {"type": "string"}, "path": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 20000},
                    "timeout_ms": {"type": "integer", "default": 30000, "minimum": 1000, "maximum": 86400000},
                },
            }}}}, "responses": {"200": {"description": "Workspace read result"}},
        }},
        "/api/workspaces/apply-patch": {"post": {
            "operationId": "applyWorkspacePatch",
            "summary": "Apply a Codex-style patch through upstream DevSpace on one named device",
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "additionalProperties": False, "required": ["device_id", "workspace_id", "patch"],
                "properties": {
                    "device_id": {"type": "string"}, "workspace_id": {"type": "string"}, "patch": {"type": "string"},
                    "timeout_ms": {"type": "integer", "default": 30000, "minimum": 1000, "maximum": 86400000},
                },
            }}}}, "responses": {"200": {"description": "Workspace patch result"}},
        }},
        "/api/workspaces/exec": {"post": {
            "operationId": "execWorkspaceCommand",
            "summary": "Run a command inside an opened upstream DevSpace workspace",
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "additionalProperties": False, "required": ["device_id", "workspace_id", "command"],
                "properties": {
                    "device_id": {"type": "string"}, "workspace_id": {"type": "string"}, "command": {"type": "string"},
                    "working_directory": {"type": "string", "default": ""}, "tty": {"type": "boolean", "default": False},
                    "yield_time_ms": {"type": "integer", "minimum": 0, "maximum": 300000},
                    "max_output_tokens": {"type": "integer", "minimum": 1, "maximum": 100000},
                    "timeout_ms": {"type": "integer", "default": 30000, "minimum": 1000, "maximum": 86400000},
                },
            }}}}, "responses": {"200": {"description": "Workspace command result or process session"}},
        }},
        "/api/workspaces/stdin": {"post": {
            "operationId": "writeWorkspaceStdin",
            "summary": "Poll or interact with a running upstream DevSpace process session",
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "additionalProperties": False, "required": ["device_id", "workspace_id", "session_id"],
                "properties": {
                    "device_id": {"type": "string"}, "workspace_id": {"type": "string"},
                    "session_id": {"type": "integer", "minimum": 1}, "chars": {"type": "string", "default": ""},
                    "yield_time_ms": {"type": "integer", "minimum": 0, "maximum": 300000},
                    "timeout_ms": {"type": "integer", "default": 30000, "minimum": 1000, "maximum": 86400000},
                },
            }}}}, "responses": {"200": {"description": "Workspace process session result"}},
        }},
    }


def _legacy_broker_url(region: str) -> str:
    normalized = region.strip().lower()
    if normalized not in {"eu", "cn"}:
        raise ValueError("region must be eu or cn")
    name = "NEXUS_V3_EU_BROKER_URL" if normalized == "eu" else "NEXUS_V3_CN_BROKER_URL"
    value = os.getenv(name, "").rstrip("/")
    if not value:
        raise RuntimeError(f"{name} is required for legacy job lookup")
    return value


def get_legacy_job(job_id: str, region: str) -> dict[str, Any]:
    """Compatibility lookup for asynchronous jobs created through the broker-backed MCP path."""
    admin_key = os.getenv("NEXUS_V3_ADMIN_KEY", "")
    if not admin_key:
        raise RuntimeError("NEXUS_V3_ADMIN_KEY is required for legacy job lookup")
    normalized = region.strip().lower()
    url = f"{_legacy_broker_url(normalized)}/v3/jobs?{urlencode({'id': job_id})}"
    request = Request(url, method="GET", headers={"X-Nexus-Admin-Key": admin_key})
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            payload = json.loads(raw or "{}")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw or "{}")
        except Exception:
            payload = {"error": raw[:500]}
        raise RuntimeError(f"Nexus broker returned HTTP {exc.code}: {payload.get('error')}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("invalid Nexus broker job response")
    payload["broker_region"] = normalized
    return payload


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
            **_workspace_action_paths(),
            "/api/jobs/{region}/{job_id}": {"get": {
                "operationId": "getJob", "summary": "Get an asynchronous Nexus broker job by ID",
                "parameters": [
                    {"name": "region", "in": "path", "required": True, "schema": {"type": "string", "enum": ["eu", "cn"]}},
                    {"name": "job_id", "in": "path", "required": True, "schema": {"type": "string"}},
                ],
                "responses": {"200": {"description": "Job status and result"}},
            }},
        },
        "components": {"schemas": {}, "securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer"}}},
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
                if parsed.path.startswith("/api/jobs/"):
                    suffix = parsed.path[len("/api/jobs/"):]
                    parts = suffix.split("/", 1)
                    if len(parts) != 2:
                        raise ValueError("job path must be /api/jobs/{region}/{job_id}")
                    region, job_id = parts
                    return self.send_json(200, get_legacy_job(job_id, region))
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
                if self.path == "/api/workspaces/open":
                    input_data = {"path": str(payload["path"]), "mode": str(payload.get("mode") or "checkout")}
                    if payload.get("base_ref"):
                        input_data["baseRef"] = str(payload["base_ref"])
                    return self.send_json(200, service.router.runtime(str(payload["device_id"]), "workspace.open", input_data, int(payload.get("timeout_ms") or 30000)))
                if self.path == "/api/workspaces/read":
                    input_data = {"workspaceId": str(payload["workspace_id"]), "path": str(payload["path"])}
                    if payload.get("offset") is not None:
                        input_data["offset"] = int(payload["offset"])
                    if payload.get("limit") is not None:
                        input_data["limit"] = int(payload["limit"])
                    return self.send_json(200, service.router.runtime(str(payload["device_id"]), "workspace.read", input_data, int(payload.get("timeout_ms") or 30000)))
                if self.path == "/api/workspaces/apply-patch":
                    return self.send_json(200, service.router.runtime(str(payload["device_id"]), "workspace.apply_patch", {"workspaceId": str(payload["workspace_id"]), "patch": str(payload["patch"])}, int(payload.get("timeout_ms") or 30000)))
                if self.path == "/api/workspaces/exec":
                    input_data = {"workspaceId": str(payload["workspace_id"]), "command": str(payload["command"]), "tty": bool(payload.get("tty", False))}
                    if payload.get("working_directory"):
                        input_data["workingDirectory"] = str(payload["working_directory"])
                    if payload.get("yield_time_ms") is not None:
                        input_data["yieldTimeMs"] = int(payload["yield_time_ms"])
                    if payload.get("max_output_tokens") is not None:
                        input_data["maxOutputTokens"] = int(payload["max_output_tokens"])
                    return self.send_json(200, service.router.runtime(str(payload["device_id"]), "workspace.exec", input_data, int(payload.get("timeout_ms") or 30000)))
                if self.path == "/api/workspaces/stdin":
                    input_data = {"workspaceId": str(payload["workspace_id"]), "sessionId": int(payload["session_id"]), "chars": str(payload.get("chars") or "")}
                    if payload.get("yield_time_ms") is not None:
                        input_data["yieldTimeMs"] = int(payload["yield_time_ms"])
                    return self.send_json(200, service.router.runtime(str(payload["device_id"]), "workspace.write_stdin", input_data, int(payload.get("timeout_ms") or 30000)))
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
