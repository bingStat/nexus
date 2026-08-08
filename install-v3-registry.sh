#!/usr/bin/env bash
set -euo pipefail

SOURCE_BASE="${NEXUS_SOURCE_BASE:-https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394}"
INSTALL_DIR="${NEXUS_V3_INSTALL_DIR:-/opt/nexus-v3}"
PACKAGE_DIR="$INSTALL_DIR/nexus_v3"
ENV_FILE="${NEXUS_V3_ENV_FILE:-/etc/nexus-v3.env}"
DB_PATH="${NEXUS_V3_REGISTRY_DB:-/var/lib/nexus-v3/registry.db}"
BIND="${NEXUS_V3_BIND:-0.0.0.0}"
PORT="${NEXUS_V3_REGISTRY_PORT:-18101}"
SERVICE_NAME="${NEXUS_V3_REGISTRY_SERVICE:-nexus-v3-registry}"

fail() { printf 'nexus v3 registry install: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail "run with sudo/root"

mkdir -p "$PACKAGE_DIR" "$(dirname "$DB_PATH")" "$(dirname "$ENV_FILE")"
for file in __init__.py common.py registry.py; do
  curl -fsSL "$SOURCE_BASE/nexus_v3/$file" -o "$PACKAGE_DIR/$file"
done

if [ ! -f "$ENV_FILE" ] || ! grep -q '^NEXUS_V3_ADMIN_KEY=' "$ENV_FILE"; then
  key="$(openssl rand -hex 32)"
  {
    [ -f "$ENV_FILE" ] && cat "$ENV_FILE"
    printf 'NEXUS_V3_ADMIN_KEY=%s\n' "$key"
  } | awk '!seen[$0]++' > "$ENV_FILE.tmp"
  mv "$ENV_FILE.tmp" "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

cat > "/etc/systemd/system/$SERVICE_NAME.service" <<EOF
[Unit]
Description=Nexus v3 Registry
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$ENV_FILE
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 -m nexus_v3.registry --bind $BIND --port $PORT --db $DB_PATH
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl stop "$SERVICE_NAME.service" >/dev/null 2>&1 || true
ps w 2>/dev/null | awk '/[p]ython3 -m nexus_v3\.registry/ {print $1}' | while read -r pid; do
  [ -n "$pid" ] && kill "$pid" >/dev/null 2>&1 || true
done
systemctl daemon-reload
systemctl enable "$SERVICE_NAME.service" >/dev/null
systemctl restart "$SERVICE_NAME.service"
sleep 2
systemctl is-active --quiet "$SERVICE_NAME.service" || fail "registry service did not start"
curl -fsS "http://127.0.0.1:$PORT/v3/health" >/dev/null
printf 'Nexus v3 registry installed on %s:%s\n' "$BIND" "$PORT"
