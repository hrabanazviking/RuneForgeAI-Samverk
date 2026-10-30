"""S-050 acceptance battery: repository metadata model.

Acceptance (roadmap S-050): owner, name, description, visibility,
default branch; rename updates paths atomically.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.repositories import RepositoryError, RepositoryStore


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.audit = AuditLog(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.store = RepositoryStore(
            self.conn, self.data_root, self.accounts, audit=self.audit)
        self.repo = self.store.create_repository(
            self.owner.id, "volmarr", "samverk",
            description="The together-work", visibility="public")

    def test_metadata_defaults_and_creation_values(self):
        self.assertEqual(self.repo.description, "The together-work")
        self.assertEqual(self.repo.visibility, "public")
        self.assertEqual(self.repo.default_branch, "main")
        plain = self.store.create_repository(self.owner.id, "volmarr", "plain")
        self.assertEqual(plain.description, "")
        self.assertEqual(plain.visibility, "private")  # secure default

    def test_update_metadata_owner_only_and_validated(self):
        updated = self.store.update_metadata(
            self.owner.id, "volmarr", "samverk",
            description="New words", visibility="private")
        self.assertEqual(updated.description, "New words")
        self.assertEqual(updated.visibility, "private")
        with self.assertRaises(RepositoryError):
            self.store.update_metadata(
                self.other.id, "volmarr", "samverk", description="hijack")
        with self.assertRaises(RepositoryError):
            self.store.update_metadata(
                self.owner.id, "volmarr", "samverk", visibility="internal")
        with self.assertRaises(RepositoryError):
            self.store.update_metadata(
                self.owner.id, "volmarr", "samverk",
                description="x" * 351)

    def test_visibility_change_is_audited_as_such(self):
        self.store.update_metadata(
            self.owner.id, "volmarr", "samverk", visibility="private")
        rows = self.conn.execute(
            "SELECT action FROM audit_log"
            " WHERE action='repo.visibility.change'").fetchall()
        self.assertEqual(len(rows), 1)

    def test_default_branch_change_moves_head(self):
        updated = self.store.update_metadata(
            self.owner.id, "volmarr", "samverk", default_branch="trunk")
        self.assertEqual(updated.default_branch, "trunk")
        path = self.store.path_for("volmarr", "samverk")
        out = subprocess.run(
            ["git", f"--git-dir={path}", "symbolic-ref", "HEAD"],
            capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "refs/heads/trunk")
        with self.assertRaises(RepositoryError):
            self.store.update_metadata(
                self.owner.id, "volmarr", "samverk",
                default_branch="../evil")

    def test_rename_moves_row_and_directory_together(self):
        old_path = self.store.path_for("volmarr", "samverk")
        marker = old_path / "HEAD"
        self.assertTrue(marker.is_file())
        renamed = self.store.rename(
            self.owner.id, "volmarr", "samverk", "samverk-ng")
        self.assertEqual(renamed.name, "samverk-ng")
        self.assertFalse(old_path.exists())
        new_path = self.store.path_for("volmarr", "samverk-ng")
        self.assertTrue((new_path / "HEAD").is_file())
        self.assertIsNone(self.store.get_repository("volmarr", "samverk"))
        self.assertIsNotNone(self.store.get_repository("volmarr", "samverk-ng"))
        out = subprocess.run(
            ["git", f"--git-dir={new_path}", "rev-parse", "--is-bare-repository"],
            capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "true")

    def test_rename_refusals_leave_everything_in_place(self):
        self.store.create_repository(self.owner.id, "volmarr", "taken")
        with self.assertRaises(RepositoryError):
            self.store.rename(self.owner.id, "volmarr", "samverk", "taken")
        with self.assertRaises(RepositoryError):
            self.store.rename(self.other.id, "volmarr", "samverk", "stolen")
        with self.assertRaises(RepositoryError):
            self.store.rename(self.owner.id, "volmarr", "samverk", "../evil")
        self.assertTrue(self.store.path_for("volmarr", "samverk").is_dir())
        self.assertIsNotNone(self.store.get_repository("volmarr", "samverk"))


if __name__ == "__main__":
    unittest.main()
