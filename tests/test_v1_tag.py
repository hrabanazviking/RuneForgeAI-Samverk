"""S-401 -- The v1.0 tag battery.

Proves the counted-green law: only a finished, sound,
zero-failure counted verdict may carry the tag; the tag
names the one counted tree; the census arithmetic holds;
the release notes carry the census; a non-green verdict
renders a named remainder and never a tag claim; and
docs/V1_TAG.md states a tag state consistent with the
verdict it records.

Counted with: python3 -m unittest tests.test_v1_tag
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from samverk.v1_tag import (
    COUNTED_TREE, TAG_NAME, CountedVerdict,
    aggregate_shard_logs, build_census, judge_counted_verdict,
    judge_tag_placement, may_tag, render_release_notes,
    render_remainder)

DOC = Path(__file__).resolve().parent.parent / "docs" / "V1_TAG.md"

GREEN = CountedVerdict(ran=100, passed=97, failed=0, skipped=3)
RED = CountedVerdict(ran=100, passed=82, failed=15, skipped=3,
                     failures=tuple("tests.test_x.F%d" % i
                                      for i in range(15)))


def _census(verdict):
    return build_census(
        slices_banked=400, roadmap_slices=416, verdict=verdict,
        claims_final_count=17, package_sha256="d49482e6",
        schema=140, taxonomy=142)


class CountedGreenLawTests(unittest.TestCase):
    def test_green_verdict_may_tag(self):
        self.assertEqual(judge_counted_verdict(GREEN), "green")
        self.assertTrue(may_tag(GREEN))

    def test_any_failure_refuses_the_tag(self):
        self.assertEqual(judge_counted_verdict(RED), "not_green")
        self.assertFalse(may_tag(RED))

    def test_unfinished_run_is_not_green(self):
        v = CountedVerdict(ran=10, passed=10, failed=0, skipped=0,
                           finished=False)
        self.assertEqual(judge_counted_verdict(v), "unfinished")
        self.assertFalse(may_tag(v))

    def test_broken_arithmetic_is_uncounted(self):
        v = CountedVerdict(ran=100, passed=50, failed=0, skipped=3)
        self.assertEqual(judge_counted_verdict(v), "uncounted")
        self.assertFalse(may_tag(v))

    def test_placement_names_the_counted_tree_only(self):
        self.assertEqual(judge_tag_placement(GREEN, COUNTED_TREE), ())
        reasons = judge_tag_placement(GREEN, "0" * 40)
        self.assertEqual(len(reasons), 1)
        self.assertIn("not the counted tree", reasons[0])
        reasons = judge_tag_placement(RED, COUNTED_TREE)
        self.assertEqual(len(reasons), 1)
        self.assertIn("not green", reasons[0])


class ShardAggregationTests(unittest.TestCase):
    def test_aggregates_counts_and_names(self):
        logs = [
            "Ran 10 tests in 1s\nOK (skipped=2)\n",
            "FAIL: test_a (tests.test_x.T)\n"
            "Ran 5 tests in 1s\nFAILED (failures=1)\n"]
        v = aggregate_shard_logs(logs)
        self.assertEqual((v.ran, v.passed, v.failed, v.skipped),
                         (15, 12, 1, 2))
        self.assertTrue(v.finished)
        self.assertEqual(v.failures, ("test_a",))

    def test_shard_without_ran_line_is_unfinished(self):
        v = aggregate_shard_logs(["........", "Ran 3 tests\nOK\n"])
        self.assertFalse(v.finished)
        self.assertFalse(may_tag(v))


class CensusAndNotesTests(unittest.TestCase):
    def test_census_carries_the_counts(self):
        c = _census(GREEN)
        self.assertEqual(c["tag"], TAG_NAME)
        self.assertEqual(c["counted_tree"], COUNTED_TREE)
        self.assertEqual(c["counted_verdict"], "green")
        self.assertEqual(
            c["counted_passed"] + c["counted_failed"]
            + c["counted_skipped"], c["counted_ran"])

    def test_release_notes_carry_the_census(self):
        notes = render_release_notes(_census(GREEN))
        self.assertTrue(notes.startswith("# Samverk v1.0"))
        self.assertIn("400 of 416", notes)
        self.assertIn("0 failed", notes)
        self.assertIn("Honest remainders", notes)

    def test_remainder_names_every_failure_and_no_tag(self):
        text = render_remainder(RED)
        self.assertIn("was NOT placed", text)
        for name in RED.failures:
            self.assertIn(name, text)
        self.assertNotIn("Tag placed", text)


class DocumentConsistencyTests(unittest.TestCase):
    def test_doc_records_verdict_and_consistent_tag_state(self):
        text = DOC.read_text(encoding="utf-8")
        m = re.search(
            r"Counted: Ran (\d+) / Passed (\d+) / Failed (\d+)"
            r" / Skipped (\d+)", text)
        self.assertIsNotNone(m, "counted line missing in V1_TAG.md")
        ran, passed, failed, skipped = (int(g) for g in m.groups())
        self.assertEqual(passed + failed + skipped, ran)
        placed = "Tag placed: v1.0 on " + COUNTED_TREE in text
        remainder = "Tag NOT placed" in text
        self.assertTrue(placed != remainder,
                        "doc must state exactly one tag state")
        if placed:
            self.assertEqual(failed, 0,
                             "a placed tag requires 0 counted failures")
        self.assertIn("## Census", text)


if __name__ == "__main__":
    unittest.main()
