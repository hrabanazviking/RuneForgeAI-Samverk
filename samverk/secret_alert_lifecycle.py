"""Secret alert lifecycle (S-294).

Roadmap S-294: Secret alert lifecycle -- open ->
resolved (revoked / false positive / used-in-test)
with resolver and reason recorded; reopening
supported.

S-291's scan on push stands every finding as one
open row in migration 115's ``secret_alerts`` and
stops there: an alert could be born but never
answered. This slice is the answering -- the whole
life of an alert after its birth:

- **Open -> resolved, in three named kinds.** A
  resolution is one of ``revoked`` (the credential
  is dead: rotated or revoked at its provider),
  ``false_positive`` (the detector named a shape
  that is not a live secret) or ``used_in_test``
  (the value exists to be found: a fixture, a
  test, a published example). No other kind
  resolves an alert, and no resolution stands
  without its kind: ``resolution_invalid`` names
  the three. An alert that was reopened resolves
  on exactly the same terms as one freshly open.
- **Resolver and reason, always recorded.** The
  standing resolution lives on the alert row
  itself (migration 117's columns): the kind, the
  resolver's account id and username, when, and
  the resolver's stated reason in their own words.
  A resolve or a reopen without a stated reason
  is refused ``reason_required``; one past the
  stated cap is ``reason_too_long``. There is no
  default reason and no silent transition: a
  lifecycle act without its reason is exactly the
  unaccountable act this slice refuses to be.
- **Reopening supported.** A resolved alert may be
  reopened by the same permitted rungs, with a
  stated reason; it then stands ``reopened`` --
  the state S-291's vocabulary already held -- and
  its standing resolution is cleared whole, so no
  surface ever shows a stale resolver against a
  live alert. Resolving an already-resolved alert
  is refused ``alert_already_resolved``; reopening
  one that stands open or reopened is refused
  ``alert_not_resolved``; an unknown alert id is
  ``alert_not_found``.
- **Permitted roles only.** A person's standing is
  their S-190 ``PermissionEngine`` role in the
  repository, never re-derived here. The permitted
  rungs are ``admin`` and ``maintain`` -- the two
  rungs that already answer for a repository's
  safety, the same rungs S-293 trusts at the
  bypass door. ``write``, ``triage``, ``read`` and
  no access are refused ``lifecycle_not_permitted``
  with a sentence naming the actor, the role they
  hold (or that they hold none), the repository
  and the permitted rungs. An anonymous actor
  moves no alert: a lifecycle act is a person's
  act, recorded under their account. The pure
  check (``decide_transition`` / the store's
  ``judge``) writes nothing.
- **Every transition is recorded, in the same
  transaction.** Migration 117's
  ``secret_alert_events`` is the alert's own
  lifecycle record: one row per transition naming
  the action (``resolve`` / ``reopen``), the state
  it moved from and to, the resolution kind (on a
  resolve), the actor, their role and its source,
  the stated reason and when -- written inside
  the same ``with conn`` transaction that moves
  the alert row, so the record can never claim a
  transition the alert does not show, nor the
  alert move without its record. A resolve, a
  reopen and a re-resolve stand as three rows;
  nothing is ever edited or deleted there.
- **Unwitnessed in the audit taxonomy -- said
  plainly.** No new taxonomy event: 134 stand
  (33 auth / 88 repo / 13 admin), and the battery
  proves the audit log does not move across a
  resolve, a reopen and a re-resolve. The choice
  follows the neighbouring law: S-291's scanning
  is unwitnessed (a judgement over an already-
  witnessed push), S-284's answer marks stand as
  events on the thread's own timeline rather than
  audit rows, and S-214's / S-224's personal state
  changes claim no event. A lifecycle transition
  changes no code, lands no push and lets no
  secret in -- unlike S-293's bypass, which does
  land one and is witnessed for exactly that
  reason. The alert's witness is its own events
  table, complete and in-transaction.
- **Never the secret.** An alert, its resolution
  and its events carry where and what shape --
  path, detector, line, redacted preview,
  fingerprint -- exactly as S-291 stored them.
  The matched text is never read, stored or
  rendered by this module; the rendered pages and
  ``to_dict`` surfaces are grepped for a planted
  secret in the battery.
- **Reads follow the repository.** The lifecycle
  read (one alert with its standing resolution,
  its event history, per-state counts) answers to
  anyone the permission engine resolves to any
  role in the repository; a stranger to a private
  repository gets the uniform ``repo_not_found``
  before any alert position is named, exactly as
  at S-293's door. S-291's own scan and alert
  reads are untouched and keep their own law.

Storage is migration 117's resolution columns on
``secret_alerts`` plus the ``secret_alert_events``
table (schema 116 -> 117 on the banked line;
renumbered from 116 at banking, S-293's migration
116 for its bypass table banking first in roadmap
order, and nothing else here is renumbered).
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .permission_engine import PermissionEngine
from .repositories import RepositoryError, RepositoryStore
from .team_permissions import role_word

__all__ = [
    "ALERT_NOT_FOUND", "ALERT_ALREADY_RESOLVED",
    "ALERT_NOT_RESOLVED", "LIFECYCLE_NOT_PERMITTED",
    "MAX_REASON_CHARS", "PERMITTED_ROLES",
    "REASON_REQUIRED", "REASON_TOO_LONG",
    "RESOLUTION_INVALID", "RESOLUTIONS",
    "RESOLUTION_WORDS", "LifecycleAlert",
    "LifecycleDecision", "LifecycleError",
    "LifecycleEvent", "SecretAlertLifecycleStore",
    "decide_transition", "render_alert_page",
    "render_alerts_page", "resolution_word",
    "validate_reason", "validate_resolution",
]

#: The three resolution kinds the roadmap names,
#: as stored slugs. Their read words are below.
RESOLUTIONS = frozenset(
    {"revoked", "false_positive", "used_in_test"})

RESOLUTION_WORDS = {
    "revoked": "revoked",
    "false_positive": "false positive",
    "used_in_test": "used in test",
}

#: The rungs that may move an alert: the two that
#: already answer for a repository's safety.
PERMITTED_ROLES = frozenset({"admin", "maintain"})

#: A stated reason is a sentence a person owns,
#: not an essay: the cap is said, never silent.
MAX_REASON_CHARS = 500

LIFECYCLE_NOT_PERMITTED = "lifecycle_not_permitted"
REASON_REQUIRED = "reason_required"
REASON_TOO_LONG = "reason_too_long"
RESOLUTION_INVALID = "resolution_invalid"
ALERT_NOT_FOUND = "alert_not_found"
ALERT_ALREADY_RESOLVED = "alert_already_resolved"
ALERT_NOT_RESOLVED = "alert_not_resolved"

#: The states an alert stands in (S-291's own
#: vocabulary, migration 115). ``open`` and
#: ``reopened`` are the live states a resolve may
#: answer; ``resolved`` is the only state a reopen
#: may answer.
LIVE_STATES = frozenset({"open", "reopened"})
ALERT_STATES = frozenset({"open", "resolved", "reopened"})


class LifecycleError(RepositoryError):
    """A secret-alert lifecycle error: a
    RepositoryError carrying `.reason`, in the
    house shape."""


def resolution_word(resolution: object) -> str:
    """A resolution kind said in words a person
    reads; an unknown kind is refused loudly."""
    if resolution not in RESOLUTION_WORDS:
        raise LifecycleError(
            RESOLUTION_INVALID,
            f"Unknown resolution kind: {resolution!r}. "
            f"An alert resolves as revoked, a false "
            f"positive, or used in test -- no other "
            f"kind stands.")
    return RESOLUTION_WORDS[resolution]  # type: ignore[index]


def validate_resolution(resolution: object) -> str:
    """The resolution kind, cleaned -- or a named
    refusal naming the three kinds that stand."""
    if not isinstance(resolution, str) \
            or resolution not in RESOLUTIONS:
        raise LifecycleError(
            RESOLUTION_INVALID,
            f"Unknown resolution kind: {resolution!r}. "
            f"An alert resolves as 'revoked' (the "
            f"credential is dead), 'false_positive' "
            f"(the shape is not a live secret) or "
            f"'used_in_test' (the value exists to be "
            f"found) -- no other kind stands.")
    return resolution


def validate_reason(reason: object) -> str:
    """The stated reason, cleaned -- or a named
    refusal. A transition without a reason is
    refused, never defaulted."""
    if not isinstance(reason, str) or not reason.strip():
        raise LifecycleError(
            REASON_REQUIRED,
            "A secret-alert transition needs a stated "
            "reason: the actor's own words for why "
            "this alert moves. A transition without "
            "its reason is an unaccountable act, and "
            "this slice builds none.")
    cleaned = reason.strip()
    if len(cleaned) > MAX_REASON_CHARS:
        raise LifecycleError(
            REASON_TOO_LONG,
            f"A lifecycle reason is at most "
            f"{MAX_REASON_CHARS} characters; this one "
            f"runs {len(cleaned)}. Say the reason "
            f"plainly and briefly.")
    return cleaned


# --- the pure judgement --------------------------------


@dataclass(frozen=True)
class LifecycleDecision:
    """The pure judgement: may this person move
    this alert, holding this role, in this way, for
    this stated reason? A refusal carries its named
    code and its sentence. `words` says the whole
    position in plain text. Pure: writes nothing."""
    may_move: bool
    action: str            # resolve | reopen
    role: str | None
    source: str
    code: str              # "" when may_move
    reason: str            # the refusal sentence; "" when may_move
    words: str


def _permitted_words() -> str:
    return ", ".join(
        role_word(r) for r in ("maintain", "admin"))


def decide_transition(*, action: str, role: str | None,
                      source: str = "none",
                      actor: str | None = None,
                      full_name: str = "",
                      alert_state: str = "open",
                      resolution: object = None,
                      reason: object = "") -> LifecycleDecision:
    """Judge one lifecycle ask, in the house order:
    the state the alert stands in first (a move the
    alert's own state forbids is refused before any
    person is judged), then the person's rung, then
    -- on a resolve -- the resolution kind, then the
    stated reason."""
    who = f"'{actor}'" if actor else "an anonymous actor"
    verb = "resolve" if action == "resolve" else "reopen"
    if action == "resolve" and alert_state == "resolved":
        return LifecycleDecision(
            may_move=False, action=action, role=role,
            source=source, code=ALERT_ALREADY_RESOLVED,
            reason=(
                f"This alert in {full_name} already "
                f"stands resolved; it cannot be "
                f"resolved again. Reopen it first if "
                f"the resolution no longer holds."),
            words=(
                f"The alert in {full_name} already "
                f"stands resolved: resolving it again "
                f"would overwrite the standing "
                f"resolution and its record."))
    if action == "reopen" and alert_state != "resolved":
        return LifecycleDecision(
            may_move=False, action=action, role=role,
            source=source, code=ALERT_NOT_RESOLVED,
            reason=(
                f"This alert in {full_name} stands "
                f"{alert_state}, not resolved; there "
                f"is no resolution to reopen. Only a "
                f"resolved alert reopens."),
            words=(
                f"The alert in {full_name} stands "
                f"{alert_state}: reopening answers a "
                f"resolution, and this alert has none "
                f"standing."))
    if role not in PERMITTED_ROLES:
        held = (f"holds the {role_word(role)} role"
                if role else "holds no role")
        return LifecycleDecision(
            may_move=False, action=action, role=role,
            source=source, code=LIFECYCLE_NOT_PERMITTED,
            reason=(
                f"Secret-alert {verb} in {full_name} "
                f"was refused: {who} {held}, and only "
                f"the permitted roles may move a "
                f"secret alert ({_permitted_words()}). "
                f"Ask a repository maintainer to act, "
                f"or be granted a permitted role "
                f"first."),
            words=(
                f"{who} may not {verb} a secret alert "
                f"in {full_name}: only "
                f"{_permitted_words()} may, and every "
                f"transition records its actor and "
                f"reason."))
    if action == "resolve":
        try:
            validate_resolution(resolution)
        except LifecycleError as exc:
            return LifecycleDecision(
                may_move=False, action=action, role=role,
                source=source, code=exc.reason,
                reason=str(exc),
                words=(
                    f"{who} may not resolve the alert "
                    f"in {full_name} under that kind: "
                    f"an alert resolves as revoked, a "
                    f"false positive, or used in test, "
                    f"and the kind is part of the "
                    f"record."))
    try:
        validate_reason(reason)
    except LifecycleError as exc:
        return LifecycleDecision(
            may_move=False, action=action, role=role,
            source=source, code=exc.reason,
            reason=str(exc),
            words=(
                f"{who} may not {verb} the alert in "
                f"{full_name} without a stated reason: "
                f"every transition records its actor "
                f"and reason, and the reason is part "
                f"of the record."))
    kind_words = (
        f" as {resolution_word(resolution)}"
        if action == "resolve" else "")
    return LifecycleDecision(
        may_move=True, action=action, role=role,
        source=source, code="", reason="",
        words=(
            f"{who} may {verb} the alert in "
            f"{full_name} as {role_word(role)}{kind_words}: "
            f"the transition will stand on the "
            f"alert's own lifecycle record with its "
            f"reason."))


# --- the records -----------------------------------------


@dataclass(frozen=True)
class LifecycleAlert:
    """One secret alert with its standing lifecycle:
    S-291's alert shape plus, while it stands
    resolved, the resolution kind, the resolver and
    the stated reason. Never the secret."""
    id: int
    repo_id: int
    full_name: str
    scan_id: int
    commit_oid: str
    path: str
    blob_oid: str
    source: str
    detector_id: str
    line: int
    column: int
    redacted: str
    fingerprint: str
    state: str
    created_at: int
    resolution: str        # "" unless resolved
    resolved_by_id: int | None
    resolved_by: str       # "" unless resolved
    resolved_at: int | None
    resolution_reason: str  # "" unless resolved

    @property
    def is_resolved(self) -> bool:
        return self.state == "resolved"

    def resolution_words(self) -> str:
        """The standing position in one sentence, in
        words -- never colour alone."""
        if self.state == "resolved":
            return (
                f"resolved as {resolution_word(self.resolution)} "
                f"by {self.resolved_by}: "
                f"{self.resolution_reason}")
        if self.state == "reopened":
            return ("reopened -- the earlier resolution "
                    "no longer stands; this alert is "
                    "live again")
        return "open -- no resolution stands"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "repository": self.full_name,
            "scan_id": self.scan_id,
            "commit": self.commit_oid,
            "path": self.path,
            "blob": self.blob_oid,
            "source": self.source,
            "detector_id": self.detector_id,
            "line": self.line,
            "column": self.column,
            "redacted": self.redacted,
            "fingerprint": self.fingerprint,
            "state": self.state,
            "created_at": self.created_at,
            "resolution": self.resolution or None,
            "resolved_by_id": self.resolved_by_id,
            "resolved_by": self.resolved_by or None,
            "resolved_at": self.resolved_at,
            "resolution_reason":
                self.resolution_reason or None,
        }


@dataclass(frozen=True)
class LifecycleEvent:
    """One standing transition on an alert's own
    lifecycle record: who moved it, from what state
    to what state, under what kind (on a resolve),
    and why, in their own words."""
    id: int
    alert_id: int
    repo_id: int
    action: str            # resolve | reopen
    from_state: str
    to_state: str
    resolution: str        # "" on a reopen
    actor_id: int
    actor_username: str
    role: str
    role_source: str
    reason: str
    created_at: int

    def words(self) -> str:
        if self.action == "resolve":
            return (
                f"{self.actor_username} resolved this "
                f"alert as {resolution_word(self.resolution)}: "
                f"{self.reason}")
        return (
            f"{self.actor_username} reopened this "
            f"alert: {self.reason}")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "alert_id": self.alert_id,
            "action": self.action,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "resolution": self.resolution or None,
            "actor_id": self.actor_id,
            "actor": self.actor_username,
            "role": self.role,
            "role_source": self.role_source,
            "reason": self.reason,
            "created_at": self.created_at,
        }


def _row_to_alert(row, full_name: str) -> LifecycleAlert:
    return LifecycleAlert(
        id=int(row["id"]), repo_id=int(row["repo_id"]),
        full_name=full_name, scan_id=int(row["scan_id"]),
        commit_oid=row["commit_oid"], path=row["path"],
        blob_oid=row["blob_oid"], source=row["source"],
        detector_id=row["detector_id"],
        line=int(row["line"]), column=int(row["column"]),
        redacted=row["redacted"],
        fingerprint=row["fingerprint"], state=row["state"],
        created_at=int(row["created_at"]),
        resolution=row["resolution"] or "",
        resolved_by_id=row["resolved_by_id"],
        resolved_by=row["resolved_by"] or "",
        resolved_at=row["resolved_at"],
        resolution_reason=row["resolution_reason"] or "")


def _row_to_event(row) -> LifecycleEvent:
    return LifecycleEvent(
        id=int(row["id"]), alert_id=int(row["alert_id"]),
        repo_id=int(row["repo_id"]), action=row["action"],
        from_state=row["from_state"],
        to_state=row["to_state"],
        resolution=row["resolution"] or "",
        actor_id=int(row["actor_id"]),
        actor_username=row["actor_username"],
        role=row["role"], role_source=row["role_source"],
        reason=row["reason"],
        created_at=int(row["created_at"]))


# --- the store -------------------------------------------


class SecretAlertLifecycleStore:
    """The life of S-291's secret alerts after their
    birth: resolve, reopen, and the recorded reads."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 accounts: AccountStore,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._now = time_fn
        self._engine = PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)

    # -- resolution ----------------------------------------

    def _resolve_repo(self, viewer: User | None, owner, repo,
                      *, any_role: bool):
        """(repository, resolution). A missing
        repository answers `repo_not_found`; so does
        a non-public repository the viewer holds no
        role in, before any alert position is named.
        With `any_role`, holding any role is enough
        to stand inside the door (the read law); the
        act law judges the rung itself afterwards."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise LifecycleError(
                "repo_not_found", "No such repository.")
        resolution = self._engine.resolve(viewer, current)
        if resolution.role is None                 and current.visibility != "public":
            raise LifecycleError(
                "repo_not_found", "No such repository.")
        if any_role and resolution.role is None:
            raise LifecycleError(
                "repo_not_found", "No such repository.")
        return current, resolution

    def _alert_row(self, repo_id: int, alert_id: int):
        row = self._conn.execute(
            "SELECT * FROM secret_alerts WHERE id = ?"
            " AND repo_id = ?", (alert_id, repo_id)).fetchone()
        if row is None:
            raise LifecycleError(
                ALERT_NOT_FOUND,
                f"No secret alert {alert_id} stands in "
                f"this repository.")
        return row

    # -- the pure check --------------------------------------

    def judge(self, actor: User | None, owner, repo,
              alert_id: int, *, action: str,
              resolution: object = None,
              reason: object = "") -> LifecycleDecision:
        """May this actor move this alert in this
        way? A pure read: writes nothing, records
        nothing."""
        current, resolved = self._resolve_repo(
            actor, owner, repo, any_role=False)
        row = self._alert_row(current.id, alert_id)
        return decide_transition(
            action=action, role=resolved.role,
            source=resolved.source,
            actor=actor.username if actor is not None else None,
            full_name=current.full_name,
            alert_state=row["state"],
            resolution=resolution, reason=reason)

    # -- the acts ----------------------------------------------

    def _transition(self, actor: User | None, owner, repo,
                    alert_id: int, *, action: str,
                    resolution: object = None,
                    reason: object = "") -> LifecycleAlert:
        current, resolved = self._resolve_repo(
            actor, owner, repo, any_role=False)
        row = self._alert_row(current.id, alert_id)
        judgement = decide_transition(
            action=action, role=resolved.role,
            source=resolved.source,
            actor=actor.username if actor is not None else None,
            full_name=current.full_name,
            alert_state=row["state"],
            resolution=resolution, reason=reason)
        if not judgement.may_move:
            raise LifecycleError(judgement.code, judgement.reason)
        cleaned_reason = validate_reason(reason)
        created_at = int(self._now())
        from_state = row["state"]
        if action == "resolve":
            kind = validate_resolution(resolution)
            to_state = "resolved"
            with self._conn:
                self._conn.execute(
                    "UPDATE secret_alerts SET state = 'resolved',"
                    " resolution = ?, resolved_by_id = ?,"
                    " resolved_by = ?, resolved_at = ?,"
                    " resolution_reason = ? WHERE id = ?",
                    (kind, actor.id, actor.username, created_at,
                     cleaned_reason, alert_id))
                self._conn.execute(
                    "INSERT INTO secret_alert_events ("
                    " alert_id, repo_id, action, from_state,"
                    " to_state, resolution, actor_id,"
                    " actor_username, role, role_source,"
                    " reason, created_at)"
                    " VALUES (?, ?, 'resolve', ?, 'resolved',"
                    " ?, ?, ?, ?, ?, ?, ?)",
                    (alert_id, current.id, from_state, kind,
                     actor.id, actor.username, resolved.role,
                     resolved.source, cleaned_reason, created_at))
        else:
            to_state = "reopened"
            with self._conn:
                self._conn.execute(
                    "UPDATE secret_alerts SET state = 'reopened',"
                    " resolution = '', resolved_by_id = NULL,"
                    " resolved_by = '', resolved_at = NULL,"
                    " resolution_reason = '' WHERE id = ?",
                    (alert_id,))
                self._conn.execute(
                    "INSERT INTO secret_alert_events ("
                    " alert_id, repo_id, action, from_state,"
                    " to_state, resolution, actor_id,"
                    " actor_username, role, role_source,"
                    " reason, created_at)"
                    " VALUES (?, ?, 'reopen', ?, 'reopened',"
                    " '', ?, ?, ?, ?, ?, ?)",
                    (alert_id, current.id, from_state,
                     actor.id, actor.username, resolved.role,
                     resolved.source, cleaned_reason, created_at))
        return self._get_alert(current, alert_id)

    def resolve_alert(self, actor: User | None, owner, repo,
                      alert_id: int, *,
                      resolution: object = None,
                      reason: object = "") -> LifecycleAlert:
        """Resolve one live alert under one of the
        three named kinds, with the resolver and the
        stated reason recorded, and the transition
        standing on the alert's lifecycle record --
        all before this answers."""
        return self._transition(
            actor, owner, repo, alert_id, action="resolve",
            resolution=resolution, reason=reason)

    def reopen_alert(self, actor: User | None, owner, repo,
                     alert_id: int, *,
                     reason: object = "") -> LifecycleAlert:
        """Reopen one resolved alert, with the actor
        and the stated reason recorded and the
        standing resolution cleared whole -- all
        before this answers."""
        return self._transition(
            actor, owner, repo, alert_id, action="reopen",
            reason=reason)

    # -- the reads ----------------------------------------------

    def _get_alert(self, current, alert_id: int) -> LifecycleAlert:
        row = self._alert_row(current.id, alert_id)
        return _row_to_alert(row, current.full_name)

    def get_alert(self, viewer: User | None, owner, repo,
                  alert_id: int) -> LifecycleAlert:
        """One alert with its standing lifecycle."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        return self._get_alert(current, alert_id)

    def list_alerts(self, viewer: User | None, owner, repo, *,
                    state: str | None = None,
                    limit: int = 100) -> tuple:
        """Newest first; optionally one lifecycle
        state (`open` / `resolved` / `reopened`)."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        if state is not None and state not in ALERT_STATES:
            raise LifecycleError(
                "state_invalid",
                f"Unknown alert state: {state!r}")
        clamped = max(1, min(int(limit), 500))
        if state is None:
            rows = self._conn.execute(
                "SELECT * FROM secret_alerts WHERE repo_id = ?"
                " ORDER BY id DESC LIMIT ?",
                (current.id, clamped)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM secret_alerts WHERE repo_id = ?"
                " AND state = ? ORDER BY id DESC LIMIT ?",
                (current.id, state, clamped)).fetchall()
        return tuple(
            _row_to_alert(r, current.full_name) for r in rows)

    def count_alerts(self, viewer: User | None, owner, repo, *,
                     state: str | None = None) -> int:
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        if state is None:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM secret_alerts"
                " WHERE repo_id = ?", (current.id,)).fetchone()
        else:
            if state not in ALERT_STATES:
                raise LifecycleError(
                    "state_invalid",
                    f"Unknown alert state: {state!r}")
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM secret_alerts"
                " WHERE repo_id = ? AND state = ?",
                (current.id, state)).fetchone()
        return int(row["n"])

    def list_events(self, viewer: User | None, owner, repo,
                    alert_id: int) -> tuple:
        """The alert's lifecycle record, oldest first:
        every transition it has ever stood, unedited."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        self._alert_row(current.id, alert_id)
        rows = self._conn.execute(
            "SELECT * FROM secret_alert_events"
            " WHERE alert_id = ? AND repo_id = ?"
            " ORDER BY id", (alert_id, current.id)).fetchall()
        return tuple(_row_to_event(r) for r in rows)


