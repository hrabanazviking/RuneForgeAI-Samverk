"""S-314 acceptance battery: workflow triggers.

Acceptance (roadmap S-314): Triggers -- push,
pull_request, tag, schedule (cron), and manual
dispatch with inputs.

The centre is the pure judge: an ``on`` value
parses into an exact trigger set, repository
events are judged against it with every filter
refusal named in words, cron expressions are
validated field by field and their next firing
computed (February 29 answers, February 31
answers None), dispatch inputs are resolved
against their declarations with defaults filled
and undeclared or missing-required inputs
refused by name, and the audit checks the law
against the live instance -- no table, column
or audit event carries a workflow trigger surface --
with a planted trigger table proving the audit
would catch one arriving ahead of its slice.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.db import schema_version
from samverk.workflow_format import TRIGGER_EVENTS, parse_workflow
from samverk.workflow_triggers import (
    CronSchedule, RepoEvent, TriggerError,
    audit_workflow_triggers, cron_matches,
    decide_trigger, match_patterns, next_cron_after,
    parse_cron, parse_triggers, render_workflow_triggers_page,
    resolve_dispatch_inputs)

ROOT = Path(__file__).resolve().parent.parent


def _reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except TriggerError as exc:
        return exc.reason
    raise AssertionError("expected TriggerError")


class TriggerParseTests(unittest.TestCase):
    def test_vocabulary_is_s313s_five(self):
        self.assertEqual(
            TRIGGER_EVENTS,
            ("push", "pull_request", "tag", "schedule",
             "workflow_dispatch"))
        triggers = parse_triggers("push")
        self.assertEqual(triggers.events, ("push",))

    def test_list_and_mapping_forms(self):
        triggers = parse_triggers(["push", "pull_request"])
        self.assertEqual(
            triggers.events, ("push", "pull_request"))
        triggers = parse_triggers(
            {"push": {"branches": ["main", "release/*"]}})
        spec = triggers.for_event("push")
        self.assertEqual(spec.branches, ("main", "release/*"))
        self.assertIsNone(triggers.for_event("tag"))

    def test_boolean_on_refused(self):
        self.assertEqual(
            _reason(parse_triggers, True), "trigger_invalid")
        self.assertEqual(
            _reason(parse_triggers, None), "trigger_invalid")
        self.assertEqual(
            _reason(parse_triggers, []), "trigger_invalid")

    def test_unknown_event_and_duplicate_refused(self):
        self.assertEqual(
            _reason(parse_triggers, "release"),
            "trigger_event_unknown")
        self.assertEqual(
            _reason(parse_triggers, ["push", "push"]),
            "trigger_invalid")

    def test_unknown_key_refused_by_name(self):
        self.assertEqual(
            _reason(parse_triggers,
                    {"push": {"branch": ["main"]}}),
            "trigger_key_unknown")
        self.assertEqual(
            _reason(parse_triggers,
                    {"push": {"tags": ["v*"]}}),
            "trigger_key_unknown")

    def test_filter_conflict_refused(self):
        self.assertEqual(
            _reason(parse_triggers, {"push": {
                "branches": ["main"],
                "branches-ignore": ["dev"]}}),
            "trigger_filters_conflict")
        self.assertEqual(
            _reason(parse_triggers, {"push": {
                "paths": ["src/**"],
                "paths-ignore": ["docs/**"]}}),
            "trigger_filters_conflict")

    def test_ignore_negation_refused(self):
        self.assertEqual(
            _reason(parse_triggers, {"push": {
                "branches-ignore": ["!main"]}}),
            "trigger_invalid")


class PatternTests(unittest.TestCase):
    def test_glob_segments(self):
        self.assertTrue(match_patterns(("main",), "main"))
        self.assertTrue(
            match_patterns(("release/*",), "release/1.0"))
        self.assertFalse(
            match_patterns(("release/*",), "release/a/b"))
        self.assertTrue(
            match_patterns(("release/**",), "release/a/b"))
        self.assertTrue(match_patterns(("v?.?",), "v1.2"))
        self.assertTrue(match_patterns((), "anything"))

    def test_ordered_negation(self):
        patterns = ("**", "!docs/**", "docs/keep.md")
        self.assertTrue(match_patterns(patterns, "src/x.py"))
        self.assertFalse(match_patterns(patterns, "docs/a.md"))
        self.assertTrue(
            match_patterns(patterns, "docs/keep.md"))


class DecideTests(unittest.TestCase):
    def test_push_branch_and_paths(self):
        triggers = parse_triggers({"push": {
            "branches": ["main"], "paths": ["src/**"]}})
        self.assertTrue(decide_trigger(
            triggers, RepoEvent("push", branch="main",
                                paths=("src/a.py",))).fires)
        decision = decide_trigger(
            triggers, RepoEvent("push", branch="dev",
                                paths=("src/a.py",)))
        self.assertEqual(
            (decision.fires, decision.reason),
            (False, "branch_filtered"))
        decision = decide_trigger(
            triggers, RepoEvent("push", branch="main",
                                paths=("docs/a.md",)))
        self.assertEqual(decision.reason, "path_filtered")
        decision = decide_trigger(
            triggers, RepoEvent("push", branch="main"))
        self.assertEqual(decision.reason, "path_filtered")

    def test_push_unconfigured_and_tag_push(self):
        triggers = parse_triggers("pull_request")
        decision = decide_trigger(
            triggers, RepoEvent("push", branch="main"))
        self.assertEqual(decision.reason, "event_not_configured")
        triggers = parse_triggers(["push", "tag"])
        decision = decide_trigger(
            triggers, RepoEvent("push", tag="v1.0"))
        self.assertEqual(
            decision.reason, "tag_push_is_tag_event")

    def test_tag_patterns(self):
        triggers = parse_triggers(
            {"tag": {"tags": ["v*", "!v0.*"]}})
        self.assertTrue(decide_trigger(
            triggers, RepoEvent("tag", tag="v1.2")).fires)
        decision = decide_trigger(
            triggers, RepoEvent("tag", tag="v0.9"))
        self.assertEqual(decision.reason, "tag_filtered")
        decision = decide_trigger(
            triggers, RepoEvent("tag", tag="nightly"))
        self.assertEqual(decision.reason, "tag_filtered")

    def test_pull_request_defaults_and_types(self):
        triggers = parse_triggers("pull_request")
        self.assertTrue(decide_trigger(
            triggers, RepoEvent(
                "pull_request", branch="main",
                action="opened")).fires)
        decision = decide_trigger(
            triggers, RepoEvent(
                "pull_request", branch="main",
                action="closed"))
        self.assertEqual(decision.reason, "type_filtered")
        triggers = parse_triggers(
            {"pull_request": {"types": ["closed"]}})
        self.assertTrue(decide_trigger(
            triggers, RepoEvent(
                "pull_request", branch="main",
                action="closed")).fires)
        self.assertEqual(
            _reason(parse_triggers,
                    {"pull_request": {"types": ["merged"]}}),
            "trigger_invalid")

    def test_clock_and_hand_are_not_events(self):
        triggers = parse_triggers({
            "schedule": [{"cron": "0 3 * * *"}],
            "workflow_dispatch": None})
        for kind in ("schedule", "workflow_dispatch"):
            decision = decide_trigger(
                triggers, RepoEvent(kind))
            self.assertEqual(
                (decision.fires, decision.reason),
                (False, "not_an_event_trigger"))
        self.assertEqual(
            _reason(decide_trigger, triggers,
                    RepoEvent("release")),
            "trigger_event_unknown")


class CronTests(unittest.TestCase):
    def test_field_validation(self):
        self.assertEqual(
            _reason(parse_cron, "61 * * * *"),
            "trigger_cron_invalid")
        self.assertEqual(
            _reason(parse_cron, "* * * *"),
            "trigger_cron_invalid")
        self.assertEqual(
            _reason(parse_cron, "0 0 * foo *"),
            "trigger_cron_invalid")
        self.assertEqual(
            _reason(parse_cron, "0 0 5-2 * *"),
            "trigger_cron_invalid")
        schedule = parse_cron("*/15 9-17 * * mon-fri")
        self.assertEqual(schedule.minutes,
                         frozenset({0, 15, 30, 45}))
        self.assertEqual(schedule.days_of_week,
                         frozenset({1, 2, 3, 4, 5}))

    def test_sunday_zero_and_seven(self):
        self.assertEqual(
            parse_cron("0 0 * * 0").days_of_week,
            parse_cron("0 0 * * 7").days_of_week)
        self.assertEqual(
            parse_cron("0 0 * * sun").days_of_week,
            frozenset({0}))

    def test_matches_and_next(self):
        schedule = parse_cron("30 4 * * *")
        moment = datetime(2026, 11, 14, 4, 30)
        self.assertTrue(cron_matches(schedule, moment))
        self.assertFalse(
            cron_matches(schedule, moment.replace(hour=5)))
        self.assertEqual(
            next_cron_after(schedule, moment),
            datetime(2026, 11, 15, 4, 30))
        self.assertEqual(
            next_cron_after(
                schedule, datetime(2026, 11, 14, 4, 29)),
            datetime(2026, 11, 14, 4, 30))

    def test_dom_dow_or_rule(self):
        # Both day fields restricted: either fires.
        schedule = parse_cron("0 0 13 * fri")
        friday = datetime(2026, 11, 13)  # a Friday the 13th
        self.assertTrue(cron_matches(schedule, friday))
        self.assertTrue(cron_matches(
            schedule, datetime(2026, 12, 13)))  # the 13th, a Sunday
        self.assertTrue(cron_matches(
            schedule, datetime(2026, 11, 20)))  # a Friday, not 13th
        self.assertFalse(cron_matches(
            schedule, datetime(2026, 11, 14)))

    def test_leap_day_answers_and_feb31_none(self):
        schedule = parse_cron("0 0 29 2 *")
        self.assertEqual(
            next_cron_after(schedule, datetime(2026, 3, 1)),
            datetime(2028, 2, 29))
        never = parse_cron("0 0 31 2 *")
        self.assertIsNone(
            next_cron_after(never, datetime(2026, 1, 1)))

    def test_schedule_trigger_shape(self):
        self.assertEqual(
            _reason(parse_triggers, {"schedule": []}),
            "trigger_invalid")
        self.assertEqual(
            _reason(parse_triggers,
                    {"schedule": [{"cron": "0 3 * * *",
                                    "tz": "UTC"}]}),
            "trigger_invalid")
        triggers = parse_triggers(
            {"schedule": [{"cron": "0 3 * * *"},
                          {"cron": "0 4 * * sun"}]})
        spec = triggers.for_event("schedule")
        self.assertEqual(len(spec.crons), 2)
        self.assertIsInstance(spec.crons[0], CronSchedule)


DISPATCH_ON = {
    "workflow_dispatch": {"inputs": {
        "target": {"description": "Where to deploy",
                   "required": True, "type": "string"},
        "retries": {"type": "number", "default": 2},
        "dry_run": {"type": "boolean", "default": "false"},
        "channel": {"type": "choice",
                    "options": ["stable", "beta"],
                    "default": "stable"},
        "note": {"type": "string"}}}}


class DispatchTests(unittest.TestCase):
    def test_resolve_defaults_and_coercion(self):
        triggers = parse_triggers(DISPATCH_ON)
        resolved = resolve_dispatch_inputs(
            triggers, {"target": "prod", "retries": "3",
                       "dry_run": "true"})
        self.assertEqual(resolved, {
            "target": "prod", "retries": 3,
            "dry_run": True, "channel": "stable"})

    def test_missing_required_and_unknown_refused(self):
        triggers = parse_triggers(DISPATCH_ON)
        self.assertEqual(
            _reason(resolve_dispatch_inputs, triggers, {}),
            "dispatch_input_required")
        self.assertEqual(
            _reason(resolve_dispatch_inputs, triggers,
                    {"target": "prod", "surprise": 1}),
            "dispatch_input_unknown")

    def test_type_refusals(self):
        triggers = parse_triggers(DISPATCH_ON)
        self.assertEqual(
            _reason(resolve_dispatch_inputs, triggers,
                    {"target": "prod", "channel": "canary"}),
            "dispatch_input_invalid")
        self.assertEqual(
            _reason(resolve_dispatch_inputs, triggers,
                    {"target": "prod", "dry_run": "yes"}),
            "dispatch_input_invalid")
        self.assertEqual(
            _reason(resolve_dispatch_inputs, triggers,
                    {"target": "prod", "retries": True}),
            "dispatch_input_invalid")

    def test_declaration_law(self):
        self.assertEqual(
            _reason(parse_triggers, {"workflow_dispatch": {
                "inputs": {"x": {"type": "choice"}}}}),
            "trigger_invalid")
        self.assertEqual(
            _reason(parse_triggers, {"workflow_dispatch": {
                "inputs": {"x": {"type": "string",
                                 "options": ["a"]}}}}),
            "trigger_invalid")
        self.assertEqual(
            _reason(parse_triggers, {"workflow_dispatch": {
                "inputs": {"x": {"type": "choice",
                                 "options": ["a"],
                                 "default": "b"}}}}),
            "dispatch_input_invalid")
        self.assertEqual(
            _reason(parse_triggers, {"workflow_dispatch": {
                "inputs": {"x": {"bogus": 1}}}}),
            "trigger_key_unknown")
        self.assertEqual(
            _reason(resolve_dispatch_inputs,
                    parse_triggers("push"), {}),
            "trigger_event_unknown")


class AuditAndPageTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def test_pins_hold(self):
        self.assertEqual(schema_version(self.conn), 128)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)

    def test_audit_clean_on_live_instance(self):
        audit = audit_workflow_triggers(self.conn)
        self.assertTrue(audit.events_ok)
        self.assertTrue(audit.stands_cleanly, audit)
        self.assertEqual(audit.events_scanned, 135)
        self.assertGreater(audit.tables_scanned, 0)

    def test_audit_catches_planted_table(self):
        self.conn.execute(
            "CREATE TABLE workflow_triggers (id INTEGER)")
        audit = audit_workflow_triggers(self.conn)
        self.assertFalse(audit.stands_cleanly)
        self.assertIn("workflow_triggers", audit.offending_tables)
        self.conn.execute("DROP TABLE workflow_triggers")
        self.conn.execute(
            "CREATE TABLE runs (workflow_cron TEXT)")
        audit = audit_workflow_triggers(self.conn)
        self.assertFalse(audit.stands_cleanly)
        self.assertIn("runs.workflow_cron", audit.offending_columns)

    def test_page_says_the_law_in_words(self):
        audit = audit_workflow_triggers(self.conn)
        page = render_workflow_triggers_page(audit)
        self.assertIn("stands cleanly", page)
        self.assertIn("workflow_dispatch", page)
        self.assertIn("Cron", page)
        self.assertNotIn("<script", page)

    def test_document_integration(self):
        definition = parse_workflow(
            "name: CI\n"
            "on: [push, pull_request]\n"
            "jobs:\n"
            "  test:\n"
            "    runner: [linux]\n"
            "    steps:\n"
            "      - run: python3 -m unittest discover\n")
        triggers = parse_triggers(list(definition.triggers))
        self.assertEqual(
            triggers.events, definition.triggers)
        self.assertTrue(decide_trigger(
            triggers, RepoEvent("push", branch="main")).fires)


if __name__ == "__main__":
    unittest.main()
