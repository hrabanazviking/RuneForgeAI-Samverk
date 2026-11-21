"""Fork-PR safety -- the scheduler's rule (S-320).

Workflows from fork pull requests run with no
secrets and read-only tokens by default; the
rule is in the scheduler, not in docs alone.

S-313 stated this invariant before the scheduler
existed (its ``fork-safety-in-the-scheduler``
must-not-break row), S-314's trigger law named
the scheduler that consults it, and S-319 built
the secrets road (``resolve_env``) a dispatch
walks. This slice is that scheduler judgement:
one pure function, ``schedule_dispatch``, that
every dispatch passes through, which decides --
from the run's event and its head/base
repositories alone -- what secrets the run may
carry and what token it runs under:

- **A fork run, defined exactly.** A run is a
  fork run when its event is ``pull_request``
  and its head repository -- canonicalised by
  S-317's target law, the same law S-319 judges
  secret targets by -- is not its base
  repository. Every other event (``push``,
  ``tag``, ``schedule``, ``workflow_dispatch``)
  runs on the base repository itself and is
  never a fork run, whatever head a caller
  claims: a schedule reads the default branch
  (S-313's invariant) and a dispatch is a
  maintainer's own act on the base. A
  same-repository pull request is not a fork
  run either. The fork *fact* (that the head
  stands in the base's fork lineage) is S-142's
  record, made when the pull request was
  opened; the scheduler judges the two names it
  is handed, canonicalises them, and compares
  -- it fetches nothing and trusts no flag a
  workflow file could set.
- **No secrets, by construction.** For a fork
  run the dispatch's secret environment is
  empty -- not filtered, emptied. The scheduler
  is handed the mapping S-319 resolved (or only
  the names it would inject) and returns a plan
  carrying no value and none of the secret
  names; the names withheld are recorded on the
  plan (names only -- a name is not a value) so
  the run page can say what was withheld.
  ``resolve_dispatch_env`` is the dispatch
  road: for a fork run it never calls the
  store's ``resolve_env`` at all, so no value
  is decrypted, no instance key is needed, and
  a fork run dispatches identically on an
  instance whose key is missing or wrong --
  there is nothing to leak because nothing was
  read. ``assignment_env_names`` applies the
  same cut to S-316's assignment: a fork run's
  ``env_names`` names no secret, so no runner
  is ever told to expect one.
- **Read-only tokens, by the same cut.** The
  token's permissions are S-313's ``permissions:``
  value -- a shorthand (``read-all`` /
  ``write-all`` / ``none``) or a mapping of
  scopes to ``read`` / ``write`` / ``none`` --
  parsed by ``parse_permissions``. Undeclared
  means read-only: S-313's read-by-default,
  inherited here, not re-decided. For a fork
  run the parsed permissions are capped by
  ``cap_to_read_only``: every ``write`` -- the
  fallback and each scope's -- becomes ``read``,
  ``read`` and ``none`` stand, and the plan
  records both what was declared and what was
  granted, with ``permissions_capped`` saying
  whether the cap moved anything. A workflow
  file in a fork can ask for write; the
  scheduler is where that ask ends. For any
  other run the declared permissions stand as
  declared (still read-only when undeclared).
- **A pure judgement, like S-314 and S-315.**
  This module holds no store, writes no row,
  audits nothing and runs nothing: scheduling a
  dispatch changes nothing by being judged.
  The plan is data -- ``plan_to_dict`` carries
  names, permissions and reasons, never a
  secret value; a fork plan carries no value
  anywhere, ``repr`` included. (A non-fork
  plan's env items are the dispatch's own
  working copy, held in the frozen record the
  dispatcher consumes; renderers print names
  and permissions only, never values.)
  No migration (schema stays 130), no taxonomy
  event (135 stand: 33 auth / 89 repo / 13
  admin). No fork-safety table, column or audit
  event exists; the audit below proves that
  absence against the live instance -- the rule
  is code, not data -- and the battery plants a
  fork-shaped workflow table to prove the audit
  would catch one arriving as a back door.

Honest limits, stated plainly: there is no
privileged fork trigger in Samverk's vocabulary
-- no ``pull_request_target``-style event that
runs fork code with base secrets, by design.
A maintainer who wants a fork's change tested
with secrets merges it, or dispatches the
workflow by hand on the base repository
(``workflow_dispatch``, never a fork run);
both roads run the base's own reviewed code,
which is the point. Literal ``env:`` values a
workflow declares (S-313) are not secrets and
are not this slice's to cut; S-321 lands the
run's conclusions as check runs, and S-327's
UI renders runs in this plan's words.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from . import taxonomy
from .escaping import escape_html_text
from .runner_registration import (
    RunnerRegistrationError, validate_target)
from .workflow_format import (
    PERMISSION_SHORTHANDS, PERMISSION_VALUES, TRIGGER_EVENTS)

__all__ = [
    "EVENT_KINDS", "PERMISSION_LEVELS", "DispatchPlan",
    "ForkSafetyAudit", "ForkSafetyError", "RunRequest",
    "TokenPermissions", "assignment_env_names",
    "audit_fork_pr_safety", "cap_to_read_only",
    "canonical_repo", "describe_permissions",
    "effective_permissions", "is_fork_head",
    "parse_permissions", "plan_to_dict",
    "render_fork_pr_safety_page", "resolve_dispatch_env",
    "schedule_dispatch",
]

#: The trigger vocabulary, S-313's own five,
#: pinned by the battery against S-314's law.
EVENT_KINDS = tuple(TRIGGER_EVENTS)

#: The token permission levels, weakest first --
#: S-313's vocabulary, word for word.
PERMISSION_LEVELS = ("none", "read", "write")
_LEVEL_RANK = {level: rank for rank, level in
               enumerate(PERMISSION_LEVELS)}

_SCOPE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ForkSafetyError(ValueError):
    """One refused scheduler judgement: a
    machine-branchable reason with its human
    detail, in the house shape."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _invalid(message: str) -> ForkSafetyError:
    return ForkSafetyError("fork_safety_invalid", message)

