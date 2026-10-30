"""S-134 acceptance battery: bulk edit.

Acceptance (roadmap S-134): label/assign/close across a
filtered set, one audit event per issue.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.assignees import AssigneeStore
from samverk.audit import AuditLog
from samverk.issue_bulk_edit import MAX_BULK_SET, BulkEditStore
from samverk.issues import IssueError, IssueStore
from samverk.labels import LabelStore
from samverk.milestones import MilestoneStore
from samverk.repositories import RepositoryStore


class BulkEditTests(unittest.TestCase):
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
        self.labels = LabelStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.assignees = AssigneeStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.milestones = MilestoneStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.bulk = BulkEditStore(
            self.conn, self.repos, self.accounts, self.issues,
            self.labels, self.assignees)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.issues.create_issue(self.reader, "volmarr", "pub", "One")
        self.issues.create_issue(self.owner, "volmarr", "pub", "Two")
        self.issues.create_issue(self.owner, "volmarr", "pub", "Three")

    def audit_count(self, action, number=None):
        rows = self.conn.execute(
            "SELECT detail FROM audit_log WHERE action = ?", (action,)).fetchall()
        if number is None:
            return len(rows)
        import json
        return sum(1 for r in rows if json.loads(r["detail"]).get("number") == number)

    def test_bulk_label_one_audit_event_per_issue(self):
        result = self.bulk.bulk_edit(
            self.owner, "volmarr", "pub", [1, 2, 3], add_label="bug")
        self.assertEqual(result.succeeded, (1, 2, 3))
        self.assertEqual(result.failures, ())
        self.assertEqual(self.audit_count("repo.issue.label_add"), 3)
        for n in (1, 2, 3):
            names = [l.name for l in self.labels.labels_for_issue(
                None, "volmarr", "pub", n)]
            self.assertEqual(names, ["bug"])

    def test_bulk_assign_and_close_together(self):
        result = self.bulk.bulk_edit(
            self.owner, "volmarr", "pub", [1, 2], assign="yrsa",
            close_reason="completed")
        self.assertEqual(result.succeeded, (1, 2))
        self.assertEqual(self.audit_count("repo.issue.assign"), 2)
        self.assertEqual(self.audit_count("repo.issue.close"), 2)
        for n in (1, 2):
            issue = self.issues.get_issue(None, "volmarr", "pub", n)
            self.assertEqual(issue.state_words, "closed as completed")
            names = [a.username for a in self.assignees.assignees_for_issue(
                None, "volmarr", "pub", n)]
            self.assertEqual(names, ["yrsa"])

    def test_per_issue_failures_do_not_stop_the_set(self):
        claimed = self.issues.claim_number("volmarr", "pub", "pull_request",
                                           self.owner.id)
        result = self.bulk.bulk_edit(
            self.owner, "volmarr", "pub", [1, 99, claimed.number],
            add_label="bug")
        self.assertEqual(result.succeeded, (1,))
        reasons = {f.number: f.reason for f in result.failures}
        self.assertEqual(reasons, {99: "issue_not_found",
                                   claimed.number: "issue_not_found"})
        self.assertEqual(self.audit_count("repo.issue.label_add"), 1)

    def test_bad_parameters_change_nothing(self):
        for kwargs, reason in (
                (dict(add_label="nope"), "label_not_found"),
                (dict(assign="ghost"), "no_such_user"),
                (dict(close_reason="done"), "reason_invalid"),
                (dict(), "no_operation")):
            with self.assertRaises(IssueError) as caught:
                self.bulk.bulk_edit(self.owner, "volmarr", "pub", [1, 2], **kwargs)
            self.assertEqual(caught.exception.reason, reason)
        with self.assertRaises(IssueError) as caught:
            self.bulk.bulk_edit(self.owner, "volmarr", "pub", [], add_label="bug")
        self.assertEqual(caught.exception.reason, "empty_set")
        with self.assertRaises(IssueError) as caught:
            self.bulk.bulk_edit(self.owner, "volmarr", "pub",
                                list(range(1, MAX_BULK_SET + 2)), add_label="bug")
        self.assertEqual(caught.exception.reason, "set_too_large")
        self.assertEqual(self.audit_count("repo.issue.label_add"), 0)
        self.assertEqual(self.labels.labels_for_issue(None, "volmarr", "pub", 1), [])

    def test_permissions_are_per_issue(self):
        # The reader authored #1 but is a plain reader on
        # the owner's #2: her bulk edit lands on her own
        # issue and fails, named, on the other.
        result = self.bulk.bulk_edit(
            self.reader, "volmarr", "pub", [1, 2], add_label="bug")
        self.assertEqual(result.succeeded, (1,))
        self.assertEqual([(f.number, f.reason) for f in result.failures],
                         [(2, "permission_denied")])

    def test_retries_are_quiet_successes(self):
        self.bulk.bulk_edit(self.owner, "volmarr", "pub", [1],
                            add_label="bug", close_reason="completed")
        again = self.bulk.bulk_edit(self.owner, "volmarr", "pub", [1],
                                    add_label="bug", close_reason="completed")
        self.assertEqual(again.succeeded, (1,))
        self.assertEqual(self.audit_count("repo.issue.label_add"), 1)
        self.assertEqual(self.audit_count("repo.issue.close"), 1)

    def test_filtered_selection(self):
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 2, "bug")
        self.assignees.assign(self.owner, "volmarr", "pub", 3, "yrsa")
        self.milestones.create_milestone(self.owner, "volmarr", "pub", "Launch")
        self.milestones.set_issue_milestone(self.owner, "volmarr", "pub", 1, "Launch")
        self.issues.close_issue(self.owner, "volmarr", "pub", 3)
        pick = self.bulk.select_numbers
        self.assertEqual(pick(None, "volmarr", "pub"), [1, 2, 3])
        self.assertEqual(pick(None, "volmarr", "pub", state="open"), [1, 2])
        self.assertEqual(pick(None, "volmarr", "pub", label="bug"), [2])
        self.assertEqual(pick(None, "volmarr", "pub", assignee="yrsa"), [3])
        self.assertEqual(pick(None, "volmarr", "pub", milestone="Launch"), [1])
        self.assertEqual(pick(None, "volmarr", "pub", author="yrsa"), [1])
        # A filtered set feeds the edit directly.
        result = self.bulk.bulk_edit(
            self.owner, "volmarr", "pub",
            pick(None, "volmarr", "pub", state="open"), add_label="enhancement")
        self.assertEqual(result.succeeded, (1, 2))


if __name__ == "__main__":
    unittest.main()
