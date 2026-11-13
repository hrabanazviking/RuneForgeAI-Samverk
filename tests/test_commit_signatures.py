"""S-305 acceptance battery: signed-commit verification.

Acceptance (roadmap S-305): Signed-commit verification
-- GPG and SSH signatures verified on ingest and
display; badges say verified / partial / unverified
in words, with the signer shown (never a bare green
tick).

The centre is samverk/commit_signatures.py: the
signature header is extracted from the raw commit
and the payload rebuilt byte for byte as git framed
it for the signer; SSH signatures (produced here by
the real ssh-keygen, and by an independent in-test
SSHSIG framer) are verified in-process against the
registered key blob, and OpenPGP signatures
(produced by the real gpg) are verified by gpg
itself against the registered public keys. A passed
check whose key belongs to the author's account is
verified; a passed check under another account's
key is partial; everything else is unverified, and
a never-ingested commit answers unverified /
not_checked in words. Schema 125 to 126 moved
in-slice (migration 126's signing_keys and
commit_verifications); taxonomy unmoved at 135
(33 auth / 89 repo / 13 admin) -- verification is
a machine judgement and emits no event.

Counted with: python3 -m unittest tests.test_commit_signatures
"""
from __future__ import annotations

import base64
import os
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
    CommitSignatureError, CommitSignatureStore, SigningKeyStore,
    audit_commit_signatures, extract_signature,
    render_commit_signature_badge,
    render_commit_signatures_page, verification_to_dict,
    verify_ssh)
from samverk.db import schema_version
from samverk.repositories import RepositoryStore

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
    """(oid, payload) for a commit; when sig_armour is
    given it is folded into a gpgsig header and the
    payload is the unsigned raw object, exactly what
    the signer signed."""
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
    """One real ed25519 keypair via cryptography, plus
    its OpenSSH public line."""

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
    """A real SSH signature over payload in the git
    namespace, produced by ssh-keygen -Y sign."""
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


