# Nexus engineering contract

Nexus has one production path:

`Client -> Remote API / MCP -> Registry -> Regional Broker -> exact target Agent`

## Non-negotiable architecture

- Do not preserve obsolete compatibility paths. Remove them.
- Never reintroduce Supabase as a task queue or Agent transport.
- Never add shared fleet tokens to Agents; device identity is Ed25519.
- Never support `all`, `broadcast`, fuzzy target aliases, or target substitution.
- Network/Broker failover may change transport only; it must never change `target_device`.
- Registry owns identity, approval, and SSH public keys only.
- Regional Brokers own jobs, leases, idempotency, execution receipts, and Agent presence.
- Agent liveness comes from existing Broker long-poll traffic; do not add a second heartbeat loop.

## Runtime boundary

- Nexus owns the fleet control plane; it does not reimplement single-machine coding tools.
- Compatible Windows/Linux/VSC nodes reuse upstream `@waishnav/devspace` through `runtime/devspace/`.
- Workspace/worktree/read/patch/process-session semantics belong to DevSpace.
- OpenWrt/N1 may remain shell-only; do not require Node there.
- A workspace operation is always bound to the named device and may not use managed-target fallback.

## Repository discipline

- `nexus_v3/` is the control-plane package.
- `runtime/` contains upstream runtime adapters only.
- `ops/` contains low-frequency monitoring and notification logic only.
- `agent-council/` is an optional orchestration/review layer, not another control plane.
- `dashboard/`, `docs/`, `scripts/`, and `tests/` stay separated by concern.
- Secrets, local `.ai` history, caches, vendored external repos, and migration scratch files do not belong in Git.
- Prefer existing dependencies and the smallest implementation that works end to end.
- Before publishing: run pytest, compile checks, DevSpace self-test, and installer syntax checks.
