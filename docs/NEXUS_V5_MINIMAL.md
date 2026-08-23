# Nexus v5 minimal architecture

Nexus v5 keeps one control-plane endpoint on Oracle and removes the v3 polling/broker path from normal execution.

## Routing

ChatGPT selects a logical device. Oracle performs an in-memory route-table lookup; there is no per-command capability probe.

- `oracle`: local execution.
- `victus`, `vsc`, `thinkcenter`: direct tailnet HTTP worker first; OpenSSH over Tailscale if the worker is unavailable.
- `n1`: SSH-only. No Nexus worker or DevSpace runtime is installed.

OpenSSH uses a persistent control socket (`ControlPersist=600`) so repeated SSH-only operations avoid a fresh handshake.

## DevSpace

The three development workers keep the existing upstream DevSpace adapter. Nexus does not reimplement workspace semantics. A failed DevSpace call uses SSH only to restart the v5 worker and then retries the direct DevSpace request once.

## Services

- Oracle: `nexus-v5-api.service`
- Development workers: `nexus-v5-worker.service` when systemd is available; VSC uses the same worker through a rootless launcher.
- N1: Tailscale/OpenSSH only.

There is no v5 broker, registry daemon, polling loop, execution ledger, or presence service. Offline deferred-job delivery is intentionally outside v5's current scope.

## Deployment

Run the fleet rollout on Oracle:

```sh
sudo NEXUS_REF=main sh deploy/nexus-v5-fleet.sh
```

The rollout stages workers, smoke-tests all configured routes, activates the Oracle API, then disables v3 runtime services. Source and configuration are retained for rollback; v3 is stopped, not destructively deleted.