class CommitSignatureTests(unittest.TestCase):
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
        self.store = CommitSignatureStore(
            self.conn, self.repos, self.accounts, self.keys,
            time_fn=self.clock)
        self.repos.create_repository(
            self.alice.id, "alice", "pub", visibility="public")
        self.repos.create_repository(
            self.alice.id, "alice", "priv", visibility="private")
        self.path = self.repos.path_for("alice", "pub")
        self.ssh = SshKeys()

    # -- extraction ---------------------------------------------------

    def test_extract_pgp_header_and_payload_roundtrip(self):
        armour = ("-----BEGIN PGP SIGNATURE-----\nabc\n"
                  "-----END PGP SIGNATURE-----")
        oid, payload = make_raw_commit(
            self.path, ALICE_MAIL, sig_armour=armour)
        from samverk.objects import ObjectReader
        raw = ObjectReader(self.path).read_object(oid).data
        found = extract_signature(raw)
        self.assertEqual(found.kind, "openpgp")
        self.assertEqual(found.armour, armour)
        self.assertEqual(found.payload, payload)

    def test_extract_ssh_header(self):
        armour = ("-----BEGIN SSH SIGNATURE-----\nabc\n"
                  "-----END SSH SIGNATURE-----")
        _oid, payload = make_raw_commit(
            self.path, ALICE_MAIL, sig_armour=armour)
        head = payload.partition(b"\n\n")[0]
        raw = (head + b"\ngpgsig "
               + armour.replace("\n", "\n ").encode()
               + b"\n\nwork\n")
        found = extract_signature(raw)
        self.assertEqual(found.kind, "ssh")
        self.assertEqual(found.payload, payload)

    def test_unsigned_commit_extracts_nothing(self):
        _oid, payload = make_raw_commit(self.path, ALICE_MAIL)
        found = extract_signature(payload)
        self.assertEqual(found.kind, "")
        self.assertEqual(found.header, "")
        self.assertEqual(found.payload, payload)

    def test_signature_in_message_body_vouches_for_nothing(self):
        raw = (b"tree abc\nauthor A <a@a> 1 +0000\n\n"
               b"gpgsig -----BEGIN PGP SIGNATURE-----\n")
        found = extract_signature(raw)
        self.assertEqual(found.kind, "")
        self.assertEqual(found.header, "")

    def test_gpgsig_sha256_header_is_a_signature(self):
        armour = ("-----BEGIN PGP SIGNATURE-----\nabc\n"
                  "-----END PGP SIGNATURE-----")
        raw = (b"tree abc\ngpgsig-sha256 "
               + armour.replace("\n", "\n ").encode()
               + b"\n\nwork\n")
        found = extract_signature(raw)
        self.assertEqual(found.header, "gpgsig-sha256")
        self.assertEqual(found.kind, "openpgp")

    # -- the registry ---------------------------------------------------

    def test_register_ssh_key_fingerprints_it(self):
        key = self.keys.register_key(
            self.alice, "ssh", "laptop", self.ssh.line)
        self.assertTrue(key.fingerprint.startswith("SHA256:"))
        self.assertEqual(key.key_id, "ssh-ed25519")
        self.assertEqual(
            [k.id for k in self.keys.list_keys(self.alice)],
            [key.id])

    def test_register_same_key_twice_refused(self):
        self.keys.register_key(
            self.alice, "ssh", "laptop", self.ssh.line)
        with self.assertRaises(CommitSignatureError) as cm:
            self.keys.register_key(
                self.alice, "ssh", "again", self.ssh.line)
        self.assertEqual(cm.exception.reason, "signing_key_taken")

    def test_one_key_cannot_vouch_for_two_accounts(self):
        self.keys.register_key(
            self.alice, "ssh", "laptop", self.ssh.line)
        with self.assertRaises(CommitSignatureError) as cm:
            self.keys.register_key(
                self.bob, "ssh", "mine now", self.ssh.line)
        self.assertEqual(cm.exception.reason, "signing_key_taken")

    def test_private_key_refused_at_the_door(self):
        with self.assertRaises(CommitSignatureError) as cm:
            self.keys.register_key(
                self.alice, "ssh", "oops",
                self.ssh.pem.decode())
        self.assertEqual(cm.exception.reason, "signing_key_invalid")
        self.assertEqual(self.keys.list_keys(self.alice), [])

    def test_remove_key_is_owner_only(self):
        key = self.keys.register_key(
            self.alice, "ssh", "laptop", self.ssh.line)
        with self.assertRaises(CommitSignatureError) as cm:
            self.keys.remove_key(self.bob, key.id)
        self.assertEqual(
            cm.exception.reason, "signing_key_not_found")
        self.keys.remove_key(self.alice, key.id)
        self.assertEqual(self.keys.list_keys(self.alice), [])

    def test_bad_kind_refused(self):
        with self.assertRaises(CommitSignatureError) as cm:
            self.keys.register_key(
                self.alice, "tls", "x", self.ssh.line)
        self.assertEqual(
            cm.exception.reason, "signing_key_kind_invalid")

    # -- SSH verification, end to end -----------------------------------

    def _ssh_commit(self, author_email, signer=None, payload_msg="work"):
        signer = signer or self.ssh
        _probe_oid, payload = make_raw_commit(
            self.path, author_email, message=payload_msg)
        armour = sshsig_sign_with_keygen(
            signer.pem, payload, self.root)
        oid, _p = make_raw_commit(
            self.path, author_email, message=payload_msg,
            sig_armour=armour)
        return oid

    def test_ssh_verified_when_key_is_authors(self):
        self.keys.register_key(
            self.alice, "ssh", "laptop", self.ssh.line)
        oid = self._ssh_commit(ALICE_MAIL)
        record = self.store.verify_commit("alice", "pub", oid)
        self.assertEqual(record.trust, "verified")
        self.assertEqual(record.check, "passed")
        self.assertEqual(record.signer, "alice")
        self.assertTrue(record.fingerprint.startswith("SHA256:"))
        shown = self.store.verification_for(
            self.bob, "alice", "pub", oid)
        self.assertEqual(shown.trust, "verified")
        self.assertIn("Verified", shown.badge_words)
        self.assertIn("alice", shown.badge_words)

    def test_ssh_partial_when_key_is_another_accounts(self):
        self.keys.register_key(
            self.bob, "ssh", "bob key", self.ssh.line)
        oid = self._ssh_commit(ALICE_MAIL)
        record = self.store.verify_commit("alice", "pub", oid)
        self.assertEqual(record.trust, "partial")
        self.assertEqual(record.signer, "bob")
        self.assertIn("Partially verified", record.badge_words)

    def test_ssh_unknown_key_is_unverified(self):
        oid = self._ssh_commit(ALICE_MAIL)
        record = self.store.verify_commit("alice", "pub", oid)
        self.assertEqual(record.trust, "unverified")
        self.assertEqual(record.signer, "")

    def test_ssh_tampered_commit_is_unverified(self):
        self.keys.register_key(
            self.alice, "ssh", "laptop", self.ssh.line)
        _probe, payload = make_raw_commit(
            self.path, ALICE_MAIL, message="honest")
        armour = sshsig_sign_with_keygen(
            self.ssh.pem, payload, self.root)
        oid, _p = make_raw_commit(
            self.path, ALICE_MAIL, message="forged",
            sig_armour=armour)
        record = self.store.verify_commit("alice", "pub", oid)
        self.assertEqual(record.trust, "unverified")
        self.assertEqual(record.check, "failed")

    def test_verify_ssh_rejects_other_namespace(self):
        _probe, payload = make_raw_commit(self.path, ALICE_MAIL)
        key_path = self.root / "k"
        key_path.write_bytes(self.ssh.pem)
        key_path.chmod(0o600)
        data_path = self.root / "d.bin"
        data_path.write_bytes(payload)
        out = subprocess.run(
            ["ssh-keygen", "-Y", "sign", "-f", str(key_path),
             "-n", "file", str(data_path)], capture_output=True)
        assert out.returncode == 0, out.stderr.decode()
        armour = (self.root / "d.bin.sig").read_text().strip()
        self.assertFalse(
            verify_ssh(payload, armour, self.ssh.blob))

    def test_unsigned_commit_is_unverified(self):
        oid, _p = make_raw_commit(self.path, ALICE_MAIL)
        record = self.store.verify_commit("alice", "pub", oid)
        self.assertEqual(record.trust, "unverified")
        self.assertEqual(record.check, "not_checked")
        self.assertEqual(record.kind, "")

    def test_reingest_after_registering_key_raises_badge(self):
        oid = self._ssh_commit(ALICE_MAIL)
        first = self.store.verify_commit("alice", "pub", oid)
        self.assertEqual(first.trust, "unverified")
        self.keys.register_key(
            self.alice, "ssh", "laptop", self.ssh.line)
        second = self.store.verify_commit("alice", "pub", oid)
        self.assertEqual(second.trust, "verified")
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM commit_verifications"
            " WHERE oid = ?", (oid,)).fetchone()
        self.assertEqual(rows["n"], 1)

    # -- display honesty --------------------------------------------------

    def test_never_ingested_commit_answers_not_checked(self):
        oid, _p = make_raw_commit(self.path, ALICE_MAIL)
        record = self.store.verification_for(
            self.alice, "alice", "pub", oid)
        self.assertEqual(record.trust, "unverified")
        self.assertEqual(record.check, "not_checked")
        self.assertEqual(record.verified_at, 0)
        self.assertIn("not checked", record.detail)

    def test_private_repo_badge_is_repo_not_found_to_stranger(self):
        path = self.repos.path_for("alice", "priv")
        oid, _p = make_raw_commit(path, ALICE_MAIL)
        self.store.verify_commit("alice", "priv", oid)
        with self.assertRaises(CommitSignatureError) as cm:
            self.store.verification_for(
                self.bob, "alice", "priv", oid)
        self.assertEqual(cm.exception.reason, "repo_not_found")
        own = self.store.verification_for(
            self.alice, "alice", "priv", oid)
        self.assertEqual(own.oid, oid)

    def test_missing_commit_refused(self):
        with self.assertRaises(CommitSignatureError) as cm:
            self.store.verify_commit("alice", "pub", "f" * 40)
        self.assertEqual(cm.exception.reason, "commit_not_found")

    def test_badge_is_words_with_signer_never_a_bare_tick(self):
        self.keys.register_key(
            self.alice, "ssh", "laptop", self.ssh.line)
        oid = self._ssh_commit(ALICE_MAIL)
        record = self.store.verify_commit("alice", "pub", oid)
        html = render_commit_signature_badge(record)
        self.assertIn("Verified", html)
        self.assertIn("signer alice", html)
        self.assertNotIn("✓", html)
        page = render_commit_signatures_page("alice/pub", [record])
        self.assertIn("never a bare tick", page)
        as_dict = verification_to_dict(record)
        self.assertEqual(as_dict["trust_words"], "Verified")
        self.assertEqual(as_dict["signer"], "alice")

    # -- pins and the honesty audit ---------------------------------------

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 127)
        self.assertEqual(db.MIGRATIONS[-1][0], 127)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    def test_audit_clean_then_flags_a_planted_verified_row(self):
        self.keys.register_key(
            self.alice, "ssh", "laptop", self.ssh.line)
        oid = self._ssh_commit(ALICE_MAIL)
        self.store.verify_commit("alice", "pub", oid)
        self.assertEqual(
            audit_commit_signatures(self.conn), [])
        self.conn.execute(
            "INSERT INTO commit_verifications (repo_id, oid,"
            " kind, trust, check_state, signer, fingerprint,"
            " author_email, detail, verified_at) VALUES"
            " (1, ?, 'ssh', 'verified', 'failed', '', '',"
            " '', 'planted', 1)", ("e" * 40,))
        self.conn.commit()
        problems = audit_commit_signatures(self.conn)
        self.assertTrue(any("verified" in p for p in problems))


