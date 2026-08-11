# Nexus DevSpace Runtime Adapter

This directory intentionally contains **no copied DevSpace source code**.

Nexus depends on the published upstream package `@waishnav/devspace` and keeps only a thin JSONL adapter (`bridge.mjs`) that maps Nexus distributed jobs onto upstream workspace primitives.

## Install

```bash
npm install --no-audit --no-fund
npm run check
```

`npm run check` imports the installed package and reports the DevSpace version and supported Nexus workspace operations.

## Upgrade upstream

From the repository root:

```bash
python scripts/update_devspace_runtime.py latest
cd runtime/devspace
npm install --no-audit --no-fund
npm run check
```

Then run the Nexus compatibility tests. The GitHub `DevSpace Runtime` workflow performs the same gate on pull requests.

## Configuration

The Python Nexus Agent launches this bridge only when its config contains:

```json
{
  "devspace": {
    "bridge": "/opt/nexus-agent/devspace-runtime/bridge.mjs",
    "allowed_roots": ["/srv/projects"],
    "state_dir": "/var/lib/nexus-agent/devspace"
  }
}
```

On Windows, use the corresponding local paths. Keep `allowed_roots` narrow. OpenWrt nodes should remain shell-only and do not need this runtime.
