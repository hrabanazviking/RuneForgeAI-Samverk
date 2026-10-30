"""S-004 acceptance battery: password hashing.

Acceptance (roadmap S-004): known-answer + timing tests; per-user
salt; hash-upgrade-on-login path.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import passwords

PASSWORD = "correct horse battery staple"
# Known-answer vectors, computed once from hashlib primitives with
# salt b"samverk-test-salt" (base64 c2FtdmVyay10ZXN0LXNhbHQ=) and the
# password above. If these fail, the KDF wiring — not the test — moved.
SCRYPT_KAT = (
    "scrypt$32768$8$1$c2FtdmVyay10ZXN0LXNhbHQ="
    "$BnkTLj89hXd1qKy5nZ5P99pNV9MKCq9IYqMOBuBixxQ="
)
LEGACY_KAT = (
    "pbkdf2-sha256$1000$c2FtdmVyay10ZXN0LXNhbHQ="
    "$uVzproluGkzJRx750mw9uG7p0shrmAv3dfxxJX9ED7E="
)


class KnownAnswerTests(unittest.TestCase):
    def test_scrypt_known_answer(self):
        self.assertTrue(passwords.verify_password(PASSWORD, SCRYPT_KAT))

    def test_legacy_known_answer(self):
        self.assertTrue(passwords.verify_password(PASSWORD, LEGACY_KAT))

    def test_wrong_password_rejected(self):
        self.assertFalse(passwords.verify_password("wrong horse", SCRYPT_KAT))
        self.assertFalse(passwords.verify_password("wrong horse", LEGACY_KAT))

    def test_malformed_rows_fail_closed(self):
        for bad in ("", "scrypt", "scrypt$abc$8$1$xx$yy",
                    "unknown$1$2$3", "scrypt$32768$8$1$!!$%%"):
            self.assertFalse(passwords.verify_password(PASSWORD, bad), bad)


class HashBehaviourTests(unittest.TestCase):
    def test_round_trip_and_per_user_salt(self):
        h1 = passwords.hash_password(PASSWORD)
        h2 = passwords.hash_password(PASSWORD)
        self.assertNotEqual(h1, h2, "salts must differ per hash")
        self.assertTrue(passwords.verify_password(PASSWORD, h1))
        self.assertTrue(passwords.verify_password(PASSWORD, h2))
        self.assertFalse(passwords.needs_upgrade(h1))

    def test_timing_floor_proves_work_factor(self):
        """A fast hash would verify in microseconds; scrypt at the
        current parameters must cost real time. The floor is set far
        below the expected cost so only a broken (weakened) KDF fails,
        never a slow machine."""
        start = time.perf_counter()
        passwords.verify_password(PASSWORD, SCRYPT_KAT)
        elapsed = time.perf_counter() - start
        self.assertGreater(elapsed, 0.002,
                           f"verification too fast ({elapsed:.4f}s): "
                           "work factor missing?")


class UpgradeTests(unittest.TestCase):
    def test_legacy_needs_upgrade_and_upgrades_on_login(self):
        self.assertTrue(passwords.needs_upgrade(LEGACY_KAT))
        ok, new_hash = passwords.verify_and_upgrade(PASSWORD, LEGACY_KAT)
        self.assertTrue(ok)
        self.assertIsNotNone(new_hash)
        self.assertTrue(new_hash.startswith("scrypt$"))
        self.assertFalse(passwords.needs_upgrade(new_hash))
        self.assertTrue(passwords.verify_password(PASSWORD, new_hash))

    def test_current_hash_does_not_upgrade(self):
        ok, new_hash = passwords.verify_and_upgrade(PASSWORD, SCRYPT_KAT)
        self.assertTrue(ok)
        self.assertIsNone(new_hash)

    def test_failed_login_never_upgrades(self):
        ok, new_hash = passwords.verify_and_upgrade("nope", LEGACY_KAT)
        self.assertFalse(ok)
        self.assertIsNone(new_hash)


if __name__ == "__main__":
    unittest.main()
