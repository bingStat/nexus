from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chatgpt_remote_openapi_is_valid() -> None:
    spec = json.loads((ROOT / "agent-council" / "integrations" / "nexus-v3-remote-control-openapi.json").read_text(encoding="utf-8"))
    assert spec["openapi"] == "3.1.0"
    assert {"getFleetStatus", "listDevices", "getDevice", "executeCommand", "executeBatch", "executeRuntimeOperation", "getJob"} <= {
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
    assert "managed-targets" not in text
    assert "cleanup_legacy" not in text
    assert "remote|chatgpt-remote" not in text


def test_chatgpt_prompt_mentions_canonical_devices_and_receipts() -> None:
    prompt = (ROOT / "agent-council" / "integrations" / "nexus-v3-chatgpt-remote-prompt.md").read_text(encoding="utf-8")
    assert "canonical device IDs" in prompt
    assert "job_id" in prompt
    assert "status" in prompt


def test_execute_command_never_substitutes_target_device(monkeypatch) -> None:
    from nexus_v3 import remote_control

    calls = []

    def fake_request_json(method: str, url: str, body=None):
        calls.append((method, url, body))
        if method == "POST" and "/v3/jobs" in url:
            return 201, {"id": "job-1", "status": "pending", "target_device": body["target_device"]}
        if method == "GET" and "id=job-1" in url:
            return 200, {"id": "job-1", "status": "completed", "target_device": "ax3600", "output": "ok"}
        raise AssertionError((method, url, body))

    monkeypatch.setattr(remote_control, "request_json", fake_request_json)
    result = remote_control.execute_command("ax3600", "uptime", wait_seconds=2)

    submitted = next(body for method, _url, body in calls if method == "POST")
    assert submitted["target_device"] == "ax3600"
    assert submitted["input"]["command"] == "uptime"
    assert result["target_device"] == "ax3600"


def test_dashboard_uses_standard_roles_and_live_runtime_capabilities() -> None:
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert "deviceRoleLabel" in html
    assert "deviceRuntimeLabel" in html
    assert "capabilities.devspace_version" in html
    assert "'victus-wsl'" in html
    assert "v3 Broker (EU)" in html and "v3 Broker (CN)" in html
    assert "EU compute target" not in html
    assert "pending agent" not in html
