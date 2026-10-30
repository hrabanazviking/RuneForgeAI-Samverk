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
"""

from __future__ import annotations

import base64
import binascii
import sqlite3

from .accounts import AccountStore, User
from .login import _DECOY_HASH
from .passwords import verify_and_upgrade


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

    def authenticate_basic(self, header: object) -> User | None:
        """Resolve a Basic header to its account via the
        password road, or None — every failure shape (unknown
        name, wrong password, deactivated account, malformed
        header) answers the same None."""
        parsed = parse_basic_credentials(header)
        if parsed is None:
            return None
        username, credential = parsed
        return self._authenticate_password(username, credential)

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
