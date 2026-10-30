"""S-036 acceptance battery: sudo mode.

Acceptance (roadmap S-036): sensitive actions (keys, tokens,
2FA, deletion) require fresh re-authentication within a time
window — proven here by the window's lifecycle and by the
real verifier driving S-030's SSH key-add gate, the seam
S-030 left for exactly this slice. Includes the DB-leak test:
a grant row holds only the session token's hash.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import base64
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.sessions import SessionStore
from samverk.ssh_keys import SshKeyError, SshKeyStore
from samverk.sudo_mode import (
    WINDOW_SECONDS,
    SudoFailed,
    SudoMode,
    SudoRequiredError,
)

GOOD_PW = "a long enough passphrase"


def make_key_line(material: bytes = b"\x07" * 32) -> str:
    blob = (struct.pack(">I", 11) + b"ssh-ed25519"
            + struct.pack(">I", 32) + material)
    return "ssh-ed25519 " + base64.b64encode(blob).decode() + " laptop"


class SudoModeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.db_path = Path(self._td.name) / "samverk.db"
        self.conn = db.init_db(self.db_path)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.clock = [int(time.time())]
        now = lambda: self.clock[0]  # noqa: E731
        self.sessions = SessionStore(self.conn, time_fn=now)
        self.token = self.sessions.create(self.user.id)
        self.other_token = self.sessions.create(self.user.id)
        self.sudo = SudoMode(self.conn, self.accounts, time_fn=now)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_grant_with_password_opens_the_window(self):
        expires = self.sudo.grant(self.user.id, GOOD_PW, self.token)
        self.assertEqual(expires, self.clock[0] + WINDOW_SECONDS)
        self.assertTrue(self.sudo.is_fresh(self.user.id, self.token))
        self.sudo.require_fresh(self.user.id, self.token)

    def test_wrong_password_and_unknown_user_grant_nothing(self):
        for uid, pw in ((self.user.id, "wrong password here"),
                        (99999, GOOD_PW), (self.user.id, None)):
            with self.assertRaises(SudoFailed):
                self.sudo.grant(uid, pw, self.token)
        self.assertFalse(self.sudo.is_fresh(self.user.id, self.token))
        with self.assertRaises(SudoRequiredError):
            self.sudo.require_fresh(self.user.id, self.token)

    def test_window_expires(self):
        self.sudo.grant(self.user.id, GOOD_PW, self.token)
        self.clock[0] += WINDOW_SECONDS - 1
        self.assertTrue(self.sudo.is_fresh(self.user.id, self.token))
        self.clock[0] += 1
        self.assertFalse(self.sudo.is_fresh(self.user.id, self.token))
        self.assertIsNone(self.sudo.expires_at(self.user.id, self.token))

    def test_grant_is_bound_to_its_session(self):
        self.sudo.grant(self.user.id, GOOD_PW, self.token)
        self.assertFalse(
            self.sudo.is_fresh(self.user.id, self.other_token))
        self.assertFalse(self.sudo.is_fresh(self.user.id, ""))
        self.assertTrue(self.sudo.revoke(self.user.id, self.token))
        self.assertFalse(self.sudo.is_fresh(self.user.id, self.token))

    def test_grant_row_holds_only_the_session_hash(self):
        self.sudo.grant(self.user.id, GOOD_PW, self.token)
        self.assertNotIn(self.token.encode("ascii"),
                         self.db_path.read_bytes())
        # …and the stored hash itself buys no freshness.
        stored = self.conn.execute(
            "SELECT session_hash FROM sudo_grants").fetchone()
        self.assertFalse(
            self.sudo.is_fresh(self.user.id, stored["session_hash"]))

    def test_real_verifier_drives_the_ssh_key_gate(self):
        """S-030's promise, kept: its seam, this slice's verifier."""
        keys = SshKeyStore(
            self.conn, self.accounts, audit=self.audit,
            reauth_verifier=self.sudo.as_verifier(self.token))
        with self.assertRaises(SshKeyError) as ctx:
            keys.add_key(self.user.id, "Laptop", make_key_line())
        self.assertEqual(ctx.exception.reason, "sudo_required")
        self.sudo.grant(self.user.id, GOOD_PW, self.token)
        key = keys.add_key(self.user.id, "Laptop", make_key_line())
        self.assertEqual(key.title, "Laptop")
        self.clock[0] += WINDOW_SECONDS + 1
        with self.assertRaises(SshKeyError):
            keys.add_key(self.user.id, "Second",
                         make_key_line(b"\x08" * 32))


if __name__ == "__main__":
    unittest.main()
