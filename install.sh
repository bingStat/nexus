#!/bin/sh
set -eu

SOURCE_BASE="${NEXUS_SOURCE_BASE:-https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"

fail() { printf 'nexus install: %s\n' "$*" >&2; exit 1; }
need_root() { [ "$(id -u)" -eq 0 ] || fail "run with sudo/root"; }
have_local() { [ -f "$SCRIPT_DIR/$1" ]; }
copy_or_fetch() {
  src="$1"
  dst="$2"
  if have_local "$src"; then
    cp "$SCRIPT_DIR/$src" "$dst"
  else
    curl -fsSL "$SOURCE_BASE/$src" -o "$dst"
  fi
}
append_env_once() {
  file="$1"
  key="$2"
  value="$3"
  touch "$file"
  if grep -q "^$key=" "$file"; then
    tmp="$file.tmp.$$"
    awk -v k="$key" -v v="$value" 'BEGIN{p=k"="v} $0 ~ "^" k "=" {print p; next} {print}' "$file" > "$tmp"
    mv "$tmp" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}
install_python_package() {
  install_dir="$1"
  shift
  mkdir -p "$install_dir/nexus_v3"
  for file in "$@"; do
    copy_or_fetch "nexus_v3/$file" "$install_dir/nexus_v3/$file"
  done
}

