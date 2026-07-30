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
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

# Fix: force UTF-8 stdout so emoji/Chinese chars don't crash on Windows cmd
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

IS_WINDOWS = sys.platform == "win32"

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

def get_public_ip():
    apis = ['https://checkip.amazonaws.com', 'https://api.ipify.org', 'https://api.ip.sb/ip', 'http://myip.ipip.net']
    for api in apis:
        try:
            r = requests.get(api, timeout=5)
            if r.status_code == 200:
                text = r.text.strip()
                if "当前 IP" in text:
                    text = text.split("：")[1].split(" ")[0]
                return text
        except:
            pass
    return None

def heartbeat():
    """heartbeat: register device + update last_seen + status=online"""
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        ip = get_public_ip()
        status_val = f"online|ip={ip}" if ip else "online"
        session.post(
            f"{API_URL}/devices",
            headers={**base_headers(), "Prefer": "resolution=merge-duplicates"},
            json={
                "device_id": DEVICE_ID,
                "name":      DEVICE_NAME,
                "status":    status_val,
                "last_seen": now_iso,
            },
            timeout=15
        )
        log(f"[HB] heartbeat OK ({DEVICE_ID})")
    except Exception as e:
        log(f"[HB] heartbeat FAIL: {e}")

def run_task(task):
    task_id     = task["id"]
    cmd_str     = task.get("command", "")
    timeout_sec = task.get("timeout_ms", 60000) / 1000.0

    # Windows: force powershell.exe, set UTF-8 output encoding
    if IS_WINDOWS:
        orig_cmd = task.get("command", "")
        cmd_str = (
            f'powershell.exe -NoProfile -NonInteractive -Command '
            f'"$OutputEncoding=[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; '
            f'{orig_cmd.replace(chr(34), chr(92)+chr(34))}"'
        )
    log(f"[RUN] [{task_id[:8]}] {cmd_str[:100]}")

    try:
        kwargs = dict(
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            # Fix: 强制 UTF-8 解码，遇到无法解码的字符替换为 ? 而不是崩溃
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
        # Windows: 使用 CREATE_NO_WINDOW 避免弹出黑窗口
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(cmd_str, **kwargs)
        output = result.stdout.strip()
        status = "completed" if result.returncode == 0 else "failed"

    except subprocess.TimeoutExpired:
        output = f"Error: command timed out after {timeout_sec}s"
        status = "failed"
    except Exception as e:
        output = f"Error: {e}"
        status = "failed"

    log(f"[OK] [{task_id[:8]}] {status.upper()} | {output[:60]}")

    try:
        session.patch(
            f"{API_URL}/commands?id=eq.{task_id}",
            headers=base_headers(),
            json={"status": status, "output": output},
            timeout=15
        )
    except Exception as e:
        log(f"[ERR] PATCH failed [{task_id[:8]}]: {e}")

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
