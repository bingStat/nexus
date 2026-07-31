from __future__ import annotations

import argparse
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server.client import (
    create_command,
    get_command_result,
    get_device_status,
    list_devices as backend_list_devices,
    wait_for_command,
)
from mcp_server.security import validate_command

mcp = FastMCP(
    "Nexus",
    instructions=(
        "Direct, audited control of registered Nexus Agents. Always target the destination "
        "device directly; cross-node SSH and nested command-queue calls are forbidden."
    ),
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def list_devices() -> list[dict[str, Any]]:
    """List devices using heartbeat-derived online, degraded, or offline state."""
    return backend_list_devices()


@mcp.tool()
def get_status(device_id: str) -> dict[str, Any]:
    """Get one device record and its heartbeat-derived state."""
    result = get_device_status(device_id)
    return result or {"status": "not_found", "device_id": device_id}


@mcp.tool()
def execute_command(
    device: str,
    command: str,
    wait_seconds: int = 10,
    timeout_ms: int = 30_000,
    allow_privileged: bool = False,
    allow_destructive: bool = False,
) -> dict[str, Any]:
    """Run a command on one Agent after server-side risk and routing checks."""
    allowed, reason, risk = validate_command(
        command,
        allow_privileged=allow_privileged,
        allow_destructive=allow_destructive,
    )
    if not allowed:
        return {"status": "rejected", "reason": reason, "risk_level": risk.value}
    record = create_command(
        target_device=device,
        command_str=command,
        timeout_ms=timeout_ms,
        metadata={"risk_level": risk.value, "source": "mcp"},
    )
    job_id = record.get("id")
    if not job_id:
        return {"status": "failed", "reason": "Backend returned no job id"}
    if wait_seconds <= 0:
        return {"job_id": job_id, "status": "pending", "risk_level": risk.value}
    result = wait_for_command(job_id, min(wait_seconds, 120))
    result.setdefault("risk_level", risk.value)
    return result


@mcp.tool()
def get_job(job_id: str) -> dict[str, Any]:
    """Return the current status and output fields for a submitted job."""
    return get_command_result(job_id) or {"status": "not_found", "job_id": job_id}


def main() -> None:
    parser = argparse.ArgumentParser(description="Nexus MCP control plane")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.getenv("NEXUS_MCP_TRANSPORT", "streamable-http"),
    )
    parser.add_argument("--host", default=os.getenv("NEXUS_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("NEXUS_MCP_PORT", "8000")))
    args = parser.parse_args()
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.settings.streamable_http_path = "/mcp"
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