# ------------------------------------------------------------------
# Pure law: repositories, fork-ness, permissions.
# ------------------------------------------------------------------

def canonical_repo(value: object, where: str = "repository") -> str:
    """Pure: one repository's canonical
    ``owner/name``, judged by S-317's own target
    law (the law S-319 judges secret targets by);
    its refusal is re-spelt in this slice's
    reason, ``fork_repo_invalid``."""
    try:
        return validate_target("repo", value)
    except RunnerRegistrationError as exc:
        raise ForkSafetyError(
            "fork_repo_invalid",
            f"{where}: {exc}") from None


def is_fork_head(base_repository: object,
                 head_repository: object) -> bool:
    """Pure: True when a head repository stands
    apart from the base repository it proposes
    into -- the name half of the fork judgement
    (``schedule_dispatch`` adds the event half:
    only a pull request can be a fork run). An
    empty head names the base itself."""
    base = canonical_repo(base_repository, "base repository")
    if head_repository is None or head_repository == "":
        return False
    head = canonical_repo(head_repository, "head repository")
    return head != base


@dataclass(frozen=True)
class TokenPermissions:
    """One token's permissions, canonical: a
    fallback level for scopes the mapping does
    not name, and the named scopes' levels as
    (scope, level) pairs in scope order. Scopes
    are lowercase names; levels are S-313's
    three words."""
    fallback: str
    scopes: tuple = ()

    def level_for(self, scope: object) -> str:
        """The level one scope runs at: its named
        level, or the fallback when unnamed."""
        if isinstance(scope, str):
            wanted = scope.strip().lower()
            for name, level in self.scopes:
                if name == wanted:
                    return level
        return self.fallback

    @property
    def is_read_only(self) -> bool:
        """True when no scope and no fallback
        grants write -- the fork token's shape."""
        if _LEVEL_RANK[self.fallback] > _LEVEL_RANK["read"]:
            return False
        return all(_LEVEL_RANK[level] <= _LEVEL_RANK["read"]
                   for _name, level in self.scopes)

    def to_dict(self) -> dict:
        return {"fallback": self.fallback,
                "scopes": dict(self.scopes)}


