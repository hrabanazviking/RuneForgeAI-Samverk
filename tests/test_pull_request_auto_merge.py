"""S-158 acceptance battery: pull request auto-merge.

Acceptance (roadmap S-158): Auto-merge — merge when
requirements pass: the queue of one, with cancellation
and full audit.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.issues import IssueStore
from samverk.pull_request_auto_merge import (
    PullRequestAutoMergeStore, render_auto_merge)
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


CHECKS_DDL = (
    "CREATE TABLE IF NOT EXISTS commit_checks ("
    "  id INTEGER PRIMARY KEY,"
    "  repo_id INTEGER NOT NULL,"
    "  head_oid TEXT NOT NULL,"
    "  context TEXT NOT NULL,"
    "  state TEXT NOT NULL DEFAULT 'pending',"
    "  target_url TEXT NOT NULL DEFAULT '',"
    "  description TEXT NOT NULL DEFAULT '',"
    "  created_at INTEGER NOT NULL,"
    "  updated_at INTEGER NOT NULL,"
    "  UNIQUE (repo_id, head_oid, context)"
    ")")


class PullRequestAutoMergeTests(unittest.TestCase):
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
        self.reader = self.accounts.register(
            "yrsa", "correct horse battery")
        self.third = self.accounts.register(
            "tess", "correct horse battery")
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.auto = PullRequestAutoMergeStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")

    # -- helpers ---------------------------------------------------

    def _open(self, *, draft=False, name="pub"):
        if name != "pub":
            self.repos.create_repository(
                self.owner.id, "volmarr", name, visibility="public")
        path = self.repos.path_for("volmarr", name)
        base_oid = make_commit(path, None, {"a.txt": "alpha\n"}, "base")
        git(path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(
            path, base_oid, {"a.txt": "alpha\nbeta\n"}, "feature work")
        git(path, "update-ref", "refs/heads/feature", head_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", name,
            base_branch="main", head_branch="feature", draft=draft)
        return pr, path, base_oid, head_oid

    def _audit_actions(self):
        rows = self.conn.execute(
            "SELECT action FROM audit_log ORDER BY seq").fetchall()
        return [r["action"] for r in rows]

    def _make_checks_table(self):
        with self.conn:
            self.conn.execute(CHECKS_DDL)

    def _report_check(self, repo_id, head_oid, context, state):
        with self.conn:
            self.conn.execute(
                "INSERT INTO commit_checks"
                " (repo_id, head_oid, context, state, created_at,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (repo_id, head_oid, context)"
                " DO UPDATE SET state = excluded.state",
                (repo_id, head_oid, context, state,
                 self.clock.now, self.clock.now))

    # -- arming ------------------------------------------------------

    def test_arm_by_author_records_terms_and_audits(self):
        pr, _path, _base, head_oid = self._open()
        record = self.auto.arm_auto_merge(
            self.owner, "volmarr", "pub", pr.number,
            strategy="squash", required_checks=("ci/tests",))
        self.assertTrue(record.is_armed)
        self.assertEqual(record.strategy, "squash")
        self.assertEqual(record.required_checks, ("ci/tests",))
        self.assertEqual(record.armed_by, self.owner.id)
        self.assertEqual(record.head_oid, head_oid)
        events = self.auto.events_for(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual([e.kind for e in events], ["armed"])
        self.assertIn("repo.pull_request.auto_merge_arm",
                      self._audit_actions())

    def test_arm_defaults_to_merge_strategy(self):
        pr, _p, _b, _h = self._open()
        record = self.auto.arm_auto_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(record.strategy, "merge")
        self.assertEqual(record.required_checks, ())

    def test_arm_refused_for_mere_reader(self):
        pr, _p, _b, _h = self._open()
        with self.assertRaises(PullRequestError) as ctx:
            self.auto.arm_auto_merge(
                self.reader, "volmarr", "pub", pr.number)
        self.assertEqual(ctx.exception.reason, "permission_denied")
        self.assertIsNone(self.auto.get_auto_merge(
            self.owner, "volmarr", "pub", pr.number))

    def test_arm_refused_on_closed_pull_request(self):
        pr, _p, _b, _h = self._open()
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE id = ?",
                (pr.row_id,))
        with self.assertRaises(PullRequestError) as ctx:
            self.auto.arm_auto_merge(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(ctx.exception.reason, "pull_request_closed")

    def test_arm_refused_for_unknown_strategy(self):
        pr, _p, _b, _h = self._open()
        with self.assertRaises(PullRequestError) as ctx:
            self.auto.arm_auto_merge(
                self.owner, "volmarr", "pub", pr.number,
                strategy="fast-forward")
        self.assertEqual(ctx.exception.reason,
                         "auto_merge_strategy_invalid")
        self.assertIsNone(self.auto.get_auto_merge(
            self.owner, "volmarr", "pub", pr.number))

    def test_arm_refused_for_blank_required_check(self):
        pr, _p, _b, _h = self._open()
        with self.assertRaises(PullRequestError) as ctx:
            self.auto.arm_auto_merge(
                self.owner, "volmarr", "pub", pr.number,
                required_checks=("ci/tests", "  "))
        self.assertEqual(ctx.exception.reason,
                         "auto_merge_checks_invalid")
        self.assertIsNone(self.auto.get_auto_merge(
            self.owner, "volmarr", "pub", pr.number))

    def test_double_arm_is_a_quiet_noop(self):
        pr, _p, _b, _h = self._open()
        first = self.auto.arm_auto_merge(
            self.owner, "volmarr", "pub", pr.number,
            required_checks=("ci/tests",))
        second = self.auto.arm_auto_merge(
            self.owner, "volmarr", "pub", pr.number,
            strategy="rebase")
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.strategy, "merge")
        self.assertEqual(second.required_checks, ("ci/tests",))
        events = self.auto.events_for(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual([e.kind for e in events], ["armed"])

    # -- cancellation --------------------------------------------------

    def test_cancel_records_act_and_audits(self):
        pr, _p, _b, _h = self._open()
        self.auto.arm_auto_merge(self.owner, "volmarr", "pub", pr.number)
        cancelled = self.auto.cancel_auto_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(cancelled.state, "cancelled")
        self.assertEqual(cancelled.cancelled_by, self.owner.id)
        self.assertIsNotNone(cancelled.cancelled_at)
        events = self.auto.events_for(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual([e.kind for e in events],
                         ["armed", "cancelled"])
        self.assertIn("repo.pull_request.auto_merge_cancel",
                      self._audit_actions())

    def test_cancel_when_not_armed_is_refused(self):
        pr, _p, _b, _h = self._open()
        with self.assertRaises(PullRequestError) as ctx:
            self.auto.cancel_auto_merge(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(ctx.exception.reason, "auto_merge_not_armed")

    def test_rearm_after_cancel_starts_a_fresh_cycle(self):
        pr, _p, _b, _h = self._open()
        self.auto.arm_auto_merge(self.owner, "volmarr", "pub", pr.number)
        self.auto.cancel_auto_merge(
            self.owner, "volmarr", "pub", pr.number)
        rearmed = self.auto.arm_auto_merge(
            self.owner, "volmarr", "pub", pr.number, strategy="rebase")
        self.assertTrue(rearmed.is_armed)
        self.assertEqual(rearmed.strategy, "rebase")
        self.assertIsNone(rearmed.cancelled_at)
        events = self.auto.events_for(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual([e.kind for e in events],
                         ["armed", "cancelled", "armed"])

    # -- evaluation ------------------------------------------------------

    def test_evaluate_ready_pull_request_with_no_checks_named(self):
        pr, _p, _b, _h = self._open()
        self.auto.arm_auto_merge(self.owner, "volmarr", "pub", pr.number)
        evaluation = self.auto.evaluate(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(evaluation.requirements_met)
        self.assertEqual(evaluation.blockers, ())

    def test_evaluate_draft_is_blocked_in_words(self):
        pr, _p, _b, _h = self._open(draft=True)
        self.auto.arm_auto_merge(self.owner, "volmarr", "pub", pr.number)
        evaluation = self.auto.evaluate(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(evaluation.requirements_met)
        self.assertTrue(any("draft" in b for b in evaluation.blockers))

    def test_evaluate_moved_head_is_blocked(self):
        pr, path, _b, head_oid = self._open()
        self.auto.arm_auto_merge(self.owner, "volmarr", "pub", pr.number)
        newer = make_commit(
            path, head_oid, {"a.txt": "alpha\nbeta\ngamma\n"}, "more")
        git(path, "update-ref", "refs/heads/feature", newer)
        evaluation = self.auto.evaluate(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(evaluation.requirements_met)
        self.assertTrue(
            any("head branch has moved" in b
                for b in evaluation.blockers))

    def test_required_check_must_stand_passed(self):
        pr, _p, _b, head_oid = self._open()
        repo = self.repos.get_repository("volmarr", "pub")
        self.auto.arm_auto_merge(
            self.owner, "volmarr", "pub", pr.number,
            required_checks=("ci/tests",))
        # no checks table on this slice's base: honestly unmet
        evaluation = self.auto.evaluate(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(evaluation.requirements_met)
        self._make_checks_table()
        evaluation = self.auto.evaluate(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(evaluation.requirements_met)
        self.assertTrue(any("has not been reported" in b
                            for b in evaluation.blockers))
        self._report_check(repo.id, head_oid, "ci/tests", "pending")
        evaluation = self.auto.evaluate(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(evaluation.requirements_met)
        self._report_check(repo.id, head_oid, "ci/tests", "failed")
        evaluation = self.auto.evaluate(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(evaluation.requirements_met)
        self._report_check(repo.id, head_oid, "ci/tests", "passed")
        evaluation = self.auto.evaluate(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(evaluation.requirements_met)

    # -- firing ------------------------------------------------------------

    def test_try_fire_lands_through_the_wired_seam(self):
        pr, _p, _b, _h = self._open()
        self.auto.arm_auto_merge(self.owner, "volmarr", "pub", pr.number)
        calls = []

        def merger(actor, owner, repo, number):
            calls.append(number)
            return SimpleNamespace(merge_commit_oid="a" * 40)

        self.auto.set_merger(merger)
        outcome = self.auto.try_fire(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(outcome.fired)
        self.assertEqual(calls, [pr.number])
        self.assertEqual(outcome.merge_commit_oid, "a" * 40)
        record = self.auto.get_auto_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(record.state, "fired")
        self.assertEqual(record.merge_commit_oid, "a" * 40)
        self.assertIsNotNone(record.fired_at)
        events = self.auto.events_for(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual([e.kind for e in events],
                         ["armed", "evaluated", "fired"])
        self.assertIn("repo.pull_request.auto_merge_fire",
                      self._audit_actions())

    def test_try_fire_blocked_never_calls_the_seam(self):
        pr, _p, _b, _h = self._open(draft=True)
        self.auto.arm_auto_merge(self.owner, "volmarr", "pub", pr.number)
        calls = []
        self.auto.set_merger(
            lambda *a: calls.append(a)
            or SimpleNamespace(merge_commit_oid="b" * 40))
        outcome = self.auto.try_fire(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(outcome.fired)
        self.assertEqual(calls, [])
        record = self.auto.get_auto_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(record.state, "armed")
        self.assertTrue(record.last_blockers)

    def test_try_fire_refused_merge_marks_failed_once(self):
        pr, _p, _b, _h = self._open()
        self.auto.arm_auto_merge(self.owner, "volmarr", "pub", pr.number)

        def merger(actor, owner, repo, number):
            raise PullRequestError(
                "merge_conflict", "The branches conflict.")

        self.auto.set_merger(merger)
        outcome = self.auto.try_fire(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(outcome.fired)
        record = self.auto.get_auto_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(record.state, "failed")
        events = self.auto.events_for(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual([e.kind for e in events],
                         ["armed", "evaluated", "failed"])
        again = self.auto.try_fire(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(again.fired)

    def test_try_fire_without_a_seam_stays_armed_and_says_so(self):
        pr, _p, _b, _h = self._open()
        self.auto.arm_auto_merge(self.owner, "volmarr", "pub", pr.number)
        outcome = self.auto.try_fire(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(outcome.fired)
        self.assertIn("no merge seam is wired", outcome.words)
        record = self.auto.get_auto_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(record.state, "armed")

    # -- seams, render, counts --------------------------------------------

    def test_stranger_to_private_repo_gets_uniform_refusal(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        path = self.repos.path_for("volmarr", "priv")
        base_oid = make_commit(path, None, {"a.txt": "x\n"}, "base")
        git(path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(path, base_oid, {"a.txt": "y\n"}, "work")
        git(path, "update-ref", "refs/heads/feature", head_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "priv",
            base_branch="main", head_branch="feature")
        with self.assertRaises(PullRequestError) as ctx:
            self.auto.get_auto_merge(
                self.reader, "volmarr", "priv", pr.number)
        self.assertEqual(ctx.exception.reason,
                         "pull_request_not_found")

    def test_render_says_the_state_in_words(self):
        pr, _p, _b, _h = self._open()
        self.assertIn("not armed", render_auto_merge(None))
        record = self.auto.arm_auto_merge(
            self.owner, "volmarr", "pub", pr.number)
        html = render_auto_merge(
            record, self.auto.evaluate(
                self.owner, "volmarr", "pub", pr.number))
        self.assertIn("Auto-merge is armed", html)
        self.assertIn("Met:", html)
        cancelled = self.auto.cancel_auto_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertIn("was cancelled", render_auto_merge(cancelled))

    def test_schema_and_taxonomy_counts(self):
        self.assertEqual(db.schema_version(self.conn), 99)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        for name in ("repo.pull_request.auto_merge_arm",
                     "repo.pull_request.auto_merge_cancel",
                     "repo.pull_request.auto_merge_fire"):
            self.assertIn(name, taxonomy.AUDIT_EVENTS)


if __name__ == "__main__":
    unittest.main()
