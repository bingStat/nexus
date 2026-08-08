from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("council_recipe_test", ROOT / "council.py")
council = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = council
spec.loader.exec_module(council)


class RecipeResolutionTests(unittest.TestCase):
    def test_explicit_commands_override_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "nexus.json").write_text(json.dumps({"verification": ["config-test"]}))
            commands, source = council.resolve_acceptance_commands(repo, [" explicit-test "], required=True)
            self.assertEqual(["explicit-test"], commands)
            self.assertEqual("explicit", source)

    def test_nexus_json_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "nexus.json").write_text(json.dumps({"verification": ["python -m unittest", "python -m py_compile x.py"]}))
            commands, source = council.resolve_acceptance_commands(repo, [], required=True)
            self.assertEqual("nexus.json", source)
            self.assertEqual(2, len(commands))

    def test_invalid_nexus_json_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "nexus.json").write_text("{bad")
            with self.assertRaisesRegex(council.CouncilError, "NEEDS_RECIPE"):
                council.resolve_acceptance_commands(repo, [], required=True)

    def test_safe_manifest_detection(self) -> None:
        cases = [
            ({"pytest.ini": "[pytest]"}, ["python -m pytest -q"]),
            ({"package.json": json.dumps({"scripts": {"test": "vitest run"}})}, ["npm test"]),
            ({"Cargo.toml": "[package]"}, ["cargo test"]),
            ({"Makefile": "test:\n\t@echo ok\n"}, ["make test"]),
        ]
        for files, expected in cases:
            with self.subTest(files=files), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                for name, content in files.items():
                    (repo / name).write_text(content)
                commands, source = council.resolve_acceptance_commands(repo, [], required=True)
                self.assertEqual(expected, commands)
                self.assertEqual("auto-detect", source)

    def test_missing_recipe_fails_only_when_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.assertEqual(([], "not-required"), council.resolve_acceptance_commands(repo, [], required=False))
            with self.assertRaisesRegex(council.CouncilError, "NEEDS_RECIPE"):
                council.resolve_acceptance_commands(repo, [], required=True)

    def test_repo_config_and_public_prompt_are_safe(self) -> None:
        config, source = council.load_repo_nexus_config(ROOT.parent)
        self.assertEqual("README.md:Nexus 控制配置", source)
        self.assertIsNotNone(config)
        self.assertTrue(config["verification"])
        prompt = (ROOT / "integrations" / "WEB_NEXUS_SYSTEM_PROMPT.md").read_text(encoding="utf-8")
        self.assertIn("task_id", prompt)
        self.assertIn("不得读取、抓取", prompt)
        openapi = json.loads((ROOT / "integrations" / "nexus-task-api-openapi.json").read_text(encoding="utf-8"))
        self.assertNotIn("/api/execute", openapi["paths"])


if __name__ == "__main__":
    unittest.main()
