"""S-407 battery — dependency replaceability register. Real runs only."""
import os, subprocess, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from samverk.dependency_replaceability import OSES, REGISTER, audit_tree, non_stdlib_imports

class RegisterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = audit_tree(ROOT)
    def test_audit_clean_no_defects(self):
        self.assertEqual(self.r["defects"], [])
        self.assertTrue(self.r["clean"])
    def test_every_dep_names_path_per_os(self):
        for d in REGISTER:
            self.assertEqual(sorted(dict(d.per_os)), sorted(OSES), d.name)
            for os_name in OSES:
                self.assertTrue(d.path_for(os_name).strip(), f"{d.name}/{os_name}")
    def test_no_irreplaceable(self):
        self.assertTrue(all(d.replaceable for d in REGISTER))
    def test_roadmap_named_deps_present(self):
        names = {d.name for d in REGISTER}
        for want in ("git", "cryptography", "sqlite3 / libsqlite3"):
            self.assertIn(want, names)
    def test_only_nonstdlib_import_is_cryptography(self):
        self.assertEqual(non_stdlib_imports(ROOT), {"cryptography"})
        self.assertEqual(self.r["non_stdlib_imports"], ["cryptography"])
    def test_allowed_programs_registered(self):
        self.assertEqual(self.r["allowed_programs"], ["git", "gpg"])
    def test_pyproject_deps_registered(self):
        self.assertEqual(self.r["pyproject_dependencies"], ["cryptography"])
    def test_sqlite_in_use_and_registered(self):
        self.assertTrue(self.r["sqlite_in_use"])
    def test_register_size(self):
        self.assertEqual(len(REGISTER), 7)
    def test_tool_exits_zero(self):
        out = subprocess.run([sys.executable, "tools/run_dependency_replaceability.py"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("VERDICT: CLEAN", out.stdout)

if __name__ == "__main__":
    unittest.main()
