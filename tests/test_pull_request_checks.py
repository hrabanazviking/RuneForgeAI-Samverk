"""S-157 acceptance battery: pull request checks panel.

Acceptance (roadmap S-157): Checks panel — external
status/check results (Part XII API, Part XVI CI) listed
on the PR with links; pending/failed/passed are
text+icon, never colour-only.

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
from samverk.pull_request_checks import (
    PullRequestChecksStore, render_pull_request_checks)
from samverk.pull_request_forks import ForkPullRequestStore
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


class PullRequestChecksTests(unittest.TestCase):
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
        self.checks = PullRequestChecksStore(
            self.conn, self.repos, self.accounts, self.issues,
            time_fn=self.clock)
        self.xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")

    # -- helpers ---------------------------------------------------

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
        pr = self.xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub", head_branch="feature")
        return pr, fork_head

    def _rows(self, number, name="pub", viewer=None):
        return self.checks.checks_for(
            viewer or self.owner, "volmarr", name, number)

    def _record_three(self, head_oid, name="pub"):
        self.checks.record_result(
            "volmarr", name, head_oid, "ci/tests", "passed",
            target_url="https://ci.example/runs/1",
            description="128 tests, all green")
        self.checks.record_result(
            "volmarr", name, head_oid, "ci/lint", "failed",
            target_url="https://ci.example/runs/2",
            description="2 warnings treated as errors")
        self.checks.record_result(
            "volmarr", name, head_oid, "deploy/preview", "pending")

    # -- recording and listing --------------------------------------

    def test_all_three_states_list_on_the_pr(self):
        pr, _p, _b, head_oid = self._open()
        self._record_three(head_oid)
        rows = self._rows(pr.number)
        self.assertEqual([r.context for r in rows],
                         ["ci/tests", "ci/lint", "deploy/preview"])
        self.assertEqual([r.state for r in rows],
                         ["passed", "failed", "pending"])
        self.assertEqual([r.number for r in rows], [pr.number] * 3)
        self.assertEqual([r.head_oid for r in rows], [head_oid] * 3)
        self.assertTrue(rows[0].is_passed)
        self.assertTrue(rows[1].is_failed)
        self.assertTrue(rows[2].is_pending)
        self.assertEqual(rows[0].target_url, "https://ci.example/runs/1")
        self.assertEqual(rows[0].description, "128 tests, all green")
        self.assertEqual(rows[0].created_at, 1_700_000_000)
        self.assertEqual(rows[0].updated_at, 1_700_000_000)
        by_commit = self.checks.checks_for_commit(
            "volmarr", "pub", head_oid)
        self.assertEqual([r.context for r in by_commit],
                         ["ci/tests", "ci/lint", "deploy/preview"])

    def test_state_defaults_to_pending_and_link_fields_to_empty(self):
        pr, _p, _b, head_oid = self._open()
        row = self.checks.record_result(
            "volmarr", "pub", head_oid, "ci/tests")
        self.assertEqual(row.state, "pending")
        self.assertEqual(row.target_url, "")
        self.assertEqual(row.description, "")
        rows = self._rows(pr.number)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].state, "pending")

    def test_a_rereport_updates_the_same_row(self):
        pr, _p, _b, head_oid = self._open()
        first = self.checks.record_result(
            "volmarr", "pub", head_oid, "ci/tests", "pending")
        self.clock.now += 50
        again = self.checks.record_result(
            "volmarr", "pub", head_oid, "ci/tests", "passed",
            target_url="https://ci.example/runs/9",
            description="green on the second run")
        self.assertEqual(again.id, first.id)
        rows = self._rows(pr.number)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].state, "passed")
        self.assertEqual(rows[0].target_url, "https://ci.example/runs/9")
        self.assertEqual(rows[0].description, "green on the second run")
        self.assertEqual(rows[0].created_at, 1_700_000_000)
        self.assertEqual(rows[0].updated_at, 1_700_000_050)

    def test_checks_are_scoped_to_head_and_repository(self):
        pr, _p, base_oid, head_oid = self._open()
        self.checks.record_result(
            "volmarr", "pub", head_oid, "ci/tests", "passed")
        self.checks.record_result(
            "volmarr", "pub", base_oid, "ci/tests", "failed")
        self.repos.create_repository(
            self.owner.id, "volmarr", "other", visibility="public")
        # The same commit oid named in another repository is
        # that repository's business, not this pull request's.
        self.checks.record_result(
            "volmarr", "other", head_oid, "ci/lint", "failed")
        rows = self._rows(pr.number)
        self.assertEqual([r.context for r in rows], ["ci/tests"])
        self.assertEqual(rows[0].state, "passed")
        other_rows = self.checks.checks_for_commit(
            "volmarr", "other", head_oid)
        self.assertEqual([r.context for r in other_rows], ["ci/lint"])

    def test_a_cross_fork_pr_lists_checks_on_its_base_repository(self):
        pr, fork_head = self._open_cross_fork()
        self.checks.record_result(
            "volmarr", "pub", fork_head, "ci/tests", "passed",
            target_url="https://ci.example/runs/3")
        rows = self.checks.checks_for(
            self.reader, "volmarr", "pub", pr.number)
        self.assertEqual([r.context for r in rows], ["ci/tests"])
        self.assertEqual(rows[0].head_oid, fork_head)
        self.assertEqual(rows[0].state, "passed")

    # -- validation ---------------------------------------------------

    def test_a_state_outside_the_three_words_is_refused(self):
        pr, _p, _b, head_oid = self._open()
        for bad in ("success", "error", "Passed", "", "queued"):
            with self.assertRaises(PullRequestError) as caught:
                self.checks.record_result(
                    "volmarr", "pub", head_oid, "ci/tests", bad)
            self.assertEqual(caught.exception.reason,
                             "check_state_invalid", msg=bad)
            self.assertIn("check_state_invalid", str(caught.exception))
        self.assertEqual(self._rows(pr.number), [])

    def test_a_blank_context_or_head_is_refused(self):
        pr, _p, _b, head_oid = self._open()
        for bad in ("", "   "):
            with self.assertRaises(PullRequestError) as caught:
                self.checks.record_result(
                    "volmarr", "pub", head_oid, bad, "passed")
            self.assertEqual(caught.exception.reason,
                             "check_context_invalid", msg=repr(bad))
        with self.assertRaises(PullRequestError) as caught:
            self.checks.record_result(
                "volmarr", "pub", "  ", "ci/tests", "passed")
        self.assertEqual(caught.exception.reason, "check_head_invalid")
        self.assertEqual(self._rows(pr.number), [])

    def test_a_link_that_is_not_http_is_refused(self):
        pr, _p, _b, head_oid = self._open()
        for bad in ("javascript:alert(1)", "ftp://ci.example/x",
                    "/runs/1", "ci.example/runs/1"):
            with self.assertRaises(PullRequestError) as caught:
                self.checks.record_result(
                    "volmarr", "pub", head_oid, "ci/tests", "passed",
                    target_url=bad)
            self.assertEqual(caught.exception.reason,
                             "check_url_invalid", msg=bad)
        self.assertEqual(self._rows(pr.number), [])
        ok = self.checks.record_result(
            "volmarr", "pub", head_oid, "ci/tests", "passed",
            target_url="http://ci.example/runs/1")
        self.assertEqual(ok.target_url, "http://ci.example/runs/1")

    def test_an_unknown_repository_is_refused(self):
        with self.assertRaises(PullRequestError) as caught:
            self.checks.record_result(
                "volmarr", "nope", "abc123", "ci/tests", "passed")
        self.assertEqual(caught.exception.reason, "repository_not_found")
        with self.assertRaises(PullRequestError) as caught:
            self.checks.checks_for_commit("volmarr", "nope", "abc123")
        self.assertEqual(caught.exception.reason, "repository_not_found")

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
            self.owner, "volmarr", "priv",
            base_branch="main", head_branch="feature")
        self.checks.record_result(
            "volmarr", "priv", head_oid, "ci/tests", "passed")
        with self.assertRaises(PullRequestError) as caught:
            self.checks.checks_for(
                self.reader, "volmarr", "priv", pr.number)
        self.assertEqual(caught.exception.reason,
                         "pull_request_not_found")
        rows = self.checks.checks_for(
            self.owner, "volmarr", "priv", pr.number)
        self.assertEqual([r.context for r in rows], ["ci/tests"])

    # -- counts and render ---------------------------------------------

    def test_schema_version_and_taxonomy_counts(self):
        self.assertEqual(db.schema_version(self.conn), 128)
        # S-157 adds no audit event: the poster's scoped
        # identity and its audit-logging are S-246's law.
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertIn("repo.pull_request.review_request",
                      taxonomy.AUDIT_EVENTS)

    def test_render_says_every_state_in_words_with_icons(self):
        pr, _p, _b, head_oid = self._open()
        self._record_three(head_oid)
        html = render_pull_request_checks(self._rows(pr.number))
        self.assertIn("ci/tests", html)
        self.assertIn("Passed", html)
        self.assertIn("✓", html)
        self.assertIn("ci/lint", html)
        self.assertIn("Failed", html)
        self.assertIn("✗", html)
        self.assertIn("deploy/preview", html)
        self.assertIn("Pending", html)
        self.assertIn("◐", html)
        self.assertIn("128 tests, all green", html)

    def test_render_links_only_when_a_url_exists(self):
        pr, _p, _b, head_oid = self._open()
        self._record_three(head_oid)
        html = render_pull_request_checks(self._rows(pr.number))
        self.assertIn('href="https://ci.example/runs/1"', html)
        self.assertIn('href="https://ci.example/runs/2"', html)
        self.assertEqual(html.count("View details"), 2)
        self.assertEqual(html.count("<a "), 2)

    def test_render_escapes_context_description_and_url(self):
        pr, _p, _b, head_oid = self._open()
        self.checks.record_result(
            "volmarr", "pub", head_oid, "ci/<script>", "failed",
            target_url="https://ci.example/runs?a=1&b=2",
            description="broke <b>here</b>")
        html = render_pull_request_checks(self._rows(pr.number))
        self.assertIn("ci/&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertIn("broke &lt;b&gt;here&lt;/b&gt;", html)
        self.assertIn('href="https://ci.example/runs?a=1&amp;b=2"',
                      html)

    def test_render_empty_state_and_tally_in_words(self):
        pr, _p, _b, head_oid = self._open()
        empty = render_pull_request_checks(self._rows(pr.number))
        self.assertIn("No checks have been reported", empty)
        self.checks.record_result(
            "volmarr", "pub", head_oid, "ci/tests", "passed")
        one = render_pull_request_checks(self._rows(pr.number))
        self.assertIn("1 check reported: 1 passed.", one)
        self.checks.record_result(
            "volmarr", "pub", head_oid, "ci/lint", "failed")
        self.checks.record_result(
            "volmarr", "pub", head_oid, "deploy/preview", "pending")
        three = render_pull_request_checks(self._rows(pr.number))
        self.assertIn(
            "3 checks reported: 1 passed; 1 failed; 1 pending.",
            three)

    def test_words_say_context_state_and_head(self):
        pr, _p, _b, head_oid = self._open()
        row = self.checks.record_result(
            "volmarr", "pub", head_oid, "ci/tests", "passed",
            description="all green")
        self.assertEqual(
            row.words,
            f"ci/tests — Passed; all green; against head {head_oid}.")
        bare = self.checks.record_result(
            "volmarr", "pub", head_oid, "ci/lint", "pending")
        self.assertEqual(
            bare.words,
            f"ci/lint — Pending; against head {head_oid}.")


if __name__ == "__main__":
    unittest.main()
