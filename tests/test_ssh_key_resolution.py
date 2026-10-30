"""S-085 acceptance battery: SSH key resolution.

Acceptance (roadmap S-085 + study 02): presented key fingerprint
→ account, cached briefly; unknown keys refused without user
enumeration — here: one uniform None for unknown, malformed,
and dead-account fingerprints alike, deploy keys resolving to
their one bound repository, the cache bounded and expiring,
and the authorized_keys emitter printing at most one
forced-command line (or nothing).

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
from samverk.audit import AuditLog
from samverk.deploy_keys import DeployKeyStore
from samverk.ssh_auth import SshKeyResolver
from samverk.ssh_keys import SshKeyStore, fingerprint_of, parse_public_key

GOOD_PW = "a long enough passphrase"


def make_key_line(material: bytes = b"\x07" * 32,
                  comment: str = "laptop") -> str:
    key_type = "ssh-ed25519"
    blob = (struct.pack(">I", len(key_type)) + key_type.encode()
            + struct.pack(">I", len(material)) + material)
    return f"{key_type} {base64.b64encode(blob).decode()} {comment}"


def fp_of(line: str) -> str:
    return parse_public_key(line).fingerprint


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.other = self.accounts.register("astrid", GOOD_PW)
        self.keys = SshKeyStore(
            self.conn, self.accounts, audit=self.audit,
            reauth_verifier=lambda uid: True)
        self.personal_line = make_key_line()
        self.personal = self.keys.add_key(
            self.user.id, "laptop", self.personal_line)
        self.deploy = DeployKeyStore(
            self.conn, self.accounts, audit=self.audit)
        self.deploy_line = make_key_line(b"\x09" * 32, "ci")
        self.deploy_key = self.deploy.add_key(
            self.user.id, "volmarr", "samverk", "CI", self.deploy_line)
        self.clock = [1000.0]
        self.resolver = SshKeyResolver(
            self.conn, self.accounts, time_fn=lambda: self.clock[0])

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_personal_key_resolves_to_its_account(self):
        p = self.resolver.resolve(fp_of(self.personal_line))
        self.assertIsNotNone(p)
        self.assertEqual(p.kind, "account")
        self.assertEqual(p.account_id, self.user.id)
        self.assertEqual(p.user.username, "volmarr")
        self.assertEqual(p.ssh_key.id, self.personal.id)

    def test_deploy_key_resolves_to_its_one_repository(self):
        p = self.resolver.resolve(fp_of(self.deploy_line))
        self.assertIsNotNone(p)
        self.assertEqual(p.kind, "deploy_key")
        self.assertEqual(p.deploy_key.owner, "volmarr")
        self.assertEqual(p.deploy_key.repo, "samverk")
        self.assertFalse(p.deploy_key.can_write)

    def test_unknown_and_malformed_share_one_none(self):
        unknown = fingerprint_of(b"\x00" * 32)
        for bad in (unknown, None, 42, "", "SHA256:", "SHA256:x",
                    "not-a-fingerprint", b"bytes"):
            self.assertIsNone(self.resolver.resolve(bad), msg=repr(bad))

    def test_dead_account_authenticates_to_nothing(self):
        self.accounts.set_status(self.user.id, "suspended")
        fresh = SshKeyResolver(self.conn, self.accounts)
        self.assertIsNone(fresh.resolve(fp_of(self.personal_line)))

    def test_cache_is_brief_and_invalidation_is_immediate(self):
        fp = fp_of(self.personal_line)
        self.assertIsNotNone(self.resolver.resolve(fp))
        self.keys.delete_key(self.user.id, self.personal.id)
        # Within the TTL the cached answer stands (study 02's law)…
        self.assertIsNotNone(self.resolver.resolve(fp))
        # …invalidation ends it at once…
        self.resolver.invalidate(fp)
        self.assertIsNone(self.resolver.resolve(fp))

    def test_cache_entry_expires_with_the_ttl(self):
        fp = fp_of(self.personal_line)
        self.assertIsNotNone(self.resolver.resolve(fp))
        self.keys.delete_key(self.user.id, self.personal.id)
        self.assertIsNotNone(self.resolver.resolve(fp))  # still cached
        self.clock[0] += 60.0                            # past the TTL
        self.assertIsNone(self.resolver.resolve(fp))     # now refused

    def test_cache_can_be_disabled(self):
        resolver = SshKeyResolver(
            self.conn, self.accounts, cache_ttl=0,
            time_fn=lambda: self.clock[0])
        fp = fp_of(self.personal_line)
        self.assertIsNotNone(resolver.resolve(fp))
        self.keys.delete_key(self.user.id, self.personal.id)
        self.assertIsNone(resolver.resolve(fp))

    def test_cache_is_bounded(self):
        resolver = SshKeyResolver(
            self.conn, self.accounts, cache_max=4,
            time_fn=lambda: self.clock[0])
        for i in range(8):
            resolver.resolve(fingerprint_of(bytes([i]) * 32))
        self.assertLessEqual(len(resolver._cache), 4)


class AuthorizedKeysLineTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.accounts = AccountStore(self.conn, audit=AuditLog(self.conn))
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.keys = SshKeyStore(
            self.conn, self.accounts, reauth_verifier=lambda uid: True)
        self.line = make_key_line()
        self.keys.add_key(self.user.id, "laptop", self.line)
        self.deploy = DeployKeyStore(self.conn, self.accounts)
        self.deploy_line = make_key_line(b"\x09" * 32, "ci")
        self.deploy.add_key(
            self.user.id, "volmarr", "samverk", "CI", self.deploy_line)
        self.resolver = SshKeyResolver(self.conn, self.accounts)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_personal_line_is_forced_and_restricted(self):
        out = self.resolver.authorized_keys_line(fp_of(self.line))
        self.assertIsNotNone(out)
        self.assertNotIn("\n", out)
        self.assertTrue(out.startswith('restrict,command="samverk'
                                       ' ssh-serve --account '))
        self.assertIn(f"--account {self.user.id} --key-id ", out)
        self.assertIn(f"--fingerprint {fp_of(self.line)}", out)
        blob_b64 = self.line.split()[1]
        self.assertTrue(out.endswith(f"ssh-ed25519 {blob_b64} samverk-ssh"))

    def test_deploy_line_carries_its_binding(self):
        out = self.resolver.authorized_keys_line(fp_of(self.deploy_line))
        self.assertIn("--deploy-key ", out)
        self.assertIn("--bound volmarr/samverk", out)

    def test_unknown_key_emits_nothing(self):
        self.assertIsNone(self.resolver.authorized_keys_line(
            fingerprint_of(b"\x01" * 32)))

    def test_unsafe_serve_prefix_is_a_config_error(self):
        with self.assertRaises(ValueError):
            self.resolver.authorized_keys_line(
                fp_of(self.line), serve_prefix='bad "prefix')


if __name__ == "__main__":
    unittest.main()
