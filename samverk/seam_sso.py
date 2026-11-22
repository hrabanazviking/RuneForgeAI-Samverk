"""Single sign-on over the seam (S-363).

A signed-in Samtal session may enter Samverk without a
second password, via short-lived exchange tokens — and
Samverk's own login remains, whole, for standalone use.

The road: for a principal holding a standing S-362 link,
Samtal mints an exchange token (signed assertion, S-361
contract shape, audience 'samverk', purpose 'sso', life
at most 120 seconds, single-use nonce). Samverk's
SeamSsoService verifies it exactly as S-362 verifies link
tokens, resolves the principal through the S-045 link,
refuses when no link stands (link_required — SSO never
creates accounts or links implicitly), and mints a
*real* Samverk session through the standing SessionStore
— the same session machinery, the same revocation, the
same audit shape as a password login, with the device
label naming the seam so the holder can see and revoke
it in their session list.

Guards: the seam must be enabled; the account must be
active (a suspended or pending account is refused with
the login road's own posture — the seam is never a way
around an account state); the token is single-use.
Nothing here weakens the standalone door: with the seam
disabled or Samtal dead, password login is untouched.
"""
from __future__ import annotations

import base64, hashlib, hmac, json, time
from collections.abc import Callable

from .accounts import AccountStore
from .identity_linking import IdentityLinkStore
from .seam_contract import seam_enabled
from .sessions import SessionStore

SSO_TOKEN_MAX_AGE_SECONDS = 120
SSO_AUDIENCE = "samverk"
SSO_DEVICE_LABEL = "Samtal seam (SSO)"


class SeamSsoError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def mint_sso_token(secret: bytes, *, principal: str, now: int, nonce: str,
                   ttl_seconds: int = SSO_TOKEN_MAX_AGE_SECONDS) -> str:
    claims = {"provider": "samtal", "audience": SSO_AUDIENCE, "purpose": "sso",
              "principal": principal, "issued_at": int(now),
              "expires_at": int(now) + int(ttl_seconds), "nonce": nonce}
    body = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return _b64(body) + "." + sig


class SeamSsoService:
    def __init__(self, links: IdentityLinkStore, accounts: AccountStore,
                 sessions: SessionStore, *, secret: bytes,
                 settings: dict | None = None,
                 time_fn: Callable[[], float] = time.time):
        self._links = links; self._accounts = accounts; self._sessions = sessions
        self._secret = secret; self._settings = settings; self._now = time_fn
        self._seen_nonces: set = set()

    def exchange(self, token: object, *, source_ip: str | None = None) -> str:
        """Trade a Samtal exchange token for a Samverk session token."""
        if not seam_enabled(self._settings):
            raise SeamSsoError("seam_disabled", "The Samtal seam is not enabled.")
        if not isinstance(token, str) or token.count(".") != 1:
            raise SeamSsoError("token_invalid", "That exchange token is not well-formed.")
        body_b64, sig = token.split(".")
        try:
            body = _unb64(body_b64); claims = json.loads(body)
        except Exception:
            raise SeamSsoError("token_invalid", "That exchange token is not well-formed.") from None
        expected = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise SeamSsoError("signature_invalid", "The exchange token signature does not verify.")
        if claims.get("provider") != "samtal" or claims.get("audience") != SSO_AUDIENCE or claims.get("purpose") != "sso":
            raise SeamSsoError("claim_mismatch", "That token was not issued for Samverk sign-on.")
        now = int(self._now()); exp = claims.get("expires_at"); iat = claims.get("issued_at")
        nonce = claims.get("nonce"); principal = claims.get("principal")
        if not isinstance(exp, int) or not isinstance(iat, int) or not nonce or not principal:
            raise SeamSsoError("claim_incomplete", "Exchange token lacks required claims.")
        if exp < iat or exp - iat > SSO_TOKEN_MAX_AGE_SECONDS or now > exp:
            raise SeamSsoError("assertion_expired", "Exchange token is expired or over-long.")
        if nonce in self._seen_nonces:
            raise SeamSsoError("assertion_replay", "Exchange token already used.")
        user_id = self._links.resolve("samtal", str(principal))
        if user_id is None:
            raise SeamSsoError("link_required", "No Samverk account is linked to that principal.")
        account = self._accounts.get_by_id(user_id)
        if account is None or getattr(account, "status", "active") != "active":
            raise SeamSsoError("account_not_active", "That account cannot sign in.")
        self._seen_nonces.add(str(nonce))
        session = self._sessions.create(user_id, device_label=SSO_DEVICE_LABEL, source_ip=source_ip)
        return session.token if hasattr(session, "token") else str(session)