class GpgVerificationTests(unittest.TestCase):
    """Real OpenPGP: keys and signatures made by gpg."""

    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        cls.home = Path(cls._td.name) / "gnupg"
        cls.home.mkdir(mode=0o700)
        env = dict(os.environ, GNUPGHOME=str(cls.home))
        out = subprocess.run(
            ["gpg", "--batch", "--pinentry-mode", "loopback",
             "--passphrase", "", "--quick-generate-key",
             "Alice <alice@example.test>", "ed25519", "sign",
             "never"], capture_output=True, env=env)
        assert out.returncode == 0, out.stderr.decode()
        out = subprocess.run(
            ["gpg", "--batch", "--armor", "--export",
             "alice@example.test"], capture_output=True, env=env)
        assert out.returncode == 0, out.stderr.decode()
        cls.public_armour = out.stdout.decode()

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

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
        self.store = CommitSignatureStore(
            self.conn, self.repos, self.accounts, self.keys,
            time_fn=self.clock)
        self.repos.create_repository(
            self.alice.id, "alice", "pub", visibility="public")
        self.path = self.repos.path_for("alice", "pub")

    def _gpg_sign(self, payload: bytes) -> str:
        data = self.root / "payload.bin"
        data.write_bytes(payload)
        env = dict(os.environ, GNUPGHOME=str(self.home))
        out = subprocess.run(
            ["gpg", "--batch", "--pinentry-mode", "loopback",
             "--passphrase", "", "--detach-sign", "--armor",
             "--local-user", "alice@example.test",
             "--output", "-", str(data)],
            capture_output=True, env=env)
        assert out.returncode == 0, out.stderr.decode()
        return out.stdout.decode().strip()

    def _gpg_commit(self, message="work"):
        _probe, payload = make_raw_commit(
            self.path, ALICE_MAIL, message=message)
        armour = self._gpg_sign(payload)
        oid, _p = make_raw_commit(
            self.path, ALICE_MAIL, message=message,
            sig_armour=armour)
        return oid

    def test_register_openpgp_key_reads_fingerprint(self):
        key = self.keys.register_key(
            self.alice, "openpgp", "gpg", self.public_armour)
        self.assertEqual(len(key.fingerprint), 40)
        self.assertTrue(key.key_id)

    def test_gpg_verified_when_key_is_authors(self):
        self.keys.register_key(
            self.alice, "openpgp", "gpg", self.public_armour)
        oid = self._gpg_commit()
        record = self.store.verify_commit("alice", "pub", oid)
        self.assertEqual(record.trust, "verified")
        self.assertEqual(record.signer, "alice")
        self.assertEqual(len(record.fingerprint), 40)

    def test_gpg_partial_when_key_is_another_accounts(self):
        self.keys.register_key(
            self.bob, "openpgp", "bob gpg", self.public_armour)
        oid = self._gpg_commit()
        record = self.store.verify_commit("alice", "pub", oid)
        self.assertEqual(record.trust, "partial")
        self.assertEqual(record.signer, "bob")

    def test_gpg_unregistered_key_is_unverified(self):
        oid = self._gpg_commit()
        record = self.store.verify_commit("alice", "pub", oid)
        self.assertEqual(record.trust, "unverified")

    def test_gpg_tampered_commit_is_unverified(self):
        self.keys.register_key(
            self.alice, "openpgp", "gpg", self.public_armour)
        _probe, payload = make_raw_commit(
            self.path, ALICE_MAIL, message="honest")
        armour = self._gpg_sign(payload)
        oid, _p = make_raw_commit(
            self.path, ALICE_MAIL, message="forged",
            sig_armour=armour)
        record = self.store.verify_commit("alice", "pub", oid)
        self.assertEqual(record.trust, "unverified")
        self.assertEqual(record.check, "failed")


if __name__ == "__main__":
    unittest.main()
