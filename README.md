# Nexus

**Distributed DevSpace + Fleet Control Plane for a small trusted device fleet.**

Nexus routes a command or workspace operation to one exact device through Ed25519 device identity, regional Brokers, durable execution receipts, and optional upstream DevSpace. GitHub `main` is the single code and documentation source of truth. `nexus.bings.app` is only the production Dashboard website.

## Install

### Windows

```powershell
irm https://raw.githubusercontent.com/bingStat/nexus/main/install.ps1 -OutFile $env:TEMP\nexus-install.ps1
& $env:TEMP\nexus-install.ps1 -DeviceId victus -AllowedRoots @("$env:USERPROFILE\aurora")
```

### Linux / WSL

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/main/install.sh | sudo sh -s -- agent <device-id>
```

### VSC / HPC / other no-root Linux

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/main/install.sh | sh -s -- user-agent vsc
```
### OpenWrt / iStoreOS

```sh
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/main/install.sh | sh -s -- openwrt-agent <n1-or-ax3600>
```

### Control-plane components

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/main/install.sh -o /tmp/nexus-install.sh
sudo sh /tmp/nexus-install.sh registry
sudo sh /tmp/nexus-install.sh broker eu
sudo sh /tmp/nexus-install.sh broker cn
sudo sh /tmp/nexus-install.sh remote
sudo sh /tmp/nexus-install.sh ops
```

A new Agent registers as `pending`; approve it before expecting job delivery. Installers remove known retired Nexus paths before installing the current v3 runtime. Device private keys remain local and are preserved across normal reinstall/update operations.

## Production fleet

Roles describe Nexus responsibilities. Runtime is a separate live capability and is not part of a role name.

| Device | Standard roles | Runtime |
| --- | --- | --- |
| `oracle` | `v3 Registry` · `v3 Broker (EU)` · `v3 MCP` · `Remote API` · `Ops` · `v3 Agent` | **DevSpace 1.0.6** |
| `thinkcenter` | `v3 Broker (CN)` · `v3 Agent` · `Public Guard` | **DevSpace 1.0.6** |
| `victus` | `v3 Agent` | **DevSpace 1.0.6** |
| `victus-wsl` | `v3 Agent` | **DevSpace 1.0.6** |
| `vsc` | `v3 Agent` | **Shell** |
| `n1` | `v3 Agent` | **Shell** |

Canonical IDs also reserve `elitebook` and `ax3600`; they are not part of the current registered production fleet until they register and are approved.

## Architecture

```text
ChatGPT / MCP / operator
          |
          v
     Remote API / MCP
          |
          +---- Registry: identity / approval / SSH public keys
          |
          +---- EU Broker ---- exact EU target Agent
          |
          +---- CN Broker ---- exact CN target Agent
                                |
                         Shell or DevSpace
