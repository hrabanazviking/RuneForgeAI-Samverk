"""Custom patterns (S-295).

Roadmap S-295: Custom patterns -- org/instance-defined
regex patterns with a dry-run against repo history
before activation.

S-289 gave Samverk a detector set for the major public
token formats, S-290 a generic entropy judgement,
S-291 the scan of every accepted push across its full
introduced history, and S-292 the same judgement as a
refusal at the receive gate. Those detectors are the
ones Samverk ships. This slice is the door for the
patterns Samverk does *not* ship: the ones an instance
or an organization defines for itself -- an internal
token prefix, a project codename that must never be
committed, a vendor format no public set names.

- **Two scopes, judged managers.** A pattern lives at
  instance scope (defined by a site administrator, in
  force for every repository) or at organization
  scope (defined by an organization owner or a site
  administrator, in force for that organization's
  repositories). There is no user scope and no
  repository scope in this slice: the roadmap names
  org/instance, and a narrower scope is a later
  slice's decision, not this one's quiet widening.
  Anonymous definition is refused
  `authentication_required`; a signed-in non-manager
  is refused `permission_denied`; a missing
  organization is named `org_not_found`.
- **A pattern is a name and a regex, judged at the
  door.** The name is plain text under a cap; the
  description likewise. The regex is validated before
  anything is stored: it must compile, it must fit
  the length cap, it must not carry a backreference,
  it must not nest quantifiers (the classic
  catastrophic-backtracking shape), and it must not
  be able to match the empty string -- a pattern that
  matches nothing-in-particular matches everything
  and means nothing. A refused pattern stores
  nothing. The stored row keeps a SHA-256 of the
  regex text (`regex_sha`) so a later edit is
  detectable by comparison, never by memory.
- **Draft, then dry-run, then active -- in that
  order.** A new pattern stands `draft` and judges
  nothing. Activation is refused until the pattern
  has a *complete* dry-run against repository history
  whose recorded `regex_sha` equals the pattern's
  current one: no dry-run at all is
  `dry_run_required`, a dry-run of an older text is
  `dry_run_stale`, and a dry-run cut short by a cap
  is `dry_run_incomplete` -- an operator activates a
  pattern knowing what it would have caught, or does
  not activate it. Editing the regex of a draft
  returns it to needing a fresh dry-run (the sha
  guard makes the stale one unusable); editing the
  regex of an *active* pattern is refused
  `pattern_is_active` outright -- disable first, so
  the pattern in force is always the pattern that
  was dry-run. Disabling is the off switch; there is
  no delete in this slice, so a pattern's history
  (its dry-runs) is never orphaned.
- **A dry-run walks real history.** A dry-run judges
  one repository's history: every commit reachable
  from the given tips, oldest first, and every blob
  version each commit introduces (S-291's
  `introduced_blobs` law, reused whole) -- judged
  once per blob oid, reported at the oldest
  introducing commit per (path, blob). The operator
  must be a manager of the pattern's scope *and*
  able to read the repository (S-054's `role_for`);
  a repository the operator cannot read answers
  exactly as a missing one (`repo_not_found`), so a
  dry-run can never be used to probe a private
  repository's contents. Caps are S-291's own
  (commits / distinct blobs / blob bytes; binary
  blobs skipped and counted), and a capped dry-run
  stands `partial` naming its cap -- never a clean
  bill for history that was not read, and never
  enough to activate on.
- **Findings never carry the secret.** A dry-run
  match, like S-289's finding, holds the commit, the
  path, the blob, the line and column, a redacted
  preview keeping only the match's first characters
  and its length, and a SHA-256 fingerprint -- where
  and what shape, never the matched text. The
  rendered pages follow the same law, and the
  battery plants a secret and greps every surface
  for it.
- **What activation puts in force.**
  `effective_patterns` answers the patterns judging
  a repository: every active instance pattern, plus
  the active patterns of the organization that owns
  the repository (when the owner is an organization
  at all). `scan_text_with_patterns` judges one text
  against a pattern set with S-289's deterministic
  overlap law (earliest span, longest at a shared
  start, pattern order as tiebreak; one span yields
  at most one finding), and `scan_text_effective`
  composes the two. Wiring these patterns into
  S-291's push scan and S-292's gate is *not* this
  slice: those slices judge with the layers they
  name, and a later slice may plug this set in as a
  third layer through their standing seams. This
  slice builds the definition, the dry-run, the
  activation law and the effective set -- the seam
  is documented, not silently crossed.
- **Witnessed by the events that already stand.**
  Defining, editing, activating and disabling a
  pattern are governance acts, and they are audited
  with the taxonomy's existing verbs: instance
  patterns ride `admin.settings.change` (target
  `custom_patterns`, as S-255's defence settings
  do), organization patterns ride
  `auth.organization.update` (as S-186's membership
  changes do). A dry-run, like S-291's scan, is a
  judgement over a record and is not witnessed --
  its own row is its record. No new taxonomy event:
  134 stand (33 auth / 88 repo / 13 admin).

Storage is migration 118's `custom_patterns`,
`custom_pattern_dry_runs` and
`custom_pattern_dry_run_matches` tables
(schema 117 -> 118).
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import User
from .organization_members import OrgMembershipStore
from .organizations import Organization, OrganizationStore
from .permissions import role_for
from .push_scanning import GitHistory, introduced_blobs
from .repositories import RepositoryStore

__all__ = [
    "BINARY_SNIFF_BYTES", "DESCRIPTION_MAX", "MAX_BLOB_BYTES",
    "MAX_BLOBS_PER_RUN", "MAX_COMMITS_PER_RUN",
    "MAX_MATCHES_STORED", "NAME_MAX", "REGEX_MAX", "SCOPES",
    "STATES", "CustomFinding", "CustomPattern",
    "CustomPatternError", "CustomPatternsAudit", "DryRun",
    "DryRunMatch", "GitHistory", "audit_custom_patterns",
    "decide_activation", "decide_manager", "history_commits",
    "pattern_sha", "redact_custom_match",
    "render_custom_patterns_page", "render_dry_run_page",
    "scan_text_custom", "validate_description",
    "validate_pattern_name", "validate_regex",
    "CustomPatternStore",
]

SCOPES = frozenset({"instance", "org"})
STATES = frozenset({"draft", "active", "disabled"})

NAME_MAX = 80
DESCRIPTION_MAX = 500
REGEX_MAX = 500

MAX_COMMITS_PER_RUN = 1000
MAX_BLOBS_PER_RUN = 10000
MAX_BLOB_BYTES = 1_000_000
BINARY_SNIFF_BYTES = 8192
MAX_MATCHES_STORED = 500

_OID_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")
_BACKREFERENCE_RE = re.compile(r"\\[1-9]")
_NESTED_QUANTIFIER_RE = re.compile(
    r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)\s*(?:[+*]|\{\d)")


class CustomPatternError(ValueError):
    """A custom-pattern refusal, named by `reason`."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# --- pure validators ---------------------------------------------------


