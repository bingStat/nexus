#!/bin/sh
set -u

AGENT_VERSION="3.0.0-openwrt"
CONFIG_FILE="${NEXUS_V3_CONFIG:-/etc/nexus-agent/v3.env}"
[ -r "$CONFIG_FILE" ] || { echo "missing config: $CONFIG_FILE" >&2; exit 1; }
. "$CONFIG_FILE"

DEVICE_ID="${NEXUS_DEVICE_ID:-}"
REGISTRY_URL="$(printf '%s' "${NEXUS_V3_REGISTRY_URL:-}" | sed 's:/*$::')"
BROKER_URL="$(printf '%s' "${NEXUS_V3_BROKER_URL:-}" | sed 's:/*$::')"
IDENTITY_KEY="${NEXUS_IDENTITY_KEY:-/etc/nexus-agent/identity_ed25519}"
IDENTITY_PUB="${NEXUS_IDENTITY_PUBLIC_KEY:-/etc/nexus-agent/identity_ed25519.pub}"
SSH_PUB="${NEXUS_SSH_PUBLIC_KEY:-$IDENTITY_PUB}"
ED25519_SIGNER="${NEXUS_ED25519_SIGNER:-/opt/nexus-agent/openwrt_ed25519_signer.rb}"
RUN_DIR="${NEXUS_RUN_DIR:-/var/run/nexus-v3-agent}"
LOCK_DIR="${NEXUS_LOCK_DIR:-/var/run/nexus-v3-agent.lock}"
POLL_SECONDS="${NEXUS_POLL_SECONDS:-1}"
WAIT_SECONDS="${NEXUS_WAIT_SECONDS:-20}"
REQUEST_TIMEOUT="${NEXUS_REQUEST_TIMEOUT:-35}"

mkdir -p "$RUN_DIR"
[ -d "$LOCK_DIR" ] || mkdir -p "$LOCK_DIR" 2>/dev/null || true
[ -n "$DEVICE_ID" ] || { echo "NEXUS_DEVICE_ID is required" >&2; exit 1; }
[ -n "$REGISTRY_URL" ] || { echo "NEXUS_V3_REGISTRY_URL is required" >&2; exit 1; }
[ -n "$BROKER_URL" ] || { echo "NEXUS_V3_BROKER_URL is required" >&2; exit 1; }
if [ -r "$IDENTITY_KEY" ] && ! sed -n '1p' "$IDENTITY_KEY" | grep -q 'BEGIN OPENSSH PRIVATE KEY'; then
  ruby "$ED25519_SIGNER" convert "$IDENTITY_KEY" "$IDENTITY_PUB" "nexus-$DEVICE_ID@$(hostname 2>/dev/null || echo openwrt)" || {
    echo "failed to convert Nexus identity key to OpenSSH format" >&2
    exit 1
  }
fi
if ! mkdir "$LOCK_DIR/instance" 2>/dev/null; then
  echo "Another Nexus v3 Agent instance is running" >&2
  exit 1
fi
cleanup_lock() {
  rmdir "$LOCK_DIR/instance" 2>/dev/null || true
}
trap cleanup_lock EXIT INT TERM

json_escape() {
  awk 'BEGIN{ORS=""}{gsub(/\\/,"\\\\");gsub(/"/,"\\\"");gsub(/\t/,"\\t");gsub(/\r/,"\\r");if(NR>1)printf "\\n";printf "%s",$0;}'
}

b64url_file() {
  openssl base64 -A < "$1" | tr '+/' '-_' | tr -d '='
}

sha256_file() {
  openssl dgst -sha256 -r "$1" | awk '{print $1}'
}

key_id() {
  ruby "$ED25519_SIGNER" key-id "$IDENTITY_PUB"
}

sign_file() {
  input_file="$1"
  output_file="$2"
  ruby "$ED25519_SIGNER" sign "$IDENTITY_KEY" "$input_file" "$output_file" && return 0
  openssl pkeyutl -sign -inkey "$IDENTITY_KEY" -rawin -in "$input_file" -out "$output_file" 2>/dev/null && return 0
  openssl pkeyutl -sign -inkey "$IDENTITY_KEY" -in "$input_file" -out "$output_file" 2>/dev/null && return 0
  return 1
}

nonce_value() {
  dd if=/dev/urandom bs=16 count=1 2>/dev/null | openssl base64 -A | tr '+/' '-_' | tr -d '='
}

