from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "runtime" / "devspace" / "package.json"


def npm_latest() -> str:
    proc = subprocess.run(
        ["npm", "view", "@waishnav/devspace", "version"],
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def main() -> None:
    requested = sys.argv[1] if len(sys.argv) > 1 else "latest"
    version = npm_latest() if requested == "latest" else requested
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    previous = package["dependencies"]["@waishnav/devspace"]
    package["dependencies"]["@waishnav/devspace"] = version
    PACKAGE.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    print(f"@waishnav/devspace {previous} -> {version}")
    print("Next: cd runtime/devspace && npm install && npm run check; then run pytest -q tests/test_devspace_runtime.py")


if __name__ == "__main__":
    main()