def _has_control(text: str, *, allow_newline_tab: bool = False) -> bool:
    for ch in text:
        if ord(ch) == 0x7F or ord(ch) < 0x20:
            if allow_newline_tab and ch in "\n\t":
                continue
            return True
    return False


def validate_pattern_name(value: object) -> tuple:
    """(display, name_lower) for a pattern name, or a
    named refusal. Plain text, stripped, capped, no
    control characters; uniqueness is judged
    case-insensitively per scope."""
    if not isinstance(value, str):
        raise CustomPatternError(
            "name_invalid", "A pattern name is required.")
    name = value.strip()
    if not name:
        raise CustomPatternError(
            "name_invalid", "A pattern name is required.")
    if len(name) > NAME_MAX:
        raise CustomPatternError(
            "name_too_long",
            f"A pattern name is at most {NAME_MAX} characters.")
    if _has_control(name):
        raise CustomPatternError(
            "name_invalid",
            "A pattern name contains characters that "
            "cannot be shown.")
    return name, name.lower()


def validate_description(value: object) -> str:
    """A pattern description: plain text, stripped,
    capped; empty is a lawful description."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CustomPatternError(
            "description_invalid", "That description is not valid.")
    text = value.strip()
    if len(text) > DESCRIPTION_MAX:
        raise CustomPatternError(
            "description_too_long",
            f"A description is at most {DESCRIPTION_MAX} "
            "characters.")
    if _has_control(text, allow_newline_tab=True):
        raise CustomPatternError(
            "description_invalid",
            "That description contains characters that "
            "cannot be shown.")
    return text


def pattern_sha(regex: str) -> str:
    """The stored identity of one regex text."""
    return hashlib.sha256(regex.encode("utf-8")).hexdigest()


def validate_regex(value: object) -> tuple:
    """(regex, compiled) for a lawful custom pattern,
    or a named refusal. Judged whole before anything
    is stored: it must compile, fit the cap, carry no
    backreference, nest no quantifiers, and be unable
    to match the empty string."""
    if not isinstance(value, str):
        raise CustomPatternError(
            "pattern_invalid", "A pattern must be regex text.")
    regex = value.strip()
    if not regex:
        raise CustomPatternError(
            "pattern_invalid", "A pattern must not be empty.")
    if len(regex) > REGEX_MAX:
        raise CustomPatternError(
            "pattern_too_long",
            f"A pattern is at most {REGEX_MAX} characters.")
    if _BACKREFERENCE_RE.search(regex):
        raise CustomPatternError(
            "pattern_unsafe",
            "A pattern must not use backreferences; they "
            "make matching slow and the match hard to "
            "reason about.")
    if _NESTED_QUANTIFIER_RE.search(regex):
        raise CustomPatternError(
            "pattern_unsafe",
            "A pattern must not nest quantifiers (a "
            "quantified group carrying a quantifier); "
            "that shape can backtrack catastrophically "
            "over repository text.")
    try:
        compiled = re.compile(regex)
    except re.error as exc:
        raise CustomPatternError(
            "pattern_invalid",
            f"That pattern does not compile: {exc}") from None
    if compiled.search("") is not None:
        raise CustomPatternError(
            "pattern_matches_empty",
            "A pattern that can match the empty string "
            "matches everywhere and means nothing; "
            "require at least one character.")
    return regex, compiled


def redact_custom_match(matched: str) -> str:
    """The only printable form of a match: its first
    characters and its length -- never the match."""
    keep = matched[:4]
    return f"{keep}\u2026[{len(matched)} chars]"


def decide_manager(scope: str, *, is_admin: bool,
                   org_role: str | None) -> str | None:
    """Pure management law: the refusal reason, or
    None when this actor may manage a pattern at
    `scope`. Instance patterns belong to site admins;
    organization patterns to the organization's
    owners and to site admins."""
    if scope == "instance":
        return None if is_admin else "permission_denied"
    if scope == "org":
        if is_admin or org_role == "owner":
            return None
        return "permission_denied"
    return "scope_invalid"


def decide_activation(state: str, current_sha: str,
                      dry_run) -> str | None:
    """Pure activation law: the refusal reason, or
    None when the pattern may activate. `dry_run` is
    the pattern's latest dry-run (a DryRun or None)."""
    if state == "active":
        return "already_active"
    if dry_run is None:
        return "dry_run_required"
    if dry_run.pattern_sha != current_sha:
        return "dry_run_stale"
    if dry_run.status != "complete":
        return "dry_run_incomplete"
    return None


