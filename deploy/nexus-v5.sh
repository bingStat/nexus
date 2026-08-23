#!/bin/sh
set -eu

ROLE="${NEXUS_ROLE:-worker}"
DEVICE_ID="${NEXUS_DEVICE_ID:-$(hostname | tr '[:upper:]' '[:lower:]')}"
REF="${NEXUS_REF:-nexus-v5-minimal}"
PYTHON="${PYTHON:-python3}"

fail() { printf 'nexus-v5 install: %s\n' "$*" >&2; exit 1; }
command -v "$PYTHON" >/dev/null 2>&1 || fail "python3 is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"

if [ "$(id -u)" -eq 0 ]; then
  ROOT="${NEXUS_INSTALL_ROOT:-/opt/nexus-v5}"
  CONF="${NEXUS_CONFIG_ROOT:-/etc/nexus-v5}"
  STATE="${NEXUS_STATE_ROOT:-/var/lib/nexus-v5}"
else
  ROOT="${NEXUS_INSTALL_ROOT:-$HOME/.local/share/nexus-v5}"
  CONF="${NEXUS_CONFIG_ROOT:-$HOME/.config/nexus-v5}"
  STATE="${NEXUS_STATE_ROOT:-$HOME/.local/state/nexus-v5}"
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT INT TERM
curl -fsSL "https://github.com/bingStat/nexus/archive/${REF}.tar.gz" -o "$TMP/nexus.tar.gz"
tar -xzf "$TMP/nexus.tar.gz" -C "$TMP"
SRC="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -1)"
[ -d "$SRC/nexus_v5" ] || fail "nexus_v5 source missing from $REF"
mkdir -p "$ROOT" "$CONF" "$STATE"
rm -rf "$ROOT/nexus_v5" "$ROOT/nexus_v3" "$ROOT/runtime"
cp -R "$SRC/nexus_v5" "$SRC/nexus_v3" "$SRC/runtime" "$ROOT/"
printf '%s\n' "$REF" > "$ROOT/DEPLOYED_REF"

TOKEN_FILE="$CONF/token"
if [ -n "${NEXUS_TOKEN_SOURCE:-}" ]; then
  cp "$NEXUS_TOKEN_SOURCE" "$TOKEN_FILE"
elif [ -n "${NEXUS_V5_TOKEN:-}" ]; then
  umask 077
  printf '%s\n' "$NEXUS_V5_TOKEN" > "$TOKEN_FILE"
elif [ ! -s "$TOKEN_FILE" ]; then
  umask 077
  "$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(32))' > "$TOKEN_FILE"
fi
chmod 600 "$TOKEN_FILE"

retire_v3() {
  [ "${NEXUS_RETIRE_V3:-0}" = "1" ] || return 0
  if command -v systemctl >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
    for unit in nexus-v3-agent nexus-v3-mcp nexus-v3-registry nexus-v3-eu-broker nexus-v3-cn-broker nexus-chatgpt-remote nexus-v5-agent nexus-v5-direct; do
      systemctl disable --now "$unit.service" >/dev/null 2>&1 || true
    done
  else
    pkill -f 'python.*-m nexus_v3.agent' >/dev/null 2>&1 || true
  fi
}

if [ "$ROLE" = "ssh-only" ]; then
  retire_v3
  printf 'nexus-v5: %s configured as ssh-only; no agent installed\n' "$DEVICE_ID"
  exit 0
fi

