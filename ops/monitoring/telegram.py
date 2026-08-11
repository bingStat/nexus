from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import atomic_json, load_config, load_json

DEFAULT_TOKEN = Path("/etc/nexus/telegram.token")
DEFAULT_STATE = Path("/var/lib/nexus/ops/telegram-state.json")
DEFAULT_EVENTS = Path("/var/lib/nexus/ops/events.json")
DEFAULT_HEALTH = Path("/var/lib/nexus/ops/health.json")
MAX_SEEN = 500


def opener() -> urllib.request.OpenerDirector:
    proxy = os.getenv("NEXUS_TELEGRAM_PROXY", "").strip()
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})
    )


def api(token: str, method: str, payload: dict[str, Any] | None = None) -> Any:
    data = urllib.parse.urlencode(payload or {}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data)
    with opener().open(req, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(f"Telegram {method} failed")
    return result.get("result")


def send(token: str, chat_id: int | str, text: str, silent: bool = False) -> None:
    api(token, "sendMessage", {
        "chat_id": str(chat_id), "text": text, "disable_web_page_preview": "true",
        "disable_notification": "true" if silent else "false",
    })


def current_ids(events: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("id")) for item in events if item.get("id")][:MAX_SEEN]


def status_text(health: dict[str, Any]) -> str:
    counts = health.get("counts") or {}
    offline_services = [
        str(item.get("name") or item.get("id"))
        for item in health.get("checks") or [] if item.get("status") == "offline"
    ]
    lines = [
        "Nexus status",
        f"Devices: {counts.get('online', 0)} online / {counts.get('degraded', 0)} degraded / {counts.get('offline', 0)} offline",
        f"Service checks offline: {len(offline_services)}",
    ]
    if offline_services:
        lines.append("Offline: " + ", ".join(offline_services[:8]))
    lines.append("Policy: confirmed failures/recoveries only; notifications are batched.")
    lines.append("https://nexus.bings.app")
    return "\n".join(lines)


def configure(token: str) -> None:
    commands = [
        {"command": "start", "description": "Bind this private chat and enable alerts"},
        {"command": "status", "description": "Show Nexus fleet status"},
        {"command": "mute", "description": "Pause proactive alerts"},
        {"command": "resume", "description": "Resume alerts without replaying history"},
        {"command": "help", "description": "Show the alert policy"},
    ]
    api(token, "setMyCommands", {"commands": json.dumps(commands, ensure_ascii=False)})


def handle_updates(token: str, state: dict[str, Any], events: list[dict[str, Any]], health: dict[str, Any]) -> None:
    updates = api(token, "getUpdates", {
        "offset": state.get("offset", 0), "timeout": 0,
        "allowed_updates": json.dumps(["message"]),
    })
    for update in updates or []:
        state["offset"] = max(int(state.get("offset", 0)), int(update["update_id"]) + 1)
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        if chat.get("type") != "private":
            continue
        chat_id = chat.get("id")
        text = str(message.get("text") or "").split("@", 1)[0].strip().lower()
        if text == "/start":
            state.update({"chat_id": chat_id, "enabled": True, "seen_event_ids": current_ids(events)})
            send(token, chat_id, "Nexus alerts enabled. Historical events will not be replayed.\n\n" + status_text(health))
        elif text == "/status":
            send(token, chat_id, status_text(health))
        elif text == "/mute":
            state["enabled"] = False
            send(token, chat_id, "Proactive Nexus alerts paused. /status remains available.")
        elif text == "/resume":
            state.update({"enabled": True, "seen_event_ids": current_ids(events)})
            send(token, chat_id, "Nexus alerts resumed. Events from the muted period will not be replayed.")
        elif text == "/help":
            send(token, chat_id, "Nexus confirms repeated failures before alerting, requires repeated success before recovery, suppresses rapid reopen flapping, and batches events into one message.")


def send_new_events(token: str, state: dict[str, Any], events: list[dict[str, Any]]) -> None:
    ids = current_ids(events)
    if state.get("notification_version") != 3:
        state.update({"notification_version": 3, "seen_event_ids": ids})
        return
    seen = {str(value) for value in state.get("seen_event_ids") or []}
    relevant = [item for item in reversed(events) if str(item.get("id")) not in seen and item.get("kind") in {"incident", "recovery"}]
    state["seen_event_ids"] = ids
    if not relevant or not state.get("enabled", True) or not state.get("chat_id"):
        return
    incidents = [item for item in relevant if item.get("kind") == "incident"]
    recoveries = [item for item in relevant if item.get("kind") == "recovery"]
    lines: list[str] = []
    if incidents:
        lines.append(f"Nexus incidents confirmed ({len(incidents)})")
        lines.extend(f"• {item.get('title')}: {item.get('detail')}" for item in incidents[:12])
    if recoveries:
        if lines:
            lines.append("")
        lines.append(f"Nexus recoveries confirmed ({len(recoveries)})")
        lines.extend(f"• {item.get('title')}: {item.get('detail')}" for item in recoveries[:12])
    if len(relevant) > 24:
        lines.append(f"... {len(relevant) - 24} additional events; see dashboard.")
    lines.append("https://nexus.bings.app")
    send(token, state["chat_id"], "\n".join(lines), silent=not incidents)
    state["last_push_at"] = datetime.now(timezone.utc).isoformat()


def main() -> None:
    config = load_config()
    telegram = config.get("telegram") if isinstance(config.get("telegram"), dict) else {}
    token_file = Path(str(telegram.get("token_file") or DEFAULT_TOKEN))
    state_file = Path(str(telegram.get("state_file") or DEFAULT_STATE))
    events_file = Path(str((config.get("alerts") or {}).get("events_file") or DEFAULT_EVENTS))
    health_file = Path(str(config.get("health_file") or DEFAULT_HEALTH))
    if not token_file.exists():
        raise SystemExit(f"Telegram token file missing: {token_file}")
    token = token_file.read_text(encoding="utf-8").strip()
    events = load_json(events_file, [])
    health = load_json(health_file, {})
    state = load_json(state_file, {"offset": 0, "enabled": True, "seen_event_ids": []})
    if state.get("bot_config_version") != 3:
        configure(token)
        state["bot_config_version"] = 3
    handle_updates(token, state, events, health)
    send_new_events(token, state, events)
    atomic_json(state_file, state, 0o600)
    print(json.dumps({"chat_bound": bool(state.get("chat_id")), "enabled": bool(state.get("enabled", True)), "seen": len(state.get("seen_event_ids") or [])}))


if __name__ == "__main__":
    main()