```

The invariant is strict: failover may change transport, never `target_device`. Registry does not own liveness; signed Agent long-poll traffic updates Broker presence. Broker jobs use stable IDs, idempotency keys and leases, while each Agent keeps a local execution ledger to prevent duplicate side effects after lost acknowledgements.

## Repository layout

The repository is deliberately split by concern. The directories below are the maintained project structure; `.git/`, ignored `.bak/`, caches and generated Python metadata are local implementation artifacts, not product modules.
### `nexus_v3/` — core control plane

| File / directory | Responsibility |
| --- | --- |
| `registry.py` | Canonical device-key hashes, pending/approved/revoked state and SSH public-key directory |
| `broker.py` | Regional job queue, idempotency, leases, result receipts and Agent presence |
| `agent.py` | Device-key-authenticated registration/claim/complete loop and exact-target execution |
| `ledger.py` | Durable local execution ledger preventing duplicate side effects |
| `remote_control.py` | Fleet status aggregation and remote-control service layer |
| `chatgpt_api.py` | HTTP API used by ChatGPT/OpenAPI clients |
| `mcp_server.py` | MCP exposure of Nexus remote-control operations |
| `devspace_runtime.py` | Thin adapter between Nexus jobs and upstream DevSpace |
| `status.py` | `online / degraded / offline` derivation |
| `common.py` | Opaque device-key lifecycle, hashing, authentication headers and shared primitives |
| `assets/` | Lightweight platform assets such as the OpenWrt Agent |

### `runtime/` — external runtime adapters

`runtime/devspace/` contains the pinned upstream DevSpace integration:

- `package.json` / `package-lock.json`: reproducible `@waishnav/devspace` dependency pin;
- `bridge.mjs`: Nexus ↔ DevSpace operation bridge;
- `install.sh`: standalone runtime installation helper;
- `README.md`: runtime-specific notes.

Nexus does not vendor or reimplement DevSpace workspace semantics.
### `ops/` — monitoring and operations

- `monitoring/snapshot.py`: low-frequency fleet/service snapshots;
- `monitoring/alerts.py`: transition-based alert evaluation and anti-flapping thresholds;
- `monitoring/telegram.py`: batched Telegram delivery, mute/resume and replay suppression;
- `monitoring/state_store.py`: SQLite/WAL operational history;
- `monitoring/common.py`: shared Ops helpers;
- `systemd/`: health, alert, Telegram and state-store service/timer units;
- `config.example.json`: Ops configuration template;
- `install.sh`: production Ops installer;
- `README.md`: detailed Ops behavior and cadence.

### `dashboard/` — `nexus.bings.app`

- `index.html`: compact fleet topology, standard roles, runtime capabilities and task/status UI;
- `nexus-dashboard-worker.js`: single-password authentication, session cookie and R2 website serving;
- `wrangler.toml`: Cloudflare Worker route and R2 binding;
- `test-worker-login.mjs`: Worker authentication/route regression test;
- `package.json`: Dashboard-side test/development metadata.

Only website runtime assets are published to the `nexus` R2 bucket. Project documentation and source code are not mirrored there.

### `agent-council/` — optional multi-agent review layer

Agent Council is deliberately separate from the Nexus control plane. It coordinates advisor/reviewer workflows but does not own device routing, identity or job delivery.
Key contents:

- `council.py` / `council.ps1`: Council entry points;
- `advisor_flow.py`: advisor workflow orchestration;
- `agent_browser.py`: browser-driven advisor integration;
- `web_council.py` / `web_board.py`: local web Council and status board;
- `selectors.json`: browser selector configuration;
- `task_ids.py`: stable Council task identifiers;
- `integrations/`: OpenAPI/prompt assets used to connect Council or ChatGPT to Nexus;
- `herdr-plugin/`: Herdr integration files;
- `tests/`: Agent Council-specific regression tests;
- `NEXUS_AGENT_COUNCIL_PROMPT.md`: Council behavior contract.

### `scripts/` — maintenance and release tooling

- `approve_v3_devices.py`: explicit pending-device approval;
- `verify_v3.py`: production-contract verification helper;
- `update_devspace_runtime.py`: controlled DevSpace version update;
- `stage_r2_release.py`: stages only the Dashboard website assets for R2 publication.

### `tests/` — control-plane contracts

Regression tests cover v3 signatures/job contracts, presence/status behavior, DevSpace integration, ChatGPT/OpenAPI assets, Dashboard authentication, website-only R2 publication, and VSC reconciliation invariants.

### `docs/` — maintained nine-document engineering system

`docs/` contains exactly the nine long-lived project documents listed below; project history/runtime scratch data does not belong here.
1. [Project overview](docs/PROJECT_OVERVIEW.md)
2. [Clean architecture](docs/NEXUS_V3_CLEAN_ARCHITECTURE.md)
3. [Distributed DevSpace architecture](docs/DISTRIBUTED_DEVSPACE_ARCHITECTURE.md)
4. [Device identity & authentication](docs/DEVICE_IDENTITY_AUTH.md)
5. [Deployment](docs/DEPLOYMENT.md)
6. [Operations](docs/OPERATIONS.md)
7. [Security](docs/SECURITY.md)
8. [Recovery runbook](docs/RECOVERY_RUNBOOK.md)
9. [VSC / Victus reconciliation history](docs/VSC_RECONCILIATION.md)

### `.github/workflows/` — CI and production publishing

- `devspace-runtime.yml`: DevSpace compatibility and runtime regression gate;
- `publish-r2.yml`: full regression followed by authoritative **website-only** R2 sync, checksum verification and exact-object verification.

### Root files

| File | Purpose |
| --- | --- |
| `install.sh` | Unified Linux / WSL / VSC user-local / OpenWrt / server-component installer |
| `install.ps1` | Windows user-level v3 Agent installer |
| `AGENTS.md` | Non-negotiable Nexus engineering contract |
| `NEXUS_CHATGPT_PROMPT.md` | ChatGPT / MCP integration instructions |
| `nexus.json` | Project-level Nexus configuration/metadata |
| `pyproject.toml` | Python package metadata and dependencies |
| `README.md` | User-facing entry point and repository map |
| `.gitignore` / `.gitattributes` | Repository hygiene and text/file behavior |
### Local-only directories

`.bak/` is an ignored Victus-only recovery/archive area for reconciled patches and migration material. It is not production source, is not published, and must not be used as a compatibility path. `.git/`, caches, `__pycache__`, `.pytest_cache`, `*.egg-info` and temporary environments are generated/local metadata.

## Dashboard website and R2

R2 has one responsibility: static storage for `nexus.bings.app`.

The canonical production bucket is intentionally minimal:

```text
R2:nexus
├── index.html
└── release.json
```

`index.html` is the Dashboard. `release.json` records the Git commit, Actions run, publish time and SHA-256 for the website asset. The Cloudflare Worker code itself is deployed to Workers, not stored in R2.

README, `docs/`, installers, OpenAPI/prompt assets, Python source, DevSpace and Ops files remain on GitHub only. Every push to GitHub `main` runs the website publishing gate: full regression → stage website → R2 credential check → dry-run → checksum sync → checksum verification → exact-object verification.

The Dashboard is protected by a single-password Worker session. Human login passwords belong in **Bitwarden Password Manager**; machine/API credentials belong in **Bitwarden Secrets Manager** or platform-native secret stores.

## DevSpace

Compatible Agents advertise `runtime=devspace` and the tested DevSpace version. Nexus delegates workspace semantics to upstream `@waishnav/devspace`; it does not reimplement worktrees, patching or interactive process sessions. OpenWrt and constrained nodes remain Shell-only by design.
## Validate

```bash
python -m pytest -q
python scripts/verify_v3.py
sh -n install.sh ops/install.sh runtime/devspace/install.sh nexus_v3/assets/openwrt_v3_agent.sh
```

Production acceptance requires more than a running process: verify approval, Broker presence, exact-target execution, real exit code/result, expected runtime capability, and absence of retired duplicate Nexus services/processes.

## Development model

Development happens on Victus. GitHub `main` is the canonical remote source and documentation source. Production nodes keep installed runtime/configuration only, not development clones. Changes should flow Victus → pull request → GitHub `main` → CI; only Dashboard website assets then flow automatically to R2.
