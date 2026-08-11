from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import advisor_flow
import agent_browser


class FakeAdapter:
    def __init__(self, replies: dict[str, list[agent_browser.ProviderResult]]) -> None:
        self.replies = {key: list(value) for key, value in replies.items()}
        self.calls: list[tuple[str, str, Path]] = []

    def new_turn_metadata(self, provider: str, task_id: str, idempotency_key: str, prompt: str, profile_path: Path) -> agent_browser.ProviderTurnMetadata:
        return agent_browser.AgentBrowserAdapter(
            agent_browser.BrowserConfig(profile_root=profile_path.parents[1])
        ).new_turn_metadata(provider, task_id, idempotency_key, prompt, profile_path)

    def send(self, provider: str, prompt: str, profile_path: Path, timeout_seconds: int, turn_metadata: object | None = None) -> agent_browser.ProviderResult:
        self.calls.append((provider, prompt, profile_path))
        queue = self.replies.setdefault(provider, [])
        if not queue:
            return agent_browser.ProviderResult(status="completed", provider=provider, response=f"{provider} default")
        result = queue.pop(0)
        metadata = result.metadata or {}
        if hasattr(turn_metadata, "to_dict"):
            metadata = turn_metadata.to_dict()
        elif isinstance(turn_metadata, dict):
            metadata = dict(turn_metadata)
        metadata["prompt_sent"] = True
        result.metadata = metadata
        return result

    def resume(self, provider: str, turn_metadata: object, timeout_seconds: int) -> agent_browser.ProviderResult:
        queue = self.replies.setdefault(provider, [])
        if not queue:
            return agent_browser.ProviderResult(status="timed_out", provider=provider, error="resume pending", metadata=dict(turn_metadata))
        result = queue.pop(0)
        result.metadata = dict(turn_metadata)
        return result


class AdvisorFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.room = self.root / "rooms" / "task-1"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def flow(self, adapter: FakeAdapter | None = None, byte_limit: int = 100000) -> advisor_flow.AdvisorFlow:
        return advisor_flow.AdvisorFlow(
            repo=self.repo,
            task_id="task-1",
            task_text="Original task body.",
            room=self.room,
            adapter=adapter or FakeAdapter({}),
            byte_limit=byte_limit,
            profile_root=self.root / "profiles",
        )

    def read_events(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in (self.room / "advisor" / "transcript.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_full_context_is_deterministic_and_complete(self) -> None:
        flow = self.flow()
        flow.append_central_event("user", "first user message", "u1")
        flow.append_central_event("orchestrator", "orchestrator note", "o1")
        first = flow.build_full_context("claude")
        second = flow.build_full_context("claude")
        self.assertEqual(first, second)
        self.assertIn("Original task body.", first)
        self.assertIn("first user message", first)
        self.assertIn("orchestrator note", first)
        events = self.read_events()
        self.assertEqual("task", events[0]["role"])
        self.assertEqual("Original task body.", events[0]["body"])
        self.assertEqual("__original_task__", events[0]["idempotency_key"])
        self.assertEqual(advisor_flow.sha256_text("Original task body."), events[0]["sha256"])

    def test_original_task_is_stored_once_and_conflicts_fail_closed(self) -> None:
        first = self.flow()
        first._ensure()
        second = self.flow()
        second._ensure()
        task_events = [event for event in self.read_events() if event["role"] == "task"]
        self.assertEqual(1, len(task_events))

        resumed = advisor_flow.AdvisorFlow(
            repo=self.repo,
            task_id="task-1",
            task_text="",
            room=self.room,
            adapter=FakeAdapter({}),
            profile_root=self.root / "profiles",
        )
        resumed._ensure()
        self.assertEqual("Original task body.", resumed.task_text)

        conflicting = advisor_flow.AdvisorFlow(
            repo=self.repo,
            task_id="task-1",
            task_text="Different original task.",
            room=self.room,
            adapter=FakeAdapter({}),
            profile_root=self.root / "profiles",
        )
        with self.assertRaisesRegex(advisor_flow.AdvisorFlowError, "Original task conflicts"):
            conflicting._ensure()

    def test_no_truncation_and_context_too_large_does_not_send(self) -> None:
        adapter = FakeAdapter({})
        flow = self.flow(adapter=adapter, byte_limit=40)
        result = flow.advisor_turn(current_user_message="x" * 100, idempotency_key="too-large")
        self.assertEqual("CONTEXT_TOO_LARGE", result["status"])
        self.assertEqual([], adapter.calls)
        self.assertGreater(result["telemetry"]["context_bytes"], result["telemetry"]["byte_limit"])
        for key in (
            "total_bytes",
            "context_bytes",
            "limit",
            "overflow",
            "event_count",
            "original_task_bytes",
            "central_event_bytes",
            "advisor_prompt_bytes",
            "advisor_response_bytes",
            "structural_overhead_bytes",
            "provider",
        ):
            self.assertIn(key, result["telemetry"])
        self.assertTrue(Path(result["telemetry"]["bundle_path"]).exists())

    def test_transcript_hash_markdown_and_idempotency(self) -> None:
        adapter = FakeAdapter({"claude": [agent_browser.ProviderResult("completed", "claude", "reply")]})
        flow = self.flow(adapter=adapter)
        result = flow.advisor_turn(current_user_message="hello", providers=["claude"], idempotency_key="k1")
        self.assertEqual("completed", result["status"])
        events = self.read_events()
        self.assertEqual(list(range(1, len(events) + 1)), [event["sequence"] for event in events])
        for event in events:
            self.assertEqual(hashlib.sha256(str(event["body"]).encode("utf-8")).hexdigest(), event["sha256"])
        markdown1 = (self.room / "advisor" / "transcript.md").read_text(encoding="utf-8")
        advisor_flow.regenerate_markdown(self.room / "advisor" / "transcript.jsonl", self.room / "advisor" / "transcript.md")
        markdown2 = (self.room / "advisor" / "transcript.md").read_text(encoding="utf-8")
        self.assertEqual(markdown1, markdown2)
        replay = flow.advisor_turn(current_user_message="hello", providers=["claude"], idempotency_key="k1")
        self.assertEqual("idempotent_replay", replay["idempotency"])
        self.assertEqual(1, len(adapter.calls))
        conflict = flow.advisor_turn(current_user_message="different", providers=["claude"], idempotency_key="k1")
        self.assertEqual("idempotency_conflict", conflict["status"])

    def test_timeout_retry_does_not_duplicate_send(self) -> None:
        adapter = FakeAdapter(
            {
                "claude": [
                    agent_browser.ProviderResult("timed_out", "claude", error="slow"),
                    agent_browser.ProviderResult("completed", "claude", response="late reply"),
                ]
            }
        )
        flow = self.flow(adapter=adapter)
        first = flow.advisor_turn(current_user_message="hello", providers=["claude"], idempotency_key="timeout")
        self.assertEqual("timed_out", first["status"])
        second = flow.advisor_turn(current_user_message="hello", providers=["claude"], idempotency_key="timeout")
        self.assertEqual("recorded", second["idempotency"])
        self.assertEqual("completed", second["status"])
        self.assertEqual(1, len(adapter.calls))

    def test_provider_failure_states_are_preserved(self) -> None:
        statuses = [
            "login_required",
            "human_verification_required",
            "rate_limited",
            "selector_changed",
            "timed_out",
            "failed",
        ]
        for status in statuses:
            with self.subTest(status=status):
                adapter = FakeAdapter({"claude": [agent_browser.ProviderResult(status, "claude", error=status)]})
                flow = advisor_flow.AdvisorFlow(
                    repo=self.repo,
                    task_id=f"task-{status}",
                    task_text="Original task body.",
                    room=self.root / "rooms" / f"task-{status}",
                    adapter=adapter,
                    profile_root=self.root / "profiles",
                )
                result = flow.advisor_turn(current_user_message=status, providers=["claude"], idempotency_key=status)
                self.assertEqual(status, result["status"])
                self.assertEqual(status, result["providers"]["claude"]["status"])

    def test_two_round_claude_gemini_flow_has_prior_prompts_and_verbatim_replies(self) -> None:
        adapter = FakeAdapter(
            {
                "claude": [
                    agent_browser.ProviderResult("completed", "claude", "claude r1 exact\nline two"),
                    agent_browser.ProviderResult("completed", "claude", "claude r2"),
                ],
                "gemini": [
                    agent_browser.ProviderResult("completed", "gemini", "gemini r1 exact"),
                    agent_browser.ProviderResult("completed", "gemini", "gemini r2"),
                ],
            }
        )
        flow = self.flow(adapter=adapter)
        r1 = flow.advisor_turn(current_user_message="round one", providers=["claude", "gemini"], idempotency_key="r1")
        self.assertEqual("completed", r1["status"])
        r2 = flow.advisor_turn(orchestrator_message="round two", providers=["claude", "gemini"], idempotency_key="r2")
        self.assertEqual("completed", r2["status"])
        claude_r2_prompt = adapter.calls[2][1]
        self.assertIn("round one", claude_r2_prompt)
        self.assertIn("round two", claude_r2_prompt)
        self.assertIn("claude r1 exact\nline two", claude_r2_prompt)
        self.assertIn("gemini r1 exact", claude_r2_prompt)
        self.assertIn("advisor_prompt", claude_r2_prompt)
        profile_path = adapter.calls[0][2]
        self.assertEqual(self.root / "profiles" / "task-1" / "claude", profile_path)


class AdvisorPowerShellWrapperTests(unittest.TestCase):
    def test_wrapper_omits_empty_optional_advisor_arguments(self) -> None:
        script = (ROOT / "council.ps1").read_text(encoding="utf-8")
        self.assertIn("if ($Task) { $ArgsList += @('--task', $Task) }", script)
        self.assertIn("if ($CurrentUserMessage)", script)
        self.assertIn("if ($OrchestratorMessage)", script)
        self.assertIn("if ($Synthesis)", script)
        self.assertNotIn("'--synthesis', $Synthesis, '--providers'", script)


class AgentBrowserTests(unittest.TestCase):
    def test_native_browser_command_resolution(self) -> None:
        command = agent_browser.resolve_browser_command()
        self.assertTrue(Path(command).is_file())
        if os.name == "nt":
            self.assertEqual(".exe", Path(command).suffix.lower())
            self.assertIn("agent-browser", Path(command).name.lower())

    def test_selector_registry_and_profile_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = agent_browser.BrowserConfig(profile_root=Path(tmp) / "profiles")
            adapter = agent_browser.AgentBrowserAdapter(config)
            self.assertEqual("https://claude.ai/", adapter.provider_url("claude"))
            self.assertEqual(Path(tmp) / "profiles" / "room-a" / "gemini", adapter.profile_path("room-a", "gemini"))
            selectors = adapter.selectors_for("gemini")
            self.assertIn("aria_fallbacks", selectors)


class AgentBrowserContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / "fake-state.json"
        self.state.write_text(json.dumps({"mode": "completed"}), encoding="utf-8")
        self.fake = self.root / "fake_agent_browser.py"
        self.fake.write_text(
            f"""#!{sys.executable}
import json, os, sys
from pathlib import Path

state_path = Path(os.environ["FAKE_AGENT_BROWSER_STATE"])
state = json.loads(state_path.read_text(encoding="utf-8"))
mode = state.get("mode", "completed")
log = state.setdefault("log", [])
args = sys.argv[1:]
command = next((a for a in args if a in ("open", "wait", "eval")), "")
stdin = sys.stdin.read()

def save():
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

def out(value):
    print(json.dumps({{"value": json.dumps(value)}}))
    save()

log.append({{"command": command, "session": args[args.index("--session") + 1] if "--session" in args else "", "profile": args[args.index("--profile") + 1] if "--profile" in args else ""}})
if command in ("open", "wait"):
    out({{"status": "ok", "url": args[-1] if command == "open" else ""}})
elif "__nexus_classify_page" in stdin:
    mapping = {{"login": "login_required", "human": "human_verification_required", "rate": "rate_limited"}}
    out({{"status": mapping.get(mode, "ready"), "url": "https://example.test/chat"}})
elif "__nexus_baseline" in stdin:
    out({{"status": "ready", "count": 1, "fingerprint": "old", "url": "https://example.test/chat/1"}})
elif "__nexus_send_prompt" in stdin:
    if mode == "selector":
        out({{"status": "selector_changed", "error": "composer_not_found", "url": "https://example.test/chat/1"}})
    else:
        state["send_count"] = int(state.get("send_count", 0)) + 1
        out({{"status": "sent", "url": "https://example.test/chat/1"}})
elif "__nexus_extract_response" in stdin:
    if mode == "timeout":
        out({{"status": "pending", "response": "", "url": "https://example.test/chat/1"}})
    else:
        out({{"status": "completed", "response": "visible assistant reply\\nline two", "count": 2, "fingerprint": "new", "url": "https://example.test/chat/1"}})
else:
    out({{"status": "failed", "error": "unknown script"}})
""",
            encoding="utf-8",
        )
        self.fake.chmod(0o755)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def set_mode(self, mode: str) -> None:
        data = json.loads(self.state.read_text(encoding="utf-8"))
        data["mode"] = mode
        self.state.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")

    def adapter(self) -> agent_browser.AgentBrowserAdapter:
        config = agent_browser.BrowserConfig(
            profile_root=self.root / "profiles",
            browser_command=(sys.executable, str(self.fake)),
            headed=True,
            poll_interval_seconds=0.01,
            stable_polls=1,
            command_timeout_seconds=5,
            extra_env={"FAKE_AGENT_BROWSER_STATE": str(self.state)},
        )
        return agent_browser.AgentBrowserAdapter(config)

    def test_fake_executable_send_completion_uses_configured_backend(self) -> None:
        adapter = self.adapter()
        profile = adapter.profile_path("task/room", "claude")
        meta = adapter.new_turn_metadata("claude", "task/room", "k", "FULL_CONTEXT", profile)
        result = adapter.send("claude", "FULL_CONTEXT", profile, 2, meta)
        self.assertEqual("completed", result.status)
        self.assertEqual("visible assistant reply\nline two", result.response)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(1, state["send_count"])
        sessions = {entry["session"] for entry in state["log"]}
        self.assertEqual({"nexus-task-room-claude"}, sessions)
        self.assertTrue(str(profile).endswith(os.path.join("task-room", "claude")))

    def test_fake_executable_maps_blocking_states(self) -> None:
        cases = {
            "login": "login_required",
            "human": "human_verification_required",
            "rate": "rate_limited",
            "selector": "selector_changed",
            "timeout": "timed_out",
        }
        for mode, status in cases.items():
            with self.subTest(mode=mode):
                self.set_mode(mode)
                adapter = self.adapter()
                profile = adapter.profile_path(f"task-{mode}", "gemini")
                meta = adapter.new_turn_metadata("gemini", f"task-{mode}", "k", "FULL_CONTEXT", profile)
                result = adapter.send("gemini", "FULL_CONTEXT", profile, 1, meta)
                self.assertEqual(status, result.status)

    def test_flow_resume_uses_same_turn_without_duplicate_send(self) -> None:
        self.set_mode("timeout")
        adapter = self.adapter()
        flow = advisor_flow.AdvisorFlow(
            repo=self.root / "repo",
            task_id="resume-task",
            task_text="Task",
            room=self.root / "room",
            adapter=adapter,
            profile_root=self.root / "profiles",
        )
        (self.root / "repo").mkdir()
        first = flow.advisor_turn(current_user_message="hello", providers=["claude"], idempotency_key="same-key", timeout_seconds=1)
        self.assertEqual("timed_out", first["status"])
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(1, state["send_count"])

        self.set_mode("completed")
        second = flow.advisor_turn(current_user_message="hello", providers=["claude"], idempotency_key="same-key", timeout_seconds=2)
        self.assertEqual("completed", second["status"])
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(1, state["send_count"])


if __name__ == "__main__":
    unittest.main()
