#!/bin/sh
set -eu

SOURCE_BASE="${NEXUS_SOURCE_BASE:-https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394}"
INSTALL_DIR="${NEXUS_V3_MCP_INSTALL_DIR:-/opt/nexus-v3-mcp}"
ENV_FILE="${NEXUS_V3_MCP_ENV_FILE:-/etc/nexus-v3-mcp.env}"
V3_ENV_FILE="${NEXUS_V3_ENV_FILE:-/etc/nexus-v3.env}"
PYTHON="${PYTHON:-python3}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi
command -v "$PYTHON" >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 1; }

mkdir -p "$INSTALL_DIR/nexus_v3"
curl -fsSL "$SOURCE_BASE/nexus_v3/mcp_server.py" -o "$INSTALL_DIR/nexus_v3/mcp_server.py"
curl -fsSL "$SOURCE_BASE/nexus_v3/__init__.py" -o "$INSTALL_DIR/nexus_v3/__init__.py"

if ! "$PYTHON" -m venv "$INSTALL_DIR/.venv" 2>/dev/null; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y python3-venv
    "$PYTHON" -m venv "$INSTALL_DIR/.venv"
  else
    echo "python3-venv is required" >&2
    exit 1
  fi
fi
"$INSTALL_DIR/.venv/bin/pip" install --disable-pip-version-check --no-cache-dir "mcp[cli]>=1.26,<2"

ADMIN_KEY="${NEXUS_V3_ADMIN_KEY:-}"
if [ -z "$ADMIN_KEY" ] && [ -r "$V3_ENV_FILE" ]; then
  ADMIN_KEY=$(sed -n 's/^NEXUS_V3_ADMIN_KEY=//p' "$V3_ENV_FILE" | tail -n 1)
fi
[ -n "$ADMIN_KEY" ] || { echo "NEXUS_V3_ADMIN_KEY is unavailable" >&2; exit 1; }

umask 077
cat > "$ENV_FILE" <<EOF
NEXUS_V3_ADMIN_KEY=$ADMIN_KEY
NEXUS_V3_REGISTRY_URL=${NEXUS_V3_REGISTRY_URL:-http://127.0.0.1:18101}
NEXUS_V3_EU_BROKER_URL=${NEXUS_V3_EU_BROKER_URL:-http://127.0.0.1:18102}
NEXUS_V3_CN_BROKER_URL=${NEXUS_V3_CN_BROKER_URL:-http://100.103.12.14:18120}
NEXUS_V3_MCP_BIND=${NEXUS_V3_MCP_BIND:-127.0.0.1}
NEXUS_V3_MCP_PORT=${NEXUS_V3_MCP_PORT:-18130}
NEXUS_V3_ALLOW_DANGEROUS=${NEXUS_V3_ALLOW_DANGEROUS:-0}
EOF
chmod 600 "$ENV_FILE"

cat > /etc/systemd/system/nexus-v3-mcp.service <<EOF
[Unit]
Description=Nexus v3 MCP Adapter
After=network-online.target nexus-v3-registry.service nexus-v3-eu-broker.service
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$ENV_FILE
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python -m nexus_v3.mcp_server
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_DIR

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable nexus-v3-mcp.service >/dev/null
systemctl restart nexus-v3-mcp.service
sleep 2
systemctl is-active nexus-v3-mcp.service
curl -fsS "http://${NEXUS_V3_MCP_BIND:-127.0.0.1}:${NEXUS_V3_MCP_PORT:-18130}/mcp" -o /dev/null || true
echo "Nexus v3 MCP installed at http://${NEXUS_V3_MCP_BIND:-127.0.0.1}:${NEXUS_V3_MCP_PORT:-18130}/mcp"
