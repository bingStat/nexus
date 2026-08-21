from __future__ import annotations

import hmac
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from . import remote_control
from .mcp_contracts import (
    BaseRef,
    BatchJobs,
    BatchOutput,
    BrokerRegion,
    Command,
    DeviceId,
    DeviceListOutput,
    DeviceOutput,
    DeviceStatus,
    FleetStatusOutput,
    JobId,
    JobOutput,
    MaxOutputTokens,
    OptionalPath,
    Patch,
    Path,
    ReadLimit,
    ReadOffset,
    SessionId,
    SelfTestOutput,
    StdinChars,
    TimeoutMs,
    WaitSeconds,
    WorkspaceId,
    WorkspaceMode,
    YieldTimeMs,
)

VERSION = "3.2.2"

mcp = FastMCP(
    "Nexus",
    instructions=(
        "Nexus is the canonical production control interface for the user's Nexus-managed fleet. When the user "
        "explicitly says Nexus or @Nexus, use these Nexus tools first; do not substitute a developer MCP, SSH, "
        "Desktop Commander, or another remote-control path unless a Nexus invocation actually fails. Tool "
        "availability is determined from the tools registered in the current turn, never from an earlier failure. "
        "Use self_test to distinguish control-plane health from client/tool-routing problems. Always name the exact "
        "target device and never change that device during failover. For coding on runtime=devspace, open one "
        "workspace and reuse its workspaceId. Shell-only devices remain available through execute_command."
    ),
    host=os.getenv("NEXUS_V3_MCP_BIND", "127.0.0.1"),
    port=int(os.getenv("NEXUS_V3_MCP_PORT", "18130")),
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
            "nexus.bings.app",
            "nexus.bings.app:*",
            "nexus-api.bings.app",
            "nexus-api.bings.app:*",
        ],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            "https://nexus.bings.app",
            "https://nexus.bings.app:*",
            "https://nexus-api.bings.app",
            "https://nexus-api.bings.app:*",
        ],
    ),
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
NON_DESTRUCTIVE_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
DESTRUCTIVE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)


# ---------------------------------------------------------------------------
# Bearer-token auth middleware
# When NEXUS_MCP_BEARER_TOKEN is set every request must carry
# "Authorization: Bearer <token>". Requests to /health are always allowed.
# ---------------------------------------------------------------------------

_UNPROTECTED = {"/health", "/"}

def _make_auth_middleware(app: Any, token: str) -> Any:
    """Wrap an ASGI app with a simple constant-time Bearer token check."""
    token_bytes = token.encode()

    async def middleware(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            path: str = scope.get("path", "")
            if path not in _UNPROTECTED:
                headers = dict(scope.get("headers", []))
                auth = headers.get(b"authorization", b"").decode()
                prefix = "Bearer "
                supplied = auth[len(prefix):].encode() if auth.startswith(prefix) else b""
                if not hmac.compare_digest(supplied, token_bytes):
                    body = b'{"error":"unauthorized"}'
                    await send({
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                            (b"www-authenticate", b'Bearer realm="Nexus MCP"'),
                        ],
                    })
                    await send({"type": "http.response.body", "body": body})
                    return
        await app(scope, receive, send)

    return middleware


@mcp.tool(annotations=READ_ONLY, structured_output=True)
def self_test() -> SelfTestOutput:
    """Check Registry, both Brokers, and Agent presence without executing on a device."""
    return remote_control.self_test()


@mcp.tool(annotations=READ_ONLY, structured_output=True)
def list_devices(status: DeviceStatus = "approved") -> DeviceListOutput:
    """List Nexus devices, including their runtime capabilities."""
    return remote_control.list_devices(status)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
def get_device(device_id: DeviceId) -> DeviceOutput:
    """Return one Nexus device identity and its runtime capabilities."""
    return remote_control.get_device(device_id)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
def fleet_status() -> FleetStatusOutput:
    """Return current runtime status for approved devices and both Regional Brokers."""
    return remote_control.fleet_status()


@mcp.tool(annotations=DESTRUCTIVE, structured_output=True)
def execute_batch(jobs: BatchJobs, wait_seconds: WaitSeconds = 20) -> BatchOutput:
    """Execute up to 16 shell jobs concurrently; every job must name its target device."""
    return remote_control.execute_batch([job.model_dump(exclude_none=True) for job in jobs], wait_seconds)


