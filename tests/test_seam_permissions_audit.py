"""S-373 battery — seam permissions audit."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk.seam_permissions_audit import (SAMTAL_ROLES, SAMVERK_ROLES,
    SURFACES, run_audit)

ON = {"seam.samtal.enabled": True}

class SeamPermissionsAuditTests(unittest.TestCase):
    def setUp(self):
        self.report = run_audit(ON)
    def test_matrix_is_the_full_counted_grid(self):
        self.assertEqual(self.report.total, 90)
        self.assertEqual(len(SAMTAL_ROLES) * len(SAMVERK_ROLES) * len(SURFACES), 90)
        self.assertEqual(self.report.allowed, 68)
        self.assertEqual(self.report.denied, 22)
        self.assertIn("90 cells", self.report.summary())
        self.assertIn("68 allowed", self.report.summary())
    def test_per_surface_counts(self):
        self.assertEqual(self.report.for_surface("panel"), (18, 15))
        self.assertEqual(self.report.for_surface("unfurl"), (18, 15))
        self.assertEqual(self.report.for_surface("mentions"), (18, 18))
        self.assertEqual(self.report.for_surface("hall_events"), (18, 10))
        self.assertEqual(self.report.for_surface("village_repo"), (18, 10))
    def test_read_is_the_floor_for_decided_surfaces(self):
        for surface in ("panel", "unfurl"):
            for role in ("read", "triage", "write", "maintain", "admin"):
                self.assertTrue(self.report.cell("member", role, surface).allowed)
            denied = self.report.cell("member", "none", surface)
            self.assertFalse(denied.allowed)
            self.assertEqual(denied.reason, "role_insufficient")
    def test_hall_surfaces_need_hall_membership(self):
        for surface in ("hall_events", "village_repo"):
            cell = self.report.cell("none", "admin", surface)
            self.assertFalse(cell.allowed)
            self.assertEqual(cell.reason, "not_hall_member")
            self.assertTrue(self.report.cell("owner", "read", surface).allowed)
            self.assertTrue(self.report.cell("member", "write", surface).allowed)
    def test_mentions_bridge_needs_link_not_repo_role(self):
        for st in SAMTAL_ROLES:
            self.assertTrue(self.report.cell(st, "none", "mentions").allowed)
    def test_seam_disabled_collapses_every_cell(self):
        off = run_audit({})
        self.assertEqual(off.allowed, 0)
        self.assertTrue(all(c.reason == "seam_disabled" for c in off.cells))
    def test_unlinked_identity_collapses_every_cell(self):
        unlinked = run_audit(ON, linked=False)
        self.assertEqual(unlinked.allowed, 0)
        self.assertTrue(all(c.reason == "not_linked" for c in unlinked.cells))
    def test_no_cell_exceeds_its_samverk_role(self):
        # The audit's core invariant: nothing crosses on a
        # Samtal role alone — every allowed decided-surface
        # cell carries at least the read rung on S-189's ladder.
        for c in self.report.cells:
            if c.allowed and c.surface != "mentions":
                self.assertNotEqual(c.samverk_role, "none")

if __name__ == "__main__":
    unittest.main()
