import json
from pathlib import Path

from scripts.stage_r2_release import PUBLISH_MAP, stage


def test_r2_release_contains_only_website_assets(tmp_path: Path) -> None:
    output = tmp_path / "release"
    release = stage(output)
    staged = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
    assert staged == {"index.html", "release.json"}
    assert set(PUBLISH_MAP.values()) == {"index.html"}
    assert release["source"] == "bingStat/nexus"


def test_r2_release_manifest_hashes_match_website_files(tmp_path: Path) -> None:
    output = tmp_path / "release"
    stage(output)
    manifest = json.loads((output / "release.json").read_text(encoding="utf-8"))
    assert {item["path"] for item in manifest["files"]} == {"index.html"}
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])