#: S-313's read-by-default, as data: a workflow
#: that declares no permissions runs read-only.
DEFAULT_PERMISSIONS = TokenPermissions(fallback="read", scopes=())


def parse_permissions(value: object) -> TokenPermissions:
    """Pure: judge one S-313 ``permissions:``
    value -- nothing (read-only, the default),
    a shorthand (``read-all`` / ``write-all`` /
    ``none``), a mapping of scopes to levels, or
    an already-parsed TokenPermissions -- into
    its canonical form. A stated mapping is
    exhaustive: a scope it does not name runs at
    ``none`` (the GitHub reading, stated here
    because it is the strict one). Refusals are
    ``fork_permissions_invalid`` in words."""
    if value is None:
        return DEFAULT_PERMISSIONS
    if isinstance(value, TokenPermissions):
        return value
    if isinstance(value, str):
        if value not in PERMISSION_SHORTHANDS:
            raise ForkSafetyError(
                "fork_permissions_invalid",
                "permissions: is read-all, write-all, none, "
                "or a mapping of scopes to read / write / "
                f"none; got {value!r}.")
        fallback = {"read-all": "read", "write-all": "write",
                    "none": "none"}[value]
        return TokenPermissions(fallback=fallback, scopes=())
    if isinstance(value, dict):
        scopes: dict = {}
        for scope, level in value.items():
            if not isinstance(scope, str) \
                    or not _SCOPE_RE.match(scope.strip().lower()):
                raise ForkSafetyError(
                    "fork_permissions_invalid",
                    f"permissions: scope {scope!r} is not a "
                    "plain scope name.")
            name = scope.strip().lower()
            if level not in PERMISSION_VALUES:
                raise ForkSafetyError(
                    "fork_permissions_invalid",
                    f"permissions: scope {name!r} is read, "
                    f"write or none; got {level!r}.")
            if name in scopes:
                raise ForkSafetyError(
                    "fork_permissions_invalid",
                    f"permissions: scope {name!r} is named "
                    "twice.")
            scopes[name] = level
        return TokenPermissions(
            fallback="none",
            scopes=tuple(sorted(scopes.items())))
    raise ForkSafetyError(
        "fork_permissions_invalid",
        "permissions: is a shorthand or a mapping.")


def cap_to_read_only(perms: TokenPermissions) -> TokenPermissions:
    """Pure: the fork cap -- every ``write``, the
    fallback's and each scope's, becomes
    ``read``; ``read`` and ``none`` stand. The
    cap only ever lowers, and capping a read-only
    token returns it unchanged."""
    def lowered(level: str) -> str:
        return "read" if level == "write" else level
    return TokenPermissions(
        fallback=lowered(perms.fallback),
        scopes=tuple((name, lowered(level))
                     for name, level in perms.scopes))


def effective_permissions(declared: object, *, is_fork: bool) -> TokenPermissions:
    """Pure: the token a run actually carries --
    the declared permissions parsed, then capped
    to read-only when the run is a fork run."""
    parsed = parse_permissions(declared)
    return cap_to_read_only(parsed) if is_fork else parsed


def describe_permissions(perms: TokenPermissions) -> str:
    """The permissions in words, for pages and
    plans: read-only said as read-only, a write
    grant named scope by scope -- never an icon,
    never colour alone."""
    if perms.is_read_only:
        base = "read-only"
    else:
        base = "read/write"
    parts = [f"{base} (fallback {perms.fallback}"]
    for name, level in perms.scopes:
        parts.append(f"; {name}: {level}")
    parts.append(")")
    return "".join(parts)

