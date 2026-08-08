from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent import unix_agent

ROOT = Path(__file__).resolve().parents[1]


class DeviceIdentityContractTests(unittest.TestCase):
    def test_identity_keypair_generates_public_key_and_stable_key_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            private_key = Path(tmp) / "identity_ed25519"
            public_key = Path(tmp) / "identity_ed25519.pub"
            identity = unix_agent.ensure_identity_keypair(private_key, public_key)

            self.assertTrue(private_key.exists())
            self.assertTrue(public_key.exists())
            self.assertTrue(identity.key_id.startswith("sha256:"))
            self.assertIn("BEGIN PRIVATE KEY", private_key.read_text(encoding="utf-8"))
            self.assertIn("BEGIN PUBLIC KEY", identity.public_key_pem)

    def test_signed_headers_verify_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            private_key = Path(tmp) / "identity_ed25519"
            public_key = Path(tmp) / "identity_ed25519.pub"
            identity = unix_agent.ensure_identity_keypair(private_key, public_key)
            body = json.dumps({"status": "online"}, separators=(",", ":")).encode("utf-8")

            headers = unix_agent.build_signed_headers(
                identity=identity,
                device_id="oracle",
                method="POST",
                path_and_query="/api/devices/heartbeat",
                body=body,
                timestamp="2026-08-08T10:00:00Z",
                nonce="unit-test-nonce",
            )

            self.assertEqual(headers["X-Nexus-Device"], "oracle")
            self.assertEqual(headers["X-Nexus-Key-Id"], identity.key_id)
            self.assertEqual(headers["X-Nexus-Timestamp"], "2026-08-08T10:00:00Z")
            self.assertEqual(headers["X-Nexus-Nonce"], "unit-test-nonce")
            self.assertTrue(headers["X-Nexus-Signature"])
            self.assertTrue(unix_agent.verify_signed_headers_for_test(identity.public_key_pem, headers, "POST", "/api/devices/heartbeat", body))

    def test_installers_no_longer_require_or_store_agent_token(self) -> None:
        linux = (ROOT / "install.sh").read_text(encoding="utf-8")
        windows = (ROOT / "install.ps1").read_text(encoding="utf-8")
        openwrt = (ROOT / "install-openwrt.sh").read_text(encoding="utf-8")

        self.assertNotIn("NEXUS_API_TOKEN or NEXUS_BROKER_TOKEN is required", linux)
        self.assertNotIn("api_token", linux)
        self.assertNotIn("[string]$Token", windows)
        self.assertNotIn("api_token", windows)
        self.assertNotIn("NEXUS_API_TOKEN", openwrt)
        self.assertIn("identity_ed25519", linux)
        self.assertIn("identity_ed25519", windows)
        self.assertIn("identity_ed25519", openwrt)

    def test_openwrt_installer_downloads_dedicated_ed25519_signer(self) -> None:
        installer = (ROOT / "install-openwrt.sh").read_text(encoding="utf-8")
        agent = (ROOT / "openwrt_agent.sh").read_text(encoding="utf-8")
        signer = ROOT / "openwrt_ed25519_signer.rb"

        self.assertTrue(signer.exists())
        self.assertIn("openwrt_ed25519_signer.rb", installer)
        self.assertIn("NEXUS_ED25519_SIGNER", installer)
        self.assertIn("ruby \"$ED25519_SIGNER\" sign", agent)
        self.assertIn("ruby \"$ED25519_SIGNER\" key-id", agent)


if __name__ == "__main__":
    unittest.main()
