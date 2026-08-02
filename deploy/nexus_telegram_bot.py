#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TOKEN_FILE = Path('/etc/nexus/telegram.token')
PROXY_URL = os.getenv('NEXUS_TELEGRAM_PROXY', 'http://127.0.0.1:7890')
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({'http': PROXY_URL, 'https': PROXY_URL}))
STATE_FILE = Path('/var/lib/nexus/telegram-state.json')
EVENTS_FILE = Path('/var/lib/nexus/events.json')
HEALTH_FILE = Path('/var/lib/nexus/health.json')
MAX_SEEN = 500


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def save_json(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def api(method, payload=None):
    token = TOKEN_FILE.read_text(encoding='utf-8').strip()
    data = urllib.parse.urlencode(payload or {}).encode()
    req = urllib.request.Request(f'https://api.telegram.org/bot{token}/{method}', data=data)
    with OPENER.open(req, timeout=20) as response:
        result = json.loads(response.read().decode())
    if not result.get('ok'):
        raise RuntimeError(method)
    return result.get('result')


def send(chat_id, text, silent=False):
    return api('sendMessage', {
        'chat_id': str(chat_id),
        'text': text,
        'disable_web_page_preview': 'true',
        'disable_notification': 'true' if silent else 'false',
    })


def status_text():
    health = load_json(HEALTH_FILE, {})
    checks = [x for x in (health.get('checks') or []) if x.get('id') != 'elitebook']
    online = sum(x.get('status') == 'online' for x in checks)
    degraded = sum(x.get('status') == 'degraded' for x in checks)
    offline = [str(x.get('name')) for x in checks if x.get('status') == 'offline']
    lines = ['Nexus 状态', f'服务：{online} online / {degraded} degraded / {len(offline)} offline']
    if offline:
        lines.append('当前离线：' + '、'.join(offline[:8]))
    lines.append('告警策略：连续失败确认、恢复确认、批量推送')
    lines.append('面板：https://nexus.bings.app')
    return '\n'.join(lines)


def configure_bot():
    api('setMyCommands', {'commands': json.dumps([
        {'command':'start','description':'绑定当前聊天并启用通知'},
        {'command':'status','description':'查看集群状态'},
        {'command':'mute','description':'暂停主动通知'},
        {'command':'resume','description':'恢复主动通知'},
        {'command':'help','description':'查看告警策略'},
    ], ensure_ascii=False)})
    api('setMyDescription', {'description':'Nexus 集群低噪声故障确认、恢复与状态查询机器人。'})
    api('setMyShortDescription', {'short_description':'Nexus 低噪声集群告警'})


def current_event_ids(events):
    return [str(e.get('id')) for e in events if e.get('id')][:MAX_SEEN]


def handle_updates(state, events):
    updates = api('getUpdates', {
        'offset': state.get('offset', 0),
        'timeout': 0,
        'allowed_updates': json.dumps(['message']),
    })
    for update in updates:
        state['offset'] = max(state.get('offset', 0), int(update['update_id']) + 1)
        msg = update.get('message') or {}
        chat = msg.get('chat') or {}
        text = (msg.get('text') or '').split('@', 1)[0].strip().lower()
        if chat.get('type') != 'private':
            continue
        chat_id = chat.get('id')
        if text == '/start':
            state['chat_id'] = chat_id
            state['enabled'] = True
            state['seen_event_ids'] = current_event_ids(events)
            send(chat_id, 'Nexus 通知已启用。既有历史事件不会重放。\n\n' + status_text())
        elif text == '/status':
            send(chat_id, status_text())
        elif text == '/mute':
            state['enabled'] = False
            send(chat_id, '主动通知已暂停。/status 仍可查询。')
        elif text == '/resume':
            state['enabled'] = True
            state['seen_event_ids'] = current_event_ids(events)
            send(chat_id, '主动通知已恢复。暂停期间的历史事件不会补发。')
        elif text == '/help':
            send(chat_id, '告警规则：\n• 服务连续失败3次才确认\n• 局域网管理项和设备连续失败5次才确认\n• 恢复需连续成功3次\n• 刚恢复30分钟内再次抖动需连续失败10次\n• 多个事件合并为一条消息\n• 恢复消息静默发送')
    return state


def event_line(event):
    title = str(event.get('title') or event.get('subject') or 'Nexus event')
    detail = str(event.get('detail') or '')
    return f'• {title}：{detail}'


def send_new_events(state, events):
    current_ids = current_event_ids(events)
    if state.get('notification_version') != 2:
        state['notification_version'] = 2
        state['seen_event_ids'] = current_ids
        return state

    seen = set(str(x) for x in (state.get('seen_event_ids') or []))
    candidates = [e for e in reversed(events) if str(e.get('id')) not in seen]
    relevant = [e for e in candidates if e.get('kind') in {'incident', 'recovery'}]
    state['seen_event_ids'] = current_ids
    if not relevant or not state.get('enabled', True) or not state.get('chat_id'):
        return state

    incidents = [e for e in relevant if e.get('kind') == 'incident']
    recoveries = [e for e in relevant if e.get('kind') == 'recovery']
    lines = []
    if incidents:
        lines.append(f'🔴 Nexus 故障确认（{len(incidents)}）')
        lines.extend(event_line(e) for e in incidents[:12])
    if recoveries:
        if lines:
            lines.append('')
        lines.append(f'🟢 Nexus 恢复确认（{len(recoveries)}）')
        lines.extend(event_line(e) for e in recoveries[:12])
    omitted = max(0, len(relevant) - 24)
    if omitted:
        lines.append(f'另有 {omitted} 条事件，请查看面板。')
    lines.append('https://nexus.bings.app')
    send(state['chat_id'], '\n'.join(lines), silent=not incidents)
    state['last_push_at'] = datetime.now(timezone.utc).isoformat()
    return state


def main():
    if not TOKEN_FILE.exists():
        raise SystemExit('token file missing')
    events = load_json(EVENTS_FILE, [])
    state = load_json(STATE_FILE, {
        'offset': 0,
        'configured': False,
        'enabled': True,
        'seen_event_ids': [],
    })
    state.setdefault('enabled', True)
    if state.get('bot_config_version') != 2:
        configure_bot()
        state['configured'] = True
        state['bot_config_version'] = 2
    state = handle_updates(state, events)
    state = send_new_events(state, events)
    save_json(STATE_FILE, state)
    print(json.dumps({
        'configured': bool(state.get('configured')),
        'chat_bound': bool(state.get('chat_id')),
        'enabled': bool(state.get('enabled', True)),
        'seen': len(state.get('seen_event_ids') or []),
        'notification_version': state.get('notification_version'),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
