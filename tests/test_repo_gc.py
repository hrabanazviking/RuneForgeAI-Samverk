"""S-059 acceptance battery: garbage-collection scheduling.

Acceptance (roadmap S-059): `git gc` policy per repo
size/activity, run off the request path; no request waits on gc.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.repo_gc import GCScheduler, count_loose_objects, gc_policy, DAY
from samverk.repositories import RepositoryStore

class GCTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.repo = self.repos.create_repository(self.owner.id, "volmarr", "gcrepo")
        self.path = self.repos.path_for("volmarr", "gcrepo")
        self.clock = [1_700_000_000]
        self.gc = GCScheduler(self.conn, self.data_root, self.repos,
                              time_fn=lambda: self.clock[0])

    def _add_loose(self, n):
        for i in range(n):
            payload = self.data_root / f"p{i}.bin"
            payload.write_bytes(f"blob-{i}-".encode() * 20)
            subprocess.run(["git", f"--git-dir={self.path}", "hash-object", "-w", str(payload)],
                           capture_output=True, check=True)

    def test_policy_tiers(self):
        self.assertFalse(gc_policy(total_bytes=10**9, loose_objects=0).needed)
        small = gc_policy(total_bytes=100, loose_objects=3)
        self.assertEqual((small.interval_seconds, small.level), (30 * DAY, "standard"))
        medium = gc_policy(total_bytes=100, loose_objects=60)
        self.assertEqual(medium.interval_seconds, 7 * DAY)
        large = gc_policy(total_bytes=100, loose_objects=600)
        self.assertEqual((large.interval_seconds, large.level), (DAY, "aggressive"))
        self.assertEqual(gc_policy(total_bytes=40 * 1024 * 1024, loose_objects=1).level,
                         "aggressive")

    def test_assess_schedules_but_never_runs_gc(self):
        self._add_loose(5)
        before = count_loose_objects(self.path)
        self.assertEqual(before, 5)
        state = self.gc.assess("volmarr", "gcrepo")
        # Scheduling is request-safe: it recorded a due time and
        # spawned nothing — the loose objects are still loose.
        self.assertEqual(count_loose_objects(self.path), before)
        self.assertEqual(state.runs, 0)
        self.assertIn(self.repo.id, self.gc.due_repo_ids())

    def test_run_due_packs_loose_objects_and_records(self):
        self._add_loose(5)
        self.gc.assess("volmarr", "gcrepo")
        results = self.gc.run_due()
        self.assertEqual(results, [(self.repo.id, "ok")])
        self.assertEqual(count_loose_objects(self.path), 0)
        pack = self.path / "objects" / "pack"
        self.assertTrue(any(p.suffix == ".pack" for p in pack.iterdir()))
        state = self.gc.state_for(self.repo.id)
        self.assertEqual((state.runs, state.last_status), (1, "ok"))
        # Not due again until the policy interval passes.
        self.assertEqual(self.gc.due_repo_ids(), [])
        self.clock[0] += 31 * DAY
        self.assertIn(self.repo.id, self.gc.due_repo_ids())

    def test_quiet_repo_is_not_due(self):
        state = self.gc.assess("volmarr", "gcrepo")  # no loose objects
        self.assertEqual(self.gc.due_repo_ids(), [])
        self.assertGreater(state.next_due_at, self.clock[0])

if __name__ == "__main__":
    unittest.main()
