from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from . import remote_control

VERSION = "3.0.0"

mcp = FastMCP(
    "Nexus v3",
    instructions=(
        "Control only explicitly named Nexus devices. Never change the target device during failover. "
        "Report job IDs and actual terminal status. Destructive network, credential, disk, power, and deletion commands are blocked."
    ),
    host=os.getenv("NEXUS_V3_MCP_BIND", "127.0.0.1"),
    port=int(os.getenv("NEXUS_V3_MCP_PORT", "18130")),
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def list_devices(status: str = "approved") -> dict[str, Any]:
    """List Nexus device identities by approval status."""
    return remote_control.list_devices(status)


@mcp.tool()
def get_device(device_id: str) -> dict[str, Any]:
    """Return the registered public identity and approval status for one Nexus device."""
    return remote_control.get_device(device_id)


@mcp.tool()
def execute_command(device_id: str, command: str, timeout_ms: int = 30000, wait_seconds: int = 20) -> dict[str, Any]:
    """Execute a command on one explicitly named Nexus device and optionally wait for its terminal result."""
    return remote_control.execute_command(device_id, command, timeout_ms, wait_seconds)


@mcp.tool()
def get_job(job_id: str, region: str) -> dict[str, Any]:
    """Get a Nexus job by ID from the specified eu or cn broker."""
    return remote_control.get_job(job_id, region)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
