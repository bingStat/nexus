#!/bin/sh
set -eu

[ "$(id -u)" -eq 0 ] || { echo "run on Oracle as root" >&2; exit 1; }
REF="${NEXUS_REF:-main}"
SSH_KEY="${NEXUS_V5_SSH_KEY:-/home/ubuntu/.ssh/id_ed25519_oracle}"
KNOWN="${NEXUS_V5_KNOWN_HOSTS:-/etc/nexus-v5/known_hosts}"
mkdir -p /etc/nexus-v5
chmod 700 /etc/nexus-v5
[ -f "$KNOWN" ] || : > "$KNOWN"

ssh_cmd() {
  target="$1"; shift
  ssh -n -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=5 \
    -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN" \
    "$target" "$@"
}
scp_to() {
  src="$1" target="$2" dst="$3"
  scp -q -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=5 \
    -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN" \
    "$src" "$target:$dst"
}
wait_health() {
  url="$1"
  i=0
  while [ "$i" -lt 12 ]; do
    curl -fsS --max-time 1 "$url/v5/health" >/dev/null 2>&1 && return 0
    i=$((i + 1))
    sleep 1
  done
  echo "worker health check failed: $url" >&2
  return 1
}

TOKEN=/etc/nexus-v5/token
if [ ! -s "$TOKEN" ]; then
  umask 077
  python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "$TOKEN"
fi
chmod 600 "$TOKEN"

install_root_worker() {
  target="$1" device="$2" bind="$3"
  remote_token="/tmp/nexus-v5-token.$$"
  scp_to "$TOKEN" "$target" "$remote_token"
  ssh_cmd "$target" "curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/$REF/deploy/nexus-v5.sh | NEXUS_ROLE=worker NEXUS_DEVICE_ID=$device NEXUS_BIND=$bind NEXUS_REF=$REF NEXUS_TOKEN_SOURCE=$remote_token NEXUS_RETIRE_V3=0 sh; rm -f $remote_token"
}

printf '[1/6] staging direct workers\n'
install_root_worker root@100.72.134.105 victus 100.72.134.105
install_root_worker root@100.86.0.66 thinkcenter 100.86.0.66

VSC_TARGET="vsc35603@100.123.110.53"
VSC_BASE="/data/leuven/356/vsc35603/services/nexus-v5"
VSC_NODE="$VSC_BASE/node-v22.22.0"
VSC_TOKEN="/tmp/nexus-v5-token.$$"
scp_to "$TOKEN" "$VSC_TARGET" "$VSC_TOKEN"
ssh_cmd "$VSC_TARGET" "bash -lc 'set -e; if [ ! -x $VSC_NODE/bin/node ]; then mkdir -p $VSC_BASE; curl -fsSL https://nodejs.org/dist/v22.22.0/node-v22.22.0-linux-x64.tar.xz -o /tmp/node-v22.22.0.tar.xz; tar -xJf /tmp/node-v22.22.0.tar.xz -C $VSC_BASE; mv $VSC_BASE/node-v22.22.0-linux-x64 $VSC_NODE; rm -f /tmp/node-v22.22.0.tar.xz; fi; module load Python/3.11.5-GCCcore-13.2.0 >/dev/null 2>&1; PY=\$(command -v python3); export PATH=$VSC_NODE/bin:\$PATH; curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/$REF/deploy/nexus-v5.sh | PYTHON=\$PY NEXUS_ROLE=worker NEXUS_DEVICE_ID=vsc NEXUS_BIND=100.123.110.53 NEXUS_REF=$REF NEXUS_TOKEN_SOURCE=$VSC_TOKEN NEXUS_INSTALL_ROOT=$VSC_BASE/current NEXUS_CONFIG_ROOT=$VSC_BASE/config NEXUS_STATE_ROOT=$VSC_BASE/state NEXUS_DEVSPACE_ALLOWED_ROOTS=/data/leuven/356/vsc35603 NEXUS_NODE=$VSC_NODE/bin/node NEXUS_NPM=$VSC_NODE/bin/npm NEXUS_RETIRE_V3=0 sh; rm -f $VSC_TOKEN'"

wait_health http://100.72.134.105:18505
wait_health http://100.86.0.66:18505
wait_health http://100.123.110.53:18505

