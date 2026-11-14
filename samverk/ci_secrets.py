"""CI secrets (S-319) -- per-repo and per-org
secrets, encrypted at rest under the instance
keys, injected as env, masked in logs.

S-316's assignment carries environment *names*,
never values, and said values would travel this
slice's road. S-317 registered the runners that
poll for work, S-318 built the reference runner
that executes it under environment discipline.
This slice is the values' road -- the store a
workflow's secrets live in, the decryption a
dispatch performs, and the masking a log line
passes through:

- **Two scopes, one law.** A CI secret belongs
  to exactly one **organization** or one
  **repository** -- named as S-317 names its
  targets (the org's lowercase name, the repo's
  lowercase ``owner/name``), judged by the same
  ``validate_target``. There is no instance
  scope here: a secret always has an owner a
  steward can be named for. Names are
  environment names, canonical uppercase (the
  S-003 shape): a letter or underscore, then
  letters, digits and underscores. The reserved
  ``SAMVERK_`` prefix (the runner's own context
  variables, S-318) and S-318's env denylist
  (``LD_PRELOAD`` and kin, the ``GIT_CONFIG``
  family) are refused in any position -- a
  secret is injected as env, so a secret may
  never be named as a code-loading redirect.
- **Encrypted at rest under instance keys.**
  A value is stored only as ciphertext:
  ``v1:<base64 nonce+tag+ciphertext>``, an
  HMAC-SHA256 keystream (S-035's cipher shape)
  keyed by a caller-supplied 256-bit instance
  key, with a fresh random nonce per value and
  an HMAC-SHA256 tag over nonce and ciphertext
  -- so a tampered row, or a row read under the
  wrong key, fails closed as
  ``ci_secret_unreadable`` and never decrypts
  to garbage. The instance key itself is
  custodied per S-003 (env or a mode-600 file,
  in memory only); it is never in the database,
  so a stolen database holds no usable secret
  (the battery sweeps the DB file for a seeded
  plaintext and finds none). With **no key
  supplied, setting and resolving refuse**
  (``encryption_unavailable``): fail-closed,
  like every other Samverk seam. Listing and
  deleting metadata need no key -- a steward
  can always see *which* secrets stand and
  withdraw one.
- **Stewards guard each scope.** Setting,
  listing and deleting are steward acts,
  guarded exactly as S-317 guards its tokens:
  a site admin, or the organization's **owner**
  (S-186), for an org; a site admin or a viewer
  holding the **admin** rung on the repository
  (S-054 / S-190) for a repo. Anyone else is
  refused ``ci_secret_not_permitted`` -- except
  a stranger to a private repository, who gets
  the uniform ``repo_not_found``. Setting a
  standing name replaces its value in place
  (the row, its creation stamp and its creator
  stand; the value and the update stamp move).
- **Injected as env at dispatch.**
  ``resolve_env`` is the forge's own act when
  it hands a job to a runner: for one
  repository it returns the decrypted mapping
  the runner's ``env_names`` will carry -- the
  owning organization's secrets first, the
  repository's own secrets laid over them, so
  a repo secret of the same name wins over its
  org's. The org of a repo is its owner when
  that owner is an organization; a user-owned
  repo receives only its own secrets. The
  mapping is the *only* road a value leaves
  this module by: no listing, page or dict
  ever carries one, and ``repr`` never does.
- **Masked in logs, S-018's filter reused.**
  ``mask_text`` is S-018's own ``redact_text``
  with the secret values handed to it as
  ``extra_secrets``: a value that reaches a log
  line anyway is struck whole and replaced by
  the visible ``[REDACTED]`` marker, beside
  S-018's standing scheme, header and
  sensitive-key layers. The store's
  ``redact_for_repo`` / ``redact_for_scope``
  resolve the standing values and mask with
  exactly them -- masking is this slice's
  second half, not a promise about callers.
- **Witnessed, values never.** Setting and
  deleting ride the standing scoped verbs, as
  S-317's acts do -- an org rides
  ``auth.organization.update``, a repo rides
  ``repo.settings.change`` -- each detail
  naming the act under ``key`` (``ci_secret.set``
  / ``ci_secret.delete``) with the scope, target
  and secret *name*, never a value, never
  ciphertext. No new taxonomy event: 135 stand
  (33 auth / 89 repo / 13 admin).

Storage is migration 130 (schema 129 -> 130):
``ci_secrets`` -- one row per (scope, target,
name), ciphertext only.

Honest limits, stated plainly: this slice
stores, resolves and masks; it dispatches no
job (S-320's scheduler hands ``resolve_env``'s
mapping to a runner under S-316/S-318's law)
and renders no routed page -- the pages here
are render functions in the house shape, and
the web layer that routes them is the
instance's own (S-382 owns the nav shell).
Key rotation is the operator's road: values
are re-set under the new key; this module
keeps no old key and pretends no migration.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import sqlite3
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text
from .log_redaction import redact_text
from .organization_members import OrgMembershipStore
from .organizations import OrganizationStore
from .permissions import role_for
from .reference_runner import ENV_DENYLIST
from .repositories import RepositoryStore
from .runner_registration import (
    RunnerRegistrationError, validate_target)

__all__ = [
    "MAX_SECRET_VALUE_CHARS", "SECRET_AREAS",
    "SECRET_SCOPES", "SECRETS_HOME_PATH",
    "CISecret", "CISecretsAudit", "CISecretsError",
    "CISecretsStore", "audit_ci_secrets",
    "ci_secret_areas", "decrypt_value",
    "encrypt_value", "mask_text", "render_secrets_home",
    "render_secrets_page", "secret_to_dict",
    "secrets_page_path", "validate_scope",
    "validate_secret_name", "validate_secret_value",
]

#: The scopes a CI secret may live at: an
#: organization (shared by its repositories) or
#: one repository. Deliberately narrower than
#: S-317's runner scopes -- a secret always has
#: a steward who can be named.
SECRET_SCOPES = ("org", "repo")

SECRETS_HOME_PATH = "/settings/secrets"

#: A secret value's bound: GitHub's 48 KB shape,
#: in characters -- a CI secret is a credential,
#: not a file.
MAX_SECRET_VALUE_CHARS = 49152

_KEY_BYTES = 32
_NONCE_BYTES = 16
_TAG_CONTEXT = b"samverk/ci-secret/v1\x00"

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_PREFIX = "SAMVERK_"

# The secret areas, in the order a steward looks
# for them: (scope, title, plain description,
# path template) -- the findability map as data,
# in S-317's shape. ``{target}`` in a template is
# the scope's canonical target.
SECRET_AREAS = (
    ("org", "Organization secrets",
     "Secrets shared by one organization's "
     "repositories. The organization's owners "
     "govern them here.",
     "/orgs/{target}/settings/secrets"),
    ("repo", "Repository secrets",
     "Secrets belonging to one repository. The "
     "repository's admins govern them here.",
     "/{target}/settings/secrets"),
)


class CISecretsError(ValueError):
    """One refused CI-secret act: a
    machine-branchable reason with its human
    detail, in the house shape."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# ------------------------------------------------------------------
