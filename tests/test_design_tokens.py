"""S-381 battery -- design tokens: the Lawbook's numbers as code.

Counted with: python3 -m unittest tests.test_design_tokens
"""
from __future__ import annotations

import dataclasses
import unittest

from samverk import design_tokens as dt


class RegistryLawTests(unittest.TestCase):
    def test_standing_registry_is_lawful(self):
        self.assertEqual(dt.validate_registry(), [])

    def test_corner_cuts_within_6_to_12(self):
        for cut in dt.TOKENS.corner_cuts_px:
            self.assertGreaterEqual(cut, 6)
            self.assertLessEqual(cut, 12)
        self.assertEqual(dt.corner_cut("soft"), 6)
        self.assertEqual(dt.corner_cut("deep"), 12)
        with self.assertRaises(ValueError):
            dt.corner_cut("round")

    def test_corner_cut_out_of_range_refused(self):
        bad = dataclasses.replace(dt.TOKENS, corner_cuts_px=(4, 9))
        self.assertIn("corner_cut_out_of_range", dt.validate_registry(bad))

    def test_at_most_three_frame_strengths(self):
        self.assertLessEqual(len(dt.TOKENS.frame_strengths_px), 3)
        bad = dataclasses.replace(dt.TOKENS, frame_strengths_px=(1, 2, 3, 4))
        self.assertIn("too_many_frame_strengths", dt.validate_registry(bad))

    def test_at_least_four_dark_surfaces(self):
        self.assertGreaterEqual(len(set(dt.TOKENS.dark_surfaces)), 4)
        bad = dataclasses.replace(dt.TOKENS, dark_surfaces=("#000", "#111"))
        self.assertIn("too_few_dark_surfaces", dt.validate_registry(bad))

    def test_body_text_within_14_to_18(self):
        self.assertGreaterEqual(dt.TOKENS.body_text_px, 14)
        self.assertLessEqual(dt.TOKENS.body_text_px, 18)
        bad = dataclasses.replace(dt.TOKENS, body_text_px=12)
        self.assertIn("body_text_out_of_range", dt.validate_registry(bad))
        bad2 = dataclasses.replace(dt.TOKENS, small_text_px=11)
        self.assertIn("small_text_below_floor", dt.validate_registry(bad2))


class AccentBudgetTests(unittest.TestCase):
    def test_share_computed_from_areas(self):
        self.assertEqual(dt.accent_share([(90, False), (10, True)]), 10.0)
        self.assertEqual(dt.accent_share([]), 0.0)
        with self.assertRaises(ValueError):
            dt.accent_share([(-1, True)])

    def test_budget_band_5_to_12(self):
        self.assertTrue(dt.check_accent_budget([(92, False), (8, True)])["ok"])
        low = dt.check_accent_budget([(99, False), (1, True)])
        self.assertEqual(low["reason"], "accent_below_budget")
        high = dt.check_accent_budget([(50, False), (50, True)])
        self.assertEqual(high["reason"], "accent_over_budget")

    def test_budget_edges_are_lawful(self):
        self.assertTrue(dt.check_accent_budget([(95, False), (5, True)])["ok"])
        self.assertTrue(dt.check_accent_budget([(88, False), (12, True)])["ok"])


class CssSeamTests(unittest.TestCase):
    def test_css_variables_carry_every_number(self):
        css = dt.render_css_variables()
        for cut in dt.TOKENS.corner_cuts_px:
            self.assertIn(f"{cut}px", css)
        for surface in dt.TOKENS.dark_surfaces:
            self.assertIn(surface, css)
        self.assertIn(dt.TOKENS.accent_colour, css)
        self.assertIn("--sv-body-text: 16px", css)
        self.assertTrue(css.startswith(":root {"))

    def test_registry_is_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            dt.TOKENS.body_text_px = 12


if __name__ == "__main__":
    unittest.main()
