"""Runner registration (S-317) -- the registry
S-316's contract promised.

S-316 wrote the wire law and judged registration
messages, but it kept no registry, minted no token
and stored nothing: the token was carried, never
kept, and its minting was named as this slice's
work. This slice is that work -- a runner becomes
a standing thing on the instance only by passing
through here, under five laws:

- **Three scopes, one law.** A runner serves the
  whole **instance**, one **organization**, or one
  **repository** -- S-316's ``RUNNER_SCOPES``,
  imported, never re-spelt. An instance runner
  names no target; an org runner names exactly
  its organization; a repo runner names exactly
  its repository in ``owner/name`` form. The
  scope/target pair is judged by the pure
  ``validate_scope`` / ``validate_target`` at
  every door, and the stored target is canonical:
  the org's lowercase name, the repo's lowercase
  ``owner/name``, or the empty string for the
  instance.
- **One-time registration tokens, shown once.**
  A token is minted for exactly one scope and
  target by ``mint_token``: ``svr_`` + 256 bits
  from the OS CSPRNG, returned raw exactly once
  to its minter, and stored only as its SHA-256
  hash beside an identifying prefix (the S-006 /
  S-032 law -- a stolen database holds no usable
  token, and this battery presents the stored
  hash itself and is refused). A token lives at
  most 24 hours (default 1 hour; the TTL is
  judged at minting, never warned about), may be
  revoked by its scope's stewards while it stands
  unused, and is consumed by exactly one
  successful registration: a second presentation
  is refused ``runner_token_used`` in words.
  Expired, revoked and unknown tokens are refused
  by name (``runner_token_expired`` /
  ``runner_token_refused``), and a token presented
  for another scope or target is refused
  ``runner_token_scope_mismatch`` -- a repo token
  never registers an instance runner.
- **Registration speaks S-316, whole.**
  ``register_runner`` takes the protocol's own
  ``register`` message and judges it with
  S-316's ``parse_registration`` before any token
  is touched, so a shapeless message consumes
  nothing. The runner's name, labels and agent
  version are the message's own; labels obey
  S-316's label law (1..16, each a name, said
  once). A live runner's name is taken within
  its scope and target (``runner_name_taken``);
  deregistration frees it. The token's
  consumption and the runner's row are written
  in one transaction, committed before the
  runner is answered with (the commit-before-
  answer law), so a returned runner is real.
- **Stewards guard each scope.** Minting,
  listing, revoking and deregistering are
  steward acts, judged per scope: a **site
  admin** for the instance; a site admin or the
  organization's **owner** (S-186's membership)
  for an org; a site admin or a viewer holding
  the **admin** rung on the repository (S-054 /
  S-190) for a repo. Anyone else is refused
  ``runner_not_permitted`` -- except a stranger
  to a private repository, who gets the uniform
  ``repo_not_found``, because a private repo's
  existence is itself private. Registering
  itself needs no account: the token is the
  credential, exactly as S-316 drew it.
- **The token page passes the findability
  walk.** ``RUNNER_AREAS`` names the three
  runner areas as data -- instance, organization
  and repository, each with its one path -- and
  ``render_runner_home`` links every area from
  one page, so a steward standing on the runner
  home reaches any scope's token page in one
  click. ``render_runner_token_page`` renders
  exactly one scope's page: its tokens with
  prefix, status word, creation and expiry, a
  revoke form for live tokens only, its runners
  with name, labels, agent version and standing,
  a deregister form for live runners, and the
  mint form -- every state in plain words,
  never colour alone, every value through
  S-010's escaping seam.

Witness: minting, revoking, registering and
deregistering are witnessed on standing verbs,
scoped as the act is -- the instance rides
``admin.settings.change`` (target the instance's
runner registration), an org rides
``auth.organization.update``, a repo rides
``repo.settings.change`` -- each detail naming
the act under ``key`` (``runner_token.mint`` /
``runner_token.revoke`` / ``runner.register`` /
``runner.deregister``) with the scope, target
and token or runner id, never token material.
No new taxonomy event: 135 stand (33 auth /
89 repo / 13 admin).

Storage is migration 129 (schema 128 -> 129):
``runner_registration_tokens`` and ``runners``.
S-316's audit is updated in this slice to admit
exactly these two tables and their columns as
the lawful runner surface; any other
runner-named table, column or audit event is
still an offender there.

Honest limits, stated plainly: this slice keeps
the registry and mints the tokens; it builds no
runner (S-318), injects no secret (S-319) and
runs no job. A registered runner's standing here
is *registered* until it is deregistered -- this
module records ``last_seen_at`` as the
registration moment and does not judge liveness
from heartbeats; the heartbeat is S-316's
protocol message, and the live tail is S-322's
road. The pages are render functions in the
house shape; the web layer that routes them is
the instance's own (S-382 owns the nav shell).
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text
from .organization_members import OrgMembershipStore
from .organizations import OrganizationStore
from .permissions import role_for
from .repositories import RepositoryStore
from .runner_protocol import (
    MAX_LABELS, RUNNER_SCOPES, RunnerProtocolError,
    parse_registration)

__all__ = [
    "MAX_TOKEN_TTL_SECONDS", "MIN_TOKEN_TTL_SECONDS",
    "RUNNER_AREAS", "RUNNERS_HOME_PATH", "TOKEN_PREFIX",
    "TOKEN_TTL_SECONDS", "RegistrationToken", "Runner",
    "RunnerRegistrationAudit", "RunnerRegistrationError",
    "RunnerRegistrationStore", "audit_runner_registration",
    "decide_token_status", "render_runner_home",
    "render_runner_token_page", "runner_areas",
    "runner_to_dict", "scope_word", "token_page_path",
    "token_to_dict", "validate_labels", "validate_scope",
    "validate_target",
]

TOKEN_PREFIX = "svr_"
_TOKEN_BYTES = 32  # 256 bits
_PREFIX_CHARS = 12  # "svr_" + 8 random chars

#: A registration token's ordinary life: long
#: enough to carry to the runner's machine and
#: use, short enough that a forgotten token is
#: not a standing door.
TOKEN_TTL_SECONDS = 3600
MIN_TOKEN_TTL_SECONDS = 60
MAX_TOKEN_TTL_SECONDS = 24 * 3600

RUNNERS_HOME_PATH = "/runners"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_SCOPE_WORDS = {
    "instance": "the whole instance",
    "org": "one organization",
    "repo": "one repository",
}

# The runner areas, in the order a steward looks
# for them: (scope, title, plain description, path
# template). The findability map is data, as in
# S-228: the home renders exactly these, so no
# area can hide and none is promised that its
# page does not carry. ``{target}`` in a template
# is the scope's canonical target.
RUNNER_AREAS = (
    ("instance", "Instance runners",
     "Runners serving the whole instance. Site "
     "admins mint their registration tokens here.",
     "/admin/runners"),
    ("org", "Organization runners",
     "Runners serving one organization. The "
     "organization's owners mint their "
     "registration tokens here.",
     "/orgs/{target}/settings/runners"),
    ("repo", "Repository runners",
     "Runners serving one repository. The "
     "repository's admins mint their registration "
     "tokens here.",
     "/{target}/settings/runners"),
)


class RunnerRegistrationError(ValueError):
    """One refused runner-registration act: a
    machine-branchable reason with its human
    detail, in the house shape."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def scope_word(scope: object) -> str:
    """Pure: the plain words one scope is shown
    under, judged through the scope door."""
    return _SCOPE_WORDS[validate_scope(scope)]


