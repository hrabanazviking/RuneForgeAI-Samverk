"""S-300 acceptance battery: advisory refresh.

Acceptance (roadmap S-300): Advisory refresh --
the snapshot updates by operator action or
scheduled fetch where the instance has network;
offline instances show staleness honestly.

The refresh road lives in samverk/advisory_refresh.py
over migration 122's advisory_snapshot_state and
advisory_refreshes (schema 121 -> 122 on the banked
line; the suite's standing schema pins moved
in-slice). One path serves both triggers; every
candidate is validated by S-298's parse_snapshot
itself before it may replace anything, so a bad
refresh changes nothing and is refused by the
validator's own name. The fetch is an injected
seam -- this battery runs wholly offline, with
fetchers that answer, fail, and are absent (the
offline instance) -- and no landed, refused or
failed attempt ever moves the standing snapshot's
date, so S-298's age law reads stale as stale.
Every attempt stands on the provenance record.
No new taxonomy event -- 134 stand (33 auth /
88 repo / 13 admin); the battery proves the audit
log does not move.

Counted with: python3 -m unittest tests.test_advisory_refresh
"""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.advisory_data import (
    FRESHNESS_CURRENT, FRESHNESS_STALE, AdvisoryStore)
from samverk.advisory_refresh import (
    ACTOR_REQUIRED, FETCH_FAILED, FETCH_UNAVAILABLE,
    RESULT_FAILED, RESULT_REFRESHED, RESULT_REFUSED,
    RESULT_UNCHANGED, SCHEDULED_ACTOR,
    SNAPSHOT_OLDER_THAN_STANDING, TRIGGER_INVALID,
    TRIGGER_OPERATOR, TRIGGER_SCHEDULED,
    AdvisoryRefreshError, AdvisoryRefreshStore,
    judge_refresh, make_url_fetcher, render_refresh_page)
from samverk.audit import AuditLog
from samverk.db import schema_version

TODAY = date(2026, 11, 12)
BUNDLED_DATE = date(2026, 11, 12)
T0 = 1_700_000_000


def snap_text(snapshot_date, adv_id="CVE-3000-0001",
              package="Example_Pkg"):
    return json.dumps({
        "snapshot_format": 1,
        "source": "S-300 battery snapshot",
        "snapshot_date": snapshot_date,
        "advisories": [{
            "id": adv_id, "ecosystem": "python",
            "package": package, "severity": "high",
            "affected": "<2.0", "fixed_version": "2.0",
            "summary": "a refreshed test advisory",
            "published": "2026-01-01", "references": [],
        }],
    })


NEWER = snap_text("2026-11-18", adv_id="CVE-3000-0002",
                  package="Refreshed_Pkg")


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "t.db")
        self.clock = Clock()
        self.store = AdvisoryRefreshStore(
            self.conn, time_fn=self.clock)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()


class StandingTests(StoreCase):
    def test_bundled_stands_before_any_refresh(self):
        info = self.store.snapshot_info(TODAY)
        self.assertEqual(info.snapshot_date, BUNDLED_DATE)
        self.assertEqual(info.freshness, FRESHNESS_CURRENT)
        store = self.store.current_store(TODAY)
        self.assertIsInstance(store, AdvisoryStore)
        self.assertTrue(store.all_advisories())
        self.assertIsNone(self.store.latest())
        self.assertEqual(self.store.history(), ())

    def test_standing_age_is_honest_as_days_pass(self):
        later = TODAY + timedelta(days=45)
        info = self.store.snapshot_info(later)
        self.assertEqual(info.age_days, 45)
        self.assertEqual(info.freshness, FRESHNESS_STALE)
        self.assertIn("stale", info.age_words)


class PureLawTests(unittest.TestCase):
    def test_judge_refresh(self):
        old = date(2026, 11, 12)
        self.assertEqual(
            judge_refresh(old, date(2026, 11, 13)),
            ("replace", ""))
        self.assertEqual(judge_refresh(old, old),
                         ("unchanged", ""))
        action, reason = judge_refresh(
            old, date(2026, 11, 1))
        self.assertEqual(action, "backwards")
        self.assertEqual(reason, SNAPSHOT_OLDER_THAN_STANDING)

    def test_url_fetcher_is_lazy(self):
        fetcher = make_url_fetcher(
            "https://example.invalid/snapshot.json")
        self.assertTrue(callable(fetcher))


