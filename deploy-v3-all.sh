#!/bin/sh
set -eu

SOURCE_BASE="${NEXUS_SOURCE_BASE:-https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394}"
ORACLE_HOST="${NEXUS_ORACLE_HOST:-oracle_amd}"
THINKCENTER_HOST="${NEXUS_THINKCENTER_HOST:-root@100.103.12.14}"
N1_HOST="${NEXUS_N1_HOST:-root@100.90.67.12}"

run_ssh() {
  host=$1
  shift
  ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$host" "$@"
}

printf '%s\n' '[1/7] Deploy Oracle agent and MCP adapter'
run_ssh "$ORACLE_HOST" "curl -fsSL '$SOURCE_BASE/install-v3.sh' -o /tmp/install-v3.sh && sudo env NEXUS_SOURCE_BASE='$SOURCE_BASE' NEXUS_V3_REGISTRY_URL=https://nexus-global-api.bings.app NEXUS_V3_BROKER_URL=http://127.0.0.1:18102 bash /tmp/install-v3.sh oracle"
run_ssh "$ORACLE_HOST" "curl -fsSL '$SOURCE_BASE/install-mcp-v3.sh' -o /tmp/install-mcp-v3.sh && sudo env NEXUS_SOURCE_BASE='$SOURCE_BASE' sh /tmp/install-mcp-v3.sh"
run_ssh "$ORACLE_HOST" "sudo mkdir -p /opt/nexus-v3/scripts && sudo curl -fsSL '$SOURCE_BASE/scripts/approve_v3_devices.py' -o /opt/nexus-v3/scripts/approve_v3_devices.py && sudo curl -fsSL '$SOURCE_BASE/scripts/verify_v3.py' -o /opt/nexus-v3/scripts/verify_v3.py && sudo chmod 755 /opt/nexus-v3/scripts/*.py"

printf '%s\n' '[2/7] Deploy ThinkCenter agent'
run_ssh "$THINKCENTER_HOST" "curl -fsSL '$SOURCE_BASE/install-v3.sh' -o /tmp/install-v3.sh && env NEXUS_SOURCE_BASE='$SOURCE_BASE' NEXUS_V3_REGISTRY_URL=https://nexus-global-api.bings.app NEXUS_V3_BROKER_URL=http://127.0.0.1:18120 bash /tmp/install-v3.sh thinkcenter"

printf '%s\n' '[3/7] Refresh N1 bootstrap mirror'
run_ssh "$THINKCENTER_HOST" "mkdir -p /opt/nexus-bootstrap && for f in install-openwrt-v3.sh openwrt_v3_agent.sh openwrt_ed25519_signer.rb; do curl -fsSL '$SOURCE_BASE/'\"\$f\" -o /opt/nexus-bootstrap/\"\$f\"; done && chmod 644 /opt/nexus-bootstrap/*"

printf '%s\n' '[4/7] Deploy N1 agent through ThinkCenter'
run_ssh "$THINKCENTER_HOST" "ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new '$N1_HOST' 'curl -fsSL http://100.103.12.14:18085/install-openwrt-v3.sh -o /tmp/install-openwrt-v3.sh && NEXUS_SOURCE_BASE=http://100.103.12.14:18085 NEXUS_V3_REGISTRY_URL=https://nexus-global-api.bings.app NEXUS_V3_BROKER_URL=http://100.103.12.14:18120 sh /tmp/install-openwrt-v3.sh n1'"

printf '%s\n' '[5/7] Approve registered devices'
run_ssh "$ORACLE_HOST" "sudo python3 /opt/nexus-v3/scripts/approve_v3_devices.py oracle thinkcenter n1"

printf '%s\n' '[6/7] Verify services'
run_ssh "$ORACLE_HOST" "systemctl is-active nexus-v3-registry nexus-v3-eu-broker nexus-v3-agent nexus-v3-mcp && curl -fsS http://127.0.0.1:18101/v3/health && curl -fsS http://127.0.0.1:18102/v3/health"
run_ssh "$THINKCENTER_HOST" "systemctl is-active nexus-v3-broker nexus-v3-agent && curl -fsS http://127.0.0.1:18120/v3/health"
run_ssh "$THINKCENTER_HOST" "ssh -o BatchMode=yes '$N1_HOST' '/etc/init.d/nexus-v3-agent status'"

printf '%s\n' '[7/7] Run end-to-end verification'
run_ssh "$ORACLE_HOST" "sudo env NEXUS_V3_CN_BROKER_URL=http://100.103.12.14:18120 python3 /opt/nexus-v3/scripts/verify_v3.py oracle thinkcenter n1"
printf '%s\n' 'Nexus v3 deployment completed.'
