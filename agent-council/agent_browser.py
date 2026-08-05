from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


PROVIDERS = ("claude", "gemini")
PROVIDER_URLS = {
    "claude": "https://claude.ai/",
    "gemini": "https://gemini.google.com/",
}
STATUSES = (
    "completed",
    "login_required",
    "human_verification_required",
    "rate_limited",
    "selector_changed",
    "timed_out",
    "failed",
)

DEFAULT_SELECTORS: dict[str, dict[str, Any]] = {
    "claude": {
        "composer": ["div[contenteditable='true']", "textarea"],
        "send": ["button[aria-label*='Send']", "button[type='submit']"],
        "response": ["div[data-testid*='message']", "article"],
        "aria_fallbacks": {
            "composer_roles": ["textbox"],
            "send_names": ["Send", "Submit"],
        },
    },
    "gemini": {
        "composer": ["rich-textarea div[contenteditable='true']", "textarea"],
        "send": ["button[aria-label*='Send']", "button[aria-label*='Submit']"],
        "response": ["message-content", "model-response", "article"],
        "aria_fallbacks": {
            "composer_roles": ["textbox"],
            "send_names": ["Send", "Submit"],
        },
    },
}


class AgentBrowserError(RuntimeError):
    pass


def resolve_browser_command() -> str:
    configured = os.environ.get("NEXUS_AGENT_BROWSER_COMMAND", "").strip()
    if configured:
        return configured
    if os.name == "nt":
        wrappers = [
            shutil.which("agent-browser.exe"),
            shutil.which("agent-browser.cmd"),
            shutil.which("agent-browser.ps1"),
            shutil.which("agent-browser"),
        ]
        for wrapper in wrappers:
            if not wrapper:
                continue
            path = Path(wrapper)
            if path.suffix.lower() == ".exe":
                return str(path)
            binary = path.parent / "node_modules" / "agent-browser" / "bin" / "agent-browser-win32-x64.exe"
            if binary.is_file():
                return str(binary)
        raise AgentBrowserError(
            "Could not resolve the native agent-browser executable. "
            "Install agent-browser or set NEXUS_AGENT_BROWSER_COMMAND to its native executable path."
        )
    resolved = shutil.which("agent-browser")
    if resolved:
        return resolved
    raise AgentBrowserError("Could not resolve agent-browser on PATH.")


@dataclass(frozen=True)
class BrowserConfig:
    profile_root: Path = Path(os.environ.get("NEXUS_BROWSER_PROFILE_ROOT", r"F:\NexusBrowserProfiles"))
    worktree_root: Path = Path(os.environ.get("NEXUS_COUNCIL_WORKTREE_ROOT", r"F:\NexusCouncilWorktrees"))
    selector_registry: Path | None = None
    browser_command: str | tuple[str, ...] = field(default_factory=resolve_browser_command)
    headed: bool = True
    poll_interval_seconds: float = 2.0
    stable_polls: int = 2
    command_timeout_seconds: int = 45
    extra_env: Mapping[str, str] | None = None


@dataclass
class ProviderResult:
    status: str
    provider: str
    response: str = ""
    error: str = ""
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise AgentBrowserError(f"Invalid provider status: {self.status!r}")
        if self.provider not in PROVIDERS:
            raise AgentBrowserError(f"Invalid provider: {self.provider!r}")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = self.metadata or {}
        return data


@dataclass
class ProviderTurnMetadata:
    provider: str
    task_scope: str
    idempotency_key: str
    prompt_hash: str
    session_name: str
    profile_path: str
    prompt_sent: bool = False
    response_state: str = "not_started"
    conversation_url: str = ""
    baseline_count: int = 0
    baseline_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProviderTurnMetadata":
        return cls(
            provider=str(data["provider"]),
            task_scope=str(data["task_scope"]),
            idempotency_key=str(data["idempotency_key"]),
            prompt_hash=str(data["prompt_hash"]),
            session_name=str(data["session_name"]),
            profile_path=str(data["profile_path"]),
            prompt_sent=bool(data.get("prompt_sent", False)),
            response_state=str(data.get("response_state", "not_started")),
            conversation_url=str(data.get("conversation_url", "")),
            baseline_count=int(data.get("baseline_count", 0) or 0),
            baseline_fingerprint=str(data.get("baseline_fingerprint", "")),
        )


