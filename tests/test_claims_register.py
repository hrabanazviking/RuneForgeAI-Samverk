"""S-023 acceptance battery: claims register.

Acceptance (roadmap S-023): every security claim in the README
maps to a test or reads NOT PROVEN — *register complete for
Part I claims.* This battery keeps the register honest
mechanically: structure, evidence existence, anchor coverage,
and the no-Docker tree scan C-08 rests on.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "docs" / "CLAIMS_REGISTER.md"

# The tracked claim anchors: phrases the register must cover,
# drawn from the claims the README actually makes.
ANCHORS = (
    "database leak is not a credential leak",
    "threat model is written before the features",
    "audit log detects tampering",
    "cross-site forgery",
    "output-escaping seam",
    "opaque id",
    "no Samtal to run",
    "No Docker, ever",
    "unmodified git client",
    "Raspberry Pi",
    "Visual Design Lawbook",
    "mirrors Volmarr's original repositories",
)


def _rows() -> list[list[str]]:
    rows = []
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if re.match(r"^\| C-\d+ \|", line):
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows.append(cells)
    return rows


class RegisterShapeTests(unittest.TestCase):
    def test_register_covers_every_tracked_anchor(self):
        text = REGISTER.read_text(encoding="utf-8")
        for anchor in ANCHORS:
            self.assertIn(anchor, text, msg=anchor)

    def test_rows_are_complete_and_ids_unique(self):
        rows = _rows()
        self.assertGreaterEqual(len(rows), len(ANCHORS))
        ids = [r[0] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            self.assertEqual(len(row), 4, msg=str(row))
            status = row[2]
            self.assertTrue(
                status == "PROVEN" or status == "NOT PROVEN"
                or status.startswith("PROVEN (")
                or status.startswith("NOT PROVEN ("),
                msg=f"{row[0]}: bad status {status!r}")

    def test_proven_rows_name_real_evidence(self):
        for row in _rows():
            claim_id, _, status, evidence = row
            if status.startswith("NOT PROVEN"):
                self.assertIn("Part", evidence,
                              msg=f"{claim_id}: NOT PROVEN row must name its part")
                continue
            test_files = re.findall(r"tests/test_\w+\.py", evidence)
            doc_files = re.findall(r"document: (\S+)", evidence)
            self.assertTrue(
                test_files or doc_files,
                msg=f"{claim_id}: PROVEN row names no evidence")
            for rel in test_files:
                self.assertTrue((ROOT / rel).is_file(),
                                msg=f"{claim_id}: missing {rel}")
            for rel in doc_files:
                self.assertTrue((ROOT / rel).is_file(),
                                msg=f"{claim_id}: missing {rel}")


class NoDockerTreeTests(unittest.TestCase):
    def test_no_container_artifacts_in_the_tree(self):
        offenders = []
        for path in ROOT.rglob("*"):
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if path.is_file() and (
                path.name in {"Dockerfile", "docker-compose.yml",
                              "docker-compose.yaml", ".dockerignore"}
                or path.name.startswith("Dockerfile.")
            ):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
