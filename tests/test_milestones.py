"""S-125 acceptance battery: milestones.

Acceptance (roadmap S-125): milestones with due dates,
progress counted from closed/total, and milestone pages
(here: the progress rendering seam the pages consume).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.issues import IssueStore
from samverk.milestones import MilestoneError, MilestoneStore, render_progress, validate_due_on
from samverk.repositories import RepositoryStore

class MilestoneTests(unittest.TestCase):
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
        # Fixed clock: 2026-10-30 12:00 UTC.
        self.milestones = MilestoneStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=lambda: 1793361600.0)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.a = self.issues.create_issue(self.owner, "volmarr", "pub", "One")
        self.b = self.issues.create_issue(self.owner, "volmarr", "pub", "Two")
        self.c = self.issues.create_issue(self.owner, "volmarr", "pub", "Three")

    def _close(self, number):
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE number = ? AND repo_id = 1",
                (number,))

    def test_crud_and_uniqueness(self):
        m = self.milestones.create_milestone(
            self.owner, "volmarr", "pub", "v1.0", "First release", "2026-12-01")
        self.assertEqual(m.state, "open"); self.assertEqual(m.due_on, "2026-12-01")
        with self.assertRaises(MilestoneError) as caught:
            self.milestones.create_milestone(self.owner, "volmarr", "pub", "V1.0")
        self.assertEqual(caught.exception.reason, "milestone_taken")
        updated = self.milestones.update_milestone(
            self.owner, "volmarr", "pub", "v1.0", description="Shipping")
        self.assertEqual(updated.description, "Shipping")
        self.assertEqual(updated.due_on, "2026-12-01")  # untouched
        cleared = self.milestones.update_milestone(
            self.owner, "volmarr", "pub", "v1.0", due_on=None)
        self.assertIsNone(cleared.due_on)
        closed = self.milestones.close_milestone(self.owner, "volmarr", "pub", "v1.0")
        self.assertEqual(closed.state, "closed")
        self.assertEqual(self.milestones.list_milestones(None, "volmarr", "pub", state="open"), [])
        reopened = self.milestones.reopen_milestone(self.owner, "volmarr", "pub", "v1.0")
        self.assertEqual(reopened.state, "open")

    def test_due_dates_must_be_real_dates(self):
        for bad in ("2026-02-30", "2026-13-01", "30-10-2026", "2026-10-30T00:00", "soon", 7):
            with self.assertRaises(MilestoneError) as caught:
                validate_due_on(bad)
            self.assertEqual(caught.exception.reason, "due_date_invalid", bad)
        self.assertIsNone(validate_due_on(None))
        self.assertEqual(validate_due_on("2028-02-29"), "2028-02-29")  # leap day is real

    def test_progress_counts_closed_over_total(self):
        self.milestones.create_milestone(self.owner, "volmarr", "pub", "v1.0")
        empty = self.milestones.progress_for(None, "volmarr", "pub", "v1.0")
        self.assertEqual((empty.total, empty.percent_closed), (0, 0))
        self.assertEqual(empty.summary, "No issues in this milestone yet.")
        for issue in (self.a, self.b, self.c):
            self.milestones.set_issue_milestone(
                self.owner, "volmarr", "pub", issue.number, "v1.0")
        self._close(self.a.number)
        progress = self.milestones.progress_for(None, "volmarr", "pub", "v1.0")
        self.assertEqual((progress.open_count, progress.closed_count, progress.total), (2, 1, 3))
        self.assertEqual(progress.percent_closed, 33)
        self.assertEqual(progress.summary, "1 of 3 issues closed (33%).")
        html = render_progress(
            self.milestones.get_milestone(None, "volmarr", "pub", "v1.0"), progress)
        self.assertIn("1 of 3 issues closed (33%)", html)
        self.assertIn("No due date", html)

    def test_overdue_is_named_in_words(self):
        # Clock is 2026-10-30; a milestone due 2026-10-01, still
        # open, is overdue — and stops being so once closed.
        self.milestones.create_milestone(
            self.owner, "volmarr", "pub", "late", due_on="2026-10-01")
        progress = self.milestones.progress_for(None, "volmarr", "pub", "late")
        self.assertTrue(progress.is_overdue)
        html = render_progress(
            self.milestones.get_milestone(None, "volmarr", "pub", "late"), progress)
        self.assertIn("Overdue", html)
        self.milestones.close_milestone(self.owner, "volmarr", "pub", "late")
        self.assertFalse(
            self.milestones.progress_for(None, "volmarr", "pub", "late").is_overdue)

    def test_assignment_clear_and_delete_unassigns(self):
        self.milestones.create_milestone(self.owner, "volmarr", "pub", "v1.0")
        self.milestones.set_issue_milestone(self.owner, "volmarr", "pub", 1, "v1.0")
        self.assertEqual(
            self.milestones.milestone_for_issue(None, "volmarr", "pub", 1).title, "v1.0")
        self.assertEqual(self.milestones.list_issue_numbers(None, "volmarr", "pub", "v1.0"), [1])
        cleared = self.milestones.set_issue_milestone(
            self.owner, "volmarr", "pub", 1, None)
        self.assertIsNone(cleared)
        self.assertIsNone(self.milestones.milestone_for_issue(None, "volmarr", "pub", 1))
        self.milestones.set_issue_milestone(self.owner, "volmarr", "pub", 1, "v1.0")
        self.milestones.delete_milestone(self.owner, "volmarr", "pub", "v1.0")
        self.assertIsNone(self.milestones.milestone_for_issue(None, "volmarr", "pub", 1))
        # The issue itself survives its milestone.
        self.assertEqual(self.issues.get_issue(None, "volmarr", "pub", 1).title, "One")
        rows = self.conn.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'repo.milestone.%'"
            " OR action = 'repo.issue.milestone' ORDER BY seq").fetchall()
        self.assertEqual([r["action"] for r in rows], [
            "repo.milestone.create", "repo.issue.milestone",
            "repo.issue.milestone", "repo.issue.milestone",
            "repo.milestone.delete"])

    def test_permissions_and_private_uniform_answer(self):
        with self.assertRaises(MilestoneError) as caught:
            self.milestones.create_milestone(self.reader, "volmarr", "pub", "nope")
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.milestones.create_milestone(self.owner, "volmarr", "priv", "secret-plan")
        for viewer in (None, self.other):
            with self.assertRaises(MilestoneError) as caught:
                self.milestones.list_milestones(viewer, "volmarr", "priv")
            self.assertEqual(caught.exception.reason, "repo_not_found")
        self.assertEqual(
            [m.title for m in self.milestones.list_milestones(self.owner, "volmarr", "priv")],
            ["secret-plan"])

    def test_title_required_and_assignment_permission(self):
        for title in ("", "  ", None):
            with self.assertRaises(MilestoneError) as caught:
                self.milestones.create_milestone(self.owner, "volmarr", "pub", title)
            self.assertEqual(caught.exception.reason, "milestone_title_required")
        self.milestones.create_milestone(self.owner, "volmarr", "pub", "v1.0")
        with self.assertRaises(MilestoneError) as caught:
            self.milestones.set_issue_milestone(self.reader, "volmarr", "pub", 1, "v1.0")
        self.assertEqual(caught.exception.reason, "permission_denied")
        with self.assertRaises(MilestoneError) as caught:
            self.milestones.set_issue_milestone(self.owner, "volmarr", "pub", 1, "ghost")
        self.assertEqual(caught.exception.reason, "milestone_not_found")

if __name__ == "__main__":
    unittest.main()
