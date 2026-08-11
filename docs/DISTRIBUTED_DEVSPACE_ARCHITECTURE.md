# Nexus = Distributed DevSpace + Fleet Control Plane

## Definition

Nexus is the distributed control plane. DevSpace is the coding/workspace runtime on compatible individual machines.

```text
ChatGPT / Claude / Codex
          |
          v
      Nexus MCP/API
          |
   Device Registry
          |
   Regional Broker
          |
   target_device (immutable)
          |
      Nexus Agent
          |
   +------+------------------+
   |                         |
   v                         v
shell.execute          upstream DevSpace
(OpenWrt etc.)         Workspace Runtime
                             |
                open/read/apply_patch/exec
                worktree/AGENTS/skills/process
```

## Ownership boundary

### Nexus owns

- canonical device identity and Ed25519 authentication;
- approval/revocation and runtime capability discovery;
- Global API/MCP surface;
- regional routing and Brokers;
- job lifecycle, audit metadata and result delivery;
- health/availability and fleet visualization;
- the invariant that failover never changes `target_device`;
- lightweight shell-only execution for nodes where DevSpace is inappropriate.

### Upstream DevSpace owns

Nexus must not reimplement these capabilities:

- workspace IDs and workspace path containment;
- checkout/worktree creation and lifecycle;
- file read behavior;
- Codex-style `apply_patch` behavior;
- interactive process sessions (`exec_command` / `write_stdin` semantics);
- `AGENTS.md` / `CLAUDE.md` discovery;
- Agent Skills discovery;
- local agent profiles and provider integrations when enabled upstream.

Nexus consumes these through the package `@waishnav/devspace` using the thin bridge in `runtime/devspace/bridge.mjs`.

## Runtime operations

Broker jobs are structured:

```json
{
  "target_device": "victus",
  "operation": "workspace.open",
  "input": {
    "path": "C:/Users/Bing/aurora/Workstation/Nexus",
    "mode": "worktree"
  }
}
```

Supported workspace operations are:

- `workspace.open`
- `workspace.read`
- `workspace.apply_patch`
- `workspace.exec`
- `workspace.write_stdin`

Legacy shell work remains `shell.execute` and is retained for infrastructure work and lightweight nodes.

## Target-device invariant

Workspace state belongs to one physical Nexus device. A `workspaceId` is therefore meaningful only together with its `device_id`.

Nexus may change the network route or Broker used to reach a device. It may **not** execute a workspace operation on a substitute device. If the requested device is unavailable, the operation fails rather than silently moving to another machine.

The existing SSH controller fallback remains limited to shell-only managed targets such as routers. It is not used for workspace operations.

## Node classes

### DevSpace-capable

Typical examples: Linux workstations, Windows machines with a supported Node runtime, WSL, VSC user environments.

They advertise registration capabilities similar to:

```json
{
  "runtime": "devspace",
  "devspace_version": "1.0.6",
  "bridge_version": "0.1.0",
  "operations": [
    "workspace.open",
    "workspace.read",
    "workspace.apply_patch",
    "workspace.exec",
    "workspace.write_stdin"
  ]
}
```

### Shell-only

OpenWrt/N1-class nodes remain lightweight and do not acquire Node/npm merely to satisfy Nexus. They register normally and continue to run `shell.execute` jobs.

## Upstream policy

DevSpace is **not vendored and not forked** into Nexus.

`runtime/devspace/package.json` pins the tested upstream package version. A version bump is performed with:

```bash
python scripts/update_devspace_runtime.py latest
cd runtime/devspace
npm install
npm run check
pytest -q tests/test_devspace_runtime.py
```

The pin provides reproducible deployments; the update script plus CI provides a deliberate path to new upstream releases.

## Installation

The runtime is optional per node. On a compatible machine:

```bash
sh runtime/devspace/install.sh
```

Then configure the Nexus Agent with a narrow allowlist:

```json
{
  "devspace": {
    "bridge": "/opt/nexus-agent/devspace-runtime/bridge.mjs",
    "allowed_roots": ["/home/user/work", "/srv/projects"],
    "state_dir": "/var/lib/nexus-agent/devspace"
  }
}
```

Do not use `/`, a whole home directory, or an entire Windows drive as the normal workspace allowlist.

## Security boundary

The DevSpace filesystem layer constrains workspace file operations, but shell/process execution still runs with the operating-system privileges of the Nexus Agent account. Therefore DevSpace-capable Nexus Agents should run as the least-privileged account that still has the required project access.

Nexus command policy remains applied before `workspace.exec` and `shell.execute` are submitted from the control plane.

## Upgrade compatibility

Every DevSpace update must pass:

1. bridge self-test against the real installed npm package;
2. Nexus structured-job contract tests;
3. capability-registration signature test;
4. workspace-dispatch test proving it does not enter the shell path;
5. target-device invariant test;
6. existing Nexus v3 contract tests.

The GitHub workflow `.github/workflows/devspace-runtime.yml` is the compatibility gate.
