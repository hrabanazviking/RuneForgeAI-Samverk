"""S-391 battery -- motion discipline.

Counted with: python3 -m unittest tests.test_motion_discipline
"""
from __future__ import annotations

import unittest

from samverk import motion_discipline as md


class AuditTests(unittest.TestCase):
    def test_standing_motion_is_within_bands_and_ration(self):
        self.assertEqual(md.audit_motion(), [])
        self.assertTrue(md.motion_passed())

    def test_out_of_band_durations_are_named(self):
        rows = (("slow_micro", "home", "micro", 300),)
        self.assertIn("motion_out_of_band:slow_micro:300",
                      md.audit_motion(rows))
        rows = (("in_between", "home", "transition", 150),)
        self.assertIn("motion_out_of_band:in_between:150",
                      md.audit_motion(rows))

    def test_band_edges_pass(self):
        rows = (("a", "home", "micro", 80), ("b", "home", "micro", 140),
                ("c", "home", "transition", 160),
                ("d", "home", "transition", 220))
        self.assertEqual(md.audit_motion(rows), [])

    def test_ceremony_ration_is_enforced(self):
        rows = tuple((f"m{i}", "home", "micro", 100) for i in range(4)) + (
            ("big", "home", "ceremonial", 900),)
        self.assertIn("ceremonial_too_common:1/5", md.audit_motion(rows))

    def test_two_ceremonies_on_one_surface_are_named(self):
        rows = tuple((f"m{i}", "away", "micro", 100) for i in range(20)) + (
            ("c1", "home", "ceremonial", 900),
            ("c2", "home", "ceremonial", 800))
        self.assertIn("ceremonial_per_surface:home", md.audit_motion(rows))


class ReducedMotionTests(unittest.TestCase):
    def test_reduced_motion_moves_nothing(self):
        reduced = md.reduced_motion()
        self.assertTrue(all(ms == 0 for *_, ms in reduced))
        self.assertFalse(any(kind == "ceremonial"
                             for _, _, kind, _ in reduced))
        self.assertEqual(len(reduced), len(md.MOTIONS) - 1)


if __name__ == "__main__":
    unittest.main()
