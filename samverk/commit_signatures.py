"""Signed-commit verification (S-305).

Roadmap S-305: Signed-commit verification -- GPG and
SSH signatures verified on ingest and display;
badges say *verified / partial / unverified* in
words, with the signer shown (never a bare green
tick).

S-175 judged only that a signature header was
*present*; cryptographic verification was expressly
deferred to this Part. S-263 built the release
signing seam and froze the trust vocabulary this
slice speaks. This module is the verifier both
were waiting for:

- **What is signed is the commit, minus its
  signature.** A commit's signature lives in the
  `gpgsig` header (or its SHA-256 twin
  `gpgsig-sha256`), folded across continuation
  lines. The signed payload is the raw commit
  object with that one header removed -- the exact
  bytes git hands the signer -- reconstructed here
  from the header block only; signature-looking
  text in the message body is not a signature.
  The armour inside the header names the engine:
  `PGP SIGNATURE` is OpenPGP, `SSH SIGNATURE` is
  an SSH signature over the `git` namespace.
- **Verification is real, or it does not count.**
  SSH signatures are verified in-process against
  the registered key blob: the SSHSIG envelope is
  parsed field by field, the signed data rebuilt
  exactly as the SSH signing protocol frames it
  (magic, namespace, hash of the payload), and
  the Ed25519 / ECDSA / RSA signature checked with
  the `cryptography` library (admitted at this slice under S-017 -- see samverk/dependencies.py). OpenPGP signatures
  are verified by the operator's own `gpg` (S-014's
  subprocess law, extended to `gpg` in
  samverk/proc.py for this slice): the registered
  public keys are imported into a throwaway
  keyring and `gpg --verify` judges the detached
  signature over the payload; a `VALIDSIG` status
  line naming a registered fingerprint is the only
  pass. Nothing in this module ever upgrades a
  result: a check that cannot run, a key that is
  not known, a signature that does not parse, all
  land on the honest side of the vocabulary.
- **Trust is S-263's judgement, fed real facts.**
  The stored word comes from
  `release_signatures.decide_signature_trust`
  alone, so commit badges and release badges can
  never drift apart: a check that passed with the
  signing key registered to the account the
  commit's author (or committer) email names is
  **verified**; a check that passed under a known
  key registered to a *different* account is
  **partial** (the signature is real, the signer
  is not the author); everything else -- no
  signature, a failed check, a key Samverk does
  not know -- is **unverified**. The signer is
  shown in words on every face: the matched
  account for verified, the key's owner for
  partial, and an explicit "signer unknown" /
  "no signature" for unverified -- never a bare
  green tick, never colour alone.
- **Keys are registered before they can vouch.**
  Migration 126's `signing_keys` holds one
  account's public signing keys: an OpenSSH
  public-key line (parsed by S-030's strict
  parser, fingerprinted its way) or an armoured
  OpenPGP public key (fingerprinted by `gpg`
  itself). Only public material is stored -- a
  private key offered at the door is refused.
  Registration and removal are the owner's acts
  on their own keys; a fingerprint may stand for
  one account only, so attribution cannot be
  shared.
- **Ingest records, display reads.** `verify_commit`
  is the ingest act: it reads the commit object
  from the repository, verifies it whole, and
  stores the verdict in migration 126's
  `commit_verifications` (one row per repository
  and commit; re-ingesting replaces the row, so a
  key registered later can raise a badge honestly
  on re-check). `verification_for` is the display
  read: a commit that was never ingested answers
  the honest default -- unverified, not checked,
  in those words -- and never a stored guess.
  Reads follow the repository (S-054 `can_read`):
  a stranger to a private repository gets the
  uniform `repo_not_found`, badge included.
- **No witness, no new verb.** Verification is a
  machine judgement over data already in the
  forge, and key registration changes no code and
  lands no push, so this slice adds no taxonomy
  event: 135 stand (33 auth / 89 repo / 13 admin).
  The durable artefacts are the rows themselves,
  and `audit_commit_signatures` re-proves the
  honesty invariant over them: no stored row may
  claim verified without a signer and a
  fingerprint. Signatures live in migration 126
  (schema 125 to 126); the suite's standing
  schema pins moved in-slice, its taxonomy pins
  unmoved. S-306's vigil mode builds on this
  slice's registry and verdicts.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
import sqlite3
import struct
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .objects import ObjectReader
from .permissions import can_read
from .proc import run_program
from .release_signatures import (
    CHECK_STATES, TRUST_STATES, TRUST_WORDS,
    decide_signature_trust, trust_words)
from .repositories import RepositoryStore
from .ssh_keys import fingerprint_of as ssh_fingerprint_of
from .ssh_keys import parse_public_key

__all__ = [
    "CHECK_STATES", "HEADER_NAMES", "NAMESPACE",
    "TRUST_STATES", "TRUST_WORDS", "CommitSignatureError",
    "CommitVerification", "ExtractedSignature",
    "SigningKey", "SigningKeyStore",
    "CommitSignatureStore", "audit_commit_signatures",
    "extract_signature", "parse_identity",
    "render_commit_signature_badge",
    "render_commit_signatures_page", "trust_words",
    "validate_key_kind", "validate_key_title",
    "verification_to_dict", "verify_openpgp",
    "verify_ssh",
]

#: Signature headers git writes, SHA-1 and SHA-256 shapes.
HEADER_NAMES = ("gpgsig", "gpgsig-sha256")

#: The SSH signing namespace git signs under.
NAMESPACE = "git"

TITLE_MAX = 100
_MATERIAL_MAX = 65536
_IDENTITY_RE = re.compile(r"^(.*?) <([^<>]*)> \d+ [+-]\d{4}$")
_OID_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")

KIND_OPENPGP = "openpgp"
KIND_SSH = "ssh"
KEY_KINDS = (KIND_OPENPGP, KIND_SSH)
KIND_WORDS = {"openpgp": "OpenPGP", "ssh": "SSH", "": "none"}


class CommitSignatureError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# ---------------------------------------------------------------------
# Extraction: the signature header and the payload it signs
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class ExtractedSignature:
    """One raw commit's signature position: the
    engine kind ('' when unsigned), the armoured
    signature text ('' when unsigned), and the
    payload -- the raw commit with the signature
    header removed, byte for byte what was signed."""
    kind: str
    armour: str
    payload: bytes
    header: str


def extract_signature(raw: bytes) -> ExtractedSignature:
    """Split one raw commit object into its signature
    and its signed payload. Only the header block
    speaks; the payload is rebuilt from the raw
    lines so continuation folding is preserved
    everywhere except the one signature header."""
    head, sep, _message = raw.partition(b"\n\n")
    if not sep:
        return ExtractedSignature("", "", raw, "")
    lines = head.split(b"\n")
    out: list[bytes] = []
    armour = ""
    header_found = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        name, _, _value = line.partition(b" ")
        key = name.decode("ascii", "replace").lower()
        if key in HEADER_NAMES and not header_found:
            parts = [_value]
            i += 1
            while i < len(lines) and lines[i].startswith(b" "):
                parts.append(lines[i][1:])
                i += 1
            armour = b"\n".join(parts).decode("utf-8", "replace")
            header_found = key
            continue
        out.append(line)
        i += 1
    if not header_found:
        return ExtractedSignature("", "", raw, "")
    payload = b"\n".join(out) + raw[len(head):]
    if "-----BEGIN PGP SIGNATURE-----" in armour:
        kind = KIND_OPENPGP
    elif "-----BEGIN SSH SIGNATURE-----" in armour:
        kind = KIND_SSH
    else:
        kind = ""
    return ExtractedSignature(kind, armour, payload, header_found)


def parse_identity(line: str) -> tuple[str, str]:
    """One author/committer header's (name, email)."""
    match = _IDENTITY_RE.match(line or "")
    if not match:
        return (line or ""), ""
    return match.group(1), match.group(2)


