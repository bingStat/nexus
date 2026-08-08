#!/bin/sh
set -u

AGENT_VERSION="2.6.0-openwrt-shell"
CONFIG_FILE="${NEXUS_CONFIG_FILE:-/etc/nexus-agent/config.env}"
STATE_DIR="${NEXUS_STATE_DIR:-/var/lib/nexus-agent}"
RUN_DIR="${NEXUS_RUN_DIR:-/var/run/nexus-agent}"
LOCK_DIR="${NEXUS_LOCK_DIR:-/var/run/nexus-agent.lock}"

log() {
  printf '{"ts":"%s","event":"%s","device_id":"%s","detail":"%s"}\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" "${NEXUS_DEVICE_ID:-unknown}" "$(printf '%s' "${2:-}" | tr '\n\r"' '   ')"
}

fail() {
  log "agent.failed" "$*"
  exit 1
}

[ -r "$CONFIG_FILE" ] || fail "missing config file: $CONFIG_FILE"
# shellcheck disable=SC1090
. "$CONFIG_FILE"

DEVICE_ID="${NEXUS_DEVICE_ID:-}"
DEVICE_NAME="${NEXUS_DEVICE_NAME:-$DEVICE_ID}"
BROKER_URL="$(printf '%s' "${NEXUS_BROKER_URL:-}" | sed 's:/*$::')"
API_URL="$(printf '%s' "${NEXUS_API_URL:-}" | sed 's:/*$::')"
IDENTITY_KEY="${NEXUS_IDENTITY_KEY:-/etc/nexus-agent/identity_ed25519}"
IDENTITY_PUB="${NEXUS_IDENTITY_PUBLIC_KEY:-/etc/nexus-agent/identity_ed25519.pub}"
ED25519_SIGNER="${NEXUS_ED25519_SIGNER:-/opt/nexus-agent/openwrt_ed25519_signer.rb}"
POLL_SECONDS="${NEXUS_POLL_SECONDS:-1}"
HEARTBEAT_SECONDS="${NEXUS_HEARTBEAT_SECONDS:-30}"
BROKER_WAIT_SECONDS="${NEXUS_BROKER_WAIT_SECONDS:-20}"
REQUEST_TIMEOUT="${NEXUS_REQUEST_TIMEOUT:-8}"
DEFAULT_TIMEOUT_MS="${NEXUS_DEFAULT_TIMEOUT_MS:-30000}"

[ -n "$DEVICE_ID" ] || fail "NEXUS_DEVICE_ID is required"
[ "$DEVICE_ID" = "n1" ] || [ "$DEVICE_ID" = "ax3600" ] || fail "unsupported OpenWrt device id: $DEVICE_ID"
[ -n "$BROKER_URL" ] || fail "NEXUS_BROKER_URL is required"
[ -n "$API_URL" ] || fail "NEXUS_API_URL is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v openssl >/dev/null 2>&1 || fail "openssl is required"
[ -r "$IDENTITY_KEY" ] || fail "missing identity key: $IDENTITY_KEY"
[ -r "$IDENTITY_PUB" ] || fail "missing identity public key: $IDENTITY_PUB"