# --- text judging --------------------------------------------------------


def _line_col(text: str, start: int) -> tuple:
    line = text.count("\n", 0, start) + 1
    last_nl = text.rfind("\n", 0, start)
    return line, start - last_nl


@dataclass(frozen=True)
class CustomFinding:
    """One custom-pattern match in one text. Never
    the matched text."""

    pattern_id: int
    pattern_name: str
    scope: str
    start: int
    end: int
    line: int
    column: int
    redacted: str
    fingerprint: str

    def to_dict(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "pattern_name": self.pattern_name,
            "scope": self.scope,
            "start": self.start, "end": self.end,
            "line": self.line, "column": self.column,
            "redacted": self.redacted,
            "fingerprint": self.fingerprint,
        }


def scan_text_custom(text: str, patterns) -> list:
    """Every match of `patterns` in `text`, under
    S-289's deterministic overlap law: earliest span
    first, longest match at a shared start, pattern
    order as the final tiebreak; a claimed span
    yields no second finding. Zero-length matches
    are never findings."""
    compiled = []
    for pattern in patterns:
        try:
            rx = re.compile(pattern.regex)
        except re.error:
            continue
        compiled.append((pattern, rx))
    raw = []
    for order, (pattern, rx) in enumerate(compiled):
        for m in rx.finditer(text):
            if m.end() == m.start():
                continue
            raw.append((m.start(), -(m.end() - m.start()),
                        order, pattern, m))
    raw.sort(key=lambda r: (r[0], r[1], r[2]))
    findings = []
    claimed_end = -1
    for start, _neglen, _order, pattern, m in raw:
        if start < claimed_end:
            continue
        matched = m.group(0)
        line, column = _line_col(text, start)
        findings.append(CustomFinding(
            pattern_id=pattern.id, pattern_name=pattern.name,
            scope=pattern.scope, start=start, end=m.end(),
            line=line, column=column,
            redacted=redact_custom_match(matched),
            fingerprint=hashlib.sha256(
                matched.encode("utf-8")).hexdigest()))
        claimed_end = m.end()
    findings.sort(key=lambda f: f.start)
    return findings


# --- history -------------------------------------------------------------


def _is_zero_oid(oid: str) -> bool:
    return bool(oid) and set(oid) == {"0"}


def history_commits(history, tips) -> list:
    """Every commit reachable from any of `tips`,
    oldest first (parents always before children) --
    the whole history a dry-run judges."""
    ordered: list = []
    placed: set = set()

    def visit(oid: str) -> None:
        stack = [(oid, False)]
        while stack:
            current, expanded = stack.pop()
            if current in placed:
                continue
            if expanded:
                placed.add(current)
                ordered.append(current)
                continue
            stack.append((current, True))
            for parent in history.commit_parents(current):
                if parent not in placed:
                    stack.append((parent, False))

    for tip in tips:
        if tip and not _is_zero_oid(tip):
            visit(tip)
    return ordered


# --- records ---------------------------------------------------------------


@dataclass(frozen=True)
class CustomPattern:
    id: int
    scope: str             # instance | org
    org_id: int | None
    org_name: str | None
    org_name_lower: str | None
    name: str
    name_lower: str
    description: str
    regex: str
    regex_sha: str
    state: str             # draft | active | disabled
    created_by: int
    created_at: int
    updated_at: int
    activated_by: int | None
    activated_at: int | None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "scope": self.scope,
            "org": self.org_name, "name": self.name,
            "description": self.description,
            "regex": self.regex, "regex_sha": self.regex_sha,
            "state": self.state, "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "activated_by": self.activated_by,
            "activated_at": self.activated_at,
        }


