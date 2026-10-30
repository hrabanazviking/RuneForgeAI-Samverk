"""S-034 acceptance battery: token management UI (surface).

Acceptance (roadmap S-034): list with last-used and scopes,
revoke in one click, findable from the settings home — the
token page is one click from settings, lists both token
kinds with their governing facts, and one revoke call ends
a token of either kind.

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
from samverk.audit import AuditLog
from samverk.fine_grained_tokens import FineTokenStore
from samverk.token_management import (
    TOKENS_PATH,
    TokenManagement,
    render_settings_home,
    render_token_list_page,
)

GOOD_PW = "a long enough passphrase"
DAY = 24 * 3600


class TokenManagementTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.other = self.accounts.register("astrid", GOOD_PW)
        self.clock = [int(time.time())]
        now = lambda: self.clock[0]  # noqa: E731
        self.classic = AccessTokenStore(
            self.conn, self.accounts, audit=self.audit, time_fn=now)
        self.fine = FineTokenStore(
            self.conn, self.accounts, audit=self.audit, time_fn=now)
        self.mgmt = TokenManagement(
            self.conn, self.accounts, self.classic, self.fine,
            time_fn=now)
        self.exp = self.clock[0] + 30 * DAY

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def seed(self):
        ct, craw = self.classic.create_token(
            self.user.id, "CI script", ["repo:read"], self.exp)
        ft, fraw = self.fine.create_token(
            self.user.id, "volmarr", "samverk", "Repo bot",
            ["contents:read"], self.exp)
        self.classic.authenticate(craw)  # stamps last-used
        return ct, craw, ft, fraw

    def test_settings_home_links_the_token_page_in_one_click(self):
        home = render_settings_home("volmarr")
        self.assertIn(f'href="{TOKENS_PATH}"', home)
        self.assertIn("Personal access tokens", home)

    def test_list_unifies_both_kinds_with_facts(self):
        ct, _, ft, _ = self.seed()
        summaries = self.mgmt.list_all(self.user.id)
        self.assertEqual(len(summaries), 2)
        by_kind = {s.kind: s for s in summaries}
        classic = by_kind["classic"]
        self.assertEqual(classic.grants, ("repo:read",))
        self.assertIsNotNone(classic.last_used_at)
        self.assertEqual(classic.status, "Active")
        fine = by_kind["fine_grained"]
        self.assertEqual(fine.target, "volmarr/samverk")
        self.assertIn("contents:read", fine.grants)
        self.assertIsNone(fine.last_used_at)
        self.assertEqual(self.mgmt.list_all(self.other.id), [])

    def test_revoke_in_one_call_for_either_kind(self):
        ct, craw, ft, fraw = self.seed()
        self.assertFalse(
            self.mgmt.revoke(self.other.id, "classic", ct.id))
        self.assertTrue(self.mgmt.revoke(self.user.id, "classic", ct.id))
        self.assertIsNone(self.classic.authenticate(craw))
        self.assertTrue(
            self.mgmt.revoke(self.user.id, "fine_grained", ft.id))
        self.assertIsNone(self.fine.authenticate(fraw))
        self.assertFalse(self.mgmt.revoke(self.user.id, "bogus", 1))
        self.assertFalse(self.mgmt.revoke(self.user.id, "classic", "1"))

    def test_page_shows_facts_and_revoke_form_for_live_tokens(self):
        self.seed()
        page = render_token_list_page(
            "volmarr", self.mgmt.list_all(self.user.id),
            csrf_token="csrf-123")
        for text in ("CI script", "Repo bot", "repo:read",
                     "contents:read", "Last used", "Expires",
                     "Status: Active", "volmarr/samverk",
                     'name="csrf_token" value="csrf-123"'):
            self.assertIn(text, page)
        self.assertEqual(page.count("Revoke</button>"), 2)

    def test_revoked_and_expired_tokens_show_status_not_a_button(self):
        ct, craw, ft, fraw = self.seed()
        self.mgmt.revoke(self.user.id, "classic", ct.id)
        self.clock[0] += 31 * DAY  # the fine token now expires too
        page = render_token_list_page(
            "volmarr", self.mgmt.list_all(self.user.id))
        self.assertIn("Status: Revoked", page)
        self.assertIn("Status: Expired", page)
        self.assertNotIn("Revoke</button>", page)

    def test_page_escapes_token_titles(self):
        self.classic.create_token(
            self.user.id, "<script>alert(1)</script>",
            ["repo:read"], self.exp)
        page = render_token_list_page(
            "volmarr", self.mgmt.list_all(self.user.id))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_empty_state_teaches(self):
        page = render_token_list_page("volmarr", [])
        self.assertIn("No tokens yet", page)


if __name__ == "__main__":
    unittest.main()
