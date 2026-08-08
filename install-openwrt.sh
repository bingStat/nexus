#!/bin/sh
set -eu

DEVICE_ID="${1:-${NEXUS_DEVICE_ID:-}}"
BROKER_URL="${NEXUS_BROKER_URL:-}"
API_URL="${NEXUS_API_URL:-https://nexus-api.bings.app}"
SOURCE_BASE="${NEXUS_SOURCE_BASE:-https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394}"
INSTALL_DIR="/opt/nexus-agent"
CONFIG_DIR="/etc/nexus-agent"
CONFIG_FILE="$CONFIG_DIR/config.env"
IDENTITY_KEY="$CONFIG_DIR/identity_ed25519"
IDENTITY_PUB="$CONFIG_DIR/identity_ed25519.pub"
BACKUP_DIR="/opt/nexus-agent/backups/install-openwrt-$(date -u '+%Y%m%dT%H%M%SZ')"

fail() { printf 'nexus openwrt install: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail "run as root"
[ -f /etc/openwrt_release ] || fail "OpenWrt/iStoreOS is required; use install.sh for Linux systemd hosts"
[ -n "$DEVICE_ID" ] || fail "device id required: install-openwrt.sh <canonical-device-id>"
[ -n "$API_URL" ] || fail "NEXUS_API_URL is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v openssl >/dev/null 2>&1 || fail "openssl is required"

case "$DEVICE_ID" in
  n1|ax3600) BROKER_URL="${BROKER_URL:-https://nexus-broker.bings.app}" ;;
  *) fail "unsupported OpenWrt canonical device id: $DEVICE_ID" ;;
esac

quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$BACKUP_DIR"
chmod 700 "$CONFIG_DIR"
[ -f "$INSTALL_DIR/agent.sh" ] && cp "$INSTALL_DIR/agent.sh" "$BACKUP_DIR/agent.sh.bak"
[ -f "$CONFIG_FILE" ] && cp "$CONFIG_FILE" "$BACKUP_DIR/config.env.bak"
[ -f "$IDENTITY_KEY" ] && cp "$IDENTITY_KEY" "$BACKUP_DIR/identity_ed25519.bak"
[ -f "$IDENTITY_PUB" ] && cp "$IDENTITY_PUB" "$BACKUP_DIR/identity_ed25519.pub.bak"
[ -f /etc/init.d/nexus-agent ] && cp /etc/init.d/nexus-agent "$BACKUP_DIR/nexus-agent.init.bak"

curl -fsSL "$SOURCE_BASE/agent/openwrt_agent.sh" -o "$INSTALL_DIR/agent.sh"
chmod 755 "$INSTALL_DIR/agent.sh"

{
  printf 'NEXUS_DEVICE_ID=%s\n' "$(quote "$DEVICE_ID")"
  printf 'NEXUS_DEVICE_NAME=%s\n' "$(quote "$DEVICE_ID")"
  printf 'NEXUS_BROKER_URL=%s\n' "$(quote "$(printf '%s' "$BROKER_URL" | sed 's:/*$::')")"
  printf 'NEXUS_API_URL=%s\n' "$(quote "$(printf '%s' "$API_URL" | sed 's:/*$::')")"
  printf 'NEXUS_IDENTITY_KEY=%s\n' "$(quote "$IDENTITY_KEY")"
  printf 'NEXUS_IDENTITY_PUBLIC_KEY=%s\n' "$(quote "$IDENTITY_PUB")"
  printf 'NEXUS_POLL_SECONDS=%s\n' "$(quote "${NEXUS_POLL_SECONDS:-1}")"
  printf 'NEXUS_HEARTBEAT_SECONDS=%s\n' "$(quote "${NEXUS_HEARTBEAT_SECONDS:-30}")"
  printf 'NEXUS_BROKER_WAIT_SECONDS=%s\n' "$(quote "${NEXUS_BROKER_WAIT_SECONDS:-20}")"
  printf 'NEXUS_REQUEST_TIMEOUT=%s\n' "$(quote "${NEXUS_REQUEST_TIMEOUT:-8}")"
} > "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

if [ ! -f "$IDENTITY_KEY" ]; then
  openssl genpkey -algorithm Ed25519 -out "$IDENTITY_KEY" >/dev/null 2>&1 || fail "failed to generate Ed25519 identity key"
  openssl pkey -in "$IDENTITY_KEY" -pubout -out "$IDENTITY_PUB" >/dev/null 2>&1 || fail "failed to derive Ed25519 public key"
fi
chmod 600 "$IDENTITY_KEY"
chmod 644 "$IDENTITY_PUB"

cat > /etc/init.d/nexus-agent <<'EOF'
#!/bin/sh /etc/rc.common
START=95
USE_PROCD=1

start_service() {
  procd_open_instance
  procd_set_param command /bin/sh /opt/nexus-agent/agent.sh
  procd_set_param env NEXUS_CONFIG_FILE=/etc/nexus-agent/config.env
  procd_set_param respawn 5 5 0
  procd_set_param stdout 1
  procd_set_param stderr 1
  procd_close_instance
}
EOF
chmod 755 /etc/init.d/nexus-agent

for old in nexus-peer-watchdog nexus-bootstrap-mirror; do
  if [ -x "/etc/init.d/$old" ]; then
    "/etc/init.d/$old" stop >/dev/null 2>&1 || true
    "/etc/init.d/$old" disable >/dev/null 2>&1 || true
    mv "/etc/init.d/$old" "$BACKUP_DIR/$old.init.disabled"
  fi
done

ps w 2>/dev/null | awk '/\/root\/\.nexus-agent\/agent\.sh|nexus-peer-watchdog|nexus-bootstrap-mirror/ && !/awk/ {print $1}' |
while read -r pid; do
  [ -n "$pid" ] && kill "$pid" >/dev/null 2>&1 || true
done

/etc/init.d/nexus-agent enable
/etc/init.d/nexus-agent restart
sleep 2
if ! ps w 2>/dev/null | grep -q '[o]pt/nexus-agent/agent.sh'; then
  fail "nexus-agent did not start"
fi

printf 'Nexus OpenWrt agent installed for %s\n' "$DEVICE_ID"
printf 'Backup directory: %s\n' "$BACKUP_DIR"
