#!/bin/sh
set -eu

SOURCE_BASE="${NEXUS_SOURCE_BASE:-https://raw.githubusercontent.com/bingStat/nexus/main}"
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

resolve_ssh_home() {
  device_id="$1"
  if [ -n "${NEXUS_SSH_HOME:-}" ]; then
    printf '%s\n' "$NEXUS_SSH_HOME"
    return 0
  fi
  if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ] && [ -r /etc/passwd ]; then
    candidate="$(awk -F: -v u="$SUDO_USER" '$1==u{print $6; exit}' /etc/passwd)"
    if [ -n "$candidate" ] && [ -d "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi
  case "$device_id" in
    thinkcenter|victus-wsl) [ -d /home/bing ] && { printf '%s\n' /home/bing; return 0; } ;;
    oracle|oracle-amd) [ -d /home/ubuntu ] && { printf '%s\n' /home/ubuntu; return 0; } ;;
  esac
  printf '%s\n' /root
}

ssh_owner_for_home() {
  home="$1"
  [ -r /etc/passwd ] || return 0
  awk -F: -v h="$home" '$6==h{print $1; exit}' /etc/passwd
}

ensure_device_ssh_key() {
  device_id="$1"
  ssh_home="$2"
  ssh_owner="${3:-}"
  command -v ssh-keygen >/dev/null 2>&1 || fail "ssh-keygen is required to manage the per-device SSH key"
  ssh_dir="$ssh_home/.ssh"
  SSH_KEY_PATH="$ssh_dir/id_ed25519_$device_id"
  SSH_PUB_PATH="$SSH_KEY_PATH.pub"
  mkdir -p "$ssh_dir"
  chmod 700 "$ssh_dir"

  if [ ! -f "$SSH_KEY_PATH" ]; then
    source_key="${NEXUS_SSH_SOURCE_KEY:-}"
    if [ -z "$source_key" ]; then
      case "$device_id" in
        vsc) [ -f "$ssh_dir/id_ed25519_nexus_mesh" ] && source_key="$ssh_dir/id_ed25519_nexus_mesh" ;;
        victus-wsl) source_key="" ;;
        *) [ -f "$ssh_dir/id_ed25519" ] && source_key="$ssh_dir/id_ed25519" ;;
      esac
    fi
    if [ -n "$source_key" ] && [ -f "$source_key" ] && ssh-keygen -y -f "$source_key" >/dev/null 2>&1; then
      mv "$source_key" "$SSH_KEY_PATH"
      [ ! -f "$source_key.pub" ] || mv "$source_key.pub" "$SSH_PUB_PATH"
    else
      ssh-keygen -q -t ed25519 -N '' -C "nexus-$device_id@$(hostname 2>/dev/null || echo unknown)" -f "$SSH_KEY_PATH"
    fi
  fi
  if [ ! -f "$SSH_PUB_PATH" ]; then
    public_body="$(ssh-keygen -y -f "$SSH_KEY_PATH")"
    printf '%s nexus-%s@%s\n' "$public_body" "$device_id" "$(hostname 2>/dev/null || echo unknown)" > "$SSH_PUB_PATH"
  fi
  chmod 600 "$SSH_KEY_PATH"
  chmod 644 "$SSH_PUB_PATH"
  if [ -n "$ssh_owner" ] && id "$ssh_owner" >/dev/null 2>&1; then
    chown "$ssh_owner" "$ssh_dir" "$SSH_KEY_PATH" "$SSH_PUB_PATH"
  fi
}

