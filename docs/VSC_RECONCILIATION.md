# VSC / Victus reconciliation history

## Why this document exists

On 2026-08-11 Nexus had a Victus v3/DevSpace line and an older VSC production-ops line. They were deliberately converged into one architecture rather than preserved as compatibility branches.

The retained production path is:

```text
Client -> Remote API / MCP -> Registry -> Regional Broker -> exact target v3 Agent
```

Victus became the only development working copy and GitHub `main` the canonical remote source. The VSC Git source clone was removed after the histories were reconciled.

## Retained lessons

The VSC line contributed low-frequency health snapshots, debounced alert transitions, Telegram batching, SQLite operational history and production failure lessons. These were rewritten into `ops/`, Broker idempotency/leases, Agent execution ledger and status derivation rather than carrying forward the legacy execution path.

## Retired paths

Removed permanently: Supabase task queue/relay, shared-token Agents, old MCP/control-plane implementation, duplicate heartbeat loops, high-frequency probes, Oracle legacy standby, N1 Supabase relay, `all`/`broadcast`, fuzzy aliases and target-device substitution.

VSC itself now runs only one user-local v3 Agent. Legacy `.nexus-agent`, `.nexus`, old watchdog/cron/profile starts, local Broker forwarding and the VSC Nexus source repository were removed.
## Current VSC baseline

- Role: `v3 Agent`.
- Runtime: `Shell`.
- Install root: `~/.local/nexus-agent-v3`.
- Config: `~/.config/nexus-agent/v3.json`.
- Persistence: managed `~/.profile` ensure block.
- Human code-server password: Bitwarden Password Manager; VSC stores only a local Argon2 hash and starts code-server with `HASHED_PASSWORD`.
- DevSpace is intentionally disabled until the available Node runtime meets the pinned minimum.

ThinkDesk reverse-tunnel material is separated under ThinkDesk-owned paths; it is not a Nexus runtime dependency.

## Reconciliation rules going forward

Do not recreate a VSC source clone to solve an operational problem. Fix the canonical repository on Victus, merge through GitHub, then reinstall/update the VSC runtime from the GitHub canonical installer. R2 publication is only for the Dashboard website. Historical patches remain local recovery material under ignored Victus `.bak` only.