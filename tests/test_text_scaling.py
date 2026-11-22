"""S-384 battery -- text scaling.

Counted with: python3 -m unittest tests.test_text_scaling
"""
from __future__ import annotations

import unittest

from samverk import text_scaling as ts


class ScalingTests(unittest.TestCase):
    def test_both_scales_pass_on_every_core_flow(self):
        self.assertEqual(ts.audit_scaling(), [])
        self.assertTrue(ts.scaling_passed())

    def test_scaled_token_sizes(self):
        self.assertEqual(ts.scaled_sizes(1.25),
                         {"body_px": 20.0, "small_px": 17.5})
        self.assertEqual(ts.scaled_sizes(2.0),
                         {"body_px": 32.0, "small_px": 28.0})

    def test_needed_width_grows_with_scale(self):
        self.assertEqual(ts.needed_width("Save", 16, 1.0), 32)
        self.assertEqual(ts.needed_width("Save", 16, 2.0), 64)

    def test_planted_clip_is_named_at_200_only(self):
        rows = (("f", "tight", "Repositories", 16, 160, False),)
        problems = ts.audit_scaling(rows, ())
        self.assertIn("clipped:f:tight@200pct", problems)
        self.assertNotIn("clipped:f:tight@125pct", problems)

    def test_planted_overlap_is_named(self):
        ctrls = (("f", "a", "Alpha button", 16, 500, False),
                 ("f", "b", "Beta button", 16, 500, False))
        rows = (("f", "r", 200, ("a", "b")),)
        problems = ts.audit_scaling(ctrls, rows)
        self.assertTrue(any(p.startswith("overlap:f:r@") for p in problems))

    def test_core_flows_are_all_modelled(self):
        flows = {c[0] for c in ts.CONTROLS}
        self.assertEqual(flows, {"navigation", "repo_header", "issue_list",
                                 "settings_form"})

    def test_wrapping_controls_never_clip(self):
        rows = (("f", "fluid", "A very long wrapping label indeed",
                 16, 40, True),)
        self.assertEqual(ts.audit_scaling(rows, ()), [])


if __name__ == "__main__":
    unittest.main()