class OperatorRefreshTests(StoreCase):
    def test_operator_refresh_replaces_and_updates_age(self):
        rec = self.store.refresh_by_operator(
            "volmarr", raw=NEWER, now=date(2026, 11, 20))
        self.assertEqual(rec.result, RESULT_REFRESHED)
        self.assertEqual(rec.trigger, TRIGGER_OPERATOR)
        self.assertEqual(rec.actor, "volmarr")
        self.assertEqual(rec.old_snapshot_date, "2026-11-12")
        self.assertEqual(rec.new_snapshot_date, "2026-11-18")
        self.assertTrue(rec.landed)
        self.assertIsNotNone(rec.id)
        info = self.store.snapshot_info(date(2026, 11, 20))
        self.assertEqual(info.snapshot_date, date(2026, 11, 18))
        self.assertEqual(info.age_days, 2)
        self.assertEqual(info.freshness, FRESHNESS_CURRENT)
        current = self.store.current_store(date(2026, 11, 20))
        self.assertEqual(current.all_advisories()[0].id,
                         "CVE-3000-0002")
        self.assertTrue(
            current.for_package("python", "refreshed-pkg"))

    def test_refresh_persists_across_store_instances(self):
        self.store.refresh_by_operator(
            "volmarr", raw=NEWER, now=date(2026, 11, 20))
        again = AdvisoryRefreshStore(
            self.conn, time_fn=self.clock)
        self.assertEqual(
            again.snapshot_info(date(2026, 11, 20)).snapshot_date,
            date(2026, 11, 18))
        self.assertEqual(len(again.history()), 1)

    def test_second_refresh_moves_from_refreshed_date(self):
        self.store.refresh_by_operator(
            "volmarr", raw=NEWER, now=date(2026, 11, 20))
        newest = snap_text("2026-11-25",
                           adv_id="CVE-3000-0003")
        rec = self.store.refresh_by_operator(
            "yrsa", raw=newest, now=date(2026, 11, 26))
        self.assertEqual(rec.old_snapshot_date, "2026-11-18")
        self.assertEqual(rec.new_snapshot_date, "2026-11-25")
        self.assertEqual(
            [r.result for r in self.store.history()],
            [RESULT_REFRESHED, RESULT_REFRESHED])
        self.assertEqual(self.store.latest().id, rec.id)