def validate_scope(scope: object) -> str:
    """Pure: one of S-316's three scopes, or
    refused ``runner_scope_unknown`` in words --
    the same refusal the protocol gives."""
    if not isinstance(scope, str) or scope not in RUNNER_SCOPES:
        raise RunnerRegistrationError(
            "runner_scope_unknown",
            "Runner scope: one of "
            + ", ".join(RUNNER_SCOPES) + ".")
    return scope


def validate_target(scope: object, target: object) -> str:
    """Pure: the canonical stored target for one
    scope -- ``""`` for the instance (an instance
    runner names no target), the org's name for
    an org, ``owner/name`` for a repo -- judged
    exactly as S-316's register message judges
    its target. Canonical form is lowercase,
    because org and repo identity in Samverk is
    case-insensitive. Refusals are
    ``runner_target_invalid`` in words. Whether
    the named org or repo stands is the store's
    question, not this pure law's."""
    checked = validate_scope(scope)
    if target is None:
        target = ""
    if not isinstance(target, str):
        raise RunnerRegistrationError(
            "runner_target_invalid",
            "Runner target: text.")
    target = target.strip()
    if checked == "instance":
        if target:
            raise RunnerRegistrationError(
                "runner_target_invalid",
                "An instance runner names no target; "
                "its scope is the whole instance.")
        return ""
    if checked == "org":
        if not _NAME_RE.match(target):
            raise RunnerRegistrationError(
                "runner_target_invalid",
                "An org runner names exactly its "
                "organization.")
        return target.lower()
    parts = target.split("/")
    if len(parts) != 2 or not all(
            _NAME_RE.match(part) for part in parts):
        raise RunnerRegistrationError(
            "runner_target_invalid",
            "A repo runner names exactly its "
            "repository, as owner/name.")
    return target.lower()


