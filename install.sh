#!/usr/bin/env bash
set -euo pipefail

DEVICE_ID="${1:-${NEXUS_DEVICE_ID:-}}"
BROKER_URL="${NEXUS_BROKER_URL:-}"
TOKEN="${NEXUS_BROKER_TOKEN:-}"
SOURCE_BASE="${NEXUS_SOURCE_BASE:-https://raw.githubusercontent.com/bingStat/nexus/main}"
INSTALL_DIR="/opt/nexus-agent"
CONFIG_FILE="/etc/nexus-agent/config.json"

fail() { printf 'nexus install: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail "run as root"
[ -n "$DEVICE_ID" ] || fail "device id required: install.sh <canonical-device-id>"
[ -n "$BROKER_URL" ] || fail "NEXUS_BROKER_URL is required"
[ -n "$TOKEN" ] || fail "NEXUS_BROKER_TOKEN is required"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"

case "$DEVICE_ID" in
  oracle|vsc|victus-wsl|elitebook|thinkcenter|n1|ax3600) ;;
  *) fail "unsupported canonical device id: $DEVICE_ID" ;;
esac

mkdir -p "$INSTALL_DIR" "$(dirname "$CONFIG_FILE")"
curl -fsSL "$SOURCE_BASE/agent/unix_agent.py" -o "$INSTALL_DIR/agent.py"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --disable-pip-version-check --quiet requests
python3 - "$CONFIG_FILE" "$DEVICE_ID" "$BROKER_URL" "$TOKEN" <<'PY'
import json, os, sys
path, device_id, broker_url, token = sys.argv[1:]
data = {
    "device_id": device_id,
    "device_name": device_id,
    "broker_urls": [broker_url.rstrip("/")],
    "api_token": token,
    "poll_seconds": 0.5,
    "heartbeat_seconds": 30,
    "max_workers": 2,
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
os.chmod(path, 0o600)
PY

if [ -f /etc/openwrt_release ]; then
  cat > /etc/init.d/nexus-agent <<'EOF'
#!/bin/sh /etc/rc.common
START=95
USE_PROCD=1
start_service() {
  procd_open_instance
  procd_set_param command /opt/nexus-agent/venv/bin/python /opt/nexus-agent/agent.py
  procd_set_param env NEXUS_CONFIG_FILE=/etc/nexus-agent/config.json
  procd_set_param respawn 5 5 0
  procd_set_param stdout 1
  procd_set_param stderr 1
  procd_close_instance
}
EOF
  chmod 755 /etc/init.d/nexus-agent
  /etc/init.d/nexus-agent enable
  /etc/init.d/nexus-agent restart
else
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
  systemctl enable --now nexus-agent.service
  systemctl is-active --quiet nexus-agent.service
fi

printf 'Nexus agent installed for %s\n' "$DEVICE_ID"
