"""HTTP Basic credentials for the git transport (S-081).

Git clients speak HTTP Basic: the account name in the username
slot, a credential in the password slot. This module resolves
that header to an account — or to nothing. It creates no
session (a transport request is stateless; S-006's sessions
belong to browsers), and it applies no login throttle (bulk
git traffic is S-011 rate-limit territory, not the interactive
login door's failure backoff).

The password road (S-081):

- Verification is S-004's `verify_and_upgrade`, against the
  account's stored hash — or against the login door's decoy
  hash when the account does not exist, so the work done does
  not reveal whether the name is real (the S-027 timing law,
  reused, not reinvented).
- **Deactivated accounts authenticate to nothing.** Any status
  other than `active` (suspended, pending, deleted-in-waiting)
  refuses, indistinguishably from a wrong password: a caller
  with a dead account learns nothing about which part failed.
- A successful verify against a legacy hash upgrades it in
  place, exactly as the login door does.
- Malformed headers — not Basic, bad base64, no colon, empty
  name — resolve to None, never to an error that describes
  the header back to its sender.

The token road (S-082): a personal access token in the
password slot works like the password it replaces, *scoped* —
classic tokens (S-032) by their repo scopes, fine-grained
tokens (S-033) by their per-repository contents permissions.
`authorize_basic` is the scoped question the transport asks;
`authenticate_basic` remains the identity-only one.
"""

from __future__ import annotations

import base64
import binascii
import sqlite3

from .access_tokens import (
    TOKEN_PREFIX as CLASSIC_PREFIX,
    AccessTokenStore,
    token_allows,
)
from .accounts import AccountStore, User
from .fine_grained_tokens import (
    TOKEN_PREFIX as FINE_PREFIX,
    FineTokenStore,
)
from .login import _DECOY_HASH
from .passwords import verify_and_upgrade

TOKEN_USERNAME = "x-access-token"


def _is_token_shaped(credential: str) -> bool:
    return credential.startswith((CLASSIC_PREFIX, FINE_PREFIX))


def parse_basic_credentials(header: object) -> tuple[str, str] | None:
    """(username, credential) from an `Authorization: Basic …`
    header, or None for anything malformed. The password slot
    may itself contain colons (split on the first only)."""
    if not isinstance(header, str):
        return None
    scheme, _, payload = header.partition(" ")
    if scheme.lower() != "basic" or not payload:
        return None
    try:
        raw = base64.b64decode(payload.strip(), validate=True)
        text = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    username, sep, credential = text.partition(":")
    if not sep or not username:
        return None
    return username, credential


class GitAuthenticator:
    def __init__(self, conn: sqlite3.Connection, accounts: AccountStore):
        self._conn = conn
        self._accounts = accounts
        self._classic = AccessTokenStore(conn, accounts)
        self._fine = FineTokenStore(conn, accounts)

    def authenticate_basic(self, header: object) -> User | None:
        """Resolve a Basic header to its account, or None —
        every failure shape (unknown name, wrong password,
        deactivated account, malformed header) answers the
        same None. A token-shaped credential (S-082) resolves
        through its token store instead of the password road."""
        parsed = parse_basic_credentials(header)
        if parsed is None:
            return None
        username, credential = parsed
        if _is_token_shaped(credential):
            resolved = self._resolve_token(username, credential)
            return resolved[0] if resolved else None
        return self._authenticate_password(username, credential)

    # -- S-082: token-as-password ----------------------------------

    def _resolve_token(self, username: str, presented: str):
        """(user, kind) for a live token whose username slot is
        lawful — the token owner's own name, or the conventional
        `x-access-token` — else None. A token belonging to a
        deactivated account resolves to nothing, like its
        owner's password does."""
        if presented.startswith(FINE_PREFIX):
            token = self._fine.authenticate(presented)
            kind = "fine"
        else:
            token = self._classic.authenticate(presented)
            kind = "classic"
        if token is None:
            return None
        user = self._accounts.get_by_id(token.user_id)
        if user is None or user.status != "active":
            return None
        if username.lower() not in (user.username_lower, TOKEN_USERNAME):
            return None
        return user, kind, token

    def authorize_basic(self, header: object, owner: object,
                        repo: object, minimum: str) -> User | None:
        """The transport question: the account this header may
        act as *on this repository* at *minimum* ('read' or
        'write'), or None.

        Password credentials answer with the account itself —
        the repository permission check is S-054's, applied by
        the transport service as usual. Token credentials must
        additionally carry the scope for the operation: a
        classic token needs `repo:read` / `repo:write`
        (S-032's implication law decides), a fine-grained
        token needs `contents:read` / `contents:write` on
        exactly this repository (S-033's `authorize` decides).
        A read-only token in a push's password slot is refused
        here, before any pack byte moves.
        """
        parsed = parse_basic_credentials(header)
        if parsed is None:
            return None
        username, credential = parsed
        if not _is_token_shaped(credential):
            return self._authenticate_password(username, credential)
        resolved = self._resolve_token(username, credential)
        if resolved is None:
            return None
        user, kind, token = resolved
        if kind == "classic":
            scope = "repo:write" if minimum == "write" else "repo:read"
            return user if token_allows(token, scope) else None
        permission = ("contents:write" if minimum == "write"
                      else "contents:read")
        allowed = self._fine.authorize(credential, owner, repo, permission)
        return user if allowed is not None else None

    def _authenticate_password(self, username: str,
                               credential: str) -> User | None:
        user = self._accounts.get_by_username(username)
        stored = (self._accounts.password_hash_for(user.id)
                  if user is not None else _DECOY_HASH)
        ok, upgrade = verify_and_upgrade(credential, stored or _DECOY_HASH)
        if user is None or not ok:
            return None
        if user.status != "active":
            return None
        if upgrade is not None:
            self._accounts.set_password_hash(user.id, upgrade)
        return user
