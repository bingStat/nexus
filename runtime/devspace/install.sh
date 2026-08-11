#!/bin/sh
set -eu

RUNTIME_DIR="${NEXUS_DEVSPACE_RUNTIME_DIR:-/opt/nexus-agent/devspace-runtime}"
SOURCE_BASE="${NEXUS_SOURCE_BASE:-https://raw.githubusercontent.com/bingStat/nexus/main}"
NODE_MIN_MAJOR=22

command -v node >/dev/null 2>&1 || {
  echo "DevSpace runtime skipped: Node >=22.19 is not installed" >&2
  exit 2
}
command -v npm >/dev/null 2>&1 || {
  echo "DevSpace runtime skipped: npm is not installed" >&2
  exit 2
}

node_version="$(node -p 'process.versions.node')"
node_major="$(printf '%s' "$node_version" | cut -d. -f1)"
node_minor="$(printf '%s' "$node_version" | cut -d. -f2)"
if [ "$node_major" -lt "$NODE_MIN_MAJOR" ] || { [ "$node_major" -eq 22 ] && [ "$node_minor" -lt 19 ]; }; then
  echo "DevSpace runtime skipped: Node >=22.19 is required" >&2
  exit 2
fi

mkdir -p "$RUNTIME_DIR"
curl -fsSL "$SOURCE_BASE/runtime/devspace/package.json" -o "$RUNTIME_DIR/package.json"
curl -fsSL "$SOURCE_BASE/runtime/devspace/package-lock.json" -o "$RUNTIME_DIR/package-lock.json"
curl -fsSL "$SOURCE_BASE/runtime/devspace/bridge.mjs" -o "$RUNTIME_DIR/bridge.mjs"
(
  cd "$RUNTIME_DIR"
  npm ci --omit=dev --no-audit --no-fund
  node ./bridge.mjs --self-test
)
printf 'DevSpace runtime installed at %s\n' "$RUNTIME_DIR"
printf 'Set agent config devspace.bridge=%s/bridge.mjs and devspace.allowed_roots to enable it.\n' "$RUNTIME_DIR"
