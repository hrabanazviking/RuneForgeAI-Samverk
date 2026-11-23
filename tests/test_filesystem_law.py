"""S-408 battery — filesystem law. Real runs only.

Host kind is PROBED, never assumed: on this host the probe is
reported as measured. The insensitive kind is exercised through
the honest simulation (SimulatedInsensitiveDirectory) plus the
pure name-law, which is platform-independent by construction.
A real insensitive-filesystem run is NOT claimed here.
"""
import subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from samverk.filesystem_law import (FilesystemLawError, SimulatedInsensitiveDirectory,
    audit_directory, check_names, find_case_collisions, fold_key, plan_storage, probe_case_sensitive)

class NameLawTests(unittest.TestCase):
    def test_fold_key_casefolds(self):
        self.assertEqual(fold_key("ReadMe.TXT"), "readme.txt")
        self.assertEqual(fold_key("STRASSE"), "strasse")
    def test_no_collision_clean_set(self):
        self.assertEqual(find_case_collisions(["alpha", "Beta", "gamma.txt"]), ())
        self.assertEqual(check_names(["gamma.txt", "alpha", "Beta"]), ("Beta", "alpha", "gamma.txt"))
    def test_collision_detected_deterministically(self):
        want = (("README", "ReadMe"),)
        self.assertEqual(find_case_collisions(["ReadMe", "README"]), want)
        self.assertEqual(find_case_collisions(["README", "ReadMe"]), want)  # order-independent
    def test_collision_refused_with_stable_reason(self):
        with self.assertRaises(FilesystemLawError) as cm:
            check_names(["Foo.git", "foo.git"])
        self.assertEqual(cm.exception.reason, "case_collision")
    def test_exact_duplicate_is_its_own_reason(self):
        with self.assertRaises(FilesystemLawError) as cm:
            check_names(["same", "same"])
        self.assertEqual(cm.exception.reason, "duplicate_name")
    def test_multiple_collision_groups_sorted(self):
        got = find_case_collisions(["b", "B", "a", "A", "ok"])
        self.assertEqual(got, (("A", "a"), ("B", "b")))
    def test_plan_storage_refuses_collision_as_whole(self):
        with self.assertRaises(FilesystemLawError):
            plan_storage(["Keep", "keep", "other"])
    def test_plan_storage_lawful_set(self):
        self.assertEqual(plan_storage(["Repo", "meta.json"]), {"Repo": "repo", "meta.json": "meta.json"})

class RealFilesystemTests(unittest.TestCase):
    def test_probe_matches_manual_probe(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); (d / "ProbeA").write_text("x"); (d / "probea").write_text("y")
            manual = len(list(d.iterdir())) == 2
            self.assertEqual(probe_case_sensitive(d), manual)
    def test_probe_leaves_no_files(self):
        with tempfile.TemporaryDirectory() as td:
            probe_case_sensitive(td)
            self.assertEqual(list(Path(td).iterdir()), [])
    def test_audit_clean_dir(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "one.txt").write_text("1")
            r = audit_directory(td)
            self.assertTrue(r["clean"]); self.assertEqual(r["collisions"], [])
    def test_audit_finds_on_disk_collision_when_sensitive(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            if not probe_case_sensitive(d):
                self.skipTest("host FS insensitive: on-disk pair cannot coexist")
            (d / "Meta.json").write_text("1"); (d / "meta.json").write_text("2")
            r = audit_directory(d)
            self.assertFalse(r["clean"])
            self.assertEqual(r["collisions"], [["Meta.json", "meta.json"]])

class SimulatedInsensitiveTests(unittest.TestCase):
    """The insensitive kind, SIMULATED honestly on a sensitive host."""
    def test_simulation_merges_case_variants(self):
        sim = SimulatedInsensitiveDirectory()
        self.assertFalse(sim.store("ReadMe", "first"))
        self.assertTrue(sim.store("readme", "second"))  # same slot: would overwrite
        self.assertEqual(len(sim), 1)
    def test_name_law_prevents_the_simulated_overwrite(self):
        # The law refuses the pair BEFORE storage, on either kind.
        with self.assertRaises(FilesystemLawError):
            plan_storage(["ReadMe", "readme"])
    def test_lawful_set_stores_fully_in_simulation(self):
        sim = SimulatedInsensitiveDirectory()
        for n in plan_storage(["Alpha", "beta.txt"]):
            self.assertFalse(sim.store(n, "data"))
        self.assertEqual(len(sim), 2)
    def test_tool_exits_zero(self):
        out = subprocess.run([sys.executable, "tools/run_filesystem_law.py"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("VERDICT: CLEAN", out.stdout)

if __name__ == "__main__":
    unittest.main()
