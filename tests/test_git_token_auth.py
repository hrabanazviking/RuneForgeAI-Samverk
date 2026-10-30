"""S-082 acceptance battery: token-as-password.

Acceptance (roadmap S-082): personal access tokens work in the
Basic password slot, scoped per S-032/S-033 — a read-only
token's push is refused.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore
from samverk.fine_grained_tokens import FineTokenStore
from samverk.git_auth import GitAuthenticator
from test_git_basic_auth import basic

YEAR = int(time.time()) + 30 * 24 * 3600


class TokenAuthTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register(
            "volmarr", "correct horse battery")
        self.classic = AccessTokenStore(self.conn, self.accounts)
        self.fine = FineTokenStore(self.conn, self.accounts)
        self.auth = GitAuthenticator(self.conn, self.accounts)
        _, self.read_raw = self.classic.create_token(
            self.owner.id, "reader", {"repo:read"}, YEAR)
        _, self.write_raw = self.classic.create_token(
            self.owner.id, "writer", {"repo:write"}, YEAR)
        _, self.fine_read = self.fine.create_token(
            self.owner.id, "volmarr", "open", "fine reader",
            {"contents:read", "metadata:read"}, YEAR)
        _, self.fine_write = self.fine.create_token(
            self.owner.id, "volmarr", "open", "fine writer",
            {"contents:write", "metadata:read"}, YEAR)

    def test_classic_token_authenticates_as_its_owner(self):
        for username in ("volmarr", "x-access-token"):
            user = self.auth.authenticate_basic(basic(username, self.read_raw))
            self.assertIsNotNone(user, msg=username)
            self.assertEqual(user.id, self.owner.id)

    def test_read_only_token_push_is_refused(self):
        # The roadmap's named acceptance: the read token reads…
        self.assertIsNotNone(self.auth.authorize_basic(
            basic("volmarr", self.read_raw), "volmarr", "open", "read"))
        # …and its push is refused, at the credential gate.
        self.assertIsNone(self.auth.authorize_basic(
            basic("volmarr", self.read_raw), "volmarr", "open", "write"))
        # The write token does both (repo:write implies read).
        self.assertIsNotNone(self.auth.authorize_basic(
            basic("volmarr", self.write_raw), "volmarr", "open", "write"))
        self.assertIsNotNone(self.auth.authorize_basic(
            basic("volmarr", self.write_raw), "volmarr", "open", "read"))

    def test_fine_token_is_bound_to_its_one_repository(self):
        self.assertIsNotNone(self.auth.authorize_basic(
            basic("volmarr", self.fine_read), "volmarr", "open", "read"))
        self.assertIsNone(self.auth.authorize_basic(
            basic("volmarr", self.fine_read), "volmarr", "open", "write"))
        self.assertIsNone(self.auth.authorize_basic(
            basic("volmarr", self.fine_read), "volmarr", "other", "read"))
        self.assertIsNotNone(self.auth.authorize_basic(
            basic("volmarr", self.fine_write), "volmarr", "open", "write"))

    def test_token_under_a_strangers_name_resolves_to_nothing(self):
        self.assertIsNone(self.auth.authenticate_basic(
            basic("yrsa", self.read_raw)))
        self.assertIsNone(self.auth.authorize_basic(
            basic("yrsa", self.write_raw), "volmarr", "open", "write"))

    def test_revoked_and_expired_tokens_authenticate_to_nothing(self):
        token, raw = self.classic.create_token(
            self.owner.id, "short-lived", {"repo:read"}, YEAR)
        self.classic.revoke_token(self.owner.id, token.id)
        self.assertIsNone(self.auth.authenticate_basic(basic("volmarr", raw)))
        _, stale = self.classic.create_token(
            self.owner.id, "stale", {"repo:read"}, int(time.time()) + 60)
        # Wind the store's clock past the expiry by direct row
        # surgery — the shape an actually-old token has.
        self.conn.execute(
            "UPDATE access_tokens SET expires_at = ? WHERE prefix = ?",
            (int(time.time()) - 1, stale[:12]))
        self.conn.commit()
        self.assertIsNone(self.auth.authenticate_basic(basic("volmarr", stale)))

    def test_token_of_a_suspended_account_resolves_to_nothing(self):
        self.accounts.set_status(self.owner.id, "suspended")
        self.assertIsNone(self.auth.authenticate_basic(
            basic("volmarr", self.write_raw)))
        self.assertIsNone(self.auth.authorize_basic(
            basic("volmarr", self.write_raw), "volmarr", "open", "write"))

    def test_password_road_still_answers_authorize(self):
        self.assertIsNotNone(self.auth.authorize_basic(
            basic("volmarr", "correct horse battery"),
            "volmarr", "open", "write"))
        self.assertIsNone(self.auth.authorize_basic(
            basic("volmarr", "wrong horse battery"),
            "volmarr", "open", "read"))


if __name__ == "__main__":
    unittest.main()
