#!/usr/bin/env bash
set -euo pipefail

SOURCE_BASE="${NEXUS_SOURCE_BASE:-https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394}"
INSTALL_DIR="${NEXUS_V3_INSTALL_DIR:-/opt/nexus-v3}"
PACKAGE_DIR="$INSTALL_DIR/nexus_v3"
ENV_FILE="${NEXUS_V3_ENV_FILE:-/etc/nexus-v3.env}"
DB_PATH="${NEXUS_V3_BROKER_DB:-/var/lib/nexus-v3/broker.db}"
BIND="${NEXUS_V3_BIND:-127.0.0.1}"
PORT="${NEXUS_V3_BROKER_PORT:-18120}"
REGION="${NEXUS_V3_REGION:-cn}"
REGISTRY_URL="${NEXUS_V3_REGISTRY_URL:-http://127.0.0.1:18101}"
SERVICE_NAME="${NEXUS_V3_BROKER_SERVICE:-nexus-v3-broker}"

fail() { printf 'nexus v3 broker install: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail "run with sudo/root"

mkdir -p "$PACKAGE_DIR" "$(dirname "$DB_PATH")" "$(dirname "$ENV_FILE")"
for file in __init__.py common.py broker.py; do
  curl -fsSL "$SOURCE_BASE/nexus_v3/$file" -o "$PACKAGE_DIR/$file"
done

[ -f "$ENV_FILE" ] || touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

cat > "/etc/systemd/system/$SERVICE_NAME.service" <<EOF
[Unit]
Description=Nexus v3 Broker ($REGION)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$ENV_FILE
Environment=NEXUS_V3_REGION=$REGION
Environment=NEXUS_V3_REGISTRY_URL=$REGISTRY_URL
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 -m nexus_v3.broker --bind $BIND --port $PORT --db $DB_PATH
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl stop "$SERVICE_NAME.service" >/dev/null 2>&1 || true
ps w 2>/dev/null | awk '/[p]ython3 -m nexus_v3\.broker/ {print $1}' | while read -r pid; do
  [ -n "$pid" ] && kill "$pid" >/dev/null 2>&1 || true
done
systemctl daemon-reload
systemctl enable "$SERVICE_NAME.service" >/dev/null
systemctl restart "$SERVICE_NAME.service"
sleep 2
systemctl is-active --quiet "$SERVICE_NAME.service" || fail "broker service did not start"
curl -fsS "http://127.0.0.1:$PORT/v3/health" >/dev/null
printf 'Nexus v3 broker installed on %s:%s (region=%s, registry=%s)\n' "$BIND" "$PORT" "$REGION" "$REGISTRY_URL"
