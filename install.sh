#!/bin/bash
set -e

NODE_NAME="${1:-$(hostname -s 2>/dev/null || hostname)}"
API_KEY="${NEXUS_API_KEY:-eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng}"
API_URL="${NEXUS_API_URL:-https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1}"
AGENT_DIR="$HOME/.nexus-agent"

echo "=================================================="
echo " 🚀 Nexus Multi-Device Agent Installer"
echo "=================================================="
echo "📌 Node Name   : $NODE_NAME"
echo "📌 Target API  : $API_URL"
echo "📌 Install Dir : $AGENT_DIR"
echo "--------------------------------------------------"

# Cleanup legacy containers and old content
echo "🧹 Cleaning up legacy services (dc-backend, etc.)..."
if command -v docker &> /dev/null; then
    docker rm -f dc-backend dc-agent desktop-commander 2>/dev/null || true
fi
pkill -f "dc-backend" 2>/dev/null || true
pkill -f "dc_backend" 2>/dev/null || true

# Cleanup legacy crontabs
(crontab -l 2>/dev/null | grep -v "dc-backend\|dc-agent\|desktop-commander\|agent_v2.py" || true) | crontab - 2>/dev/null || true

mkdir -p "$AGENT_DIR"

if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 is required on this machine."
    exit 1
fi

cat << 'EOF' > "$AGENT_DIR/agent.py"
import time
import subprocess
import requests
import socket
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

API_URL = os.getenv("NEXUS_API_URL", "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1")
API_KEY = os.getenv("NEXUS_API_KEY", "")
DEVICE_ID = os.getenv("DEVICE_ID", socket.gethostname())
DEVICE_NAME = os.getenv("DEVICE_NAME", DEVICE_ID)
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "10"))
POLL_SEC = float(os.getenv("POLL_SEC", "2"))
HB_SEC = float(os.getenv("HB_SEC", "15"))

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def base_headers():
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
        h["apikey"] = API_KEY
    return h

def heartbeat():
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        requests.post(
            f"{API_URL}/devices",
            headers={**base_headers(), "Prefer": "resolution=merge-duplicates"},
            json={
                "device_id": DEVICE_ID,
                "name": DEVICE_NAME,
                "status": "online",
                "last_seen": now_iso,
            },
            timeout=5
        )
        log(f"♥ heartbeat OK ({DEVICE_ID})")
    except Exception as e:
        log(f"♥ heartbeat FAIL: {e}")

def run_task(task):
    task_id = task["id"]
    cmd_str = task.get("command", "")
    timeout_sec = task.get("timeout_ms", 30000) / 1000.0

    log(f"⚡ [{task_id[:8]}] RUN: {cmd_str[:80]}")

    try:
        result = subprocess.run(
            cmd_str,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_sec
        )
        output = result.stdout.strip()
        status = "completed" if result.returncode == 0 else "failed"
    except subprocess.TimeoutExpired:
        output = f"Error: command timed out after {timeout_sec}s"
        status = "failed"
    except Exception as e:
        output = f"Error: {e}"
        status = "failed"

    log(f"✅ [{task_id[:8]}] {status.upper()} | {output[:60]}")

    try:
        requests.patch(
            f"{API_URL}/commands?id=eq.{task_id}",
            headers=base_headers(),
            json={"status": status, "output": output},
            timeout=10
        )
    except Exception as e:
        log(f"❌ PATCH failed [{task_id[:8]}]: {e}")

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
last_hb = 0.0

log("==================================================")
log(f" Nexus Agent v2 | DEVICE={DEVICE_ID} | API={API_URL}")
log("==================================================")

while True:
    now = time.time()
    if now - last_hb > HB_SEC:
        heartbeat()
        last_hb = now

    try:
        q = (
            f"status=eq.pending"
            f"&or=(target_device.ilike.{DEVICE_ID},"
            f"target_device.ilike.{DEVICE_NAME})"
            f"&order=created_at.asc&limit=5"
        )
        resp = requests.get(f"{API_URL}/commands?{q}", headers=base_headers(), timeout=10)

        if resp.ok:
            for task in resp.json():
                tid = task["id"]
                upd = requests.patch(
                    f"{API_URL}/commands?id=eq.{tid}&status=eq.pending",
                    headers={**base_headers(), "Prefer": "return=representation"},
                    json={"status": "running"},
                    timeout=5
                )
                if upd.ok and upd.json():
                    executor.submit(run_task, task)
    except Exception as e:
        log(f"Poll error: {e}")

    time.sleep(POLL_SEC)
EOF

pkill -f "$AGENT_DIR/agent.py" 2>/dev/null || true

START_CMD="nohup env DEVICE_NAME=\"$NODE_NAME\" DEVICE_ID=\"$NODE_NAME\" NEXUS_API_KEY=\"$API_KEY\" NEXUS_API_URL=\"$API_URL\" python3 \"$AGENT_DIR/agent.py\" > \"$AGENT_DIR/agent.log\" 2>&1 &"

# Install into crontab for persistence
(crontab -l 2>/dev/null | grep -v "$AGENT_DIR/agent.py" ; echo "@reboot $START_CMD") | crontab -

# Start it now
eval "$START_CMD"

echo "=================================================="
echo " 🎉 Nexus Agent successfully deployed & running for [$NODE_NAME]!"
echo " 📄 Log file: $AGENT_DIR/agent.log"
echo "=================================================="
