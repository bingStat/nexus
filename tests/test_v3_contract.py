from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from nexus_v3 import agent as v3_agent
from nexus_v3.common import Identity, device_key_hash, verify_device_key
from nexus_v3.registry import RegistryStore, SSH_PUBLIC_KEY_RE


def test_v3_registration_and_device_key_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        identity = Identity(Path(tmp) / "device.key")
        registration = identity.registration_payload(
            "n1", "openwrt", "openwrt", "3.2.0-test",
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest nexus-n1",
        )
        assert registration["device_key"] == identity.key
        assert device_key_hash(identity.key) == identity.key_id
        assert registration["ssh_public_key"].startswith("ssh-ed25519 ")

        headers = identity.auth_headers("n1")
        assert verify_device_key(identity.key_id, headers) == "n1"


def test_registry_schema_has_no_legacy_signing_public_key() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "registry.db"
        store = RegistryStore(db_path)
        db = sqlite3.connect(db_path)
        try:
            columns = {row[1] for row in db.execute("PRAGMA table_info(devices)").fetchall()}
        finally:
            db.close()
        assert "public_key_ed25519" not in columns

        identity = Identity(Path(tmp) / "device.key")
        row = store.register(
            identity.registration_payload(
                "test-node", "test-host", "linux", "3.2.1-test",
                "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest nexus-test",
            )
        )
        assert row["key_id"] == identity.key_id
        assert "public_key_ed25519" not in row


def test_registry_handler_matches_store_get_contract() -> None:
    registry = (Path(__file__).resolve().parents[1] / "nexus_v3" / "registry.py").read_text(encoding="utf-8")
    assert "include_key=False" not in registry


def test_v3_rejects_wrong_device_key() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        identity = Identity(Path(tmp) / "device.key")
        other = Identity(Path(tmp) / "other.key")
        headers = other.auth_headers("n1")
        with pytest.raises(PermissionError, match="authentication failed"):
            verify_device_key(identity.key_id, headers) == "n1"

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


def test_agent_decodes_subprocess_output_without_crashing() -> None:
    assert v3_agent.decode_process_output("plain utf8".encode("utf-8")) == "plain utf8"
    assert "bad" in v3_agent.decode_process_output(b"bad\x8foutput")


def test_windows_installer_uses_task_scheduler_as_single_supervisor() -> None:
    root = Path(__file__).resolve().parents[1]
    installer = (root / "install.ps1").read_text(encoding="utf-8")

    assert "Register-ScheduledTask" in installer
    assert '"NexusV3Agent"' in installer
    assert "MultipleInstances" in installer
    assert "RestartCount" in installer
    assert "run-agent.ps1" in installer
    assert "New-ItemProperty -Path $RunKey" not in installer
    assert "New-ItemProperty -Path \"HKCU:" not in installer
    assert "$VbsRunner" not in installer
    assert "WshShell.Run" not in installer
    assert ":restart" not in installer
    assert "timeout /t" not in installer
    assert "$clusterColor = if" in installer
    assert "-ForegroundColor (if" not in installer


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
    assert "install_user_agent" in installer
    assert "user-agent" in installer
    assert "https://raw.githubusercontent.com/bingStat/nexus/main" in installer
    assert "https://nexus.bings.app/bootstrap" not in installer
    assert "cleanup_legacy" not in installer
    assert "managed-targets" not in installer
    assert "sync_ssh_authorized_keys.sh" in installer
    assert "sync-cluster-ssh" in installer
    assert "trigger_cluster_ssh_sync" in installer
    assert "device.key" in installer
    assert "identity_key" not in installer
    assert "NEXUS_IDENTITY" not in installer
    assert "nexus-functional-watchdog" in installer
    assert "NEXUS_INSTALL_FUNCTIONAL_WATCHDOG" in installer
    assert "nexus-v3-agent.timer" not in installer
    assert "*/5 * * * * /opt/nexus-agent/sync_ssh_authorized_keys.sh" not in installer
    assert "/api/devices/heartbeat" not in agent
    assert "/v3/devices/heartbeat" not in python_agent
    assert "agent_presence" in broker
    assert '"$BROKER_URL/claim' not in agent
    assert "require_success" in python_agent
    assert "subprocess.TimeoutExpired" in python_agent
    assert "verify_device_key" in broker
    assert "ReplayGuard" not in broker
    assert "X-Nexus-Signature" not in broker


def test_ssh_public_key_contract() -> None:
    assert SSH_PUBLIC_KEY_RE.match("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest nexus-test")
    root = Path(__file__).resolve().parents[1]
    registry = (root / "nexus_v3" / "registry.py").read_text(encoding="utf-8")
    installer = (root / "install.sh").read_text(encoding="utf-8")
    assert "/v3/ssh/authorized-keys" in registry
    assert "BEGIN NEXUS MANAGED SSH KEYS" in installer
    assert "authorized_keys" in installer
