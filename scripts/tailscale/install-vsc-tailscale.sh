#!/usr/bin/env bash
set -Eeuo pipefail

DEVICE_NAME="${TAILSCALE_DEVICE_NAME:-vsc-tier2}"
RESTART_SEC="${TAILSCALE_RESTART_SEC:-5}"
HEALTH_SEC="${TAILSCALE_HEALTH_SEC:-20}"
MAX_BAD_HEALTH="${TAILSCALE_MAX_BAD_HEALTH:-3}"

if [[ -n "${VSC_DATA:-}" && -d "$VSC_DATA" ]]; then
  DATA_ROOT="$VSC_DATA"
elif [[ -d "/vsc-hard-mounts/leuven-data/356/vsc35603" ]]; then
  DATA_ROOT="/vsc-hard-mounts/leuven-data/356/vsc35603"
else
  DATA_ROOT="$HOME"
fi

BASE="${TAILSCALE_VSC_BASE:-$DATA_ROOT/services/tailscale}"
STATE_DIR="${TAILSCALE_STATE_DIR:-$HOME/.local/state/tailscale}"
STATE_FILE="$STATE_DIR/tailscaled.state"
SOCKET="$STATE_DIR/tailscaled.sock"
TAILSCALE_BIN="${TAILSCALE_BIN:-$HOME/.local/bin/tailscale}"
TAILSALED_BIN="${TAILSALED_BIN:-$HOME/.local/bin/tailscaled}"

CONTROL="$BASE/tailscale-vsc.sh"
LOG_DIR="$BASE/logs"
WATCHDOG_LOG="$BASE/watchdog.log"
WATCHDOG_LOCK="$BASE/watchdog.lock"
WATCHDOG_PID="$BASE/watchdog.pid"
DAEMON_PID="$BASE/tailscaled.pid"
SELF="$(cd -- "$(dirname -- "$0")" && pwd -P)/$(basename -- "$0")"

mkdir_runtime() {
  mkdir -p "$BASE" "$LOG_DIR" "$STATE_DIR"
}

require_existing_identity() {
  [[ -f "$STATE_FILE" ]] || {
    echo "ERROR: existing Tailscale identity not found: $STATE_FILE" >&2
    echo "Refusing to create a new VSC Tailscale identity." >&2
    exit 1
  }
}

require_bins() {
  [[ -x "$TAILSCALE_BIN" ]] || { echo "ERROR: missing $TAILSCALE_BIN" >&2; exit 1; }
  [[ -x "$TAILSALED_BIN" ]] || { echo "ERROR: missing $TAILSALED_BIN" >&2; exit 1; }
  command -v flock >/dev/null 2>&1 || { echo "ERROR: flock is required" >&2; exit 1; }
  command -v setsid >/dev/null 2>&1 || { echo "ERROR: setsid is required" >&2; exit 1; }
}

sync_control() {
  mkdir_runtime
  if [[ "$(readlink -f "$SELF" 2>/dev/null || printf '%s' "$SELF")" != \
        "$(readlink -f "$CONTROL" 2>/dev/null || printf '%s' "$CONTROL")" ]]; then
    cp -f "$SELF" "$CONTROL"
    chmod 700 "$CONTROL"
  fi
}

backend_state() {
  local json state
  if command -v timeout >/dev/null 2>&1; then
    json="$(timeout 8 "$TAILSCALE_BIN" --socket="$SOCKET" status --json 2>/dev/null || true)"
  else
    json="$("$TAILSCALE_BIN" --socket="$SOCKET" status --json 2>/dev/null || true)"
  fi
  [[ -n "$json" ]] || { echo "Unavailable"; return 0; }
  state="$(printf '%s' "$json" | sed -n 's/.*"BackendState"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
  printf '%s\n' "${state:-Unknown}"
}

watchdog_running() {
  mkdir_runtime
  ! flock -n "$WATCHDOG_LOCK" -c true 2>/dev/null
}

stop_pidfile() {
  local file="$1" pid=""
  [[ -f "$file" ]] || return 0
  pid="$(cat "$file" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.25
    done
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$file"
}

stop_legacy_daemon() {
  local pid cmd
  while read -r pid; do
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    if [[ "$cmd" == *"tailscaled"* && "$cmd" == *"tailscaled.state"* ]]; then
      kill "$pid" 2>/dev/null || true
    fi
  done < <(pgrep -u "$(id -u)" -f 'tailscaled' 2>/dev/null || true)
  sleep 1
}

