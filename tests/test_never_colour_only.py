"""S-387 battery -- never colour-only.

Counted with: python3 -m unittest tests.test_never_colour_only
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from samverk import never_colour_only as nco


class AuditTests(unittest.TestCase):
    def test_every_standing_status_carries_icon_and_text(self):
        self.assertEqual(nco.audit_statuses(), [])
        self.assertTrue(nco.colour_only_passed())

    def test_missing_icon_is_named(self):
        rows = (("s", "checks", "#111111", "Passed", None),)
        self.assertEqual(nco.audit_statuses(rows),
                         ["status_missing_icon:s"])

    def test_missing_text_is_named(self):
        rows = (("s", "alerts", "#111111", None, "alarm"),)
        self.assertEqual(nco.audit_statuses(rows),
                         ["status_missing_text:s"])

    def test_navigation_is_not_a_status_group(self):
        names = {r[0] for r in nco.status_carriers()}
        self.assertNotIn("nav_current", names)
        self.assertIn("check_passed", names)


class GrepTests(unittest.TestCase):
    def test_shipped_ui_greps_clean(self):
        self.assertEqual(nco.grep_ui(), [])

    def test_grep_names_a_colour_only_renderer(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "bad_render.py").write_text(
                'BADGE = "#cf222e"  # failed, but no text or icon here\n',
                encoding="utf-8")
            problems = nco.grep_ui(d)
            self.assertIn("grep_colour_without_text:bad_render.py:check_failed",
                          problems)
            self.assertIn("grep_colour_without_icon:bad_render.py:check_failed",
                          problems)

    def test_grep_accepts_a_full_renderer(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "good_render.py").write_text(
                'BADGE = ("#cf222e", "Failed", "cross")\n', encoding="utf-8")
            self.assertEqual(nco.grep_ui(d), [])


if __name__ == "__main__":
    unittest.main()