install_ssh_sync_script() {
  install_dir="$1"
  registry_url="$2"
  mkdir -p "$install_dir"
cat > "$install_dir/sync_ssh_authorized_keys.sh" <<'EOF'
#!/bin/sh
set -eu

ENV_FILE="${NEXUS_SSH_SYNC_ENV:-/etc/nexus-agent/ssh-sync.env}"
OVERRIDE_REGISTRY_URL="${NEXUS_V3_REGISTRY_URL:-}"
[ -r "$ENV_FILE" ] && . "$ENV_FILE"
REGISTRY_URL="${OVERRIDE_REGISTRY_URL:-${NEXUS_V3_REGISTRY_URL:-}}"
[ -n "$REGISTRY_URL" ] || { echo "NEXUS_V3_REGISTRY_URL is required" >&2; exit 1; }

target_home="${NEXUS_SSH_AUTHORIZED_HOME:-/root}"
auth_file="${NEXUS_SSH_AUTHORIZED_KEYS_FILE:-$target_home/.ssh/authorized_keys}"
ssh_dir="$(dirname "$auth_file")"
keys_file="/tmp/nexus-authorized-keys.$$"
tmp_file="/tmp/nexus-authorized-keys-out.$$"
begin="### BEGIN NEXUS MANAGED SSH KEYS"
end="### END NEXUS MANAGED SSH KEYS"

cleanup() {
  rm -f "$keys_file" "$tmp_file" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

curl -fsS "$REGISTRY_URL/v3/ssh/authorized-keys" -o "$keys_file"
mkdir -p "$ssh_dir"
chmod 700 "$ssh_dir"
touch "$auth_file"
awk -v begin="$begin" -v end="$end" '
  $0 == begin {skip=1; next}
  $0 == end {skip=0; next}
  skip != 1 {print}
' "$auth_file" > "$tmp_file"
{
  cat "$tmp_file"
  printf "%s\n" "$begin"
  cat "$keys_file"
  printf "%s\n" "$end"
} > "$auth_file"
chmod 600 "$auth_file"
EOF
  chmod 755 "$install_dir/sync_ssh_authorized_keys.sh"
  mkdir -p /etc/nexus-agent
  cat > /etc/nexus-agent/ssh-sync.env <<EOF
NEXUS_V3_REGISTRY_URL=$(printf '%s' "$registry_url" | sed 's:/*$::')
EOF
  chmod 600 /etc/nexus-agent/ssh-sync.env
}

install_ssh_sync_systemd() {
  install_ssh_sync_script /opt/nexus-agent "${1:-https://nexus-global-api.bings.app}"
  cat > /etc/systemd/system/nexus-ssh-authorized-keys.service <<'EOF'
[Unit]
Description=Nexus SSH authorized keys sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/opt/nexus-agent/sync_ssh_authorized_keys.sh
EOF
  systemctl disable --now nexus-ssh-authorized-keys.timer >/dev/null 2>&1 || true
  systemctl daemon-reload
  /opt/nexus-agent/sync_ssh_authorized_keys.sh || true
}

install_ssh_sync_openwrt() {
  install_ssh_sync_script /opt/nexus-agent "${1:-https://nexus-global-api.bings.app}"
  append_env_once /etc/nexus-agent/ssh-sync.env NEXUS_SSH_AUTHORIZED_KEYS_FILE /etc/dropbear/authorized_keys
  if [ -f /etc/crontabs/root ]; then
    tmp="/tmp/nexus-crontab.$$"
    grep -v '/opt/nexus-agent/sync_ssh_authorized_keys.sh' /etc/crontabs/root > "$tmp" || true
    mv "$tmp" /etc/crontabs/root
    /etc/init.d/cron restart >/dev/null 2>&1 || true
  fi
  /opt/nexus-agent/sync_ssh_authorized_keys.sh || true
}

sync_ssh_keys() {
  need_root
  /opt/nexus-agent/sync_ssh_authorized_keys.sh
}

sync_cluster_ssh() {
  registry_url="${NEXUS_V3_REGISTRY_URL:-http://100.116.89.65:18101}"
  hosts="${NEXUS_CLUSTER_SSH_HOSTS:-oracle_amd root@100.103.12.14 root@100.90.67.12}"
  failures=0
  for host in $hosts; do
    if [ "$host" = "local" ] || [ "$host" = "$(hostname 2>/dev/null || true)" ]; then
      if ! NEXUS_V3_REGISTRY_URL="$registry_url" sh "$SCRIPT_DIR/install.sh" sync-ssh-keys; then
        failures=$((failures + 1))
      fi
      continue
    fi
    if ! ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "$host" \
      "NEXUS_V3_REGISTRY_URL='$registry_url' /opt/nexus-agent/sync_ssh_authorized_keys.sh"; then
      failures=$((failures + 1))
    fi
  done
  [ "$failures" -eq 0 ] || fail "$failures cluster SSH sync target(s) failed"
}

trigger_cluster_ssh_sync() {
  [ "${NEXUS_SYNC_CLUSTER_ON_INSTALL:-1}" = "1" ] || return 0
  if ! sync_cluster_ssh; then
    printf 'Nexus cluster SSH sync did not complete; run install.sh sync-cluster-ssh after approval/connectivity is ready.\n' >&2
  fi
}

install_registry() {
  need_root
  install_dir="${NEXUS_V3_INSTALL_DIR:-/opt/nexus-v3}"
  env_file="${NEXUS_V3_ENV_FILE:-/etc/nexus-v3.env}"
  db_path="${NEXUS_V3_REGISTRY_DB:-/var/lib/nexus-v3/registry.db}"
  bind="${NEXUS_V3_BIND:-0.0.0.0}"
  port="${NEXUS_V3_REGISTRY_PORT:-18101}"
  service="${NEXUS_V3_REGISTRY_SERVICE:-nexus-v3-registry}"

  mkdir -p "$install_dir" "$(dirname "$db_path")" "$(dirname "$env_file")"
  install_python_package "$install_dir" __init__.py common.py registry.py
  if [ ! -f "$env_file" ] || ! grep -q '^NEXUS_V3_ADMIN_KEY=' "$env_file"; then
    append_env_once "$env_file" NEXUS_V3_ADMIN_KEY "$(openssl rand -hex 32)"
  fi
  chmod 600 "$env_file"

  cat > "/etc/systemd/system/$service.service" <<EOF
[Unit]
Description=Nexus v3 Registry
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$env_file
WorkingDirectory=$install_dir
ExecStart=/usr/bin/python3 -m nexus_v3.registry --bind $bind --port $port --db $db_path
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable "$service.service" >/dev/null
  systemctl restart "$service.service"
  sleep 2
  systemctl is-active --quiet "$service.service" || fail "registry service did not start"
  curl -fsS "http://127.0.0.1:$port/v3/health" >/dev/null
  printf 'Nexus registry installed: %s:%s\n' "$bind" "$port"
}

install_broker() {
  need_root
  region="${1:-${NEXUS_V3_REGION:-cn}}"
  install_dir="${NEXUS_V3_INSTALL_DIR:-/opt/nexus-v3}"
  env_file="${NEXUS_V3_ENV_FILE:-/etc/nexus-v3.env}"
  db_path="${NEXUS_V3_BROKER_DB:-/var/lib/nexus-v3/broker.db}"
  bind="${NEXUS_V3_BIND:-127.0.0.1}"
  port="${NEXUS_V3_BROKER_PORT:-18120}"
  registry_url="${NEXUS_V3_REGISTRY_URL:-http://127.0.0.1:18101}"
  service="${NEXUS_V3_BROKER_SERVICE:-nexus-v3-broker}"
  [ "$region" = "eu" ] || [ "$region" = "cn" ] || fail "broker region must be eu or cn"

  mkdir -p "$install_dir" "$(dirname "$db_path")" "$(dirname "$env_file")"
  install_python_package "$install_dir" __init__.py common.py broker.py
  touch "$env_file"
  chmod 600 "$env_file"

  cat > "/etc/systemd/system/$service.service" <<EOF
[Unit]
Description=Nexus v3 Broker ($region)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$env_file
Environment=NEXUS_V3_REGION=$region
Environment=NEXUS_V3_REGISTRY_URL=$registry_url
WorkingDirectory=$install_dir
ExecStart=/usr/bin/python3 -m nexus_v3.broker --bind $bind --port $port --db $db_path
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable "$service.service" >/dev/null
  systemctl restart "$service.service"
  sleep 2
  systemctl is-active --quiet "$service.service" || fail "broker service did not start"
  curl -fsS "http://127.0.0.1:$port/v3/health" >/dev/null
  printf 'Nexus broker installed: region=%s bind=%s port=%s\n' "$region" "$bind" "$port"
}

install_openwrt_agent() {
  need_root
  device_id="${1:-${NEXUS_DEVICE_ID:-}}"
  [ -f /etc/openwrt_release ] || fail "OpenWrt/iStoreOS required for $device_id self-claiming agent"
  [ -n "$device_id" ] || fail "OpenWrt agent mode requires canonical device id"
  command -v curl >/dev/null 2>&1 || fail "curl is required"
  command -v openssl >/dev/null 2>&1 || fail "openssl is required"
  command -v ruby >/dev/null 2>&1 || fail "ruby is required for Ed25519 signing fallback"

  registry_url="${NEXUS_V3_REGISTRY_URL:-https://nexus-global-api.bings.app}"
  broker_url="${NEXUS_V3_BROKER_URL:-http://100.103.12.14:18120}"
  install_dir="/opt/nexus-agent"
  config_dir="/etc/nexus-agent"
  config_file="$config_dir/v3.env"
  identity_key="$config_dir/identity_ed25519"
  identity_pub="$config_dir/identity_ed25519.pub"
  ssh_key="$identity_key"
  ssh_pub="$identity_pub"

  mkdir -p "$install_dir" "$config_dir"
  chmod 700 "$config_dir"
  copy_or_fetch nexus_v3/assets/openwrt_v3_agent.sh "$install_dir/v3-agent.sh"
  copy_or_fetch nexus_v3/assets/openwrt_ed25519_signer.rb "$install_dir/openwrt_ed25519_signer.rb"
  chmod 755 "$install_dir/v3-agent.sh" "$install_dir/openwrt_ed25519_signer.rb"

  if [ ! -f "$identity_key" ]; then
    ruby "$install_dir/openwrt_ed25519_signer.rb" generate "$identity_key" "$identity_pub" "nexus-$device_id@$(hostname 2>/dev/null || echo openwrt)" || fail "failed to generate identity key"
  elif [ ! -f "$identity_pub" ]; then
    ruby "$install_dir/openwrt_ed25519_signer.rb" public "$identity_key" "$identity_pub" "nexus-$device_id@$(hostname 2>/dev/null || echo openwrt)" || fail "failed to derive public key"
  fi
  chmod 600 "$identity_key"
  chmod 644 "$identity_pub"

  quote() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
  {
    printf 'NEXUS_DEVICE_ID=%s\n' "$(quote "$device_id")"
    printf 'NEXUS_V3_REGISTRY_URL=%s\n' "$(quote "$(printf '%s' "$registry_url" | sed 's:/*$::')")"
    printf 'NEXUS_V3_BROKER_URL=%s\n' "$(quote "$(printf '%s' "$broker_url" | sed 's:/*$::')")"
    printf 'NEXUS_IDENTITY_KEY=%s\n' "$(quote "$identity_key")"
    printf 'NEXUS_IDENTITY_PUBLIC_KEY=%s\n' "$(quote "$identity_pub")"
    printf 'NEXUS_SSH_PRIVATE_KEY=%s\n' "$(quote "$ssh_key")"
    printf 'NEXUS_SSH_PUBLIC_KEY=%s\n' "$(quote "$ssh_pub")"
    printf 'NEXUS_ED25519_SIGNER=%s\n' "$(quote "$install_dir/openwrt_ed25519_signer.rb")"
  } > "$config_file"
  chmod 600 "$config_file"

  cat > /etc/init.d/nexus-v3-agent <<'EOF'
#!/bin/sh /etc/rc.common
START=96
USE_PROCD=1

start_service() {
  procd_open_instance
  procd_set_param command /bin/sh /opt/nexus-agent/v3-agent.sh
  procd_set_param env NEXUS_V3_CONFIG=/etc/nexus-agent/v3.env
  procd_set_param respawn 5 5 0
  procd_set_param stdout 1
  procd_set_param stderr 1
  procd_close_instance
}
EOF
  chmod 755 /etc/init.d/nexus-v3-agent
  /etc/init.d/nexus-v3-agent enable
  /etc/init.d/nexus-v3-agent restart
  install_ssh_sync_openwrt "$registry_url"
  sleep 2
  /etc/init.d/nexus-v3-agent status >/dev/null 2>&1 || fail "openwrt agent did not start"
  trigger_cluster_ssh_sync
  printf 'Nexus OpenWrt self-claiming agent installed for %s\n' "$device_id"
  printf 'Public key: %s\n' "$identity_pub"
}

install_agent() {
  need_root
  device_id="${1:-${NEXUS_DEVICE_ID:-}}"
  [ -n "$device_id" ] || fail "agent mode requires canonical device id"
  case "$device_id" in
    n1|ax3600)
      if [ -f /etc/openwrt_release ]; then
        install_openwrt_agent "$device_id"
        return 0
      fi
      printf '%s is not running OpenWrt here; configure it as a ThinkCenter-managed target with: install.sh managed-targets\n' "$device_id"
      return 0
      ;;
  esac

  registry_url="${NEXUS_V3_REGISTRY_URL:-https://nexus-global-api.bings.app}"
  broker_url="${NEXUS_V3_BROKER_URL:-}"
  case "$device_id" in
    thinkcenter) broker_url="${broker_url:-http://127.0.0.1:18120}" ;;
    oracle|oracle-amd) broker_url="${broker_url:-http://127.0.0.1:18102}" ;;
    *) broker_url="${broker_url:-https://nexus-broker.bings.app}" ;;
  esac

  install_dir="/opt/nexus-agent"
  config_dir="/etc/nexus-agent"
  config_file="$config_dir/v3.json"
  identity_key="$config_dir/identity_ed25519"
  identity_pub="$config_dir/identity_ed25519.pub"
  ssh_key="$identity_key"
  ssh_pub="$identity_pub"
  mkdir -p "$install_dir" "$config_dir"
  chmod 700 "$config_dir"
  install_python_package "$install_dir" __init__.py common.py agent.py

  "$PYTHON" - <<PY
