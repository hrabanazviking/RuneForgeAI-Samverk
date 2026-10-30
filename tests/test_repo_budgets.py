"""S-073 acceptance battery: large-repository budgets.

Acceptance (roadmap S-073): clone of the reference big repo
completes on Pi-class hardware within the stated budget
(measured, Part XXI re-verifies). This battery measures on
the hardware it runs on and claims only that class: the
Pi-class cell is NOT PROVEN here — it is named in the code
and in the map, and Part XXI/XXII own its proof.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk.repo_budgets import (CLONE_BUDGETS_SECONDS, REFERENCE_BLOBS,
                                  REFERENCE_COMMITS, hardware_class,
                                  measure_local_clone)
from samverk.refs import RefStore

def build_reference_repo(path: Path, commits: int, files_per_commit: int) -> str:
    """Build the reference shape fast, with git fast-import
    (test-side tooling; Samverk's own seams are not used to
    *build* fixtures, exactly as earlier batteries use git
    directly). Returns HEAD's commit id."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", "-b", "main", str(path)],
                   check=True, capture_output=True)
    marks = []
    stream = []
    blob_mark = 0
    for c in range(commits):
        for f in range(files_per_commit):
            blob_mark += 1
            data = (f"reference payload {c}/{f}\n" * 8).encode()
            stream.append(f"blob\nmark :{blob_mark}\ndata {len(data)}\n".encode() + data)
            marks.append((c, f, blob_mark))
    # Commits are built as one fast-import stream segment each
    # reusing incrementally added files.
    by_commit: dict[int, list[tuple[int, int]]] = {}
    for c, f, m in marks:
        by_commit.setdefault(c, []).append((f, m))
    parts: list[bytes] = list(stream)
    for c in range(commits):
        lines = [f"commit refs/heads/main\nmark :{100000 + c}\n"
                 f"author A U Thor <a@e.c> 1700000000 +0000\n"
                 f"committer A U Thor <a@e.c> 1700000000 +0000\n"
                 f"data 4\nmsg\n"]
        if c:
            lines.append(f"from :{100000 + c - 1}\n")
        for f, m in by_commit[c]:
            lines.append(f"M 100644 :{m} file-{c}-{f}.txt\n")
        parts.append("".join(lines).encode())
    proc = subprocess.run(["git", f"--git-dir={path}", "fast-import", "--quiet"],
                          input=b"".join(parts), capture_output=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr.decode())
    return RefStore(path).resolve("refs/heads/main")

class RepoBudgetTests(unittest.TestCase):
    def test_the_reference_shape_and_budgets_are_stated(self):
        self.assertEqual(REFERENCE_COMMITS, 1000)
        self.assertEqual(REFERENCE_BLOBS, 2000)
        for cls in ("server_x86_64", "laptop_x86_64", "pi_class_arm"):
            self.assertIn(cls, CLONE_BUDGETS_SECONDS)
        self.assertIn(hardware_class(), CLONE_BUDGETS_SECONDS)

    def test_clone_of_the_reference_repo_within_budget_here(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # The full reference shape: 1000 commits x 2 files.
            src = root / "ref.git"
            head = build_reference_repo(src, REFERENCE_COMMITS, 2)
            self.assertIsNotNone(head)
            measurement = measure_local_clone(src, root / "clone.git")
            self.assertTrue(measurement.within_budget, measurement)
            self.assertGreater(measurement.total_bytes, 0)
            # The clone is real and complete: HEAD matches.
            self.assertEqual(
                RefStore(root / "clone.git").resolve("refs/heads/main"), head)
            self.assertEqual(measurement.hardware_class, hardware_class())

    def test_a_budget_is_enforced_not_assumed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "small.git"
            build_reference_repo(src, 5, 1)
            measurement = measure_local_clone(
                src, root / "clone.git", budget_seconds=0.0)
            self.assertFalse(measurement.within_budget)
            self.assertGreaterEqual(measurement.seconds, 0.0)

if __name__ == "__main__":
    unittest.main()
