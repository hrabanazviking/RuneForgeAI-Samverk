"""S-321 acceptance battery: check reporting.

Acceptance (roadmap S-321): Check reporting --
job conclusions land as check runs (S-246) on
the commit and PR; required checks (S-174) can
gate merges on them.

The centre is samverk/check_reporting.py:
`CheckReportingStore.report_conclusion` takes
S-316's assignment + conclusion pair and writes
exactly what S-246's post writes -- one
`check_runs` row (status completed, the
conclusion in the run vocabulary, poster
`samverk-ci`) and one S-157 row folded through
`record_result` at S-246's decided panel state,
stamped with the same poster. The check's name
is `<workflow> / <job>`, the context a branch
rule requires; S-174's gate is then satisfied
or blocked by the landed job exactly as by an
external post. No migration (schema stays 130);
taxonomy unmoved at 135 (33 auth / 89 repo /
13 admin); a landing writes no audit row.

Counted with: python3 -m unittest tests.test_check_reporting
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
from samverk.api_checks import CHECK_RUN_CONCLUSIONS
from samverk.audit import AuditLog
from samverk.check_reporting import (
    CHECK_RUN_STATUS_COMPLETED, POSTER, CheckReportingError,
    CheckReportingStore, audit_check_reporting,
    check_name_for, check_report_to_dict, describe_report,
    panel_state_for, render_check_reporting_page)
from samverk.db import schema_version
from samverk.issues import IssueStore
from samverk.protection_rules import ProtectionRuleStore
from samverk.protection_status_checks import (
    StatusCheckProtectionStore)
from samverk.pull_request_checks import PullRequestChecksStore
from samverk.pull_requests import PullRequestStore
from samverk.reference_runner import ReferenceRunner
from samverk.repositories import RepositoryStore
from samverk.runner_protocol import (
    RUNNER_CONCLUSIONS, ConclusionReport, StepConclusion,
    parse_assignment, parse_conclusion)

PW = "correct horse battery"
T0 = 1_700_000_000
OID = "a" * 40


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes,
                         env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_commit(repo, parents, files, message):
    lines = []
    for name in sorted(files):
        blob = git(repo, "hash-object", "-w", "--stdin",
                   input_bytes=files[name].encode())
        lines.append(f"100644 blob {blob}\t{name}\n")
    tree = git(repo, "mktree",
               input_bytes="".join(lines).encode())
    args = ["commit-tree", tree]
    for parent in parents:
        args += ["-p", parent]
    return git(repo, *args,
               input_bytes=(message + "\n").encode())


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def _reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except CheckReportingError as exc:
        return exc.reason
    raise AssertionError("expected CheckReportingError")


def _offer(oid=OID, job_id="build", workflow="CI",
           repository="volmarr/pub", run_id="run-1"):
    return parse_assignment({
        "kind": "assignment", "protocol": 1,
        "response": "assignment", "run_id": run_id,
        "job_id": job_id, "workflow": workflow,
        "repository": repository, "oid": oid,
        "steps": [{"name": "hello", "run": "echo hi"}],
        "runner_labels": ["self-hosted"],
        "env_names": [], "timeout_minutes": 5})


def _report(conclusion="success", run_id="run-1",
            job_id="build", summary="", duration=12,
            step_word=None):
    word = step_word if step_word is not None else (
        "success" if conclusion == "success" else
        "skipped" if conclusion == "skipped" else
        "failure" if conclusion == "failure" else
        "success")
    return ConclusionReport(
        run_id=run_id, job_id=job_id, conclusion=conclusion,
        steps=(StepConclusion(index=1, name="hello",
                              conclusion=word),),
        duration_seconds=duration, summary=summary)


class PureLawTests(unittest.TestCase):
    def test_vocabularies_agree_word_for_word(self):
        self.assertEqual(tuple(RUNNER_CONCLUSIONS),
                         tuple(CHECK_RUN_CONCLUSIONS))

    def test_panel_fold_for_every_conclusion(self):
        expected = {
            "success": "passed", "neutral": "passed",
            "skipped": "passed", "failure": "failed",
            "cancelled": "failed", "timed_out": "failed",
            "action_required": "failed"}
        self.assertEqual(set(expected),
                         set(CHECK_RUN_CONCLUSIONS))
        for word, state in expected.items():
            self.assertEqual(panel_state_for(word), state)

    def test_panel_state_refuses_unknown_conclusion(self):
        self.assertEqual(
            _reason(panel_state_for, "green"),
            "check_conclusion_invalid")
        self.assertEqual(
            _reason(panel_state_for, ""), "check_conclusion_invalid")

    def test_check_name_form(self):
        self.assertEqual(check_name_for("CI", "build"), "CI / build")
        self.assertEqual(
            check_name_for("CI", "test (linux, 3.12)"),
            "CI / test (linux, 3.12)")

    def test_check_name_refuses_blank_halves(self):
        self.assertEqual(_reason(check_name_for, "", "build"),
                         "check_name_invalid")
        self.assertEqual(_reason(check_name_for, "CI", "  "),
                         "check_name_invalid")
        self.assertEqual(_reason(check_name_for, None, "build"),
                         "check_name_invalid")

    def test_describe_prefers_summary_one_line(self):
        offer = _offer()
        report = _report(summary="Step 1 failed.\nBadly.")
        self.assertEqual(describe_report(offer, report),
                         "Step 1 failed. Badly.")

    def test_describe_default_words(self):
        offer = _offer()
        report = _report(conclusion="failure", duration=7)
        self.assertEqual(
            describe_report(offer, report),
            "Job 'build' of workflow 'CI' concluded "
            "failure in 7 seconds.")

    def test_pins_hold(self):
        self.assertEqual(POSTER, "samverk-ci")
        self.assertEqual(CHECK_RUN_STATUS_COMPLETED, "completed")
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)


class LandingCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.rules = ProtectionRuleStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.checks = PullRequestChecksStore(
            self.conn, self.repos, self.accounts, self.issues,
            time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.gate = StatusCheckProtectionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.reporting = CheckReportingStore(
            self.conn, self.repos, self.accounts, self.issues,
            time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.path = self.repos.path_for("volmarr", "pub")
        self.base_oid = make_commit(
            self.path, [], {"a.txt": "alpha\n"}, "base")
        git(self.path, "update-ref", "refs/heads/main",
            self.base_oid)
        self.head_oid = make_commit(
            self.path, [self.base_oid], {"a.txt": "beta\n"},
            "feature work")
        git(self.path, "update-ref", "refs/heads/feature",
            self.head_oid)
        self.pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature")

    # -- helpers -----------------------------------------------------

    def _offer(self, **kw):
        kw.setdefault("oid", self.head_oid)
        return _offer(**kw)

    def _land(self, conclusion="success", **kw):
        offer = self._offer()
        return self.reporting.report_conclusion(
            offer, _report(conclusion=conclusion, **kw))

    def _require(self, *names, repo="pub"):
        return self.rules.create_rule(
            self.owner, "volmarr", repo, "main",
            required_status_checks=tuple(names))

    def _gate(self):
        return self.gate.check_pull_request(
            self.owner, "volmarr", "pub", self.pr.number)

    def _counts(self):
        runs = self.conn.execute(
            "SELECT COUNT(*) c FROM check_runs").fetchone()["c"]
        panel = self.conn.execute(
            "SELECT COUNT(*) c FROM commit_checks").fetchone()["c"]
        return runs, panel

    def _audit_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]

    # -- the landing ---------------------------------------------------

    def test_success_lands_on_both_records(self):
        record = self._land()
        self.assertEqual(record.name, "CI / build")
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.conclusion, "success")
        self.assertEqual(record.panel_state, "passed")
        self.assertEqual(record.poster, POSTER)
        self.assertEqual(record.oid, self.head_oid)
        self.assertEqual(record.full_name, "volmarr/pub")
        self.assertEqual(self._counts(), (1, 1))
        row = self.conn.execute(
            "SELECT * FROM check_runs").fetchone()
        self.assertEqual(row["poster"], POSTER)
        self.assertEqual(row["status"], "completed")
        panel = self.checks.checks_for(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertEqual(len(panel), 1)
        self.assertEqual(panel[0].context, "CI / build")
        self.assertEqual(panel[0].state, "passed")
        poster = self.conn.execute(
            "SELECT poster FROM commit_checks").fetchone()
        self.assertEqual(poster["poster"], POSTER)

    def test_failure_lands_failed_with_summary(self):
        record = self._land(
            conclusion="failure", summary="Step 1 blew up.")
        self.assertEqual(record.panel_state, "failed")
        self.assertEqual(record.description, "Step 1 blew up.")
        panel = self.checks.checks_for(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertEqual(panel[0].state, "failed")
        self.assertEqual(panel[0].description, "Step 1 blew up.")

    def test_every_conclusion_folds_and_lands(self):
        expected = {
            "success": "passed", "neutral": "passed",
            "skipped": "passed", "failure": "failed",
            "cancelled": "failed", "timed_out": "failed",
            "action_required": "failed"}
        for word, state in expected.items():
            with self.subTest(conclusion=word):
                record = self.reporting.report_conclusion(
                    self._offer(job_id=f"job-{word}"),
                    _report(conclusion=word, job_id=f"job-{word}"))
                self.assertEqual(record.conclusion, word)
                self.assertEqual(record.panel_state, state)
        self.assertEqual(self._counts(), (7, 7))

    def test_reads_for_commit_and_pull_request(self):
        self._land()
        runs = self.reporting.runs_for_commit(
            "volmarr", "pub", self.head_oid)
        self.assertEqual([r.name for r in runs], ["CI / build"])
        on_pr = self.reporting.runs_for_pull_request(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertEqual(len(on_pr), 1)
        self.assertEqual(on_pr[0].conclusion, "success")
        self.assertEqual(
            self.reporting.runs_for_commit(
                "volmarr", "pub", self.base_oid), [])

    def test_rereport_updates_in_place_latest_word_stands(self):
        first = self._land(conclusion="failure",
                           summary="first attempt failed.")
        self.clock.now += 60
        second = self.reporting.report_conclusion(
            self._offer(), _report(conclusion="success"))
        self.assertEqual(second.id, first.id)
        self.assertEqual(second.created_at, first.created_at)
        self.assertGreater(second.updated_at, first.updated_at)
        self.assertEqual(second.conclusion, "success")
        self.assertEqual(second.panel_state, "passed")
        self.assertEqual(self._counts(), (1, 1))

    def test_two_jobs_land_two_checks(self):
        self.reporting.report_conclusion(
            self._offer(job_id="build"),
            _report(conclusion="success", job_id="build"))
        self.reporting.report_conclusion(
            self._offer(job_id="test", run_id="run-1"),
            _report(conclusion="failure", job_id="test"))
        runs = self.reporting.runs_for_commit(
            "volmarr", "pub", self.head_oid)
        self.assertEqual([r.name for r in runs],
                         ["CI / build", "CI / test"])
        self.assertEqual(self._counts(), (2, 2))

    def test_landing_writes_no_audit_row(self):
        before = self._audit_count()
        self._land()
        self.assertEqual(self._audit_count(), before)

    def test_dict_shape(self):
        record = self._land()
        data = check_report_to_dict(record)
        self.assertEqual(data["name"], "CI / build")
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["conclusion"], "success")
        self.assertEqual(data["panel_state"], "passed")
        self.assertEqual(data["poster"], POSTER)
        self.assertEqual(data["run_id"], "run-1")
        self.assertEqual(data["job_id"], "build")
        self.assertEqual(data["workflow"], "CI")
        self.assertEqual(data["oid"], self.head_oid)

    # -- refusals --------------------------------------------------------

    def test_mismatched_report_refused_nothing_stored(self):
        offer = self._offer()
        bad = _report(run_id="run-2")
        self.assertEqual(
            _reason(self.reporting.report_conclusion, offer, bad),
            "check_report_mismatch")
        bad2 = _report(job_id="test")
        self.assertEqual(
            _reason(self.reporting.report_conclusion, offer, bad2),
            "check_report_mismatch")
        self.assertEqual(self._counts(), (0, 0))

    def test_unknown_conclusion_refused_nothing_stored(self):
        offer = self._offer()
        bad = ConclusionReport(
            run_id="run-1", job_id="build", conclusion="green",
            steps=(), duration_seconds=1, summary="")
        self.assertEqual(
            _reason(self.reporting.report_conclusion, offer, bad),
            "check_conclusion_invalid")
        self.assertEqual(self._counts(), (0, 0))

    def test_unknown_repository_refused(self):
        offer = _offer(oid=self.head_oid,
                       repository="volmarr/ghost")
        self.assertEqual(
            _reason(self.reporting.report_conclusion,
                    offer, _report()),
            "repository_not_found")
        self.assertEqual(
            _reason(self.reporting.runs_for_commit,
                    "volmarr", "ghost", self.head_oid),
            "repository_not_found")

    def test_payload_road_lands_a_raw_conclusion(self):
        offer_payload = {
            "kind": "assignment", "protocol": 1,
            "response": "assignment", "run_id": "run-1",
            "job_id": "build", "workflow": "CI",
            "repository": "volmarr/pub", "oid": self.head_oid,
            "steps": [{"name": "hello", "run": "echo hi"}],
            "runner_labels": ["self-hosted"],
            "env_names": [], "timeout_minutes": 5}
        conclusion_payload = {
            "kind": "conclusion", "protocol": 1,
            "run_id": "run-1", "job_id": "build",
            "conclusion": "success",
            "steps": [{"index": 1, "name": "hello",
                       "conclusion": "success"}],
            "duration_seconds": 3, "summary": ""}
        record = self.reporting.report_payload(
            offer_payload, conclusion_payload)
        self.assertEqual(record.panel_state, "passed")
        self.assertEqual(self._counts(), (1, 1))

    def test_payload_at_war_with_its_steps_refused(self):
        offer_payload = {
            "kind": "assignment", "protocol": 1,
            "response": "assignment", "run_id": "run-1",
            "job_id": "build", "workflow": "CI",
            "repository": "volmarr/pub", "oid": self.head_oid,
            "steps": [{"name": "hello", "run": "echo hi"}],
            "runner_labels": ["self-hosted"],
            "env_names": [], "timeout_minutes": 5}
        conclusion_payload = {
            "kind": "conclusion", "protocol": 1,
            "run_id": "run-1", "job_id": "build",
            "conclusion": "success",
            "steps": [{"index": 1, "name": "hello",
                       "conclusion": "failure"}],
            "duration_seconds": 3, "summary": "boom"}
        self.assertEqual(
            _reason(self.reporting.report_payload,
                    offer_payload, conclusion_payload),
            "runner_conclusion_mismatch")
        self.assertEqual(self._counts(), (0, 0))

    # -- the gate (S-174) ------------------------------------------------

    def test_gate_missing_then_satisfied_by_success(self):
        self._require("CI / build")
        decision = self._gate()
        self.assertEqual(decision.missing_checks, ("CI / build",))
        self.assertFalse(decision.satisfied)
        self._land()
        decision = self._gate()
        self.assertEqual(decision.passed_checks, ("CI / build",))
        self.assertTrue(decision.satisfied)
        enforced = self.gate.enforce_pull_request(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertTrue(enforced.satisfied)

    def test_gate_blocked_by_failure(self):
        self._require("CI / build")
        self._land(conclusion="failure", summary="It broke.")
        decision = self._gate()
        self.assertEqual(decision.failed_checks, ("CI / build",))
        self.assertFalse(decision.satisfied)
        self.assertIn("CI / build", decision.blockers[0])

    def test_gate_requires_both_jobs(self):
        self._require("CI / build", "CI / test")
        self.reporting.report_conclusion(
            self._offer(job_id="build"),
            _report(conclusion="success", job_id="build"))
        decision = self._gate()
        self.assertEqual(decision.missing_checks, ("CI / test",))
        self.assertFalse(decision.satisfied)
        self.reporting.report_conclusion(
            self._offer(job_id="test"),
            _report(conclusion="success", job_id="test"))
        self.assertTrue(self._gate().satisfied)

    def test_conclusion_on_another_commit_does_not_count(self):
        self._require("CI / build")
        self.reporting.report_conclusion(
            _offer(oid=self.base_oid), _report())
        decision = self._gate()
        self.assertEqual(decision.missing_checks, ("CI / build",))
        self.assertFalse(decision.satisfied)

    def test_skipped_conclusion_passes_per_s246_fold(self):
        self._require("CI / build")
        self._land(conclusion="skipped")
        self.assertTrue(self._gate().satisfied)

    # -- visibility --------------------------------------------------------

    def test_private_pr_runs_hidden_from_stranger(self):
        priv_path = self.repos.path_for("volmarr", "priv")
        base = make_commit(priv_path, [], {"a.txt": "x\n"}, "b")
        git(priv_path, "update-ref", "refs/heads/main", base)
        head = make_commit(priv_path, [base], {"a.txt": "y\n"}, "h")
        git(priv_path, "update-ref", "refs/heads/feature", head)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "priv", base_branch="main",
            head_branch="feature")
        self.reporting.report_conclusion(
            _offer(oid=head, repository="volmarr/priv"),
            _report())
        mine = self.reporting.runs_for_pull_request(
            self.owner, "volmarr", "priv", pr.number)
        self.assertEqual(len(mine), 1)
        self.assertEqual(
            _reason(self.reporting.runs_for_pull_request,
                    self.stranger, "volmarr", "priv", pr.number),
            "pull_request_not_found")


class RunnerEndToEndTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.rules = ProtectionRuleStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.gate = StatusCheckProtectionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.reporting = CheckReportingStore(
            self.conn, self.repos, self.accounts, self.issues,
            time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")
        self.base_oid = make_commit(
            self.path, [], {"a.txt": "alpha\n"}, "base")
        git(self.path, "update-ref", "refs/heads/main",
            self.base_oid)
        self.head_oid = make_commit(
            self.path, [self.base_oid], {"a.txt": "beta\n"},
            "feature work")
        git(self.path, "update-ref", "refs/heads/feature",
            self.head_oid)
        self.pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature")

    def _require(self, *names):
        return self.rules.create_rule(
            self.owner, "volmarr", "pub", "main",
            required_status_checks=tuple(names))

    def _gate(self):
        return self.gate.check_pull_request(
            self.owner, "volmarr", "pub", self.pr.number)

    def test_reference_runner_success_gates_the_pr(self):
        self._require("CI / build")
        self.assertFalse(self._gate().satisfied)
        work = self.root / "work"
        work.mkdir()
        runner = ReferenceRunner(work, labels=("self-hosted",))
        payload = {
            "kind": "assignment", "protocol": 1,
            "response": "assignment", "run_id": "run-1",
            "job_id": "build", "workflow": "CI",
            "repository": "volmarr/pub", "oid": self.head_oid,
            "steps": [{"name": "hello", "run": "echo hello-321"}],
            "runner_labels": ["self-hosted"],
            "env_names": [], "timeout_minutes": 5}
        result = runner.run_assignment(payload)
        self.assertEqual(result.conclusion.conclusion, "success")
        offer = parse_assignment(payload)
        record = self.reporting.report_conclusion(
            offer, result.conclusion)
        self.assertEqual(record.panel_state, "passed")
        self.assertTrue(self._gate().satisfied)

    def test_reference_runner_failure_blocks_the_pr(self):
        self._require("CI / build")
        work = self.root / "work"
        work.mkdir()
        runner = ReferenceRunner(work, labels=("self-hosted",))
        payload = {
            "kind": "assignment", "protocol": 1,
            "response": "assignment", "run_id": "run-1",
            "job_id": "build", "workflow": "CI",
            "repository": "volmarr/pub", "oid": self.head_oid,
            "steps": [{"name": "boom", "run": "exit 3"}],
            "runner_labels": ["self-hosted"],
            "env_names": [], "timeout_minutes": 5}
        result = runner.run_assignment(payload)
        self.assertEqual(result.conclusion.conclusion, "failure")
        offer = parse_assignment(payload)
        record = self.reporting.report_conclusion(
            offer, result.conclusion)
        self.assertEqual(record.panel_state, "failed")
        decision = self._gate()
        self.assertEqual(decision.failed_checks, ("CI / build",))
        self.assertFalse(decision.satisfied)


class AuditAndPageTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "s.db")
        self.addCleanup(self.conn.close)

    def test_schema_pin(self):
        self.assertEqual(schema_version(self.conn), 131)

    def test_audit_stands_cleanly(self):
        audit = audit_check_reporting(self.conn)
        self.assertTrue(audit.vocabulary_ok)
        self.assertTrue(audit.schema_ok)
        self.assertTrue(audit.events_ok)
        self.assertTrue(audit.tables_ok)
        self.assertEqual(audit.offending_tables, ())
        self.assertEqual(audit.offending_columns, ())
        self.assertEqual(audit.offending_events, ())
        self.assertTrue(audit.stands_cleanly)

    def test_audit_catches_a_planted_table(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE check_reporting_shadow (id INTEGER)")
        audit = audit_check_reporting(self.conn)
        self.assertIn("check_reporting_shadow",
                      audit.offending_tables)
        self.assertFalse(audit.stands_cleanly)

    def test_audit_catches_a_planted_column(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE shadow2 (id INTEGER,"
                " check_reporting_note TEXT)")
        audit = audit_check_reporting(self.conn)
        self.assertIn("shadow2.check_reporting_note",
                      audit.offending_columns)
        self.assertFalse(audit.stands_cleanly)

    def test_page_renders_the_rule(self):
        page = render_check_reporting_page()
        self.assertIn("Check reporting", page)
        self.assertIn("conclusion lands as a check run", page)
        self.assertIn("blocks the merge", page)

    def test_page_escapes_a_landed_run(self):
        from samverk.check_reporting import CheckReport
        record = CheckReport(
            id=1, repo_id=1, full_name="volmarr/pub", oid=OID,
            name="<script> / build", status="completed",
            conclusion="success", panel_state="passed",
            poster=POSTER, description="<b>bold</b>",
            run_id="run-1", job_id="build", workflow="<script>",
            created_at=T0, updated_at=T0)
        page = render_check_reporting_page(report=record)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<b>bold</b>", page)


if __name__ == "__main__":
    unittest.main()
