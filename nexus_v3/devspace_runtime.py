from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any


class DevSpaceUnavailable(RuntimeError):
    pass


class DevSpaceRuntime:
    """Long-lived JSONL adapter around the upstream @waishnav/devspace package.

    Nexus owns routing and device identity only. Workspace semantics, worktrees,
    file operations and interactive process sessions stay in upstream DevSpace.
    """

    def __init__(self, config: dict[str, Any]):
        runtime = dict(config.get("devspace") or {})
        bridge = runtime.get("bridge") or os.getenv("NEXUS_DEVSPACE_BRIDGE")
        if not bridge:
            raise DevSpaceUnavailable("DevSpace bridge is not configured")
        self.bridge = Path(str(bridge))
        if not self.bridge.is_file():
            raise DevSpaceUnavailable(f"DevSpace bridge not found: {self.bridge}")
        self.node = str(runtime.get("node") or os.getenv("NEXUS_NODE") or "node")
        self.allowed_roots = runtime.get("allowed_roots") or []
        self.state_dir = runtime.get("state_dir")
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    @classmethod
    def available(cls, config: dict[str, Any]) -> bool:
        try:
            runtime = cls(config)
            return runtime.info().get("devspaceVersion") is not None
        except Exception:
            return False

    def _start(self) -> subprocess.Popen[str]:
        if self._process and self._process.poll() is None:
            return self._process
        env = os.environ.copy()
        if self.allowed_roots:
            env["NEXUS_DEVSPACE_ALLOWED_ROOTS"] = os.pathsep.join(map(str, self.allowed_roots))
        if self.state_dir:
            env["NEXUS_DEVSPACE_STATE_DIR"] = str(self.state_dir)
        try:
            self._process = subprocess.Popen(
                [self.node, str(self.bridge)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=env,
            )
        except OSError as exc:
            raise DevSpaceUnavailable(f"failed to start DevSpace runtime: {exc}") from exc
        return self._process

    def call(self, operation: str, input_data: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            proc = self._start()
            if not proc.stdin or not proc.stdout:
                raise DevSpaceUnavailable("DevSpace bridge pipes are unavailable")
            request_id = uuid.uuid4().hex
            proc.stdin.write(json.dumps({"id": request_id, "operation": operation, "input": input_data or {}}, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
            if not line:
                stderr = proc.stderr.read()[-2000:] if proc.stderr else ""
                raise DevSpaceUnavailable(f"DevSpace bridge stopped unexpectedly: {stderr}")
            response = json.loads(line)
            if response.get("id") != request_id:
                raise DevSpaceUnavailable("DevSpace bridge response id mismatch")
            if not response.get("ok"):
                raise RuntimeError(str(response.get("error") or "DevSpace operation failed"))
            result = response.get("result")
            return result if isinstance(result, dict) else {"value": result}

    def info(self) -> dict[str, Any]:
        return self.call("runtime.info")

    def close(self) -> None:
        with self._lock:
            if self._process and self._process.poll() is None:
                self._process.terminate()
            self._process = None
