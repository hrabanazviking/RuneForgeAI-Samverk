"""S-159 acceptance battery (Builder-3): fork sync hint.

Acceptance (roadmap S-159, fork sync hint leg): the hint
is read-only, computed on read, stored nowhere; states
not_a_fork / no_upstream / up_to_date / behind / unknown;
default branches compared across the separate object
stores through the S-142 fetch seam; shown only when
behind > 0; no counts leak to a viewer who cannot read
the upstream.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sqlite3, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.forks import ForkStore
from samverk.fork_sync import (
    SCRATCH_REF, ForkSyncError, ForkSyncStore, render_fork_network_rows,
    render_fork_sync_hint)
from samverk.refs import RefStore
from samverk.repositories import RepositoryStore


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_commit(repo, parent, text, message):
    blob = git(repo, "hash-object", "-w", "--stdin",
               input_bytes=text.encode())
    tree = git(repo, "mktree",
               input_bytes=f"100644 blob {blob}\ta.txt\n".encode())
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class ForkSyncTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register(
            "volmarr", "correct horse battery")
        self.other = self.accounts.register(
            "yrsa", "correct horse battery")
        self.third = self.accounts.register(
            "tess", "correct horse battery")
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts, audit=self.audit)
        self.forks = ForkStore(
            self.conn, self.root, self.accounts, self.repos,
            audit=self.audit)
        self.sync = ForkSyncStore(self.repos)
        self.source = self.repos.create_repository(
            self.owner.id, "volmarr", "upstream", visibility="public")
        self.upath = self.repos.path_for("volmarr", "upstream")
        self.c1 = make_commit(self.upath, None, "one\n", "first")
        git(self.upath, "update-ref", "refs/heads/main", self.c1)
        self.fork = self.forks.fork(self.other.id, "volmarr", "upstream")
        self.fpath = self.repos.path_for("yrsa", "upstream")

    # -- helpers -----------------------------------------------------
    def _advance_upstream(self, n=1):
        tip = git(self.upath, "rev-parse", "refs/heads/main")
        for i in range(n):
            tip = make_commit(self.upath, tip, f"up {i}\n", f"up {i}")
        git(self.upath, "update-ref", "refs/heads/main", tip)
        return tip

    def _advance_fork(self, n=1):
        tip = git(self.fpath, "rev-parse", "refs/heads/main")
        for i in range(n):
            tip = make_commit(self.fpath, tip, f"fork {i}\n", f"fork {i}")
        git(self.fpath, "update-ref", "refs/heads/main", tip)
        return tip

    def _status(self, who=None, owner="yrsa", repo="upstream"):
        return self.sync.fork_sync_status(
            who or self.other, owner, repo)

    # -- states --------------------------------------------------------
    def test_not_a_fork(self):
        status = self.sync.fork_sync_status(
            self.other, "volmarr", "upstream")
        self.assertEqual(status.state, "not_a_fork")
        self.assertEqual(status.behind, 0)
        self.assertEqual(render_fork_sync_hint(status), "")
        payload = status.to_dict()
        self.assertEqual(set(payload),
                         {"state", "upstream", "branch", "behind", "ahead"})
        self.assertEqual(payload["state"], "not_a_fork")

    def test_up_to_date_at_fork_time_and_no_scratch_left(self):
        status = self._status()
        self.assertEqual(status.state, "up_to_date")
        self.assertEqual((status.behind, status.ahead), (0, 0))
        self.assertEqual(status.upstream_full_name, "volmarr/upstream")
        self.assertEqual(status.branch, "main")
        self.assertEqual(render_fork_sync_hint(status), "")
        self.assertIsNone(RefStore(self.fpath).resolve(SCRATCH_REF))

    def test_behind_counts_and_design_words(self):
        tip = self._advance_upstream(2)
        status = self._status()
        self.assertEqual(status.state, "behind")
        self.assertEqual(status.behind, 2)
        self.assertEqual(status.ahead, 0)
        self.assertEqual(
            status.words,
            "This fork is behind volmarr/upstream: its main is "
            "2 commits behind. Open a pull request from the "
            "upstream repository, or fetch upstream locally, "
            "to catch up.")
        html = render_fork_sync_hint(status)
        self.assertIn("fork-sync-hint", html)
        self.assertIn("2 commits behind", html)
        # The check itself moved nothing in either repository.
        self.assertEqual(
            git(self.upath, "rev-parse", "refs/heads/main"), tip)
        self.assertEqual(
            git(self.fpath, "rev-parse", "refs/heads/main"), self.c1)
        self.assertIsNone(RefStore(self.fpath).resolve(SCRATCH_REF))

    def test_diverged_words_carry_both_counts(self):
        self._advance_fork(1)
        self._advance_upstream(2)
        status = self._status()
        self.assertEqual(status.state, "behind")
        self.assertEqual((status.behind, status.ahead), (2, 1))
        self.assertIn("2 commits behind and 1 commits ahead",
                      status.words)

    def test_catching_up_returns_to_up_to_date(self):
        tip = self._advance_upstream(2)
        self.assertEqual(self._status().state, "behind")
        git(self.fpath, "update-ref", "refs/heads/main", tip)
        status = self._status()
        self.assertEqual(status.state, "up_to_date")
        self.assertEqual(status.behind, 0)

    def test_no_upstream_when_parent_row_is_gone(self):
        raw = sqlite3.connect(str(self.root / "samverk.db"))
        raw.execute("PRAGMA foreign_keys=OFF")
        raw.execute("DELETE FROM repositories WHERE id = ?",
                    (self.source.id,))
        raw.commit()
        raw.close()
        status = self._status()
        self.assertEqual(status.state, "no_upstream")
        self.assertEqual(status.behind, 0)
        self.assertEqual(render_fork_sync_hint(status), "")

    def test_no_upstream_leaks_no_counts_to_a_stranger(self):
        self._advance_upstream(3)
        # The parent goes private after the fork was made.
        self.repos.update_metadata(
            self.owner.id, "volmarr", "upstream", visibility="private")
        status = self.sync.fork_sync_status(
            self.third, "yrsa", "upstream")
        self.assertEqual(status.state, "no_upstream")
        self.assertEqual((status.behind, status.ahead), (0, 0))
        self.assertEqual(render_fork_sync_hint(status), "")
        # The fork's owner still cannot read the parent either
        # (it is not hers), so she gets the same closed answer;
        # the parent's owner, who can read both, sees the truth.
        self.assertEqual(self._status().state, "no_upstream")
        owner_view = self.sync.fork_sync_status(
            self.owner, "yrsa", "upstream")
        self.assertEqual(owner_view.state, "behind")
        self.assertEqual(owner_view.behind, 3)

    def test_stranger_to_a_private_fork_gets_not_found(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "secret", visibility="private")
        spath = self.repos.path_for("volmarr", "secret")
        c = make_commit(spath, None, "s\n", "secret first")
        git(spath, "update-ref", "refs/heads/main", c)
        self.forks.fork(self.owner.id, "volmarr", "secret", "secretfork")
        with self.assertRaises(ForkSyncError) as caught:
            self.sync.fork_sync_status(
                self.other, "volmarr", "secretfork")
        self.assertEqual(caught.exception.reason, "repo_not_found")

    def test_unknown_when_the_fetch_fails_never_guessed(self):
        self._advance_upstream(1)
        failed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b"boom")
        with mock.patch("samverk.fork_sync.run_git_fetch_ref",
                        return_value=failed):
            status = self._status()
        self.assertEqual(status.state, "unknown")
        self.assertIsNone(status.behind)
        self.assertIsNone(status.ahead)
        self.assertIsNone(status.to_dict()["behind"])
        self.assertEqual(render_fork_sync_hint(status), "")
        self.assertIn("could not be", status.words)

    def test_network_rows_carry_the_hint_only_where_behind(self):
        self._advance_upstream(2)
        members = self.forks.network_for(self.fork)
        statuses = self.sync.statuses_for_network(self.owner, members)
        by_name = {s.full_name: s for s in statuses}
        self.assertEqual(by_name["volmarr/upstream"].state, "not_a_fork")
        self.assertEqual(by_name["yrsa/upstream"].state, "behind")
        html = render_fork_network_rows(statuses)
        self.assertIn("volmarr/upstream", html)
        self.assertIn("yrsa/upstream", html)
        self.assertIn("2 commits behind", html)


if __name__ == "__main__":
    unittest.main()
