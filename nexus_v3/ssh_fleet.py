from __future__ import annotations

import os
from pathlib import Path

import requests


BEGIN_MARKER = "### BEGIN NEXUS MANAGED SSH KEYS"
END_MARKER = "### END NEXUS MANAGED SSH KEYS"


def _strip_managed_block(text: str) -> str:
    output: list[str] = []
    skipping = False
    for line in text.splitlines():
        if line == BEGIN_MARKER:
            skipping = True
            continue
        if line == END_MARKER:
            skipping = False
            continue
        if not skipping:
            output.append(line)
    return "\n".join(output).strip()


def _normalize_keys(text: str) -> list[str]:
    keys: list[str] = []
    seen: set[tuple[str, str]] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 2 or parts[0] not in {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256"}:
            continue
        fingerprint = (parts[0], parts[1])
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        keys.append(line)
    return keys


def render_authorized_keys(existing: str, fleet_keys: str) -> tuple[str, int]:
    unmanaged = _strip_managed_block(existing)
    keys = _normalize_keys(fleet_keys)
    chunks: list[str] = []
    if unmanaged:
        chunks.append(unmanaged)
    chunks.append(BEGIN_MARKER)
    chunks.extend(keys)
    chunks.append(END_MARKER)
    return "\n".join(chunks) + "\n", len(keys)


def _prepare_posix_parent(path: Path) -> tuple[int, int] | None:
    if os.name == "nt":
        path.parent.mkdir(parents=True, exist_ok=True)
        return None

    home = path.parent.parent
    owner = None
    if home.exists():
        stat = home.stat()
        owner = (stat.st_uid, stat.st_gid)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if owner and os.geteuid() == 0:
        os.chown(path.parent, owner[0], owner[1])
    return owner


def write_authorized_keys(path: Path, fleet_keys: str) -> tuple[bool, int]:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    rendered, count = render_authorized_keys(existing, fleet_keys)
    if rendered == existing:
        return False, count

    owner = _prepare_posix_parent(path)
    temp = path.with_name(f".{path.name}.nexus-{os.getpid()}.tmp")
    try:
        temp.write_text(rendered, encoding="utf-8")
        if os.name != "nt":
            os.chmod(temp, 0o600)
            if owner and os.geteuid() == 0:
                os.chown(temp, owner[0], owner[1])
        os.replace(temp, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
        return True, count
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


def sync_authorized_keys(registry_url: str, authorized_keys_path: str, timeout: int = 15) -> tuple[bool, int]:
    response = requests.get(f"{registry_url.rstrip('/')}/v3/ssh/authorized-keys", timeout=timeout)
    response.raise_for_status()
    return write_authorized_keys(Path(authorized_keys_path), response.text)
