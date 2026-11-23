"""S-413 acceptance battery: CPU honesty.

Acceptance (roadmap S-413): performance budgets
(S-073, S-217, S-395) restated per hardware class
(Pi-class ARM, laptop x86-64, desktop/server); a
budget proven on one class claims nothing about
another.

This battery proves the register restates the
source modules' own budgets exactly (no drift),
that proof status is per class and honest —
S-395 measured Pi-class ARM and desktop/server
x86-64; laptop x86-64 is NOT PROVEN in words and
carries no measured number — and that carrying a
verdict across classes is refused by name. It
measures nothing itself: the numbers pinned here
are S-395's published ones.

Counted with: python3 -m unittest tests.test_cpu_honesty
"""
from __future__ import annotations
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk.cpu_honesty import (
    BUDGET_KINDS, CpuHonestyError, budget_register, claim_for,
    class_status, cross_class_verdict, render_cpu_honesty_page,
    restatement)
from samverk.perf_verification import BROWSE_BUDGETS_MS
from samverk.repo_budgets import CLONE_BUDGETS_SECONDS
from samverk.search_budgets import HARDWARE_CLASSES, SEARCH_BUDGETS_MS


class RegisterShapeTests(unittest.TestCase):
    def test_register_covers_every_kind_times_every_class(self):
        reg = budget_register()
        self.assertEqual(len(reg), len(BUDGET_KINDS) * len(HARDWARE_CLASSES))
        pairs = {(e.kind, e.hardware_class) for e in reg}
        self.assertEqual(pairs, {(k, c) for k in BUDGET_KINDS
                                 for c in HARDWARE_CLASSES})

    def test_kinds_and_sources(self):
        self.assertEqual(BUDGET_KINDS, ("clone", "search_substring",
                                        "search_regex", "browse"))
        src = {e.kind: e.source for e in budget_register()}
        self.assertEqual(src, {"clone": "S-073", "search_substring": "S-217",
                               "search_regex": "S-217", "browse": "S-395"})

    def test_restated_budgets_equal_source_modules_exactly(self):
        for e in budget_register():
            if e.kind == "clone":
                want = CLONE_BUDGETS_SECONDS[e.hardware_class]
            elif e.kind == "search_substring":
                want = SEARCH_BUDGETS_MS[e.hardware_class]["substring"]
            elif e.kind == "search_regex":
                want = SEARCH_BUDGETS_MS[e.hardware_class]["regex"]
            else:
                want = BROWSE_BUDGETS_MS[e.hardware_class]
            self.assertEqual(e.budget, want, (e.kind, e.hardware_class))

    def test_stated_budget_values_pinned(self):
        pin = {("clone", "server_x86_64"): 30.0,
               ("clone", "laptop_x86_64"): 60.0,
               ("clone", "pi_class_arm"): 60.0,
               ("search_substring", "server_x86_64"): 1000.0,
               ("search_substring", "pi_class_arm"): 2000.0,
               ("search_regex", "laptop_x86_64"): 4000.0,
               ("browse", "server_x86_64"): 1000.0,
               ("browse", "laptop_x86_64"): 2000.0,
               ("browse", "pi_class_arm"): 4000.0}
        for (kind, cls), want in pin.items():
            self.assertEqual(claim_for(kind, cls).budget, want)


class HonestyTests(unittest.TestCase):
    def test_measured_classes_carry_s395_numbers_verbatim(self):
        pi = {e.kind: e.measured for e in budget_register()
              if e.hardware_class == "pi_class_arm"}
        self.assertEqual(pi, {"clone": 0.011, "search_substring": 56.2,
                              "search_regex": 12.2, "browse": 10.2})
        srv = {e.kind: e.measured for e in budget_register()
               if e.hardware_class == "server_x86_64"}
        self.assertEqual(srv, {"clone": 0.050, "search_substring": 54.8,
                               "search_regex": 17.3, "browse": 35.5})

    def test_measured_numbers_within_their_class_budgets(self):
        for e in budget_register():
            if e.status == "measured":
                self.assertLessEqual(e.measured, e.budget, e)
                self.assertIsNotNone(e.machine)

    def test_laptop_is_not_proven_in_words_everywhere(self):
        self.assertEqual(class_status("laptop_x86_64"), "NOT PROVEN")
        for e in budget_register():
            if e.hardware_class == "laptop_x86_64":
                self.assertEqual(e.status, "NOT PROVEN")
                self.assertIsNone(e.measured)
                self.assertIsNone(e.machine)

    def test_measured_class_statuses(self):
        self.assertEqual(class_status("pi_class_arm"), "measured")
        self.assertEqual(class_status("server_x86_64"), "measured")

    def test_cross_class_claim_refused_by_name(self):
        for kind in BUDGET_KINDS:
            with self.assertRaises(CpuHonestyError) as cm:
                cross_class_verdict(kind, "pi_class_arm", "laptop_x86_64")
            self.assertEqual(cm.exception.reason, "cross_class_claim")
            with self.assertRaises(CpuHonestyError):
                cross_class_verdict(kind, "server_x86_64", "pi_class_arm")

    def test_same_class_verdict_follows_the_cell(self):
        self.assertTrue(cross_class_verdict("clone", "pi_class_arm",
                                            "pi_class_arm"))
        self.assertFalse(cross_class_verdict("clone", "laptop_x86_64",
                                             "laptop_x86_64"))

    def test_unknown_kind_and_class_refused_by_name(self):
        with self.assertRaises(CpuHonestyError) as cm:
            claim_for("teleport", "pi_class_arm")
        self.assertEqual(cm.exception.reason, "kind_unknown")
        with self.assertRaises(CpuHonestyError) as cm:
            claim_for("clone", "quantum")
        self.assertEqual(cm.exception.reason, "budget_unknown")
        with self.assertRaises(CpuHonestyError):
            class_status("quantum")


class RenderTests(unittest.TestCase):
    def test_restatement_is_json_safe_and_complete(self):
        import json
        data = restatement()
        json.dumps(data)
        self.assertEqual(len(data["entries"]), 12)
        self.assertEqual(data["classes"]["laptop_x86_64"], "NOT PROVEN")

    def test_page_names_every_class_and_not_proven(self):
        page = render_cpu_honesty_page(restatement())
        for label in ("Pi-class ARM", "laptop x86-64", "desktop/server"):
            self.assertIn(label, page)
        self.assertIn("NOT PROVEN on this class", page)
        self.assertIn("claims nothing about", page)


if __name__ == "__main__":
    unittest.main()
