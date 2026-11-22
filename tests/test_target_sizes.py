"""S-386 battery -- target sizes.

Counted with: python3 -m unittest tests.test_target_sizes
"""
from __future__ import annotations

import unittest

from samverk import target_sizes as tz


class AuditTests(unittest.TestCase):
    def test_standing_targets_pass_both_laws(self):
        self.assertEqual(tz.audit_targets(), [])
        self.assertTrue(tz.targets_passed())

    def test_small_target_is_named_with_size(self):
        rows = (("tiny", "home", "target", 30, 44),)
        self.assertEqual(tz.audit_targets(rows),
                         ["target_too_small:tiny:30x44"])

    def test_control_out_of_band_is_named(self):
        rows = (("tall", "home", "control", 90, 52),)
        self.assertIn("control_out_of_band:tall:52", tz.audit_targets(rows))
        rows = (("short", "home", "control", 90, 44),)
        self.assertEqual(tz.audit_targets(rows), [])

    def test_unknown_surface_is_named(self):
        rows = (("x", "nowhere", "target", 50, 50),)
        self.assertIn("target_surface_unknown:x:nowhere",
                      tz.audit_targets(rows))

    def test_rendered_nav_targets_all_registered_and_passing(self):
        self.assertEqual(tz.audit_rendered_nav(), [])

    def test_rendered_nav_with_unregistered_link_is_named(self):
        html = '<nav><ul><li><a href="/tokens">Access tokens</a></li></ul></nav>'
        self.assertEqual(tz.audit_rendered_nav(html),
                         ["rendered_target_unregistered:tokens"])

    def test_every_nav_surface_has_a_target(self):
        from samverk.layout_shell import NAV_ORDER
        have = {r[1] for r in tz.TARGETS if r[0].startswith("nav_")}
        self.assertEqual(have, set(NAV_ORDER))


if __name__ == "__main__":
    unittest.main()
