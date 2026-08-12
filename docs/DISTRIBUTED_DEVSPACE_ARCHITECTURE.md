# Distributed DevSpace architecture

Nexus is the distributed fleet control plane; DevSpace is the single-machine workspace runtime on compatible Agents.

```text
Remote API / MCP
      |
      v
exact target v3 Agent
      |
      +--> shell.execute
      |
      +--> upstream DevSpace
             workspace.open
             workspace.read
             workspace.apply_patch
             workspace.exec
             workspace.write_stdin
```

## Ownership

Nexus owns canonical device identity, approval, regional routing, job lifecycle, presence, capability discovery, audit metadata and target-device immutability. DevSpace owns workspace IDs, path containment, worktrees, file reads, patch semantics and interactive process sessions.

Nexus consumes pinned `@waishnav/devspace` through `runtime/devspace/bridge.mjs`; it does not vendor or fork DevSpace.

## Current runtime fleet

| Device | Runtime |
| --- | --- |
| `oracle` | DevSpace 1.0.6 |
| `thinkcenter` | DevSpace 1.0.6 |
| `victus` | DevSpace 1.0.6 |
| `victus-wsl` | DevSpace 1.0.6 |
| `vsc` | Shell |
| `n1` | Shell |
VSC remains Shell because the platform module currently provides Node 22.17.1 while the pinned DevSpace requires Node >= 22.19. OpenWrt/N1 remains Shell intentionally and must not acquire Node merely for Nexus.

## Workspace invariant

A workspace belongs to one physical device. `workspaceId` is meaningful only together with `device_id`; if that device is unavailable, the operation fails rather than moving to another host.

Allowed roots must be narrow project paths. DevSpace filesystem containment does not reduce the OS privileges of `workspace.exec`, so Agents should run with the least privilege that still permits the intended projects.

## Upgrade policy

Update the pin deliberately:

```bash
python scripts/update_devspace_runtime.py latest
cd runtime/devspace
npm install
npm run check
python -m pytest -q tests/test_devspace_runtime.py
```

CI must verify bridge self-test, structured-job dispatch, capability signing, workspace routing and exact-target behavior before a new DevSpace version reaches production.