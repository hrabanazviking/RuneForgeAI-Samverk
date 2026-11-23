"""S-403 -- Successor roadmap seed battery.

Proves the seed is the honest remainder: the census
counts hold, every item names source/status/owner/
reopen, the revisited GraphQL verdict is present as
deferred (never upgraded), OCI and the standing
exclusions are refused, the three S-398 open studies
are carried as open, the S-399 NOT PROVEN claims stay
NOT PROVEN, the founder walk is founder-owned, and
the seed document on disk carries every item.

Counted with: python3 -m unittest tests.test_successor_roadmap_seed
"""
from __future__ import annotations

import unittest
from pathlib import Path

from samverk.successor_roadmap_seed import (
    EXPECTED_COUNT, SEED_ITEMS, STATUSES, audit_seed,
    items_by_status, judge_seed, render_seed,
    render_seed_log, seed_counts)

ROOT = Path(__file__).resolve().parent.parent
BY_ID = {it.item_id: it for it in SEED_ITEMS}


class SeedCensusTests(unittest.TestCase):
    def test_census_count_and_split(self):
        counts = seed_counts()
        self.assertEqual(counts["total"], EXPECTED_COUNT)
        self.assertEqual(counts["total"], 24)
        self.assertEqual(counts["deferred"], 6)
        self.assertEqual(counts["refused"], 5)
        self.assertEqual(counts["not_proven"], 5)
        self.assertEqual(counts["open"], 5)
        self.assertEqual(counts["founder"], 1)
        self.assertEqual(counts["served"], 2)
        self.assertEqual(judge_seed(), ())

    def test_every_item_names_source_owner_reopen(self):
        for it in SEED_ITEMS:
            self.assertIn(it.status, STATUSES)
            for field in (it.title, it.source, it.owner,
                          it.reopen, it.note):
                self.assertTrue(field.strip(), it.item_id)

    def test_ids_unique(self):
        self.assertEqual(len(BY_ID), len(SEED_ITEMS))


class HonestStatusTests(unittest.TestCase):
    def test_graphql_revisited_as_deferred_not_upgraded(self):
        it = BY_ID["graphql-layer"]
        self.assertEqual(it.status, "deferred")
        self.assertEqual(it.source, "S-253")

    def test_oci_and_standing_exclusions_refused(self):
        for iid in ("package-oci", "standing-no-federation",
                    "standing-no-hosted-service",
                    "standing-no-invented-facts",
                    "standing-no-docker"):
            self.assertEqual(BY_ID[iid].status, "refused", iid)
            self.assertIn("Volmarr", BY_ID[iid].owner)

    def test_s398_open_studies_carried_open(self):
        for iid in ("study-24-graphql", "study-26-packages",
                    "study-30-discussions"):
            self.assertEqual(BY_ID[iid].status, "open", iid)
            self.assertIn("S-398", BY_ID[iid].source)

    def test_s399_not_proven_stays_not_proven(self):
        for iid in ("claims-f02-platform-matrix",
                    "claims-f10-live-composition",
                    "claims-f11-full-suite-green",
                    "claims-f01-real-sshd-cell"):
            self.assertEqual(BY_ID[iid].status, "not_proven", iid)

    def test_founder_walk_is_founder_owned(self):
        it = BY_ID["founder-usability-walk"]
        self.assertEqual(it.status, "founder")
        self.assertEqual(it.owner, "Volmarr")
        self.assertEqual(it.source, "S-402")

    def test_polls_and_badges_deferred(self):
        self.assertEqual(BY_ID["discussion-polls"].status, "deferred")
        self.assertEqual(BY_ID["discussion-badges"].status, "deferred")
        self.assertIn("S-286", BY_ID["discussion-polls"].source)

    def test_served_items_are_not_remainders(self):
        served = {it.item_id for it in items_by_status("served")}
        self.assertEqual(served, {"package-generic-archives",
                                  "package-go-modules"})


class SeedDocumentTests(unittest.TestCase):
    def test_audit_against_disk_passes(self):
        self.assertEqual(audit_seed(ROOT), ())

    def test_rendered_seed_carries_every_item(self):
        text = render_seed()
        for it in SEED_ITEMS:
            self.assertIn(it.item_id, text)
        self.assertIn("NOT PROVEN", text)

    def test_rendered_log_counts_match(self):
        log = render_seed_log()
        self.assertIn("Seed items judged: 24", log)
        self.assertIn("SEEDED", log)
        doc = (ROOT / "docs" / "SUCCESSOR_ROADMAP_SEED.md")
        self.assertTrue(doc.exists())
        self.assertIn("graphql-layer", doc.read_text())


if __name__ == "__main__":
    unittest.main()
