"""S-133 acceptance battery: issue transfer.

Acceptance (roadmap S-133): transfer an issue between
repos of the same owner, with a forwarding note left
behind.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.issue_comments import IssueCommentStore
from samverk.issue_locking import IssueLockPinStore
from samverk.issue_timeline import TimelineStore, describe_event
from samverk.issue_transfer import IssueTransferStore, render_forwarding
from samverk.issues import IssueError, IssueStore
from samverk.labels import LabelStore
from samverk.milestones import MilestoneStore
from samverk.repositories import RepositoryStore


class TransferTests(unittest.TestCase):
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
        self.comments = IssueCommentStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.labels = LabelStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.milestones = MilestoneStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.controls = IssueLockPinStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.timeline = TimelineStore(self.conn, self.repos, self.accounts, self.issues)
        self.transfers = IssueTransferStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.repos.create_repository(self.owner.id, "volmarr", "src", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "dst", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "vault", visibility="private")
        self.repos.create_repository(self.other.id, "mallory", "foreign", visibility="public")
        self.issue = self.issues.create_issue(
            self.reader, "volmarr", "src", "Reader's report", "Body text")

    def actions(self):
        return [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'repo.issue.transfer%'"
            " ORDER BY seq")]

    def test_transfer_moves_issue_and_leaves_forwarding(self):
        self.comments.add_comment(self.reader, "volmarr", "src", 1, "First words")
        existing = self.issues.create_issue(self.owner, "volmarr", "dst", "Already here")
        self.assertEqual(existing.number, 1)
        result = self.transfers.transfer_issue(
            self.owner, "volmarr", "src", 1, "volmarr", "dst")
        self.assertEqual((result.source_repo, result.source_number),
                         ("volmarr/src", 1))
        self.assertEqual((result.dest_repo, result.dest_number),
                         ("volmarr/dst", 2))
        moved = result.issue
        self.assertEqual((moved.title, moved.body, moved.author_id),
                         ("Reader's report", "Body text", self.reader.id))
        self.assertEqual(moved.state, "open")
        # The conversation travelled with it.
        bodies = [c.body for c in self.comments.list_comments(
            None, "volmarr", "dst", 2)]
        self.assertEqual(bodies, ["First words"])
        # The old address is vacated, with a note left behind.
        with self.assertRaises(IssueError) as caught:
            self.issues.get_issue(None, "volmarr", "src", 1)
        self.assertEqual(caught.exception.reason, "issue_not_found")
        note = self.transfers.forwarding_for(None, "volmarr", "src", 1)
        self.assertIsNotNone(note)
        self.assertEqual(note.words,
                         "This issue was transferred to volmarr/dst#2")
        self.assertIn("volmarr/dst#2", render_forwarding(note))
        self.assertIsNone(self.transfers.forwarding_for(None, "volmarr", "src", 99))
        self.assertEqual(self.actions(),
                         ["repo.issue.transfer_out", "repo.issue.transfer_in"])

    def test_vacated_number_is_never_reused(self):
        self.transfers.transfer_issue(self.owner, "volmarr", "src", 1, "volmarr", "dst")
        fresh = self.issues.create_issue(self.owner, "volmarr", "src", "Next")
        self.assertEqual(fresh.number, 2)  # #1 stays a gap with its note

    def test_same_owner_only_and_same_repo_refused(self):
        with self.assertRaises(IssueError) as caught:
            self.transfers.transfer_issue(
                self.owner, "volmarr", "src", 1, "mallory", "foreign")
        self.assertEqual(caught.exception.reason, "different_owner")
        with self.assertRaises(IssueError) as caught:
            self.transfers.transfer_issue(
                self.owner, "volmarr", "src", 1, "volmarr", "src")
        self.assertEqual(caught.exception.reason, "same_repository")
        with self.assertRaises(IssueError) as caught:
            self.transfers.transfer_issue(
                self.owner, "volmarr", "src", 1, "volmarr", "nope")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        # Nothing moved and nothing was witnessed.
        self.assertEqual(self.issues.get_issue(None, "volmarr", "src", 1).title,
                         "Reader's report")
        self.assertEqual(self.actions(), [])

    def test_author_can_transfer_reader_cannot_transfer_others(self):
        with self.assertRaises(IssueError) as caught:
            self.transfers.transfer_issue(
                self.other, "volmarr", "src", 1, "volmarr", "dst")
        self.assertEqual(caught.exception.reason, "permission_denied")
        result = self.transfers.transfer_issue(
            self.reader, "volmarr", "src", 1, "volmarr", "dst")
        self.assertEqual(result.dest_number, 1)

    def test_unreadable_destination_is_uniform_not_found(self):
        # The reader authored the issue but cannot read the
        # owner's private repository, so it is not found for her.
        with self.assertRaises(IssueError) as caught:
            self.transfers.transfer_issue(
                self.reader, "volmarr", "src", 1, "volmarr", "vault")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        # The forwarding note likewise hides a private
        # destination from a viewer who cannot read it.
        self.transfers.transfer_issue(
            self.owner, "volmarr", "src", 1, "volmarr", "vault")
        hidden = self.transfers.forwarding_for(self.reader, "volmarr", "src", 1)
        self.assertEqual(hidden.words,
                         "This issue was transferred to another repository")
        named = self.transfers.forwarding_for(self.owner, "volmarr", "src", 1)
        self.assertEqual(named.dest_repo, "volmarr/vault")

    def test_labels_milestone_remap_by_name_pin_left_behind(self):
        self.labels.create_label(self.owner, "volmarr", "src", "triage", "#112233")
        self.labels.add_to_issue(self.owner, "volmarr", "src", 1, "bug")
        self.labels.add_to_issue(self.owner, "volmarr", "src", 1, "triage")
        self.milestones.create_milestone(self.owner, "volmarr", "src", "Launch")
        self.milestones.set_issue_milestone(self.owner, "volmarr", "src", 1, "Launch")
        self.milestones.create_milestone(self.owner, "volmarr", "dst", "Launch")
        self.controls.pin_issue(self.owner, "volmarr", "src", 1)
        result = self.transfers.transfer_issue(
            self.owner, "volmarr", "src", 1, "volmarr", "dst")
        # 'bug' is a default label in both repos; 'triage' is not.
        self.assertEqual(result.labels_carried, ("bug",))
        self.assertEqual(result.labels_dropped, ("triage",))
        names = [l.name for l in self.labels.labels_for_issue(
            None, "volmarr", "dst", result.dest_number)]
        self.assertEqual(names, ["bug"])
        self.assertTrue(result.milestone_carried)
        row = self.conn.execute(
            "SELECT m.title FROM issues i JOIN milestones m"
            " ON m.id = i.milestone_id WHERE i.id = ?",
            (result.issue.id,)).fetchone()
        self.assertEqual(row["title"], "Launch")
        self.assertEqual(self.controls.pinned_issues(None, "volmarr", "src"), [])

    def test_closed_state_and_timeline_arrival_survive(self):
        self.issues.close_issue(self.reader, "volmarr", "src", 1, reason="not_planned")
        result = self.transfers.transfer_issue(
            self.owner, "volmarr", "src", 1, "volmarr", "dst")
        self.assertEqual(result.issue.state_words, "closed as not planned")
        words = [describe_event(e) for e in self.timeline.timeline_for(
            None, "volmarr", "dst", result.dest_number)]
        self.assertTrue(any("transferred this issue from volmarr/src#1" in w
                            for w in words), words)
        self.assertTrue(any("closed this issue as not planned" in w for w in words),
                        words)

    def test_pull_request_number_cannot_transfer(self):
        claimed = self.issues.claim_number("volmarr", "src", "pull_request",
                                           self.owner.id)
        with self.assertRaises(IssueError) as caught:
            self.transfers.transfer_issue(
                self.owner, "volmarr", "src", claimed.number, "volmarr", "dst")
        self.assertEqual(caught.exception.reason, "issue_not_found")


if __name__ == "__main__":
    unittest.main()
