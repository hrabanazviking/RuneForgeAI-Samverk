"""S-327 acceptance battery: workflow UI.

Acceptance (roadmap S-327): Workflow UI -- run
list, run detail (jobs, steps, timing, logs),
workflow file linting with errors in plain
words.

The centre is samverk/workflow_ui.py:
`WorkflowUIStore` gathers the run list and the
run detail from S-321's landed check runs
(named ``<workflow> / <job>`` on the run's
commit, S-323's address law), read through
S-054's `can_read` (a stranger to a private
repository gets the uniform
`repository_not_found`); the detail carries
each job's steps from the workflow file
itself, its timing from the rows' stamps, its
log tails through S-322's store under the
run's `run_id`, and its artifacts as S-323's
own listing. Standings are said in text+icon,
never colour-only (S-157's law); a job with no
landed conclusion stands as pending, never as
passed. Linting is pure: S-313's
`parse_workflow` surfaced, path judged against
S-313's directory law, every problem a reason
beside its plain-words sentence. The fixtures
seed the S-246 check-run rows, S-157 panel
rows, S-322 log rows and S-266 artifact rows
the pages read -- the neighbouring batteries
prove the roads that write them; this battery
proves the gathering and the lint. No
migration (schema stays 131); taxonomy unmoved
at 135 (33 auth / 89 repo / 13 admin); no audit
row is written by any face.

Counted with: python3 -m unittest
tests.test_workflow_ui
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.ci_logs import LogStreamingStore
from samverk.db import schema_version
from samverk.issues import IssueStore
from samverk.repositories import RepositoryStore
from samverk.workflow_ui import (
    PENDING, LintResult, RunDetail, RunSummary,
    WorkflowUIError, WorkflowUIStore,
    audit_workflow_ui, conclusion_icon,
    conclusion_word, conclusion_words,
    detail_to_dict, format_duration, lint_to_dict,
    lint_workflow, lint_workflows,
    render_lint_page, render_run_detail_page,
    render_run_list_page, run_conclusion_for,
    run_to_dict, split_check_name)

PW = "correct horse battery"
T0 = 1_700_000_000
DAY = 86400
OID = "a" * 40
OID2 = "b" * 40

GOOD = (
    "name: CI\n"
    "on: [push, pull_request]\n"
    "jobs:\n"
    "  build:\n"
    "    runner: linux\n"
    "    steps:\n"
    "      - name: Compile\n"
    "        run: make all\n"
    "      - run: make package\n"
    "  test:\n"
    "    runner: linux\n"
    "    needs: build\n"
    "    steps:\n"
    "      - name: Run tests\n"
    "        run: python3 -m unittest\n"
    "  lint:\n"
    "    runner: linux\n"
    "    steps:\n"
    "      - run: echo lint\n")


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def _reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except WorkflowUIError as exc:
        return exc.reason
    raise AssertionError("expected WorkflowUIError")


class PureLawTests(unittest.TestCase):
    def test_pins(self):
        conn = db.init_db(
            Path(tempfile.mkdtemp()) / "samverk.db")
        self.addCleanup(conn.close)
        self.assertEqual(schema_version(conn), 137)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 92)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    def test_conclusion_words_are_text_plus_icon(self):
        expected = {
            "success": ("Succeeded", "\u2713"),
            "failure": ("Failed", "\u2717"),
            "neutral": ("Neutral", "\u25cb"),
            "cancelled": ("Cancelled", "\u2298"),
            "skipped": ("Skipped", "\u00bb"),
            "timed_out": ("Timed out", "\u25f7"),
            "action_required": ("Action required", "\u26a0"),
            PENDING: ("Pending", "\u25d0"),
        }
        for conclusion, (word, icon) in expected.items():
            self.assertEqual(conclusion_word(conclusion), word)
            self.assertEqual(conclusion_icon(conclusion), icon)
            self.assertEqual(
                conclusion_words(conclusion), f"{icon} {word}")

    def test_conclusion_unknown_refused(self):
        for bad in ("passed", "green", "", None, 7):
            self.assertEqual(
                _reason(conclusion_word, bad),
                "run_conclusion_invalid")
            self.assertEqual(
                _reason(conclusion_words, bad),
                "run_conclusion_invalid")

    def test_format_duration(self):
        cases = {
            0: "0 seconds", 1: "1 second", 5: "5 seconds",
            60: "1 minute", 65: "1 minute 5 seconds",
            3600: "1 hour", 3661: "1 hour 1 minute 1 second",
            86400: "1 day", 90061: "1 day 1 hour 1 minute 1 second",
        }
        for seconds, words in cases.items():
            self.assertEqual(format_duration(seconds), words)
        for bad in (-1, 1.5, "65", True, None):
            self.assertEqual(
                _reason(format_duration, bad),
                "run_duration_invalid")

    def test_split_check_name(self):
        self.assertEqual(
            split_check_name("CI / build"), ("CI", "build"))
        self.assertEqual(
            split_check_name("Nightly CI / test-2"),
            ("Nightly CI", "test-2"))
        self.assertEqual(
            split_check_name("CI / build (linux, 3.12)"),
            ("CI", "build (linux, 3.12)"))
        self.assertEqual(
            split_check_name("Nightly / CI / build"),
            ("Nightly / CI", "build"))

    def test_split_check_name_refusals(self):
        for name in ("external-scan", "CI", "CI /", "CI / ",
                     "CI/build", " / build", "CI / not a job",
                     "", None, 7):
            self.assertIsNone(split_check_name(name))

    def test_run_conclusion_precedence(self):
        self.assertEqual(run_conclusion_for([]), PENDING)
        self.assertEqual(run_conclusion_for(["success"]), "success")
        self.assertEqual(
            run_conclusion_for(["success", "failure"]), "failure")
        self.assertEqual(
            run_conclusion_for(["cancelled", "timed_out"]),
            "timed_out")
        self.assertEqual(
            run_conclusion_for(["cancelled", "action_required"]),
            "action_required")
        self.assertEqual(
            run_conclusion_for(["success", "neutral"]), "neutral")
        self.assertEqual(
            run_conclusion_for(["skipped", "skipped"]), "skipped")
        self.assertEqual(
            run_conclusion_for(["skipped", "success"]), "success")

    def test_run_conclusion_unknown_refused(self):
        self.assertEqual(
            _reason(run_conclusion_for, ["passed"]),
            "run_conclusion_invalid")


class LintTests(unittest.TestCase):
    def test_lint_clean_file(self):
        result = lint_workflow(
            GOOD, ".samverk/workflows/ci.yml")
        self.assertTrue(result.ok)
        self.assertEqual(result.errors, ())
        self.assertEqual(result.job_ids, ("build", "test", "lint"))
        self.assertEqual(result.step_count, 4)
        self.assertIn("clean", result.words)
        self.assertIn("3 jobs, 4 steps", result.words)

    def test_lint_uses_refused_in_plain_words(self):
        text = ("on: push\njobs:\n  a:\n    runner: linux\n"
                "    steps:\n      - uses: actions/checkout@v4\n")
        result = lint_workflow(text, ".samverk/workflows/a.yml")
        self.assertFalse(result.ok)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(
            result.errors[0].reason, "workflow_uses_refused")
        self.assertIn("marketplace", result.errors[0].message)

    def test_lint_expression_refused(self):
        text = ("on: push\njobs:\n  a:\n    runner: linux\n"
                "    steps:\n      - run: echo ${{ github.sha }}\n")
        result = lint_workflow(text)
        self.assertFalse(result.ok)
        self.assertEqual(
            result.errors[0].reason,
            "workflow_expression_refused")

    def test_lint_shape_invalid(self):
        result = lint_workflow("name: CI\non: push\n")
        self.assertFalse(result.ok)
        self.assertEqual(
            result.errors[0].reason, "workflow_invalid")
        self.assertIn("jobs", result.errors[0].message)

    def test_lint_github_path_says_the_difference(self):
        result = lint_workflow(GOOD, ".github/workflows/ci.yml")
        self.assertFalse(result.ok)
        self.assertEqual(
            result.errors[0].reason, "workflow_path_github")
        self.assertIn(".samverk/workflows/",
                      result.errors[0].message)

    def test_lint_wrong_path(self):
        result = lint_workflow(GOOD, "ci/ci.yml")
        self.assertFalse(result.ok)
        self.assertEqual(
            result.errors[0].reason, "workflow_path_invalid")

    def test_lint_path_and_text_problems_ride_together(self):
        result = lint_workflow(
            "name: CI\n", ".github/workflows/ci.yml")
        self.assertFalse(result.ok)
        self.assertEqual(
            [error.reason for error in result.errors],
            ["workflow_path_github", "workflow_invalid"])

    def test_lint_many_in_path_order(self):
        results = lint_workflows({
            ".samverk/workflows/b.yml": "name: CI\n",
            ".samverk/workflows/a.yml": GOOD,
        })
        self.assertEqual(
            [result.path for result in results],
            [".samverk/workflows/a.yml",
             ".samverk/workflows/b.yml"])
        self.assertTrue(results[0].ok)
        self.assertFalse(results[1].ok)
        self.assertEqual(
            _reason(lint_workflows, ["x"]),
            "workflow_files_invalid")

    def test_lint_dict_and_page(self):
        result = lint_workflow(GOOD, ".samverk/workflows/ci.yml")
        data = lint_to_dict(result)
        self.assertTrue(data["ok"])
        self.assertEqual(data["jobs"], ["build", "test", "lint"])
        page = render_lint_page([result])
        self.assertIn("Workflow file lint", page)
        self.assertIn("clean", page)
        bad = lint_workflow("name: CI\n", ".samverk/workflows/x.yml")
        page = render_lint_page([bad])
        self.assertIn("workflow_invalid", page)


class World(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit_log = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit_log, time_fn=self.clock)
        self.store = WorkflowUIStore(
            self.conn, self.repos, time_fn=self.clock)
        self.logs = LogStreamingStore(
            self.conn, self.repos, time_fn=self.clock)
        self.pub = self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.priv = self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")

    # -- seeding: the rows S-246 / S-157 / S-266 stand ----

    def _check_run(self, repo, name, oid=OID, conclusion="success",
                   created_at=T0, updated_at=None,
                   description="", panel=None):
        updated_at = created_at if updated_at is None else updated_at
        cur = self.conn.execute(
            "INSERT INTO check_runs (repo_id, head_oid, name,"
            " status, conclusion, poster, target_url,"
            " description, created_at, updated_at)"
            " VALUES (?, ?, ?, 'completed', ?, 'samverk-ci', '',"
            " ?, ?, ?)",
            (repo.id, oid, name, conclusion, description,
             created_at, updated_at))
        if panel is not None:
            self.conn.execute(
                "INSERT INTO commit_checks (repo_id, head_oid,"
                " context, state, target_url, description,"
                " created_at, updated_at)"
                " VALUES (?, ?, ?, ?, '', ?, ?, ?)",
                (repo.id, oid, name, panel, description,
                 created_at, updated_at))
        self.conn.commit()
        return int(cur.lastrowid)

    def _artifact(self, repo, check_run_id, name, oid=OID,
                  check_run="CI / build", size=100):
        digest = hashlib.sha256(name.encode()).hexdigest()
        cur = self.conn.execute(
            "INSERT INTO ci_artifacts (repo_id, check_run_id,"
            " head_oid, check_run, name, size, sha256,"
            " content_type, download_count, retention_days,"
            " expires_at, uploader_id, poster, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'application/zip',"
            " 0, 90, ?, ?, 'volmarr', ?)",
            (repo.id, check_run_id, oid, check_run, name, size,
             digest, T0 + 90 * DAY, self.owner.id, T0))
        self.conn.commit()
        return int(cur.lastrowid)

    def _seed(self):
        build = self._check_run(
            self.pub, "CI / build", conclusion="success",
            created_at=T0, panel="passed",
            description="Job 'build' concluded success.")
        self._check_run(
            self.pub, "CI / test", conclusion="failure",
            created_at=T0 + 65, panel="failed",
            description="2 tests failed.")
        self._check_run(self.pub, "Docs / build", created_at=T0 + 10)
        self._check_run(self.pub, "external-scan", created_at=T0 + 20)
        self._check_run(
            self.pub, "CI / build", oid=OID2, created_at=T0 + 30)
        self._artifact(self.pub, build, "app.zip", size=300)
        return build

    def _viewer(self, who):
        return {"owner": self.owner,
                "stranger": self.stranger,
                "anon": None}[who]

    # -- the run list --------------------------------

    def test_run_list_groups_by_workflow_and_commit(self):
        self._seed()
        runs = self.store.list_runs(self.owner, "volmarr", "pub")
        self.assertEqual(
            [(run.workflow, run.oid) for run in runs],
            [("CI", OID), ("Docs", OID), ("CI", OID2)])
        ci = runs[0]
        self.assertEqual(
            [job.job_id for job in ci.jobs], ["build", "test"])
        self.assertEqual(ci.conclusion, "failure")
        self.assertEqual(ci.span_seconds, 65)
        self.assertIn("\u2717 Failed", ci.words)
        self.assertIn("1 minute 5 seconds", ci.words)
        self.assertEqual(runs[2].conclusion, "success")

    def test_run_list_excludes_plain_checks(self):
        self._seed()
        names = [job.check_name
                 for run in self.store.list_runs(
                     self.owner, "volmarr", "pub")
                 for job in run.jobs]
        self.assertNotIn("external-scan", names)
        self.assertEqual(len(names), 4)

    def test_run_list_empty_repository(self):
        self.assertEqual(
            self.store.list_runs(self.owner, "volmarr", "pub"), [])

    def test_run_list_permissions(self):
        self._check_run(self.priv, "CI / build")
        self.assertEqual(
            _reason(self.store.list_runs,
                    self.stranger, "volmarr", "priv"),
            "repository_not_found")
        self.assertEqual(
            _reason(self.store.list_runs,
                    self.owner, "volmarr", "nope"),
            "repository_not_found")
        self._seed()
        runs = self.store.list_runs(None, "volmarr", "pub")
        self.assertEqual(len(runs), 3)

    def test_run_list_page_says_standings_in_words(self):
        self._seed()
        runs = self.store.list_runs(self.owner, "volmarr", "pub")
        page = render_run_list_page(runs)
        self.assertIn("Workflow runs", page)
        self.assertIn("\u2717 Failed", page)
        self.assertIn("\u2713 Succeeded", page)
        self.assertIn("never a colour alone", page)
        data = run_to_dict(runs[0])
        self.assertEqual(data["conclusion"], "failure")
        self.assertEqual(data["job_count"], 2)
        self.assertEqual(data["span_seconds"], 65)

    # -- the run detail -------------------------------

    def test_detail_landed_jobs_timing_and_panel(self):
        self._seed()
        detail = self.store.run_detail(
            self.owner, "volmarr", "pub", "CI", OID)
        self.assertIsInstance(detail, RunDetail)
        self.assertEqual(
            [view.job_id for view in detail.jobs],
            ["build", "test"])
        self.assertEqual(detail.jobs[0].job.panel_state, "passed")
        self.assertEqual(detail.jobs[1].job.panel_state, "failed")
        self.assertEqual(detail.jobs[1].conclusion, "failure")
        self.assertEqual(detail.conclusion, "failure")
        self.assertEqual(detail.span_seconds, 65)
        self.assertEqual(detail.artifacts.total_count, 1)
        self.assertEqual(detail.artifacts.total_bytes, 300)

    def test_detail_steps_and_pending_from_workflow_file(self):
        self._seed()
        detail = self.store.run_detail(
            self.owner, "volmarr", "pub", "CI", OID,
            workflow_text=GOOD)
        self.assertIsNotNone(detail.lint)
        self.assertTrue(detail.lint.ok)
        self.assertEqual(
            [view.job_id for view in detail.jobs],
            ["build", "test", "lint"])
        build = detail.jobs[0]
        self.assertEqual(
            [step.name for step in build.steps],
            ["Compile", ""])
        self.assertEqual(build.steps[0].run, "make all")
        pending = detail.jobs[2]
        self.assertIsNone(pending.job)
        self.assertEqual(pending.conclusion, PENDING)
        self.assertIn("\u25d0 Pending", pending.words)
        # Pending never counts toward the run's standing.
        self.assertEqual(detail.conclusion, "failure")
        page = render_run_detail_page(detail)
        self.assertIn("Compile", page)
        self.assertIn("\u25d0 Pending", page)
        self.assertIn("Conclusions land per job", page)

    def test_detail_bad_workflow_file_lints_without_steps(self):
        self._seed()
        detail = self.store.run_detail(
            self.owner, "volmarr", "pub", "CI", OID,
            workflow_text="name: CI\n")
        self.assertFalse(detail.lint.ok)
        self.assertEqual(
            detail.lint.errors[0].reason, "workflow_invalid")
        self.assertTrue(
            all(view.steps == () for view in detail.jobs))
        self.assertEqual(len(detail.jobs), 2)

    def test_detail_logs_ride_s322(self):
        self._seed()
        self.logs.append_log(
            "volmarr", "pub", "run-1", "build",
            "compiling\ndone\n", workflow="CI")
        detail = self.store.run_detail(
            self.owner, "volmarr", "pub", "CI", OID,
            run_id="run-1")
        build, test = detail.jobs
        self.assertIsNotNone(build.log)
        self.assertEqual(build.log.tail.lines, ("compiling", "done"))
        self.assertEqual(build.log.tail.total_lines, 2)
        self.assertIsNone(test.log)
        page = render_run_detail_page(detail)
        self.assertIn("<pre>compiling", page)
        self.assertIn("No stored log stands for this job", page)

    def test_detail_without_run_id_says_so(self):
        self._seed()
        detail = self.store.run_detail(
            self.owner, "volmarr", "pub", "CI", OID)
        self.assertIsNone(detail.run_id)
        page = render_run_detail_page(detail)
        self.assertIn("no run id was named", page)

    def test_detail_unknown_run_is_honestly_empty(self):
        detail = self.store.run_detail(
            self.owner, "volmarr", "pub", "CI", OID)
        self.assertEqual(detail.jobs, ())
        self.assertEqual(detail.conclusion, PENDING)
        self.assertIn("\u25d0 Pending", detail.words)

    def test_detail_permissions_and_address(self):
        self._check_run(self.priv, "CI / build")
        self.assertEqual(
            _reason(self.store.run_detail,
                    self.stranger, "volmarr", "priv", "CI", OID),
            "repository_not_found")
        self.assertEqual(
            _reason(self.store.run_detail,
                    self.owner, "volmarr", "pub", "  ", OID),
            "run_workflow_invalid")
        self.assertEqual(
            _reason(self.store.run_detail,
                    self.owner, "volmarr", "pub", "CI", ""),
            "run_oid_invalid")

    def test_detail_dict_shape(self):
        self._seed()
        detail = self.store.run_detail(
            self.owner, "volmarr", "pub", "CI", OID,
            workflow_text=GOOD)
        data = detail_to_dict(detail)
        self.assertEqual(data["conclusion"], "failure")
        self.assertEqual(data["artifacts"]["total_count"], 1)
        self.assertTrue(data["lint"]["ok"])
        self.assertEqual(data["jobs"][2]["conclusion"], PENDING)
        self.assertFalse(data["jobs"][2]["landed"])
        self.assertEqual(
            data["jobs"][0]["steps"][0]["run"], "make all")

    def test_renders_escape_values(self):
        self._check_run(self.pub, "A&B / build")
        runs = self.store.list_runs(self.owner, "volmarr", "pub")
        page = render_run_list_page(runs)
        self.assertIn("A&amp;B", page)
        self.assertNotIn("<h2>A&B ", page)

    # -- the audit -------------------------------------

    def test_audit_stands_cleanly(self):
        self._seed()
        audit = audit_workflow_ui(self.conn)
        self.assertTrue(audit.stands_cleanly, audit.problems)
        self.assertEqual(audit.schema_version, 137)
        self.assertEqual(audit.rows_scanned, 5)
        page = render_run_list_page(
            self.store.list_runs(self.owner, "volmarr", "pub"),
            audit=audit)
        self.assertIn("stands cleanly", page)

    def test_audit_catches_unlawful_rows(self):
        self._check_run(
            self.pub, "CI / build", conclusion="green")
        self._check_run(self.pub, "CI / not a job")
        audit = audit_workflow_ui(self.conn)
        self.assertFalse(audit.stands_cleanly)
        self.assertEqual(len(audit.problems), 2)

    def test_reads_write_no_audit_rows(self):
        self._seed()
        before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.store.list_runs(self.owner, "volmarr", "pub")
        self.store.run_detail(
            self.owner, "volmarr", "pub", "CI", OID,
            workflow_text=GOOD, run_id="run-1")
        after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.assertEqual(before, after)
