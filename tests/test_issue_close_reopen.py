"""S-130 acceptance battery: close and reopen with reason.

Acceptance (roadmap S-130): close and reopen — with reason
(completed / not planned), state events in the timeline.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.issues import IssueError, IssueStore, describe_state_event
from samverk.repositories import RepositoryStore


class CloseReopenTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.other = self.accounts.register("mallory", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.issue = self.issues.create_issue(
            self.reader, "volmarr", "pub", "Reader's report")

    def test_close_completed_records_event_and_words(self):
        closed = self.issues.close_issue(self.owner, "volmarr", "pub", 1)
        self.assertEqual((closed.state, closed.state_reason),
                         ("closed", "completed"))
        self.assertEqual(closed.state_words, "closed as completed")
        events = self.issues.state_events_for(None, "volmarr", "pub", 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(describe_state_event(events[0]),
                         "volmarr closed this issue as completed")
        row = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action = 'repo.issue.close'").fetchone()
        self.assertIn('"reason":"completed"', row["detail"])
        self.assertEqual(
            [i.number for i in self.issues.list_issues(
                None, "volmarr", "pub", state="closed")], [1])
        self.assertEqual(
            self.issues.list_issues(None, "volmarr", "pub", state="open"), [])

    def test_close_not_planned(self):
        closed = self.issues.close_issue(
            self.reader, "volmarr", "pub", 1, reason="not_planned")
        self.assertEqual(closed.state_words, "closed as not planned")
        events = self.issues.state_events_for(None, "volmarr", "pub", 1)
        self.assertEqual(describe_state_event(events[0]),
                         "yrsa closed this issue as not planned")

    def test_invalid_reason_changes_nothing(self):
        for bad in ("done", "", "COMPLETED", None):
            with self.assertRaises(IssueError) as caught:
                self.issues.close_issue(self.owner, "volmarr", "pub", 1, reason=bad)
            self.assertEqual(caught.exception.reason, "reason_invalid")
        issue = self.issues.get_issue(None, "volmarr", "pub", 1)
        self.assertEqual((issue.state, issue.state_reason), ("open", ""))
        self.assertEqual(self.issues.state_events_for(None, "volmarr", "pub", 1), [])

    def test_reclose_and_reopen_are_quiet_noops(self):
        self.issues.close_issue(self.owner, "volmarr", "pub", 1)
        again = self.issues.close_issue(
            self.owner, "volmarr", "pub", 1, reason="not_planned")
        self.assertEqual(again.state_reason, "completed")  # not rewritten
        self.assertEqual(len(self.issues.state_events_for(
            None, "volmarr", "pub", 1)), 1)
        reopened = self.issues.reopen_issue(self.reader, "volmarr", "pub", 1)
        self.assertEqual((reopened.state, reopened.state_reason), ("open", ""))
        self.assertEqual(reopened.state_words, "open")
        self.issues.reopen_issue(self.owner, "volmarr", "pub", 1)
        events = self.issues.state_events_for(None, "volmarr", "pub", 1)
        self.assertEqual([e.kind for e in events], ["closed", "reopened"])
        self.assertEqual(describe_state_event(events[1]),
                         "yrsa reopened this issue")
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log WHERE action IN"
            " ('repo.issue.close', 'repo.issue.reopen') ORDER BY seq")]
        self.assertEqual(actions, ["repo.issue.close", "repo.issue.reopen"])

    def test_full_cycle_order(self):
        self.issues.close_issue(self.owner, "volmarr", "pub", 1, reason="not_planned")
        self.issues.reopen_issue(self.owner, "volmarr", "pub", 1)
        self.issues.close_issue(self.owner, "volmarr", "pub", 1)
        events = self.issues.state_events_for(None, "volmarr", "pub", 1)
        self.assertEqual([(e.kind, e.reason) for e in events],
                         [("closed", "not_planned"), ("reopened", ""),
                          ("closed", "completed")])
        self.assertTrue(all(e.actor == "volmarr" for e in events))

    def test_permissions(self):
        with self.assertRaises(IssueError) as caught:
            self.issues.close_issue(self.other, "volmarr", "pub", 1)
        self.assertEqual(caught.exception.reason, "permission_denied")
        # The author may close their own issue without write access.
        self.issues.close_issue(self.reader, "volmarr", "pub", 1)
        priv = self.issues.create_issue(self.owner, "volmarr", "priv", "Secret")
        with self.assertRaises(IssueError) as caught:
            self.issues.close_issue(self.other, "volmarr", "priv", priv.number)
        self.assertEqual(caught.exception.reason, "issue_not_found")
        with self.assertRaises(IssueError) as caught:
            self.issues.state_events_for(self.other, "volmarr", "priv", priv.number)
        self.assertEqual(caught.exception.reason, "issue_not_found")


if __name__ == "__main__":
    unittest.main()
