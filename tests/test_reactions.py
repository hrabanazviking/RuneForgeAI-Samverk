"""S-128 acceptance battery: reactions.

Acceptance (roadmap S-128): the small honest set;
counts shown, who-reacted list available.

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
from samverk.reactions import REACTIONS, ReactionError, ReactionStore, render_summary
from samverk.repositories import RepositoryStore

class ReactionTests(unittest.TestCase):
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
        self.reactions = ReactionStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.issue = self.issues.create_issue(self.owner, "volmarr", "pub", "Nice work")
        self.priv = self.issues.create_issue(self.owner, "volmarr", "priv", "Secret")

    def test_counts_and_who_reacted(self):
        self.reactions.add_reaction(self.owner, "volmarr", "pub", 1, "heart")
        got = self.reactions.add_reaction(self.reader, "volmarr", "pub", 1, "heart")
        self.assertEqual(len(got), 1)
        summary = got[0]
        self.assertEqual((summary.reaction, summary.count), ("heart", 2))
        self.assertEqual(summary.users, ("volmarr", "yrsa"))
        self.assertEqual(render_summary(summary), "❤️ heart: 2 (volmarr, yrsa)")
        self.assertTrue(self.reactions.has_reacted(self.reader, "volmarr", "pub", 1, "heart"))
        self.assertFalse(self.reactions.has_reacted(self.other, "volmarr", "pub", 1, "heart"))

    def test_idempotent_add_and_remove_only_own(self):
        self.reactions.add_reaction(self.reader, "volmarr", "pub", 1, "rocket")
        self.reactions.add_reaction(self.reader, "volmarr", "pub", 1, "rocket")
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'repo.issue.reaction_add'").fetchone()
        self.assertEqual(rows["n"], 1)  # the retry changed nothing, said nothing
        # Another account's remove touches only their own (absent) row.
        self.reactions.remove_reaction(self.other, "volmarr", "pub", 1, "rocket")
        self.assertEqual(
            self.reactions.summaries_for(None, "volmarr", "pub", 1)[0].count, 1)
        left = self.reactions.remove_reaction(self.reader, "volmarr", "pub", 1, "rocket")
        self.assertEqual(left, [])
        self.assertEqual(self.reactions.remove_reaction(
            self.reader, "volmarr", "pub", 1, "rocket"), [])

    def test_small_closed_set(self):
        self.assertEqual(len(REACTIONS), 8)
        for bad in ("party", "👍", "", "THUMBS_UP"):
            with self.assertRaises(ReactionError) as caught:
                self.reactions.add_reaction(self.owner, "volmarr", "pub", 1, bad)
            self.assertEqual(caught.exception.reason, "reaction_invalid")
        for name in REACTIONS:
            self.reactions.add_reaction(self.owner, "volmarr", "pub", 1, name)
        got = self.reactions.summaries_for(None, "volmarr", "pub", 1)
        self.assertEqual([s.reaction for s in got], list(REACTIONS))

    def test_comment_reactions_are_their_own(self):
        comment = self.comments.add_comment(self.reader, "volmarr", "pub", 1, "Agreed")
        self.reactions.add_reaction(self.owner, "volmarr", "pub", 1, "eyes",
                                    comment_id=comment.id)
        self.assertEqual(self.reactions.summaries_for(None, "volmarr", "pub", 1), [])
        on_comment = self.reactions.summaries_for(
            None, "volmarr", "pub", 1, comment_id=comment.id)
        self.assertEqual([(s.reaction, s.users) for s in on_comment],
                         [("eyes", ("volmarr",))])
        detail = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action = 'repo.issue.reaction_add'").fetchone()["detail"]
        self.assertIn('"comment_id"', detail)
        self.comments.delete_comment(self.reader, "volmarr", "pub", 1, comment.id)
        with self.assertRaises(IssueError) as caught:
            self.reactions.summaries_for(None, "volmarr", "pub", 1, comment_id=comment.id)
        self.assertEqual(caught.exception.reason, "comment_not_found")

    def test_private_repo_uniform_answer(self):
        self.reactions.add_reaction(self.owner, "volmarr", "priv", 1, "heart")
        self.assertEqual(
            self.reactions.summaries_for(self.owner, "volmarr", "priv", 1)[0].count, 1)
        with self.assertRaises(IssueError) as caught:
            self.reactions.summaries_for(self.other, "volmarr", "priv", 1)
        self.assertEqual(caught.exception.reason, "issue_not_found")
        with self.assertRaises(IssueError):
            self.reactions.add_reaction(self.other, "volmarr", "priv", 1, "heart")

if __name__ == "__main__":
    unittest.main()
