from __future__ import annotations

import hashlib
import re

TASK_DIGEST_RE = re.compile(r"^task-[a-f0-9]+$")


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or "task"


def stable_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def normalize_task_id(task_id: str) -> str:
    value = str(task_id).strip()
    lowered = value.lower()
    if TASK_DIGEST_RE.fullmatch(lowered):
        return lowered
    digest = stable_hash(value)
    max_slug = 64 - len(digest) - 1
    return f"{_safe_slug(value)[:max_slug].rstrip('-') or 'task'}-{digest}"


def agent_task_token(task_id: str, limit: int = 24) -> str:
    normalized = normalize_task_id(task_id)
    if len(normalized) <= limit:
        return normalized
    digest = stable_hash(normalized, 10)
    prefix_len = max(1, limit - len(digest) - 1)
    return f"{normalized[:prefix_len].rstrip('-')}-{digest}"
