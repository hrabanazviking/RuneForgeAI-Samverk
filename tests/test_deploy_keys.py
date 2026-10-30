"""S-031 acceptance battery: deploy keys.

Acceptance (roadmap S-031): per-repository keys, read-only by
default, read/write an explicit grant; a deploy key cannot
reach other repos in test.

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
from samverk.audit import AuditLog, verify_chain
from samverk.deploy_keys import DeployKeyError, DeployKeyStore
from samverk.ssh_keys import SshKeyStore

GOOD_PW = "a long enough passphrase"


def make_key_line(key_type: str = "ssh-ed25519",
                  material: bytes = b"\x07" * 32,
                  comment: str = "laptop") -> str:
    import base64
    import struct
    blob = (struct.pack(">I", len(key_type)) + key_type.encode()
            + struct.pack(">I", len(material)) + material)
    return f"{key_type} {base64.b64encode(blob).decode()} {comment}"


OTHER_KEY = make_key_line(material=b"\x09" * 32, comment="ci")


class DeployKeyTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.owner = self.accounts.register("volmarr", GOOD_PW)
        self.other = self.accounts.register("astrid", GOOD_PW)
        self.deploy = DeployKeyStore(
            self.conn, self.accounts, audit=self.audit)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_default_is_read_only_and_write_is_an_explicit_grant(self):
        key = self.deploy.add_key(
            self.owner.id, "volmarr", "samverk", "CI", make_key_line())
        self.assertFalse(key.can_write)
        granted = self.deploy.add_key(
            self.owner.id, "volmarr", "samverk", "Release", OTHER_KEY,
            can_write=True)
        self.assertTrue(granted.can_write)

    def test_key_cannot_reach_other_repos(self):
        """The acceptance in literal form."""
        key = self.deploy.add_key(
            self.owner.id, "volmarr", "samverk", "CI", make_key_line(),
            can_write=True)
        self.assertIsNotNone(self.deploy.authorize(
            key.fingerprint, "volmarr", "samverk"))
        self.assertIsNotNone(self.deploy.authorize(
            key.fingerprint, "Volmarr", "Samverk", write=True))
        self.assertIsNone(self.deploy.authorize(
            key.fingerprint, "volmarr", "other-repo"))
        self.assertIsNone(self.deploy.authorize(
            key.fingerprint, "astrid", "samverk"))
        self.assertIsNone(self.deploy.authorize(
            key.fingerprint, "astrid", "other-repo", write=True))
        self.assertIsNone(self.deploy.authorize(
            "SHA256:unknown", "volmarr", "samverk"))

    def test_read_only_key_is_refused_for_write(self):
        key = self.deploy.add_key(
            self.owner.id, "volmarr", "samverk", "CI", make_key_line())
        self.assertIsNotNone(self.deploy.authorize(
            key.fingerprint, "volmarr", "samverk", write=False))
        self.assertIsNone(self.deploy.authorize(
            key.fingerprint, "volmarr", "samverk", write=True))

    def test_only_the_repo_owner_can_add_or_delete(self):
        with self.assertRaises(DeployKeyError) as ctx:
            self.deploy.add_key(
                self.other.id, "volmarr", "samverk", "CI",
                make_key_line())
        self.assertEqual(ctx.exception.reason, "not_repo_owner")
        key = self.deploy.add_key(
            self.owner.id, "volmarr", "samverk", "CI", make_key_line())
        self.assertFalse(self.deploy.delete_key(self.other.id, key.id))
        self.assertTrue(self.deploy.delete_key(self.owner.id, key.id))
        self.assertIsNone(self.deploy.authorize(
            key.fingerprint, "volmarr", "samverk"))

    def test_fingerprint_cannot_be_personal_and_deploy(self):
        personal = SshKeyStore(
            self.conn, self.accounts, audit=self.audit,
            reauth_verifier=lambda uid: True)
        personal.add_key(self.owner.id, "Mine", make_key_line())
        with self.assertRaises(DeployKeyError) as ctx:
            self.deploy.add_key(
                self.owner.id, "volmarr", "samverk", "CI",
                make_key_line())
        self.assertEqual(ctx.exception.reason, "key_already_registered")

    def test_invalid_repo_names_and_listing(self):
        with self.assertRaises(DeployKeyError):
            self.deploy.add_key(
                self.owner.id, "volmarr", "../escape", "CI",
                make_key_line())
        self.deploy.add_key(
            self.owner.id, "volmarr", "samverk", "CI", make_key_line())
        self.deploy.add_key(
            self.owner.id, "volmarr", "samverk", "Release", OTHER_KEY,
            can_write=True)
        listed = self.deploy.list_keys("Volmarr", "Samverk")
        self.assertEqual([k.title for k in listed], ["CI", "Release"])
        self.assertEqual(self.deploy.list_keys("volmarr", "nope"), [])

    def test_add_and_remove_are_audited(self):
        key = self.deploy.add_key(
            self.owner.id, "volmarr", "samverk", "CI", make_key_line())
        self.deploy.record_use(key.id)
        self.assertIsNotNone(
            self.deploy.list_keys("volmarr", "samverk")[0].last_used_at)
        self.deploy.delete_key(self.owner.id, key.id)
        details = [r["detail"] for r in self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action='repo.settings.change' ORDER BY seq")]
        self.assertEqual(len(details), 2)
        self.assertIn('"deploy_key.add"', details[0])
        self.assertIn('"can_write":false', details[0])
        self.assertIn('"deploy_key.remove"', details[1])
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, msg=f"chain broken at {bad}")


if __name__ == "__main__":
    unittest.main()
