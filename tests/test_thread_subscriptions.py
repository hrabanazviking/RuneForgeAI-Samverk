"""S-225 acceptance battery: thread subscription.

Acceptance (roadmap S-225): per-issue/PR
subscription and mute, overriding repo-level watch
honestly and visibly.

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
from samverk.issues import IssueStore
from samverk.repositories import RepositoryStore
from samverk.thread_subscriptions import (
    OVERRIDE_STATES, THREAD_KINDS, ThreadSubscriptionError,
    ThreadSubscriptionStore, decide_notify, decide_subscription,
    explain_effective, render_thread_subscription,
    render_thread_subscriptions, validate_subscription_state,
    validate_thread_kind, validate_thread_number)
from samverk.watch_star import WatchStarStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class ThreadSubscriptionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.other = self.accounts.register("mallory", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)
        self.watch = WatchStarStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)
        self.store = ThreadSubscriptionStore(
            self.conn, self.repos, self.accounts,
            watch_store=self.watch, issues=self.issues, time_fn=self.clock)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.issue = self.issues.create_issue(self.owner, "volmarr", "pub", "First thread")
        self.pr = self.issues.claim_number("volmarr", "pub", "pull_request", self.owner.id)
        self.priv_issue = self.issues.create_issue(self.owner, "volmarr", "priv", "Secret thread")

    def _rows(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM thread_overrides").fetchone()["n"]

    def _audit_rows(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    # -- pins ---------------------------------------------------
    def test_pins_schema_99_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 117)
        self.assertEqual(db.MIGRATIONS[-1][0], 117)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 88)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("thread_overrides", tables)
        self.assertIn("repo_watches", tables)

    def test_fresh_database_migrates_to_93(self):
        path = self.root / "fresh.db"
        conn = db.connect(path); self.addCleanup(conn.close)
        self.assertEqual(db.migrate(conn), 117)
        self.assertEqual(db.schema_version(conn), 117)

    # -- pure law -------------------------------------------------
    def test_vocabulary_and_validators(self):
        self.assertEqual(set(THREAD_KINDS), {"issue", "pull_request"})
        self.assertEqual(set(OVERRIDE_STATES), {"subscribed", "muted"})
        self.assertEqual(validate_thread_kind("issue"), "issue")
        self.assertEqual(validate_thread_kind("pull_request"), "pull_request")
        self.assertEqual(validate_thread_number(7), 7)
        self.assertEqual(validate_subscription_state("muted"), "muted")
        self.assertTrue(decide_subscription(None, "muted"))
        self.assertTrue(decide_subscription("muted", "subscribed"))
        self.assertFalse(decide_subscription("muted", "muted"))

    def test_pure_decide_notify_matrix(self):
        self.assertFalse(decide_notify("muted", "all"))
        self.assertFalse(decide_notify("muted", None))
        self.assertTrue(decide_notify("subscribed", "ignore"))
        self.assertTrue(decide_notify("subscribed", "releases_only"))
        self.assertTrue(decide_notify("subscribed", None))
        self.assertTrue(decide_notify(None, "all"))
        self.assertFalse(decide_notify(None, "releases_only"))
        self.assertFalse(decide_notify(None, "ignore"))
        self.assertFalse(decide_notify(None, None))

    def test_explanations_name_both_levels(self):
        self.assertIn("muted -- overrides repository watch: all activity",
                      explain_effective("muted", "all"))
        self.assertIn("subscribed -- overrides repository watch: ignore",
                      explain_effective("subscribed", "ignore"))
        self.assertIn("subscribed -- overrides repository watch: releases only",
                      explain_effective("subscribed", "releases_only"))
        self.assertIn("inherited from repository watch: all activity",
                      explain_effective(None, "all"))
        self.assertIn("inherited from repository watch: releases only",
                      explain_effective(None, "releases_only"))
        self.assertIn("inherited from repository watch: ignore",
                      explain_effective(None, "ignore"))
        self.assertIn("no repository watch set", explain_effective(None, None))
        self.assertIn("confirms", explain_effective("subscribed", "all"))
        self.assertIn("confirms", explain_effective("muted", "ignore"))

    # -- subscribe / mute / inherit --------------------------------
    def test_subscribe_stores_row_and_view_is_visible(self):
        v = self.store.set_subscription(
            self.reader, "volmarr", "pub", "issue", self.issue.number, "subscribed")
        self.assertEqual(self._rows(), 1)
        self.assertEqual(v.override, "subscribed")
        self.assertIsNone(v.watch_mode)
        self.assertTrue(v.notify)
        self.assertEqual(v.decision.reason, "subscribed")
        self.assertIn("overrides repository watch", v.explanation)
        self.assertEqual(v.label, f"volmarr/pub#{self.issue.number}")
        got = self.store.get_subscription(
            self.reader, "volmarr", "pub", "issue", self.issue.number)
        self.assertEqual(got.override, "subscribed")

    def test_mute_beats_watch_all(self):
        self.watch.set_watch(self.reader, "volmarr", "pub", "all")
        v = self.store.set_subscription(
            self.reader, "volmarr", "pub", "issue", self.issue.number, "muted")
        self.assertFalse(v.notify)
        self.assertEqual(v.watch_mode, "all")
        self.assertIn("muted -- overrides repository watch: all activity", v.explanation)
        d = self.store.effective_for(
            self.reader, "volmarr", "pub", "issue", self.issue.number)
        self.assertFalse(d.notify); self.assertIsNone(d.reason)

    def test_subscribe_beats_ignore_and_releases_only(self):
        self.watch.set_watch(self.reader, "volmarr", "pub", "ignore")
        v = self.store.set_subscription(
            self.reader, "volmarr", "pub", "pull_request", self.pr.number, "subscribed")
        self.assertTrue(v.notify)
        self.assertIn("overrides repository watch: ignore", v.explanation)
        self.watch.set_watch(self.reader, "volmarr", "pub", "releases_only")
        v = self.store.get_subscription(
            self.reader, "volmarr", "pub", "pull_request", self.pr.number)
        self.assertTrue(v.notify)
        self.assertIn("releases only", v.explanation)

    def test_inherit_follows_repo_watch(self):
        v = self.store.get_subscription(
            self.reader, "volmarr", "pub", "issue", self.issue.number)
        self.assertIsNone(v.override); self.assertFalse(v.notify)
        self.assertIn("no repository watch set", v.explanation)
        self.watch.set_watch(self.reader, "volmarr", "pub", "all")
        v = self.store.get_subscription(
            self.reader, "volmarr", "pub", "issue", self.issue.number)
        self.assertTrue(v.notify)
        self.assertIn("inherited from repository watch: all activity", v.explanation)
        self.watch.set_watch(self.reader, "volmarr", "pub", "releases_only")
        v = self.store.get_subscription(
            self.reader, "volmarr", "pub", "issue", self.issue.number)
        self.assertFalse(v.notify)
        self.assertIn("thread activity does not notify", v.explanation)
        self.watch.set_watch(self.reader, "volmarr", "pub", "ignore")
        v = self.store.get_subscription(
            self.reader, "volmarr", "pub", "issue", self.issue.number)
        self.assertFalse(v.notify)

    def test_transitions_and_clear_restores_inherit(self):
        n = self.issue.number
        self.store.set_subscription(self.reader, "volmarr", "pub", "issue", n, "subscribed")
        v = self.store.set_subscription(self.reader, "volmarr", "pub", "issue", n, "muted")
        self.assertEqual(v.override, "muted"); self.assertEqual(self._rows(), 1)
        v = self.store.clear_subscription(self.reader, "volmarr", "pub", "issue", n)
        self.assertIsNone(v.override); self.assertEqual(self._rows(), 0)
        self.assertEqual(v.state_words, "inherited")
        v = self.store.clear_subscription(self.reader, "volmarr", "pub", "issue", n)
        self.assertIsNone(v.override); self.assertEqual(self._rows(), 0)

    def test_idempotent_reset_keeps_updated_at(self):
        n = self.issue.number
        first = self.store.set_subscription(self.reader, "volmarr", "pub", "issue", n, "muted")
        self.clock.now += 500
        again = self.store.set_subscription(self.reader, "volmarr", "pub", "issue", n, "muted")
        self.assertEqual(again.updated_at, first.updated_at)
        self.assertEqual(self._rows(), 1)
        changed = self.store.set_subscription(self.reader, "volmarr", "pub", "issue", n, "subscribed")
        self.assertEqual(changed.updated_at, self.clock.now)
        self.assertEqual(changed.created_at, first.created_at)

    # -- refusals ----------------------------------------------------
    def test_invalid_kind_number_state_refused_storing_nothing(self):
        n = self.issue.number
        for bad_kind in ("comment", "", None, 3, "ISSUE"):
            with self.assertRaises(ThreadSubscriptionError) as cm:
                self.store.set_subscription(self.reader, "volmarr", "pub", bad_kind, n, "muted")
            self.assertEqual(cm.exception.reason, "thread_kind_invalid")
        for bad_num in (0, -2, "1", 1.5, True, None):
            with self.assertRaises(ThreadSubscriptionError) as cm:
                self.store.set_subscription(self.reader, "volmarr", "pub", "issue", bad_num, "muted")
            self.assertEqual(cm.exception.reason, "thread_number_invalid")
        for bad_state in ("inherit", "watching", "", None, 3):
            with self.assertRaises(ThreadSubscriptionError) as cm:
                self.store.set_subscription(self.reader, "volmarr", "pub", "issue", n, bad_state)
            self.assertEqual(cm.exception.reason, "subscription_state_invalid")
        self.assertEqual(self._rows(), 0)

    def test_missing_thread_and_kind_mismatch_are_uniform_not_found(self):
        for kind, num in (("issue", 999), ("pull_request", self.issue.number),
                          ("issue", self.pr.number), ("issue", 999)):
            with self.assertRaises(ThreadSubscriptionError) as cm:
                self.store.set_subscription(self.reader, "volmarr", "pub", kind, num, "muted")
            self.assertEqual(cm.exception.reason, "thread_not_found")
        with self.assertRaises(ThreadSubscriptionError) as cm:
            self.store.get_subscription(self.reader, "volmarr", "nosuch", "issue", 1)
        self.assertEqual(cm.exception.reason, "thread_not_found")
        self.assertEqual(self._rows(), 0)

    def test_anonymous_refused_everywhere(self):
        n = self.issue.number
        calls = (
            lambda: self.store.set_subscription(None, "volmarr", "pub", "issue", n, "muted"),
            lambda: self.store.get_subscription(None, "volmarr", "pub", "issue", n),
            lambda: self.store.clear_subscription(None, "volmarr", "pub", "issue", n),
            lambda: self.store.list_subscriptions(None),
        )
        for call in calls:
            with self.assertRaises(ThreadSubscriptionError) as cm:
                call()
            self.assertEqual(cm.exception.reason, "authentication_required")
        self.assertEqual(self._rows(), 0)

    def test_private_repo_uniform_refusal_for_stranger(self):
        n = self.priv_issue.number
        for call in (
            lambda: self.store.set_subscription(self.other, "volmarr", "priv", "issue", n, "muted"),
            lambda: self.store.get_subscription(self.other, "volmarr", "priv", "issue", n),
            lambda: self.store.list_for_repo(self.other, "volmarr", "priv"),
        ):
            with self.assertRaises(ThreadSubscriptionError) as cm:
                call()
            self.assertEqual(cm.exception.reason, "thread_not_found")
        self.assertEqual(self._rows(), 0)
        v = self.store.set_subscription(self.owner, "volmarr", "priv", "issue", n, "muted")
        self.assertEqual(v.override, "muted")

    # -- owner scoping -------------------------------------------------
    def test_owner_scoping_other_user_sees_only_own(self):
        n = self.issue.number
        self.store.set_subscription(self.reader, "volmarr", "pub", "issue", n, "muted")
        other_view = self.store.get_subscription(self.other, "volmarr", "pub", "issue", n)
        self.assertIsNone(other_view.override)
        self.assertEqual(self.store.list_subscriptions(self.other), [])
        self.store.set_subscription(self.other, "volmarr", "pub", "issue", n, "subscribed")
        mine = self.store.get_subscription(self.reader, "volmarr", "pub", "issue", n)
        self.assertEqual(mine.override, "muted")
        self.assertEqual(self._rows(), 2)
        self.store.clear_subscription(self.other, "volmarr", "pub", "issue", n)
        mine = self.store.get_subscription(self.reader, "volmarr", "pub", "issue", n)
        self.assertEqual(mine.override, "muted")

    def test_list_subscriptions_and_for_repo(self):
        self.store.set_subscription(self.reader, "volmarr", "pub", "issue", self.issue.number, "muted")
        self.store.set_subscription(self.reader, "volmarr", "pub", "pull_request", self.pr.number, "subscribed")
        mine = self.store.list_subscriptions(self.reader)
        self.assertEqual([(v.kind, v.number) for v in mine],
                         [("issue", self.issue.number), ("pull_request", self.pr.number)])
        in_repo = self.store.list_for_repo(self.reader, "volmarr", "pub")
        self.assertEqual(len(in_repo), 2)
        self.assertTrue(all(v.username == "yrsa" for v in mine))

    # -- no witnessed act ------------------------------------------------
    def test_audit_log_does_not_move(self):
        before = self._audit_rows()
        n = self.issue.number
        self.store.set_subscription(self.reader, "volmarr", "pub", "issue", n, "muted")
        self.store.set_subscription(self.reader, "volmarr", "pub", "issue", n, "subscribed")
        self.store.get_subscription(self.reader, "volmarr", "pub", "issue", n)
        self.store.list_subscriptions(self.reader)
        self.store.clear_subscription(self.reader, "volmarr", "pub", "issue", n)
        self.assertEqual(self._audit_rows(), before)

    # -- renders -----------------------------------------------------------
    def test_renders_say_explanation_and_escape(self):
        self.watch.set_watch(self.reader, "volmarr", "pub", "all")
        v = self.store.set_subscription(
            self.reader, "volmarr", "pub", "issue", self.issue.number, "muted")
        html = render_thread_subscription(v)
        self.assertIn("muted -- overrides repository watch: all activity", html)
        self.assertIn("volmarr/pub#", html)
        panel = render_thread_subscriptions([v])
        self.assertIn("thread-subscriptions", panel)
        self.assertIn("no notifications", panel)

    def test_empty_render_teaches_model(self):
        html = render_thread_subscriptions([])
        self.assertIn("subscribe", html)
        self.assertIn("mute", html)
        self.assertIn("inherits", html)
        self.assertIn("repository watch", html)


if __name__ == "__main__":
    unittest.main()