# ------------------------------------------------------------------
# The scheduler: one run in, one dispatch plan out.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class RunRequest:
    """One run the scheduler is asked to place:
    its event (S-314's vocabulary), the base
    repository the run belongs to, the head
    repository a pull request proposes from
    (empty when the head is the base itself or
    the event has no head), and the workflow's
    declared ``permissions:`` value, raw as
    S-313 admits it (None when undeclared)."""
    event: str
    base_repository: str
    head_repository: str = ""
    declared_permissions: object = None


@dataclass(frozen=True)
class DispatchPlan:
    """The scheduler's answer, as data: whether
    the run is a fork run, the secret environment
    it may carry (name/value pairs in name order
    -- the dispatcher's working copy, consumed
    at dispatch and printed by no renderer), the
    secret names withheld from it, what token
    permissions were declared and what were
    granted, whether the cap moved anything, and
    the reasons in machine words.``env`` and
    ``secret_names`` are the dispatcher's views
    of the one ``env_items`` record."""
    event: str
    base_repository: str
    head_repository: str
    is_fork: bool
    env_items: tuple
    withheld_secret_names: tuple
    declared_permissions: TokenPermissions
    permissions: TokenPermissions
    permissions_capped: bool
    reasons: tuple

    @property
    def env(self) -> dict:
        return dict(self.env_items)

    @property
    def secret_names(self) -> tuple:
        return tuple(name for name, _value in self.env_items)

    @property
    def secrets_withheld(self) -> bool:
        return bool(self.withheld_secret_names)

    @property
    def token_read_only(self) -> bool:
        return self.permissions.is_read_only

    @property
    def summary(self) -> str:
        """The plan in one plain sentence."""
        if self.is_fork:
            text = (f"Fork pull request ({self.head_repository} "
                    f"into {self.base_repository}): no secrets "
                    "are injected and the token is read-only.")
            if self.permissions_capped:
                text += (" The declared permissions asked for "
                         "write and were capped to read.")
            return text
        if self.event == "pull_request":
            return ("Same-repository pull request: secrets and "
                    "the token follow the workflow's declared "
                    "permissions (read-only when undeclared).")
        return (f"A {self.event} run on {self.base_repository}: "
                "not a fork pull request, so the fork rule "
                "does not apply.")


def _judged_secret_env(secret_env: object) -> dict:
    """Judge the mapping a caller hands the
    scheduler as S-319's resolved environment:
    a mapping of environment names to text
    values, or nothing. Anything else is refused
    ``fork_safety_invalid`` -- the scheduler
    judges what it is handed rather than trusting
    it, exactly as S-314 resolves dispatch inputs."""
    if secret_env is None:
        return {}
    if not isinstance(secret_env, dict):
        raise _invalid(
            "The secret environment is a mapping of names "
            "to values (S-319's resolved env).")
    env: dict = {}
    for name, value in secret_env.items():
        if not isinstance(name, str) or not _ENV_RE.match(name):
            raise _invalid(
                f"Secret environment: {name!r} is not an "
                "environment variable name.")
        if not isinstance(value, str):
            raise _invalid(
                f"Secret environment: the value of {name} "
                "is text.")
        env[name] = value
    return env


def _judged_secret_names(secret_names: object) -> tuple:
    if secret_names is None:
        return ()
    if isinstance(secret_names, (str, bytes)) \
            or not isinstance(secret_names, (list, tuple)):
        raise _invalid(
            "Secret names: a list of environment variable "
            "names.")
    names: list = []
    for name in secret_names:
        if not isinstance(name, str) or not _ENV_RE.match(name):
            raise _invalid(
                f"Secret names: {name!r} is not an "
                "environment variable name.")
        if name not in names:
            names.append(name)
    return tuple(names)


