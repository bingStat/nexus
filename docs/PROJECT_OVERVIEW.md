# Nexus project overview

## Purpose

Nexus is a small-fleet remote control plane and distributed development layer. It gives ChatGPT/MCP and operators one consistent path to an exact device while preserving device identity, regional routing, auditability and local execution semantics.

The only production path is:

```text
Client -> Remote API / MCP -> Registry -> Regional Broker -> exact target Agent
```

Nexus does not provide cross-device task substitution. A device may be reached through a different transport or Broker path, but the logical `target_device` never changes.

## Current production fleet

| Device | Standard roles | Runtime |
| --- | --- | --- |
| `oracle` | v3 Registry · v3 Broker (EU) · v3 MCP · Remote API · Ops · v3 Agent | DevSpace 1.0.6 |
| `thinkcenter` | v3 Broker (CN) · v3 Agent · Public Guard | DevSpace 1.0.6 |
| `victus` | v3 Agent | DevSpace 1.0.6 |
| `victus-wsl` | v3 Agent | DevSpace 1.0.6 |
| `vsc` | v3 Agent | Shell |
| `n1` | v3 Agent | Shell |

`elitebook` and `ax3600` remain canonical IDs but are not current registered production nodes.

## Source and production truth

GitHub `bingStat/nexus` `main` is the code source of truth. Victus is the only development working copy. Production nodes retain installed runtime/configuration only. `nexus.bings.app` is backed by Cloudflare R2 and receives its release tree automatically from GitHub Actions.
## Product boundaries

Nexus owns device identity, approval, Regional Brokers, job lifecycle, presence, Remote API/MCP, fleet visualization, low-frequency ops and a thin DevSpace adapter. Upstream DevSpace owns workspace/worktree/read/patch/process-session semantics. Agent Council is an optional review/orchestration layer, not another control plane.

Retired concepts stay retired: Supabase task queues, shared-token Agents, `all`/`broadcast`, fuzzy target aliases, duplicate heartbeat loops, legacy control-plane fallbacks and target-device substitution.

## Credential policy

Human-facing login passwords are authoritative in Bitwarden Password Manager. Machine/API credentials remain in Bitwarden Secrets Manager or the platform-native secret store. The Nexus Dashboard stores only a Cloudflare Worker runtime secret copy of its login password; R2 and Git never contain the password.

## Nine-document system

1. `PROJECT_OVERVIEW.md` — mission, scope, fleet and source-of-truth rules.
2. `NEXUS_V3_CLEAN_ARCHITECTURE.md` — production components and data flow.
3. `DISTRIBUTED_DEVSPACE_ARCHITECTURE.md` — runtime ownership boundary.
4. `DEVICE_IDENTITY_AUTH.md` — Ed25519, approval and authentication.
5. `DEPLOYMENT.md` — installers, topology and post-install approval.
6. `OPERATIONS.md` — service ownership, monitoring and release operations.
7. `SECURITY.md` — credentials, command boundary and exposure policy.
8. `RECOVERY_RUNBOOK.md` — fault isolation and restoration procedure.
9. `VSC_RECONCILIATION.md` — historical convergence decisions and retired paths.

README is the user-facing project entry point; these nine documents are the maintained engineering reference.