#!/usr/bin/env python3
from __future__ import annotations
import json, sqlite3, urllib.request
from datetime import datetime, timezone
from pathlib import Path

DB=Path('/var/lib/nexus/nexus_state.db'); HEALTH=Path('/var/lib/nexus/health.json'); EVENTS=Path('/var/lib/nexus/events.json'); CREDENTIALS=Path('/var/lib/nexus/credential-refs.json'); API='http://127.0.0.1:8000'
def now(): return datetime.now(timezone.utc).isoformat()
def load(path,default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except Exception: return default
def fetch(path):
    with urllib.request.urlopen(API+path,timeout=20) as response: return json.loads(response.read().decode())
def upsert(cur,table,key,row):
    cols=list(row); marks=','.join('?' for _ in cols); updates=','.join(f'{c}=excluded.{c}' for c in cols if c!=key)
    cur.execute(f'INSERT INTO {table} ({",".join(cols)}) VALUES ({marks}) ON CONFLICT({key}) DO UPDATE SET {updates}',[row[c] for c in cols])
def schema(cur):
    cur.executescript('''
CREATE TABLE IF NOT EXISTS devices(device_id TEXT PRIMARY KEY,name TEXT,state TEXT,last_seen TEXT,platform TEXT,agent_version TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS agents(agent_id TEXT PRIMARY KEY,device_id TEXT,version TEXT,state TEXT,last_seen TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS heartbeats(id INTEGER PRIMARY KEY AUTOINCREMENT,device_id TEXT,observed_at TEXT,state TEXT,age_seconds INTEGER);
CREATE TABLE IF NOT EXISTS connections(connection_id TEXT PRIMARY KEY,source TEXT,target TEXT,kind TEXT,label TEXT,state TEXT,checked_at TEXT);
CREATE TABLE IF NOT EXISTS services(service_id TEXT PRIMARY KEY,name TEXT,kind TEXT,target TEXT,state TEXT,http_code INTEGER,latency_ms INTEGER,checked_at TEXT);
CREATE TABLE IF NOT EXISTS service_checks(id INTEGER PRIMARY KEY AUTOINCREMENT,service_id TEXT,observed_at TEXT,state TEXT,http_code INTEGER,latency_ms INTEGER,error TEXT);
CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY,target_device TEXT,state TEXT,created_at TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY,created_at TEXT,kind TEXT,severity TEXT,subject TEXT,title TEXT,detail TEXT,old_state TEXT,new_state TEXT);
CREATE TABLE IF NOT EXISTS managed_targets(target_id TEXT PRIMARY KEY,name TEXT,manager_primary TEXT,manager_secondary TEXT,management_paths TEXT,state TEXT,checked_at TEXT);
CREATE TABLE IF NOT EXISTS credential_refs(device_id TEXT PRIMARY KEY,kind TEXT,status TEXT,created_at TEXT,rotated_at TEXT,secret_location TEXT);
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
CREATE INDEX IF NOT EXISTS idx_heartbeats_device_time ON heartbeats(device_id,observed_at);
CREATE INDEX IF NOT EXISTS idx_service_checks_time ON service_checks(service_id,observed_at);
''')
def sync_devices(cur,observed):
    for d in fetch('/dashboard/devices'):
        upsert(cur,'devices','device_id',{'device_id':d['device_id'],'name':d.get('name'),'state':d.get('state'),'last_seen':d.get('last_seen'),'platform':d.get('platform'),'agent_version':d.get('agent_version'),'updated_at':observed})
        upsert(cur,'agents','agent_id',{'agent_id':d['device_id']+':primary','device_id':d['device_id'],'version':d.get('agent_version'),'state':d.get('state'),'last_seen':d.get('last_seen'),'updated_at':observed})
        cur.execute('INSERT INTO heartbeats(device_id,observed_at,state,age_seconds) VALUES(?,?,?,?)',(d['device_id'],observed,d.get('state'),d.get('age_seconds')))
def sync_connections(cur,observed):
    for c in fetch('/dashboard/connections'):
        cid=f"{c.get('source')}:{c.get('target')}:{c.get('kind')}"; upsert(cur,'connections','connection_id',{'connection_id':cid,'source':c.get('source'),'target':c.get('target'),'kind':c.get('kind'),'label':c.get('label'),'state':c.get('state'),'checked_at':observed})
def sync_jobs(cur):
    for j in fetch('/dashboard/commands?limit=100'): upsert(cur,'jobs','job_id',{'job_id':j['id'],'target_device':j.get('target_device'),'state':j.get('status'),'created_at':j.get('created_at'),'updated_at':j.get('updated_at')})
def sync_services(cur,observed):
    health=load(HEALTH,{})
    for s in health.get('checks') or []:
        sid=s.get('id'); upsert(cur,'services','service_id',{'service_id':sid,'name':s.get('name'),'kind':s.get('kind'),'target':s.get('target'),'state':s.get('status'),'http_code':s.get('http_code'),'latency_ms':s.get('latency_ms'),'checked_at':s.get('checked_at') or observed})
        cur.execute('INSERT INTO service_checks(service_id,observed_at,state,http_code,latency_ms,error) VALUES(?,?,?,?,?,?)',(sid,observed,s.get('status'),s.get('http_code'),s.get('latency_ms'),s.get('error')))
    states={x.get('id'):x.get('status') for x in health.get('checks') or []}
    for target in [{'target_id':'v152','name':'Huawei V152','manager_primary':'thinkcenter','manager_secondary':'n1','management_paths':'web,ssh,telnet'},{'target_id':'ax3600','name':'Xiaomi AX3600','manager_primary':'thinkcenter','manager_secondary':'n1','management_paths':'web,ssh'}]:
        target['state']=states.get(target['target_id'],'unknown'); target['checked_at']=observed; upsert(cur,'managed_targets','target_id',target)
def sync_events(cur):
    for e in load(EVENTS,[]): upsert(cur,'events','event_id',{'event_id':str(e.get('id')),'created_at':e.get('created_at'),'kind':e.get('kind'),'severity':e.get('severity'),'subject':e.get('subject'),'title':e.get('title'),'detail':e.get('detail'),'old_state':e.get('old_state'),'new_state':e.get('new_state')})
def sync_credentials(cur):
    for item in load(CREDENTIALS,[]): upsert(cur,'credential_refs','device_id',item)
def prune(cur):
    cur.execute("DELETE FROM heartbeats WHERE observed_at < datetime('now','-30 days')"); cur.execute("DELETE FROM service_checks WHERE observed_at < datetime('now','-30 days')")
def main():
    observed=now(); DB.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DB) as db:
        cur=db.cursor(); schema(cur); errors=[]
        for name,func in (("devices",lambda:sync_devices(cur,observed)),("connections",lambda:sync_connections(cur,observed)),("jobs",lambda:sync_jobs(cur)),("services",lambda:sync_services(cur,observed)),("events",lambda:sync_events(cur)),("credentials",lambda:sync_credentials(cur))):
            try: func()
            except Exception as exc: errors.append(f"{name}:{type(exc).__name__}")
        prune(cur); upsert(cur,'metadata','key',{'key':'last_sync','value':observed}); upsert(cur,'metadata','key',{'key':'last_errors','value':','.join(errors)}); db.commit()
    DB.chmod(0o640)
    with sqlite3.connect(DB) as db: counts={t:db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('devices','agents','heartbeats','connections','services','service_checks','jobs','events','managed_targets','credential_refs')}
    print(json.dumps({'database':str(DB),'last_sync':observed,'counts':counts},ensure_ascii=False))
if __name__=='__main__': main()
