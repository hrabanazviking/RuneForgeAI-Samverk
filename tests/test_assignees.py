"""S-126 acceptance battery: assignees.

Acceptance (roadmap S-126): multiple assignees,
assignment events, and 'assigned to me' filters.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.assignees import MAX_ASSIGNEES, AssigneeError, AssigneeStore
from samverk.audit import AuditLog
from samverk.issues import IssueError, IssueStore
from samverk.repositories import RepositoryStore

class AssigneeTests(unittest.TestCase):
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
        self.assignees = AssigneeStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.issue = self.issues.create_issue(self.owner, "volmarr", "pub", "Fix it")
        self.priv = self.issues.create_issue(self.owner, "volmarr", "priv", "Secret")

    def test_multiple_assignees_and_idempotence(self):
        self.assignees.assign(self.owner, "volmarr", "pub", 1, "yrsa")
        both = self.assignees.assign(self.owner, "volmarr", "pub", 1, "volmarr")
        self.assertEqual([a.username for a in both], ["yrsa", "volmarr"])
        again = self.assignees.assign(self.owner, "volmarr", "pub", 1, "YRSA")
        self.assertEqual(len(again), 2)  # retry changes nothing
        self.assertTrue(self.assignees.is_assigned(None, "volmarr", "pub", 1, "yrsa"))
        rows = self.conn.execute(
            "SELECT detail FROM audit_log WHERE action = 'repo.issue.assign'"
            " ORDER BY seq").fetchall()
        self.assertEqual(len(rows), 2)  # the retry emitted no event

    def test_unassign_rules(self):
        self.assignees.assign(self.owner, "volmarr", "pub", 1, "yrsa")
        # A third party cannot unassign someone else.
        with self.assertRaises(AssigneeError) as caught:
            self.assignees.unassign(self.other, "volmarr", "pub", 1, "yrsa")
        self.assertEqual(caught.exception.reason, "permission_denied")
        # Self-unassign always works; a repeat is a quiet no-op.
        left = self.assignees.unassign(self.reader, "volmarr", "pub", 1, "yrsa")
        self.assertEqual(left, [])
        self.assertEqual(self.assignees.unassign(self.reader, "volmarr", "pub", 1, "yrsa"), [])
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'repo.issue.unassign'").fetchone()
        self.assertEqual(rows["n"], 1)

    def test_self_assign_for_readers_writer_assign_for_others(self):
        # A reader takes the work themselves: allowed.
        mine = self.assignees.assign(self.reader, "volmarr", "pub", 1, "yrsa")
        self.assertEqual([a.username for a in mine], ["yrsa"])
        # ...but cannot assign someone else.
        with self.assertRaises(AssigneeError) as caught:
            self.assignees.assign(self.reader, "volmarr", "pub", 1, "mallory")
        self.assertEqual(caught.exception.reason, "permission_denied")
        with self.assertRaises(AssigneeError) as caught:
            self.assignees.assign(self.owner, "volmarr", "pub", 1, "ghost")
        self.assertEqual(caught.exception.reason, "no_such_user")

    def test_private_repo_assignee_must_be_able_to_read(self):
        with self.assertRaises(AssigneeError) as caught:
            self.assignees.assign(self.owner, "volmarr", "priv", 1, "mallory")
        self.assertEqual(caught.exception.reason, "assignee_cannot_read")
        got = self.assignees.assign(self.owner, "volmarr", "priv", 1, "volmarr")
        self.assertEqual([a.username for a in got], ["volmarr"])
        # And the assignment list itself is hidden from strangers.
        with self.assertRaises(IssueError) as caught:
            self.assignees.assignees_for_issue(self.other, "volmarr", "priv", 1)
        self.assertEqual(caught.exception.reason, "issue_not_found")

    def test_assigned_to_me_filter(self):
        second = self.issues.create_issue(self.owner, "volmarr", "pub", "Also fix")
        self.assignees.assign(self.owner, "volmarr", "pub", 1, "yrsa")
        self.assignees.assign(self.owner, "volmarr", "pub", second.number, "yrsa")
        self.assignees.assign(self.owner, "volmarr", "pub", second.number, "volmarr")
        mine = self.assignees.issues_assigned_to(self.reader, "volmarr", "pub")
        self.assertEqual([i.number for i in mine], [1, second.number])
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE number = ?",
                (second.number,))
        self.assertEqual(
            [i.number for i in self.assignees.issues_assigned_to(
                self.reader, "volmarr", "pub", state="open")], [1])
        self.assertEqual(
            [i.number for i in self.assignees.issues_assigned_to(
                self.reader, "volmarr", "pub", state="closed")], [second.number])
        self.assertEqual(self.assignees.issues_assigned_to(self.other, "volmarr", "pub"), [])

    def test_assignee_limit_is_named(self):
        names = []
        for i in range(MAX_ASSIGNEES + 2):
            user = self.accounts.register(f"helper{i}", "correct horse battery")
            names.append(user.username)
        for name in names[:MAX_ASSIGNEES]:
            self.assignees.assign(self.owner, "volmarr", "pub", 1, name)
        with self.assertRaises(AssigneeError) as caught:
            self.assignees.assign(self.owner, "volmarr", "pub", 1, names[MAX_ASSIGNEES])
        self.assertEqual(caught.exception.reason, "assignee_limit")
        self.assertEqual(
            len(self.assignees.assignees_for_issue(None, "volmarr", "pub", 1)),
            MAX_ASSIGNEES)

if __name__ == "__main__":
    unittest.main()
