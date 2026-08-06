#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROVIDERS = {
    "gemini": {
        "url": "https://gemini.google.com/app",
        "textbox": "Enter a prompt for Gemini",
    },
    "claude": {
        "url": "https://claude.ai/new",
        "textbox": None,
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class MCPError(RuntimeError):
    pass


class RawMCP:
    def __init__(self, command: list[str], timeout: float) -> None:
        self.timeout = timeout
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.seq = 0
        self.waiters: dict[int, tuple[threading.Event, dict[str, Any]]] = {}
        self.lock = threading.Lock()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg_id = msg.get("id")
            with self.lock:
                waiter = self.waiters.get(msg_id)
            if waiter:
                waiter[1]["message"] = msg
                waiter[0].set()

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.seq += 1
        msg_id = self.seq
        event = threading.Event()
        box: dict[str, Any] = {}
        with self.lock:
            self.waiters[msg_id] = (event, box)
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        if not event.wait(self.timeout):
            raise MCPError(f"MCP request timed out: {method}")
        with self.lock:
            self.waiters.pop(msg_id, None)
        msg = box["message"]
        if "error" in msg:
            raise MCPError(json.dumps(msg["error"], ensure_ascii=False))
        return msg.get("result") or {}

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n")
        self.proc.stdin.flush()

    def close(self) -> None:
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def extract_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "\n".join(parts)


def provider_code(provider: str, prompt: str, timeout_seconds: int) -> str:
    prompt_json = json.dumps(prompt, ensure_ascii=False)
    loops = max(10, min(180, timeout_seconds // 2))
    if provider == "gemini":
        return f"""async (page) => {{
          const prompt = {prompt_json};
          const box = page.getByRole('textbox',{{name:'Enter a prompt for Gemini'}});
          await box.waitFor({{state:'visible', timeout:30000}});
          await box.fill(prompt); await box.press('Enter');
          let previous='', stable=0, current='';
          for (let i=0;i<{loops};i++) {{
            await page.waitForTimeout(2000);
            current=await page.locator('main').innerText().catch(()=>page.locator('body').innerText());
            stable=current===previous && current.length>100 ? stable+1 : 0;
            previous=current; if(stable>=3) break;
          }}
          return {{title:await page.title(),url:page.url(),text:current.slice(-24000)}};
        }}"""
    return f"""async (page) => {{
      const prompt = {prompt_json};
      const box = page.locator('[contenteditable=\"true\"]').last();
      await box.waitFor({{state:'visible', timeout:30000}});
      await box.fill(prompt); await box.press('Enter');
      let previous='', stable=0, current='';
      for (let i=0;i<{loops};i++) {{
        await page.waitForTimeout(2000);
        const candidates=page.locator('[data-testid*=\"assistant\"], [data-is-streaming], article');
        const texts=await candidates.allInnerTexts().catch(()=>[]);
        const usable=texts.map(x=>x.trim()).filter(x=>x.length>15 && !x.includes(prompt));
        current=usable.length ? usable[usable.length-1] : '';
        if(!current) {{
          const main=await page.locator('main').innerText().catch(()=>page.locator('body').innerText());
          current=main.slice(-12000);
        }}
        stable=current===previous && current.length>20 ? stable+1 : 0;
        previous=current;
        const streaming=await page.locator('[data-is-streaming=\"true\"]').count().catch(()=>0);
        if(stable>=3 && streaming===0) break;
      }}
      return {{title:await page.title(),url:page.url(),text:current.slice(-24000)}};
    }}"""


def append_receipt(room_dir: Path, receipt: dict[str, Any]) -> None:
    room_dir.mkdir(parents=True, exist_ok=True)
    transcript = room_dir / "transcript.jsonl"
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")) + "\n")
    markdown = room_dir / "transcript.md"
    with markdown.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {receipt['turn_id']} — {receipt['provider']}\n\n")
        handle.write(receipt.get("response_text") or f"**{receipt['status']}**")
        handle.write("\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    provider = PROVIDERS[args.provider]
    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    room_dir = Path(args.room_dir)
    ledger = room_dir / "idempotency.json"
    existing: dict[str, Any] = {}
    if ledger.exists():
        existing = json.loads(ledger.read_text(encoding="utf-8"))
    if args.idempotency_key in existing:
        return existing[args.idempotency_key]

    started = now()
    command = args.mcp_command or os.getenv("NEXUS_PLAYWRIGHT_MCP_COMMAND")
    if not command:
        command = "/mnt/c/Windows/System32/cmd.exe /d /s /c F:\\NexusBrowser\\start-pw-mcp.cmd"
    client = RawMCP(command.split(), timeout=float(args.timeout))
    try:
        client.request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "Nexus Browser Adapter", "version": "1.0.0"},
        })
        client.notify("notifications/initialized")
        client.request("tools/call", {"name": "browser_navigate", "arguments": {"url": provider["url"]}})
        time.sleep(3)
        result = client.request("tools/call", {
            "name": "browser_run_code_unsafe",
            "arguments": {"code": provider_code(args.provider, prompt, args.timeout)},
        })
        response = extract_text(result)
        status = "completed" if response else "failed"
        receipt = {
            "schema_version": 1,
            "room_id": args.room_id_value,
            "turn_id": args.turn_id,
            "provider": args.provider,
            "idempotency_key": args.idempotency_key,
            "status": status,
            "prompt_sha256": digest(prompt),
            "response_sha256": digest(response) if response else None,
            "response_text": response,
            "started_at": started,
            "completed_at": now(),
        }
    except Exception as exc:
        receipt = {
            "schema_version": 1,
            "room_id": args.room_id_value,
            "turn_id": args.turn_id,
            "provider": args.provider,
            "idempotency_key": args.idempotency_key,
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:1000],
            "prompt_sha256": digest(prompt),
            "started_at": started,
            "completed_at": now(),
        }
    finally:
        client.close()

    append_receipt(room_dir, receipt)
    existing[args.idempotency_key] = receipt
    ledger.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Nexus browser advisor adapter")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--room-dir", required=True)
    parser.add_argument("--room-id", dest="room_id_value", required=True)
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--mcp-command")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = run(args)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
