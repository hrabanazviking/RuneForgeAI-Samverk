"""S-042 acceptance battery: account rename.

Acceptance (roadmap S-042): account rename — the old name
redirects (for repos, via the resolution seam Part III will
ride) with a tombstone period; collisions are refused.
Proven: the rename itself, the redirect, registration and
rename collisions against live names and held tombstones,
the tombstone lapsing, renaming back, case-only changes,
and sessions surviving a rename (they key on the account
id, not the name).

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
from samverk.accounts import (
    TOMBSTONE_SECONDS,
    AccountStore,
    RegistrationError,
)
from samverk.audit import AuditLog
from samverk.login import LoginService
from samverk.sessions import SessionStore

GOOD_PW = "a long enough passphrase"


class AccountRenameTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.clock = [int(time.time())]
        now = lambda: self.clock[0]  # noqa: E731
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=now)
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.other = self.accounts.register("astrid", GOOD_PW)
        self.sessions = SessionStore(self.conn, time_fn=now)
        self.login = LoginService(
            self.conn, self.accounts, self.sessions,
            audit=self.audit, time_fn=now)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_rename_moves_the_name_and_old_name_redirects(self):
        renamed = self.accounts.rename(self.user.id, "wyrdwalker")
        self.assertEqual(renamed.username, "wyrdwalker")
        self.assertIsNone(self.accounts.get_by_username("volmarr"))
        self.assertEqual(
            self.accounts.get_by_username("WyrdWalker").id, self.user.id)
        # The redirect seam: old name still means this account.
        self.assertEqual(
            self.accounts.redirect_for("volmarr"), "wyrdwalker")
        self.assertEqual(
            self.accounts.resolve_user("VOLMARR").id, self.user.id)
        self.assertIsNone(self.accounts.redirect_for("wyrdwalker"))
        # Sign-in follows the new name.
        token = self.login.login("wyrdwalker", GOOD_PW)
        self.assertEqual(self.sessions.authenticate(token), self.user.id)

    def test_sessions_survive_a_rename(self):
        token = self.login.login("volmarr", GOOD_PW)
        self.accounts.rename(self.user.id, "wyrdwalker")
        self.assertEqual(self.sessions.authenticate(token), self.user.id)

    def test_collisions_are_refused(self):
        with self.assertRaises(RegistrationError) as ctx:
            self.accounts.rename(self.user.id, "Astrid")
        self.assertEqual(ctx.exception.reason, "username_taken")
        with self.assertRaises(RegistrationError) as ctx:
            self.accounts.rename(self.user.id, "admin")
        self.assertEqual(ctx.exception.reason, "username_reserved")
        with self.assertRaises(RegistrationError) as ctx:
            self.accounts.rename(self.user.id, "volmarr")
        self.assertEqual(ctx.exception.reason, "rename_same")
        # Nothing moved.
        self.assertEqual(
            self.accounts.get_by_id(self.user.id).username, "volmarr")

    def test_tombstoned_name_is_held_then_lapses(self):
        self.accounts.rename(self.user.id, "wyrdwalker")
        # Nobody else may register the held name…
        with self.assertRaises(RegistrationError) as ctx:
            self.accounts.register("Volmarr", GOOD_PW)
        self.assertEqual(ctx.exception.reason, "username_taken")
        # …nor rename onto it.
        with self.assertRaises(RegistrationError) as ctx:
            self.accounts.rename(self.other.id, "volmarr")
        self.assertEqual(ctx.exception.reason, "username_taken")
        # After the tombstone lapses the name is free again
        # and the redirect is gone.
        self.clock[0] += TOMBSTONE_SECONDS + 1
        self.assertIsNone(self.accounts.redirect_for("volmarr"))
        newcomer = self.accounts.register("volmarr", GOOD_PW)
        self.assertNotEqual(newcomer.id, self.user.id)

    def test_owner_may_rename_back_onto_their_tombstone(self):
        self.accounts.rename(self.user.id, "wyrdwalker")
        back = self.accounts.rename(self.user.id, "Volmarr")
        self.assertEqual(back.username, "Volmarr")
        self.assertIsNone(self.accounts.redirect_for("volmarr"))
        # And now the *other* old name is the tombstone.
        self.assertEqual(
            self.accounts.redirect_for("wyrdwalker"), "Volmarr")

    def test_case_only_change_leaves_no_tombstone(self):
        renamed = self.accounts.rename(self.user.id, "Volmarr")
        self.assertEqual(renamed.username, "Volmarr")
        self.assertIsNone(self.accounts.redirect_for("volmarr"))
        self.assertEqual(
            self.accounts.get_by_username("volmarr").username, "Volmarr")

    def test_rename_is_audited_with_from_and_to(self):
        self.accounts.rename(self.user.id, "wyrdwalker")
        rows = self.conn.execute(
            "SELECT detail, outcome FROM audit_log"
            " WHERE action = 'auth.username.change'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "success")
        self.assertIn('"volmarr"', rows[0]["detail"])
        self.assertIn('"wyrdwalker"', rows[0]["detail"])


if __name__ == "__main__":
    unittest.main()
