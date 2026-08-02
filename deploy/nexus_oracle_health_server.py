#!/usr/bin/env python3
import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HEALTH=Path('/var/lib/nexus/oracle-health.json')
HOST=os.getenv('NEXUS_ORACLE_HEALTH_HOST','100.116.89.65')
PORT=int(os.getenv('NEXUS_ORACLE_HEALTH_PORT','19083'))
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ('/health','/healthz','/'):
            self.send_error(404); return
        try:
            payload=json.loads(HEALTH.read_text(encoding='utf-8')); body=json.dumps(payload,ensure_ascii=False).encode(); code=200 if payload.get('status')=='online' else 503
        except Exception:
            body=b'{"status":"unknown"}'; code=503
        self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self,fmt,*args): pass
ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