ensure_device_auth_key() {
  DEVICE_KEY_PATH="$1"
  mkdir -p "$(dirname "$DEVICE_KEY_PATH")"
  if [ -s "$DEVICE_KEY_PATH" ]; then
    existing="$(tr -d '\r\n' < "$DEVICE_KEY_PATH")"
    case "$existing" in
      nxk_????????????????????????????????????*) ;;
      *) fail "invalid existing Nexus device key: $DEVICE_KEY_PATH" ;;
    esac
    chmod 600 "$DEVICE_KEY_PATH"
    return 0
  fi

  umask 077
  token=""
  if command -v openssl >/dev/null 2>&1; then
    token="$(openssl rand -hex 32 2>/dev/null || true)"
    case "$token" in
      ''|*[!0-9a-fA-F]*) token="" ;;
    esac
    [ "${#token}" -eq 64 ] || token=""
  fi
  if [ -z "$token" ] && [ -n "${PYTHON:-}" ] && command -v "$PYTHON" >/dev/null 2>&1; then
    token="$("$PYTHON" -c 'import secrets; print(secrets.token_hex(32))')"
  fi
  if [ -z "$token" ] && command -v dd >/dev/null 2>&1 && command -v sha256sum >/dev/null 2>&1; then
    random_file="${DEVICE_KEY_PATH}.random.$$"
    dd if=/dev/urandom of="$random_file" bs=64 count=1 >/dev/null 2>&1 || fail "failed to read /dev/urandom"
    token="$(sha256sum "$random_file" | awk '{print $1}')"
    rm -f "$random_file"
  fi
  [ "${#token}" -eq 64 ] || fail "unable to create a secure Nexus device key"
  printf 'nxk_%s\n' "$token" > "$DEVICE_KEY_PATH"
  chmod 600 "$DEVICE_KEY_PATH"
}

cleanup_retired_linux() {
  command -v systemctl >/dev/null 2>&1 || return 0
  retired_units="nexus-agent.service nexus-mcp.service nexus-broker.service nexus-n1-api-proxy.service nexus-readonly-api.service nexus-state-sync.service nexus-state-sync.timer nexus-peer-watchdog.service nexus-peer-watchdog.timer nexus-remediator.service nexus-remediator.timer nexus-api-dns-failover.service nexus-bootstrap-mirror.service nexus-global-api.service nexus-eu-broker.service nexus-eu-broker-tailnet.service nexus-oracle-api-relay.service nexus-oracle-container-recovery.service nexus-oracle-health-server.service nexus-oracle-health.service nexus-oracle-health.timer nexus-oracle-monitor.service nexus-oracle-monitor.timer nexus-oracle-standby.service nexus-telegram-source-sync.service nexus-telegram-source-sync.timer"
  for unit in $retired_units; do
    systemctl disable --now "$unit" >/dev/null 2>&1 || true
    rm -f "/etc/systemd/system/$unit"
  done
  rm -rf /opt/nexus /opt/nexus-bootstrap /opt/nexus-n1-api-relay /opt/nexus-global-api /opt/nexus-eu-broker /opt/nexus-oracle-api-relay /opt/nexus-v3-mcp /opt/nexus-bak
  rm -rf /var/lib/nexus-global-api /var/lib/nexus-eu-broker /var/lib/nexus-broker /var/lib/nexus-agent /var/lib/nexus-api-failover /var/lib/nexus-peer-watchdog
  rm -f /etc/nexus-agent.env /etc/nexus-mcp.env /etc/nexus-global-api-connector.env /etc/nexus-mcp-public-path /etc/nexus-oracle-standby.env /etc/nexus-service.env
  rm -f /usr/local/sbin/nexus-api-dns-failover /usr/local/sbin/nexus-peer-watchdog /usr/local/sbin/nexus-remediator
  systemctl daemon-reload
  systemctl reset-failed >/dev/null 2>&1 || true
}

cleanup_retired_openwrt() {
  for init in /etc/init.d/nexus-agent /etc/init.d/nexus; do
    [ -e "$init" ] || continue
    "$init" stop >/dev/null 2>&1 || true
    "$init" disable >/dev/null 2>&1 || true
    rm -f "$init"
  done
  rm -rf /opt/nexus-bak /opt/nexus-agent/backups /opt/nexus-agent/state
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
auth_owner="${NEXUS_SSH_AUTHORIZED_OWNER:-}"
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
[ -n "$auth_owner" ] && chown "$auth_owner" "$ssh_dir" "$auth_file" 2>/dev/null || true
EOF
  chmod 755 "$install_dir/sync_ssh_authorized_keys.sh"
  mkdir -p /etc/nexus-agent
  cat > /etc/nexus-agent/ssh-sync.env <<EOF
NEXUS_V3_REGISTRY_URL=$(printf '%s' "$registry_url" | sed 's:/*$::')
EOF
  chmod 600 /etc/nexus-agent/ssh-sync.env
}

