"""S-355 acceptance battery: the abuse queue.

Acceptance (roadmap S-355): user reports on content and
accounts land in one admin queue with the audit context
attached.

The centre is samverk/abuse_queue.py: the pure judges
(validate_report, decide_transition, is_duplicate), the
AbuseQueue service over migration 140's abuse_reports
table, filing against real seams (real users, repository,
issue and comment rows; the real AuditLog whose context
the report attaches by sequence reference), admin-only
queue working (acknowledge/resolve/dismiss, each
audit-logged under S-355's events), the reporter's own
plain-words view, and the two renders. Schema 140;
taxonomy 142 (138 + S-355's four abuse_report events).

Counted with: python3 -m unittest tests.test_abuse_queue
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import taxonomy
from samverk.abuse_queue import (
    AbuseQueue, AbuseReportError, decide_transition, is_duplicate,
    render_my_reports, render_queue, state_words, validate_report,
)
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.db import init_db, schema_version

ROOT = Path(__file__).resolve().parent.parent


class PureJudgesTest(unittest.TestCase):
    def test_validate_report(self):
        self.assertEqual(validate_report("repository", "1", "spam"), ())
        self.assertTrue(validate_report("nope", "1", "spam"))
        self.assertTrue(validate_report("issue", "", "spam"))
        self.assertTrue(validate_report("issue", "1", "  "))
        self.assertTrue(validate_report("issue", "1", "x" * 1001))

    def test_decide_transition(self):
        self.assertEqual(decide_transition("open", "acknowledge"), "acknowledged")
        self.assertEqual(decide_transition("open", "resolve"), "resolved")
        self.assertEqual(decide_transition("acknowledged", "dismiss"), "dismissed")
        self.assertIsNone(decide_transition("resolved", "resolve"))
        self.assertIsNone(decide_transition("dismissed", "acknowledge"))
        self.assertIsNone(decide_transition("acknowledged", "acknowledge"))
        self.assertIsNone(decide_transition("open", "explode"))

    def test_is_duplicate(self):
        self.assertTrue(is_duplicate(["resolved", "open"]))
        self.assertFalse(is_duplicate(["resolved", "dismissed"]))
        self.assertFalse(is_duplicate([]))

    def test_state_words_cover_states(self):
        for s in ("open", "acknowledged", "resolved", "dismissed"):
            self.assertTrue(state_words(s))

    def test_pins(self):
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 34)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 16)


class QueueBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.conn = init_db(Path(self.dir) / "t.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        now = 1700000000
        def user(name, admin=0):
            cur = self.conn.execute(
                "INSERT INTO users (username, username_lower, email, email_lower, password_hash, status, is_admin, created_at) VALUES (?,?,?,?, 'x', 'active', ?, ?)",
                (name, name.lower(), None, None, admin, now))
            self.conn.commit()
            return int(cur.lastrowid)
        self.admin = user("admina", admin=1)
        self.reporter = user("reporter")
        self.other = user("other")
        cur = self.conn.execute(
            "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at) VALUES ('o','o','r','r',?,?)", (self.other, now))
        self.repo_id = int(cur.lastrowid)
        cur = self.conn.execute(
            "INSERT INTO issues (repo_id, number, author_id, title, created_at, updated_at) VALUES (?,1,?,'t',?,?)", (self.repo_id, self.other, now, now))
        self.issue_id = int(cur.lastrowid)
        cur = self.conn.execute(
            "INSERT INTO issue_comments (issue_id, author_id, body, created_at, updated_at) VALUES (?,?, 'mean words', ?, ?)", (self.issue_id, self.other, now, now))
        self.comment_id = int(cur.lastrowid)
        self.conn.commit()
        self.audit.append(actor_kind="user", actor_id=self.other,
                          action="repo.create", target_kind="repo",
                          target_id=str(self.repo_id), outcome="success")
        self.queue = AbuseQueue(self.conn, self.accounts, audit=self.audit)

    def tearDown(self):
        self.conn.close()


class FilingTest(QueueBase):
    def test_schema_pin(self):
        self.assertEqual(schema_version(self.conn), 140)

    def test_file_on_each_target_kind(self):
        for kind, tid in (("repository", self.repo_id), ("issue", self.issue_id),
                          ("comment", self.comment_id), ("account", self.other)):
            r = self.queue.file_report(self.reporter, kind, tid, "abusive behaviour")
            self.assertEqual(r.state, "open")
            self.assertEqual(r.target_kind, kind)

    def test_audit_context_attached_and_chain_intact(self):
        r = self.queue.file_report(self.reporter, "repository", self.repo_id, "spam farm")
        self.assertTrue(r.audit_context)
        entry = self.queue.context_for(r)
        self.assertTrue(entry.chain_ok)
        self.assertEqual([c.action for c in entry.context], ["repo.create"])
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok)

    def test_filing_is_audit_logged(self):
        self.queue.file_report(self.reporter, "account", self.other, "harassment")
        row = self.conn.execute("SELECT action FROM audit_log WHERE action='auth.abuse_report.filed'").fetchone()
        self.assertIsNotNone(row)

    def test_reason_required_and_target_must_exist(self):
        with self.assertRaises(AbuseReportError):
            self.queue.file_report(self.reporter, "issue", self.issue_id, " ")
        with self.assertRaises(AbuseReportError) as cm:
            self.queue.file_report(self.reporter, "issue", 99999, "spam")
        self.assertEqual(cm.exception.reason, "no_such_target")

    def test_cannot_report_self(self):
        with self.assertRaises(AbuseReportError) as cm:
            self.queue.file_report(self.reporter, "account", self.reporter, "me")
        self.assertEqual(cm.exception.reason, "cannot_report_self")

    def test_duplicate_refused_until_closed(self):
        r = self.queue.file_report(self.reporter, "comment", self.comment_id, "slur")
        with self.assertRaises(AbuseReportError) as cm:
            self.queue.file_report(self.reporter, "comment", self.comment_id, "again")
        self.assertEqual(cm.exception.reason, "duplicate")
        other = self.queue.file_report(self.other, "comment", self.comment_id, "saw it too")
        self.assertEqual(other.state, "open")
        self.queue.dismiss(self.admin, r.id, "already handled")
        fresh = self.queue.file_report(self.reporter, "comment", self.comment_id, "still happening")
        self.assertEqual(fresh.state, "open")


class WorkingTest(QueueBase):
    def setUp(self):
        super().setUp()
        self.report = self.queue.file_report(self.reporter, "issue", self.issue_id, "threats in thread")

    def test_non_admin_cannot_see_or_work_queue(self):
        with self.assertRaises(AbuseReportError):
            self.queue.queue(self.reporter)
        with self.assertRaises(AbuseReportError):
            self.queue.resolve(self.reporter, self.report.id, "nope")

    def test_acknowledge_resolve_flow_and_audit(self):
        ack = self.queue.acknowledge(self.admin, self.report.id)
        self.assertEqual(ack.state, "acknowledged")
        done = self.queue.resolve(self.admin, self.report.id, "content removed")
        self.assertEqual(done.state, "resolved")
        self.assertEqual(done.resolution_reason, "content removed")
        self.assertEqual(done.handled_by, self.admin)
        actions = [r[0] for r in self.conn.execute("SELECT action FROM audit_log WHERE action LIKE '%abuse_report.%' ORDER BY seq")]
        self.assertEqual(actions, ["auth.abuse_report.filed", "admin.abuse_report.acknowledged", "admin.abuse_report.resolved"])
        with self.assertRaises(AbuseReportError):
            self.queue.resolve(self.admin, self.report.id, "again")

    def test_dismiss_needs_reason(self):
        with self.assertRaises(AbuseReportError):
            self.queue.dismiss(self.admin, self.report.id, "")
        gone = self.queue.dismiss(self.admin, self.report.id, "not abuse")
        self.assertEqual(gone.state, "dismissed")

    def test_queue_orders_live_first(self):
        r2 = self.queue.file_report(self.other, "account", self.reporter, "spam")
        self.queue.resolve(self.admin, self.report.id, "done")
        entries = self.queue.queue(self.admin)
        self.assertEqual(entries[0].report.id, r2.id)
        self.assertTrue(all(e.chain_ok for e in entries))

    def test_reporter_sees_own_state_in_words_only(self):
        mine = self.queue.my_reports(self.reporter)
        self.assertEqual(len(mine), 1)
        self.assertIn("Waiting", mine[0].state_in_words)
        with self.assertRaises(AbuseReportError):
            self.queue.my_report(self.other, self.report.id)
        page = render_my_reports(mine)
        self.assertIn("Waiting", page)

    def test_render_queue_escapes(self):
        self.queue.file_report(self.other, "account", self.reporter, "<script>x</script>")
        page = render_queue(self.queue.queue(self.admin))
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("Audit chain: intact", page)


class DocsTest(unittest.TestCase):
    def test_guide_exists_and_names_events(self):
        text = (ROOT / "docs" / "ABUSE_QUEUE.md").read_text()
        for name in ("auth.abuse_report.filed", "admin.abuse_report.resolved", "140"):
            self.assertIn(name, text)
        tax = (ROOT / "docs" / "AUDIT_TAXONOMY.md").read_text()
        self.assertIn("S-355", tax)


if __name__ == "__main__":
    unittest.main()
