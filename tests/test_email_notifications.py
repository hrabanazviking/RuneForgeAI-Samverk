"""S-227 acceptance battery: email notifications.

Acceptance (roadmap S-227): email notifications --
via instance SMTP when configured: per-event or
digest, signed unsubscribe links, no email when
SMTP is absent (in-app still works).

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
    EmailError, EmailNotificationStore, decide_email,
    make_unsubscribe_token, parse_unsubscribe_token,
    render_email_deliveries, render_email_delivery,
    smtp_config_from, smtp_mailer, validate_email_mode,
    validate_scope)
from samverk.notification_reasons import (
    Notification, NotificationStore)

KEY = b"unit-test-signing-key"


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class FakeMailer:
    def __init__(self):
        self.sent = []
        self.fail = False
    def __call__(self, address, subject, body):
        if self.fail:
            raise OSError("smtp down")
        self.sent.append((address, subject, body))


class EmailNotificationTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.volmarr = self.accounts.register("volmarr", "correct horse battery")
        self.yrsa = self.accounts.register("yrsa", "correct horse battery", "yrsa@example.com")
        self.bryn = self.accounts.register("brynhild", "correct horse battery", "bryn@example.com")
        self.notes = NotificationStore(self.conn, self.accounts, time_fn=self.clock)
        self.mailer = FakeMailer()

    # -- fixtures -------------------------------------------------
    def _store(self, mailer="default", mode="per-event"):
        return EmailNotificationStore(
            self.conn, self.accounts, self.notes,
            mailer=self.mailer if mailer == "default" else mailer,
            signing_key=KEY, mode=mode, time_fn=self.clock)

    def _note(self, recipient=None, reason="mention", target="crew/anvil#1"):
        return self.notes.notify(
            recipient or self.yrsa, self.volmarr, reason,
            verb="issue.create", target_kind="issue",
            target_id=target, detail={"repo": "crew/anvil"})

    def _rows(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM email_deliveries").fetchone()["n"]

    # -- pins -------------------------------------------------------
    def test_pins_schema_99_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 124)
        self.assertEqual(db.MIGRATIONS[-1][0], 124)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("email_deliveries", tables)
        self.assertIn("email_optouts", tables)
        self.assertIn("notifications", tables)

    def test_fresh_database_migrates_to_93(self):
        path = self.root / "fresh.db"
        conn = db.connect(path); self.addCleanup(conn.close)
        self.assertEqual(db.migrate(conn), 124)
        self.assertEqual(db.schema_version(conn), 124)

    # -- pure law -----------------------------------------------------
    def test_mode_door(self):
        self.assertEqual(validate_email_mode("per-event"), "per-event")
        self.assertEqual(validate_email_mode("digest"), "digest")
        for bad in ("weekly", "", None, 42):
            with self.assertRaises(EmailError) as cm:
                validate_email_mode(bad)
            self.assertEqual(cm.exception.reason, "email_mode_invalid")

    def test_smtp_config_from_absent_half_and_full(self):
        self.assertIsNone(smtp_config_from(None))
        self.assertIsNone(smtp_config_from({}))
        self.assertIsNone(smtp_config_from({"host": "", "port": 0, "from_address": ""}))
        for half in ({"host": "mail.example"},
                     {"host": "mail.example", "port": 587},
                     {"from_address": "forge@example.com", "port": 25}):
            with self.assertRaises(EmailError) as cm:
                smtp_config_from(half)
            self.assertEqual(cm.exception.reason, "smtp_config_invalid")
        cfg = smtp_config_from({"host": "mail.example", "port": "587",
                                "from_address": "forge@example.com", "use_tls": True})
        self.assertTrue(cfg.configured)
        self.assertEqual(cfg.port, 587)
        self.assertTrue(cfg.use_tls)
        self.assertTrue(callable(smtp_mailer(cfg)))

    def test_decide_email_matrix(self):
        base = dict(email_address="yrsa@example.com", mode="per-event",
                    unsubscribed_all=False, unsubscribed_reason=False)
        self.assertEqual(decide_email(smtp_configured=False, **base), ("skip", "smtp_absent"))
        self.assertEqual(decide_email(smtp_configured=True, **{**base, "email_address": None}),
                         ("skip", "no_email_address"))
        self.assertEqual(decide_email(smtp_configured=True, **{**base, "unsubscribed_reason": True}),
                         ("skip", "unsubscribed"))
        self.assertEqual(decide_email(smtp_configured=True, **{**base, "unsubscribed_all": True}),
                         ("skip", "unsubscribed"))
        self.assertEqual(decide_email(smtp_configured=True, **base), ("send", "per_event"))
        self.assertEqual(decide_email(smtp_configured=True, **{**base, "mode": "digest"}),
                         ("queue", "digest"))
        with self.assertRaises(EmailError):
            decide_email(smtp_configured=True, **{**base, "mode": "hourly"})

    def test_scope_door(self):
        self.assertEqual(validate_scope("all"), "all")
        self.assertEqual(validate_scope("mention"), "mention")
        with self.assertRaises(EmailError) as cm:
            validate_scope("everything")
        self.assertEqual(cm.exception.reason, "scope_invalid")

    def test_token_roundtrip_and_forgery(self):
        token = make_unsubscribe_token(KEY, self.yrsa.id, "mention")
        self.assertEqual(parse_unsubscribe_token(KEY, token), (self.yrsa.id, "mention"))
        all_token = make_unsubscribe_token(KEY, self.yrsa.id, "all")
        self.assertEqual(parse_unsubscribe_token(KEY, all_token), (self.yrsa.id, "all"))
        self.assertIsNone(parse_unsubscribe_token(b"other-key", token))
        head, _, sig = token.partition(".")
        self.assertIsNone(parse_unsubscribe_token(KEY, head + ".AAAA" + sig[4:]))
        self.assertIsNone(parse_unsubscribe_token(KEY, "not-a-token"))
        self.assertIsNone(parse_unsubscribe_token(KEY, None))
        self.assertIsNone(parse_unsubscribe_token(KEY, ""))
        forged = make_unsubscribe_token(KEY, self.yrsa.id, "comment")
        self.assertNotEqual(forged, token)

    def test_signing_key_required(self):
        with self.assertRaises(EmailError) as cm:
            EmailNotificationStore(self.conn, self.accounts, self.notes,
                                   mailer=self.mailer, signing_key=b"")
        self.assertEqual(cm.exception.reason, "signing_key_required")

    # -- per-event delivery -------------------------------------------
    def test_per_event_sends_one_letter_with_signed_links(self):
        store = self._store()
        note = self._note()
        delivery = store.deliver(note)
        self.assertEqual(delivery.status, "sent")
        self.assertEqual(delivery.why, "per_event")
        self.assertEqual(delivery.mode, "per-event")
        self.assertEqual(delivery.email_address, "yrsa@example.com")
        self.assertIsNotNone(delivery.sent_at)
        self.assertEqual(len(self.mailer.sent), 1)
        address, subject, body = self.mailer.sent[0]
        self.assertEqual(address, "yrsa@example.com")
        self.assertIn("you were mentioned", subject)
        self.assertIn("you were mentioned", body)
        self.assertIn("/unsubscribe/", body)
        token_lines = [ln for ln in body.splitlines() if "/unsubscribe/" in ln]
        self.assertEqual(len(token_lines), 2)
        reason_token = token_lines[0].rsplit("/unsubscribe/", 1)[1].strip()
        self.assertEqual(parse_unsubscribe_token(KEY, reason_token),
                         (self.yrsa.id, "mention"))
        all_token = token_lines[1].rsplit("/unsubscribe/", 1)[1].strip()
        self.assertEqual(parse_unsubscribe_token(KEY, all_token),
                         (self.yrsa.id, "all"))

    def test_no_smtp_skips_and_in_app_still_works(self):
        store = self._store(mailer=None)
        self.assertFalse(store.smtp_configured)
        note = self._note()
        delivery = store.deliver(note)
        self.assertEqual(delivery.status, "skipped")
        self.assertEqual(delivery.why, "smtp_absent")
        self.assertIsNone(delivery.sent_at)
        inbox = self.notes.list_for_recipient(self.yrsa)
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0].reason, "mention")
        self.assertEqual(self.notes.unread_count(self.yrsa), 1)

    def test_no_email_address_skips(self):
        store = self._store()
        note = self._note(recipient=self.volmarr)
        delivery = store.deliver(note)
        self.assertEqual(delivery.status, "skipped")
        self.assertEqual(delivery.why, "no_email_address")
        self.assertEqual(self.mailer.sent, [])

    def test_deliver_is_exactly_once(self):
        store = self._store()
        note = self._note()
        first = store.deliver(note)
        second = store.deliver(note)
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(self.mailer.sent), 1)
        self.assertEqual(self._rows(), 1)

    def test_transport_failure_is_recorded_never_raised(self):
        self.mailer.fail = True
        store = self._store()
        note = self._note()
        delivery = store.deliver(note)
        self.assertEqual(delivery.status, "failed")
        self.assertIsNone(delivery.sent_at)
        self.assertEqual(len(self.notes.list_for_recipient(self.yrsa)), 1)

    def test_deliver_unknown_recipient_refused(self):
        store = self._store()
        ghost = Notification(
            id=9999, recipient_id=9999, recipient="ghost",
            actor_id=None, actor="", reason="mention", verb="",
            target_kind="issue", target_id="crew/anvil#9",
            detail={}, created_at=1_700_000_000, read_at=None)
        with self.assertRaises(EmailError) as cm:
            store.deliver(ghost)
        self.assertEqual(cm.exception.reason, "no_such_user")
        self.assertEqual(self._rows(), 0)

    # -- unsubscribe ----------------------------------------------------
    def test_unsubscribed_reason_skips_only_that_reason(self):
        store = self._store()
        store.opt_out(self.yrsa, "mention")
        skipped = store.deliver(self._note(reason="mention"))
        self.assertEqual((skipped.status, skipped.why), ("skipped", "unsubscribed"))
        sent = store.deliver(self._note(reason="comment", target="crew/anvil#2"))
        self.assertEqual(sent.status, "sent")
        self.assertEqual(len(self.mailer.sent), 1)

    def test_unsubscribed_all_skips_everything(self):
        store = self._store()
        store.opt_out(self.yrsa, "all")
        for reason, target in (("mention", "crew/anvil#1"), ("assign", "crew/anvil#2")):
            d = store.deliver(self._note(reason=reason, target=target))
            self.assertEqual((d.status, d.why), ("skipped", "unsubscribed"))
        self.assertEqual(self.mailer.sent, [])

    def test_signed_link_unsubscribes_and_resubscribe_restores(self):
        store = self._store()
        token = make_unsubscribe_token(KEY, self.yrsa.id, "mention")
        self.assertEqual(store.unsubscribe(token), (self.yrsa.id, "mention"))
        self.assertTrue(store.is_unsubscribed(self.yrsa.id, "mention"))
        self.assertFalse(store.is_unsubscribed(self.yrsa.id, "comment"))
        self.assertEqual(store.unsubscribe(token), (self.yrsa.id, "mention"))  # idempotent
        rows = self.conn.execute("SELECT COUNT(*) AS n FROM email_optouts").fetchone()["n"]
        self.assertEqual(rows, 1)
        d = store.deliver(self._note())
        self.assertEqual(d.status, "skipped")
        self.assertTrue(store.resubscribe(self.yrsa, "mention"))
        self.assertFalse(store.resubscribe(self.yrsa, "mention"))
        d2 = store.deliver(self._note(target="crew/anvil#7"))
        self.assertEqual(d2.status, "sent")

    def test_unsubscribe_refusals_are_one_generic_kind(self):
        store = self._store()
        for bad in ("garbage", "", None, 42,
                    make_unsubscribe_token(b"other-key", self.yrsa.id, "all"),
                    make_unsubscribe_token(KEY, 9999, "all")):
            with self.assertRaises(EmailError) as cm:
                store.unsubscribe(bad)
            self.assertEqual(cm.exception.reason, "unsubscribe_token_invalid")

    def test_opt_out_faces_require_sign_in(self):
        store = self._store()
        with self.assertRaises(EmailError) as cm:
            store.opt_out(None, "all")
        self.assertEqual(cm.exception.reason, "authentication_required")
        with self.assertRaises(EmailError):
            store.resubscribe(None, "all")
        with self.assertRaises(EmailError):
            store.flush_digest(None)

    # -- digest -----------------------------------------------------------
    def test_digest_queues_then_flush_sends_one_letter(self):
        store = self._store(mode="digest")
        first = store.deliver(self._note(reason="mention"))
        second = store.deliver(self._note(reason="comment", target="crew/anvil#2"))
        self.assertEqual((first.status, first.why), ("queued", "digest"))
        self.assertEqual(second.status, "queued")
        self.assertEqual(self.mailer.sent, [])
        self.assertEqual(store.pending_digest_count(self.yrsa), 2)
        self.assertEqual(store.flush_digest(self.yrsa), 2)
        self.assertEqual(len(self.mailer.sent), 1)
        address, subject, body = self.mailer.sent[0]
        self.assertEqual(address, "yrsa@example.com")
        self.assertIn("2 notifications", subject)
        self.assertIn("you were mentioned", body)
        self.assertIn("there is a new comment", body)
        self.assertIn("/unsubscribe/", body)
        self.assertEqual(store.pending_digest_count(self.yrsa), 0)
        statuses = [d.status for d in store.deliveries_for(self.yrsa)]
        self.assertEqual(statuses, ["sent", "sent"])
        self.assertEqual(store.flush_digest(self.yrsa), 0)
        self.assertEqual(len(self.mailer.sent), 1)

    def test_digest_flush_rejudges_unsubscribe(self):
        store = self._store(mode="digest")
        store.deliver(self._note(reason="mention"))
        store.deliver(self._note(reason="comment", target="crew/anvil#2"))
        store.opt_out(self.yrsa, "mention")
        self.assertEqual(store.flush_digest(self.yrsa), 1)
        self.assertEqual(len(self.mailer.sent), 1)
        rows = store.deliveries_for(self.yrsa)
        self.assertEqual(rows[0].status, "skipped")
        self.assertEqual(rows[0].why, "unsubscribed")
        self.assertEqual(rows[1].status, "sent")
        _, _, body = self.mailer.sent[0]
        self.assertNotIn("you were mentioned", body)
        self.assertIn("there is a new comment", body)

    def test_digest_flush_failure_leaves_queue_standing(self):
        store = self._store(mode="digest")
        store.deliver(self._note())
        self.mailer.fail = True
        self.assertEqual(store.flush_digest(self.yrsa), 0)
        self.assertEqual(store.pending_digest_count(self.yrsa), 1)
        self.mailer.fail = False
        self.assertEqual(store.flush_digest(self.yrsa), 1)
        self.assertEqual(len(self.mailer.sent), 1)

    def test_digest_with_no_smtp_queues_nothing(self):
        store = self._store(mailer=None, mode="digest")
        delivery = store.deliver(self._note())
        self.assertEqual((delivery.status, delivery.why), ("skipped", "smtp_absent"))
        self.assertEqual(store.flush_digest(self.yrsa), 0)

    # -- reads, audit, rendering -------------------------------------------
    def test_deliveries_for_is_recipient_scoped(self):
        store = self._store()
        store.deliver(self._note())
        store.deliver(self._note(recipient=self.bryn, target="crew/anvil#3"))
        self.assertEqual(len(store.deliveries_for(self.yrsa)), 1)
        self.assertEqual(len(store.deliveries_for(self.bryn)), 1)
        self.assertEqual(store.deliveries_for(None), [])
        self.assertEqual(store.pending_digest_count(None), 0)
        self.assertEqual(store.deliveries_for(self.volmarr), [])

    def test_email_work_audits_nothing(self):
        store = self._store(mode="digest")
        before = self.conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        store.deliver(self._note())
        store.unsubscribe(make_unsubscribe_token(KEY, self.yrsa.id, "all"))
        store.flush_digest(self.yrsa)
        after = self.conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.assertEqual(after, before)

    def test_renderers_say_status_and_escape(self):
        store = self._store()
        delivery = store.deliver(self._note())
        html = render_email_delivery(delivery)
        self.assertIn("sent", html)
        self.assertIn("one email per notification", html)
        page = render_email_deliveries([delivery])
        self.assertIn("email-deliveries", page)
        empty = render_email_deliveries([])
        self.assertIn("No notification email yet", empty)
        self.assertIn("SMTP", empty)
        self.assertIn("unsubscribe", empty)


if __name__ == "__main__":
    unittest.main()