mkdir -p "$STATE_DIR/ledger" "$RUN_DIR" || fail "cannot create state directories"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  fail "Another Nexus Agent instance is running"
fi
cleanup_lock() {
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup_lock EXIT
trap 'cleanup_lock; exit 0' INT TERM

HOSTNAME_VALUE="$(hostname 2>/dev/null || echo openwrt)"
AGENT_ID="$DEVICE_ID:$HOSTNAME_VALUE:$$"
LAST_HEARTBEAT=0
REGISTERED_IDENTITY=0

json_escape() {
  awk 'BEGIN{ORS=""}
    {
      gsub(/\\/,"\\\\");
      gsub(/"/,"\\\"");
      gsub(/\t/,"\\t");
      gsub(/\r/,"\\r");
      if (NR > 1) printf "\\n";
      printf "%s", $0;
    }'
}

b64url_file() {
  openssl base64 -A < "$1" | tr '+/' '-_' | tr -d '='
}

sha256_file() {
  openssl dgst -sha256 -r "$1" | awk '{print $1}'
}

key_id() {
  der_file="$RUN_DIR/public-key.der"
  if openssl pkey -pubin -in "$IDENTITY_PUB" -outform DER -out "$der_file" 2>/dev/null; then
    digest="$(openssl dgst -sha256 -r "$der_file" 2>/dev/null | awk '{print $1}')"
    if [ -n "$digest" ]; then
      printf 'sha256:%s\n' "$digest"
      return 0
    fi
  fi
  if command -v ruby >/dev/null 2>&1 && [ -r "$ED25519_SIGNER" ]; then
    ruby "$ED25519_SIGNER" key-id "$IDENTITY_PUB"
    return $?
  fi
  return 1
}

sign_file() {
  input_file="$1"
  output_file="$2"
  if openssl pkeyutl -sign -inkey "$IDENTITY_KEY" -rawin -in "$input_file" -out "$output_file" 2>/dev/null; then
    return 0
  fi
  if openssl pkeyutl -sign -inkey "$IDENTITY_KEY" -in "$input_file" -out "$output_file" 2>/dev/null; then
    return 0
  fi
  if command -v ruby >/dev/null 2>&1 && [ -r "$ED25519_SIGNER" ]; then
    ruby "$ED25519_SIGNER" sign "$IDENTITY_KEY" "$input_file" "$output_file"
    return $?
  fi
  return 1
}

nonce_value() {
  dd if=/dev/urandom bs=16 count=1 2>/dev/null | openssl base64 -A | tr '+/' '-_' | tr -d '='
}

signed_headers() {
  method="$1"
  path_query="$2"
  body_file="$3"
  prefix="$4"
  timestamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  nonce="$(nonce_value)"
  body_hash="$(sha256_file "$body_file")"
  message="$RUN_DIR/$prefix.signing-message"
  signature_bin="$RUN_DIR/$prefix.signature.bin"
  {
    printf 'NEXUS-ED25519-V1\n'
    printf '%s\n' "$method"
    printf '%s\n' "$path_query"
    printf '%s\n' "$timestamp"
    printf '%s\n' "$nonce"
    printf '%s\n' "$DEVICE_ID"
    printf '%s' "$body_hash"
  } > "$message"
  sign_file "$message" "$signature_bin"
  signature="$(b64url_file "$signature_bin")"
  printf '%s\n%s\n%s\n%s\n' "$(key_id)" "$timestamp" "$nonce" "$signature"
}

register_identity() {
  [ "$REGISTERED_IDENTITY" -eq 0 ] || return 0
  public_key_json="$(json_escape < "$IDENTITY_PUB")"
  payload_base="$RUN_DIR/register-base.json"
  payload="$RUN_DIR/register.json"
  proof_msg="$RUN_DIR/register-proof-message"
  proof_sig="$RUN_DIR/register-proof-signature.bin"
  printf '{"agent_version":"%s","device_id":"%s","hostname":"%s","key_id":"%s","platform":"openwrt","public_key_ed25519":"%s"}' \
    "$AGENT_VERSION" "$DEVICE_ID" "$HOSTNAME_VALUE" "$(key_id)" "$public_key_json" > "$payload_base"
  {
    printf 'NEXUS-REGISTER-V1\n'
    sha256_file "$payload_base" | tr -d '\n'
  } > "$proof_msg"
  sign_file "$proof_msg" "$proof_sig"
  proof="$(b64url_file "$proof_sig")"
  sed "s/}$/,\"proof\":\"$proof\"}/" "$payload_base" > "$payload"
  curl -fsS -m "$REQUEST_TIMEOUT" -X POST "$API_URL/api/device-identities/register" \
    -H "Content-Type: application/json" \
    --data-binary "@$payload" >/dev/null 2>&1 && {
      REGISTERED_IDENTITY=1
      log "identity.registered" "$(key_id)"
      return 0
    }
  log "identity.register_failed"
  return 1
}

json_get() {
  key="$1"
  file="$2"
  if command -v jsonfilter >/dev/null 2>&1; then
    jsonfilter -i "$file" -e "@.$key" 2>/dev/null
    return
  fi
  sed -n "s/.*\"$key\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" "$file" | sed -n '1p'
}

post_heartbeat() {
  now="$(date +%s)"
  [ $((now - LAST_HEARTBEAT)) -ge "$HEARTBEAT_SECONDS" ] || return 0
  LAST_HEARTBEAT="$now"
  payload="$RUN_DIR/heartbeat.json"
  cat > "$payload" <<EOF
{"device_id":"$DEVICE_ID","name":"$DEVICE_NAME","status":"online","last_seen":"$(date -u '+%Y-%m-%dT%H:%M:%SZ')","platform":"openwrt","agent_version":"$AGENT_VERSION","capabilities":{"shell":true,"openwrt":true,"procd":true,"execution_ledger":true,"regional_broker_failover":false}}
EOF
  set -- $(signed_headers POST /api/devices/heartbeat "$payload" heartbeat)
  curl -fsS -m "$REQUEST_TIMEOUT" -X POST "$API_URL/api/devices/heartbeat" \
    -H "X-Nexus-Device: $DEVICE_ID" -H "X-Nexus-Key-Id: $1" \
    -H "X-Nexus-Timestamp: $2" -H "X-Nexus-Nonce: $3" -H "X-Nexus-Signature: $4" \
    -H "Content-Type: application/json" \
    -H "Prefer: resolution=merge-duplicates,return=minimal" \
    --data-binary "@$payload" >/dev/null 2>&1 && log "heartbeat.ok" || log "heartbeat.failed"
}

claim_job() {
  body="$RUN_DIR/claim.json"
  code="$RUN_DIR/claim.code"
  wait_seconds="$BROKER_WAIT_SECONDS"
  max_time=$((wait_seconds + REQUEST_TIMEOUT + 2))
  empty="$RUN_DIR/empty-body"
  : > "$empty"
  path_query="/claim?device_id=$DEVICE_ID&agent_id=$AGENT_ID&aliases=$DEVICE_ID&wait=$wait_seconds"
  set -- $(signed_headers GET "$path_query" "$empty" claim)
  curl -sS -m "$max_time" -w "%{http_code}" -o "$body" \
    -H "X-Nexus-Device: $DEVICE_ID" -H "X-Nexus-Key-Id: $1" \
    -H "X-Nexus-Timestamp: $2" -H "X-Nexus-Nonce: $3" -H "X-Nexus-Signature: $4" \
    "$BROKER_URL$path_query" > "$code" 2>"$RUN_DIR/claim.err"
  rc=$?
  http_code="$(cat "$code" 2>/dev/null || echo 000)"
  if [ "$rc" -ne 0 ]; then
    log "claim.failed" "$(cat "$RUN_DIR/claim.err" 2>/dev/null)"
    return 1
  fi
  [ "$http_code" = "204" ] && return 2
  case "$http_code" in
    2*) [ -s "$body" ] && return 0 || return 2 ;;
    *) log "claim.http_failed" "$http_code"; return 1 ;;
  esac
}

