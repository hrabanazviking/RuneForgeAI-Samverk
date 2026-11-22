"""S-356 acceptance battery: instance audit view.

Acceptance (roadmap S-356): Instance audit
view -- S-309 at instance scope, chain-verified.

The centre is samverk/instance_audit_view.py:
the dedicated instance face over S-309's
instance view and S-007's hash chain -- site
admins only (uniform audit_not_found), S-309's
filters, honest windowing over the filtered
rows, breakdown counts over the find, and
verify_chain recomputed whole on every read:
verified with the count, or broken naming the
first broken entry (a tampered row is proven
to read broken at the right place, never a
false green). No migration by this slice (schema 140 stands,
moved by S-355); taxonomy 142 (34/92/16).

Counted with: python3 -m unittest tests.test_instance_audit_view
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.audit_log_ui import AuditLogUIError
from samverk.db import schema_version
from samverk.instance_audit_view import (
    InstanceAuditViewError, InstanceAuditViewStore,
    audit_instance_audit_view, decide_window,
    render_instance_audit_page, summarise_breakdowns)
from samverk.repositories import RepositoryStore

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class PureLawTests(unittest.TestCase):
    def test_window_bounds_and_flags(self):
        w = decide_window(0, 2, 5)
        self.assertEqual((w["start"], w["end"], w["shown"]), (0, 2, 2))
        self.assertFalse(w["has_before"]); self.assertTrue(w["has_after"])
        w = decide_window(4, 2, 5)
        self.assertEqual((w["start"], w["end"]), (4, 5))
        self.assertTrue(w["has_before"]); self.assertFalse(w["has_after"])

    def test_window_default_limit(self):
        self.assertEqual(decide_window(0, None, 3)["limit"], 50)

    def test_window_past_end_is_empty_not_error(self):
        w = decide_window(99, 10, 5)
        self.assertEqual(w["shown"], 0)
        self.assertTrue(w["has_before"]); self.assertFalse(w["has_after"])

    def test_window_invalid_refused(self):
        for bad in ((-1, 10), (0, 0), (0, 1001), ("0", 10), (0, "x"), (True, 10)):
            with self.assertRaises(InstanceAuditViewError) as ctx:
                decide_window(bad[0], bad[1], 5)
            self.assertEqual(ctx.exception.reason, "window_invalid")

    def test_breakdowns_count_rows(self):
        class E:
            def __init__(s, u, a, k, o):
                s.actor_username, s.action, s.target_kind, s.outcome = u, a, k, o
        rows = [E("yrsa", "repo.push", "repo", "success"),
                E("yrsa", "repo.push", "repo", "failure"),
                E(None, "auth.login.success", "user", "success")]
        b = summarise_breakdowns(rows)
        self.assertEqual(b["by_actor"], {"an unnamed actor": 1, "yrsa": 2})
        self.assertEqual(b["by_action"]["repo.push"], 2)
        self.assertEqual(b["by_outcome"], {"failure": 1, "success": 2})
        self.assertEqual(b["by_target_kind"], {"repo": 2, "user": 1})


class InstanceAuditTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=self.clock)
        self.creator = self.accounts.register("volmarr", PW)
        self.member = self.accounts.register("yrsa", PW)
        admin = self.accounts.register("sitemod", PW)
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (admin.id,))
        self.admin = self.accounts.get_by_id(admin.id)
        self.repos = RepositoryStore(self.conn, self.root, self.accounts, audit=self.audit, time_fn=self.clock)
        self.store = InstanceAuditViewStore(self.conn, self.repos, self.accounts, time_fn=self.clock)

    def _append(self, action, target_kind, target_id, actor=None, outcome="success", detail=None):
        return self.audit.append(actor_kind="user", actor_id=(actor.id if actor else self.creator.id), action=action, target_kind=target_kind, target_id=target_id, outcome=outcome, detail=detail)

    def seed(self):
        self._append("repo.push", "repo", "crew/alpha", actor=self.member, detail={"refs": ["main"]})
        self._append("repo.push", "repo", "other/beta", outcome="failure")
        self._append("auth.login.success", "user", "yrsa", actor=self.member)

    def _rows(self):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]

    def test_lists_events_across_instance(self):
        self.seed()
        page = self.store.page(self.admin)
        self.assertEqual(page.total_in_scope, self._rows())
        self.assertEqual(page.total_filtered, self._rows())
        targets = {e.target_id for e in page.entries}
        self.assertIn("crew/alpha", targets); self.assertIn("other/beta", targets); self.assertIn("yrsa", targets)
        actors = {e.actor_username for e in page.entries}
        self.assertIn("yrsa", actors); self.assertIn("volmarr", actors)

    def test_non_admin_and_anonymous_refused(self):
        self.seed()
        for viewer in (self.creator, self.member, None):
            with self.assertRaises(AuditLogUIError) as ctx:
                self.store.page(viewer)
            self.assertEqual(ctx.exception.reason, "audit_not_found")
            with self.assertRaises(AuditLogUIError):
                self.store.verification(viewer)
            with self.assertRaises(AuditLogUIError):
                self.store.export(viewer)

    def test_filters_by_actor_action_kind_object(self):
        self.seed()
        by_actor = self.store.page(self.admin, actor_id=self.member.id)
        self.assertTrue(by_actor.entries)
        self.assertTrue(all(e.actor_id == self.member.id for e in by_actor.entries))
        by_action = self.store.page(self.admin, action="repo.push")
        self.assertTrue(all(e.action == "repo.push" for e in by_action.entries))
        self.assertGreaterEqual(by_action.total_filtered, 2)
        by_kind = self.store.page(self.admin, target_kind="user")
        self.assertTrue(all(e.target_kind == "user" for e in by_kind.entries))
        by_object = self.store.page(self.admin, query="other/beta")
        self.assertEqual([e.target_id for e in by_object.entries], ["other/beta"])
        by_outcome = self.store.page(self.admin, outcome="failure")
        self.assertTrue(all(e.outcome == "failure" for e in by_outcome.entries))

    def test_unknown_action_filter_refused(self):
        with self.assertRaises(AuditLogUIError) as ctx:
            self.store.page(self.admin, action="repo.nope")
        self.assertEqual(ctx.exception.reason, "filter_invalid")

    def test_chain_verified_with_count(self):
        self.seed()
        page = self.store.page(self.admin)
        self.assertTrue(page.chain.ok)
        self.assertEqual(page.chain.status, "verified")
        self.assertEqual(page.chain.entries_checked, self._rows())
        self.assertIn("Chain verified", page.headline_words)
        status = self.store.verification(self.admin)
        self.assertTrue(status.ok); self.assertEqual(status.entries_checked, self._rows())

    def test_tampered_row_reports_break_at_right_place(self):
        self.seed()
        target_seq = 2
        with self.conn:
            self.conn.execute("UPDATE audit_log SET outcome = 'failure' WHERE seq = ?", (target_seq,))
        page = self.store.page(self.admin)
        self.assertFalse(page.chain.ok)
        self.assertEqual(page.chain.status, "broken")
        self.assertEqual(page.chain.first_bad_seq, target_seq)
        self.assertIn(f"Chain broken at entry {target_seq}", page.headline_words)
        html = render_instance_audit_page(page)
        self.assertIn(f"Chain broken at entry {target_seq}", html)
        self.assertNotIn("Chain verified", html.split("Chain broken")[0][-200:])

    def test_windowing_pages_in_chain_order(self):
        self.seed()
        first = self.store.page(self.admin, offset=0, limit=2)
        second = self.store.page(self.admin, offset=2, limit=2)
        self.assertEqual(first.shown, 2); self.assertTrue(first.window["has_after"])
        seqs = [e.seq for e in first.entries] + [e.seq for e in second.entries]
        self.assertEqual(seqs, sorted(seqs)); self.assertEqual(len(set(seqs)), len(seqs))
        self.assertEqual(first.total_filtered, second.total_filtered)
        past = self.store.page(self.admin, offset=10000, limit=5)
        self.assertEqual(past.shown, 0); self.assertIn("empty", past.headline_words)

    def test_breakdowns_describe_filtered_find(self):
        self.seed()
        page = self.store.page(self.admin, action="repo.push", limit=1)
        self.assertEqual(page.breakdowns["by_action"], {"repo.push": page.total_filtered})
        self.assertEqual(page.shown, 1)

    def test_render_shows_status_window_breakdowns(self):
        self.seed()
        html = render_instance_audit_page(self.store.page(self.admin))
        self.assertIn("Chain verified", html)
        self.assertIn("Window:", html); self.assertIn("By outcome", html)
        self.assertIn("repo push", html)

    def test_export_goes_through_door(self):
        self.seed()
        text = self.store.export(self.admin, fmt="json", action="repo.push")
        self.assertIn("repo.push", text); self.assertIn("verified", text)

    def test_audit_clean_and_pins(self):
        self.seed()
        self.assertEqual(audit_instance_audit_view(self.conn), [])
        self.assertEqual(schema_version(self.conn), 140)

    def test_read_writes_nothing(self):
        self.seed()
        before = self._rows()
        self.store.page(self.admin); self.store.verification(self.admin)
        self.assertEqual(self._rows(), before)


if __name__ == "__main__":
    unittest.main()