def validate_labels(labels: object) -> tuple:
    """Pure: a runner's labels under S-316's
    label law -- a non-empty list of at most
    ``MAX_LABELS`` names, each said once --
    returned as a tuple in the order declared.
    Refused ``runner_labels_invalid`` in words."""
    if (not isinstance(labels, (list, tuple))
            or not labels or len(labels) > MAX_LABELS):
        raise RunnerRegistrationError(
            "runner_labels_invalid",
            f"Labels are a non-empty list of at most "
            f"{MAX_LABELS} labels.")
    out: list = []
    for label in labels:
        if not isinstance(label, str) or not _NAME_RE.match(label):
            raise RunnerRegistrationError(
                "runner_labels_invalid",
                f"Label {label!r} is not a valid "
                "runner label.")
        if label in out:
            raise RunnerRegistrationError(
                "runner_labels_invalid",
                f"Label {label!r} is stated twice; "
                "a label is said once.")
        out.append(label)
    return tuple(out)


def decide_token_status(*, revoked: bool,
                        used_at: int | None,
                        expires_at: int,
                        now: int) -> str:
    """Pure: one token's standing in one word --
    ``revoked`` (its stewards withdrew it),
    ``used`` (it registered its one runner),
    ``expired`` (its life ran out unused), or
    ``live`` (it may still register a runner).
    Revocation outranks use in the telling only
    when both stand; a token is consumed and
    revoked in no ordinary road, and the word
    order here keeps the stronger fact first."""
    if revoked:
        return "revoked"
    if used_at is not None:
        return "used"
    if now >= expires_at:
        return "expired"
    return "live"


def runner_areas() -> list[dict]:
    """The findability map as data: every runner
    area, in order, with its plain description
    and path template. The home renders exactly
    this."""
    return [
        {"scope": scope, "title": title,
         "description": desc, "path_template": path}
        for scope, title, desc, path in RUNNER_AREAS]


def token_page_path(scope: object, target: object = "") -> str:
    """Pure: the one path of one scope's token
    page -- the address the findability walk
    walks to. The target is judged through
    ``validate_target`` first, so a shapeless
    target has no page."""
    checked = validate_scope(scope)
    canonical = validate_target(checked, target)
    for area_scope, _title, _desc, template in RUNNER_AREAS:
        if area_scope == checked:
            return template.replace("{target}", canonical)
    raise AssertionError("scope without an area")  # unreachable


@dataclass(frozen=True)
class RegistrationToken:
    """A one-time registration token's public
    facts: its scope and target, its identifying
    prefix, its minter and its life. The raw
    token and its hash are deliberately NOT
    fields here -- the raw is returned once by
    ``mint_token`` and the hash never leaves
    the store."""
    id: int
    scope: str
    target: str
    prefix: str
    created_by: int
    created_at: int
    expires_at: int
    used_at: int | None
    used_runner: str
    revoked: bool

    def status(self, now: int) -> str:
        return decide_token_status(
            revoked=self.revoked, used_at=self.used_at,
            expires_at=self.expires_at, now=now)

    @property
    def target_words(self) -> str:
        return self.target or "the whole instance"


@dataclass(frozen=True)
class Runner:
    """One registered runner: its name, its
    scope and target, the labels it answers to,
    the agent version it runs, and its standing.
    A deregistered runner keeps its row (its
    history is a fact) and answers
    ``registered`` False."""
    id: int
    name: str
    scope: str
    target: str
    labels: tuple
    agent_version: str
    token_id: int
    registered_at: int
    last_seen_at: int
    deregistered: bool
    deregistered_at: int | None

    @property
    def registered(self) -> bool:
        return not self.deregistered

    @property
    def standing(self) -> str:
        return "Registered" if self.registered else "Deregistered"

    @property
    def target_words(self) -> str:
        return self.target or "the whole instance"


