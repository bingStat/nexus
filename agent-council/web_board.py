from __future__ import annotations

import argparse
import html
import json
import os
import secrets
import sys
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import web_council


def is_authorized(headers: dict[str, str], token: str) -> bool:
    supplied = headers.get("Authorization", "")
    return bool(token) and secrets.compare_digest(supplied, f"Bearer {token}")


def _host_and_port(value: str) -> tuple[str, int | None]:
    raw = value.strip().lower()
    if raw.startswith("["):
        end = raw.find("]")
        if end < 0:
            return "", None
        name = raw[1:end]
        suffix = raw[end + 1 :]
        port = int(suffix[1:]) if suffix.startswith(":") and suffix[1:].isdigit() else None
        return name, port
    name, separator, port_text = raw.partition(":")
    return name, int(port_text) if separator and port_text.isdigit() else None


def is_local_post_source(origin: str, host: str, client_id: str = "") -> bool:
    allowed_hosts = {"127.0.0.1", "localhost", "::1"}
    host_name, host_port = _host_and_port(host)
    if host_name not in allowed_hosts:
        return False
    if not origin:
        return client_id == "nexus-cli"
    try:
        parsed = urllib.parse.urlparse(origin)
        origin_host = (parsed.hostname or "").lower()
        origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and origin_host == host_name
        and origin_host in allowed_hosts
        and (host_port is None or origin_port == host_port)
    )


def make_handler(room: Path, token: str) -> type[BaseHTTPRequestHandler]:
    class BoardHandler(BaseHTTPRequestHandler):
        server_version = "NexusWebCouncil/1.0"

        def do_GET(self) -> None:
            if self.path.startswith("/api/status"):
                if not self._api_allowed():
                    self._send_json({"status": "forbidden"}, HTTPStatus.FORBIDDEN)
                    return
                self._send_json(web_council.WebCouncil.open(room).status()["json"])
                return
            self._send_html(render_board(room, token))

        def do_POST(self) -> None:
            if not self._write_allowed():
                self._send_json({"status": "forbidden"}, HTTPStatus.FORBIDDEN)
                return
            if not self.path.startswith("/api/submit"):
                self._send_json({"status": "not_found"}, HTTPStatus.NOT_FOUND)
                return
            try:
                data = self._read_post()
                result = web_council.WebCouncil.open(room).submit(
                    str(data.get("provider", "")),
                    data.get("round", ""),
                    str(data.get("response", "")),
                    overwrite=bool(data.get("overwrite", False)),
                )
                self._send_json({"status": "ok", **result})
            except Exception as exc:
                self._send_json({"status": "failed", "error": str(exc)}, HTTPStatus.BAD_REQUEST)

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("[web-board] " + fmt % args + "\n")

        def _api_allowed(self) -> bool:
            headers = {key: value for key, value in self.headers.items()}
            return is_authorized(headers, token)

        def _write_allowed(self) -> bool:
            headers = {key: value for key, value in self.headers.items()}
            return is_authorized(headers, token) and is_local_post_source(
                headers.get("Origin", ""),
                headers.get("Host", ""),
                headers.get("X-Nexus-Client", ""),
            )

        def _read_post(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            content_type = self.headers.get("Content-Type", "")
            if "application/json" in content_type:
                return json.loads(raw or "{}")
            parsed = urllib.parse.parse_qs(raw, keep_blank_values=True)
            return {key: values[-1] if values else "" for key, values in parsed.items()}

        def _send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, text: str) -> None:
            body = text.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(body)

        def _send_security_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'",
            )

    return BoardHandler


