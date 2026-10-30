"""S-123 acceptance battery: issue comments.

Acceptance (roadmap S-123): Markdown comments, edit
history visible, delete by author/moderator with audit
trail.

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
from samverk.issues import IssueError, IssueStore
from samverk.repositories import RepositoryStore

class IssueCommentTests(unittest.TestCase):
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
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.issue = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Discuss me")
        self.priv_issue = self.issues.create_issue(
            self.owner, "volmarr", "priv", "Secret")

    def test_add_and_list_in_order(self):
        a = self.comments.add_comment(
            self.reader, "volmarr", "pub", 1, "First **thought**")
        b = self.comments.add_comment(self.owner, "volmarr", "pub", 1, "Second")
        listed = self.comments.list_comments(None, "volmarr", "pub", 1)
        self.assertEqual([c.id for c in listed], [a.id, b.id])
        self.assertEqual(listed[0].body, "First **thought**")
        self.assertEqual(listed[0].author_id, self.reader.id)
        self.assertFalse(listed[0].was_edited); self.assertFalse(listed[0].is_deleted)
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log WHERE action = 'repo.issue.comment'")]
        self.assertEqual(len(actions), 2)

    def test_body_law_and_missing_issue(self):
        for body, reason in (("", "comment_required"), ("  ", "comment_required"),
                             (None, "comment_required")):
            with self.assertRaises(IssueError) as caught:
                self.comments.add_comment(self.owner, "volmarr", "pub", 1, body)
            self.assertEqual(caught.exception.reason, reason)
        pr = self.issues.claim_number("volmarr", "pub", "pull_request", self.owner.id)
        for number in (pr.number, 999):
            with self.assertRaises(IssueError) as caught:
                self.comments.add_comment(self.owner, "volmarr", "pub", number, "Hi")
            self.assertEqual(caught.exception.reason, "issue_not_found")
        self.assertEqual(self.comments.list_comments(None, "volmarr", "pub", 1), [])

    def test_private_repo_comments_are_hidden(self):
        self.comments.add_comment(self.owner, "volmarr", "priv", 1, "Shh")
        for viewer in (None, self.other):
            with self.assertRaises(IssueError) as caught:
                self.comments.list_comments(viewer, "volmarr", "priv", 1)
            self.assertEqual(caught.exception.reason, "issue_not_found")
            with self.assertRaises(IssueError):
                self.comments.add_comment(viewer, "volmarr", "priv", 1, "Peek")
        self.assertEqual(
            len(self.comments.list_comments(self.owner, "volmarr", "priv", 1)), 1)

    def test_edit_records_visible_history_and_is_author_only(self):
        c = self.comments.add_comment(self.reader, "volmarr", "pub", 1, "Original")
        edited = self.comments.edit_comment(
            self.reader, "volmarr", "pub", 1, c.id, "Revised")
        self.assertEqual(edited.body, "Revised"); self.assertTrue(edited.was_edited)
        history = self.comments.edits_for(None, "volmarr", "pub", 1, c.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].previous_body, "Original")
        self.assertEqual(history[0].editor_id, self.reader.id)
        self.comments.edit_comment(self.reader, "volmarr", "pub", 1, c.id, "Third")
        self.assertEqual(
            [h.previous_body for h in
             self.comments.edits_for(None, "volmarr", "pub", 1, c.id)],
            ["Original", "Revised"])
        with self.assertRaises(IssueError) as caught:
            self.comments.edit_comment(self.owner, "volmarr", "pub", 1, c.id, "Hijack")
        self.assertEqual(caught.exception.reason, "permission_denied")

    def test_delete_by_author_tombstones_and_audits(self):
        c = self.comments.add_comment(self.reader, "volmarr", "pub", 1, "Regret")
        deleted = self.comments.delete_comment(
            self.reader, "volmarr", "pub", 1, c.id)
        self.assertTrue(deleted.is_deleted); self.assertEqual(deleted.body, "")
        self.assertEqual(deleted.deleted_by, self.reader.id)
        self.assertEqual(self.comments.list_comments(None, "volmarr", "pub", 1), [])
        tomb = self.comments.get_comment(None, "volmarr", "pub", 1, c.id)
        self.assertTrue(tomb.is_deleted)
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'repo.issue.comment_delete'").fetchone()
        self.assertEqual(rows["n"], 1)
        with self.assertRaises(IssueError) as caught:
            self.comments.delete_comment(self.reader, "volmarr", "pub", 1, c.id)
        self.assertEqual(caught.exception.reason, "comment_not_found")

    def test_delete_by_repo_admin_moderator_not_by_stranger(self):
        c = self.comments.add_comment(self.reader, "volmarr", "pub", 1, "Abusive")
        with self.assertRaises(IssueError) as caught:
            self.comments.delete_comment(self.other, "volmarr", "pub", 1, c.id)
        self.assertEqual(caught.exception.reason, "permission_denied")
        deleted = self.comments.delete_comment(
            self.owner, "volmarr", "pub", 1, c.id)
        self.assertTrue(deleted.is_deleted)
        self.assertEqual(deleted.deleted_by, self.owner.id)

    def test_comment_ids_do_not_cross_issues(self):
        other_issue = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Another")
        c = self.comments.add_comment(self.owner, "volmarr", "pub", 1, "On one")
        with self.assertRaises(IssueError) as caught:
            self.comments.get_comment(
                None, "volmarr", "pub", other_issue.number, c.id)
        self.assertEqual(caught.exception.reason, "comment_not_found")

if __name__ == "__main__":
    unittest.main()
