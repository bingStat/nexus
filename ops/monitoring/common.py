from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
CONFIG_PATH = Path(os.getenv("NEXUS_OPS_CONFIG", "/etc/nexus/ops.json"))


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def load_config() -> dict[str, Any]:
    data = load_json(CONFIG_PATH, {})
    return data if isinstance(data, dict) else {}


def atomic_json(path: Path, payload: Any, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp = Path(handle.name)
    if os.name != "nt":
        os.chmod(temp, mode)
    os.replace(temp, path)


def api_key() -> str:
    direct = os.getenv("NEXUS_CHATGPT_API_KEY", "").strip()
    if direct:
        return direct
    for path in (Path("/etc/nexus-chatgpt-remote.env"), Path("/etc/nexus/ops.env")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("NEXUS_CHATGPT_API_KEY="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            continue
    return ""


def fetch_json(url: str, *, bearer: str = "", timeout: float = 15.0) -> Any:
    headers = {"Accept": "application/json", "User-Agent": "NexusOps/3.1"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
