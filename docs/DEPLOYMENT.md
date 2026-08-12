# Deployment

All production installation artifacts are published from GitHub `main` to Cloudflare R2 and served by `nexus.bings.app`. The installers use `https://nexus.bings.app/bootstrap` as their default source tree, so installation does not depend on a second GitHub Raw download chain.

## One-click Agents

Windows:

```powershell
irm https://nexus.bings.app/install.ps1 -OutFile $env:TEMP\nexus-install.ps1
& $env:TEMP\nexus-install.ps1 -DeviceId victus -AllowedRoots @("$env:USERPROFILE\aurora")
```

Linux / WSL:

```bash
curl -fsSL https://nexus.bings.app/install.sh | sudo sh -s -- agent <device-id>
```

No-root VSC/HPC:

```bash
curl -fsSL https://nexus.bings.app/install.sh | sh -s -- user-agent vsc
```

OpenWrt / iStoreOS:

```sh
curl -fsSL https://nexus.bings.app/install.sh | sh -s -- openwrt-agent <n1-or-ax3600>
```

The installer starts the Agent immediately, preserves the device identity on reinstall and removes known retired Nexus paths.
## Control-plane roles

Download the canonical installer once:

```bash
curl -fsSL https://nexus.bings.app/install.sh -o /tmp/nexus-install.sh
```

Generic component modes are `registry`, `broker <eu|cn>`, `remote`, `ops`, `sync-ssh-keys`, and `sync-cluster-ssh`. Production-specific ports/service names are set by environment variables when they differ from defaults.

Current placement:

- Oracle: Registry `18101`, EU Broker `18102`, MCP `18130`, Remote API `18131`, Ops and Oracle v3 Agent.
- ThinkCenter: CN Broker `18120`, Public Guard and ThinkCenter v3 Agent.
- Victus: Windows v3 Agent.
- Victus WSL: Linux v3 Agent only; no Registry/Broker/MCP/Remote duplication.
- VSC: no-root user-local v3 Agent only.
- N1: OpenWrt procd v3 Agent only.

## Persistence

- Linux/WSL uses systemd.
- Windows uses `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\NexusV3Agent` and a Nexus-owned local Python venv.
- VSC/HPC uses `~/.local/nexus-agent-v3` plus a managed `~/.profile` ensure block.
- OpenWrt uses procd and a PID-aware stale-lock check.

## Approval and verification

After first registration, approve the canonical device ID using `scripts/approve_v3_devices.py` from an administrative environment. Then verify Registry approval, Broker presence, runtime capability and one harmless job receipt. A successful service start alone is not deployment acceptance.

## R2 release tree

Public objects include `install.sh`, `install.ps1`, README, OpenAPI, ChatGPT prompt, `release.json`, and the canonical `/bootstrap/*` installation subset. Dashboard HTML remains authenticated. GitHub Actions owns publication; production nodes must not edit R2 objects manually during normal operation.