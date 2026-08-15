#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="0.2.47"
DEVICE_NAME="${DESKTOP_COMMANDER_DEVICE_NAME:-vsc}"
RESTART_SEC=5

if [[ -n "${VSC_DATA:-}" && -d "${VSC_DATA}" ]]; then
  DATA_ROOT="$VSC_DATA"
elif [[ -d "/vsc-hard-mounts/leuven-data/356/vsc35603" ]]; then
  DATA_ROOT="/vsc-hard-mounts/leuven-data/356/vsc35603"
else
  DATA_ROOT="$HOME"
fi

BASE="${DC_BASE:-$DATA_ROOT/services/desktop-commander}"
RUNTIME="$BASE/runtime"
CACHE="$BASE/npm-cache"
TMP="$BASE/tmp"
LOGS="$BASE/logs"
STATE="$BASE/runtime.env"
CONTROL="$BASE/vsc.sh"
RUN_LOCK="$BASE/desktop-commander.lock"
WATCHDOG_LOCK="$BASE/watchdog.lock"
WATCHDOG_LOG="$BASE/watchdog.log"
SELF="$(cd -- "$(dirname -- "$0")" && pwd -P)/$(basename -- "$0")"
mkdir_runtime() {
  mkdir -p "$BASE" "$RUNTIME" "$CACHE" "$TMP" "$LOGS"
}

load_modules_if_needed() {
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    return 0
  fi
  [[ -r /etc/profile.d/modules.sh ]] && source /etc/profile.d/modules.sh || true
  if type module >/dev/null 2>&1; then
    module load Node.js >/dev/null 2>&1 || \
    module load nodejs >/dev/null 2>&1 || \
    module load node >/dev/null 2>&1 || true
  fi
}

sync_control() {
  mkdir_runtime
  if [[ "$(readlink -f "$SELF" 2>/dev/null || printf '%s' "$SELF")" != \
        "$(readlink -f "$CONTROL" 2>/dev/null || printf '%s' "$CONTROL")" ]]; then
    cp -f "$SELF" "$CONTROL"
    chmod 700 "$CONTROL"
  fi
}

load_state() {
  [[ -f "$STATE" ]] || { echo "Not installed. Run: $SELF install" >&2; exit 1; }
  # shellcheck disable=SC1090
  source "$STATE"
}
write_state() {
  local node_bin="$1" npm_bin="$2" dc_js="$3"
  {
    printf 'NODE_BIN=%q\n' "$node_bin"
    printf 'NPM_BIN=%q\n' "$npm_bin"
    printf 'DC_JS=%q\n' "$dc_js"
    printf 'NPM_CONFIG_CACHE=%q\n' "$CACHE"
    printf 'TMPDIR=%q\n' "$TMP"
    printf 'DEVICE_NAME=%q\n' "$DEVICE_NAME"
  } > "$STATE"
  chmod 600 "$STATE"
}

install_dc() {
  mkdir_runtime
  load_modules_if_needed
  command -v node >/dev/null 2>&1 || { echo "ERROR: node is unavailable" >&2; exit 1; }
  command -v npm >/dev/null 2>&1 || { echo "ERROR: npm is unavailable" >&2; exit 1; }

  local node_bin npm_bin dc_js
  node_bin="$(command -v node)"
  npm_bin="$(command -v npm)"
  export NPM_CONFIG_CACHE="$CACHE" npm_config_cache="$CACHE" npm_config_tmp="$TMP"
  export TMPDIR="$TMP" NO_UPDATE_NOTIFIER=1

  "$npm_bin" install -g --prefix "$RUNTIME" --no-bin-links --no-audit --no-fund \
    "@wonderwhy-er/desktop-commander@$VERSION"
  dc_js="$RUNTIME/lib/node_modules/@wonderwhy-er/desktop-commander/dist/index.js"
  [[ -f "$dc_js" ]] || { echo "ERROR: entrypoint missing: $dc_js" >&2; exit 1; }

  write_state "$node_bin" "$npm_bin" "$dc_js"
  sync_control
  stop_dc true
  start_dc

  echo "Installed Desktop Commander $VERSION"
  echo "Device name: $DEVICE_NAME"
  echo "Runtime: $BASE"
}

