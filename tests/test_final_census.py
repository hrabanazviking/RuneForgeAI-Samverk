"""S-404 -- Final census battery.

Proves the census is counted, plain, and complete:
the slice accounting reconciles the whole roadmap
(416 = 401 banked + S-402 + S-403 + S-404 +
S-405..S-416), S-402 stands founder-pending and
NOT DONE, S-403 stands built-but-unbanked at
ad97af2, the three counted runs stand NOT GREEN
with their counted numbers, the v1.0 tag stands
NOT PLACED / NOT PROVEN, S-400 signing stands
NOT PROVEN, the S-399 NOT PROVEN claims stay
NOT PROVEN, the refused and deferred remainder
is carried whole, and the census document on
disk carries every row.

Counted with: python3 -m unittest tests.test_final_census
"""
from __future__ import annotations

import unittest
from pathlib import Path

from samverk.final_census import (
    ALL_ROWS, BANKED_SLICES, EXPECTED_FINDING_ROWS,
    EXPECTED_SLICE_ROWS, FINDING_ROWS, ROADMAP_SLICES,
    SLICE_ROWS, STATUSES, audit_census, census_counts,
    judge_census, render_census, render_census_log,
    rows_by_status, slice_accounting)

ROOT = Path(__file__).resolve().parent.parent
BY_ID = {r.row_id: r for r in ALL_ROWS}


class SliceAccountingTests(unittest.TestCase):
    def test_accounting_reconciles_whole_roadmap(self):
        acct = slice_accounting()
        self.assertEqual(acct["total"], ROADMAP_SLICES)
        self.assertEqual(acct["total"], 416)
        self.assertEqual(acct["banked"], BANKED_SLICES)
        self.assertEqual(acct["banked"], 401)
        self.assertEqual(acct["founder_pending"], 1)
        self.assertEqual(acct["built_unbanked"], 1)
        self.assertEqual(acct["this_slice"], 1)
        self.assertEqual(acct["not_yet_done"], 12)
        self.assertEqual(len(SLICE_ROWS), EXPECTED_SLICE_ROWS)
        self.assertEqual(len(FINDING_ROWS), EXPECTED_FINDING_ROWS)
        self.assertEqual(judge_census(), ())

    def test_every_row_names_source_and_note(self):
        for row in ALL_ROWS:
            self.assertIn(row.status, STATUSES)
            for field in (row.title, row.source, row.note):
                self.assertTrue(field.strip(), row.row_id)

    def test_ids_unique(self):
        self.assertEqual(len(BY_ID), len(ALL_ROWS))
        self.assertEqual(len(ALL_ROWS), 43)


class HonestStatusTests(unittest.TestCase):
    def test_founder_walk_pending_not_done(self):
        row = BY_ID["s402-founder-walk"]
        self.assertEqual(row.status, "founder_pending")
        self.assertIn("NOT DONE", row.note)

    def test_s403_built_but_unbanked(self):
        row = BY_ID["s403-successor-seed"]
        self.assertEqual(row.status, "built_unbanked")
        self.assertIn("ad97af2", row.source + row.note)

    def test_part_xxii_all_not_yet_done(self):
        pending = rows_by_status("not_yet_done")
        self.assertEqual(len(pending), 12)
        ids = {r.row_id for r in pending}
        for n in range(405, 417):
            self.assertTrue(any(i.startswith("s%d-" % n)
                                for i in ids), n)

    def test_counted_runs_not_green_with_numbers(self):
        runs = rows_by_status("not_green")
        self.assertEqual(len(runs), 3)
        self.assertIn("6029", BY_ID["wave380-counted-run"].note)
        self.assertIn("15", BY_ID["wave380-counted-run"].note)
        self.assertIn("6129", BY_ID["s393-counted-master-run"].note)
        w400 = BY_ID["wave400-counted-run"].note
        for token in ("6190", "12", "2511.9"):
            self.assertIn(token, w400)
        self.assertIn("stale", w400)

    def test_v1_tag_not_placed_not_proven(self):
        row = BY_ID["v1-tag-placement"]
        self.assertEqual(row.status, "not_proven")
        self.assertIn("NOT PLACED", row.note)
        self.assertIn("not green", row.note)

    def test_signing_not_proven(self):
        row = BY_ID["release-signing-s400"]
        self.assertEqual(row.status, "not_proven")
        self.assertIn("no maintainer key", row.note)
        self.assertIn("d49482e6", row.note)

    def test_s399_not_proven_stays_not_proven(self):
        for rid in ("claims-f02-platform-matrix",
                    "claims-f10-live-composition",
                    "claims-f11-full-suite-green",
                    "claims-f01-real-sshd-cell"):
            self.assertEqual(BY_ID[rid].status, "not_proven", rid)

    def test_refused_and_deferred_carried_whole(self):
        counts = census_counts()
        self.assertEqual(counts["refused"], 5)
        self.assertEqual(counts["deferred"], 6)
        self.assertEqual(counts["not_proven"], 6)
        self.assertEqual(counts["open"], 4)
        for rid in ("refused-oci", "refused-docker",
                    "refused-federation",
                    "refused-hosted-service",
                    "refused-invented-facts"):
            self.assertEqual(BY_ID[rid].status, "refused", rid)


class CensusDocumentTests(unittest.TestCase):
    def test_audit_against_disk_passes(self):
        self.assertEqual(audit_census(ROOT), ())

    def test_rendered_census_carries_every_row(self):
        text = render_census()
        for row in ALL_ROWS:
            self.assertIn(row.row_id, text)
        self.assertIn("NOT PROVEN", text)
        self.assertIn("NOT PLACED", text)
        self.assertIn("401", text)

    def test_rendered_log_counts_match(self):
        log = render_census_log()
        self.assertIn("Census rows judged: 43", log)
        self.assertIn("COUNTED", log)
        self.assertIn("NOT PLACED", log)
        doc = (ROOT / "docs" / "FINAL_CENSUS.md")
        self.assertTrue(doc.exists())
        self.assertIn("wave400-counted-run", doc.read_text())


if __name__ == "__main__":
    unittest.main()