# Pure law: scopes, targets, names, values.
# ------------------------------------------------------------------

def validate_scope(scope: object) -> str:
    """Pure: one of this slice's two scopes, or
    refused ``ci_secret_scope_unknown`` in
    words."""
    if not isinstance(scope, str) or scope not in SECRET_SCOPES:
        raise CISecretsError(
            "ci_secret_scope_unknown",
            "Secret scope: one of "
            + ", ".join(SECRET_SCOPES) + ".")
    return scope


def _canonical_target(scope: str, target: object) -> str:
    """Pure: the canonical stored target for one
    already-checked scope, judged by S-317's own
    target law; its refusal is re-spelt in this
    slice's reason."""
    try:
        return validate_target(scope, target)
    except RunnerRegistrationError as exc:
        raise CISecretsError(
            "ci_secret_target_invalid", str(exc)) from None


def validate_secret_name(name: object) -> str:
    """Pure: one secret's canonical name -- an
    environment name (a letter or underscore,
    then letters, digits and underscores),
    stored uppercase as S-003's names are.
    Refusals in words: ``ci_secret_name_invalid``
    for a shapeless name, ``ci_secret_name_reserved``
    for the runner's own ``SAMVERK_`` prefix,
    ``ci_secret_name_refused`` for a name on
    S-318's env denylist -- a secret is injected
    as env, so it may never be named as a
    code-loading or repository redirect."""
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise CISecretsError(
            "ci_secret_name_invalid",
            "Secret name: a letter or underscore, "
            "then letters, digits and underscores "
            "-- the name an environment variable "
            "carries.")
    canonical = name.upper()
    if canonical.startswith(_RESERVED_PREFIX):
        raise CISecretsError(
            "ci_secret_name_reserved",
            f"Secret name {canonical} begins with "
            f"{_RESERVED_PREFIX}, the runner's own "
            "context prefix (S-318); a secret may "
            "not take the runner's name.")
    if canonical in ENV_DENYLIST or canonical.startswith("GIT_CONFIG"):
        raise CISecretsError(
            "ci_secret_name_refused",
            f"Secret name {canonical} is refused -- "
            "it redirects code loading, the shell "
            "itself or another program's repository "
            "(S-318's denylist), and a secret is "
            "injected as env.")
    return canonical


