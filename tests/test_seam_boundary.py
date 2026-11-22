"""S-375 battery — the honest boundary document.

The boundary is only honest if it is counted and
checked: the statements are all present, the operator
document carries every one of them, and the standing
code still honours the load-bearing claims (seam off
by default, the contract's no-federation line, no
federation surface in the package).
"""
import unittest
from pathlib import Path

from samverk.seam_boundary import boundary_statements, check_boundary

DOC = Path(__file__).resolve().parent.parent / "docs" / "SEAM_BOUNDARY.md"


class SeamBoundaryTests(unittest.TestCase):
    def test_the_boundary_is_counted(self):
        ids = [b["id"] for b in boundary_statements()]
        self.assertEqual(ids, ["no_federation",
                               "no_cross_village_identity",
                               "no_samtal_requirement"])

    def test_the_document_carries_every_statement(self):
        text = DOC.read_text().lower()
        for phrase in ("no federation",
                       "no cross-village identity",
                       "no samtal requirement"):
            self.assertIn(phrase, text)

    def test_the_code_honours_the_boundary(self):
        report = check_boundary()
        self.assertTrue(report["ok"], report)
        self.assertEqual([c["name"] for c in report["checks"]],
                         ["seam_disabled_by_default",
                          "contract_names_no_federation",
                          "no_federation_surface"])


if __name__ == "__main__":
    unittest.main()
