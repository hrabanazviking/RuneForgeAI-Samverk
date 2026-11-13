"""Code scanning alerts UI (S-304).

Roadmap S-304: Code scanning alerts UI -- alert
list and detail with rule help, locations, and
dismissal reasons; PR annotations for findings on
changed lines.

S-302 stores SARIF uploads per commit and S-303
settles them into alerts -- one fingerprint on one
branch, open or fixed -- and stops there: the API
face answers data, but no page shows a person the
alerts, no page explains the rule that fired, and
no one can answer an alert that should not stand.
This module is that surface, built on S-303's rows
alone:

- **The list and the detail are pages.** One
  repository's alerts render as an escaped HTML
  list -- state, rule, level, message and location
  per alert, newest first, narrowed by branch and
  by state exactly where S-303's API narrows them
  -- and one alert renders whole: its rule's help
  (below), every location its finding stands at,
  its fingerprint and basis, when it was first and
  most recently reported, its sighting history,
  and its dismissal standing. Standing is always
  said in words beside any mark -- never a colour
  alone -- and every rendered value escapes
  through S-010.
- **Rule help comes from the upload itself.** A
  SARIF run's tool driver carries its rules'
  metadata -- name, short and full description,
  help text and help URI. The detail reads the
  alert's most recently reporting upload (falling
  back to its first) out of S-302's store and
  lifts the matching rule's help whole, through
  the pure `rule_help_for`. Where the upload
  carried no rule metadata -- or none for this
  rule -- the page says so plainly: no help is
  invented, and the absence is itself shown.
- **All locations, not only the first.** S-303's
  alert row carries the finding's primary
  location; a SARIF result may stand at several.
  The pure `locations_for` re-walks the reporting
  upload's document, matches its results to the
  alert by S-303's own fingerprint, and lifts
  every location of every matching result,
  deduplicated in document order. Where no
  matching result stands in the uploads read
  (a defensive floor, never the expected road),
  the detail falls back to the alert row's own
  primary location and the page still stands.
- **Dismissal is a human act, with reasons.**
  Modelled on S-294's secret-alert lifecycle: an
  open alert may be dismissed under exactly one
  dismissal kind from a closed set --
  `false_positive` (the finding is not a real
  problem), `wont_fix` (the problem is known and
  accepted), `used_in_tests` (the flagged code
  exists only for tests) -- always with the
  dismisser's stated reason in their own words;
  a dismissal without its kind is refused
  `dismissal_invalid` naming the three, one
  without a stated reason is `reason_required`,
  and one past the stated cap is
  `reason_too_long`. A dismissed alert may be
  reopened, with a stated reason, and reopening
  clears the standing dismissal whole. Dismissing
  an already-dismissed alert is refused
  `code_scanning_alert_already_dismissed`;
  dismissing a fixed one is
  `code_scanning_alert_not_open` (there is
  nothing live to answer -- the scanner already
  closed it); reopening one that stands
  undismissed is `code_scanning_alert_not_dismissed`.
  The standing dismissal lives on the alert row
  (migration 125's columns) and every transition
  stands as a row on the alert's own events
  record, written inside the same transaction
  that moves the alert, so the record can never
  claim a transition the alert does not show.
  A dismissed alert reads as dismissed in the
  list, the detail and the counts: its effective
  state is `dismissed` while a dismissal stands,
  whatever the scanner state underneath does --
  S-303's transitions keep settling the scanner
  state (open / fixed) beneath it, and reopening
  returns the alert to that standing state.
- **Permitted roles only, judged by S-190.** A
  person's standing is their S-190
  `PermissionEngine` role in the repository,
  never re-derived here. The permitted rungs are
  `admin` and `maintain` -- the two rungs that
  already answer for a repository's safety, the
  S-294 precedent and the rungs S-293 trusts at
  the bypass door. Every other rung, no access
  and anonymity are refused
  `dismissal_not_permitted`. The pure check
  (`decide_dismissal` / the store's `judge`)
  writes nothing. Reads follow S-294's read law:
  anyone holding any role in the repository may
  read; a stranger to a private repository gets
  the uniform `repo_not_found` before any alert
  position is named, and an alert id standing in
  no repository the reader may read is the one
  `code_scanning_alert_not_found`, as at S-303's
  door.
- **PR annotations stand only on changed lines.**
  For a pull request, the changed lines are
  S-104's diff over the pull request's current
  branches, read through S-145's files view --
  never a re-derived diff parse here. A line is
  changed where the diff adds it (an `add` line's
  head-side number); context lines stand in the
  diff but are unchanged, and findings on them
  are NOT annotated. The pure
  `annotations_for_diff` lays the head branch's
  open, undismissed alerts over those changed
  lines: an alert annotates the pull request
  exactly where its artifact and line meet a
  changed line, and nowhere else. Fixed and
  dismissed alerts annotate nothing -- the one
  is no longer reported, the other already
  answered by a person.
- **Unwitnessed in the audit taxonomy -- said
  plainly, with the rationale judged.** No new
  taxonomy event: 135 stand (33 auth / 89 repo /
  13 admin), and the battery proves the audit log
  does not move across a dismiss, a reopen and a
  re-dismiss. S-302's uploads and S-303's alerts
  are derived data and unwitnessed; a dismissal
  is a human act, but the S-294 precedent governs
  it: a lifecycle transition changes no code,
  lands no push and lets nothing in -- unlike
  S-293's bypass, which does land one and is
  witnessed for exactly that reason. The
  dismissal's witness is its own events table,
  complete and in-transaction, exactly as
  S-294's is.

Storage is migration 125's dismissal columns on
``code_scanning_alerts`` plus the
``code_scanning_alert_events`` table (schema
124 -> 125); the suite's standing schema pins
moved in-slice, its taxonomy pins unmoved.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .code_scanning_alerts import _result_finding, fingerprint_finding
from .diff_engine import DiffSet
from .escaping import escape_html_text
from .issues import IssueStore
from .permission_engine import PermissionEngine
from .pull_request_files import PullRequestFilesStore
from .pull_requests import PullRequestError
from .repositories import RepositoryError, RepositoryStore
from .team_permissions import role_word

__all__ = [
    "ALERT_NOT_FOUND", "ALERT_ALREADY_DISMISSED",
    "ALERT_NOT_DISMISSED", "ALERT_NOT_OPEN",
    "DISMISSALS", "DISMISSAL_INVALID",
    "DISMISSAL_NOT_PERMITTED", "DISMISSAL_WORDS",
    "EFFECTIVE_STATES", "MAX_REASON_CHARS",
    "PERMITTED_ROLES", "REASON_REQUIRED",
    "REASON_TOO_LONG", "STATE_INVALID",
    "AlertDetail", "AlertLocation",
    "CodeScanningAlertView", "CodeScanningUIError",
    "CodeScanningUIStore", "DismissalDecision",
    "DismissalEvent", "PrAnnotation", "RuleHelp",
    "annotations_for_diff", "changed_lines_by_path",
    "decide_dismissal", "dismissal_word",
    "locations_for", "render_alert_detail_page",
    "render_alerts_page", "render_annotations_page",
    "rule_help_for", "validate_dismissal",
    "validate_reason",
]

#: The three dismissal kinds the roadmap's
#: "dismissal reasons" names, as stored slugs --
#: GitHub's own code-scanning dismissal vocabulary.
#: Their read words are below.
DISMISSALS = frozenset(
    {"false_positive", "wont_fix", "used_in_tests"})

DISMISSAL_WORDS = {
    "false_positive": "false positive",
    "wont_fix": "won't fix",
    "used_in_tests": "used in tests",
}

#: The rungs that may dismiss or reopen: the two
#: that already answer for a repository's safety
#: (the S-294 precedent).
PERMITTED_ROLES = frozenset({"admin", "maintain"})

#: A stated reason is a sentence a person owns,
#: not an essay: the cap is said, never silent.
MAX_REASON_CHARS = 500

DISMISSAL_INVALID = "dismissal_invalid"
DISMISSAL_NOT_PERMITTED = "dismissal_not_permitted"
REASON_REQUIRED = "reason_required"
REASON_TOO_LONG = "reason_too_long"
ALERT_NOT_FOUND = "code_scanning_alert_not_found"
ALERT_ALREADY_DISMISSED = "code_scanning_alert_already_dismissed"
ALERT_NOT_DISMISSED = "code_scanning_alert_not_dismissed"
ALERT_NOT_OPEN = "code_scanning_alert_not_open"
STATE_INVALID = "state_invalid"

#: The states an alert reads in on this surface:
#: its scanner state (S-303's `open` / `fixed`)
#: unless a dismissal stands, when it reads
#: `dismissed` whatever the scanner state does.
EFFECTIVE_STATES = frozenset({"open", "fixed", "dismissed"})


class CodeScanningUIError(RepositoryError):
    """A code-scanning UI error: a RepositoryError
    carrying `.reason`, in the house shape."""


def dismissal_word(dismissal: object) -> str:
    """A dismissal kind said in words a person
    reads; an unknown kind is refused loudly."""
    if dismissal not in DISMISSAL_WORDS:
        raise CodeScanningUIError(
            DISMISSAL_INVALID,
            f"Unknown dismissal kind: {dismissal!r}. "
            f"An alert is dismissed as a false "
            f"positive, won't fix, or used in tests "
            f"-- no other kind stands.")
    return DISMISSAL_WORDS[dismissal]  # type: ignore[index]


def validate_dismissal(dismissal: object) -> str:
    """The dismissal kind, cleaned -- or a named
    refusal naming the three kinds that stand."""
    if not isinstance(dismissal, str) \
            or dismissal not in DISMISSALS:
        raise CodeScanningUIError(
            DISMISSAL_INVALID,
            f"Unknown dismissal kind: {dismissal!r}. "
            f"An alert is dismissed as 'false_positive' "
            f"(the finding is not a real problem), "
            f"'wont_fix' (the problem is known and "
            f"accepted) or 'used_in_tests' (the "
            f"flagged code exists only for tests) -- "
            f"no other kind stands.")
    return dismissal


def validate_reason(reason: object) -> str:
    """The stated reason, cleaned -- or a named
    refusal. A transition without a reason is
    refused, never defaulted."""
    if not isinstance(reason, str) or not reason.strip():
        raise CodeScanningUIError(
            REASON_REQUIRED,
            "A code-scanning dismissal or reopening "
            "needs a stated reason: the actor's own "
            "words for why this alert moves. A "
            "transition without its reason is an "
            "unaccountable act, and this slice "
            "builds none.")
    cleaned = reason.strip()
    if len(cleaned) > MAX_REASON_CHARS:
        raise CodeScanningUIError(
            REASON_TOO_LONG,
            f"A dismissal reason is at most "
            f"{MAX_REASON_CHARS} characters; this one "
            f"runs {len(cleaned)}. Say the reason "
            f"plainly and briefly.")
    return cleaned


# --- SARIF rule help and locations (pure) ----------


@dataclass(frozen=True)
class RuleHelp:
    """One rule's help, as its SARIF upload carried
    it: the rule's name and its short and full
    descriptions, help text and help URI, each
    empty where the upload stated none. `present`
    is true where the upload carried any metadata
    for this rule at all."""
    rule_id: str
    name: str
    short_description: str
    full_description: str
    help_text: str
    help_uri: str

    @property
    def present(self) -> bool:
        return bool(self.name or self.short_description
                    or self.full_description
                    or self.help_text or self.help_uri)

    def words(self) -> str:
        """The help position in one sentence, in
        words -- the absence said as plainly as
        the presence."""
        if not self.present:
            return ("No rule help was carried for this "
                    "rule in the upload that reported "
                    "it: the scanner stated no name, "
                    "description or help for it, and "
                    "none is invented here.")
        bits = []
        if self.short_description:
            bits.append(self.short_description)
        if self.full_description \
                and self.full_description != self.short_description:
            bits.append(self.full_description)
        if self.help_text:
            bits.append(self.help_text)
        return " ".join(bits)


def _text_of(node: object) -> str:
    """A SARIF message node's text, where it is an
    object carrying a string `text`; else empty."""
    if isinstance(node, dict) \
            and isinstance(node.get("text"), str):
        return node["text"]
    return ""


def rule_help_for(document: object, tool_name: str,
                  rule_id: str) -> RuleHelp:
    """One rule's help out of one judged SARIF
    document: the rule whose id matches, in a run
    of the alert's own tool where one stands (any
    run carrying the rule otherwise). Shapes are
    read defensively, never trusted. Pure."""
    empty = RuleHelp(rule_id=rule_id, name="",
                     short_description="",
                     full_description="", help_text="",
                     help_uri="")
    if not isinstance(document, dict) or not rule_id:
        return empty
    runs = document.get("runs")
    if not isinstance(runs, list):
        return empty
    ordered = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        tool = run.get("tool")
        driver = tool.get("driver") \
            if isinstance(tool, dict) else None
        if not isinstance(driver, dict):
            continue
        name = driver.get("name")
        ordered.append(
            (name == tool_name, driver.get("rules")))
    # The alert's own tool first, then every run.
    ordered.sort(key=lambda pair: not pair[0])
    for _, rules in ordered:
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if rule.get("id") != rule_id \
                    and rule.get("name") != rule_id:
                continue
            return RuleHelp(
                rule_id=rule_id,
                name=rule["name"]
                if isinstance(rule.get("name"), str)
                else "",
                short_description=_text_of(
                    rule.get("shortDescription")),
                full_description=_text_of(
                    rule.get("fullDescription")),
                help_text=_text_of(rule.get("help")),
                help_uri=rule["helpUri"]
                if isinstance(rule.get("helpUri"), str)
                else "")
    return empty


@dataclass(frozen=True)
class AlertLocation:
    """One place a finding stands: an artifact and
    its region's start line and column (line and
    column zero where the result named none)."""
    uri: str
    line: int
    column: int

    def words(self) -> str:
        if not self.uri:
            return "no location"
        out = self.uri
        if self.line:
            out += f" line {self.line}"
            if self.column:
                out += f" column {self.column}"
        return out


def _location_of(location: object) -> AlertLocation | None:
    if not isinstance(location, dict):
        return None
    physical = location.get("physicalLocation")
    if not isinstance(physical, dict):
        return None
    uri = ""
    artifact = physical.get("artifactLocation")
    if isinstance(artifact, dict) \
            and isinstance(artifact.get("uri"), str):
        uri = artifact["uri"]
    line = 0
    column = 0
    region = physical.get("region")
    if isinstance(region, dict):
        start_line = region.get("startLine")
        start_col = region.get("startColumn")
        if isinstance(start_line, int) \
                and not isinstance(start_line, bool) \
                and start_line > 0:
            line = start_line
        if isinstance(start_col, int) \
                and not isinstance(start_col, bool) \
                and start_col > 0:
            column = start_col
    if not uri and not line:
        return None
    return AlertLocation(uri=uri, line=line, column=column)


def locations_for(document: object,
                  fingerprint: str) -> tuple:
    """Every location of every result in one judged
    SARIF document whose S-303 fingerprint is the
    alert's, deduplicated in document order. Pure."""
    if not isinstance(document, dict):
        return ()
    out: list = []
    seen: set = set()
    for run in document.get("runs") or ():
        if not isinstance(run, dict):
            continue
        tool = run.get("tool")
        driver = tool.get("driver") \
            if isinstance(tool, dict) else None
        name = driver.get("name") \
            if isinstance(driver, dict) else None
        tool_name = name if isinstance(name, str) else ""
        for result in run.get("results") or ():
            if not isinstance(result, dict):
                continue
            found, _basis = fingerprint_finding(
                _result_finding(tool_name, result))
            if found != fingerprint:
                continue
            locations = result.get("locations")
            if not isinstance(locations, list):
                continue
            for raw in locations:
                place = _location_of(raw)
                if place is None or place in seen:
                    continue
                seen.add(place)
                out.append(place)
    return tuple(out)


