"""S-032 acceptance battery: personal access tokens (classic).

Acceptance (roadmap S-032): scopes, expiry required, shown
once, stored hashed; DB leak test as S-006 — stolen stored
values authenticate no one and the raw token is absent from
the database file.

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
from samverk.access_tokens import (
    AccessTokenError,
    AccessTokenStore,
    token_allows,
)
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain

GOOD_PW = "a long enough passphrase"
DAY = 24 * 3600


class AccessTokenTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.db_path = Path(self._td.name) / "samverk.db"
        self.conn = db.init_db(self.db_path)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.other = self.accounts.register("astrid", GOOD_PW)
        self.clock = [int(time.time())]
        self.tokens = AccessTokenStore(
            self.conn, self.accounts, audit=self.audit,
            time_fn=lambda: self.clock[0])

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def mint(self, user=None, scopes=("repo:read",), days=30):
        return self.tokens.create_token(
            (user or self.user).id, "CI script", list(scopes),
            self.clock[0] + days * DAY)

    def test_created_token_authenticates_and_is_shown_once(self):
        token, raw = self.mint()
        self.assertTrue(raw.startswith("svk_"))
        self.assertTrue(raw.startswith(token.prefix))
        self.assertEqual(token.scopes, frozenset({"repo:read"}))
        self.assertIsNone(token.last_used_at)
        found = self.tokens.authenticate(raw)
        self.assertIsNotNone(found)
        self.assertEqual(found.id, token.id)
        self.assertEqual(found.last_used_at, self.clock[0])

    def test_db_leak_values_are_unusable(self):
        """The acceptance in literal form (as S-006)."""
        token, raw = self.mint()
        self.conn.commit()
        stored_hash = self.conn.execute(
            "SELECT token_hash FROM access_tokens WHERE id = ?",
            (token.id,)).fetchone()["token_hash"]
        self.assertIsNone(self.tokens.authenticate(stored_hash))
        self.assertIsNone(self.tokens.authenticate(token.prefix))
        self.assertIsNone(self.tokens.authenticate("svk_" + stored_hash))
        db_bytes = self.db_path.read_bytes()
        self.assertNotIn(raw.encode(), db_bytes)
        self.assertNotIn(raw[len("svk_"):].encode(), db_bytes)

    def test_expiry_is_required_and_bounded(self):
        for bad, reason in ((None, "expiry_required"),
                            (self.clock[0] - 1, "expiry_in_past"),
                            (self.clock[0] + 400 * DAY, "expiry_too_far")):
            with self.assertRaises(AccessTokenError) as ctx:
                self.tokens.create_token(
                    self.user.id, "T", ["repo:read"], bad)
            self.assertEqual(ctx.exception.reason, reason)
        self.assertEqual(self.tokens.list_tokens(self.user.id), [])

    def test_expired_token_authenticates_to_nothing(self):
        token, raw = self.mint(days=1)
        self.assertIsNotNone(self.tokens.authenticate(raw))
        self.clock[0] += 2 * DAY
        self.assertIsNone(self.tokens.authenticate(raw))

    def test_scopes_are_required_and_closed(self):
        for bad, reason in (([], "scopes_required"),
                            (["repo:read", "root:everything"], "scope_unknown")):
            with self.assertRaises(AccessTokenError) as ctx:
                self.tokens.create_token(
                    self.user.id, "T", bad, self.clock[0] + DAY)
            self.assertEqual(ctx.exception.reason, reason)
        self.assertEqual(self.tokens.list_tokens(self.user.id), [])

    def test_write_scope_implies_its_read_sibling_only(self):
        token, _ = self.mint(scopes=("repo:write",))
        self.assertTrue(token_allows(token, "repo:write"))
        self.assertTrue(token_allows(token, "repo:read"))
        self.assertFalse(token_allows(token, "issues:read"))
        reader, _ = self.mint(scopes=("issues:read",))
        self.assertFalse(token_allows(reader, "issues:write"))

    def test_revoke_is_owner_only_and_final(self):
        token, raw = self.mint()
        self.assertFalse(self.tokens.revoke_token(self.other.id, token.id))
        self.assertIsNotNone(self.tokens.authenticate(raw))
        self.assertTrue(self.tokens.revoke_token(self.user.id, token.id))
        self.assertIsNone(self.tokens.authenticate(raw))
        self.assertFalse(self.tokens.revoke_token(self.user.id, token.id))
        listed = self.tokens.list_tokens(self.user.id)
        self.assertTrue(listed[0].revoked)

    def test_malformed_and_unknown_tokens_refused(self):
        for bad in (None, "", "not-a-token", "svk_", "svk_" + "A" * 43):
            self.assertIsNone(self.tokens.authenticate(bad), msg=repr(bad))

    def test_create_and_revoke_are_audited_without_the_token(self):
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