def schedule_dispatch(request: RunRequest,
                      secret_env: object = None,
                      secret_names: object = None) -> DispatchPlan:
    """THE scheduler judgement (S-320): place one
    run. The event is judged against S-314's
    vocabulary (``fork_event_unknown``), the
    repositories canonicalised, the fork question
    answered from event + head/base alone, and
    the plan built under the rule: a fork run's
    plan carries an empty secret environment
    (every handed value dropped, every handed
    name recorded as withheld) and read-only
    token permissions; any other run's plan
    carries the handed environment whole and
    the declared permissions as declared. Pure:
    the same request always plans the same, and
    nothing is recorded by the planning."""
    if not isinstance(request, RunRequest):
        raise _invalid("The scheduler judges a RunRequest.")
    event = request.event
    if not isinstance(event, str) or event not in EVENT_KINDS:
        raise ForkSafetyError(
            "fork_event_unknown",
            f"Unknown run event {event!r}; the events are: "
            f"{', '.join(EVENT_KINDS)}.")
    base = canonical_repo(request.base_repository,
                          "base repository")
    head_raw = request.head_repository or ""
    head = canonical_repo(head_raw, "head repository") \
        if head_raw else base
    is_fork = event == "pull_request" and head != base
    declared = parse_permissions(request.declared_permissions)
    granted = cap_to_read_only(declared) if is_fork else declared
    capped = bool(is_fork and granted != declared)
    env = _judged_secret_env(secret_env)
    extra_names = _judged_secret_names(secret_names)
    if is_fork:
        withheld = tuple(sorted(set(env) | set(extra_names)))
        env_items: tuple = ()
        reasons = ["fork_pull_request", "no_secrets",
                   "read_only_token"]
        if capped:
            reasons.append("permissions_capped")
    else:
        withheld = ()
        env_items = tuple(sorted(env.items()))
        if event == "pull_request":
            reasons = ["same_repository_pull_request"]
        else:
            reasons = ["not_a_pull_request"]
    return DispatchPlan(
        event=event, base_repository=base,
        head_repository=head if event == "pull_request" else base,
        is_fork=is_fork, env_items=env_items,
        withheld_secret_names=withheld,
        declared_permissions=declared, permissions=granted,
        permissions_capped=capped, reasons=tuple(reasons))

def resolve_dispatch_env(secrets_store: object,
                         request: RunRequest) -> DispatchPlan:
    """The dispatch road (S-320 over S-319):
    schedule one run, resolving its secrets from
    the store when -- and only when -- the run
    may carry them. A fork run is planned from
    the request alone: the store is never
    consulted, no value is decrypted, and no
    instance key is needed, so a fork dispatch
    cannot fail (or leak) for want of a key. Any
    other run resolves through the store's own
    ``resolve_env`` for the base repository and
    is planned with exactly that environment."""
    probe = schedule_dispatch(request)
    if probe.is_fork:
        return schedule_dispatch(
            request,
            secret_names=_store_secret_names(
                secrets_store, probe.base_repository))
    resolve = getattr(secrets_store, "resolve_env", None)
    if not callable(resolve):
        raise _invalid(
            "The secrets store offers no resolve_env road "
            "(S-319).")
    env = resolve(probe.base_repository)
    return schedule_dispatch(request, secret_env=env)


def _store_secret_names(secrets_store: object,
                        repo_target: str) -> tuple:
    """The names a fork run withholds, read from
    the store's names-only face when it offers
    one (S-319's ``secret_names_for_repo`` --
    names, never values, no key needed). A store
    without that face withholds an unnamed set:
    the plan still carries no secret, it merely
    cannot name what it did not take."""
    names_fn = getattr(secrets_store, "secret_names_for_repo", None)
    if not callable(names_fn):
        return ()
    return tuple(names_fn(repo_target))