# --- the pure judgement ------------------------------


@dataclass(frozen=True)
class DismissalDecision:
    """The pure judgement: may this person move
    this alert, holding this role, in this way, for
    this stated reason? A refusal carries its named
    code and its sentence. `words` says the whole
    position in plain text. Pure: writes nothing."""
    may_move: bool
    action: str            # dismiss | reopen
    role: str | None
    source: str
    code: str              # "" when may_move
    reason: str            # the refusal sentence; "" when may_move
    words: str


def _permitted_words() -> str:
    return ", ".join(
        role_word(r) for r in ("maintain", "admin"))


def decide_dismissal(*, action: str, role: str | None,
                     source: str = "none",
                     actor: str | None = None,
                     full_name: str = "",
                     alert_state: str = "open",
                     dismissal: object = None,
                     reason: object = "") -> DismissalDecision:
    """Judge one dismissal ask, in the house order:
    the state the alert stands in first (a move the
    alert's own state forbids is refused before any
    person is judged), then the person's rung, then
    -- on a dismiss -- the dismissal kind, then the
    stated reason. `alert_state` is the alert's
    effective state: open, fixed or dismissed."""
    who = f"'{actor}'" if actor else "an anonymous actor"
    verb = "dismiss" if action == "dismiss" else "reopen"
    if action == "dismiss" and alert_state == "dismissed":
        return DismissalDecision(
            may_move=False, action=action, role=role,
            source=source, code=ALERT_ALREADY_DISMISSED,
            reason=(
                f"This alert in {full_name} already "
                f"stands dismissed; it cannot be "
                f"dismissed again. Reopen it first if "
                f"the dismissal no longer holds."),
            words=(
                f"The alert in {full_name} already "
                f"stands dismissed: dismissing it again "
                f"would overwrite the standing "
                f"dismissal and its record."))
    if action == "dismiss" and alert_state == "fixed":
        return DismissalDecision(
            may_move=False, action=action, role=role,
            source=source, code=ALERT_NOT_OPEN,
            reason=(
                f"This alert in {full_name} stands "
                f"fixed, not open; there is no live "
                f"finding to dismiss. Only an open "
                f"alert is dismissed."),
            words=(
                f"The alert in {full_name} stands "
                f"fixed: the scanner no longer reports "
                f"it, and dismissal answers a live "
                f"finding."))
    if action == "reopen" and alert_state != "dismissed":
        return DismissalDecision(
            may_move=False, action=action, role=role,
            source=source, code=ALERT_NOT_DISMISSED,
            reason=(
                f"This alert in {full_name} stands "
                f"{alert_state}, not dismissed; there "
                f"is no dismissal to reopen. Only a "
                f"dismissed alert reopens."),
            words=(
                f"The alert in {full_name} stands "
                f"{alert_state}: reopening answers a "
                f"dismissal, and this alert has none "
                f"standing."))
    if role not in PERMITTED_ROLES:
        held = (f"holds the {role_word(role)} role"
                if role else "holds no role")
        return DismissalDecision(
            may_move=False, action=action, role=role,
            source=source, code=DISMISSAL_NOT_PERMITTED,
            reason=(
                f"Code-scanning {verb} in {full_name} "
                f"was refused: {who} {held}, and only "
                f"the permitted roles may move a "
                f"code-scanning alert "
                f"({_permitted_words()}). Ask a "
                f"repository maintainer to act, or be "
                f"granted a permitted role first."),
            words=(
                f"{who} may not {verb} a code-scanning "
                f"alert in {full_name}: only "
                f"{_permitted_words()} may, and every "
                f"transition records its actor and "
                f"reason."))
    if action == "dismiss":
        try:
            validate_dismissal(dismissal)
        except CodeScanningUIError as exc:
            return DismissalDecision(
                may_move=False, action=action, role=role,
                source=source, code=exc.reason,
                reason=str(exc),
                words=(
                    f"{who} may not dismiss the alert "
                    f"in {full_name} under that kind: "
                    f"an alert is dismissed as a false "
                    f"positive, won't fix, or used in "
                    f"tests, and the kind is part of "
                    f"the record."))
    try:
        validate_reason(reason)
    except CodeScanningUIError as exc:
        return DismissalDecision(
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
        f" as {dismissal_word(dismissal)}"
        if action == "dismiss" else "")
    return DismissalDecision(
        may_move=True, action=action, role=role,
        source=source, code="", reason="",
        words=(
            f"{who} may {verb} the alert in "
            f"{full_name} as {role_word(role)}{kind_words}: "
            f"the transition will stand on the "
            f"alert's own record with its reason."))