class RefusalTests(StoreCase):
    def test_future_snapshot_refused_by_name_nothing_changed(self):
        future = snap_text("2026-12-01")
        rec = self.store.refresh_by_operator(
            "volmarr", raw=future, now=TODAY)
        self.assertEqual(rec.result, RESULT_REFUSED)
        self.assertEqual(rec.reason, "snapshot_date_in_future")
        self.assertEqual(
            self.store.snapshot_info(TODAY).snapshot_date,
            BUNDLED_DATE)
        row = self.conn.execute(
            "SELECT COUNT(*) FROM advisory_snapshot_state"
        ).fetchone()[0]
        self.assertEqual(row, 0)
        self.assertEqual(self.store.latest().reason,
                         "snapshot_date_in_future")

    def test_malformed_snapshot_refused_by_name(self):
        rec = self.store.refresh_by_operator(
            "volmarr", raw="{not json", now=TODAY)
        self.assertEqual(rec.result, RESULT_REFUSED)
        self.assertEqual(rec.reason, "snapshot_malformed")
        self.assertEqual(
            self.store.snapshot_info(TODAY).snapshot_date,
            BUNDLED_DATE)

    def test_empty_snapshot_refused_by_name(self):
        empty = json.dumps({
            "snapshot_format": 1, "source": "x",
            "snapshot_date": "2026-11-19", "advisories": []})
        rec = self.store.refresh_by_operator(
            "volmarr", raw=empty, now=date(2026, 11, 20))
        self.assertEqual(rec.result, RESULT_REFUSED)
        self.assertEqual(rec.reason, "snapshot_empty")

    def test_older_snapshot_refused_by_name(self):
        older = snap_text("2026-11-01")
        rec = self.store.refresh_by_operator(
            "volmarr", raw=older, now=TODAY)
        self.assertEqual(rec.result, RESULT_REFUSED)
        self.assertEqual(rec.reason,
                         SNAPSHOT_OLDER_THAN_STANDING)
        self.assertEqual(rec.new_snapshot_date, "2026-11-01")
        self.assertEqual(
            self.store.snapshot_info(TODAY).snapshot_date,
            BUNDLED_DATE)

    def test_same_day_snapshot_is_unchanged(self):
        same = snap_text("2026-11-12",
                         adv_id="CVE-3000-0099")
        rec = self.store.refresh_by_operator(
            "volmarr", raw=same, now=TODAY)
        self.assertEqual(rec.result, RESULT_UNCHANGED)
        self.assertEqual(
            self.store.snapshot_info(TODAY).snapshot_date,
            BUNDLED_DATE)
        # The bundled advisories still stand: an
        # unchanged refresh replaces nothing.
        ids = [a.id for a in
               self.store.current_store(TODAY).all_advisories()]
        self.assertNotIn("CVE-3000-0099", ids)

    def test_refusal_after_landing_keeps_landed_snapshot(self):
        self.store.refresh_by_operator(
            "volmarr", raw=NEWER, now=date(2026, 11, 20))
        rec = self.store.refresh_by_operator(
            "volmarr", raw="{broken",
            now=date(2026, 11, 21))
        self.assertEqual(rec.result, RESULT_REFUSED)
        self.assertEqual(rec.old_snapshot_date, "2026-11-18")
        self.assertEqual(
            self.store.snapshot_info(
                date(2026, 11, 21)).snapshot_date,
            date(2026, 11, 18))


class FetchRoadTests(StoreCase):
    def test_fetcher_success_uses_same_path(self):
        rec = self.store.refresh_by_operator(
            "volmarr", fetcher=lambda: NEWER,
            now=date(2026, 11, 20))
        self.assertEqual(rec.result, RESULT_REFRESHED)
        self.assertEqual(rec.new_snapshot_date, "2026-11-18")

    def test_fetch_failure_leaves_snapshot_and_honest_staleness(self):
        def boom():
            raise RuntimeError("network unreachable")
        rec = self.store.refresh_by_operator(
            "volmarr", fetcher=boom, now=TODAY)
        self.assertEqual(rec.result, RESULT_FAILED)
        self.assertEqual(rec.reason, FETCH_FAILED)
        self.assertIn("network unreachable", rec.detail)
        later = TODAY + timedelta(days=45)
        info = self.store.snapshot_info(later)
        self.assertEqual(info.snapshot_date, BUNDLED_DATE)
        self.assertEqual(info.freshness, FRESHNESS_STALE)
        self.assertIn("stale", info.age_words)

    def test_offline_no_fetcher_is_honest_failure(self):
        rec = self.store.refresh_by_operator(
            "volmarr", now=TODAY)
        self.assertEqual(rec.result, RESULT_FAILED)
        self.assertEqual(rec.reason, FETCH_UNAVAILABLE)
        self.assertEqual(
            self.store.snapshot_info(TODAY).snapshot_date,
            BUNDLED_DATE)
        self.assertEqual(len(self.store.history()), 1)

    def test_fetcher_returning_nothing_is_unavailable(self):
        rec = self.store.refresh_scheduled(
            fetcher=lambda: None, now=TODAY)
        self.assertEqual(rec.result, RESULT_FAILED)
        self.assertEqual(rec.reason, FETCH_UNAVAILABLE)


