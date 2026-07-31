"""
Deployment script for Nexus Agent on Oracle Cloud VPS
Uses C:/Users/Bing/.ssh/victus SSH key.
"""
import sys
import subprocess

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "${NEXUS_SECRET_FROM_ENV}"
SSH_KEY = "C:/Users/Bing/.ssh/victus"
HOST = "ubuntu@100.116.89.65"
REMOTE_DIR = "/home/ubuntu/nexus"
SERVICE_NAME = "nexus-agent"

print("1. Copying agent_v2.py to Oracle...")
subprocess.run([
    "scp.exe", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
    "C:\\Users\\Bing\\aurora\\Workstation\\Nexus\\agent_v2.py", f"{HOST}:/tmp/agent_v2.py"
], check=True)

print("2. Setting up nexus-agent service on Oracle...")
setup_script = f"""
mkdir -p {REMOTE_DIR}
cp /tmp/agent_v2.py {REMOTE_DIR}/agent_v2.py
chmod +x {REMOTE_DIR}/agent_v2.py

sudo bash -c "cat > /etc/systemd/system/{SERVICE_NAME}.service << 'EOF'
[Unit]
Description=Nexus Agent v2
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory={REMOTE_DIR}
ExecStart=/usr/bin/python3 {REMOTE_DIR}/agent_v2.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=\\"NEXUS_API_KEY={API_KEY}\\"
Environment=\\"DEVICE_ID=oracle\\"
Environment=\\"DEVICE_NAME=OracleCloud\\"

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
sudo systemctl enable --now {SERVICE_NAME}.service
sudo systemctl restart {SERVICE_NAME}.service
sleep 2
sudo systemctl status {SERVICE_NAME}.service --no-pager
"""

setup_script = setup_script.replace('\r', '')

r = subprocess.run([
    "ssh.exe", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", HOST, "bash", "-s"
], input=setup_script.encode('utf-8'), capture_output=True)

print(r.stdout.decode('utf-8', errors='replace'))
if r.stderr:
    print("STDERR:", r.stderr.decode('utf-8', errors='replace'))

