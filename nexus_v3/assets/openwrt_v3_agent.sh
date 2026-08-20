#!/bin/sh
set -u

AGENT_VERSION="3.2.1-openwrt"
CONFIG_FILE="${NEXUS_V3_CONFIG:-/etc/nexus-agent/v3.env}"
[ -r "$CONFIG_FILE" ] || { echo "missing config: $CONFIG_FILE" >&2; exit 1; }
. "$CONFIG_FILE"

DEVICE_ID="${NEXUS_DEVICE_ID:-}"
REGISTRY_URL="$(printf '%s' "${NEXUS_V3_REGISTRY_URL:-}" | sed 's:/*$::')"
BROKER_URL="$(printf '%s' "${NEXUS_V3_BROKER_URL:-}" | sed 's:/*$::')"
DEVICE_KEY_FILE="${NEXUS_DEVICE_KEY_FILE:-/etc/nexus-agent/device.key}"
SSH_PUB="${NEXUS_SSH_PUBLIC_KEY:-/root/.ssh/id_ed25519_${DEVICE_ID}.pub}"
RUN_DIR="${NEXUS_RUN_DIR:-/var/run/nexus-v3-agent}"
LOCK_DIR="${NEXUS_LOCK_DIR:-/var/run/nexus-v3-agent.lock}"
POLL_SECONDS="${NEXUS_POLL_SECONDS:-1}"
WAIT_SECONDS="${NEXUS_WAIT_SECONDS:-20}"
REQUEST_TIMEOUT="${NEXUS_REQUEST_TIMEOUT:-35}"
SSH_SYNC_SCRIPT="${NEXUS_SSH_SYNC_SCRIPT:-/opt/nexus-agent/sync_ssh_authorized_keys.sh}"
SSH_SYNC_INTERVAL="${NEXUS_SSH_SYNC_INTERVAL:-300}"

mkdir -p "$RUN_DIR"
[ -d "$LOCK_DIR" ] || mkdir -p "$LOCK_DIR" 2>/dev/null || true
[ -n "$DEVICE_ID" ] || { echo "NEXUS_DEVICE_ID is required" >&2; exit 1; }
[ -n "$REGISTRY_URL" ] || { echo "NEXUS_V3_REGISTRY_URL is required" >&2; exit 1; }
[ -n "$BROKER_URL" ] || { echo "NEXUS_V3_BROKER_URL is required" >&2; exit 1; }
[ -r "$DEVICE_KEY_FILE" ] || { echo "missing Nexus device key" >&2; exit 1; }
DEVICE_KEY="$(tr -d '\r\n' < "$DEVICE_KEY_FILE")"
case "$DEVICE_KEY" in nxk_*) ;; *) echo "invalid Nexus device key" >&2; exit 1 ;; esac

LOCK_INSTANCE="$LOCK_DIR/instance"
acquire_lock() {
  if mkdir "$LOCK_INSTANCE" 2>/dev/null; then
    printf '%s\n' "$$" > "$LOCK_INSTANCE/pid"
    return 0
  fi
  old_pid="$(cat "$LOCK_INSTANCE/pid" 2>/dev/null || true)"
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Another Nexus v3 Agent instance is running (pid $old_pid)" >&2
    exit 1
  fi
  rm -rf "$LOCK_INSTANCE"
  mkdir "$LOCK_INSTANCE" 2>/dev/null || { echo "Unable to acquire Nexus v3 Agent lock" >&2; exit 1; }
  printf '%s\n' "$$" > "$LOCK_INSTANCE/pid"
}
cleanup_lock() {
  lock_pid="$(cat "$LOCK_INSTANCE/pid" 2>/dev/null || true)"
  [ "$lock_pid" = "$$" ] && rm -rf "$LOCK_INSTANCE"
  return 0
}
trap cleanup_lock EXIT INT TERM
acquire_lock

json_escape() {
  awk 'BEGIN{ORS=""}{gsub(/\\/,"\\\\");gsub(/"/,"\\\"");gsub(/\t/,"\\t");gsub(/\r/,"\\r");if(NR>1)printf "\\n";printf "%s",$0;}'
}

