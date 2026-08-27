#!/bin/sh
set -eu

ENV_FILE="${NEXUS_CHATGPT_ENV_FILE:-/etc/nexus-chatgpt-remote.env}"
OAUTH_SECRET_FILE="${NEXUS_OAUTH_SECRET_FILE:-/etc/nexus-oauth-signing-secret}"

[ -r "$ENV_FILE" ] || { echo "missing $ENV_FILE" >&2; exit 1; }
API_KEY="$(sed -n 's/^NEXUS_CHATGPT_API_KEY=//p' "$ENV_FILE" | tail -n 1)"
[ -n "$API_KEY" ] || { echo "NEXUS_CHATGPT_API_KEY missing" >&2; exit 1; }

if [ ! -s "$OAUTH_SECRET_FILE" ]; then
  umask 077
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "$OAUTH_SECRET_FILE"
fi
chmod 600 "$OAUTH_SECRET_FILE"

printf '%s' "$API_KEY" | npx wrangler secret put NEXUS_CHATGPT_API_KEY
printf '%s' "$(cat "$OAUTH_SECRET_FILE")" | npx wrangler secret put NEXUS_OAUTH_SIGNING_SECRET
echo "Nexus Worker secrets synchronized; OAuth signing secret preserved in $OAUTH_SECRET_FILE"
