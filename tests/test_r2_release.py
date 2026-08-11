import json
from pathlib import Path

from scripts.stage_r2_release import PUBLISH_MAP, stage


def test_r2_release_contains_only_canonical_public_artifacts(tmp_path: Path) -> None:
    release = stage(tmp_path / "release")
    staged = {p.relative_to(tmp_path / "release").as_posix() for p in (tmp_path / "release").rglob("*") if p.is_file()}
    assert staged == set(PUBLISH_MAP.values()) | {"release.json"}
    assert ".git" not in " ".join(staged)
    assert not any("identity" in name.lower() or "ledger" in name.lower() for name in staged)
    assert release["source"] == "bingStat/nexus"


def test_r2_release_manifest_hashes_match_staged_files(tmp_path: Path) -> None:
    output = tmp_path / "release"
    stage(output)
    manifest = json.loads((output / "release.json").read_text(encoding="utf-8"))
    assert {item["path"] for item in manifest["files"]} == set(PUBLISH_MAP.values())
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])