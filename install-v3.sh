#!/usr/bin/env bash
set -euo pipefail

DEVICE_ID="${1:-${NEXUS_DEVICE_ID:-}}"
REGISTRY_URL="${NEXUS_V3_REGISTRY_URL:-https://nexus-global-api.bings.app}"
BROKER_URL="${NEXUS_V3_BROKER_URL:-}"
SOURCE_BASE="${NEXUS_SOURCE_BASE:-https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394}"
INSTALL_DIR="/opt/nexus-agent"
PACKAGE_DIR="$INSTALL_DIR/nexus_v3"
CONFIG_DIR="/etc/nexus-agent"
CONFIG_FILE="$CONFIG_DIR/v3.json"
IDENTITY_KEY="$CONFIG_DIR/identity_ed25519"
IDENTITY_PUB="$CONFIG_DIR/identity_ed25519.pub"

fail() { printf 'nexus v3 install: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail "run with sudo/root"
[ -n "$DEVICE_ID" ] || fail "device id required: install-v3.sh <canonical-device-id>"

case "$DEVICE_ID" in
  thinkcenter) BROKER_URL="${BROKER_URL:-http://127.0.0.1:18120}" ;;
  oracle|oracle-amd) BROKER_URL="${BROKER_URL:-http://127.0.0.1:18102}" ;;
  *) BROKER_URL="${BROKER_URL:-https://nexus-broker.bings.app}" ;;
esac

mkdir -p "$PACKAGE_DIR" "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

for file in __init__.py common.py agent.py; do
  curl -fsSL "$SOURCE_BASE/nexus_v3/$file" -o "$PACKAGE_DIR/$file"
done

python3 - <<PY
import json
from pathlib import Path
config = {
    "device_id": "$DEVICE_ID",
    "registry_url": "$REGISTRY_URL".rstrip("/"),
    "broker_url": "$BROKER_URL".rstrip("/"),
    "identity_key": "$IDENTITY_KEY",
    "identity_public_key": "$IDENTITY_PUB",
    "wait_seconds": 20,
    "poll_seconds": 1,
    "request_timeout": 35,
}
Path("$CONFIG_FILE").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY
chmod 600 "$CONFIG_FILE"

if ! python3 - <<'PY' >/dev/null 2>&1
import cryptography, requests
PY
then
  if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv" || {
      if command -v apt-get >/dev/null 2>&1; then
        apt-get update
        apt-get install -y python3-venv
        python3 -m venv "$INSTALL_DIR/venv"
      else
        exit 1
      fi
    }
  fi
  "$INSTALL_DIR/venv/bin/python" -m pip install --upgrade pip >/dev/null
  "$INSTALL_DIR/venv/bin/python" -m pip install requests cryptography >/dev/null
  PYTHON="$INSTALL_DIR/venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

cat > /etc/systemd/system/nexus-v3-agent.service <<EOF
[Unit]
Description=Nexus v3 Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=NEXUS_V3_CONFIG=$CONFIG_FILE
WorkingDirectory=$INSTALL_DIR
ExecStart=$PYTHON -m nexus_v3.agent
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl stop nexus-v3-agent.service >/dev/null 2>&1 || true
ps w 2>/dev/null | awk '/[p]ython.*-m nexus_v3\.agent/ {print $1}' | while read -r pid; do
  [ -n "$pid" ] && kill "$pid" >/dev/null 2>&1 || true
done
systemctl daemon-reload
systemctl enable nexus-v3-agent.service >/dev/null
systemctl restart nexus-v3-agent.service
sleep 2
systemctl is-active --quiet nexus-v3-agent.service || fail "nexus-v3-agent did not start"
printf 'Nexus v3 agent installed for %s\n' "$DEVICE_ID"
printf 'Private key: %s\nPublic key: %s\nConfig: %s\n' "$IDENTITY_KEY" "$IDENTITY_PUB" "$CONFIG_FILE"