def validate_secret_value(value: object) -> str:
    """Pure: one secret's value -- non-empty
    text of at most ``MAX_SECRET_VALUE_CHARS``
    characters, with no NUL byte (an environment
    value cannot carry one). Refused
    ``ci_secret_value_invalid`` in words."""
    if not isinstance(value, str) or not value:
        raise CISecretsError(
            "ci_secret_value_invalid",
            "Secret value: text -- a secret with "
            "no value is a deletion, not a set.")
    if "\x00" in value or len(value) > MAX_SECRET_VALUE_CHARS:
        raise CISecretsError(
            "ci_secret_value_invalid",
            f"Secret value: text of at most "
            f"{MAX_SECRET_VALUE_CHARS} characters, "
            "with no NUL byte.")
    return value


# ------------------------------------------------------------------
# The cipher: encrypted at rest under instance keys.
# ------------------------------------------------------------------

def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    block = 0
    while len(out) < length:
        out.extend(hmac.new(
            key, nonce + struct.pack(">I", block), hashlib.sha256
        ).digest())
        block += 1
    return bytes(out[:length])


def encrypt_value(key: bytes, plaintext: str) -> str:
    """Encrypt one value under the instance key:
    a fresh random nonce, an HMAC-SHA256
    keystream (S-035's cipher shape), and an
    HMAC-SHA256 tag over context, nonce and
    ciphertext, stored as
    ``v1:<base64 nonce+tag+ciphertext>``."""
    nonce = os.urandom(_NONCE_BYTES)
    data = plaintext.encode("utf-8")
    stream = _keystream(key, nonce, len(data))
    cipher = bytes(a ^ b for a, b in zip(data, stream))
    tag = hmac.new(
        key, _TAG_CONTEXT + nonce + cipher, hashlib.sha256
    ).digest()
    return "v1:" + base64.b64encode(
        nonce + tag + cipher).decode("ascii")


def decrypt_value(key: bytes, stored: str) -> str:
    """Decrypt one stored value, verifying its
    tag first: a tampered row, a truncated row
    or the wrong key is refused
    ``ci_secret_unreadable`` in words and never
    decrypts to garbage."""
    if not isinstance(stored, str) or not stored.startswith("v1:"):
        raise CISecretsError(
            "ci_secret_unreadable",
            "The stored secret is unreadable.")
    try:
        blob = base64.b64decode(stored[3:], validate=True)
    except ValueError:
        raise CISecretsError(
            "ci_secret_unreadable",
            "The stored secret is unreadable.") from None
    if len(blob) < _NONCE_BYTES + 32:
        raise CISecretsError(
            "ci_secret_unreadable",
            "The stored secret is unreadable.")
    nonce = blob[:_NONCE_BYTES]
    tag = blob[_NONCE_BYTES:_NONCE_BYTES + 32]
    cipher = blob[_NONCE_BYTES + 32:]
    expected = hmac.new(
        key, _TAG_CONTEXT + nonce + cipher, hashlib.sha256
    ).digest()
    if not hmac.compare_digest(tag, expected):
        raise CISecretsError(
            "ci_secret_unreadable",
            "The stored secret is unreadable -- "
            "its seal does not verify under this "
            "instance key.")
    stream = _keystream(key, nonce, len(cipher))
    try:
        return bytes(
            a ^ b for a, b in zip(cipher, stream)).decode("utf-8")
    except UnicodeDecodeError:
        raise CISecretsError(
            "ci_secret_unreadable",
            "The stored secret is unreadable.") from None


