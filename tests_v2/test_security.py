from datetime import datetime, timezone

from mcp_server.models import DeviceState, derive_device_state
from mcp_server.security import validate_command


def test_device_state_thresholds():
    now = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
    assert derive_device_state("2026-07-31T09:59:30+00:00", now) is DeviceState.online
    assert derive_device_state("2026-07-31T09:58:00+00:00", now) is DeviceState.degraded
    assert derive_device_state("2026-07-31T09:50:00+00:00", now) is DeviceState.offline


def test_cross_node_ssh_is_rejected():
    allowed, reason, _ = validate_command("ssh root@n1 uname -a")
    assert not allowed and "Cross-node" in reason


def test_privileged_requires_flag():
    allowed, _, risk = validate_command("systemctl restart cloudflared")
    assert not allowed and risk.value == "privileged"
    allowed, _, _ = validate_command(
        "systemctl restart cloudflared", allow_privileged=True
    )
    assert allowed


def test_destructive_requires_separate_flag():
    allowed, _, risk = validate_command("rm -rf /")
    assert not allowed and risk.value == "destructive"


def test_read_only_is_allowed():
    allowed, _, risk = validate_command("systemctl status cloudflared")
    assert allowed and risk.value == "read_only"
