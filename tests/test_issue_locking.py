"""S-132 acceptance battery: locking and pinning.

Acceptance (roadmap S-132): lock conversation with
reason; pin up to three issues; both moderator-only
and audit-logged.

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
from samverk.issue_locking import MAX_PINS, IssueLockPinStore
from samverk.issues import IssueError, IssueStore
from samverk.repositories import RepositoryStore


class LockPinTests(unittest.TestCase):
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
        self.controls = IssueLockPinStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.issue = self.issues.create_issue(
            self.reader, "volmarr", "pub", "Reader's report")

    def actions(self):
        return [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'repo.issue.%'"
            " ORDER BY seq")]

    def test_lock_with_reason_and_words(self):
        lock = self.controls.lock_issue(
            self.owner, "volmarr", "pub", 1, reason="too_heated")
        self.assertTrue(lock.locked)
        self.assertEqual(lock.words, "locked as too heated")
        self.assertEqual(lock.locked_by, self.owner.id)
        standing = self.controls.lock_for(None, "volmarr", "pub", 1)
        self.assertEqual(standing, lock)
        issue = self.issues.get_issue(None, "volmarr", "pub", 1)
        self.assertTrue(issue.locked)
        self.assertEqual(issue.lock_reason, "too_heated")
        row = self.conn.execute(
            "SELECT detail FROM audit_log WHERE action = 'repo.issue.lock'"
        ).fetchone()
        self.assertIn('"reason":"too_heated"', row["detail"])

    def test_invalid_reason_changes_nothing(self):
        for bad in ("done", "", "TOO_HEATED", None):
            with self.assertRaises(IssueError) as caught:
                self.controls.lock_issue(self.owner, "volmarr", "pub", 1, reason=bad)
            self.assertEqual(caught.exception.reason, "reason_invalid")
        self.assertFalse(self.controls.lock_for(None, "volmarr", "pub", 1).locked)
        self.assertNotIn("repo.issue.lock", self.actions())

    def test_relock_and_reunlock_are_quiet_noops(self):
        self.controls.lock_issue(self.owner, "volmarr", "pub", 1, reason="spam")
        again = self.controls.lock_issue(
            self.owner, "volmarr", "pub", 1, reason="resolved")
        self.assertEqual(again.reason, "spam")  # the record is not rewritten
        self.controls.unlock_issue(self.owner, "volmarr", "pub", 1)
        self.controls.unlock_issue(self.owner, "volmarr", "pub", 1)
        self.assertEqual(self.controls.lock_for(None, "volmarr", "pub", 1).words,
                         "not locked")
        self.assertEqual(self.actions().count("repo.issue.lock"), 1)
        self.assertEqual(self.actions().count("repo.issue.unlock"), 1)

    def test_locked_conversation_refuses_comments_but_not_writers(self):
        self.controls.lock_issue(self.owner, "volmarr", "pub", 1, reason="off_topic")
        with self.assertRaises(IssueError) as caught:
            self.comments.add_comment(self.reader, "volmarr", "pub", 1, "Still talking")
        self.assertEqual(caught.exception.reason, "conversation_locked")
        self.assertIn("off-topic", str(caught.exception))
        # The repository owner (a writer/admin) can still speak.
        note = self.comments.add_comment(self.owner, "volmarr", "pub", 1, "Moderating")
        self.assertEqual(note.body, "Moderating")
        # Unlocking reopens the conversation to everyone.
        self.controls.unlock_issue(self.owner, "volmarr", "pub", 1)
        reply = self.comments.add_comment(self.reader, "volmarr", "pub", 1, "Back")
        self.assertEqual(reply.body, "Back")

    def test_moderator_only(self):
        # The issue's own author is not a moderator of the repo.
        with self.assertRaises(IssueError) as caught:
            self.controls.lock_issue(self.reader, "volmarr", "pub", 1)
        self.assertEqual(caught.exception.reason, "permission_denied")
        with self.assertRaises(IssueError) as caught:
            self.controls.pin_issue(self.other, "volmarr", "pub", 1)
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertFalse(self.controls.lock_for(None, "volmarr", "pub", 1).locked)
        self.assertEqual(self.controls.pinned_issues(None, "volmarr", "pub"), [])

    def test_pin_up_to_three_in_order(self):
        for title in ("Two", "Three", "Four"):
            self.issues.create_issue(self.owner, "volmarr", "pub", title)
        self.controls.pin_issue(self.owner, "volmarr", "pub", 3)
        self.controls.pin_issue(self.owner, "volmarr", "pub", 1)
        pinned = self.controls.pin_issue(self.owner, "volmarr", "pub", 2)
        self.assertEqual([i.number for i in pinned], [3, 1, 2])
        self.assertTrue(self.controls.is_pinned(None, "volmarr", "pub", 1))
        self.assertFalse(self.controls.is_pinned(None, "volmarr", "pub", 4))
        with self.assertRaises(IssueError) as caught:
            self.controls.pin_issue(self.owner, "volmarr", "pub", 4)
        self.assertEqual(caught.exception.reason, "pin_limit")
        self.assertIn(str(MAX_PINS), str(caught.exception))
        # Repinning is a quiet no-op; unpinning frees a slot.
        self.controls.pin_issue(self.owner, "volmarr", "pub", 2)
        self.assertEqual(self.actions().count("repo.issue.pin"), 3)
        remaining = self.controls.unpin_issue(self.owner, "volmarr", "pub", 3)
        self.assertEqual([i.number for i in remaining], [1, 2])
        freed = self.controls.pin_issue(self.owner, "volmarr", "pub", 4)
        self.assertEqual([i.number for i in freed], [1, 2, 4])

    def test_private_issue_controls_are_uniformly_hidden(self):
        secret = self.issues.create_issue(self.owner, "volmarr", "priv", "Secret")
        for call in (
                lambda: self.controls.lock_issue(self.other, "volmarr", "priv", secret.number),
                lambda: self.controls.pin_issue(self.other, "volmarr", "priv", secret.number),
                lambda: self.controls.lock_for(self.other, "volmarr", "priv", secret.number),
                lambda: self.controls.pinned_issues(self.other, "volmarr", "priv")):
            with self.assertRaises(IssueError) as caught:
                call()
            self.assertIn(caught.exception.reason,
                          ("issue_not_found", "repo_not_found"))


if __name__ == "__main__":
    unittest.main()