# --- the records -------------------------------------


@dataclass(frozen=True)
class CodeScanningAlertView:
    """One code-scanning alert as this surface
    carries it: S-303's standing facts plus, while
    a dismissal stands, the dismissal kind, the
    dismisser and the stated reason. Its
    `effective_state` is `dismissed` while a
    dismissal stands, else the scanner state."""
    id: int
    repo_id: int
    full_name: str
    branch: str
    fingerprint: str
    basis: str
    tool_name: str
    rule_id: str
    level: str
    message: str
    artifact_uri: str
    start_line: int
    start_column: int
    state: str
    first_seen_upload_id: int
    first_seen_oid: str
    last_seen_upload_id: int
    last_seen_oid: str
    fixed_upload_id: int | None
    fixed_oid: str
    times_seen: int
    times_fixed: int
    created_at: int
    updated_at: int
    dismissal: str         # "" unless dismissed
    dismissed_by_id: int | None
    dismissed_by: str      # "" unless dismissed
    dismissed_at: int | None
    dismissal_reason: str  # "" unless dismissed

    @property
    def is_dismissed(self) -> bool:
        return self.dismissed_at is not None

    @property
    def effective_state(self) -> str:
        return "dismissed" if self.is_dismissed else self.state

    @property
    def primary_location(self) -> AlertLocation:
        return AlertLocation(uri=self.artifact_uri,
                             line=self.start_line,
                             column=self.start_column)

    def state_words(self) -> str:
        """The standing position in one sentence, in
        words -- never colour alone."""
        if self.is_dismissed:
            return (
                f"dismissed as "
                f"{dismissal_word(self.dismissal)} by "
                f"{self.dismissed_by}: "
                f"{self.dismissal_reason}")
        if self.state == "fixed":
            return ("fixed -- the latest processed run "
                    "on this branch no longer reports it")
        return "open -- reported by the latest processed run"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "repository": self.full_name,
            "branch": self.branch,
            "fingerprint": self.fingerprint,
            "basis": self.basis,
            "tool": self.tool_name,
            "rule_id": self.rule_id,
            "level": self.level,
            "message": self.message,
            "artifact_uri": self.artifact_uri,
            "start_line": self.start_line,
            "start_column": self.start_column,
            "state": self.state,
            "effective_state": self.effective_state,
            "first_seen_upload": self.first_seen_upload_id,
            "first_seen_oid": self.first_seen_oid,
            "last_seen_upload": self.last_seen_upload_id,
            "last_seen_oid": self.last_seen_oid,
            "fixed_upload": self.fixed_upload_id,
            "fixed_oid": self.fixed_oid,
            "times_seen": self.times_seen,
            "times_fixed": self.times_fixed,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "dismissal": self.dismissal or None,
            "dismissed_by_id": self.dismissed_by_id,
            "dismissed_by": self.dismissed_by or None,
            "dismissed_at": self.dismissed_at,
            "dismissal_reason": self.dismissal_reason or None,
        }


