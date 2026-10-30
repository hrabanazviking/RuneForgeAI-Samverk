"""S-054 acceptance battery: repository visibility enforcement.

The Part IX permission matrix, run early (roadmap S-054):
owner / collaborator / stranger / anonymous x public /
private x read / write / admin, all decided by the one
function every surface consults.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.permissions import (
    PermissionDeniedError, can_admin, can_read, can_write,
    require_role, role_for)
from samverk.repositories import RepositoryStore


class VisibilityMatrixTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.collab = self.accounts.register("collab", "correct horse battery")
        self.admin = self.accounts.register("adminuser", "correct horse battery")
        with self.conn:
            self.conn.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.store = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.public = self.store.create_repository(
            self.owner.id, "volmarr", "open", visibility="public")
        self.private = self.store.create_repository(
            self.owner.id, "volmarr", "secret", visibility="private")

    def test_owner_holds_admin_on_both_visibilities(self):
        for repo in (self.public, self.private):
            self.assertEqual(role_for(self.owner, repo), "admin")
            self.assertTrue(can_write(self.owner, repo))
            self.assertTrue(can_admin(self.owner, repo))

    def test_public_is_world_readable_never_world_writable(self):
        for viewer in (self.stranger, self.collab, None):
            self.assertTrue(can_read(viewer, self.public), viewer)
            self.assertFalse(can_write(viewer, self.public), viewer)
            self.assertFalse(can_admin(viewer, self.public), viewer)

    def test_private_is_invisible_to_strangers_and_anonymous(self):
        for viewer in (self.stranger, self.collab, None):
            self.assertIsNone(role_for(viewer, self.private), viewer)
            self.assertFalse(can_read(viewer, self.private), viewer)
            with self.assertRaises(PermissionDeniedError):
                require_role(viewer, self.private)

    def test_collaborator_role_applies_on_private(self):
        self.assertEqual(
            role_for(self.collab, self.private, collaborator_role="read"), "read")
        self.assertTrue(
            can_write(self.collab, self.private, collaborator_role="write"))
        self.assertFalse(
            can_write(self.collab, self.private, collaborator_role="read"))
        # A nonsense grant is no grant.
        self.assertIsNone(
            role_for(self.collab, self.private, collaborator_role="superuser"))

    def test_site_admin_holds_admin(self):
        self.assertEqual(role_for(self.admin, self.private), "admin")

    def test_require_role_returns_the_role_it_verified(self):
        self.assertEqual(require_role(self.owner, self.private, "write"), "admin")
        self.assertEqual(require_role(None, self.public), "read")
        with self.assertRaises(PermissionDeniedError):
            require_role(None, self.public, "write")


if __name__ == "__main__":
    unittest.main()
