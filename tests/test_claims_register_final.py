"""S-399 acceptance battery: claims register final.

Acceptance (roadmap S-399): every public claim in the
README and docs traced to a proof or reworded; the
register ships with the release. This battery keeps the
final judgement honest mechanically: the census stands,
every PROVEN row's evidence exists on disk, every NOT
PROVEN row names its owner, every OPEN row names
Volmarr (the README is never edited by this campaign),
the register document carries every final row and the
re-judged C-09..C-12 verdicts, and no positive overclaim
phrase stands in docs/.

Counted with: python3 -m unittest tests.test_claims_register_final -v
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.claims_register_final import (
    EXPECTED_FINAL_COUNT, FINAL_CLAIMS, audit_register, judge_register)

ROOT = Path(__file__).resolve().parent.parent


class FinalCensusTests(unittest.TestCase):
    def test_census_stands(self):
        self.assertEqual(len(FINAL_CLAIMS), EXPECTED_FINAL_COUNT)
        ids = [c.claim_id for c in FINAL_CLAIMS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_status_vocabulary(self):
        for claim in FINAL_CLAIMS:
            self.assertIn(claim.status, ("proven", "proven_scoped",
                "not_proven", "open", "historical"), msg=claim.claim_id)

    def test_proven_evidence_exists(self):
        for claim in FINAL_CLAIMS:
            if claim.status in ("proven", "proven_scoped"):
                self.assertTrue(claim.evidence, msg=claim.claim_id)
                for rel in claim.evidence:
                    self.assertTrue((ROOT / rel).is_file(),
                        msg=f"{claim.claim_id}: missing {rel}")

    def test_unproven_rows_name_an_owner(self):
        for claim in FINAL_CLAIMS:
            if claim.status == "not_proven":
                self.assertTrue("Part" in claim.owner or "S-" in claim.owner,
                    msg=claim.claim_id)
            if claim.status == "open":
                self.assertEqual(claim.owner, "Volmarr", msg=claim.claim_id)

    def test_the_open_readme_items_are_named(self):
        opens = [c for c in FINAL_CLAIMS if c.status == "open"]
        self.assertEqual(len(opens), 1)
        self.assertIn("empty file", opens[0].note)
        self.assertIn("Samtel", opens[0].note)


class RegisterDocumentTests(unittest.TestCase):
    def test_audit_is_clean(self):
        self.assertEqual(audit_register(ROOT), [])

    def test_judgement_counts(self):
        result = judge_register(ROOT)
        self.assertTrue(result["passed"])
        self.assertEqual(result["total"], EXPECTED_FINAL_COUNT)
        self.assertEqual(result["counts"].get("proven", 0)
            + result["counts"].get("proven_scoped", 0), 12)
        self.assertEqual(result["not_proven"], ["F-02", "F-10", "F-11"])
        self.assertEqual(result["open"], ["F-17"])


if __name__ == "__main__":
    unittest.main()