@dataclass(frozen=True)
class DismissalEvent:
    """One standing transition on an alert's own
    record: who moved it, from what effective state
    to what, under what kind (on a dismiss), and
    why, in their own words."""
    id: int
    alert_id: int
    repo_id: int
    action: str            # dismiss | reopen
    from_state: str
    to_state: str
    dismissal: str         # "" on a reopen
    actor_id: int
    actor_username: str
    role: str
    role_source: str
    reason: str
    created_at: int

    def words(self) -> str:
        if self.action == "dismiss":
            return (
                f"{self.actor_username} dismissed this "
                f"alert as "
                f"{dismissal_word(self.dismissal)}: "
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
            "dismissal": self.dismissal or None,
            "actor_id": self.actor_id,
            "actor": self.actor_username,
            "role": self.role,
            "role_source": self.role_source,
            "reason": self.reason,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class AlertDetail:
    """One alert whole: the alert, its rule help,
    every location it stands at, its dismissal
    record, and its sighting history in words."""
    alert: CodeScanningAlertView
    rule_help: RuleHelp
    locations: tuple       # of AlertLocation
    events: tuple          # of DismissalEvent, oldest first
    history: tuple         # of str, oldest first


@dataclass(frozen=True)
class PrAnnotation:
    """One finding laid on one changed line of a
    pull request: the alert, and the head-side line
    it annotates."""
    alert_id: int
    rule_id: str
    level: str
    message: str
    path: str
    line: int
    branch: str
    fingerprint: str

    def words(self) -> str:
        return (
            f"{self.level} from rule {self.rule_id} "
            f"on changed line {self.line} of "
            f"{self.path}: {self.message}")

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "rule_id": self.rule_id,
            "level": self.level,
            "message": self.message,
            "path": self.path,
            "line": self.line,
            "branch": self.branch,
            "fingerprint": self.fingerprint,
        }


