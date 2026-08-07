from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import advisor_flow
import council
import task_ids


class TaskIdTests(unittest.TestCase):
    def test_digest_ids_do_not_collide_after_old_prefix_limit(self) -> None:
        first = "task-" + "a" * 24 + "0"
        second = "task-" + "a" * 24 + "1"
        self.assertEqual(first, task_ids.normalize_task_id(first))
        self.assertEqual(second, task_ids.normalize_task_id(second))
        repo = Path("C:/repo")
        self.assertNotEqual(council.room_path(repo, first), council.room_path(repo, second))
        self.assertNotEqual(council.worktree_path(repo, first, "implementer"), council.worktree_path(repo, second, "implementer"))
        self.assertNotEqual(council.agent_name("implementer", first), council.agent_name("implementer", second))

    def test_arbitrary_long_ids_are_bounded_and_stable(self) -> None:
        title = "Implement Claude Gemini Web Advisor Workflow " * 8
        normalized = task_ids.normalize_task_id(title)
        self.assertLessEqual(len(normalized), 64)
        self.assertRegex(normalized, r"-[a-f0-9]{12}$")
        self.assertEqual(normalized, task_ids.normalize_task_id(title))

    def test_advisor_flow_normalizes_direct_cli_task_ids(self) -> None:
        flow = advisor_flow.AdvisorFlow(repo=Path("C:/repo"), task_id="A long task title " * 10, room=Path("C:/room"), adapter=object())
        self.assertEqual(flow.task_id, task_ids.normalize_task_id("A long task title " * 10))


if __name__ == "__main__":
    unittest.main()
