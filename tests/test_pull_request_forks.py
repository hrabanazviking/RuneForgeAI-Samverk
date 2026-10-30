"""S-142 acceptance battery: pull request creation, cross-fork.

Acceptance (roadmap S-142): PR creation, cross-fork — head
from a fork, maintainer-edits permission flag, honest
display of the fork relationship.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.forks import ForkStore
from samverk.issues import IssueStore
from samverk.pull_request_forks import (
    SCRATCH_REF, ForkPullRequestStore, render_cross_fork_line,
    render_cross_fork_page)
from samverk.pull_requests import PullRequestError, PullRequestStore
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


def make_commit(repo, parent, files, message):
    """One plumbing commit over *files* ({name: text}) on top
    of *parent* (or root when None); returns the oid."""
    lines = []
    for name in sorted(files):
        blob = git(repo, "hash-object", "-w", "--stdin",
                   input_bytes=files[name].encode())
        lines.append(f"100644 blob {blob}\t{name}\n")
    tree = git(repo, "mktree", input_bytes="".join(lines).encode())
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class CrossForkPullRequestTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.forker = self.accounts.register("yrsa", "correct horse battery")
        self.third = self.accounts.register("tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.forks = ForkStore(self.conn, self.root, self.accounts,
                               self.repos, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit)
        self.xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        base_path = self.repos.path_for("volmarr", "pub")
        self.base_oid = make_commit(
            base_path, None, {"a.txt": "base\n"}, "base commit")
        git(base_path, "update-ref", "refs/heads/main", self.base_oid)
        self.fork = self.forks.fork(self.forker.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        self.head_oid = make_commit(
            fork_path, self.base_oid,
            {"a.txt": "base\nfeature <work>\n"}, "feature <work>")
        git(fork_path, "update-ref", "refs/heads/feature", self.head_oid)
        self.issues.create_issue(
            self.owner, "volmarr", "pub", "An ordinary issue")

    def _open(self, actor=None, **overrides):
        kwargs = dict(base_branch="main", head_owner="yrsa",
                      head_repo="pub", head_branch="feature")
        kwargs.update(overrides)
        return self.xprs.create_cross_fork_pull_request(
            actor or self.forker, "volmarr", "pub", **kwargs)

    # -- preview ------------------------------------------------------
    def test_preview_says_the_relationship_and_the_true_numbers(self):
        preview = self.xprs.preview_cross_fork(
            self.forker, "volmarr", "pub", "main",
            "yrsa", "pub", "feature")
        self.assertEqual(preview.fork_chain, ("yrsa/pub", "volmarr/pub"))
        self.assertEqual(preview.relationship_words,
                         "yrsa/pub is a fork of volmarr/pub")
        self.assertTrue(preview.can_open)
        self.assertEqual(
            (preview.compare.ahead, preview.compare.behind), (1, 0))
        self.assertEqual(preview.compare.files_changed, 1)
        self.assertEqual(preview.compare.base_oid, self.base_oid)
        self.assertEqual(preview.compare.head_oid, self.head_oid)
        self.assertEqual(preview.suggested_title, "feature <work>")
        page = render_cross_fork_page(preview)
        self.assertIn("yrsa/pub is a fork of volmarr/pub", page)
        self.assertIn('<select name="base_branch">', page)
        self.assertIn('<select name="head_branch">', page)
        self.assertIn('name="maintainer_can_edit" checked', page)
        self.assertIn("may push to the head branch", page)
        self.assertIn("Open pull request", page)
        # The scratch compare ref never survives the preview.
        fork_path = self.repos.path_for("yrsa", "pub")
        self.assertIsNone(RefStore(fork_path).resolve(SCRATCH_REF))

    def test_preview_after_the_base_branch_moves(self):
        # The upstream advances after the fork was taken: the
        # compare must be against the base as it stands today,
        # not the fork's stale copy of it.
        base_path = self.repos.path_for("volmarr", "pub")
        new_base = make_commit(
            base_path, self.base_oid,
            {"a.txt": "base\n", "b.txt": "upstream\n"}, "upstream work")
        git(base_path, "update-ref", "refs/heads/main", new_base)
        preview = self.xprs.preview_cross_fork(
            self.forker, "volmarr", "pub", "main",
            "yrsa", "pub", "feature")
        self.assertEqual(
            (preview.compare.ahead, preview.compare.behind), (1, 1))
        self.assertEqual(preview.compare.base_oid, new_base)
        created = self._open()
        self.assertEqual(created.pull_request.base_oid, new_base)

    # -- creation -------------------------------------------------------
    def test_creation_by_the_fork_owner_who_cannot_write_the_base(self):
        created = self._open(title="Ship <it>")
        pr = created.pull_request
        # The setUp issue is #1 in the base repo; the PR claims
        # the base repository's shared next number.
        self.assertEqual(pr.number, 2)
        self.assertFalse(pr.is_draft)
        self.assertEqual((pr.base_branch, pr.head_branch),
                         ("main", "feature"))
        self.assertEqual((pr.base_oid, pr.head_oid),
                         (self.base_oid, self.head_oid))
        self.assertTrue(created.maintainer_can_edit)
        self.assertEqual(created.relationship_words,
                         "yrsa/pub is a fork of volmarr/pub")
        line = render_cross_fork_line(created)
        self.assertIn("Ship &lt;it&gt;", line)
        self.assertIn("yrsa/pub:feature into volmarr/pub:main", line)
        self.assertIn("is a fork of", line)
        # It is an ordinary PR in the base repository's list…
        listed = self.prs.list_pull_requests(
            self.owner, "volmarr", "pub")
        self.assertEqual([p.number for p in listed], [2])
        # …and its fork record reads back through the seam.
        again = self.xprs.get_cross_fork(
            self.third, "volmarr", "pub", 2)
        self.assertIsNotNone(again)
        self.assertEqual(again.head_full_name, "yrsa/pub")
        rows = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action = 'repo.pull_request.create'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn('"same_repo":false', rows[0]["detail"])
        self.assertIn('"head_repo":"yrsa/pub"', rows[0]["detail"])
        self.assertIn('"maintainer_can_edit":true', rows[0]["detail"])

    def test_same_repo_pull_request_has_no_cross_fork_record(self):
        base_path = self.repos.path_for("volmarr", "pub")
        # A same-repo head branch in the base itself:
        RefStore(base_path).create_branch("local-feature", self.base_oid)
        local = make_commit(
            base_path, self.base_oid,
            {"a.txt": "base\nlocal\n"}, "local work")
        git(base_path, "update-ref", "refs/heads/local-feature", local)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub",
            base_branch="main", head_branch="local-feature")
        self.assertIsNone(self.xprs.get_cross_fork(
            self.owner, "volmarr", "pub", pr.number))
        self.assertFalse(self.xprs.maintainer_edit_allowed(
            self.owner, "volmarr", "pub", pr.number))

    # -- the maintainer-edits flag ---------------------------------------
    def test_maintainer_edits_flag_and_seam(self):
        opened = self._open()
        # Flag on (the default): a writer on the BASE repository
        # may edit; a mere reader of the base may not, and the
        # author — no writer on the base — is not a "maintainer".
        self.assertTrue(self.xprs.maintainer_edit_allowed(
            self.owner, "volmarr", "pub", opened.number))
        self.assertFalse(self.xprs.maintainer_edit_allowed(
            self.third, "volmarr", "pub", opened.number))
        self.assertFalse(self.xprs.maintainer_edit_allowed(
            self.forker, "volmarr", "pub", opened.number))
        self.assertIn("may push to the head branch",
                      opened.maintainer_words)

    def test_maintainer_edits_off_is_stored_and_said(self):
        created = self._open(maintainer_can_edit=False)
        self.assertFalse(created.maintainer_can_edit)
        self.assertIn("may not push to the head branch",
                      created.maintainer_words)
        self.assertFalse(self.xprs.maintainer_edit_allowed(
            self.owner, "volmarr", "pub", created.number))
        preview = self.xprs.preview_cross_fork(
            self.forker, "volmarr", "pub", "main",
            "yrsa", "pub", "feature", maintainer_can_edit=False)
        page = render_cross_fork_page(preview)
        self.assertNotIn('name="maintainer_can_edit" checked', page)
        self.assertIn("may not push to the head branch", page)

    # -- refusals ----------------------------------------------------------
    def test_refusals_burn_nothing(self):
        # An unrelated repository the actor owns is not a fork.
        self.repos.create_repository(
            self.third.id, "tess", "solo", visibility="public")
        solo_path = self.repos.path_for("tess", "solo")
        solo_oid = make_commit(solo_path, None, {"x.txt": "x\n"}, "solo")
        git(solo_path, "update-ref", "refs/heads/feature", solo_oid)
        before = self.issues.last_number("volmarr", "pub")
        cases = [
            (dict(head_owner="tess", head_repo="solo"), "not_a_fork"),
            (dict(head_owner="volmarr", head_repo="pub"), "same_repository"),
            (dict(base_branch="nope"), "base_not_found"),
            (dict(head_branch="nope"), "head_not_found"),
            (dict(head_branch="main"), "no_commits"),
            (dict(head_branch="bad..name"), "branch_invalid"),
            (dict(title="  "), "title_required"),
        ]
        for overrides, reason in cases:
            actor = self.third if reason == "not_a_fork" else self.forker
            with self.assertRaises(PullRequestError) as caught:
                self._open(actor=actor, **overrides)
            self.assertEqual(caught.exception.reason, reason, overrides)
        # The base owner cannot offer somebody else's fork branch.
        with self.assertRaises(PullRequestError) as caught:
            self._open(actor=self.owner)
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertEqual(self.issues.last_number("volmarr", "pub"), before)
        self.assertEqual(
            self.prs.list_pull_requests(self.owner, "volmarr", "pub"), [])

    def test_second_open_from_the_same_fork_refused(self):
        self._open()
        with self.assertRaises(PullRequestError) as caught:
            self._open()
        self.assertEqual(caught.exception.reason, "already_exists")
        self.assertIn("#2", str(caught.exception))
        preview = self.xprs.preview_cross_fork(
            self.forker, "volmarr", "pub", "main",
            "yrsa", "pub", "feature")
        self.assertFalse(preview.can_open)
        self.assertIn("#2", preview.blockers[0])

    def test_private_repositories_stay_invisible(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        priv_path = self.repos.path_for("volmarr", "priv")
        priv_oid = make_commit(priv_path, None, {"s.txt": "s\n"}, "secret")
        git(priv_path, "update-ref", "refs/heads/main", priv_oid)
        own_fork = self.forks.fork(self.owner.id, "volmarr", "priv",
                                   "privfork")
        self.assertEqual(own_fork.visibility, "private")
        # A stranger cannot even preview against the private base.
        with self.assertRaises(PullRequestError) as caught:
            self.xprs.preview_cross_fork(
                self.forker, "volmarr", "priv", "main",
                "volmarr", "privfork", "main")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        # Nor name the owner's private fork as a head into a
        # public base — its existence is itself private.
        with self.assertRaises(PullRequestError) as caught:
            self.xprs.preview_cross_fork(
                self.forker, "volmarr", "pub", "main",
                "volmarr", "privfork", "main")
        self.assertEqual(caught.exception.reason, "head_repo_not_found")

    # -- fork of a fork -------------------------------------------------------
    def test_fork_of_a_fork_names_the_whole_chain(self):
        self.forks.fork(self.third.id, "yrsa", "pub", "pub2")
        preview = self.xprs.preview_cross_fork(
            self.third, "volmarr", "pub", "main",
            "tess", "pub2", "feature")
        self.assertEqual(
            preview.fork_chain,
            ("tess/pub2", "yrsa/pub", "volmarr/pub"))
        self.assertEqual(
            preview.relationship_words,
            "tess/pub2 is a fork of yrsa/pub, which is a fork of "
            "volmarr/pub")
        created = self.xprs.create_cross_fork_pull_request(
            self.third, "volmarr", "pub", base_branch="main",
            head_owner="tess", head_repo="pub2", head_branch="feature")
        self.assertEqual(created.head_full_name, "tess/pub2")
        self.assertIn("yrsa/pub", render_cross_fork_line(created))


if __name__ == "__main__":
    unittest.main()