class ScheduledTests(StoreCase):
    def test_scheduled_trigger_uses_the_same_path(self):
        rec = self.store.refresh_scheduled(
            fetcher=lambda: NEWER, now=date(2026, 11, 20))
        self.assertEqual(rec.trigger, TRIGGER_SCHEDULED)
        self.assertEqual(rec.actor, SCHEDULED_ACTOR)
        self.assertEqual(rec.result, RESULT_REFRESHED)
        self.assertEqual(
            self.store.snapshot_info(
                date(2026, 11, 20)).snapshot_date,
            date(2026, 11, 18))

    def test_scheduled_offline_records_and_stays_stale(self):
        rec = self.store.refresh_scheduled(now=TODAY)
        self.assertEqual(rec.result, RESULT_FAILED)
        self.assertEqual(rec.reason, FETCH_UNAVAILABLE)
        page = render_refresh_page(
            self.store, TODAY + timedelta(days=45))
        self.assertIn("stale", page)
        self.assertIn("fetch_unavailable", page)


class ProvenanceTests(StoreCase):
    def test_provenance_records_every_attempt_in_order(self):
        self.store.refresh_by_operator(
            "volmarr", raw="{broken", now=TODAY)
        self.store.refresh_by_operator(
            "volmarr", now=TODAY)
        self.store.refresh_by_operator(
            "yrsa", raw=NEWER, now=date(2026, 11, 20))
        history = self.store.history()
        self.assertEqual(
            [r.result for r in history],
            [RESULT_REFUSED, RESULT_FAILED, RESULT_REFRESHED])
        self.assertEqual(
            [r.actor for r in history],
            ["volmarr", "volmarr", "yrsa"])
        self.assertTrue(all(
            r.created_at == T0 for r in history))
        self.assertTrue(all(
            r.old_snapshot_date == "2026-11-12"
            for r in history))
        landed = history[-1]
        self.assertEqual(landed.advisory_count, 1)
        self.assertEqual(landed.new_snapshot_date,
                         "2026-11-18")
        self.assertIn("refreshed", landed.words())
        self.assertEqual(landed.to_dict()["trigger"],
                         TRIGGER_OPERATOR)

    def test_caller_faults_raise_by_name_and_record_nothing(self):
        with self.assertRaises(AdvisoryRefreshError) as ctx:
            self.store.refresh(trigger="cron fairies",
                               actor="volmarr", raw=NEWER,
                               now=TODAY)
        self.assertEqual(ctx.exception.reason, TRIGGER_INVALID)
        with self.assertRaises(AdvisoryRefreshError) as ctx:
            self.store.refresh_by_operator(
                "  ", raw=NEWER, now=TODAY)
        self.assertEqual(ctx.exception.reason, ACTOR_REQUIRED)
        self.assertEqual(self.store.history(), ())


class RenderTests(StoreCase):
    def test_page_shows_standing_age_and_history(self):
        self.store.refresh_by_operator(
            "volmarr", raw=NEWER, now=date(2026, 11, 20))
        page = render_refresh_page(
            self.store, date(2026, 11, 20))
        self.assertIn("2026-11-18", page)
        self.assertIn("2 days old", page)
        self.assertIn("operator", page)
        self.assertIn("volmarr", page)
        self.assertIn("refreshed", page)

    def test_page_escapes_actor_and_detail(self):
        self.store.refresh_by_operator(
            "<script>alert(1)</script>", now=TODAY)
        page = render_refresh_page(self.store, TODAY)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)


class InvariantTests(StoreCase):
    def test_migration_122_stands(self):
        self.assertEqual(schema_version(self.conn), 125)
        self.assertEqual(db.MIGRATIONS[-1][0], 125)

    def test_no_new_taxonomy_event(self):
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    def test_audit_log_does_not_move(self):
        accounts = AccountStore(self.conn)
        acct = accounts.register("aud2", "password-12345")
        self.assertIsNotNone(acct)
        log = AuditLog(self.conn)
        self.assertIsNotNone(log)
        before = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log").fetchone()[0]
        self.store.refresh_by_operator(
            "volmarr", raw=NEWER, now=date(2026, 11, 20))
        self.store.refresh_by_operator(
            "volmarr", raw="{broken", now=date(2026, 11, 20))
        self.store.refresh_scheduled(now=date(2026, 11, 20))
        after = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log").fetchone()[0]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
