"""Identity linking over the seam (S-362).

Built on the frozen S-361 contract and S-045's shape: a
Samtal principal links to a Samverk account by mutual
proof — a signed token exchange — and unlinking is one
click on either side.

The exchange: Samtal mints a short-lived assertion token
(claims judged by S-361's validate_link_assertion) signed
with the seam's shared HMAC secret (S-249's road: HMAC-
SHA256 over the exact claim bytes). Samverk verifies the
signature in constant time, judges the claims (audience,
consent, lifetime, replay by nonce), and only then writes
the S-045 link. A token confers nothing else: it is not a
session, not a login, and Git transports never see it
(S-363 builds sign-on separately, on this link).

Mutual means mutual: Samverk's side of the proof is the
signed-in account holder initiating or confirming the link
(the caller passes the acting account; the service refuses
to link an account to a principal whose assertion names a
different consent), and Samtal's side is the signed
assertion itself. Unlink is one action from either side:
the account holder unlinks in Samverk, or Samtal asks for
its principal to be unlinked — both land on the same
S-045 unlink and its audit verb.

The seam must be enabled (S-361: disabled by default) or
every door here refuses seam_disabled. Used nonces are
remembered by the service instance; a deployment that
restarts inside an assertion's 300-second life should
share the nonce set — named honestly: this slice keeps it
in-process, and the lifetime cap bounds the exposure.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable

from .identity_linking import IdentityLinkStore
from .seam_contract import SeamContractError, seam_enabled, validate_link_assertion


class SeamIdentityError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def mint_link_token(secret: bytes, *, principal: str, now: int,
                    nonce: str, ttl_seconds: int = 300) -> str:
    """Samtal's side of the proof: a signed assertion token."""
    claims = {"provider": "samtal", "audience": "samverk", "consent": True,
              "principal": principal, "issued_at": int(now),
              "expires_at": int(now) + int(ttl_seconds), "nonce": nonce}
    body = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return _b64(body) + "." + sig


class SeamIdentityService:
    def __init__(self, links: IdentityLinkStore, *, secret: bytes,
                 settings: dict | None = None,
                 time_fn: Callable[[], float] = time.time):
        self._links = links
        self._secret = secret
        self._settings = settings
        self._now = time_fn
        self._seen_nonces: set = set()

    def _require_enabled(self):
        if not seam_enabled(self._settings):
            raise SeamIdentityError("seam_disabled", "The Samtal seam is not enabled.")

    def complete_link(self, user_id: int, token: object, *, source_ip: str | None = None):
        """Verify Samtal's signed assertion and write the link."""
        self._require_enabled()
        if not isinstance(token, str) or token.count(".") != 1:
            raise SeamIdentityError("token_invalid", "That link token is not well-formed.")
        body_b64, sig = token.split(".")
        try:
            body = _unb64(body_b64)
            claims = json.loads(body)
        except Exception:
            raise SeamIdentityError("token_invalid", "That link token is not well-formed.") from None
        expected = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise SeamIdentityError("signature_invalid", "The link token signature does not verify.")
        try:
            clean = validate_link_assertion(claims, now=int(self._now()), seen_nonces=self._seen_nonces)
        except SeamContractError as exc:
            raise SeamIdentityError(exc.reason, str(exc)) from None
        link = self._links.link(user_id, "samtal", clean["principal"], source_ip=source_ip)
        self._seen_nonces.add(clean["nonce"])
        return link

    def unlink_from_samverk(self, user_id: int, *, source_ip: str | None = None) -> bool:
        """One click on the Samverk side."""
        self._require_enabled()
        return self._links.unlink(user_id, "samtal", source_ip=source_ip)

    def unlink_from_samtal(self, principal: str, *, source_ip: str | None = None) -> bool:
        """One click on the Samtal side: resolve and unlink."""
        self._require_enabled()
        user_id = self._links.resolve("samtal", principal)
        if user_id is None:
            return False
        return self._links.unlink(user_id, "samtal", source_ip=source_ip)