def _identities(raw: bytes) -> tuple[str, str]:
    head = raw.partition(b"\n\n")[0].decode("utf-8", "replace")
    author_email = committer_email = ""
    current: str | None = None
    values: dict[str, str] = {}
    for line in head.split("\n"):
        if line.startswith(" ") and current is not None:
            values[current] += "\n" + line[1:]
            continue
        name, _, value = line.partition(" ")
        current = name.lower()
        values[current] = value
    if "author" in values:
        _n, author_email = parse_identity(values["author"])
    if "committer" in values:
        _n, committer_email = parse_identity(values["committer"])
    return author_email, committer_email


# ---------------------------------------------------------------------
# SSH verification (pure, against the registered key blob)
# ---------------------------------------------------------------------

def _ssh_read_string(buf: bytes, pos: int) -> tuple[bytes, int]:
    if pos + 4 > len(buf):
        raise CommitSignatureError(
            "signature_invalid", "That SSH signature is truncated.")
    (size,) = struct.unpack(">I", buf[pos:pos + 4])
    pos += 4
    if pos + size > len(buf):
        raise CommitSignatureError(
            "signature_invalid", "That SSH signature is truncated.")
    return buf[pos:pos + size], pos + size


def _ssh_string(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


def _dearmor(armour: str, kind_word: str) -> bytes:
    begin = f"-----BEGIN {kind_word}-----"
    end = f"-----END {kind_word}-----"
    start = armour.find(begin)
    stop = armour.find(end)
    if start < 0 or stop < 0 or stop <= start:
        raise CommitSignatureError(
            "signature_invalid",
            f"That is not an armoured {kind_word}.")
    body = armour[start + len(begin):stop]
    lines = [ln.strip() for ln in body.splitlines()
             if ln.strip() and ":" not in ln]
    try:
        return base64.b64decode("".join(lines), validate=True)
    except (binascii.Error, ValueError):
        raise CommitSignatureError(
            "signature_invalid",
            f"That {kind_word} does not decode.") from None


def _signed_data(namespace: str, reserved: bytes,
                 hash_algo: str, payload: bytes) -> bytes:
    digest = hashlib.new(
        "sha512" if hash_algo == "sha512" else "sha256",
        payload).digest()
    return (
        b"SSHSIG" + _ssh_string(namespace.encode())
        + _ssh_string(reserved)
        + _ssh_string(hash_algo.encode())
        + _ssh_string(digest))


def verify_ssh(payload: bytes, armour: str,
               key_blob: bytes) -> bool:
    """True only when *armour* is a well-formed SSHSIG
    over *payload* under the `git` namespace and the
    signature checks against *key_blob*. Any malformed
    shape, another namespace, or a failed check is
    False -- the caller never sees a maybe."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric import (
        ec, ed25519, padding, rsa)
    from cryptography.hazmat.primitives import hashes

    blob = _dearmor(armour, "SSH SIGNATURE")
    if blob[:6] != b"SSHSIG":
        raise CommitSignatureError(
            "signature_invalid", "That SSH signature is malformed.")
    pos = 6
    (version,), pos = struct.unpack(">I", blob[pos:pos + 4]), pos + 4
    if version != 1:
        raise CommitSignatureError(
            "signature_invalid", "That SSH signature is malformed.")
    pub_blob, pos = _ssh_read_string(blob, pos)
    namespace_b, pos = _ssh_read_string(blob, pos)
    reserved, pos = _ssh_read_string(blob, pos)
    hash_algo_b, pos = _ssh_read_string(blob, pos)
    sig_blob, pos = _ssh_read_string(blob, pos)
    if pub_blob != key_blob:
        return False
    namespace = namespace_b.decode("ascii", "replace")
    if namespace != NAMESPACE:
        return False
    hash_algo = hash_algo_b.decode("ascii", "replace")
    data = _signed_data(namespace, reserved, hash_algo, payload)
    alg_b, p = _ssh_read_string(sig_blob, 0)
    signature, p = _ssh_read_string(sig_blob, p)
    alg = alg_b.decode("ascii", "replace")
    key_alg_b, q = _ssh_read_string(key_blob, 0)
    if key_alg_b.decode("ascii", "replace") != alg and not (
            alg.startswith("rsa-sha2-")
            and key_alg_b == b"ssh-rsa"):
        return False
    try:
        if alg == "ssh-ed25519":
            key_bytes, q = _ssh_read_string(key_blob, q)
            ed25519.Ed25519PublicKey.from_public_bytes(
                key_bytes).verify(signature, data)
        elif alg.startswith("ecdsa-sha2-"):
            curve_name, q = _ssh_read_string(key_blob, q)
            point, q = _ssh_read_string(key_blob, q)
            curves = {
                b"nistp256": (ec.SECP256R1, hashes.SHA256),
                b"nistp384": (ec.SECP384R1, hashes.SHA384),
                b"nistp521": (ec.SECP521R1, hashes.SHA512),
            }
            if curve_name not in curves:
                return False
            curve_cls, hash_cls = curves[curve_name]
            rr, r = _ssh_read_string(signature, 0)
            ss, r = _ssh_read_string(signature, r)
            from cryptography.hazmat.primitives.asymmetric.utils import (
                encode_dss_signature)
            der = encode_dss_signature(
                int.from_bytes(rr, "big"), int.from_bytes(ss, "big"))
            ec.EllipticCurvePublicKey.from_encoded_point(
                curve_cls(), point).verify(
                    der, data, ec.ECDSA(hash_cls()))
        elif alg in ("ssh-rsa", "rsa-sha2-256", "rsa-sha2-512"):
            e_b, q = _ssh_read_string(key_blob, q)
            n_b, q = _ssh_read_string(key_blob, q)
            public = rsa.RSAPublicNumbers(
                int.from_bytes(e_b, "big"),
                int.from_bytes(n_b, "big")).public_key()
            hash_cls = {
                "ssh-rsa": hashes.SHA1,
                "rsa-sha2-256": hashes.SHA256,
                "rsa-sha2-512": hashes.SHA512,
            }[alg]
            public.verify(
                signature, data, padding.PKCS1v15(), hash_cls())
        else:
            return False
    except InvalidSignature:
        return False
    return True


# ---------------------------------------------------------------------
# OpenPGP verification (the operator's gpg, throwaway keyring)
# ---------------------------------------------------------------------

def _gpg_fingerprint(material: str) -> tuple[str, str]:
    """(fingerprint, key_id) of one armoured OpenPGP
    public key, read by gpg itself; a shape gpg
    cannot read is refused at the door."""
    if ("-----BEGIN PGP PUBLIC KEY BLOCK-----" not in material
            or "-----END PGP PUBLIC KEY BLOCK-----" not in material):
        raise CommitSignatureError(
            "signing_key_invalid",
            "An OpenPGP signing key is an armoured public key "
            "block.")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "key.asc"
        path.write_text(material, encoding="utf-8")
        result = run_program("gpg", [
            "--batch", "--no-tty", "--with-colons",
            "--show-keys", str(path)], timeout=30.0)
    if result.returncode != 0:
        raise CommitSignatureError(
            "signing_key_invalid",
            "That OpenPGP public key cannot be read.")
    fingerprint = key_id = ""
    for line in result.stdout.decode("utf-8", "replace").splitlines():
        fields = line.split(":")
        if fields[0] == "pub" and len(fields) > 4:
            key_id = fields[4]
        if fields[0] == "fpr" and len(fields) > 9:
            fingerprint = fields[9]
            break
    if not fingerprint:
        raise CommitSignatureError(
            "signing_key_invalid",
            "That OpenPGP public key carries no fingerprint.")
    return fingerprint, key_id


def verify_openpgp(payload: bytes, armour: str,
                   materials: list[str]) -> tuple[bool, str]:
    """(passed, fingerprint): gpg verifies the detached
    *armour* over *payload* with only the registered
    *materials* in a throwaway keyring. A VALIDSIG
    status line is the only pass, and its fingerprint
    is returned so the caller can name the key."""
    if not materials:
        return False, ""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td) / "gnupg"
        home.mkdir(mode=0o700)
        keys_path = Path(td) / "keys.asc"
        keys_path.write_text("\n".join(materials), encoding="utf-8")
        imported = run_program("gpg", [
            "--batch", "--no-tty", "--homedir", str(home),
            "--import", str(keys_path)], timeout=30.0)
        if imported.returncode != 0:
            return False, ""
        sig_path = Path(td) / "sig.asc"
        sig_path.write_text(armour, encoding="utf-8")
        data_path = Path(td) / "payload.bin"
        data_path.write_bytes(payload)
        result = run_program("gpg", [
            "--batch", "--no-tty", "--homedir", str(home),
            "--status-fd", "1", "--verify",
            str(sig_path), str(data_path)], timeout=30.0)
    status = result.stdout.decode("utf-8", "replace")
    for line in status.splitlines():
        if line.startswith("[GNUPG:] VALIDSIG "):
            parts = line.split()
            if len(parts) >= 3:
                return True, parts[2]
    return False, ""


# ---------------------------------------------------------------------
# Signing-key registry (migration 126)
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class SigningKey:
    id: int
    user_id: int
    username: str
    kind: str
    title: str
    fingerprint: str
    key_id: str
    material: str
    created_at: int


def validate_key_kind(kind: object) -> str:
    if kind not in KEY_KINDS:
        raise CommitSignatureError(
            "signing_key_kind_invalid",
            "A signing key is OpenPGP or SSH.")
    return str(kind)


def validate_key_title(title: object) -> str:
    if not isinstance(title, str) or not title.strip():
        raise CommitSignatureError(
            "signing_key_title_required",
            "Name the signing key.")
    text = title.strip()
    if len(text) > TITLE_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise CommitSignatureError(
            "signing_key_title_invalid",
            f"A signing-key name is at most {TITLE_MAX} "
            "characters of plain text.")
    return text


class SigningKeyStore:
    """Accounts' public signing keys. Only public
    material is ever stored: an SSH private shape or
    an OpenPGP private block offered at the door is
    refused, never filed."""

    def __init__(self, conn: sqlite3.Connection,
                 accounts: AccountStore,
                 time_fn=time.time):
        self._conn = conn
        self._accounts = accounts
        self._time = time_fn

    def _row(self, row: sqlite3.Row) -> SigningKey:
        return SigningKey(
            id=row["id"], user_id=row["user_id"],
            username=row["username"], kind=row["kind"],
            title=row["title"], fingerprint=row["fingerprint"],
            key_id=row["key_id"], material=row["material"],
            created_at=row["created_at"])

    def register_key(self, user: User, kind: object,
                     title: object, material: object) -> SigningKey:
        kind_v = validate_key_kind(kind)
        title_v = validate_key_title(title)
        if not isinstance(material, str) or not material.strip():
            raise CommitSignatureError(
                "signing_key_required", "Paste a public key.")
        text = material.strip()
        if len(text) > _MATERIAL_MAX:
            raise CommitSignatureError(
                "signing_key_too_large", "That key is too large.")
        if "PRIVATE KEY" in text or "OPENSSH PRIVATE" in text:
            raise CommitSignatureError(
                "signing_key_invalid",
                "That is a private key; register the public "
                "key only.")
        if kind_v == KIND_SSH:
            parsed = parse_public_key(text)
            fingerprint = ssh_fingerprint_of(parsed.blob)
            key_id = parsed.key_type
            stored = text
            blob = parsed.blob
        else:
            fingerprint, key_id = _gpg_fingerprint(text)
            stored = text
            blob = b""
        clash = self._conn.execute(
            "SELECT username FROM signing_keys"
            " WHERE kind = ? AND fingerprint = ?",
            (kind_v, fingerprint)).fetchone()
        if clash is not None:
            if clash["username"] != user.username:
                raise CommitSignatureError(
                    "signing_key_taken",
                    "That key already stands for another "
                    "account; a key vouches for one signer.")
            raise CommitSignatureError(
                "signing_key_taken",
                "That key is already registered to your "
                "account.")
        cur = self._conn.execute(
            "INSERT INTO signing_keys (user_id, username, kind,"
            " title, fingerprint, key_id, material, blob,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user.id, user.username, kind_v, title_v,
             fingerprint, key_id, stored, blob,
             int(self._time())))
        self._conn.commit()
        return self.get_key(cur.lastrowid)

    def get_key(self, key_id_pk: int) -> SigningKey:
        row = self._conn.execute(
            "SELECT * FROM signing_keys WHERE id = ?",
            (key_id_pk,)).fetchone()
        if row is None:
            raise CommitSignatureError(
                "signing_key_not_found", "No such signing key.")
        return self._row(row)

    def list_keys(self, user: User) -> list[SigningKey]:
        rows = self._conn.execute(
            "SELECT * FROM signing_keys WHERE user_id = ?"
            " ORDER BY id", (user.id,)).fetchall()
        return [self._row(r) for r in rows]

    def all_keys(self, kind: str = "") -> list[SigningKey]:
        if kind:
            rows = self._conn.execute(
                "SELECT * FROM signing_keys WHERE kind = ?"
                " ORDER BY id", (kind,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM signing_keys ORDER BY id").fetchall()
        return [self._row(r) for r in rows]

    def remove_key(self, user: User, key_id_pk: object) -> SigningKey:
        row = self._conn.execute(
            "SELECT * FROM signing_keys WHERE id = ?"
            " AND user_id = ?",
            (key_id_pk, user.id)).fetchone()
        if row is None:
            raise CommitSignatureError(
                "signing_key_not_found", "No such signing key.")
        key = self._row(row)
        self._conn.execute(
            "DELETE FROM signing_keys WHERE id = ?", (key.id,))
        self._conn.commit()
        return key


# ---------------------------------------------------------------------
# Verification records: ingest and display
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class CommitVerification:
    full_name: str
    oid: str
    kind: str
    trust: str
    check: str
    signer: str
    fingerprint: str
    author_email: str
    detail: str
    verified_at: int

    @property
    def trust_words(self) -> str:
        return trust_words(self.trust)

    @property
    def signer_words(self) -> str:
        if self.signer:
            return f"signer {self.signer}"
        if self.kind:
            return "signer unknown"
        return "no signature"

    @property
    def badge_words(self) -> str:
        return (
            f"{self.trust_words} -- {self.signer_words} "
            f"({KIND_WORDS.get(self.kind, 'none')} signature)"
            if self.kind else
            f"{self.trust_words} -- no signature")


def verification_to_dict(record: CommitVerification) -> dict:
    return {
        "repository": record.full_name,
        "oid": record.oid,
        "kind": record.kind,
        "kind_words": KIND_WORDS.get(record.kind, "none"),
        "trust": record.trust,
        "trust_words": record.trust_words,
        "check": record.check,
        "signer": record.signer,
        "signer_words": record.signer_words,
        "badge_words": record.badge_words,
        "fingerprint": record.fingerprint,
        "author_email": record.author_email,
        "detail": record.detail,
        "verified_at": record.verified_at,
    }


class CommitSignatureStore:
    """Verifies commits on ingest and answers their
    badges on display, over migration 126's rows."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 accounts: AccountStore,
                 signing_keys: SigningKeyStore,
                 time_fn=time.time):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._keys = signing_keys
        self._time = time_fn

    # -- the judgement, pure over gathered facts ----------------------

    def _judge(self, extracted: ExtractedSignature,
               author_email: str, committer_email: str,
               ) -> tuple[str, str, str, str, str]:
        """(trust, check, signer, fingerprint, detail)."""
        if not extracted.header:
            return (
                "unverified", "not_checked", "", "",
                "This commit carries no signature header, so "
                "there is nothing to verify.")
        if extracted.kind == KIND_SSH:
            keys = self._keys.all_keys(KIND_SSH)
            matched: SigningKey | None = None
            check = "failed"
            for key in keys:
                row = self._conn.execute(
                    "SELECT blob FROM signing_keys WHERE id = ?",
                    (key.id,)).fetchone()
                try:
                    if verify_ssh(extracted.payload,
                                  extracted.armour,
                                  bytes(row["blob"])):
                        matched = key
                        check = "passed"
                        break
                except CommitSignatureError:
                    check = "failed"
                    break
            if matched is None:
                return (
                    "unverified", check, "", "",
                    "The SSH signature does not verify under "
                    "any registered signing key, so the "
                    "signer is not proven.")
            return self._matched(matched, author_email,
                                 committer_email, "SSH")
        if extracted.kind == KIND_OPENPGP:
            keys = self._keys.all_keys(KIND_OPENPGP)
            passed, fingerprint = verify_openpgp(
                extracted.payload, extracted.armour,
                [k.material for k in keys])
            if not passed:
                return (
                    "unverified", "failed", "", "",
                    "The OpenPGP signature does not verify "
                    "under any registered signing key, so "
                    "the signer is not proven.")
            matched = next(
                (k for k in keys
                 if k.fingerprint == fingerprint), None)
            if matched is None:
                return (
                    "unverified", "failed", "", fingerprint,
                    "The OpenPGP signature verified under a "
                    "key Samverk does not hold, so the "
                    "signer is not proven.")
            return self._matched(matched, author_email,
                                 committer_email, "OpenPGP")
        return (
            "unverified", "failed", "", "",
            "The signature header carries no armour "
            "Samverk can check (neither an OpenPGP nor "
            "an SSH signature), so the signer is not "
            "proven.")

    def _matched(self, key: SigningKey, author_email: str,
                 committer_email: str, kind_word: str,
                 ) -> tuple[str, str, str, str, str]:
        owner = self._accounts.get_by_id(key.user_id)
        known = False
        if owner is not None:
            for email in (author_email, committer_email):
                if not email:
                    continue
                named = self._accounts.get_by_email(email)
                if named is not None and named.id == owner.id:
                    known = True
        trust = decide_signature_trust("passed", known)
        if trust == "verified":
            detail = (
                f"Samverk verified this {kind_word} signature "
                f"against the registered key for "
                f"{key.username}, and that account matches "
                f"the commit's author.")
        else:
            detail = (
                f"Samverk verified this {kind_word} signature "
                f"against the registered key for "
                f"{key.username}, but that account is not "
                f"the commit's author, so the badge is "
                f"partial: the signature is real, the "
                f"signer is not the author.")
        return (trust, "passed", key.username,
                key.fingerprint, detail)

    # -- ingest ---------------------------------------------------------

    def verify_commit(self, owner: object, repo: object,
                      oid: object) -> CommitVerification:
        """The ingest act: verify one commit whole and
        store the verdict. A machine act with no
        viewer: it judges the object, never a person,
        and it writes only the verdict row."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise CommitSignatureError(
                "repo_not_found", "No such repository.")
        if not isinstance(oid, str) or not _OID_RE.match(oid):
            raise CommitSignatureError(
                "commit_not_found", "No such commit.")
        path = self._repos.path_for(current.owner, current.name)
        reader = ObjectReader(path)
        try:
            obj = reader.read_object(oid)
        except Exception:
            raise CommitSignatureError(
                "commit_not_found", "No such commit.") from None
        if obj.type != "commit":
            raise CommitSignatureError(
                "commit_not_found", "No such commit.")
        raw = obj.data
        extracted = extract_signature(raw)
        author_email, committer_email = _identities(raw)
        trust, check, signer, fingerprint, detail = self._judge(
            extracted, author_email, committer_email)
        now = int(self._time())
        self._conn.execute(
            "INSERT INTO commit_verifications (repo_id, oid,"
            " kind, trust, check_state, signer, fingerprint,"
            " author_email, detail, verified_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(repo_id, oid) DO UPDATE SET"
            " kind = excluded.kind, trust = excluded.trust,"
            " check_state = excluded.check_state,"
            " signer = excluded.signer,"
            " fingerprint = excluded.fingerprint,"
            " author_email = excluded.author_email,"
            " detail = excluded.detail,"
            " verified_at = excluded.verified_at",
            (current.id, oid, extracted.kind, trust, check,
             signer, fingerprint, author_email, detail, now))
        self._conn.commit()
        return CommitVerification(
            full_name=current.full_name, oid=oid,
            kind=extracted.kind, trust=trust, check=check,
            signer=signer, fingerprint=fingerprint,
            author_email=author_email, detail=detail,
            verified_at=now)

    def ingest(self, owner: object, repo: object,
               oids) -> list[CommitVerification]:
        return [self.verify_commit(owner, repo, oid)
                for oid in oids]

    # -- display --------------------------------------------------------

    def verification_for(self, viewer: User | None,
                         owner: object, repo: object,
                         oid: object) -> CommitVerification:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise CommitSignatureError(
                "repo_not_found", "No such repository.")
        if not isinstance(oid, str) or not _OID_RE.match(oid):
            raise CommitSignatureError(
                "commit_not_found", "No such commit.")
        row = self._conn.execute(
            "SELECT * FROM commit_verifications"
            " WHERE repo_id = ? AND oid = ?",
            (current.id, oid)).fetchone()
        if row is None:
            return CommitVerification(
                full_name=current.full_name, oid=oid, kind="",
                trust="unverified", check="not_checked",
                signer="", fingerprint="", author_email="",
                detail="Samverk has not checked this commit "
                       "yet; an unchecked commit is shown "
                       "unverified, never assumed signed.",
                verified_at=0)
        return CommitVerification(
            full_name=current.full_name, oid=oid,
            kind=row["kind"], trust=row["trust"],
            check=row["check_state"], signer=row["signer"],
            fingerprint=row["fingerprint"],
            author_email=row["author_email"],
            detail=row["detail"],
            verified_at=row["verified_at"])


# ---------------------------------------------------------------------
# Rendering (S-010 escaped; the badge is words, never a bare tick)
# ---------------------------------------------------------------------

def render_commit_signature_badge(
        record: CommitVerification) -> str:
    trust = record.trust if record.trust in TRUST_STATES \
        else "unverified"
    return (
        '<span class="commit-signature-badge '
        'commit-signature-' + escape_html_text(trust) + '">'
        + escape_html_text(record.badge_words)
        + "</span>")


def render_commit_signatures_page(
        full_name: str,
        records: list[CommitVerification]) -> str:
    if records:
        body = "".join(
            '<article class="commit-signature"><p>'
            + '<span class="commit-oid">'
            + escape_html_text(r.oid[:12]) + "</span> &middot; "
            + render_commit_signature_badge(r)
            + "</p><p>" + escape_html_text(r.detail)
            + "</p></article>"
            for r in records)
    else:
        body = ("<p>No commits have been checked in this "
                "repository yet.</p>")
    return (
        '<section class="commit-signatures"><h3>Signed '
        "commits in " + escape_html_text(full_name)
        + "</h3><p>Badges are words, never a bare tick: "
        "verified, partially verified, or unverified, "
        "with the signer named.</p>" + body + "</section>")


# ---------------------------------------------------------------------
# Audit: the honesty invariant over the stored rows
# ---------------------------------------------------------------------

def audit_commit_signatures(conn: sqlite3.Connection) -> list[str]:
    problems: list[str] = []
    for row in conn.execute(
            "SELECT * FROM commit_verifications").fetchall():
        if row["trust"] not in TRUST_STATES:
            problems.append(
                f"commit {row['oid']} in repo {row['repo_id']} "
                f"carries trust {row['trust']!r} outside the "
                f"vocabulary")
        if row["check_state"] not in CHECK_STATES:
            problems.append(
                f"commit {row['oid']} in repo {row['repo_id']} "
                f"carries check {row['check_state']!r} outside "
                f"the vocabulary")
        if row["trust"] == "verified" and (
                not row["signer"] or not row["fingerprint"]):
            problems.append(
                f"commit {row['oid']} in repo {row['repo_id']} "
                f"claims verified without a signer and a "
                f"fingerprint")
        if row["trust"] == "verified" \
                and row["check_state"] != "passed":
            problems.append(
                f"commit {row['oid']} in repo {row['repo_id']} "
                f"claims verified without a passed check")
    for row in conn.execute(
            "SELECT * FROM signing_keys").fetchall():
        if row["kind"] not in KEY_KINDS:
            problems.append(
                f"signing key {row['id']} carries kind "
                f"{row['kind']!r} outside the vocabulary")
        if not row["fingerprint"]:
            problems.append(
                f"signing key {row['id']} carries no "
                f"fingerprint")
    return problems
