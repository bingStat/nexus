# Nexus v3 security baseline

## Device trust

Each Agent owns a Nexus-specific Ed25519 private key. Registry stores only public identity and approval state. Signed claim/complete requests include canonical device ID, timestamp, nonce and request-body hash; replay and stale timestamps are rejected.

No shared fleet token is stored on Agents. `all`, `broadcast`, fuzzy aliases and target substitution are prohibited.

## Execution boundary

A command or workspace operation must name one canonical device. If that device is offline, unapproved or lacks the requested runtime, the operation fails. Network/Broker failover may change transport only.

Dangerous operations remain explicit and reviewable: destructive filesystem/database actions, network/firewall/routing changes, reboots, private-key/password/token changes, storage formatting and changes outside the Nexus-managed SSH block.

## Human passwords vs machine secrets

**Bitwarden Password Manager** is authoritative for human-facing passwords such as Nexus Dashboard, VSC/code-server and OpenList.

**Bitwarden Secrets Manager** or platform-native secret stores are for machine/API credentials: Cloudflare/R2 tokens, Nexus admin/service keys, GitHub automation credentials, Agent-related machine credentials and similar unattended secrets.

Do not duplicate human passwords into Secrets Manager. If unattended verification is required, prefer a one-way hash or the platform's runtime-secret mechanism.
## Dashboard security

`nexus.bings.app` Dashboard uses a Cloudflare Worker runtime secret and issues a `__Host-nexus_session` cookie with HttpOnly, Secure and SameSite=Strict. Login responses are `no-store`; open redirects are rejected. Password plaintext is absent from R2 and Git.

The only intentionally public website metadata path is `/release.json`. Dashboard HTML and live status remain authenticated. README, installers, docs, OpenAPI/prompt assets and source code are not stored in R2.

## VSC

VSC inbound SSH remains constrained by KU Leuven HPC certificate policy. Nexus must not bypass that policy with ordinary `authorized_keys`. VSC code-server stores a local Argon2 password hash and starts with `HASHED_PASSWORD`; the human plaintext remains only in Password Manager.

## Repository and release hygiene

Never commit private keys, browser cookies, MFA material, API keys, runtime databases, execution ledgers, `.env` secrets or Password Manager exports. GitHub `main` is the source of truth; GitHub Actions publishes a deliberate R2 subset and verifies exact objects/checksums.

## Acceptance

Security-sensitive changes require more than `service active`: verify approval, signed job execution, exact target, real exit code, relevant key/cookie behavior, and absence of retired service/process paths.