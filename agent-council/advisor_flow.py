from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import agent_browser
import task_ids


TASK_ROLE = "task"
CENTRAL_ROLES = ("user", "orchestrator", "synthesis")
ADVISOR_ROLES = ("advisor_prompt", "advisor_response")
TERMINAL_STATUSES = (
    "completed",
    "login_required",
    "human_verification_required",
    "rate_limited",
    "selector_changed",
    "timed_out",
    "failed",
    "CONTEXT_TOO_LARGE",
)
REPLAYABLE_TERMINAL_STATUSES = tuple(status for status in TERMINAL_STATUSES if status != "timed_out")


class AdvisorFlowError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{int(time.time() * 1000000)}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


class DirectoryLock:
    def __init__(self, path: Path, timeout: float = 15.0, stale_after: float = 120.0) -> None:
        self.path = path
        self.timeout = timeout
        self.stale_after = stale_after

    def __enter__(self) -> "DirectoryLock":
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                os.mkdir(self.path)
                atomic_write_json(self.path / "owner.json", {"pid": os.getpid(), "created_at": now_iso()})
                return self
            except FileExistsError:
                if self._is_stale():
                    self._clear()
                    continue
                if time.monotonic() >= deadline:
                    raise AdvisorFlowError(f"Timed out waiting for lock: {self.path}")
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
        except OSError:
            return


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def render_markdown(events: Iterable[dict[str, Any]]) -> str:
    parts = ["# Advisor Transcript", ""]
    for event in events:
        provider = event.get("provider") or "central"
        parts.extend(
            [
                f"## {int(event['sequence']):06d} {event['role']} {provider}",
                "",
                f"- utc_time: `{event['utc_time']}`",
                f"- sha256: `{event['sha256']}`",
                f"- idempotency_key: `{event.get('idempotency_key') or ''}`",
                "",
                "```text",
                str(event["body"]),
                "```",
                "",
            ]
        )
    return "\n".join(parts).rstrip() + "\n"


def regenerate_markdown(jsonl_path: Path, markdown_path: Path) -> None:
    atomic_write_text(markdown_path, render_markdown(read_jsonl(jsonl_path)))


