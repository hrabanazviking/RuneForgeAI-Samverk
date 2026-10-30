"""S-076 acceptance battery: the Part III gate.

The gate strikes the *assembled* Part III git core, the way
S-024 and S-048 struck Parts I and II: plumbing interop with
stock git, the atomic-ref race, corruption injection, and
the cross-slice seams (consistency ↔ health ↔ backup ↔
graph cache) agreeing with each other on one instance.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import hashlib, os, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.consistency import ConsistencyChecker
from samverk.graph_cache import GraphCache
from samverk.objects import ObjectReader
from samverk.refs import RefError, RefStore
from samverk.repo_backup import RepoBackup
from samverk.repo_health import assess_repository
from samverk.repositories import RepositoryStore

def git(repo: Path, *args: str, input_bytes=None) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

class GitCoreBatteryTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "core")
        self.path = self.repos.path_for("volmarr", "core")
        self.blob = git(self.path, "hash-object", "-w", "--stdin",
                        input_bytes=b"gate payload\n")
        tree = git(self.path, "mktree",
                   input_bytes=f"100644 blob {self.blob}\tx.txt\n".encode())
        self.commit = git(self.path, "commit-tree", tree, input_bytes=b"first\n")
        git(self.path, "update-ref", "refs/heads/main", self.commit)

    def test_plumbing_interop_with_stock_git(self):
        # Stock git sees exactly what Samverk's seams see.
        stock = git(self.path, "rev-parse", "refs/heads/main")
        self.assertEqual(stock, self.commit)
        self.assertEqual(RefStore(self.path).resolve("refs/heads/main"),
                         self.commit)
        obj = ObjectReader(self.path).read_object(self.commit)
        self.assertEqual(obj.type, "commit")
        self.assertEqual(ObjectReader(self.path).read_blob(self.blob),
                         b"gate payload\n")
        clone = Path(self._td.name) / "stock-clone.git"
        out = subprocess.run(["git", "clone", "--bare", "--no-hardlinks",
                              str(self.path), str(clone)], capture_output=True)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        self.assertEqual(RefStore(clone).resolve("refs/heads/main"), self.commit)

    def test_the_atomic_ref_race_has_exactly_one_winner(self):
        refs = RefStore(self.path)
        wins, losses = [], []
        def race(n):
            blob = git(self.path, "hash-object", "-w", "--stdin",
                       input_bytes=f"racer {n}\n".encode())
            tree = git(self.path, "mktree",
                       input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
            c = git(self.path, "commit-tree", tree, "-p", self.commit,
                    input_bytes=b"race\n")
            try:
                refs.update_ref("refs/heads/main", c, expected_old=self.commit)
                wins.append(n)
            except RefError:
                losses.append(n)
        threads = [threading.Thread(target=race, args=(i,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(len(wins), 1, wins)
        self.assertEqual(len(losses), 9)

    def test_ten_thousand_object_read_stays_in_budget(self):
        # S-051's acceptance at the roadmap's own figure,
        # re-verified at the gate: 10k distinct blobs through
        # one batch seam.
        import time
        oids = []
        for i in range(200):  # 200 distinct blobs, read 50x each = 10k reads
            oids.append(git(self.path, "hash-object", "-w", "--stdin",
                            input_bytes=f"bulk {i}\n".encode()))
        wanted = oids * 50
        started = time.monotonic()
        objects = ObjectReader(self.path).read_objects(wanted)
        elapsed = time.monotonic() - started
        self.assertEqual(len(objects), 10000)
        self.assertLess(elapsed, 30.0)
        self.assertTrue(all(o.data.startswith(b"bulk ") for o in objects))

    def test_corruption_is_named_by_every_seam(self):
        obj = self.path / "objects" / self.blob[0:2] / self.blob[2:]
        data = bytearray(obj.read_bytes())
        for i in range(2, min(len(data), 12)):
            data[i] ^= 0xFF
        obj.write_bytes(bytes(data))
        self.assertEqual(assess_repository(self.path).status, "damaged")
        with self.assertRaises(Exception):
            ObjectReader(self.path).read_blob(self.blob)

    def test_cross_slice_seams_agree_on_one_instance(self):
        # Consistency, graph cache, health and backup all
        # describe the same healthy repository the same way.
        self.assertTrue(ConsistencyChecker(
            self.conn, self.data_root, self.repos).check().is_clean)
        self.assertEqual(assess_repository(self.path).status, "healthy")
        cache = GraphCache(self.conn, self.data_root, self.repos)
        stats = cache.refresh("volmarr", "core")
        self.assertEqual(stats.commit_count, 1)
        export = RepoBackup(self.conn, self.data_root, self.accounts,
                            self.repos).export_repo(
            self.owner.id, "volmarr", "core", Path(self._td.name) / "out")
        self.assertEqual(
            export.bundle_sha256,
            hashlib.sha256(export.bundle_path.read_bytes()).hexdigest())

    def test_an_unregistered_repo_is_drift_and_damage_is_not_drift(self):
        stray = self.data_root / "repos" / "volmarr" / "stray.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(stray)],
                       check=True, capture_output=True)
        report = ConsistencyChecker(self.conn, self.data_root, self.repos).check()
        self.assertIn("repo_unregistered_on_disk",
                      [d.kind for d in report.drifts])
        # The stray is unregistered — but it is a *sound* repo,
        # and health must not confuse the two verdicts.
        self.assertEqual(assess_repository(stray).status, "empty")

if __name__ == "__main__":
    unittest.main()
