"""Dependency alerts (S-299).

Roadmap S-299: Dependency alerts -- graph x
advisory data -> alerts with severity, affected
range, and fixed version when known; alert
lifecycle as S-294.

S-297 graphs a repository's manifests into a
dependency table; S-298 bundles a dated snapshot
of public vulnerability data and rules that its
age is displayed wherever alerts are shown. This
slice is the join the two were built for, and the
life of the alerts it raises:

- **The join is a pure judgement first.**
  ``judge_dependency`` decides, for one dependency
  row and one advisory, whether the dependency
  stands in the advisory's affected range -- and
  says *how* it knows. A dependency whose
  specifier pins one exact version (S-297's
  ``resolved``) is judged on that version alone
  (basis ``pinned``). A range specifier is judged
  by range intersection: the alert stands when
  some version satisfies both the manifest's
  range and the advisory's affected range (basis
  ``range``). A specifier whose version shape
  cannot be judged at all -- a direct URL, a VCS
  reference, a filesystem path -- is *unjudged*:
  it raises no alert and is silently cleared of
  nothing either; the refresh report counts it,
  by name of its standing, so the gap is said
  wherever the counts are shown. Version
  comparison is the ecosystems' shared numeric
  shape (dotted numbers, an optional leading
  ``v``, an optional prerelease tail); range
  algebra is conjunctions of comparators, the
  shape public advisory data actually ships.
- **One alert per (dependency, advisory), ever.**
  An alert's identity is the repository, the
  ecosystem, the normalised package name, the
  manifest it stands in and the advisory id
  (migration 121's unique key) -- never the
  dependency row's id, which a re-graph replaces
  whole. Refreshing recomputes the join from the
  standing graph and the standing snapshot: a
  match with no alert creates one ``open``; a
  live alert whose match stands has its standing
  facts (specifier, severity, affected range,
  fixed version, snapshot date) brought current
  and nothing else touched; a *resolved* alert is
  a person's answer and refresh never moves it,
  in either direction.
- **A match that vanishes answers itself --
  honestly, as automatic.** When a re-graph moves
  a dependency out of the affected range (or out
  of the graph), a live alert for it no longer
  describes anything standing. Refresh resolves
  it ``fixed`` with no human resolver claimed:
  ``resolved_by`` stands empty, and the alert's
  own event record carries an ``auto_resolve``
  transition under the system actor (``samverk``,
  source ``system``) with the reason said in
  words. No surface ever dresses that up as a
  person's act.
- **The lifecycle is S-294's, word for word in
  shape.** Open (or reopened) -> resolved under
  one of three named kinds -- ``fixed`` (the
  dependency moved out of the affected range, or
  a fix otherwise landed), ``false_positive``
  (the match is wrong: the graph or the advisory
  misnames this dependency) or ``risk_accepted``
  (the vulnerability is real and the risk is
  knowingly carried) -- with the resolver and a
  stated reason always recorded, and reopening
  supported on the same terms. The permitted
  rungs are S-294's: ``admin`` and ``maintain``,
  judged by S-190's permission engine, never
  re-derived. A transition without its reason is
  refused ``reason_required``; resolving a
  resolved alert is ``alert_already_resolved``;
  reopening a live one is ``alert_not_resolved``;
  an unknown alert is ``alert_not_found``. Every
  human transition stands on migration 121's
  ``dependency_alert_events``, written in the
  same transaction that moves the alert row.
- **Severity, affected range, fixed version --
  as the advisory carries them.** The alert
  stores the advisory's severity, its affected
  range exactly as published, and its fixed
  version -- which is honestly ``None`` (*fix
  unknown*, said in those words on every
  surface) where the snapshot knows none. Nothing
  here invents a fix, upgrades a severity, or
  narrows a range.
- **The snapshot's age stands beside every
  alert.** Following S-298's law, every render
  surface in this module carries the advisory
  banner (snapshot date + age words, through
  ``render_advisory_banner``), and every alert
  records the snapshot date it was computed
  against. A stale snapshot raises stale alerts
  and says so; it never passes as current.
- **Reads follow the repository.** As at
  S-294's door, the alert reads answer to anyone
  holding any role in the repository; a stranger
  to a private repository gets the uniform
  ``repo_not_found`` before any alert position
  is named. Refresh is derived data over the
  standing graph -- rebuildable at any time, like
  the graph itself -- and is read-judged on the
  same terms as the dependency table it joins.
- **Unwitnessed in the audit taxonomy -- said
  plainly.** No new taxonomy event: 134 stand
  (33 auth / 88 repo / 13 admin), and the battery
  proves the audit log does not move across a
  refresh, a resolve, a reopen and a re-resolve.
  The reasoning is the neighbours': S-297's graph
  and S-294's lifecycle are unwitnessed for the
  same cause -- a refresh changes no code and
  lands no push, and a lifecycle transition lets
  nothing in. The alert's witness is its own
  events table, complete and in-transaction.

Storage is migration 121's ``dependency_alerts``
and ``dependency_alert_events`` tables (schema
120 -> 121 on this base; the keeper renumbers at
banking if later slices land first). S-298 is
not yet banked on this base: its module is read
here exactly as it will stand on the merged tree,
and its battery's schema pin will need the same
value move at banking that this slice's own
neighbours receive in-slice.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .advisory_data import (
    Advisory, AdvisoryStore, SnapshotInfo, render_advisory_banner)
from .dependency_graph import Dependency, DependencyGraphStore
from .escaping import escape_html_text
from .permission_engine import PermissionEngine
from .repositories import Repository, RepositoryError, RepositoryStore
from .team_permissions import role_word

__all__ = [
    "ALERT_NOT_FOUND", "ALERT_ALREADY_RESOLVED",
    "ALERT_NOT_RESOLVED", "BASIS_PINNED", "BASIS_RANGE",
    "DependencyAlert", "DependencyAlertError",
    "DependencyAlertEvent", "DependencyAlertStore",
    "DependencyMatch", "LIFECYCLE_NOT_PERMITTED",
    "MAX_REASON_CHARS", "PERMITTED_ROLES",
    "REASON_REQUIRED", "REASON_TOO_LONG",
    "RESOLUTION_INVALID", "RESOLUTIONS",
    "RESOLUTION_WORDS", "RefreshReport",
    "compare_versions", "decide_transition",
    "judge_dependency", "parse_version",
    "render_alert_page", "render_alerts_page",
    "resolution_word", "validate_resolution",
    "validate_reason", "version_in_range",
]

#: The three resolution kinds for a dependency
#: alert, as stored slugs. Their read words are
#: below. ``fixed`` is also the kind an automatic
#: resolution stands under (see the docstring).
RESOLUTIONS = frozenset(
    {"fixed", "false_positive", "risk_accepted"})

RESOLUTION_WORDS = {
    "fixed": "fixed",
    "false_positive": "false positive",
    "risk_accepted": "risk accepted",
}

#: The rungs that may move an alert: S-294's two,
#: the ones that already answer for a repository's
#: safety.
PERMITTED_ROLES = frozenset({"admin", "maintain"})

#: A stated reason is a sentence a person owns,
#: not an essay: S-294's cap, said never silent.
MAX_REASON_CHARS = 500

LIFECYCLE_NOT_PERMITTED = "lifecycle_not_permitted"
REASON_REQUIRED = "reason_required"
REASON_TOO_LONG = "reason_too_long"
RESOLUTION_INVALID = "resolution_invalid"
ALERT_NOT_FOUND = "alert_not_found"
ALERT_ALREADY_RESOLVED = "alert_already_resolved"
ALERT_NOT_RESOLVED = "alert_not_resolved"

#: The states an alert stands in (S-294's
#: vocabulary, carried whole).
LIVE_STATES = frozenset({"open", "reopened"})
ALERT_STATES = frozenset({"open", "resolved", "reopened"})

#: How a match was judged. ``pinned``: the
#: manifest pins one exact version and it stands
#: in the affected range. ``range``: the
#: manifest's range and the affected range share
#: at least one version.
BASIS_PINNED = "pinned"
BASIS_RANGE = "range"

#: The system actor an automatic resolution is
#: recorded under. It is a label, not an account:
#: actor_id stands NULL beside it, always.
SYSTEM_ACTOR = "samverk"
SYSTEM_SOURCE = "system"
AUTO_RESOLVE_REASON = (
    "The dependency no longer stands in the "
    "affected range (updated, removed, or the "
    "graph moved); resolved automatically by "
    "refresh, with no human resolver claimed.")

SEVERITY_ORDER = ("critical", "high", "moderate", "low")


class DependencyAlertError(RepositoryError):
    """A dependency-alert error: a RepositoryError
    carrying `.reason`, in the house shape."""


# ------------------------------------------------------------------
# Versions and ranges (pure)
# ------------------------------------------------------------------

_VERSION_RE = re.compile(
    r"^v?(\d+(?:\.\d+)*)"
    r"(?:-([0-9A-Za-z.-]+))?"
    r"(?:\+[0-9A-Za-z.-]+)?$")


def parse_version(value: object) -> tuple | None:
    """One version as a comparable key, or None
    when the text is no version this house can
    judge: dotted numbers, an optional leading
    ``v``, an optional prerelease tail, build
    metadata ignored. The key is (numbers,
    release-flag, prerelease parts): a release
    outranks its own prereleases, and prerelease
    identifiers compare numerically where they
    are numbers, lexically where they are not."""
    if not isinstance(value, str):
        return None
    match = _VERSION_RE.match(value.strip())
    if match is None:
        return None
    numbers = tuple(int(p) for p in match.group(1).split("."))
    pre = match.group(2)
    if pre is None:
        return (numbers, 1, ())
    parts = tuple(
        (0, int(p), "") if p.isdigit() else (1, 0, p)
        for p in pre.split("."))
    return (numbers, 0, parts)


def _pad(key_a: tuple, key_b: tuple) -> tuple:
    """Two version keys with their number tuples
    padded to one length, so 1.2 and 1.2.0 compare
    equal, as every ecosystem here treats them."""
    a_nums, b_nums = key_a[0], key_b[0]
    width = max(len(a_nums), len(b_nums))
    return (
        (a_nums + (0,) * (width - len(a_nums)),)
        + key_a[1:],
        (b_nums + (0,) * (width - len(b_nums)),)
        + key_b[1:])


def compare_versions(left: object, right: object) -> int | None:
    """-1 / 0 / 1 as *left* stands below / at /
    above *right*, or None when either side is
    not a judgeable version."""
    key_a, key_b = parse_version(left), parse_version(right)
    if key_a is None or key_b is None:
        return None
    key_a, key_b = _pad(key_a, key_b)
    return (key_a > key_b) - (key_a < key_b)


@dataclass(frozen=True)
class _Constraint:
    op: str                # < | <= | > | >= | = | !=
    version: tuple         # a parse_version key


def _parse_comparators(text: str) -> list | None:
    """A conjunction of comparators (``<5.4``,
    ``>=1.0,<2.0``, ``<=3.2.0``) as constraints,
    or None when any token is not one. A bare
    version token is an exact comparator."""
    out: list = []
    for token in re.split(r"[,\s]+", text.strip()):
        if not token:
            continue
        match = re.match(
            r"^(<=|>=|==|!=|<|>|=)?(.+)$", token)
        if match is None:
            return None
        op = match.group(1) or "="
        if op == "==":
            op = "="
        key = parse_version(match.group(2))
        if key is None:
            return None
        out.append(_Constraint(op, key))
    return out


def _satisfies(key: tuple, constraint: _Constraint) -> bool:
    mine, theirs = _pad(key, constraint.version)
    cmp = (mine > theirs) - (mine < theirs)
    return {"<": cmp < 0, "<=": cmp <= 0, ">": cmp > 0,
            ">=": cmp >= 0, "=": cmp == 0,
            "!=": cmp != 0}[constraint.op]


def _conjunction_satisfiable(constraints: list) -> bool:
    """Whether some version satisfies every
    constraint in the conjunction. Exact
    comparators pin the candidate; otherwise the
    strongest lower and upper bounds must leave a
    version standing between them."""
    exacts = [c for c in constraints if c.op == "="]
    if exacts:
        candidate = exacts[0].version
        return all(
            _satisfies(candidate, c) for c in constraints)
    lowers = [c for c in constraints if c.op in (">", ">=")]
    uppers = [c for c in constraints if c.op in ("<", "<=")]
    excluded = [c.version for c in constraints if c.op == "!="]
    lower = None
    for c in lowers:
        if lower is None:
            lower = c
            continue
        mine, theirs = _pad(c.version, lower.version)
        if mine > theirs or (mine == theirs
                             and c.op == ">" and lower.op == ">="):
            lower = c
    upper = None
    for c in uppers:
        if upper is None:
            upper = c
            continue
        mine, theirs = _pad(c.version, upper.version)
        if mine < theirs or (mine == theirs
                             and c.op == "<" and upper.op == "<="):
            upper = c
    if lower is not None and upper is not None:
        low_key, high_key = _pad(lower.version, upper.version)
        if low_key > high_key:
            return False
        if low_key == high_key:
            if lower.op == ">" or upper.op == "<":
                return False
            point = low_key
            return all(
                _pad(point, e)[0] != _pad(point, e)[1]
                for e in excluded)
    return True


def version_in_range(version: object, affected: object) -> bool | None:
    """Whether one pinned *version* stands in an
    advisory's *affected* range: True / False, or
    None when either side cannot be judged."""
    key = parse_version(version)
    if key is None or not isinstance(affected, str):
        return None
    constraints = _parse_comparators(affected)
    if constraints is None:
        return None
    return all(_satisfies(key, c) for c in constraints)


def _caret_upper(key: tuple) -> tuple:
    """The upper bound of a caret range: the
    leftmost non-zero number component bumps, the
    rest zero (semver's ^, Cargo's default)."""
    numbers = list(key[0])
    for i, part in enumerate(numbers):
        if part != 0:
            bumped = numbers[:i] + [part + 1] \
                + [0] * (len(numbers) - i - 1)
            return (tuple(bumped), 1, ())
    bumped = numbers[:-1] + [numbers[-1] + 1]
    return (tuple(bumped), 1, ())


def _specifier_constraints(ecosystem: str,
                           specifier: str) -> list | None:
    """One manifest specifier as a constraint
    conjunction, in its own ecosystem's semantics:

    - ``python``: PEP 440's common shapes --
      ``==`` (with a ``.*`` wildcard tail read as
      its range), ``>=`` / ``<=`` / ``>`` / ``<`` /
      ``!=`` lists, ``~=`` compatible-release, a
      bare name or empty specifier is unbounded.
    - ``npm``: bare / ``=`` exact, ``^`` and ``~``
      ranges, comparator lists, ``x`` wildcards,
      ``*`` / ``latest`` unbounded.
    - ``go``: the specifier is one exact version.
    - ``rust``: Cargo's shapes -- bare is a caret
      range, ``=`` exact, ``~`` and comparators,
      partial versions (``1``, ``1.2``) are their
      wildcard ranges, ``*`` unbounded.

    None means *unjudged*: the specifier carries
    no judgeable version shape at all (a URL, a
    VCS or path reference, a workspace alias).
    An empty list means *unbounded*: every version
    satisfies it, so it overlaps any affected
    range that has a version standing in it."""
    spec = specifier.strip()
    if not spec:
        return []
    lowered = spec.lower()
    if "://" in spec or spec.startswith(
            ("git+", "file:", "http:", "https:", "ssh:",
             "ftp:", "path:", "workspace:", "npm:",
             "github:", ".", "/", "@ http", "@ file")):
        return None
    if " @ " in spec or spec.startswith("@ "):
        return None
    if ecosystem == "go":
        key = parse_version(spec)
        return [_Constraint("=", key)] if key else None
    if ecosystem == "python":
        if "," not in spec and " " not in spec \
                and parse_version(spec) is None \
                and not spec.startswith(
                    ("=", "<", ">", "!", "~")):
            return []  # a bare name: unbounded
        if spec.startswith("~="):
            key = parse_version(spec[2:].strip())
            if key is None:
                return None
            numbers = key[0]
            if len(numbers) >= 2:
                upper_nums = numbers[:-2] + (numbers[-2] + 1,)
            else:
                upper_nums = (numbers[0] + 1,)
            return [_Constraint(">=", key),
                    _Constraint("<", (upper_nums, 1, ()))]
        if spec.startswith("==") \
                and spec.rstrip().endswith(".*"):
            key = parse_version(spec[2:].rstrip(".*"))
            if key is None:
                return None
            numbers = key[0]
            upper_nums = numbers[:-1] + (numbers[-1] + 1,)
            return [_Constraint(">=", key),
                    _Constraint("<", (upper_nums, 1, ()))]
        return _parse_comparators(spec.replace("===", "="))
    if ecosystem == "npm":
        if lowered in ("*", "latest", "x", ""):
            return []
        if spec.startswith(("^", "~")):
            key = parse_version(spec[1:].strip())
            if key is None:
                return None
            if spec.startswith("~"):
                numbers = key[0]
                upper_nums = (numbers[0], numbers[1] + 1) \
                    if len(numbers) > 1 else (numbers[0] + 1,)
                upper = (tuple(upper_nums), 1, ())
            else:
                upper = _caret_upper(key)
            return [_Constraint(">=", key),
                    _Constraint("<", upper)]
        if re.search(r"[xX*]$", spec) \
                and parse_version(spec) is None:
            base = re.sub(r"[.]?(?:[xX*])$", "", spec)
            key = parse_version(base)
            if key is None:
                return None
            numbers = key[0]
            upper_nums = numbers[:-1] + (numbers[-1] + 1,)
            return [_Constraint(">=", key),
                    _Constraint("<", (upper_nums, 1, ()))]
        return _parse_comparators(spec)
    if ecosystem == "rust":
        if lowered == "*":
            return []
        if spec.startswith(("^", "~")):
            return _specifier_constraints("npm", spec)
        if "," in spec or spec.startswith(("<", ">")):
            return _parse_comparators(spec)
        if spec.startswith("="):
            return _parse_comparators(spec)
        key = parse_version(spec)
        if key is None:
            return None
        numbers = key[0]
        if len(numbers) < 3:
            upper_nums = numbers[:-1] + (numbers[-1] + 1,)
            return [_Constraint(">=", key),
                    _Constraint("<", (tuple(upper_nums), 1, ()))]
        return [_Constraint(">=", key),
                _Constraint("<", _caret_upper(key))]
    return None


def _pinned_version(ecosystem: str,
                    specifier: str) -> str | None:
    """The one exact version a specifier pins, in
    the manifest's own semantics (S-297's
    ``resolved`` shapes), or None."""
    spec = specifier.strip()
    if ecosystem == "python":
        if spec.startswith("==") and "," not in spec \
                and "*" not in spec:
            version = spec[2:].strip()
            return version if parse_version(version) else None
        return None
    if ecosystem == "go":
        return spec if parse_version(spec) else None
    if ecosystem == "npm":
        version = spec[1:].strip() if spec.startswith("=") else spec
        return version if parse_version(version) else None
    if ecosystem == "rust":
        if spec.startswith("="):
            version = spec[1:].strip()
            return version if parse_version(version) else None
        return None
    return None


@dataclass(frozen=True)
class DependencyMatch:
    """The pure join's verdict for one dependency
    against one advisory: whether it stands, and
    on what basis."""
    matched: bool
    basis: str             # BASIS_PINNED | BASIS_RANGE | ""
    pinned_version: str    # "" unless a pin was judged
    unjudged: bool         # the specifier could not be judged


def judge_dependency(ecosystem: str, specifier: str,
                     affected: str) -> DependencyMatch:
    """Judge one dependency specifier against one
    advisory's affected range. Pure: no storage,
    no snapshot, no clock. A pinned specifier is
    judged on its version; a range specifier on
    whether the two ranges share a version; a
    specifier with no judgeable version shape is
    unjudged -- neither matched nor cleared."""
    pinned = _pinned_version(ecosystem, specifier)
    if pinned is not None:
        inside = version_in_range(pinned, affected)
        if inside is None:
            return DependencyMatch(False, "", pinned, True)
        return DependencyMatch(
            inside, BASIS_PINNED if inside else "", pinned, False)
    constraints = _specifier_constraints(ecosystem, specifier)
    if constraints is None:
        return DependencyMatch(False, "", "", True)
    affected_constraints = _parse_comparators(affected) \
        if isinstance(affected, str) else None
    if affected_constraints is None:
        return DependencyMatch(False, "", "", True)
    overlap = _conjunction_satisfiable(
        constraints + affected_constraints)
    return DependencyMatch(
        overlap, BASIS_RANGE if overlap else "", "", False)


# ------------------------------------------------------------------
# Resolution vocabulary (S-294's shape)
# ------------------------------------------------------------------

def resolution_word(resolution: object) -> str:
    """A resolution kind said in words a person
    reads; an unknown kind is refused loudly."""
    if resolution not in RESOLUTION_WORDS:
        raise DependencyAlertError(
            RESOLUTION_INVALID,
            f"Unknown resolution kind: {resolution!r}. "
            f"An alert resolves as fixed, a false "
            f"positive, or risk accepted -- no other "
            f"kind stands.")
    return RESOLUTION_WORDS[resolution]  # type: ignore[index]


def validate_resolution(resolution: object) -> str:
    """The resolution kind, cleaned -- or a named
    refusal naming the three kinds that stand."""
    if not isinstance(resolution, str) \
            or resolution not in RESOLUTIONS:
        raise DependencyAlertError(
            RESOLUTION_INVALID,
            f"Unknown resolution kind: {resolution!r}. "
            f"An alert resolves as 'fixed' (the "
            f"dependency moved out of the affected "
            f"range), 'false_positive' (the match "
            f"misnames this dependency) or "
            f"'risk_accepted' (the risk is knowingly "
            f"carried) -- no other kind stands.")
    return resolution


def validate_reason(reason: object) -> str:
    """The stated reason, cleaned -- or a named
    refusal. A transition without a reason is
    refused, never defaulted (S-294's law, and its
    cap)."""
    if not isinstance(reason, str) or not reason.strip():
        raise DependencyAlertError(
            REASON_REQUIRED,
            "A dependency-alert transition needs a "
            "stated reason: the actor's own words "
            "for why this alert moves. A transition "
            "without its reason is an unaccountable "
            "act, and this slice builds none.")
    cleaned = reason.strip()
    if len(cleaned) > MAX_REASON_CHARS:
        raise DependencyAlertError(
            REASON_TOO_LONG,
            f"A lifecycle reason is at most "
            f"{MAX_REASON_CHARS} characters; this "
            f"one runs {len(cleaned)}. Say the "
            f"reason plainly and briefly.")
    return cleaned


# ------------------------------------------------------------------
# The pure lifecycle judgement (S-294's shape)
# ------------------------------------------------------------------

@dataclass(frozen=True)
class LifecycleDecision:
    """The pure judgement: may this person move
    this alert, holding this role, in this way,
    for this stated reason? A refusal carries its
    named code and its sentence. Pure: writes
    nothing."""
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
    """Judge one lifecycle ask, in S-294's house
    order: the state the alert stands in first,
    then the person's rung, then -- on a resolve --
    the resolution kind, then the stated reason."""
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
                f"Dependency-alert {verb} in {full_name} "
                f"was refused: {who} {held}, and only "
                f"the permitted roles may move a "
                f"dependency alert ({_permitted_words()}). "
                f"Ask a repository maintainer to act, "
                f"or be granted a permitted role "
                f"first."),
            words=(
                f"{who} may not {verb} a dependency "
                f"alert in {full_name}: only "
                f"{_permitted_words()} may, and every "
                f"transition records its actor and "
                f"reason."))
    if action == "resolve":
        try:
            validate_resolution(resolution)
        except DependencyAlertError as exc:
            return LifecycleDecision(
                may_move=False, action=action, role=role,
                source=source, code=exc.reason,
                reason=str(exc),
                words=(
                    f"{who} may not resolve the alert "
                    f"in {full_name} under that kind: "
                    f"an alert resolves as fixed, a "
                    f"false positive, or risk accepted, "
                    f"and the kind is part of the "
                    f"record."))
    try:
        validate_reason(reason)
    except DependencyAlertError as exc:
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


# ------------------------------------------------------------------
# The records
# ------------------------------------------------------------------

@dataclass(frozen=True)
class DependencyAlert:
    """One dependency alert: one dependency in one
    manifest standing in one advisory's affected
    range, with its lifecycle standing. The fixed
    version is None where the snapshot knows none
    -- *fix unknown*, never invented."""
    id: int
    repo_id: int
    full_name: str
    dependency_id: int | None
    ecosystem: str
    package: str
    name_key: str
    manifest_path: str
    specifier: str
    basis: str
    pinned_version: str    # "" unless basis is pinned
    advisory_id: str
    severity: str
    affected: str
    fixed_version: str | None
    summary: str
    snapshot_date: str
    state: str
    created_at: int
    updated_at: int
    resolution: str        # "" unless resolved
    resolved_by_id: int | None
    resolved_by: str       # "" unless resolved by a person
    resolved_at: int | None
    resolution_reason: str  # "" unless resolved

    @property
    def is_resolved(self) -> bool:
        return self.state == "resolved"

    @property
    def fixed_words(self) -> str:
        if self.fixed_version is None:
            return "fix unknown"
        return "fixed in " + self.fixed_version

    def resolution_words(self) -> str:
        """The standing position in one sentence, in
        words -- never colour alone. An automatic
        resolution says it is automatic."""
        if self.state == "resolved":
            if self.resolved_by:
                return (
                    f"resolved as "
                    f"{resolution_word(self.resolution)} "
                    f"by {self.resolved_by}: "
                    f"{self.resolution_reason}")
            return (
                f"resolved as "
                f"{resolution_word(self.resolution)} "
                f"automatically by refresh: "
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
            "dependency_id": self.dependency_id,
            "ecosystem": self.ecosystem,
            "package": self.package,
            "name_key": self.name_key,
            "manifest": self.manifest_path,
            "specifier": self.specifier,
            "basis": self.basis,
            "pinned_version": self.pinned_version or None,
            "advisory_id": self.advisory_id,
            "severity": self.severity,
            "affected": self.affected,
            "fixed_version": self.fixed_version,
            "fixed_words": self.fixed_words,
            "summary": self.summary,
            "snapshot_date": self.snapshot_date,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "resolution": self.resolution or None,
            "resolved_by_id": self.resolved_by_id,
            "resolved_by": self.resolved_by or None,
            "resolved_at": self.resolved_at,
            "resolution_reason":
                self.resolution_reason or None,
        }


@dataclass(frozen=True)
class DependencyAlertEvent:
    """One standing transition on an alert's own
    lifecycle record: who moved it (a person, or
    the system actor on an auto-resolve), from
    what state to what state, under what kind (on
    a resolve), and why, in the stated words."""
    id: int
    alert_id: int
    repo_id: int
    action: str            # resolve | reopen | auto_resolve
    from_state: str
    to_state: str
    resolution: str        # "" on a reopen
    actor_id: int | None
    actor_username: str
    role: str
    role_source: str
    reason: str
    created_at: int

    def words(self) -> str:
        if self.action == "auto_resolve":
            return (
                f"Refresh resolved this alert "
                f"automatically as "
                f"{resolution_word(self.resolution)}: "
                f"{self.reason}")
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
            "role": self.role or None,
            "role_source": self.role_source,
            "reason": self.reason,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class RefreshReport:
    """One refresh of one repository, whole: the
    snapshot it judged against (date + age words),
    what it created, what it auto-resolved, what
    stands live now, and how much it could not
    judge -- said, never shrugged."""
    repo_id: int
    full_name: str
    snapshot_date: str
    age_words: str
    created: int
    updated: int
    auto_resolved: int
    standing_live: int
    matches: int
    unjudged: int

    def to_dict(self) -> dict:
        return {
            "repository": self.full_name,
            "snapshot_date": self.snapshot_date,
            "age_words": self.age_words,
            "created": self.created,
            "updated": self.updated,
            "auto_resolved": self.auto_resolved,
            "standing_live": self.standing_live,
            "matches": self.matches,
            "unjudged": self.unjudged,
        }


def _row_to_alert(row, full_name: str) -> DependencyAlert:
    return DependencyAlert(
        id=int(row["id"]), repo_id=int(row["repo_id"]),
        full_name=full_name,
        dependency_id=row["dependency_id"],
        ecosystem=row["ecosystem"], package=row["dependency_name"],
        name_key=row["name_key"],
        manifest_path=row["manifest_path"],
        specifier=row["specifier"], basis=row["basis"],
        pinned_version=row["pinned_version"] or "",
        advisory_id=row["advisory_id"],
        severity=row["severity"], affected=row["affected"],
        fixed_version=row["fixed_version"],
        summary=row["summary"],
        snapshot_date=row["snapshot_date"],
        state=row["state"],
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
        resolution=row["resolution"] or "",
        resolved_by_id=row["resolved_by_id"],
        resolved_by=row["resolved_by"] or "",
        resolved_at=row["resolved_at"],
        resolution_reason=row["resolution_reason"] or "")


def _row_to_event(row) -> DependencyAlertEvent:
    return DependencyAlertEvent(
        id=int(row["id"]), alert_id=int(row["alert_id"]),
        repo_id=int(row["repo_id"]), action=row["action"],
        from_state=row["from_state"],
        to_state=row["to_state"],
        resolution=row["resolution"] or "",
        actor_id=row["actor_id"],
        actor_username=row["actor_username"],
        role=row["role"] or "",
        role_source=row["role_source"] or "",
        reason=row["reason"],
        created_at=int(row["created_at"]))


# ------------------------------------------------------------------
# The store
# ------------------------------------------------------------------

class DependencyAlertStore:
    """The join of S-297's graph and S-298's
    advisory snapshot, and the life of the alerts
    it raises. It grants no permission of its own:
    reads and refresh resolve through the graph's
    law, lifecycle acts through S-190's engine,
    exactly as S-294's store stands."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 accounts: AccountStore,
                 advisories: AdvisoryStore,
                 *, time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._advisories = advisories
        self._now = time_fn
        self._graph = DependencyGraphStore(
            conn, repositories, accounts, time_fn=time_fn)
        self._engine = PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)

    # -- resolution ------------------------------------

    def _resolve_repo(self, viewer: User | None, owner, repo,
                      *, any_role: bool):
        """(repository, resolution) under S-294's
        read law: a missing repository answers
        `repo_not_found`; so does a repository the
        viewer holds no role in when a role is
        required, before any alert position is
        named."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise DependencyAlertError(
                "repo_not_found", "No such repository.")
        resolution = self._engine.resolve(viewer, current)
        if resolution.role is None \
                and current.visibility != "public":
            raise DependencyAlertError(
                "repo_not_found", "No such repository.")
        if any_role and resolution.role is None:
            raise DependencyAlertError(
                "repo_not_found", "No such repository.")
        return current, resolution

    def _alert_row(self, repo_id: int, alert_id: int):
        row = self._conn.execute(
            "SELECT * FROM dependency_alerts WHERE id = ?"
            " AND repo_id = ?", (alert_id, repo_id)).fetchone()
        if row is None:
            raise DependencyAlertError(
                ALERT_NOT_FOUND,
                f"No dependency alert {alert_id} stands "
                f"in this repository.")
        return row

    def snapshot_info(self, now: object = None) -> SnapshotInfo:
        """The advisory snapshot's date, age and
        freshness -- what every alert surface must
        stand beside the alerts (S-298's law)."""
        return self._advisories.snapshot_info(now)

    # -- the join ----------------------------------------

    def compute_matches(self, owner: object, repo: object,
                        viewer=None) -> tuple:
        """The standing join, computed and returned
        without writing anything: (matches,
        unjudged) where each match is (Dependency,
        Advisory, DependencyMatch) and *unjudged*
        counts dependency rows whose specifier no
        judgement could reach. Read under the
        graph's own law."""
        rows = self._graph.dependencies_for(
            owner, repo, viewer)
        matches: list = []
        unjudged = 0
        for row in rows:
            dep = row.dependency
            advisories: list = []
            seen: set = set()
            for candidate in (dep.name, dep.name_key):
                for adv in self._advisories.for_package(
                        dep.ecosystem, candidate):
                    if adv.id not in seen:
                        seen.add(adv.id)
                        advisories.append(adv)
            if not advisories:
                continue
            dep_unjudged = False
            for adv in advisories:
                verdict = judge_dependency(
                    dep.ecosystem, dep.specifier, adv.affected)
                if verdict.unjudged:
                    dep_unjudged = True
                elif verdict.matched:
                    matches.append((row, adv, verdict))
            if dep_unjudged:
                unjudged += 1
        return tuple(matches), unjudged

    def refresh_alerts(self, viewer: User | None, owner, repo
                       ) -> RefreshReport:
        """Recompute one repository's alerts from
        the standing graph and the standing
        snapshot, in one transaction: create what
        is newly matched, bring live alerts'
        standing facts current, auto-resolve live
        alerts whose match has vanished, and leave
        every resolved alert -- a person's answer --
        exactly as it stands. Derived data,
        rebuildable at any time; unwitnessed in the
        audit taxonomy, like the graph itself."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=False)
        matches, unjudged = self.compute_matches(
            owner, repo, viewer)
        info = self.snapshot_info()
        snapshot_date = (
            info.snapshot_date.isoformat()
            if info.snapshot_date else "")
        now = int(self._now())
        wanted: dict = {}
        for row, adv, verdict in matches:
            dep = row.dependency
            key = (dep.ecosystem, dep.name_key,
                   row.manifest_path, adv.id)
            wanted[key] = (row, adv, verdict)
        created = updated = auto_resolved = 0
        with self._conn:
            existing = {
                (r["ecosystem"], r["name_key"],
                 r["manifest_path"], r["advisory_id"]): r
                for r in self._conn.execute(
                    "SELECT * FROM dependency_alerts"
                    " WHERE repo_id = ?",
                    (current.id,)).fetchall()}
            for key, (row, adv, verdict) in wanted.items():
                dep = row.dependency
                standing = existing.get(key)
                if standing is None:
                    self._conn.execute(
                        "INSERT INTO dependency_alerts ("
                        " repo_id, dependency_id, ecosystem,"
                        " dependency_name, name_key, manifest_path,"
                        " specifier, basis, pinned_version,"
                        " advisory_id, severity, affected,"
                        " fixed_version, summary,"
                        " snapshot_date, state, created_at,"
                        " updated_at, resolution,"
                        " resolved_by_id, resolved_by,"
                        " resolved_at, resolution_reason)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,"
                        " ?, ?, ?, ?, ?, ?, 'open', ?, ?, '',"
                        " NULL, '', NULL, '')",
                        (current.id, row.id, dep.ecosystem,
                         dep.name, dep.name_key,
                         row.manifest_path, dep.specifier,
                         verdict.basis, verdict.pinned_version,
                         adv.id, adv.severity, adv.affected,
                         adv.fixed_version, adv.summary,
                         snapshot_date, now, now))
                    created += 1
                elif standing["state"] in LIVE_STATES:
                    self._conn.execute(
                        "UPDATE dependency_alerts SET"
                        " dependency_id = ?, dependency_name = ?,"
                        " specifier = ?, basis = ?,"
                        " pinned_version = ?, severity = ?,"
                        " affected = ?, fixed_version = ?,"
                        " summary = ?, snapshot_date = ?,"
                        " updated_at = ? WHERE id = ?",
                        (row.id, dep.name, dep.specifier,
                         verdict.basis, verdict.pinned_version,
                         adv.severity, adv.affected,
                         adv.fixed_version, adv.summary,
                         snapshot_date, now, standing["id"]))
                    updated += 1
            for key, standing in existing.items():
                if key in wanted \
                        or standing["state"] not in LIVE_STATES:
                    continue
                self._conn.execute(
                    "UPDATE dependency_alerts SET"
                    " state = 'resolved', resolution ="
                    " 'fixed', resolved_by_id = NULL,"
                    " resolved_by = '', resolved_at = ?,"
                    " resolution_reason = ?,"
                    " updated_at = ? WHERE id = ?",
                    (now, AUTO_RESOLVE_REASON, now,
                     standing["id"]))
                self._conn.execute(
                    "INSERT INTO dependency_alert_events ("
                    " alert_id, repo_id, action, from_state,"
                    " to_state, resolution, actor_id,"
                    " actor_username, role, role_source,"
                    " reason, created_at)"
                    " VALUES (?, ?, 'auto_resolve', ?,"
                    " 'resolved', 'fixed', NULL, ?, '',"
                    " ?, ?, ?)",
                    (standing["id"], current.id,
                     standing["state"], SYSTEM_ACTOR,
                     SYSTEM_SOURCE, AUTO_RESOLVE_REASON, now))
                auto_resolved += 1
        live = self._conn.execute(
            "SELECT COUNT(*) AS n FROM dependency_alerts"
            " WHERE repo_id = ? AND state IN"
            " ('open', 'reopened')",
            (current.id,)).fetchone()["n"]
        return RefreshReport(
            repo_id=current.id, full_name=current.full_name,
            snapshot_date=snapshot_date,
            age_words=info.age_words,
            created=created, updated=updated,
            auto_resolved=auto_resolved,
            standing_live=int(live), matches=len(wanted),
            unjudged=unjudged)

    # -- the pure check ------------------------------------

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

    # -- the acts -------------------------------------------

    def _transition(self, actor: User | None, owner, repo,
                    alert_id: int, *, action: str,
                    resolution: object = None,
                    reason: object = "") -> DependencyAlert:
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
            raise DependencyAlertError(
                judgement.code, judgement.reason)
        cleaned_reason = validate_reason(reason)
        created_at = int(self._now())
        from_state = row["state"]
        if action == "resolve":
            kind = validate_resolution(resolution)
            with self._conn:
                self._conn.execute(
                    "UPDATE dependency_alerts SET"
                    " state = 'resolved', resolution = ?,"
                    " resolved_by_id = ?, resolved_by = ?,"
                    " resolved_at = ?, resolution_reason = ?,"
                    " updated_at = ? WHERE id = ?",
                    (kind, actor.id, actor.username,
                     created_at, cleaned_reason, created_at,
                     alert_id))
                self._conn.execute(
                    "INSERT INTO dependency_alert_events ("
                    " alert_id, repo_id, action, from_state,"
                    " to_state, resolution, actor_id,"
                    " actor_username, role, role_source,"
                    " reason, created_at)"
                    " VALUES (?, ?, 'resolve', ?,"
                    " 'resolved', ?, ?, ?, ?, ?, ?, ?)",
                    (alert_id, current.id, from_state, kind,
                     actor.id, actor.username, resolved.role,
                     resolved.source, cleaned_reason,
                     created_at))
        else:
            with self._conn:
                self._conn.execute(
                    "UPDATE dependency_alerts SET"
                    " state = 'reopened', resolution = '',"
                    " resolved_by_id = NULL, resolved_by = '',"
                    " resolved_at = NULL,"
                    " resolution_reason = '',"
                    " updated_at = ? WHERE id = ?",
                    (created_at, alert_id))
                self._conn.execute(
                    "INSERT INTO dependency_alert_events ("
                    " alert_id, repo_id, action, from_state,"
                    " to_state, resolution, actor_id,"
                    " actor_username, role, role_source,"
                    " reason, created_at)"
                    " VALUES (?, ?, 'reopen', ?,"
                    " 'reopened', '', ?, ?, ?, ?, ?, ?)",
                    (alert_id, current.id, from_state,
                     actor.id, actor.username, resolved.role,
                     resolved.source, cleaned_reason,
                     created_at))
        return self._get_alert(current, alert_id)

    def resolve_alert(self, actor: User | None, owner, repo,
                      alert_id: int, *,
                      resolution: object = None,
                      reason: object = "") -> DependencyAlert:
        """Resolve one live alert under one of the
        three named kinds, with the resolver and
        the stated reason recorded, and the
        transition standing on the alert's lifecycle
        record -- all before this answers."""
        return self._transition(
            actor, owner, repo, alert_id, action="resolve",
            resolution=resolution, reason=reason)

    def reopen_alert(self, actor: User | None, owner, repo,
                     alert_id: int, *,
                     reason: object = "") -> DependencyAlert:
        """Reopen one resolved alert, with the actor
        and the stated reason recorded and the
        standing resolution cleared whole -- all
        before this answers."""
        return self._transition(
            actor, owner, repo, alert_id, action="reopen",
            reason=reason)

    # -- the reads -------------------------------------------

    def _get_alert(self, current: Repository,
                   alert_id: int) -> DependencyAlert:
        row = self._alert_row(current.id, alert_id)
        return _row_to_alert(row, current.full_name)

    def get_alert(self, viewer: User | None, owner, repo,
                  alert_id: int) -> DependencyAlert:
        """One alert with its standing lifecycle."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        return self._get_alert(current, alert_id)

    def list_alerts(self, viewer: User | None, owner, repo, *,
                    state: str | None = None,
                    severity: str | None = None,
                    limit: int = 100) -> tuple:
        """Most severe first, then newest;
        optionally one lifecycle state and/or one
        severity."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        if state is not None and state not in ALERT_STATES:
            raise DependencyAlertError(
                "state_invalid",
                f"Unknown alert state: {state!r}")
        if severity is not None \
                and severity not in SEVERITY_ORDER:
            raise DependencyAlertError(
                "severity_invalid",
                f"Unknown severity: {severity!r}")
        clamped = max(1, min(int(limit), 500))
        sql = ("SELECT * FROM dependency_alerts"
               " WHERE repo_id = ?")
        params: list = [current.id]
        if state is not None:
            sql += " AND state = ?"
            params.append(state)
        if severity is not None:
            sql += " AND severity = ?"
            params.append(severity)
        sql += (
            " ORDER BY CASE severity WHEN 'critical'"
            " THEN 0 WHEN 'high' THEN 1 WHEN 'moderate'"
            " THEN 2 ELSE 3 END, id DESC LIMIT ?")
        params.append(clamped)
        rows = self._conn.execute(sql, params).fetchall()
        return tuple(
            _row_to_alert(r, current.full_name) for r in rows)

    def count_alerts(self, viewer: User | None, owner, repo, *,
                     state: str | None = None,
                     severity: str | None = None) -> int:
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        if state is not None and state not in ALERT_STATES:
            raise DependencyAlertError(
                "state_invalid",
                f"Unknown alert state: {state!r}")
        if severity is not None \
                and severity not in SEVERITY_ORDER:
            raise DependencyAlertError(
                "severity_invalid",
                f"Unknown severity: {severity!r}")
        sql = ("SELECT COUNT(*) AS n FROM"
               " dependency_alerts WHERE repo_id = ?")
        params: list = [current.id]
        if state is not None:
            sql += " AND state = ?"
            params.append(state)
        if severity is not None:
            sql += " AND severity = ?"
            params.append(severity)
        row = self._conn.execute(sql, params).fetchone()
        return int(row["n"])

    def counts_by_severity(self, viewer: User | None,
                           owner, repo) -> dict:
        """Live (open + reopened) alerts counted by
        severity, every severity named even at
        zero -- the shape S-307's security tab and
        S-308's rollup will read."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        counts = {name: 0 for name in SEVERITY_ORDER}
        rows = self._conn.execute(
            "SELECT severity, COUNT(*) AS n FROM"
            " dependency_alerts WHERE repo_id = ?"
            " AND state IN ('open', 'reopened')"
            " GROUP BY severity", (current.id,)).fetchall()
        for row in rows:
            counts[row["severity"]] = int(row["n"])
        return counts

    def list_events(self, viewer: User | None, owner, repo,
                    alert_id: int) -> tuple:
        """The alert's lifecycle record, oldest
        first: every transition it has ever stood,
        unedited -- human and automatic alike."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        self._alert_row(current.id, alert_id)
        rows = self._conn.execute(
            "SELECT * FROM dependency_alert_events"
            " WHERE alert_id = ? AND repo_id = ?"
            " ORDER BY id", (alert_id, current.id)).fetchall()
        return tuple(_row_to_event(r) for r in rows)


# ------------------------------------------------------------------
# Rendering (S-010 escaped; S-298's banner on every surface)
# ------------------------------------------------------------------

def render_alert_page(alert: DependencyAlert, events=(),
                      info: SnapshotInfo | None = None,
                      title: str = "Dependency alert") -> str:
    """One alert's face: the advisory banner first
    (date + age words -- no alert surface without
    them), the package, its severity, affected
    range and fixed version in words, its standing
    lifecycle, and its recorded transitions."""
    rows = "".join(
        "<li>" + escape_html_text(e.words())
        + " (" + escape_html_text(e.role or "system")
        + ", " + escape_html_text(e.from_state) + " -> "
        + escape_html_text(e.to_state) + ")</li>"
        for e in events)
    if not rows:
        rows = "<li>No lifecycle transitions yet.</li>"
    banner = render_advisory_banner(info) if info else ""
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1>" + banner
        + "<p>Alert in "
        + escape_html_text(alert.full_name)
        + ": " + escape_html_text(alert.ecosystem)
        + " package " + escape_html_text(alert.package)
        + " " + escape_html_text(alert.specifier)
        + " (from " + escape_html_text(alert.manifest_path)
        + ") is affected by "
        + escape_html_text(alert.advisory_id)
        + " -- severity "
        + escape_html_text(alert.severity)
        + ", affected "
        + escape_html_text(alert.affected)
        + ", " + escape_html_text(alert.fixed_words)
        + ". " + escape_html_text(alert.summary)
        + " Judged on a "
        + escape_html_text(alert.basis)
        + " match against advisory snapshot dated "
        + escape_html_text(alert.snapshot_date)
        + ". State: " + escape_html_text(alert.state)
        + " -- " + escape_html_text(alert.resolution_words())
        + ".</p><ul>" + rows + "</ul></body></html>")


def render_alerts_page(alerts, full_name: str,
                       info: SnapshotInfo | None = None,
                       title: str = "Dependency alerts"
                       ) -> str:
    """The alerts face: the advisory banner first,
    then each alert with its severity, affected
    range, fixed version and standing lifecycle
    said in words -- never colour alone."""
    rows = "".join(
        "<li>" + escape_html_text(a.ecosystem)
        + ": " + escape_html_text(a.package)
        + " " + escape_html_text(a.specifier)
        + " -- " + escape_html_text(a.advisory_id)
        + " [" + escape_html_text(a.severity)
        + ", affected " + escape_html_text(a.affected)
        + ", " + escape_html_text(a.fixed_words)
        + "] (" + escape_html_text(a.state) + " -- "
        + escape_html_text(a.resolution_words())
        + ")</li>"
        for a in alerts)
    if not rows:
        rows = "<li>No dependency alerts.</li>"
    banner = render_advisory_banner(info) if info else ""
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title) + " -- "
        + escape_html_text(full_name)
        + "</h1>" + banner
        + "<ul>" + rows + "</ul></body></html>")
