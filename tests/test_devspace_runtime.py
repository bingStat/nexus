from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from nexus_v3 import agent, remote_control
from nexus_v3.broker import BrokerStore
from nexus_v3.common import Identity, verify_registration_payload


class FakeDevSpace:
    def call(self, operation: str, input_data: dict):
        return {"operation": operation, "input": input_data, "workspaceId": "ws_test"}


def test_broker_supports_structured_workspace_jobs_and_legacy_shell() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = BrokerStore(Path(tmp) / "broker.db")
        workspace_job = store.submit(
            {
                "target_device": "victus",
                "operation": "workspace.open",
                "input": {"path": "C:/work/nexus", "mode": "worktree"},
            }
        )
        assert workspace_job["target_device"] == "victus"
        assert workspace_job["operation"] == "workspace.open"
        assert workspace_job["input"]["mode"] == "worktree"

        shell_job = store.submit({"target_device": "n1", "command": "uptime"})
        assert shell_job["operation"] == "shell.execute"
        assert shell_job["input"] == {"command": "uptime"}


def test_agent_registration_capabilities_are_signed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        identity = Identity(Path(tmp) / "id", Path(tmp) / "id.pub")
        payload = agent.registration_with_capabilities(
            identity,
            "victus",
            "victus",
            "Windows",
            identity.public_key_pem,
            {"runtime": "devspace", "devspace_version": "1.0.6"},
        )
        verify_registration_payload(payload)
        assert payload["capabilities"]["runtime"] == "devspace"


def test_workspace_job_is_dispatched_to_devspace_not_shell() -> None:
    job = {
        "id": "job-1",
        "operation": "workspace.open",
        "input": {"path": "/work/project"},
        "timeout_ms": 30000,
    }
    with mock.patch.object(agent.subprocess, "run") as shell:
        status, exit_code, _output, result = agent.execute_job(job, FakeDevSpace())
    shell.assert_not_called()
    assert status == "completed"
    assert exit_code == 0
    assert result["operation"] == "workspace.open"


def test_workspace_operation_never_uses_managed_target_fallback(monkeypatch) -> None:
    requested = []

    def fake_request_json(method: str, url: str, body=None):
        requested.append((method, url, body))
        if "/v3/devices/n1/public-key" in url:
            return 200, {"device_id": "n1", "capabilities": {"runtime": "shell"}}
        raise AssertionError(url)

    monkeypatch.setattr(remote_control, "request_json", fake_request_json)
    try:
        remote_control.open_workspace("n1", "/tmp")
    except RuntimeError as exc:
        assert "does not advertise" in str(exc)
    else:
        raise AssertionError("shell-only target must reject workspace operations")
    assert all("thinkcenter" not in url for _method, url, _body in requested)


def test_devspace_dependency_is_pinned_and_not_vendored() -> None:
    root = Path(__file__).resolve().parents[1]
    package = json.loads((root / "runtime" / "devspace" / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["@waishnav/devspace"] == "1.0.6"
    assert not (root / "external" / "devspace").exists()
    bridge = (root / "runtime" / "devspace" / "bridge.mjs").read_text(encoding="utf-8")
    assert "@waishnav/devspace/dist/workspaces.js" in bridge
    assert "@waishnav/devspace/dist/process-sessions.js" in bridge
