"""S-152 acceptance battery: pull request review assignment.

Acceptance (roadmap S-152): review assignment —
individuals and teams requested; re-request and
dismissal recorded.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.forks import ForkStore
from samverk.issues import IssueStore
from samverk.pull_request_codeowners import PullRequestCodeownersStore
from samverk.pull_request_forks import ForkPullRequestStore
from samverk.pull_request_review_assignment import (
    ReviewAssignmentStore, render_review_assignments)
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


class ReviewAssignmentTests(unittest.TestCase):
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
        self.codeowners = PullRequestCodeownersStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.assign = ReviewAssignmentStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")

    # -- helpers ---------------------------------------------------------
    def _open(self, base_files=None, head_files=None, *, name="pub"):
        if name != "pub":
            self.repos.create_repository(
                self.owner.id, "volmarr", name, visibility="public")
        path = self.repos.path_for("volmarr", name)
        base_files = base_files or {"a.txt": "alpha\n"}
        head_files = head_files or {"a.txt": "alpha\nbeta\n"}
        base_oid = make_commit(path, None, base_files, "base")
        git(path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(path, base_oid, head_files, "feature work")
        git(path, "update-ref", "refs/heads/feature", head_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", name,
            base_branch="main", head_branch="feature")
        return pr, path, base_oid, head_oid

    def _open_cross_fork(self):
        base_oid = make_commit(
            self.path, None, {"a.txt": "alpha\n"}, "base")
        git(self.path, "update-ref", "refs/heads/main", base_oid)
        self.forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fork_head = make_commit(
            fork_path, base_oid, {"a.txt": "alpha\nfrom the fork\n"},
            "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        return self.xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub", head_branch="feature")

    def _audit_count(self, action):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = ?",
            (action,)).fetchone()
        return int(row["c"])

    def _rows(self, number, name="pub", viewer=None):
        return self.assign.requests_for(
            viewer or self.owner, "volmarr", name, number)

    def _event_kinds(self, number=None):
        rows = self.conn.execute(
            "SELECT kind FROM pull_request_review_request_events"
            " ORDER BY id").fetchall()
        return [r["kind"] for r in rows]

    # -- requesting ---------------------------------------------------------
    def test_manual_request_of_individual_and_team(self):
        pr, _p, _b, head_oid = self._open()
        report = self.assign.request_reviewers(
            self.owner, "volmarr", "pub", pr.number,
            ["@yrsa", "@volmarr/core"])
        self.assertEqual(report.requested_now, ("@yrsa", "@volmarr/core"))
        self.assertEqual(report.rerequested, ())
        rows = self._rows(pr.number)
        self.assertEqual([r.owner_ref for r in rows],
                         ["@yrsa", "@volmarr/core"])
        self.assertEqual(rows[0].user_id, self.reader.id)
        self.assertIsNone(rows[1].user_id)
        self.assertEqual([r.source for r in rows], ["manual", "manual"])
        self.assertEqual([r.state for r in rows],
                         ["requested", "requested"])
        self.assertEqual(rows[0].head_oid, head_oid)
        self.assertEqual(rows[0].rerequest_count, 0)
        self.assertEqual(
            self._audit_count("repo.pull_request.review_request"), 1)
        self.assertEqual(self._event_kinds(), ["request", "request"])

    def test_invalid_token_refuses_the_whole_batch(self):
        pr, _p, _b, _h = self._open()
        for bad in ("someone@example.com", "yrsa", "@", "@yrsa/team/x",
                    "bogus!"):
            with self.assertRaises(PullRequestError) as caught:
                self.assign.request_reviewers(
                    self.owner, "volmarr", "pub", pr.number,
                    ["@yrsa", bad])
            self.assertEqual(caught.exception.reason, "owner_ref_invalid",
                             msg=bad)
            self.assertIn("owner_ref_invalid", str(caught.exception))
        self.assertEqual(self._rows(pr.number), [])
        self.assertEqual(
            self._audit_count("repo.pull_request.review_request"), 0)
        self.assertEqual(self._event_kinds(), [])

    def test_author_token_is_excluded_and_the_rest_still_land(self):
        pr, _p, _b, _h = self._open()
        report = self.assign.request_reviewers(
            self.owner, "volmarr", "pub", pr.number,
            ["@volmarr", "@yrsa"])
        self.assertEqual(report.skipped_author, ("@volmarr",))
        self.assertEqual(report.requested_now, ("@yrsa",))
        self.assertEqual([r.owner_ref for r in self._rows(pr.number)],
                         ["@yrsa"])

    def test_a_closed_pull_request_takes_no_requests(self):
        pr, _p, _b, _h = self._open()
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE id = ?",
                (pr.row_id,))
        with self.assertRaises(PullRequestError) as caught:
            self.assign.request_reviewers(
                self.owner, "volmarr", "pub", pr.number, ["@yrsa"])
        self.assertEqual(caught.exception.reason, "pull_request_closed")
        self.assertEqual(self._rows(pr.number), [])
        self.assertEqual(
            self._audit_count("repo.pull_request.review_request"), 0)

    def test_duplicate_active_request_is_a_quiet_noop(self):
        pr, _p, _b, _h = self._open()
        self.assign.request_reviewers(
            self.owner, "volmarr", "pub", pr.number, ["@yrsa"])
        report = self.assign.request_reviewers(
            self.owner, "volmarr", "pub", pr.number, ["@yrsa"])
        self.assertEqual(report.requested_now, ())
        self.assertEqual(report.already_requested, ("@yrsa",))
        self.assertEqual(len(self._rows(pr.number)), 1)
        self.assertEqual(
            self._audit_count("repo.pull_request.review_request"), 1)
        self.assertEqual(self._event_kinds(), ["request"])

    # -- dismissal and re-request -------------------------------------------
    def test_dismiss_records_who_and_when_and_the_row_stays_visible(self):
        pr, _p, _b, _h = self._open()
        self.assign.request_reviewers(
            self.owner, "volmarr", "pub", pr.number, ["@yrsa"])
        self.clock.now += 100
        dismissed = self.assign.dismiss_request(
            self.owner, "volmarr", "pub", pr.number, "@yrsa")
        self.assertEqual(dismissed.state, "dismissed")
        self.assertTrue(dismissed.is_dismissed)
        self.assertEqual(dismissed.dismissed_by, self.owner.id)
        self.assertEqual(dismissed.dismissed_at, 1_700_000_100)
        self.assertEqual(dismissed.dismissed_by_username, "volmarr")
        rows = self._rows(pr.number)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].state, "dismissed")
        self.assertIn("volmarr", rows[0].dismissal_words)
        self.assertEqual(
            self._audit_count("repo.pull_request.review_dismiss"), 1)
        self.assertEqual(self._event_kinds(), ["request", "dismiss"])

    def test_dismiss_of_a_ref_with_no_active_request_is_refused(self):
        pr, _p, _b, _h = self._open()
        with self.assertRaises(PullRequestError) as caught:
            self.assign.dismiss_request(
                self.owner, "volmarr", "pub", pr.number, "@yrsa")
        self.assertEqual(caught.exception.reason, "request_not_found")
        self.assign.request_reviewers(
            self.owner, "volmarr", "pub", pr.number, ["@yrsa"])
        self.assign.dismiss_request(
            self.owner, "volmarr", "pub", pr.number, "@yrsa")
        with self.assertRaises(PullRequestError) as caught:
            self.assign.dismiss_request(
                self.owner, "volmarr", "pub", pr.number, "@yrsa")
        self.assertEqual(caught.exception.reason, "request_not_found")
        self.assertEqual(
            self._audit_count("repo.pull_request.review_dismiss"), 1)

    def test_rerequest_after_dismissal_reactivates_and_records(self):
        pr, _p, _b, _h = self._open()
        self.assign.request_reviewers(
            self.owner, "volmarr", "pub", pr.number, ["@yrsa"])
        self.assign.dismiss_request(
            self.owner, "volmarr", "pub", pr.number, "@yrsa")
        report = self.assign.request_reviewers(
            self.owner, "volmarr", "pub", pr.number, ["@yrsa"])
        self.assertEqual(report.requested_now, ())
        self.assertEqual(report.rerequested, ("@yrsa",))
        rows = self._rows(pr.number)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].state, "requested")
        self.assertIsNone(rows[0].dismissed_by)
        self.assertIsNone(rows[0].dismissed_at)
        self.assertEqual(rows[0].rerequest_count, 1)
        self.assertEqual(
            self._audit_count("repo.pull_request.review_request"), 1)
        self.assertEqual(
            self._audit_count("repo.pull_request.review_rerequest"), 1)
        self.assertEqual(self._event_kinds(),
                         ["request", "dismiss", "rerequest"])

    def test_dismissal_prefers_the_manual_row_over_codeowners(self):
        pr, _p, _b, _h = self._open(
            {"CODEOWNERS": "a.txt @yrsa\n", "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"})
        self.codeowners.sync_requests(
            self.owner, "volmarr", "pub", pr.number)
        self.assign.request_reviewers(
            self.owner, "volmarr", "pub", pr.number, ["@yrsa"])
        self.assign.dismiss_request(
            self.owner, "volmarr", "pub", pr.number, "@yrsa")
        by_source = {r.source: r for r in self._rows(pr.number)}
        self.assertEqual(by_source["manual"].state, "dismissed")
        self.assertEqual(by_source["codeowners"].state, "requested")
        self.assign.dismiss_request(
            self.owner, "volmarr", "pub", pr.number, "@yrsa")
        by_source = {r.source: r for r in self._rows(pr.number)}
        self.assertEqual(by_source["codeowners"].state, "dismissed")

    def test_a_codeowners_dismissed_row_is_not_resurrected_by_sync(self):
        pr, _p, _b, _h = self._open(
            {"CODEOWNERS": "a.txt @yrsa\n", "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"})
        first = self.codeowners.sync_requests(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(first.requested_now, ("@yrsa",))
        self.assign.dismiss_request(
            self.owner, "volmarr", "pub", pr.number, "@yrsa")
        second = self.codeowners.sync_requests(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(second.requested_now, ())
        rows = self._rows(pr.number)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, "codeowners")
        self.assertEqual(rows[0].state, "dismissed")

    # -- permissions -----------------------------------------------------------
    def test_the_author_can_request_on_a_cross_fork_pull_request(self):
        pr = self._open_cross_fork()
        report = self.assign.request_reviewers(
            self.reader, "volmarr", "pub", pr.number, ["@tess"])
        self.assertEqual(report.requested_now, ("@tess",))
        self.assertEqual([r.owner_ref for r in self._rows(pr.number)],
                         ["@tess"])

    def test_a_base_repository_writer_can_request_and_dismiss(self):
        pr = self._open_cross_fork()
        report = self.assign.request_reviewers(
            self.owner, "volmarr", "pub", pr.number, ["@tess"])
        self.assertEqual(report.requested_now, ("@tess",))
        dismissed = self.assign.dismiss_request(
            self.owner, "volmarr", "pub", pr.number, "@tess")
        self.assertEqual(dismissed.state, "dismissed")

    def test_a_public_repo_non_writer_gets_permission_denied(self):
        pr, _p, _b, _h = self._open()
        with self.assertRaises(PullRequestError) as caught:
            self.assign.request_reviewers(
                self.third, "volmarr", "pub", pr.number, ["@yrsa"])
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertIn("permission_denied", str(caught.exception))
        self.assign.request_reviewers(
            self.owner, "volmarr", "pub", pr.number, ["@yrsa"])
        with self.assertRaises(PullRequestError) as caught:
            self.assign.dismiss_request(
                self.third, "volmarr", "pub", pr.number, "@yrsa")
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertEqual(self._rows(pr.number)[0].state, "requested")

    def test_a_private_repo_stranger_gets_pull_request_not_found(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        priv_path = self.repos.path_for("volmarr", "priv")
        base_oid = make_commit(priv_path, None, {"s.txt": "s\n"}, "one")
        git(priv_path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(
            priv_path, base_oid, {"s.txt": "s\nmore\n"}, "two")
        git(priv_path, "update-ref", "refs/heads/feature", head_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "priv", base_branch="main",
            head_branch="feature")
        for call in (
                lambda: self.assign.request_reviewers(
                    self.reader, "volmarr", "priv", pr.number, ["@tess"]),
                lambda: self.assign.dismiss_request(
                    self.reader, "volmarr", "priv", pr.number, "@tess"),
                lambda: self.assign.requests_for(
                    self.reader, "volmarr", "priv", pr.number)):
            with self.assertRaises(PullRequestError) as caught:
                call()
            self.assertEqual(
                caught.exception.reason, "pull_request_not_found")

    # -- counts and render -------------------------------------------------------
    def test_schema_and_taxonomy_counts(self):
        self.assertEqual(db.schema_version(self.conn), 61)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 116)
        self.assertIn("repo.pull_request.review_request",
                      taxonomy.AUDIT_EVENTS)
        self.assertIn("repo.pull_request.review_rerequest",
                      taxonomy.AUDIT_EVENTS)
        self.assertIn("repo.pull_request.review_dismiss",
                      taxonomy.AUDIT_EVENTS)

    def test_render_says_states_in_words(self):
        pr, _p, _b, _h = self._open()
        self.assign.request_reviewers(
            self.owner, "volmarr", "pub", pr.number,
            ["@yrsa", "@tess"])
        self.assign.dismiss_request(
            self.owner, "volmarr", "pub", pr.number, "@tess")
        html = render_review_assignments(self._rows(pr.number))
        self.assertIn("@yrsa", html)
        self.assertIn("requested", html)
        self.assertIn("@tess", html)
        self.assertIn("dismissed", html)
        self.assertIn("dismissed by volmarr", html)
        self.assertIn("manual", html)
        empty = render_review_assignments([])
        self.assertIn("No reviewers", empty)
        report = self.assign.request_reviewers(
            self.owner, "volmarr", "pub", pr.number, ["@yrsa"])
        self.assertIn("already requested",
                      render_review_assignments(report))


if __name__ == "__main__":
    unittest.main()
