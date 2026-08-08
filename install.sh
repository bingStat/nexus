#!/usr/bin/env bash
set -euo pipefail

DEVICE_ID="${1:-${NEXUS_DEVICE_ID:-}}"
API_URL="${NEXUS_API_URL:-https://nexus-global-api.bings.app}"
SOURCE_BASE="${NEXUS_SOURCE_BASE:-https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394}"
INSTALL_DIR="/opt/nexus-agent"
CONFIG_DIR="/etc/nexus-agent"
CONFIG_FILE="$CONFIG_DIR/config.json"
IDENTITY_KEY="$CONFIG_DIR/identity_ed25519"
IDENTITY_PUB="$CONFIG_DIR/identity_ed25519.pub"

fail() { printf 'nexus install: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail "run as root"
[ -n "$DEVICE_ID" ] || fail "device id required: install.sh <canonical-device-id>"
[ -n "$API_URL" ] || fail "NEXUS_API_URL is required"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"

case "$DEVICE_ID" in
  oracle|vsc|victus-wsl|elitebook|thinkcenter) ;;
  n1|ax3600) fail "use install-openwrt.sh for OpenWrt/iStoreOS devices" ;;
  *) fail "unsupported canonical device id: $DEVICE_ID" ;;
esac

[ ! -f /etc/openwrt_release ] || fail "use install-openwrt.sh on OpenWrt/iStoreOS"

case "$DEVICE_ID" in
  oracle|vsc|victus-wsl|elitebook) BROKER_URL="${NEXUS_BROKER_URL:-http://127.0.0.1:18000}" ;;
  thinkcenter) BROKER_URL="${NEXUS_BROKER_URL:-http://127.0.0.1:18000}" ;;
esac

mkdir -p "$INSTALL_DIR" "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
curl -fsSL "$SOURCE_BASE/agent/unix_agent.py" -o "$INSTALL_DIR/agent.py"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --disable-pip-version-check --quiet requests cryptography
python3 - "$CONFIG_FILE" "$DEVICE_ID" "$BROKER_URL" "$API_URL" "$IDENTITY_KEY" "$IDENTITY_PUB" <<'PY'
import json, os, sys
path, device_id, broker_url, api_url, identity_key, identity_pub = sys.argv[1:]
data = {
    "device_id": device_id,
    "device_name": device_id,
    "broker_urls": [broker_url.rstrip("/")],
    "api_url": api_url.rstrip("/"),
    "identity_key_path": identity_key,
    "identity_public_key_path": identity_pub,
    "poll_seconds": 0.5,
    "heartbeat_seconds": 30,
    "max_workers": 2,
    "ledger_path": "/var/lib/nexus-agent/execution_ledger.db",
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
os.chmod(path, 0o600)
PY
if [ ! -f "$IDENTITY_KEY" ]; then
  "$INSTALL_DIR/venv/bin/python" - "$IDENTITY_KEY" "$IDENTITY_PUB" <<'PY'
import os, sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
private_path, public_path = map(Path, sys.argv[1:])
private_path.parent.mkdir(parents=True, exist_ok=True)
key = Ed25519PrivateKey.generate()
private_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
public_path.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
os.chmod(private_path, 0o600)
os.chmod(public_path, 0o644)
os.chmod(private_path.parent, 0o700)
PY
fi

command -v systemctl >/dev/null 2>&1 || fail "systemd is required on Linux"
cat > /etc/systemd/system/nexus-agent.service <<'EOF'
[Unit]
Description=Nexus Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=NEXUS_CONFIG_FILE=/etc/nexus-agent/config.json
ExecStart=/opt/nexus-agent/venv/bin/python /opt/nexus-agent/agent.py
Restart=always
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable nexus-agent.service >/dev/null
systemctl restart nexus-agent.service
systemctl is-active --quiet nexus-agent.service

printf 'Nexus agent installed for %s\n' "$DEVICE_ID"
