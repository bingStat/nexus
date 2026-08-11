# Nexus Operations

`ops/` is the low-frequency operational layer for Nexus v3. It was rebuilt from the production lessons in the former VSC `main` line without carrying forward its Supabase queue, token agents, or legacy dashboard APIs.

## Cadence

- fleet health snapshot: every 3 minutes
- transition-based alert evaluation: every 3 minutes
- Telegram polling/batched delivery: every 5 minutes
- SQLite state archive: every 5 minutes

## Alert policy

Incidents are not emitted on one failed probe. Services require 3 consecutive failures, devices and low-priority targets default to 5, recovery requires 3 consecutive successes, and a subject that recovered within 30 minutes requires 10 failures before reopening. `degraded` never pages.

Telegram intentionally seeds the current event IDs on first bind, upgrade, `/start`, and `/resume`; historical incidents are therefore not replayed. Multiple new incidents/recoveries are sent in one message.

## Deployment

```bash
sudo ./ops/install.sh
sudo editor /etc/nexus/ops.json
```

The module reads v3 `/api/status`; it does not query Supabase. Keep the Telegram token only in `/etc/nexus/telegram.token`, never in Git.