# --- the page faces ----------------------------------------


def render_alert_page(alert: LifecycleAlert, events=(),
                      title: str = "Secret alert") -> str:
    """One alert's face: where and what shape, its
    standing lifecycle in words, and its recorded
    transitions -- never the secret."""
    rows = "".join(
        "<li>" + escape_html_text(e.words())
        + " (" + escape_html_text(e.role) + ", "
        + escape_html_text(e.from_state) + " -> "
        + escape_html_text(e.to_state) + ")</li>"
        for e in events)
    if not rows:
        rows = "<li>No lifecycle transitions yet.</li>"
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1><p>Alert in "
        + escape_html_text(alert.full_name)
        + ": " + escape_html_text(alert.path)
        + " @ " + escape_html_text(alert.commit_oid[:12])
        + " -- " + escape_html_text(alert.detector_id)
        + " (" + escape_html_text(alert.source) + ")"
        + ", line " + str(alert.line)
        + ": " + escape_html_text(alert.redacted)
        + ". State: " + escape_html_text(alert.state)
        + " -- " + escape_html_text(alert.resolution_words())
        + ".</p><ul>" + rows + "</ul></body></html>")


def render_alerts_page(alerts, title: str = "Secret alerts"
                       ) -> str:
    """The alerts face with each standing lifecycle
    said in words: places and shapes, never secrets."""
    rows = "".join(
        "<li>" + escape_html_text(a.path)
        + " @ " + escape_html_text(a.commit_oid[:12])
        + " -- " + escape_html_text(a.detector_id)
        + ", line " + str(a.line)
        + ": " + escape_html_text(a.redacted)
        + " [" + escape_html_text(a.state) + " -- "
        + escape_html_text(a.resolution_words()) + "]</li>"
        for a in alerts)
    if not rows:
        rows = "<li>No secret alerts.</li>"
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1><ul>" + rows + "</ul></body></html>")
