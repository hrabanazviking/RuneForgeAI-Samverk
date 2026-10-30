"""S-033 acceptance battery: fine-grained tokens.

Acceptance (roadmap S-033): per-repository, per-permission
tokens; the permission matrix battery — every granted and
ungranted permission, on its own repo and on others, is
checked in both directions.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.fine_grained_tokens import (
    FINE_PERMISSIONS,
    FineTokenError,
    FineTokenStore,
    permission_allows,
)

GOOD_PW = "a long enough passphrase"
DAY = 24 * 3600
OWNER, REPO = "volmarr", "samverk"


class FineTokenTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.db_path = Path(self._td.name) / "samverk.db"
        self.conn = db.init_db(self.db_path)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.other = self.accounts.register("astrid", GOOD_PW)
        self.clock = [int(time.time())]
        self.tokens = FineTokenStore(
            self.conn, self.accounts, audit=self.audit,
            time_fn=lambda: self.clock[0])

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def mint(self, perms=("contents:read",), owner=OWNER, repo=REPO, days=30):
        return self.tokens.create_token(
            self.user.id, owner, repo, "bot token", list(perms),
            self.clock[0] + days * DAY)

    def test_permission_matrix(self):
        """The acceptance in literal form: granted permissions
        pass on the token's repo; everything else fails."""
        _, raw = self.mint(perms=("contents:read", "issues:write"))
        granted = {"contents:read", "issues:read", "issues:write",
                   "metadata:read"}
        for perm in sorted(FINE_PERMISSIONS):
            got = self.tokens.authorize(raw, OWNER, REPO, perm)
            if perm in granted:
                self.assertIsNotNone(got, msg=perm)
            else:
                self.assertIsNone(got, msg=perm)
        # Case-insensitive repo identity is the same repo.
        self.assertIsNotNone(
            self.tokens.authorize(raw, "Volmarr", "Samverk", "contents:read"))
        # Another repo, another owner, an unknown permission: None.
        self.assertIsNone(
            self.tokens.authorize(raw, OWNER, "other-repo", "contents:read"))
        self.assertIsNone(
            self.tokens.authorize(raw, "astrid", REPO, "contents:read"))
        self.assertIsNone(
            self.tokens.authorize(raw, OWNER, REPO, "admin:write"))

    def test_write_implies_only_its_own_read(self):
        token, _ = self.mint(perms=("contents:write",))
        self.assertTrue(permission_allows(token, "contents:write"))
        self.assertTrue(permission_allows(token, "contents:read"))
        self.assertFalse(permission_allows(token, "issues:read"))
        self.assertFalse(permission_allows(token, "pull_requests:read"))

    def test_metadata_read_is_mandatory_and_stored(self):
        token, _ = self.mint(perms=("issues:read",))
        self.assertIn("metadata:read", token.permissions)
        listed = self.tokens.list_for_repo(OWNER, REPO)
        self.assertEqual([t.id for t in listed], [token.id])

    def test_permissions_required_and_closed(self):
        for bad, reason in (([], "permissions_required"),
                            (["contents:read", "root:all"], "permission_unknown")):
            with self.assertRaises(FineTokenError) as ctx:
                self.tokens.create_token(
                    self.user.id, OWNER, REPO, "T", bad,
                    self.clock[0] + DAY)
            self.assertEqual(ctx.exception.reason, reason)

    def test_repo_name_law_applies(self):
        with self.assertRaises(FineTokenError):
            self.mint(owner="..", repo=REPO)
        with self.assertRaises(FineTokenError):
            self.mint(repo="bad/name")

    def test_db_leak_and_shown_once(self):
        token, raw = self.mint()
        self.conn.commit()
        stored_hash = self.conn.execute(
            "SELECT token_hash FROM fine_grained_tokens WHERE id = ?",
            (token.id,)).fetchone()["token_hash"]
        self.assertIsNone(self.tokens.authenticate(stored_hash))
        self.assertNotIn(raw.encode(), self.db_path.read_bytes())
        classic = self.tokens.authenticate(
            raw.replace("svkf_", "svk_", 1))
        self.assertIsNone(classic)

    def test_expiry_and_revocation_end_authorization(self):
        token, raw = self.mint(days=1)
        self.assertIsNotNone(
            self.tokens.authorize(raw, OWNER, REPO, "contents:read"))
        self.clock[0] += 2 * DAY
        self.assertIsNone(
            self.tokens.authorize(raw, OWNER, REPO, "contents:read"))
        token2, raw2 = self.mint()
        self.assertFalse(self.tokens.revoke_token(self.other.id, token2.id))
        self.assertTrue(self.tokens.revoke_token(self.user.id, token2.id))
        self.assertIsNone(
            self.tokens.authorize(raw2, OWNER, REPO, "contents:read"))

    def test_expiry_required(self):
        with self.assertRaises(FineTokenError) as ctx:
            self.tokens.create_token(
                self.user.id, OWNER, REPO, "T", ["contents:read"], None)
        self.assertEqual(ctx.exception.reason, "expiry_required")

    def test_audited_without_the_token(self):
        token, raw = self.mint()
        self.tokens.revoke_token(self.user.id, token.id)
        rows = self.conn.execute(
            "SELECT action, detail FROM audit_log ORDER BY seq").fetchall()
        actions = [r["action"] for r in rows]
        self.assertIn("auth.token.create", actions)
        self.assertIn("auth.token.revoke", actions)
        for r in rows:
            self.assertNotIn(raw, r["detail"] or "")
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, msg=f"chain broken at {bad}")


if __name__ == "__main__":
    unittest.main()
