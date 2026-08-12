from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLISH_MAP = {
    "README.md": "README.md",
    "dashboard/index.html": "index.html",
    "install.sh": "install.sh",
    "install.ps1": "install.ps1",
    "agent-council/integrations/nexus-v3-chatgpt-remote-prompt.md": "nexus-v3-chatgpt-remote-prompt.md",
    "agent-council/integrations/nexus-v3-remote-control-openapi.json": "nexus-v3-remote-control-openapi.json",
    "AGENTS.md": "AGENTS.md",
    "NEXUS_CHATGPT_PROMPT.md": "NEXUS_CHATGPT_PROMPT.md",
    "ops/README.md": "ops/README.md",
    "docs/PROJECT_OVERVIEW.md": "docs/PROJECT_OVERVIEW.md",
    "docs/NEXUS_V3_CLEAN_ARCHITECTURE.md": "docs/NEXUS_V3_CLEAN_ARCHITECTURE.md",
    "docs/DISTRIBUTED_DEVSPACE_ARCHITECTURE.md": "docs/DISTRIBUTED_DEVSPACE_ARCHITECTURE.md",
    "docs/DEVICE_IDENTITY_AUTH.md": "docs/DEVICE_IDENTITY_AUTH.md",
    "docs/DEPLOYMENT.md": "docs/DEPLOYMENT.md",
    "docs/OPERATIONS.md": "docs/OPERATIONS.md",
    "docs/SECURITY.md": "docs/SECURITY.md",
    "docs/RECOVERY_RUNBOOK.md": "docs/RECOVERY_RUNBOOK.md",
    "docs/VSC_RECONCILIATION.md": "docs/VSC_RECONCILIATION.md",
}

BOOTSTRAP_SOURCES = [
    "nexus_v3/__init__.py",
    "nexus_v3/common.py",
    "nexus_v3/registry.py",
    "nexus_v3/broker.py",
    "nexus_v3/agent.py",
    "nexus_v3/devspace_runtime.py",
    "nexus_v3/ledger.py",
    "nexus_v3/status.py",
    "nexus_v3/remote_control.py",
    "nexus_v3/mcp_server.py",
    "nexus_v3/chatgpt_api.py",
    "nexus_v3/assets/openwrt_v3_agent.sh",
    "nexus_v3/assets/openwrt_ed25519_signer.rb",
    "runtime/devspace/package.json",
    "runtime/devspace/package-lock.json",
    "runtime/devspace/bridge.mjs",
    "agent-council/integrations/nexus-v3-remote-control-openapi.json",
    "agent-council/integrations/nexus-v3-chatgpt-remote-prompt.md",
    "ops/install.sh",
    "ops/__init__.py",
    "ops/config.example.json",
    "ops/monitoring/__init__.py",
    "ops/monitoring/common.py",
    "ops/monitoring/snapshot.py",
    "ops/monitoring/alerts.py",
    "ops/monitoring/telegram.py",
    "ops/monitoring/state_store.py",
    "ops/systemd/nexus-health-snapshot.service",
    "ops/systemd/nexus-health-snapshot.timer",
    "ops/systemd/nexus-alert-engine.service",
    "ops/systemd/nexus-alert-engine.timer",
    "ops/systemd/nexus-telegram-bot.service",
    "ops/systemd/nexus-telegram-bot.timer",
    "ops/systemd/nexus-state-store.service",
    "ops/systemd/nexus-state-store.timer",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage(output: Path) -> dict:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    files = []
    for source_name, target_name in PUBLISH_MAP.items():
        source = ROOT / source_name
        if not source.is_file():
            raise FileNotFoundError(source)
        target = output / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        files.append({"path": target_name, "sha256": sha256(target), "source": source_name})
    for source_name in BOOTSTRAP_SOURCES:
        source = ROOT / source_name
        if not source.is_file():
            raise FileNotFoundError(source)
        target_name = f"bootstrap/{source_name}"
        target = output / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        files.append({"path": target_name, "sha256": sha256(target), "source": source_name})
    release = {
        "schema": 1,
        "source": "bingStat/nexus",
        "commit": os.getenv("GITHUB_SHA", "local"),
        "run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "files": files,
    }
    (output / "release.json").write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
    return release


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage the authoritative Nexus R2 release tree")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    release = stage(args.output.resolve())
    print(f"staged {len(release['files']) + 1} R2 objects in {args.output}")


if __name__ == "__main__":
    main()
