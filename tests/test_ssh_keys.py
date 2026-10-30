"""S-030 acceptance battery: SSH keys.

Acceptance (roadmap S-030): add/list/delete personal keys,
fingerprint and last-used shown; key add requires sudo-mode
re-auth (S-036 — exercised here through its seam, fail-closed).

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import base64
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.ssh_keys import (
    SshKeyError,
    SshKeyStore,
    fingerprint_of,
    parse_public_key,
)

GOOD_PW = "a long enough passphrase"


def make_key_line(key_type: str = "ssh-ed25519",
                  material: bytes = b"\x07" * 32,
                  comment: str = "laptop") -> str:
    blob = (struct.pack(">I", len(key_type)) + key_type.encode()
            + struct.pack(">I", len(material)) + material)
    return f"{key_type} {base64.b64encode(blob).decode()} {comment}"


class ParseTests(unittest.TestCase):
    def test_valid_key_parses_with_openssh_fingerprint(self):
        parsed = parse_public_key(make_key_line())
        self.assertEqual(parsed.key_type, "ssh-ed25519")
        self.assertTrue(parsed.fingerprint.startswith("SHA256:"))
        self.assertNotIn("=", parsed.fingerprint)
        self.assertEqual(parsed.fingerprint, fingerprint_of(parsed.blob))
        self.assertEqual(parsed.comment, "laptop")

    def test_malformed_keys_are_refused(self):
        for bad in ("", "ssh-ed25519", "ssh-ed25519 !!!not-base64!!!",
                    "ssh-ed25519 " + base64.b64encode(b"tiny").decode()):
            with self.assertRaises(SshKeyError, msg=bad):
                parse_public_key(bad)

    def test_inner_type_must_match_outer_label(self):
        blob = (struct.pack(">I", 7) + b"ssh-rsa"
                + struct.pack(">I", 4) + b"\x01\x02\x03\x04")
        line = "ssh-ed25519 " + base64.b64encode(blob).decode()
        with self.assertRaises(SshKeyError) as ctx:
            parse_public_key(line)
        self.assertEqual(ctx.exception.reason, "key_malformed")

    def test_legacy_dss_is_not_admitted(self):
        with self.assertRaises(SshKeyError) as ctx:
            parse_public_key(make_key_line("ssh-dss"))
        self.assertEqual(ctx.exception.reason, "key_type_not_admitted")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.other = self.accounts.register("astrid", GOOD_PW)
        self.sudo = {self.user.id: False, self.other.id: False}
        self.keys = SshKeyStore(
            self.conn, self.accounts, audit=self.audit,
            reauth_verifier=lambda uid: self.sudo.get(uid, False))

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_add_requires_sudo_reauth_and_fails_closed(self):
        """The acceptance in literal form."""
        with self.assertRaises(SshKeyError) as ctx:
            self.keys.add_key(self.user.id, "Laptop", make_key_line())
        self.assertEqual(ctx.exception.reason, "sudo_required")
        self.assertEqual(self.keys.list_keys(self.user.id), [])
        # No verifier wired at all: still refused, never open.
        bare = SshKeyStore(self.conn, self.accounts)
        with self.assertRaises(SshKeyError):
            bare.add_key(self.user.id, "Laptop", make_key_line())
        self.sudo[self.user.id] = True
        key = self.keys.add_key(self.user.id, "Laptop", make_key_line())
        self.assertEqual(key.title, "Laptop")
        self.assertIsNone(key.last_used_at)

    def test_list_shows_fingerprint_and_last_used(self):
        self.sudo[self.user.id] = True
        key = self.keys.add_key(self.user.id, "Laptop", make_key_line())
        self.keys.record_use(key.id)
        listed = self.keys.list_keys(self.user.id)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].fingerprint, key.fingerprint)
        self.assertIsNotNone(listed[0].last_used_at)
        found = self.keys.find_by_fingerprint(key.fingerprint)
        self.assertEqual(found.id, key.id)

    def test_same_key_cannot_be_registered_twice(self):
        self.sudo[self.user.id] = True
        self.sudo[self.other.id] = True
        self.keys.add_key(self.user.id, "Laptop", make_key_line())
        with self.assertRaises(SshKeyError) as ctx:
            self.keys.add_key(self.user.id, "Again", make_key_line())
        self.assertEqual(ctx.exception.reason, "key_already_registered")
        with self.assertRaises(SshKeyError):
            self.keys.add_key(self.other.id, "Stolen", make_key_line())

    def test_delete_is_owner_only_and_audited(self):
        self.sudo[self.user.id] = True
        key = self.keys.add_key(self.user.id, "Laptop", make_key_line())
        self.assertFalse(self.keys.delete_key(self.other.id, key.id))
        self.assertIsNotNone(self.keys.get_key(key.id))
        self.assertTrue(self.keys.delete_key(self.user.id, key.id))
        self.assertIsNone(self.keys.get_key(key.id))
        self.assertFalse(self.keys.delete_key(self.user.id, key.id))
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log ORDER BY seq")]
        self.assertIn("auth.ssh_key.add", actions)
        self.assertIn("auth.ssh_key.remove", actions)
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, msg=f"chain broken at {bad}")


if __name__ == "__main__":
    unittest.main()
