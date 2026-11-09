"""S-236 — PART XI GATE battery: notifications, assembled.

The whole Part XI system struck at once, in the house
gate shape of S-096/S-120/S-140/S-168/S-184/S-204/S-220
— no new production code, only the battery that walks
the landed S-221..S-235 machinery end to end through
its public seams, at the two things the gate names:

- **Every reason x every subscription state** — S-223's
  seven reasons (mention, assign, review-requested,
  author, comment, state-change, subscribed) crossed
  with the full subscription lattice: S-225's thread
  override (inherit / subscribed / muted) over S-222's
  repository watch (none / all / releases_only /
  ignore) — twelve standings, judged pure through
  `decide_notify`/`effective_decision`, judged stored
  through `ThreadSubscriptionStore.effective_for`, and
  judged delivered through the gate's own fan-out law
  (a standing that notifies delivers exactly its
  reason; the `subscribed` override delivers reason
  `subscribed`). Every reason is then stored, listed,
  filtered and counted through S-223/S-224, carried by
  email under S-227/S-228's composed law (per-reason
  and master switches x immediate/daily/weekly
  cadences), and shown with its reason in plain words.
- **Exactly-once delivery, proven at every seam that
  can duplicate** — mention routing re-synced (S-226:
  one source, one notification per recipient, however
  many mention paths reach them; muted threads skip;
  private threads never leak to non-readers), email
  delivery re-run (S-227: one ledger row, one letter;
  digest flush sends once), the weekly digest job
  re-run (S-235: one standing digest per person per
  week), the event store re-synced (S-221), and the
  idempotent retries of watch/star/follow/triage.
- **The privacy faces agree** — one private-repository
  action is invisible, identically, in S-229's feeds,
  S-230's profile activity, S-231's events API and
  S-232's following feed, while remaining visible to
  its owner; S-233's star lists and S-234's push feed
  keep the same law on their own surfaces.

The gate claimed no migration and no taxonomy event:
the assembled system stands at schema 95 with 131
audit events (33 auth / 83 repo / 13 admin), and the
battery proves both pins. The full-suite counted
recount at this gate is recorded in
PROJECT_MEMORY_MAP.md (the gate entry), read back
from its log file after the run finished.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.activity_feeds import ActivityFeedStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.digest_job import DigestJobStore, week_window
from samverk.email_notifications import (
    EmailNotificationStore, decide_email)
from samverk.event_store import EventStore
from samverk.events_api import EventsAPI
from samverk.following import FollowingStore
from samverk.hooks import RefUpdate
from samverk.inbox import InboxStore
from samverk.issues import IssueStore
from samverk.mention_routing import MentionRoutingStore
from samverk.notification_preferences import (
    NotificationPreferencesStore)
from samverk.notification_reasons import (
    NOTIFICATION_REASONS, NotificationError, NotificationStore,
    render_notifications)
from samverk.organizations import OrganizationStore
from samverk.organization_members import OrgMembershipStore
from samverk.profile_activity import ProfileActivityStore
from samverk.push_events import PushEventStore
from samverk.push_feed import PushFeedStore
from samverk.repositories import RepositoryStore
from samverk.star_lists import StarListStore
from samverk.teams import TeamStore
from samverk.thread_subscriptions import (
    ThreadSubscriptionStore, decide_notify, effective_decision)
from samverk.watch_star import WATCH_MODES, WatchStarStore
from test_git_http_upload import seed_commit

PW = "correct horse battery"
KEY = b"unit-test-signing-key"
NOW = 1_700_000_000
SEVEN = ("mention", "assign", "review-requested", "author",
         "comment", "state-change", "subscribed")
WATCHES = (None, "all", "releases_only", "ignore")
OVERRIDES = (None, "subscribed", "muted")
# The delivery table, stated once, in full: a thread
# override wins in both directions; with no override
# only the `all` watch notifies thread activity.
NOTIFY_TABLE = {
    (None, None): False, (None, "all"): True,
    (None, "releases_only"): False, (None, "ignore"): False,
    ("subscribed", None): True, ("subscribed", "all"): True,
    ("subscribed", "releases_only"): True,
    ("subscribed", "ignore"): True,
    ("muted", None): False, ("muted", "all"): False,
    ("muted", "releases_only"): False, ("muted", "ignore"): False,
}


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


class FakeMailer:
    def __init__(self):
        self.sent = []

    def __call__(self, address, subject, body):
        self.sent.append((address, subject, body))


class PartXIGateTests(unittest.TestCase):
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
        self.reader = self.accounts.register(
            "yrsa", PW, "yrsa@example.com")
        self.bryn = self.accounts.register(
            "brynhild", PW, "bryn@example.com")
        self.tess = self.accounts.register("tess", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.watch = WatchStarStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.threads = ThreadSubscriptionStore(
            self.conn, self.repos, self.accounts,
            watch_store=self.watch, issues=self.issues,
            time_fn=self.clock)
        self.notes = NotificationStore(
            self.conn, self.accounts, time_fn=self.clock)
        self.inbox = InboxStore(
            self.conn, self.accounts, time_fn=self.clock)
        self.mailer = FakeMailer()
        self.email = EmailNotificationStore(
            self.conn, self.accounts, self.notes,
            mailer=self.mailer, signing_key=KEY,
            time_fn=self.clock)
        self.prefs = NotificationPreferencesStore(
            self.conn, self.accounts, self.repos, self.watch,
            time_fn=self.clock)
        self.events = EventStore(
            self.conn, self.repos, self.accounts)
        self.feeds = ActivityFeedStore(
            self.conn, self.repos, self.accounts,
            events=self.events)
        self.profile = ProfileActivityStore(
            self.conn, self.repos, self.accounts,
            events=self.events)
        self.api = EventsAPI(
            self.conn, self.repos, self.accounts,
            events=self.events)
        self.follows = FollowingStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, events=self.events,
            time_fn=self.clock)
        self.stars = StarListStore(
            self.conn, self.repos, self.accounts)
        self.pushes = PushEventStore(
            self.conn, self.repos, time_fn=self.clock)
        self.push_feed = PushFeedStore(
            self.conn, self.repos, self.accounts, self.pushes)
        self.router = MentionRoutingStore(
            self.conn, self.accounts, self.audit,
            time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.issue = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Gate thread",
            "Opening the gate thread.")
        self.priv_issue = self.issues.create_issue(
            self.owner, "volmarr", "priv", "Secret thread",
            "Nothing to see here.")

    # -- helpers -------------------------------------------
    def _count(self, table):
        return self.conn.execute(
            f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]

    def _set_standing(self, user, watch_mode, override):
        if watch_mode is None:
            self.watch.clear_watch(user, "volmarr", "pub")
        else:
            self.watch.set_watch(user, "volmarr", "pub", watch_mode)
        if override is None:
            self.threads.clear_subscription(
                user, "volmarr", "pub", "issue", self.issue.number)
        else:
            self.threads.set_subscription(
                user, "volmarr", "pub", "issue",
                self.issue.number, override)

    def _fan_out(self, user, reason):
        """The gate's delivery law, composed from the
        landed seams exactly as a thread action composes
        them: the effective standing decides, and a
        standing subscription names its own reason."""
        decision = self.threads.effective_for(
            user, "volmarr", "pub", "issue", self.issue.number)
        if not decision.notify:
            return None
        return self.notes.notify(
            user, self.owner, decision.reason or reason,
            verb="repo.issue.comment", target_kind="repo",
            target_id=f"volmarr/pub#{self.issue.number}",
            detail={"repo": "volmarr/pub"})

    # -- pins ------------------------------------------------
    def test_pins_schema_95_taxonomy_131(self):
        self.assertEqual(schema_version(self.conn), 95)
        self.assertEqual(db.MIGRATIONS[-1][0], 95)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 85)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("events", "repo_watches", "repo_stars",
                      "notifications", "inbox_triage",
                      "thread_overrides", "mention_deliveries",
                      "email_deliveries", "email_optouts",
                      "notification_preferences", "weekly_digests"):
            self.assertIn(table, tables)

    def test_fresh_database_migrates_to_95(self):
        conn = db.connect(self.root / "fresh.db")
        self.addCleanup(conn.close)
        self.assertEqual(db.migrate(conn), 95)
        self.assertEqual(db.schema_version(conn), 95)

    # -- the vocabularies --------------------------------------
    def test_vocabularies_are_exact(self):
        self.assertEqual(tuple(NOTIFICATION_REASONS), SEVEN)
        self.assertEqual(tuple(WATCH_MODES),
                         ("all", "releases_only", "ignore"))

    # -- every subscription state, pure --------------------------
    def test_pure_matrix_all_twelve_standings(self):
        for (override, watch_mode), expected in NOTIFY_TABLE.items():
            self.assertEqual(
                decide_notify(override, watch_mode), expected,
                f"override={override} watch={watch_mode}")
            decision = effective_decision(override, watch_mode)
            self.assertEqual(decision.notify, expected)
            self.assertEqual(
                decision.reason,
                "subscribed" if override == "subscribed" else None)
            self.assertTrue(decision.explanation)

    # -- every subscription state, stored -------------------------
    def test_stored_matrix_matches_pure_law(self):
        for (override, watch_mode), expected in NOTIFY_TABLE.items():
            self._set_standing(self.reader, watch_mode, override)
            decision = self.threads.effective_for(
                self.reader, "volmarr", "pub", "issue",
                self.issue.number)
            self.assertEqual(decision.override, override)
            self.assertEqual(decision.watch_mode, watch_mode)
            self.assertEqual(
                decision.notify, expected,
                f"override={override} watch={watch_mode}")
            view = self.threads.get_subscription(
                self.reader, "volmarr", "pub", "issue",
                self.issue.number)
            self.assertIn(
                "repository watch", view.explanation)

    # -- every reason x every state, delivered ----------------------
    def test_every_reason_cross_every_state_delivery(self):
        delivered = 0
        for index, (override, watch_mode) in enumerate(
                sorted(NOTIFY_TABLE, key=str)):
            user = self.accounts.register(f"gate{index:02d}", PW)
            self._set_standing(user, watch_mode, override)
            for reason in SEVEN:
                note = self._fan_out(user, reason)
                if NOTIFY_TABLE[(override, watch_mode)]:
                    self.assertIsNotNone(
                        note, f"{reason} x {override}/{watch_mode}")
                    want = ("subscribed"
                            if override == "subscribed" else reason)
                    self.assertEqual(note.reason, want)
                    delivered += 1
                else:
                    self.assertIsNone(
                        note, f"{reason} x {override}/{watch_mode}")
        # Seven notify-true standings (1 inherited-all +
        # 4 subscribed + ... counted from the table itself)
        # times seven reasons each.
        true_standings = sum(1 for v in NOTIFY_TABLE.values() if v)
        self.assertEqual(true_standings, 5)
        self.assertEqual(delivered, true_standings * len(SEVEN))
        self.assertEqual(self._count("notifications"), delivered)

    # -- every reason, stored and shown ------------------------------
    def test_every_reason_stored_listed_filtered_counted(self):
        for reason in SEVEN:
            self.notes.notify(
                self.reader, self.owner, reason,
                verb="repo.issue.comment", target_kind="repo",
                target_id="volmarr/pub#1",
                detail={"repo": "volmarr/pub"})
        listed = self.notes.list_for_recipient(self.reader)
        self.assertEqual([n.reason for n in listed], list(SEVEN))
        for reason in SEVEN:
            self.assertIn(NOTIFICATION_REASONS[reason],
                          listed[SEVEN.index(reason)].words)
            only = self.inbox.list_inbox(self.reader, reason=reason)
            self.assertEqual([e.reason for e in only], [reason])
        counts = self.inbox.counts(self.reader)
        self.assertEqual(counts.unread, len(SEVEN))
        self.assertEqual(self.inbox.unread_count(self.reader),
                         len(SEVEN))
        self.assertEqual(
            self.inbox.list_inbox(
                self.reader, repo="volmarr/pub")[0].repo,
            "volmarr/pub")
        page = render_notifications(listed)
        for reason in SEVEN:
            self.assertIn(NOTIFICATION_REASONS[reason], page)

    def test_unknown_reason_refused_at_every_door(self):
        for bad in ("participating", "", None, "MENTION"):
            with self.assertRaises(NotificationError):
                self.notes.notify(self.reader, self.owner, bad)
        # A None filter is the list's own no-filter
        # spelling, not a reason; the refused set for
        # filtering is every other shapeless value.
        for bad in ("participating", "", "MENTION", 3):
            with self.assertRaises(NotificationError):
                self.notes.list_for_recipient(
                    self.reader, reason=bad)
        self.assertEqual(self._count("notifications"), 0)

    # -- triage and read state: exactly once ---------------------------
    def test_triage_and_read_transitions_are_idempotent(self):
        note = self.notes.notify(
            self.reader, self.owner, "comment",
            target_id="volmarr/pub#1", detail={"repo": "volmarr/pub"})
        self.assertTrue(self.notes.mark_read(self.reader, note.id))
        self.assertFalse(self.notes.mark_read(self.reader, note.id))
        self.inbox.set_saved(self.reader, note.id, True)
        self.inbox.set_saved(self.reader, note.id, True)
        self.assertEqual(self.inbox.counts(self.reader).saved, 1)
        self.inbox.mark_done(self.reader, note.id)
        self.inbox.mark_done(self.reader, note.id)
        counts = self.inbox.counts(self.reader)
        self.assertEqual((counts.done, counts.unread), (1, 0))
        self.assertEqual(self.inbox.list_inbox(self.reader), [])
        self.inbox.reopen(self.reader, note.id)
        self.assertEqual(len(self.inbox.list_inbox(self.reader)), 1)
        self.assertEqual(self._count("inbox_triage"), 1)

    def test_watch_star_follow_retries_store_once(self):
        self.watch.set_watch(self.reader, "volmarr", "pub", "all")
        audits = self._count("audit_log")
        self.watch.set_watch(self.reader, "volmarr", "pub", "all")
        self.assertEqual(self._count("audit_log"), audits)
        self.assertEqual(
            self.watch.summary(self.reader, "volmarr", "pub")
            .watch_count, 1)
        self.watch.star(self.reader, "volmarr", "pub")
        self.watch.star(self.reader, "volmarr", "pub")
        self.assertEqual(self._count("repo_stars"), 1)
        self.follows.follow(self.reader, "volmarr")
        self.follows.follow(self.reader, "volmarr")
        self.assertEqual(self.follows.follower_count("volmarr"), 1)
        self.follows.unfollow(self.reader, "volmarr")
        self.follows.unfollow(self.reader, "volmarr")
        self.assertEqual(self.follows.follower_count("volmarr"), 0)

    # -- mention routing: exactly once ----------------------------------
    def _mention_world(self):
        orgs = OrganizationStore(
            self.conn, self.accounts, self.audit,
            time_fn=self.clock)
        org = orgs.create_organization(self.owner.id, "crew")
        members = OrgMembershipStore(
            self.conn, self.accounts, self.audit,
            time_fn=self.clock)
        members.add_member(self.owner.id, org.id, self.reader.id)
        members.add_member(self.owner.id, org.id, self.bryn.id)
        teams = TeamStore(
            self.conn, self.accounts, self.audit,
            time_fn=self.clock)
        forge = teams.create_team(self.owner.id, org.id, "Forge")
        teams.add_member(
            self.owner.id, org.id, forge.id, self.reader.id)
        with self.conn:
            self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower,"
                " name, name_lower, created_by, created_at,"
                " description, visibility) VALUES ('crew',"
                " 'crew', 'anvil', 'anvil', ?, ?, '', 'public')",
                (self.owner.id, NOW))
        return self.issues.create_issue(
            self.owner, "crew", "anvil", "Anvil work",
            "Ping @yrsa and @crew/forge -- @yrsa twice over.")

    def test_mention_direct_and_team_paths_deliver_once(self):
        issue = self._mention_world()
        # yrsa is reached by two paths at once — the direct
        # @yrsa token (twice in the prose) and @crew/forge,
        # whose only non-author member is yrsa — and the
        # two paths merge into ONE delivery. Bryn, an org
        # member who is not on Forge, is reached by no path.
        self.assertEqual(
            self.router.sync_issue("crew", "anvil", issue.number), 1)
        mine = self.notes.list_for_recipient(self.reader)
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0].reason, "mention")
        self.assertEqual(
            self.notes.list_for_recipient(self.bryn), [])
        self.assertEqual(self._count("mention_deliveries"), 1)
        self.assertEqual(
            set(mine[0].detail["via"]), {"@yrsa", "@crew/forge"})
        before = self._count("notifications")
        self.assertEqual(
            self.router.sync_issue("crew", "anvil", issue.number), 1)
        self.assertEqual(self._count("notifications"), before)
        self.assertEqual(self._count("mention_deliveries"), 1)

    def test_mention_resync_preserves_read_state(self):
        issue = self.issues.create_issue(
            self.tess, "volmarr", "pub", "Second thread",
            "Over to @yrsa now.")
        self.router.sync_issue("volmarr", "pub", issue.number)
        mine = self.notes.list_for_recipient(self.reader)
        self.assertEqual(len(mine), 1)
        self.assertTrue(self.notes.mark_read(self.reader, mine[0].id))
        self.router.sync_issue("volmarr", "pub", issue.number)
        mine = self.notes.list_for_recipient(self.reader)
        self.assertEqual(len(mine), 1)
        self.assertFalse(mine[0].unread)

    def test_mention_muted_thread_skips_until_cleared(self):
        issue = self.issues.create_issue(
            self.tess, "volmarr", "pub", "Third thread",
            "Over to @yrsa again.")
        self.threads.set_subscription(
            self.reader, "volmarr", "pub", "issue",
            issue.number, "muted")
        self.router.sync_issue("volmarr", "pub", issue.number)
        self.assertEqual(
            self.notes.list_for_recipient(self.reader), [])
        self.threads.clear_subscription(
            self.reader, "volmarr", "pub", "issue", issue.number)
        self.router.sync_issue("volmarr", "pub", issue.number)
        self.assertEqual(
            len(self.notes.list_for_recipient(self.reader)), 1)
        self.router.sync_issue("volmarr", "pub", issue.number)
        self.assertEqual(
            len(self.notes.list_for_recipient(self.reader)), 1)

    def test_mention_in_private_repo_never_reaches_non_reader(self):
        self.router.sync_issue(
            "volmarr", "priv", self.priv_issue.number)
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET body = ? WHERE id = ?",
                ("Ping @mallory.", self.priv_issue.id))
        self.router.sync_issue(
            "volmarr", "priv", self.priv_issue.number)
        self.assertEqual(
            self.notes.list_for_recipient(self.stranger), [])

    # -- email: the composed law, every reason ---------------------------
    def test_email_pure_matrix(self):
        base = dict(smtp_configured=True,
                    email_address="yrsa@example.com",
                    mode="per-event", unsubscribed_all=False,
                    unsubscribed_reason=False)
        self.assertEqual(decide_email(**base), ("send", "per_event"))
        self.assertEqual(
            decide_email(**{**base, "mode": "digest"}),
            ("queue", "digest"))
        self.assertEqual(
            decide_email(**{**base, "smtp_configured": False}),
            ("skip", "smtp_absent"))
        self.assertEqual(
            decide_email(**{**base, "email_address": None}),
            ("skip", "no_email_address"))
        self.assertEqual(
            decide_email(**{**base, "unsubscribed_reason": True}),
            ("skip", "unsubscribed"))
        self.assertEqual(
            decide_email(**{**base, "unsubscribed_all": True}),
            ("skip", "unsubscribed"))

    def test_email_per_event_every_reason_exactly_once(self):
        for reason in SEVEN:
            note = self.notes.notify(
                self.reader, self.owner, reason,
                target_id="volmarr/pub#1",
                detail={"repo": "volmarr/pub"})
            first = self.email.deliver(note)
            self.assertEqual((first.status, first.why),
                             ("sent", "per_event"))
            again = self.email.deliver(note)
            self.assertEqual(again.id, first.id)
        self.assertEqual(self._count("email_deliveries"), len(SEVEN))
        self.assertEqual(len(self.mailer.sent), len(SEVEN))
        subjects = " ".join(s for _, s, _ in self.mailer.sent)
        for reason in SEVEN:
            self.assertIn(NOTIFICATION_REASONS[reason], subjects)

    def test_email_digest_mode_queues_and_flushes_once(self):
        store = EmailNotificationStore(
            self.conn, self.accounts, self.notes,
            mailer=self.mailer, signing_key=KEY, mode="digest",
            time_fn=self.clock)
        for reason in ("mention", "comment"):
            note = self.notes.notify(
                self.bryn, self.owner, reason,
                target_id="volmarr/pub#1",
                detail={"repo": "volmarr/pub"})
            self.assertEqual(store.deliver(note).status, "queued")
        self.assertEqual(store.pending_digest_count(self.bryn), 2)
        self.assertEqual(store.flush_digest(self.bryn), 2)
        self.assertEqual(len(self.mailer.sent), 1)
        self.assertEqual(store.flush_digest(self.bryn), 0)
        self.assertEqual(len(self.mailer.sent), 1)
        self.assertEqual(
            {d.status for d in store.deliveries_for(self.bryn)},
            {"sent"})

    def test_email_absent_smtp_skips_but_inbox_stands(self):
        store = EmailNotificationStore(
            self.conn, self.accounts, self.notes, mailer=None,
            signing_key=KEY, time_fn=self.clock)
        note = self.notes.notify(
            self.reader, self.owner, "mention",
            target_id="volmarr/pub#1", detail={"repo": "volmarr/pub"})
        delivery = store.deliver(note)
        self.assertEqual((delivery.status, delivery.why),
                         ("skipped", "smtp_absent"))
        self.assertEqual(
            len(self.inbox.list_inbox(self.reader)), 1)

    def test_email_unsubscribe_per_reason_and_all(self):
        self.email.opt_out(self.reader, "mention")
        mention = self.notes.notify(
            self.reader, self.owner, "mention",
            target_id="volmarr/pub#1", detail={"repo": "volmarr/pub"})
        comment = self.notes.notify(
            self.reader, self.owner, "comment",
            target_id="volmarr/pub#1", detail={"repo": "volmarr/pub"})
        self.assertEqual(self.email.deliver(mention).why,
                         "unsubscribed")
        self.assertEqual(self.email.deliver(comment).status, "sent")
        self.email.opt_out(self.reader, "all")
        assign = self.notes.notify(
            self.reader, self.owner, "assign",
            target_id="volmarr/pub#1", detail={"repo": "volmarr/pub"})
        self.assertEqual(self.email.deliver(assign).why,
                         "unsubscribed")
        self.assertEqual(len(self.mailer.sent), 1)

    # -- preferences: switches x cadences, every reason --------------------
    def test_preferences_plan_matrix_every_reason(self):
        for reason in SEVEN:
            self.assertEqual(self.prefs.email_plan(self.reader, reason),
                             ("send", "per_event"))
        self.prefs.set_email_enabled(self.reader, "mention", False)
        self.assertEqual(self.prefs.email_plan(self.reader, "mention"),
                         ("skip", "preferences_off"))
        self.assertEqual(self.prefs.email_plan(self.reader, "comment"),
                         ("send", "per_event"))
        self.prefs.set_all_email_enabled(self.reader, False)
        for reason in SEVEN:
            self.assertEqual(
                self.prefs.email_plan(self.reader, reason),
                ("skip", "preferences_off"))
        self.prefs.set_all_email_enabled(self.reader, True)
        self.prefs.set_email_enabled(self.reader, "mention", True)
        self.prefs.set_digest_cadence(self.reader, "daily")
        for reason in SEVEN:
            self.assertEqual(
                self.prefs.email_plan(self.reader, reason),
                ("queue", "digest_daily"))
        self.prefs.set_digest_cadence(self.reader, "weekly")
        for reason in SEVEN:
            self.assertEqual(
                self.prefs.email_plan(self.reader, reason),
                ("queue", "digest_weekly"))

    def test_preferences_watched_list_counts_honestly(self):
        self.watch.set_watch(self.reader, "volmarr", "pub", "all")
        # yrsa holds no volmarr/priv watch: S-222's own
        # door refuses a watch on a repo she cannot read,
        # so the preferences list can never name it.
        view = self.prefs.preferences_for(self.reader)
        self.assertEqual([w.full_name for w in view.watched],
                         ["volmarr/pub"])
        self.assertEqual(view.watched_count, 1)
        self.watch.set_watch(self.owner, "volmarr", "priv", "ignore")
        owner_view = self.prefs.preferences_for(self.owner)
        by_name = {w.full_name: w for w in owner_view.watched}
        self.assertFalse(by_name["volmarr/priv"].counted)
        self.assertIn("not a watch", by_name["volmarr/priv"].words)

    # -- the event store and its faces --------------------------------------
    def test_event_store_resync_is_exactly_once(self):
        self.events.sync_all()
        first = self._count("events")
        self.assertGreater(first, 0)
        self.events.sync_all()
        self.assertEqual(self._count("events"), first)
        repo_events = self.events.list_for_repo(
            self.owner, "volmarr", "pub")
        self.assertTrue(
            any(e.verb == "repo.issue.create" for e in repo_events))

    def test_private_action_invisible_on_every_public_face(self):
        pub_targets = {
            e.target_id for e in self.feeds.public_feed(None).events}
        self.assertNotIn(
            f"volmarr/priv#{self.priv_issue.number}", pub_targets)
        profile = self.profile.profile_activity(None, self.owner)
        self.assertTrue(all(
            not (e.target_id or "").startswith("volmarr/priv")
            for e in profile.events))
        api_public = self.api.public_events(None)
        self.assertTrue(all(
            not (e["target"] or "").startswith("volmarr/priv")
            for e in api_public["events"]))
        self.follows.follow(self.stranger, "volmarr")
        followed = self.follows.following_feed(self.stranger)
        self.assertTrue(all(
            not (e.target_id or "").startswith("volmarr/priv")
            for e in followed.events))
        # ...while its owner sees it on the repo's own faces.
        owner_feed = self.feeds.repo_feed(
            self.owner, "volmarr", "priv")
        self.assertTrue(any(
            e.target_id == f"volmarr/priv#{self.priv_issue.number}"
            for e in owner_feed.events))
        owner_api = self.api.repo_events(
            self.owner, "volmarr", "priv")
        self.assertTrue(any(
            e["target"] == f"volmarr/priv#{self.priv_issue.number}"
            for e in owner_api["events"]))

    def test_api_and_feed_faces_agree(self):
        feed = self.feeds.repo_feed(self.stranger, "volmarr", "pub")
        api = self.api.repo_events(self.stranger, "volmarr", "pub")
        self.assertEqual(
            [e.id for e in feed.events],
            [e["id"] for e in api["events"]])
        user_feed = self.feeds.user_feed(self.stranger, self.owner)
        user_api = self.api.user_events(self.stranger, self.owner)
        self.assertEqual(
            [e.id for e in user_feed.events],
            [e["id"] for e in user_api["events"]])

    def test_following_feed_chronological_and_follow_gated(self):
        self.assertEqual(
            self.follows.following_feed(self.reader).count, 0)
        self.follows.follow(self.reader, "volmarr")
        feed = self.follows.following_feed(self.reader)
        self.assertGreater(feed.count, 0)
        stamps = [e.created_at for e in feed.events]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        self.assertTrue(all(
            e.actor == "volmarr" for e in feed.events))

    def test_star_lists_public_signal_private_hidden(self):
        self.watch.star(self.owner, "volmarr", "pub")
        self.watch.star(self.owner, "volmarr", "priv")
        mine = self.stars.star_list(self.owner, "volmarr")
        self.assertEqual(
            {e.full_name for e in mine.entries},
            {"volmarr/pub", "volmarr/priv"})
        seen = self.stars.star_list(self.stranger, "volmarr")
        self.assertEqual([e.full_name for e in seen.entries],
                         ["volmarr/pub"])
        self.assertTrue(all(
            e.visibility == "public" and e.signal_label
            for e in seen.entries))
        self.watch.unstar(self.owner, "volmarr", "pub")
        self.assertEqual(
            self.stars.starred_count(self.stranger, "volmarr"), 0)

    def test_push_feed_surfaces_push_once_with_summary(self):
        first = seed_commit(
            self.repos, "volmarr", "pub",
            text=b"one\n", message=b"gate commit one\n")
        second = seed_commit(
            self.repos, "volmarr", "pub", text=b"two\n",
            parent=first, message=b"gate commit two\n")
        self.pushes.record_push(
            "volmarr", "pub",
            updates=(RefUpdate("refs/heads/main", first, second),),
            actor_kind="user", actor_id=self.tess.id,
            transport="http")
        feed = self.push_feed.push_feed(self.owner)
        self.assertEqual(feed.count, 1)
        self.assertIn("gate commit", feed.entries[0].words)
        self.assertEqual(self.push_feed.push_feed(self.owner).count, 1)
        self.assertEqual(self.push_feed.push_feed(self.reader).count, 0)

    # -- the weekly digest job ------------------------------------------------
    def test_digest_job_composes_exactly_once_per_person(self):
        self.prefs.set_digest_cadence(self.reader, "weekly")
        self.prefs.set_digest_cadence(self.tess, "daily")
        self.watch.set_watch(self.reader, "volmarr", "pub", "all")
        week_start, week_end = week_window(NOW)
        self.issues.create_issue(
            self.tess, "volmarr", "pub", "Digest week thread")
        job = DigestJobStore(
            self.conn, self.accounts, self.repos, self.events,
            self.prefs, mailer=None, time_fn=self.clock)
        self.assertEqual(
            [u.username for u in job.eligible_users()], ["yrsa"])
        digest, created = job.compose_for(
            self.reader, week_start, week_end)
        self.assertTrue(created)
        self.assertGreater(digest.event_count, 0)
        again, created_again = job.compose_for(
            self.reader, week_start, week_end)
        self.assertFalse(created_again)
        self.assertEqual(again.id, digest.id)
        self.assertEqual(self._count("weekly_digests"), 1)
        run = job.run_weekly(now=week_end + 60)
        self.assertEqual(
            (run.eligible, run.composed, run.sent), (1, 0, 0))
        self.assertEqual(run.existing, 1)
        self.assertEqual(self._count("weekly_digests"), 1)

    def test_digest_empty_week_recorded_honestly(self):
        # A week three weeks before any fixture activity:
        # nothing relevant stands in it for anyone.
        week_start, week_end = week_window(NOW - 3 * 604800)
        job = DigestJobStore(
            self.conn, self.accounts, self.repos, self.events,
            self.prefs, mailer=None, time_fn=self.clock)
        digest, created = job.compose_for(
            self.stranger, week_start, week_end)
        self.assertTrue(created)
        self.assertEqual(digest.status, "empty")
        self.assertEqual(digest.event_count, 0)
        self.assertIn("never sent", digest.words)

    # -- honesty seams -----------------------------------------------------------
    def test_renders_escape_through_s010(self):
        note = self.notes.notify(
            self.reader, self.owner, "mention",
            target_id="<script>alert(1)</script>")
        page = render_notifications([note])
        self.assertNotIn("<script>", page)
        self.assertIn("you were mentioned", page)

    def test_anonymous_callers_refused(self):
        with self.assertRaises(NotificationError):
            self.notes.list_for_recipient(None)
        with self.assertRaises(Exception):
            self.inbox.list_inbox(None)
        with self.assertRaises(Exception):
            self.threads.effective_for(
                None, "volmarr", "pub", "issue", self.issue.number)
        with self.assertRaises(Exception):
            self.prefs.preferences_for(None)


if __name__ == "__main__":
    unittest.main()
