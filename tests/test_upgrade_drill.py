"""S-396 acceptance battery: upgrade drill.

Acceptance (roadmap S-396): an RC instance with
real-shaped data upgraded per S-357 and verified;
the drill log is a release artifact.

The battery runs the real drill: leg A upgrades a
fresh RC instance through S-357's procedure with a
stand-in next migration and verifies refs, LFS bytes
and counts independently; leg B proves a destructive
migration rolls back to the export. The published
log (docs/upgrade-drill-s396.md) is pinned to the
verdict this machinery produces.

Counted with: python3 -m unittest tests.test_upgrade_drill
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.db import schema_version
from samverk.upgrade_drill import (
    RC_REPOS, RC_USERS, build_rc_instance, drill_log_dict,
    expected_rc_counts, judge_drill, render_drill_log, run_drill)


class PureLawTests(unittest.TestCase):
    def test_pins_no_new_migration_or_event(self):
        with tempfile.TemporaryDirectory() as td:
            inst = build_rc_instance(Path(td) / "i")
            self.assertEqual(schema_version(inst.conn), 140)
            inst.conn.close()
        self.assertEqual(db.MIGRATIONS[-1][0], 140)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)

    def test_rc_shape_counts_are_derived_from_the_shape(self):
        counts = expected_rc_counts()
        self.assertEqual(counts["users"], len(RC_USERS))
        self.assertEqual(counts["repos"], len(RC_REPOS))
        self.assertEqual(counts["commits"], 15)
        self.assertEqual(counts["lfs_objects"], 3)

    def test_judge_requires_both_legs_and_no_problems(self):
        self.assertTrue(judge_drill(True, True, []))
        self.assertFalse(judge_drill(False, True, []))
        self.assertFalse(judge_drill(True, False, []))
        self.assertFalse(judge_drill(True, True, ["named"]))

    def test_rc_instance_is_real_shaped(self):
        with tempfile.TemporaryDirectory() as td:
            inst = build_rc_instance(Path(td) / "i")
            self.assertEqual(len(inst.heads), 4)
            for key, refs in inst.refs.items():
                self.assertEqual(len(refs), 3, key)
            self.assertEqual(sum(len(v) for v in inst.lfs.values()), 3)
            rows = [tuple(r) for r in inst.conn.execute(
                "SELECT visibility FROM repositories ORDER BY name")]
            self.assertIn(("private",), rows)
            inst.conn.close()


class DrillRunTests(unittest.TestCase):
    def test_drill_passes_both_legs_for_real(self):
        with tempfile.TemporaryDirectory() as td:
            log = run_drill(Path(td))
        self.assertTrue(log["passed"], log["problems"])
        self.assertEqual(log["verdict"], "PASSED")
        leg_a, leg_b = log["legs"]
        self.assertTrue(leg_a["procedure_ok"])
        self.assertEqual(leg_a["counts_after"]["schema"], 141)
        self.assertFalse(leg_b["procedure_ok"])
        self.assertTrue(leg_b["rolled_back"])
        self.assertEqual(leg_b["counts_after"]["schema"], 140)
        for leg in (leg_a, leg_b):
            self.assertEqual(
                [s["step"] for s in leg["steps"]],
                ["export", "verify_export", "stop",
                 "migrate", "start", "verify_counts"][:len(leg["steps"])])
        self.assertEqual(drill_log_dict(log)["slice"], "S-396")

    def test_rendered_log_is_the_release_artifact_shape(self):
        with tempfile.TemporaryDirectory() as td:
            text = render_drill_log(run_drill(Path(td)))
        self.assertIn("UPGRADE DRILL PASSED", text)
        self.assertIn("leg-a-upgrade", text)
        self.assertIn("leg-b-rollback", text)
        self.assertNotIn("never-log-this-value", text)

    def test_published_drill_log_matches_the_verdict(self):
        doc = (Path(__file__).resolve().parent.parent / "docs"
               / "upgrade-drill-s396.md").read_text(encoding="utf-8")
        self.assertIn("UPGRADE DRILL PASSED", doc)
        self.assertIn("leg-a-upgrade", doc)
        self.assertIn("leg-b-rollback", doc)
        self.assertIn("S-357", doc)


if __name__ == "__main__":
    unittest.main()