@dataclass(frozen=True)
class DryRun:
    id: int
    pattern_id: int
    repo_id: int
    repo_full_name: str
    pattern_sha: str
    status: str            # complete | partial
    partial_reason: str    # "" when complete
    commits_scanned: int
    blobs_scanned: int
    blobs_skipped: int
    matches_count: int
    matches_stored: int
    created_by: int
    created_at: int

    def to_dict(self) -> dict:
        return {
            "id": self.id, "pattern_id": self.pattern_id,
            "repository": self.repo_full_name,
            "pattern_sha": self.pattern_sha,
            "status": self.status,
            "partial_reason": self.partial_reason,
            "commits_scanned": self.commits_scanned,
            "blobs_scanned": self.blobs_scanned,
            "blobs_skipped": self.blobs_skipped,
            "matches": self.matches_count,
            "matches_stored": self.matches_stored,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class DryRunMatch:
    id: int
    dry_run_id: int
    commit_oid: str
    path: str
    blob_oid: str
    line: int
    column: int
    redacted: str
    fingerprint: str

    def to_dict(self) -> dict:
        return {
            "id": self.id, "dry_run_id": self.dry_run_id,
            "commit": self.commit_oid, "path": self.path,
            "blob": self.blob_oid, "line": self.line,
            "column": self.column, "redacted": self.redacted,
            "fingerprint": self.fingerprint,
        }


def _row_to_pattern(row: sqlite3.Row) -> CustomPattern:
    return CustomPattern(
        id=int(row["id"]), scope=row["scope"],
        org_id=(int(row["org_id"])
                if row["org_id"] is not None else None),
        org_name=row["org_name"],
        org_name_lower=row["org_name_lower"],
        name=row["name"], name_lower=row["name_lower"],
        description=row["description"], regex=row["regex"],
        regex_sha=row["regex_sha"], state=row["state"],
        created_by=int(row["created_by"]),
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
        activated_by=(int(row["activated_by"])
                      if row["activated_by"] is not None
                      else None),
        activated_at=(int(row["activated_at"])
                      if row["activated_at"] is not None
                      else None))


def _row_to_dry_run(row: sqlite3.Row) -> DryRun:
    return DryRun(
        id=int(row["id"]), pattern_id=int(row["pattern_id"]),
        repo_id=int(row["repo_id"]),
        repo_full_name=row["repo_full_name"],
        pattern_sha=row["pattern_sha"], status=row["status"],
        partial_reason=row["partial_reason"],
        commits_scanned=int(row["commits_scanned"]),
        blobs_scanned=int(row["blobs_scanned"]),
        blobs_skipped=int(row["blobs_skipped"]),
        matches_count=int(row["matches_count"]),
        matches_stored=int(row["matches_stored"]),
        created_by=int(row["created_by"]),
        created_at=int(row["created_at"]))


def _row_to_match(row: sqlite3.Row) -> DryRunMatch:
    return DryRunMatch(
        id=int(row["id"]), dry_run_id=int(row["dry_run_id"]),
        commit_oid=row["commit_oid"], path=row["path"],
        blob_oid=row["blob_oid"], line=int(row["line"]),
        column=int(row["column"]), redacted=row["redacted"],
        fingerprint=row["fingerprint"])


# --- the store -------------------------------------------------------------


class CustomPatternStore:
    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 organizations: OrganizationStore,
                 memberships: OrgMembershipStore,
                 audit=None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._repos = repositories
        self._orgs = organizations
        self._members = memberships
        self._audit = audit
        self._now = time_fn

    # -- guards ---------------------------------------------------------

    def _require_manager(self, viewer, scope: str,
                         org: Organization | None = None
                         ) -> Organization | None:
        """Resolve the management door for one act.
        Returns the organization for org scope (None
        for instance scope); raises the named refusal
        otherwise."""
        if viewer is None:
            raise CustomPatternError(
                "authentication_required",
                "Sign in to manage custom patterns.")
        if scope not in SCOPES:
            raise CustomPatternError(
                "scope_invalid",
                "A pattern's scope is instance or org.")
        if scope == "instance":
            reason = decide_manager(
                scope, is_admin=bool(viewer.is_admin),
                org_role=None)
            if reason is not None:
                raise CustomPatternError(
                    reason,
                    "Only a site administrator manages "
                    "instance patterns.")
            return None
        if org is None:
            raise CustomPatternError(
                "org_not_found", "No such organization.")
        org_role = None
        if not viewer.is_admin:
            org_role = self._members.role_for(viewer.id, org.id)
        reason = decide_manager(
            scope, is_admin=bool(viewer.is_admin),
            org_role=org_role)
        if reason is not None:
            raise CustomPatternError(
                reason,
                "Only an organization owner or a site "
                "administrator manages this organization's "
                "patterns.")
        return org

    def _org_for_pattern(self, pattern: CustomPattern):
        if pattern.org_id is None:
            return None
        return self._orgs.get_by_id(pattern.org_id)

    def _audit_change(self, viewer: User, pattern: CustomPattern,
                      action_word: str) -> None:
        if self._audit is None:
            return
        if pattern.scope == "instance":
            self._audit.append(
                actor_kind="user", actor_id=viewer.id,
                action="admin.settings.change",
                target_kind="instance",
                target_id="custom_patterns",
                outcome="success",
                detail={"pattern": pattern.name_lower,
                        "action": action_word})
        else:
            self._audit.append(
                actor_kind="user", actor_id=viewer.id,
                action="auth.organization.update",
                target_kind="organization",
                target_id=pattern.org_name_lower,
                outcome="success",
                detail={"fields": "custom_patterns",
                        "action": action_word,
                        "pattern": pattern.name_lower})

    def _name_taken(self, scope: str, org_id, name_lower: str,
                    exclude_id: int | None = None) -> bool:
        row = self._conn.execute(
            "SELECT id FROM custom_patterns WHERE scope = ?"
            " AND org_id IS ? AND name_lower = ?",
            (scope, org_id, name_lower)).fetchone()
        if row is None:
            return False
        return exclude_id is None or int(row["id"]) != exclude_id

    # -- definition -------------------------------------------------------

    def create_pattern(self, viewer, scope: str, name,
                       regex, description: object = "",
                       org_name: object = None) -> CustomPattern:
        """Define a pattern standing `draft`. Judged
        whole before anything is stored; committed
        before it is answered; audited on the standing
        events."""
        if scope not in SCOPES:
            raise CustomPatternError(
                "scope_invalid",
                "A pattern's scope is instance or org.")
        org = None
        if scope == "org":
            if not isinstance(org_name, str) or not org_name.strip():
                raise CustomPatternError(
                    "org_not_found", "No such organization.")
            org = self._orgs.get_by_name(org_name)
            if org is None:
                raise CustomPatternError(
                    "org_not_found", "No such organization.")
        elif org_name is not None:
            raise CustomPatternError(
                "scope_invalid",
                "An instance pattern names no organization.")
        self._require_manager(viewer, scope, org)
        display, name_lower = validate_pattern_name(name)
        clean_description = validate_description(description)
        clean_regex, _compiled = validate_regex(regex)
        org_id = org.id if org is not None else None
        if self._name_taken(scope, org_id, name_lower):
            raise CustomPatternError(
                "pattern_taken",
                f"A pattern named {display!r} already "
                "stands at this scope.")
        now = int(self._now())
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO custom_patterns (scope, org_id,"
                " org_name, org_name_lower, name, name_lower,"
                " description, regex, regex_sha, state,"
                " created_by, created_at, updated_at,"
                " activated_by, activated_at) VALUES"
                " (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?,"
                " NULL, NULL)",
                (scope, org_id,
                 org.name if org is not None else None,
                 org.name_lower if org is not None else None,
                 display, name_lower, clean_description,
                 clean_regex, pattern_sha(clean_regex),
                 viewer.id, now, now))
            pattern_id = int(cursor.lastrowid)
        pattern = self.get_pattern(pattern_id)
        assert pattern is not None
        self._audit_change(viewer, pattern, "create")
        return pattern

    def update_pattern(self, viewer, pattern_id: int, *,
                       name=None, description=None,
                       regex=None) -> CustomPattern:
        """Edit a pattern's name, description or regex.
        A regex change on a draft (or a disabled
        pattern) returns it to `draft` unactivated --
        the dry-run it stands on no longer matches its
        text; a regex change on an active pattern is
        refused: disable first."""
        pattern = self.get_pattern(pattern_id)
        if pattern is None:
            raise CustomPatternError(
                "pattern_not_found", "No such custom pattern.")
        org = self._org_for_pattern(pattern)
        self._require_manager(viewer, pattern.scope, org)
        display, name_lower = (
            validate_pattern_name(name) if name is not None
            else (pattern.name, pattern.name_lower))
        clean_description = (
            validate_description(description)
            if description is not None else pattern.description)
        clean_regex = pattern.regex
        regex_changed = False
        if regex is not None:
            clean_regex, _compiled = validate_regex(regex)
            regex_changed = clean_regex != pattern.regex
        if regex_changed and pattern.state == "active":
            raise CustomPatternError(
                "pattern_is_active",
                "An active pattern's regex is the text "
                "that was dry-run; disable the pattern "
                "before changing it.")
        if self._name_taken(pattern.scope, pattern.org_id,
                            name_lower, exclude_id=pattern.id):
            raise CustomPatternError(
                "pattern_taken",
                f"A pattern named {display!r} already "
                "stands at this scope.")
        now = int(self._now())
        state = "draft" if regex_changed else pattern.state
        with self._conn:
            if regex_changed:
                self._conn.execute(
                    "UPDATE custom_patterns SET name = ?,"
                    " name_lower = ?, description = ?,"
                    " regex = ?, regex_sha = ?, state = ?,"
                    " activated_by = NULL, activated_at = NULL,"
                    " updated_at = ? WHERE id = ?",
                    (display, name_lower, clean_description,
                     clean_regex, pattern_sha(clean_regex),
                     state, now, pattern.id))
            else:
                self._conn.execute(
                    "UPDATE custom_patterns SET name = ?,"
                    " name_lower = ?, description = ?,"
                    " updated_at = ? WHERE id = ?",
                    (display, name_lower, clean_description,
                     now, pattern.id))
        updated = self.get_pattern(pattern.id)
        assert updated is not None
        self._audit_change(viewer, updated, "update")
        return updated

    # -- reads --------------------------------------------------------------

    def get_pattern(self, pattern_id: int):
        row = self._conn.execute(
            "SELECT * FROM custom_patterns WHERE id = ?",
            (pattern_id,)).fetchone()
        return _row_to_pattern(row) if row else None

    def list_patterns(self, *, scope: str | None = None,
                      org_name: object = None,
                      state: str | None = None) -> tuple:
        """Patterns in id order, optionally narrowed to
        one scope, one organization, or one state."""
        if scope is not None and scope not in SCOPES:
            raise CustomPatternError(
                "scope_invalid",
                "A pattern's scope is instance or org.")
        if state is not None and state not in STATES:
            raise CustomPatternError(
                "state_invalid",
                "A pattern's state is draft, active or "
                "disabled.")
        clauses = []
        params: list = []
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        if org_name is not None:
            if not isinstance(org_name, str):
                raise CustomPatternError(
                    "org_not_found", "No such organization.")
            clauses.append("org_name_lower = ?")
            params.append(org_name.strip().lower())
        if state is not None:
            clauses.append("state = ?")
            params.append(state)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            "SELECT * FROM custom_patterns" + where
            + " ORDER BY id", params).fetchall()
        return tuple(_row_to_pattern(r) for r in rows)

    def count_patterns(self, *, state: str | None = None) -> int:
        if state is None:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM custom_patterns"
            ).fetchone()
        else:
            if state not in STATES:
                raise CustomPatternError(
                    "state_invalid",
                    "A pattern's state is draft, active or "
                    "disabled.")
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM custom_patterns"
                " WHERE state = ?", (state,)).fetchone()
        return int(row["n"])

    # -- dry-run --------------------------------------------------------------

    def dry_run(self, viewer, pattern_id: int, owner, repo, *,
                history, tips) -> DryRun:
        """Judge one pattern against one repository's
        whole history from `tips`, and record the run.
        The record, its matches are written in one
        transaction and committed before the run is
        answered. A dry-run is a judgement and is not
        witnessed."""
        pattern = self.get_pattern(pattern_id)
        if pattern is None:
            raise CustomPatternError(
                "pattern_not_found", "No such custom pattern.")
        org = self._org_for_pattern(pattern)
        self._require_manager(viewer, pattern.scope, org)
        current = self._repos.get_repository(owner, repo)
        if current is None or role_for(viewer, current) is None:
            raise CustomPatternError(
                "repo_not_found", "No such repository.")
        if tips is None:
            raise CustomPatternError(
                "tips_invalid",
                "A dry-run names the history tips to judge "
                "from.")
        checked_tips = []
        for tip in tips:
            if (not isinstance(tip, str)
                    or not _OID_RE.match(tip.lower())
                    or _is_zero_oid(tip)):
                raise CustomPatternError(
                    "tips_invalid",
                    f"Not a history tip: {tip!r}")
            checked_tips.append(tip.lower())
        if not checked_tips:
            raise CustomPatternError(
                "tips_invalid",
                "A dry-run names the history tips to judge "
                "from.")
        commits = history_commits(history, checked_tips)
        partial_reason = ""
        if len(commits) > MAX_COMMITS_PER_RUN:
            commits = commits[:MAX_COMMITS_PER_RUN]
            partial_reason = "commit_cap"
        judged: dict = {}
        occurrences: list = []
        blobs_skipped = 0
        blobs_judged = 0
        for commit_oid in commits:
            for path, _mode, blob_oid in introduced_blobs(
                    history, commit_oid):
                occurrences.append((commit_oid, path, blob_oid))
                if blob_oid in judged:
                    continue
                if len(judged) >= MAX_BLOBS_PER_RUN:
                    if not partial_reason:
                        partial_reason = "blob_cap"
                    blobs_skipped += 1
                    judged[blob_oid] = ()
                    continue
                data = history.read_blob(blob_oid)
                if len(data) > MAX_BLOB_BYTES:
                    blobs_skipped += 1
                    judged[blob_oid] = ()
                    continue
                if b"\x00" in data[:BINARY_SNIFF_BYTES]:
                    blobs_skipped += 1
                    judged[blob_oid] = ()
                    continue
                text = data.decode("utf-8", "replace")
                blobs_judged += 1
                judged[blob_oid] = tuple(
                    scan_text_custom(text, [pattern]))
        matches: list = []
        seen_pairs: set = set()
        for commit_oid, path, blob_oid in occurrences:
            if (path, blob_oid) in seen_pairs:
                continue
            seen_pairs.add((path, blob_oid))
            for finding in judged.get(blob_oid, ()):
                matches.append((
                    commit_oid, path, blob_oid, finding.line,
                    finding.column, finding.redacted,
                    finding.fingerprint))
        stored = matches[:MAX_MATCHES_STORED]
        created_at = int(self._now())
        status = "partial" if partial_reason else "complete"
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO custom_pattern_dry_runs"
                " (pattern_id, repo_id, repo_full_name,"
                " pattern_sha, status, partial_reason,"
                " commits_scanned, blobs_scanned, blobs_skipped,"
                " matches_count, matches_stored, created_by,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?,"
                " ?, ?, ?, ?, ?)",
                (pattern.id, current.id, current.full_name,
                 pattern.regex_sha, status, partial_reason,
                 len(commits), blobs_judged, blobs_skipped,
                 len(matches), len(stored), viewer.id,
                 created_at))
            run_id = int(cursor.lastrowid)
            for row in stored:
                self._conn.execute(
                    "INSERT INTO custom_pattern_dry_run_matches"
                    " (dry_run_id, commit_oid, path, blob_oid,"
                    " line, column, redacted, fingerprint)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, row[0], row[1], row[2], row[3],
                     row[4], row[5], row[6]))
        run = self.get_dry_run(run_id)
        assert run is not None
        return run

    def get_dry_run(self, run_id: int):
        row = self._conn.execute(
            "SELECT * FROM custom_pattern_dry_runs WHERE id = ?",
            (run_id,)).fetchone()
        return _row_to_dry_run(row) if row else None

    def latest_dry_run(self, pattern_id: int):
        row = self._conn.execute(
            "SELECT * FROM custom_pattern_dry_runs"
            " WHERE pattern_id = ? ORDER BY id DESC LIMIT 1",
            (pattern_id,)).fetchone()
        return _row_to_dry_run(row) if row else None

    def list_dry_runs(self, pattern_id: int) -> tuple:
        """Newest first."""
        rows = self._conn.execute(
            "SELECT * FROM custom_pattern_dry_runs"
            " WHERE pattern_id = ? ORDER BY id DESC",
            (pattern_id,)).fetchall()
        return tuple(_row_to_dry_run(r) for r in rows)

    def dry_run_matches(self, run_id: int) -> tuple:
        rows = self._conn.execute(
            "SELECT * FROM custom_pattern_dry_run_matches"
            " WHERE dry_run_id = ? ORDER BY id",
            (run_id,)).fetchall()
        return tuple(_row_to_match(r) for r in rows)

    # -- activation -----------------------------------------------------------

    def activate_pattern(self, viewer, pattern_id: int
                         ) -> CustomPattern:
        """Put a pattern in force, under the activation
        law: a complete dry-run of the current text
        must stand first."""
        pattern = self.get_pattern(pattern_id)
        if pattern is None:
            raise CustomPatternError(
                "pattern_not_found", "No such custom pattern.")
        org = self._org_for_pattern(pattern)
        self._require_manager(viewer, pattern.scope, org)
        reason = decide_activation(
            pattern.state, pattern.regex_sha,
            self.latest_dry_run(pattern.id))
        if reason is not None:
            messages = {
                "already_active":
                    "That pattern is already active.",
                "dry_run_required":
                    "A pattern activates only after a "
                    "dry-run against repository history; "
                    "run one first.",
                "dry_run_stale":
                    "The standing dry-run judged an older "
                    "text of this pattern; dry-run the "
                    "current text first.",
                "dry_run_incomplete":
                    "The standing dry-run was cut short "
                    "by a cap and did not judge the whole "
                    "history; a complete dry-run is "
                    "required before activation.",
            }
            raise CustomPatternError(reason, messages[reason])
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE custom_patterns SET state = 'active',"
                " activated_by = ?, activated_at = ?,"
                " updated_at = ? WHERE id = ?",
                (viewer.id, now, now, pattern.id))
        updated = self.get_pattern(pattern.id)
        assert updated is not None
        self._audit_change(viewer, updated, "activate")
        return updated

    def disable_pattern(self, viewer, pattern_id: int
                        ) -> CustomPattern:
        """Take a pattern out of force. Its dry-runs
        stand; reactivation judges the activation law
        again against them."""
        pattern = self.get_pattern(pattern_id)
        if pattern is None:
            raise CustomPatternError(
                "pattern_not_found", "No such custom pattern.")
        org = self._org_for_pattern(pattern)
        self._require_manager(viewer, pattern.scope, org)
        if pattern.state != "active":
            raise CustomPatternError(
                "not_active",
                "Only an active pattern can be disabled.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE custom_patterns SET state = 'disabled',"
                " updated_at = ? WHERE id = ?",
                (now, pattern.id))
        updated = self.get_pattern(pattern.id)
        assert updated is not None
        self._audit_change(viewer, updated, "disable")
        return updated

    # -- the effective set ------------------------------------------------------

    def effective_patterns(self, owner, repo) -> tuple:
        """The patterns judging one repository: every
        active instance pattern, plus the owning
        organization's active patterns when the owner
        is an organization."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise CustomPatternError(
                "repo_not_found", "No such repository.")
        rows = self._conn.execute(
            "SELECT * FROM custom_patterns WHERE state = 'active'"
            " AND (scope = 'instance' OR (scope = 'org'"
            " AND org_name_lower = ?))"
            " ORDER BY CASE scope WHEN 'instance' THEN 0"
            " ELSE 1 END, id",
            (current.owner_lower,)).fetchall()
        return tuple(_row_to_pattern(r) for r in rows)

    def scan_text_effective(self, text: str, owner, repo) -> list:
        """Judge one text against the repository's
        effective patterns."""
        return scan_text_custom(
            text, self.effective_patterns(owner, repo))


# --- the audit -----------------------------------------------------------------


@dataclass(frozen=True)
class CustomPatternsAudit:
    patterns_total: int
    active_total: int
    problems: tuple

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict:
        return {
            "patterns": self.patterns_total,
            "active": self.active_total,
            "problems": list(self.problems),
            "ok": self.ok,
        }


def audit_custom_patterns(conn: sqlite3.Connection
                          ) -> CustomPatternsAudit:
    """Re-prove the slice's standing invariants over a
    live database: the tables stand; every active
    pattern has a complete dry-run of its current
    text standing behind it; no dry-run or match is
    orphaned."""
    problems: list = []
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()}
    for table in ("custom_patterns", "custom_pattern_dry_runs",
                  "custom_pattern_dry_run_matches"):
        if table not in tables:
            problems.append(f"table_missing:{table}")
    if problems:
        return CustomPatternsAudit(0, 0, tuple(problems))
    total = int(conn.execute(
        "SELECT COUNT(*) FROM custom_patterns").fetchone()[0])
    active_rows = conn.execute(
        "SELECT id, regex_sha FROM custom_patterns"
        " WHERE state = 'active'").fetchall()
    for row in active_rows:
        latest = conn.execute(
            "SELECT pattern_sha, status FROM"
            " custom_pattern_dry_runs WHERE pattern_id = ?"
            " ORDER BY id DESC LIMIT 1",
            (int(row[0]),)).fetchone()
        if latest is None:
            problems.append(
                f"active_without_dry_run:{int(row[0])}")
        elif latest[0] != row[1]:
            problems.append(f"active_stale_dry_run:{int(row[0])}")
        elif latest[1] != "complete":
            problems.append(
                f"active_incomplete_dry_run:{int(row[0])}")
    orphan_runs = int(conn.execute(
        "SELECT COUNT(*) FROM custom_pattern_dry_runs d"
        " LEFT JOIN custom_patterns p ON p.id = d.pattern_id"
        " WHERE p.id IS NULL").fetchone()[0])
    if orphan_runs:
        problems.append(f"orphan_dry_runs:{orphan_runs}")
    orphan_matches = int(conn.execute(
        "SELECT COUNT(*) FROM custom_pattern_dry_run_matches m"
        " LEFT JOIN custom_pattern_dry_runs d"
        " ON d.id = m.dry_run_id WHERE d.id IS NULL"
    ).fetchone()[0])
    if orphan_matches:
        problems.append(f"orphan_matches:{orphan_matches}")
    return CustomPatternsAudit(
        total, len(active_rows), tuple(problems))


# --- the page faces --------------------------------------------------------------


def render_custom_patterns_page(patterns,
                                title: str = "Custom patterns"
                                ) -> str:
    """The patterns face: scopes, names, states and
    regexes as their managers wrote them -- a pattern
    is a definition, not a secret."""
    from .escaping import escape_html_text
    rows = "".join(
        "<li>" + escape_html_text(p.name)
        + " [" + escape_html_text(p.scope)
        + ((" / " + escape_html_text(p.org_name))
           if p.org_name else "")
        + "] -- " + escape_html_text(p.state)
        + ": " + escape_html_text(p.regex) + "</li>"
        for p in patterns)
    if not rows:
        rows = "<li>No custom patterns defined.</li>"
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1><ul>" + rows + "</ul></body></html>")


def render_dry_run_page(run: DryRun, matches=(),
                        pattern: CustomPattern | None = None,
                        title: str = "Pattern dry-run") -> str:
    """The dry-run's face: coverage and matches in
    words, redacted only -- never a matched text."""
    from .escaping import escape_html_text
    rows = "".join(
        "<li>" + escape_html_text(m.path)
        + " @ " + escape_html_text(m.commit_oid[:12])
        + ", line " + str(m.line)
        + ": " + escape_html_text(m.redacted) + "</li>"
        for m in matches)
    if not rows:
        rows = "<li>No matches in the judged history.</li>"
    status_words = (
        "complete -- the whole history from the named "
        "tips was judged" if run.status == "complete" else
        "partial -- the dry-run stopped at a named cap: "
        + run.partial_reason)
    heading = (
        escape_html_text(pattern.name) if pattern is not None
        else "pattern " + str(run.pattern_id))
    truncated = (
        "; only the first " + str(run.matches_stored)
        + " matches are stored"
        if run.matches_stored < run.matches_count else "")
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1><p>Dry-run of " + heading
        + " against " + escape_html_text(run.repo_full_name)
        + ": " + escape_html_text(status_words)
        + ". Commits scanned: " + str(run.commits_scanned)
        + "; blobs scanned: " + str(run.blobs_scanned)
        + "; blobs skipped: " + str(run.blobs_skipped)
        + "; matches: " + str(run.matches_count)
        + escape_html_text(truncated)
        + ".</p><ul>" + rows + "</ul></body></html>")
