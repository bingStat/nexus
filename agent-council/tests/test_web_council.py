from __future__ import annotations

import ast
import concurrent.futures
import http.client
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import web_board
import web_council


class WebCouncilTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def start(self, mode: str = "web-discussion") -> web_council.WebCouncil:
        council = web_council.WebCouncil(
            repo=self.root / "repo",
            task_id="task-1",
            task_text="Implement the feature safely.",
            mode=mode,
            room=self.root / "rooms" / "repo" / "task-1",
        )
        council.start()
        return council

    def test_provider_and_round_validation(self) -> None:
        self.start()
        with self.assertRaises(web_council.WebCouncilError):
            web_council.validate_provider("openai")
        with self.assertRaises(web_council.WebCouncilError):
            web_council.validate_round(3)
        with self.assertRaises(web_council.WebCouncilError):
            web_council.WebCouncil.open(self.root / "rooms" / "repo" / "task-1").submit("chatgpt", 2, "early")

    def test_prompt_generation_for_rounds(self) -> None:
        council = self.start()
        for provider in web_council.PROVIDERS:
            text = (council.room / "web" / "prompts" / "1" / f"{provider}.md").read_text(encoding="utf-8")
            self.assertIn(provider, text)
            self.assertIn("independent proposal", text)
        for provider in web_council.PROVIDERS:
            council.submit(provider, 1, f"{provider} proposal")
        status = council.advance()
        self.assertEqual("awaiting-web-cross-review", status["phase"])
        gemini_prompt = (council.room / "web" / "prompts" / "2" / "gemini.md").read_text(encoding="utf-8")
        self.assertIn("chatgpt proposal", gemini_prompt)
        self.assertIn("claude proposal", gemini_prompt)
        self.assertNotIn("gemini proposal", gemini_prompt)

    def test_atomic_idempotent_and_conflicting_submission(self) -> None:
        council = self.start()
        first = council.submit("chatgpt", 1, "\r\n```markdown\nsame\n```\r\n")
        self.assertEqual("submitted", first["result"])
        duplicate = council.submit("chatgpt", 1, "same")
        self.assertEqual("idempotent", duplicate["result"])
        with self.assertRaises(web_council.WebCouncilError):
            council.submit("chatgpt", 1, "different")
        state = json.loads((council.room / "web" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual("awaiting-web-proposals", state["phase"])
        self.assertEqual("same", (council.room / "web" / "responses" / "1" / "chatgpt.md").read_text(encoding="utf-8"))

    def test_transition_gates_and_overwrite_freeze(self) -> None:
        council = self.start()
        council.submit("chatgpt", 1, "a")
        with self.assertRaises(web_council.WebCouncilError):
            council.advance()
        council.submit("claude", 1, "b")
        council.submit("gemini", 1, "c")
        council.submit("gemini", 1, "c2", overwrite=True)
        council.advance()
        with self.assertRaises(web_council.WebCouncilError):
            council.submit("gemini", 1, "c3", overwrite=True)
        with self.assertRaises(web_council.WebCouncilError):
            council.finalize_discussion("decision")
        for provider in web_council.PROVIDERS:
            council.submit(provider, 2, f"{provider} review")
        state = council.finalize_discussion("final decision")
        self.assertEqual("decision-complete", state["phase"])
        self.assertTrue((council.room / "decisions" / "final-decision.md").exists())

    def test_status_digest_and_canonical_messages(self) -> None:
        council = self.start()
        council.submit("chatgpt", 1, "hello")
        status = council.status()
        self.assertEqual("awaiting-web-proposals", status["json"]["phase"])
        self.assertIn("awaiting-web-proposals", status["digest"])
        message = next((council.room / "messages").glob("*chatgpt-web-response.md"))
        text = message.read_text(encoding="utf-8")
        self.assertIn("provider: chatgpt", text)
        self.assertIn("round: 1", text)

    def test_concurrent_identical_submissions_are_idempotent(self) -> None:
        council = self.start()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: council.submit("chatgpt", 1, "same response"), range(6)))
        outcomes = [item["result"] for item in results]
        self.assertEqual(1, outcomes.count("submitted"))
        self.assertEqual(5, outcomes.count("idempotent"))

    def test_hybrid_transitions_update_states_and_events(self) -> None:
        council = self.start("web-hybrid")
        for provider in web_council.PROVIDERS:
            council.submit(provider, 1, f"{provider} proposal")
        council.advance()
        for provider in web_council.PROVIDERS:
            council.submit(provider, 2, f"{provider} review")
        council.finalize_discussion("decision")
        implementing = council.transition("implementing", event="web-hybrid-implementing")
        self.assertEqual("implementing", implementing["phase"])
        accepted = council.transition(
            "accepted",
            event="web-hybrid-complete",
            updates={"verdict": "ACCEPT", "machine_acceptance_passed": True},
        )
        self.assertEqual("accepted", accepted["phase"])
        room_state = json.loads((council.room / "state.json").read_text(encoding="utf-8"))
        self.assertEqual("accepted", room_state["status"])
        events = (council.room / "web" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertTrue(any('"event": "web-hybrid-implementing"' in line for line in events))
        self.assertTrue(any('"event": "web-hybrid-complete"' in line for line in events))
        with self.assertRaises(web_council.WebCouncilError):
            council.transition("implementing", event="invalid-backward-transition")

    def test_no_scraping_or_credentials_keywords(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "web_council.py", ROOT / "web_board.py")
            if path.exists()
        )
        forbidden = ("selenium", "puppeteer", "playwright", "webdriver", "beautifulsoup", "cookie", "localStorage", "captcha")
        for word in forbidden:
            self.assertNotIn(word.lower(), combined.lower())
        forbidden_modules = {"selenium", "playwright", "puppeteer", "bs4", "requests"}
        for source_path in (ROOT / "web_council.py", ROOT / "web_board.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            imported = {
                alias.name.split(".", 1)[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            }
            imported.update(
                (node.module or "").split(".", 1)[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            )
            self.assertTrue(forbidden_modules.isdisjoint(imported))


class BoardSecurityTests(unittest.TestCase):
    def test_write_security_checks(self) -> None:
        self.assertFalse(web_board.is_authorized({"Authorization": ""}, "secret"))
        self.assertFalse(web_board.is_authorized({"Authorization": "Bearer wrong"}, "secret"))
        self.assertTrue(web_board.is_authorized({"Authorization": "Bearer secret"}, "secret"))
        self.assertFalse(web_board.is_local_post_source("http://evil.example", "127.0.0.1:8765"))
        self.assertTrue(web_board.is_local_post_source("http://127.0.0.1:8765", "127.0.0.1:8765"))
        self.assertFalse(web_board.is_local_post_source("http://127.0.0.1:9999", "127.0.0.1:8765"))
        self.assertFalse(web_board.is_local_post_source("", "localhost:8765"))
        self.assertTrue(web_board.is_local_post_source("", "localhost:8765", "nexus-cli"))

    def test_status_api_and_post_origin_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            council = web_council.WebCouncil(
                repo=root / "repo",
                task_id="board-task",
                task_text="test",
                room=root / "rooms" / "board-task",
            )
            council.start()
            server = ThreadingHTTPServer(("127.0.0.1", 0), web_board.make_handler(council.room, "secret"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/api/status")
                response = conn.getresponse()
                response.read()
                self.assertEqual(403, response.status)
                conn.close()

                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/api/status", headers={"Authorization": "Bearer secret"})
                response = conn.getresponse()
                response.read()
                self.assertEqual(200, response.status)
                conn.close()

                body = json.dumps({"provider": "chatgpt", "round": 1, "response": "reply"})
                headers = {"Authorization": "Bearer secret", "Content-Type": "application/json"}
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("POST", "/api/submit", body=body, headers=headers)
                response = conn.getresponse()
                response.read()
                self.assertEqual(403, response.status)
                conn.close()

                headers["X-Nexus-Client"] = "nexus-cli"
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("POST", "/api/submit", body=body, headers=headers)
                response = conn.getresponse()
                response.read()
                self.assertEqual(200, response.status)
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


    def test_herdr_plugin_manifest_schema(self) -> None:
        import tomllib

        plugin_root = ROOT / "herdr-plugin"
        data = tomllib.loads((plugin_root / "herdr-plugin.toml").read_text(encoding="utf-8"))
        self.assertEqual("nexus-web-council", data["id"])
        self.assertEqual(["windows"], data["platforms"])
        self.assertNotIn("plugin", data)
        self.assertIsInstance(data["actions"][0]["command"], list)
        self.assertIn("title", data["actions"][0])
        self.assertNotIn("args", data["actions"][0])
        self.assertIsInstance(data["panes"][0]["command"], list)
        self.assertEqual("tab", data["panes"][0]["placement"])
        for script in ("start-board.ps1", "status-pane.ps1"):
            content = (plugin_root / script).read_text(encoding="utf-8")
            self.assertNotIn("Mandatory=$true", content)
            self.assertIn("Resolve-WebCouncilTask", content)


if __name__ == "__main__":
    unittest.main()
