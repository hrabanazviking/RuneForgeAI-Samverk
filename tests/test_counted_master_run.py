"""S-393 -- Counted master run battery.

The deliverable of S-393 is the counted run itself, reported
honestly in docs/COUNTED_MASTER_RUN.md. This battery proves the
report is internally consistent and complete: the per-shard
table sums to the headline counts, passed + failed + skipped
equals ran, every failure is named, and every named failure is
in the stale schema/taxonomy-pin class the report declares.

Counted with: python3 -m unittest tests.test_counted_master_run
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "COUNTED_MASTER_RUN.md"


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _headline(text: str) -> dict:
    m = re.search(
        r"Counted: Ran (\d+) / Passed (\d+) / Failed (\d+) / Skipped (\d+)",
        text)
    assert m is not None, "headline counted line missing"
    return {"ran": int(m.group(1)), "passed": int(m.group(2)),
            "failed": int(m.group(3)), "skipped": int(m.group(4))}


def _shard_rows(text: str) -> list:
    rows = []
    for m in re.finditer(
            r"^\| (\d{2}) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|$",
            text, re.M):
        rows.append(tuple(int(g) for g in m.groups()))
    return rows


def _failure_names(text: str) -> list:
    section = text.split("## Failures", 1)[1].split("## Skips", 1)[0]
    return re.findall(r"^- (tests\.test_\S+)$", section, re.M)


class CountedMasterRunTests(unittest.TestCase):
    def test_headline_arithmetic_holds(self):
        h = _headline(_text())
        self.assertEqual(h["passed"] + h["failed"] + h["skipped"], h["ran"])

    def test_shard_table_sums_to_headline(self):
        text = _text()
        h = _headline(text)
        rows = _shard_rows(text)
        self.assertEqual(len(rows), 8)
        self.assertEqual(sum(r[2] for r in rows), h["ran"])
        self.assertEqual(sum(r[3] for r in rows), h["skipped"])
        self.assertEqual(sum(r[4] for r in rows), h["failed"])

    def test_every_failure_is_named(self):
        text = _text()
        h = _headline(text)
        names = _failure_names(text)
        self.assertEqual(len(names), h["failed"])
        self.assertEqual(len(set(names)), len(names))

    def test_named_failures_are_the_declared_pin_class(self):
        for name in _failure_names(_text()):
            self.assertTrue(
                "taxonomy" in name or "pins" in name,
                "failure outside the declared pin class: " + name)

    def test_skips_are_named_with_reasons(self):
        text = _text()
        h = _headline(_text())
        section = text.split("## Skips", 1)[1].split("## Verdict", 1)[0]
        bullets = re.findall(r"^- (S-\d+ .+)$", section, re.M)
        self.assertEqual(len(bullets), h["skipped"])


if __name__ == "__main__":
    unittest.main()
