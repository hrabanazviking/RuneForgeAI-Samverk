"""S-326 acceptance battery: scheduled workflows.

Acceptance (roadmap S-326): Scheduled
workflows -- cron on the default branch only;
drift and missed-run behaviour stated
honestly.

The centre is samverk/workflow_schedules.py:
`decide_schedule_source` and `collect_schedules`
judging that only the default branch's
schedules count (other branches' named as
ignored); `judge_due` and `judge_tick` judging
one scheduler tick over the window since the
last -- a due firing fires at the tick, late by
exactly its stated drift and never early, and
every earlier due firing in the window is
missed, counted and named, never replayed in a
catch-up burst. No migration (schema stays
131); taxonomy unmoved at 135 (33 auth / 89
repo / 13 admin).

Counted with: python3 -m unittest tests.test_workflow_schedules
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.db import schema_version
from samverk.workflow_schedules import (
    MAX_WINDOW_FIRINGS, ScheduleError,
    audit_workflow_schedules, collect_schedules,
    decide_schedule_source, firings_between,
    judge_due, judge_tick,
    render_workflow_schedules_page,
    scheduled_entries, tick_to_dict)
from samverk.workflow_triggers import parse_cron, parse_triggers


def _reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ScheduleError as exc:
        return exc.reason
    raise AssertionError("expected ScheduleError")


def _triggers(*crons):
    return parse_triggers(
        {"schedule": [{"cron": c} for c in crons]})


def _entry(workflow="nightly", cron="0 2 * * *"):
    return scheduled_entries(workflow, _triggers(cron))[0]


class SourceLawTests(unittest.TestCase):
    def test_default_branch_counts(self):
        decision = decide_schedule_source("main", "main")
        self.assertTrue(decision.is_default)
        self.assertEqual(decision.reason, "default_branch")
        self.assertIn("count", decision.words)

    def test_other_branch_does_not_count(self):
        decision = decide_schedule_source("feature", "main")
        self.assertFalse(decision.is_default)
        self.assertEqual(decision.reason, "not_default_branch")
        self.assertIn("main", decision.words)

    def test_non_main_default_counts(self):
        self.assertTrue(
            decide_schedule_source("trunk", "trunk").is_default)
        self.assertFalse(
            decide_schedule_source("main", "trunk").is_default)

    def test_blank_branches_refused(self):
        self.assertEqual(
            _reason(decide_schedule_source, "", "main"),
            "schedule_branch_invalid")
        self.assertEqual(
            _reason(decide_schedule_source, "main", None),
            "schedule_branch_invalid")
        self.assertEqual(
            _reason(decide_schedule_source, "  ", "main"),
            "schedule_branch_invalid")

    def test_collect_on_default_gathers_every_cron(self):
        collection = collect_schedules(
            [("nightly", _triggers("0 2 * * *", "30 3 * * 1")),
             ("ci", parse_triggers("push")),
             ("weekly", _triggers("0 4 * * 0"))],
            "main", "main")
        self.assertEqual(
            [(e.workflow, e.expression) for e in collection.entries],
            [("nightly", "0 2 * * *"),
             ("nightly", "30 3 * * 1"),
             ("weekly", "0 4 * * 0")])
        self.assertEqual(
            collection.declared_workflows,
            ("nightly", "ci", "weekly"))
        self.assertEqual(collection.ignored_workflows, ())

    def test_collect_off_default_counts_nothing_and_names_ignored(self):
        collection = collect_schedules(
            [("nightly", _triggers("0 2 * * *")),
             ("ci", parse_triggers("push"))],
            "feature", "main")
        self.assertEqual(collection.entries, ())
        self.assertEqual(collection.ignored_workflows, ("nightly",))
        self.assertIn("nightly", collection.words)

    def test_entries_empty_without_schedule_trigger(self):
        self.assertEqual(
            scheduled_entries("ci", parse_triggers("push")), ())
        self.assertEqual(
            scheduled_entries(
                "ci", parse_triggers(["push", "workflow_dispatch"])),
            ())

    def test_invalid_definitions_refused(self):
        self.assertEqual(
            _reason(collect_schedules, "nightly", "main", "main"),
            "schedule_definitions_invalid")
        self.assertEqual(
            _reason(collect_schedules,
                    [("nightly",)], "main", "main"),
            "schedule_definitions_invalid")
        self.assertEqual(
            _reason(scheduled_entries, "", _triggers("0 2 * * *")),
            "schedule_workflow_invalid")
        self.assertEqual(
            _reason(scheduled_entries, "ci", {"schedule": []}),
            "schedule_triggers_invalid")


class FiringsTests(unittest.TestCase):
    def test_window_start_excluded_end_included(self):
        cron = parse_cron("0 * * * *")
        found = firings_between(
            cron, datetime(2026, 1, 1, 0, 0),
            datetime(2026, 1, 1, 3, 0))
        self.assertEqual(found, (
            datetime(2026, 1, 1, 1, 0),
            datetime(2026, 1, 1, 2, 0),
            datetime(2026, 1, 1, 3, 0)))

    def test_no_firing_in_window(self):
        cron = parse_cron("0 2 * * *")
        self.assertEqual(firings_between(
            cron, datetime(2026, 1, 1, 3, 0),
            datetime(2026, 1, 1, 4, 0)), ())

    def test_backwards_or_empty_window_refused(self):
        cron = parse_cron("0 2 * * *")
        self.assertEqual(_reason(
            firings_between, cron,
            datetime(2026, 1, 2), datetime(2026, 1, 1)),
            "schedule_window_invalid")
        self.assertEqual(_reason(
            firings_between, cron,
            datetime(2026, 1, 1), datetime(2026, 1, 1)),
            "schedule_window_invalid")

    def test_non_moments_refused(self):
        cron = parse_cron("0 2 * * *")
        self.assertEqual(_reason(
            firings_between, cron, "then", datetime(2026, 1, 1)),
            "schedule_time_invalid")
        self.assertEqual(_reason(
            firings_between, "0 2 * * *",
            datetime(2026, 1, 1), datetime(2026, 1, 2)),
            "schedule_cron_invalid")

    def test_window_too_large_refused_whole(self):
        cron = parse_cron("* * * * *")
        start = datetime(2026, 1, 1)
        end = start + timedelta(minutes=MAX_WINDOW_FIRINGS + 60)
        self.assertEqual(
            _reason(firings_between, cron, start, end),
            "schedule_window_too_large")


class DueTests(unittest.TestCase):
    def test_not_due_states_next_and_never_fires_early(self):
        judgement = judge_due(
            _entry(), datetime(2026, 1, 1, 0, 0),
            datetime(2026, 1, 1, 1, 59))
        self.assertFalse(judgement.fires)
        self.assertEqual(judgement.reason, "not_due")
        self.assertEqual(judgement.due, ())
        self.assertEqual(
            judgement.next_due, datetime(2026, 1, 1, 2, 0))
        self.assertIsNone(judgement.drift_seconds)

    def test_due_exactly_at_tick_fires_with_zero_drift(self):
        judgement = judge_due(
            _entry(), datetime(2026, 1, 1, 0, 0),
            datetime(2026, 1, 1, 2, 0))
        self.assertTrue(judgement.fires)
        self.assertEqual(judgement.reason, "due")
        self.assertEqual(
            judgement.fire_due, datetime(2026, 1, 1, 2, 0))
        self.assertEqual(judgement.drift_seconds, 0)
        self.assertEqual(judgement.missed, ())
        self.assertEqual(
            judgement.next_due, datetime(2026, 1, 2, 2, 0))

    def test_due_fires_late_by_exact_drift(self):
        judgement = judge_due(
            _entry(), datetime(2026, 1, 1, 0, 0),
            datetime(2026, 1, 1, 5, 30))
        self.assertTrue(judgement.fires)
        self.assertEqual(judgement.drift_seconds, 3 * 3600 + 1800)
        self.assertIn("12600 seconds late", judgement.words)

    def test_missed_firings_named_and_never_replayed(self):
        judgement = judge_due(
            _entry(), datetime(2026, 1, 1, 0, 0),
            datetime(2026, 1, 4, 2, 0))
        self.assertEqual(judgement.reason, "due_with_missed")
        self.assertEqual(len(judgement.due), 4)
        self.assertEqual(
            judgement.fire_due, datetime(2026, 1, 4, 2, 0))
        self.assertEqual(judgement.missed, (
            datetime(2026, 1, 1, 2, 0),
            datetime(2026, 1, 2, 2, 0),
            datetime(2026, 1, 3, 2, 0)))
        self.assertEqual(judgement.missed_count, 3)
        self.assertIn("not replayed", judgement.words)
        # The schedule resumes after the tick; it
        # does not rewind to a missed firing.
        self.assertEqual(
            judgement.next_due, datetime(2026, 1, 5, 2, 0))

    def test_week_of_downtime_fires_once_not_seven(self):
        judgement = judge_due(
            _entry(), datetime(2026, 1, 1, 0, 0),
            datetime(2026, 1, 8, 2, 0))
        self.assertEqual(len(judgement.due), 8)
        self.assertTrue(judgement.fires)
        self.assertEqual(judgement.missed_count, 7)

    def test_never_firing_cron_stated_honestly(self):
        entry = _entry("impossible", "0 0 31 2 *")
        judgement = judge_due(
            entry, datetime(2026, 1, 1), datetime(2026, 6, 1))
        self.assertFalse(judgement.fires)
        self.assertEqual(judgement.reason, "never_fires")
        self.assertIsNone(judgement.next_due)
        self.assertIn("never fires", judgement.words)

    def test_empty_window_judges_not_due(self):
        moment = datetime(2026, 1, 1, 2, 0)
        judgement = judge_due(_entry(), moment, moment)
        self.assertFalse(judgement.fires)
        self.assertEqual(judgement.reason, "not_due")

    def test_backwards_window_refused(self):
        self.assertEqual(_reason(
            judge_due, _entry(),
            datetime(2026, 1, 2), datetime(2026, 1, 1)),
            "schedule_window_invalid")
        self.assertEqual(_reason(
            judge_due, _entry(), "then", datetime(2026, 1, 1)),
            "schedule_time_invalid")
        self.assertEqual(_reason(
            judge_due, ("nightly", "0 2 * * *"),
            datetime(2026, 1, 1), datetime(2026, 1, 2)),
            "schedule_entry_invalid")

    def test_window_stamps_ride_on_the_judgement(self):
        start, end = datetime(2026, 1, 1), datetime(2026, 1, 2)
        judgement = judge_due(_entry(), start, end)
        self.assertEqual(judgement.window_start, start)
        self.assertEqual(judgement.window_end, end)


class TickTests(unittest.TestCase):
    def test_tick_aggregates_fires_and_missed(self):
        entries = collect_schedules(
            [("nightly", _triggers("0 2 * * *")),
             ("hourly", _triggers("0 * * * *")),
             ("weekly", _triggers("0 4 * * 0"))],
            "main", "main").entries
        tick = judge_tick(
            entries, datetime(2026, 1, 1, 0, 0),
            datetime(2026, 1, 1, 3, 0))
        self.assertEqual(tick.fires_count, 2)
        self.assertEqual(tick.missed_count, 2)
        self.assertIn("2 scheduled run(s) fire", tick.words)
        self.assertIn("2 firing(s) missed", tick.words)

    def test_tick_to_dict_is_json_safe_data(self):
        tick = judge_tick(
            [_entry()], datetime(2026, 1, 1, 0, 0),
            datetime(2026, 1, 3, 2, 0))
        data = tick_to_dict(tick)
        self.assertEqual(data["fires"], 1)
        self.assertEqual(data["missed"], 2)
        (entry,) = data["entries"]
        self.assertEqual(entry["workflow"], "nightly")
        self.assertEqual(entry["reason"], "due_with_missed")
        self.assertEqual(entry["fire_due"], "2026-01-03T02:00:00")
        self.assertEqual(
            entry["missed"],
            ["2026-01-01T02:00:00", "2026-01-02T02:00:00"])
        self.assertEqual(entry["drift_seconds"], 0)
        self.assertEqual(entry["next_due"], "2026-01-04T02:00:00")

    def test_tick_refuses_bad_shapes(self):
        self.assertEqual(_reason(
            judge_tick, "nightly",
            datetime(2026, 1, 1), datetime(2026, 1, 2)),
            "schedule_entry_invalid")
        self.assertEqual(_reason(
            judge_tick, [],
            datetime(2026, 1, 2), datetime(2026, 1, 1)),
            "schedule_window_invalid")

    def test_document_integration(self):
        triggers = parse_triggers({
            "push": None,
            "schedule": [{"cron": "15 3 * * *"}]})
        collection = collect_schedules(
            [("backup", triggers)], "main", "main")
        self.assertEqual(len(collection.entries), 1)
        tick = judge_tick(
            collection.entries, datetime(2026, 3, 1, 0, 0),
            datetime(2026, 3, 1, 3, 15))
        self.assertEqual(tick.fires_count, 1)


class AuditAndPageTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def test_pins_hold(self):
        self.assertEqual(schema_version(self.conn), 136)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 92)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    def test_audit_clean_on_live_instance(self):
        audit = audit_workflow_schedules(self.conn)
        self.assertTrue(audit.source_ok)
        self.assertTrue(audit.stands_cleanly, audit)
        self.assertEqual(audit.events_scanned, 138)
        self.assertGreater(audit.tables_scanned, 0)

    def test_audit_catches_planted_table(self):
        self.conn.execute(
            "CREATE TABLE workflow_schedules (id INTEGER)")
        audit = audit_workflow_schedules(self.conn)
        self.assertFalse(audit.stands_cleanly)
        self.assertIn(
            "workflow_schedules", audit.offending_tables)
        self.conn.execute("DROP TABLE workflow_schedules")
        self.conn.execute(
            "CREATE TABLE runs (missed_run TEXT)")
        audit = audit_workflow_schedules(self.conn)
        self.assertFalse(audit.stands_cleanly)
        self.assertIn("runs.missed_run", audit.offending_columns)

    def test_page_says_the_law_in_words(self):
        audit = audit_workflow_schedules(self.conn)
        page = render_workflow_schedules_page(audit=audit)
        self.assertIn("default branch only", page)
        self.assertIn("drift", page)
        self.assertIn("skipped, not", page)
        self.assertIn("stands cleanly", page)
        self.assertNotIn("<script", page)

    def test_page_escapes_collection_words(self):
        collection = collect_schedules(
            [("<script>x", _triggers("0 2 * * *"))],
            "feature", "main")
        page = render_workflow_schedules_page(
            collection=collection)
        self.assertNotIn("<script>x", page)
        self.assertIn("&lt;script&gt;x", page)


if __name__ == "__main__":
    unittest.main()
