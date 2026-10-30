"""S-131 acceptance battery: issue timeline.

Acceptance (roadmap S-131): every state change, label,
assignment, mention, and cross-reference an event in one
ordered stream (feeds Part XI).

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
from samverk.cross_references import CrossReferenceStore
from samverk.issue_locking import IssueLockPinStore
from samverk.issue_timeline import TimelineStore, describe_event, render_timeline
from samverk.issues import IssueError, IssueStore
from samverk.labels import LabelStore
from samverk.milestones import MilestoneStore
from samverk.repositories import RepositoryStore

FULL_OID = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"


class Clock:
    """A ticking clock: every record lands at its own second,
    in action order, so the stream's order is provable."""
    def __init__(self):
        self.t = 1_700_000_000
    def __call__(self):
        self.t += 1
        return float(self.t)


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.clock = Clock()
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.other = self.accounts.register("mallory", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.labels = LabelStore(self.conn, self.repos, self.accounts,
                                 issues=self.issues, audit=self.audit,
                                 time_fn=self.clock)
        self.assignees = AssigneeStore(self.conn, self.repos, self.accounts,
                                       self.issues, audit=self.audit,
                                       time_fn=self.clock)
        self.milestones = MilestoneStore(self.conn, self.repos, self.accounts,
                                         issues=self.issues, audit=self.audit,
                                         time_fn=self.clock)
        self.xrefs = CrossReferenceStore(
            self.conn, self.repos, self.accounts, self.issues,
            commit_resolver=lambda o, r, s: FULL_OID if FULL_OID.startswith(s) else None,
            time_fn=self.clock)
        self.timeline = TimelineStore(self.conn, self.repos, self.accounts, self.issues)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.issue = self.issues.create_issue(
            self.reader, "volmarr", "pub", "Reader's report")

    def kinds(self, viewer=None, repo="pub", number=1):
        return [e.kind for e in self.timeline.timeline_for(viewer, "volmarr", repo, number)]

    def test_new_issue_timeline_is_its_creation(self):
        events = self.timeline.timeline_for(None, "volmarr", "pub", 1)
        self.assertEqual([e.kind for e in events], ["created"])
        self.assertEqual(describe_event(events[0]), "yrsa created this issue")

    def test_full_stream_in_order_with_words(self):
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 1, "bug")
        self.assignees.assign(self.owner, "volmarr", "pub", 1, "yrsa")
        self.milestones.create_milestone(self.owner, "volmarr", "pub", "First")
        self.milestones.set_issue_milestone(self.owner, "volmarr", "pub", 1, "First")
        self.issues.close_issue(self.owner, "volmarr", "pub", 1, reason="not_planned")
        self.issues.reopen_issue(self.owner, "volmarr", "pub", 1)
        self.labels.remove_from_issue(self.owner, "volmarr", "pub", 1, "bug")
        self.assignees.unassign(self.owner, "volmarr", "pub", 1, "yrsa")
        self.milestones.set_issue_milestone(self.owner, "volmarr", "pub", 1, None)
        events = self.timeline.timeline_for(None, "volmarr", "pub", 1)
        self.assertEqual(
            [e.kind for e in events],
            ["created", "labelled", "assigned", "milestone", "closed",
             "reopened", "unlabelled", "unassigned", "milestone"])
        self.assertEqual(
            [describe_event(e) for e in events],
            ["yrsa created this issue",
             "volmarr added the bug label",
             "volmarr assigned yrsa",
             "volmarr added this issue to the First milestone",
             "volmarr closed this issue as not planned",
             "volmarr reopened this issue",
             "volmarr removed the bug label",
             "volmarr removed yrsa's assignment",
             "volmarr removed this issue from its milestone"])
        times = [e.created_at for e in events]
        self.assertEqual(times, sorted(times))

    def test_quiet_noops_leave_no_events(self):
        self.issues.close_issue(self.owner, "volmarr", "pub", 1)
        self.issues.close_issue(self.owner, "volmarr", "pub", 1, reason="not_planned")
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 1, "bug")
        self.assignees.assign(self.owner, "volmarr", "pub", 1, "yrsa")
        self.assignees.assign(self.owner, "volmarr", "pub", 1, "yrsa")
        # A repeated label-add is audited by S-124's slice as an act,
        # but a repeated assign is a no-op; state no-ops never land.
        self.assertEqual(self.kinds().count("closed"), 1)
        self.assertEqual(self.kinds().count("assigned"), 1)

    def test_mention_and_cross_reference_both_directions(self):
        source = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Source", "See #1 — fixes #1 later.")
        self.xrefs.sync_issue_references(self.owner, "volmarr", "pub", source.number)
        target_events = self.timeline.timeline_for(None, "volmarr", "pub", 1)
        mentioned = [e for e in target_events if e.kind == "mentioned"]
        self.assertEqual(len(mentioned), 1)
        self.assertEqual(describe_event(mentioned[0]),
                         "volmarr mentioned this issue in volmarr/pub#2")
        source_events = self.timeline.timeline_for(None, "volmarr", "pub", source.number)
        referenced = [e for e in source_events if e.kind == "referenced"]
        self.assertEqual(len(referenced), 1)
        self.assertTrue(referenced[0].is_closing)
        self.assertEqual(
            describe_event(referenced[0]),
            "volmarr referenced volmarr/pub#1 and marked it to close on merge")

    def test_commit_mention(self):
        self.xrefs.record_commit_references(
            "volmarr", "pub", FULL_OID, "Work on #1", author_id=self.owner.id)
        events = self.timeline.timeline_for(None, "volmarr", "pub", 1)
        mentioned = [e for e in events if e.kind == "mentioned"]
        self.assertEqual(len(mentioned), 1)
        self.assertEqual(describe_event(mentioned[0]),
                         "volmarr mentioned this issue in commit a1b2c3d")

    def test_private_source_mention_is_hidden(self):
        secret = self.issues.create_issue(
            self.owner, "volmarr", "priv", "Secret", "About volmarr/pub#1")
        self.xrefs.sync_issue_references(self.owner, "volmarr", "priv", secret.number)
        # A reader of the public target who cannot read the private
        # source sees no back-reference; the owner sees it.
        self.assertEqual(
            [e for e in self.timeline.timeline_for(self.other, "volmarr", "pub", 1)
             if e.kind == "mentioned"], [])
        self.assertEqual(
            len([e for e in self.timeline.timeline_for(self.owner, "volmarr", "pub", 1)
                 if e.kind == "mentioned"]), 1)

    def test_private_issue_timeline_is_uniformly_hidden(self):
        secret = self.issues.create_issue(self.owner, "volmarr", "priv", "Secret")
        with self.assertRaises(IssueError) as caught:
            self.timeline.timeline_for(self.other, "volmarr", "priv", secret.number)
        self.assertEqual(caught.exception.reason, "issue_not_found")
        with self.assertRaises(IssueError) as caught:
            self.timeline.timeline_for(None, "volmarr", "priv", secret.number)
        self.assertEqual(caught.exception.reason, "issue_not_found")

    def test_lock_and_pin_events_join_the_stream(self):
        controls = IssueLockPinStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        controls.pin_issue(self.owner, "volmarr", "pub", 1)
        controls.lock_issue(self.owner, "volmarr", "pub", 1, reason="too_heated")
        controls.unlock_issue(self.owner, "volmarr", "pub", 1)
        controls.unpin_issue(self.owner, "volmarr", "pub", 1)
        events = self.timeline.timeline_for(None, "volmarr", "pub", 1)
        self.assertEqual([e.kind for e in events],
                         ["created", "pinned", "locked", "unlocked", "unpinned"])
        self.assertEqual(describe_event(events[2]),
                         "volmarr locked this conversation as too heated")

    def test_rebuild_is_identical_and_render_is_words(self):
        self.labels.create_label(self.owner, "volmarr", "pub", "<b>bold</b>", "#123456")
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 1, "<b>bold</b>")
        first = self.timeline.timeline_for(None, "volmarr", "pub", 1)
        second = self.timeline.timeline_for(None, "volmarr", "pub", 1)
        self.assertEqual(first, second)
        html = render_timeline(first)
        self.assertIn("volmarr added the &lt;b&gt;bold&lt;/b&gt; label", html)
        self.assertNotIn("<b>bold</b> label", html)


if __name__ == "__main__":
    unittest.main()
