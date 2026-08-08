from __future__ import annotations

import tempfile
from pathlib import Path

from nexus_v3.common import Identity, verify_http_signature, verify_registration_payload


def test_v3_registration_and_http_signature_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        private_key = Path(tmp) / "identity_ed25519"
        public_key = Path(tmp) / "identity_ed25519.pub"
        identity = Identity(private_key, public_key)
        registration = identity.registration_payload("n1", "openwrt", "openwrt", "3.0.0-test")

        verify_registration_payload(registration)

        body = b'{"id":"job-1","status":"completed","exit_code":0,"output":"ok"}'
        headers = identity.sign_headers("n1", "POST", "/v3/jobs/complete", body)
        device_id = verify_http_signature(identity.public_key_pem, headers, "POST", "/v3/jobs/complete", body)

        assert device_id == "n1"
        assert registration["key_id"] == identity.key_id


def test_v3_installers_are_separate_from_legacy_services() -> None:
    root = Path(__file__).resolve().parents[1]
    linux = (root / "install-v3.sh").read_text(encoding="utf-8")
    openwrt = (root / "install-openwrt-v3.sh").read_text(encoding="utf-8")
    agent = (root / "openwrt_v3_agent.sh").read_text(encoding="utf-8")

    assert "/v3/devices/register" in agent
    assert "/v3/jobs/claim" in agent
    assert "/v3/jobs/complete" in agent
    assert "nexus-v3-agent.service" in linux
    assert "nexus-v3-agent" in openwrt
    assert "/api/devices/heartbeat" not in agent
    assert '"$BROKER_URL/claim' not in agent
