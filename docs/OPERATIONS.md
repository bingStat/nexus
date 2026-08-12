# Operations

## Service ownership

Oracle runs the global identity/control entry points: v3 Registry, v3 Broker (EU), v3 MCP, Remote API, Ops and its v3 Agent. ThinkCenter runs v3 Broker (CN), Public Guard and its v3 Agent. Other production devices run only their v3 Agent and platform-specific persistence.

The production fleet baseline is six online nodes: Oracle, ThinkCenter, Victus, Victus WSL, VSC and N1. Runtime capability is live metadata; current baseline is DevSpace 1.0.6 on Oracle/ThinkCenter/Victus/Victus WSL and Shell on VSC/N1.

## Presence and monitoring

Agent liveness comes from signed Broker claim long-poll traffic. Do not add a second Registry heartbeat.

Default Ops cadence:

- health snapshot: every 3 minutes;
- alert evaluation: every 3 minutes;
- Telegram delivery: every 5 minutes;
- state archive: every 5 minutes.

Alerts use consecutive-failure/recovery thresholds to suppress flapping. Ops state is SQLite/WAL with bounded retention; Supabase is not part of the task or monitoring path.

## Dashboard

`nexus.bings.app` is a Cloudflare Worker + R2 application. The Dashboard requires the single Password Manager-backed login, while public release/install artifacts remain readable without a session. The UI renders standard roles separately from Agent runtime capability.
## Release operations

Every push to GitHub `main` triggers the authoritative R2 workflow:

```text
full regression -> stage release -> credential check -> dry-run
-> rclone sync --checksum -> checksum check -> exact object-set diff
```

A failed gate does not count as a production release. `release.json` records the source commit, run ID, timestamp and SHA-256 hashes.

Normal changes flow Victus → GitHub PR/main → GitHub Actions → R2. Do not keep a second source clone on Oracle, ThinkCenter or VSC, and do not manually mutate production R2 except emergency recovery.

## Routine checks

1. Check Registry and both Broker health endpoints.
2. Confirm six expected production device IDs and their presence state.
3. Confirm DevSpace/Shell runtime capabilities match the intended node class.
4. Confirm no legacy Nexus services, duplicate Agents or legacy `.nexus-agent` processes have returned.
5. Confirm the latest R2 workflow is green after a release change.
6. Confirm Dashboard login and public `/install.sh` both behave as intended.

## Credential operations

Human login changes begin in Bitwarden Password Manager. Machine/API credential rotation remains in Bitwarden Secrets Manager or the target platform secret store. Never copy a human password back into BSM merely to simplify automation; use hashes or a platform runtime-secret copy when a service needs unattended verification.