def changed_lines_by_path(diff: DiffSet) -> dict:
    """The changed lines of one S-104 diff, by file
    path: the head-side numbers of its added lines.
    Context lines stand in the diff but are not
    changed, and deleted lines have no head side.
    Pure."""
    out: dict = {}
    for file in diff.files:
        changed = frozenset(
            line.new_number for line in file.lines
            if line.kind == "add"
            and line.new_number is not None)
        if changed:
            out[file.path] = changed
    return out


def annotations_for_diff(alerts, diff: DiffSet) -> tuple:
    """The annotations one diff carries: every open,
    undismissed alert whose artifact and line meet
    a changed line, in alert order. Fixed and
    dismissed alerts annotate nothing. Pure."""
    changed = changed_lines_by_path(diff)
    out = []
    for alert in alerts:
        if alert.effective_state != "open":
            continue
        lines = changed.get(alert.artifact_uri)
        if not lines or alert.start_line not in lines:
            continue
        out.append(PrAnnotation(
            alert_id=alert.id, rule_id=alert.rule_id,
            level=alert.level, message=alert.message,
            path=alert.artifact_uri, line=alert.start_line,
            branch=alert.branch,
            fingerprint=alert.fingerprint))
    return tuple(out)


def _row_to_view(row, full_name: str) -> CodeScanningAlertView:
    return CodeScanningAlertView(
        id=int(row["id"]), repo_id=int(row["repo_id"]),
        full_name=full_name, branch=row["branch"],
        fingerprint=row["fingerprint"], basis=row["basis"],
        tool_name=row["tool_name"], rule_id=row["rule_id"],
        level=row["level"], message=row["message"],
        artifact_uri=row["artifact_uri"],
        start_line=int(row["start_line"]),
        start_column=int(row["start_column"]),
        state=row["state"],
        first_seen_upload_id=int(row["first_seen_upload_id"]),
        first_seen_oid=row["first_seen_oid"],
        last_seen_upload_id=int(row["last_seen_upload_id"]),
        last_seen_oid=row["last_seen_oid"],
        fixed_upload_id=row["fixed_upload_id"],
        fixed_oid=row["fixed_oid"],
        times_seen=int(row["times_seen"]),
        times_fixed=int(row["times_fixed"]),
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
        dismissal=row["dismissal"] or "",
        dismissed_by_id=row["dismissed_by_id"],
        dismissed_by=row["dismissed_by"] or "",
        dismissed_at=row["dismissed_at"],
        dismissal_reason=row["dismissal_reason"] or "")