if [ "$ROLE" = "worker" ]; then
  BIND="${NEXUS_BIND:-}"
  if [ -z "$BIND" ] && command -v tailscale >/dev/null 2>&1; then
    BIND="$(tailscale ip -4 2>/dev/null | head -1 || true)"
  fi
  [ -n "$BIND" ] || BIND="127.0.0.1"
  DEVSPACE="${NEXUS_DEVSPACE:-1}"
  DEVSPACE_JSON=""
  if [ "$DEVSPACE" = "1" ]; then
    NODE_BIN="${NEXUS_NODE:-$(command -v node 2>/dev/null || true)}"
    NPM_BIN="${NEXUS_NPM:-$(command -v npm 2>/dev/null || true)}"
    [ -n "$NODE_BIN" ] || fail "node is required for DevSpace worker mode"
    [ -n "$NPM_BIN" ] || fail "npm is required for DevSpace worker mode"
    (cd "$ROOT/runtime/devspace" && "$NPM_BIN" install --no-audit --no-fund >/dev/null)
    ALLOWED="${NEXUS_DEVSPACE_ALLOWED_ROOTS:-/}"
    DEVSPACE_JSON=",
  \"devspace\": {
    \"bridge\": \"$ROOT/runtime/devspace/bridge.mjs\",
    \"node\": \"$NODE_BIN\",
    \"allowed_roots\": [\"$ALLOWED\"],
    \"state_dir\": \"$STATE/devspace\"
  }"
  fi
  cat > "$CONF/worker.json" <<EOF
{
  "device_id": "$DEVICE_ID",
  "token_file": "$TOKEN_FILE",
  "bind": "$BIND",
  "port": 18505$DEVSPACE_JSON
}
EOF

  if command -v systemctl >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
    for old in nexus-v5-agent nexus-v5-direct; do
      systemctl disable --now "$old.service" >/dev/null 2>&1 || true
    done
    cat > /etc/systemd/system/nexus-v5-worker.service <<EOF
[Unit]
Description=Nexus v5 direct worker
After=network-online.target tailscaled.service
Wants=network-online.target
[Service]
Type=simple
Environment=PYTHONPATH=$ROOT
WorkingDirectory=$ROOT
ExecStart=$PYTHON -m nexus_v5.worker --config $CONF/worker.json
Restart=always
RestartSec=1
[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now nexus-v5-worker.service
  else
    pkill -f 'python.*-m nexus_v5.agent' >/dev/null 2>&1 || true
    pkill -f 'python.*-m nexus_v5.direct_server' >/dev/null 2>&1 || true
    cat > "$ROOT/run-worker.sh" <<EOF
#!/bin/sh
exec env PYTHONPATH="$ROOT" "$PYTHON" -m nexus_v5.worker --config "$CONF/worker.json"
EOF
    chmod 755 "$ROOT/run-worker.sh"
    pkill -f "nexus_v5.worker --config $CONF/worker.json" >/dev/null 2>&1 || true
    nohup "$ROOT/run-worker.sh" > "$STATE/worker.log" 2>&1 </dev/null &
    if command -v crontab >/dev/null 2>&1; then
      (crontab -l 2>/dev/null | grep -v 'nexus-v5/current/run-worker.sh' || true; printf '@reboot %s\n' "$ROOT/run-worker.sh") | crontab -
    fi
  fi
  retire_v3
  printf 'nexus-v5: worker %s installed at %s:%s\n' "$DEVICE_ID" "$BIND" 18505
  exit 0
fi

if [ "$ROLE" = "controller" ]; then
  [ "$(id -u)" -eq 0 ] || fail "controller install requires root"
  cp "$SRC/deploy/routes.v5.json" "$CONF/routes.json"
  chmod 600 "$CONF/routes.json"
  cat > /etc/systemd/system/nexus-v5-api.service <<EOF
[Unit]
Description=Nexus v5 ChatGPT control plane
After=network-online.target tailscaled.service
Wants=network-online.target
[Service]
Type=simple
EnvironmentFile=-/etc/nexus-chatgpt-remote.env
Environment=PYTHONPATH=$ROOT
Environment=NEXUS_V5_ROUTES=$CONF/routes.json
Environment=NEXUS_V5_TOKEN_FILE=$TOKEN_FILE
Environment=NEXUS_V5_API_BIND=127.0.0.1
Environment=NEXUS_V5_API_PORT=18131
WorkingDirectory=$ROOT
ExecStart=$PYTHON -m nexus_v5.api
Restart=always
RestartSec=1
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable nexus-v5-api.service >/dev/null
  if [ "${NEXUS_ACTIVATE:-0}" = "1" ]; then
    systemctl stop nexus-chatgpt-remote.service >/dev/null 2>&1 || true
    systemctl restart nexus-v5-api.service
  fi
  retire_v3
  printf 'nexus-v5: controller staged at %s; activate=%s\n' "$ROOT" "${NEXUS_ACTIVATE:-0}"
  exit 0
fi

fail "unknown NEXUS_ROLE=$ROLE"
