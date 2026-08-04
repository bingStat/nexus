from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SESSION = "nexus-council"
ROLES = ("architect", "reviewer", "implementer", "verifier")


class CouncilError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str, limit: int = 24) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return (value or "task")[:limit]


def run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise CouncilError(f"Command failed ({proc.returncode}): {shlex.join(cmd)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    return proc


def herdr(*args: str, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["herdr", "--session", SESSION, *args], timeout=timeout, check=check)


def herdr_json(*args: str, timeout: int = 120) -> dict[str, Any]:
    proc = herdr(*args, timeout=timeout)
    text = proc.stdout.strip()
    if not text:
        raise CouncilError(f"Herdr returned no JSON for: {' '.join(args)}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CouncilError(f"Invalid Herdr JSON: {text}\nstderr: {proc.stderr}") from exc


def ensure_server() -> None:
    status = herdr("status", "server", timeout=15, check=False)
    if status.returncode == 0 and "status: running" in status.stdout:
        return
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "Start-ScheduledTask -TaskName 'NexusHerdrCouncil'"], capture_output=True, text=True, timeout=30)
    for _ in range(20):
        time.sleep(0.5)
        status = herdr("status", "server", timeout=10, check=False)
        if status.returncode == 0 and "status: running" in status.stdout:
            return
    raise CouncilError("Herdr server did not become ready.")


def git(repo: Path, *args: str, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(repo), *args], timeout=timeout, check=check)


def validate_repo(repo: Path) -> Path:
    repo = repo.resolve()
    if not repo.exists():
        raise CouncilError(f"Repository does not exist: {repo}")
    return Path(git(repo, "rev-parse", "--show-toplevel").stdout.strip()).resolve()


def worktree_path(repo: Path, task_id: str, role: str) -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    return root / "Nexus" / "agent-council" / "worktrees" / repo.name / task_id / role


def room_path(repo: Path, task_id: str) -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    return root / "Nexus" / "agent-council" / "rooms" / repo.name / task_id


def ensure_worktree(repo: Path, task_id: str, role: str, *, writable: bool) -> Path:
    path = worktree_path(repo, task_id, role)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and (path / ".git").exists():
        return path
    if path.exists() and any(path.iterdir()):
        raise CouncilError(f"Worktree path exists and is not empty: {path}")
    if writable:
        branch = f"council/{task_id}/{role}"
        existing = git(repo, "branch", "--list", branch).stdout.strip()
        if existing:
            git(repo, "worktree", "add", str(path), branch)
        else:
            git(repo, "worktree", "add", "-b", branch, str(path), "HEAD")
    else:
        git(repo, "worktree", "add", "--detach", str(path), "HEAD")
    return path


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_message(room: Path, seq: int, sender: str, kind: str, body: str, reply_to: int | None = None) -> Path:
    path = room / "messages" / f"{seq:03d}-{sender}-{kind}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    front = ["---", f"id: {seq:03d}", f"from: {sender}", "to: orchestrator", f"type: {kind}", f"reply_to: {reply_to if reply_to is not None else 'null'}", "status: final", f"created_at: {now_iso()}", "---", ""]
    path.write_text("\n".join(front) + body.strip() + "\n", encoding="utf-8")
    return path


def create_workspace(path: Path, label: str) -> tuple[str, str]:
    result = herdr_json("workspace", "create", "--cwd", str(path), "--label", label, "--no-focus")["result"]
    return result["workspace"]["workspace_id"], result["root_pane"]["pane_id"]


def start_agent(name: str, kind: str, pane: str, role: str) -> None:
    return

def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def to_wsl_path(path: Path) -> str:
    proc = run(["wsl.exe", "--exec", "wslpath", "-a", str(path)], timeout=30)
    value = proc.stdout.strip().replace("\x00", "")
    if not value:
        raise CouncilError(f"Could not convert path for WSL: {path}")
    return value


