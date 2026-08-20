#!/bin/sh
set -eu
REGISTRY_URL="${NEXUS_V3_REGISTRY_URL:-http://127.0.0.1:18101}"
BROKER_URL="${NEXUS_V3_BROKER_URL:-http://127.0.0.1:18102}"
ENV_FILE="${NEXUS_V3_ENV_FILE:-/etc/nexus-v3.env}"
MAX_AGE="${NEXUS_WATCHDOG_MAX_AGE:-120}"
REGISTRY_SERVICE="${NEXUS_WATCHDOG_REGISTRY_SERVICE:-nexus-v3-registry.service}"
BROKER_SERVICE="${NEXUS_WATCHDOG_BROKER_SERVICE:-nexus-v3-eu-broker.service}"
AGENT_SERVICE="${NEXUS_WATCHDOG_AGENT_SERVICE:-nexus-v3-agent.service}"
AGENT_CONFIG="${NEXUS_AGENT_CONFIG:-/etc/nexus-agent/v3.json}"
[ -r "$ENV_FILE" ] && . "$ENV_FILE"
DEVICE_ID="${NEXUS_WATCHDOG_DEVICE_ID:-}"
if [ -z "$DEVICE_ID" ] && [ -r "$AGENT_CONFIG" ]; then
  DEVICE_ID="$(python3 - "$AGENT_CONFIG" <<'PY'
import json,sys
try: print(json.load(open(sys.argv[1],encoding='utf-8')).get('device_id',''))
except Exception: print('')
PY
)"
fi
[ -n "$DEVICE_ID" ] || DEVICE_ID="$(hostname | tr 'A-Z' 'a-z')"
log(){ logger -t nexus-functional-watchdog -- "$*" 2>/dev/null || true; printf '%s\n' "$*"; }
registry_ok(){ curl -fsS --max-time 5 "$REGISTRY_URL/v3/devices/$DEVICE_ID/auth-key-hash" | grep -q '"status":"approved"'; }
broker_ok(){ curl -fsS --max-time 5 "$BROKER_URL/v3/health" | grep -q '"status":"ok"'; }
agent_fresh(){
  python3 - "$BROKER_URL" "$DEVICE_ID" "$MAX_AGE" "${NEXUS_V3_ADMIN_KEY:-}" <<'PY'
import sys,json,datetime,urllib.request
url,device,max_age,key=sys.argv[1],sys.argv[2],int(sys.argv[3]),sys.argv[4]
req=urllib.request.Request(url.rstrip('/')+'/v3/agents',headers={'X-Nexus-Admin-Key':key})
with urllib.request.urlopen(req,timeout=5) as r: data=json.load(r)
rows=[x for x in data.get('agents',[]) if x.get('device_id')==device]
if not rows: raise SystemExit(1)
ts=max(x['last_seen'] for x in rows)
dt=datetime.datetime.fromisoformat(ts.replace('Z','+00:00'))
age=(datetime.datetime.now(datetime.timezone.utc)-dt).total_seconds()
raise SystemExit(0 if age <= max_age else 1)
PY
}
fail=0
if ! registry_ok; then
  log 'registry functional check failed; restarting registry and broker'
  systemctl restart "$REGISTRY_SERVICE" "$BROKER_SERVICE" || true
  sleep 2
  registry_ok || fail=1
fi
if ! broker_ok; then
  log 'broker health check failed; restarting broker'
  systemctl restart "$BROKER_SERVICE" || true
  sleep 2
  broker_ok || fail=1
fi
if ! agent_fresh; then
  log "$DEVICE_ID agent presence stale; restarting agent"
  systemctl restart "$AGENT_SERVICE" || true
  sleep 3
  agent_fresh || fail=1
fi
if [ "$fail" -ne 0 ]; then
  log 'functional watchdog still unhealthy after recovery'
  exit 1
fi
log 'functional checks passed'