def token_to_dict(token: RegistrationToken, now: int) -> dict:
    """The token's programmatic face: its public
    facts and its standing in words -- never the
    hash, never the raw token."""
    return {
        "id": token.id, "scope": token.scope,
        "target": token.target, "prefix": token.prefix,
        "created_by": token.created_by,
        "created_at": token.created_at,
        "expires_at": token.expires_at,
        "used_at": token.used_at,
        "used_runner": token.used_runner,
        "revoked": token.revoked,
        "status": token.status(now),
    }


def runner_to_dict(runner: Runner) -> dict:
    """The runner's programmatic face, in the
    shape S-316's register message stated it."""
    return {
        "id": runner.id, "name": runner.name,
        "scope": runner.scope, "target": runner.target,
        "labels": list(runner.labels),
        "agent_version": runner.agent_version,
        "token_id": runner.token_id,
        "registered_at": runner.registered_at,
        "last_seen_at": runner.last_seen_at,
        "registered": runner.registered,
        "standing": runner.standing,
    }


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    raw = base64.urlsafe_b64encode(
        os.urandom(_TOKEN_BYTES)).decode("ascii")
    return TOKEN_PREFIX + raw.rstrip("=")


def _row_to_token(row: sqlite3.Row) -> RegistrationToken:
    return RegistrationToken(
        id=row["id"], scope=row["scope"], target=row["target"],
        prefix=row["prefix"], created_by=row["created_by"],
        created_at=row["created_at"],
        expires_at=row["expires_at"], used_at=row["used_at"],
        used_runner=row["used_runner"],
        revoked=bool(row["revoked"]))


def _row_to_runner(row: sqlite3.Row) -> Runner:
    labels = tuple(
        row["labels"].split(",")) if row["labels"] else ()
    return Runner(
        id=row["id"], name=row["name"], scope=row["scope"],
        target=row["target"], labels=labels,
        agent_version=row["agent_version"],
        token_id=row["token_id"],
        registered_at=row["registered_at"],
        last_seen_at=row["last_seen_at"],
        deregistered=bool(row["deregistered"]),
        deregistered_at=row["deregistered_at"])


