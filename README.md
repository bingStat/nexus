# Nexus

**Distributed DevSpace + Fleet Control Plane for a small trusted device fleet.**

Nexus routes a command or workspace operation to one exact device, using Ed25519 device identity, regional Brokers, durable execution receipts, and optional upstream DevSpace. GitHub `main` is the code source of truth; `nexus.bings.app` is the R2-backed production distribution and Dashboard entry point.

## Install

### Windows

```powershell
irm https://nexus.bings.app/install.ps1 -OutFile $env:TEMP\nexus-install.ps1
& $env:TEMP\nexus-install.ps1 -DeviceId victus -AllowedRoots @("$env:USERPROFILE\aurora")
```

### Linux / WSL

```bash
curl -fsSL https://nexus.bings.app/install.sh | sudo sh -s -- agent <device-id>
```

### VSC / HPC / other no-root Linux

```bash
curl -fsSL https://nexus.bings.app/install.sh | sh -s -- user-agent vsc
```

### OpenWrt / iStoreOS

```sh
curl -fsSL https://nexus.bings.app/install.sh | sh -s -- openwrt-agent <n1-or-ax3600>
```
### Control-plane components

```bash
curl -fsSL https://nexus.bings.app/install.sh -o /tmp/nexus-install.sh
sudo sh /tmp/nexus-install.sh registry
sudo sh /tmp/nexus-install.sh broker eu
sudo sh /tmp/nexus-install.sh broker cn
sudo sh /tmp/nexus-install.sh remote
sudo sh /tmp/nexus-install.sh ops
```

A new Agent registers as `pending`; approve it before expecting job delivery. Installers remove known retired Nexus paths before installing the current v3 runtime. Private device keys remain local.

## Production fleet

Roles describe responsibilities. Runtime is a separate live capability and must not be folded into role names.

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

## Production distribution

Every push to GitHub `main` runs the R2 publishing gate: full tests → release staging → R2 credential validation → dry-run → checksum sync → checksum verification → exact object-set verification.

`nexus.bings.app` serves public install/release artifacts from R2 and protects the Dashboard with a single-password Worker session. Human login passwords belong in **Bitwarden Password Manager**; machine/API credentials belong in **Bitwarden Secrets Manager** or platform-native secret stores.

## DevSpace

Compatible Agents advertise `runtime=devspace` and the tested DevSpace version. Nexus delegates workspace semantics to upstream `@waishnav/devspace`; it does not reimplement worktrees, patching or interactive process sessions. OpenWrt and constrained nodes remain Shell-only by design.
## Documentation

The maintained nine-document system lives under `docs/`:

1. [Project overview](docs/PROJECT_OVERVIEW.md)
2. [Clean architecture](docs/NEXUS_V3_CLEAN_ARCHITECTURE.md)
3. [Distributed DevSpace architecture](docs/DISTRIBUTED_DEVSPACE_ARCHITECTURE.md)
4. [Device identity & authentication](docs/DEVICE_IDENTITY_AUTH.md)
5. [Deployment](docs/DEPLOYMENT.md)
6. [Operations](docs/OPERATIONS.md)
7. [Security](docs/SECURITY.md)
8. [Recovery runbook](docs/RECOVERY_RUNBOOK.md)
9. [VSC / Victus reconciliation history](docs/VSC_RECONCILIATION.md)

Additional contracts: [AGENTS.md](AGENTS.md), [ChatGPT / MCP integration](NEXUS_CHATGPT_PROMPT.md), and [Ops details](ops/README.md).

## Repository layout

`nexus_v3/` control plane · `runtime/` DevSpace bridge · `ops/` monitoring · `dashboard/` R2/Worker UI · `agent-council/` optional multi-agent review · `scripts/` maintenance · `tests/` contracts.

## Validate

```bash
python -m pytest -q
python scripts/verify_v3.py
sh -n install.sh ops/install.sh runtime/devspace/install.sh nexus_v3/assets/openwrt_v3_agent.sh
```

Development happens on Victus; GitHub `main` is the canonical remote source. Production nodes keep installed runtime/configuration only, not development clones.