class AgentBrowserAdapter:
    """Provider-neutral browser boundary for Claude/Gemini web advisors."""

    def __init__(self, config: BrowserConfig | None = None) -> None:
        self.config = config or BrowserConfig()
        self._selectors = self._load_selectors()

    def provider_url(self, provider: str) -> str:
        self._validate_provider(provider)
        return PROVIDER_URLS[provider]

    def profile_path(self, task_or_room_id: str, provider: str) -> Path:
        self._validate_provider(provider)
        safe_scope = self.safe_name(task_or_room_id, "task")
        return Path(self.config.profile_root) / safe_scope / provider

    def session_name(self, task_or_room_id: str, provider: str) -> str:
        self._validate_provider(provider)
        return f"nexus-{self.safe_name(task_or_room_id, 'task')}-{provider}"

    def new_turn_metadata(self, provider: str, task_or_room_id: str, idempotency_key: str, prompt: str, profile_path: Path | None = None) -> ProviderTurnMetadata:
        self._validate_provider(provider)
        profile = profile_path or self.profile_path(task_or_room_id, provider)
        return ProviderTurnMetadata(
            provider=provider,
            task_scope=self.safe_name(task_or_room_id, "task"),
            idempotency_key=idempotency_key,
            prompt_hash=self._sha256(prompt),
            session_name=self.session_name(task_or_room_id, provider),
            profile_path=str(profile),
        )

    def selectors_for(self, provider: str) -> dict[str, Any]:
        self._validate_provider(provider)
        return dict(self._selectors[provider])

    def send(
        self,
        provider: str,
        prompt: str,
        profile_path: Path,
        timeout_seconds: int,
        turn_metadata: ProviderTurnMetadata | Mapping[str, Any] | None = None,
    ) -> ProviderResult:
        self._validate_provider(provider)
        profile_path.mkdir(parents=True, exist_ok=True)
        metadata = self._coerce_metadata(provider, prompt, profile_path, turn_metadata)
        if metadata.prompt_sent:
            return self.resume(provider, metadata, timeout_seconds)

        self._open_provider(provider, metadata)
        page_state = self._classify(provider, metadata)
        if page_state["status"] != "ready":
            return self._state_result(provider, page_state, metadata)

        baseline = self._baseline(provider, metadata)
        metadata.baseline_count = int(baseline.get("count", 0) or 0)
        metadata.baseline_fingerprint = str(baseline.get("fingerprint", ""))
        metadata.conversation_url = str(baseline.get("url", "") or metadata.conversation_url)

        sent = self._send_prompt(provider, prompt, metadata)
        if sent.get("status") != "sent":
            return self._state_result(provider, sent, metadata)
        metadata.prompt_sent = True
        metadata.conversation_url = str(sent.get("url", "") or metadata.conversation_url)
        result = self._wait_for_response(provider, metadata, timeout_seconds)
        if result.status == "completed":
            metadata.response_state = "completed"
        return result

    def resume(
        self,
        provider: str,
        turn_metadata: ProviderTurnMetadata | Mapping[str, Any],
        timeout_seconds: int,
    ) -> ProviderResult:
        self._validate_provider(provider)
        if isinstance(turn_metadata, Mapping):
            metadata = ProviderTurnMetadata.from_dict(turn_metadata)
        else:
            metadata = turn_metadata
        Path(metadata.profile_path).mkdir(parents=True, exist_ok=True)
        self._open_provider(provider, metadata, prefer_url=metadata.conversation_url or self.provider_url(provider))
        page_state = self._classify(provider, metadata)
        if page_state["status"] != "ready":
            return self._state_result(provider, page_state, metadata)
        result = self._wait_for_response(provider, metadata, timeout_seconds)
        if result.status == "completed":
            metadata.response_state = "completed"
        return result

    def _load_selectors(self) -> dict[str, dict[str, Any]]:
        path = self.config.selector_registry
        if path and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return self._validate_selectors(data)
        local = Path(__file__).with_name("selectors.json")
        if local.exists():
            data = json.loads(local.read_text(encoding="utf-8"))
            return self._validate_selectors(data)
        return self._validate_selectors(DEFAULT_SELECTORS)

    def _validate_selectors(self, data: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for provider in PROVIDERS:
            entry = data.get(provider)
            if not isinstance(entry, dict) or "aria_fallbacks" not in entry:
                raise AgentBrowserError(f"Selector registry missing accessibility fallbacks for {provider}.")
            result[provider] = entry
        return result

    def _validate_provider(self, provider: str) -> None:
        if provider not in PROVIDERS:
            raise AgentBrowserError(f"Invalid provider {provider!r}; expected one of: {', '.join(PROVIDERS)}")

    def _open_provider(self, provider: str, metadata: ProviderTurnMetadata, prefer_url: str | None = None) -> None:
        self._run(metadata, ["open", prefer_url or self.provider_url(provider)], timeout=self.config.command_timeout_seconds)
        self._run(metadata, ["wait", "--load", "domcontentloaded"], timeout=min(self.config.command_timeout_seconds, 20), check=False)

    def _classify(self, provider: str, metadata: ProviderTurnMetadata) -> dict[str, Any]:
        return self._eval_json(metadata, self._classification_js(provider), timeout=self.config.command_timeout_seconds)

    def _baseline(self, provider: str, metadata: ProviderTurnMetadata) -> dict[str, Any]:
        return self._eval_json(metadata, self._baseline_js(self.selectors_for(provider)), timeout=self.config.command_timeout_seconds)

    def _send_prompt(self, provider: str, prompt: str, metadata: ProviderTurnMetadata) -> dict[str, Any]:
        payload = json.dumps({"prompt": prompt, "selectors": self.selectors_for(provider)}, ensure_ascii=False)
        return self._eval_json(metadata, self._send_js(payload), timeout=self.config.command_timeout_seconds)

    def _wait_for_response(self, provider: str, metadata: ProviderTurnMetadata, timeout_seconds: int) -> ProviderResult:
        deadline = time_monotonic() + max(1, timeout_seconds)
        last_text = ""
        stable = 0
        last_state: dict[str, Any] = {}
        while time_monotonic() < deadline:
            state = self._classify(provider, metadata)
            if state["status"] != "ready":
                return self._state_result(provider, state, metadata)
            current = self._eval_json(metadata, self._extract_js(provider, metadata), timeout=self.config.command_timeout_seconds)
            last_state = current
            status = str(current.get("status", "pending"))
            if status == "selector_changed":
                return self._state_result(provider, current, metadata)
            text = str(current.get("response", ""))
            if status == "completed" and text:
                if text == last_text:
                    stable += 1
                else:
                    stable = 1
                    last_text = text
                if stable >= self.config.stable_polls:
                    metadata.conversation_url = str(current.get("url", "") or metadata.conversation_url)
                    return ProviderResult("completed", provider, response=text, metadata=metadata.to_dict())
            self._sleep()
        return ProviderResult(
            "timed_out",
            provider,
            error="Timed out waiting for a stable visible assistant response.",
            metadata={**metadata.to_dict(), "last_response_bytes": len(str(last_state.get("response", "")).encode("utf-8"))},
        )

    def _state_result(self, provider: str, state: Mapping[str, Any], metadata: ProviderTurnMetadata) -> ProviderResult:
        status = str(state.get("status", "failed"))
        if status == "ready":
            status = "failed"
        if status not in STATUSES:
            status = "failed"
        return ProviderResult(status=status, provider=provider, error=str(state.get("error", "")), metadata={**metadata.to_dict(), "page_state": dict(state)})

    def _run(self, metadata: ProviderTurnMetadata, args: list[str], *, input_text: str | None = None, timeout: int, check: bool = True) -> subprocess.CompletedProcess[str]:
        base = [
            *self._browser_command_args(),
            "--session",
            metadata.session_name,
            "--profile",
            metadata.profile_path,
            "--restore",
            "--restore-save",
            "auto",
            "--allowed-domains",
            "claude.ai,*.claude.ai,anthropic.com,*.anthropic.com,gemini.google.com,*.gemini.google.com,accounts.google.com",
            "--json",
        ]
        if self.config.headed:
            base.append("--headed")
        env = os.environ.copy()
        if self.config.extra_env:
            env.update(dict(self.config.extra_env))
        try:
            proc = subprocess.run(
                [*base, *args],
                input=input_text if input_text is not None else "",
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
                shell=False,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AgentBrowserError(f"agent-browser command failed: {shlex.join([*base, *args])}: {exc}") from exc
        if check and proc.returncode != 0:
            raise AgentBrowserError(f"agent-browser command failed ({proc.returncode}): {shlex.join([*base, *args])}: {proc.stderr.strip()}")
        return proc

    def _browser_command_args(self) -> list[str]:
        if isinstance(self.config.browser_command, str):
            return shlex.split(self.config.browser_command, posix=(os.name != "nt"))
        return list(self.config.browser_command)

    def _eval_json(self, metadata: ProviderTurnMetadata, script: str, *, timeout: int) -> dict[str, Any]:
        proc = self._run(metadata, ["eval", "--stdin"], input_text=script, timeout=timeout)
        return self._parse_json_value(proc.stdout)

    def _parse_json_value(self, text: str) -> dict[str, Any]:
        raw = text.strip()
        if not raw:
            return {"status": "failed", "error": "agent-browser returned empty JSON output"}
        try:
            data: Any = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start < 0 or end < start:
                return {"status": "failed", "error": "agent-browser returned non-JSON output"}
            data = json.loads(raw[start : end + 1])
        if isinstance(data, dict) and "value" in data:
            value = data["value"]
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    return {"status": "failed", "error": value}
            if isinstance(value, dict):
                return value
        if isinstance(data, dict):
            return data
        return {"status": "failed", "error": "agent-browser returned unexpected JSON shape"}

    def _coerce_metadata(
        self,
        provider: str,
        prompt: str,
        profile_path: Path,
        turn_metadata: ProviderTurnMetadata | Mapping[str, Any] | None,
    ) -> ProviderTurnMetadata:
        if isinstance(turn_metadata, ProviderTurnMetadata):
            return turn_metadata
        if isinstance(turn_metadata, Mapping):
            return ProviderTurnMetadata.from_dict(turn_metadata)
        return ProviderTurnMetadata(
            provider=provider,
            task_scope=profile_path.parent.name,
            idempotency_key="",
            prompt_hash=self._sha256(prompt) if prompt else "",
            session_name=f"nexus-{profile_path.parent.name}-{provider}",
            profile_path=str(profile_path),
        )

    def _classification_js(self, provider: str) -> str:
        return f"""
(() => {{
  const __nexus_classify_page = true;
  const provider = {json.dumps(provider)};
  const visibleText = (document.body && document.body.innerText || '').replace(/\\s+/g, ' ').trim();
  const url = location.href;
  const title = document.title || '';
  const lower = (visibleText + ' ' + url + ' ' + title).toLowerCase();
  const has = (patterns) => patterns.some((p) => lower.includes(p));
  if (has(['verify you are human', 'captcha', 'turnstile', 'checking your browser', 'human verification'])) return {{status:'human_verification_required', url, title}};
  if (has(['too many requests', 'rate limit', 'try again later', 'temporarily unavailable', 'unusual traffic'])) return {{status:'rate_limited', url, title}};
  if (provider === 'claude' && has(['sign in', 'log in', 'continue with google']) && !has(['new chat', 'message claude'])) return {{status:'login_required', url, title}};
  if (provider === 'gemini' && has(['sign in', 'log in', 'use gemini with your google account']) && !has(['enter a prompt', 'ask gemini'])) return {{status:'login_required', url, title}};
  return {{status:'ready', url, title}};
}})()
"""

    def _baseline_js(self, selectors: Mapping[str, Any]) -> str:
        payload = json.dumps(selectors, ensure_ascii=False)
        return f"""
(() => {{
  const __nexus_baseline = true;
  const selectors = {payload};
  const visible = (el) => !!el && el.offsetParent !== null && getComputedStyle(el).visibility !== 'hidden';
  const text = (el) => (el.innerText || el.textContent || '').trim();
  const responses = [];
  for (const sel of (selectors.response || [])) {{
    for (const el of document.querySelectorAll(sel)) {{
      const value = text(el);
      if (visible(el) && value) responses.push(value);
    }}
  }}
  const last = responses.length ? responses[responses.length - 1] : '';
  return {{status:'ready', count: responses.length, fingerprint: String(responses.length) + ':' + last.length + ':' + last.slice(0,64) + ':' + last.slice(-64), url: location.href}};
}})()
"""

    def _send_js(self, payload: str) -> str:
        return f"""
(() => {{
  const __nexus_send_prompt = true;
  const payload = {payload};
  const prompt = payload.prompt;
  const selectors = payload.selectors || {{}};
  const visible = (el) => !!el && el.offsetParent !== null && getComputedStyle(el).visibility !== 'hidden';
  const bySelectors = (items) => {{
    for (const sel of (items || [])) {{
      const matches = Array.from(document.querySelectorAll(sel)).filter(visible);
      if (matches[0]) return matches[0];
    }}
    return null;
  }};
  const roleTextbox = () => Array.from(document.querySelectorAll('[role="textbox"], textarea, [contenteditable="true"]')).filter(visible)[0] || null;
  const composer = bySelectors(selectors.composer) || roleTextbox();
  if (!composer) return {{status:'selector_changed', error:'composer_not_found', url: location.href}};
  composer.focus();
  if ('value' in composer) {{
    composer.value = prompt;
    composer.dispatchEvent(new InputEvent('input', {{bubbles:true, inputType:'insertText', data: prompt}}));
    composer.dispatchEvent(new Event('change', {{bubbles:true}}));
  }} else {{
    composer.textContent = prompt;
    composer.dispatchEvent(new InputEvent('input', {{bubbles:true, inputType:'insertText', data: prompt}}));
  }}
  const namedButton = () => Array.from(document.querySelectorAll('button,[role="button"]')).filter(visible).find((el) => /send|submit|arrow_upward/i.test(el.getAttribute('aria-label') || el.innerText || '')) || null;
  const send = bySelectors(selectors.send) || namedButton();
  if (!send) return {{status:'selector_changed', error:'send_not_found', url: location.href}};
  if (send.disabled || send.getAttribute('aria-disabled') === 'true') return {{status:'selector_changed', error:'send_disabled', url: location.href}};
  send.click();
  return {{status:'sent', url: location.href}};
}})()
"""

    def _extract_js(self, provider: str, metadata: ProviderTurnMetadata) -> str:
        payload = json.dumps({"selectors": self.selectors_for(provider), "baseline_count": metadata.baseline_count, "baseline_fingerprint": metadata.baseline_fingerprint}, ensure_ascii=False)
        return f"""
(() => {{
  const __nexus_extract_response = true;
  const payload = {payload};
  const selectors = payload.selectors || {{}};
  const visible = (el) => !!el && el.offsetParent !== null && getComputedStyle(el).visibility !== 'hidden';
  const text = (el) => (el.innerText || el.textContent || '').trim();
  const responses = [];
  for (const sel of (selectors.response || [])) {{
    for (const el of document.querySelectorAll(sel)) {{
      const value = text(el);
      if (visible(el) && value) responses.push(value);
    }}
  }}
  if (!responses.length) return {{status:'selector_changed', error:'response_not_found', url: location.href}};
  const count = responses.length;
  const last = responses[count - 1];
  const fingerprint = String(count) + ':' + last.length + ':' + last.slice(0,64) + ':' + last.slice(-64);
  const response = count > payload.baseline_count || fingerprint !== payload.baseline_fingerprint ? last : '';
  const busy = Array.from(document.querySelectorAll('button,[role="button"]')).some((el) => visible(el) && /stop|cancel/i.test(el.getAttribute('aria-label') || el.innerText || ''));
  return {{status: response && !busy ? 'completed' : 'pending', response, count, fingerprint, url: location.href}};
}})()
"""

    def _sleep(self) -> None:
        import time

        time.sleep(max(0.1, self.config.poll_interval_seconds))

    @staticmethod
    def safe_name(value: str, fallback: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
        return safe or fallback

    @staticmethod
    def _sha256(text: str) -> str:
        import hashlib

        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def time_monotonic() -> float:
    import time

    return time.monotonic()
