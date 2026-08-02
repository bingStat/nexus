#!/usr/bin/env python3
from __future__ import annotations
import json, os, urllib.parse, urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST=os.getenv('NEXUS_STANDBY_HOST','100.116.89.65'); PORT=int(os.getenv('NEXUS_STANDBY_PORT','19084')); API=os.getenv('NEXUS_API_URL','http://100.116.89.65:19082/rest/v1').rstrip('/'); KEY=os.getenv('NEXUS_API_KEY',''); ORACLE_HEALTH=Path('/var/lib/nexus/oracle-health.json')
CANON={'ThinkCenter':'thinkcenter','oracle-amd':'oracle','YANG':'victus','Yang':'victus','victus-windows':'victus'}
def request(path,params):
    query=urllib.parse.urlencode(params); req=urllib.request.Request(f'{API}/{path}?{query}',headers={'Authorization':f'Bearer {KEY}','apikey':KEY})
    with urllib.request.urlopen(req,timeout=20) as response: return json.loads(response.read().decode())
def state():
    rows=request('devices',{'select':'device_id,name,status,last_seen','order':'last_seen.desc'}); chosen={}
    for row in rows:
        raw=str(row.get('device_id') or ''); device=CANON.get(raw,raw.lower())
        if device=='test': continue
        if device not in chosen: chosen[device]=row
    try: health=json.loads(ORACLE_HEALTH.read_text())
    except Exception: health={}
    return {'generated_at':datetime.now(timezone.utc).isoformat(),'devices':[{'device_id':k,'name':v.get('name') or k,'status':v.get('status'),'last_seen':v.get('last_seen')} for k,v in sorted(chosen.items())],'oracle_health':health}
HTML='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Nexus Standby</title><style>body{font-family:system-ui;background:#0b1020;color:#e8edf7;max-width:900px;margin:auto;padding:24px}table{width:100%;border-collapse:collapse;background:#121a2d}th,td{padding:11px;border-bottom:1px solid #27334d;text-align:left}.ok{color:#7fe0ae}.bad{color:#ff9ca9}.muted{color:#9aa7bd}code{color:#b8c6ff}</style></head><body><h1>Nexus Oracle Standby</h1><p class="muted">只读热备控制面 · 每15秒刷新</p><div id="summary"></div><table><thead><tr><th>设备</th><th>状态</th><th>最后心跳</th></tr></thead><tbody id="devices"></tbody></table><p class="muted" id="stamp"></p><script>const e=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));async function load(){let x=await fetch('/api/state').then(r=>r.json());let checks=(x.oracle_health.checks||[]),bad=checks.filter(c=>c.status!=='online');document.querySelector('#summary').innerHTML=`<p>Oracle/VSC探针：<b class="${bad.length?'bad':'ok'}">${bad.length?'异常':'正常'}</b></p>`;document.querySelector('#devices').innerHTML=x.devices.map(d=>`<tr><td><b>${e(d.name)}</b><br><code>${e(d.device_id)}</code></td><td>${e(d.status)}</td><td>${e(d.last_seen)}</td></tr>`).join('');document.querySelector('#stamp').textContent='更新时间：'+x.generated_at}load();setInterval(load,15000)</script></body></html>'''
class Handler(BaseHTTPRequestHandler):
    def send_body(self,code,body,content_type):
        data=body.encode(); self.send_response(code); self.send_header('Content-Type',content_type); self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        try:
            if self.path=='/health': self.send_body(200,'{"status":"ok","service":"nexus-oracle-standby"}','application/json'); return
            if self.path=='/api/state': self.send_body(200,json.dumps(state(),ensure_ascii=False),'application/json; charset=utf-8'); return
            if self.path=='/': self.send_body(200,HTML,'text/html; charset=utf-8'); return
            self.send_body(404,'not found','text/plain')
        except Exception as exc: self.send_body(503,json.dumps({'status':'degraded','error':type(exc).__name__}),'application/json')
    def log_message(self,fmt,*args): pass
ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
