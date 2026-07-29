#!/usr/bin/env python3
"""
Nexus Agent v2 — 跨国网络优化版
优化清单:
  1. 使用 requests.Session() 保持 HTTP / HTTPS Keep-Alive 长连接
  2. 超时参数增加至 15s，适应跨国网络抖动
  3. CAS 抢占与心跳自动重试
"""
import time
import subprocess
import requests
import socket
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

API_URL    = os.getenv("NEXUS_API_URL",   "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1")
API_KEY    = os.getenv("NEXUS_API_KEY",   "")
DEVICE_ID  = os.getenv("DEVICE_ID",   socket.gethostname())
DEVICE_NAME= os.getenv("DEVICE_NAME", DEVICE_ID)
MAX_WORKERS= int(os.getenv("MAX_WORKERS", "5"))
POLL_SEC   = float(os.getenv("POLL_SEC", "2"))
HB_SEC     = float(os.getenv("HB_SEC",  "15"))

session = requests.Session()

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
    """心跳：注册设备 + 更新 last_seen + status=online"""
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        session.post(
            f"{API_URL}/devices",
            headers={**base_headers(), "Prefer": "resolution=merge-duplicates"},
            json={
                "device_id": DEVICE_ID,
                "name":      DEVICE_NAME,
                "status":    "online",
                "last_seen": now_iso,
            },
            timeout=15
        )
        log(f"♥ heartbeat OK ({DEVICE_ID})")
    except Exception as e:
        log(f"♥ heartbeat FAIL: {e}")

def run_task(task):
    task_id    = task["id"]
    cmd_str    = task.get("command", "")
    timeout_sec= task.get("timeout_ms", 30000) / 1000.0

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
        session.patch(
            f"{API_URL}/commands?id=eq.{task_id}",
            headers=base_headers(),
            json={"status": status, "output": output},
            timeout=15
        )
    except Exception as e:
        log(f"❌ PATCH failed [{task_id[:8]}]: {e}")

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
last_hb   = 0.0

log(f"================================================")
log(f" Nexus Agent v2 | DEVICE={DEVICE_ID} | API={API_URL}")
log(f"================================================")

while True:
    now = time.time()

    # 心跳
    if now - last_hb > HB_SEC:
        heartbeat()
        last_hb = now

    # 拉取任务
    try:
        q = (
            f"status=eq.pending"
            f"&or=(target_device.ilike.{DEVICE_ID},"
            f"target_device.ilike.{DEVICE_NAME})"
            f"&order=created_at.asc&limit=5"
        )
        resp = session.get(f"{API_URL}/commands?{q}",
                           headers=base_headers(), timeout=15)

        if resp.ok:
            for task in resp.json():
                tid = task["id"]
                # CAS: pending → running
                upd = session.patch(
                    f"{API_URL}/commands?id=eq.{tid}&status=eq.pending",
                    headers={**base_headers(), "Prefer": "return=representation"},
                    json={"status": "running"},
                    timeout=15
                )
                if upd.ok and upd.json():
                    executor.submit(run_task, task)
    except Exception as e:
        log(f"Poll error: {e}")

    time.sleep(POLL_SEC)
