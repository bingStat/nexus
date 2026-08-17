from __future__ import annotations

import hmac
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import remote_control

VERSION = "3.1.0"

mcp = FastMCP(
    "Nexus v3",
    instructions=(
        "Nexus is a distributed DevSpace plus fleet control plane. Always name the target device and never "
        "change that device during failover. For coding work on a device that advertises runtime=devspace, "
        "open one workspace and reuse its workspaceId for reads, patches and process sessions. Use worktree "
        "mode when isolation is required. Shell-only devices remain available through execute_command."
    ),
    host=os.getenv("NEXUS_V3_MCP_BIND", "127.0.0.1"),
    port=int(os.getenv("NEXUS_V3_MCP_PORT", "18130")),
    stateless_http=True,
    json_response=True,
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


@mcp.tool()
def list_devices(status: str = "approved") -> dict[str, Any]:
    """List Nexus devices, including their runtime capabilities."""
    return remote_control.list_devices(status)


@mcp.tool()
def get_device(device_id: str) -> dict[str, Any]:
    """Return one Nexus device identity and its runtime capabilities."""
    return remote_control.get_device(device_id)


@mcp.tool()
def fleet_status() -> dict[str, Any]:
    """Return current runtime status for approved devices and both Regional Brokers."""
    return remote_control.fleet_status()


@mcp.tool()
def execute_batch(jobs: list[dict[str, Any]], wait_seconds: int = 20) -> dict[str, Any]:
    """Execute up to 16 shell jobs concurrently; every job must name its target device."""
    return remote_control.execute_batch(jobs, wait_seconds)


@mcp.tool()
def execute_command(device_id: str, command: str, timeout_ms: int = 30000, wait_seconds: int = 20) -> dict[str, Any]:
    """Execute a shell command on one explicitly named Nexus device."""
    return remote_control.execute_command(device_id, command, timeout_ms, wait_seconds)


@mcp.tool()
def open_workspace(
    device_id: str,
    path: str,
    mode: str = "checkout",
    base_ref: str = "",
    wait_seconds: int = 20,
) -> dict[str, Any]:
    """Open an upstream DevSpace checkout or managed worktree on one named device."""
    return remote_control.open_workspace(device_id, path, mode, base_ref or None, wait_seconds)


@mcp.tool()
def read_workspace(
    device_id: str,
    workspace_id: str,
    path: str,
    offset: int | None = None,
    limit: int | None = None,
    wait_seconds: int = 20,
) -> dict[str, Any]:
    """Read a file using the upstream DevSpace workspace runtime."""
    return remote_control.read_workspace(device_id, workspace_id, path, offset, limit, wait_seconds)


@mcp.tool()
def apply_workspace_patch(
    device_id: str,
    workspace_id: str,
    patch: str,
    wait_seconds: int = 20,
) -> dict[str, Any]:
    """Apply a Codex-style patch through upstream DevSpace on the named device."""
    return remote_control.apply_workspace_patch(device_id, workspace_id, patch, wait_seconds)


@mcp.tool()
def exec_workspace_command(
    device_id: str,
    workspace_id: str,
    command: str,
    working_directory: str = "",
    tty: bool = False,
    yield_time_ms: int | None = None,
    max_output_tokens: int | None = None,
    wait_seconds: int = 20,
) -> dict[str, Any]:
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


@mcp.tool()
def write_workspace_stdin(
    device_id: str,
    workspace_id: str,
    session_id: int,
    chars: str = "",
    yield_time_ms: int | None = None,
    wait_seconds: int = 20,
) -> dict[str, Any]:
    """Poll or interact with a running upstream DevSpace process session."""
    return remote_control.write_workspace_stdin(
        device_id,
        workspace_id,
        session_id,
        chars,
        yield_time_ms,
        wait_seconds,
    )


@mcp.tool()
def terminate_workspace_session(
    device_id: str,
    workspace_id: str,
    session_id: int,
    signal: str = "SIGTERM",
    wait_seconds: int = 20,
) -> dict[str, Any]:
    """Terminate or send interrupt signal (e.g. SIGINT/Ctrl+C, SIGTERM) to a running workspace process session."""
    return remote_control.terminate_workspace_session(
        device_id,
        workspace_id,
        session_id,
        signal,
        wait_seconds,
    )


@mcp.tool()
def get_job(job_id: str, region: str) -> dict[str, Any]:
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
