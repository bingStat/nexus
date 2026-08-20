from __future__ import annotations

import json
import locale
import os
import platform
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from .common import Identity, json_dumps
from .devspace_runtime import DevSpaceRuntime
from .ledger import ExecutionLedger
from .ssh_fleet import sync_authorized_keys

VERSION = "3.2.0"


class SingleInstanceLock:
    """Cross-platform non-blocking file lock to prevent duplicate Agent processes."""

    def __init__(self, lock_file: Path):
        self.lock_file = lock_file
        self._fd: int | None = None
        self._locked = False

    def acquire(self) -> bool:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                import msvcrt

                flags = os.O_RDWR | os.O_CREAT
                self._fd = os.open(str(self.lock_file), flags)
                msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                self._fd = os.open(str(self.lock_file), os.O_RDWR | os.O_CREAT, 0o644)
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            os.ftruncate(self._fd, 0)
            os.lseek(self._fd, 0, os.SEEK_SET)
            os.write(self._fd, f"{os.getpid()}\n".encode("utf-8"))
            self._locked = True
            return True
        except (OSError, IOError):
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except Exception:
                    pass
                self._fd = None
            return False

    def release(self) -> None:
        if not self._locked or self._fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(self._fd, 0, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
        except Exception:
            pass
        finally:
            self._fd = None
            self._locked = False


def config_path() -> Path:
    return Path(os.getenv("NEXUS_V3_CONFIG", "/etc/nexus-agent/v3.json"))



def load_config() -> dict:
    with config_path().open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def request_json(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    body: bytes = b"",
    timeout: int = 20,
) -> tuple[int, dict | None]:
    response = requests.request(method, url, headers=headers or {}, data=body if body else None, timeout=timeout)
    if response.status_code == 204:
        return response.status_code, None
    payload = response.json() if response.text else {}
    return response.status_code, payload


def require_success(code: int, payload: dict | None, operation: str, expected: set[int]) -> None:
    if code in expected:
        return
    detail = payload.get("error") if isinstance(payload, dict) else None
    raise RuntimeError(f"{operation} failed: HTTP {code}: {detail or 'unexpected response'}")


def command_argv(command: str) -> list[str]:
    if os.name == "nt":
        shell = os.getenv("NEXUS_WINDOWS_SHELL", "powershell").strip().lower()
        if shell in {"cmd", "cmd.exe"}:
            return ["cmd.exe", "/d", "/s", "/c", command]
        return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
    return ["/bin/sh", "-c", command]


def decode_process_output(data: bytes | None) -> str:
    if not data:
        return ""
    encodings = ["utf-8", locale.getpreferredencoding(False)]
    if os.name == "nt":
        encodings.extend(["mbcs", "cp1252"])
    tried: set[str] = set()
    for encoding in encodings:
        normalized = encoding.lower()
        if normalized in tried:
            continue
        tried.add(normalized)
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def load_devspace_runtime(config: dict) -> tuple[DevSpaceRuntime | None, dict]:
    try:
        runtime = DevSpaceRuntime(config)
        info = runtime.info()
        return runtime, {
            "runtime": "devspace",
            "devspace_version": info.get("devspaceVersion"),
            "bridge_version": info.get("bridgeVersion"),
            "operations": info.get("operations") or [],
        }
    except Exception as exc:
        return None, {"runtime": "shell", "devspace_error": str(exc)[:200]}


def registration_with_capabilities(
    identity: Identity,
    device_id: str,
    hostname: str,
    platform_name: str,
    ssh_public_key: str,
    capabilities: dict,
) -> dict:
    payload = identity.registration_payload(device_id, hostname, platform_name, VERSION, ssh_public_key)
    payload["capabilities"] = capabilities
    return payload


def main() -> None:
    cfg_path = config_path()
    lock_file = cfg_path.parent / ".nexus-agent.lock"
    lock = SingleInstanceLock(lock_file)
    if not lock.acquire():
        print(
            json_dumps({
                "event": "agent.already_running",
                "message": "Another Nexus Agent instance is already running on this machine.",
            }),
            flush=True,
        )
        return

    devspace = None
    try:
        config = load_config()
        device_id = str(config["device_id"]).strip().lower()
        registry = str(config["registry_url"]).rstrip("/")
        broker = str(config["broker_url"]).rstrip("/")
        identity = Identity(Path(config.get("device_key", "/etc/nexus-agent/device.key")))
        agent_id = f"{device_id}:{socket.gethostname()}:{os.getpid()}"
        devspace, capabilities = load_devspace_runtime(config)
        ledger_path = Path(config.get("execution_ledger") or (cfg_path.parent / "execution-ledger.db"))
        ledger = ExecutionLedger(ledger_path)

        ssh_public_key = ""
        ssh_public_key_path = config.get("ssh_public_key")
        if ssh_public_key_path:
            path = Path(str(ssh_public_key_path))
            if path.exists():
                ssh_public_key = path.read_text(encoding="utf-8").strip()
        registration = registration_with_capabilities(
            identity,
            device_id,
            socket.gethostname(),
            platform.platform(),
            ssh_public_key,
            capabilities,
        )
        response = requests.post(f"{registry}/v3/devices/register", json=registration, timeout=20)
        registration_payload = response.json() if response.text else {}
        require_success(response.status_code, registration_payload, "device registration", {200, 201, 202})
        print(
            json_dumps(
                {
                    "event": "agent.registered",
                    "device_id": device_id,
                    "status": registration_payload.get("status", "unknown"),
                    "auth_key_hash": identity.key_id,
                    "runtime": capabilities.get("runtime"),
                    "devspace_version": capabilities.get("devspace_version"),
                }
            ),
            flush=True,
        )

        ssh_authorized_keys = str(config.get("ssh_authorized_keys") or "").strip()
        ssh_sync_interval = max(60, int(config.get("ssh_sync_interval") or 300))
        last_ssh_sync = 0.0

        def maybe_sync_ssh_keys(force: bool = False) -> None:
            nonlocal last_ssh_sync
            if not ssh_authorized_keys:
                return
            now = time.monotonic()
            if not force and now - last_ssh_sync < ssh_sync_interval:
                return
            last_ssh_sync = now
            try:
                changed, key_count = sync_authorized_keys(
                    registry,
                    ssh_authorized_keys,
                    timeout=min(20, int(config.get("request_timeout", 35))),
                )
                if force or changed:
                    print(
                        json_dumps(
                            {
                                "event": "agent.ssh_keys_synced",
                                "device_id": device_id,
                                "authorized_keys": ssh_authorized_keys,
                                "key_count": key_count,
                                "changed": changed,
                            }
                        ),
                        flush=True,
                    )
            except Exception as exc:
                print(
                    json_dumps(
                        {
                            "event": "agent.ssh_keys_sync_error",
                            "device_id": device_id,
                            "error": str(exc)[:500],
                        }
                    ),
                    flush=True,
                )

        maybe_sync_ssh_keys(force=True)

        while True:
            maybe_sync_ssh_keys()
            query = urlencode({"device_id": device_id, "agent_id": agent_id, "wait": int(config.get("wait_seconds", 20))})
            path = f"/v3/jobs/claim?{query}"
            headers = identity.auth_headers(device_id)
            try:
                code, job = request_json("GET", broker + path, headers=headers, timeout=int(config.get("request_timeout", 35)))
                if code == 204:
                    time.sleep(int(config.get("poll_seconds", 1)))
                    continue
                require_success(code, job, "job claim", {200})
                if not job:
                    raise RuntimeError("job claim returned an empty body")
                execute_and_complete(config, identity, device_id, broker, job, devspace, ledger)
            except Exception as exc:
                print(json_dumps({"event": "agent.error", "device_id": device_id, "error": str(exc)[:500]}), flush=True)
                time.sleep(5)
    finally:
        if devspace:
            devspace.close()
        lock.release()



def execute_job(job: dict, devspace: DevSpaceRuntime | None) -> tuple[str, int, str, dict]:
    operation = str(job.get("operation") or "shell.execute")
    input_data = job.get("input") if isinstance(job.get("input"), dict) else {}
    timeout = max(1, int(job.get("timeout_ms") or 30000) // 1000)

    if operation.startswith("workspace."):
        if not devspace:
            raise RuntimeError("target device does not have DevSpace runtime enabled")
        result = devspace.call(operation, input_data)
        return "completed", 0, json_dumps(result)[-20000:], result

    if operation != "shell.execute":
        raise RuntimeError(f"unsupported operation: {operation}")
    command = str(input_data.get("command") or job.get("command") or "")
    proc = subprocess.run(command_argv(command), text=False, capture_output=True, timeout=timeout)
    status = "completed" if proc.returncode == 0 else "failed"
    output = (decode_process_output(proc.stdout) + decode_process_output(proc.stderr))[-20000:]
    return status, proc.returncode, output, {"output": output, "exitCode": proc.returncode}


def execute_and_complete(
    config: dict,
    identity: Identity,
    device_id: str,
    broker: str,
    job: dict,
    devspace: DevSpaceRuntime | None = None,
    ledger: ExecutionLedger | None = None,
) -> None:
    timeout = max(1, int(job.get("timeout_ms") or 30000) // 1000)
    replay_state, cached = ledger.begin(job) if ledger else ("new", None)
    try:
        if replay_state == "terminal" and cached:
            status = str(cached["status"]); exit_code = int(cached.get("exit_code") or 0)
            output = str(cached.get("output") or ""); result = cached.get("result") or {}
        elif replay_state == "conflict":
            raise RuntimeError("duplicate job id conflicts with a different operation")
        elif replay_state == "uncertain":
            raise RuntimeError("duplicate execution suppressed because previous execution state is uncertain")
        else:
            status, exit_code, output, result = execute_job(job, devspace)
            if ledger:
                ledger.finish(str(job["id"]), status, exit_code, output, result)
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        exit_code = 124
        stdout = decode_process_output(exc.stdout) if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = decode_process_output(exc.stderr) if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        output = (stdout + stderr + f"\ncommand timed out after {timeout}s")[-20000:]
        result = {"error": output, "exitCode": exit_code}
    except Exception as exc:
        status = "failed"
        exit_code = 1
        output = str(exc)[-20000:]
        result = {"error": output}

    payload = {
        "id": job["id"],
        "status": status,
        "exit_code": exit_code,
        "output": output,
        "result": result,
    }
    body = json_dumps(payload).encode("utf-8")
    headers = identity.auth_headers(device_id)
    headers["Content-Type"] = "application/json"
    code, response_payload = request_json(
        "POST",
        f"{broker}/v3/jobs/complete",
        headers=headers,
        body=body,
        timeout=int(config.get("request_timeout", 20)),
    )
    require_success(code, response_payload, "job completion", {200})
    print(
        json_dumps(
            {
                "event": "agent.job_finished",
                "device_id": device_id,
                "job_id": job["id"],
                "operation": job.get("operation", "shell.execute"),
                "status": status,
                "exit_code": exit_code,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
