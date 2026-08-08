#!/bin/sh
set -eu

DEVICE_ID="${1:-${NEXUS_DEVICE_ID:-}}"
REGISTRY_URL="${NEXUS_V3_REGISTRY_URL:-https://nexus-global-api.bings.app}"
BROKER_URL="${NEXUS_V3_BROKER_URL:-https://nexus-broker.bings.app}"
SOURCE_BASE="${NEXUS_SOURCE_BASE:-https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394}"
INSTALL_DIR="/opt/nexus-agent"
CONFIG_DIR="/etc/nexus-agent"
CONFIG_FILE="$CONFIG_DIR/v3.env"
IDENTITY_KEY="$CONFIG_DIR/identity_ed25519"
IDENTITY_PUB="$CONFIG_DIR/identity_ed25519.pub"

fail() { printf 'nexus openwrt v3 install: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail "run as root"
[ -f /etc/openwrt_release ] || fail "OpenWrt/iStoreOS required"
[ -n "$DEVICE_ID" ] || fail "device id required"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v openssl >/dev/null 2>&1 || fail "openssl is required"
command -v ruby >/dev/null 2>&1 || fail "ruby is required for Ed25519 signing fallback"

mkdir -p "$INSTALL_DIR" "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
curl -fsSL "$SOURCE_BASE/openwrt_v3_agent.sh" -o "$INSTALL_DIR/v3-agent.sh"
curl -fsSL "$SOURCE_BASE/openwrt_ed25519_signer.rb" -o "$INSTALL_DIR/openwrt_ed25519_signer.rb"
chmod 755 "$INSTALL_DIR/v3-agent.sh" "$INSTALL_DIR/openwrt_ed25519_signer.rb"

if [ ! -f "$IDENTITY_KEY" ]; then
  openssl genpkey -algorithm Ed25519 -out "$IDENTITY_KEY" >/dev/null 2>&1 || fail "failed to generate identity key"
  openssl pkey -in "$IDENTITY_KEY" -pubout -out "$IDENTITY_PUB" >/dev/null 2>&1 || fail "failed to derive public key"
fi
chmod 600 "$IDENTITY_KEY"
chmod 644 "$IDENTITY_PUB"

quote() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
{
  printf 'NEXUS_DEVICE_ID=%s\n' "$(quote "$DEVICE_ID")"
  printf 'NEXUS_V3_REGISTRY_URL=%s\n' "$(quote "$(printf '%s' "$REGISTRY_URL" | sed 's:/*$::')")"
  printf 'NEXUS_V3_BROKER_URL=%s\n' "$(quote "$(printf '%s' "$BROKER_URL" | sed 's:/*$::')")"
  printf 'NEXUS_IDENTITY_KEY=%s\n' "$(quote "$IDENTITY_KEY")"
  printf 'NEXUS_IDENTITY_PUBLIC_KEY=%s\n' "$(quote "$IDENTITY_PUB")"
  printf 'NEXUS_ED25519_SIGNER=%s\n' "$(quote "$INSTALL_DIR/openwrt_ed25519_signer.rb")"
} > "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

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
sleep 2
ps w | grep -q '[v]3-agent.sh' || fail "nexus-v3-agent did not start"
printf 'Nexus OpenWrt v3 agent installed for %s\n' "$DEVICE_ID"
