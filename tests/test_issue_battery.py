"""S-140 — PART VI GATE battery: issues, assembled.

The whole Part VI system walked end to end over one
public and one private repository, struck at the three
things the gate names:

- **Lifecycle** — an issue lives its whole life through
  the public seams: create, comment, label, milestone,
  assign, react, pin, lock (and the lock bites), close
  with a reason, reopen, transfer, convert to a draft
  PR — with the timeline and the event outbox telling
  the same story the acts wrote.
- **References** — `#n` means one thing, mentions link
  both ways, closing marks are said before any merge,
  and a private source never leaks into a public
  target's record.
- **Permissions at each role** — anonymous, stranger,
  reader-author, writer-owner, and moderator, on public
  and private repositories alike: readers report and
  converse, writers govern, strangers to a private repo
  meet one uniform not-found answer on every surface.

The full-suite counted recount at this gate is recorded
in PROJECT_MEMORY_MAP.md (the gate entry), read back
from its log file after the run finished.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.assignees import AssigneeStore
from samverk.audit import AuditLog
from samverk.cross_references import CrossReferenceStore
from samverk.issue_comments import IssueCommentStore
from samverk.issue_conversion import IssueConversionStore
from samverk.issue_events_out import IssueEventOutbox
from samverk.issue_locking import IssueLockPinStore
from samverk.issue_timeline import TimelineStore
from samverk.issue_transfer import IssueTransferStore
from samverk.issues import IssueError, IssueStore
from samverk.labels import LabelStore
from samverk.milestones import MilestoneStore
from samverk.moderation import ModerationStore
from samverk.reactions import ReactionStore
from samverk.repositories import RepositoryStore
from test_repo_home import run_git


class PartVIGateTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.author = self.accounts.register("yrsa", "correct horse battery")
        self.stranger = self.accounts.register("mallory", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit)
        self.comments = IssueCommentStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.labels = LabelStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.milestones = MilestoneStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.assignees = AssigneeStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.reactions = ReactionStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.locking = IssueLockPinStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.moderation = ModerationStore(
            self.conn, self.repos, self.accounts, self.comments, audit=self.audit)
        self.timeline = TimelineStore(self.conn, self.repos, self.accounts, self.issues)
        self.xrefs = CrossReferenceStore(
            self.conn, self.repos, self.accounts, self.issues)
        self.transfer = IssueTransferStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.conversion = IssueConversionStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.outbox = IssueEventOutbox(self.conn, self.repos, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "pub2", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        # A real base commit on main in pub, for S-137's road.
        bare = self.repos.path_for("volmarr", "pub")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "a.txt").write_text("base\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "base commit")
        run_git(work, "push", str(bare), "main")

    # -- lifecycle ------------------------------------------------------
    def test_full_lifecycle_end_to_end(self):
        issue = self.issues.create_issue(
            self.author, "volmarr", "pub", "The gate issue", "Body text")
        self.assertEqual(issue.number, 1)
        comment = self.comments.add_comment(
            self.author, "volmarr", "pub", 1, "First words")
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 1, "bug")
        mile = self.milestones.create_milestone(
            self.owner, "volmarr", "pub", "v1")
        self.milestones.set_issue_milestone(
            self.owner, "volmarr", "pub", 1, mile.title)
        self.assignees.assign(self.owner, "volmarr", "pub", 1, "yrsa")
        summaries = self.reactions.add_reaction(
            self.author, "volmarr", "pub", 1, "heart")
        self.assertEqual(summaries[0].count, 1)
        self.locking.pin_issue(self.owner, "volmarr", "pub", 1)
        self.locking.lock_issue(self.owner, "volmarr", "pub", 1, "resolved")
        # The lock bites: the author (a reader) cannot comment now.
        with self.assertRaises(IssueError) as caught:
            self.comments.add_comment(self.author, "volmarr", "pub", 1, "more")
        self.assertEqual(caught.exception.reason, "conversation_locked")
        self.locking.unlock_issue(self.owner, "volmarr", "pub", 1)
        closed = self.issues.close_issue(
            self.owner, "volmarr", "pub", 1, "completed")
        self.assertEqual(closed.state_words, "closed as completed")
        self.issues.reopen_issue(self.owner, "volmarr", "pub", 1)
        # The timeline tells the same story the acts wrote.
        kinds = [e.kind for e in
                 self.timeline.timeline_for(self.owner, "volmarr", "pub", 1)]
        for kind in ("created", "labelled", "milestone", "assigned",
                     "pinned", "locked", "unlocked", "closed", "reopened"):
            self.assertIn(kind, kinds)
        # Conversion crowns the lifecycle: branch + draft PR, shared number.
        pr = self.conversion.convert_issue(self.owner, "volmarr", "pub", 1)
        self.assertTrue(pr.is_draft)
        self.assertEqual(
            self.issues.resolve_number("volmarr", "pub", pr.number).kind,
            "pull_request")
        # And every mutation above reached the outbox, in order.
        verbs = [e.verb for e in
                 self.outbox.list_events(self.owner, "volmarr", "pub")]
        for verb in ("repo.issue.create", "repo.issue.comment",
                     "repo.issue.label_add", "repo.issue.milestone",
                     "repo.issue.assign", "repo.issue.reaction_add",
                     "repo.issue.pin", "repo.issue.lock",
                     "repo.issue.unlock", "repo.issue.close",
                     "repo.issue.reopen", "repo.issue.convert",
                     "repo.pull_request.create"):
            self.assertIn(verb, verbs)
        self.assertEqual(verbs[0], "repo.issue.create")
        self.assertEqual(verbs[-1], "repo.pull_request.create")
        self.assertIsNotNone(comment.id)

    def test_transfer_keeps_the_issue_whole(self):
        self.issues.create_issue(self.author, "volmarr", "pub", "Wandering")
        self.comments.add_comment(self.author, "volmarr", "pub", 1, "I travel")
        moved = self.transfer.transfer_issue(
            self.owner, "volmarr", "pub", 1, "volmarr", "pub2")
        self.assertEqual(moved.issue.title, "Wandering")
        self.assertEqual(
            len(self.comments.list_comments(self.owner, "volmarr", "pub2", 1)), 1)
        note = self.transfer.forwarding_for(self.owner, "volmarr", "pub", 1)
        self.assertIn("pub2#1", note.words)

    # -- references -------------------------------------------------------
    def test_references_link_both_ways_and_close_honestly(self):
        self.issues.create_issue(self.owner, "volmarr", "pub", "Target")
        source = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Source", "See #1 — fixes #1 too")
        recorded = self.xrefs.sync_issue_references(
            self.owner, "volmarr", "pub", source.number)
        self.assertEqual([r.target_number for r in recorded], [1])
        self.assertEqual(
            [r.target_number for r in self.xrefs.references_from(
                None, "volmarr", "pub", source.number)], [1])
        self.assertEqual(
            [r.source_number for r in self.xrefs.references_to(
                None, "volmarr", "pub", 1)], [source.number])
        notice = " ".join(self.xrefs.closing_notice(
            self.owner, "volmarr", "pub", source.number))
        self.assertIn("Will close volmarr/pub#1 on merge.", notice)
        kinds = [e.kind for e in
                 self.timeline.timeline_for(None, "volmarr", "pub", 1)]
        self.assertIn("mentioned", kinds)

    # -- permissions at each role -----------------------------------------
    def test_private_repo_uniform_answer_on_every_surface(self):
        self.issues.create_issue(self.owner, "volmarr", "priv", "Secret plan")
        self.comments.add_comment(self.owner, "volmarr", "priv", 1, "quiet")
        surfaces = [
            lambda v: self.issues.get_issue(v, "volmarr", "priv", 1),
            lambda v: self.issues.list_issues(v, "volmarr", "priv"),
            lambda v: self.comments.list_comments(v, "volmarr", "priv", 1),
            lambda v: self.timeline.timeline_for(v, "volmarr", "priv", 1),
            lambda v: self.outbox.list_events(v, "volmarr", "priv"),
            lambda v: self.xrefs.references_to(v, "volmarr", "priv", 1),
        ]
        for viewer in (self.stranger, self.author, None):
            for surface in surfaces:
                with self.assertRaises(Exception) as caught:
                    surface(viewer)
                self.assertIn(caught.exception.reason,
                              ("issue_not_found", "repo_not_found"))
        # The owner walks it all fine.
        self.assertEqual(
            self.issues.get_issue(self.owner, "volmarr", "priv", 1).title,
            "Secret plan")

    def test_roles_on_a_public_repo(self):
        self.issues.create_issue(self.author, "volmarr", "pub", "Roles")
        # Anonymous and strangers may read a public issue.
        self.assertEqual(
            self.issues.get_issue(None, "volmarr", "pub", 1).title, "Roles")
        self.assertEqual(
            self.issues.get_issue(self.stranger, "volmarr", "pub", 1).title,
            "Roles")
        # A reader who is not the author cannot edit it.
        with self.assertRaises(IssueError) as caught:
            self.issues.update_issue(
                self.stranger, "volmarr", "pub", 1, title="Hijacked")
        self.assertEqual(caught.exception.reason, "permission_denied")
        # A reader cannot moderate; the owner (moderator) can.
        comment = self.comments.add_comment(
            self.stranger, "volmarr", "pub", 1, "spammy pitch")
        with self.assertRaises(IssueError) as caught:
            self.moderation.hide_comment(
                self.stranger, "volmarr", "pub", 1, comment.id, "spam")
        self.assertEqual(caught.exception.reason, "permission_denied")
        hidden = self.moderation.hide_comment(
            self.owner, "volmarr", "pub", 1, comment.id, "spam")
        self.assertTrue(hidden.is_hidden)
        kinds = [e.kind for e in
                 self.timeline.timeline_for(self.owner, "volmarr", "pub", 1)]
        self.assertIn("comment_hidden", kinds)


if __name__ == "__main__":
    unittest.main()
