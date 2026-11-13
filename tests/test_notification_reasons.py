"""S-223 acceptance battery: notification reasons.

Acceptance (roadmap S-223): mention, assign,
review-requested, author, comment, state-change,
subscribed; the reason is stored and shown with
every notification.

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
from samverk.notification_reasons import (
    NOTIFICATION_REASONS, NotificationError, NotificationStore,
    reason_words, render_notification, render_notifications,
    validate_reason)

SEVEN = ("mention", "assign", "review-requested", "author",
         "comment", "state-change", "subscribed")


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class NotificationReasonTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=self.clock)
        self.actor = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.other = self.accounts.register("mallory", "correct horse battery")
        self.store = NotificationStore(self.conn, self.accounts, time_fn=self.clock)

    def _rows(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM notifications").fetchone()["n"]

    # -- pins -------------------------------------------------
    def test_pins_schema_99_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 126)
        self.assertEqual(db.MIGRATIONS[-1][0], 126)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("notifications", tables)

    # -- the vocabulary -----------------------------------------
    def test_vocabulary_is_exactly_the_seven_in_order(self):
        self.assertEqual(tuple(NOTIFICATION_REASONS), SEVEN)
        for reason in SEVEN:
            self.assertEqual(validate_reason(reason), reason)
            self.assertTrue(reason_words(reason))

    def test_invalid_reasons_refused_and_store_nothing(self):
        for bad in ("review-dismissed", "participating", "", None, 3, True, "MENTION"):
            with self.assertRaises(NotificationError) as cm:
                validate_reason(bad)
            self.assertEqual(cm.exception.reason, "reason_invalid")
            with self.assertRaises(NotificationError) as cm:
                self.store.notify(self.reader, self.actor, bad)
            self.assertEqual(cm.exception.reason, "reason_invalid")
        self.assertEqual(self._rows(), 0)

    # -- storage --------------------------------------------------
    def test_every_reason_is_stored_on_its_row(self):
        for reason in SEVEN:
            n = self.store.notify(self.reader, self.actor, reason,
                                  verb="repo.issue.comment",
                                  target_kind="repo",
                                  target_id="volmarr/pub#1",
                                  detail={"number": 1})
            self.assertEqual(n.reason, reason)
            self.assertEqual(n.recipient, "yrsa")
            self.assertEqual(n.actor, "volmarr")
            self.assertTrue(n.unread)
        stored = [r["reason"] for r in self.conn.execute(
            "SELECT reason FROM notifications ORDER BY id")]
        self.assertEqual(stored, list(SEVEN))
        listed = self.store.list_for_recipient(self.reader)
        self.assertEqual([n.reason for n in listed], list(SEVEN))

    def test_detail_roundtrips_and_actor_may_be_absent(self):
        n = self.store.notify(self.reader, None, "subscribed",
                              detail={"repo": "volmarr/pub"})
        self.assertEqual(n.detail, {"repo": "volmarr/pub"})
        self.assertEqual(n.actor, "")
        self.assertIn("Someone", n.words)

    def test_unknown_recipient_refused(self):
        ghost = type(self.reader)(id=99999, username="ghost",
                                  email=None, password_hash="x",
                                  created_at=0, is_admin=False,
                                  is_suspended=False) \
            if False else None
        with self.assertRaises(NotificationError) as cm:
            self.store.notify(ghost, self.actor, "mention")
        self.assertEqual(cm.exception.reason, "no_such_user")
        self.assertEqual(self._rows(), 0)

    # -- shown with every notification ------------------------------
    def test_reason_shown_in_words_and_renders(self):
        for reason in SEVEN:
            n = self.store.notify(self.reader, self.actor, reason,
                                  target_id="volmarr/pub#2")
            self.assertIn(NOTIFICATION_REASONS[reason], n.words)
            self.assertIn(NOTIFICATION_REASONS[reason],
                          render_notification(n))
        page = render_notifications(self.store.list_for_recipient(self.reader))
        for reason in SEVEN:
            self.assertIn(NOTIFICATION_REASONS[reason], page)

    def test_render_escapes_through_s010(self):
        n = self.store.notify(self.reader, self.actor, "mention",
                              target_id="<script>alert(1)</script>")
        html = render_notification(n)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_empty_render_teaches_the_model(self):
        html = render_notifications([])
        self.assertIn("No notifications yet", html)
        self.assertIn("reason", html)

    # -- filtering and read state --------------------------------------
    def test_filter_by_reason_and_unknown_filter_refused(self):
        self.store.notify(self.reader, self.actor, "mention")
        self.store.notify(self.reader, self.actor, "comment")
        self.store.notify(self.reader, self.actor, "mention")
        got = self.store.list_for_recipient(self.reader, reason="mention")
        self.assertEqual(len(got), 2)
        self.assertTrue(all(n.reason == "mention" for n in got))
        with self.assertRaises(NotificationError):
            self.store.list_for_recipient(self.reader, reason="bogus")

    def test_inbox_belongs_to_recipient_and_marking_is_owner_scoped(self):
        n = self.store.notify(self.reader, self.actor, "assign")
        self.assertEqual(self.store.list_for_recipient(self.other), [])
        self.assertFalse(self.store.mark_read(self.other, n.id))
        self.assertEqual(self.store.unread_count(self.reader), 1)
        self.assertTrue(self.store.mark_read(self.reader, n.id))
        self.assertFalse(self.store.mark_read(self.reader, n.id))
        self.assertEqual(self.store.unread_count(self.reader), 0)
        unread = self.store.list_for_recipient(self.reader, unread_only=True)
        self.assertEqual(unread, [])

    def test_mark_all_read_and_anonymous_refused(self):
        self.store.notify(self.reader, self.actor, "author")
        self.store.notify(self.reader, self.actor, "state-change")
        self.assertEqual(self.store.mark_all_read(self.reader), 2)
        self.assertEqual(self.store.unread_count(self.reader), 0)
        for call in (lambda: self.store.list_for_recipient(None),
                     lambda: self.store.unread_count(None),
                     lambda: self.store.mark_all_read(None)):
            with self.assertRaises(NotificationError) as cm:
                call()
            self.assertEqual(cm.exception.reason, "authentication_required")


if __name__ == "__main__":
    unittest.main()
