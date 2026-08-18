from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("mcp")

from nexus_v3 import mcp_server

mcp = mcp_server.mcp


def tool_map() -> dict[str, Any]:
    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


def test_every_tool_has_a_concrete_output_schema() -> None:
    tools = tool_map()

    assert len(tools) == 11
    for tool in tools.values():
        schema = tool.outputSchema
        assert schema is not None
        assert schema.get("type") == "object"
        assert schema.get("properties"), tool.name


def test_structured_output_preserves_runtime_extension_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "devices": [
            {
                "device_id": "victus",
                "status": "approved",
                "future_device_field": 1,
            }
        ],
        "presence_errors": {},
        "future_top_level_field": "kept",
    }
    monkeypatch.setattr(mcp_server.remote_control, "list_devices", lambda status: payload)

    content, structured = asyncio.run(mcp.call_tool("list_devices", {}))

    assert content
    assert structured == payload


def test_batch_defaults_are_forwarded_without_a_null_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_execute_batch(jobs: list[dict[str, Any]], wait_seconds: int) -> dict[str, Any]:
        captured["jobs"] = jobs
        captured["wait_seconds"] = wait_seconds
        return {"results": [{"status": "failed", "error": "Example", "detail": "test"}]}

    monkeypatch.setattr(mcp_server.remote_control, "execute_batch", fake_execute_batch)

    asyncio.run(
        mcp.call_tool(
            "execute_batch",
            {"jobs": [{"device_id": "victus", "command": "echo ok"}]},
        )
    )

    assert captured == {
        "jobs": [{"device_id": "victus", "command": "echo ok", "timeout_ms": 30_000}],
        "wait_seconds": 20,
    }


def test_tool_risk_annotations_match_remote_side_effects() -> None:
    tools = tool_map()
    read_only = {"list_devices", "get_device", "fleet_status", "read_workspace", "get_job"}
    destructive = {
        "execute_batch",
        "execute_command",
        "apply_workspace_patch",
        "exec_workspace_command",
        "write_workspace_stdin",
    }

    for name in read_only:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.readOnlyHint is True
        assert annotations.destructiveHint is False
        assert annotations.idempotentHint is True
        assert annotations.openWorldHint is True

    for name in destructive:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.readOnlyHint is False
        assert annotations.destructiveHint is True
        assert annotations.idempotentHint is False
        assert annotations.openWorldHint is True

    annotations = tools["open_workspace"].annotations
    assert annotations is not None
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is True


def test_input_schemas_publish_operational_limits() -> None:
    tools = tool_map()

    batch = tools["execute_batch"].inputSchema["properties"]["jobs"]
    assert batch["minItems"] == 1
    assert batch["maxItems"] == 16

    command = tools["execute_command"].inputSchema["properties"]
    assert command["device_id"]["minLength"] == 1
    assert command["command"]["minLength"] == 1
    assert command["timeout_ms"]["minimum"] == 1000
    assert command["timeout_ms"]["maximum"] == 86_400_000
    assert command["wait_seconds"]["minimum"] == 0
    assert command["wait_seconds"]["maximum"] == 120

    workspace = tools["open_workspace"].inputSchema["properties"]
    assert set(workspace["mode"]["enum"]) == {"checkout", "worktree"}

    job = tools["get_job"].inputSchema["properties"]
    assert set(job["region"]["enum"]) == {"eu", "cn"}
