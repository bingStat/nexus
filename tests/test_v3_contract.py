from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from nexus_v3.common import Identity, verify_http_signature, verify_registration_payload


def test_v3_registration_and_http_signature_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        private_key = Path(tmp) / "identity_ed25519"
        public_key = Path(tmp) / "identity_ed25519.pub"
        identity = Identity(private_key, public_key)
        registration = identity.registration_payload("n1", "openwrt", "openwrt", "3.0.1-test")

        verify_registration_payload(registration)

        body = b'{"id":"job-1","status":"completed","exit_code":0,"output":"ok"}'
        headers = identity.sign_headers("n1", "POST", "/v3/jobs/complete", body)
        device_id = verify_http_signature(identity.public_key_pem, headers, "POST", "/v3/jobs/complete", body)

        assert device_id == "n1"
        assert registration["key_id"] == identity.key_id


def test_v3_rejects_stale_signature_timestamp() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        identity = Identity(Path(tmp) / "identity_ed25519", Path(tmp) / "identity_ed25519.pub")
        body = b""
        headers = identity.sign_headers("n1", "GET", "/v3/jobs/claim", body)
        headers["X-Nexus-Timestamp"] = "2000-01-01T00:00:00Z"

        with pytest.raises(PermissionError, match="outside allowed window"):
            verify_http_signature(identity.public_key_pem, headers, "GET", "/v3/jobs/claim", body)


def test_v3_installers_are_separate_from_legacy_services() -> None:
    root = Path(__file__).resolve().parents[1]
    linux = (root / "install-v3.sh").read_text(encoding="utf-8")
    openwrt = (root / "install-openwrt-v3.sh").read_text(encoding="utf-8")
    agent = (root / "openwrt_v3_agent.sh").read_text(encoding="utf-8")
    python_agent = (root / "nexus_v3" / "agent.py").read_text(encoding="utf-8")
    broker = (root / "nexus_v3" / "broker.py").read_text(encoding="utf-8")

    assert "/v3/devices/register" in agent
    assert "/v3/jobs/claim" in agent
    assert "/v3/jobs/complete" in agent
    assert "nexus-v3-agent.service" in linux
    assert "nexus-v3-agent" in openwrt
    assert "/api/devices/heartbeat" not in agent
    assert '"$BROKER_URL/claim' not in agent
    assert "require_success" in python_agent
    assert "subprocess.TimeoutExpired" in python_agent
    assert "ReplayGuard" in broker
    assert "signature nonce already used" in broker