install_ssh_sync_systemd() {
  registry_url="${1:-https://nexus-global-api.bings.app}"
  auth_file="${2:-/root/.ssh/authorized_keys}"
  auth_owner="${3:-}"
  install_ssh_sync_script /opt/nexus-agent "$registry_url"
  append_env_once /etc/nexus-agent/ssh-sync.env NEXUS_SSH_AUTHORIZED_KEYS_FILE "$auth_file"
  [ -n "$auth_owner" ] && append_env_once /etc/nexus-agent/ssh-sync.env NEXUS_SSH_AUTHORIZED_OWNER "$auth_owner"
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
  cleanup_retired_linux
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
  cleanup_retired_linux
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
  cleanup_retired_openwrt
  device_id="${1:-${NEXUS_DEVICE_ID:-}}"
  [ -f /etc/openwrt_release ] || fail "OpenWrt/iStoreOS required for $device_id self-claiming agent"
  [ -n "$device_id" ] || fail "OpenWrt agent mode requires canonical device id"
  command -v curl >/dev/null 2>&1 || fail "curl is required"
  command -v openssl >/dev/null 2>&1 || fail "openssl is required"

  registry_url="${NEXUS_V3_REGISTRY_URL:-https://nexus-global-api.bings.app}"
  broker_url="${NEXUS_V3_BROKER_URL:-http://100.103.12.14:18120}"
  install_dir="/opt/nexus-agent"
  config_dir="/etc/nexus-agent"
  config_file="$config_dir/v3.env"
  device_key="$config_dir/device.key"
  ssh_key="/root/.ssh/id_ed25519_$device_id"
  ssh_pub="$ssh_key.pub"

  mkdir -p "$install_dir" "$config_dir"
  chmod 700 "$config_dir"
  copy_or_fetch nexus_v3/assets/openwrt_v3_agent.sh "$install_dir/v3-agent.sh"
  chmod 755 "$install_dir/v3-agent.sh"
  ensure_device_auth_key "$device_key"
  rm -f "$config_dir/identity_ed25519" "$config_dir/identity_ed25519.pub"

  mkdir -p /root/.ssh
  chmod 700 /root/.ssh
  if [ ! -f "$ssh_key" ]; then
    if [ -f /root/.ssh/id_dropbear ]; then
      mv /root/.ssh/id_dropbear "$ssh_key"
    else
      command -v dropbearkey >/dev/null 2>&1 || fail "dropbearkey is required to create the OpenWrt SSH key"
      dropbearkey -t ed25519 -f "$ssh_key" >/dev/null 2>&1 || fail "failed to generate Dropbear SSH key"
    fi
  fi
  if [ ! -f "$ssh_pub" ]; then
    dropbearkey -y -f "$ssh_key" 2>/dev/null | awk '/^ssh-ed25519 / {print; exit}' | sed "s/$/ nexus-$device_id@$(hostname 2>/dev/null || echo openwrt)/" > "$ssh_pub"
  fi
  [ -s "$ssh_pub" ] || fail "failed to produce SSH public key"
  chmod 600 "$ssh_key"
  chmod 644 "$ssh_pub"

  quote() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
  {
    printf 'NEXUS_DEVICE_ID=%s\n' "$(quote "$device_id")"
    printf 'NEXUS_V3_REGISTRY_URL=%s\n' "$(quote "$(printf '%s' "$registry_url" | sed 's:/*$::')")"
    printf 'NEXUS_V3_BROKER_URL=%s\n' "$(quote "$(printf '%s' "$broker_url" | sed 's:/*$::')")"
    printf 'NEXUS_DEVICE_KEY_FILE=%s\n' "$(quote "$device_key")"
    printf 'NEXUS_SSH_PRIVATE_KEY=%s\n' "$(quote "$ssh_key")"
    printf 'NEXUS_SSH_PUBLIC_KEY=%s\n' "$(quote "$ssh_pub")"
    printf 'NEXUS_SSH_SYNC_SCRIPT=%s\n' "$(quote "$install_dir/sync_ssh_authorized_keys.sh")"
    printf 'NEXUS_SSH_SYNC_INTERVAL=%s\n' "$(quote "${NEXUS_SSH_SYNC_INTERVAL:-300}")"
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
  printf 'SSH key: %s\n' "$ssh_key"
}

install_agent() {
  need_root
  cleanup_retired_linux
  device_id="${1:-${NEXUS_DEVICE_ID:-}}"
  [ -n "$device_id" ] || fail "agent mode requires canonical device id"
  case "$device_id" in
    n1|ax3600)
      fail "$device_id requires: install.sh openwrt-agent $device_id on that OpenWrt device"
      ;;
  esac

  registry_url="${NEXUS_V3_REGISTRY_URL:-https://nexus-global-api.bings.app}"
  broker_url="${NEXUS_V3_BROKER_URL:-}"
  case "$device_id" in
    thinkcenter) broker_url="${broker_url:-http://127.0.0.1:18120}" ;;
    oracle|oracle-amd) broker_url="${broker_url:-http://127.0.0.1:18102}" ;;
    *) broker_url="${broker_url:-https://nexus-eu-broker.bings.app}" ;;
  esac

  install_dir="/opt/nexus-agent"
  config_dir="/etc/nexus-agent"
  config_file="$config_dir/v3.json"
  device_key="$config_dir/device.key"
  ssh_home="$(resolve_ssh_home "$device_id")"
  ssh_owner="${NEXUS_SSH_OWNER:-$(ssh_owner_for_home "$ssh_home")}"
  ensure_device_ssh_key "$device_id" "$ssh_home" "$ssh_owner"
  ssh_key="$SSH_KEY_PATH"
  ssh_pub="$SSH_PUB_PATH"
  ssh_authorized_keys="$ssh_home/.ssh/authorized_keys"
  ssh_sync_interval="${NEXUS_SSH_SYNC_INTERVAL:-300}"
  mkdir -p "$install_dir" "$config_dir"
  chmod 700 "$config_dir"
  ensure_device_auth_key "$device_key"
  rm -f "$config_dir/identity_ed25519" "$config_dir/identity_ed25519.pub"
  install_python_package "$install_dir" __init__.py common.py agent.py devspace_runtime.py ledger.py ssh_fleet.py

  devspace_bridge=""
  devspace_roots="${NEXUS_DEVSPACE_ALLOWED_ROOTS:-}"
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    node_version="$(node -p 'process.versions.node' 2>/dev/null || true)"
    node_major="$(printf '%s' "$node_version" | cut -d. -f1)"
    node_minor="$(printf '%s' "$node_version" | cut -d. -f2)"
    if [ "${node_major:-0}" -gt 22 ] || { [ "${node_major:-0}" -eq 22 ] && [ "${node_minor:-0}" -ge 19 ]; }; then
      runtime_dir="$install_dir/devspace-runtime"
      mkdir -p "$runtime_dir"
      copy_or_fetch runtime/devspace/package.json "$runtime_dir/package.json"
      copy_or_fetch runtime/devspace/package-lock.json "$runtime_dir/package-lock.json"
      copy_or_fetch runtime/devspace/bridge.mjs "$runtime_dir/bridge.mjs"
      (cd "$runtime_dir" && npm ci --omit=dev --no-audit --no-fund >/dev/null && node ./bridge.mjs --self-test >/dev/null)
      devspace_bridge="$runtime_dir/bridge.mjs"
      [ -n "$devspace_roots" ] || { [ -d /home ] && devspace_roots=/home || true; }
    fi
  fi

  "$PYTHON" - <<PY
