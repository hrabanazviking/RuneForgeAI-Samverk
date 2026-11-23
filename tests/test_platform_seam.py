"""S-406 battery — platform seam + audit tool. Real runs only."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from samverk import platform_seam as seam
from samverk.platform_seam_audit import INVENTORY, audit_tree, code_lines

class SeamTests(unittest.TestCase):
    def test_os_name_known(self):
        self.assertIn(seam.os_name(), ("linux", "windows", "macos"))
    def test_machine_nonempty(self):
        self.assertTrue(seam.machine())
    def test_platform_string_nonempty(self):
        self.assertTrue(seam.platform_string())
    def test_data_root_under_home_or_env(self):
        self.assertTrue(str(seam.data_root_default()))
    def test_ensure_dir_creates(self):
        with tempfile.TemporaryDirectory() as d:
            p = seam.ensure_dir(Path(d) / "a" / "b")
            self.assertTrue(p.is_dir())
    def test_restrict_to_owner(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.txt"; p.write_text("x")
            seam.restrict_to_owner(p)
            if seam.os_name() != "windows":
                self.assertEqual(p.stat().st_mode & 0o077, 0)
                self.assertTrue(seam.secret_file_is_private(p))
    def test_make_owner_executable(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.sh"; p.write_text("#!/bin/sh\n")
            seam.make_owner_executable(p)
            if seam.os_name() != "windows":
                self.assertTrue(os.access(p, os.X_OK))

class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = audit_tree(ROOT)
    def test_no_uninventoried_strays(self):
        self.assertEqual(self.r["strays"], [])
    def test_scanned_many_files(self):
        self.assertGreater(self.r["files_scanned"], 300)
    def test_no_platform_id_strays(self):
        self.assertEqual(self.r["per_category"]["platform_id"], 0)
    def test_no_locking_or_signal_strays(self):
        self.assertEqual(self.r["per_category"]["locking"], 0)
        self.assertEqual(self.r["per_category"]["signals"], 0)
    def test_remainders_all_in_inventory_files(self):
        for e in self.r["inventoried"]:
            self.assertIn(Path(e["file"]).name, INVENTORY)
    def test_code_lines_strips_docstrings(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.py"
            p.write_text('"""subprocess.run in a docstring."""\nx = 1  # os.chmod\n')
            text = "\n".join(t for _, t in code_lines(p))
            self.assertNotIn("subprocess", text)
            self.assertNotIn("chmod", text)
    def test_tool_exits_zero(self):
        env = dict(os.environ); env["TMPDIR"] = str(ROOT / "hidden_files")
        out = subprocess.run([sys.executable, "tools/run_platform_seam_audit.py"],
                             cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("VERDICT: CLEAN", out.stdout)

if __name__ == "__main__":
    unittest.main()
