"""S-049 acceptance battery: bare repository creation.

Acceptance (roadmap S-049): `git init --bare` under the
traversal-proof path of S-013; metadata row written in the
commit-before-answer shape.

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
from samverk.audit import AuditLog, verify_chain
from samverk.repositories import RepositoryError, RepositoryStore


class BareCreationTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.db_path = self.data_root / "samverk.db"
        self.conn = db.init_db(self.db_path)
        self.accounts = AccountStore(self.conn)
        self.audit = AuditLog(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.store = RepositoryStore(
            self.conn, self.data_root, self.accounts, audit=self.audit)

    def test_create_makes_a_real_bare_repo_and_a_committed_row(self):
        repo = self.store.create_repository(self.owner.id, "volmarr", "samverk")
        path = self.store.path_for("volmarr", "samverk")
        self.assertTrue((path / "HEAD").is_file())
        self.assertTrue((path / "objects").is_dir())
        self.assertTrue((path / "refs").is_dir())
        out = subprocess.run(
            ["git", f"--git-dir={path}", "rev-parse", "--is-bare-repository"],
            capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "true")
        head = subprocess.run(
            ["git", f"--git-dir={path}", "symbolic-ref", "HEAD"],
            capture_output=True, text=True)
        self.assertEqual(head.stdout.strip(), "refs/heads/main")
        # Commit-before-answer: a *separate* connection sees the row.
        other_conn = db.connect(self.db_path)
        row = other_conn.execute(
            "SELECT * FROM repositories WHERE owner_lower='volmarr'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "samverk")
        self.assertEqual(repo.full_name, "volmarr/samverk")

    def test_duplicate_any_case_is_refused_and_creates_nothing_new(self):
        self.store.create_repository(self.owner.id, "volmarr", "samverk")
        with self.assertRaises(RepositoryError) as caught:
            self.store.create_repository(self.owner.id, "Volmarr", "SAMVERK")
        self.assertEqual(caught.exception.reason, "repo_taken")
        self.assertEqual(len(self.store.list_for_owner("volmarr")), 1)

    def test_only_the_owner_can_create(self):
        with self.assertRaises(RepositoryError) as caught:
            self.store.create_repository(self.other.id, "volmarr", "stolen")
        self.assertEqual(caught.exception.reason, "not_repo_owner")
        self.assertFalse(self.store.path_for("volmarr", "stolen").exists())
        self.assertIsNone(self.store.get_repository("volmarr", "stolen"))

    def test_traversal_names_are_refused_before_disk(self):
        for bad in ("../escape", "a/b", "..", "a..b"):
            with self.assertRaises(RepositoryError, msg=bad):
                self.store.create_repository(self.owner.id, "volmarr", bad)
        self.assertEqual(self.store.list_for_owner("volmarr"), [])

    def test_preexisting_directory_is_refused_not_adopted(self):
        path = self.store.path_for("volmarr", "squatted")
        path.mkdir(parents=True)
        (path / "marker").write_text("not ours")
        with self.assertRaises(RepositoryError) as caught:
            self.store.create_repository(self.owner.id, "volmarr", "squatted")
        self.assertEqual(caught.exception.reason, "repo_path_exists")
        self.assertEqual((path / "marker").read_text(), "not ours")
        self.assertIsNone(self.store.get_repository("volmarr", "squatted"))

    def test_creation_is_audited(self):
        self.store.create_repository(self.owner.id, "volmarr", "samverk")
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, bad)
        rows = self.conn.execute(
            "SELECT action FROM audit_log WHERE action='repo.create'").fetchall()
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
