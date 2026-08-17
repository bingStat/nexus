# VSC Tailscale recovery

Tailscale is independent from Desktop Commander and Nexus. This directory only stores the canonical VSC deployment/recovery script.

## Existing VSC identity

The installer preserves the existing userspace Tailscale identity:

- device name: `vsc-tier2`;
- CLI: `~/.local/bin/tailscale`;
- daemon: `~/.local/bin/tailscaled`;
- state: `~/.local/state/tailscale/tailscaled.state`;
- socket: `~/.local/state/tailscale/tailscaled.sock`;
- SOCKS5 proxy: `127.0.0.1:1055`;
- HTTP proxy: `127.0.0.1:1055`;
- DNS acceptance disabled.

The script refuses to create a new identity when the existing state file is missing.

## Long-running mechanism

`install-vsc-tailscale.sh` mirrors the stable VSC Desktop Commander supervision pattern without coupling the two services:

- detached `nohup + setsid` watchdog;
- shared `flock` single-instance lock;
- persistent runtime/log directory;
- `tailscaled` restart 5 seconds after exit;
- BackendState health check every 20 seconds;
- restart after 3 consecutive unhealthy checks;
- `tailscale up` recovery when the backend is `Stopped`.
The daemon runs in Tailscale userspace-networking mode with both SOCKS5 and HTTP proxy listeners on port 1055.

## Install / recover

From a repository checkout:

```bash
bash scripts/tailscale/install-vsc-tailscale.sh install
```

Or directly from GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/main/scripts/tailscale/install-vsc-tailscale.sh | bash -s -- install
```

After installation, the persistent control copy is:

```text
/vsc-hard-mounts/leuven-data/356/vsc35603/services/tailscale/tailscale-vsc.sh
```

Useful commands:

```bash
/vsc-hard-mounts/leuven-data/356/vsc35603/services/tailscale/tailscale-vsc.sh status
/vsc-hard-mounts/leuven-data/356/vsc35603/services/tailscale/tailscale-vsc.sh restart
tail -f /vsc-hard-mounts/leuven-data/356/vsc35603/services/tailscale/watchdog.log
```
