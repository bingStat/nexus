#!/usr/bin/env python3
from __future__ import annotations
import json, os, socket, subprocess, tempfile, time
from datetime import datetime, timezone
from pathlib import Path

OUTPUT=Path('/var/lib/nexus/oracle-health.json')
CHECKS=[('vsc-ssh','VSC reverse SSH','127.0.0.1',22204),('vsc-thinkdesk','VSC ThinkDesk','127.0.0.1',28787),('vsc-code','VSC code-server','127.0.0.1',28788),('oracle-api-relay','Oracle API relay','100.116.89.65',19082)]
def now_iso(): return datetime.now(timezone.utc).isoformat()
def tcp_check(check_id,name,host,port):
    started=time.monotonic()
    try:
        with socket.create_connection((host,port),timeout=5): state,error='online',None
    except Exception as exc: state,error='offline',type(exc).__name__
    return {'id':check_id,'name':name,'kind':'tcp','target':f'{host}:{port}','status':state,'latency_ms':round((time.monotonic()-started)*1000),'error':error,'checked_at':now_iso()}
def tailscale_self():
    try:
        run=subprocess.run(['tailscale','status','--self','--json'],text=True,capture_output=True,timeout=8,check=True); payload=json.loads(run.stdout); node=payload.get('Self') or {}
        return {'status':'online' if node.get('Online',True) else 'offline','dns_name':node.get('DNSName'),'tailscale_ips':node.get('TailscaleIPs') or []}
    except Exception as exc: return {'status':'offline','error':type(exc).__name__}
def main():
    checks=[tcp_check(*item) for item in CHECKS]; payload={'generated_at':now_iso(),'node':socket.gethostname(),'status':'online' if all(x['status']=='online' for x in checks) else 'offline','tailscale':tailscale_self(),'checks':checks}
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',dir=OUTPUT.parent,delete=False,encoding='utf-8') as handle: json.dump(payload,handle,ensure_ascii=False,indent=2); name=handle.name
    os.chmod(name,0o644); os.replace(name,OUTPUT)
if __name__=='__main__': main()
