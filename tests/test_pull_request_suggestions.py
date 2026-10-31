"""S-150 acceptance battery: pull request suggested changes.

Acceptance (roadmap S-150): suggested changes — reviewers
propose committable patches; author applies one or batches
them, each application a signed-off commit.

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
from samverk.pull_request_forks import ForkPullRequestStore
from samverk.pull_request_suggestions import (
    PullRequestSuggestionStore, render_suggestions)
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
    """A tree oid for a {path: content} mapping, nested
    paths built as real subtrees."""
    def build(items):
        entries = []   # (sort_key, line)
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


BASE_FILES = {"a.txt": "alpha\nbeta\n"}
HEAD_FILES = {"a.txt": "alpha\nBETA\n",
              "b.txt": "one\ntwo\nthree\n",
              "sub/c.txt": "x\ny\n"}


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class SuggestionTests(unittest.TestCase):
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
        self.third = self.accounts.register("tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.forks = ForkStore(self.conn, self.root, self.accounts,
                               self.repos, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.suggestions = PullRequestSuggestionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")
        self.base_oid = make_commit(self.path, None, BASE_FILES, "base")
        git(self.path, "update-ref", "refs/heads/main", self.base_oid)
        self.head_oid = make_commit(
            self.path, self.base_oid, HEAD_FILES, "feature work")
        git(self.path, "update-ref", "refs/heads/feature", self.head_oid)
        self.pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature")

    # -- helpers ---------------------------------------------------------
    def _propose(self, who=None, file="a.txt", start=2, end=2,
                 replacement="BETA!", body=""):
        return self.suggestions.propose_suggestion(
            who or self.reader, "volmarr", "pub", self.pr.number,
            file, start, end, replacement, body=body)

    def _head(self, branch="feature", repo=None):
        return git(repo or self.path, "rev-parse", f"refs/heads/{branch}")

    def _show(self, oid, path, repo=None):
        return git(repo or self.path, "show", f"{oid}:{path}")

    def _audit_count(self, action):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = ?",
            (action,)).fetchone()
        return int(row["c"])

    def _commit_count(self, repo=None):
        return int(git(repo or self.path, "rev-list", "--count",
                       "refs/heads/feature"))

    # -- proposal ---------------------------------------------------------
    def test_a_proposal_stores_its_anchor_and_the_lines_it_replaces(self):
        self.assertEqual(db.schema_version(self.conn), 55)
        suggestion = self._propose(body="Clearer this way.")
        self.assertEqual(suggestion.file_path, "a.txt")
        self.assertEqual((suggestion.start_line, suggestion.end_line), (2, 2))
        self.assertEqual(suggestion.original_text, "BETA")
        self.assertEqual(suggestion.replacement_text, "BETA!")
        self.assertEqual(suggestion.head_oid, self.head_oid)
        self.assertEqual(suggestion.state, "pending")
        self.assertFalse(suggestion.is_outdated)
        self.assertIn("line 2", suggestion.anchor_words)
        self.assertEqual(
            self._audit_count("repo.pull_request.suggestion_propose"), 1)

    def test_proposal_refusals_store_nothing(self):
        cases = [
            (dict(file="zzz.txt"), "file_not_found"),
            (dict(start=3, end=3), "line_not_found"),
            (dict(start=0, end=2), "range_invalid"),
            (dict(start=2, end=1), "range_invalid"),
            (dict(replacement="BETA"), "suggestion_no_change"),
        ]
        for kwargs, reason in cases:
            with self.assertRaises(PullRequestError) as caught:
                self._propose(**kwargs)
            self.assertEqual(caught.exception.reason, reason, kwargs)
        self.assertEqual(
            self.suggestions.suggestions_for(
                self.owner, "volmarr", "pub", self.pr.number), [])
        self.assertEqual(
            self._audit_count("repo.pull_request.suggestion_propose"), 0)

    def test_a_closed_pull_request_takes_no_proposals(self):
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE id = ?",
                (self.pr.row_id,))
        with self.assertRaises(PullRequestError) as caught:
            self._propose()
        self.assertEqual(caught.exception.reason, "pull_request_closed")

    # -- single application ---------------------------------------------------
    def test_the_author_applies_one_suggestion_as_one_signed_off_commit(self):
        suggestion = self._propose()
        before = self._commit_count()
        applied = self.suggestions.apply_suggestion(
            self.owner, "volmarr", "pub", self.pr.number, suggestion.id)
        self.assertEqual(applied.count, 1)
        self.assertEqual(self._head(), applied.commit_oid)
        self.assertEqual(self._commit_count(), before + 1)
        # The commit itself: parent is the old head, the
        # applier is its author, the file carries exactly
        # the suggested text, and the sign-off record is
        # in its message.
        parent = git(self.path, "rev-parse", f"{applied.commit_oid}^")
        self.assertEqual(parent, self.head_oid)
        author = git(self.path, "log", "-1", "--format=%an",
                     applied.commit_oid)
        self.assertEqual(author, "volmarr")
        self.assertEqual(
            self._show(applied.commit_oid, "a.txt"), "alpha\nBETA!")
        message = git(self.path, "log", "-1", "--format=%B",
                      applied.commit_oid)
        self.assertIn("Suggested-by: yrsa <yrsa@samverk.invalid>", message)
        self.assertIn(
            "Signed-off-by: volmarr <volmarr@samverk.invalid>", message)
        # The record: applied, naming the commit, audited.
        stored = self.suggestions.get_suggestion(
            self.owner, "volmarr", "pub", self.pr.number, suggestion.id)
        self.assertTrue(stored.is_applied)
        self.assertEqual(stored.applied_commit_oid, applied.commit_oid)
        self.assertEqual(stored.applied_by, self.owner.id)
        self.assertEqual(
            self._audit_count("repo.pull_request.suggestion_apply"), 1)

    def test_only_the_author_or_an_allowed_maintainer_can_apply(self):
        suggestion = self._propose()
        with self.assertRaises(PullRequestError) as caught:
            self.suggestions.apply_suggestion(
                self.third, "volmarr", "pub", self.pr.number,
                suggestion.id)
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertEqual(self._head(), self.head_oid)

    def test_an_applied_suggestion_cannot_be_applied_again(self):
        suggestion = self._propose()
        self.suggestions.apply_suggestion(
            self.owner, "volmarr", "pub", self.pr.number, suggestion.id)
        with self.assertRaises(PullRequestError) as caught:
            self.suggestions.apply_suggestion(
                self.owner, "volmarr", "pub", self.pr.number,
                suggestion.id)
        self.assertEqual(
            caught.exception.reason, "suggestion_not_pending")

    def test_an_empty_batch_and_a_foreign_suggestion_are_refused(self):
        with self.assertRaises(PullRequestError) as caught:
            self.suggestions.apply_suggestions(
                self.owner, "volmarr", "pub", self.pr.number, [])
        self.assertEqual(caught.exception.reason, "no_suggestions")
        with self.assertRaises(PullRequestError) as caught:
            self.suggestions.apply_suggestions(
                self.owner, "volmarr", "pub", self.pr.number, [9999])
        self.assertEqual(caught.exception.reason, "suggestion_not_found")
        self.assertEqual(self._head(), self.head_oid)

    def test_a_suggestion_can_delete_lines(self):
        suggestion = self._propose(file="b.txt", start=2, end=2,
                                   replacement="")
        applied = self.suggestions.apply_suggestion(
            self.owner, "volmarr", "pub", self.pr.number, suggestion.id)
        self.assertEqual(
            self._show(applied.commit_oid, "b.txt"), "one\nthree")

    def test_a_suggestion_in_a_subdirectory_applies(self):
        suggestion = self._propose(file="sub/c.txt", start=1, end=2,
                                   replacement="x\ny\nz")
        applied = self.suggestions.apply_suggestion(
            self.owner, "volmarr", "pub", self.pr.number, suggestion.id)
        self.assertEqual(
            self._show(applied.commit_oid, "sub/c.txt"), "x\ny\nz")
        self.assertEqual(
            self._show(applied.commit_oid, "a.txt"), "alpha\nBETA")

    def test_applying_one_suggestion_leaves_an_untouched_neighbour_pending(
            self):
        first = self._propose(file="b.txt", start=1, end=1,
                              replacement="ONE")
        second = self._propose()
        self.suggestions.apply_suggestion(
            self.owner, "volmarr", "pub", self.pr.number, first.id)
        stored = self.suggestions.get_suggestion(
            self.owner, "volmarr", "pub", self.pr.number, second.id)
        self.assertFalse(stored.is_applied)
        self.assertFalse(stored.is_outdated)
        applied = self.suggestions.apply_suggestion(
            self.owner, "volmarr", "pub", self.pr.number, second.id)
        self.assertEqual(
            self._show(applied.commit_oid, "a.txt"), "alpha\nBETA!")

    # -- batches ----------------------------------------------------------------
    def test_a_batch_lands_as_exactly_one_commit(self):
        one = self._propose(start=1, end=1, replacement="ALPHA")
        two = self._propose()
        three = self._propose(who=self.third, file="b.txt", start=3,
                              end=3, replacement="THREE")
        before = self._commit_count()
        applied = self.suggestions.apply_suggestions(
            self.owner, "volmarr", "pub", self.pr.number,
            [one.id, two.id, three.id])
        self.assertEqual(applied.count, 3)
        self.assertEqual(self._commit_count(), before + 1)
        self.assertEqual(
            self._show(applied.commit_oid, "a.txt"), "ALPHA\nBETA!")
        self.assertEqual(
            self._show(applied.commit_oid, "b.txt"), "one\ntwo\nTHREE")
        message = git(self.path, "log", "-1", "--format=%B",
                      applied.commit_oid)
        self.assertIn("Apply 3 suggested changes", message)
        self.assertIn("Suggested-by: yrsa", message)
        self.assertIn("Suggested-by: tess", message)
        for suggestion in (one, two, three):
            stored = self.suggestions.get_suggestion(
                self.owner, "volmarr", "pub", self.pr.number,
                suggestion.id)
            self.assertTrue(stored.is_applied)
            self.assertEqual(
                stored.applied_commit_oid, applied.commit_oid)
        self.assertEqual(
            self._audit_count("repo.pull_request.suggestion_apply"), 1)

    def test_an_overlapping_batch_is_refused_whole(self):
        one = self._propose()
        two = self._propose(who=self.third, replacement="BETA?")
        with self.assertRaises(PullRequestError) as caught:
            self.suggestions.apply_suggestions(
                self.owner, "volmarr", "pub", self.pr.number,
                [one.id, two.id])
        self.assertEqual(caught.exception.reason, "suggestion_overlap")
        self.assertEqual(self._head(), self.head_oid)
        for suggestion in (one, two):
            stored = self.suggestions.get_suggestion(
                self.owner, "volmarr", "pub", self.pr.number,
                suggestion.id)
            self.assertFalse(stored.is_applied)

    # -- outdated ------------------------------------------------------------------
    def test_a_push_that_moves_the_lines_makes_a_suggestion_outdated(self):
        suggestion = self._propose()
        pushed = make_commit(
            self.path, self.head_oid,
            {"a.txt": "alpha\nBETA changed\n",
             "b.txt": "one\ntwo\nthree\n", "sub/c.txt": "x\ny\n"},
            "push")
        git(self.path, "update-ref", "refs/heads/feature", pushed)
        stored = self.suggestions.get_suggestion(
            self.owner, "volmarr", "pub", self.pr.number, suggestion.id)
        self.assertTrue(stored.is_outdated)
        self.assertIn("Outdated", stored.state_words)
        with self.assertRaises(PullRequestError) as caught:
            self.suggestions.apply_suggestion(
                self.owner, "volmarr", "pub", self.pr.number,
                suggestion.id)
        self.assertEqual(caught.exception.reason, "suggestion_outdated")
        self.assertEqual(self._head(), pushed)

    # -- cross-fork -------------------------------------------------------------------
    def _fork_pr(self, maintainer_can_edit=True):
        self.forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fork_head = make_commit(
            fork_path, self.base_oid,
            {"a.txt": "alpha\nfrom the fork\n"}, "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        created = self.xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub", head_branch="feature",
            maintainer_can_edit=maintainer_can_edit)
        return created, fork_path, fork_head

    def test_cross_fork_the_author_applies_to_the_fork_branch(self):
        created, fork_path, fork_head = self._fork_pr()
        suggestion = self.suggestions.propose_suggestion(
            self.owner, "volmarr", "pub", created.number,
            "a.txt", 2, 2, "from the fork, fixed")
        applied = self.suggestions.apply_suggestion(
            self.reader, "volmarr", "pub", created.number, suggestion.id)
        self.assertEqual(
            git(fork_path, "rev-parse", "refs/heads/feature"),
            applied.commit_oid)
        self.assertEqual(
            self._show(applied.commit_oid, "a.txt", repo=fork_path),
            "alpha\nfrom the fork, fixed")
        # The base repository's branches never moved.
        self.assertEqual(self._head(), self.head_oid)

    def test_cross_fork_maintainer_edits_gate_a_maintainer_application(self):
        created, fork_path, _head = self._fork_pr(maintainer_can_edit=True)
        suggestion = self.suggestions.propose_suggestion(
            self.third, "volmarr", "pub", created.number,
            "a.txt", 2, 2, "maintainer fix")
        applied = self.suggestions.apply_suggestion(
            self.owner, "volmarr", "pub", created.number, suggestion.id)
        self.assertEqual(
            git(fork_path, "rev-parse", "refs/heads/feature"),
            applied.commit_oid)

    def test_cross_fork_without_maintainer_edits_the_maintainer_cannot_apply(
            self):
        created, fork_path, fork_head = self._fork_pr(
            maintainer_can_edit=False)
        suggestion = self.suggestions.propose_suggestion(
            self.third, "volmarr", "pub", created.number,
            "a.txt", 2, 2, "maintainer fix")
        with self.assertRaises(PullRequestError) as caught:
            self.suggestions.apply_suggestion(
                self.owner, "volmarr", "pub", created.number,
                suggestion.id)
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertEqual(
            git(fork_path, "rev-parse", "refs/heads/feature"), fork_head)

    # -- privacy + rendering ---------------------------------------------------------
    def test_private_repository_answers_uniformly(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        priv_path = self.repos.path_for("volmarr", "priv")
        priv_base = make_commit(priv_path, None, {"s.txt": "s\n"}, "one")
        git(priv_path, "update-ref", "refs/heads/main", priv_base)
        priv_head = make_commit(
            priv_path, priv_base, {"s.txt": "s\nmore\n"}, "two")
        git(priv_path, "update-ref", "refs/heads/feature", priv_head)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "priv", base_branch="main",
            head_branch="feature")
        with self.assertRaises(PullRequestError) as caught:
            self.suggestions.propose_suggestion(
                self.reader, "volmarr", "priv", pr.number,
                "s.txt", 2, 2, "more!")
        self.assertEqual(
            caught.exception.reason, "pull_request_not_found")
        with self.assertRaises(PullRequestError) as caught:
            self.suggestions.suggestions_for(
                self.reader, "volmarr", "priv", pr.number)
        self.assertEqual(
            caught.exception.reason, "pull_request_not_found")

    def test_rendering_says_the_state_in_words_and_escapes(self):
        suggestion = self._propose(replacement="BETA <&> !")
        html = render_suggestions([suggestion])
        self.assertIn("Pending", html)
        self.assertIn("a.txt, line 2", html)
        self.assertIn("BETA &lt;&amp;&gt; !", html)
        self.assertIn("No suggested changes",
                      render_suggestions([]))


if __name__ == "__main__":
    unittest.main()
