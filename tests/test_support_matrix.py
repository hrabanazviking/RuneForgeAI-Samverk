"""S-405 -- Support matrix battery.

Proves the matrix is the promise written down and
nothing more: the census counts hold, the four
primary OS x CPU cells of research 45 are present,
the Raspberry Pi 5 floor is named, every cell reads
NOT PROVEN at ratification (no platform claimed
proven without a real run on that platform), every
cell names the slice and counted run that can flip
it, no overclaim phrase appears anywhere, the matrix
document on disk carries every cell, research file
45 carries the ratified section with every cell,
and the schema/taxonomy pins stand.

Counted with: python3 -m unittest tests.test_support_matrix
"""
from __future__ import annotations

import unittest
from pathlib import Path

from samverk import db, taxonomy
from samverk.support_matrix import (
    DIMENSIONS, EXPECTED_COUNT, MATRIX_CELLS,
    OVERCLAIM_PHRASES, RESEARCH_FILE, SECTION_BEGIN,
    STATUSES, audit_matrix, cells_by_dimension,
    judge_matrix, matrix_counts, render_matrix,
    render_matrix_log, render_matrix_section)

ROOT = Path(__file__).resolve().parent.parent
BY_ID = {c.cell_id: c for c in MATRIX_CELLS}


class MatrixCensusTests(unittest.TestCase):
    def test_census_count_and_split(self):
        counts = matrix_counts()
        self.assertEqual(counts["total"], EXPECTED_COUNT)
        self.assertEqual(counts["total"], 12)
        self.assertEqual(counts["os_cpu"], 4)
        self.assertEqual(counts["filesystem"], 2)
        self.assertEqual(counts["deployment"], 2)
        self.assertEqual(counts["service"], 3)
        self.assertEqual(counts["reach"], 1)
        self.assertEqual(judge_matrix(), ())

    def test_every_cell_names_platform_floor_and_proof(self):
        for cell in MATRIX_CELLS:
            self.assertIn(cell.dimension, DIMENSIONS)
            self.assertIn(cell.status, STATUSES)
            for field in (cell.title, cell.platform,
                          cell.cpu, cell.floor,
                          cell.proof_slice, cell.proof,
                          cell.note):
                self.assertTrue(field.strip(), cell.cell_id)

    def test_ids_unique(self):
        self.assertEqual(len(BY_ID), len(MATRIX_CELLS))

    def test_pins_no_new_migration_or_event(self):
        self.assertEqual(db.MIGRATIONS[-1][0], 140)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)


class HonestStatusTests(unittest.TestCase):
    def test_every_cell_not_proven_at_ratification(self):
        counts = matrix_counts()
        self.assertEqual(counts["not_proven"], counts["total"])
        for cell in MATRIX_CELLS:
            self.assertEqual(cell.status, "not_proven", cell.cell_id)

    def test_primary_cells_are_research45s_four(self):
        primaries = {c.cell_id for c in cells_by_dimension("os_cpu")}
        self.assertEqual(primaries, {"linux-x86-64",
            "linux-arm64-pi5", "windows-x86-64", "macos-arm64"})

    def test_pi5_is_the_floor(self):
        cell = BY_ID["linux-arm64-pi5"]
        self.assertIn("Raspberry Pi 5", cell.floor)
        self.assertEqual(cell.proof_slice, "S-415")

    def test_flip_slices_named_per_cell(self):
        self.assertEqual(BY_ID["windows-x86-64"].proof_slice, "S-416")
        self.assertEqual(BY_ID["macos-arm64"].proof_slice, "S-416")
        self.assertEqual(BY_ID["fs-case-sensitive"].proof_slice, "S-408")
        self.assertEqual(BY_ID["fs-case-insensitive"].proof_slice, "S-408")
        self.assertEqual(BY_ID["service-windows"].proof_slice, "S-410")
        self.assertEqual(BY_ID["service-launchd"].proof_slice, "S-411")
        self.assertEqual(BY_ID["service-systemd"].proof_slice, "S-412")
        self.assertEqual(BY_ID["browser-device-reach"].proof_slice, "S-414")

    def test_no_overclaim_anywhere(self):
        blob = (render_matrix() + render_matrix_log()
                + render_matrix_section()).lower()
        for phrase in OVERCLAIM_PHRASES:
            self.assertNotIn(phrase, blob)
        for cell in MATRIX_CELLS:
            self.assertNotIn("proven", cell.status.replace(
                "not_proven", ""))

    def test_unpromised_combos_have_no_cell(self):
        for cell in MATRIX_CELLS:
            combo = (cell.platform, cell.cpu)
            self.assertNotEqual(combo, ("Windows", "ARM64"))
            self.assertNotEqual(combo, ("macOS", "x86-64"))


class MatrixDocumentTests(unittest.TestCase):
    def test_audit_against_disk_passes(self):
        self.assertEqual(audit_matrix(ROOT), ())

    def test_rendered_matrix_carries_every_cell(self):
        text = render_matrix()
        for cell in MATRIX_CELLS:
            self.assertIn(cell.cell_id, text)
        self.assertIn("NOT PROVEN", text)
        self.assertIn("Raspberry Pi 5", text)

    def test_research45_carries_ratified_section(self):
        text = (ROOT / RESEARCH_FILE).read_text(encoding="utf-8")
        self.assertIn(SECTION_BEGIN, text)
        self.assertIn("## Support matrix (ratified at S-405)", text)
        for cell in MATRIX_CELLS:
            self.assertIn(cell.cell_id, text)
        section = render_matrix_section()
        for cell in MATRIX_CELLS:
            self.assertIn(cell.cell_id, section)

    def test_rendered_log_counts_match(self):
        log = render_matrix_log()
        self.assertIn("Matrix cells judged: 12", log)
        self.assertIn("RATIFIED", log)
        doc = (ROOT / "docs" / "SUPPORT_MATRIX.md")
        self.assertTrue(doc.exists())
        self.assertIn("windows-x86-64", doc.read_text())


if __name__ == "__main__":
    unittest.main()
