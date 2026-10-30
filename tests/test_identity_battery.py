"""S-048 Part II gate battery: the assembled identity system
under attack, plus the findability walk.

This is Part II's inheritance of S-022's security battery:
where Part I had no per-user resources for classic IDOR to
strike, Part II is made of them — sessions, tokens, keys,
profiles, links, histories — so this battery strikes across
accounts at every seam and requires every one to hold:
nothing authenticates that should not, nothing belonging to
one account can be revoked, read, or claimed by another.

The gate's second half is human: the token page findability
walk (settings home -> one click -> token page -> revoke)
is exercised end to end, as S-034 promised.

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
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.fine_grained_tokens import FineTokenStore
from samverk.identity_linking import IdentityLinkStore
from samverk.login import LoginFailed, LoginService
from samverk.login_history import LoginHistory
from samverk.session_management import SessionManagement
from samverk.sessions import SessionStore
from samverk.token_management import (
    TokenManagement, render_settings_home, render_token_list_page)

GOOD_PW = "a long enough passphrase"


class IdentityBatteryTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.clock = [int(time.time())]
        now = lambda: self.clock[0]  # noqa: E731
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=now)
        self.alice = self.accounts.register("alice", GOOD_PW)
        self.mallory = self.accounts.register("mallory", GOOD_PW)
        self.sessions = SessionStore(self.conn, time_fn=now)
        self.login = LoginService(
            self.conn, self.accounts, self.sessions,
            audit=self.audit, time_fn=now)
        self.classic = AccessTokenStore(
            self.conn, self.accounts, audit=self.audit, time_fn=now)
        self.fine = FineTokenStore(
            self.conn, self.accounts, audit=self.audit, time_fn=now)
        self.tokens = TokenManagement(
            self.conn, self.accounts, self.classic, self.fine, time_fn=now)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_fabricated_credentials_authenticate_no_one(self):
        self.assertIsNone(self.sessions.authenticate("forged-token"))
        self.assertIsNone(self.classic.authenticate("svk_forged"))
        with self.assertRaises(LoginFailed):
            self.login.login("alice", "not the password at all")

    def test_cross_account_token_revoke_fails(self):
        summary, raw = self.classic.create_token(
            self.alice.id, "alice-ci", {"repo:read"},
            self.clock[0] + 3600)
        self.assertFalse(self.tokens.revoke(
            self.mallory.id, "classic", summary.id))
        # Alice's token still works.
        self.assertEqual(
            self.classic.authenticate(raw).id, self.alice.id)

    def test_cross_account_session_revoke_fails(self):
        token = self.login.login("alice", GOOD_PW)
        mgmt = SessionManagement(
            self.conn, self.accounts, self.sessions, audit=self.audit)
        mine = mgmt.list_sessions(self.alice.id)
        self.assertEqual(len(mine), 1)
        self.assertFalse(mgmt.revoke_one(self.mallory.id, mine[0].id))
        self.assertEqual(self.sessions.authenticate(token), self.alice.id)

    def test_fine_token_matrix_holds_at_the_gate(self):
        _summary, raw = self.fine.create_token(
            self.alice.id, "alice", "repo", "alice-bot",
            {"contents:read"}, self.clock[0] + 3600)
        self.assertIsNotNone(self.fine.authorize(
            raw, "alice", "repo", "contents:read"))
        self.assertIsNone(self.fine.authorize(
            raw, "alice", "repo", "contents:write"))
        self.assertIsNone(self.fine.authorize(
            raw, "mallory", "repo", "contents:read"))
        self.assertIsNone(self.fine.authorize(
            raw, "alice", "other", "contents:read"))

    def test_histories_and_links_do_not_cross_accounts(self):
        self.login.login("alice", GOOD_PW)
        history = LoginHistory(self.conn, self.accounts)
        self.assertEqual(
            [e for e in history.history_for(self.mallory.id)
             if e.action == "auth.login.success"], [])
        links = IdentityLinkStore(
            self.conn, self.accounts, audit=self.audit)
        links.link(self.alice.id, "samtal", "seat-1")
        from samverk.identity_linking import IdentityLinkError
        with self.assertRaises(IdentityLinkError):
            links.link(self.mallory.id, "samtal", "seat-1")

    def test_db_leak_buys_no_identity(self):
        _summary, raw = self.classic.create_token(
            self.alice.id, "leak-check", {"repo:read"},
            self.clock[0] + 3600)
        row = self.conn.execute(
            "SELECT token_hash, prefix FROM access_tokens"
            " WHERE user_id = ?", (self.alice.id,)).fetchone()
        self.assertIsNone(self.classic.authenticate(row["token_hash"]))
        self.assertIsNone(self.classic.authenticate(row["prefix"]))
        # The raw database file carries no usable token.
        db_bytes = Path(self._td.name, "samverk.db").read_bytes()
        self.assertNotIn(raw.encode(), db_bytes)

    def test_token_findability_walk(self):
        home = render_settings_home("alice")
        self.assertIn("/settings/tokens", home)
        summary, _raw = self.classic.create_token(
            self.alice.id, "walk-token", {"repo:read"},
            self.clock[0] + 3600)
        page = render_token_list_page(
            "alice", self.tokens.list_all(self.alice.id),
            csrf_token="csrf-x")
        self.assertIn("walk-token", page)
        self.assertIn("Revoke", page)
        self.assertTrue(self.tokens.revoke(
            self.alice.id, "classic", summary.id))
        page2 = render_token_list_page(
            "alice", self.tokens.list_all(self.alice.id))
        self.assertIn("Revoked", page2)

    def test_audit_chain_survives_the_battery(self):
        self.login.login("alice", GOOD_PW)
        ok, bad, checked = verify_chain(self.conn)
        self.assertTrue(ok, bad)
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