import json
from pathlib import Path
config = {
    "device_id": "$device_id",
    "registry_url": "$registry_url".rstrip("/"),
    "broker_url": "$broker_url".rstrip("/"),
    "device_key": "$device_key",
    "ssh_private_key": "$ssh_key",
    "ssh_public_key": "$ssh_pub",
    "ssh_authorized_keys": "$ssh_authorized_keys",
    "ssh_sync_interval": $ssh_sync_interval,
    "wait_seconds": 20,
    "poll_seconds": 1,
    "request_timeout": 35,
    "execution_ledger": "$config_dir/execution-ledger.db",
}
bridge = "$devspace_bridge"
roots = [item for item in "$devspace_roots".split(":") if item]
if bridge and roots:
    config["devspace"] = {"bridge": bridge, "allowed_roots": roots, "state_dir": "$config_dir/devspace-state"}
Path("$config_file").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY
  chmod 600 "$config_file"

  if ! "$PYTHON" - <<'PY' >/dev/null 2>&1
import requests
PY
  then
    [ -d "$install_dir/venv" ] || "$PYTHON" -m venv "$install_dir/venv"
    "$install_dir/venv/bin/python" -m pip install --upgrade pip >/dev/null
    "$install_dir/venv/bin/python" -m pip install requests >/dev/null
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
  install_ssh_sync_systemd "$registry_url" "$ssh_authorized_keys" "$ssh_owner"
  sleep 2
  systemctl is-active --quiet nexus-v3-agent.service || fail "agent service did not start"
  trigger_cluster_ssh_sync
  printf 'Nexus agent installed for %s\n' "$device_id"
  printf 'SSH key: %s\n' "$ssh_key"
}