run_remote() {
  load_state
  mkdir_runtime
  exec 9>"$RUN_LOCK"
  if ! flock -n 9; then
    exit 73
  fi

  local stamp log
  stamp="$(date +%Y%m%d-%H%M%S)"
  log="$LOGS/remote-$stamp.log"
  find "$LOGS" -maxdepth 1 -type f -name 'remote-*.log' -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr | tail -n +21 | cut -d' ' -f2- | xargs -r rm -f

  export HOME USERPROFILE="$HOME" NPM_CONFIG_CACHE TMPDIR
  export NO_UPDATE_NOTIFIER=1 DC_REMOTE_DEVICE=1
  export DESKTOP_COMMANDER_DEVICE_NAME="$DEVICE_NAME"
  {
    echo "START $(date -Is) user=$(id -un) host=$(hostname)"
    echo "node=$NODE_BIN"
    echo "desktop_commander=$DC_JS"
  } >> "$log"

  exec "$NODE_BIN" "$DC_JS" remote --persist-session >> "$log" 2>&1
}

watchdog() {
  load_state
  mkdir_runtime
  exec 8>"$WATCHDOG_LOCK"
  flock -n 8 || exit 0
  echo "START $(date -Is) host=$(hostname) pid=$$" >> "$WATCHDOG_LOG"

  while true; do
    set +e
    "$CONTROL" _run
    rc=$?
    set -e
    if [[ "$rc" -ne 73 ]]; then
      echo "$(date -Is) remote exited rc=$rc; restart in ${RESTART_SEC}s" >> "$WATCHDOG_LOG"
    fi
    sleep "$RESTART_SEC"
  done
}

watchdog_running() {
  mkdir_runtime
  ! flock -n "$WATCHDOG_LOCK" -c true 2>/dev/null
}
start_dc() {
  load_state
  sync_control
  if watchdog_running; then
    echo "Desktop Commander watchdog already running."
    return 0
  fi

  nohup setsid "$CONTROL" _watchdog </dev/null >> "$WATCHDOG_LOG" 2>&1 &
  echo $! > "$BASE/watchdog.pid"
  sleep 2

  if watchdog_running; then
    echo "Desktop Commander started. watchdog_pid=$(cat "$BASE/watchdog.pid")"
  else
    echo "ERROR: watchdog failed to start. See $WATCHDOG_LOG" >&2
    return 1
  fi
}

stop_dc() {
  local quiet="${1:-false}"
  mkdir_runtime
  if [[ -f "$STATE" ]]; then
    load_state
    pkill -u "$(id -u)" -f "$CONTROL _watchdog" 2>/dev/null || true
    pkill -u "$(id -u)" -f "$DC_JS remote --persist-session" 2>/dev/null || true
  fi
  pkill -u "$(id -u)" -f 'npx.*desktop-commander.*remote' 2>/dev/null || true
  pkill -u "$(id -u)" -f '@wonderwhy-er/desktop-commander/dist/index\.js.*remote --persist-session' 2>/dev/null || true
  rm -f "$BASE/watchdog.pid"
  [[ "$quiet" == true ]] || echo "Desktop Commander stopped."
}
status_dc() {
  echo "Desktop Commander VSC"
  echo "version=$VERSION"
  echo "base=$BASE"
  echo "device=$DEVICE_NAME"

  if watchdog_running; then
    echo "watchdog=running"
  else
    echo "watchdog=stopped"
  fi

  if [[ -f "$STATE" ]]; then
    load_state
    pgrep -af "$DC_JS remote --persist-session" || true
  else
    echo "runtime=not-installed"
  fi

  local latest
  latest="$(ls -1t "$LOGS"/remote-*.log 2>/dev/null | head -1 || true)"
  if [[ -n "$latest" ]]; then
    echo "latest_log=$latest"
    tail -n 20 "$latest"
  fi
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [install|start|stop|restart|status]

install   Install pinned Desktop Commander $VERSION and start it.
start     Start the detached watchdog.
stop      Stop watchdog and remote process.
restart   Stop then start.
status    Show process state and latest remote log.
EOF
}
cmd="${1:-install}"
case "$cmd" in
  install) install_dc ;;
  start) start_dc ;;
  stop) stop_dc ;;
  restart)
    stop_dc true
    sleep 1
    start_dc
    ;;
  status) status_dc ;;
  _run) run_remote ;;
  _watchdog) watchdog ;;
  -h|--help|help) usage ;;
  *)
    usage >&2
    exit 2
    ;;
esac
