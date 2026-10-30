"""S-081 acceptance battery: HTTP Basic auth for git.

Acceptance (roadmap S-081): the account password is accepted
for git operations; deactivated accounts authenticate to
nothing.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.git_auth import GitAuthenticator, parse_basic_credentials


def basic(username: str, password: str) -> str:
    raw = base64.b64encode(f"{username}:{password}".encode())
    return f"Basic {raw.decode()}"


class BasicAuthTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register(
            "volmarr", "correct horse battery")
        self.auth = GitAuthenticator(self.conn, self.accounts)

    def test_account_password_authenticates_case_insensitively(self):
        user = self.auth.authenticate_basic(
            basic("Volmarr", "correct horse battery"))
        self.assertIsNotNone(user)
        self.assertEqual(user.id, self.owner.id)

    def test_wrong_password_and_unknown_user_authenticate_to_nothing(self):
        self.assertIsNone(self.auth.authenticate_basic(
            basic("volmarr", "wrong horse battery")))
        self.assertIsNone(self.auth.authenticate_basic(
            basic("nosuchuser", "correct horse battery")))

    def test_deactivated_accounts_authenticate_to_nothing(self):
        for status in ("suspended", "pending_approval",
                       "pending_verification"):
            self.accounts.set_status(self.owner.id, status)
            self.assertIsNone(
                self.auth.authenticate_basic(
                    basic("volmarr", "correct horse battery")),
                msg=status)
        self.accounts.set_status(self.owner.id, "active")
        self.assertIsNotNone(self.auth.authenticate_basic(
            basic("volmarr", "correct horse battery")))

    def test_malformed_headers_resolve_to_nothing(self):
        bad = [
            None, "", "Bearer abc", "Basic", "Basic !!!",
            "Basic " + base64.b64encode(b"nocolon").decode(),
            "Basic " + base64.b64encode(b":password").decode(),
            "basic", 42,
        ]
        for header in bad:
            self.assertIsNone(
                self.auth.authenticate_basic(header), msg=repr(header))
            self.assertIsNone(
                parse_basic_credentials(header), msg=repr(header))

    def test_password_slot_may_contain_colons(self):
        self.accounts.register("colonfan", "pass:word:12345")
        user = self.auth.authenticate_basic(basic("colonfan", "pass:word:12345"))
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "colonfan")

    def test_parser_is_case_insensitive_about_the_scheme(self):
        raw = base64.b64encode(b"volmarr:correct horse battery").decode()
        self.assertEqual(
            parse_basic_credentials(f"bAsIc {raw}"),
            ("volmarr", "correct horse battery"))


if __name__ == "__main__":
    unittest.main()
