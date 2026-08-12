import json
from pathlib import Path

from scripts.stage_r2_release import BOOTSTRAP_SOURCES, PUBLISH_MAP, stage


def test_r2_release_contains_only_canonical_public_artifacts(tmp_path: Path) -> None:
    release = stage(tmp_path / "release")
    staged = {p.relative_to(tmp_path / "release").as_posix() for p in (tmp_path / "release").rglob("*") if p.is_file()}
    assert staged == set(PUBLISH_MAP.values()) | {f"bootstrap/{name}" for name in BOOTSTRAP_SOURCES} | {"release.json"}
    assert ".git" not in " ".join(staged)
    assert not any(name.endswith(".db") or "identity_ed25519" in name.lower() or name.endswith(".env") for name in staged)
    assert release["source"] == "bingStat/nexus"


def test_r2_release_manifest_hashes_match_staged_files(tmp_path: Path) -> None:
    output = tmp_path / "release"
    stage(output)
    manifest = json.loads((output / "release.json").read_text(encoding="utf-8"))
    assert {item["path"] for item in manifest["files"]} == set(PUBLISH_MAP.values()) | {f"bootstrap/{name}" for name in BOOTSTRAP_SOURCES}
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])