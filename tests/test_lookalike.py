"""S-046 acceptance battery: reserved/impersonation defence.

Acceptance (roadmap S-046): lookalike-name warnings on
registration for instance-known names. Proven: leetspeak,
separator and one-edit lookalikes of reserved names and of
live accounts warn plainly; exact names earn no warning
(S-025 refuses those instead); genuinely distinct names
warn about nothing.

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
from samverk.lookalike import (
    lookalike_warnings, registration_warnings, skeleton)

GOOD_PW = "a long enough passphrase"


class LookalikeTests(unittest.TestCase):
    def test_skeleton_folds_leet_and_separators(self):
        self.assertEqual(skeleton("Vol-marr"), "volmarr")
        self.assertEqual(skeleton("v0lmarr"), "volmarr")
        self.assertEqual(skeleton("ADM1N"), "admin")

    def test_reserved_lookalikes_warn(self):
        for cand in ("adm1n", "admln", "supp0rt", "sarnverk"):
            warnings = lookalike_warnings(cand)
            self.assertTrue(warnings, cand)
            self.assertEqual(warnings[0].kind, "reserved")
            self.assertIn("looks very similar", warnings[0].message)

    def test_existing_account_lookalikes_warn(self):
        warnings = lookalike_warnings(
            "volrnarr", known_existing=["volmarr", "astrid"])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].resembles, "volmarr")
        self.assertEqual(warnings[0].kind, "existing")
        warnings = lookalike_warnings(
            "vol-marr", known_existing=["volmarr"])
        self.assertEqual(len(warnings), 1)

    def test_exact_and_distinct_names_warn_about_nothing(self):
        self.assertEqual(lookalike_warnings("admin"), [])
        self.assertEqual(
            lookalike_warnings("volmarr", known_existing=["volmarr"]), [])
        self.assertEqual(
            lookalike_warnings("zephyrquill",
                               known_existing=["volmarr", "astrid"]), [])
        self.assertEqual(lookalike_warnings(""), [])
        self.assertEqual(lookalike_warnings(None), [])

    def test_registration_warnings_reads_live_accounts(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "samverk.db")
            accounts = AccountStore(conn)
            accounts.register("volmarr", GOOD_PW)
            warnings = registration_warnings(conn, "v0lmarr")
            self.assertTrue(any(
                w.resembles == "volmarr" and w.kind == "existing"
                for w in warnings))
            conn.close()


if __name__ == "__main__":
    unittest.main()