class RunnerRegistrationStore:
    """The registry: minting, registration,
    listing, revocation and deregistration over
    migration 129's two tables, guarded per scope
    and witnessed on the standing verbs."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        repos: RepositoryStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._repos = repos
        self._audit = audit
        self._now = time_fn
        self._orgs = OrganizationStore(
            conn, accounts, audit=audit, time_fn=time_fn)
        self._members = OrgMembershipStore(
            conn, accounts, audit=audit, time_fn=time_fn)

    # -- guards ------------------------------------

    def _require_actor(self, actor_id: object) -> User:
        if actor_id is None:
            raise RunnerRegistrationError(
                "authentication_required",
                "Sign in to govern runners.")
        actor = self._accounts.get_by_id(actor_id) \
            if isinstance(actor_id, int) else None
        if actor is None:
            raise RunnerRegistrationError(
                "no_such_user", "No such account.")
        return actor

    def _guard(self, actor: User, scope: str,
               target: str) -> None:
        """Judge one steward act over one already-
        canonical scope/target. Raises the scope's
        refusal; returns None when the actor may
        act. Org and repo existence are judged
        here, so a mint for a ghost is refused
        before any token exists."""
        if scope == "instance":
            if not actor.is_admin:
                raise RunnerRegistrationError(
                    "runner_not_permitted",
                    "Only a site admin governs "
                    "instance runners.")
            return
        if scope == "org":
            org = self._orgs.get_by_name(target)
            if org is None:
                raise RunnerRegistrationError(
                    "org_not_found", "No such organization.")
            if actor.is_admin or self._members.is_owner(
                    actor.id, org.id):
                return
            raise RunnerRegistrationError(
                "runner_not_permitted",
                "Only the organization's owners or a "
                "site admin govern its runners.")
        owner, _sep, name = target.partition("/")
        repo = self._repos.get_repository(owner, name)
        if repo is None:
            raise RunnerRegistrationError(
                "repo_not_found", "No such repository.")
        role = role_for(actor, repo)
        if role is None:
            raise RunnerRegistrationError(
                "repo_not_found", "No such repository.")
        if role != "admin":
            raise RunnerRegistrationError(
                "runner_not_permitted",
                "Only the repository's admins or a "
                "site admin govern its runners.")

    def _witness(self, actor_id: int, scope: str,
                 target: str, key: str, *,
                 token_id: int | None = None,
                 runner_id: int | None = None,
                 runner_name: str = "",
                 source_ip: str | None = None) -> None:
        if self._audit is None:
            return
        detail: dict = {"key": key, "scope": scope,
                        "target": target}
        if token_id is not None:
            detail["token_id"] = token_id
        if runner_id is not None:
            detail["runner_id"] = runner_id
        if runner_name:
            detail["runner"] = runner_name
        if scope == "instance":
            action, kind, tid = (
                "admin.settings.change", "instance",
                "runner_registration")
        elif scope == "org":
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

    # -- tokens ------------------------------------

    def mint_token(
        self, actor_id: object, scope: object,
        target: object = "",
        ttl_seconds: object = TOKEN_TTL_SECONDS,
        source_ip: str | None = None,
    ) -> tuple[RegistrationToken, str]:
        """Mint a one-time registration token for
        one scope and target; return (public
        facts, raw token). The raw token is
        returned here and nowhere else, ever --
        it is shown once, at minting, to its
        minter. Its life is judged here: a TTL
        outside one minute..one day is refused
        ``runner_token_ttl_invalid``."""
        actor = self._require_actor(actor_id)
        checked = validate_scope(scope)
        canonical = validate_target(checked, target)
        self._guard(actor, checked, canonical)
        if (not isinstance(ttl_seconds, int)
                or isinstance(ttl_seconds, bool)
                or ttl_seconds < MIN_TOKEN_TTL_SECONDS
                or ttl_seconds > MAX_TOKEN_TTL_SECONDS):
            raise RunnerRegistrationError(
                "runner_token_ttl_invalid",
                f"A registration token lives between "
                f"{MIN_TOKEN_TTL_SECONDS} seconds and "
                f"{MAX_TOKEN_TTL_SECONDS} seconds; "
                "choose a life inside that.")
        now = int(self._now())
        raw = _new_token()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO runner_registration_tokens"
                " (scope, target, token_hash, prefix,"
                " created_by, created_at, expires_at,"
                " used_at, used_runner, revoked)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, NULL, '', 0)",
                (checked, canonical, _hash_token(raw),
                 raw[:_PREFIX_CHARS], actor.id, now,
                 now + ttl_seconds))
        token = self.get_token(int(cur.lastrowid))
        assert token is not None
        self._witness(actor.id, checked, canonical,
                      "runner_token.mint",
                      token_id=token.id, source_ip=source_ip)
        return token, raw

    def get_token(self, token_id: int) -> RegistrationToken | None:
        row = self._conn.execute(
            "SELECT * FROM runner_registration_tokens"
            " WHERE id = ?", (token_id,)).fetchone()
        return _row_to_token(row) if row else None

    def list_tokens(self, actor_id: object, scope: object,
                    target: object = "") -> list[RegistrationToken]:
        """One scope's tokens, in minting order --
        a steward read, guarded as minting is."""
        actor = self._require_actor(actor_id)
        checked = validate_scope(scope)
        canonical = validate_target(checked, target)
        self._guard(actor, checked, canonical)
        rows = self._conn.execute(
            "SELECT * FROM runner_registration_tokens"
            " WHERE scope = ? AND target = ? ORDER BY id",
            (checked, canonical)).fetchall()
        return [_row_to_token(r) for r in rows]

    def revoke_token(self, actor_id: object, token_id: object,
                     source_ip: str | None = None) -> bool:
        """Withdraw one standing token. Returns
        False when there is no live token with
        that id -- a used, revoked, expired or
        missing token has nothing to withdraw.
        A steward of another scope asking after
        this token is refused by the guard, as
        minting would refuse them."""
        actor = self._require_actor(actor_id)
        if not isinstance(token_id, int) \
                or isinstance(token_id, bool):
            return False
        token = self.get_token(token_id)
        if token is None:
            return False
        self._guard(actor, token.scope, token.target)
        now = int(self._now())
        if token.status(now) != "live":
            return False
        with self._conn:
            cur = self._conn.execute(
                "UPDATE runner_registration_tokens"
                " SET revoked = 1 WHERE id = ?"
                " AND revoked = 0 AND used_at IS NULL",
                (token.id,))
        if cur.rowcount == 0:
            return False
        self._witness(actor.id, token.scope, token.target,
                      "runner_token.revoke",
                      token_id=token.id, source_ip=source_ip)
        return True

    # -- registration -------------------------------

    def register_runner(self, payload: object,
                        source_ip: str | None = None) -> Runner:
        """Register one runner from S-316's own
        register message. The message is judged
        whole by ``parse_registration`` first --
        a shapeless message consumes nothing --
        then the presented token is judged: it
        must stand, be live, and have been minted
        for exactly this scope and target. The
        consumption and the runner's row commit
        in one transaction before the runner is
        answered with."""
        try:
            reg = parse_registration(payload)
        except RunnerProtocolError as exc:
            raise RunnerRegistrationError(
                exc.reason, str(exc)) from None
        raw = payload.get("registration_token") \
            if isinstance(payload, dict) else None
        row = self._conn.execute(
            "SELECT * FROM runner_registration_tokens"
            " WHERE token_hash = ?",
            (_hash_token(raw),)).fetchone() \
            if isinstance(raw, str) else None
        if row is None:
            raise RunnerRegistrationError(
                "runner_token_refused",
                "That registration token is not one "
                "this instance minted.")
        token = _row_to_token(row)
        canonical = validate_target(reg.scope, reg.target)
        if token.scope != reg.scope or token.target != canonical:
            raise RunnerRegistrationError(
                "runner_token_scope_mismatch",
                "That token was minted for "
                f"{token.scope} scope"
                + (f" ({token.target})" if token.target else "")
                + "; it cannot register a runner for "
                f"{reg.scope}"
                + (f" ({canonical})" if canonical else "")
                + ".")
        now = int(self._now())
        status = token.status(now)
        if status == "used":
            raise RunnerRegistrationError(
                "runner_token_used",
                "That registration token has already "
                "registered its one runner; mint a "
                "new token for another runner.")
        if status == "expired":
            raise RunnerRegistrationError(
                "runner_token_expired",
                "That registration token's life has "
                "run out; mint a new one.")
        if status != "live":
            raise RunnerRegistrationError(
                "runner_token_refused",
                "That registration token no longer "
                "stands; mint a new one.")
        clash = self._conn.execute(
            "SELECT id FROM runners WHERE scope = ?"
            " AND target = ? AND name_lower = ?"
            " AND deregistered = 0",
            (reg.scope, canonical,
             reg.name.lower())).fetchone()
        if clash is not None:
            raise RunnerRegistrationError(
                "runner_name_taken",
                f"A live runner named {reg.name!r} "
                "already serves this scope and "
                "target; deregister it or name this "
                "runner differently.")
        labels = validate_labels(list(reg.labels))
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO runners (name, name_lower,"
                " scope, target, labels, agent_version,"
                " token_id, registered_at, last_seen_at,"
                " deregistered, deregistered_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)",
                (reg.name, reg.name.lower(), reg.scope,
                 canonical, ",".join(labels),
                 reg.agent_version, token.id, now, now))
            runner_id = int(cur.lastrowid)
            self._conn.execute(
                "UPDATE runner_registration_tokens"
                " SET used_at = ?, used_runner = ?"
                " WHERE id = ?",
                (now, reg.name, token.id))
        runner = self.get_runner(runner_id)
        assert runner is not None
        self._witness(token.created_by, reg.scope,
                      canonical, "runner.register",
                      token_id=token.id, runner_id=runner.id,
                      runner_name=runner.name,
                      source_ip=source_ip)
        return runner

    def get_runner(self, runner_id: int) -> Runner | None:
        row = self._conn.execute(
            "SELECT * FROM runners WHERE id = ?",
            (runner_id,)).fetchone()
        return _row_to_runner(row) if row else None

    def list_runners(self, actor_id: object, scope: object,
                     target: object = "") -> list[Runner]:
        """One scope's runners, live and
        deregistered together in registration
        order, each carrying its standing -- a
        steward read, guarded as minting is."""
        actor = self._require_actor(actor_id)
        checked = validate_scope(scope)
        canonical = validate_target(checked, target)
        self._guard(actor, checked, canonical)
        rows = self._conn.execute(
            "SELECT * FROM runners WHERE scope = ?"
            " AND target = ? ORDER BY id",
            (checked, canonical)).fetchall()
        return [_row_to_runner(r) for r in rows]

    def deregister_runner(self, actor_id: object,
                          runner_id: object,
                          source_ip: str | None = None) -> bool:
        """Retire one live runner: its row stands
        with its deregistration stamped, and its
        name is freed for a successor. Returns
        False when no live runner carries that
        id. The act is guarded by the runner's
        own scope, judged from its row."""
        actor = self._require_actor(actor_id)
        if not isinstance(runner_id, int) \
                or isinstance(runner_id, bool):
            return False
        runner = self.get_runner(runner_id)
        if runner is None or runner.deregistered:
            return False
        self._guard(actor, runner.scope, runner.target)
        now = int(self._now())
        with self._conn:
            cur = self._conn.execute(
                "UPDATE runners SET deregistered = 1,"
                " deregistered_at = ? WHERE id = ?"
                " AND deregistered = 0",
                (now, runner.id))
        if cur.rowcount == 0:
            return False
        self._witness(actor.id, runner.scope, runner.target,
                      "runner.deregister",
                      token_id=runner.token_id,
                      runner_id=runner.id,
                      runner_name=runner.name,
                      source_ip=source_ip)
        return True


# ------------------------------------------------------------------
# The audit: the registry checked against itself.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class RunnerRegistrationAudit:
    """The registry checked against its own law:
    every token's stored shape, every runner's
    scope/target shape, and the one-token-one-
    runner binding. The registry stands cleanly
    only while every problem list is empty."""
    tokens_scanned: int
    runners_scanned: int
    problems: tuple

    @property
    def stands_cleanly(self) -> bool:
        return not self.problems


def audit_runner_registration(
        conn: sqlite3.Connection) -> RunnerRegistrationAudit:
    """Re-prove the registry's invariants from
    its rows alone: a token's hash is a SHA-256
    hex digest and never its own prefix; a used
    token names its runner and exactly one runner
    row carries that token; a live runner's
    token stands used by that runner; every
    runner's labels obey the label law and its
    scope/target the target law. Pure read."""
    problems: list = []
    tokens = conn.execute(
        "SELECT * FROM runner_registration_tokens"
        " ORDER BY id").fetchall()
    runners = conn.execute(
        "SELECT * FROM runners ORDER BY id").fetchall()
    by_token: dict = {}
    for row in runners:
        by_token.setdefault(row["token_id"], []).append(row)
    for row in tokens:
        token = _row_to_token(row)
        stored_hash = conn.execute(
            "SELECT token_hash FROM"
            " runner_registration_tokens WHERE id = ?",
            (token.id,)).fetchone()["token_hash"]
        if len(stored_hash) != 64 or any(
                c not in "0123456789abcdef"
                for c in stored_hash):
            problems.append(
                f"token {token.id}: stored hash is "
                "not a SHA-256 digest")
        if stored_hash == token.prefix or \
                token.prefix in stored_hash:
            problems.append(
                f"token {token.id}: stored hash "
                "carries its prefix")
        try:
            validate_target(token.scope, token.target)
            if validate_target(
                    token.scope, token.target) != token.target:
                problems.append(
                    f"token {token.id}: target is "
                    "not canonical")
        except RunnerRegistrationError:
            problems.append(
                f"token {token.id}: scope/target "
                "breaks the target law")
        carriers = by_token.get(token.id, [])
        if token.used_at is not None:
            if len(carriers) != 1:
                problems.append(
                    f"token {token.id}: used by "
                    f"{len(carriers)} runners, not one")
            elif carriers[0]["name"] != token.used_runner:
                problems.append(
                    f"token {token.id}: used_runner "
                    "does not name its runner")
        elif carriers:
            problems.append(
                f"token {token.id}: a runner carries "
                "an unused token")
    for row in runners:
        runner = _row_to_runner(row)
        try:
            if validate_target(
                    runner.scope, runner.target) != runner.target:
                problems.append(
                    f"runner {runner.id}: target is "
                    "not canonical")
            validate_labels(list(runner.labels))
        except RunnerRegistrationError:
            problems.append(
                f"runner {runner.id}: scope/target "
                "or labels break the law")
        token_row = conn.execute(
            "SELECT * FROM runner_registration_tokens"
            " WHERE id = ?", (runner.token_id,)).fetchone()
        if token_row is None:
            problems.append(
                f"runner {runner.id}: its token "
                "does not stand")
        elif token_row["used_at"] is None:
            problems.append(
                f"runner {runner.id}: its token "
                "stands unused")
    return RunnerRegistrationAudit(
        tokens_scanned=len(tokens),
        runners_scanned=len(runners),
        problems=tuple(problems))


# ------------------------------------------------------------------
# Pages: the findability walk and the token page.
# ------------------------------------------------------------------

def _stamp(ts: int | None) -> str:
    if ts is None:
        return "Never"
    return time.strftime(
        "%Y-%m-%d %H:%M UTC", time.gmtime(ts))


def render_runner_home() -> str:
    """The runner home: every runner area one
    click away, each under its plain description
    -- the start of the findability walk, in
    S-034's settings-home shape. Org and repo
    areas are named by their path shapes, since
    their targets are the steward's own to name."""
    parts = [
        "<h1>Runners</h1>",
        "<p>Runners are machines that take jobs "
        "from this forge under the runner protocol "
        "(S-316). Each scope has one token page: "
        "mint a one-time registration token there, "
        "carry it to the runner, and the runner "
        "registers itself with it.</p>",
        "<nav><ul>",
    ]
    for area in runner_areas():
        parts.append(
            f'<li><a href="{escape_html_attr(area["path_template"])}">'
            f"{escape_html_text(area['title'])}</a> -- "
            f"{escape_html_text(area['description'])}</li>")
    parts.append("</ul></nav>")
    return "\n".join(parts)


