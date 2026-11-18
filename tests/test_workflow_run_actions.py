"""S-324 acceptance battery: workflow run actions.

Acceptance (roadmap S-324): Re-run and cancel
-- re-run all/failed jobs, cancel running
workflows; every action audit-logged.

The centre is samverk/workflow_run_actions.py:
`WorkflowRunActionsStore` addresses one run by
(repository, workflow, commit) and its jobs are
the run's S-321 check runs. `rerun_all` resets
every job of a completed run to queued and its
S-157 panel row to pending, opening the next
attempt; `rerun_failed_jobs` resets only the
jobs whose conclusion is in FAILED_CONCLUSIONS
(failure / timed_out / action_required --
S-246's failed fold minus cancelled); a run
still running is refused `run_still_running`,
a run that never stood `run_not_found`, and a
failed-only re-run with no failed job
`rerun_no_failed_jobs`. `cancel_run` completes
every unfinished job as cancelled (the panel
folds it to failed) and leaves finished jobs
untouched; a completed run is refused
`run_not_running`. Every accepted act lands
one migration-132 `ci_run_actions` row and
exactly one S-007 audit entry under its own
taxonomy event (repo.workflow_run.rerun_all /
rerun_failed / cancel); a refused act stores
nothing and audits nothing. Acts are S-054
write acts: a reader is refused
`permission_denied`, and a stranger to a
private repository gets the uniform
`repository_not_found`. Migration 132 (schema
131 -> 132); taxonomy +3 to 138 (33 auth /
92 repo / 13 admin). The fixtures seed the
S-246 check-run rows and S-157 panel rows the
acts move -- S-321's battery proves the landing
road that writes them; this battery proves the
hands. The module and the core patches were
recovered by the keeper after the first lead
was interrupted mid-transfer (see
hidden_files/s324-keeper-recovery.txt).

Counted with: python3 -m unittest
tests.test_workflow_run_actions
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.api_checks import decide_check_run_panel_state
from samverk.audit import AuditLog
from samverk.check_reporting import check_name_for
from samverk.db import schema_version
from samverk.issues import IssueStore
from samverk.repositories import RepositoryStore
from samverk.workflow_run_actions import (
    ACTION_CANCEL, ACTION_KINDS, ACTION_RERUN_ALL,
    ACTION_RERUN_FAILED, EVENT_BY_ACTION,
    FAILED_CONCLUSIONS, WorkflowRunActionsError,
    WorkflowRunActionsStore, audit_workflow_run_actions,
    is_failed_conclusion, is_run_check_name,
    job_for_check_name, render_run_actions_page,
    run_action_to_dict, run_check_prefix, run_job_to_dict,
    run_standing_to_dict, standing_for_statuses,
    validate_run_address)

PW = "correct horse battery"
T0 = 1_700_000_000
OID = "a" * 40
OID2 = "b" * 40


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def _reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except WorkflowRunActionsError as exc:
        return exc.reason
    raise AssertionError("expected WorkflowRunActionsError")


class PureLawTests(unittest.TestCase):
    def test_action_vocabulary_and_events(self):
        self.assertEqual(
            ACTION_KINDS,
            ("rerun_all", "rerun_failed", "cancel"))
        self.assertEqual(ACTION_RERUN_ALL, "rerun_all")
        self.assertEqual(ACTION_RERUN_FAILED, "rerun_failed")
        self.assertEqual(ACTION_CANCEL, "cancel")
        self.assertEqual(EVENT_BY_ACTION, {
            "rerun_all": "repo.workflow_run.rerun_all",
            "rerun_failed": "repo.workflow_run.rerun_failed",
            "cancel": "repo.workflow_run.cancel"})
        for event in EVENT_BY_ACTION.values():
            self.assertIn(event, taxonomy.REPO_EVENTS)
            self.assertIn(event, taxonomy.AUDIT_EVENTS)

    def test_prefix_is_s321s_separator(self):
        self.assertEqual(run_check_prefix("CI"), "CI / ")
        self.assertEqual(run_check_prefix(" CI "), "CI / ")
        self.assertEqual(
            check_name_for("CI", "build"), "CI / build")

    def test_job_extraction(self):
        self.assertEqual(
            job_for_check_name("CI", "CI / build"), "build")
        self.assertEqual(
            job_for_check_name("CI", "CI / test-2"), "test-2")
        self.assertTrue(is_run_check_name("CI", "CI / build"))

    def test_job_extraction_refusals(self):
        for name in ("CI", "CI /", "CI / ", "CI/build",
                     "Docs / build", "CI2 / build", "",
                     "CI /  build", "CI / build ", None, 7):
            self.assertIsNone(job_for_check_name("CI", name))
            self.assertFalse(is_run_check_name("CI", name))

    def test_workflow_must_be_named(self):
        for bad in ("", "  ", None, 7):
            self.assertEqual(
                _reason(run_check_prefix, bad),
                "run_workflow_invalid")
            self.assertEqual(
                _reason(validate_run_address, bad, OID),
                "run_workflow_invalid")

    def test_oid_must_be_named(self):
        for bad in ("", "  ", None, 7):
            self.assertEqual(
                _reason(validate_run_address, "CI", bad),
                "run_oid_invalid")
        self.assertEqual(
            validate_run_address(" CI ", f" {OID} "),
            ("CI", OID))

    def test_failed_conclusion_set(self):
        self.assertEqual(
            FAILED_CONCLUSIONS,
            ("failure", "timed_out", "action_required"))
        for word in FAILED_CONCLUSIONS:
            self.assertTrue(is_failed_conclusion(word))
        for word in ("success", "neutral", "skipped",
                     "cancelled", "", None):
            self.assertFalse(is_failed_conclusion(word))

    def test_standing_for_statuses(self):
        self.assertEqual(standing_for_statuses(()), "not_found")
        self.assertEqual(standing_for_statuses([]), "not_found")
        self.assertEqual(
            standing_for_statuses(("completed", "completed")),
            "completed")
        self.assertEqual(
            standing_for_statuses(("completed", "queued")),
            "running")
        self.assertEqual(
            standing_for_statuses(("in_progress",)), "running")

    def test_pins_hold(self):
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 92)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)


class World(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.reader = self.accounts.register("yrsa", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.store = WorkflowRunActionsStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.pub = self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.priv = self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")

    # -- seeding: the rows S-246 / S-157 stand --------

    def _check(self, repo, name, status="completed",
               conclusion="success", oid=OID, description=""):
        cur = self.conn.execute(
            "INSERT INTO check_runs (repo_id, head_oid, name,"
            " status, conclusion, poster, target_url,"
            " description, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, 'samverk-ci', '', ?, ?, ?)",
            (repo.id, oid, name, status, conclusion,
             description, T0, T0))
        self.conn.execute(
            "INSERT INTO commit_checks (repo_id, head_oid,"
            " context, state, target_url, description,"
            " created_at, updated_at)"
            " VALUES (?, ?, ?, ?, '', ?, ?, ?)",
            (repo.id, oid, name,
             decide_check_run_panel_state(status, conclusion),
             description, T0, T0))
        self.conn.commit()
        return int(cur.lastrowid)

    def _completed_run(self, repo=None, oid=OID, jobs=(
            ("build", "success"), ("test", "failure"),
            ("lint", "success"))):
        repo = repo or self.pub
        for job, conclusion in jobs:
            self._check(repo, f"CI / {job}", "completed",
                        conclusion, oid)

    def _running_run(self, repo=None, oid=OID):
        repo = repo or self.pub
        self._check(repo, "CI / build", "completed", "success", oid)
        self._check(repo, "CI / test", "in_progress", "", oid)
        self._check(repo, "CI / lint", "queued", "", oid)

    def _complete_all(self, conclusion="success"):
        with self.conn:
            self.conn.execute(
                "UPDATE check_runs SET status = 'completed',"
                " conclusion = ?", (conclusion,))
            self.conn.execute(
                "UPDATE commit_checks SET state = ?",
                (decide_check_run_panel_state(
                    "completed", conclusion),))

    # -- reading the record back -----------------------

    def _run(self, viewer=None, repo="pub", workflow="CI", oid=OID):
        return self.store.get_run(
            self.owner if viewer is None else viewer,
            "volmarr", repo, workflow, oid)

    def _check_state(self, name, oid=OID):
        row = self.conn.execute(
            "SELECT status, conclusion, description"
            " FROM check_runs WHERE head_oid = ? AND name = ?",
            (oid, name)).fetchone()
        return (row["status"], row["conclusion"],
                row["description"])

    def _panel(self, name, oid=OID):
        return self.conn.execute(
            "SELECT state FROM commit_checks"
            " WHERE head_oid = ? AND context = ?",
            (oid, name)).fetchone()["state"]

    def _action_rows(self):
        return self.conn.execute(
            "SELECT * FROM ci_run_actions ORDER BY id").fetchall()

    def _audit_entries(self, action=None):
        if action is None:
            return self.conn.execute(
                "SELECT * FROM audit_log ORDER BY seq").fetchall()
        return self.conn.execute(
            "SELECT * FROM audit_log WHERE action = ?"
            " ORDER BY seq", (action,)).fetchall()

    def _snapshot(self):
        checks = tuple(
            (r["name"], r["status"], r["conclusion"])
            for r in self.conn.execute(
                "SELECT * FROM check_runs ORDER BY id"))
        panels = tuple(
            (r["context"], r["state"])
            for r in self.conn.execute(
                "SELECT * FROM commit_checks ORDER BY id"))
        return (len(self._action_rows()),
                len(self._audit_entries()), checks, panels)

    def _actor(self, actor):
        return self.owner if actor == "owner" else actor

    def _rerun_all(self, actor="owner", repo="pub", oid=OID):
        return self.store.rerun_all(
            self._actor(actor), "volmarr", repo, "CI", oid)

    def _rerun_failed(self, actor="owner", repo="pub", oid=OID):
        return self.store.rerun_failed_jobs(
            self._actor(actor), "volmarr", repo, "CI", oid)

    def _cancel(self, actor="owner", repo="pub", oid=OID):
        return self.store.cancel_run(
            self._actor(actor), "volmarr", repo, "CI", oid)

    # -- the standing ----------------------------------

    def test_get_run_reads_completed_standing(self):
        self._completed_run()
        standing = self._run()
        self.assertTrue(standing.exists)
        self.assertEqual(standing.full_name, "volmarr/pub")
        self.assertEqual(standing.standing, "completed")
        self.assertEqual(standing.attempt, 1)
        self.assertEqual(
            [j.job_id for j in standing.jobs],
            ["build", "test", "lint"])
        self.assertEqual(
            [j.name for j in standing.jobs],
            ["CI / build", "CI / test", "CI / lint"])
        self.assertEqual(
            [j.panel_state for j in standing.jobs],
            ["passed", "failed", "passed"])
        self.assertEqual(
            [j.job_id for j in standing.failed_jobs], ["test"])
        self.assertEqual(standing.running_jobs, ())
        self.assertIn("completed (attempt 1)", standing.words)
        self.assertIn("1 failed", standing.words)

    def test_get_run_running_and_missing(self):
        self._running_run()
        standing = self._run()
        self.assertEqual(standing.standing, "running")
        self.assertEqual(
            [j.job_id for j in standing.running_jobs],
            ["test", "lint"])
        self.assertIn("is running (attempt 1)", standing.words)
        self.assertIn("2 of 3 jobs still unfinished",
                      standing.words)
        missing = self._run(oid=OID2)
        self.assertFalse(missing.exists)
        self.assertEqual(missing.jobs, ())
        self.assertEqual(missing.standing, "not_found")
        self.assertIn("has not run", missing.words)

    def test_get_run_excludes_other_workflows_and_commits(self):
        self._completed_run()
        self._check(self.pub, "Docs / build", "completed",
                    "success", OID)
        self._check(self.pub, "CI / build", "completed",
                    "failure", OID2)
        standing = self._run()
        self.assertEqual(
            [j.job_id for j in standing.jobs],
            ["build", "test", "lint"])
        docs = self._run(workflow="Docs")
        self.assertEqual([j.job_id for j in docs.jobs], ["build"])
        other = self._run(oid=OID2)
        self.assertEqual(len(other.jobs), 1)
        self.assertEqual(other.jobs[0].conclusion, "failure")

    def test_reads_write_nothing_and_audit_nothing(self):
        self._completed_run()
        before = self._snapshot()
        self._run()
        self.store.list_run_actions(
            self.owner, "volmarr", "pub", "CI", OID)
        self.assertEqual(self._snapshot(), before)

    # -- re-run -----------------------------------------

    def test_rerun_all_resets_every_job_opens_attempt_2(self):
        self._completed_run()
        record = self._rerun_all()
        self.assertEqual(record.kind, "rerun_all")
        self.assertEqual(record.attempt, 2)
        self.assertEqual(
            record.jobs,
            ("CI / build", "CI / test", "CI / lint"))
        self.assertEqual(record.full_name, "volmarr/pub")
        self.assertEqual(record.workflow, "CI")
        self.assertEqual(record.oid, OID)
        self.assertEqual(record.actor, "volmarr")
        self.assertEqual(record.actor_id, self.owner.id)
        self.assertEqual(record.created_at, T0)
        for name in record.jobs:
            status, conclusion, description = self._check_state(name)
            self.assertEqual(status, "queued")
            self.assertEqual(conclusion, "")
            self.assertIn("Re-run requested by volmarr",
                          description)
            self.assertIn("(attempt 2)", description)
            self.assertEqual(self._panel(name), "pending")
        standing = self._run()
        self.assertEqual(standing.attempt, 2)
        self.assertEqual(standing.standing, "running")
        rows = self._action_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "rerun_all")
        self.assertEqual(rows[0]["attempt"], 2)
        self.assertEqual(
            json.loads(rows[0]["jobs"]), list(record.jobs))

    def test_rerun_all_is_witnessed_exactly_once(self):
        self._completed_run()
        before = len(self._audit_entries())
        self._rerun_all()
        entries = self._audit_entries(
            "repo.workflow_run.rerun_all")
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(self._audit_entries()), before + 1)
        entry = entries[0]
        self.assertEqual(entry["actor_kind"], "user")
        self.assertEqual(entry["actor_id"], self.owner.id)
        self.assertEqual(entry["target_kind"], "repo")
        self.assertEqual(entry["target_id"], "volmarr/pub")
        self.assertEqual(entry["outcome"], "success")
        self.assertEqual(json.loads(entry["detail"]), {
            "workflow": "CI", "oid": OID, "attempt": 2,
            "jobs": ["CI / build", "CI / test", "CI / lint"]})

    def test_second_rerun_opens_attempt_3(self):
        self._completed_run()
        self._rerun_all()
        self._complete_all()
        record = self._rerun_all()
        self.assertEqual(record.attempt, 3)
        self.assertEqual(self._run().attempt, 3)
        history = self.store.list_run_actions(
            self.owner, "volmarr", "pub", "CI", OID)
        self.assertEqual(
            [(a.kind, a.attempt) for a in history],
            [("rerun_all", 2), ("rerun_all", 3)])

    def test_rerun_failed_jobs_touches_only_failed(self):
        self._completed_run(jobs=(
            ("build", "failure"), ("test", "success"),
            ("lint", "timed_out"), ("docs", "cancelled"),
            ("e2e", "action_required"), ("smoke", "skipped")))
        record = self._rerun_failed()
        self.assertEqual(record.kind, "rerun_failed")
        self.assertEqual(record.attempt, 2)
        self.assertEqual(
            record.jobs,
            ("CI / build", "CI / lint", "CI / e2e"))
        for name in record.jobs:
            status, conclusion, _ = self._check_state(name)
            self.assertEqual((status, conclusion), ("queued", ""))
            self.assertEqual(self._panel(name), "pending")
        for name, conclusion in (
                ("CI / test", "success"),
                ("CI / docs", "cancelled"),
                ("CI / smoke", "skipped")):
            status, standing_conclusion, _ = self._check_state(name)
            self.assertEqual(status, "completed")
            self.assertEqual(standing_conclusion, conclusion)
        self.assertEqual(self._panel("CI / test"), "passed")
        self.assertEqual(self._panel("CI / docs"), "failed")
        entries = self._audit_entries(
            "repo.workflow_run.rerun_failed")
        self.assertEqual(len(entries), 1)
        self.assertEqual(
            json.loads(entries[0]["detail"])["jobs"],
            ["CI / build", "CI / lint", "CI / e2e"])

    def test_rerun_failed_with_no_failed_jobs_refused(self):
        self._completed_run(jobs=(
            ("build", "success"), ("test", "skipped"),
            ("lint", "cancelled")))
        before = self._snapshot()
        self.assertEqual(
            _reason(self._rerun_failed), "rerun_no_failed_jobs")
        self.assertEqual(self._snapshot(), before)

    def test_rerun_running_run_refused(self):
        self._running_run()
        before = self._snapshot()
        self.assertEqual(
            _reason(self._rerun_all), "run_still_running")
        self.assertEqual(
            _reason(self._rerun_failed), "run_still_running")
        self.assertEqual(self._snapshot(), before)

    def test_rerun_missing_run_refused(self):
        before = self._snapshot()
        self.assertEqual(_reason(self._rerun_all), "run_not_found")
        self.assertEqual(
            _reason(self._rerun_failed), "run_not_found")
        self.assertEqual(self._snapshot(), before)

    # -- cancel ------------------------------------------

    def test_cancel_completes_unfinished_leaves_finished(self):
        self._running_run()
        record = self._cancel()
        self.assertEqual(record.kind, "cancel")
        self.assertEqual(record.attempt, 1)
        self.assertEqual(record.jobs, ("CI / test", "CI / lint"))
        for name in record.jobs:
            status, conclusion, description = self._check_state(name)
            self.assertEqual(status, "completed")
            self.assertEqual(conclusion, "cancelled")
            self.assertEqual(description, "Cancelled by volmarr.")
            self.assertEqual(self._panel(name), "failed")
        status, conclusion, _ = self._check_state("CI / build")
        self.assertEqual((status, conclusion), ("completed", "success"))
        self.assertEqual(self._panel("CI / build"), "passed")
        standing = self._run()
        self.assertEqual(standing.standing, "completed")
        self.assertEqual(standing.attempt, 1)
        entries = self._audit_entries("repo.workflow_run.cancel")
        self.assertEqual(len(entries), 1)
        self.assertEqual(json.loads(entries[0]["detail"]), {
            "workflow": "CI", "oid": OID, "attempt": 1,
            "jobs": ["CI / test", "CI / lint"]})

    def test_cancel_completed_run_refused(self):
        self._completed_run()
        before = self._snapshot()
        self.assertEqual(_reason(self._cancel), "run_not_running")
        self.assertEqual(self._snapshot(), before)

    def test_cancel_missing_run_refused(self):
        before = self._snapshot()
        self.assertEqual(_reason(self._cancel), "run_not_found")
        self.assertEqual(self._snapshot(), before)

    def test_cancel_then_rerun_all_covers_cancelled_jobs(self):
        self._running_run()
        self._cancel()
        record = self._rerun_all()
        self.assertEqual(record.attempt, 2)
        self.assertEqual(
            record.jobs,
            ("CI / build", "CI / test", "CI / lint"))
        history = self.store.list_run_actions(
            self.owner, "volmarr", "pub", "CI", OID)
        self.assertEqual(
            [(a.kind, a.attempt) for a in history],
            [("cancel", 1), ("rerun_all", 2)])

    # -- permission ---------------------------------------

    def test_reader_is_refused_permission_denied(self):
        self._completed_run()
        before = self._snapshot()
        for act in (self._rerun_all, self._rerun_failed,
                    self._cancel):
            self.assertEqual(
                _reason(act, self.reader), "permission_denied")
        self.assertEqual(
            _reason(self._rerun_all, None), "permission_denied")
        self.assertEqual(self._snapshot(), before)
        standing = self.store.get_run(
            self.reader, "volmarr", "pub", "CI", OID)
        self.assertEqual(standing.standing, "completed")

    def test_stranger_to_private_repo_gets_uniform_not_found(self):
        self._completed_run(repo=self.priv)
        before = self._snapshot()
        for viewer in (self.stranger, None):
            self.assertEqual(
                _reason(self.store.get_run, viewer,
                        "volmarr", "priv", "CI", OID),
                "repository_not_found")
            self.assertEqual(
                _reason(self.store.list_run_actions, viewer,
                        "volmarr", "priv", "CI", OID),
                "repository_not_found")
            self.assertEqual(
                _reason(self.store.rerun_all, viewer,
                        "volmarr", "priv", "CI", OID),
                "repository_not_found")
            self.assertEqual(
                _reason(self.store.cancel_run, viewer,
                        "volmarr", "priv", "CI", OID),
                "repository_not_found")
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(
            _reason(self._rerun_all, self.owner, "ghost"),
            "repository_not_found")
        self.assertEqual(
            _reason(self._run, self.owner, "ghost"),
            "repository_not_found")

    def test_address_validates_before_repository(self):
        self.assertEqual(
            _reason(self.store.get_run, self.owner,
                    "volmarr", "ghost", " ", OID),
            "run_workflow_invalid")
        self.assertEqual(
            _reason(self.store.rerun_all, self.owner,
                    "volmarr", "ghost", "CI", ""),
            "run_oid_invalid")
        self.assertEqual(
            _reason(self.store.cancel_run, self.owner,
                    "volmarr", "ghost", None, OID),
            "run_workflow_invalid")

    # -- shapes, render, audit, pins -----------------------

    def test_dict_shapes(self):
        self._completed_run()
        standing = self._run()
        data = run_standing_to_dict(standing)
        self.assertEqual(data["repository"], "volmarr/pub")
        self.assertEqual(data["workflow"], "CI")
        self.assertEqual(data["oid"], OID)
        self.assertEqual(data["standing"], "completed")
        self.assertEqual(data["attempt"], 1)
        self.assertEqual(len(data["jobs"]), 3)
        job = run_job_to_dict(standing.jobs[1])
        self.assertEqual(job["name"], "CI / test")
        self.assertEqual(job["job_id"], "test")
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["conclusion"], "failure")
        self.assertEqual(job["panel_state"], "failed")
        self.assertEqual(job["poster"], "samverk-ci")
        self.assertEqual(job["updated_at"], T0)
        record = self._rerun_failed()
        action = run_action_to_dict(record)
        self.assertEqual(action["id"], record.id)
        self.assertEqual(action["repository"], "volmarr/pub")
        self.assertEqual(action["kind"], "rerun_failed")
        self.assertEqual(action["attempt"], 2)
        self.assertEqual(action["jobs"], ["CI / test"])
        self.assertEqual(action["actor"], "volmarr")
        self.assertEqual(action["actor_id"], self.owner.id)
        self.assertEqual(action["created_at"], T0)
        self.assertIn("rerun_failed on workflow CI", record.words)

    def test_render_escapes_and_speaks(self):
        self._check(self.pub, "<b>CI</b> / build", "completed",
                    "success", OID)
        standing = self.store.get_run(
            self.owner, "volmarr", "pub", "<b>CI</b>", OID)
        page = render_run_actions_page(standing=standing)
        self.assertIn("<h1>Workflow run actions</h1>", page)
        self.assertIn("&lt;b&gt;CI&lt;/b&gt;", page)
        self.assertNotIn("<b>CI</b>", page)
        bare = render_run_actions_page()
        self.assertIn("A completed run can be re-run", bare)
        self.assertIn("written to the audit log", bare)

    def test_audit_stands_cleanly(self):
        self._completed_run()
        audit = audit_workflow_run_actions(self.conn)
        self.assertTrue(audit.vocabulary_ok)
        self.assertTrue(audit.schema_ok)
        self.assertEqual(audit.schema_version, 134)
        self.assertTrue(audit.events_ok)
        self.assertTrue(audit.tables_ok)
        self.assertEqual(audit.rows_scanned, 0)
        self.assertEqual(audit.problems, ())
        self.assertTrue(audit.stands_cleanly)
        self._rerun_all()
        audit = audit_workflow_run_actions(self.conn)
        self.assertEqual(audit.rows_scanned, 1)
        self.assertTrue(audit.stands_cleanly)
        page = render_run_actions_page(audit=audit)
        self.assertIn("stands cleanly", page)
        self.assertIn("1 actions scanned", page)

    def test_audit_names_broken_ties(self):
        self._completed_run()
        with self.conn:
            self.conn.execute(
                "INSERT INTO ci_run_actions (repo_id, workflow,"
                " head_oid, kind, attempt, jobs, actor_id, actor,"
                " created_at) VALUES (999999, 'CI', ?,"
                " 'rerun_all', 1, '[\"Docs / build\"]', ?,"
                " 'volmarr', ?)", (OID, self.owner.id, T0))
        audit = audit_workflow_run_actions(self.conn)
        self.assertFalse(audit.stands_cleanly)
        self.assertEqual(audit.rows_scanned, 1)
        joined = " ".join(audit.problems)
        self.assertIn("not one of its workflow's checks", joined)
        self.assertIn("its repository does not stand", joined)

    def test_pins_schema_132_taxonomy_138(self):
        self.assertEqual(schema_version(self.conn), 134)
        self.assertEqual(db.MIGRATIONS[-1][0], 134)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 92)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("ci_run_actions", tables)
        self.assertIn("check_runs", tables)
        self.assertIn("commit_checks", tables)


if __name__ == "__main__":
    unittest.main()