cleanup_retired_user() {
  profile="$HOME/.profile"
  for dir in "$HOME/.nexus-agent" "$HOME/.nexus"; do
    [ -e "$dir" ] && rm -rf "$dir"
  done
  if [ -f "$profile" ]; then
    tmp="$profile.nexus.$$"
    awk '
      $0 == "# BEGIN NEXUS V3 USER AGENT" {skip=1; next}
      $0 == "# END NEXUS V3 USER AGENT" {skip=0; next}
      skip != 1 {print}
    ' "$profile" > "$tmp"
    mv "$tmp" "$profile"
  fi
}

install_user_agent() {
  [ "$(id -u)" -ne 0 ] || fail "user-agent mode must run as a normal user, not root"
  cleanup_retired_user
  device_id="${1:-${NEXUS_DEVICE_ID:-auto}}"
  if [ "$device_id" = "auto" ] || [ -z "$device_id" ]; then
    device_id="$(hostname -s 2>/dev/null || hostname | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_.-')"
  fi
  case "$device_id" in n1|ax3600) fail "$device_id requires openwrt-agent" ;; esac

  registry_url="${NEXUS_V3_REGISTRY_URL:-https://nexus-global-api.bings.app}"
  broker_url="${NEXUS_V3_BROKER_URL:-https://nexus-eu-broker.bings.app}"
  install_dir="${NEXUS_USER_AGENT_DIR:-$HOME/.local/nexus-agent-v3}"
  config_dir="${NEXUS_USER_AGENT_CONFIG_DIR:-$HOME/.config/nexus-agent}"
  config_file="$config_dir/v3.json"
  device_key="$install_dir/device.key"
  ensure_device_ssh_key "$device_id" "$HOME" "$(id -un)"
  ssh_key="$SSH_KEY_PATH"
  ssh_pub="$SSH_PUB_PATH"
  ssh_authorized_keys="$HOME/.ssh/authorized_keys"
  ssh_sync_interval="${NEXUS_SSH_SYNC_INTERVAL:-300}"
  mkdir -p "$install_dir/logs" "$config_dir"
  chmod 700 "$install_dir" "$config_dir"
  ensure_device_auth_key "$device_key"
  rm -f "$install_dir/identity_ed25519" "$install_dir/identity_ed25519.pub"
  install_python_package "$install_dir" __init__.py common.py agent.py devspace_runtime.py ledger.py ssh_fleet.py

  devspace_bridge=""
  devspace_roots="${NEXUS_DEVSPACE_ALLOWED_ROOTS:-$HOME}"
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    node_version="$(node -p 'process.versions.node' 2>/dev/null || true)"
    node_major="$(printf '%s' "$node_version" | cut -d. -f1)"
    node_minor="$(printf '%s' "$node_version" | cut -d. -f2)"
    if [ "${node_major:-0}" -gt 22 ] || { [ "${node_major:-0}" -eq 22 ] && [ "${node_minor:-0}" -ge 19 ]; }; then
      runtime_dir="$install_dir/devspace-runtime"
      mkdir -p "$runtime_dir"
      copy_or_fetch runtime/devspace/package.json "$runtime_dir/package.json"
      copy_or_fetch runtime/devspace/package-lock.json "$runtime_dir/package-lock.json"
      copy_or_fetch runtime/devspace/bridge.mjs "$runtime_dir/bridge.mjs"
      (cd "$runtime_dir" && npm ci --omit=dev --no-audit --no-fund >/dev/null && node ./bridge.mjs --self-test >/dev/null)
      devspace_bridge="$runtime_dir/bridge.mjs"
    fi
  fi

  runtime_python="$(command -v "$PYTHON" || true)"
  [ -n "$runtime_python" ] || fail "python3 is required"
  if ! "$runtime_python" - <<'PY' >/dev/null 2>&1
import requests
PY
  then
    [ -d "$install_dir/.venv" ] || "$runtime_python" -m venv "$install_dir/.venv"
    "$install_dir/.venv/bin/python" -m pip install --disable-pip-version-check --quiet requests
    runtime_python="$install_dir/.venv/bin/python"
  fi

  "$runtime_python" - <<PY
