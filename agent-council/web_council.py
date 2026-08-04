from __future__ import annotations

import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

PROVIDERS = ("chatgpt", "claude", "gemini")
MODES = ("web-discussion", "web-hybrid")
ROUNDS = (1, 2)
PHASES = (
    "initialized",
    "awaiting-web-proposals",
    "awaiting-web-cross-review",
    "ready-to-finalize",
    "implementing",
    "accepted",
    "revision-required",
    "rejected",
    "decision-complete",
)

ALLOWED_TRANSITIONS = {
    "decision-complete": {"implementing"},
    "implementing": {"accepted", "revision-required", "rejected"},
}

PROVIDER_URLS = {
    "chatgpt": "https://chatgpt.com/",
    "claude": "https://claude.ai/",
    "gemini": "https://gemini.google.com/",
}


class WebCouncilError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_provider(provider: str) -> str:
    if provider not in PROVIDERS:
        raise WebCouncilError(f"Invalid provider {provider!r}; expected one of: {', '.join(PROVIDERS)}")
    return provider


def validate_round(round_id: int | str) -> int:
    try:
        value = int(round_id)
    except (TypeError, ValueError) as exc:
        raise WebCouncilError("Round must be 1 or 2.") from exc
    if value not in ROUNDS:
        raise WebCouncilError("Round must be 1 or 2.")
    return value


def normalize_response(text: str) -> str:
    value = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    match = re.fullmatch(r"```(?:markdown|md)?\n(.*)\n```", value, flags=re.IGNORECASE | re.DOTALL)
    if match:
        value = match.group(1).strip()
    return value


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{int(time.time() * 1000000)}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    last_error: PermissionError | None = None
    for _ in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05)
    try:
        tmp.unlink(missing_ok=True)
    finally:
        if last_error:
            raise WebCouncilError(f"Could not replace {path}: {last_error}") from last_error


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class DirectoryLock:
    def __init__(self, path: Path, timeout: float = 10.0, stale_after: float = 60.0) -> None:
        self.path = path
        self.timeout = timeout
        self.stale_after = stale_after

    def __enter__(self) -> "DirectoryLock":
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                os.mkdir(self.path)
                atomic_write_text(self.path / "owner.json", json.dumps({"pid": os.getpid(), "created_at": now_iso()}))
                return self
            except FileExistsError:
                if self._is_stale():
                    self._clear()
                    continue
                if time.monotonic() >= deadline:
                    raise WebCouncilError(f"Timed out waiting for lock: {self.path}")
                time.sleep(0.05)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._clear()

    def _is_stale(self) -> bool:
        try:
            return time.time() - self.path.stat().st_mtime > self.stale_after
        except FileNotFoundError:
            return False

    def _clear(self) -> None:
        try:
            for child in self.path.iterdir():
                child.unlink(missing_ok=True)
            self.path.rmdir()
        except FileNotFoundError:
            return
        except OSError:
            return


