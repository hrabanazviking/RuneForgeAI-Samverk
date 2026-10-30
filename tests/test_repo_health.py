"""S-075 acceptance battery: corruption behaviour.

Acceptance (roadmap S-075): a damaged repo reads as damaged
(honest error), never as empty; corruption-injection test.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk.objects import ObjectReader
from samverk.repo_health import (RepoDamagedError, assess_repository,
                                 ensure_readable)

def git(repo: Path, *args: str, input_bytes=None) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

def make_repo(base: Path) -> tuple[Path, str]:
    repo = base / "r.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(repo)],
                   check=True, capture_output=True)
    blob = git(repo, "hash-object", "-w", "--stdin", input_bytes=b"payload\n")
    tree = git(repo, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
    commit = git(repo, "commit-tree", tree, input_bytes=b"first\n")
    git(repo, "update-ref", "refs/heads/main", commit)
    return repo, blob

def corrupt_loose_object(repo: Path, oid: str) -> None:
    obj = repo / "objects" / oid[0:2] / oid[2:]
    data = bytearray(obj.read_bytes())
    # Flip bytes well inside the zlib stream: the object can
    # no longer inflate to what its name promises.
    for i in range(2, min(len(data), 12)):
        data[i] ^= 0xFF
    obj.write_bytes(bytes(data))

class RepoHealthTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.base = Path(self._td.name)

    def test_a_healthy_repo_reads_healthy(self):
        repo, _ = make_repo(self.base)
        report = assess_repository(repo)
        self.assertEqual(report.status, "healthy")
        self.assertTrue(report.readable)
        self.assertEqual(report.ref_count, 1)
        self.assertEqual(ensure_readable(repo).status, "healthy")

    def test_an_empty_repo_reads_empty_not_damaged(self):
        repo = self.base / "blank.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(repo)],
                       check=True, capture_output=True)
        report = assess_repository(repo)
        self.assertEqual(report.status, "empty")
        self.assertTrue(report.readable)

    def test_corruption_injection_reads_damaged_never_empty(self):
        repo, blob = make_repo(self.base)
        corrupt_loose_object(repo, blob)
        report = assess_repository(repo)
        self.assertEqual(report.status, "damaged", report)
        self.assertFalse(report.readable)
        self.assertTrue(report.detail)
        with self.assertRaises(RepoDamagedError) as caught:
            ensure_readable(repo)
        self.assertEqual(caught.exception.reason, "damaged")
        # And the object seam agrees: reading the damaged blob
        # is an error, never empty content.
        with self.assertRaises(Exception):
            ObjectReader(repo).read_blob(blob)

    def test_a_truncated_object_reads_damaged(self):
        repo, blob = make_repo(self.base)
        obj = repo / "objects" / blob[0:2] / blob[2:]
        obj.write_bytes(obj.read_bytes()[:4])
        self.assertEqual(assess_repository(repo).status, "damaged")

    def test_missing_and_not_a_repository_are_their_own_names(self):
        self.assertEqual(
            assess_repository(self.base / "nope.git").status, "missing")
        plain = self.base / "plain"; plain.mkdir()
        self.assertEqual(assess_repository(plain).status, "not_a_repository")
        with self.assertRaises(RepoDamagedError):
            ensure_readable(self.base / "nope.git")

    def test_a_damaged_head_reads_damaged(self):
        repo, _ = make_repo(self.base)
        (repo / "HEAD").write_text("this is not a ref\n")
        report = assess_repository(repo)
        self.assertEqual(report.status, "damaged")
        self.assertFalse(report.readable)

if __name__ == "__main__":
    unittest.main()