register_device() {
  ssh_pub_json=""
  [ -r "$SSH_PUB" ] && ssh_pub_json="$(json_escape < "$SSH_PUB")"
  payload="$RUN_DIR/register.json"
  if [ -n "$ssh_pub_json" ]; then
    printf '{"agent_version":"%s","capabilities":{"runtime":"shell"},"device_id":"%s","device_key":"%s","hostname":"%s","platform":"openwrt","ssh_public_key":"%s"}' \
      "$AGENT_VERSION" "$DEVICE_ID" "$DEVICE_KEY" "$(hostname 2>/dev/null || echo openwrt)" "$ssh_pub_json" > "$payload"
  else
    printf '{"agent_version":"%s","capabilities":{"runtime":"shell"},"device_id":"%s","device_key":"%s","hostname":"%s","platform":"openwrt"}' \
      "$AGENT_VERSION" "$DEVICE_ID" "$DEVICE_KEY" "$(hostname 2>/dev/null || echo openwrt)" > "$payload"
  fi
  curl -fsS -m "$REQUEST_TIMEOUT" -X POST "$REGISTRY_URL/v3/devices/register" -H 'Content-Type: application/json' --data-binary "@$payload" >/dev/null
}

json_get() {
  sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" "$2" | sed -n '1p'
}

claim_job() {
  path="/v3/jobs/claim?device_id=$DEVICE_ID&agent_id=$DEVICE_ID:$(hostname 2>/dev/null || echo openwrt):$$&wait=$WAIT_SECONDS"
  curl -sS -m $((WAIT_SECONDS + REQUEST_TIMEOUT + 2)) -w '%{http_code}' -o "$RUN_DIR/claim.json" \
    -H "X-Nexus-Device: $DEVICE_ID" -H "X-Nexus-Device-Key: $DEVICE_KEY" \
    "$BROKER_URL$path" > "$RUN_DIR/claim.code" 2>/dev/null || return 1
  [ "$(cat "$RUN_DIR/claim.code")" = "200" ] || return 2
  return 0
}

complete_job() {
  id="$1"; status="$2"; exit_code="$3"; output="$4"
  payload="$RUN_DIR/complete.json"
  out_json="$(json_escape < "$output")"
  printf '{"exit_code":%s,"id":"%s","output":"%s","status":"%s"}' "$exit_code" "$id" "$out_json" "$status" > "$payload"
  curl -fsS -m "$REQUEST_TIMEOUT" -X POST "$BROKER_URL/v3/jobs/complete" \
    -H "X-Nexus-Device: $DEVICE_ID" -H "X-Nexus-Device-Key: $DEVICE_KEY" \
    -H 'Content-Type: application/json' --data-binary "@$payload" >/dev/null 2>&1 || true
}

LAST_SSH_SYNC=0
maybe_sync_ssh_keys() {
  [ -x "$SSH_SYNC_SCRIPT" ] || return 0
  now="$(date +%s 2>/dev/null || echo 0)"
  case "$now" in ''|*[!0-9]*) now=0 ;; esac
  case "$SSH_SYNC_INTERVAL" in ''|*[!0-9]*) SSH_SYNC_INTERVAL=300 ;; esac
  if [ "$LAST_SSH_SYNC" -eq 0 ] || [ "$now" -eq 0 ] || [ $((now - LAST_SSH_SYNC)) -ge "$SSH_SYNC_INTERVAL" ]; then
    "$SSH_SYNC_SCRIPT" >/dev/null 2>&1 || true
    LAST_SSH_SYNC="$now"
  fi
}

register_device || true
maybe_sync_ssh_keys
while :; do
  maybe_sync_ssh_keys
  if claim_job; then
    id="$(json_get id "$RUN_DIR/claim.json")"
    command_text="$(json_get command "$RUN_DIR/claim.json")"
    out="$RUN_DIR/job.out"
    /bin/sh -c "$command_text" > "$out" 2>&1
    rc=$?
    [ "$rc" -eq 0 ] && status=completed || status=failed
    complete_job "$id" "$status" "$rc" "$out"
  else
    sleep "$POLL_SECONDS"
  fi
done
