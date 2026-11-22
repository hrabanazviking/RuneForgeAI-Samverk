"""S-397 acceptance battery: documentation completeness.

Acceptance (roadmap S-397): operator guide, admin
guide, user guide, API contract (S-237) — every guide
walked by a fresh reader against a live instance.

The battery audits the four guides on disk and runs
the real walk: a live instance stood up from this
tree, its own server answering, the guides' claims
checked against its answers. The published log
(docs/documentation-completeness-s397.md) is pinned
to the verdict this machinery produces.

Counted with: python3 -m unittest tests.test_docs_completeness
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.docs_completeness import (
    GUIDES, audit_guides, judge_walk, render_walk_log,
    walk_live_instance, walk_log_dict)
ROOT = Path(__file__).resolve().parent.parent

class PureLawTests(unittest.TestCase):
    def test_pins_no_new_migration_or_event(self):
        self.assertEqual(db.MIGRATIONS[-1][0], 140)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)
    def test_four_guides_named(self):
        self.assertEqual([g.guide_id for g in GUIDES], ["operator", "admin", "user", "api"])
    def test_judge_requires_every_check(self):
        self.assertTrue(judge_walk([{"ok": True}]))
        self.assertFalse(judge_walk([{"ok": True}, {"ok": False}]))
        self.assertFalse(judge_walk([]))
    def test_audit_of_real_tree_is_complete(self):
        self.assertEqual(audit_guides(ROOT), [])
    def test_audit_names_missing_primary(self):
        with tempfile.TemporaryDirectory() as td:
            problems = audit_guides(Path(td))
            self.assertTrue(any("primary missing" in p for p in problems))

class LiveWalkTests(unittest.TestCase):
    def test_walk_against_live_instance_passes(self):
        with tempfile.TemporaryDirectory() as td:
            log = walk_live_instance(ROOT, Path(td))
            self.assertTrue(log["passed"], log["checks"])
            names = [c["name"] for c in log["checks"]]
            for expected in ("install-walk", "healthz", "root", "admin-status-gated", "config-keys", "api-resources", "guide-audit"):
                self.assertIn(expected, names)
    def test_rendered_log_carries_verdict(self):
        text = render_walk_log(walk_log_dict([{"name": "x", "ok": True, "detail": "d"}]))
        self.assertIn("DOCUMENTATION WALK PASSED", text)

if __name__ == "__main__":
    unittest.main()
