"""
Deployment script for Nexus Agent on KU Leuven VSC HPC Cluster
Uses C:/Users/Bing/.ssh/victus SSH key.
"""
import sys
import subprocess

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "${NEXUS_SECRET_FROM_ENV}"
SSH_KEY = "C:/Users/Bing/.ssh/victus"
HOST = "vsc35603@login.hpc.kuleuven.be"
REMOTE_DIR = "$HOME/.nexus"

print("1. Copying agent_v2.py to VSC HPC...")
subprocess.run([
    "scp.exe", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
    "C:\\Users\\Bing\\aurora\\Workstation\\Nexus\\agent_v2.py", f"{HOST}:/tmp/agent_v2.py"
], check=True)

print("2. Starting agent on VSC...")
setup_script = f"""
mkdir -p {REMOTE_DIR}
cp /tmp/agent_v2.py {REMOTE_DIR}/agent_v2.py
chmod +x {REMOTE_DIR}/agent_v2.py

# Stop any existing agent
pkill -f agent_v2.py 2>/dev/null || true

export NEXUS_API_KEY="{API_KEY}"
export DEVICE_ID="vsc"
export DEVICE_NAME="VSC-Cluster"
export PYTHONUNBUFFERED=1

nohup python3 {REMOTE_DIR}/agent_v2.py > {REMOTE_DIR}/agent.log 2>&1 &
sleep 2
tail -n 10 {REMOTE_DIR}/agent.log
"""

setup_script = setup_script.replace('\r', '')

r = subprocess.run([
    "ssh.exe", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", HOST, "bash", "-s"
], input=setup_script.encode('utf-8'), capture_output=True)

print(r.stdout.decode('utf-8', errors='replace'))
if r.stderr:
    print("STDERR:", r.stderr.decode('utf-8', errors='replace'))

