"""Passkeys / WebAuthn (S-039) — the public WebAuthn Level 2
specification (W3C) as code, clean-room from the spec's
ceremonies and data shapes; no library is admitted (S-017),
so CBOR, COSE and the signature checks are implemented here
on the standard library alone.

Two ceremonies, one credential store:

- **Registration** (enrolment) is a step-up act through the
  standing re-auth seam (S-036 supplies the real verifier),
  failing closed. The server issues a 256-bit challenge —
  only its SHA-256 is stored, single-use, five minutes to
  live — and verifies the attestation response: the client
  data's type, challenge and origin; the authenticator
  data's RP-ID hash, user-presence flag and attested
  credential data; and the attestation format. `none` is
  accepted (the authenticator makes no claim beyond the
  credential itself) and `packed` *self*-attestation is
  verified with the new credential's own key; certificate
  chains (x5c) and every other format are refused by name —
  this instance vouches for accounts, not for hardware
  vendors. Each credential id belongs to exactly one
  account, worldwide.
- **Authentication** (assertion) verifies a fresh challenge,
  the RP-ID hash, the origin, and the COSE signature
  (ES256, RS256, or EdDSA) over
  `authenticatorData || SHA-256(clientDataJSON)`. The
  authenticator's signature counter must move forward —
  a counter that stands still or goes backwards, when
  counters are in use, is a cloned authenticator and is
  refused by name. The same ceremony serves both doors the
  roadmap names: with the challenge bound to an account it
  is that account's **second factor**; unbound, the verified
  credential itself names the account — **passwordless**
  login (the caller then mints the S-006 session, exactly
  as the password road does, and the battery proves it).

Public keys are stored as their original COSE bytes; no
private material of any kind ever reaches this server —
that is the whole point of the design.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore
from .audit import AuditLog
from .throttle import constant_time_equal

CHALLENGE_TTL_SECONDS = 300
_CHALLENGE_BYTES = 32  # 256 bits
_MAX_CBOR_DEPTH = 16


class PasskeyError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


# ------------------------------------------------------------------
# base64url — the WebAuthn wire encoding
# ------------------------------------------------------------------

def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(text: object) -> bytes:
    if not isinstance(text, str):
        raise PasskeyError("malformed", "Expected base64url text.")
    try:
        padded = text + "=" * (-len(text) % 4)
        return base64.b64decode(
            padded.encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError):
        raise PasskeyError(
            "malformed", "A WebAuthn value was not valid base64url."
        ) from None


# ------------------------------------------------------------------
# CBOR — the definite-length subset attestation objects use
# (RFC 8949 shapes read from the public spec; no floats needed
# beyond refusing them cleanly)
# ------------------------------------------------------------------

class _CborReader:
    def __init__(self, data: bytes):
        self._data = data
        self.pos = 0

    def _take(self, n: int) -> bytes:
        if self.pos + n > len(self._data):
            raise PasskeyError("malformed", "Truncated CBOR value.")
        out = self._data[self.pos:self.pos + n]
        self.pos += n
        return out

    def _argument(self, info: int) -> int:
        if info < 24:
            return info
        if info == 24:
            return self._take(1)[0]
        if info == 25:
            return struct.unpack(">H", self._take(2))[0]
        if info == 26:
            return struct.unpack(">I", self._take(4))[0]
        if info == 27:
            return struct.unpack(">Q", self._take(8))[0]
        raise PasskeyError("malformed", "Indefinite CBOR is refused.")

    def read(self, depth: int = 0):
        if depth > _MAX_CBOR_DEPTH:
            raise PasskeyError("malformed", "CBOR nested too deeply.")
        first = self._take(1)[0]
        major, info = first >> 5, first & 0x1F
        if major == 0:
            return self._argument(info)
        if major == 1:
            return -1 - self._argument(info)
        if major == 2:
            return self._take(self._argument(info))
        if major == 3:
            try:
                return self._take(self._argument(info)).decode("utf-8")
            except UnicodeDecodeError:
                raise PasskeyError(
                    "malformed", "CBOR text was not UTF-8.") from None
        if major == 4:
            return [self.read(depth + 1)
                    for _ in range(self._argument(info))]
        if major == 5:
            out = {}
            for _ in range(self._argument(info)):
                key = self.read(depth + 1)
                out[key] = self.read(depth + 1)
            return out
        if major == 7:
            if info == 20:
                return False
            if info == 21:
                return True
            if info == 22:
                return None
            raise PasskeyError(
                "malformed", "Unsupported CBOR simple value.")
        raise PasskeyError("malformed", "Unsupported CBOR major type.")


def cbor_decode(data: bytes):
    """Decode one CBOR value; trailing bytes are refused."""
    reader = _CborReader(data)
    value = reader.read()
    if reader.pos != len(data):
        raise PasskeyError("malformed", "Trailing bytes after CBOR value.")
    return value


# ------------------------------------------------------------------
# COSE keys and signature verification (pure Python, stdlib)
# ------------------------------------------------------------------

# P-256 (COSE curve 1) domain parameters, from the public
# FIPS 186-4 / SEC 2 specifications.
_P256_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_P256_A = _P256_P - 3
_P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_P256_G = (
    0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
    0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5,
)


def _ec_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _P256_P == 0:
        return None
    if p1 == p2:
        slope = (3 * x1 * x1 + _P256_A) * pow(
            2 * y1, _P256_P - 2, _P256_P) % _P256_P
    else:
        slope = (y2 - y1) * pow(
            (x2 - x1) % _P256_P, _P256_P - 2, _P256_P) % _P256_P
    x3 = (slope * slope - x1 - x2) % _P256_P
    return x3, (slope * (x1 - x3) - y1) % _P256_P


def _ec_mul(k: int, point):
    result = None
    addend = point
    while k:
        if k & 1:
            result = _ec_add(result, addend)
        addend = _ec_add(addend, addend)
        k >>= 1
    return result


def _der_read_int(data: bytes, pos: int) -> tuple[int, int]:
    if pos + 2 > len(data) or data[pos] != 0x02:
        raise PasskeyError("bad_signature", "Malformed ECDSA signature.")
    length = data[pos + 1]
    start, end = pos + 2, pos + 2 + length
    if end > len(data) or length == 0:
        raise PasskeyError("bad_signature", "Malformed ECDSA signature.")
    return int.from_bytes(data[start:end], "big"), end


def _verify_es256(public_point, digest: bytes, signature: bytes) -> bool:
    # Strict DER: SEQUENCE, length, then exactly two INTEGERs.
    if len(signature) < 8 or signature[0] != 0x30 \
            or signature[1] != len(signature) - 2:
        return False
    try:
        r, pos = _der_read_int(signature, 2)
        s, pos = _der_read_int(signature, pos)
    except PasskeyError:
        return False
    if pos != len(signature) or not (1 <= r < _P256_N and 1 <= s < _P256_N):
        return False
    x, y = public_point
    if (y * y - (x * x * x + _P256_A * x
                 + 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B)
            ) % _P256_P != 0:
        return False  # the stored point is not on P-256 at all
    z = int.from_bytes(digest, "big")
    w = pow(s, -1, _P256_N)
    point = _ec_add(_ec_mul(z * w % _P256_N, _P256_G),
                    _ec_mul(r * w % _P256_N, public_point))
    return point is not None and point[0] % _P256_N == r


_SHA256_DIGESTINFO_PREFIX = bytes.fromhex(
    "3031300d060960864801650304020105000420")


def _verify_rs256(modulus: int, exponent: int, digest: bytes,
                  signature: bytes) -> bool:
    k = (modulus.bit_length() + 7) // 8
    if len(signature) != k or k < len(_SHA256_DIGESTINFO_PREFIX) + 32 + 11:
        return False
    em = pow(int.from_bytes(signature, "big"), exponent, modulus)
    em_bytes = em.to_bytes(k, "big")
    expected_tail = _SHA256_DIGESTINFO_PREFIX + digest
    if not em_bytes.startswith(b"\x00\x01") or \
            not em_bytes.endswith(expected_tail):
        return False
    padding = em_bytes[2:k - len(expected_tail)]
    return all(b == 0xFF for b in padding) and \
        em_bytes[2 + len(padding)] == 0x00


# Ed25519 (COSE alg -8), per the public RFC 8032 mathematics.
_ED_Q = 2 ** 255 - 19
_ED_L = 2 ** 252 + 27742317777372353535851937790883648493
_ED_D = (-121665 * pow(121666, _ED_Q - 2, _ED_Q)) % _ED_Q
_ED_I = pow(2, (_ED_Q - 1) // 4, _ED_Q)


def _ed_add(p1, p2):
    x1, y1 = p1
    x2, y2 = p2
    t = _ED_D * x1 * x2 * y1 * y2 % _ED_Q
    return ((x1 * y2 + x2 * y1) * pow(1 + t, _ED_Q - 2, _ED_Q) % _ED_Q,
            (y1 * y2 + x1 * x2) * pow(1 - t, _ED_Q - 2, _ED_Q) % _ED_Q)


def _ed_mul(k: int, point):
    result = (0, 1)
    addend = point
    while k:
        if k & 1:
            result = _ed_add(result, addend)
        addend = _ed_add(addend, addend)
        k >>= 1
    return result


def _ed_decode_point(data: bytes):
    if len(data) != 32:
        return None
    bits = int.from_bytes(data, "little")
    sign = bits >> 255
    y = bits & ((1 << 255) - 1)
    if y >= _ED_Q:
        return None
    return _ed_recover_x(y, sign)


def _ed_recover_x(y: int, sign: int):
    u = (y * y - 1) % _ED_Q
    v = (_ED_D * y * y + 1) % _ED_Q
    xx = u * pow(v, _ED_Q - 2, _ED_Q) % _ED_Q
    x = pow(xx, (_ED_Q + 3) // 8, _ED_Q)
    if (x * x - xx) % _ED_Q != 0:
        x = x * _ED_I % _ED_Q
    if (x * x - xx) % _ED_Q != 0:
        return None
    if x == 0 and sign == 1:
        return None
    if (x & 1) != sign:
        x = _ED_Q - x
    return x, y


def _ed_encode_point(point) -> bytes:
    x, y = point
    bits = y | ((x & 1) << 255)
    return bits.to_bytes(32, "little")


def _verify_eddsa(public_bytes: bytes, message: bytes,
                  signature: bytes) -> bool:
    if len(signature) != 64:
        return False
    point_a = _ed_decode_point(public_bytes)
    point_r = _ed_decode_point(signature[:32])
    if point_a is None or point_r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _ED_L:
        return False
    h = int.from_bytes(hashlib.sha512(
        signature[:32] + public_bytes + message).digest(), "little")
    # [S]B == R + [H(R||A||M)]A   (RFC 8032 §5.1.7)
    left = _ed_mul(s, _ed_base_point())
    right = _ed_add(point_r, _ed_mul(h % _ED_L, point_a))
    return _ed_encode_point(left) == _ed_encode_point(right)


_ED_BASE = None


def _ed_base_point():
    global _ED_BASE
    if _ED_BASE is None:
        y = 4 * pow(5, _ED_Q - 2, _ED_Q) % _ED_Q
        _ED_BASE = _ed_recover_x(y, 0)
    return _ED_BASE


@dataclass(frozen=True)
class CoseKey:
    kty: int
    alg: int
    curve: int | None
    ec_point: tuple[int, int] | None   # kty 2 (EC2)
    rsa_modulus: int | None            # kty 3 (RSA)
    rsa_exponent: int | None
    okp_public: bytes | None           # kty 1 (OKP)

    def verify(self, digest: bytes, message: bytes,
               signature: bytes) -> bool:
        """ES256/EdDSA sign the *digest-of-message* construction
        WebAuthn uses: ES256 over SHA-256(message) is checked as
        ECDSA with the digest given; RS256 likewise; EdDSA takes
        the message itself."""
        if self.alg == -7 and self.ec_point is not None:
            return _verify_es256(self.ec_point, digest, signature)
        if self.alg == -257 and self.rsa_modulus is not None:
            return _verify_rs256(self.rsa_modulus,
                                 self.rsa_exponent or 0, digest, signature)
        if self.alg == -8 and self.okp_public is not None:
            return _verify_eddsa(self.okp_public, message, signature)
        return False


def parse_cose_key(data: bytes) -> CoseKey:
    value = cbor_decode(data)
    if not isinstance(value, dict):
        raise PasskeyError("malformed", "COSE key was not a map.")
    kty, alg = value.get(1), value.get(3)
    if kty == 2 and alg == -7:  # EC2 / ES256
        x, y = value.get(-2), value.get(-3)
        if value.get(-1) != 1 or not isinstance(x, bytes) \
                or not isinstance(y, bytes) or len(x) != 32 or len(y) != 32:
            raise PasskeyError("unsupported_key", "Only P-256 keys enrol.")
        return CoseKey(kty, alg, 1,
                       (int.from_bytes(x, "big"), int.from_bytes(y, "big")),
                       None, None, None)
    if kty == 3 and alg == -257:  # RSA / RS256
        n, e = value.get(-1), value.get(-2)
        if not isinstance(n, bytes) or not isinstance(e, bytes):
            raise PasskeyError("unsupported_key", "Malformed RSA key.")
        return CoseKey(kty, alg, None, None, int.from_bytes(n, "big"),
                       int.from_bytes(e, "big"), None)
    if kty == 1 and alg == -8:  # OKP / EdDSA
        x = value.get(-2)
        if value.get(-1) != 6 or not isinstance(x, bytes) or len(x) != 32:
            raise PasskeyError(
                "unsupported_key", "Only Ed25519 keys enrol.")
        return CoseKey(kty, alg, 6, None, None, None, x)
    raise PasskeyError(
        "unsupported_key",
        "Only ES256, RS256 and EdDSA passkeys are supported.")


# ------------------------------------------------------------------
# Authenticator data
# ------------------------------------------------------------------

@dataclass(frozen=True)
class AuthData:
    rp_id_hash: bytes
    user_present: bool
    user_verified: bool
    sign_count: int
    credential_id: bytes | None        # attested data, registration only
    cose_public_key: bytes | None


def parse_auth_data(raw: bytes, *, attested: bool) -> AuthData:
    if len(raw) < 37:
        raise PasskeyError("malformed", "Authenticator data too short.")
    rp_hash, flags = raw[:32], raw[32]
    sign_count = struct.unpack(">I", raw[33:37])[0]
    credential_id = cose = None
    if attested:
        if not flags & 0x40:
            raise PasskeyError(
                "malformed", "Registration carried no attested data.")
        if len(raw) < 55:
            raise PasskeyError("malformed", "Attested data truncated.")
        cred_len = struct.unpack(">H", raw[53:55])[0]
        start = 55 + cred_len
        if len(raw) < start:
            raise PasskeyError("malformed", "Credential id truncated.")
        credential_id = raw[55:start]
        # The COSE key is the remainder; measure it with the
        # reader so trailing garbage is refused, not ignored.
        reader = _CborReader(raw[start:])
        reader.read()
        if reader.pos != len(raw) - start:
            raise PasskeyError("malformed", "Trailing bytes in auth data.")
        cose = raw[start:]
    return AuthData(
        rp_id_hash=rp_hash, user_present=bool(flags & 0x01),
        user_verified=bool(flags & 0x04), sign_count=sign_count,
        credential_id=credential_id, cose_public_key=cose)


# ------------------------------------------------------------------
# The store
# ------------------------------------------------------------------

@dataclass(frozen=True)
class PasskeyCredential:
    id: int
    user_id: int
    credential_id: str      # base64url, the list-safe identifier
    nickname: str
    sign_count: int
    created_at: int
    last_used_at: int | None


@dataclass(frozen=True)
class AuthenticatedPasskey:
    user_id: int
    credential: PasskeyCredential


class PasskeyStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        reauth_verifier: Callable[[int], bool] | None = None,
        rp_id: str = "localhost",
        expected_origins: tuple[str, ...] = ("https://localhost",),
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._reauth = reauth_verifier
        self._rp_id = rp_id
        self._origins = frozenset(expected_origins)
        self._now = time_fn

    # -- challenges ------------------------------------------------
    def _issue_challenge(self, purpose: str,
                         user_id: int | None) -> str:
        raw = os.urandom(_CHALLENGE_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO passkey_challenges (challenge_hash, user_id,"
                " purpose, created_at, expires_at, used_at)"
                " VALUES (?, ?, ?, ?, ?, NULL)",
                (digest, user_id, purpose, now,
                 now + CHALLENGE_TTL_SECONDS))
        return b64url_encode(raw)

    def _consume_challenge(self, challenge: object, purpose: str,
                           user_id: int | None) -> None:
        """Single-use: the row is spent in the same breath that
        validates it, so a captured ceremony cannot be replayed
        even when its later checks fail."""
        raw = b64url_decode(challenge)
        digest = hashlib.sha256(raw).hexdigest()
        row = self._conn.execute(
            "SELECT * FROM passkey_challenges WHERE challenge_hash = ?",
            (digest,)).fetchone()
        now = int(self._now())
        if row is None or row["purpose"] != purpose \
                or row["used_at"] is not None or now >= row["expires_at"]:
            raise PasskeyError(
                "challenge_invalid",
                "That passkey ceremony has expired; start again.")
        if user_id is not None and row["user_id"] not in (None, user_id):
            raise PasskeyError(
                "challenge_invalid",
                "That passkey ceremony belongs to another account.")
        with self._conn:
            self._conn.execute(
                "UPDATE passkey_challenges SET used_at = ?"
                " WHERE id = ? AND used_at IS NULL",
                (now, row["id"]))

    # -- shared verification pieces ---------------------------------
    def _check_client_data(self, client_data_b64: object,
                           expected_type: str,
                           challenge: object) -> bytes:
        raw = b64url_decode(client_data_b64)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise PasskeyError(
                "malformed", "Client data was not JSON.") from None
        if not isinstance(data, dict) or data.get("type") != expected_type:
            raise PasskeyError(
                "ceremony_mismatch",
                "That response was for a different ceremony.")
        offered = data.get("challenge")
        if not isinstance(offered, str) or not constant_time_equal(
                offered, challenge if isinstance(challenge, str) else ""):
            raise PasskeyError(
                "challenge_invalid",
                "The response does not answer this challenge.")
        if data.get("origin") not in self._origins:
            raise PasskeyError(
                "origin_refused",
                "That origin is not this instance.")
        return hashlib.sha256(raw).digest()

    def _check_auth_data(self, auth_data_b64: object, *,
                         attested: bool) -> tuple[AuthData, bytes]:
        raw = b64url_decode(auth_data_b64)
        auth = parse_auth_data(raw, attested=attested)
        expected = hashlib.sha256(self._rp_id.encode("utf-8")).digest()
        if not constant_time_equal(auth.rp_id_hash, expected):
            raise PasskeyError(
                "rp_mismatch",
                "That passkey was made for a different site.")
        if not auth.user_present:
            raise PasskeyError(
                "user_absent",
                "The authenticator did not confirm your presence.")
        return auth, raw

    # -- registration -------------------------------------------------
    def begin_registration(self, user_id: int) -> str:
        """Issue the enrolment challenge. Step-up law: the
        re-auth seam must answer yes, first (fail-closed)."""
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise PasskeyError("no_such_user", "No such account.")
        if self._reauth is None or not self._reauth(user.id):
            raise PasskeyError(
                "sudo_required",
                "Adding a passkey needs a fresh password "
                "confirmation; confirm and try again.")
        return self._issue_challenge("register", user.id)

    def complete_registration(
        self,
        user_id: int,
        challenge: object,
        attestation_object_b64: object,
        client_data_b64: object,
        nickname: str = "Passkey",
        source_ip: str | None = None,
    ) -> PasskeyCredential:
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise PasskeyError("no_such_user", "No such account.")
        nickname = nickname.strip() if isinstance(nickname, str) else ""
        if not nickname or len(nickname) > 80:
            raise PasskeyError(
                "nickname_invalid",
                "Give the passkey a name of at most 80 characters.")
        self._consume_challenge(challenge, "register", user.id)
        client_hash = self._check_client_data(
            client_data_b64, "webauthn.create", challenge)
        attestation = cbor_decode(b64url_decode(attestation_object_b64))
        if not isinstance(attestation, dict):
            raise PasskeyError("malformed", "Attestation was not a map.")
        fmt = attestation.get("fmt")
        auth_data_raw = attestation.get("authData")
        att_stmt = attestation.get("attStmt")
        if not isinstance(auth_data_raw, bytes) \
                or not isinstance(att_stmt, dict):
            raise PasskeyError("malformed", "Attestation was incomplete.")
        auth, _ = self._check_auth_data(
            b64url_encode(auth_data_raw), attested=True)
        assert auth.credential_id is not None
        assert auth.cose_public_key is not None
        cose_key = parse_cose_key(auth.cose_public_key)
        if fmt == "none":
            if att_stmt:
                raise PasskeyError(
                    "attestation_mismatch",
                    "A 'none' attestation carrying a statement is "
                    "refused.")
        elif fmt == "packed":
            if "x5c" in att_stmt:
                raise PasskeyError(
                    "unsupported_attestation",
                    "Certificate-chain attestation is not accepted; "
                    "self-attestation or none only.")
            signature = att_stmt.get("sig")
            alg = att_stmt.get("alg")
            if not isinstance(signature, bytes) or alg != cose_key.alg:
                raise PasskeyError(
                    "attestation_mismatch",
                    "Packed attestation did not match its key.")
            message = auth_data_raw + client_hash
            if not cose_key.verify(
                    hashlib.sha256(message).digest(), message, signature):
                raise PasskeyError(
                    "attestation_mismatch",
                    "Packed attestation signature did not verify.")
        else:
            raise PasskeyError(
                "unsupported_attestation",
                "Only 'none' and self-attested 'packed' passkeys "
                "enrol on this instance.")
        credential_id = b64url_encode(auth.credential_id)
        existing = self._conn.execute(
            "SELECT id FROM passkey_credentials WHERE credential_id = ?",
            (credential_id,)).fetchone()
        if existing is not None:
            raise PasskeyError(
                "credential_taken",
                "That passkey is already enrolled on this instance.")
        now = int(self._now())
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO passkey_credentials (user_id,"
                " credential_id, public_key, sign_count, aaguid,"
                " nickname, created_at, last_used_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                (user.id, credential_id, auth.cose_public_key,
                 auth.sign_count,
                 auth_data_raw[37:53].hex(), nickname, now))
        cred = self._credential_by_id(int(cur.lastrowid))
        assert cred is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.passkey.add", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip,
                detail={"credential_id": credential_id,
                        "format": fmt})
        return cred

    # -- authentication -------------------------------------------------
    def begin_authentication(self, user_id: int | None = None) -> str:
        """Issue an assertion challenge. Bound to an account it
        serves as that account's second factor; unbound it is
        the passwordless door (the credential names the account)."""
        if user_id is not None and \
                self._accounts.get_by_id(user_id) is None:
            raise PasskeyError("no_such_user", "No such account.")
        return self._issue_challenge("assert", user_id)

    def complete_authentication(
        self,
        challenge: object,
        credential_id: object,
        authenticator_data_b64: object,
        client_data_b64: object,
        signature_b64: object,
        source_ip: str | None = None,
    ) -> AuthenticatedPasskey:
        if not isinstance(credential_id, str):
            raise PasskeyError("assertion_failed",
                               "That passkey sign-in did not verify.")
        row = self._conn.execute(
            "SELECT * FROM passkey_credentials WHERE credential_id = ?",
            (credential_id,)).fetchone()
        if row is None:
            raise PasskeyError("assertion_failed",
                               "That passkey sign-in did not verify.")
        self._consume_challenge(
            challenge, "assert", row["user_id"])
        client_hash = self._check_client_data(
            client_data_b64, "webauthn.get", challenge)
        auth, auth_raw = self._check_auth_data(
            authenticator_data_b64, attested=False)
        cose_key = parse_cose_key(bytes(row["public_key"]))
        signature = b64url_decode(signature_b64)
        message = auth_raw + client_hash
        if not cose_key.verify(
                hashlib.sha256(message).digest(), message, signature):
            raise PasskeyError("assertion_failed",
                               "That passkey sign-in did not verify.")
        stored_count = int(row["sign_count"])
        if (auth.sign_count or stored_count) \
                and auth.sign_count <= stored_count:
            raise PasskeyError(
                "cloned_authenticator",
                "That passkey's counter did not move forward; it "
                "may have been copied, and sign-in is refused.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE passkey_credentials SET sign_count = ?,"
                " last_used_at = ? WHERE id = ?",
                (auth.sign_count, now, row["id"]))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=row["user_id"],
                action="auth.passkey.login", target_kind="user",
                target_id=str(row["user_id"]), outcome="success",
                source_ip=source_ip,
                detail={"credential_id": credential_id})
        cred = self._credential_by_id(int(row["id"]))
        assert cred is not None
        return AuthenticatedPasskey(
            user_id=int(row["user_id"]), credential=cred)

    # -- management -------------------------------------------------
    def _credential_by_id(self, row_id: int) -> PasskeyCredential | None:
        row = self._conn.execute(
            "SELECT * FROM passkey_credentials WHERE id = ?",
            (row_id,)).fetchone()
        if row is None:
            return None
        return PasskeyCredential(
            id=row["id"], user_id=row["user_id"],
            credential_id=row["credential_id"], nickname=row["nickname"],
            sign_count=row["sign_count"], created_at=row["created_at"],
            last_used_at=row["last_used_at"])

    def list_for_user(self, user_id: int) -> list[PasskeyCredential]:
        rows = self._conn.execute(
            "SELECT id FROM passkey_credentials WHERE user_id = ?"
            " ORDER BY id", (user_id,)).fetchall()
        return [self._credential_by_id(r["id"]) for r in rows]  # type: ignore[misc]

    def has_passkeys(self, user_id: int) -> bool:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM passkey_credentials"
            " WHERE user_id = ?", (user_id,)).fetchone()
        return int(row["n"]) > 0

    def remove(self, user_id: int, credential_pk: int,
               source_ip: str | None = None) -> bool:
        """Owner-only removal, audited. True when a credential
        actually went away."""
        row = self._conn.execute(
            "SELECT * FROM passkey_credentials"
            " WHERE id = ? AND user_id = ?",
            (credential_pk, user_id)).fetchone()
        if row is None:
            return False
        with self._conn:
            self._conn.execute(
                "DELETE FROM passkey_credentials WHERE id = ?",
                (credential_pk,))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user_id,
                action="auth.passkey.remove", target_kind="user",
                target_id=str(user_id), outcome="success",
                source_ip=source_ip,
                detail={"credential_id": row["credential_id"]})
        return True