class WebCouncil:
    def __init__(self, repo: Path, task_id: str, task_text: str = "", mode: str = "web-discussion", room: Path | None = None) -> None:
        if mode not in MODES:
            raise WebCouncilError(f"Invalid mode {mode!r}; expected web-discussion or web-hybrid.")
        self.repo = Path(repo).resolve()
        self.task_id = task_id
        self.task_text = task_text.strip()
        self.mode = mode
        self.room = Path(room).resolve() if room else self._default_room()
        self.web = self.room / "web"

    @classmethod
    def open(cls, room: Path) -> "WebCouncil":
        state = read_json(Path(room) / "web" / "state.json")
        return cls(Path(state["repo"]), state["task_id"], state.get("task_text", ""), state["mode"], Path(room))

    def _default_room(self) -> Path:
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
        return root / "Nexus" / "agent-council" / "rooms" / self.repo.name / self.task_id

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.web.mkdir(parents=True, exist_ok=True)
        with DirectoryLock(self.web / ".lock"):
            yield

    def transition(self, phase: str, *, event: str, updates: dict[str, Any] | None = None) -> dict[str, Any]:
        if phase not in PHASES:
            raise WebCouncilError(f"Invalid target phase: {phase!r}")
        with self.locked():
            state = self._state()
            current = state["phase"]
            allowed = ALLOWED_TRANSITIONS.get(current, set())
            if phase not in allowed:
                raise WebCouncilError(f"Invalid phase transition: {current} -> {phase}")
            state.update(updates or {})
            state["phase"] = phase
            state["updated_at"] = now_iso()
            self._write_state_and_event(
                state,
                {"event": event, "from_phase": current, "phase": phase},
            )
            return state

    def start(self) -> dict[str, Any]:
        with self.locked():
            if (self.web / "state.json").exists():
                return self._state()
            for sub in ("messages", "decisions", "logs", "web/prompts/1", "web/prompts/2", "web/responses/1", "web/responses/2"):
                (self.room / sub).mkdir(parents=True, exist_ok=True)
            if self.task_text:
                atomic_write_text(self.room / "task.md", self._task_markdown())
            state = {
                "version": 1,
                "task_id": self.task_id,
                "repo": str(self.repo),
                "room": str(self.room),
                "mode": self.mode,
                "phase": "awaiting-web-proposals",
                "task_text": self.task_text,
                "providers": list(PROVIDERS),
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "rounds": {"1": {}, "2": {}},
                "frozen_rounds": [],
            }
            for provider in PROVIDERS:
                atomic_write_text(self._prompt_path(1, provider), self._round1_prompt(provider))
            self._write_state_and_event(state, {"event": "web-start", "phase": state["phase"]})
            return state

    def submit(self, provider: str, round_id: int | str, response: str, overwrite: bool = False) -> dict[str, Any]:
        provider = validate_provider(provider)
        round_num = validate_round(round_id)
        normalized = normalize_response(response)
        if not normalized:
            raise WebCouncilError("Response is empty after normalization.")
        with self.locked():
            state = self._state()
            self._assert_round_accepts_submission(state, round_num, overwrite)
            existing = self._response_path(round_num, provider)
            digest = sha256_text(normalized)
            result = "submitted"
            if existing.exists():
                old_text = normalize_response(existing.read_text(encoding="utf-8"))
                old_digest = sha256_text(old_text)
                if old_digest == digest:
                    result = "idempotent"
                elif overwrite:
                    result = "overwritten"
                else:
                    raise WebCouncilError(f"Conflicting duplicate response for provider={provider}, round={round_num}.")
            if result != "idempotent":
                atomic_write_text(existing, normalized)
                self._import_message(provider, round_num, normalized)
            state["rounds"].setdefault(str(round_num), {})[provider] = {
                "path": str(existing),
                "sha256": digest,
                "submitted_at": now_iso(),
            }
            if round_num == 2 and self._round_complete(state, 2):
                state["phase"] = "ready-to-finalize"
                state["frozen_rounds"] = sorted(set(state.get("frozen_rounds", [])) | {2})
            state["updated_at"] = now_iso()
            self._write_state_and_event(state, {"event": f"web-submit-{result}", "provider": provider, "round": round_num, "sha256": digest})
            return {"result": result, "phase": state["phase"], "provider": provider, "round": round_num}

    def advance(self) -> dict[str, Any]:
        with self.locked():
            state = self._state()
            if state["phase"] != "awaiting-web-proposals":
                raise WebCouncilError(f"Cannot advance from phase {state['phase']}.")
            if not self._round_complete(state, 1):
                missing = self._missing(state, 1)
                raise WebCouncilError(f"Round 1 is incomplete; missing: {', '.join(missing)}")
            for provider in PROVIDERS:
                atomic_write_text(self._prompt_path(2, provider), self._round2_prompt(provider))
            state["phase"] = "awaiting-web-cross-review"
            state["frozen_rounds"] = sorted(set(state.get("frozen_rounds", [])) | {1})
            state["updated_at"] = now_iso()
            self._write_state_and_event(state, {"event": "web-advance", "phase": state["phase"]})
            return state

    def finalize_discussion(self, decision: str) -> dict[str, Any]:
        normalized = normalize_response(decision)
        if not normalized:
            raise WebCouncilError("Final decision is empty.")
        with self.locked():
            state = self._state()
            if state["phase"] != "ready-to-finalize":
                missing = self._missing(state, 2)
                raise WebCouncilError(f"Round 2 is incomplete; missing: {', '.join(missing)}")
            decision_path = self.room / "decisions" / "final-decision.md"
            atomic_write_text(decision_path, normalized + "\n")
            state["phase"] = "decision-complete"
            state["decision"] = str(decision_path)
            state["frozen_rounds"] = sorted(set(state.get("frozen_rounds", [])) | {1, 2})
            state["updated_at"] = now_iso()
            self._write_state_and_event(state, {"event": "web-finalize", "phase": state["phase"]})
            return state

    def finalization_prompt(self) -> str:
        state = self._state()
        if not self._round_complete(state, 2):
            raise WebCouncilError(f"Round 2 is incomplete; missing: {', '.join(self._missing(state, 2))}")
        parts = [
            "You are the local Codex verifier for Nexus Web Council.",
            "Use only the task and manually submitted provider evidence below.",
            "Synthesize the final decision. In web-discussion, produce a decision only; in web-hybrid, include mandatory implementation constraints.",
            "",
            f"Task ID: {self.task_id}",
            f"Mode: {state['mode']}",
            "",
            "===== Task =====",
            (self.room / "task.md").read_text(encoding="utf-8") if (self.room / "task.md").exists() else state.get("task_text", ""),
        ]
        for round_num in ROUNDS:
            for provider in PROVIDERS:
                parts.extend([
                    "",
                    f"===== Round {round_num} {provider} =====",
                    self._response_path(round_num, provider).read_text(encoding="utf-8"),
                ])
        return "\n".join(parts).strip() + "\n"

    def status(self) -> dict[str, Any]:
        state = self._state()
        missing1 = self._missing(state, 1)
        missing2 = self._missing(state, 2)
        next_action = self._next_action(state, missing1, missing2)
        digest = f"{state['task_id']}: {state['phase']} | round1 missing: {', '.join(missing1) or 'none'} | round2 missing: {', '.join(missing2) or 'none'} | next: {next_action}"
        return {"json": {**state, "missing": {"1": missing1, "2": missing2}, "next_action": next_action}, "digest": digest}

    def _state(self) -> dict[str, Any]:
        path = self.web / "state.json"
        if not path.exists():
            raise WebCouncilError(f"Web Council state not found: {path}")
        state = read_json(path)
        if state.get("phase") not in PHASES:
            raise WebCouncilError(f"Invalid phase in state: {state.get('phase')!r}")
        return state

    def _write_state_and_event(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        atomic_write_json(self.web / "state.json", state)
        atomic_write_json(self.room / "state.json", {**state, "status": state["phase"], "web_state": str(self.web / "state.json")})
        event_record = {"time": now_iso(), "task_id": self.task_id, **event}
        events_path = self.web / "events.jsonl"
        previous = events_path.read_text(encoding="utf-8") if events_path.exists() else ""
        atomic_write_text(events_path, previous + json.dumps(event_record, ensure_ascii=False) + "\n")

    def _assert_round_accepts_submission(self, state: dict[str, Any], round_num: int, overwrite: bool) -> None:
        phase = state["phase"]
        frozen = set(state.get("frozen_rounds", []))
        if round_num in frozen:
            raise WebCouncilError(f"Round {round_num} is frozen.")
        if round_num == 1 and phase != "awaiting-web-proposals":
            raise WebCouncilError(f"Round 1 responses are not accepted during phase {phase}.")
        if round_num == 2 and phase != "awaiting-web-cross-review":
            raise WebCouncilError(f"Round 2 responses are not accepted during phase {phase}.")
        if overwrite and round_num in frozen:
            raise WebCouncilError(f"Round {round_num} cannot be overwritten after freeze.")

    def _round_complete(self, state: dict[str, Any], round_num: int) -> bool:
        submitted = state.get("rounds", {}).get(str(round_num), {})
        return all(provider in submitted and self._response_path(round_num, provider).exists() for provider in PROVIDERS)

    def _missing(self, state: dict[str, Any], round_num: int) -> list[str]:
        submitted = state.get("rounds", {}).get(str(round_num), {})
        return [provider for provider in PROVIDERS if provider not in submitted or not self._response_path(round_num, provider).exists()]

    def _next_action(self, state: dict[str, Any], missing1: list[str], missing2: list[str]) -> str:
        phase = state["phase"]
        if phase == "awaiting-web-proposals":
            return "submit round 1 responses" if missing1 else "run web-advance"
        if phase == "awaiting-web-cross-review":
            return "submit round 2 responses" if missing2 else "run web-finalize"
        if phase == "ready-to-finalize":
            return "run web-finalize"
        return "none"

    def _task_markdown(self) -> str:
        return (
            "# Task\n\n"
            f"{self.task_text}\n\n"
            "## Council protocol\n\n"
            "Manual Web Council: independent proposal -> cross-review -> local verifier decision -> optional local implementation.\n"
        )

    def _round1_prompt(self, provider: str) -> str:
        return (
            f"You are {provider} participating in Nexus Web Council.\n\n"
            "Produce an independent proposal for the task. Cover correctness, architecture, operational risks, tests, and rejection conditions. "
            "Do not assume access to local files beyond the task text below.\n\n"
            f"Task ID: {self.task_id}\nMode: {self.mode}\n\n===== Task =====\n{self.task_text}\n"
        )

    def _round2_prompt(self, provider: str) -> str:
        sections = [
            f"You are {provider} in Nexus Web Council round 2.",
            "Cross-review the other providers' round 1 proposals. Identify fatal issues, ordinary issues, missing tests, and recommended mandatory changes.",
            "Do not revise your own proposal here; review only the evidence below.",
            "",
            f"Task ID: {self.task_id}",
            f"Mode: {self.mode}",
        ]
        for other in PROVIDERS:
            if other == provider:
                continue
            sections.extend(["", f"===== {other} round 1 response =====", self._response_path(1, other).read_text(encoding="utf-8")])
        return "\n".join(sections).strip() + "\n"

    def _prompt_path(self, round_num: int, provider: str) -> Path:
        return self.web / "prompts" / str(round_num) / f"{provider}.md"

    def _response_path(self, round_num: int, provider: str) -> Path:
        return self.web / "responses" / str(round_num) / f"{provider}.md"

    def _import_message(self, provider: str, round_num: int, body: str) -> None:
        messages = self.room / "messages"
        messages.mkdir(parents=True, exist_ok=True)
        next_seq = 1
        for path in messages.glob("*.md"):
            try:
                next_seq = max(next_seq, int(path.name.split("-", 1)[0]) + 1)
            except ValueError:
                continue
        front = [
            "---",
            f"id: {next_seq:03d}",
            f"from: {provider}",
            "to: orchestrator",
            "type: web-response",
            f"provider: {provider}",
            f"round: {round_num}",
            f"task_id: {self.task_id}",
            "status: final",
            f"created_at: {now_iso()}",
            "---",
            "",
        ]
        atomic_write_text(messages / f"{next_seq:03d}-{provider}-web-response.md", "\n".join(front) + body.strip() + "\n")
