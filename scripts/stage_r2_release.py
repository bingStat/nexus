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
}


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
