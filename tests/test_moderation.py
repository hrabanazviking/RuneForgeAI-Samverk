"""S-138 acceptance battery: comment moderation.

Acceptance (roadmap S-138): hide/delete abusive
comments, with the act visible in the timeline (no
silent edits of the record).

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
from samverk.issue_timeline import TimelineStore, describe_event
from samverk.issues import IssueError, IssueStore
from samverk.moderation import ModerationStore, render_comment
from samverk.repositories import RepositoryStore


class ModerationTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.other = self.accounts.register("tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit)
        self.comments = IssueCommentStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.mod = ModerationStore(
            self.conn, self.repos, self.accounts, self.comments, audit=self.audit)
        self.timeline = TimelineStore(self.conn, self.repos, self.accounts, self.issues)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.issues.create_issue(self.owner, "volmarr", "pub", "Discuss the plan")
        self.spam = self.comments.add_comment(
            self.reader, "volmarr", "pub", 1, "buy my coins <now>")
        self.normal = self.comments.add_comment(
            self.other, "volmarr", "pub", 1, "A real thought")

    def _listed_ids(self, viewer):
        return [c.id for c in self.comments.list_comments(
            viewer, "volmarr", "pub", 1)]

    def test_hide_takes_comment_out_of_conversation(self):
        hidden = self.mod.hide_comment(
            self.owner, "volmarr", "pub", 1, self.spam.id, "spam")
        self.assertTrue(hidden.is_hidden)
        self.assertEqual(hidden.hide_reason, "spam")
        self.assertEqual(hidden.body, "buy my coins <now>")  # body untouched
        # Gone for ordinary readers and anonymous visitors...
        self.assertNotIn(self.spam.id, self._listed_ids(self.other))
        self.assertNotIn(self.spam.id, self._listed_ids(None))
        # ...still visible to its author and to moderators.
        self.assertIn(self.spam.id, self._listed_ids(self.reader))
        self.assertIn(self.spam.id, self._listed_ids(self.owner))
        self.assertIn(self.normal.id, self._listed_ids(self.other))
        # The notice says it in words.
        self.assertIn("hidden by a moderator as spam",
                      render_comment(hidden))

    def test_unhide_restores_and_retries_are_quiet(self):
        self.mod.hide_comment(self.owner, "volmarr", "pub", 1,
                              self.spam.id, "abuse")
        self.mod.hide_comment(self.owner, "volmarr", "pub", 1,
                              self.spam.id, "abuse")  # retry: no 2nd event
        restored = self.mod.unhide_comment(
            self.owner, "volmarr", "pub", 1, self.spam.id)
        self.assertFalse(restored.is_hidden)
        self.assertIn(self.spam.id, self._listed_ids(self.other))
        self.mod.unhide_comment(self.owner, "volmarr", "pub", 1,
                                self.spam.id)  # retry: no 2nd event
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log WHERE action LIKE"
            " 'repo.issue.comment_%hide' ORDER BY seq")]
        self.assertEqual(actions, ["repo.issue.comment_hide",
                                   "repo.issue.comment_unhide"])

    def test_only_moderators_and_valid_reasons(self):
        with self.assertRaises(IssueError) as caught:
            self.mod.hide_comment(self.reader, "volmarr", "pub", 1,
                                  self.spam.id, "spam")
        self.assertEqual(caught.exception.reason, "permission_denied")
        with self.assertRaises(IssueError) as caught:
            self.mod.hide_comment(self.owner, "volmarr", "pub", 1,
                                  self.spam.id, "rude")
        self.assertEqual(caught.exception.reason, "reason_invalid")
        self.assertFalse(self.comments.get_comment(
            self.owner, "volmarr", "pub", 1, self.spam.id).is_hidden)

    def test_moderator_remove_is_a_distinct_tombstone(self):
        removed = self.mod.remove_comment(
            self.owner, "volmarr", "pub", 1, self.spam.id, "abuse")
        self.assertTrue(removed.is_deleted)
        self.assertEqual(removed.body, "")
        self.assertEqual(removed.deleted_by, self.owner.id)
        self.assertNotIn(self.spam.id, self._listed_ids(self.owner))
        self.assertIn("This comment was deleted.", render_comment(removed))
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log WHERE action ="
            " 'repo.issue.comment_remove'")]
        self.assertEqual(len(actions), 1)
        # Gone is gone: no hiding or second removal.
        for act in (lambda: self.mod.hide_comment(
                        self.owner, "volmarr", "pub", 1, self.spam.id, "spam"),
                    lambda: self.mod.remove_comment(
                        self.owner, "volmarr", "pub", 1, self.spam.id, "spam")):
            with self.assertRaises(IssueError) as caught:
                act()
            self.assertEqual(caught.exception.reason, "comment_not_found")

    def test_hidden_comment_can_be_removed(self):
        self.mod.hide_comment(self.owner, "volmarr", "pub", 1,
                              self.spam.id, "spam")
        removed = self.mod.remove_comment(
            self.owner, "volmarr", "pub", 1, self.spam.id, "spam")
        self.assertTrue(removed.is_deleted)

    def test_timeline_shows_every_act_in_words(self):
        self.mod.hide_comment(self.owner, "volmarr", "pub", 1,
                              self.spam.id, "spam")
        self.mod.unhide_comment(self.owner, "volmarr", "pub", 1, self.spam.id)
        self.mod.remove_comment(self.owner, "volmarr", "pub", 1,
                                self.spam.id, "abuse")
        words = [describe_event(e) for e in
                 self.timeline.timeline_for(self.owner, "volmarr", "pub", 1)]
        self.assertIn("volmarr hid a comment as spam", words)
        self.assertIn("volmarr unhid a comment", words)
        self.assertIn("volmarr removed a comment as abusive", words)

    def test_private_repo_stranger_gets_uniform_answer(self):
        self.repos.create_repository(self.owner.id, "volmarr", "priv",
                                     visibility="private")
        self.issues.create_issue(self.owner, "volmarr", "priv", "Secret")
        secret = self.comments.add_comment(
            self.owner, "volmarr", "priv", 1, "secret words")
        with self.assertRaises(IssueError) as caught:
            self.mod.hide_comment(self.reader, "volmarr", "priv", 1,
                                  secret.id, "spam")
        self.assertEqual(caught.exception.reason, "issue_not_found")


if __name__ == "__main__":
    unittest.main()