def prompt_runtime(runtime: "RoleRuntime", prompt: str, timeout_seconds: int, room: Path, label: str) -> str:
    logs = room / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    prompt_path = logs / f"{label}-prompt.txt"
    output_path = logs / f"{label}-output.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    token = f"{int(time.time() * 1000)}-{runtime.role}"
    finish_marker = f"__COUNCIL_FINISHED_{token}__"
    status_path = logs / f"{label}-exit.txt"
    marker_cut = len(finish_marker) // 2
    marker_left, marker_right = finish_marker[:marker_cut], finish_marker[marker_cut:]
    marker_expr = f"({ps_quote(marker_left)}+{ps_quote(marker_right)})"
    utf8_expr = "(New-Object Text.UTF8Encoding($false))"
    agy_cmd = r"C:\Users\Bing\AppData\Local\agy\bin\agy.exe"
    codex_cmd = r"C:\nvm4w\nodejs\codex.cmd"
    if runtime.kind == "agy":
        minutes = max(1, (timeout_seconds + 59) // 60)
        command = (
            "$ErrorActionPreference='Continue'; "
            f"$p=Get-Content -Raw {ps_quote(str(prompt_path))}; "
            f"$r=& {ps_quote(agy_cmd)} -p $p --mode plan --sandbox --print-timeout {minutes}m 2>&1; "
            "$code=$LASTEXITCODE; "
            f"[IO.File]::WriteAllText({ps_quote(str(output_path))},($r -join [Environment]::NewLine),{utf8_expr}); "
            f"[IO.File]::WriteAllText({ps_quote(str(status_path))},[string]$code,{utf8_expr}); "
            f"Write-Output {marker_expr}"
        )
    else:
        hardening = "--ephemeral --ignore-user-config --ignore-rules "
        if runtime.role == "implementer":
            runner_path = logs / f"{label}-runner.sh"
            wsl_prompt = to_wsl_path(prompt_path)
            wsl_output = to_wsl_path(output_path)
            wsl_status = to_wsl_path(status_path)
            wsl_worktree = to_wsl_path(Path(runtime.path))
            wsl_runner = to_wsl_path(runner_path)
            runner = (
                "#!/bin/sh\n"
                "set +e\n"
                f"cat {shlex.quote(wsl_prompt)} | codex exec -C {shlex.quote(wsl_worktree)} "
                f"-s workspace-write {hardening}--color never -o {shlex.quote(wsl_output)} -\n"
                "code=$?\n"
                f"printf '%s' \"$code\" > {shlex.quote(wsl_status)}\n"
                f"printf '%s\n' {shlex.quote(finish_marker)}\n"
                "exit 0\n"
            )
            runner_path.write_text(runner, encoding="utf-8", newline="\n")
            command = f"wsl.exe --exec /bin/sh {ps_quote(wsl_runner)}"
        else:
            command = (
                "$ErrorActionPreference='Continue'; "
                f"Get-Content -Raw {ps_quote(str(prompt_path))} | "
                f"& {ps_quote(codex_cmd)} exec -C {ps_quote(runtime.path)} "
                f"-s read-only {hardening}--color never "
                f"-o {ps_quote(str(output_path))} -; "
                "$code=$LASTEXITCODE; "
                f"[IO.File]::WriteAllText({ps_quote(str(status_path))},[string]$code,{utf8_expr}); "
                f"Write-Output {marker_expr}"
            )
    herdr("pane", "run", runtime.pane_id, command, timeout=30)
    wait = herdr(
        "pane", "wait-output", runtime.pane_id, "--match", finish_marker,
        "--source", "recent-unwrapped", "--lines", "300", "--timeout", str(timeout_seconds * 1000),
        timeout=timeout_seconds + 30, check=False,
    )
    snapshot = herdr("pane", "read", runtime.pane_id, "--source", "recent-unwrapped", "--lines", "180", timeout=30, check=False)
    exit_text = status_path.read_text(encoding="utf-8-sig", errors="replace").strip() if status_path.exists() else "missing"
    if wait.returncode != 0 or exit_text != "0" or not output_path.exists():
        raise CouncilError(
            f"Role {runtime.role} failed or timed out.\nwait stdout:\n{wait.stdout}\nwait stderr:\n{wait.stderr}\n"
            f"pane:\n{snapshot.stdout}\n{snapshot.stderr}"
        )
    return output_path.read_text(encoding="utf-8-sig", errors="replace").strip()

def agent_name(role: str, task_id: str) -> str:
    return f"{role}-{slugify(task_id, 10)}"[:32]


@dataclass
class RoleRuntime:
    role: str
    kind: str
    path: str
    workspace_id: str
    pane_id: str
    agent_name: str


def initialize(repo: Path, task_id: str, task_text: str, discussion_only: bool) -> tuple[Path, dict[str, RoleRuntime]]:
    room = room_path(repo, task_id)
    for sub in ("messages", "decisions", "logs"):
        (room / sub).mkdir(parents=True, exist_ok=True)
    (room / "task.md").write_text(f"# Task\n\n{task_text.strip()}\n\n## Council protocol\n\nIndependent proposal -> cross-review -> verifier decision -> implementation -> review -> deterministic verification.\n", encoding="utf-8")
    runtimes: dict[str, RoleRuntime] = {}
    kinds = {"architect": "agy", "reviewer": "agy", "implementer": "codex", "verifier": "codex"}
    active_roles = ("architect", "reviewer", "verifier") if discussion_only else ROLES
    for role in active_roles:
        wt = ensure_worktree(repo, task_id, role, writable=(role == "implementer"))
        workspace_id, pane_id = create_workspace(wt, f"council-{task_id}-{role}")
        name = agent_name(role, task_id)
        runtimes[role] = RoleRuntime(role, kinds[role], str(wt), workspace_id, pane_id, name)
    write_json(room / "state.json", {"version": 1, "task_id": task_id, "repo": str(repo), "room": str(room), "status": "initialized", "discussion_only": discussion_only, "created_at": now_iso(), "roles": {k: asdict(v) for k, v in runtimes.items()}})
    return room, runtimes


def cleanup_success(repo: Path, room: Path, runtimes: dict[str, RoleRuntime], *, keep_implementer: bool) -> None:
    removed: list[str] = []
    closed: list[str] = []
    for role, runtime in runtimes.items():
        close = herdr("workspace", "close", runtime.workspace_id, timeout=30, check=False)
        if close.returncode == 0:
            closed.append(runtime.workspace_id)
        if keep_implementer and role == "implementer":
            continue
        path = Path(runtime.path)
        remove = git(repo, "worktree", "remove", "--force", str(path), timeout=120, check=False)
        if remove.returncode == 0:
            removed.append(str(path))
    git(repo, "worktree", "prune", timeout=60, check=False)
    state_path = room / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["cleanup"] = {"closed_workspaces": closed, "removed_worktrees": removed, "kept_implementer": keep_implementer, "completed_at": now_iso()}
    write_json(state_path, state)


def evidence_bundle(*paths: Path) -> str:
    sections: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        sections.append(f"===== {path.name} =====\n{text}")
    return "\n\n".join(sections)


def run_acceptance(worktree: Path, room: Path, commands: list[str], timeout_seconds: int) -> tuple[Path, bool]:
    results: list[dict[str, Any]] = []
    diff_check = git(worktree, "diff", "--cached", "--check", timeout=120, check=False)
    results.append({"name": "git-diff-check", "command": "git diff --cached --check", "exit_code": diff_check.returncode, "stdout": diff_check.stdout, "stderr": diff_check.stderr})
    changed = [line for line in git(worktree, "diff", "--cached", "--name-only").stdout.splitlines() if line.strip()]
    results.append({"name": "nonempty-staged-diff", "command": "git diff --cached --name-only", "exit_code": 0 if changed else 1, "stdout": "\n".join(changed), "stderr": "" if changed else "No staged changes were produced."})
    for index, command in enumerate(commands, start=1):
        proc = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], cwd=worktree, timeout=max(30, timeout_seconds), check=False)
        results.append({"name": f"accept-command-{index}", "command": command, "exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
    passed = all(item["exit_code"] == 0 for item in results)
    path = room / "logs" / "acceptance.json"
    write_json(path, {"passed": passed, "worktree": str(worktree), "results": results, "checked_at": now_iso()})
    return path, passed


def council_run(repo: Path, task_id: str, task_text: str, timeout_seconds: int, discussion_only: bool, acceptance_commands: list[str]) -> Path:
    ensure_server()
    room, roles = initialize(repo, task_id, task_text, discussion_only)
    task_file = room / "task.md"
    if acceptance_commands:
        with task_file.open("a", encoding="utf-8") as handle:
            handle.write("\n## Machine acceptance commands\n\n")
            for command in acceptance_commands:
                handle.write(f"- `{command}`\n")
    a1 = prompt_runtime(roles["architect"], f"You are the ARCHITECT in an Agent Council. Work read-only. Read {task_file}. Produce an independent implementation proposal covering architecture, affected files, failure modes, rollback, and acceptance tests. Do not modify source files. End with a clear recommended plan.", timeout_seconds, room, "01-architect-proposal")
    p1 = write_message(room, 1, "architect", "proposal", a1)
    r1 = prompt_runtime(roles["reviewer"], f"You are the REVIEWER in an Agent Council. Work read-only and independently. Read {task_file}. Produce a competing proposal, challenging likely assumptions. Cover correctness, security, operational risk, maintainability, and simpler alternatives. Do not modify source files.", timeout_seconds, room, "02-reviewer-proposal")
    p2 = write_message(room, 2, "reviewer", "proposal", r1)
    a2 = prompt_runtime(roles["architect"], f"Read {p2} and {p1}. Critique the competing proposal. List fatal issues, ordinary issues, unverified assumptions, and required changes. Do not edit source.", timeout_seconds, room, "03-architect-cross-review")
    p3 = write_message(room, 3, "architect", "cross-review", a2, 2)
    r2 = prompt_runtime(roles["reviewer"], f"Read {p1} and {p2}. Critique the architect proposal using the same categories. Do not edit source.", timeout_seconds, room, "04-reviewer-cross-review")
    p4 = write_message(room, 4, "reviewer", "cross-review", r2, 1)
    decision_evidence = evidence_bundle(task_file, p1, p2, p3, p4)
    decision_prompt = (
        "You are the independent VERIFIER and arbiter. The evidence below is complete and authoritative. "
        "Do not call tools, inspect the repository, or read other files. Score: Correctness 40%, "
        "Testability 20%, Operational risk 15%, Maintainability 15%, Complexity 10%. "
        "Write a final decision with selected approach, mandatory changes, machine-verifiable acceptance "
        "criteria, and rejection conditions. Do not modify source files.\n\n" + decision_evidence
    )
    decision = prompt_runtime(roles["verifier"], decision_prompt, timeout_seconds, room, "05-verifier-decision")
    decision_path = room / "decisions" / "final-decision.md"
    decision_path.write_text(decision.strip() + "\n", encoding="utf-8")
    state_path = room / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")); state.update({"status": "decision-complete", "decision": str(decision_path), "updated_at": now_iso()}); write_json(state_path, state)
    if discussion_only:
        cleanup_success(repo, room, roles, keep_implementer=False)
        return room
    implementer_path = Path(roles["implementer"].path)
    implementation_evidence = evidence_bundle(task_file, decision_path)
    implementation_prompt = (
        f"You are the IMPLEMENTER. Work only inside the assigned worktree {implementer_path}. "
        "Use tools to implement the selected approach and run relevant tests. Keep changes minimal and reversible. "
        "Do not commit, merge, push, or deploy. The task and decision below are complete; do not read files outside "
        "the worktree. Summarize files changed, tests, and remaining risks.\n\n" + implementation_evidence
    )
    implementation = prompt_runtime(roles["implementer"], implementation_prompt, timeout_seconds * 2, room, "06-implementer")
    p5 = write_message(room, 5, "implementer", "implementation-report", implementation)
    git(implementer_path, "add", "-A")
    diff_path = room / "logs" / "implementer.diff"; diff_path.write_text(git(implementer_path, "diff", "--cached", "--binary").stdout, encoding="utf-8")
    status_path = room / "logs" / "implementer-status.txt"; status_path.write_text(git(implementer_path, "status", "--short").stdout, encoding="utf-8")
    acceptance_path, machine_passed = run_acceptance(implementer_path, room, acceptance_commands, timeout_seconds)
    review_evidence = evidence_bundle(task_file, decision_path, p5, diff_path, status_path, acceptance_path)
    review = prompt_runtime(
        roles["reviewer"],
        "Review the complete evidence below without modifying files. Report blocking defects, non-blocking "
        "defects, requirement coverage, and readiness for deterministic verification.\n\n" + review_evidence,
        timeout_seconds, room, "07-reviewer-diff-review"
    )
    p6 = write_message(room, 6, "reviewer", "diff-review", review, 5)
    final_evidence = evidence_bundle(task_file, decision_path, diff_path, status_path, acceptance_path, p6)
    verification = prompt_runtime(
        roles["verifier"],
        "Independently verify only the complete evidence below. Do not call tools or inspect other files. "
        "Do not claim tests passed without captured evidence. Return ACCEPT, REVISE, or REJECT with reasons "
        "and exact next checks.\n\n" + final_evidence,
        timeout_seconds, room, "08-verifier-final"
    )
    p7 = write_message(room, 7, "verifier", "verification", verification, 6)
    verdict = verification.strip().splitlines()[0].strip().upper() if verification.strip() else "REJECT"
    accepted = machine_passed and verdict.startswith("ACCEPT")
    final_status = "accepted" if accepted else ("revision-required" if verdict.startswith("REVISE") else "rejected")
    state = json.loads(state_path.read_text(encoding="utf-8")); state.update({"status": final_status, "verdict": verdict, "machine_acceptance_passed": machine_passed, "artifacts": [str(p) for p in (p1,p2,p3,p4,p5,p6,p7,decision_path,diff_path,status_path,acceptance_path)], "updated_at": now_iso()}); write_json(state_path, state)
    cleanup_success(repo, room, roles, keep_implementer=True)
    if not accepted:
        raise CouncilError(f"Council did not accept the implementation: verdict={verdict}, machine_acceptance_passed={machine_passed}, room={room}")
    return room


def doctor() -> int:
    checks: dict[str, Any] = {"time": now_iso(), "session": SESSION}
    checks["python"] = sys.executable
    for cmd in ("herdr", "agy", "codex", "git"):
        proc = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", f"(Get-Command {cmd} -ErrorAction SilentlyContinue).Source"], timeout=20, check=False)
        checks[cmd] = proc.stdout.strip() or None
    status = herdr("status", "server", timeout=15, check=False)
    checks["herdr_server"] = {"returncode": status.returncode, "stdout": status.stdout.strip(), "stderr": status.stderr.strip()}
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if all(checks.get(x) for x in ("herdr","agy","codex","git","python")) and status.returncode == 0 else 1


def status(repo: Path, task_id: str) -> int:
    room = room_path(repo, task_id); state = room / "state.json"
    if not state.exists():
        print(json.dumps({"status": "not_found", "room": str(room)}, ensure_ascii=False)); return 2
    print(state.read_text(encoding="utf-8")); return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Nexus + Herdr Agent Council orchestrator")
    sub = parser.add_subparsers(dest="command", required=True); sub.add_parser("doctor")
    rp = sub.add_parser("run"); rp.add_argument("--repo", required=True); rp.add_argument("--task-id", required=True); rp.add_argument("--task", required=True); rp.add_argument("--timeout", type=int, default=600); rp.add_argument("--discussion-only", action="store_true"); rp.add_argument("--accept-command", action="append", default=[])
    sp = sub.add_parser("status"); sp.add_argument("--repo", required=True); sp.add_argument("--task-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "doctor": ensure_server(); return doctor()
        repo = validate_repo(Path(args.repo)); task_id = slugify(args.task_id)
        if args.command == "status": return status(repo, task_id)
        room = council_run(repo, task_id, args.task, args.timeout, args.discussion_only, args.accept_command); print(json.dumps({"status": "completed", "room": str(room)}, ensure_ascii=False)); return 0
    except (CouncilError, subprocess.TimeoutExpired, KeyError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
