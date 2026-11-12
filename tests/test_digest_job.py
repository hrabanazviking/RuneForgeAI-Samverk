"""S-235 acceptance battery: digest job.

Acceptance (roadmap S-235): a weekly optional
digest composed from the event store; generation
is off the request path. The opt-in is S-228's
weekly cadence, read live; the content is S-221's
canonical events -- the recipient's own actions
and actions on repositories they watch in a
counted S-222 mode -- judged visible to the
recipient at compose time (S-209's rule); the
job composes the last completed week exactly
once per person (migration 94's UNIQUE), records
empty weeks honestly, and delivers over an
optional mailer seam in S-227's shape.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.digest_job import (
    DIGEST_EVENT_LIMIT, DIGEST_SCOPES, WEEK_SECONDS, DigestError,
    DigestJobStore, WeeklyDigest, compose_digest_letter,
    event_relevant, last_completed_week, main, render_digest,
    render_digest_page, render_digests_page, week_window)
from samverk.event_store import CanonicalEvent, EventStore
from samverk.issues import IssueStore
from samverk.notification_preferences import NotificationPreferencesStore
from samverk.repositories import RepositoryStore
from samverk.watch_star import WatchStarStore

NOW = 1_700_000_000
WEEK_START, WEEK_END = week_window(NOW)


class Clock:
    def __init__(self, now=NOW):
        self.now = now
    def __call__(self):
        return self.now


def fake_event(*, actor_id=9, verb="repo.issue.create",
               target_id="volmarr/vpub#1", target_kind="repo"):
    return CanonicalEvent(
        id=1, audit_seq=1, actor_kind="user", actor_id=actor_id,
        actor="tess", verb=verb, target_kind=target_kind,
        target_id=target_id, refs=(), detail={}, outcome="success",
        created_at=NOW)


class DigestJobTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock(WEEK_START - 1000)  # before the test week
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.yrsa = self.accounts.register("yrsa", "correct horse battery")
        self.tess = self.accounts.register("tess", "correct horse battery")
        self.mallory = self.accounts.register("mallory", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit)
        self.ws = WatchStarStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)
        self.prefs = NotificationPreferencesStore(self.conn, self.accounts, self.repos, self.ws, time_fn=self.clock)
        self.events = EventStore(self.conn, self.repos, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "vpub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "vpriv", visibility="private")
        self.repos.create_repository(self.tess.id, "tess", "tpub", visibility="public")
        # Standing choices, all recorded before the test week.
        self.prefs.set_digest_cadence(self.yrsa, "weekly")
        self.prefs.set_digest_cadence(self.tess, "daily")
        self.ws.set_watch(self.yrsa, "volmarr", "vpub", "all")
        self.ws.set_watch(self.yrsa, "tess", "tpub", "releases_only")
        self.clock.now = NOW  # inside the test week from here

    def _store(self, mailer=None):
        return DigestJobStore(self.conn, self.accounts, self.repos,
                              self.events, self.prefs, mailer=mailer,
                              time_fn=self.clock)

    def _set_email(self, user, address):
        with self.conn:
            self.conn.execute("UPDATE users SET email = ? WHERE id = ?",
                              (address, user.id))
        return self.accounts.get_by_id(user.id)

    def _week_activity(self):
        # tess acts in the repository yrsa watches (all) and in
        # the one she watches releases-only; yrsa acts herself.
        self.issues.create_issue(self.tess, "volmarr", "vpub", "Crash on startup")
        self.issues.create_issue(self.tess, "tess", "tpub", "Tess notes")
        self.ws.star(self.yrsa, "tess", "tpub")

    # -- pins -------------------------------------------------
    def test_pins_schema_99_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 116)
        self.assertEqual(db.MIGRATIONS[-1][0], 116)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 88)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name = 'weekly_digests'").fetchone()
        self.assertIsNotNone(row)

    def test_generation_is_off_the_request_path(self):
        server = (Path(__file__).resolve().parent.parent
                  / "samverk" / "server.py").read_text()
        self.assertNotIn("digest_job", server)
        self.assertNotIn("weekly_digests", server)
        self.assertEqual(main([]), 2)

    # -- the week, purely --------------------------------------
    def test_week_window_is_monday_to_monday_utc(self):
        start, end = week_window(NOW)
        self.assertEqual(end - start, WEEK_SECONDS)
        self.assertLessEqual(start, NOW)
        self.assertLess(NOW, end)
        self.assertEqual(time.gmtime(start).tm_wday, 0)
        self.assertEqual(start % 86400, 0)

    def test_last_completed_week_ends_where_this_week_starts(self):
        start, end = last_completed_week(NOW)
        self.assertEqual(end, WEEK_START)
        self.assertEqual(end - start, WEEK_SECONDS)

    # -- relevance, purely --------------------------------------
    def test_relevance_own_actions_always(self):
        event = fake_event(actor_id=9, target_id=None, target_kind="account")
        self.assertTrue(event_relevant(event, recipient_id=9, watch_modes={}))

    def test_relevance_watched_all_carries_everything(self):
        self.assertTrue(event_relevant(
            fake_event(actor_id=3), recipient_id=9,
            watch_modes={"volmarr/vpub": "all"}))

    def test_relevance_releases_only_carries_releases_only(self):
        modes = {"volmarr/vpub": "releases_only"}
        self.assertFalse(event_relevant(
            fake_event(actor_id=3, verb="repo.issue.create"),
            recipient_id=9, watch_modes=modes))
        self.assertTrue(event_relevant(
            fake_event(actor_id=3, verb="repo.release.publish"),
            recipient_id=9, watch_modes=modes))

    def test_relevance_unwatched_and_ignored_carry_nothing(self):
        self.assertFalse(event_relevant(
            fake_event(actor_id=3), recipient_id=9, watch_modes={}))
        self.assertFalse(event_relevant(
            fake_event(actor_id=3), recipient_id=9,
            watch_modes={"volmarr/vpub": "ignore"}))

    def test_relevance_others_non_repo_events_are_not_yours(self):
        event = fake_event(actor_id=3, target_id=None, target_kind="account")
        self.assertFalse(event_relevant(event, recipient_id=9, watch_modes={}))

    # -- the letter, purely --------------------------------------
    def test_letter_says_count_scope_and_each_event(self):
        events = [fake_event(actor_id=3),
                  fake_event(actor_id=9, verb="repo.star",
                             target_id="tess/tpub")]
        subject, body = compose_digest_letter("yrsa", WEEK_START, WEEK_END, events)
        self.assertIn("2 events", subject)
        self.assertIn("2 events", body)
        self.assertIn(DIGEST_SCOPES, body)
        self.assertIn("repo.issue.create", body)
        self.assertIn("volmarr/vpub#1", body)
        self.assertIn("repo.star", body)
        self.assertLess(body.index("repo.issue.create"), body.index("repo.star"))

    def test_letter_singular_and_truncation_words(self):
        subject, _ = compose_digest_letter(
            "yrsa", WEEK_START, WEEK_END, [fake_event(actor_id=9)])
        self.assertIn("1 event,", subject)
        _, body = compose_digest_letter(
            "yrsa", WEEK_START, WEEK_END, [fake_event(actor_id=9)], total=7)
        self.assertIn("first 1 of 7 events", body)

    # -- eligibility ---------------------------------------------
    def test_eligibility_is_the_weekly_choice_only(self):
        store = self._store()
        names = [u.username for u in store.eligible_users()]
        self.assertEqual(names, ["yrsa"])

    # -- composition ------------------------------------------------
    def test_compose_gathers_watched_and_own_only(self):
        self._week_activity()
        store = self._store()
        digest, created = store.compose_for(self.yrsa, WEEK_START, WEEK_END)
        self.assertTrue(created)
        self.assertEqual(digest.status, "composed")
        self.assertEqual(digest.event_count, 2)
        self.assertIn("repo.issue.create", digest.body)
        self.assertIn("volmarr/vpub#1", digest.body)
        self.assertIn("repo.star", digest.body)
        self.assertNotIn("tess/tpub#1", digest.body)
        self.assertEqual(digest.username, "yrsa")
        self.assertIn("2 events", digest.subject)

    def test_compose_is_exactly_once(self):
        self._week_activity()
        store = self._store()
        first, created_first = store.compose_for(self.yrsa, WEEK_START, WEEK_END)
        second, created_second = store.compose_for(self.yrsa, WEEK_START, WEEK_END)
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.body, second.body)
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM weekly_digests").fetchone()
        self.assertEqual(int(rows["n"]), 1)

    def test_compose_rejects_a_non_week_window(self):
        store = self._store()
        with self.assertRaises(DigestError) as ctx:
            store.compose_for(self.yrsa, WEEK_START, WEEK_END - 60)
        self.assertEqual(ctx.exception.reason, "week_invalid")

    def test_empty_week_is_recorded_empty_and_never_sent(self):
        sent = []
        store = self._store(mailer=lambda a, s, b: sent.append(a))
        digest, created = store.compose_for(self.mallory, WEEK_START, WEEK_END)
        self.assertTrue(created)
        self.assertEqual(digest.status, "empty")
        self.assertEqual(digest.event_count, 0)
        self.assertFalse(store.send_digest(self.mallory, digest.id))
        self.assertEqual(sent, [])

    def test_window_bounds_are_exclusive(self):
        # yrsa's standing choices were recorded before the week;
        # nothing of hers from before the week is in the digest.
        self._week_activity()
        store = self._store()
        digest, _ = store.compose_for(self.yrsa, WEEK_START, WEEK_END)
        self.assertNotIn("repo.watch", digest.body)
        self.assertNotIn("account", digest.body)

    def test_private_activity_never_leaks(self):
        # The owner's private repository is busy in the week;
        # yrsa neither acts there nor watches it, and mallory's
        # digest of the same week is empty of it entirely.
        self.issues.create_issue(self.owner, "volmarr", "vpriv", "Secret plans")
        store = self._store()
        digest, _ = store.compose_for(self.yrsa, WEEK_START, WEEK_END)
        self.assertNotIn("vpriv", digest.body)
        other, _ = store.compose_for(self.mallory, WEEK_START, WEEK_END)
        self.assertEqual(other.status, "empty")
        self.assertNotIn("Secret", other.body)

    def test_unreadable_after_flip_drops_watched_events(self):
        # Watched while public; private by compose time: S-209's
        # rule judges at compose time, so nothing is carried.
        self.issues.create_issue(self.tess, "volmarr", "vpub", "Crash on startup")
        self.repos.update_metadata(self.owner.id, "volmarr", "vpub",
                                    visibility="private")
        store = self._store()
        digest, _ = store.compose_for(self.yrsa, WEEK_START, WEEK_END)
        self.assertNotIn("vpub", digest.body)
        self.assertEqual(digest.event_count, 0)
        self.assertEqual(digest.status, "empty")

    # -- the job ------------------------------------------------------
    def test_run_weekly_composes_for_eligible_only(self):
        self._week_activity()
        store = self._store()
        run = store.run_weekly(WEEK_END + 3600)
        self.assertEqual(run.week_start, WEEK_START)
        self.assertEqual(run.eligible, 1)
        self.assertEqual(run.composed, 1)
        self.assertEqual(run.empty, 0)
        self.assertEqual(run.sent, 0)  # no mailer configured
        digest = store.digest_for_week(self.yrsa, WEEK_START)
        self.assertIsNotNone(digest)
        self.assertEqual(digest.status, "composed")
        self.assertIsNone(store.digest_for_week(self.tess, WEEK_START))

    def test_run_weekly_second_run_composes_nothing_twice(self):
        self._week_activity()
        store = self._store()
        first = store.run_weekly(WEEK_END + 3600)
        second = store.run_weekly(WEEK_END + 7200)
        self.assertEqual(first.composed, 1)
        self.assertEqual(second.composed, 0)
        self.assertEqual(second.existing, 1)

    def test_run_weekly_records_empty_weeks(self):
        store = self._store()
        run = store.run_weekly(WEEK_END + 3600)
        self.assertEqual(run.eligible, 1)
        self.assertEqual(run.empty, 1)
        self.assertEqual(run.composed, 0)

    # -- delivery ------------------------------------------------------
    def test_run_with_mailer_sends_once_to_the_recipient(self):
        self._week_activity()
        yrsa = self._set_email(self.yrsa, "yrsa@example.org")
        sent = []
        store = self._store(mailer=lambda a, s, b: sent.append((a, s, b)))
        run = store.run_weekly(WEEK_END + 3600)
        self.assertEqual(run.sent, 1)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "yrsa@example.org")
        digest = store.digest_for_week(yrsa, WEEK_START)
        self.assertEqual(digest.status, "sent")
        self.assertIsNotNone(digest.sent_at)
        self.assertEqual(sent[0][1], digest.subject)
        self.assertEqual(sent[0][2], digest.body)
        again = store.run_weekly(WEEK_END + 7200)
        self.assertEqual(again.sent, 0)
        self.assertEqual(len(sent), 1)

    def test_no_address_stands_composed(self):
        self._week_activity()
        sent = []
        store = self._store(mailer=lambda a, s, b: sent.append(a))
        run = store.run_weekly(WEEK_END + 3600)
        self.assertEqual(run.composed, 1)
        self.assertEqual(run.sent, 0)
        self.assertEqual(sent, [])

    def test_transport_failure_stands_composed_and_retries(self):
        self._week_activity()
        yrsa = self._set_email(self.yrsa, "yrsa@example.org")

        def boom(address, subject, body):
            raise RuntimeError("smtp down")

        failing = self._store(mailer=boom)
        run = failing.run_weekly(WEEK_END + 3600)
        self.assertEqual(run.sent, 0)
        digest = failing.digest_for_week(yrsa, WEEK_START)
        self.assertEqual(digest.status, "composed")
        sent = []
        working = self._store(mailer=lambda a, s, b: sent.append(a))
        self.assertTrue(working.send_digest(yrsa, digest.id))
        self.assertEqual(sent, ["yrsa@example.org"])
        self.assertFalse(working.send_digest(yrsa, digest.id))
        self.assertEqual(len(sent), 1)
        self.assertEqual(working.get_digest(yrsa, digest.id).status, "sent")

    # -- ownership of reads ---------------------------------------------
    def test_reads_belong_to_the_recipient(self):
        self._week_activity()
        store = self._store()
        digest, _ = store.compose_for(self.yrsa, WEEK_START, WEEK_END)
        self.assertEqual(store.get_digest(self.yrsa, digest.id).id, digest.id)
        with self.assertRaises(DigestError) as ctx:
            store.get_digest(self.tess, digest.id)
        self.assertEqual(ctx.exception.reason, "digest_not_found")
        with self.assertRaises(DigestError) as ctx:
            store.get_digest(self.yrsa, 999999)
        self.assertEqual(ctx.exception.reason, "digest_not_found")
        with self.assertRaises(DigestError) as ctx:
            store.digests_for(None)
        self.assertEqual(ctx.exception.reason, "authentication_required")
        self.assertEqual(store.digests_for(self.tess), [])
        self.assertEqual(len(store.digests_for(self.yrsa)), 1)
        self.assertIsNone(store.digest_for_week(self.tess, WEEK_START))

    # -- renders ----------------------------------------------------------
    def test_render_pages_say_standing_and_teach(self):
        store = self._store()
        page = render_digests_page(store.digests_for(self.yrsa))
        self.assertIn("No weekly digests yet", page)
        self.assertIn("optional", page)
        self.assertIn("never while", page)
        self._week_activity()
        digest, _ = store.compose_for(self.yrsa, WEEK_START, WEEK_END)
        listing = render_digests_page(store.digests_for(self.yrsa))
        self.assertIn("Weekly digest for yrsa", listing)
        self.assertIn("composed, not yet sent", listing)
        one = render_digest_page(digest)
        self.assertIn(digest.subject, one)
        self.assertIn(DIGEST_SCOPES, one)
        self.assertIn("repo.issue.create", one)

    def test_render_escapes_user_text(self):
        digest = WeeklyDigest(
            id=1, user_id=1, username="<b>yrsa</b>",
            week_start=WEEK_START, week_end=WEEK_END,
            status="composed", event_ids=(1,), subject="<script>x</script>",
            body="body", created_at=NOW, sent_at=None)
        html = render_digest(digest)
        self.assertNotIn("<b>yrsa</b>", html)
        self.assertIn("&lt;b&gt;", html)
        page = render_digest_page(digest)
        self.assertNotIn("<script>x</script>", page)


if __name__ == "__main__":
    unittest.main()
