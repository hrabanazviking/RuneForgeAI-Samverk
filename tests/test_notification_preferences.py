"""S-228 acceptance battery: notification preferences.

Acceptance (roadmap S-228): notification preferences --
per-user page: email on/off per reason, digest cadence,
watched-repo management in one list (findability law).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.email_notifications import (
    EmailNotificationStore, UNSUBSCRIBE_ALL)
from samverk.notification_preferences import (
    DEFAULT_DIGEST_CADENCE, DIGEST_CADENCES, PREFERENCE_SECTIONS,
    NotificationPreferencesStore, PreferenceError,
    cadence_words, decide_email_enabled, decide_user_email,
    preference_sections, render_preferences_page,
    render_reason_preference, render_watched_repo,
    validate_digest_cadence)
from samverk.notification_reasons import (
    NOTIFICATION_REASONS, NotificationStore)
from samverk.repositories import RepositoryStore
from samverk.watch_star import WatchStarStore

KEY = b"unit-test-signing-key"


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class FakeMailer:
    def __init__(self):
        self.sent = []
    def __call__(self, address, subject, body):
        self.sent.append((address, subject, body))


class NotificationPreferenceTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.yrsa = self.accounts.register("yrsa", "correct horse battery", "yrsa@example.com")
        self.bryn = self.accounts.register("brynhild", "correct horse battery", "bryn@example.com")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts, audit=self.audit)
        self.ws = WatchStarStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)
        self.notes = NotificationStore(self.conn, self.accounts, time_fn=self.clock)
        self.mailer = FakeMailer()
        self.email = EmailNotificationStore(
            self.conn, self.accounts, self.notes, mailer=self.mailer,
            signing_key=KEY, time_fn=self.clock)
        self.prefs = NotificationPreferencesStore(
            self.conn, self.accounts, self.repos, self.ws, time_fn=self.clock)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.repos.create_repository(self.yrsa.id, "yrsa", "anvil", visibility="public")
        self.repos.create_repository(self.yrsa.id, "yrsa", "vault", visibility="private")

    # -- helpers --------------------------------------------------
    def _optout_rows(self, user_id=None):
        sql = "SELECT COUNT(*) AS n FROM email_optouts"
        if user_id is not None:
            row = self.conn.execute(sql + " WHERE user_id = ?", (user_id,)).fetchone()
        else:
            row = self.conn.execute(sql).fetchone()
        return row["n"]

    def _audit_actions(self):
        rows = self.conn.execute("SELECT action FROM audit_log ORDER BY seq").fetchall()
        return [r["action"] for r in rows]

    # -- pins -------------------------------------------------------
    def test_pins_schema_99_taxonomy_131(self):
        self.assertEqual(schema_version(self.conn), 99)
        self.assertEqual(db.MIGRATIONS[-1][0], 99)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 85)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("notification_preferences", tables)
        self.assertIn("email_optouts", tables)
        self.assertIn("repo_watches", tables)

    def test_fresh_database_migrates_to_93(self):
        path = self.root / "fresh.db"
        conn = db.connect(path); self.addCleanup(conn.close)
        self.assertEqual(db.migrate(conn), 99)
        self.assertEqual(db.schema_version(conn), 99)

    # -- findability map ---------------------------------------------
    def test_sections_map_is_the_whole_page(self):
        self.assertEqual([s[0] for s in PREFERENCE_SECTIONS],
                         ["email", "digest", "watched"])
        sections = preference_sections()
        self.assertEqual([s["key"] for s in sections],
                         ["email", "digest", "watched"])
        for section in sections:
            self.assertTrue(section["title"])
            self.assertTrue(section["description"])

    # -- cadence: pure law --------------------------------------------
    def test_cadence_door_and_words(self):
        self.assertEqual(DEFAULT_DIGEST_CADENCE, "immediate")
        self.assertEqual(set(DIGEST_CADENCES), {"immediate", "daily", "weekly"})
        for good in DIGEST_CADENCES:
            self.assertEqual(validate_digest_cadence(good), good)
            self.assertEqual(cadence_words(good), DIGEST_CADENCES[good])
        for bad in ("hourly", "per-event", "digest", "", None, 7, True):
            with self.assertRaises(PreferenceError) as cm:
                validate_digest_cadence(bad)
            self.assertEqual(cm.exception.reason, "digest_cadence_invalid")

    def test_decide_user_email_matrix(self):
        self.assertEqual(decide_user_email(enabled=False, cadence="immediate"),
                         ("skip", "preferences_off"))
        self.assertEqual(decide_user_email(enabled=False, cadence="daily"),
                         ("skip", "preferences_off"))
        self.assertEqual(decide_user_email(enabled=True, cadence="immediate"),
                         ("send", "per_event"))
        self.assertEqual(decide_user_email(enabled=True, cadence="daily"),
                         ("queue", "digest_daily"))
        self.assertEqual(decide_user_email(enabled=True, cadence="weekly"),
                         ("queue", "digest_weekly"))
        with self.assertRaises(PreferenceError):
            decide_user_email(enabled=True, cadence="hourly")

    def test_decide_email_enabled_two_levels(self):
        self.assertTrue(decide_email_enabled(True, True))
        self.assertFalse(decide_email_enabled(True, False))
        self.assertFalse(decide_email_enabled(False, True))
        self.assertFalse(decide_email_enabled(False, False))

    # -- cadence: store -------------------------------------------------
    def test_cadence_defaults_and_roundtrip(self):
        self.assertEqual(self.prefs.digest_cadence_for(self.yrsa), "immediate")
        view = self.prefs.set_digest_cadence(self.yrsa, "daily")
        self.assertEqual(view.digest_cadence, "daily")
        self.assertEqual(self.prefs.digest_cadence_for(self.yrsa), "daily")
        view = self.prefs.set_digest_cadence(self.yrsa, "weekly")
        self.assertEqual(view.digest_cadence, "weekly")
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM notification_preferences").fetchone()["n"]
        self.assertEqual(rows, 1)  # one row per account, updated in place

    def test_cadence_refusal_stores_nothing(self):
        with self.assertRaises(PreferenceError) as cm:
            self.prefs.set_digest_cadence(self.yrsa, "hourly")
        self.assertEqual(cm.exception.reason, "digest_cadence_invalid")
        self.assertEqual(self.prefs.digest_cadence_for(self.yrsa), "immediate")
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM notification_preferences").fetchone()["n"]
        self.assertEqual(rows, 0)

    # -- email: defaults and per-reason ----------------------------------
    def test_email_defaults_all_on(self):
        view = self.prefs.preferences_for(self.yrsa)
        self.assertTrue(view.all_email_on)
        self.assertEqual([r.reason for r in view.reasons],
                         list(NOTIFICATION_REASONS))
        for entry in view.reasons:
            self.assertTrue(entry.own_on)
            self.assertTrue(entry.enabled)
            self.assertEqual(entry.reason_words,
                             NOTIFICATION_REASONS[entry.reason])
        self.assertEqual(self._optout_rows(), 0)

    def test_email_off_per_reason_is_s227_record(self):
        view = self.prefs.set_email_enabled(self.yrsa, "mention", False)
        entry = view.reason_preference("mention")
        self.assertFalse(entry.own_on)
        self.assertFalse(entry.enabled)
        self.assertTrue(view.reason_preference("comment").enabled)
        # The very record S-227 consults: its store agrees.
        self.assertTrue(self.email.is_unsubscribed(self.yrsa.id, "mention"))
        self.assertFalse(self.email.is_unsubscribed(self.yrsa.id, "comment"))
        view = self.prefs.set_email_enabled(self.yrsa, "mention", True)
        self.assertTrue(view.reason_preference("mention").enabled)
        self.assertFalse(self.email.is_unsubscribed(self.yrsa.id, "mention"))
        self.assertEqual(self._optout_rows(self.yrsa.id), 0)

    def test_email_reason_door(self):
        for bad in ("review-dismissed", "everything", "", None, 3):
            with self.assertRaises(PreferenceError) as cm:
                self.prefs.set_email_enabled(self.yrsa, bad, False)
            self.assertEqual(cm.exception.reason, "reason_invalid")
        self.assertEqual(self._optout_rows(), 0)

    def test_unsubscribe_link_shows_on_page(self):
        # Redeeming S-227's signed link turns the reason off here.
        token_url = self.email.unsubscribe_link(self.yrsa.id, "assign")
        token = token_url.rsplit("/", 1)[-1]
        self.assertEqual(self.email.unsubscribe(token),
                         (self.yrsa.id, "assign"))
        view = self.prefs.preferences_for(self.yrsa)
        self.assertFalse(view.reason_preference("assign").enabled)
        self.assertTrue(view.reason_preference("mention").enabled)

    def test_email_toggle_idempotent(self):
        self.prefs.set_email_enabled(self.yrsa, "mention", False)
        self.prefs.set_email_enabled(self.yrsa, "mention", False)
        self.assertEqual(self._optout_rows(self.yrsa.id), 1)
        self.prefs.set_email_enabled(self.yrsa, "mention", True)
        self.prefs.set_email_enabled(self.yrsa, "mention", True)
        self.assertEqual(self._optout_rows(self.yrsa.id), 0)

    # -- email: master switch ----------------------------------------------
    def test_master_off_holds_all_reasons_honestly(self):
        self.prefs.set_email_enabled(self.yrsa, "comment", False)
        view = self.prefs.set_all_email_enabled(self.yrsa, False)
        self.assertFalse(view.all_email_on)
        for entry in view.reasons:
            self.assertFalse(entry.enabled)
        # Own choices stand beneath the master switch.
        self.assertTrue(view.reason_preference("mention").own_on)
        self.assertFalse(view.reason_preference("comment").own_on)
        self.assertIn("all notification email is off",
                      view.reason_preference("mention").words)
        # Lifting the master restores each reason's own standing.
        view = self.prefs.set_all_email_enabled(self.yrsa, True)
        self.assertTrue(view.all_email_on)
        self.assertTrue(view.reason_preference("mention").enabled)
        self.assertFalse(view.reason_preference("comment").enabled)

    def test_reason_toggle_never_lifts_master(self):
        self.prefs.set_all_email_enabled(self.yrsa, False)
        view = self.prefs.set_email_enabled(self.yrsa, "mention", True)
        self.assertFalse(view.all_email_on)
        self.assertFalse(view.reason_preference("mention").enabled)
        self.assertTrue(self.email.is_unsubscribed(
            self.yrsa.id, UNSUBSCRIBE_ALL))

    def test_email_plan_composes_choices_and_cadence(self):
        self.assertEqual(self.prefs.email_plan(self.yrsa, "mention"),
                         ("send", "per_event"))
        self.prefs.set_digest_cadence(self.yrsa, "weekly")
        self.assertEqual(self.prefs.email_plan(self.yrsa, "mention"),
                         ("queue", "digest_weekly"))
        self.prefs.set_email_enabled(self.yrsa, "mention", False)
        self.assertEqual(self.prefs.email_plan(self.yrsa, "mention"),
                         ("skip", "preferences_off"))
        self.assertEqual(self.prefs.email_plan(self.yrsa, "comment"),
                         ("queue", "digest_weekly"))

    # -- watched repositories -----------------------------------------------
    def test_watched_empty_then_one_list_all_modes(self):
        self.assertEqual(self.prefs.list_watched(self.yrsa), ())
        self.ws.set_watch(self.yrsa, "volmarr", "pub", "all")
        self.ws.set_watch(self.yrsa, "yrsa", "anvil", "releases_only")
        self.ws.set_watch(self.yrsa, "yrsa", "vault", "ignore")
        watched = self.prefs.list_watched(self.yrsa)
        # All three list, in name order, ignore included as a
        # managed choice.
        self.assertEqual(
            [(w.full_name, w.mode) for w in watched],
            [("volmarr/pub", "all"), ("yrsa/anvil", "releases_only"),
             ("yrsa/vault", "ignore")])
        view = self.prefs.preferences_for(self.yrsa)
        self.assertEqual(view.watched_count, 2)
        ignore = [w for w in watched if w.mode == "ignore"][0]
        self.assertFalse(ignore.counted)
        self.assertIn("do not count as a watcher", ignore.words)

    def test_watched_list_never_leaks_unreadable_repo(self):
        # brynhild watches the public repo; the private repo is
        # refused at S-222's door and can never appear anywhere.
        self.ws.set_watch(self.bryn, "volmarr", "pub", "all")
        with self.assertRaises(Exception):
            self.ws.set_watch(self.bryn, "volmarr", "priv", "all")
        # Even a planted row (access later revoked) is filtered.
        repo = self.repos.get_repository("volmarr", "priv")
        self.conn.execute(
            "INSERT INTO repo_watches (repo_id, user_id, mode,"
            " created_at, updated_at) VALUES (?, ?, 'all', 1, 1)",
            (repo.id, self.bryn.id))
        self.conn.commit()
        names = [w.full_name for w in self.prefs.list_watched(self.bryn)]
        self.assertEqual(names, ["volmarr/pub"])

    def test_watch_management_from_page_goes_through_s222(self):
        self.ws.set_watch(self.yrsa, "volmarr", "pub", "all")
        view = self.prefs.set_watch_mode(self.yrsa, "volmarr", "pub",
                                         "releases_only")
        self.assertEqual(
            [(w.full_name, w.mode) for w in view.watched],
            [("volmarr/pub", "releases_only")])
        self.assertEqual(self._audit_actions().count("repo.watch"), 2)
        view = self.prefs.unwatch(self.yrsa, "volmarr", "pub")
        self.assertEqual(view.watched, ())
        self.assertEqual(self._audit_actions().count("repo.unwatch"), 1)
        # A bad mode is refused through S-222's door, mapped, storing nothing.
        with self.assertRaises(PreferenceError) as cm:
            self.prefs.set_watch_mode(self.yrsa, "volmarr", "pub", "everything")
        self.assertEqual(cm.exception.reason, "watch_mode_invalid")
        with self.assertRaises(PreferenceError) as cm:
            self.prefs.unwatch(self.yrsa, "volmarr", "priv")
        self.assertEqual(cm.exception.reason, "repo_not_found")

    # -- ownership ------------------------------------------------------------
    def test_preferences_belong_to_holder(self):
        self.prefs.set_digest_cadence(self.yrsa, "daily")
        self.prefs.set_email_enabled(self.yrsa, "mention", False)
        other = self.prefs.preferences_for(self.bryn)
        self.assertEqual(other.digest_cadence, "immediate")
        self.assertTrue(other.reason_preference("mention").enabled)
        self.assertEqual(self._optout_rows(self.bryn.id), 0)

    def test_anonymous_refused_everywhere(self):
        calls = [
            lambda: self.prefs.preferences_for(None),
            lambda: self.prefs.digest_cadence_for(None),
            lambda: self.prefs.set_digest_cadence(None, "daily"),
            lambda: self.prefs.set_email_enabled(None, "mention", False),
            lambda: self.prefs.set_all_email_enabled(None, False),
            lambda: self.prefs.list_watched(None),
            lambda: self.prefs.email_plan(None, "mention"),
            lambda: self.prefs.set_watch_mode(None, "volmarr", "pub", "all"),
            lambda: self.prefs.unwatch(None, "volmarr", "pub"),
        ]
        for call in calls:
            with self.assertRaises(PreferenceError) as cm:
                call()
            self.assertEqual(cm.exception.reason, "authentication_required")

    def test_preferences_write_no_taxonomy_event(self):
        before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.prefs.set_digest_cadence(self.yrsa, "daily")
        self.prefs.set_email_enabled(self.yrsa, "mention", False)
        self.prefs.set_all_email_enabled(self.yrsa, False)
        after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.assertEqual(before, after)

    # -- renders ------------------------------------------------------------------
    def test_page_renders_all_sections_in_words(self):
        self.ws.set_watch(self.yrsa, "volmarr", "pub", "all")
        self.prefs.set_digest_cadence(self.yrsa, "daily")
        self.prefs.set_email_enabled(self.yrsa, "assign", False)
        page = render_preferences_page(self.prefs.preferences_for(self.yrsa))
        for title in ("Email", "Digest cadence", "Watched repositories"):
            self.assertIn(title, page)
        self.assertIn("yrsa@example.com", page)
        self.assertIn("All notification email: on", page)
        for reason, words in NOTIFICATION_REASONS.items():
            self.assertIn(reason, page)
            self.assertIn(words, page)
        self.assertIn("assign", page)
        self.assertIn("email off", page)
        self.assertIn("daily", page)
        self.assertIn("one digest email a day", page)
        self.assertIn("volmarr/pub", page)
        self.assertIn("all activity", page)

    def test_page_empty_watched_teaches(self):
        page = render_preferences_page(self.prefs.preferences_for(self.bryn))
        self.assertIn("not watching any repository yet", page)
        self.assertIn("bryn@example.com", page)

    def test_page_no_email_address_honest(self):
        page = render_preferences_page(self.prefs.preferences_for(self.owner))
        self.assertIn("No email address on this account", page)

    def test_renders_escape_through_s010(self):
        self.ws.set_watch(self.yrsa, "volmarr", "pub", "all")
        view = self.prefs.preferences_for(self.yrsa)
        entry = view.reason_preference("mention")
        html = render_reason_preference(entry)
        self.assertIn("mention", html)
        self.assertIn("you were mentioned", html)
        watched_html = render_watched_repo(view.watched[0])
        self.assertIn("volmarr/pub", watched_html)
        # A hostile username never reaches the page unescaped.
        evil = self.accounts.register("eviluser", "correct horse battery")
        object.__setattr__(evil, "username", "<script>alert(1)</script>")
        page = render_preferences_page(self.prefs.preferences_for(evil))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)


if __name__ == "__main__":
    unittest.main()
