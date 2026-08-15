# Desktop Commander fleet deployment

This directory stores canonical Desktop Commander deployment/recovery scripts. Desktop Commander is independent from Nexus; Nexus is only the repository that stores these scripts.

## Current stable baseline

Desktop Commander is pinned to `0.2.47` and every node uses:

- `remote --persist-session`;
- a persistent npm/cache location;
- a single-instance lock;
- detached/background execution;
- automatic restart after failure;
- no transient `npx` production path.

### Linux machines with root/systemd

ThinkCenter, Oracle and similar Linux hosts currently use:

`systemd -> /usr/local/bin/desktop-commander-remote-run -> desktop-commander remote --persist-session`

The unit uses `Restart=always`, `RestartSec=5`, a `flock` lock, and a dedicated npm cache.

Victus WSL uses the same systemd pattern and additionally pins `DESKTOP_COMMANDER_DEVICE_NAME=victus-wsl`.
### Victus Windows

Victus uses Windows Task Scheduler because it is not a systemd host:

- runtime: `%LOCALAPPDATA%\DesktopCommanderRemote`;
- `DesktopCommanderRemote` launches the hidden PowerShell runner;
- `DesktopCommanderRemote-Watchdog` checks and restores the runner;
- the runner uses a file lock and `remote --persist-session`.

Do not replace this stable task-based deployment with a foreground `npx` process.

### VSC

VSC has no fleet-managed root system service, so `install-vsc-desktop-commander.sh` reproduces the same invariants with a detached user-space watchdog.

Persistent runtime defaults to:

`/vsc-hard-mounts/leuven-data/356/vsc35603/services/desktop-commander`

The canonical source file is:

`scripts/desktop-commander/install-vsc-desktop-commander.sh`

The runtime gets a self-contained copy at `$BASE/desktop-commander-vsc.sh`; logs, locks, npm runtime and state stay outside Git.
## VSC recovery commands

From a Nexus checkout on VSC:

```bash
bash scripts/desktop-commander/install-vsc-desktop-commander.sh install
bash scripts/desktop-commander/install-vsc-desktop-commander.sh status
bash scripts/desktop-commander/install-vsc-desktop-commander.sh restart
```

After the first installation, manual recovery does not require the repository checkout:

```bash
/vsc-hard-mounts/leuven-data/356/vsc35603/services/desktop-commander/desktop-commander-vsc.sh restart
```

To inspect the latest state:

```bash
/vsc-hard-mounts/leuven-data/356/vsc35603/services/desktop-commander/desktop-commander-vsc.sh status
tail -f /vsc-hard-mounts/leuven-data/356/vsc35603/services/desktop-commander/watchdog.log
```

Upgrade Desktop Commander fleet-wide deliberately: change the pinned version in the canonical installer, validate it, then roll it out. Do not silently follow `latest`.