import json
from pathlib import Path
config = {
    "device_id": "$device_id",
    "registry_url": "$registry_url".rstrip("/"),
    "broker_url": "$broker_url".rstrip("/"),
    "identity_key": "$identity_key",
    "identity_public_key": "$identity_pub",
    "ssh_private_key": "$ssh_key",
    "ssh_public_key": "$ssh_pub",
    "wait_seconds": 20,
    "poll_seconds": 1,
    "request_timeout": 35,
}
Path("$config_file").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY
  chmod 600 "$config_file"

  if ! "$PYTHON" - <<'PY' >/dev/null 2>&1
import cryptography, requests
PY
  then
    [ -d "$install_dir/venv" ] || "$PYTHON" -m venv "$install_dir/venv"
    "$install_dir/venv/bin/python" -m pip install --upgrade pip >/dev/null
    "$install_dir/venv/bin/python" -m pip install requests cryptography >/dev/null
    runtime_python="$install_dir/venv/bin/python"
  else
    runtime_python="$(command -v "$PYTHON")"
  fi

  cat > /etc/systemd/system/nexus-v3-agent.service <<EOF
[Unit]
Description=Nexus v3 Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=NEXUS_V3_CONFIG=$config_file
WorkingDirectory=$install_dir
ExecStart=$runtime_python -m nexus_v3.agent
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable nexus-v3-agent.service >/dev/null
  systemctl restart nexus-v3-agent.service
  install_ssh_sync_systemd "$registry_url"
  sleep 2
  systemctl is-active --quiet nexus-v3-agent.service || fail "agent service did not start"
  trigger_cluster_ssh_sync
  printf 'Nexus agent installed for %s\n' "$device_id"
  printf 'Public key: %s\n' "$identity_pub"
}

