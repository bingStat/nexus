# Nexus v3 recovery runbook

Recover the current v3 path only. Do not restore Supabase queues, legacy token Agents, duplicate control planes or target-substitution fallbacks.

## 1. Isolate the failing layer

Check in order:

1. Registry `/v3/health`.
2. Regional Broker `/v3/health`.
3. Device approval in Registry.
4. Broker presence for the exact device.
5. Agent process/persistence.
6. Job creation, claim, lease and completion receipt.
7. Runtime capability (`devspace` or `shell`).
8. Remote API / MCP only after the lower layers are healthy.

Do not reinstall the entire fleet before locating the failing layer.

## 2. Platform persistence

- Linux/WSL: `systemctl status nexus-v3-agent`.
- Windows: check `%LOCALAPPDATA%\NexusAgentV3\logs\agent.log` and `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\NexusV3Agent`.
- VSC: check `~/.local/nexus-agent-v3/agent.pid`, `logs/agent.log` and the managed `.profile` ensure block.
- N1/OpenWrt: `/etc/init.d/nexus-v3-agent status`; stale instance locks are PID-aware and should self-recover.

Only one v3 Agent instance should exist per canonical device ID.
## 3. Reinstall the exact node only

Use the public R2-backed installer:

```bash
curl -fsSL https://nexus.bings.app/install.sh | sudo sh -s -- agent <device-id>
```

For VSC/HPC use `user-agent`; for N1/AX3600 use `openwrt-agent`; Windows uses `install.ps1`. Reinstallers clean known retired paths but preserve current device identity unless that identity is explicitly removed.

## 4. Dashboard / R2 recovery

If `nexus.bings.app` UI is wrong, distinguish Worker code from R2 content. A GitHub `main` release should have a green `Publish Nexus to R2` run with checksum and exact-object verification. Public `/release.json` identifies the deployed commit.

A failed Dashboard login is not an R2 failure. Human password truth is in Bitwarden Password Manager; Cloudflare holds only the runtime secret copy. Do not recreate a BSM human-password secret as a shortcut.

## 5. VSC-specific recovery

VSC runs no Nexus source clone and no root service. Re-run the no-root installer if the runtime is damaged. Its platform Node 22.17.1 is below the current DevSpace minimum, so Shell runtime is expected. VSC inbound SSH remains governed by KU Leuven certificate policy.

## 6. Recovery acceptance

Finish only after the exact device is approved and online, a harmless job completes with the expected exit code, duplicate/legacy processes are absent, and the production release or Dashboard path involved in the incident has been independently verified.