def assignment_env_names(requested: object,
                         plan: DispatchPlan) -> tuple:
    """The ``env_names`` an S-316 assignment for
    this plan may carry: the requested names in
    order, judged as environment names with
    duplicates refused -- minus, for a fork run,
    every withheld secret name, so the assignment
    never tells a runner to expect a secret the
    dispatch will not deliver. Literal (non-
    secret) names stand in both worlds."""
    if not isinstance(plan, DispatchPlan):
        raise _invalid("Assignment names are judged "
                       "against a DispatchPlan.")
    if isinstance(requested, (str, bytes)) \
            or not isinstance(requested, (list, tuple)):
        raise _invalid("Assignment env_names: a list of "
                       "variable names.")
    names: list = []
    for name in requested:
        if not isinstance(name, str) or not _ENV_RE.match(name):
            raise _invalid(
                f"Assignment env_names: {name!r} is not a "
                "variable name.")
        if name in names:
            raise _invalid(
                f"Assignment env_names: {name!r} is named "
                "twice.")
        names.append(name)
    if plan.is_fork:
        withheld = set(plan.withheld_secret_names)
        names = [n for n in names if n not in withheld]
    return tuple(names)


def plan_to_dict(plan: DispatchPlan) -> dict:
    """The plan's programmatic face: names,
    permissions and reasons only -- never a
    secret value, so the dict is safe to log,
    render and store beside the run."""
    if not isinstance(plan, DispatchPlan):
        raise _invalid("plan_to_dict judges a DispatchPlan.")
    return {
        "event": plan.event,
        "base_repository": plan.base_repository,
        "head_repository": plan.head_repository,
        "is_fork": plan.is_fork,
        "secret_names": list(plan.secret_names),
        "withheld_secret_names": list(plan.withheld_secret_names),
        "secrets_withheld": plan.secrets_withheld,
        "declared_permissions": plan.declared_permissions.to_dict(),
        "permissions": plan.permissions.to_dict(),
        "permissions_capped": plan.permissions_capped,
        "token_read_only": plan.token_read_only,
        "reasons": list(plan.reasons),
        "summary": plan.summary,
    }


# ------------------------------------------------------------------
# The audit: the rule checked against the live instance.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class ForkSafetyAudit:
    """The scheduler's rule checked against one
    live instance: the rule's own integrity (the
    default is read-only, the level vocabulary
    is S-313's three words), the schema unmoved
    at 132 (this slice mints no
    migration), the taxonomy at the standing 138, and
    every fork-shaped workflow surface found in
    the schema or the taxonomy. The rule stands
    cleanly only while it lives in this code and
    nowhere else: no table, column or audit event
    carries a fork dispatch surface. Names are
    fork-and-workflow scoped on purpose: the
    bare fork machinery (S-055's fork lineage,
    the ``repo.fork`` event) lawfully exists and
    is not this slice's to police."""
    defaults_ok: bool
    levels_ok: bool
    schema_version: int
    schema_ok: bool
    events_ok: bool
    tables_scanned: int
    columns_scanned: int
    events_scanned: int
    offending_tables: tuple
    offending_columns: tuple
    offending_events: tuple

    @property
    def stands_cleanly(self) -> bool:
        return (self.defaults_ok and self.levels_ok
                and self.schema_ok and self.events_ok
                and not self.offending_tables
                and not self.offending_columns
                and not self.offending_events)


_SURFACE_WORDS = ("workflow", "dispatch", "schedule",
                  "scheduler", "run")
_EVENT_WORDS = ("workflow", "dispatch", "ci")


def _fork_surface(name: str, words: tuple) -> bool:
    text = name.lower()
    return "fork" in text and any(word in text for word in words)