def mask_text(text: str, values: tuple | list = ()) -> str:
    """Mask one log text: S-018's own filter
    (``redact_text``) with the given secret
    values handed to it as extra secrets, so a
    value is struck whole wherever it appears,
    beside S-018's standing scheme, header and
    sensitive-key layers."""
    return redact_text(text, extra_secrets=tuple(values))


# ------------------------------------------------------------------
# The secret's public facts.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class CISecret:
    """One CI secret's public facts: its scope,
    target and name, its creator and its stamps.
    The value and its ciphertext are deliberately
    NOT fields here -- the value is returned by
    no read, and the ciphertext never leaves the
    store."""
    id: int
    scope: str
    target: str
    name: str
    created_by: int
    created_at: int
    updated_at: int

    @property
    def target_words(self) -> str:
        return self.target


def secret_to_dict(secret: CISecret) -> dict:
    """The secret's programmatic face: its public
    facts only -- never a value, never
    ciphertext."""
    return {
        "id": secret.id, "scope": secret.scope,
        "target": secret.target, "name": secret.name,
        "created_by": secret.created_by,
        "created_at": secret.created_at,
        "updated_at": secret.updated_at,
    }


def ci_secret_areas() -> list[dict]:
    """The findability map as data: every secret
    area, in order, with its plain description
    and path template. The home renders exactly
    this."""
    return [
        {"scope": scope, "title": title,
         "description": desc, "path_template": path}
        for scope, title, desc, path in SECRET_AREAS]


def secrets_page_path(scope: object, target: object = "") -> str:
    """Pure: the one path of one scope's secrets
    page -- the address the findability walk
    walks to. The target is judged through the
    target law first, so a shapeless target has
    no page."""
    checked = validate_scope(scope)
    canonical = _canonical_target(checked, target)
    for area_scope, _title, _desc, template in SECRET_AREAS:
        if area_scope == checked:
            return template.replace("{target}", canonical)
    raise AssertionError("scope without an area")  # unreachable


def _row_to_secret(row: sqlite3.Row) -> CISecret:
    return CISecret(
        id=row["id"], scope=row["scope"], target=row["target"],
        name=row["name"], created_by=row["created_by"],
        created_at=row["created_at"], updated_at=row["updated_at"])


# ------------------------------------------------------------------
# The store.
# ------------------------------------------------------------------