class AdvisorFlow:
    def __init__(
        self,
        repo: Path,
        task_id: str,
        task_text: str = "",
        room: Path | None = None,
        adapter: Any | None = None,
        byte_limit: int = 200000,
        profile_root: Path | None = None,
    ) -> None:
        self.repo = Path(repo).resolve()
        self.task_id = task_ids.normalize_task_id(task_id)
        self.task_text = task_text.strip()
        self.room = Path(room).resolve() if room else self._default_room()
        self.advisor = self.room / "advisor"
        self.transcript_jsonl = self.advisor / "transcript.jsonl"
        self.transcript_md = self.advisor / "transcript.md"
        self.idempotency_dir = self.advisor / "idempotency"
        self.profile_root = profile_root or Path(os.environ.get("NEXUS_BROWSER_PROFILE_ROOT", r"F:\NexusBrowserProfiles"))
        profile_config = agent_browser.BrowserConfig(profile_root=self.profile_root)
        self.adapter = adapter or agent_browser.AgentBrowserAdapter(profile_config)
        self.byte_limit = byte_limit

    def append_central_event(self, role: str, body: str, idempotency_key: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if role not in CENTRAL_ROLES:
            raise AdvisorFlowError(f"Invalid central role: {role!r}")
        self._ensure()
        with DirectoryLock(self.advisor / ".lock"):
            return self._append_event(role=role, provider=None, body=body, idempotency_key=idempotency_key, metadata=metadata or {})

    def build_full_context(self, target_provider: str) -> str:
        self._ensure()
        if target_provider not in agent_browser.PROVIDERS:
            raise AdvisorFlowError(f"Invalid provider: {target_provider!r}")
        events = read_jsonl(self.transcript_jsonl)
        parts = [
            "NEXUS ADVISOR FULL_CONTEXT",
            "",
            "Rules:",
            "- You are an advisor to the normal ChatGPT conversation, which is the sole orchestrator.",
            "- Use the complete context below. Do not assume hidden context.",
            "- Preserve exact evidence; do not truncate or summarize quoted transcript content.",
            "",
            f"Task ID: {self.task_id}",
            f"Target provider: {target_provider}",
            "",
            "===== ORIGINAL_TASK =====",
            self.task_text,
            "",
            "===== CANONICAL_TRANSCRIPT_JSONL =====",
        ]
        parts.extend(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for event in events)
        parts.extend(["", "===== VERBATIM_EVENT_BODIES ====="])
        for event in events:
            provider = event.get("provider") or "central"
            parts.extend(
                [
                    "",
                    f"----- sequence={event['sequence']} role={event['role']} provider={provider} sha256={event['sha256']} -----",
                    str(event["body"]),
                ]
            )
        parts.extend(["", "===== END_FULL_CONTEXT =====", ""])
        return "\n".join(parts)

    def advisor_turn(
        self,
        *,
        current_user_message: str = "",
        orchestrator_message: str = "",
        synthesis: str = "",
        providers: list[str] | None = None,
        idempotency_key: str,
        byte_limit: int | None = None,
        timeout_seconds: int = 600,
    ) -> dict[str, Any]:
        providers = providers or list(agent_browser.PROVIDERS)
        for provider in providers:
            if provider not in agent_browser.PROVIDERS:
                raise AdvisorFlowError(f"Invalid provider: {provider!r}")
        limit = byte_limit if byte_limit is not None else self.byte_limit
        payload = {
            "task_id": self.task_id,
            "task_text": self.task_text,
            "current_user_message": current_user_message,
            "orchestrator_message": orchestrator_message,
            "synthesis": synthesis,
            "providers": providers,
        }
        payload_hash = sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        self._ensure()
        with DirectoryLock(self.advisor / ".lock"):
            existing = self._read_idempotency(idempotency_key)
            if existing and existing.get("payload_hash") != payload_hash:
                return {"status": "idempotency_conflict", "idempotency": "conflict", "idempotency_key": idempotency_key}
            if existing and existing.get("status") in REPLAYABLE_TERMINAL_STATUSES:
                replay = dict(existing.get("result", {}))
                replay["idempotency"] = "idempotent_replay"
                return replay
            if not existing:
                self._write_idempotency(
                    idempotency_key,
                    {
                        "payload_hash": payload_hash,
                        "status": "started",
                        "created_at": now_iso(),
                        "result": {"status": "started", "idempotency_key": idempotency_key},
                    },
                )
                if current_user_message:
                    self._append_event("user", None, current_user_message, idempotency_key, {"kind": "current_user_message"})
                if orchestrator_message:
                    self._append_event("orchestrator", None, orchestrator_message, idempotency_key, {"kind": "orchestrator_message"})
                if synthesis:
                    self._append_event("synthesis", None, synthesis, idempotency_key, {"kind": "synthesis"})

            provider_results: dict[str, Any] = {}
            overall = "completed"
            for provider in providers:
                prior = self._provider_result_for_key(provider, idempotency_key)
                if prior:
                    provider_results[provider] = prior
                    overall = self._combine_status(overall, str(prior["status"]))
                    continue
                prompt = self.build_full_context(provider)
                telemetry = self._context_telemetry(provider, prompt, limit)
                if telemetry["total_bytes"] > limit:
                    bundle_path = self.advisor / "context-too-large" / f"{self._safe_key(idempotency_key)}-{provider}.txt"
                    atomic_write_text(bundle_path, prompt)
                    result = {
                        "status": "CONTEXT_TOO_LARGE",
                        "idempotency": "recorded",
                        "idempotency_key": idempotency_key,
                        "telemetry": {**telemetry, "bundle_path": str(bundle_path)},
                        "providers": provider_results,
                    }
                    self._finish_idempotency(idempotency_key, payload_hash, result)
                    return result
                profile_path = agent_browser.AgentBrowserAdapter(
                    agent_browser.BrowserConfig(profile_root=self.profile_root)
                ).profile_path(self.task_id, provider)
                turn_metadata = self._provider_turn_metadata(existing, provider)
                if turn_metadata and turn_metadata.get("prompt_sent"):
                    provider_result = self.adapter.resume(provider, turn_metadata, timeout_seconds)
                else:
                    if not turn_metadata:
                        turn_metadata = self.adapter.new_turn_metadata(provider, self.task_id, idempotency_key, prompt, profile_path).to_dict()
                    self._update_provider_turn(idempotency_key, payload_hash, provider, turn_metadata)
                    self._append_event("advisor_prompt", provider, prompt, idempotency_key, telemetry)
                    provider_result = self.adapter.send(provider, prompt, profile_path, timeout_seconds, turn_metadata)
                data = provider_result.to_dict()
                provider_turn = data.get("metadata") or turn_metadata or {}
                if isinstance(provider_turn, dict):
                    provider_turn["response_state"] = provider_result.status
                    self._update_provider_turn(idempotency_key, payload_hash, provider, provider_turn)
                provider_results[provider] = data
                overall = self._combine_status(overall, provider_result.status)
                if provider_result.status == "completed":
                    self._append_event("advisor_response", provider, provider_result.response, idempotency_key, data.get("metadata") or {})

            result = {
                "status": overall,
                "idempotency": "recorded",
                "idempotency_key": idempotency_key,
                "providers": provider_results,
                "transcript_jsonl": str(self.transcript_jsonl),
                "transcript_markdown": str(self.transcript_md),
            }
            self._finish_idempotency(idempotency_key, payload_hash, result)
            return result

    def _default_room(self) -> Path:
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
        return root / "Nexus" / "agent-council" / "rooms" / self.repo.name / self.task_id

    def _ensure(self) -> None:
        self.advisor.mkdir(parents=True, exist_ok=True)
        self.idempotency_dir.mkdir(parents=True, exist_ok=True)
        with DirectoryLock(self.advisor / ".init-lock"):
            if not self.transcript_jsonl.exists():
                atomic_write_text(self.transcript_jsonl, "")
                regenerate_markdown(self.transcript_jsonl, self.transcript_md)

            events = read_jsonl(self.transcript_jsonl)
            task_events = [event for event in events if event.get("role") == TASK_ROLE]
            if len(task_events) > 1:
                raise AdvisorFlowError("Canonical transcript contains multiple original task events.")
            if task_events:
                persisted_task = str(task_events[0].get("body", ""))
                if self.task_text and persisted_task != self.task_text:
                    raise AdvisorFlowError("Original task conflicts with the canonical transcript.")
                if not self.task_text:
                    self.task_text = persisted_task
            elif self.task_text:
                self._append_event(
                    role=TASK_ROLE,
                    provider=None,
                    body=self.task_text,
                    idempotency_key="__original_task__",
                    metadata={"kind": "original_task"},
                )
            elif events:
                raise AdvisorFlowError("Canonical transcript is missing the original task event.")
            else:
                raise AdvisorFlowError("Original task is required for a new advisor room.")

            task_path = self.room / "task.md"
            expected_task_markdown = f"# Task\n\n{self.task_text}\n"
            if task_path.exists():
                existing_markdown = task_path.read_text(encoding="utf-8")
                if existing_markdown != expected_task_markdown:
                    raise AdvisorFlowError("task.md conflicts with the canonical original task.")
            else:
                atomic_write_text(task_path, expected_task_markdown)

    def _append_event(
        self,
        role: str,
        provider: str | None,
        body: str,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        events = read_jsonl(self.transcript_jsonl)
        event = {
            "sequence": len(events) + 1,
            "utc_time": now_iso(),
            "role": role,
            "provider": provider,
            "body": body,
            "sha256": sha256_text(body),
            "idempotency_key": idempotency_key,
            "metadata": metadata,
        }
        with self.transcript_jsonl.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        regenerate_markdown(self.transcript_jsonl, self.transcript_md)
        return event

    def _idempotency_path(self, key: str) -> Path:
        return self.idempotency_dir / f"{self._safe_key(key)}.json"

    def _safe_key(self, key: str) -> str:
        return "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in key).strip("-") or sha256_text(key)

    def _read_idempotency(self, key: str) -> dict[str, Any] | None:
        path = self._idempotency_path(key)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def _write_idempotency(self, key: str, data: dict[str, Any]) -> None:
        atomic_write_json(self._idempotency_path(key), data)

    def _finish_idempotency(self, key: str, payload_hash: str, result: dict[str, Any]) -> None:
        existing = self._read_idempotency(key) or {}
        self._write_idempotency(
            key,
            {
                "payload_hash": payload_hash,
                "status": result["status"],
                "created_at": existing.get("created_at", now_iso()),
                "updated_at": now_iso(),
                "provider_turns": existing.get("provider_turns", {}),
                "result": result,
            },
        )

    def _provider_result_for_key(self, provider: str, idempotency_key: str) -> dict[str, Any] | None:
        events = read_jsonl(self.transcript_jsonl)
        prompt_sent = any(
            event.get("role") == "advisor_prompt"
            and event.get("provider") == provider
            and event.get("idempotency_key") == idempotency_key
            for event in events
        )
        if not prompt_sent:
            return None
        for event in reversed(events):
            if (
                event.get("role") == "advisor_response"
                and event.get("provider") == provider
                and event.get("idempotency_key") == idempotency_key
            ):
                return {"status": "completed", "provider": provider, "response": event.get("body", ""), "metadata": event.get("metadata", {})}
        return None

    def _provider_turn_metadata(self, idempotency_record: dict[str, Any] | None, provider: str) -> dict[str, Any] | None:
        if not idempotency_record:
            return None
        turns = idempotency_record.get("provider_turns", {})
        turn = turns.get(provider) if isinstance(turns, dict) else None
        return dict(turn) if isinstance(turn, dict) else None

    def _update_provider_turn(self, key: str, payload_hash: str, provider: str, turn_metadata: dict[str, Any]) -> None:
        existing = self._read_idempotency(key) or {}
        provider_turns = dict(existing.get("provider_turns", {}))
        provider_turns[provider] = dict(turn_metadata)
        self._write_idempotency(
            key,
            {
                "payload_hash": payload_hash,
                "status": existing.get("status", "started"),
                "created_at": existing.get("created_at", now_iso()),
                "updated_at": now_iso(),
                "provider_turns": provider_turns,
                "result": existing.get("result", {"status": existing.get("status", "started"), "idempotency_key": key}),
            },
        )

    def _context_telemetry(self, provider: str, prompt: str, limit: int) -> dict[str, Any]:
        events = read_jsonl(self.transcript_jsonl)
        body_bytes = lambda value: len(str(value).encode("utf-8"))
        original_task_bytes = body_bytes(self.task_text)
        central_event_bytes = sum(body_bytes(event.get("body", "")) for event in events if event.get("role") in CENTRAL_ROLES)
        advisor_prompt_bytes = sum(body_bytes(event.get("body", "")) for event in events if event.get("role") == "advisor_prompt")
        advisor_response_bytes = sum(body_bytes(event.get("body", "")) for event in events if event.get("role") == "advisor_response")
        total_bytes = len(prompt.encode("utf-8"))
        structural_overhead_bytes = total_bytes - original_task_bytes - central_event_bytes - advisor_prompt_bytes - advisor_response_bytes
        return {
            "provider": provider,
            "total_bytes": total_bytes,
            "context_bytes": total_bytes,
            "limit": limit,
            "byte_limit": limit,
            "overflow": max(0, total_bytes - limit),
            "event_count": len(events),
            "original_task_bytes": original_task_bytes,
            "central_event_bytes": central_event_bytes,
            "advisor_prompt_bytes": advisor_prompt_bytes,
            "advisor_response_bytes": advisor_response_bytes,
            "structural_overhead_bytes": structural_overhead_bytes,
        }

    def _combine_status(self, current: str, incoming: str) -> str:
        if current == "completed":
            return incoming
        if incoming == "completed" or incoming == current:
            return current
        return "failed"


def parse_providers(value: str) -> list[str]:
    providers = [item.strip() for item in value.split(",") if item.strip()]
    return providers or list(agent_browser.PROVIDERS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nexus ChatGPT-centered advisor turn")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--task", default="")
    parser.add_argument("--current-user-message", default="")
    parser.add_argument("--orchestrator-message", default="")
    parser.add_argument("--synthesis", default="")
    parser.add_argument("--providers", default="claude,gemini")
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--byte-limit", type=int, default=200000)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)
    try:
        flow = AdvisorFlow(Path(args.repo), args.task_id, args.task, byte_limit=args.byte_limit)
        result = flow.advisor_turn(
            current_user_message=args.current_user_message,
            orchestrator_message=args.orchestrator_message,
            synthesis=args.synthesis,
            providers=parse_providers(args.providers),
            idempotency_key=args.idempotency_key,
            timeout_seconds=args.timeout,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0 if result.get("status") in {"completed", "CONTEXT_TOO_LARGE", "login_required", "human_verification_required", "rate_limited", "selector_changed", "timed_out"} else 1
    except (AdvisorFlowError, agent_browser.AgentBrowserError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
