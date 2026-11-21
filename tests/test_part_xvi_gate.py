"""S-328 -- PART XVI GATE battery: CI / Actions, assembled.

The whole Part XVI system struck at once, in the house
gate shape of S-204/S-220/S-236/S-256/S-272/S-288/S-312 --
no new production code, only the battery that walks the
landed S-313..S-327 machinery end to end through its
public seams, at the thing the gate names: **the
reference runner takes a sample repo from push to a
green check on a PR, counted.**

- **The pins** -- the assembled system stands at schema
  132 with 138 audit events (33 auth / 92 repo / 13
  admin), and the claims register still stands at its
  35 rows (C-01..C-35) untouched: Part XVI minted no
  register extension of its own, and this gate claims
  none.
- **Format, triggers, jobs (S-313/S-314/S-315)** -- a
  workflow file parses under S-313's law, its triggers
  fire and filter under S-314, its jobs order and
  expand under S-315 (needs-graph waves, matrix names).
- **The safety law (S-319/S-320/S-325/S-326)** -- CI
  secrets encrypt at rest and mask in text; a fork PR
  is scheduled with no secrets and a read-only token;
  a skip marker suppresses firing and a skipped
  required check is *not passed*, never passed;
  schedules count only on the default branch.
- **The centre (S-316/S-317/S-318/S-321/S-322/S-327)**
  -- a sample repository is created, a feature commit
  lands on a branch, a pull request opens, the workflow
  fires for it, the reference runner executes the job
  in its own working directory speaking S-316 whole,
  its log stream re-judges gapless and is stored under
  S-322, its conclusion lands under S-321 as the check
  run ``CI / build`` in state passed on the PR, the
  S-174 required-check gate moves from missing to
  satisfied, and S-327's UI reads the run back. A
  failing step lands failed and blocks the merge.

Counted with: python3 -m unittest tests.test_part_xvi_gate
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.api_checks import CHECK_RUN_CONCLUSIONS
from samverk.audit import AuditLog
from samverk.check_reporting import (
    POSTER, CheckReportingStore, check_name_for)
from samverk.ci_logs import LogStreamingStore
from samverk.ci_secrets import decrypt_value, encrypt_value, mask_text
from samverk.db import schema_version
from samverk.fork_pr_safety import RunRequest, schedule_dispatch
from samverk.issues import IssueStore
from samverk.protection_rules import ProtectionRuleStore
from samverk.protection_status_checks import (
    StatusCheckProtectionStore)
from samverk.pull_request_checks import PullRequestChecksStore
from samverk.pull_requests import PullRequestStore
from samverk.reference_runner import ReferenceRunner
from samverk.repositories import RepositoryStore
from samverk.runner_protocol import (
    RUNNER_CONCLUSIONS, parse_assignment, parse_conclusion,
    parse_log_chunk, validate_log_stream)
from samverk.skip_markers import (
    contexts_for_run, decide_firing, find_skip_markers,
    judge_required_checks)
from samverk.workflow_format import (
    WORKFLOW_DIRECTORY, discover_workflows, is_workflow_path,
    parse_workflow)
from samverk.workflow_jobs import build_run_plan, jobs_from_definition
from samverk.workflow_schedules import (
    decide_schedule_source, scheduled_entries)
from samverk.workflow_triggers import (
    RepoEvent, decide_trigger, parse_cron, parse_triggers)
from samverk.workflow_ui import (
    WorkflowUIStore, conclusion_words, lint_workflow)

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "docs" / "CLAIMS_REGISTER.md"

PW = "correct horse battery"
T0 = 1_700_000_000

WORKFLOW_TEXT = (
    "name: CI\n"
    "on: [push, pull_request]\n"
    "permissions: read-all\n"
    "jobs:\n"
    "  build:\n"
    "    runner: [linux, self-hosted]\n"
    "    steps:\n"
    "      - name: Greet\n"
    "        run: echo hello-328\n")


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


class PinsTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def test_pins_schema_133_taxonomy_138(self):
        self.assertEqual(schema_version(self.conn), 137)
        self.assertEqual(db.MIGRATIONS[-1][0], 137)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 92)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    def test_runner_and_check_vocabularies_agree(self):
        self.assertEqual(tuple(RUNNER_CONCLUSIONS),
                         tuple(CHECK_RUN_CONCLUSIONS))
        self.assertEqual(POSTER, "samverk-ci")
        self.assertEqual(check_name_for("CI", "build"), "CI / build")

    def test_register_stands_at_35_rows_untouched(self):
        rows = []
        for line in REGISTER.read_text(
                encoding="utf-8").splitlines():
            line = line.strip()
            if re.match(r"\| C-\d+ \|", line):
                rows.append([c.strip() for c in
                             line.strip("|").split("|")])
        self.assertEqual(len(rows), 35)
        self.assertEqual([r[0] for r in rows],
                         [f"C-{i:02d}" for i in range(1, 36)])
        self.assertEqual(rows[0][0], "C-01")
        self.assertEqual(rows[-1][0], "C-35")

    def test_part_xvi_tables_stand(self):
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("check_runs", "commit_checks", "ci_secrets",
                      "ci_logs", "runner_registration_tokens",
                      "runners"):
            self.assertIn(table, tables, msg=table)


class FormatTriggerJobsTests(unittest.TestCase):
    def test_workflow_file_parses_under_s313(self):
        definition = parse_workflow(WORKFLOW_TEXT)
        self.assertEqual(definition.name, "CI")
        self.assertTrue(is_workflow_path(
            f"{WORKFLOW_DIRECTORY}/ci.yml"))
        self.assertFalse(is_workflow_path(".github/workflows/ci.yml"))
        self.assertEqual(
            discover_workflows(
                [f"{WORKFLOW_DIRECTORY}/ci.yml", "README.md",
                 f"{WORKFLOW_DIRECTORY}/nightly.yaml"]),
            (f"{WORKFLOW_DIRECTORY}/ci.yml",
             f"{WORKFLOW_DIRECTORY}/nightly.yaml"))

    def test_triggers_fire_and_filter(self):
        triggers = parse_triggers(
            {"push": {"branches": ["main"]}})
        self.assertTrue(decide_trigger(
            triggers, RepoEvent("push", branch="main")).fires)
        decision = decide_trigger(
            triggers, RepoEvent("push", branch="dev"))
        self.assertEqual((decision.fires, decision.reason),
                         (False, "branch_filtered"))
        pr_triggers = parse_triggers("pull_request")
        self.assertTrue(decide_trigger(
            pr_triggers, RepoEvent("pull_request", branch="main",
                                   action="opened")).fires)

    def test_cron_parses_and_advances(self):
        cron = parse_cron("0 9 * * *")
        from samverk.workflow_triggers import next_cron_after
        nxt = next_cron_after(cron, datetime(2026, 11, 17, 8, 0))
        self.assertEqual((nxt.hour, nxt.minute), (9, 0))
        self.assertEqual(nxt.day, 17)

    def test_jobs_order_waves_and_matrix(self):
        definition = parse_workflow(
            "name: CI\n"
            "on: push\n"
            "jobs:\n"
            "  build:\n"
            "    runner: [linux]\n"
            "    steps:\n"
            "      - run: echo build\n"
            "  test:\n"
            "    runner: [linux]\n"
            "    needs: [build]\n"
            "    steps:\n"
            "      - run: echo test\n")
        plan = build_run_plan(jobs_from_definition(definition))
        self.assertEqual(plan.order, ("build", "test"))
        self.assertEqual(plan.waves, (("build",), ("test",)))
        # Matrix expansion lives at S-315's own dict seam.
        from samverk.workflow_jobs import expand_job, parse_jobs
        job = parse_jobs({"test": {
            "runner": "linux",
            "strategy": {"matrix": {
                "py": ["3.11", "3.12"]}},
            "steps": [{"run": "echo test"}]}})[0]
        self.assertEqual(
            [i.id for i in expand_job(job)],
            ["test (3.11)", "test (3.12)"])

    def test_lint_speaks_plain_words(self):
        clean = lint_workflow(WORKFLOW_TEXT,
                              path=f"{WORKFLOW_DIRECTORY}/ci.yml")
        self.assertTrue(clean.ok)
        bad = lint_workflow(
            "name: CI\non: push\njobs:\n  build:\n"
            "    runner: [linux]\n    steps:\n"
            "      - uses: actions/checkout@v4\n",
            path=f"{WORKFLOW_DIRECTORY}/ci.yml")
        self.assertFalse(bad.ok)
        self.assertTrue(bad.errors)


class SafetyLawTests(unittest.TestCase):
    def test_secret_encrypts_at_rest_and_masks(self):
        key = bytes(range(32))
        stored = encrypt_value(key, "gate-secret-328")
        self.assertNotIn("gate-secret-328", stored)
        self.assertEqual(decrypt_value(key, stored), "gate-secret-328")
        masked = mask_text("token is gate-secret-328 ok",
                           ("gate-secret-328",))
        self.assertNotIn("gate-secret-328", masked)

    def test_fork_pr_gets_no_secrets_and_read_only_token(self):
        plan = schedule_dispatch(
            RunRequest(event="pull_request",
                       base_repository="volmarr/pub",
                       head_repository="mallory/pub",
                       declared_permissions="write-all"),
            secret_env={"API_KEY": "gate-secret-328"})
        self.assertTrue(plan.is_fork)
        self.assertEqual(plan.env, {})
        self.assertEqual(plan.withheld_secret_names, ("API_KEY",))
        self.assertTrue(plan.token_read_only)
        same = schedule_dispatch(
            RunRequest(event="pull_request",
                       base_repository="volmarr/pub",
                       head_repository="volmarr/pub"),
            secret_env={"API_KEY": "gate-secret-328"})
        self.assertFalse(same.is_fork)
        self.assertEqual(same.env, {"API_KEY": "gate-secret-328"})

    def test_skip_marker_suppresses_and_never_passes(self):
        self.assertEqual(find_skip_markers("fix [skip ci] please"),
                         ("[skip ci]",))
        triggers = parse_triggers(["push", "pull_request"])
        decision = decide_firing(
            triggers, RepoEvent("push", branch="main"),
            "fix [skip ci] please")
        self.assertFalse(decision.fires)
        self.assertTrue(decision.skipped)
        contexts = contexts_for_run("CI", ("build",))
        self.assertEqual(contexts, ("CI / build",))
        verdict = judge_required_checks(
            contexts, (), skipped_contexts=contexts)
        self.assertFalse(verdict.satisfied)
        self.assertEqual(verdict.verdicts[0].state, "skipped")
        self.assertFalse(verdict.verdicts[0].counts_as_passed)
        # Even a recorded pass cannot rescue a skipped context.
        verdict = judge_required_checks(
            contexts, (("CI / build", "passed"),),
            skipped_contexts=contexts)
        self.assertFalse(verdict.satisfied)

    def test_schedule_counts_only_on_default_branch(self):
        self.assertTrue(
            decide_schedule_source("main", "main").is_default)
        self.assertFalse(
            decide_schedule_source("feature", "main").is_default)
        entries = scheduled_entries(
            "nightly", parse_triggers(
                {"schedule": [{"cron": "0 2 * * *"}]}))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].expression, "0 2 * * *")
        self.assertEqual(
            scheduled_entries("ci", parse_triggers("push")), ())

    def test_conclusion_words_are_text_not_colour_only(self):
        words = conclusion_words("success")
        self.assertIn("Succeeded", words)


class EndToEndTests(unittest.TestCase):
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
        self.logs = LogStreamingStore(
            self.conn, self.repos, time_fn=self.clock)
        self.ui = WorkflowUIStore(
            self.conn, self.repos, time_fn=self.clock)
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

    def _run_and_land(self, steps, run_id="run-1"):
        work = self.root / f"work-{run_id}"
        work.mkdir()
        runner = ReferenceRunner(work, labels=("self-hosted",))
        payload = {
            "kind": "assignment", "protocol": 1,
            "response": "assignment", "run_id": run_id,
            "job_id": "build", "workflow": "CI",
            "repository": "volmarr/pub", "oid": self.head_oid,
            "steps": steps,
            "runner_labels": ["self-hosted"],
            "env_names": [], "timeout_minutes": 5}
        result = runner.run_assignment(payload)
        offer = parse_assignment(payload)
        again = parse_conclusion(result.messages[-1], offer)
        self.assertEqual(again.conclusion,
                         result.conclusion.conclusion)
        record = self.reporting.report_conclusion(
            offer, result.conclusion)
        return result, record

    def test_push_to_green_check_on_a_pr_counted(self):
        # The workflow file itself judges clean and fires.
        definition = parse_workflow(WORKFLOW_TEXT)
        self.assertEqual(definition.name, "CI")
        triggers = parse_triggers(["push", "pull_request"])
        self.assertTrue(decide_trigger(
            triggers, RepoEvent("push", branch="feature")).fires)
        self.assertTrue(decide_trigger(
            triggers, RepoEvent("pull_request", branch="main",
                                action="opened")).fires)
        plan = build_run_plan(jobs_from_definition(definition))
        self.assertEqual(plan.order, ("build",))

        # The required check starts missing; the gate blocks.
        self._require("CI / build")
        decision = self._gate()
        self.assertEqual(decision.missing_checks, ("CI / build",))
        self.assertFalse(decision.satisfied)

        # The reference runner takes the job end to end.
        result, record = self._run_and_land(
            [{"name": "Greet", "run": "echo hello-328"}])
        self.assertEqual(result.decision, "accept")
        self.assertEqual(result.conclusion.conclusion, "success")
        kinds = [m["kind"] for m in result.messages]
        self.assertEqual(kinds[0], "assignment_reply")
        self.assertEqual(kinds[-1], "conclusion")

        # Its log stream re-judges gapless and is stored (S-322).
        chunks = [parse_log_chunk(m) for m in result.messages
                  if m["kind"] == "log_chunk"]
        self.assertGreater(validate_log_stream(chunks), 0)
        texts = "".join(m["text"] for m in result.messages
                        if m["kind"] == "log_chunk")
        self.assertIn("hello-328", texts)
        self.logs.append_log(
            "volmarr", "pub", "run-1", "build", texts,
            workflow="CI")
        tail = self.logs.tail_log(
            self.owner, "volmarr", "pub", "run-1", "build")
        self.assertIn("hello-328", "\n".join(tail.lines))
        download = self.logs.download_log(
            self.owner, "volmarr", "pub", "run-1", "build")
        self.assertIn("hello-328", download.text)

        # The conclusion landed as a green check on the PR.
        self.assertEqual(record.name, "CI / build")
        self.assertEqual(record.conclusion, "success")
        self.assertEqual(record.panel_state, "passed")
        self.assertEqual(record.poster, POSTER)
        panel = self.checks.checks_for(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertEqual(
            [(p.context, p.state) for p in panel],
            [("CI / build", "passed")])

        # The S-174 gate is satisfied by the landed job.
        decision = self._gate()
        self.assertEqual(decision.passed_checks, ("CI / build",))
        self.assertTrue(decision.satisfied)
        self.assertTrue(self.gate.enforce_pull_request(
            self.owner, "volmarr", "pub",
            self.pr.number).satisfied)

        # S-327's UI reads the run back, green in words.
        runs = self.ui.list_runs(self.owner, "volmarr", "pub")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].workflow, "CI")
        self.assertEqual(runs[0].oid, self.head_oid)
        detail = self.ui.run_detail(
            self.owner, "volmarr", "pub", "CI", self.head_oid,
            run_id="run-1")
        self.assertEqual(len(detail.jobs), 1)
        self.assertEqual(detail.jobs[0].job_id, "build")
        self.assertEqual(detail.jobs[0].conclusion, "success")

    def test_failing_step_lands_failed_and_blocks(self):
        self._require("CI / build")
        result, record = self._run_and_land(
            [{"name": "Boom", "run": "exit 3"}])
        self.assertEqual(result.conclusion.conclusion, "failure")
        self.assertEqual(record.panel_state, "failed")
        decision = self._gate()
        self.assertEqual(decision.failed_checks, ("CI / build",))
        self.assertFalse(decision.satisfied)

    def test_check_on_another_commit_does_not_count(self):
        self._require("CI / build")
        work = self.root / "work-other"
        work.mkdir()
        runner = ReferenceRunner(work, labels=("self-hosted",))
        payload = {
            "kind": "assignment", "protocol": 1,
            "response": "assignment", "run_id": "run-9",
            "job_id": "build", "workflow": "CI",
            "repository": "volmarr/pub", "oid": self.base_oid,
            "steps": [{"name": "Greet", "run": "echo hi"}],
            "runner_labels": ["self-hosted"],
            "env_names": [], "timeout_minutes": 5}
        result = runner.run_assignment(payload)
        self.reporting.report_conclusion(
            parse_assignment(payload), result.conclusion)
        decision = self._gate()
        self.assertEqual(decision.missing_checks, ("CI / build",))
        self.assertFalse(decision.satisfied)


if __name__ == "__main__":
    unittest.main()
