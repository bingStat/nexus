"""
Deployment script for Nexus Agent & MCP Server on ThinkCenter
Uses C:/Users/Bing/.ssh/victus SSH key.
"""
import sys
import subprocess

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng"
SSH_KEY = "C:/Users/Bing/.ssh/victus"
HOST = "100.103.12.14"
REMOTE_DIR = "/opt/nexus"

print("1. Creating remote directory on ThinkCenter...")
subprocess.run([
    "ssh.exe", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", f"root@{HOST}",
    f"mkdir -p {REMOTE_DIR}/mcp_server"
], check=True)

print("2. Copying agent_v2.py and mcp_server to ThinkCenter...")
subprocess.run([
    "scp.exe", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
    "C:\\Users\\Bing\\aurora\\Workstation\\Nexus\\agent_v2.py", f"root@{HOST}:{REMOTE_DIR}/agent_v2.py"
], check=True)

subprocess.run([
    "scp.exe", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", "-r",
    "C:\\Users\\Bing\\aurora\\Workstation\\Nexus\\mcp_server", f"root@{HOST}:{REMOTE_DIR}/"
], check=True)

print("3. Setting up systemd services on ThinkCenter...")
setup_script = f"""
chmod +x {REMOTE_DIR}/agent_v2.py
rm -rf {REMOTE_DIR}/venv

PYTHON_BIN="/usr/bin/python3"

# 1. nexus-agent.service
cat > /etc/systemd/system/nexus-agent.service << EOF
[Unit]
Description=Nexus Agent v2
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={REMOTE_DIR}
ExecStart=$PYTHON_BIN {REMOTE_DIR}/agent_v2.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment="NEXUS_API_KEY={API_KEY}"
Environment="DEVICE_ID=thinkcenter"
Environment="DEVICE_NAME=ThinkCenter"

[Install]
WantedBy=multi-user.target
EOF

# 2. nexus-mcp.service
cat > /etc/systemd/system/nexus-mcp.service << EOF
[Unit]
Description=Nexus FastMCP Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={REMOTE_DIR}
ExecStart=$PYTHON_BIN -m mcp_server.app
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment="PYTHONPATH={REMOTE_DIR}"
Environment="NEXUS_API_KEY={API_KEY}"
Environment="PORT=8000"

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now nexus-agent.service nexus-mcp.service
systemctl restart nexus-agent.service nexus-mcp.service
sleep 2
systemctl status nexus-agent.service nexus-mcp.service --no-pager
"""

setup_script = setup_script.replace('\r', '')

r = subprocess.run([
    "ssh.exe", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", f"root@{HOST}", "bash", "-s"
], input=setup_script.encode('utf-8'), capture_output=True)

print(r.stdout.decode('utf-8', errors='replace'))
if r.stderr:
    print("STDERR:", r.stderr.decode('utf-8', errors='replace'))
