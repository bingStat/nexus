import os
import sys

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from typing import Any, Dict, List, Optional
from mcp.server.fastmcp import FastMCP

from mcp_server.client import (
    list_devices as api_list_devices,
    get_device_status as api_get_device_status,
    create_command as api_create_command,
    get_command_result as api_get_command_result,
    wait_for_command as api_wait_for_command,
)
from mcp_server.security import validate_command

# Initialize FastMCP Server instance
mcp = FastMCP("Nexus")

@mcp.tool()
def list_devices() -> List[Dict[str, Any]]:
    """
    List all registered devices in the Nexus cluster along with their status and last active timestamp.
    """
    try:
        return api_list_devices()
    except Exception as e:
        return [{"error": str(e)}]

@mcp.tool()
def get_status(device_id: str) -> Dict[str, Any]:
    """
    Get detailed running status and registration info for a specific target device in Nexus cluster.
    
    Args:
        device_id: Device ID or hostname (e.g., 'thinkcenter', 'victus', 'oracle', 'vsc', 'n1')
    """
    try:
        res = api_get_device_status(device_id)
        if not res:
            return {"error": f"Device '{device_id}' not found."}
        return res
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def execute_command(
    device: str,
    command: str,
    wait_seconds: int = 10,
    allow_dangerous: bool = False
) -> Dict[str, Any]:
    """
    Execute a shell command on a target device via Nexus command queue.
    
    Args:
        device: Target device name/ID (e.g. 'thinkcenter', 'victus', 'oracle')
        command: Shell command string to execute on the target machine
        wait_seconds: Seconds to wait synchronously for completion (default 10s, 0 for async submission)
        allow_dangerous: Must be set to True if running high-risk commands (e.g. rm -rf, shutdown, reboot)
    """
    # Safety Check
    allowed, msg = validate_command(command, allow_dangerous=allow_dangerous)
    if not allowed:
        return {"status": "rejected", "error": msg}

    try:
        cmd_record = api_create_command(target_device=device, command_str=command)
        job_id = cmd_record.get("id")
        
        if not job_id:
            return {"status": "failed", "error": "Failed to create command record", "record": cmd_record}

        if wait_seconds > 0:
            result = api_wait_for_command(job_id, max_wait_seconds=wait_seconds)
            return result
        else:
            return {
                "job_id": job_id,
                "status": "pending",
                "message": f"Command dispatched to {device}. Query job output via get_job(job_id='{job_id}')"
            }
    except Exception as e:
        return {"status": "failed", "error": str(e)}

@mcp.tool()
def get_job(job_id: str) -> Dict[str, Any]:
    """
    Retrieve the status and stdout/stderr output of a previously dispatched command by job UUID.
    
    Args:
        job_id: UUID of the command job returned by execute_command
    """
    try:
        res = api_get_command_result(job_id)
        if not res:
            return {"error": f"Job '{job_id}' not found."}
        return res
    except Exception as e:
        return {"error": str(e)}

def main():
    parser = argparse.ArgumentParser(description="Nexus FastMCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="Transport mode (default: stdio)")
    parser.add_argument("--host", default="0.0.0.0", help="Host address for SSE mode")
    parser.add_argument("--port", type=int, default=8000, help="Port for SSE mode")
    args, unknown = parser.parse_known_args()

    if args.transport == "sse":
        print(f"[Nexus MCP] Starting FastMCP Server in SSE mode on {args.host}:{args.port}...", file=sys.stderr)
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")

if __name__ == "__main__":
    main()

