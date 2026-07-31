"""
Nexus REST API Client for Supabase Cloud Backend
"""
import os
import time
import requests
from typing import Any, Dict, List, Optional

PRIMARY_API_URL = "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1"

def get_api_url() -> str:
    return os.getenv("NEXUS_API_URL", PRIMARY_API_URL).rstrip("/")

def get_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("NEXUS_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["apikey"] = api_key
    if extra:
        headers.update(extra)
    return headers

def list_devices() -> List[Dict[str, Any]]:
    """Fetch all registered devices from Nexus DB."""
    url = f"{get_api_url()}/devices?select=*"
    resp = requests.get(url, headers=get_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()

def get_device_status(device_id: str) -> Optional[Dict[str, Any]]:
    """Fetch specific device info by device_id or name."""
    url = f"{get_api_url()}/devices?or=(device_id.eq.{device_id},name.eq.{device_id})&select=*"
    resp = requests.get(url, headers=get_headers(), timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data[0] if data else None

def create_command(target_device: str, command_str: str, timeout_ms: int = 30000) -> Dict[str, Any]:
    """Create and enqueue a new pending command for target device."""
    url = f"{get_api_url()}/commands"
    payload = {
        "target_device": target_device,
        "command": command_str,
        "status": "pending",
        "timeout_ms": timeout_ms
    }
    headers = get_headers({"Prefer": "return=representation"})
    resp = requests.post(url, json=payload, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data[0] if isinstance(data, list) and data else payload

def get_command_result(job_id: str) -> Optional[Dict[str, Any]]:
    """Fetch command status and output by job UUID."""
    url = f"{get_api_url()}/commands?id=eq.{job_id}&select=*"
    resp = requests.get(url, headers=get_headers(), timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data[0] if data else None

def wait_for_command(job_id: str, max_wait_seconds: int = 10, poll_interval: float = 1.0) -> Dict[str, Any]:
    """Poll job status until completed/failed/timeout or max_wait_seconds reached."""
    start_time = time.time()
    last_res = get_command_result(job_id)
    
    while time.time() - start_time < max_wait_seconds:
        if not last_res:
            break
        status = last_res.get("status")
        if status in ("completed", "failed", "timeout"):
            return last_res
        time.sleep(poll_interval)
        last_res = get_command_result(job_id)
        
    return last_res or {"id": job_id, "status": "unknown", "output": "Failed to retrieve status"}

