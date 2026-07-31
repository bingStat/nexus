# Nexus Agent One-Liner Installer for Windows (PowerShell)
param(
    [string]$NodeName = $env:COMPUTERNAME,
    [string]$ApiKey = "${NEXUS_SECRET_FROM_ENV}",
    [string]$ApiUrl = "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1"
)

$ErrorActionPreference = "Stop"
$AgentDir = "$env:USERPROFILE\.nexus-agent"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Nexus Multi-Device Agent Installer (Windows)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Node Name   : $NodeName"
Write-Host "Target API  : $ApiUrl"
Write-Host "Install Dir : $AgentDir"
Write-Host "--------------------------------------------------"

Write-Host "Cleaning up legacy services (dc-backend, etc.)..." -ForegroundColor Yellow
if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker rm -f dc-backend dc-agent desktop-commander 2>$null
}
Stop-Process -Name "dc-backend" -ErrorAction SilentlyContinue | Out-Null
Stop-Process -Name "dc_backend" -ErrorAction SilentlyContinue | Out-Null

if (-not (Test-Path $AgentDir)) {
    New-Item -ItemType Directory -Path $AgentDir | Out-Null
}

$PyPath = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $PyPath) {
    if (Test-Path "C:\Users\Bing\miniconda3\python.exe") {
        $PyPath = "C:\Users\Bing\miniconda3\python.exe"
    } else {
        Write-Error "Python executable not found in PATH. Please install Python or specify path."
        exit 1
    }
}

$AgentCode = @"
import time
import requests
import subprocess
import os
import sys
import socket
from datetime import datetime, timezone

# Single Instance Lock to prevent duplicate background instances
def acquire_single_instance_lock():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 49158))
        return sock
    except Exception:
        print("[Nexus Agent] Another instance is already running. Exiting.", flush=True)
        sys.exit(0)

_instance_lock = acquire_single_instance_lock()

API_URL = "$ApiUrl"
API_KEY = "${NEXUS_SECRET_FROM_ENV}"

# Single Canonical Device ID
CANONICAL_DEVICE_ID = "victus"
DEVICE_NAME = "Victus Workstation"

# Task matching aliases
NODE_ALIASES = list(set([
    "victus",
    "yang",
    "$NodeName".lower(),
    socket.gethostname().lower(),
    "all",
    "broadcast"
]))

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
                "device_id": CANONICAL_DEVICE_ID,
                "name": DEVICE_NAME,
                "status": "online",
                "last_seen": now_iso,
            },
            timeout=5
        )
        log(f"â™¥ Heartbeat OK ({CANONICAL_DEVICE_ID})")
    except Exception as e:
        log(f"â™¥ Heartbeat FAIL: {e}")

def fetch_and_execute():
    try:
        or_terms = ",".join([f"target_device.ilike.{alias}" for alias in NODE_ALIASES if alias])
        q = f"status=eq.pending&or=({or_terms})&order=created_at.asc&limit=5"
        r = requests.get(f"{API_URL}/commands?{q}", headers=base_headers(), timeout=5)
        if r.ok:
            for cmd in r.json():
                cmd_id = cmd.get("id")
                command_str = cmd.get("command")
                if not cmd_id or not command_str:
                    continue
                
                log(f"âš¡ [{cmd_id[:8]}]: {command_str[:60]}")
                requests.patch(f"{API_URL}/commands?id=eq.{cmd_id}&status=eq.pending", headers={**base_headers(), "Prefer": "return=representation"}, json={"status": "running"}, timeout=5)

                try:
                    res = subprocess.run(
                        ["powershell", "-NoProfile", "-Command", command_str],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
                    )
                    output = res.stdout
                    if res.stderr:
                        output += "\n[stderr]\n" + res.stderr
                    status = "completed" if res.returncode == 0 else "failed"
                except subprocess.TimeoutExpired:
                    output = "Error: Command timed out (60s)"
                    status = "failed"
                except Exception as ex:
                    output = f"Error: {str(ex)}"
                    status = "failed"

                requests.patch(f"{API_URL}/commands?id=eq.{cmd_id}", headers=base_headers(), json={"status": status, "output": output.strip()}, timeout=5)
    except Exception as e:
        pass

def main():
    last_hb = 0
    while True:
        now = time.time()
        if now - last_hb > 15:
            heartbeat()
            last_hb = now
        fetch_and_execute()
        time.sleep(2)

if __name__ == "__main__":
    main()
"@

Set-Content -Path "$AgentDir\run_win_agent.py" -Value $AgentCode -Encoding UTF8

$ScriptPath = "$AgentDir\run_win_agent.py"
Get-WmiObject Win32_Process -Filter "name='python.exe' and CommandLine like '%run_win_agent.py%'" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$LogPath = "$AgentDir\agent.log"

# Register Task Scheduler task for auto-start and crash recovery
try {
    Unregister-ScheduledTask -TaskName "NexusAgent" -Confirm:$false -ErrorAction SilentlyContinue
    $Action = New-ScheduledTaskAction -Execute "$PyPath" -Argument "-u `"$ScriptPath`""
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 365)
    Register-ScheduledTask -TaskName "NexusAgent" -Action $Action -Trigger $Trigger -Settings $Settings -User $env:USERNAME -Force | Out-Null
    Write-Host "Registered Task Scheduler daemon [NexusAgent]" -ForegroundColor Green
} catch {
    Write-Host "Task Scheduler registration fallback to Startup VBS" -ForegroundColor Yellow
}

# Also keep Startup VBS for redundancy
$StartupScript = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\NexusAgent.vbs"
$VbsCode = @"
Set objShell = CreateObject("WScript.Shell")
objShell.Run "cmd.exe /c """"$PyPath"""" -u """"$ScriptPath"""" > """"$LogPath"""" 2>&1", 0, False
"@
Set-Content -Path $StartupScript -Value $VbsCode -Encoding ASCII

# Start background process right now
Start-Process -FilePath $PyPath -ArgumentList "-u `"$ScriptPath`"" -RedirectStandardOutput $LogPath -WindowStyle Hidden

Write-Host "==================================================" -ForegroundColor Green
Write-Host " Nexus Agent successfully deployed & running for [$NodeName]!" -ForegroundColor Green
Write-Host " Log file: $LogPath" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green