run_daemon_cycle() {
  require_existing_identity
  require_bins
  mkdir_runtime
  rm -f "$SOCKET"

  local stamp log daemon state bad=0 last_state="" rc
  stamp="$(date +%Y%m%d-%H%M%S)"
  log="$LOG_DIR/tailscaled-$stamp.log"
  echo "START $(date -Is) host=$(hostname) user=$(id -un)" >> "$log"

  "$TAILSALED_BIN" \
    --tun=userspace-networking \
    --state="$STATE_FILE" \
    --socket="$SOCKET" \
    --socks5-server=127.0.0.1:1055 \
    --outbound-http-proxy-listen=127.0.0.1:1055 \
    >> "$log" 2>&1 &
  daemon=$!
  echo "$daemon" > "$DAEMON_PID"

  for _ in {1..30}; do
    kill -0 "$daemon" 2>/dev/null || break
    state="$(backend_state)"
    [[ "$state" == "Running" ]] && break
    sleep 1
  done

  while kill -0 "$daemon" 2>/dev/null; do
    state="$(backend_state)"
    if [[ "$state" != "$last_state" ]]; then
      echo "HEALTH $(date -Is) backend=$state" >> "$log"
      last_state="$state"
    fi

    case "$state" in
      Running)
        bad=0
        ;;
      Stopped)
        bad=0
        echo "RECOVER $(date -Is) tailscale up" >> "$log"
        "$TAILSCALE_BIN" --socket="$SOCKET" up \
          --hostname="$DEVICE_NAME" --accept-dns=false >> "$log" 2>&1 || true
        ;;
      NeedsLogin)
        bad=0
        echo "AUTH_REQUIRED $(date -Is): preserved identity requires login." >> "$log"
        ;;
      *)
        bad=$((bad + 1))
        if (( bad >= MAX_BAD_HEALTH )); then
          echo "UNHEALTHY $(date -Is) backend=$state; restarting tailscaled" >> "$log"
          kill "$daemon" 2>/dev/null || true
          break
        fi
        ;;
    esac
    sleep "$HEALTH_SEC"
  done

  set +e
  wait "$daemon" 2>/dev/null
  rc=$?
  set -e
  rm -f "$DAEMON_PID" "$SOCKET"

  find "$LOG_DIR" -maxdepth 1 -type f -name 'tailscaled-*.log' -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr | tail -n +21 | cut -d' ' -f2- | xargs -r rm -f
  return "$rc"
}

watchdog() {
  require_existing_identity
  require_bins
  mkdir_runtime
  exec 8>"$WATCHDOG_LOCK"
  flock -n 8 || exit 0
  echo "START $(date -Is) host=$(hostname) pid=$$" >> "$WATCHDOG_LOG"

  trap 'stop_pidfile "$DAEMON_PID"; rm -f "$SOCKET"; exit 0' TERM INT
  while true; do
    set +e
    "$CONTROL" _cycle
    local rc=$?
    set -e
    stop_pidfile "$DAEMON_PID"
    rm -f "$SOCKET"
    echo "$(date -Is) tailscaled cycle exited rc=$rc; restart in ${RESTART_SEC}s" >> "$WATCHDOG_LOG"
    sleep "$RESTART_SEC"
  done
}

start_ts() {
  require_existing_identity
  require_bins
  sync_control
  if watchdog_running; then
    echo "VSC Tailscale watchdog already running."
    return 0
  fi

  nohup setsid "$CONTROL" _watchdog </dev/null >> "$WATCHDOG_LOG" 2>&1 &
  echo $! > "$WATCHDOG_PID"
  sleep 2

  if watchdog_running; then
    echo "VSC Tailscale started. watchdog_pid=$(cat "$WATCHDOG_PID")"
  else
    echo "ERROR: watchdog failed to start. See $WATCHDOG_LOG" >&2
    return 1
  fi
}

stop_ts() {
  local quiet="${1:-false}"
  mkdir_runtime
  stop_pidfile "$WATCHDOG_PID"
  stop_pidfile "$DAEMON_PID"
  stop_legacy_daemon
  rm -f "$SOCKET"
  [[ "$quiet" == true ]] || echo "VSC Tailscale stopped."
}

status_ts() {
  mkdir_runtime
  echo "VSC Tailscale"
  echo "device=$DEVICE_NAME"
  echo "base=$BASE"
  echo "state=$STATE_FILE"
  echo "socket=$SOCKET"
  [[ -x "$TAILSCALE_BIN" ]] && echo "version=$("$TAILSCALE_BIN" version 2>/dev/null | head -1 || true)"

  if watchdog_running; then
    echo "watchdog=running"
  else
    echo "watchdog=stopped"
  fi
  echo "backend=$(backend_state)"

  [[ -f "$DAEMON_PID" ]] && echo "tailscaled_pid=$(cat "$DAEMON_PID" 2>/dev/null || true)"
  [[ -f "$WATCHDOG_PID" ]] && echo "watchdog_pid=$(cat "$WATCHDOG_PID" 2>/dev/null || true)"

  local latest
  latest="$(ls -1t "$LOG_DIR"/tailscaled-*.log 2>/dev/null | head -1 || true)"
  if [[ -n "$latest" ]]; then
    echo "latest_log=$latest"
    tail -n 20 "$latest"
  fi
}

install_ts() {
  require_existing_identity
  require_bins
  mkdir_runtime
  sync_control
  stop_ts true
  start_ts
  sleep 3
  status_ts
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [install|start|stop|restart|status]

install   Preserve the existing VSC Tailscale identity and install the watchdog.
start     Start the detached watchdog.
stop      Stop the watchdog and userspace tailscaled.
restart   Restart the watchdog and tailscaled.
status    Show watchdog, daemon, backend state and latest log.
EOF
}

cmd="${1:-install}"
case "$cmd" in
  install) install_ts ;;
  start) start_ts ;;
  stop) stop_ts ;;
  restart)
    stop_ts true
    sleep 1
    start_ts
    ;;
  status) status_ts ;;
  _cycle) run_daemon_cycle ;;
  _watchdog) watchdog ;;
  -h|--help|help) usage ;;
  *)
    usage >&2
    exit 2
    ;;
esac
