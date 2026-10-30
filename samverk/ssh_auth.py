"""SSH key resolution (S-085).

The SSH door's identity question, from study 02's design:
*this fingerprint was presented — whose key is it?* The answer
is a principal or one uniform None:

- a **personal key** (S-030) resolves to its account, but only
  while that account's status is `active` — the S-081 law
  (deactivated accounts authenticate to nothing) applied to the
  SSH door unchanged;
- a **deploy key** (S-031) resolves to a deploy principal bound
  to exactly one repository; whether it may act on a given
  request is S-031's `authorize` question, asked per request by
  the transport (S-088), not pre-decided here;
- everything else — unknown fingerprint, malformed input, a key
  whose account is gone or not active — resolves to None, and
  no caller can tell the refusals apart. sshd turns None into
  its generic publickey denial; there is no user enumeration.

A fingerprint can never be both a personal and a deploy key
(registration refuses the overlap in both stores), so resolution
order cannot create ambiguity; personal is checked first only
because it is the common case.

Lookups are cached **briefly**: `CACHE_TTL_SECONDS` with a
bounded size, inside this resolver, disableable by passing
`cache_ttl=0`. The bound is the revocation law from study 02 —
a deleted key stops resolving within the TTL — and the cache
stores refusals too, so a scan of random fingerprints does not
become a database amplification tool. The cache is per-process
and per-resolver; AuthorizedKeysCommand processes are
short-lived, so their effective cache is the process lifetime.

This module also emits the one `authorized_keys` line sshd
needs (`authorized_keys_line`): the stored key verbatim, behind
`restrict` and a forced `ssh-serve` command carrying the
principal's identity as integer ids — never names a client
supplied. Unknown fingerprints emit nothing at all.
"""

from __future__ import annotations

import sqlite3
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable

from .accounts import AccountStore, User
from .deploy_keys import DeployKey, DeployKeyStore
from .ssh_keys import SshKey, SshKeyStore

CACHE_TTL_SECONDS = 5.0
CACHE_MAX_ENTRIES = 256


@dataclass(frozen=True)
class SshPrincipal:
    """Who a presented SSH key authenticates as."""

    kind: str                       # "account" | "deploy_key"
    fingerprint: str
    user: User | None = None        # account principals only
    ssh_key: SshKey | None = None   # account principals only
    deploy_key: DeployKey | None = None  # deploy principals only

    @property
    def account_id(self) -> int | None:
        return self.user.id if self.user is not None else None


class SshKeyResolver:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        *,
        cache_ttl: float = CACHE_TTL_SECONDS,
        cache_max: int = CACHE_MAX_ENTRIES,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._ssh_keys = SshKeyStore(conn, accounts)
        self._deploy_keys = DeployKeyStore(conn, accounts)
        self._ttl = max(0.0, float(cache_ttl))
        self._cache_max = max(1, int(cache_max))
        self._now = time_fn
        self._cache: OrderedDict[str, tuple[float, SshPrincipal | None]] = \
            OrderedDict()

    # -- resolution -------------------------------------------------

    def resolve(self, fingerprint: object) -> SshPrincipal | None:
        """The principal for *fingerprint*, or None — one None
        for every refusal (unknown, malformed, dead account)."""
        if not isinstance(fingerprint, str) \
                or not fingerprint.startswith("SHA256:") \
                or len(fingerprint) < len("SHA256:") + 8:
            return None
        now = self._now()
        if self._ttl > 0:
            hit = self._cache.get(fingerprint)
            if hit is not None:
                expires, principal = hit
                if now < expires:
                    self._cache.move_to_end(fingerprint)
                    return principal
                del self._cache[fingerprint]
        principal = self._resolve_uncached(fingerprint)
        if self._ttl > 0:
            self._cache[fingerprint] = (now + self._ttl, principal)
            while len(self._cache) > self._cache_max:
                self._cache.popitem(last=False)
        return principal

    def _resolve_uncached(self, fingerprint: str) -> SshPrincipal | None:
        key = self._ssh_keys.find_by_fingerprint(fingerprint)
        if key is not None:
            user = self._accounts.get_by_id(key.user_id)
            if user is None or user.status != "active":
                return None
            return SshPrincipal(
                kind="account", fingerprint=fingerprint,
                user=user, ssh_key=key)
        row = self._conn.execute(
            "SELECT id FROM deploy_keys WHERE fingerprint = ?",
            (fingerprint,)).fetchone()
        if row is not None:
            deploy = self._deploy_keys.get_key(int(row["id"]))
            if deploy is not None:
                return SshPrincipal(
                    kind="deploy_key", fingerprint=fingerprint,
                    deploy_key=deploy)
        return None

    def invalidate(self, fingerprint: str | None = None) -> None:
        """Drop one cached answer, or the whole cache — called
        by key-management paths that cannot wait out the TTL."""
        if fingerprint is None:
            self._cache.clear()
        else:
            self._cache.pop(fingerprint, None)

    # -- authorized_keys emission -----------------------------------

    def _key_blob(self, principal: SshPrincipal) -> tuple[str, str] | None:
        table = "ssh_keys" if principal.kind == "account" else "deploy_keys"
        row = self._conn.execute(
            f"SELECT key_type, key_blob FROM {table}"
            " WHERE fingerprint = ?",
            (principal.fingerprint,)).fetchone()
        if row is None:
            return None
        return row["key_type"], row["key_blob"]

    def authorized_keys_line(
        self, fingerprint: object, *, serve_prefix: str = "samverk",
    ) -> str | None:
        """The single forced-command `authorized_keys` line for
        a presented key, or None when the key does not
        authenticate here (sshd prints nothing, denies generically).

        *serve_prefix* is operator configuration (the absolute
        path of the samverk entry point on this host); it must be
        one shell-safe token — anything else is a configuration
        error, raised, not a refusal."""
        if not serve_prefix or any(
                c in serve_prefix for c in '"\\\n\r \t'):
            raise ValueError("serve_prefix must be one safe token")
        principal = self.resolve(fingerprint)
        if principal is None:
            return None
        blob = self._key_blob(principal)
        if blob is None:
            return None
        key_type, key_blob = blob
        if principal.kind == "account":
            assert principal.user is not None and principal.ssh_key
            identity = (f"--account {principal.user.id}"
                        f" --key-id {principal.ssh_key.id}")
        else:
            assert principal.deploy_key is not None
            dk = principal.deploy_key
            identity = (f"--deploy-key {dk.id}"
                        f" --bound {dk.owner}/{dk.repo}")
        command = (f"{serve_prefix} ssh-serve {identity}"
                   f" --fingerprint {principal.fingerprint}")
        return (f'restrict,command="{command}"'
                f" {key_type} {key_blob} samverk-ssh")