@mcp.tool(annotations=DESTRUCTIVE, structured_output=True)
def execute_command(
    device_id: DeviceId,
    command: Command,
    timeout_ms: TimeoutMs = 30000,
    wait_seconds: WaitSeconds = 20,
) -> JobOutput:
    """Execute a shell command on one explicitly named Nexus device."""
    return remote_control.execute_command(device_id, command, timeout_ms, wait_seconds)


@mcp.tool(annotations=NON_DESTRUCTIVE_WRITE, structured_output=True)
def open_workspace(
    device_id: DeviceId,
    path: Path,
    mode: WorkspaceMode = "checkout",
    base_ref: BaseRef = "",
    wait_seconds: WaitSeconds = 20,
) -> JobOutput:
    """Open an upstream DevSpace checkout or managed worktree on one named device."""
    return remote_control.open_workspace(device_id, path, mode, base_ref or None, wait_seconds)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
def read_workspace(
    device_id: DeviceId,
    workspace_id: WorkspaceId,
    path: Path,
    offset: ReadOffset | None = None,
    limit: ReadLimit | None = None,
    wait_seconds: WaitSeconds = 20,
) -> JobOutput:
    """Read a file using the upstream DevSpace workspace runtime."""
    return remote_control.read_workspace(device_id, workspace_id, path, offset, limit, wait_seconds)


@mcp.tool(annotations=DESTRUCTIVE, structured_output=True)
def apply_workspace_patch(
    device_id: DeviceId,
    workspace_id: WorkspaceId,
    patch: Patch,
    wait_seconds: WaitSeconds = 20,
) -> JobOutput:
    """Apply a Codex-style patch through upstream DevSpace on the named device."""
    return remote_control.apply_workspace_patch(device_id, workspace_id, patch, wait_seconds)


@mcp.tool(annotations=DESTRUCTIVE, structured_output=True)
def exec_workspace_command(
    device_id: DeviceId,
    workspace_id: WorkspaceId,
    command: Command,
    working_directory: OptionalPath = "",
    tty: bool = False,
    yield_time_ms: YieldTimeMs | None = None,
    max_output_tokens: MaxOutputTokens | None = None,
    wait_seconds: WaitSeconds = 20,
) -> JobOutput:
    """Run a command in an upstream DevSpace workspace, returning a process session when still running."""
    return remote_control.exec_workspace_command(
        device_id,
        workspace_id,
        command,
        working_directory or None,
        tty,
        yield_time_ms,
        max_output_tokens,
        wait_seconds,
    )


@mcp.tool(annotations=DESTRUCTIVE, structured_output=True)
def write_workspace_stdin(
    device_id: DeviceId,
    workspace_id: WorkspaceId,
    session_id: SessionId,
    chars: StdinChars = "",
    yield_time_ms: YieldTimeMs | None = None,
    wait_seconds: WaitSeconds = 20,
) -> JobOutput:
    """Poll or interact with a running upstream DevSpace process session."""
    return remote_control.write_workspace_stdin(
        device_id,
        workspace_id,
        session_id,
        chars,
        yield_time_ms,
        wait_seconds,
    )


@mcp.tool(annotations=READ_ONLY, structured_output=True)
def get_job(job_id: JobId, region: BrokerRegion) -> JobOutput:
    """Get a Nexus job by ID from the specified eu or cn broker."""
    return remote_control.get_job(job_id, region)




if __name__ == "__main__":
    _bearer = os.getenv("NEXUS_MCP_BEARER_TOKEN", "").strip()
    _bind = os.getenv("NEXUS_V3_MCP_BIND", "127.0.0.1")
    _port = int(os.getenv("NEXUS_V3_MCP_PORT", "18130"))

    if _bearer:
        # Detect the correct ASGI app getter across FastMCP versions
        _asgi_getter = (
            getattr(mcp, "streamable_http_app", None)
            or getattr(mcp, "http_app", None)
            or getattr(mcp, "get_asgi_app", None)
        )
        if _asgi_getter is not None:
            import uvicorn  # type: ignore[import-untyped]
            _raw_app = _asgi_getter()
            _app = _make_auth_middleware(_raw_app, _bearer)
            uvicorn.run(_app, host=_bind, port=_port, log_level="warning")
        else:
            # FastMCP version does not expose an ASGI app; fall back and warn
            import sys
            print(
                "WARNING: NEXUS_MCP_BEARER_TOKEN is set but this FastMCP version "
                "does not expose an ASGI app — running without auth. "
                "Upgrade mcp>=1.26 to enable auth.",
                file=sys.stderr,
            )
            mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="streamable-http")
