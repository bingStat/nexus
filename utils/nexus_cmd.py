import urllib.request
import json
import uuid
import os
import time
import argparse
import sys

SUPABASE_URL = "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1"
SUPABASE_KEY = os.environ.get("NEXUS_API_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng")

def send_command(target_device, command, timeout_ms=600000):
    job_id = str(uuid.uuid4())
    url = f"{SUPABASE_URL}/commands"
    
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    
    payload = {
        "id": job_id,
        "target_device": target_device,
        "command": command,
        "status": "pending",
        "timeout_ms": timeout_ms
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            return job_id
    except urllib.error.HTTPError as e:
        print(f"Error sending command: {e.read().decode('utf-8')}", file=sys.stderr)
        return None

def get_job_result(job_id, timeout=600):
    url = f"{SUPABASE_URL}/commands?id=eq.{job_id}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                if result:
                    job = result[0]
                    if job.get("status") in ["completed", "failed"]:
                        return job
            time.sleep(2)
        except Exception as e:
            print(f"Error checking job status: {e}", file=sys.stderr)
            time.sleep(2)
    return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send command to Nexus device")
    parser.add_argument("device", help="Target device (e.g. thinkcenter)")
    parser.add_argument("command", help="Command to execute")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout in seconds")
    
    args = parser.parse_args()
    
    job_id = send_command(args.device, args.command, timeout_ms=args.timeout*1000)
    if job_id:
        res = get_job_result(job_id, timeout=args.timeout)
        if res:
            if res.get("output"):
                sys.stdout.buffer.write(res.get("output").encode('utf-8'))
                sys.stdout.buffer.write(b'\n')
            sys.exit(0 if res.get("status") == "completed" else 1)
        else:
            print(f"Timeout waiting for result after {args.timeout}s", file=sys.stderr)
            sys.exit(1)
    else:
        sys.exit(1)