def audit_fork_pr_safety(conn: sqlite3.Connection) -> ForkSafetyAudit:
    """Check the fork rule against the live
    instance: the defaults and vocabulary are
    the strict ones, the schema is exactly
    132, the taxonomy is exactly the
    standing 138, and no table, column or audit
    event carries a fork workflow surface --
    one arriving ahead of its slice would be
    the rule bypassed by a back door. Pure read."""
    from .db import schema_version as _schema_version
    version = _schema_version(conn)
    events_ok = (len(taxonomy.AUDIT_EVENTS) == 138
                 and len(taxonomy.AUTH_EVENTS) == 33
                 and len(taxonomy.REPO_EVENTS) == 92
                 and len(taxonomy.ADMIN_EVENTS) == 13)
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    offending_tables: list = []
    offending_columns: list = []
    columns_scanned = 0
    for table in tables:
        if _fork_surface(table, _SURFACE_WORDS):
            offending_tables.append(table)
        safe = table.replace('"', '""')
        for row in conn.execute(
                f'PRAGMA table_info("{safe}")').fetchall():
            columns_scanned += 1
            if _fork_surface(str(row[1]), _SURFACE_WORDS):
                offending_columns.append(f"{table}.{row[1]}")
    events = sorted(taxonomy.AUDIT_EVENTS)
    offending_events = [
        e for e in events if _fork_surface(e, _EVENT_WORDS)]
    return ForkSafetyAudit(
        defaults_ok=DEFAULT_PERMISSIONS.is_read_only
        and DEFAULT_PERMISSIONS == parse_permissions(None),
        levels_ok=tuple(PERMISSION_LEVELS)
        == ("none", "read", "write")
        and set(PERMISSION_VALUES) == set(PERMISSION_LEVELS),
        schema_version=version, schema_ok=version == 137,
        events_ok=events_ok,
        tables_scanned=len(tables),
        columns_scanned=columns_scanned,
        events_scanned=len(events),
        offending_tables=tuple(offending_tables),
        offending_columns=tuple(offending_columns),
        offending_events=tuple(offending_events))


def render_fork_pr_safety_page(
        plan: DispatchPlan | None = None,
        audit: ForkSafetyAudit | None = None) -> str:
    """The fork rule, rendered: the rule said in
    words, one plan's outcome when a plan rides
    along (names and permissions only -- a secret
    value is rendered by no page), and the checked
    proof when an audit rides along -- every value
    escaped, the state said in words, never
    colour-only."""
    parts = [
        "<h1>Fork-PR safety (S-320)</h1>",
        "<p>A workflow run from a <strong>fork pull "
        "request</strong> -- a pull request whose head "
        "repository is not its base repository -- runs "
        "with <strong>no secrets</strong> and a "
        "<strong>read-only token</strong>. The rule is "
        "enforced by the scheduler when the run is "
        "placed: the dispatch carries an empty secret "
        "environment (the secrets store is not even "
        "consulted), and every write permission the "
        "workflow declared is capped to read. Any "
        "other run carries its declared permissions "
        "as declared -- read-only when none are "
        "declared.</p>",
        "<h2>For maintainers</h2>",
        "<p>There is no privileged fork trigger. To "
        "test a fork's change with secrets, merge it, "
        "or dispatch the workflow by hand on the base "
        "repository -- both run the base's own "
        "reviewed code.</p>",
    ]
    if plan is not None:
        parts.append("<h2>One scheduled run</h2>")
        parts.append(
            f"<p>{escape_html_text(plan.summary)}</p>")
        parts.append(
            "<p>Declared permissions: "
            f"{escape_html_text(describe_permissions(plan.declared_permissions))}; "
            "granted permissions: "
            f"{escape_html_text(describe_permissions(plan.permissions))}; "
            "secrets carried: "
            f"{escape_html_text(', '.join(plan.secret_names) or 'none')}; "
            "secrets withheld: "
            f"{escape_html_text(', '.join(plan.withheld_secret_names) or 'none')}.</p>")
    if audit is not None:
        state = ("stands cleanly" if audit.stands_cleanly
                 else "does NOT stand cleanly")
        parts.append("<h2>Checked against this instance</h2>")
        parts.append(
            f"<p>The fork rule {escape_html_text(state)}: "
            f"schema {audit.schema_version}, "
            f"{audit.tables_scanned} tables and "
            f"{audit.columns_scanned} columns scanned, "
            f"{audit.events_scanned} audit events scanned; "
            f"offending tables: "
            f"{escape_html_text(', '.join(audit.offending_tables) or 'none')}; "
            f"offending columns: "
            f"{escape_html_text(', '.join(audit.offending_columns) or 'none')}; "
            f"offending events: "
            f"{escape_html_text(', '.join(audit.offending_events) or 'none')}.</p>")
    return "\n".join(parts)