signed_headers() {
  method="$1"; path_query="$2"; body_file="$3"; prefix="$4"
  timestamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  nonce="$(nonce_value)"
  msg="$RUN_DIR/$prefix.msg"
  sig="$RUN_DIR/$prefix.sig"
  {
    printf 'NEXUS-V3-ED25519\n'
    printf '%s\n' "$method"
    printf '%s\n' "$path_query"
    printf '%s\n' "$timestamp"
    printf '%s\n' "$nonce"
    printf '%s\n' "$DEVICE_ID"
    sha256_file "$body_file" | tr -d '\n'
  } > "$msg"
  sign_file "$msg" "$sig"
  printf '%s\n%s\n%s\n%s\n' "$(key_id)" "$timestamp" "$nonce" "$(b64url_file "$sig")"
}

register_device() {
  pub_json="$(json_escape < "$IDENTITY_PUB")"
  ssh_pub_json=""
  [ -r "$SSH_PUB" ] && ssh_pub_json="$(json_escape < "$SSH_PUB")"
  base="$RUN_DIR/register-base.json"
  proof_msg="$RUN_DIR/register-proof.msg"
  proof_sig="$RUN_DIR/register-proof.sig"
  payload="$RUN_DIR/register.json"
  if [ -n "$ssh_pub_json" ]; then
    printf '{"agent_version":"%s","device_id":"%s","hostname":"%s","key_id":"%s","platform":"openwrt","public_key_ed25519":"%s","ssh_public_key":"%s"}' \
      "$AGENT_VERSION" "$DEVICE_ID" "$(hostname 2>/dev/null || echo openwrt)" "$(key_id)" "$pub_json" "$ssh_pub_json" > "$base"
  else
    printf '{"agent_version":"%s","device_id":"%s","hostname":"%s","key_id":"%s","platform":"openwrt","public_key_ed25519":"%s"}' \
      "$AGENT_VERSION" "$DEVICE_ID" "$(hostname 2>/dev/null || echo openwrt)" "$(key_id)" "$pub_json" > "$base"
  fi
  { printf 'NEXUS-V3-REGISTER\n'; sha256_file "$base" | tr -d '\n'; } > "$proof_msg"
  sign_file "$proof_msg" "$proof_sig"
  proof="$(b64url_file "$proof_sig")"
  awk -v proof="$proof" '{sub(/}$/, ",\"proof\":\"" proof "\"}"); print}' "$base" > "$payload"
  curl -fsS -m "$REQUEST_TIMEOUT" -X POST "$REGISTRY_URL/v3/devices/register" -H 'Content-Type: application/json' --data-binary "@$payload" >/dev/null 2>&1 || true
}

json_get() {
  sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" "$2" | sed -n '1p'
}

claim_job() {
  empty="$RUN_DIR/empty"; : > "$empty"
  path="/v3/jobs/claim?device_id=$DEVICE_ID&agent_id=$DEVICE_ID:$(hostname 2>/dev/null || echo openwrt):$$&wait=$WAIT_SECONDS"
  set -- $(signed_headers GET "$path" "$empty" claim)
  curl -sS -m $((WAIT_SECONDS + REQUEST_TIMEOUT + 2)) -w '%{http_code}' -o "$RUN_DIR/claim.json" \
    -H "X-Nexus-Device: $DEVICE_ID" -H "X-Nexus-Key-Id: $1" -H "X-Nexus-Timestamp: $2" -H "X-Nexus-Nonce: $3" -H "X-Nexus-Signature: $4" \
    "$BROKER_URL$path" > "$RUN_DIR/claim.code" 2>/dev/null || return 1
  [ "$(cat "$RUN_DIR/claim.code")" = "200" ] || return 2
  return 0
}

complete_job() {
  id="$1"; status="$2"; exit_code="$3"; output="$4"
  payload="$RUN_DIR/complete.json"
  out_json="$(json_escape < "$output")"
  printf '{"exit_code":%s,"id":"%s","output":"%s","status":"%s"}' "$exit_code" "$id" "$out_json" "$status" > "$payload"
  set -- $(signed_headers POST /v3/jobs/complete "$payload" complete)
  curl -fsS -m "$REQUEST_TIMEOUT" -X POST "$BROKER_URL/v3/jobs/complete" \
    -H "X-Nexus-Device: $DEVICE_ID" -H "X-Nexus-Key-Id: $1" -H "X-Nexus-Timestamp: $2" -H "X-Nexus-Nonce: $3" -H "X-Nexus-Signature: $4" \
    -H 'Content-Type: application/json' --data-binary "@$payload" >/dev/null 2>&1 || true
}

register_device
while :; do
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
