from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from nexus_v3.broker import BrokerStore
from nexus_v3 import remote_control


def test_broker_presence_is_updated_without_extra_heartbeat(tmp_path: Path) -> None:
    store = BrokerStore(tmp_path / "broker.db")
    store.touch_presence("victus", "victus:host:123")

    rows = store.list_presence()
    assert len(rows) == 1
    assert rows[0]["device_id"] == "victus"
    assert rows[0]["agent_id"] == "victus:host:123"
    assert rows[0]["last_seen"]


def test_device_status_uses_broker_presence_not_registry_updated_at(monkeypatch) -> None:
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent = datetime.now(timezone.utc).isoformat()

    def fake_request_json(method: str, url: str, body=None):
        if "/v3/admin/devices" in url:
            return 200, {"devices": [{"device_id": "victus", "status": "approved", "updated_at": old}]}
        if url.endswith("/v3/agents") and "18102" in url:
            return 200, {"agents": [{"device_id": "victus", "agent_id": "victus:host:123", "last_seen": recent}]}
        if url.endswith("/v3/agents"):
            return 200, {"agents": []}
        raise AssertionError(url)

    monkeypatch.setattr(remote_control, "request_json", fake_request_json)
    payload = remote_control.list_devices("approved")
    device = payload["devices"][0]

    assert device["runtime_status"] == "online"
    assert device["presence_source"] == "broker-long-poll"
    assert device["last_seen_at"] == recent
    assert device["updated_at"] == old


def test_missing_presence_is_unknown_even_if_registry_update_is_recent(monkeypatch) -> None:
    recent = datetime.now(timezone.utc).isoformat()

    def fake_request_json(method: str, url: str, body=None):
        if "/v3/admin/devices" in url:
            return 200, {"devices": [{"device_id": "oracle", "status": "approved", "updated_at": recent}]}
        if url.endswith("/v3/agents"):
            return 200, {"agents": []}
        raise AssertionError(url)

    monkeypatch.setattr(remote_control, "request_json", fake_request_json)
    device = remote_control.list_devices("approved")["devices"][0]
    assert device["runtime_status"] == "unknown"
    assert device["presence_source"] == "none"
