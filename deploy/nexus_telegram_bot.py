#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

TOKEN_FILE = Path('/etc/nexus/telegram.token')
PROXY_URL = os.getenv('NEXUS_TELEGRAM_PROXY', 'http://127.0.0.1:7890')
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({'http': PROXY_URL, 'https': PROXY_URL}))
STATE_FILE = Path('/var/lib/nexus/telegram-state.json')
EVENTS_FILE = Path('/var/lib/nexus/events.json')
HEALTH_FILE = Path('/var/lib/nexus/health.json')

def load_json(path, default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except Exception: return default

def save_json(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.chmod(tmp, mode); os.replace(tmp, path)

def api(method, payload=None):
    token = TOKEN_FILE.read_text(encoding='utf-8').strip()
    data = urllib.parse.urlencode(payload or {}).encode()
    req = urllib.request.Request(f'https://api.telegram.org/bot{token}/{method}', data=data)
    with OPENER.open(req, timeout=20) as response: result = json.loads(response.read().decode())
    if not result.get('ok'): raise RuntimeError(method)
    return result.get('result')

def send(chat_id, text): return api('sendMessage', {'chat_id':str(chat_id),'text':text,'disable_web_page_preview':'true'})

def status_text():
    health=load_json(HEALTH_FILE,{}); checks=health.get('checks') or []
    online=sum(x.get('status')=='online' for x in checks); degraded=sum(x.get('status')=='degraded' for x in checks); offline=sum(x.get('status')=='offline' for x in checks)
    bad=[x.get('name') for x in checks if x.get('status')!='online']
    lines=['Nexus 状态',f'服务：{online} online / {degraded} degraded / {offline} offline']
    if bad: lines.append('异常：'+'、'.join(str(x) for x in bad[:8]))
    lines.extend(['快照：'+str(health.get('generated_at') or 'unknown'),'面板：https://nexus.bings.app'])
    return '\n'.join(lines)

def event_key(event): return hashlib.sha256(json.dumps(event,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def format_event(event):
    icon={'critical':'🔴','warning':'🟠','info':'🟢'}.get(event.get('severity'),'🔵')
    title=event.get('title') or event.get('subject') or 'Nexus event'; detail=event.get('detail') or event.get('message') or ''; created=event.get('created_at') or datetime.now(timezone.utc).isoformat()
    return f"{icon} {title}\n{detail}\n{created}\nhttps://nexus.bings.app"

def configure_bot():
    api('setMyCommands', {'commands':json.dumps([{'command':'start','description':'启用 Nexus 通知'},{'command':'status','description':'查看集群状态'},{'command':'help','description':'查看可用命令'}],ensure_ascii=False)})
    api('setMyDescription', {'description':'Nexus 集群状态、故障与恢复通知机器人。'})
    api('setMyShortDescription', {'short_description':'Nexus 集群监控与告警'})

def handle_updates(state):
    updates=api('getUpdates',{'offset':state.get('offset',0),'timeout':0,'allowed_updates':json.dumps(['message'])})
    for update in updates:
        state['offset']=max(state.get('offset',0),int(update['update_id'])+1); msg=update.get('message') or {}; chat=msg.get('chat') or {}; text=(msg.get('text') or '').split('@',1)[0].strip().lower()
        if chat.get('type')!='private': continue
        chat_id=chat.get('id')
        if text=='/start': state['chat_id']=chat_id; send(chat_id,'Nexus 通知已启用。\n\n'+status_text())
        elif text=='/status': send(chat_id,status_text())
        elif text=='/help': send(chat_id,'/status 查看状态\n/start 绑定当前聊天\n告警和恢复事件会自动推送。')
    return state

def send_new_events(state):
    chat_id=state.get('chat_id')
    if not chat_id: return state
    events=load_json(EVENTS_FILE,[]); seen=set(state.get('seen_events') or []); new_items=[e for e in reversed(events) if event_key(e) not in seen]
    for event in new_items[-20:]: send(chat_id,format_event(event)); seen.add(event_key(event))
    current=[event_key(e) for e in events[:200]]; state['seen_events']=[key for key in current if key in seen][-200:]
    return state

def main():
    if not TOKEN_FILE.exists(): raise SystemExit('token file missing')
    state=load_json(STATE_FILE,{'offset':0,'configured':False,'seen_events':[]})
    if not state.get('configured'): configure_bot(); state['configured']=True
    state=handle_updates(state); state=send_new_events(state); save_json(STATE_FILE,state)

if __name__=='__main__': main()