def _row_to_event(row) -> DismissalEvent:
    return DismissalEvent(
        id=int(row["id"]), alert_id=int(row["alert_id"]),
        repo_id=int(row["repo_id"]), action=row["action"],
        from_state=row["from_state"],
        to_state=row["to_state"],
        dismissal=row["dismissal"] or "",
        actor_id=int(row["actor_id"]),
        actor_username=row["actor_username"],
        role=row["role"], role_source=row["role_source"],
        reason=row["reason"],
        created_at=int(row["created_at"]))


# --- the store ---------------------------------------


class CodeScanningUIStore:
    """The S-304 surface over S-303's alerts: the
    list and detail reads, the dismissal life, and
    the pull-request annotations."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 accounts: AccountStore,
                 issues: IssueStore | None = None,
                 audit=None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._audit = audit
        self._now = time_fn
        self._engine = PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)

    # -- door --------------------------------------

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
            raise CodeScanningUIError(
                "repo_not_found", "No such repository.")
        resolution = self._engine.resolve(viewer, current)
        if resolution.role is None \
                and current.visibility != "public":
            raise CodeScanningUIError(
                "repo_not_found", "No such repository.")
        if any_role and resolution.role is None:
            raise CodeScanningUIError(
                "repo_not_found", "No such repository.")
        return current, resolution

    def _alert_row(self, repo_id: int, alert_id: int):
        try:
            wanted = int(alert_id)
        except (TypeError, ValueError):
            raise CodeScanningUIError(
                ALERT_NOT_FOUND,
                "code_scanning_alert_not_found -- no "
                "such code-scanning alert.") from None
        row = self._conn.execute(
            "SELECT * FROM code_scanning_alerts"
            " WHERE id = ? AND repo_id = ?",
            (wanted, repo_id)).fetchone()
        if row is None:
            raise CodeScanningUIError(
                ALERT_NOT_FOUND,
                f"No code-scanning alert {wanted} "
                f"stands in this repository.")
        return row

    def _events_for(self, repo_id: int, alert_id: int) -> tuple:
        rows = self._conn.execute(
            "SELECT * FROM code_scanning_alert_events"
            " WHERE alert_id = ? AND repo_id = ?"
            " ORDER BY id", (alert_id, repo_id)).fetchall()
        return tuple(_row_to_event(r) for r in rows)

    # -- reads -------------------------------------

    def get_alert(self, viewer: User | None, owner, repo,
                  alert_id) -> CodeScanningAlertView:
        """One alert with its standing dismissal."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        row = self._alert_row(current.id, alert_id)
        return _row_to_view(row, current.full_name)

    def list_alerts(self, viewer: User | None, owner, repo, *,
                    branch: str | None = None,
                    state: str | None = None,
                    limit: int = 100) -> tuple:
        """Newest first; optionally one branch and
        one effective state (`open` / `fixed` /
        `dismissed`)."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        if state is not None and state not in EFFECTIVE_STATES:
            raise CodeScanningUIError(
                STATE_INVALID,
                f"Unknown alert state: {state!r}")
        clamped = max(1, min(int(limit), 500))
        if branch is None:
            rows = self._conn.execute(
                "SELECT * FROM code_scanning_alerts"
                " WHERE repo_id = ? ORDER BY id DESC",
                (current.id,)).fetchall()
        else:
            from .code_scanning_alerts import branch_of
            rows = self._conn.execute(
                "SELECT * FROM code_scanning_alerts"
                " WHERE repo_id = ? AND branch = ?"
                " ORDER BY id DESC",
                (current.id, branch_of(branch))).fetchall()
        views = [_row_to_view(r, current.full_name)
                 for r in rows]
        if state is not None:
            views = [v for v in views
                     if v.effective_state == state]
        return tuple(views[:clamped])

    def count_alerts(self, viewer: User | None, owner, repo, *,
                     branch: str | None = None) -> dict:
        """Per-effective-state counts: open, fixed,
        dismissed, and their total. A dismissed
        alert counts as dismissed, never also under
        its scanner state."""
        views = self.list_alerts(
            viewer, owner, repo, branch=branch, limit=500)
        counts = {"open": 0, "fixed": 0, "dismissed": 0}
        for view in views:
            counts[view.effective_state] += 1
        counts["total"] = len(views)
        return counts

    def _upload_document(self, repo_id: int, upload_id: int):
        row = self._conn.execute(
            "SELECT sarif_text FROM code_scanning_uploads"
            " WHERE repo_id = ? AND id = ?",
            (repo_id, upload_id)).fetchone()
        if row is None:
            return None
        try:
            document = json.loads(row["sarif_text"])
        except (TypeError, ValueError):
            return None
        return document if isinstance(document, dict) else None

    def alert_detail(self, viewer: User | None, owner, repo,
                     alert_id) -> AlertDetail:
        """One alert whole: its rule help and every
        location from the upload that most recently
        reported it (its first upload where that one
        carries nothing for it), its dismissal
        record, and its sighting history in words."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        row = self._alert_row(current.id, alert_id)
        view = _row_to_view(row, current.full_name)
        help_found = RuleHelp(
            rule_id=view.rule_id, name="",
            short_description="", full_description="",
            help_text="", help_uri="")
        locations: tuple = ()
        for upload_id in (view.last_seen_upload_id,
                          view.first_seen_upload_id):
            document = self._upload_document(
                current.id, upload_id)
            if document is None:
                continue
            if not help_found.present:
                help_found = rule_help_for(
                    document, view.tool_name, view.rule_id)
            if not locations:
                locations = locations_for(
                    document, view.fingerprint)
            if help_found.present and locations:
                break
        if not locations:
            locations = (view.primary_location,)
        history = [
            f"First reported by upload "
            f"{view.first_seen_upload_id} at commit "
            f"{view.first_seen_oid}.",
            f"Most recently reported by upload "
            f"{view.last_seen_upload_id} at commit "
            f"{view.last_seen_oid}; seen "
            f"{view.times_seen} time(s) in all.",
        ]
        if view.times_fixed:
            history.append(
                f"Fixed {view.times_fixed} time(s) by a "
                f"run that no longer reported it.")
        if view.state == "fixed" \
                and view.fixed_upload_id is not None:
            history.append(
                f"Currently fixed: first not reported "
                f"by upload {view.fixed_upload_id} at "
                f"commit {view.fixed_oid}.")
        return AlertDetail(
            alert=view, rule_help=help_found,
            locations=locations,
            events=self._events_for(current.id, view.id),
            history=tuple(history))

    # -- the pure check ----------------------------

    def judge(self, actor: User | None, owner, repo,
              alert_id, *, action: str,
              dismissal: object = None,
              reason: object = "") -> DismissalDecision:
        """May this actor move this alert in this
        way? A pure read: writes nothing, records
        nothing."""
        current, resolved = self._resolve_repo(
            actor, owner, repo, any_role=False)
        row = self._alert_row(current.id, alert_id)
        view = _row_to_view(row, current.full_name)
        return decide_dismissal(
            action=action, role=resolved.role,
            source=resolved.source,
            actor=actor.username if actor is not None else None,
            full_name=current.full_name,
            alert_state=view.effective_state,
            dismissal=dismissal, reason=reason)

    # -- the acts ----------------------------------

    def _transition(self, actor: User | None, owner, repo,
                    alert_id, *, action: str,
                    dismissal: object = None,
                    reason: object = "") -> CodeScanningAlertView:
        current, resolved = self._resolve_repo(
            actor, owner, repo, any_role=False)
        row = self._alert_row(current.id, alert_id)
        view = _row_to_view(row, current.full_name)
        judgement = decide_dismissal(
            action=action, role=resolved.role,
            source=resolved.source,
            actor=actor.username if actor is not None else None,
            full_name=current.full_name,
            alert_state=view.effective_state,
            dismissal=dismissal, reason=reason)
        if not judgement.may_move:
            raise CodeScanningUIError(
                judgement.code, judgement.reason)
        cleaned_reason = validate_reason(reason)
        created_at = int(self._now())
        from_state = view.effective_state
        if action == "dismiss":
            kind = validate_dismissal(dismissal)
            with self._conn:
                self._conn.execute(
                    "UPDATE code_scanning_alerts"
                    " SET dismissal = ?,"
                    " dismissed_by_id = ?, dismissed_by = ?,"
                    " dismissed_at = ?,"
                    " dismissal_reason = ? WHERE id = ?",
                    (kind, actor.id, actor.username,
                     created_at, cleaned_reason, view.id))
                self._conn.execute(
                    "INSERT INTO code_scanning_alert_events ("
                    " alert_id, repo_id, action, from_state,"
                    " to_state, dismissal, actor_id,"
                    " actor_username, role, role_source,"
                    " reason, created_at)"
                    " VALUES (?, ?, 'dismiss', ?, 'dismissed',"
                    " ?, ?, ?, ?, ?, ?, ?)",
                    (view.id, current.id, from_state, kind,
                     actor.id, actor.username, resolved.role,
                     resolved.source, cleaned_reason,
                     created_at))
        else:
            with self._conn:
                self._conn.execute(
                    "UPDATE code_scanning_alerts"
                    " SET dismissal = '',"
                    " dismissed_by_id = NULL,"
                    " dismissed_by = '', dismissed_at = NULL,"
                    " dismissal_reason = '' WHERE id = ?",
                    (view.id,))
                self._conn.execute(
                    "INSERT INTO code_scanning_alert_events ("
                    " alert_id, repo_id, action, from_state,"
                    " to_state, dismissal, actor_id,"
                    " actor_username, role, role_source,"
                    " reason, created_at)"
                    " VALUES (?, ?, 'reopen', ?, ?,"
                    " '', ?, ?, ?, ?, ?, ?)",
                    (view.id, current.id, from_state,
                     view.state, actor.id, actor.username,
                     resolved.role, resolved.source,
                     cleaned_reason, created_at))
        return self.get_alert(actor, owner, repo, view.id)

    def dismiss_alert(self, actor: User | None, owner, repo,
                      alert_id, *,
                      dismissal: object = None,
                      reason: object = "") -> CodeScanningAlertView:
        """Dismiss one open alert under one of the
        three named kinds, with the dismisser and
        the stated reason recorded, and the
        transition standing on the alert's own
        record -- all before this answers."""
        return self._transition(
            actor, owner, repo, alert_id, action="dismiss",
            dismissal=dismissal, reason=reason)

    def reopen_alert(self, actor: User | None, owner, repo,
                     alert_id, *,
                     reason: object = "") -> CodeScanningAlertView:
        """Reopen one dismissed alert, with the actor
        and the stated reason recorded and the
        standing dismissal cleared whole -- all
        before this answers."""
        return self._transition(
            actor, owner, repo, alert_id, action="reopen",
            reason=reason)

    def list_events(self, viewer: User | None, owner, repo,
                    alert_id) -> tuple:
        """The alert's dismissal record, oldest
        first: every transition it has ever stood,
        unedited."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        row = self._alert_row(current.id, alert_id)
        return self._events_for(current.id, int(row["id"]))

    # -- PR annotations ----------------------------

    def pr_annotations(self, viewer: User | None, owner, repo,
                       number) -> tuple:
        """The annotations one pull request carries:
        its head branch's open, undismissed alerts
        laid over the changed lines of its current
        diff, read through S-145's files view. A
        stranger to a private repository gets the
        uniform `pull_request_not_found` of the
        pull-request seam itself."""
        if self._issues is None:
            raise CodeScanningUIError(
                "pull_request_not_found",
                "No such pull request.")
        files = PullRequestFilesStore(
            self._conn, self._repos, self._accounts,
            self._issues, audit=self._audit,
            time_fn=self._now)
        try:
            view = files.files_for(viewer, owner, repo, number)
        except PullRequestError as exc:
            raise CodeScanningUIError(
                exc.reason, str(exc)) from None
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        rows = self._conn.execute(
            "SELECT * FROM code_scanning_alerts"
            " WHERE repo_id = ? AND branch = ?"
            " ORDER BY id",
            (current.id, view.head_branch)).fetchall()
        alerts = [_row_to_view(r, current.full_name)
                  for r in rows]
        return annotations_for_diff(alerts, view.diff)


# --- the page faces -----------------------------------


def render_alerts_page(alerts, full_name: str,
                       counts: dict | None = None,
                       title: str = "Code scanning alerts") -> str:
    """The alerts face: the counts said in words
    first, then each alert with its state, rule,
    level and location -- every value escaped."""
    if counts is None:
        counts = {"open": 0, "fixed": 0, "dismissed": 0,
                  "total": 0}
        for alert in alerts:
            counts[alert.effective_state] += 1
            counts["total"] += 1
    summary = (
        f"{counts['total']} alert(s) in "
        f"{escape_html_text(full_name)}: "
        f"{counts['open']} open, {counts['fixed']} fixed, "
        f"{counts['dismissed']} dismissed.")
    rows = "".join(
        "<li>Alert #" + str(a.id)
        + " [" + escape_html_text(a.effective_state)
        + " -- " + escape_html_text(a.state_words()) + "] "
        + escape_html_text(a.level)
        + " from " + escape_html_text(a.tool_name)
        + (" rule " + escape_html_text(a.rule_id)
           if a.rule_id else "")
        + " on branch "
        + escape_html_text(a.branch or "the unnamed branch")
        + " at " + escape_html_text(a.primary_location.words())
        + ": " + escape_html_text(a.message) + "</li>"
        for a in alerts)
    if not rows:
        rows = "<li>No code scanning alerts.</li>"
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1><p>" + summary + "</p><ul>"
        + rows + "</ul></body></html>")


def render_alert_detail_page(detail: AlertDetail,
                             title: str = "Code scanning alert") -> str:
    """One alert's face whole: its standing in
    words, its rule help (or its honest absence),
    every location, its fingerprint basis, its
    sighting history and its dismissal record --
    every value escaped."""
    alert = detail.alert
    help_html = escape_html_text(detail.rule_help.words())
    if detail.rule_help.help_uri:
        help_html += (
            " Help: " + escape_html_text(
                detail.rule_help.help_uri))
    locations = "".join(
        "<li>" + escape_html_text(place.words()) + "</li>"
        for place in detail.locations)
    if not locations:
        locations = "<li>No location recorded.</li>"
    history = "".join(
        "<li>" + escape_html_text(line) + "</li>"
        for line in detail.history)
    events = "".join(
        "<li>" + escape_html_text(e.words())
        + " (" + escape_html_text(e.role) + ", "
        + escape_html_text(e.from_state) + " -> "
        + escape_html_text(e.to_state) + ")</li>"
        for e in detail.events)
    if not events:
        events = "<li>No dismissals or reopenings yet.</li>"
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1><p>Alert in "
        + escape_html_text(alert.full_name)
        + " on branch "
        + escape_html_text(alert.branch or "the unnamed branch")
        + " is " + escape_html_text(alert.effective_state)
        + " -- " + escape_html_text(alert.state_words())
        + ". " + escape_html_text(alert.level)
        + " from " + escape_html_text(alert.tool_name)
        + (" rule " + escape_html_text(alert.rule_id)
           if alert.rule_id else "")
        + ": " + escape_html_text(alert.message)
        + "</p><h2>Rule help</h2><p>" + help_html
        + "</p><h2>Locations</h2><ul>" + locations
        + "</ul><p>Fingerprint "
        + escape_html_text(alert.fingerprint)
        + " (" + escape_html_text(alert.basis)
        + " basis).</p><h2>History</h2><ul>" + history
        + "</ul><h2>Dismissal record</h2><ul>" + events
        + "</ul></body></html>")


def render_annotations_page(annotations, full_name: str,
                            number: int,
                            title: str = "Pull request annotations") -> str:
    """The annotations face: each finding said in
    words on the changed line it annotates --
    every value escaped."""
    rows = "".join(
        "<li>" + escape_html_text(a.words()) + "</li>"
        for a in annotations)
    if not rows:
        rows = ("<li>No code scanning findings stand "
                "on this pull request's changed lines.</li>")
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1><p>Annotations for "
        + escape_html_text(full_name)
        + " pull request #" + str(number)
        + ":</p><ul>" + rows + "</ul></body></html>")
