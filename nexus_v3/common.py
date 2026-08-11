from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

SIGNATURE_VERSION = "NEXUS-V3-ED25519"
REGISTRATION_VERSION = "NEXUS-V3-REGISTER"
UTC = timezone.utc


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_json(body: bytes) -> Any:
    return json.loads(body.decode("utf-8") or "{}")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def unb64url(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode("ascii"))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def public_key_id(public_key: Ed25519PublicKey) -> str:
    der = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    digest = hashes.Hash(hashes.SHA256())
    digest.update(der)
    return "sha256:" + digest.finalize().hex()


def canonical_http_message(method: str, path_and_query: str, timestamp: str, nonce: str, device_id: str, body: bytes) -> bytes:
    return "\n".join([
        SIGNATURE_VERSION,
        method.upper(),
        path_and_query or "/",
        timestamp,
        nonce,
        device_id,
        sha256_hex(body),
    ]).encode("utf-8")


def canonical_registration_message(payload_without_proof: dict[str, Any]) -> bytes:
    canonical = json_dumps(payload_without_proof).encode("utf-8")
    return (REGISTRATION_VERSION + "\n" + sha256_hex(canonical)).encode("utf-8")


def parse_utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PermissionError("invalid signature timestamp") from exc
    if parsed.tzinfo is None:
        raise PermissionError("signature timestamp must include timezone")
    return parsed.astimezone(UTC)


class Identity:
    def __init__(self, private_key_path: Path, public_key_path: Path):
        self.private_key_path = private_key_path
        self.public_key_path = public_key_path
        self.private_key = load_or_create_private_key(private_key_path, public_key_path)
        self.public_key_pem = public_key_path.read_text(encoding="ascii").strip()
        self.key_id = public_key_id(self.private_key.public_key())

    def sign_headers(self, device_id: str, method: str, url_or_path: str, body: bytes) -> dict[str, str]:
        timestamp = utc_now()
        nonce = b64url(secrets.token_bytes(16))
        path_query = path_and_query(url_or_path)
        signature = self.private_key.sign(canonical_http_message(method, path_query, timestamp, nonce, device_id, body))
        return {
            "X-Nexus-Device": device_id,
            "X-Nexus-Key-Id": self.key_id,
            "X-Nexus-Timestamp": timestamp,
            "X-Nexus-Nonce": nonce,
            "X-Nexus-Signature": b64url(signature),
        }

    def registration_payload(
        self,
        device_id: str,
        hostname: str,
        platform: str,
        agent_version: str,
        ssh_public_key: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "device_id": device_id,
            "public_key_ed25519": self.public_key_pem,
            "key_id": self.key_id,
            "hostname": hostname,
            "platform": platform,
            "agent_version": agent_version,
        }
        if ssh_public_key:
            payload["ssh_public_key"] = ssh_public_key.strip()
        payload["proof"] = b64url(self.private_key.sign(canonical_registration_message(payload)))
        return payload


def load_or_create_private_key(private_key_path: Path, public_key_path: Path) -> Ed25519PrivateKey:
    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    if private_key_path.exists():
        raw = private_key_path.read_bytes()
        try:
            key = serialization.load_pem_private_key(raw, password=None)
        except ValueError:
            key = serialization.load_ssh_private_key(raw, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise RuntimeError(f"identity key is not Ed25519: {private_key_path}")
        if not raw.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----"):
            private_key_path.write_bytes(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption(),
            ))
    else:
        key = Ed25519PrivateKey.generate()
        private_key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption(),
        ))
    if os.name != "nt":
        os.chmod(private_key_path.parent, 0o700)
        os.chmod(private_key_path, 0o600)
    public_key = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH,
    )
    public_key_path.write_bytes(public_key + b"\n")
    if os.name != "nt":
        os.chmod(public_key_path, 0o644)
    return key


def load_public_key(public_key_pem: str) -> Ed25519PublicKey:
    raw = public_key_pem.strip().encode("ascii")
    try:
        key = serialization.load_pem_public_key(raw)
    except ValueError:
        key = serialization.load_ssh_public_key(raw)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("public key is not Ed25519")
    return key


def path_and_query(url_or_path: str) -> str:
    parsed = urlsplit(url_or_path)
    if parsed.scheme or parsed.netloc:
        return parsed.path + (f"?{parsed.query}" if parsed.query else "") or "/"
    return url_or_path or "/"


def verify_registration_payload(payload: dict[str, Any]) -> None:
    proof = str(payload.get("proof") or "")
    without = {key: payload[key] for key in sorted(payload) if key != "proof"}
    public_key = load_public_key(str(payload["public_key_ed25519"]))
    if public_key_id(public_key) != str(payload.get("key_id")):
        raise PermissionError("key_id does not match public key")
    try:
        public_key.verify(unb64url(proof), canonical_registration_message(without))
    except InvalidSignature as exc:
        raise PermissionError("registration proof is invalid") from exc


def verify_http_signature(
    public_key_pem: str,
    headers: dict[str, str],
    method: str,
    path_query: str,
    body: bytes,
    *,
    max_clock_skew_seconds: int = 300,
) -> str:
    device_id = str(headers.get("X-Nexus-Device") or "").strip().lower()
    key_id = str(headers.get("X-Nexus-Key-Id") or "").strip()
    timestamp = str(headers.get("X-Nexus-Timestamp") or "").strip()
    nonce = str(headers.get("X-Nexus-Nonce") or "").strip()
    signature = str(headers.get("X-Nexus-Signature") or "").strip()
    if not all([device_id, key_id, timestamp, nonce, signature]):
        raise PermissionError("missing signature headers")
    signed_at = parse_utc_timestamp(timestamp)
    skew = abs((datetime.now(UTC) - signed_at).total_seconds())
    if skew > max_clock_skew_seconds:
        raise PermissionError("signature timestamp outside allowed window")
    public_key = load_public_key(public_key_pem)
    if public_key_id(public_key) != key_id:
        raise PermissionError("key_id mismatch")
    try:
        public_key.verify(unb64url(signature), canonical_http_message(method, path_query, timestamp, nonce, device_id, body))
    except InvalidSignature as exc:
        raise PermissionError("signature invalid") from exc
    return device_id
