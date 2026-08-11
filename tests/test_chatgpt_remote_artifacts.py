from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chatgpt_remote_openapi_is_valid() -> None:
    spec = json.loads((ROOT / "agent-council" / "integrations" / "nexus-v3-remote-control-openapi.json").read_text(encoding="utf-8"))
    assert spec["openapi"] == "3.1.0"
    assert {"listDevices", "getDevice", "executeCommand", "executeRuntimeOperation", "getJob"} <= {
        operation["operationId"]
        for methods in spec["paths"].values()
        for operation in methods.values()
        if isinstance(operation, dict) and "operationId" in operation
    }
    runtime = spec["paths"]["/api/runtime"]["post"]
    assert "workspace.open" in runtime["requestBody"]["content"]["application/json"]["schema"]["properties"]["operation"]["enum"]


def test_chatgpt_remote_installer_deploys_mcp_and_action_api() -> None:
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "chatgpt_api.py" in text
    assert "mcp_server.py" in text
    assert "nexus-chatgpt-remote.service" in text
    assert "nexus-v3-mcp.service" in text
    assert "install_openwrt_agent" in text
    assert "n1 and ax3600 self-claim jobs" in text


def test_chatgpt_prompt_mentions_canonical_devices_and_receipts() -> None:
    prompt = (ROOT / "agent-council" / "integrations" / "nexus-v3-chatgpt-remote-prompt.md").read_text(encoding="utf-8")
    assert "canonical device IDs" in prompt
    assert "job_id" in prompt
    assert "status" in prompt


def test_managed_target_fallback_prefers_controller_when_device_unapproved(monkeypatch) -> None:
    from nexus_v3 import remote_control

    def fake_request_json(method: str, url: str, body=None):
        if "/v3/devices/ax3600/public-key" in url:
            return 404, {"error": "not_found"}
        raise AssertionError(url)

    monkeypatch.setattr(remote_control, "request_json", fake_request_json)
    target, command, managed = remote_control.dispatch_target("ax3600", "uptime")

    assert target == "thinkcenter"
    assert managed == "ax3600"
    assert "root@192.168.1.1" in command
    assert "uptime" in command


def test_managed_target_uses_self_when_approved(monkeypatch) -> None:
    from nexus_v3 import remote_control

    def fake_request_json(method: str, url: str, body=None):
        if "/v3/devices/n1/public-key" in url:
            return 200, {"device_id": "n1"}
        raise AssertionError(url)

    monkeypatch.setattr(remote_control, "request_json", fake_request_json)
    target, command, managed = remote_control.dispatch_target("n1", "uname -a")

    assert target == "n1"
    assert command == "uname -a"
    assert managed is None
