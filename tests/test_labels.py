"""S-124 acceptance battery: labels.

Acceptance (roadmap S-124): labels CRUD, colours with
mandatory text (never colour-only meaning), and a default
label set for new repositories.

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
from samverk.labels import DEFAULT_LABELS, LabelError, LabelStore, render_label, validate_colour
from samverk.repositories import RepositoryStore

class LabelTests(unittest.TestCase):
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
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.issue = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Needs triage")

    def test_new_repo_is_born_with_defaults(self):
        names = [l.name for l in self.labels.list_labels(None, "volmarr", "pub")]
        self.assertEqual(names, sorted(n for n, _, _ in DEFAULT_LABELS))
        bug = self.labels.get_label(None, "volmarr", "pub", "BUG")
        self.assertEqual(bug.colour, "#d73a4a")
        self.assertEqual(bug.description, "Something isn't working")
        # Seeding again adds nothing.
        before = len(self.labels.list_labels(None, "volmarr", "pub"))
        self.labels.seed_default_labels(self.owner, "volmarr", "pub")
        self.assertEqual(len(self.labels.list_labels(None, "volmarr", "pub")), before)

    def test_colour_requires_a_name_and_a_valid_hex(self):
        for name in ("", "   ", None):
            with self.assertRaises(LabelError) as caught:
                self.labels.create_label(self.owner, "volmarr", "pub", name, "#ff0000")
            self.assertEqual(caught.exception.reason, "label_name_required")
        for colour in ("red", "#fff", "#gggggg", "12345", None, 7):
            with self.assertRaises(LabelError) as caught:
                self.labels.create_label(self.owner, "volmarr", "pub", "hot", colour)
            self.assertEqual(caught.exception.reason, "colour_invalid")
        self.assertEqual(validate_colour("D73A4A"), "#d73a4a")
        self.assertEqual(validate_colour("#A2EEEF"), "#a2eeef")

    def test_render_carries_name_and_colour_as_text(self):
        label = self.labels.create_label(
            self.owner, "volmarr", "pub", "urgent", "#ff0000", "Drop everything")
        html = render_label(label)
        self.assertIn("urgent", html)
        self.assertIn("#ff0000", html)
        self.assertNotIn("<script", html)
        hostile = self.labels.create_label(
            self.owner, "volmarr", "pub", "<b>bold</b>", "#00ff00")
        self.assertNotIn("<b>bold</b>", render_label(hostile))
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", render_label(hostile))

    def test_crud_and_case_insensitive_uniqueness(self):
        label = self.labels.create_label(
            self.owner, "volmarr", "pub", "Triage", "#123456", "First look")
        self.assertEqual(label.name, "Triage")
        with self.assertRaises(LabelError) as caught:
            self.labels.create_label(self.owner, "volmarr", "pub", "triage", "#000000")
        self.assertEqual(caught.exception.reason, "label_taken")
        updated = self.labels.update_label(
            self.owner, "volmarr", "pub", "TRIAGE", new_name="triage-2",
            colour="#654321")
        self.assertEqual(updated.name, "triage-2")
        self.assertEqual(updated.colour, "#654321")
        self.assertEqual(updated.description, "First look")
        with self.assertRaises(LabelError) as caught:
            self.labels.update_label(
                self.owner, "volmarr", "pub", "triage-2", new_name="bug")
        self.assertEqual(caught.exception.reason, "label_taken")
        deleted = self.labels.delete_label(self.owner, "volmarr", "pub", "triage-2")
        self.assertEqual(deleted.name, "triage-2")
        with self.assertRaises(LabelError) as caught:
            self.labels.get_label(None, "volmarr", "pub", "triage-2")
        self.assertEqual(caught.exception.reason, "label_not_found")
        rows = self.conn.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'repo.label.%'"
            " ORDER BY id").fetchall()
        self.assertEqual([r["action"] for r in rows],
                         ["repo.label.create", "repo.label.update", "repo.label.delete"])

    def test_permissions_and_private_uniform_answer(self):
        # A reader cannot manage labels; a stranger to a private
        # repo gets the uniform not-found, not a refusal.
        with self.assertRaises(LabelError) as caught:
            self.labels.create_label(self.reader, "volmarr", "pub", "x", "#000000")
        self.assertEqual(caught.exception.reason, "permission_denied")
        for viewer in (None, self.other):
            with self.assertRaises(LabelError) as caught:
                self.labels.list_labels(viewer, "volmarr", "priv")
            self.assertEqual(caught.exception.reason, "repo_not_found")
        self.assertEqual(len(self.labels.list_labels(self.owner, "volmarr", "priv")), 9)

    def test_assign_remove_and_delete_cleans_assignments(self):
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 1, "bug")
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 1, "bug")
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 1, "question")
        got = self.labels.labels_for_issue(None, "volmarr", "pub", 1)
        self.assertEqual([l.name for l in got], ["bug", "question"])
        with self.assertRaises(LabelError) as caught:
            self.labels.add_to_issue(self.owner, "volmarr", "pub", 1, "nope")
        self.assertEqual(caught.exception.reason, "label_not_found")
        with self.assertRaises(LabelError) as caught:
            self.labels.add_to_issue(self.reader, "volmarr", "pub", 1, "bug")
        self.assertEqual(caught.exception.reason, "permission_denied")
        remaining = self.labels.remove_from_issue(self.owner, "volmarr", "pub", 1, "bug")
        self.assertEqual([l.name for l in remaining], ["question"])
        # Deleting a label takes its assignments with it.
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 1, "bug")
        self.labels.delete_label(self.owner, "volmarr", "pub", "bug")
        self.assertEqual(
            [l.name for l in self.labels.labels_for_issue(None, "volmarr", "pub", 1)],
            ["question"])

    def test_private_issue_labels_are_hidden(self):
        priv = self.issues.create_issue(self.owner, "volmarr", "priv", "Secret")
        self.labels.add_to_issue(self.owner, "volmarr", "priv", priv.number, "bug")
        with self.assertRaises(LabelError) as caught:
            self.labels.labels_for_issue(self.other, "volmarr", "priv", priv.number)
        self.assertEqual(caught.exception.reason, "issue_not_found")

    def test_issue_author_may_label_their_own_issue(self):
        # The reader filed nothing here; make the reader an issue
        # author on a fresh issue, then let them label it — while
        # a non-author reader still cannot.
        mine = self.issues.create_issue(self.reader, "volmarr", "pub", "My report")
        self.labels.add_to_issue(self.reader, "volmarr", "pub", mine.number, "question")
        self.assertEqual(
            [l.name for l in self.labels.labels_for_issue(None, "volmarr", "pub", mine.number)],
            ["question"])

if __name__ == "__main__":
    unittest.main()