def render_runner_token_page(
        scope: object, target: object,
        tokens: list[RegistrationToken],
        runners: list[Runner],
        csrf_token: str = "",
        now: int | None = None) -> str:
    """One scope's token page: the walk's end.
    Its tokens (prefix, standing in words,
    creation, expiry, and the runner each used
    token registered), a revoke form for live
    tokens only; its runners (name, labels,
    agent version, standing in words), a
    deregister form for live runners only; and
    the mint form, with the shown-once law said
    plainly. Every value escaped through S-010."""
    checked = validate_scope(scope)
    canonical = validate_target(checked, target)
    moment = int(time.time()) if now is None else now
    page_path = token_page_path(checked, canonical)
    heading = (
        f"Runner registration -- {checked} scope")
    where = canonical if canonical else "the whole instance"
    parts = [
        "<h1>" + escape_html_text(heading) + "</h1>",
        f'<p><a href="{RUNNERS_HOME_PATH}">Back to runners</a></p>',
        f"<p>Scope: {escape_html_text(checked)} -- "
        f"serving {escape_html_text(where)}. "
        "A registration token registers exactly "
        "one runner for this scope and target, is "
        "shown once at minting, and dies unused "
        "when its life runs out.</p>",
        "<h2>Mint a registration token</h2>",
        f'<form method="post" action="{escape_html_attr(page_path)}/mint">'
        f'<input type="hidden" name="csrf_token" '
        f'value="{escape_html_attr(csrf_token)}">'
        '<button type="submit">Mint token</button></form>',
        "<h2>Registration tokens</h2>",
    ]
    if not tokens:
        parts.append(
            "<p>No registration tokens minted for "
            "this scope yet.</p>")
    for token in tokens:
        status = token.status(moment)
        parts.append('<div class="token">')
        parts.append(
            f"<p>Token {token.id} -- prefix "
            f"{escape_html_text(token.prefix)} -- "
            f"status: {escape_html_text(status)} -- "
            f"minted {_stamp(token.created_at)} -- "
            f"expires {_stamp(token.expires_at)}"
            + (f" -- used by runner "
               f"{escape_html_text(token.used_runner)} "
               f"at {_stamp(token.used_at)}"
               if token.used_at is not None else "")
            + "</p>")
        if status == "live":
            parts.append(
                f'<form method="post" '
                f'action="{escape_html_attr(page_path)}/revoke">'
                f'<input type="hidden" name="token_id" '
                f'value="{token.id}">'
                f'<input type="hidden" name="csrf_token" '
                f'value="{escape_html_attr(csrf_token)}">'
                '<button type="submit">Revoke</button></form>')
        parts.append("</div>")
    parts.append("<h2>Runners</h2>")
    if not runners:
        parts.append(
            "<p>No runners registered for this "
            "scope yet.</p>")
    for runner in runners:
        parts.append('<div class="runner">')
        parts.append(
            f"<p>Runner {escape_html_text(runner.name)} -- "
            f"labels: {escape_html_text(', '.join(runner.labels))} -- "
            f"agent version {escape_html_text(runner.agent_version)} -- "
            f"standing: {escape_html_text(runner.standing)} -- "
            f"registered {_stamp(runner.registered_at)}</p>")
        if runner.registered:
            parts.append(
                f'<form method="post" '
                f'action="{escape_html_attr(page_path)}/deregister">'
                f'<input type="hidden" name="runner_id" '
                f'value="{runner.id}">'
                f'<input type="hidden" name="csrf_token" '
                f'value="{escape_html_attr(csrf_token)}">'
                '<button type="submit">Deregister</button></form>')
        parts.append("</div>")
    return "\n".join(parts)
