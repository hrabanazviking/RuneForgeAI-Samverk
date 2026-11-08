"""S-224 acceptance battery: inbox.

Acceptance (roadmap S-224): unread list with
filters by reason and repo, mark done/saved,
keyboard triage; empty state teaches the model in
one screen.

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
from samverk.inbox import (
    INBOX_LESSONS, TRIAGE_KEYS, InboxError, InboxStore, TriageState,
    apply_triage, empty_state, move_cursor, render_inbox,
    render_inbox_entry, render_inbox_lessons, repo_of,
    triage_manifest, validate_repo_filter)
from samverk.notification_reasons import (
    NOTIFICATION_REASONS, NotificationStore)

SEVEN = ("mention", "assign", "review-requested", "author",
         "comment", "state-change", "subscribed")


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class InboxTests(unittest.TestCase):
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
        self.notes = NotificationStore(self.conn, self.accounts, time_fn=self.clock)
        self.inbox = InboxStore(self.conn, self.accounts, time_fn=self.clock)

    def _notify(self, reason="mention", target_id="volmarr/pub#1",
                detail=None, recipient=None):
        return self.notes.notify(
            recipient or self.reader, self.actor, reason,
            verb="repo.issue.comment", target_kind="repo",
            target_id=target_id, detail=detail or {})

    def _audit_rows(self):
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    # -- pins -------------------------------------------------
    def test_pins_schema_88_taxonomy_127(self):
        self.assertEqual(schema_version(self.conn), 88)
        self.assertEqual(db.MIGRATIONS[-1][0], 88)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 127)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 31)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 83)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("notifications", tables)
        self.assertIn("inbox_triage", tables)

    # -- repo derivation ---------------------------------------
    def test_repo_derived_from_target_and_detail(self):
        self.assertEqual(repo_of("repo", "volmarr/pub#1", {}),
                         "volmarr/pub")
        self.assertEqual(repo_of("repo", "volmarr/pub", {}),
                         "volmarr/pub")
        self.assertEqual(repo_of("repo", "", {"repo": "yrsa/forge"}),
                         "yrsa/forge")
        self.assertEqual(repo_of("user", "yrsa", {}), "")
        self.assertEqual(repo_of("", "", {}), "")
        self.assertEqual(repo_of("repo", "volmarr/pub#1",
                                 {"repo": "not a repo"}),
                         "volmarr/pub")

    def test_repo_filter_judged_at_the_door(self):
        self.assertEqual(validate_repo_filter("volmarr/pub"),
                         "volmarr/pub")
        for bad in ("pub", "volmarr/", "/pub", "a/b/c", "",
                    "volmarr / pub", None, 3):
            with self.assertRaises(InboxError) as cm:
                validate_repo_filter(bad)
            self.assertEqual(cm.exception.reason, "repo_invalid")

    # -- the working list and its filters -------------------------
    def test_list_is_recipients_own_newest_first(self):
        a = self._notify("mention")
        b = self._notify("comment", target_id="yrsa/forge#2")
        got = self.inbox.list_inbox(self.reader)
        self.assertEqual([e.id for e in got], [b.id, a.id])
        self.assertTrue(all(e.unread for e in got))
        self.assertEqual(got[0].repo, "yrsa/forge")
        self.assertEqual(self.inbox.list_inbox(self.other), [])
        self.assertEqual(self.inbox.unread_count(self.reader), 2)

    def test_filter_by_reason_and_unknown_reason_refused(self):
        self._notify("mention")
        self._notify("comment")
        self._notify("mention", target_id="yrsa/forge#9")
        got = self.inbox.list_inbox(self.reader, reason="mention")
        self.assertEqual(len(got), 2)
        self.assertTrue(all(e.reason == "mention" for e in got))
        with self.assertRaises(InboxError) as cm:
            self.inbox.list_inbox(self.reader, reason="bogus")
        self.assertEqual(cm.exception.reason, "reason_invalid")

    def test_filter_by_repo_and_both_filters_together(self):
        self._notify("mention", target_id="volmarr/pub#1")
        self._notify("mention", target_id="yrsa/forge#2")
        self._notify("comment", target_id="yrsa/forge#3")
        self._notify("assign", target_id="",
                     detail={"repo": "yrsa/forge"})
        by_repo = self.inbox.list_inbox(self.reader, repo="yrsa/forge")
        self.assertEqual(len(by_repo), 3)
        both = self.inbox.list_inbox(self.reader, reason="mention",
                                     repo="yrsa/forge")
        self.assertEqual(len(both), 1)
        self.assertEqual(self.inbox.repos(self.reader),
                         ("volmarr/pub", "yrsa/forge"))
        with self.assertRaises(InboxError):
            self.inbox.list_inbox(self.reader, repo="justname")

    # -- done: the only exit ---------------------------------------
    def test_mark_done_exits_and_done_means_read(self):
        n = self._notify("assign")
        self.assertTrue(self.inbox.mark_done(self.reader, n.id))
        self.assertEqual(self.inbox.list_inbox(self.reader), [])
        self.assertEqual(self.inbox.unread_count(self.reader), 0)
        self.assertEqual(self.notes.unread_count(self.reader), 0)
        done = self.inbox.list_inbox(self.reader, include_done=True)
        self.assertEqual(len(done), 1)
        self.assertTrue(done[0].done)
        self.assertFalse(done[0].unread)
        self.assertFalse(self.inbox.mark_done(self.reader, n.id))
        counts = self.inbox.counts(self.reader)
        self.assertEqual((counts.unread, counts.done), (0, 1))

    def test_reopen_restores_unread_as_it_was(self):
        n = self._notify("author")
        self.assertTrue(self.inbox.mark_done(self.reader, n.id))
        self.assertTrue(self.inbox.reopen(self.reader, n.id))
        got = self.inbox.list_inbox(self.reader)
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].unread)
        self.assertEqual(self.notes.unread_count(self.reader), 1)
        self.assertFalse(self.inbox.reopen(self.reader, n.id))

    # -- saved: a flag, not an exit ----------------------------------
    def test_saved_is_distinct_from_done_and_read(self):
        n = self._notify("comment")
        self.assertTrue(self.inbox.set_saved(self.reader, n.id, True))
        self.assertFalse(self.inbox.set_saved(self.reader, n.id, True))
        got = self.inbox.list_inbox(self.reader)
        self.assertEqual(len(got), 1)          # still in the inbox
        self.assertTrue(got[0].saved)
        self.assertTrue(got[0].unread)         # saving is not reading
        saved = self.inbox.list_inbox(self.reader, saved_only=True)
        self.assertEqual([e.id for e in saved], [n.id])
        self.assertEqual(self.inbox.counts(self.reader).saved, 1)
        # done keeps the saved flag, honestly separate
        self.assertTrue(self.inbox.mark_done(self.reader, n.id))
        kept = self.inbox.list_inbox(self.reader, saved_only=True,
                                     include_done=True)
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0].saved and kept[0].done)
        self.assertEqual(
            self.inbox.list_inbox(self.reader, saved_only=True), [])
        # unsaving a done row works too; toggle flips either way
        self.assertTrue(self.inbox.toggle_saved(self.reader, n.id))
        entry = self.inbox.get_entry(self.reader, n.id)
        self.assertFalse(entry.saved)
        self.assertTrue(self.inbox.toggle_saved(self.reader, n.id))
        self.assertTrue(self.inbox.get_entry(self.reader, n.id).saved)

    # -- ownership -----------------------------------------------------
    def test_inbox_belongs_to_recipient_on_every_face(self):
        n = self._notify("mention")
        self.assertIsNone(self.inbox.get_entry(self.other, n.id))
        self.assertFalse(self.inbox.mark_done(self.other, n.id))
        self.assertFalse(self.inbox.reopen(self.other, n.id))
        self.assertFalse(self.inbox.set_saved(self.other, n.id, True))
        self.assertFalse(self.inbox.toggle_saved(self.other, n.id))
        self.assertEqual(self.inbox.unread_count(self.reader), 1)
        entry = self.inbox.get_entry(self.reader, n.id)
        self.assertFalse(entry.done or entry.saved)
        for call in (lambda: self.inbox.list_inbox(None),
                     lambda: self.inbox.counts(None),
                     lambda: self.inbox.repos(None),
                     lambda: self.inbox.mark_done(None, n.id),
                     lambda: self.inbox.set_saved(None, n.id, True)):
            with self.assertRaises(InboxError) as cm:
                call()
            self.assertEqual(cm.exception.reason,
                             "authentication_required")

    def test_triage_writes_no_audit_event(self):
        n = self._notify("state-change")
        before = self._audit_rows()
        self.inbox.set_saved(self.reader, n.id, True)
        self.inbox.mark_done(self.reader, n.id)
        self.inbox.reopen(self.reader, n.id)
        self.assertEqual(self._audit_rows(), before)

    # -- keyboard triage ------------------------------------------------
    def test_triage_registry_is_law(self):
        keys = [k.keys for k in TRIAGE_KEYS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(not k.active_when_typing
                            for k in TRIAGE_KEYS))
        self.assertTrue(all(k.context == "inbox" for k in TRIAGE_KEYS))
        manifest = triage_manifest()
        self.assertEqual([m["keys"] for m in manifest], keys)
        self.assertEqual({m["action"] for m in manifest},
                         {k.action for k in TRIAGE_KEYS})

    def test_apply_triage_transitions_are_pure_and_distinct(self):
        fresh = TriageState()
        done = apply_triage(fresh, "mark_done")
        self.assertEqual(done, TriageState(read=True, done=True))
        self.assertEqual(apply_triage(done, "reopen"), fresh)
        saved = apply_triage(fresh, "toggle_saved")
        self.assertEqual(saved, TriageState(saved=True))
        self.assertEqual(apply_triage(saved, "toggle_saved"), fresh)
        self.assertEqual(apply_triage(done, "toggle_saved"),
                         TriageState(read=True, done=True, saved=True))
        opened = apply_triage(fresh, "open_selected")
        self.assertEqual(opened, TriageState(read=True))
        self.assertEqual(apply_triage(fresh, "move_next"), fresh)
        with self.assertRaises(InboxError) as cm:
            apply_triage(fresh, "delete_everything")
        self.assertEqual(cm.exception.reason, "triage_action_invalid")

    def test_move_cursor_clamps_at_both_ends(self):
        self.assertEqual(move_cursor(0, 0, "move_next"), 0)
        self.assertEqual(move_cursor(0, 3, "move_previous"), 0)
        self.assertEqual(move_cursor(0, 3, "move_next"), 1)
        self.assertEqual(move_cursor(2, 3, "move_next"), 2)
        self.assertEqual(move_cursor(9, 3, "move_previous"), 1)
        self.assertEqual(move_cursor(1, 3, "open_selected"), 1)

    def test_store_agrees_with_pure_triage(self):
        n = self._notify("review-requested")
        entry = self.inbox.get_entry(self.reader, n.id)
        after = apply_triage(entry.state, "toggle_saved")
        self.assertTrue(self.inbox.toggle_saved(self.reader, n.id))
        self.assertEqual(
            self.inbox.get_entry(self.reader, n.id).state, after)
        after = apply_triage(after, "mark_done")
        self.assertTrue(self.inbox.mark_done(self.reader, n.id))
        self.assertEqual(
            self.inbox.get_entry(self.reader, n.id).state, after)

    # -- renders and the teaching empty state -----------------------------
    def test_empty_state_teaches_the_model_in_one_screen(self):
        lessons = empty_state()
        self.assertEqual([l.title for l in lessons],
                         [t for t, _ in INBOX_LESSONS])
        self.assertEqual(len(lessons), 4)
        html = render_inbox([])
        self.assertEqual(html, render_inbox_lessons())
        for reason in SEVEN:
            self.assertIn(reason, html)
            self.assertIn(NOTIFICATION_REASONS[reason], html)
        for key in TRIAGE_KEYS:
            self.assertIn(key.keys, html)
            self.assertIn(key.description, html)
        self.assertIn("Done is the exit", html)
        self.assertIn("Saved is a flag", html)
        self.assertIn("owner/name", html)

    def test_render_says_reason_repo_and_standing_outright(self):
        n = self._notify("mention", target_id="volmarr/pub#4")
        self.inbox.set_saved(self.reader, n.id, True)
        entry = self.inbox.get_entry(self.reader, n.id)
        html = render_inbox_entry(entry)
        self.assertIn(NOTIFICATION_REASONS["mention"], html)
        self.assertIn("volmarr/pub", html)
        self.assertIn("saved", html)
        self.assertIn("unread", entry.words)

    def test_render_escapes_through_s010(self):
        n = self._notify("mention",
                         target_id="<script>alert(1)</script>/x#1")
        entry = self.inbox.get_entry(self.reader, n.id)
        html = render_inbox([entry])
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_filtered_empty_says_so_and_names_the_way_back(self):
        self._notify("mention")
        html = render_inbox(
            self.inbox.list_inbox(self.reader, reason="comment"),
            filtered=True)
        self.assertIn("No notifications match this filter", html)
        self.assertIn("Clear the reason", html)
        self.assertNotIn("Your inbox is empty", html)


if __name__ == "__main__":
    unittest.main()
