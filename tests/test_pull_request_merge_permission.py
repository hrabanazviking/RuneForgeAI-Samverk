"""S-163 acceptance battery: merge permission.

Acceptance (roadmap S-163): only users with write may
merge; the button's absence for others is chrome law
(S-112), the refusal is server law (S-054).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import dataclasses, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.forks import ForkStore
from samverk.issues import IssueStore
from samverk.pull_request_merge import (
    PullRequestMergeStore, render_merge_preview)
from samverk.pull_request_merge_permission import (
    can_merge, merge_permission, permission_words)
from samverk.pull_requests import PullRequestError, PullRequestStore
from samverk.repositories import RepositoryStore


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_tree(repo, files):
    def build(items):
        entries = []
        dirs = {}
        for path, content in items:
            head, _, rest = path.partition("/")
            if rest:
                dirs.setdefault(head, []).append((rest, content))
            else:
                blob = git(repo, "hash-object", "-w", "--stdin",
                           input_bytes=content.encode())
                entries.append((path, f"100644 blob {blob}\t{path}"))
        for name, sub in dirs.items():
            tree = build(sub)
            entries.append((name + "/", f"040000 tree {tree}\t{name}"))
        entries.sort(key=lambda item: item[0])
        return git(repo, "mktree",
                   input_bytes=("\n".join(
                       line for _key, line in entries) + "\n").encode())
    return build(sorted(files.items()))


def make_commit(repo, parent, files, message):
    tree = make_tree(repo, files)
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class MergePermissionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.admin = dataclasses.replace(
            self.accounts.register("tess", "correct horse battery"),
            is_admin=True)
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.forks = ForkStore(self.conn, self.root, self.accounts,
                               self.repos, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.merge = PullRequestMergeStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.pub = self.repos.get_repository("volmarr", "pub")
        self.priv = self.repos.get_repository("volmarr", "priv")

    # -- helpers ---------------------------------------------------------
    def _open(self, *, repo="pub", draft=False):
        path = self.repos.path_for("volmarr", repo)
        base_oid = make_commit(path, None, {"a.txt": "alpha\n"}, "base")
        git(path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(path, base_oid,
                               {"a.txt": "alpha\nbeta\n"}, "feature work")
        git(path, "update-ref", "refs/heads/feature", head_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", repo, base_branch="main",
            head_branch="feature", title="Fix the thing", draft=draft)
        return pr, path, base_oid

    def _audit(self, outcome):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log"
            " WHERE action = 'repo.pull_request.merge'"
            " AND outcome = ?", (outcome,)).fetchone()
        return int(row["c"])

    def _tip(self, path, branch="main"):
        return git(path, "rev-parse", f"refs/heads/{branch}")

    # -- the seam: write is the whole law --------------------------------
    def test_owner_and_site_admin_may_merge_reader_may_not(self):
        self.assertTrue(can_merge(self.owner, self.pub))
        self.assertTrue(can_merge(self.admin, self.pub))
        self.assertFalse(can_merge(self.reader, self.pub))
        self.assertFalse(can_merge(None, self.pub))
        self.assertFalse(can_merge(self.reader, self.priv))
        self.assertTrue(can_merge(self.owner, self.priv))

    def test_collaborator_roles_rank_by_write(self):
        self.assertFalse(can_merge(self.reader, self.pub,
                                   collaborator_role="read"))
        self.assertTrue(can_merge(self.reader, self.pub,
                                  collaborator_role="write"))
        self.assertTrue(can_merge(self.reader, self.pub,
                                  collaborator_role="admin"))
        self.assertFalse(can_merge(self.reader, self.pub,
                                   collaborator_role="owner"))

    def test_permission_words_and_reason(self):
        denied = merge_permission(self.reader, self.pub)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "permission_denied")
        self.assertEqual(denied.role, "read")
        self.assertEqual(denied.words, permission_words("volmarr/pub"))
        self.assertIn("write", denied.words)
        granted = merge_permission(self.owner, self.pub)
        self.assertTrue(granted.allowed)
        self.assertEqual(granted.reason, "")
        self.assertEqual(granted.role, "admin")

    # -- the store answer: visibility first, then permission -------------
    def test_store_permission_for_owner_and_reader(self):
        pr, _p, _b = self._open()
        owner_perm = self.merge.merge_permission_for(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(owner_perm.allowed)
        self.assertEqual(owner_perm.number, pr.number)
        reader_perm = self.merge.merge_permission_for(
            self.reader, "volmarr", "pub", pr.number)
        self.assertFalse(reader_perm.allowed)
        self.assertEqual(reader_perm.reason, "permission_denied")

    def test_store_permission_hides_a_private_repository(self):
        pr, _p, _b = self._open(repo="priv")
        for call in (
                lambda: self.merge.merge_permission_for(
                    self.reader, "volmarr", "priv", pr.number),
                lambda: self.merge.preview_merge(
                    self.reader, "volmarr", "priv", pr.number),
                lambda: self.merge.merge_pull_request(
                    self.reader, "volmarr", "priv", pr.number)):
            with self.assertRaises(PullRequestError) as caught:
                call()
            self.assertEqual(caught.exception.reason,
                             "pull_request_not_found")

    def test_permission_for_a_missing_pull_request_is_not_found(self):
        with self.assertRaises(PullRequestError) as caught:
            self.merge.merge_permission_for(
                self.owner, "volmarr", "pub", 999)
        self.assertEqual(caught.exception.reason,
                         "pull_request_not_found")

    # -- chrome law: the button exists only for a writer who can land ----
    def test_preview_for_reader_reads_without_a_button(self):
        pr, _p, _b = self._open()
        preview = self.merge.preview_merge(
            self.reader, "volmarr", "pub", pr.number)
        self.assertTrue(preview.mergeable)
        self.assertFalse(preview.viewer_can_merge)
        self.assertEqual(preview.viewer_role, "read")
        self.assertFalse(preview.can_merge)
        self.assertFalse(preview.show_merge_button)
        self.assertEqual(preview.words, permission_words("volmarr/pub"))
        html = render_merge_preview(preview)
        self.assertNotIn("<button", html)
        self.assertNotIn("merge-button", html)
        self.assertNotIn("disabled", html)
        self.assertIn("Only a writer on volmarr/pub", html)

    def test_preview_for_owner_shows_the_merge_button(self):
        pr, _p, _b = self._open()
        preview = self.merge.preview_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(preview.viewer_can_merge)
        self.assertEqual(preview.viewer_role, "admin")
        self.assertTrue(preview.can_merge)
        self.assertTrue(preview.show_merge_button)
        html = render_merge_preview(preview)
        self.assertIn("<button", html)
        self.assertIn("merge-button", html)
        self.assertIn("Merge pull request", html)
        self.assertNotIn("disabled", html)

    def test_blocked_writer_sees_no_button_either(self):
        pr, _p, _b = self._open(draft=True)
        preview = self.merge.preview_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(preview.viewer_can_merge)
        self.assertFalse(preview.mergeable)
        self.assertFalse(preview.show_merge_button)
        self.assertIn("draft", preview.words)
        html = render_merge_preview(preview)
        self.assertNotIn("<button", html)
        self.assertNotIn("disabled", html)

    def test_private_owner_preview_shows_the_button(self):
        pr, _p, _b = self._open(repo="priv")
        preview = self.merge.preview_merge(
            self.owner, "volmarr", "priv", pr.number)
        self.assertTrue(preview.show_merge_button)
        self.assertIn("merge-button", render_merge_preview(preview))

    def test_reader_preview_writes_no_denied_audit(self):
        pr, _p, _b = self._open()
        self.merge.preview_merge(self.reader, "volmarr", "pub", pr.number)
        self.assertEqual(self._audit("denied"), 0)
        self.assertEqual(self._audit("success"), 0)

    # -- server law: the refusal, and it burns nothing ---------------------
    def test_reader_merge_refused_and_burns_nothing(self):
        pr, path, base_oid = self._open()
        with self.assertRaises(PullRequestError) as caught:
            self.merge.merge_pull_request(
                self.reader, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertIn("Only a writer on volmarr/pub",
                      str(caught.exception))
        self.assertEqual(self._tip(path), base_oid)
        self.assertEqual(self.prs.get_pull_request(
            self.owner, "volmarr", "pub", pr.number).state, "open")
        rows = self.conn.execute(
            "SELECT COUNT(*) AS c FROM pull_request_merges").fetchone()
        self.assertEqual(int(rows["c"]), 0)
        self.assertEqual(self._audit("success"), 0)

    def test_reader_merge_refusal_is_audited_denied(self):
        pr, _p, _b = self._open()
        with self.assertRaises(PullRequestError):
            self.merge.merge_pull_request(
                self.reader, "volmarr", "pub", pr.number)
        self.assertEqual(self._audit("denied"), 1)
        self.assertEqual(self._audit("success"), 0)

    def test_author_on_authorship_alone_cannot_merge(self):
        from samverk.pull_request_forks import ForkPullRequestStore
        path = self.repos.path_for("volmarr", "pub")
        base_oid = make_commit(path, None, {"a.txt": "alpha\n"}, "base")
        git(path, "update-ref", "refs/heads/main", base_oid)
        self.forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fork_head = make_commit(fork_path, base_oid,
                                {"a.txt": "alpha\nfrom the fork\n"},
                                "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        opened = xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub",
            head_branch="feature", title="From the fork")
        with self.assertRaises(PullRequestError) as caught:
            self.merge.merge_pull_request(
                self.reader, "volmarr", "pub", opened.number)
        self.assertEqual(caught.exception.reason, "permission_denied")
        result = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", opened.number)
        self.assertEqual(result.pull_request.state, "closed")

    def test_site_admin_can_merge_another_users_pull_request(self):
        pr, _p, _b = self._open()
        result = self.merge.merge_pull_request(
            self.admin, "volmarr", "pub", pr.number)
        self.assertEqual(result.pull_request.state, "closed")
        self.assertEqual(self._audit("success"), 1)

    def test_no_migration_and_no_new_taxonomy_event(self):
        self.assertIn("repo.pull_request.merge", taxonomy.AUDIT_EVENTS)
        self.assertEqual(schema_version(self.conn), 123)


if __name__ == "__main__":
    unittest.main()
