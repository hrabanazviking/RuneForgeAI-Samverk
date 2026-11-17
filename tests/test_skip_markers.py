"""S-325 acceptance battery: skip markers.

Acceptance (roadmap S-325): Skip markers --
`[skip ci]` and kin honoured for push/PR
triggers; required checks treat skipped as
*not passed*, never as passed (the known trap).

The centre is samverk/skip_markers.py: the five
GitHub markers matched case-insensitively as
whole bracketed tokens; `decide_firing` judging
an event through S-314's own `decide_trigger`
with the marker applied (push and pull_request
suppressed, every other event recorded but not
honoured); and `judge_required_checks`, the
gate judge that answers `skipped` -- never
passed -- for a required context a skipped
workflow would have produced, whatever state a
panel row claims for it, proven both as a pure
judgement and against S-174's real gate over a
live pull request. No migration (schema stays
132); taxonomy unmoved at 138 (33 auth / 92
repo / 13 admin).

Counted with: python3 -m unittest tests.test_skip_markers
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.issues import IssueStore
from samverk.protection_rules import ProtectionRuleStore
from samverk.protection_status_checks import (
    StatusCheckProtectionStore)
from samverk.pull_request_checks import PullRequestChecksStore
from samverk.pull_requests import PullRequestStore
from samverk.repositories import RepositoryStore
from samverk.skip_markers import (
    SKIP_MARKERS, SKIPPABLE_EVENTS, SkipMarkerError,
    audit_skip_markers, contexts_for_run, decide_firing,
    find_skip_markers, judge_required_checks,
    render_skip_markers_page, verdict_to_dict)
from samverk.workflow_triggers import (
    RepoEvent, parse_triggers)

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def _reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except SkipMarkerError as exc:
        return exc.reason
    raise AssertionError("expected SkipMarkerError")


def _push(branch="main", paths=("src/a.py",)):
    return RepoEvent(kind="push", branch=branch, paths=paths)


def _pr(action="opened", branch="main", paths=("src/a.py",)):
    return RepoEvent(
        kind="pull_request", branch=branch, paths=paths,
        action=action)


class MarkerFindTests(unittest.TestCase):
    def test_the_five_markers_exact(self):
        self.assertEqual(
            SKIP_MARKERS,
            ("[skip ci]", "[ci skip]", "[no ci]",
             "[skip actions]", "[actions skip]"))
        for marker in SKIP_MARKERS:
            self.assertEqual(find_skip_markers(marker), (marker,))

    def test_case_insensitive_and_in_prose(self):
        self.assertEqual(
            find_skip_markers("Fix the thing [SKIP CI] please"),
            ("[skip ci]",))
        self.assertEqual(
            find_skip_markers("docs only\n\n[Ci Skip]"),
            ("[ci skip]",))

    def test_bare_words_and_half_brackets_are_prose(self):
        self.assertEqual(find_skip_markers("skip ci"), ())
        self.assertEqual(find_skip_markers("[skip ci"), ())
        self.assertEqual(find_skip_markers("skip ci]"), ())
        self.assertEqual(find_skip_markers("[skip  ci]"), ())
        self.assertEqual(find_skip_markers(""), ())
        self.assertEqual(find_skip_markers(None), ())

    def test_order_of_first_appearance_across_texts(self):
        found = find_skip_markers(
            "title [no ci]", "body [skip ci] and [no ci] again")
        self.assertEqual(found, ("[no ci]", "[skip ci]"))

    def test_non_text_refused(self):
        self.assertEqual(
            _reason(find_skip_markers, 42), "skip_text_invalid")
        self.assertEqual(
            _reason(find_skip_markers, "ok", b"[skip ci]"),
            "skip_text_invalid")


class FiringTests(unittest.TestCase):
    def setUp(self):
        self.triggers = parse_triggers(["push", "pull_request"])

    def test_push_without_marker_fires(self):
        decision = decide_firing(
            self.triggers, _push(), "ordinary work")
        self.assertTrue(decision.fires)
        self.assertFalse(decision.skipped)
        self.assertEqual(decision.markers, ())
        self.assertEqual(decision.reason, "matched")

    def test_push_with_marker_suppressed(self):
        decision = decide_firing(
            self.triggers, _push(), "wip [skip ci]")
        self.assertFalse(decision.fires)
        self.assertTrue(decision.skipped)
        self.assertEqual(decision.markers, ("[skip ci]",))
        self.assertEqual(decision.reason, "skip_marker")
        self.assertEqual(decision.trigger_reason, "matched")
        self.assertIn("[skip ci]", decision.words)

    def test_each_kin_marker_suppresses_push(self):
        for marker in SKIP_MARKERS:
            decision = decide_firing(
                self.triggers, _push(), f"x {marker}")
            self.assertTrue(decision.skipped, marker)
            self.assertFalse(decision.fires, marker)

    def test_pull_request_marker_in_title_or_head_message(self):
        by_title = decide_firing(
            self.triggers, _pr(), "Docs sweep [no ci]", "head msg")
        self.assertTrue(by_title.skipped)
        by_head = decide_firing(
            self.triggers, _pr(), "Docs sweep", "head [actions skip]")
        self.assertTrue(by_head.skipped)
        self.assertEqual(by_head.markers, ("[actions skip]",))

    def test_pull_request_without_marker_fires(self):
        decision = decide_firing(self.triggers, _pr(), "real work")
        self.assertTrue(decision.fires)
        self.assertFalse(decision.skipped)

    def test_marker_keeps_trigger_reason_when_filtered(self):
        triggers = parse_triggers(
            {"push": {"branches": ["release/*"]}})
        decision = decide_firing(
            triggers, _push(branch="dev"), "wip [skip ci]")
        self.assertTrue(decision.skipped)
        self.assertFalse(decision.fires)
        self.assertEqual(decision.trigger_reason, "branch_filtered")

    def test_tag_marker_recorded_not_honoured(self):
        triggers = parse_triggers(["tag"])
        decision = decide_firing(
            triggers, RepoEvent(kind="tag", tag="v1.2"),
            "release [skip ci]")
        self.assertFalse(decision.skipped)
        self.assertTrue(decision.fires)
        self.assertEqual(decision.markers, ("[skip ci]",))

    def test_schedule_and_dispatch_not_event_triggers(self):
        triggers = parse_triggers({"schedule": [{"cron": "0 0 * * *"}], "workflow_dispatch": None})
        for kind in ("schedule", "workflow_dispatch"):
            decision = decide_firing(
                triggers, RepoEvent(kind=kind), "x [skip ci]")
            self.assertFalse(decision.skipped)
            self.assertFalse(decision.fires)
            self.assertEqual(
                decision.reason, "not_an_event_trigger")

    def test_unconfigured_event_with_marker_not_skipped(self):
        decision = decide_firing(
            self.triggers, RepoEvent(kind="tag", tag="v1"),
            "x [skip ci]")
        self.assertFalse(decision.skipped)
        self.assertEqual(decision.reason, "event_not_configured")

    def test_skippable_events_are_push_and_pr(self):
        self.assertEqual(SKIPPABLE_EVENTS, ("push", "pull_request"))


class RequiredCheckTests(unittest.TestCase):
    def test_contexts_for_run_use_s321_names(self):
        self.assertEqual(
            contexts_for_run("CI", ["build", "test (linux, 3.12)"]),
            ("CI / build", "CI / test (linux, 3.12)"))
        self.assertEqual(
            _reason(contexts_for_run, "CI", "build"),
            "skip_jobs_invalid")

    def test_passed_satisfies_and_others_block(self):
        verdict = judge_required_checks(
            ["CI / build", "CI / test", "CI / lint", "CI / docs"],
            [("CI / build", "passed"), ("CI / test", "failed"),
             ("CI / lint", "pending")])
        self.assertFalse(verdict.satisfied)
        states = {v.context: v.state for v in verdict.verdicts}
        self.assertEqual(states["CI / build"], "passed")
        self.assertEqual(states["CI / test"], "failed")
        self.assertEqual(states["CI / lint"], "pending")
        self.assertEqual(states["CI / docs"], "missing")
        self.assertEqual(
            verdict.blockers,
            ("CI / test", "CI / lint", "CI / docs"))

    def test_all_passed_satisfies(self):
        verdict = judge_required_checks(
            ["CI / build"], [("CI / build", "passed")])
        self.assertTrue(verdict.satisfied)
        self.assertEqual(verdict.blockers, ())
        self.assertIn("1 of 1", verdict.words)

    def test_no_required_checks_satisfies(self):
        verdict = judge_required_checks([], [("CI / build", "failed")])
        self.assertTrue(verdict.satisfied)

    def test_skipped_is_not_passed_the_trap(self):
        # The trap's exact shape: a panel row claiming
        # `passed` for a context the skipped workflow
        # would have produced (a `skipped` conclusion
        # folded to passed). The judge refuses it.
        verdict = judge_required_checks(
            ["CI / build"],
            [("CI / build", "passed")],
            skipped_contexts=("CI / build",))
        self.assertFalse(verdict.satisfied)
        only = verdict.verdicts[0]
        self.assertEqual(only.state, "skipped")
        self.assertEqual(only.recorded_state, "passed")
        self.assertFalse(only.counts_as_passed)
        self.assertEqual(verdict.blockers, ("CI / build",))

    def test_skipped_with_no_row_is_skipped_not_missing(self):
        verdict = judge_required_checks(
            ["CI / build"], [], skipped_contexts=("CI / build",))
        self.assertEqual(verdict.verdicts[0].state, "skipped")
        self.assertEqual(verdict.verdicts[0].recorded_state, "")
        self.assertFalse(verdict.satisfied)

    def test_skipped_non_required_context_does_not_block(self):
        verdict = judge_required_checks(
            ["CI / build"],
            [("CI / build", "passed"), ("CI / extra", "passed")],
            skipped_contexts=("CI / extra",))
        self.assertTrue(verdict.satisfied)

    def test_result_forms_and_latest_row_stands(self):
        row = SimpleNamespace(context="CI / build", state="failed")
        verdict = judge_required_checks(
            ["CI / build", "CI / test"],
            [row, {"context": "CI / test", "state": "pending"},
             ("CI / test", "passed")])
        states = {v.context: v.state for v in verdict.verdicts}
        self.assertEqual(states["CI / build"], "failed")
        self.assertEqual(states["CI / test"], "passed")

    def test_unknown_state_and_bad_shapes_refused(self):
        self.assertEqual(
            _reason(judge_required_checks,
                    ["CI / build"], [("CI / build", "skipped")]),
            "skip_result_invalid")
        self.assertEqual(
            _reason(judge_required_checks, "CI / build", []),
            "skip_required_invalid")
        self.assertEqual(
            _reason(judge_required_checks, [""], []),
            "skip_required_invalid")
        self.assertEqual(
            _reason(judge_required_checks, ["A"], [42]),
            "skip_result_invalid")

    def test_verdict_to_dict_shape(self):
        verdict = judge_required_checks(
            ["CI / build"], [], skipped_contexts=("CI / build",))
        data = verdict_to_dict(verdict)
        self.assertFalse(data["satisfied"])
        self.assertEqual(data["blockers"], ["CI / build"])
        self.assertEqual(data["checks"], [{
            "context": "CI / build", "state": "skipped",
            "recorded_state": "", "counts_as_passed": False}])


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(
        ["git", f"--git-dir={repo}", *args],
        capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_commit(repo, parents, files, message):
    lines = []
    for name in sorted(files):
        blob = git(repo, "hash-object", "-w", "--stdin",
                   input_bytes=files[name].encode())
        lines.append(f"100644 blob {blob}\t{name}\n")
    tree = git(repo, "mktree", input_bytes="".join(lines).encode())
    args = ["commit-tree", tree]
    for parent in parents:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class GateIntegrationTests(unittest.TestCase):
    """The trap closed against S-174's real gate."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts, audit=self.audit)
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
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")
        base = make_commit(self.path, [], {"a.txt": "a\n"}, "base")
        git(self.path, "update-ref", "refs/heads/main", base)
        head = make_commit(
            self.path, [base], {"a.txt": "b\n"}, "feature [skip ci]")
        git(self.path, "update-ref", "refs/heads/feature", head)
        self.pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature")
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "main",
            required_status_checks=("CI / build",))

    def _panel(self):
        return self.checks.checks_for(
            self.owner, "volmarr", "pub", self.pr.number)

    def test_skipped_run_lands_nothing_and_gate_blocks(self):
        decision = self.gate.check_pull_request(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertFalse(decision.checks_satisfied)
        verdict = judge_required_checks(
            ["CI / build"], self._panel(),
            skipped_contexts=contexts_for_run("CI", ["build"]))
        self.assertFalse(verdict.satisfied)
        self.assertEqual(verdict.verdicts[0].state, "skipped")

    def test_folded_passed_row_does_not_satisfy_skipped(self):
        # A `skipped` conclusion folded onto the panel as
        # `passed` (S-246's fold) satisfies S-174's own
        # gate -- and S-325's judge still refuses it,
        # because the run was trigger-skipped.
        self.checks.record_result(
            "volmarr", "pub", self.pr.head_oid,
            "CI / build", "passed",
            description="conclusion skipped, folded passed")
        decision = self.gate.check_pull_request(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertTrue(decision.checks_satisfied)
        verdict = judge_required_checks(
            ["CI / build"], self._panel(),
            skipped_contexts=contexts_for_run("CI", ["build"]))
        self.assertFalse(verdict.satisfied)
        self.assertEqual(verdict.verdicts[0].state, "skipped")
        self.assertEqual(verdict.verdicts[0].recorded_state, "passed")

    def test_real_passed_run_satisfies_both_judges(self):
        self.checks.record_result(
            "volmarr", "pub", self.pr.head_oid,
            "CI / build", "passed")
        verdict = judge_required_checks(
            ["CI / build"], self._panel(), skipped_contexts=())
        self.assertTrue(verdict.satisfied)


class AuditAndRenderTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def test_audit_stands_cleanly_on_live_instance(self):
        audit = audit_skip_markers(self.conn)
        self.assertTrue(audit.stands_cleanly)
        self.assertEqual(audit.schema_version, 132)
        self.assertEqual(schema_version(self.conn), 132)
        self.assertEqual(audit.events_scanned, 138)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    def test_audit_catches_planted_skip_table(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE skip_marker_runs (id INTEGER)")
        audit = audit_skip_markers(self.conn)
        self.assertFalse(audit.stands_cleanly)
        self.assertEqual(audit.offending_tables, ("skip_marker_runs",))

    def test_render_page_says_the_law_and_escapes(self):
        decision = decide_firing(
            parse_triggers(["push"]), _push(), "x [skip ci]")
        verdict = judge_required_checks(
            ["CI / build"], [], skipped_contexts=("CI / build",))
        page = render_skip_markers_page(
            decision=decision, verdict=verdict,
            audit=audit_skip_markers(self.conn))
        self.assertIn("[skip ci]", page)
        self.assertIn("not passed", page)
        self.assertIn("stands cleanly", page)
        self.assertIn("CI / build", page)


if __name__ == "__main__":
    unittest.main()