import json
from pathlib import Path
config = {
    "device_id": "$device_id",
    "registry_url": "$registry_url".rstrip("/"),
    "broker_url": "$broker_url".rstrip("/"),
    "device_key": "$device_key",
    "ssh_private_key": "$ssh_key",
    "ssh_public_key": "$ssh_pub",
    "ssh_authorized_keys": "$ssh_authorized_keys",
    "ssh_sync_interval": $ssh_sync_interval,
    "wait_seconds": 20,
    "poll_seconds": 1,
    "request_timeout": 35,
    "execution_ledger": "$install_dir/execution-ledger.db",
}
bridge = "$devspace_bridge"
roots = [item for item in "$devspace_roots".split(":") if item]
if bridge and roots:
    config["devspace"] = {"bridge": bridge, "allowed_roots": roots, "state_dir": "$install_dir/devspace-state"}
Path("$config_file").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY
  chmod 600 "$config_file"

  cat > "$install_dir/run-agent.sh" <<EOF
#!/bin/sh
export NEXUS_V3_CONFIG="$config_file"
cd "$install_dir"
exec "$runtime_python" -m nexus_v3.agent >>"$install_dir/logs/agent.log" 2>&1
EOF
  chmod 700 "$install_dir/run-agent.sh"
  cat > "$install_dir/ensure-agent.sh" <<EOF
#!/bin/sh
pid_file="$install_dir/agent.pid"
if [ -s "\$pid_file" ]; then
  pid="\$(cat "\$pid_file" 2>/dev/null || true)"
  [ -n "\$pid" ] && kill -0 "\$pid" 2>/dev/null && exit 0
fi
nohup "$install_dir/run-agent.sh" </dev/null >/dev/null 2>&1 &
echo \$! >"\$pid_file"
EOF
  chmod 700 "$install_dir/ensure-agent.sh"

  profile="$HOME/.profile"
  touch "$profile"
  {
    printf '\n# BEGIN NEXUS V3 USER AGENT\n'
    printf '[ -x "%s/ensure-agent.sh" ] && "%s/ensure-agent.sh" >/dev/null 2>&1 || true\n' "$install_dir" "$install_dir"
    printf '# END NEXUS V3 USER AGENT\n'
  } >> "$profile"
  "$install_dir/ensure-agent.sh"
  sleep 2
  pid="$(cat "$install_dir/agent.pid" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null || fail "user agent did not start"

  approval_status="pending (awaiting cluster approval)"
  admin_key="${NEXUS_V3_ADMIN_KEY:-}"
  if [ -n "$admin_key" ]; then
    approve_resp="$(curl -s -X POST -H "X-Nexus-Admin-Key: $admin_key" -H "Content-Type: application/json" -d '{}' "$registry_url/v3/admin/devices/$device_id/approve" 2>/dev/null || true)"
    if echo "$approve_resp" | grep -q '"status":"approved"'; then
      approval_status="Approved & Active"
    fi
  fi

  printf '\n================================================================\n'
  printf '        Nexus v3 User Agent Installed Successfully              \n'
  printf '================================================================\n'
  printf ' Device ID:     %s\n' "$device_id"
  printf ' Platform:      %s\n' "$(uname -srm 2>/dev/null || uname -a)"
  printf ' Install Dir:   %s\n' "$install_dir"
  printf ' Persistence:   managed block in %s\n' "$profile"
  printf ' Registry:      %s\n' "$registry_url"
  printf ' Broker:        %s\n' "$broker_url"
  printf ' SSH key:       %s\n' "$ssh_key"
  printf ' Cluster State: %s\n' "$approval_status"
  if [ -n "$devspace_bridge" ]; then
    printf ' DevSpace:      Enabled (bridge: %s)\n' "$devspace_bridge"
  else
    printf ' DevSpace:      Skipped (Node >= 22.19 not detected)\n'
  fi
  printf ' Dashboard:     https://nexus.bings.app\n'
  printf ' MCP Endpoint:  https://nexus.bings.app/mcp\n'
  printf '================================================================\n\n'
}


