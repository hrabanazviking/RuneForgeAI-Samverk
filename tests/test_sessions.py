"""S-006 acceptance battery: session tokens.

Acceptance (roadmap S-006): 256-bit random tokens, stored hashed,
absolute + idle expiry — *stolen-DB session values are unusable in
test.*

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.sessions import SessionStore

T0 = 1_700_000_000.0
DAY = 24 * 3600


class FakeClock:
    def __init__(self):
        self.t = T0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class SessionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.db_path = Path(self._td.name) / "samverk.db"
        self.conn = db.init_db(self.db_path)
        self.clock = FakeClock()
        self.store = SessionStore(self.conn, time_fn=self.clock)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_create_and_authenticate(self):
        token = self.store.create(42)
        self.assertEqual(self.store.authenticate(token), 42)

    def test_tokens_are_unique_per_session(self):
        self.assertNotEqual(self.store.create(1), self.store.create(1))

    def test_unknown_token_rejected(self):
        self.store.create(42)
        self.assertIsNone(self.store.authenticate("not-a-real-token"))

    def test_stolen_db_values_are_unusable(self):
        """The acceptance in its literal form: everything about the
        session that the database holds, presented as a credential,
        must fail — and the raw token must not be in the DB at all."""
        token = self.store.create(42)
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        rows = self.conn.execute("SELECT token_hash FROM sessions").fetchall()
        self.assertEqual(len(rows), 1)
        stored_hash = rows[0]["token_hash"]
        self.assertNotEqual(stored_hash, token)
        # Presenting the stolen hash as a token must not authenticate.
        self.assertIsNone(self.store.authenticate(stored_hash))
        # The raw token appears nowhere in the database file.
        self.assertNotIn(token.encode(), self.db_path.read_bytes())

    def test_absolute_expiry(self):
        token = self.store.create(42)
        self.clock.advance(31 * DAY)
        self.assertIsNone(self.store.authenticate(token))

    def test_idle_expiry(self):
        token = self.store.create(42)
        self.clock.advance(8 * DAY)  # idle limit is 7 days
        self.assertIsNone(self.store.authenticate(token))

    def test_activity_keeps_session_alive_within_absolute_bound(self):
        token = self.store.create(42)
        for _ in range(4):
            self.clock.advance(6 * DAY)  # under the 7-day idle limit
            self.assertEqual(self.store.authenticate(token), 42)
        # 24 days elapsed: alive. One more step crosses 30 absolute.
        self.clock.advance(6 * DAY)
        self.assertIsNone(self.store.authenticate(token))

    def test_revoke_one(self):
        token = self.store.create(42)
        other = self.store.create(42)
        self.assertTrue(self.store.revoke(token))
        self.assertIsNone(self.store.authenticate(token))
        self.assertEqual(self.store.authenticate(other), 42)

    def test_revoke_all_evicts_everyone(self):
        t1 = self.store.create(42)
        t2 = self.store.create(42)
        t3 = self.store.create(7)
        self.assertEqual(self.store.revoke_all(42), 2)
        self.assertIsNone(self.store.authenticate(t1))
        self.assertIsNone(self.store.authenticate(t2))
        self.assertEqual(self.store.authenticate(t3), 7)


if __name__ == "__main__":
    unittest.main()
