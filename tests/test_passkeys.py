"""S-039 acceptance battery: passkeys / WebAuthn.

Acceptance (roadmap S-039): enrolment and login as a second
factor and as a passwordless option — interop test with two
authenticator implementations. Two independent software
authenticators live in this file and share no code with the
server: one ES256 (P-256 ECDSA, DER signatures, `none` and
`packed` self-attestation) and one Ed25519 (RFC 8032
mathematics written out here again). Around them: the
sudo gate, challenge single-use and expiry, RP and origin
binding, cloned-counter refusal, one-passkey-one-account,
and owner-only removal.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.passkeys import PasskeyError, PasskeyStore, b64url_encode
from samverk.sessions import SessionStore

GOOD_PW = "a long enough passphrase"
RP_ID = "localhost"
ORIGIN = "https://localhost"


# ------------------------------------------------------------------
# Minimal CBOR encoder (test-side; the server has only a decoder)
# ------------------------------------------------------------------

def _head(major: int, arg: int) -> bytes:
    if arg < 24:
        return bytes([(major << 5) | arg])
    if arg < 256:
        return bytes([(major << 5) | 24, arg])
    if arg < 65536:
        return bytes([(major << 5) | 25]) + struct.pack(">H", arg)
    return bytes([(major << 5) | 26]) + struct.pack(">I", arg)


def cbor_encode(value) -> bytes:
    if isinstance(value, int):
        if value >= 0:
            return _head(0, value)
        return _head(1, -1 - value)
    if isinstance(value, bytes):
        return _head(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return _head(3, len(raw)) + raw
    if isinstance(value, (list, tuple)):
        return _head(4, len(value)) + b"".join(
            cbor_encode(v) for v in value)
    if isinstance(value, dict):
        out = _head(5, len(value))
        for k, v in value.items():
            out += cbor_encode(k) + cbor_encode(v)
        return out
    raise TypeError(type(value))


def client_data(kind: str, challenge: str, origin: str = ORIGIN) -> str:
    raw = json.dumps({
        "type": kind, "challenge": challenge, "origin": origin,
        "crossOrigin": False,
    }).encode("utf-8")
    return b64url_encode(raw)


# ------------------------------------------------------------------
# Authenticator one: ES256 (P-256), `none` / `packed` attestation
# ------------------------------------------------------------------

_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
      0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if p1 == p2:
        m = (3 * x1 * x1 + _A) * pow(2 * y1, _P - 2, _P) % _P
    else:
        m = (y2 - y1) * pow((x2 - x1) % _P, _P - 2, _P) % _P
    x3 = (m * m - x1 - x2) % _P
    return x3, (m * (x1 - x3) - y1) % _P


def _mul(k, point):
    result, addend = None, point
    while k:
        if k & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        k >>= 1
    return result


def _der_int(v: int) -> bytes:
    raw = v.to_bytes(max(1, (v.bit_length() + 7) // 8), "big")
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return b"\x02" + bytes([len(raw)]) + raw


class EcAuthenticator:
    def __init__(self, rp_id: str = RP_ID):
        self.rp_id = rp_id
        self.priv = secrets.randbelow(_N - 1) + 1
        self.pub = _mul(self.priv, _G)
        self.cred_id = os.urandom(16)
        self.count = 0

    def cose(self) -> bytes:
        x, y = self.pub
        return cbor_encode({
            1: 2, 3: -7, -1: 1,
            -2: x.to_bytes(32, "big"), -3: y.to_bytes(32, "big")})

    def _sign_digest(self, digest: bytes) -> bytes:
        z = int.from_bytes(digest, "big")
        while True:
            k = secrets.randbelow(_N - 1) + 1
            r = _mul(k, _G)[0] % _N
            if r == 0:
                continue
            s = pow(k, -1, _N) * (z + r * self.priv) % _N
            if s:
                break
        body = _der_int(r) + _der_int(s)
        return b"\x30" + bytes([len(body)]) + body

    def attestation(self, challenge: str, fmt: str = "none",
                    origin: str = ORIGIN):
        cd = client_data("webauthn.create", challenge, origin)
        from samverk.passkeys import b64url_decode
        client_hash = hashlib.sha256(b64url_decode(cd)).digest()
        auth = (hashlib.sha256(self.rp_id.encode()).digest()
                + bytes([0x45]) + struct.pack(">I", self.count)
                + b"\x00" * 16
                + struct.pack(">H", len(self.cred_id)) + self.cred_id
                + self.cose())
        if fmt == "packed":
            sig = self._sign_digest(
                hashlib.sha256(auth + client_hash).digest())
            stmt = {"alg": -7, "sig": sig}
        else:
            stmt = {}
        att = cbor_encode({"fmt": fmt, "attStmt": stmt, "authData": auth})
        return b64url_encode(att), cd

    def assertion(self, challenge: str, origin: str = ORIGIN,
                  count: int | None = None):
        if count is None:
            self.count += 1
            count = self.count
        cd = client_data("webauthn.get", challenge, origin)
        from samverk.passkeys import b64url_decode
        client_hash = hashlib.sha256(b64url_decode(cd)).digest()
        auth = (hashlib.sha256(self.rp_id.encode()).digest()
                + bytes([0x05]) + struct.pack(">I", count))
        sig = self._sign_digest(hashlib.sha256(auth + client_hash).digest())
        return {
            "credential_id": b64url_encode(self.cred_id),
            "authenticator_data_b64": b64url_encode(auth),
            "client_data_b64": cd,
            "signature_b64": b64url_encode(sig),
        }


# ------------------------------------------------------------------
# Authenticator two: Ed25519, RFC 8032 written out independently
# ------------------------------------------------------------------

_Q = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _Q - 2, _Q)) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)


def _ed_add(p1, p2):
    x1, y1 = p1
    x2, y2 = p2
    t = _D * x1 * x2 * y1 * y2 % _Q
    return ((x1 * y2 + x2 * y1) * pow(1 + t, _Q - 2, _Q) % _Q,
            (y1 * y2 + x1 * x2) * pow(1 - t, _Q - 2, _Q) % _Q)


def _ed_mul(k, point):
    result, addend = (0, 1), point
    while k:
        if k & 1:
            result = _ed_add(result, addend)
        addend = _ed_add(addend, addend)
        k >>= 1
    return result


def _ed_encode(point) -> bytes:
    x, y = point
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _ed_base():
    y = 4 * pow(5, _Q - 2, _Q) % _Q
    xx = (y * y - 1) * pow(_D * y * y + 1, _Q - 2, _Q) % _Q
    x = pow(xx, (_Q + 3) // 8, _Q)
    if (x * x - xx) % _Q != 0:
        x = x * _I % _Q
    if x & 1:
        x = _Q - x
    return x, y


class EdAuthenticator:
    def __init__(self, rp_id: str = RP_ID):
        self.rp_id = rp_id
        seed = os.urandom(32)
        h = hashlib.sha512(seed).digest()
        a_bytes = bytearray(h[:32])
        a_bytes[0] &= 248
        a_bytes[31] &= 63
        a_bytes[31] |= 64
        self.a = int.from_bytes(a_bytes, "little")
        self.prefix = h[32:]
        self.pub_bytes = _ed_encode(_ed_mul(self.a, _ed_base()))
        self.cred_id = os.urandom(16)
        self.count = 0

    def cose(self) -> bytes:
        return cbor_encode({1: 1, 3: -8, -1: 6, -2: self.pub_bytes})

    def _sign(self, message: bytes) -> bytes:
        r = int.from_bytes(hashlib.sha512(
            self.prefix + message).digest(), "little") % _L
        r_enc = _ed_encode(_ed_mul(r, _ed_base()))
        h = int.from_bytes(hashlib.sha512(
            r_enc + self.pub_bytes + message).digest(), "little") % _L
        s = (r + h * self.a) % _L
        return r_enc + s.to_bytes(32, "little")

    def attestation(self, challenge: str, origin: str = ORIGIN):
        cd = client_data("webauthn.create", challenge, origin)
        auth = (hashlib.sha256(self.rp_id.encode()).digest()
                + bytes([0x45]) + struct.pack(">I", self.count)
                + b"\x00" * 16
                + struct.pack(">H", len(self.cred_id)) + self.cred_id
                + self.cose())
        att = cbor_encode(
            {"fmt": "none", "attStmt": {}, "authData": auth})
        return b64url_encode(att), cd

    def assertion(self, challenge: str, origin: str = ORIGIN):
        self.count += 1
        cd = client_data("webauthn.get", challenge, origin)
        from samverk.passkeys import b64url_decode
        client_digest = hashlib.sha256(b64url_decode(cd)).digest()
        auth = (hashlib.sha256(self.rp_id.encode()).digest()
                + bytes([0x05]) + struct.pack(">I", self.count))
        sig = self._sign(auth + client_digest)
        return {
            "credential_id": b64url_encode(self.cred_id),
            "authenticator_data_b64": b64url_encode(auth),
            "client_data_b64": cd,
            "signature_b64": b64url_encode(sig),
        }


# ------------------------------------------------------------------
# The battery
# ------------------------------------------------------------------

class PasskeyTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.other = self.accounts.register("astrid", GOOD_PW)
        self.clock = [int(time.time())]
        now = lambda: self.clock[0]  # noqa: E731
        self.store = PasskeyStore(
            self.conn, self.accounts, audit=self.audit,
            reauth_verifier=lambda uid: True,
            rp_id=RP_ID, expected_origins=(ORIGIN,), time_fn=now)
        self.sessions = SessionStore(self.conn, time_fn=now)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def _enrol(self, authenticator, user=None, **kw):
        user = user or self.user
        challenge = self.store.begin_registration(user.id)
        att, cd = authenticator.attestation(challenge, **kw)
        return self.store.complete_registration(
            user.id, challenge, att, cd, nickname="Test key")

    # -- interop: two authenticator implementations ----------------
    def test_es256_enrol_and_passwordless_login(self):
        auth = EcAuthenticator()
        cred = self._enrol(auth)
        self.assertTrue(self.store.has_passkeys(self.user.id))
        self.assertEqual([c.id for c in self.store.list_for_user(
            self.user.id)], [cred.id])
        challenge = self.store.begin_authentication()
        result = self.store.complete_authentication(
            challenge, **auth.assertion(challenge))
        self.assertEqual(result.user_id, self.user.id)
        # The passwordless door: a verified assertion mints the
        # ordinary S-006 session, exactly as the password road does.
        token = self.sessions.create(result.user_id)
        self.assertEqual(self.sessions.authenticate(token), self.user.id)
        self.assertEqual(result.credential.sign_count, 1)

    def test_ed25519_enrol_and_second_factor_login(self):
        auth = EdAuthenticator()
        self._enrol(auth)
        # Bound to the account: the second-factor shape.
        challenge = self.store.begin_authentication(self.user.id)
        result = self.store.complete_authentication(
            challenge, **auth.assertion(challenge))
        self.assertEqual(result.user_id, self.user.id)

    def test_packed_self_attestation_enrols(self):
        auth = EcAuthenticator()
        cred = self._enrol(auth, fmt="packed")
        self.assertEqual(cred.user_id, self.user.id)

    # -- the gates ---------------------------------------------------
    def test_enrolment_requires_sudo(self):
        bare = PasskeyStore(
            self.conn, self.accounts, rp_id=RP_ID,
            expected_origins=(ORIGIN,),
            time_fn=lambda: self.clock[0])
        with self.assertRaises(PasskeyError) as ctx:
            bare.begin_registration(self.user.id)
        self.assertEqual(ctx.exception.reason, "sudo_required")

    def test_challenge_is_single_use(self):
        auth = EcAuthenticator()
        self._enrol(auth)
        challenge = self.store.begin_authentication()
        args = auth.assertion(challenge)
        self.store.complete_authentication(challenge, **args)
        with self.assertRaises(PasskeyError) as ctx:
            # A fresh assertion answering the *same* challenge:
            # its response is honest, the challenge is spent.
            self.store.complete_authentication(
                challenge, **auth.assertion(challenge))
        self.assertEqual(ctx.exception.reason, "challenge_invalid")

    def test_challenge_expires(self):
        auth = EcAuthenticator()
        challenge = self.store.begin_registration(self.user.id)
        self.clock[0] += 301
        att, cd = auth.attestation(challenge)
        with self.assertRaises(PasskeyError) as ctx:
            self.store.complete_registration(
                self.user.id, challenge, att, cd)
        self.assertEqual(ctx.exception.reason, "challenge_invalid")

    def test_wrong_rp_is_refused(self):
        auth = EcAuthenticator(rp_id="evil.example")
        challenge = self.store.begin_registration(self.user.id)
        att, cd = auth.attestation(challenge)
        with self.assertRaises(PasskeyError) as ctx:
            self.store.complete_registration(
                self.user.id, challenge, att, cd)
        self.assertEqual(ctx.exception.reason, "rp_mismatch")

    def test_wrong_origin_is_refused(self):
        auth = EcAuthenticator()
        self._enrol(auth)
        challenge = self.store.begin_authentication()
        with self.assertRaises(PasskeyError) as ctx:
            self.store.complete_authentication(
                challenge,
                **auth.assertion(challenge, origin="https://evil.example"))
        self.assertEqual(ctx.exception.reason, "origin_refused")

    def test_tampered_signature_is_refused(self):
        auth = EcAuthenticator()
        self._enrol(auth)
        challenge = self.store.begin_authentication()
        args = auth.assertion(challenge)
        from samverk.passkeys import b64url_decode
        sig = bytearray(b64url_decode(args["signature_b64"]))
        sig[-1] ^= 0x01
        args["signature_b64"] = b64url_encode(bytes(sig))
        with self.assertRaises(PasskeyError) as ctx:
            self.store.complete_authentication(challenge, **args)
        self.assertEqual(ctx.exception.reason, "assertion_failed")

    def test_cloned_counter_is_refused(self):
        auth = EcAuthenticator()
        self._enrol(auth)
        challenge = self.store.begin_authentication()
        self.store.complete_authentication(
            challenge, **auth.assertion(challenge))  # count -> 1
        challenge = self.store.begin_authentication()
        with self.assertRaises(PasskeyError) as ctx:
            # The "clone" still sits at the copied counter.
            self.store.complete_authentication(
                challenge, **auth.assertion(challenge, count=1))
        self.assertEqual(ctx.exception.reason, "cloned_authenticator")

    def test_one_passkey_one_account(self):
        auth = EcAuthenticator()
        self._enrol(auth)
        with self.assertRaises(PasskeyError) as ctx:
            self._enrol(auth, user=self.other)
        self.assertEqual(ctx.exception.reason, "credential_taken")

    def test_unknown_attestation_format_refused_by_name(self):
        auth = EcAuthenticator()
        challenge = self.store.begin_registration(self.user.id)
        att, cd = auth.attestation(challenge, fmt="tpm")
        with self.assertRaises(PasskeyError) as ctx:
            self.store.complete_registration(
                self.user.id, challenge, att, cd)
        self.assertEqual(ctx.exception.reason, "unsupported_attestation")

    def test_remove_is_owner_only_and_audited(self):
        auth = EcAuthenticator()
        cred = self._enrol(auth)
        self.assertFalse(self.store.remove(self.other.id, cred.id))
        self.assertTrue(self.store.has_passkeys(self.user.id))
        self.assertTrue(self.store.remove(self.user.id, cred.id))
        self.assertFalse(self.store.has_passkeys(self.user.id))
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log"
            " WHERE action LIKE 'auth.passkey.%' ORDER BY seq")]
        self.assertEqual(actions,
                         ["auth.passkey.add", "auth.passkey.remove"])


if __name__ == "__main__":
    unittest.main()
