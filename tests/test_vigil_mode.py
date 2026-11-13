"""S-306 acceptance battery: vigil mode.

Acceptance (roadmap S-306): Vigil mode -- an account
may declare "only my known keys count": commits
claiming their identity but signed by other keys
display as unverified, loudly.

The centre is samverk/vigil_mode.py, over S-305's
verifier: the declaration is the account's own
(migration 127's vigil_settings, schema 126 to
127); the display read re-judges the stored S-305
verdict by the pure decide_vigil_display -- verified
survives only under the author account's own
registered key, every other shape claiming that
identity displays unverified, and the demotion is
spoken on the badge itself, in words. The stored
verdict is never rewritten: lifting the declaration
restores the ordinary badges. Taxonomy unmoved at
135 (33 auth / 89 repo / 13 admin) -- a declaration
and a machine judgement emit no event.

Counted with: python3 -m unittest tests.test_vigil_mode
"""
from __future__ import annotations

import base64
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.commit_signatures import (
    CommitSignatureError, CommitSignatureStore, SigningKeyStore)
from samverk.db import schema_version
from samverk.repositories import RepositoryStore
from samverk.vigil_mode import (
    VigilError, VigilStore, audit_vigil, decide_vigil_display,
    render_vigil_badge, render_vigil_page, render_vigil_setting,
    vigil_to_dict)

PW = "correct horse battery"
ALICE_MAIL = "alice@example.test"
BOB_MAIL = "bob@example.test"


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(
        ["git", f"--git-dir={repo}", *args],
        capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def ssh_string(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


def make_raw_commit(repo, author_email, message="work",
                    sig_armour=None):
    blob = git(repo, "hash-object", "-w", "--stdin",
               input_bytes=b"alpha\n")
    tree = git(repo, "mktree",
               input_bytes=f"100644 blob {blob}\ta.txt\n".encode())
    head = (
        f"tree {tree}\n"
        f"author Alice <{author_email}> 1700000000 +0000\n"
        f"committer Alice <{author_email}> 1700000000 +0000")
    payload = (head + f"\n\n{message}\n").encode()
    if sig_armour is None:
        raw = payload
    else:
        folded = sig_armour.replace("\n", "\n ")
        raw = (head + f"\ngpgsig {folded}"
               + f"\n\n{message}\n").encode()
    oid = git(repo, "hash-object", "-t", "commit", "-w",
              "--stdin", input_bytes=raw)
    return oid, payload


class SshKeys:
    def __init__(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey)
        self.private = Ed25519PrivateKey.generate()
        raw_pub = self.private.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw)
        self.blob = ssh_string(b"ssh-ed25519") + ssh_string(raw_pub)
        self.line = ("ssh-ed25519 "
                     + base64.b64encode(self.blob).decode()
                     + " signer")
        self.pem = self.private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption())


def sshsig_sign_with_keygen(pem: bytes, payload: bytes,
                            workdir: Path) -> str:
    key_path = workdir / "signing_key"
    key_path.write_bytes(pem)
    key_path.chmod(0o600)
    data_path = workdir / "payload.bin"
    data_path.write_bytes(payload)
    out = subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(key_path),
         "-n", "git", str(data_path)],
        capture_output=True)
    assert out.returncode == 0, out.stderr.decode()
    return (workdir / "payload.bin.sig").read_text().strip()


class VigilModeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=self.clock)
        self.alice = self.accounts.register(
            "alice", PW, ALICE_MAIL)
        self.bob = self.accounts.register("bob", PW, BOB_MAIL)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.keys = SigningKeyStore(
            self.conn, self.accounts, time_fn=self.clock)
        self.signatures = CommitSignatureStore(
            self.conn, self.repos, self.accounts, self.keys,
            time_fn=self.clock)
        self.vigil = VigilStore(
            self.conn, self.repos, self.accounts, self.keys,
            self.signatures, time_fn=self.clock)
        self.repos.create_repository(
            self.alice.id, "alice", "pub", visibility="public")
        self.repos.create_repository(
            self.alice.id, "alice", "priv", visibility="private")
        self.path = self.repos.path_for("alice", "pub")
        self.alice_keys = SshKeys()
        self.bob_keys = SshKeys()

    # -- helpers -----------------------------------------------------

    def _signed_commit(self, author_email, signer_keys):
        _probe, payload = make_raw_commit(self.path, author_email)
        armour = sshsig_sign_with_keygen(
            signer_keys.pem, payload, self.root)
        oid, _p = make_raw_commit(
            self.path, author_email, sig_armour=armour)
        return oid

    def _unsigned_commit(self, author_email):
        oid, _p = make_raw_commit(self.path, author_email)
        return oid

    def _register_alice(self):
        return self.keys.register_key(
            self.alice, "ssh", "laptop", self.alice_keys.line)

    def _register_bob(self):
        return self.keys.register_key(
            self.bob, "ssh", "desk", self.bob_keys.line)

    # -- the pure judgement -------------------------------------------

    def test_decide_off_is_a_passthrough(self):
        self.assertEqual(
            decide_vigil_display("partial", "bob", "SHA256:x",
                                 "alice", False, ["SHA256:y"]),
            ("partial", False, False))

    def test_decide_no_claimed_identity_is_a_passthrough(self):
        self.assertEqual(
            decide_vigil_display("verified", "alice", "SHA256:x",
                                 "", True, ["SHA256:x"]),
            ("verified", False, False))

    def test_decide_own_key_satisfies_vigil(self):
        self.assertEqual(
            decide_vigil_display("verified", "alice", "SHA256:x",
                                 "alice", True, ["SHA256:x"]),
            ("verified", True, True))

    def test_decide_partial_under_vigil_is_unverified(self):
        self.assertEqual(
            decide_vigil_display("partial", "bob", "SHA256:x",
                                 "alice", True, ["SHA256:y"]),
            ("unverified", True, False))

    def test_decide_verified_under_a_foreign_fingerprint_fails(self):
        self.assertEqual(
            decide_vigil_display("verified", "alice", "SHA256:x",
                                 "alice", True, ["SHA256:y"]),
            ("unverified", True, False))

    def test_decide_unsigned_under_vigil_is_unverified(self):
        self.assertEqual(
            decide_vigil_display("unverified", "", "",
                                 "alice", True, []),
            ("unverified", True, False))

    # -- the declaration ----------------------------------------------

    def test_setting_defaults_off(self):
        setting = self.vigil.setting_for(self.alice)
        self.assertFalse(setting.enabled)
        self.assertEqual(setting.updated_at, 0)
        self.assertIn("off", setting.words)

    def test_set_vigil_on_and_off(self):
        setting = self.vigil.set_vigil(self.alice, True)
        self.assertTrue(setting.enabled)
        self.assertEqual(setting.updated_at, 1_700_000_000)
        self.assertIn("ON", setting.words)
        self.assertTrue(self.vigil.setting_for(self.alice).enabled)
        lifted = self.vigil.set_vigil(self.alice, False)
        self.assertFalse(lifted.enabled)
        self.assertFalse(self.vigil.setting_for(self.alice).enabled)

    def test_set_vigil_is_per_account(self):
        self.vigil.set_vigil(self.alice, True)
        self.assertFalse(self.vigil.setting_for(self.bob).enabled)

    def test_set_vigil_refuses_a_non_boolean(self):
        with self.assertRaises(VigilError) as cm:
            self.vigil.set_vigil(self.alice, "yes")
        self.assertEqual(cm.exception.reason, "vigil_value_invalid")

    def test_setting_render_speaks_the_rule(self):
        self.vigil.set_vigil(self.alice, True)
        html = render_vigil_setting(
            self.vigil.setting_for(self.alice))
        self.assertIn("only my known keys count", html)
        self.assertIn("Vigil mode is ON for alice", html)

    # -- display under vigil -------------------------------------------

    def test_vigil_off_keeps_the_partial_badge(self):
        self._register_bob()
        oid = self._signed_commit(ALICE_MAIL, self.bob_keys)
        self.signatures.verify_commit("alice", "pub", oid)
        view = self.vigil.display_verification(
            self.alice, "alice", "pub", oid)
        self.assertEqual(view.trust, "partial")
        self.assertFalse(view.vigil_applied)
        self.assertEqual(view.stored_trust, "partial")

    def test_other_key_under_vigil_displays_unverified_loudly(self):
        self._register_alice()
        self._register_bob()
        self.vigil.set_vigil(self.alice, True)
        oid = self._signed_commit(ALICE_MAIL, self.bob_keys)
        self.signatures.verify_commit("alice", "pub", oid)
        view = self.vigil.display_verification(
            self.alice, "alice", "pub", oid)
        self.assertEqual(view.stored_trust, "partial")
        self.assertEqual(view.trust, "unverified")
        self.assertTrue(view.vigil_applied)
        self.assertFalse(view.vigil_satisfied)
        self.assertIn("vigil mode", view.badge_words.lower())
        self.assertIn("bob", view.badge_words)
        self.assertIn("Vigil mode", view.detail)
        self.assertIn("alice", view.detail)

    def test_own_key_under_vigil_stays_verified(self):
        key = self._register_alice()
        self.vigil.set_vigil(self.alice, True)
        oid = self._signed_commit(ALICE_MAIL, self.alice_keys)
        record = self.signatures.verify_commit("alice", "pub", oid)
        self.assertEqual(record.fingerprint, key.fingerprint)
        view = self.vigil.display_verification(
            self.alice, "alice", "pub", oid)
        self.assertEqual(view.trust, "verified")
        self.assertTrue(view.vigil_satisfied)
        self.assertIn("vigil mode", view.badge_words.lower())

    def test_unsigned_claim_under_vigil_is_unverified_loudly(self):
        self._register_alice()
        self.vigil.set_vigil(self.alice, True)
        oid = self._unsigned_commit(ALICE_MAIL)
        self.signatures.verify_commit("alice", "pub", oid)
        view = self.vigil.display_verification(
            self.alice, "alice", "pub", oid)
        self.assertEqual(view.trust, "unverified")
        self.assertTrue(view.vigil_applied)
        self.assertIn("no signature", view.badge_words)

    def test_unknown_key_under_vigil_is_unverified_loudly(self):
        self._register_alice()
        self.vigil.set_vigil(self.alice, True)
        oid = self._signed_commit(ALICE_MAIL, self.bob_keys)
        self.signatures.verify_commit("alice", "pub", oid)
        view = self.vigil.display_verification(
            self.alice, "alice", "pub", oid)
        self.assertEqual(view.trust, "unverified")
        self.assertTrue(view.vigil_applied)
        self.assertIn("vigil mode", view.detail.lower())

    def test_lifting_vigil_restores_the_stored_badge(self):
        self._register_bob()
        oid = self._signed_commit(ALICE_MAIL, self.bob_keys)
        self.signatures.verify_commit("alice", "pub", oid)
        self.vigil.set_vigil(self.alice, True)
        demoted = self.vigil.display_verification(
            self.alice, "alice", "pub", oid)
        self.assertEqual(demoted.trust, "unverified")
        self.vigil.set_vigil(self.alice, False)
        restored = self.vigil.display_verification(
            self.alice, "alice", "pub", oid)
        self.assertEqual(restored.trust, "partial")
        stored = self.signatures.verification_for(
            self.alice, "alice", "pub", oid)
        self.assertEqual(stored.trust, "partial")

    def test_vigil_of_the_signer_does_not_rejudge_anothers_claim(self):
        self._register_alice()
        self.vigil.set_vigil(self.bob, True)
        oid = self._signed_commit(ALICE_MAIL, self.alice_keys)
        self.signatures.verify_commit("alice", "pub", oid)
        view = self.vigil.display_verification(
            self.bob, "alice", "pub", oid)
        self.assertEqual(view.trust, "verified")
        self.assertFalse(view.vigil_applied)

    def test_never_ingested_commit_claims_no_vigil(self):
        self.vigil.set_vigil(self.alice, True)
        oid = self._unsigned_commit(ALICE_MAIL)
        view = self.vigil.display_verification(
            self.alice, "alice", "pub", oid)
        self.assertEqual(view.trust, "unverified")
        self.assertEqual(view.check, "not_checked")
        self.assertFalse(view.vigil_applied)

    def test_private_repo_is_repo_not_found_to_a_stranger(self):
        self.repos.create_repository(
            self.alice.id, "alice", "priv2", visibility="private")
        path = self.repos.path_for("alice", "priv2")
        oid, _p = make_raw_commit(path, ALICE_MAIL)
        with self.assertRaises(CommitSignatureError) as cm:
            self.vigil.display_verification(
                self.bob, "alice", "priv2", oid)
        self.assertEqual(cm.exception.reason, "repo_not_found")

    def test_display_list_and_dict_shape(self):
        self._register_alice()
        self.vigil.set_vigil(self.alice, True)
        oid = self._signed_commit(ALICE_MAIL, self.alice_keys)
        self.signatures.verify_commit("alice", "pub", oid)
        views = self.vigil.display_list(
            self.alice, "alice", "pub", [oid])
        self.assertEqual(len(views), 1)
        as_dict = vigil_to_dict(views[0])
        self.assertEqual(as_dict["trust"], "verified")
        self.assertEqual(as_dict["stored_trust"], "verified")
        self.assertTrue(as_dict["vigil_satisfied"])
        self.assertEqual(as_dict["author_username"], "alice")

    # -- rendering -------------------------------------------------------

    def test_badge_and_page_speak_vigil_in_words(self):
        self._register_bob()
        self.vigil.set_vigil(self.alice, True)
        oid = self._signed_commit(ALICE_MAIL, self.bob_keys)
        self.signatures.verify_commit("alice", "pub", oid)
        view = self.vigil.display_verification(
            self.alice, "alice", "pub", oid)
        badge = render_vigil_badge(view)
        self.assertIn("Unverified", badge)
        self.assertIn("vigil-demoted", badge)
        self.assertNotIn("✓", badge)
        page = render_vigil_page("alice/pub", [view])
        self.assertIn("only my known keys count", page)
        self.assertIn("Vigil mode", page)

    # -- pins and the honesty audit ---------------------------------------

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 127)
        self.assertEqual(db.MIGRATIONS[-1][0], 127)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    def test_audit_clean_with_vigil_satisfied(self):
        self._register_alice()
        self.vigil.set_vigil(self.alice, True)
        oid = self._signed_commit(ALICE_MAIL, self.alice_keys)
        self.signatures.verify_commit("alice", "pub", oid)
        self.assertEqual(audit_vigil(self.conn), [])

    def test_audit_flags_a_verified_row_under_a_foreign_key(self):
        self._register_alice()
        bob_key = self._register_bob()
        self.vigil.set_vigil(self.alice, True)
        repo = self.repos.get_repository("alice", "pub")
        self.conn.execute(
            "INSERT INTO commit_verifications (repo_id, oid,"
            " kind, trust, check_state, signer, fingerprint,"
            " author_email, detail, verified_at) VALUES"
            " (?, ?, 'ssh', 'verified', 'passed', 'bob', ?,"
            " ?, 'planted', 1)",
            (repo.id, "f" * 40, bob_key.fingerprint, ALICE_MAIL))
        self.conn.commit()
        problems = audit_vigil(self.conn)
        self.assertTrue(any("vigil" in p for p in problems))

    def test_audit_flags_a_broken_setting_row(self):
        self.conn.execute(
            "INSERT INTO vigil_settings (user_id, username,"
            " enabled, updated_at) VALUES (?, 'alice', 7, 1)",
            (self.alice.id,))
        self.conn.commit()
        problems = audit_vigil(self.conn)
        self.assertTrue(any("enabled" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
