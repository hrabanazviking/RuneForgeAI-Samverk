"""Push-protection bypass (S-293).

Roadmap S-293: Push-protection bypass -- permitted
roles may bypass with a stated reason; the bypass
is an alert + audit event, visible to owners
(GitHub's honest pattern, adopted openly).

S-292's push protection refuses a push that carries
a detected secret, unconditionally and recording
nothing: a refusal is a gate veto, not a stored
act. But a refusal can be wrong for a push a
responsible person still judges safe -- a rotated
credential already revoked, a fixture that only
looks like a token, an incident fix that cannot
wait for the shape to be re-cut. GitHub's answer,
adopted here openly, is not a silent second door:
it is a bypass that is itself a witnessed act.
This slice is that door, and its laws are:

- **The bypass answers a refusal, and only a
  refusal.** The judgement it answers is S-292's
  `PushProtection` decision, reached through a
  lazy seam (below): a push protection allows is
  not bypassed -- there is nothing to bypass --
  and the attempt is refused `bypass_not_needed`.
  A refusal cut short by a cap (a walk that could
  not be proven clean) can be bypassed on the
  same terms as a finding: the bypasser takes the
  unproven history on their own witnessed word.
- **Permitted roles only.** A person's standing
  is their S-190 `PermissionEngine` role in the
  repository, never re-derived here. The
  permitted rungs are `admin` and `maintain` --
  the two rungs that already answer for a
  repository's safety. `write`, `triage`, `read`
  and no access are refused `bypass_not_permitted`
  with a sentence naming the actor, the role they
  hold (or that they hold none), the repository
  and the permitted rungs. An anonymous actor
  bypasses nothing: a bypass is a person's act,
  witnessed under their account.
- **A stated reason, always.** The reason is the
  bypasser's own words for why this refused push
  may land anyway. An absent, blank or non-text
  reason is refused `bypass_reason_required`; one
  past the stated cap is `bypass_reason_too_long`.
  There is no default reason and no silent form
  of this door: a bypass without its reason is
  exactly the hidden door this slice refuses to
  be.
- **Every bypass is an alert + an audit event --
  by construction.** A used bypass appends the
  audit event this slice claims --
  `repo.push_protection.bypass` (taxonomy 133 ->
  134: 33 auth / 88 repo / 13 admin) -- and writes
  one standing alert row in migration 116's
  `push_protection_bypasses`, carrying the
  audit row's sequence number. The alert and the
  audit detail name the repository, the actor,
  their role and its source, the stated reason,
  the refs the bypass covers, and each finding as
  file, pattern class, line and fingerprint.
  A store built without an audit log cannot use
  a bypass at all -- it fails closed with
  `bypass_audit_required`, because a bypass that
  cannot be witnessed must not happen. The pure
  check (`decide_bypass` / `judge`) writes and
  audits nothing.
- **Visible to owners.** Standing alerts are read
  through `list_bypasses` / `get_bypass`, which
  answer only to the `admin` rung -- the rung a
  repository's owners hold -- so the people who
  answer for the repository can always see who
  bypassed its protection, when, and why. A
  reader below that rung is refused
  `bypass_not_visible`; a stranger to a private
  repository gets the uniform `repo_not_found`
  before any bypass position is named.
- **The secret is never echoed anywhere.** A
  finding is normalised through a fixed field
  list -- path, commit, blob, detector, pattern
  class, line, column, the detector layer's
  redacted preview and a SHA-256 fingerprint --
  so a finding handed in carrying the matched
  text (or any other extra field) has it dropped
  at this door, never stored, audited or
  rendered. The decision, the alert row, the
  audit detail, `to_dict` and the rendered pages
  all follow the same law, and the battery plants
  a secret and greps every surface for it.
- **The protection seam is lazy and honest,**
  as in S-290/S-291/S-292: `samverk.push_protection`
  is never imported at load. At use time it is
  probed and its `PushProtection.check_push`
  judges the push when present; a caller may
  instead hand one decision to `bypass_push`
  (the battery's road, and the seam a caller
  behind the S-089 gate uses, since the gate
  keeps the decision on the protection face) or
  inject one `protection` callable into the
  store. With no decision, no injected judge and
  no S-292 module, the use raises
  `protection_unavailable` -- a bypass of a
  refusal nobody has judged does not happen.
- **Storage and witnessing.** Migration 116's
  `push_protection_bypasses` (schema 115 -> 116
  on the banked line: S-291's migration 115 lands
  before this slice and is untouched by it; on
  this slice's own base the migration list runs
  114 -> 116). Alert state stands `open`; the
  lifecycle that resolves alerts is S-294's road
  for S-291's `secret_alerts`, and this slice
  does not reach into it.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .permission_engine import PermissionEngine
from .repositories import RepositoryError, RepositoryStore
from .team_permissions import role_word

__all__ = [
    "BYPASS_AUDIT_REQUIRED", "BYPASS_EVENT",
    "BYPASS_NOT_NEEDED", "BYPASS_NOT_PERMITTED",
    "BYPASS_NOT_VISIBLE", "BYPASS_REASON_REQUIRED",
    "BYPASS_REASON_TOO_LONG", "MAX_REASON_CHARS",
    "PERMITTED_ROLES", "PROTECTION_UNAVAILABLE",
    "BypassDecision", "BypassError", "BypassFinding",
    "PushBypass", "PushProtectionBypassStore",
    "RefusalView", "decide_bypass", "normalise_decision",
    "normalise_finding", "protection_available",
    "render_bypass_list_page", "render_bypass_page",
    "validate_reason",
]

#: The audit event a used bypass writes (S-293's
#: taxonomy claim, append-only per the taxonomy rules).
BYPASS_EVENT = "repo.push_protection.bypass"

#: The rungs that may bypass push protection: the
#: two that already answer for a repository's safety.
PERMITTED_ROLES = frozenset({"admin", "maintain"})

#: A stated reason is a sentence a person owns, not
#: an essay: the cap is said, never silent.
MAX_REASON_CHARS = 500

BYPASS_NOT_PERMITTED = "bypass_not_permitted"
BYPASS_REASON_REQUIRED = "bypass_reason_required"
BYPASS_REASON_TOO_LONG = "bypass_reason_too_long"
BYPASS_NOT_NEEDED = "bypass_not_needed"
BYPASS_NOT_VISIBLE = "bypass_not_visible"
BYPASS_AUDIT_REQUIRED = "bypass_audit_required"
PROTECTION_UNAVAILABLE = "protection_unavailable"

#: The standing state of a bypass alert. Resolution
#: is S-294's lifecycle road, not this slice's.
ALERT_STATE_OPEN = "open"


class BypassError(RepositoryError):
    """A push-protection bypass error: a
    RepositoryError carrying `.reason`, in the
    house shape."""


# --- findings and the refusal, normalised ----------------------------


@dataclass(frozen=True)
class BypassFinding:
    """One detected secret shape behind a refusal.
    Never the secret: the fixed field list is the
    whole of what this module will carry, and any
    other field a finding arrives with is dropped
    by `normalise_finding`."""
    path: str
    commit_oid: str
    blob_oid: str
    source: str
    detector_id: str
    pattern_class: str
    line: int
    column: int
    redacted: str
    fingerprint: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "commit": self.commit_oid,
            "blob": self.blob_oid,
            "source": self.source,
            "detector_id": self.detector_id,
            "pattern_class": self.pattern_class,
            "line": self.line,
            "column": self.column,
            "redacted": self.redacted,
            "fingerprint": self.fingerprint,
        }

    def audit_dict(self) -> dict:
        """The finding as the audit detail carries
        it: where and what shape, without even the
        redacted preview -- the audit log is the
        widest-read surface in the house."""
        return {
            "path": self.path,
            "commit": self.commit_oid,
            "detector_id": self.detector_id,
            "pattern_class": self.pattern_class,
            "line": self.line,
            "fingerprint": self.fingerprint,
        }


def normalise_finding(raw) -> BypassFinding:
    """One finding, from a dict (S-292's `to_dict`
    shape) or an object with the same attributes,
    through the fixed field list. Extra fields --
    a planted secret above all -- are dropped."""
    if isinstance(raw, BypassFinding):
        return raw
    if isinstance(raw, dict):
        get = raw.get
    else:
        def get(key, default=None):
            return getattr(raw, key, default)
    return BypassFinding(
        path=str(get("path", "") or ""),
        commit_oid=str(get("commit", get("commit_oid", "")) or ""),
        blob_oid=str(get("blob", get("blob_oid", "")) or ""),
        source=str(get("source", "") or ""),
        detector_id=str(get("detector_id", "") or ""),
        pattern_class=str(get("pattern_class", "") or ""),
        line=int(get("line", 0) or 0),
        column=int(get("column", 0) or 0),
        redacted=str(get("redacted", "") or ""),
        fingerprint=str(get("fingerprint", "") or ""))


@dataclass(frozen=True)
class RefusalView:
    """S-292's decision, normalised: allowed or
    refused, the refusal sentence, and the findings
    behind it (normalised, never the secret)."""
    allowed: bool
    reason: str
    findings: tuple

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "findings": [f.to_dict() for f in self.findings],
        }


def normalise_decision(raw) -> RefusalView:
    """A protection decision, from a dict or from
    S-292's `PushProtectionDecision` (or any object
    with `allowed` / `reason` / `findings`)."""
    if isinstance(raw, RefusalView):
        return raw
    if isinstance(raw, dict):
        allowed = bool(raw.get("allowed", False))
        reason = str(raw.get("reason", "") or "")
        findings = raw.get("findings", ()) or ()
    else:
        allowed = bool(getattr(raw, "allowed", False))
        reason = str(getattr(raw, "reason", "") or "")
        findings = getattr(raw, "findings", ()) or ()
    return RefusalView(
        allowed=allowed, reason=reason,
        findings=tuple(normalise_finding(f) for f in findings))


# --- the lazy protection seam -----------------------------------------


def _try_protection_module():
    try:
        return importlib.import_module("samverk.push_protection")
    except Exception:
        return None


def protection_available() -> bool:
    """Whether S-292's push protection stands on
    this base. Probed at call time, never at load."""
    return _try_protection_module() is not None


# --- the pure judgement -------------------------------------------------


def validate_reason(reason) -> str:
    """The stated reason, cleaned -- or a named
    refusal. A bypass without a reason is refused,
    never defaulted."""
    if not isinstance(reason, str) or not reason.strip():
        raise BypassError(
            BYPASS_REASON_REQUIRED,
            "A push-protection bypass needs a stated "
            "reason: the bypasser's own words for why "
            "this refused push may land anyway. A "
            "bypass without its reason is a hidden "
            "door, and this slice builds none.")
    cleaned = reason.strip()
    if len(cleaned) > MAX_REASON_CHARS:
        raise BypassError(
            BYPASS_REASON_TOO_LONG,
            f"A bypass reason is at most "
            f"{MAX_REASON_CHARS} characters; this one "
            f"runs {len(cleaned)}. Say the reason "
            f"plainly and briefly.")
    return cleaned


@dataclass(frozen=True)
class BypassDecision:
    """The pure judgement: may this person bypass,
    holding this role, for this stated reason? A
    refusal carries its named code and its sentence.
    `words` says the whole position in plain text."""
    may_bypass: bool
    role: str | None
    source: str
    code: str            # "" when may_bypass
    reason: str          # the refusal sentence; "" when may_bypass
    words: str


def _permitted_words() -> str:
    return ", ".join(
        role_word(r) for r in ("maintain", "admin"))


def decide_bypass(*, role: str | None, source: str = "none",
                  actor: str | None = None,
                  full_name: str = "",
                  reason: object = "") -> BypassDecision:
    """Judge one bypass ask. Role is judged first
    (a person who may not bypass is told so, with
    the permitted rungs named), then the stated
    reason. Pure: writes nothing, audits nothing."""
    who = f"'{actor}'" if actor else "an anonymous actor"
    if role not in PERMITTED_ROLES:
        held = (f"holds the {role_word(role)} role"
                if role else "holds no role")
        sentence = (
            f"Push-protection bypass in {full_name} was "
            f"refused: {who} {held}, and only the "
            f"permitted roles may bypass push "
            f"protection ({_permitted_words()}). Ask a "
            f"repository owner to land the change, fix "
            f"the detected secret, or be granted a "
            f"permitted role first.")
        return BypassDecision(
            may_bypass=False, role=role, source=source,
            code=BYPASS_NOT_PERMITTED, reason=sentence,
            words=(f"{who} may not bypass push protection "
                   f"in {full_name}: only "
                   f"{_permitted_words()} may, and every "
                   f"bypass is an alert and an audit event."))
    try:
        validate_reason(reason)
    except BypassError as exc:
        return BypassDecision(
            may_bypass=False, role=role, source=source,
            code=exc.reason, reason=str(exc),
            words=(f"{who} may not bypass push protection "
                   f"in {full_name} without a stated "
                   f"reason: every bypass is an alert and "
                   f"an audit event, and its reason is "
                   f"part of the record."))
    return BypassDecision(
        may_bypass=True, role=role, source=source,
        code="", reason="",
        words=(f"{who} may bypass push protection in "
               f"{full_name} as {role_word(role)}: the "
               f"bypass will stand as an alert and an "
               f"audit event, visible to the "
               f"repository's owners."))


# --- the record ---------------------------------------------------------


@dataclass(frozen=True)
class PushBypass:
    """One used bypass: the standing alert. Carries
    the audit sequence of its witness row."""
    id: int
    repo_id: int
    full_name: str
    actor_id: int
    actor_username: str
    role: str
    role_source: str
    reason: str
    findings: tuple
    refs: tuple
    audit_seq: int
    state: str
    created_at: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "repository": self.full_name,
            "actor_id": self.actor_id,
            "actor": self.actor_username,
            "role": self.role,
            "role_source": self.role_source,
            "reason": self.reason,
            "findings": [f.to_dict() for f in self.findings],
            "refs": [dict(r) for r in self.refs],
            "audit_seq": self.audit_seq,
            "state": self.state,
            "created_at": self.created_at,
        }


def _row_to_bypass(row: sqlite3.Row, full_name: str) -> PushBypass:
    findings = tuple(
        normalise_finding(f)
        for f in json.loads(row["findings"] or "[]"))
    refs = tuple(json.loads(row["refs"] or "[]"))
    return PushBypass(
        id=row["id"], repo_id=row["repo_id"],
        full_name=full_name,
        actor_id=row["actor_id"],
        actor_username=row["actor_username"],
        role=row["role"], role_source=row["role_source"],
        reason=row["reason"], findings=findings, refs=refs,
        audit_seq=row["audit_seq"], state=row["state"],
        created_at=row["created_at"])


def _ref_dicts(updates) -> tuple:
    out = []
    for update in updates or ():
        if isinstance(update, dict):
            out.append({
                "ref": str(update.get("ref", "")),
                "old": str(update.get("old", update.get("old_oid", ""))),
                "new": str(update.get("new", update.get("new_oid", "")))})
        else:
            out.append({
                "ref": str(getattr(update, "ref", "")),
                "old": str(getattr(update, "old_oid", "")),
                "new": str(getattr(update, "new_oid", ""))})
    return tuple(out)


# --- the store ----------------------------------------------------------


class PushProtectionBypassStore:
    """The one road on which a push-protection
    refusal may be bypassed, and the owners' read
    of the alerts it leaves."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 accounts: AccountStore,
                 audit: AuditLog | None = None,
                 *, protection=None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._audit = audit
        self._protection = protection
        self._now = time_fn
        self._engine = PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)

    # -- resolution ---------------------------------------------------

    def _resolve(self, actor: User | None, owner, repo):
        """(repository, resolution). A missing
        repository, and a private or internal one
        the actor holds no role in, answer the
        uniform `repo_not_found`."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise BypassError(
                "repo_not_found", "No such repository.")
        resolution = self._engine.resolve(actor, current)
        if actor is None or resolution.role is None:
            if current.visibility != "public":
                raise BypassError(
                    "repo_not_found", "No such repository.")
        return current, resolution

    # -- the pure check -------------------------------------------------

    def judge(self, actor: User | None, owner, repo, *,
              reason: object = "") -> BypassDecision:
        """May this actor bypass push protection in
        this repository, for this stated reason? A
        pure read: writes nothing, audits nothing."""
        current, resolution = self._resolve(actor, owner, repo)
        return decide_bypass(
            role=resolution.role, source=resolution.source,
            actor=actor.username if actor is not None else None,
            full_name=current.full_name, reason=reason)

    # -- the judgement behind the door ----------------------------------

    def _judge_refusal(self, owner, repo, updates, *,
                       history, prior_tips) -> RefusalView:
        """S-292's decision over this push, through
        the injected judge when one was given, else
        the lazy seam. No judge anywhere is a named
        failure, never a waved-through bypass."""
        if self._protection is not None:
            judge = self._protection
            if hasattr(judge, "check_push"):
                return normalise_decision(judge.check_push(
                    owner, repo, updates, history=history,
                    prior_tips=tuple(prior_tips)))
            return normalise_decision(judge(
                owner, repo, updates, history=history,
                prior_tips=tuple(prior_tips)))
        module = _try_protection_module()
        if module is not None:
            face = module.PushProtection(self._repos)
            return normalise_decision(face.check_push(
                owner, repo, updates, history=history,
                prior_tips=tuple(prior_tips)))
        raise BypassError(
            PROTECTION_UNAVAILABLE,
            "Push protection cannot judge this push: "
            "S-292's push protection is not available "
            "on this base and no judge was injected, "
            "so there is no refusal to bypass. A bypass "
            "of an unjudged push does not happen.")

    # -- the use ---------------------------------------------------------

    def bypass_push(self, actor: User | None, owner, repo, *,
                    reason: object = "",
                    decision=None, updates=(),
                    history=None, prior_tips=(),
                    source_ip: str | None = None) -> PushBypass:
        """Use a bypass: answer a standing refusal
        with a permitted role and a stated reason,
        and leave the alert + audit event behind
        before answering. `decision` is S-292's
        decision when the caller already holds it
        (the gate's road); otherwise the push is
        judged here through the lazy seam over
        `updates`."""
        current, resolution = self._resolve(actor, owner, repo)
        if decision is not None:
            refusal = normalise_decision(decision)
        else:
            refusal = self._judge_refusal(
                owner, repo, updates,
                history=history, prior_tips=prior_tips)
        if refusal.allowed:
            raise BypassError(
                BYPASS_NOT_NEEDED,
                f"Push protection did not refuse this "
                f"push to {current.full_name}: there is "
                f"nothing to bypass. Land the push "
                f"under protection, as it stands.")
        judgement = decide_bypass(
            role=resolution.role, source=resolution.source,
            actor=actor.username if actor is not None else None,
            full_name=current.full_name, reason=reason)
        if not judgement.may_bypass:
            raise BypassError(judgement.code, judgement.reason)
        cleaned_reason = validate_reason(reason)
        if self._audit is None:
            raise BypassError(
                BYPASS_AUDIT_REQUIRED,
                "A push-protection bypass cannot be "
                "used here: this store was built "
                "without an audit log, and a bypass "
                "that cannot be witnessed must not "
                "happen.")
        refs = _ref_dicts(updates)
        audit_seq = self._audit.append(
            actor_kind="user", actor_id=actor.id,
            action=BYPASS_EVENT, target_kind="repo",
            target_id=current.full_name,
            source_ip=source_ip, outcome="success",
            detail={
                "repository": current.full_name,
                "actor": actor.username,
                "role": resolution.role,
                "role_source": resolution.source,
                "reason": cleaned_reason,
                "findings": [f.audit_dict()
                             for f in refusal.findings],
                "refs": [dict(r) for r in refs],
            })
        created_at = int(self._now())
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO push_protection_bypasses ("
                " repo_id, actor_id, actor_username, role,"
                " role_source, reason, findings, refs,"
                " audit_seq, state, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (current.id, actor.id, actor.username,
                 resolution.role, resolution.source,
                 cleaned_reason,
                 json.dumps([f.to_dict()
                             for f in refusal.findings]),
                 json.dumps([dict(r) for r in refs]),
                 audit_seq, ALERT_STATE_OPEN, created_at))
            bypass_id = int(cursor.lastrowid)
        row = self._conn.execute(
            "SELECT * FROM push_protection_bypasses"
            " WHERE id = ?", (bypass_id,)).fetchone()
        return _row_to_bypass(row, current.full_name)

    # -- the owners' read --------------------------------------------------

    def _require_owner_view(self, viewer: User | None,
                            owner, repo):
        """The visibility law, shared by both reads:
        only the admin rung -- the owners' rung --
        sees bypass alerts."""
        current, resolution = self._resolve(viewer, owner, repo)
        if resolution.role != "admin":
            raise BypassError(
                BYPASS_NOT_VISIBLE,
                f"Push-protection bypass alerts in "
                f"{current.full_name} are visible to "
                f"the repository's owners (the admin "
                f"role); "
                f"{'an anonymous reader' if viewer is None else repr(viewer.username)}"
                f" does not hold it.")
        return current

    def list_bypasses(self, viewer: User | None, owner,
                      repo) -> tuple:
        """Every standing bypass alert in the
        repository, oldest first. Owners only."""
        current = self._require_owner_view(viewer, owner, repo)
        rows = self._conn.execute(
            "SELECT * FROM push_protection_bypasses"
            " WHERE repo_id = ? ORDER BY id",
            (current.id,)).fetchall()
        return tuple(
            _row_to_bypass(row, current.full_name)
            for row in rows)

    def get_bypass(self, viewer: User | None, owner, repo,
                   bypass_id: int) -> PushBypass:
        """One standing bypass alert. Owners only;
        a missing alert is `bypass_not_found`."""
        current = self._require_owner_view(viewer, owner, repo)
        row = self._conn.execute(
            "SELECT * FROM push_protection_bypasses"
            " WHERE repo_id = ? AND id = ?",
            (current.id, int(bypass_id))).fetchone()
        if row is None:
            raise BypassError(
                "bypass_not_found",
                f"No push-protection bypass "
                f"#{bypass_id} stands in "
                f"{current.full_name}.")
        return _row_to_bypass(row, current.full_name)


# --- the page faces -----------------------------------------------------


def _finding_words(finding: BypassFinding) -> str:
    return (f"{finding.path} -- {finding.pattern_class} "
            f"(line {finding.line})")


def render_bypass_page(record: PushBypass,
                       title: str = "Push-protection bypass"):
    """One bypass alert, said in words: who, which
    role, why, and what was bypassed -- escaped
    through S-010, never a secret."""
    findings = "".join(
        "<li>" + escape_html_text(_finding_words(f)) + "</li>"
        for f in record.findings)
    if findings:
        findings = "<ul>" + findings + "</ul>"
    else:
        findings = ("<p>The refused push was cut short "
                    "before it could be proven clean; no "
                    "finding was named.</p>")
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1>"
        + '<div class="push-protection-bypass">'
        + "<p>Push protection was bypassed in "
        + escape_html_text(record.full_name)
        + " by " + escape_html_text(record.actor_username)
        + " (" + escape_html_text(role_word(record.role))
        + "), alert #" + str(record.id)
        + ", state " + escape_html_text(record.state)
        + ".</p>"
        + "<p>Stated reason: "
        + escape_html_text(record.reason) + "</p>"
        + findings
        + "</div>"
        + "</body></html>")


def render_bypass_list_page(records, full_name: str,
                            title: str = "Push-protection bypasses"):
    """The owners' list of standing bypass alerts
    in one repository, said in words."""
    if records:
        rows = "".join(
            '<li><a href="#bypass-' + str(r.id) + '">'
            + "Bypass #" + str(r.id) + "</a> by "
            + escape_html_text(r.actor_username)
            + " (" + escape_html_text(role_word(r.role))
            + "): " + escape_html_text(r.reason) + "</li>"
            for r in records)
        body = "<ul>" + rows + "</ul>"
    else:
        body = ("<p>No push-protection bypasses stand "
                "in this repository.</p>")
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1>"
        + '<div class="push-protection-bypass-list">'
        + "<p>Repository: " + escape_html_text(full_name)
        + "</p>"
        + body
        + "</div>"
        + "</body></html>")