install_remote() {
  need_root
  cleanup_retired_linux
  install_dir="${NEXUS_CHATGPT_INSTALL_DIR:-/opt/nexus-chatgpt-remote}"
  env_file="${NEXUS_CHATGPT_ENV_FILE:-/etc/nexus-chatgpt-remote.env}"
  v3_env="${NEXUS_V3_ENV_FILE:-/etc/nexus-v3.env}"
  mkdir -p "$install_dir/assets"
  install_python_package "$install_dir" __init__.py common.py status.py remote_control.py mcp_contracts.py mcp_server.py chatgpt_api.py
  copy_or_fetch "agent-council/integrations/nexus-v3-remote-control-openapi.json" "$install_dir/assets/openapi.template.json"
  copy_or_fetch "agent-council/integrations/nexus-v3-chatgpt-remote-prompt.md" "$install_dir/assets/chatgpt-prompt.md"

  [ -d "$install_dir/.venv" ] || "$PYTHON" -m venv "$install_dir/.venv"
  "$install_dir/.venv/bin/pip" install --disable-pip-version-check --no-cache-dir "mcp[cli]>=1.26,<2" uvicorn

  admin_key="${NEXUS_V3_ADMIN_KEY:-}"
  if [ -z "$admin_key" ] && [ -r "$v3_env" ]; then
    admin_key="$(sed -n 's/^NEXUS_V3_ADMIN_KEY=//p' "$v3_env" | tail -n 1)"
  fi
  [ -n "$admin_key" ] || fail "NEXUS_V3_ADMIN_KEY is unavailable"
  chatgpt_key="${NEXUS_CHATGPT_API_KEY:-$(openssl rand -hex 32)}"
  bearer_token="${NEXUS_MCP_BEARER_TOKEN:-$(openssl rand -hex 32)}"

  umask 077
  cat > "$env_file" <<EOF
NEXUS_V3_ADMIN_KEY=$admin_key
NEXUS_V3_REGISTRY_URL=${NEXUS_V3_REGISTRY_URL:-http://127.0.0.1:18101}
NEXUS_V3_EU_BROKER_URL=${NEXUS_V3_EU_BROKER_URL:-http://127.0.0.1:18102}
NEXUS_V3_CN_BROKER_URL=${NEXUS_V3_CN_BROKER_URL:-http://100.103.12.14:18120}
NEXUS_V3_MCP_BIND=${NEXUS_V3_MCP_BIND:-127.0.0.1}
NEXUS_V3_MCP_PORT=${NEXUS_V3_MCP_PORT:-18130}
NEXUS_V3_ALLOW_DANGEROUS=${NEXUS_V3_ALLOW_DANGEROUS:-0}
NEXUS_MCP_BEARER_TOKEN=$bearer_token
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
  printf '\nMCP Server endpoint:  https://nexus.bings.app/mcp\n'
  printf 'MCP Bearer token:     %s\n' "$bearer_token"
  printf '(Save the token in Bitwarden as "Nexus MCP Bearer Token")\n'
}

install_ops() {
  need_root
  cleanup_retired_linux
  tmp="/tmp/nexus-ops-install.$$"
  copy_or_fetch ops/install.sh "$tmp"
  chmod 755 "$tmp"
  NEXUS_SOURCE_BASE="$SOURCE_BASE" sh "$tmp"
  rm -f "$tmp"
}

usage() {
  cat <<'EOF'
Usage:
  install.sh registry
  install.sh broker <eu|cn>
  install.sh agent <canonical-device-id>
  install.sh user-agent <canonical-device-id>
  install.sh openwrt-agent <n1|ax3600>
  install.sh remote
  install.sh ops
  install.sh sync-ssh-keys
  install.sh sync-cluster-ssh
EOF
}

cmd="${1:-}"
case "$cmd" in
  registry) install_registry ;;
  broker) shift; install_broker "${1:-}" ;;
  agent) shift; install_agent "${1:-auto}" ;;
  user-agent) shift; install_user_agent "${1:-auto}" ;;
  openwrt-agent) shift; install_openwrt_agent "${1:-}" ;;
  remote) install_remote ;;
  ops) install_ops ;;
  sync-ssh-keys) sync_ssh_keys ;;
  sync-cluster-ssh) sync_cluster_ssh ;;
  -h|--help|help) usage ;;
  "")
    # Default one-command action: install agent automatically based on permissions
    if [ "$(id -u)" -eq 0 ]; then
      install_agent auto
    else
      install_user_agent auto
    fi
    ;;
  *) usage; fail "unknown installer command: $cmd" ;;
esac