complete_job() {
  job_id="$1"
  status="$2"
  exit_code="$3"
  output_file="$4"
  payload="$RUN_DIR/complete-$job_id.json"
  escaped_output="$(json_escape < "$output_file")"
  cat > "$payload" <<EOF
{"id":"$job_id","status":"$status","output":"$escaped_output","updated_at":"$(date -u '+%Y-%m-%dT%H:%M:%SZ')","exit_code":$exit_code,"lease_owner":"$AGENT_ID"}
EOF
  set -- $(signed_headers POST /complete "$payload" complete)
  curl -fsS -m "$REQUEST_TIMEOUT" -X POST "$BROKER_URL/complete" \
    -H "X-Nexus-Device: $DEVICE_ID" -H "X-Nexus-Key-Id: $1" \
    -H "X-Nexus-Timestamp: $2" -H "X-Nexus-Nonce: $3" -H "X-Nexus-Signature: $4" \
    -H "Content-Type: application/json" \
    --data-binary "@$payload" >/dev/null
}

safe_name() {
  printf '%s' "$1" | tr -c 'A-Za-z0-9_.-' '_'
}

execute_job() {
  job_file="$1"
  job_id="$(json_get id "$job_file")"
  command_text="$(json_get command "$job_file")"
  timeout_ms="$(json_get timeout_ms "$job_file")"
  [ -n "$timeout_ms" ] || timeout_ms="$DEFAULT_TIMEOUT_MS"
  [ -n "$job_id" ] || return 0
  [ -n "$command_text" ] || {
    printf 'Empty command\n' > "$RUN_DIR/empty-command.out"
    complete_job "$job_id" "failed" 127 "$RUN_DIR/empty-command.out" || log "complete.failed" "$job_id"
    return 0
  }

  safe_id="$(safe_name "$job_id")"
  done_file="$STATE_DIR/ledger/$safe_id.done"
  running_dir="$STATE_DIR/ledger/$safe_id.running"
  output_file="$RUN_DIR/$safe_id.out"
  script_file="$RUN_DIR/$safe_id.sh"
  if [ -f "$done_file" ]; then
    status="$(sed -n '1p' "$done_file")"
    exit_code="$(sed -n '2p' "$done_file")"
    sed '1,2d' "$done_file" > "$output_file"
    complete_job "$job_id" "$status" "$exit_code" "$output_file" || log "complete.replay_failed" "$job_id"
    return 0
  fi
  if ! mkdir "$running_dir" 2>/dev/null; then
    printf 'Duplicate execution suppressed; original execution is running or uncertain\n' > "$output_file"
    complete_job "$job_id" "failed" 125 "$output_file" || log "complete.duplicate_failed" "$job_id"
    return 0
  fi

  printf '%s\n' "$command_text" > "$script_file"
  chmod 700 "$script_file"
  timeout_seconds=$(( (timeout_ms + 999) / 1000 ))
  [ "$timeout_seconds" -ge 1 ] || timeout_seconds=1
  log "command.started" "$job_id"
  if command -v timeout >/dev/null 2>&1; then
    timeout "$timeout_seconds" /bin/sh "$script_file" > "$output_file" 2>&1
    exit_code=$?
  else
    /bin/sh "$script_file" > "$output_file" 2>&1
    exit_code=$?
  fi
  if [ "$exit_code" -eq 124 ]; then
    status="timeout"
    printf '\nCommand timed out after %ss\n' "$timeout_seconds" >> "$output_file"
  elif [ "$exit_code" -eq 0 ]; then
    status="completed"
  else
    status="failed"
  fi
  {
    printf '%s\n' "$status"
    printf '%s\n' "$exit_code"
    cat "$output_file"
  } > "$done_file"
  rmdir "$running_dir" 2>/dev/null || true
  complete_job "$job_id" "$status" "$exit_code" "$output_file" && log "command.finished" "$job_id:$status:$exit_code" || log "complete.failed" "$job_id"
}

log "agent.started" "$AGENT_VERSION broker=$BROKER_URL"
while :; do
  register_identity
  post_heartbeat
  claim_job
  claim_rc=$?
  case "$claim_rc" in
    0) execute_job "$RUN_DIR/claim.json" ;;
    2) sleep "$POLL_SECONDS" ;;
    *) sleep "$POLL_SECONDS" ;;
  esac
done
