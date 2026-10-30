"""S-017 acceptance battery: dependency policy.

Acceptance (roadmap S-017): stdlib-first register; each admitted
dependency has a reason line and a pinned version — *the register
is complete and checked in CI-style battery.* This battery is
that check: pyproject, the code register, the doc register, and
every actual import in the tree must all agree.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.dependencies import ADMITTED_DEPENDENCIES

ROOT = Path(__file__).resolve().parent.parent


def _declared_runtime_dependencies() -> list[str]:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)
    return list(data["project"].get("dependencies", []))


def _imported_top_levels(*dirs: Path) -> set[str]:
    names: set[str] = set()
    for directory in dirs:
        for py in sorted(directory.rglob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        names.add(alias.name.split(".", 1)[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        names.add(node.module.split(".", 1)[0])
    return names


class RegisterAgreementTests(unittest.TestCase):
    def test_pyproject_matches_the_code_register_exactly(self):
        declared = _declared_runtime_dependencies()
        expected = sorted(
            f"{dep.distribution}{dep.pin}" for dep in ADMITTED_DEPENDENCIES)
        normalised = sorted(
            re.sub(r"\s+", "", d) for d in declared)
        self.assertEqual(normalised, expected)

    def test_every_admission_has_a_reason_and_an_exact_pin(self):
        for dep in ADMITTED_DEPENDENCIES:
            self.assertTrue(dep.reason.strip(), msg=dep.distribution)
            self.assertTrue(dep.pin.startswith("=="), msg=dep.distribution)
            self.assertTrue(dep.import_name, msg=dep.distribution)

    def test_doc_register_names_every_admission(self):
        doc = (ROOT / "docs" / "DEPENDENCY_REGISTER.md").read_text(
            encoding="utf-8")
        self.assertIn("stdlib-first", doc)
        for dep in ADMITTED_DEPENDENCIES:
            self.assertIn(dep.distribution, doc)
            self.assertIn(dep.pin, doc)


class ImportScanTests(unittest.TestCase):
    def test_no_unregistered_third_party_imports_anywhere(self):
        admitted = {dep.import_name for dep in ADMITTED_DEPENDENCIES}
        allowed = set(sys.stdlib_module_names) | {"samverk"} | admitted
        imported = _imported_top_levels(ROOT / "samverk", ROOT / "tests")
        unregistered = imported - allowed
        self.assertEqual(
            unregistered, set(),
            msg=f"unregistered imports: {sorted(unregistered)} — "
                "admit them in samverk/dependencies.py (S-017) or "
                "remove the import")

    def test_the_scan_actually_sees_the_package(self):
        # Guard against a vacuous pass: the scan must find the
        # stdlib modules the package plainly uses.
        imported = _imported_top_levels(ROOT / "samverk")
        self.assertIn("sqlite3", imported)
        self.assertIn("hashlib", imported)


if __name__ == "__main__":
    unittest.main()