class CISecretsStore:
    """The CI secrets store: setting, listing,
    deleting, resolving and masking over
    migration 130's table, guarded per scope,
    encrypted under the instance key, and
    witnessed on the standing verbs."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        repos: RepositoryStore,
        audit: AuditLog | None = None,
        encryption_key: bytes | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._repos = repos
        self._audit = audit
        self._key = encryption_key
        self._now = time_fn
        self._orgs = OrganizationStore(
            conn, accounts, audit=audit, time_fn=time_fn)
        self._members = OrgMembershipStore(
            conn, accounts, audit=audit, time_fn=time_fn)

    # -- guards ------------------------------------

    def _require_key(self) -> bytes:
        if not isinstance(self._key, bytes) \
                or len(self._key) != _KEY_BYTES:
            raise CISecretsError(
                "encryption_unavailable",
                "No instance encryption key is "
                "available; CI secrets cannot be "
                "set or resolved without one "
                "(S-003 custodies the key).")
        return self._key

    def _require_actor(self, actor_id: object) -> User:
        if actor_id is None:
            raise CISecretsError(
                "authentication_required",
                "Sign in to govern CI secrets.")
        actor = self._accounts.get_by_id(actor_id) \
            if isinstance(actor_id, int) else None
        if actor is None:
            raise CISecretsError(
                "no_such_user", "No such account.")
        return actor

    def _guard(self, actor: User, scope: str,
               target: str) -> None:
        """Judge one steward act over one already-
        canonical scope/target, exactly as S-317
        guards its tokens. Org and repo existence
        are judged here, so an act for a ghost is
        refused before anything is stored."""
        if scope == "org":
            org = self._orgs.get_by_name(target)
            if org is None:
                raise CISecretsError(
                    "org_not_found", "No such organization.")
            if actor.is_admin or self._members.is_owner(
                    actor.id, org.id):
                return
            raise CISecretsError(
                "ci_secret_not_permitted",
                "Only the organization's owners or a "
                "site admin govern its CI secrets.")
        owner, _sep, name = target.partition("/")
        repo = self._repos.get_repository(owner, name)
        if repo is None:
            raise CISecretsError(
                "repo_not_found", "No such repository.")
        role = role_for(actor, repo)
        if role is None:
            raise CISecretsError(
                "repo_not_found", "No such repository.")
        if role != "admin":
            raise CISecretsError(
                "ci_secret_not_permitted",
                "Only the repository's admins or a "
                "site admin govern its CI secrets.")

    def _witness(self, actor_id: int, scope: str,
                 target: str, key: str, *,
                 name: str = "",
                 source_ip: str | None = None) -> None:
        if self._audit is None:
            return
        detail: dict = {"key": key, "scope": scope,
                        "target": target}
        if name:
            detail["name"] = name
        if scope == "org":
            action, kind, tid = (
                "auth.organization.update", "organization",
                target)
        else:
            action, kind, tid = (
                "repo.settings.change", "repo", target)
        self._audit.append(
            actor_kind="user", actor_id=actor_id,
            action=action, target_kind=kind,
            target_id=tid, outcome="success",
            source_ip=source_ip, detail=detail)

    # -- steward acts -------------------------------

    def set_secret(
        self, actor_id: object, scope: object,
        target: object, name: object, value: object,
        source_ip: str | None = None,
    ) -> CISecret:
        """Set one secret: create its row, or
        replace a standing secret's value in
        place (its creation stamp and creator
        stand; the value and update stamp move).
        The value is encrypted before it is
        stored and is returned by nothing; the
        write commits before the secret is
        answered with (the commit-before-answer
        law)."""
        actor = self._require_actor(actor_id)
        checked = validate_scope(scope)
        canonical = _canonical_target(checked, target)
        self._guard(actor, checked, canonical)
        canon_name = validate_secret_name(name)
        checked_value = validate_secret_value(value)
        key = self._require_key()
        stored = encrypt_value(key, checked_value)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO ci_secrets"
                " (scope, target, name, value_enc,"
                " created_by, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(scope, target, name)"
                " DO UPDATE SET"
                " value_enc = excluded.value_enc,"
                " updated_at = excluded.updated_at",
                (checked, canonical, canon_name, stored,
                 actor.id, now, now))
        secret = self._by_name(checked, canonical, canon_name)
        assert secret is not None
        self._witness(actor.id, checked, canonical,
                      "ci_secret.set", name=canon_name,
                      source_ip=source_ip)
        return secret

    def _by_name(self, scope: str, target: str,
                 name: str) -> CISecret | None:
        row = self._conn.execute(
            "SELECT * FROM ci_secrets WHERE scope = ?"
            " AND target = ? AND name = ?",
            (scope, target, name)).fetchone()
        return _row_to_secret(row) if row else None

    def get_secret(self, actor_id: object, scope: object,
                   target: object,
                   name: object) -> CISecret | None:
        """One secret's public facts, or None --
        a steward read, guarded as setting is.
        The value is not part of any read."""
        actor = self._require_actor(actor_id)
        checked = validate_scope(scope)
        canonical = _canonical_target(checked, target)
        self._guard(actor, checked, canonical)
        canon_name = validate_secret_name(name)
        return self._by_name(checked, canonical, canon_name)

    def list_secrets(self, actor_id: object, scope: object,
                     target: object = "") -> list[CISecret]:
        """One scope's secrets' public facts, in
        name order -- a steward read, guarded as
        setting is. Values appear nowhere in it."""
        actor = self._require_actor(actor_id)
        checked = validate_scope(scope)
        canonical = _canonical_target(checked, target)
        self._guard(actor, checked, canonical)
        rows = self._conn.execute(
            "SELECT * FROM ci_secrets WHERE scope = ?"
            " AND target = ? ORDER BY name",
            (checked, canonical)).fetchall()
        return [_row_to_secret(r) for r in rows]

    def delete_secret(self, actor_id: object, scope: object,
                      target: object, name: object,
                      source_ip: str | None = None) -> bool:
        """Withdraw one standing secret. Returns
        False when no secret of that name stands
        at the scope -- a missing secret has
        nothing to withdraw."""
        actor = self._require_actor(actor_id)
        checked = validate_scope(scope)
        canonical = _canonical_target(checked, target)
        self._guard(actor, checked, canonical)
        canon_name = validate_secret_name(name)
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM ci_secrets WHERE scope = ?"
                " AND target = ? AND name = ?",
                (checked, canonical, canon_name))
        if cur.rowcount == 0:
            return False
        self._witness(actor.id, checked, canonical,
                      "ci_secret.delete", name=canon_name,
                      source_ip=source_ip)
        return True

    # -- the dispatch road --------------------------

    def _values_at(self, scope: str, target: str) -> dict:
        key = self._require_key()
        rows = self._conn.execute(
            "SELECT name, value_enc FROM ci_secrets"
            " WHERE scope = ? AND target = ? ORDER BY name",
            (scope, target)).fetchall()
        return {row["name"]: decrypt_value(key, row["value_enc"])
                for row in rows}

    def secret_names_for_repo(self, repo_target: object) -> list:
        """The names a dispatch for one repository
        would carry: its org's names and its own,
        sorted, said once -- names only, the
        S-316 assignment shape. An internal read
        (the forge's own act), unguarded."""
        canonical = _canonical_target("repo", repo_target)
        names = set(self._names_at("repo", canonical))
        owner = canonical.partition("/")[0]
        if self._orgs.get_by_name(owner) is not None:
            names.update(self._names_at("org", owner))
        return sorted(names)

    def _names_at(self, scope: str, target: str) -> list:
        rows = self._conn.execute(
            "SELECT name FROM ci_secrets WHERE scope = ?"
            " AND target = ? ORDER BY name",
            (scope, target)).fetchall()
        return [row["name"] for row in rows]

    def resolve_env(self, repo_target: object) -> dict:
        """Resolve one repository's injected
        environment: the owning organization's
        secrets first, the repository's own laid
        over them (a repo secret of the same name
        wins). The org is the repo's owner when
        that owner is an organization; a
        user-owned repo receives only its own
        secrets. This mapping is the only road a
        value leaves this module by -- the
        forge's own act at dispatch, unguarded,
        and never logged."""
        canonical = _canonical_target("repo", repo_target)
        env: dict = {}
        owner = canonical.partition("/")[0]
        if self._orgs.get_by_name(owner) is not None:
            env.update(self._values_at("org", owner))
        env.update(self._values_at("repo", canonical))
        return env

    def resolve_scope_env(self, scope: object,
                          target: object = "") -> dict:
        """Resolve exactly one scope's secrets --
        the org page's own test of what its
        repositories would inherit, and the
        masking road's source. The forge's own
        act, unguarded."""
        checked = validate_scope(scope)
        canonical = _canonical_target(checked, target)
        return self._values_at(checked, canonical)

    # -- the masking road ---------------------------

    def redact_for_repo(self, text: str,
                        repo_target: object) -> str:
        """Mask one log text with exactly the
        values a dispatch for this repository
        would inject, struck through S-018's
        filter (``mask_text``)."""
        env = self.resolve_env(repo_target)
        return mask_text(text, tuple(env.values()))

    def redact_for_scope(self, text: str, scope: object,
                         target: object = "") -> str:
        """Mask one log text with exactly one
        scope's standing values, struck through
        S-018's filter (``mask_text``)."""
        env = self.resolve_scope_env(scope, target)
        return mask_text(text, tuple(env.values()))


# ------------------------------------------------------------------
# The audit: the store checked against itself.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class CISecretsAudit:
    """The store checked against its own law:
    every row's scope/target shape, name law and
    sealed value. The store stands cleanly only
    while the problem list is empty."""
    secrets_scanned: int
    problems: tuple

    @property
    def stands_cleanly(self) -> bool:
        return not self.problems


def audit_ci_secrets(
        conn: sqlite3.Connection,
        encryption_key: bytes | None = None) -> CISecretsAudit:
    """Re-prove the store's invariants from its
    rows alone: each row's scope is one of the
    two, its target canonical, its name lawful,
    and its stored value a sealed ``v1:`` blob --
    decrypted and seal-checked when a key rides
    along. Pure read."""
    problems: list = []
    rows = conn.execute(
        "SELECT * FROM ci_secrets ORDER BY id").fetchall()
    seen: set = set()
    for row in rows:
        secret = _row_to_secret(row)
        label = f"secret {secret.id}"
        if secret.scope not in SECRET_SCOPES:
            problems.append(
                f"{label}: scope is not one of the two")
            continue
        try:
            if _canonical_target(
                    secret.scope, secret.target) != secret.target:
                problems.append(
                    f"{label}: target is not canonical")
            if validate_secret_name(secret.name) != secret.name:
                problems.append(
                    f"{label}: name is not canonical")
        except CISecretsError:
            problems.append(
                f"{label}: scope/target or name breaks the law")
        binding = (secret.scope, secret.target, secret.name)
        if binding in seen:
            problems.append(
                f"{label}: a second row carries this "
                "scope, target and name")
        seen.add(binding)
        stored = row["value_enc"]
        if not isinstance(stored, str) \
                or not stored.startswith("v1:"):
            problems.append(
                f"{label}: stored value is not a sealed blob")
        elif encryption_key is not None:
            try:
                decrypt_value(encryption_key, stored)
            except CISecretsError:
                problems.append(
                    f"{label}: stored value does not "
                    "unseal under the instance key")
    return CISecretsAudit(
        secrets_scanned=len(rows), problems=tuple(problems))


# ------------------------------------------------------------------
# Pages: the findability walk and the secrets page.
# ------------------------------------------------------------------

def _stamp(ts: int | None) -> str:
    if ts is None:
        return "Never"
    return time.strftime(
        "%Y-%m-%d %H:%M UTC", time.gmtime(ts))


def render_secrets_home() -> str:
    """The secrets home: every secret area one
    click away, each under its plain description
    -- the start of the findability walk, in
    S-317's shape. Org and repo areas are named
    by their path shapes, since their targets
    are the steward's own to name."""
    parts = [
        "<h1>CI secrets</h1>",
        "<p>CI secrets are values a workflow's "
        "jobs receive as environment variables. "
        "They are encrypted at rest under the "
        "instance keys, injected as env at "
        "dispatch, and masked in logs. Each scope "
        "has one secrets page: set and withdraw "
        "its secrets there.</p>",
        "<nav><ul>",
    ]
    for area in ci_secret_areas():
        parts.append(
            f'<li><a href="{escape_html_attr(area["path_template"])}">'
            f"{escape_html_text(area['title'])}</a> -- "
            f"{escape_html_text(area['description'])}</li>")
    parts.append("</ul></nav>")
    return "\n".join(parts)


def render_secrets_page(
        scope: object, target: object,
        secrets: list[CISecret],
        csrf_token: str = "") -> str:
    """One scope's secrets page: the walk's end.
    Its secrets by name only -- with creator and
    creation/update stamps, and a withdraw form
    for each -- and the set form, with the
    never-shown law said plainly: a secret's
    value is written once, at setting, and read
    by no page ever. Every value escaped through
    S-010."""
    checked = validate_scope(scope)
    canonical = _canonical_target(checked, target)
    page_path = secrets_page_path(checked, canonical)
    heading = f"CI secrets -- {checked} scope"
    parts = [
        "<h1>" + escape_html_text(heading) + "</h1>",
        f'<p><a href="{SECRETS_HOME_PATH}">Back to CI secrets</a></p>',
        f"<p>Scope: {escape_html_text(checked)} -- "
        f"serving {escape_html_text(canonical)}. "
        "A secret's value is encrypted at rest, "
        "injected as env when a job runs, and "
        "masked in logs. Values are never shown: "
        "setting a name that already stands "
        "replaces its value.</p>",
        "<h2>Set a secret</h2>",
        f'<form method="post" action="{escape_html_attr(page_path)}/set">'
        f'<input type="hidden" name="csrf_token" '
        f'value="{escape_html_attr(csrf_token)}">'
        '<label>Name <input type="text" name="name"></label> '
        '<label>Value <input type="password" name="value"></label> '
        '<button type="submit">Set secret</button></form>',
        "<h2>Secrets</h2>",
    ]
    if not secrets:
        parts.append(
            "<p>No CI secrets set for this scope yet.</p>")
    for secret in secrets:
        parts.append('<div class="secret">')
        parts.append(
            f"<p>Secret {escape_html_text(secret.name)} -- "
            f"set {_stamp(secret.created_at)} -- "
            f"updated {_stamp(secret.updated_at)}</p>")
        parts.append(
            f'<form method="post" '
            f'action="{escape_html_attr(page_path)}/delete">'
            f'<input type="hidden" name="name" '
            f'value="{escape_html_attr(secret.name)}">'
            f'<input type="hidden" name="csrf_token" '
            f'value="{escape_html_attr(csrf_token)}">'
            '<button type="submit">Delete</button></form>')
        parts.append("</div>")
    return "\n".join(parts)
