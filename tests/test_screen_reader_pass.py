"""S-389 battery -- screen-reader pass (structural ARIA audit).

Counted with: python3 -m unittest tests.test_screen_reader_pass
"""
from __future__ import annotations

import unittest

from samverk import screen_reader_pass as sr
from samverk.layout_shell import render_nav


class LandmarkTests(unittest.TestCase):
    def test_every_surface_declares_all_landmarks(self):
        self.assertEqual(sr.audit_landmarks(), [])

    def test_missing_landmark_is_named(self):
        rows = dict(sr.LANDMARKS)
        rows["home"] = ("banner", "navigation", "contentinfo")
        self.assertIn("landmark_missing:home:main", sr.audit_landmarks(rows))


class RenderedTests(unittest.TestCase):
    def test_rendered_nav_passes_on_every_surface(self):
        from samverk.layout_shell import NAV_ORDER
        for surface in NAV_ORDER:
            self.assertEqual(sr.audit_rendered(render_nav(surface)), [],
                             surface)

    def test_unlabelled_nav_is_named(self):
        html = '<nav><ul><li><a href="/home">Home</a></li></ul></nav>'
        self.assertIn("nav_landmark_unlabelled", sr.audit_rendered(html))

    def test_nameless_link_is_named(self):
        html = ('<nav aria-label="Primary"><ul><li>'
                '<a href="/x"><span class="icon"></span></a>'
                "</li></ul></nav>")
        problems = sr.audit_rendered(html)
        self.assertTrue(any(p.startswith("link_without_name")
                            for p in problems), problems)

    def test_aria_label_counts_as_a_name(self):
        self.assertEqual(sr.accessible_name(
            '<a href="/x" aria-label="Close"></a>'), "Close")

    def test_heading_skip_is_named(self):
        html = ('<nav aria-label="Primary"></nav>'
                "<h1>Title</h1><h3>Skipped</h3>")
        self.assertIn("heading_skip:h1->h3", sr.audit_rendered(html))


class StatusNameTests(unittest.TestCase):
    def test_every_status_has_an_accessible_name(self):
        self.assertEqual(sr.audit_status_names(), [])

    def test_full_pass(self):
        self.assertEqual(sr.audit_core_flows(), [])
        self.assertTrue(sr.screen_reader_passed())


if __name__ == "__main__":
    unittest.main()
