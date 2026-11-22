"""S-382 battery -- layout shell + findability.

Counted with: python3 -m unittest tests.test_layout_shell
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from samverk import layout_shell as ls

ROOT = Path(__file__).resolve().parent.parent


class ShellAuditTests(unittest.TestCase):
    def test_standing_shell_is_coherent(self):
        self.assertEqual(ls.audit_shell(), [])

    def test_every_surface_reachable_from_home(self):
        for name in ls.SURFACES:
            self.assertIsNotNone(ls.shortest_path("home", name), name)

    def test_unreachable_surface_is_named(self):
        broken = {k: tuple(d for d in v if d != "tokens")
                  for k, v in ls.LINKS.items()}
        self.assertIn("surface_unreachable:tokens", ls.audit_shell(broken))

    def test_nav_order_names_only_known_surfaces(self):
        for name in ls.NAV_ORDER:
            self.assertIn(name, ls.SURFACES)
        self.assertEqual(ls.NAV_ORDER[0], "home")


class FindabilityTests(unittest.TestCase):
    def test_all_three_tasks_pass(self):
        results = ls.run_findability()
        self.assertEqual(set(results), {"mint_a_token", "create_a_repo",
                                        "add_a_mirror"})
        for task, result in results.items():
            self.assertTrue(result["ok"], task)
            self.assertLessEqual(result["steps"], ls.MAX_TASK_STEPS)
            self.assertLessEqual(result["seconds"], ls.MAX_TASK_SECONDS)
        self.assertTrue(ls.findability_passed())

    def test_task_paths_are_real_walks(self):
        for result in ls.run_findability().values():
            path = result["path"]
            self.assertEqual(path[0], "home")
            for a, b in zip(path, path[1:]):
                self.assertIn(b, ls.LINKS[a])

    def test_broken_shell_fails_findability(self):
        broken = {k: tuple(d for d in v if d != "new_mirror")
                  for k, v in ls.LINKS.items()}
        result = ls.run_findability(broken)["add_a_mirror"]
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "unreachable")
        self.assertFalse(ls.findability_passed(broken))

    def test_release_script_passes(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "findability_check.py")],
            capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for task in ("mint_a_token", "create_a_repo", "add_a_mirror"):
            self.assertIn(f"{task}: ok", proc.stdout)


class RenderTests(unittest.TestCase):
    def test_nav_marks_current_in_text_not_colour(self):
        html = ls.render_nav("settings")
        self.assertIn('aria-current="page"', html)
        self.assertIn("<span>Settings</span>", html)
        self.assertIn('<a href="/repositories">Repositories</a>', html)
        self.assertIn("Repositories", html)

    def test_unknown_surface_refused(self):
        with self.assertRaises(ValueError):
            ls.render_nav("nope")
        self.assertIsNone(ls.shortest_path("home", "nope"))


if __name__ == "__main__":
    unittest.main()
