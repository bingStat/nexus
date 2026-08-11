from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from nexus_v3.broker import BrokerStore
from nexus_v3.ledger import ExecutionLedger
from nexus_v3.status import annotate_device

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def test_device_status_preserves_vsc_threshold_policy() -> None:
    now = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
    def row(device: str, seconds: int):
        seen = (now - timedelta(seconds=seconds)).isoformat()
        return {"device_id": device, "status": "approved", "last_seen_at": seen}

    assert annotate_device(row("oracle", 89), now=now)["runtime_status"] == "online"
    assert annotate_device(row("oracle", 100), now=now)["runtime_status"] == "degraded"
    assert annotate_device(row("oracle", 301), now=now)["runtime_status"] == "offline"
    assert annotate_device(row("victus", 119), now=now)["runtime_status"] == "online"
    assert annotate_device(row("n1", 359), now=now)["runtime_status"] == "degraded"
    assert annotate_device(row("n1", 361), now=now)["runtime_status"] == "offline"


def test_broker_idempotency_and_stale_lease_recovery() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = BrokerStore(Path(tmp) / "broker.db")
        first = store.submit({
            "id": "job-1", "idempotency_key": "idem-1", "target_device": "victus",
            "operation": "shell.execute", "input": {"command": "echo ok"}, "timeout_ms": 1000,
        })
        duplicate = store.submit({
            "id": "job-1", "idempotency_key": "idem-1", "target_device": "victus",
            "operation": "shell.execute", "input": {"command": "echo ok"}, "timeout_ms": 1000,
        })
        assert duplicate["id"] == first["id"]
        claimed = store.claim("victus", "agent-a")
        assert claimed and claimed["attempt"] == 1 and claimed["lease_expires_at"]
        expired = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
        with store.connect() as db:
            db.execute("UPDATE jobs SET lease_expires_at=? WHERE id=?", (expired, "job-1"))
            db.commit()
        reclaimed = store.claim("victus", "agent-b")
        assert reclaimed and reclaimed["id"] == "job-1" and reclaimed["attempt"] == 2


def test_execution_ledger_replays_terminal_result_without_rerun() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ledger = ExecutionLedger(Path(tmp) / "ledger.db")
        job = {"id": "job-a", "operation": "shell.execute", "input": {"command": "echo once"}}
        state, _ = ledger.begin(job)
        assert state == "new"
        ledger.finish("job-a", "completed", 0, "once", {"output": "once", "exitCode": 0})
        state, cached = ledger.begin(job)
        assert state == "terminal"
        assert cached and cached["result"]["output"] == "once"
        conflicting = {"id": "job-a", "operation": "shell.execute", "input": {"command": "echo twice"}}
        assert ledger.begin(conflicting)[0] == "conflict"


def test_installers_keep_v3_identity_and_devspace_boundaries() -> None:
    linux = (ROOT / "install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "install.ps1").read_text(encoding="utf-8")
    openwrt = (ROOT / "nexus_v3" / "assets" / "openwrt_v3_agent.sh").read_text(encoding="utf-8")
    assert "devspace_runtime.py ledger.py" in linux
    assert "install.sh ops" in linux
    assert "NEXUS_DEVSPACE_ALLOWED_ROOTS" in linux
    assert "[string]$ApiToken" not in windows
    assert "NEXUS_API_TOKEN" not in windows
    assert "supabase.co" not in windows
    assert "https://nexus-eu-broker.bings.app" in windows
    assert "https://nexus-eu-broker.bings.app" in linux
    assert "Test-RuntimePython" in windows
    assert "UTF8Encoding($false)" in windows
    assert "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" in windows
    assert "schtasks.exe /Create" not in windows
    assert "$env:USERPROFILE\\.nexus-agent" in windows
    assert "identity_ed25519" in windows and "execution-ledger.db" in windows
    assert "/v3/devices/heartbeat" not in openwrt
    assert "NEXUS_HEARTBEAT_SECONDS" not in openwrt
    assert '"capabilities":{"runtime":"shell"}' in openwrt
    assert '"agent_version":"%s","capabilities":{"runtime":"shell"},"device_id":"%s"' in openwrt
    assert 'kill -0 "$old_pid"' in openwrt
    assert 'rm -rf "$LOCK_INSTANCE"' in openwrt
    cleanup = linux[linux.index("cleanup_retired_linux()"):linux.index("install_ssh_sync_script()")]
    assert "nexus-api-dns-failover.service" in cleanup
    assert "/opt/nexus-global-api" in cleanup
    assert "/opt/nexus-agent/backups" in cleanup
    assert "nexus-v3-agent.service" not in cleanup
    assert "nexus-public-guard.service" not in cleanup
    assert "nexus-health-snapshot.timer" not in cleanup
    assert "/var/lib/nexus-v3" not in cleanup
    broker = (ROOT / "nexus_v3" / "broker.py").read_text(encoding="utf-8")
    assert "agent_presence" in broker and "touch_presence" in broker


def test_ops_preserve_low_frequency_alert_cadence() -> None:
    systemd = ROOT / "ops" / "systemd"
    health = (systemd / "nexus-health-snapshot.timer").read_text(encoding="utf-8")
    alerts = (systemd / "nexus-alert-engine.timer").read_text(encoding="utf-8")
    telegram = (systemd / "nexus-telegram-bot.timer").read_text(encoding="utf-8")
    state = (systemd / "nexus-state-store.timer").read_text(encoding="utf-8")
    assert "OnUnitActiveSec=3min" in health
    assert "OnUnitActiveSec=3min" in alerts
    assert "OnUnitActiveSec=5min" in telegram
    assert "OnUnitActiveSec=5min" in state
    alert_code = (ROOT / "ops" / "monitoring" / "alerts.py").read_text(encoding="utf-8")
    telegram_code = (ROOT / "ops" / "monitoring" / "telegram.py").read_text(encoding="utf-8")
    assert "reopen_streak" in alert_code and "reopen_window_seconds" in alert_code
    assert "seen_event_ids" in telegram_code and "notification_version" in telegram_code


def test_remote_api_exposes_status_and_batch() -> None:
    from nexus_v3.chatgpt_api import openapi_document
    spec = openapi_document()
    operation_ids = {
        operation["operationId"]
        for methods in spec["paths"].values()
        for operation in methods.values()
        if isinstance(operation, dict) and "operationId" in operation
    }
    assert {"getFleetStatus", "executeBatch", "executeCommand", "executeRuntimeOperation"} <= operation_ids
