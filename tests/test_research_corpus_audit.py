"""S-398 acceptance battery: research corpus audit.

Acceptance (roadmap S-398): all 46 study files either
hold a completed study or are honestly marked open
with the roadmap slice that owns them; no file claims
what it does not hold.

The battery pins the census (46 files, counted from
disk), the completed/open split reached by reading
every file (43 complete, 3 open -- the verdict files
24, 26 and 30, each owned by S-403), and runs the
structural audit over the real corpus: substance
floors, the elements the corpus index itself defines
a study by, honest status lines, no overclaims, and
in-file open markings. The published log
(docs/research-corpus-audit-s398.md) is pinned to the
verdict this machinery produces.

Counted with: python3 -m unittest tests.test_research_corpus_audit
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.research_corpus_audit import (
    EXPECTED_COUNT, STUDIES, audit_corpus, audit_log_dict,
    judge_audit, render_audit_log, run_audit)
ROOT = Path(__file__).resolve().parent.parent

class PureLawTests(unittest.TestCase):
    def test_pins_no_new_migration_or_event(self):
        self.assertEqual(db.MIGRATIONS[-1][0], 140)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)
    def test_census_is_46_counted(self):
        self.assertEqual(len(STUDIES), EXPECTED_COUNT)
        self.assertEqual(EXPECTED_COUNT, 46)
        self.assertEqual(len({s.filename for s in STUDIES}), 46)
    def test_split_is_43_complete_3_open(self):
        complete = [s for s in STUDIES if s.verdict == "complete"]
        open_ = [s for s in STUDIES if s.verdict == "open"]
        self.assertEqual(len(complete), 43)
        self.assertEqual([s.filename for s in open_],
            ["24-graphql-api-shape.md", "26-packages-and-registry.md", "30-discussions.md"])
        self.assertTrue(all(s.owner == "S-403" for s in open_))
    def test_judge_requires_clean_and_full(self):
        self.assertTrue(judge_audit([]))
        self.assertFalse(judge_audit(["x"]))
        self.assertFalse(judge_audit([], studies=STUDIES[:45]))
    def test_audit_of_real_tree_is_sound(self):
        self.assertEqual(audit_corpus(ROOT), [])
    def test_audit_names_missing_and_stub(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "research").mkdir()
            problems = audit_corpus(root)
            self.assertTrue(any("missing on disk" in p for p in problems))
            (root / "research" / STUDIES[0].filename).write_text("# stub\n", encoding="utf-8")
            problems = audit_corpus(root)
            self.assertTrue(any("stub" in p for p in problems))

class ArtifactTests(unittest.TestCase):
    def test_run_audit_passes_with_split(self):
        log = run_audit(ROOT)
        self.assertTrue(log["passed"], log["problems"])
        self.assertEqual((log["total"], log["complete"], len(log["open"])), (46, 43, 3))
    def test_rendered_log_carries_verdict_and_open_owners(self):
        text = render_audit_log(run_audit(ROOT))
        self.assertIn("RESEARCH CORPUS AUDIT PASSED", text)
        self.assertIn("24-graphql-api-shape.md", text)
        self.assertIn("S-403", text)
    def test_log_dict_shape(self):
        log = audit_log_dict([])
        self.assertEqual(log["schema"], 140)
        self.assertEqual(log["taxonomy_events"], 142)

if __name__ == "__main__":
    unittest.main()
