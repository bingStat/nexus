# VSC / Victus reconciliation — 2026-08-11

Nexus had two production-oriented lines after commit `e1827e8`:

- Victus v3 line: Ed25519 identity, Registry, Regional Brokers, clean installers, exact-target routing, DevSpace runtime.
- VSC `nexus-perf` line: operational dashboard, service probes, alert debouncing, Telegram batching, Oracle standby, state history, legacy Supabase-based execution.

The canonical architecture is the Victus v3 line. VSC was treated as a source of production lessons, not as a branch to merge wholesale.

## Retained and rewritten

- health snapshots -> `ops/monitoring/snapshot.py`
- transition-based alert engine -> `ops/monitoring/alerts.py`
- 3/5/10 streak thresholds and 30-minute reopen suppression
- Telegram event batching, mute/resume, and replay suppression -> `ops/monitoring/telegram.py`
- SQLite operational history -> `ops/monitoring/state_store.py`
- VSC/Oracle external probes -> configurable HTTP/TCP checks in `ops/config.example.json`
- Windows deployment lessons -> root `install.ps1`
- API resilience -> Broker idempotency, lease expiry/reclaim, Agent execution ledger
- device-state thresholds -> `nexus_v3/status.py`

## Intentionally retired

- Supabase task queue / REST relay
- old shared API-token Agents
- old `mcp_server/` execution path
- N1 relay whose fallback returned to Supabase
- Oracle read-only standby built on the legacy data model
- duplicate Windows installer that downloaded legacy `agent.py`
- high-frequency probes and notification polling
- compatibility aliases, `all`/`broadcast`, and cross-device execution fallback

## Liveness decision

The temporary v3 implementation added a separate Registry heartbeat. It was removed during reconciliation. Every active Agent already long-polls its Regional Broker, so the Broker records `agent_presence` on those authenticated claim requests. The Global API merges Registry identity with EU/CN Broker presence and derives `online/degraded/offline` from that timestamp.

This avoids a second heartbeat loop, keeps Registry focused on identity, and makes liveness reflect the actual execution path.

## Source preservation

The VSC worktree was backed up before reconciliation. On Victus, migration references and removed local AI/history material are retained under ignored `.bak/` directories. These are recovery material only and are not part of the production repository.