install_remote() {
  need_root
  install_dir="${NEXUS_CHATGPT_INSTALL_DIR:-/opt/nexus-chatgpt-remote}"
  env_file="${NEXUS_CHATGPT_ENV_FILE:-/etc/nexus-chatgpt-remote.env}"
  v3_env="${NEXUS_V3_ENV_FILE:-/etc/nexus-v3.env}"
  mkdir -p "$install_dir/assets"
  install_python_package "$install_dir" __init__.py common.py remote_control.py mcp_server.py chatgpt_api.py
  copy_or_fetch "agent-council/integrations/nexus-v3-remote-control-openapi.json" "$install_dir/assets/openapi.template.json"
  copy_or_fetch "agent-council/integrations/nexus-v3-chatgpt-remote-prompt.md" "$install_dir/assets/chatgpt-prompt.md"

  [ -d "$install_dir/.venv" ] || "$PYTHON" -m venv "$install_dir/.venv"
  "$install_dir/.venv/bin/pip" install --disable-pip-version-check --no-cache-dir "mcp[cli]>=1.26,<2"

  admin_key="${NEXUS_V3_ADMIN_KEY:-}"
  if [ -z "$admin_key" ] && [ -r "$v3_env" ]; then
    admin_key="$(sed -n 's/^NEXUS_V3_ADMIN_KEY=//p' "$v3_env" | tail -n 1)"
  fi
  [ -n "$admin_key" ] || fail "NEXUS_V3_ADMIN_KEY is unavailable"
  chatgpt_key="${NEXUS_CHATGPT_API_KEY:-$(openssl rand -hex 32)}"

  umask 077
  cat > "$env_file" <<EOF
NEXUS_V3_ADMIN_KEY=$admin_key
NEXUS_V3_REGISTRY_URL=${NEXUS_V3_REGISTRY_URL:-http://127.0.0.1:18101}
NEXUS_V3_EU_BROKER_URL=${NEXUS_V3_EU_BROKER_URL:-http://127.0.0.1:18102}
NEXUS_V3_CN_BROKER_URL=${NEXUS_V3_CN_BROKER_URL:-http://100.103.12.14:18120}
NEXUS_V3_MCP_BIND=${NEXUS_V3_MCP_BIND:-127.0.0.1}
NEXUS_V3_MCP_PORT=${NEXUS_V3_MCP_PORT:-18130}
NEXUS_V3_ALLOW_DANGEROUS=${NEXUS_V3_ALLOW_DANGEROUS:-0}
NEXUS_CHATGPT_API_KEY=$chatgpt_key
NEXUS_CHATGPT_BIND=${NEXUS_CHATGPT_BIND:-127.0.0.1}
NEXUS_CHATGPT_PORT=${NEXUS_CHATGPT_PORT:-18131}
NEXUS_CHATGPT_PUBLIC_BASE_URL=${NEXUS_CHATGPT_PUBLIC_BASE_URL:-http://127.0.0.1:18131}
EOF
  chmod 600 "$env_file"

  cat > /etc/systemd/system/nexus-v3-mcp.service <<EOF
[Unit]
Description=Nexus v3 MCP Adapter
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$env_file
WorkingDirectory=$install_dir
ExecStart=$install_dir/.venv/bin/python -m nexus_v3.mcp_server
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  cat > /etc/systemd/system/nexus-chatgpt-remote.service <<EOF
[Unit]
Description=Nexus ChatGPT Remote API
After=network-online.target nexus-v3-mcp.service
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$env_file
WorkingDirectory=$install_dir
ExecStart=$install_dir/.venv/bin/python -m nexus_v3.chatgpt_api
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable nexus-v3-mcp.service nexus-chatgpt-remote.service >/dev/null
  systemctl restart nexus-v3-mcp.service nexus-chatgpt-remote.service
  sleep 2
  systemctl is-active --quiet nexus-v3-mcp.service || fail "mcp service did not start"
  systemctl is-active --quiet nexus-chatgpt-remote.service || fail "chatgpt remote service did not start"
  curl -fsS "http://${NEXUS_CHATGPT_BIND:-127.0.0.1}:${NEXUS_CHATGPT_PORT:-18131}/health" >/dev/null
  printf 'Nexus ChatGPT Remote installed. OpenAPI: http://%s:%s/openapi.json\n' "${NEXUS_CHATGPT_BIND:-127.0.0.1}" "${NEXUS_CHATGPT_PORT:-18131}"
}

install_managed_targets() {
  need_root
  dir="${NEXUS_MANAGED_TARGETS_DIR:-/etc/nexus-managed-targets}"
  mkdir -p "$dir"
  chmod 700 "$dir"
  cat > "$dir/targets.env" <<EOF
NEXUS_N1_SSH=${NEXUS_N1_SSH:-root@100.90.67.12}
NEXUS_AX3600_SSH=${NEXUS_AX3600_SSH:-root@192.168.1.1}
EOF
  chmod 600 "$dir/targets.env"
  printf 'Managed targets configured on ThinkCenter: %s\n' "$dir/targets.env"
}

cleanup_legacy() {
  need_root
  stamp="$(date -u '+%Y%m%dT%H%M%SZ')"
  backup_dir="/opt/nexus-bak/legacy-$stamp"
  mkdir -p "$backup_dir"

  if command -v systemctl >/dev/null 2>&1; then
    for service in nexus-agent.service nexus-mcp.service nexus-openwrt-agent.service; do
      systemctl disable --now "$service" >/dev/null 2>&1 || true
    done
    systemctl daemon-reload >/dev/null 2>&1 || true
  fi

  if [ -x /etc/init.d/nexus-agent ]; then
    /etc/init.d/nexus-agent stop >/dev/null 2>&1 || true
    /etc/init.d/nexus-agent disable >/dev/null 2>&1 || true
  fi

  move_legacy_path() {
    src="$1"
    [ -e "$src" ] || return 0
    dst="$backup_dir$(printf '%s' "$src")"
    mkdir -p "$(dirname "$dst")"
    mv "$src" "$dst"
  }

  for path in \
    /etc/systemd/system/nexus-agent.service \
    /etc/systemd/system/nexus-mcp.service \
    /etc/systemd/system/nexus-openwrt-agent.service \
    /etc/systemd/system/nexus-ssh-authorized-keys.timer \
    /etc/init.d/nexus-agent \
    /etc/nexus-agent/config.json \
    /etc/nexus-agent/config.env \
    /etc/nexus-agent/token \
    /opt/nexus-mcp \
    /opt/nexus-agent/agent.py \
    /opt/nexus-agent/unix_agent.py \
    /opt/nexus-agent/windows_agent.py \
    /opt/nexus-agent/openwrt_agent.sh \
    /opt/nexus-agent/nexus_agent.sh \
    /opt/nexus-agent/agent.sh; do
    move_legacy_path "$path"
  done

  if [ -f /etc/crontabs/root ]; then
    tmp="/tmp/nexus-crontab-clean.$$"
    grep -v '/opt/nexus-agent/sync_ssh_authorized_keys.sh' /etc/crontabs/root > "$tmp" || true
    mv "$tmp" /etc/crontabs/root
    /etc/init.d/cron restart >/dev/null 2>&1 || true
  fi

  if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload >/dev/null 2>&1 || true
  fi
  printf 'Legacy Nexus files moved to %s\n' "$backup_dir"
}

usage() {
  cat <<'EOF'
Usage:
  install.sh cleanup
  install.sh sync-ssh-keys
  install.sh sync-cluster-ssh
  install.sh registry
  install.sh broker [eu|cn]
  install.sh agent <canonical-device-id>
  install.sh <canonical-device-id>
  install.sh remote
  install.sh managed-targets

n1 and ax3600 self-claim jobs when they can run the OpenWrt agent; otherwise configure ThinkCenter-managed SSH fallback.
EOF
}

cmd="${1:-}"
case "$cmd" in
  cleanup) cleanup_legacy ;;
  sync-ssh-keys) sync_ssh_keys ;;
  sync-cluster-ssh) sync_cluster_ssh ;;
  registry) install_registry ;;
  broker) shift; install_broker "${1:-}" ;;
  agent) shift; install_agent "${1:-}" ;;
  openwrt-agent) shift; install_openwrt_agent "${1:-}" ;;
  remote|chatgpt-remote) install_remote ;;
  managed-targets) install_managed_targets ;;
  ""|-h|--help|help) usage ;;
  *) install_agent "$cmd" ;;
esac
