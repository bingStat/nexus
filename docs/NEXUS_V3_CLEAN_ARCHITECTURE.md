# Nexus v3 clean architecture

## Single production path

```text
Client / ChatGPT / MCP
          |
          v
Remote API / MCP Adapter
          |
          +--> Registry: identity / approval / SSH public-key directory
          |
          +--> EU Broker -----> exact EU target Agent
          |
          +--> CN Broker -----> exact CN target Agent
                                  |
                           Shell or DevSpace
```

The non-negotiable invariant is that failover may change transport, never `target_device`. Offline, unapproved or incapable targets fail explicitly; another machine must not silently execute in their place.

## Production placement

| Component | Host | Listener / storage |
| --- | --- | --- |
| v3 Registry | Oracle | `127.0.0.1:18101`, `/var/lib/nexus-v3/registry.db` |
| v3 Broker (EU) | Oracle | `127.0.0.1:18102`, EU Broker DB |
| v3 Broker (CN) | ThinkCenter | `127.0.0.1:18120`, CN Broker DB |
| v3 MCP | Oracle | `18130` |
| Remote API | Oracle | `18131` |
| Ops | Oracle | systemd timers + `/var/lib/nexus/ops/` |
| Dashboard Worker + static release | Cloudflare Worker + R2 | `nexus.bings.app` |

Agents run on Oracle, ThinkCenter, Victus, Victus WSL, VSC and N1. Registry owns identity only; Broker long-poll traffic is the liveness source.
## Reliability model

A Broker job has a stable job ID, idempotency key, attempt count and lease. If an Agent disappears, an expired lease may return the job to pending. The Agent execution ledger records operation hashes and terminal results so a command that executed before an acknowledgement was lost does not execute twice.

Presence is updated by the signed `/v3/jobs/claim` long-poll already required for work delivery. There is no second Registry heartbeat loop.

## Runtime boundary

`runtime=devspace` nodes use the pinned upstream `@waishnav/devspace` bridge for workspace operations. Shell-only nodes use `shell.execute`. Runtime capability is live Agent metadata and is separate from standard roles.

## Distribution boundary

GitHub `main` is canonical code. GitHub Actions stages the R2 release, including public install/bootstrap artifacts, then performs checksum sync and exact-object verification. `nexus.bings.app` protects the Dashboard and `/status.json`, while install scripts, README, OpenAPI, prompt, release metadata and `/bootstrap/*` are read-only public release assets.

## Current persistence

- Linux system Agents: systemd.
- Windows Agent: user-level `HKCU\...\Run\NexusV3Agent`, not a privileged Scheduled Task.
- VSC/HPC Agent: user-local runtime plus a managed `~/.profile` ensure block.
- OpenWrt Agent: procd with PID-aware stale-lock recovery.

No production node should retain a Nexus development Git clone except Victus.