printf '[2/6] staging Oracle controller\n'
curl -fsSL "https://raw.githubusercontent.com/bingStat/nexus/$REF/deploy/nexus-v5.sh" | \
  NEXUS_ROLE=controller NEXUS_DEVICE_ID=oracle NEXUS_REF="$REF" NEXUS_TOKEN_SOURCE="$TOKEN" NEXUS_ACTIVATE=0 NEXUS_RETIRE_V3=0 sh

printf '[3/6] smoke testing routes\n'
PYTHONPATH=/opt/nexus-v5 NEXUS_V5_ROUTES=/etc/nexus-v5/routes.json NEXUS_V5_TOKEN_FILE="$TOKEN" NEXUS_V5_SSH_KEY="$SSH_KEY" NEXUS_V5_KNOWN_HOSTS="$KNOWN" python3 - <<'PY'
from nexus_v5.router import Router
r=Router()
expected={
    'oracle':'v5-local',
    'victus':'v5-direct',
    'vsc':'v5-direct',
    'thinkcenter':'v5-direct',
    'n1':'v5-ssh',
}
for device, transport in expected.items():
    out=r.execute(device,'printf NEXUS_V5_SMOKE',5000)
    if out.get('status')!='completed' or 'NEXUS_V5_SMOKE' not in out.get('output',''):
        raise SystemExit(f'{device} smoke failed: {out}')
    if out.get('transport') != transport:
        raise SystemExit(f'{device} expected {transport}, got {out.get("transport")}: {out}')
    print(device, out.get('transport'), round(float(out.get('client_elapsed_ms',0)),1),'ms')
PY

printf '[4/6] activating v5 API\n'
curl -fsSL "https://raw.githubusercontent.com/bingStat/nexus/$REF/deploy/nexus-v5.sh" | \
  NEXUS_ROLE=controller NEXUS_DEVICE_ID=oracle NEXUS_REF="$REF" NEXUS_TOKEN_SOURCE="$TOKEN" NEXUS_ACTIVATE=1 NEXUS_RETIRE_V3=0 sh
for i in 1 2 3 4 5; do
  curl -fsS http://127.0.0.1:18131/health >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:18131/health >/dev/null

printf '[5/6] retiring v3 runtime\n'
for target in root@100.72.134.105 root@100.86.0.66; do
  ssh_cmd "$target" "for u in nexus-v3-agent nexus-v3-broker nexus-v5-agent nexus-v5-direct nexus-v5-eu-broker nexus-v5-cn-broker; do systemctl disable --now \$u.service >/dev/null 2>&1 || true; done"
done
ssh_cmd "$VSC_TARGET" "pkill -f '^[^ ]*python[^ ]* -m nexus_v3[.]agent( |$)' >/dev/null 2>&1 || true; if command -v crontab >/dev/null 2>&1; then (crontab -l 2>/dev/null | grep -v -E 'nexus-agent-v3|nexus_v3.agent' || true) | crontab -; fi"
ssh_cmd root@100.90.67.12 "for s in nexus-v3-agent nexus-agent nexus; do [ ! -x /etc/init.d/\$s ] || { /etc/init.d/\$s stop >/dev/null 2>&1 || true; /etc/init.d/\$s disable >/dev/null 2>&1 || true; }; done"
for u in nexus-v3-agent nexus-v3-broker nexus-v3-mcp nexus-v3-registry nexus-v3-eu-broker nexus-v3-cn-broker nexus-chatgpt-remote nexus-v5-agent nexus-v5-direct nexus-v5-eu-broker nexus-v5-cn-broker; do
  systemctl disable --now "$u.service" >/dev/null 2>&1 || true
done
systemctl restart nexus-v5-api.service

printf '[6/6] final verification\n'
PYTHONPATH=/opt/nexus-v5 NEXUS_V5_ROUTES=/etc/nexus-v5/routes.json NEXUS_V5_TOKEN_FILE="$TOKEN" NEXUS_V5_SSH_KEY="$SSH_KEY" NEXUS_V5_KNOWN_HOSTS="$KNOWN" python3 - <<'PY'
from nexus_v5.router import Router
r=Router()
rows=r.health_all()
for row in rows:
    print(row)
if any(row.get('status') != 'online' for row in rows):
    raise SystemExit('one or more Nexus v5 routes are offline')
for row in rows:
    if row['device_id'] in {'victus','vsc','thinkcenter'} and not row.get('devspace'):
        raise SystemExit(f"{row['device_id']} DevSpace is unavailable")
PY
systemctl --no-pager --full status nexus-v5-api.service | sed -n '1,8p'
printf 'Nexus v5 rollout complete; v3 runtime is disabled.\n'
