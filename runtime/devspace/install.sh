#!/bin/sh
set -eu

RUNTIME_DIR="${NEXUS_DEVSPACE_RUNTIME_DIR:-/opt/nexus-agent/devspace-runtime}"
SOURCE_BASE="${NEXUS_SOURCE_BASE:-https://raw.githubusercontent.com/bingStat/nexus/agent/distributed-devspace-runtime}"
NODE_MIN_MAJOR=22

command -v node >/dev/null 2>&1 || {
  echo "DevSpace runtime skipped: Node >=22.19 is not installed" >&2
  exit 2
}
command -v npm >/dev/null 2>&1 || {
  echo "DevSpace runtime skipped: npm is not installed" >&2
  exit 2
}

node_major="$(node -p 'process.versions.node.split(".")[0]')"
[ "$node_major" -ge "$NODE_MIN_MAJOR" ] || {
  echo "DevSpace runtime skipped: Node >=22.19 is required" >&2
  exit 2
}

mkdir -p "$RUNTIME_DIR"
curl -fsSL "$SOURCE_BASE/runtime/devspace/package.json" -o "$RUNTIME_DIR/package.json"
curl -fsSL "$SOURCE_BASE/runtime/devspace/bridge.mjs" -o "$RUNTIME_DIR/bridge.mjs"
(
  cd "$RUNTIME_DIR"
  npm install --omit=dev --no-audit --no-fund
  node ./bridge.mjs --self-test
)
printf 'DevSpace runtime installed at %s\n' "$RUNTIME_DIR"
printf 'Set agent config devspace.bridge=%s/bridge.mjs and devspace.allowed_roots to enable it.\n' "$RUNTIME_DIR"
