"""S-414 acceptance battery: browser and device reach.

Acceptance (roadmap S-414): the web UI verified in
current Chrome, Firefox, Safari, and Edge, and on
phone and tablet browsers (small screens, touch
targets per S-386); the device matrix is the test
list.

This battery proves the matrix is complete (4
browsers x 3 form factors = the test list), that
exactly one cell carries a run -- firefox/desktop,
render-checked in a real Firefox 159.0 headless
screenshot on purplelongship, 2026-11-22 -- and
that every other cell is NOT PROVEN in words with
named reasons and no invented run. It proves the
code-layer checks: S-386 touch audits green, no
proprietary tokens, and the viewport defect
(viewport_meta_missing, 70 page modules) detected
and named, holding every small-screen cell at
NOT PROVEN. Cross-browser claims are refused by
name. Full verification of every cell belongs to
the S-416 gate; this battery claims none of it.

Counted with: python3 -m unittest tests.test_browser_reach
"""
from __future__ import annotations
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk.browser_reach import (
    BROWSERS, FORM_FACTORS, FORM_VIEWPORT_CSS_PX, RUNS, TEST_LIST,
    BrowserReachError, audit_proprietary, audit_touch_targets,
    audit_viewport, cell_status, claim_for, cross_browser_verdict,
    reach_data, reach_register, render_browser_reach_page)
from samverk.target_sizes import MIN_TARGET


class MatrixShapeTests(unittest.TestCase):
    def test_matrix_is_four_browsers_times_three_forms(self):
        self.assertEqual(BROWSERS, ("chrome", "firefox", "safari", "edge"))
        self.assertEqual(FORM_FACTORS, ("desktop", "phone", "tablet"))
        reg = reach_register()
        self.assertEqual(len(reg), 12)
        pairs = {(e.browser, e.form_factor) for e in reg}
        self.assertEqual(pairs, {(b, f) for b in BROWSERS for f in FORM_FACTORS})

    def test_test_list_is_the_matrix(self):
        self.assertEqual(len(TEST_LIST), 12)
        self.assertEqual(set(TEST_LIST),
                         {f"{b}/{f}" for b in BROWSERS for f in FORM_FACTORS})

    def test_viewport_widths_per_form(self):
        self.assertEqual(FORM_VIEWPORT_CSS_PX,
                         {"desktop": 1280, "phone": 360, "tablet": 768})
        for e in reach_register():
            self.assertEqual(e.viewport_css_px, FORM_VIEWPORT_CSS_PX[e.form_factor])


class HonestStatusTests(unittest.TestCase):
    def test_exactly_one_run_recorded_firefox_desktop(self):
        self.assertEqual(set(RUNS), {("firefox", "desktop")})
        run = RUNS[("firefox", "desktop")]
        self.assertEqual(run["browser_version"], "Mozilla Firefox 159.0")
        self.assertEqual(run["date"], "2026-11-22")
        self.assertIn("screenshot", run["method"])

    def test_firefox_desktop_is_render_checked_not_verified(self):
        e = claim_for("firefox", "desktop")
        self.assertEqual(e.status, "render_checked")
        self.assertIsNotNone(e.run)

    def test_every_other_cell_not_proven_with_reason(self):
        for e in reach_register():
            if (e.browser, e.form_factor) == ("firefox", "desktop"):
                continue
            self.assertEqual(e.status, "NOT PROVEN", e)
            self.assertIsNone(e.run)
            self.assertIn(f"no_run_recorded:{e.browser}/{e.form_factor}", e.reasons)

    def test_no_browser_was_run_on_phone_or_tablet(self):
        for b in BROWSERS:
            for f in ("phone", "tablet"):
                self.assertEqual(cell_status(b, f), "NOT PROVEN")


class CodeLayerCheckTests(unittest.TestCase):
    def test_touch_targets_green_per_s386(self):
        self.assertEqual(MIN_TARGET, 44)
        self.assertEqual(audit_touch_targets(), [])

    def test_no_proprietary_tokens(self):
        self.assertEqual(audit_proprietary(), [])

    def test_viewport_defect_detected_and_named(self):
        problems = audit_viewport()
        self.assertTrue(problems)
        self.assertTrue(all(p.startswith("viewport_meta_missing:")
                            for p in problems))
        self.assertIn("viewport_meta_missing:audit_log_ui.py", problems)

    def test_small_screen_cells_carry_viewport_reason(self):
        for e in reach_register():
            if e.form_factor in ("phone", "tablet"):
                self.assertIn("viewport_meta_missing", e.reasons)
                self.assertEqual(e.status, "NOT PROVEN")
        data = reach_data()
        self.assertEqual(data["small_screen_status"], "NOT PROVEN")
        self.assertEqual(data["viewport_problems"], audit_viewport())


class RefusalTests(unittest.TestCase):
    def test_cross_browser_claim_refused_by_name(self):
        with self.assertRaises(BrowserReachError) as ctx:
            cross_browser_verdict("firefox", "chrome", "desktop")
        self.assertEqual(ctx.exception.reason, "cross_browser_claim")

    def test_same_browser_verdict_is_the_cells_own(self):
        self.assertTrue(cross_browser_verdict("firefox", "firefox", "desktop"))
        self.assertFalse(cross_browser_verdict("chrome", "chrome", "desktop"))

    def test_unknown_browser_and_form_refused_by_name(self):
        with self.assertRaises(BrowserReachError) as ctx:
            claim_for("opera", "desktop")
        self.assertEqual(ctx.exception.reason, "browser_unknown")
        with self.assertRaises(BrowserReachError) as ctx:
            claim_for("firefox", "watch")
        self.assertEqual(ctx.exception.reason, "form_unknown")


class RenderTests(unittest.TestCase):
    def test_page_states_run_and_not_proven_plainly(self):
        page = render_browser_reach_page(reach_data())
        self.assertIn("Mozilla Firefox 159.0", page)
        self.assertIn("render checked", page)
        self.assertIn("NOT PROVEN", page)
        self.assertIn("viewport_meta_missing", page)
        self.assertIn("S-416", page)
        for label in ("Chrome", "Safari", "Edge"):
            self.assertIn(label, page)

    def test_reach_data_is_complete_and_json_safe(self):
        data = reach_data()
        self.assertEqual(len(data["entries"]), 12)
        self.assertEqual(data["touch_target_problems"], [])
        self.assertEqual(data["proprietary_problems"], [])
        import json; json.dumps(data)


if __name__ == "__main__":
    unittest.main()
