"""S-168 — PART VII GATE battery: pull requests & review, assembled.

The whole Part VII system walked end to end, struck at the
four things the gate names:

- **Full lifecycle** — a pull request lives its whole life
  through the public seams: open (same-repo, cross-fork, and
  from the compare view), converse, request a reviewer (the
  request reaches the reviewer's notification inbox), record
  checks, review, consult the required-review seam (S-164),
  watch mergeability say its verdict in words (S-156), land,
  and — once landed — revert through a linked pull request
  of its own (S-160).
- **Roles** — author, reviewer, writer-owner, reader,
  stranger, and anonymous, on public and private
  repositories alike: writers merge, readers review and
  converse but never merge, an author never approves their
  own work, and a private repository answers every Part VII
  surface with the one uniform not-found.
- **Forks** — a cross-fork pull request is opened by the
  fork's owner (who cannot write the base), reviewed and
  landed by the base's owner by merge commit and by squash,
  with the fork itself untouched; rebase, whose head lives
  in the fork, refuses cleanly and changes nothing.
- **Drafts and all three merge methods** — a draft blocks
  merge commit, squash, and rebase alike until it is marked
  ready; then each method lands in its own shape: a
  two-parent merge commit, one squashed commit with the
  author preserved, and head commits replayed onto an
  advanced base with the head branch unmoved. Conflicts
  surface before anyone merges and block every road.
  Auto-merge (S-158) fires through the real merge store
  once its required check passes, and a push that
  stale-dates an approval (S-149) un-satisfies the
  required-review seam until the reviewer approves again.

The gate claimed no migration and no taxonomy event: the
assembled system stands at schema 66 with 119 audit
events, and the audit chain verifies over the gate's own
landings. The full-suite counted recount at this gate is
recorded in PROJECT_MEMORY_MAP.md (the gate entry), read
back from its log file after the run finished.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.db import schema_version
from samverk.forks import ForkStore
from samverk.issues import IssueStore
from samverk.labels import LabelStore
from samverk.pull_request_auto_merge import PullRequestAutoMergeStore
from samverk.pull_request_checks import PullRequestChecksStore
from samverk.pull_request_conversation import PullRequestConversationStore
from samverk.pull_request_drafts import PullRequestDraftStore
from samverk.pull_request_forks import ForkPullRequestStore
from samverk.pull_request_from_compare import PullRequestFromCompareStore
from samverk.pull_request_merge import PullRequestMergeStore
from samverk.pull_request_merge_permission import can_merge, merge_permission
from samverk.pull_request_mergeability import MergeabilityStore
from samverk.pull_request_rebase import PullRequestRebaseStore
from samverk.pull_request_required_review import (
    PullRequestRequiredReviewStore, ReviewRequirement)
from samverk.pull_request_revert import PullRequestRevertStore
from samverk.pull_request_review_assignment import ReviewAssignmentStore
from samverk.pull_request_review_freshness import (
    PullRequestReviewFreshnessStore)
from samverk.pull_request_review_notifications import ReviewNotificationStore
from samverk.pull_request_reviews import PullRequestReviewStore
from samverk.pull_request_search import PullRequestSearch
from samverk.pull_request_squash import PullRequestSquashStore
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


def make_commit(repo, parent, files, message, parents=()):
    tree = make_tree(repo, files)
    args = ["commit-tree", tree]
    for p in ((parent,) if parent else ()) + tuple(parents):
        args += ["-p", p]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


BASE_FILES = {"a.txt": "alpha\n"}
HEAD_FILES = {"a.txt": "alpha\nbeta\n"}


class PartVIIGateTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register(
            "volmarr", "correct horse battery")
        self.reviewer = self.accounts.register(
            "yrsa", "correct horse battery")
        self.third = self.accounts.register(
            "tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.forks = ForkStore(self.conn, self.root, self.accounts,
                               self.repos, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.labels = LabelStore(self.conn, self.repos, self.accounts,
                                 self.issues, audit=self.audit)
        kw = dict(audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.drafts = PullRequestDraftStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.convo = PullRequestConversationStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.reviews = PullRequestReviewStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.freshness = PullRequestReviewFreshnessStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.required = PullRequestRequiredReviewStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.assignments = ReviewAssignmentStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.mergeability = MergeabilityStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.merge = PullRequestMergeStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.squash = PullRequestSquashStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.rebase = PullRequestRebaseStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.checks = PullRequestChecksStore(
            self.conn, self.repos, self.accounts, self.issues,
            time_fn=self.clock)
        self.auto = PullRequestAutoMergeStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.revert = PullRequestRevertStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.notifs = ReviewNotificationStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.from_compare = PullRequestFromCompareStore(
            self.conn, self.repos, self.accounts, self.issues, **kw)
        self.search = PullRequestSearch(
            self.conn, self.repos, self.accounts, self.prs,
            self.labels, self.reviews, self.assignments)

    # -- helpers ------------------------------------------------------

    def _repo(self, name, visibility="public"):
        self.repos.create_repository(
            self.owner.id, "volmarr", name, visibility=visibility)
        return self.repos.path_for("volmarr", name)

    def _branches(self, path, base_files, steps):
        """Root on main plus a chain of head commits on
        feature; steps carry FULL tree snapshots. Returns
        (base_oid, head_oid)."""
        base_oid = make_commit(path, None, base_files, "base commit")
        git(path, "update-ref", "refs/heads/main", base_oid)
        parent = base_oid
        for files, message in steps:
            parent = make_commit(path, parent, files, message)
        git(path, "update-ref", "refs/heads/feature", parent)
        return base_oid, parent

    def _open_same(self, name="pub", *, base_files=None, steps=None,
                   draft=False, title=None, body="", actor=None,
                   visibility="public"):
        path = self._repo(name, visibility)
        base_oid, head_oid = self._branches(
            path, base_files or BASE_FILES,
            steps or [(HEAD_FILES, "feature work")])
        pr = self.prs.create_pull_request(
            actor or self.owner, "volmarr", name, base_branch="main",
            head_branch="feature", title=title, body=body, draft=draft)
        return pr, path, base_oid, head_oid

    def _open_fork(self, name="pub", *, head_files=None):
        """Base repo, yrsa's fork of it, one head commit in
        the fork, one cross-fork pull request opened by the
        fork's owner (who cannot write the base)."""
        path = self._repo(name)
        base_oid = make_commit(path, None, BASE_FILES, "base commit")
        git(path, "update-ref", "refs/heads/main", base_oid)
        self.forks.fork(self.reviewer.id, "volmarr", name)
        fork_path = self.repos.path_for("yrsa", name)
        head_oid = make_commit(
            fork_path, base_oid, head_files or HEAD_FILES, "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", head_oid)
        created = self.xprs.create_cross_fork_pull_request(
            self.reviewer, "volmarr", name, base_branch="main",
            head_owner="yrsa", head_repo=name, head_branch="feature")
        return created.pull_request, path, fork_path, base_oid, head_oid

    def _tip(self, path, branch="main"):
        return git(path, "rev-parse", f"refs/heads/{branch}")

    def _parents(self, path, oid):
        out = git(path, "show", "-s", "--format=%P", oid)
        return out.split() if out else []

    def _show(self, path, oid, name):
        return git(path, "show", f"{oid}:{name}")

    def _audit_count(self, action):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = ?",
            (action,)).fetchone()
        return int(row["c"])

    # -- the merge-commit lifecycle, across roles ----------------------

    def test_merge_commit_lifecycle_across_roles(self):
        path = self._repo("pub")
        bug = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Crash on save")
        base_oid, head_oid = self._branches(path, BASE_FILES,
                                            [(HEAD_FILES, "feature work")])
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature", title="Fix the crash",
            body=f"Fixes #{bug.number}")
        # Conversation: a reader converses on the PR.
        comment = self.convo.add_comment(
            self.reviewer, "volmarr", "pub", pr.number,
            "Reproduced it — the fix reads right.")
        self.assertIn("Reproduced", comment.body)
        # Assignment: the owner requests the reviewer's review,
        # and the request lands in her notification inbox.
        self.assignments.request_reviewers(
            self.owner, "volmarr", "pub", pr.number, ["@yrsa"])
        notes = self.notifs.notifications_for_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(any(
            n.recipient_id == self.reviewer.id
            and n.action == "review_request" for n in notes), notes)
        # Checks: pending, then passed, said in words.
        self.checks.record_result(
            "volmarr", "pub", head_oid, "ci/tests", "pending")
        self.checks.record_result(
            "volmarr", "pub", head_oid, "ci/tests", "passed",
            target_url="https://ci.example/run/1",
            description="all green")
        panel = self.checks.checks_for(
            self.reviewer, "volmarr", "pub", pr.number)
        self.assertEqual([c.state for c in panel], ["passed"])
        self.assertIn("Passed", panel[0].words)
        # The required-review seam before and after the review.
        need = ReviewRequirement(required_approvals=1)
        before = self.required.review_state_for(
            self.owner, "volmarr", "pub", pr.number, requirement=need)
        self.assertFalse(before.satisfied)
        self.assertEqual(before.approval_count, 0)
        self.reviews.submit_review(
            self.reviewer, "volmarr", "pub", pr.number,
            verdict="approve", summary="Looks right to me.")
        after = self.required.review_state_for(
            self.owner, "volmarr", "pub", pr.number, requirement=need)
        self.assertTrue(after.satisfied)
        self.assertEqual(after.approval_count, 1)
        self.assertTrue(after.has_approved(self.reviewer.id))
        # Mergeability says clean, in words, before anyone merges.
        report = self.mergeability.mergeability_for(
            self.reviewer, "volmarr", "pub", pr.number)
        self.assertTrue(report.mergeable)
        self.assertEqual(report.conflicting_files, ())
        self.assertIn("can be merged", report.words)
        # The merge lands: two parents, PR closed, issue closed.
        preview = self.merge.preview_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(preview.can_merge)
        result = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(result.pull_request.state, "closed")
        self.assertEqual(self._tip(path), result.merge_commit_oid)
        self.assertEqual(self._parents(path, result.merge_commit_oid),
                         [base_oid, head_oid])
        self.assertEqual(result.closed_issues,
                         (f"volmarr/pub#{bug.number}",))
        closed = self.issues.get_issue(
            self.owner, "volmarr", "pub", bug.number)
        self.assertEqual(closed.state, "closed")
        self.assertEqual(closed.state_reason, "completed")
        self.assertEqual(self._audit_count("repo.pull_request.merge"), 1)
        self.assertEqual(
            self._audit_count("repo.pull_request.review_submit"), 1)
        # Search finds the landed PR by its review and its state.
        by_review = self.search.search(
            self.owner, "volmarr", "pub", "is:pr review:approved")
        self.assertIn(pr.number, [p.number for p in by_review])
        by_state = self.search.search(
            self.owner, "volmarr", "pub", "is:pr status:closed")
        self.assertIn(pr.number, [p.number for p in by_state])
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, bad)

    # -- squash ---------------------------------------------------------

    def test_squash_lifecycle_two_commits_one_landing(self):
        path = self._repo("pub")
        bug = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Crash on save")
        steps = [({"a.txt": "alpha\nbeta\n"}, "first half"),
                 ({"a.txt": "alpha\nbeta\ngamma\n"}, "second half")]
        base_oid, head_oid = self._branches(path, BASE_FILES, steps)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature", title="Fix the crash",
            body=f"Fixes #{bug.number}")
        self.reviews.submit_review(
            self.reviewer, "volmarr", "pub", pr.number,
            verdict="approve", summary="Ship it.")
        preview = self.squash.preview_squash(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(preview.can_squash)
        self.assertEqual(preview.head_commit_count, 2)
        report = self.squash.squash_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        # One commit on the base, the head's final tree, the
        # PR's author preserved as the commit's author.
        self.assertEqual(self._tip(path), report.commit_oid)
        self.assertEqual(self._parents(path, report.commit_oid),
                         [base_oid])
        self.assertEqual(
            git(path, "show", "-s", "--format=%T", report.commit_oid),
            git(path, "show", "-s", "--format=%T", head_oid))
        self.assertEqual(report.author, "volmarr")
        self.assertEqual(
            git(path, "log", "-1", "--format=%an", report.commit_oid),
            "volmarr")
        landed = self.prs.get_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(landed.state, "closed")
        self.assertEqual(self.issues.get_issue(
            self.owner, "volmarr", "pub", bug.number).state, "closed")
        self.assertEqual(
            self._audit_count("repo.pull_request.squash_merge"), 1)

    # -- rebase ---------------------------------------------------------

    def test_rebase_lifecycle_onto_advanced_base(self):
        steps = [({"a.txt": "alpha\nbeta\n"}, "first half"),
                 ({"a.txt": "alpha\nbeta\n", "f.txt": "feature\n"},
                  "second half")]
        pr, path, base_oid, head_oid = self._open_same("pub", steps=steps)
        # The base advances after the PR opens (disjoint file).
        advanced = make_commit(
            path, base_oid,
            {"a.txt": "alpha\n", "u.txt": "upstream\n"}, "upstream work")
        git(path, "update-ref", "refs/heads/main", advanced)
        self.reviews.submit_review(
            self.reviewer, "volmarr", "pub", pr.number,
            verdict="approve", summary="Replay it.")
        report = self.rebase.rebase_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(report.up_to_date)
        self.assertEqual(len(report.replayed), 2)
        self.assertEqual(report.base_before, advanced)
        self.assertEqual(self._tip(path), report.base_after)
        # Linear landing: the replayed tip stands on the
        # advanced base, single-parented, carrying both
        # changes; the head branch never moved; the original
        # head commits were replayed, not merged.
        self.assertEqual(self._parents(path, report.base_after),
                         [report.replayed[0][1]])
        self.assertEqual(
            git(path, "merge-base", "--is-ancestor",
                advanced, report.base_after), "")
        self.assertEqual(self._show(path, report.base_after, "f.txt"),
                         "feature")
        self.assertEqual(self._show(path, report.base_after, "u.txt"),
                         "upstream")
        self.assertEqual(self._tip(path, "feature"), head_oid)
        self.assertNotIn(head_oid,
                         git(path, "rev-list", report.base_after).split())
        self.assertEqual(self._audit_count("repo.pull_request.rebase"), 1)
        # A second rebase is a quiet up-to-date report.
        again = self.rebase.rebase_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(again.up_to_date)
        self.assertEqual(again.replayed, ())

    # -- drafts block every method --------------------------------------

    def test_draft_blocks_all_merge_methods_until_ready(self):
        pr, path, base_oid, head_oid = self._open_same("pub", draft=True)
        readiness = self.drafts.readiness(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(readiness.is_draft)
        self.assertFalse(readiness.can_merge)
        for land in (
                lambda: self.merge.merge_pull_request(
                    self.owner, "volmarr", "pub", pr.number),
                lambda: self.squash.squash_pull_request(
                    self.owner, "volmarr", "pub", pr.number),
                lambda: self.rebase.rebase_pull_request(
                    self.owner, "volmarr", "pub", pr.number)):
            with self.assertRaises(PullRequestError) as caught:
                land()
            self.assertEqual(caught.exception.reason,
                             "pull_request_draft")
        self.assertEqual(self._tip(path), base_oid)
        self.drafts.mark_ready(self.owner, "volmarr", "pub", pr.number)
        ready = self.drafts.readiness(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(ready.is_draft)
        self.assertTrue(ready.can_merge)
        result = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(result.pull_request.state, "closed")
        self.assertEqual(self._tip(path), result.merge_commit_oid)

    # -- forks ------------------------------------------------------------

    def test_cross_fork_lifecycle_merge_commit(self):
        pr, path, fork_path, base_oid, head_oid = self._open_fork("pub")
        record = self.xprs.get_cross_fork(
            self.owner, "volmarr", "pub", pr.number)
        self.assertIsNotNone(record)
        self.assertIn("fork of volmarr/pub", record.relationship_words)
        # The fork's owner cannot write the base; the base's
        # owner reviews and lands the fork's work.
        self.assertFalse(can_merge(
            self.reviewer, self.repos.get_repository("volmarr", "pub")))
        self.reviews.submit_review(
            self.owner, "volmarr", "pub", pr.number,
            verdict="approve", summary="Welcome aboard.")
        report = self.mergeability.mergeability_for(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(report.mergeable)
        result = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(self._tip(path), result.merge_commit_oid)
        self.assertEqual(self._parents(path, result.merge_commit_oid),
                         [base_oid, head_oid])
        self.assertEqual(self._show(path, result.merge_commit_oid,
                                    "a.txt"), "alpha\nbeta")
        # The fork itself is untouched by the landing.
        self.assertEqual(self._tip(fork_path, "feature"), head_oid)
        self.assertEqual(self._tip(fork_path, "main"), base_oid)

    def test_cross_fork_squash_lands_in_base_fork_untouched(self):
        pr, path, fork_path, base_oid, head_oid = self._open_fork("pub")
        report = self.squash.squash_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(self._tip(path), report.commit_oid)
        self.assertEqual(self._parents(path, report.commit_oid),
                         [base_oid])
        self.assertEqual(report.author, "yrsa")
        self.assertEqual(self._show(path, report.commit_oid, "a.txt"),
                         "alpha\nbeta")
        self.assertEqual(self._tip(fork_path, "feature"), head_oid)
        landed = self.prs.get_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(landed.state, "closed")

    def test_cross_fork_rebase_refuses_cleanly(self):
        # The rebase road reads its head in the base
        # repository; a cross-fork head lives in the fork, so
        # the landing refuses by name and changes nothing.
        pr, path, fork_path, base_oid, head_oid = self._open_fork("pub")
        with self.assertRaises(PullRequestError) as caught:
            self.rebase.rebase_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, "branch_not_found")
        self.assertEqual(self._tip(path), base_oid)
        self.assertEqual(self._tip(fork_path, "feature"), head_oid)
        still = self.prs.get_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(still.state, "open")

    # -- roles ------------------------------------------------------------

    def test_roles_merge_permission_and_self_review_law(self):
        pr, path, base_oid, head_oid = self._open_same("pub")
        repo = self.repos.get_repository("volmarr", "pub")
        self.assertTrue(can_merge(self.owner, repo))
        self.assertFalse(can_merge(self.reviewer, repo))
        self.assertFalse(can_merge(None, repo))
        standing = merge_permission(self.reviewer, repo, number=pr.number)
        self.assertFalse(standing.allowed)
        self.assertEqual(standing.reason, "permission_denied")
        self.assertIn("Only a writer", standing.words)
        # A reader converses and reviews, but never merges —
        # by any method.
        for land in (
                lambda: self.merge.merge_pull_request(
                    self.reviewer, "volmarr", "pub", pr.number),
                lambda: self.squash.squash_pull_request(
                    self.reviewer, "volmarr", "pub", pr.number),
                lambda: self.rebase.rebase_pull_request(
                    self.reviewer, "volmarr", "pub", pr.number)):
            with self.assertRaises(PullRequestError) as caught:
                land()
            self.assertEqual(caught.exception.reason,
                             "permission_denied")
        self.assertEqual(self._tip(path), base_oid)
        # The author can comment on their own PR but can
        # neither approve it nor request changes on it.
        with self.assertRaises(PullRequestError) as caught:
            self.reviews.submit_review(
                self.owner, "volmarr", "pub", pr.number,
                verdict="approve", summary="My own work is great.")
        self.assertEqual(caught.exception.reason, "self_review")
        with self.assertRaises(PullRequestError) as caught:
            self.reviews.submit_review(
                self.owner, "volmarr", "pub", pr.number,
                verdict="request_changes", summary="Fix myself.")
        self.assertEqual(caught.exception.reason, "self_review")
        own = self.reviews.submit_review(
            self.owner, "volmarr", "pub", pr.number,
            verdict="comment", summary="A note on my own work.")
        self.assertEqual(own.verdict, "commented")
        # Anonymous readers can read a public PR.
        seen = self.prs.get_pull_request(None, "volmarr", "pub", pr.number)
        self.assertEqual(seen.number, pr.number)

    def test_private_repo_uniform_not_found_on_every_surface(self):
        pr, path, base_oid, head_oid = self._open_same(
            "priv", visibility="private")
        surfaces = (
            lambda v: self.prs.get_pull_request(v, "volmarr", "priv",
                                                pr.number),
            lambda v: self.reviews.reviews_for(v, "volmarr", "priv",
                                               pr.number),
            lambda v: self.mergeability.mergeability_for(
                v, "volmarr", "priv", pr.number),
            lambda v: self.required.review_state_for(
                v, "volmarr", "priv", pr.number),
            lambda v: self.merge.merge_pull_request(
                v, "volmarr", "priv", pr.number),
        )
        for viewer in (self.third, None):
            for call in surfaces:
                with self.assertRaises(PullRequestError) as caught:
                    call(viewer)
                self.assertEqual(caught.exception.reason,
                                 "pull_request_not_found")
            # Search rides S-141's list seam, whose uniform
            # private answer is the repository's own
            # repo_not_found (pinned by S-161's battery) —
            # the same no-leak law, said at the repo level.
            with self.assertRaises(PullRequestError) as caught:
                self.search.search(viewer, "volmarr", "priv", "is:pr")
            self.assertEqual(caught.exception.reason, "repo_not_found")
        # The owner walks the same surfaces fine.
        seen = self.prs.get_pull_request(
            self.owner, "volmarr", "priv", pr.number)
        self.assertEqual(seen.number, pr.number)
        self.assertEqual(self._tip(path), base_oid)

    # -- conflicts ---------------------------------------------------------

    def test_conflicts_surface_before_merge_and_block_all_roads(self):
        path = self._repo("pub")
        base_oid = make_commit(path, None, {"a.txt": "one\n"},
                               "base commit")
        git(path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(path, base_oid, {"a.txt": "one\nfeature\n"},
                               "feature work")
        git(path, "update-ref", "refs/heads/feature", head_oid)
        advanced = make_commit(path, base_oid, {"a.txt": "one\nmain\n"},
                               "main work")
        git(path, "update-ref", "refs/heads/main", advanced)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature", title="Conflicting work")
        # The conflict is known before anyone presses merge.
        report = self.mergeability.mergeability_for(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(report.mergeable)
        self.assertEqual(report.conflicting_files, ("a.txt",))
        self.assertIn("a.txt", report.words)
        preview = self.merge.preview_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(preview.conflicts)
        self.assertFalse(preview.can_merge)
        with self.assertRaises(PullRequestError):
            self.merge.merge_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        with self.assertRaises(PullRequestError) as caught:
            self.rebase.rebase_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, "rebase_conflict")
        # Nothing landed, nothing half-landed, the PR is open.
        self.assertEqual(self._tip(path), advanced)
        self.assertEqual(self._tip(path, "feature"), head_oid)
        still = self.prs.get_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(still.state, "open")

    # -- checks + auto-merge ------------------------------------------------

    def test_checks_panel_and_auto_merge_fire_through_real_merger(self):
        pr, path, base_oid, head_oid = self._open_same("pub")
        record = self.auto.arm_auto_merge(
            self.owner, "volmarr", "pub", pr.number,
            strategy="merge", required_checks=("ci/tests",))
        self.assertTrue(record.is_armed)
        waiting = self.auto.evaluate(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(waiting.requirements_met)
        self.assertTrue(waiting.blockers)
        self.checks.record_result(
            "volmarr", "pub", head_oid, "ci/tests", "failed")
        failing = self.auto.evaluate(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(failing.requirements_met)
        self.checks.record_result(
            "volmarr", "pub", head_oid, "ci/tests", "passed")
        ready = self.auto.evaluate(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(ready.requirements_met)
        self.assertEqual(ready.blockers, ())
        self.auto.set_merger(
            lambda actor, owner, repo, number:
            self.merge.merge_pull_request(actor, owner, repo, number))
        outcome = self.auto.try_fire(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(outcome.fired)
        self.assertEqual(self._tip(path), outcome.merge_commit_oid)
        landed = self.prs.get_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(landed.state, "closed")
        final = self.auto.get_auto_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(final.state, "fired")
        self.assertEqual(
            self._audit_count("repo.pull_request.auto_merge_fire"), 1)

    # -- revert --------------------------------------------------------------

    def test_revert_of_merged_pr_links_both_ways_and_lands(self):
        pr, path, base_oid, head_oid = self._open_same("pub")
        merged = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(self._show(path, merged.merge_commit_oid,
                                    "a.txt"), "alpha\nbeta")
        result = self.revert.revert_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(result.original.number, pr.number)
        self.assertEqual(result.revert.state, "open")
        self.assertIn(f'Revert "{pr.title}"', result.revert.title)
        forward = self.revert.revert_of(
            self.owner, "volmarr", "pub", result.revert.number)
        self.assertIsNotNone(forward)
        self.assertEqual(forward.original_number, pr.number)
        back = self.revert.reverted_by(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual([r.revert_number for r in back],
                         [result.revert.number])
        landed = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", result.revert.number)
        self.assertEqual(self._show(path, landed.merge_commit_oid,
                                    "a.txt"), "alpha")
        self.assertEqual(
            self._audit_count("repo.pull_request.revert"), 1)

    # -- freshness + the required-review seam --------------------------------

    def test_freshness_stales_approval_and_required_seam_recovers(self):
        pr, path, base_oid, head_oid = self._open_same("pub")
        self.freshness.set_policy(self.owner, "volmarr", "pub",
                                  "approvals")
        self.reviews.submit_review(
            self.reviewer, "volmarr", "pub", pr.number,
            verdict="approve", summary="Good as it stands.")
        need = ReviewRequirement(required_approvals=1)
        fresh = self.freshness.freshness_for(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(fresh.has_counting_approval)
        self.assertTrue(self.required.review_state_for(
            self.owner, "volmarr", "pub", pr.number,
            requirement=need).satisfied)
        # A push moves the head; the approval stops counting.
        new_head = make_commit(
            path, head_oid, {"a.txt": "alpha\nbeta\ngamma\n"},
            "more work")
        git(path, "update-ref", "refs/heads/feature", new_head)
        stale = self.freshness.freshness_for(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(stale.stale_count, 1)
        self.assertFalse(stale.has_counting_approval)
        state = self.required.review_state_for(
            self.owner, "volmarr", "pub", pr.number, requirement=need)
        self.assertFalse(state.satisfied)
        self.assertEqual(state.approval_count, 0)
        self.assertTrue(state.blockers)
        # A fresh approval on the new head satisfies it again.
        self.reviews.submit_review(
            self.reviewer, "volmarr", "pub", pr.number,
            verdict="approve", summary="Still good.")
        self.assertTrue(self.required.review_state_for(
            self.owner, "volmarr", "pub", pr.number,
            requirement=need).satisfied)

    # -- search + from-compare on the assembled system ------------------------

    def test_search_and_from_compare_on_the_assembled_system(self):
        path = self._repo("pub")
        base_oid, head_oid = self._branches(path, BASE_FILES,
                                            [(HEAD_FILES, "feature work")])
        offer = self.from_compare.offer(
            self.owner, "volmarr", "pub", "main", "feature")
        self.assertTrue(offer.can_open)
        self.assertEqual(offer.compare.ahead, 1)
        pr = self.from_compare.open_from_compare(
            self.owner, "volmarr", "pub", "main", "feature",
            title="Opened from compare")
        self.assertEqual(pr.title, "Opened from compare")
        self.assertEqual((pr.base_oid, pr.head_oid), (base_oid, head_oid))
        found = self.search.search(
            self.reviewer, "volmarr", "pub", "is:pr status:open compare")
        self.assertIn(pr.number, [p.number for p in found])
        missed = self.search.search(
            self.reviewer, "volmarr", "pub", "is:pr status:closed")
        self.assertNotIn(pr.number, [p.number for p in missed])

    # -- gate invariants -------------------------------------------------------

    def test_gate_invariants_schema_taxonomy_and_audit_chain(self):
        # The gate builds nothing of its own: no migration,
        # no taxonomy event — the assembled system stands
        # exactly where S-167 left it.
        self.assertEqual(schema_version(self.conn), 66)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 119)
        pr, path, base_oid, head_oid = self._open_same("pub")
        self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(schema_version(self.conn), 66)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 119)
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, bad)


if __name__ == "__main__":
    unittest.main()
