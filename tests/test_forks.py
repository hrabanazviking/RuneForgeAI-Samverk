"""S-055 acceptance battery: forking.

Acceptance (roadmap S-055): server-side clone with upstream
link recorded; fork counts and network listing.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.forks import ForkError, ForkStore
from samverk.repositories import RepositoryStore

def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args], capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()

class ForkTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.audit = AuditLog(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.third = self.accounts.register("tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts, audit=self.audit)
        self.forks = ForkStore(self.conn, self.data_root, self.accounts, self.repos, audit=self.audit)
        self.source = self.repos.create_repository(self.owner.id, "volmarr", "upstream", visibility="public")
        path = self.repos.path_for("volmarr", "upstream")
        blob = git(path, "hash-object", "-w", "--stdin", input_bytes=b"hello\n")
        tree = git(path, "mktree", input_bytes=f"100644 blob {blob}\thello.txt\n".encode())
        commit = git(path, "commit-tree", tree, input_bytes=b"first\n")
        git(path, "update-ref", "refs/heads/main", commit)
        self.commit = commit

    def test_fork_is_a_real_independent_clone_with_upstream_link(self):
        fork = self.forks.fork(self.other.id, "volmarr", "upstream")
        self.assertEqual(fork.fork_of_id, self.source.id)
        self.assertEqual(fork.owner, "yrsa")
        fpath = self.repos.path_for("yrsa", "upstream")
        self.assertEqual(git(fpath, "rev-parse", "refs/heads/main"), self.commit)
        # Independence: deleting a ref in the fork leaves upstream alone.
        git(fpath, "update-ref", "-d", "refs/heads/main")
        self.assertEqual(git(self.repos.path_for("volmarr", "upstream"), "rev-parse", "refs/heads/main"), self.commit)

    def test_fork_counts_and_network_listing(self):
        f1 = self.forks.fork(self.other.id, "volmarr", "upstream")
        f2 = self.forks.fork(self.third.id, "yrsa", "upstream", "second")
        self.assertEqual(self.forks.fork_count(self.source.id), 1)
        self.assertEqual(self.forks.fork_count(f1.id), 1)
        self.assertEqual(self.forks.upstream_of(f1).id, self.source.id)
        self.assertEqual(self.forks.network_root(f2).id, self.source.id)
        names = [r.full_name for r in self.forks.network_for(f2)]
        self.assertEqual(names, ["tess/second", "volmarr/upstream", "yrsa/upstream"])

    def test_private_unreadable_source_is_not_found(self):
        self.repos.create_repository(self.owner.id, "volmarr", "secret", visibility="private")
        with self.assertRaises(ForkError) as caught:
            self.forks.fork(self.other.id, "volmarr", "secret")
        self.assertEqual(caught.exception.reason, "no_such_repo")
        self.assertIsNone(self.repos.get_repository("yrsa", "secret"))

    def test_private_source_cannot_be_forked_public(self):
        self.repos.create_repository(self.owner.id, "volmarr", "mine", visibility="private")
        with self.assertRaises(ForkError) as caught:
            self.forks.fork(self.owner.id, "volmarr", "mine", "minefork", visibility="public")
        self.assertEqual(caught.exception.reason, "fork_visibility_escalation")
        ok = self.forks.fork(self.owner.id, "volmarr", "mine", "minefork")
        self.assertEqual(ok.visibility, "private")

    def test_name_collision_refused_and_fork_audited(self):
        self.forks.fork(self.other.id, "volmarr", "upstream")
        with self.assertRaises(ForkError) as caught:
            self.forks.fork(self.other.id, "volmarr", "upstream")
        self.assertEqual(caught.exception.reason, "repo_taken")
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, bad)
        rows = self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action='repo.fork'").fetchone()
        self.assertEqual(rows["c"], 1)

if __name__ == "__main__":
    unittest.main()
