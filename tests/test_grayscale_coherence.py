"""S-383 battery -- grayscale coherence.

Counted with: python3 -m unittest tests.test_grayscale_coherence
"""
from __future__ import annotations

import unittest

from samverk import grayscale_coherence as gc


class LuminanceTests(unittest.TestCase):
    def test_black_and_white_ends(self):
        self.assertEqual(gc.grayscale_value("#000000"), 0)
        self.assertEqual(gc.grayscale_value("#ffffff"), 255)

    def test_mid_gray_luminance_is_the_wcag_value(self):
        # #808080 has relative luminance ~0.2158 -> gray 55.
        self.assertEqual(gc.grayscale_value("#808080"), 55)
        self.assertLess(gc.grayscale_value("#404040"), 55)
        self.assertGreater(gc.grayscale_value("#c0c0c0"), 55)


class AuditTests(unittest.TestCase):
    def test_standing_ui_loses_no_meaning(self):
        self.assertEqual(gc.audit_grayscale(), [])
        self.assertTrue(gc.grayscale_passed())

    def test_colour_only_carrier_is_named(self):
        rows = (("bare", "g", "#123456", None, None),)
        self.assertEqual(gc.audit_grayscale(rows), ["colour_only:bare"])

    def test_collapse_without_separation_is_named(self):
        rows = (("a", "g", "#808080", "Same", "dot"),
                ("b", "g", "#818181", "Same", "dot"))
        problems = gc.audit_grayscale(rows)
        self.assertTrue(any(p.startswith("grayscale_collapse:g:a/b")
                            for p in problems), problems)

    def test_collapse_with_text_separation_passes(self):
        rows = (("a", "g", "#808080", "Alpha", None),
                ("b", "g", "#818181", "Beta", None))
        self.assertEqual(gc.audit_grayscale(rows), [])

    def test_every_group_is_covered(self):
        groups = {r[1] for r in gc.MEANING_CARRIERS}
        self.assertEqual(groups, {"checks", "visibility", "protection",
                                  "alerts", "navigation"})


class ProofTests(unittest.TestCase):
    def test_proof_report_lists_every_carrier_with_gray(self):
        report = gc.render_proof_report()
        for name, group, colour, text, icon in gc.MEANING_CARRIERS:
            self.assertIn(name, report)
            self.assertIn(str(gc.grayscale_value(colour)), report)

    def test_checks_states_survive_by_text_and_icon(self):
        checks = [r for r in gc.MEANING_CARRIERS if r[1] == "checks"]
        self.assertEqual({r[3] for r in checks},
                         {"Passed", "Failed", "Pending"})
        self.assertEqual(len({r[4] for r in checks}), 3)


if __name__ == "__main__":
    unittest.main()