def render_board(room: Path, token: str) -> str:
    council = web_council.WebCouncil.open(room)
    status = council.status()["json"]
    cards = []
    for provider in web_council.PROVIDERS:
        url = web_council.PROVIDER_URLS[provider]
        prompt = ""
        for round_num in (2, 1):
            path = room / "web" / "prompts" / str(round_num) / f"{provider}.md"
            if path.exists():
                prompt = path.read_text(encoding="utf-8")
                break
        submitted = []
        for round_num in (1, 2):
            state = status.get("rounds", {}).get(str(round_num), {})
            submitted.append(f"R{round_num}: {'submitted' if provider in state else 'pending'}")
        cards.append(
            f"""
            <section class="card">
              <header><h2>{html.escape(provider)}</h2><a target="_blank" rel="noreferrer" href="{url}">Open</a></header>
              <p class="state">{html.escape(' | '.join(submitted))}</p>
              <textarea readonly id="prompt-{provider}">{html.escape(prompt)}</textarea>
              <button type="button" onclick="copyPrompt('{provider}')">Copy Prompt</button>
              <form onsubmit="submitReply(event, '{provider}')">
                <label>Round <select name="round"><option value="1">1</option><option value="2">2</option></select></label>
                <textarea name="response" placeholder="Paste the provider reply here"></textarea>
                <label class="inline">or load a text/Markdown file <input type="file" name="response_file" accept=".txt,.md,text/plain,text/markdown"></label>
                <label class="inline"><input type="checkbox" name="overwrite" value="1"> overwrite before freeze</label>
                <button type="submit">Submit</button>
              </form>
            </section>
            """
        )
    final_path = room / "decisions" / "final-decision.md"
    final_text = final_path.read_text(encoding="utf-8") if final_path.exists() else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nexus Web Council</title>
<style>
body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f7f7f4; color: #202124; }}
main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
.top {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 18px; }}
.phase {{ font-size: 18px; font-weight: 650; }}
.note {{ background: #fff7d6; border: 1px solid #ead487; padding: 10px 12px; border-radius: 6px; max-width: 560px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }}
.card {{ background: #fff; border: 1px solid #d8d9d5; border-radius: 8px; padding: 14px; }}
header {{ display: flex; justify-content: space-between; align-items: center; }}
h1, h2 {{ margin: 0; }}
h2 {{ font-size: 18px; }}
a, button {{ border: 1px solid #2f5d50; background: #2f5d50; color: white; text-decoration: none; border-radius: 6px; padding: 8px 10px; cursor: pointer; }}
textarea {{ width: 100%; min-height: 150px; box-sizing: border-box; margin: 8px 0; border: 1px solid #c7c8c3; border-radius: 6px; padding: 8px; font: 13px Consolas, monospace; }}
.state, .next {{ color: #5f6368; }}
.inline {{ display: block; margin: 4px 0 10px; }}
pre {{ white-space: pre-wrap; background: #fff; border: 1px solid #d8d9d5; border-radius: 8px; padding: 14px; }}
</style>
</head>
<body>
<main>
  <section class="top">
    <div>
      <h1>Nexus Web Council</h1>
      <p>Task: {html.escape(status["task_id"])}</p>
      <p class="phase">Phase: {html.escape(status["phase"])}</p>
      <p class="next">Next: {html.escape(status["next_action"])}</p>
    </div>
    <p class="note">Replies are manually submitted. This board does not read provider pages, control browser tabs, extract page content, or store provider sign-in material.</p>
  </section>
  <section class="grid">{''.join(cards)}</section>
  <h2>Final Result</h2>
  <pre>{html.escape(final_text or 'No final decision yet.')}</pre>
</main>
<script>
const token = {json.dumps(token)};
async function copyPrompt(provider) {{
  const node = document.getElementById('prompt-' + provider);
  await navigator.clipboard.writeText(node.value);
}}
async function submitReply(event, provider) {{
  event.preventDefault();
  const form = event.target;
  const selectedFile = form.response_file.files[0];
  const payload = {{
    provider,
    round: form.round.value,
    response: selectedFile ? await selectedFile.text() : form.response.value,
    overwrite: form.overwrite.checked
  }};
  const res = await fetch('/api/submit', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token }},
    body: JSON.stringify(payload)
  }});
  const data = await res.json();
  if (!res.ok) alert(data.error || 'Submit failed');
  else location.reload();
}}
</script>
</body>
</html>"""


def serve(room: Path, bind: str = "127.0.0.1", port: int = 8765, token: str | None = None) -> None:
    token = token or os.environ.get("NEXUS_WEB_COUNCIL_TOKEN") or secrets.token_urlsafe(24)
    server = ThreadingHTTPServer((bind, port), make_handler(room, token))
    print(json.dumps({"status": "serving", "url": f"http://{bind}:{port}/", "token": token, "room": str(room)}, ensure_ascii=False), flush=True)
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Nexus Web Council Board")
    parser.add_argument("--room", required=True)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token")
    args = parser.parse_args()
    serve(Path(args.room), args.bind, args.port, args.token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
