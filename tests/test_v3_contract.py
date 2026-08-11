from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from nexus_v3 import agent as v3_agent
from nexus_v3.common import Identity, verify_http_signature, verify_registration_payload
from nexus_v3.registry import SSH_PUBLIC_KEY_RE


def test_v3_registration_and_http_signature_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        private_key = Path(tmp) / "identity_ed25519"
        public_key = Path(tmp) / "identity_ed25519.pub"
        identity = Identity(private_key, public_key)
        registration = identity.registration_payload("n1", "openwrt", "openwrt", "3.0.1-test", identity.public_key_pem)

        verify_registration_payload(registration)

        body = b'{"id":"job-1","status":"completed","exit_code":0,"output":"ok"}'
        headers = identity.sign_headers("n1", "POST", "/v3/jobs/complete", body)
        device_id = verify_http_signature(identity.public_key_pem, headers, "POST", "/v3/jobs/complete", body)

        assert device_id == "n1"
        assert registration["key_id"] == identity.key_id
        assert registration["public_key_ed25519"].startswith("ssh-ed25519 ")
        assert registration["ssh_public_key"] == registration["public_key_ed25519"]


def test_v3_rejects_stale_signature_timestamp() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        identity = Identity(Path(tmp) / "identity_ed25519", Path(tmp) / "identity_ed25519.pub")
        body = b""
        headers = identity.sign_headers("n1", "GET", "/v3/jobs/claim", body)
        headers["X-Nexus-Timestamp"] = "2000-01-01T00:00:00Z"

        with pytest.raises(PermissionError, match="outside allowed window"):
            verify_http_signature(identity.public_key_pem, headers, "GET", "/v3/jobs/claim", body)


def test_agent_command_argv_uses_platform_shell() -> None:
    if v3_agent.os.name == "nt":
        assert v3_agent.command_argv("echo ok")[-1] == "echo ok"
    else:
        assert v3_agent.command_argv("echo ok") == ["/bin/sh", "-c", "echo ok"]

    with mock.patch.object(v3_agent.os, "name", "nt"):
        with mock.patch.dict(v3_agent.os.environ, {}, clear=False):
            v3_agent.os.environ.pop("NEXUS_WINDOWS_SHELL", None)
            assert v3_agent.command_argv("Write-Output ok") == [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "Write-Output ok",
            ]

        with mock.patch.dict(v3_agent.os.environ, {"NEXUS_WINDOWS_SHELL": "cmd"}, clear=False):
            assert v3_agent.command_argv("echo ok") == ["cmd.exe", "/d", "/s", "/c", "echo ok"]


def test_v3_installers_are_separate_from_legacy_services() -> None:
    root = Path(__file__).resolve().parents[1]
    installer = (root / "install.sh").read_text(encoding="utf-8")
    agent = (root / "nexus_v3" / "assets" / "openwrt_v3_agent.sh").read_text(encoding="utf-8")
    python_agent = (root / "nexus_v3" / "agent.py").read_text(encoding="utf-8")
    broker = (root / "nexus_v3" / "broker.py").read_text(encoding="utf-8")

    assert "/v3/devices/register" in agent
    assert "/v3/jobs/claim" in agent
    assert "/v3/jobs/complete" in agent
    assert "nexus-v3-agent.service" in installer
    assert "install_openwrt_agent" in installer
    assert "openwrt-agent" in installer
    assert "cleanup_legacy" not in installer
    assert "managed-targets" not in installer
    assert "sync_ssh_authorized_keys.sh" in installer
    assert "sync-cluster-ssh" in installer
    assert "trigger_cluster_ssh_sync" in installer
    assert "identity_ed25519" in installer
    assert "OnUnitActiveSec" not in installer
    assert "*/5 * * * * /opt/nexus-agent/sync_ssh_authorized_keys.sh" not in installer
    assert "/api/devices/heartbeat" not in agent
    assert "/v3/devices/heartbeat" not in python_agent
    assert "agent_presence" in broker
    assert '"$BROKER_URL/claim' not in agent
    assert "require_success" in python_agent
    assert "subprocess.TimeoutExpired" in python_agent
    assert "ReplayGuard" in broker
    assert "signature nonce already used" in broker


def test_ssh_public_key_contract() -> None:
    assert SSH_PUBLIC_KEY_RE.match("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest nexus-test")
    root = Path(__file__).resolve().parents[1]
    registry = (root / "nexus_v3" / "registry.py").read_text(encoding="utf-8")
    installer = (root / "install.sh").read_text(encoding="utf-8")
    assert "/v3/ssh/authorized-keys" in registry
    assert "BEGIN NEXUS MANAGED SSH KEYS" in installer
    assert "authorized_keys" in installer
