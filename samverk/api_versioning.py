"""API versioning policy -- what may change in v1 (S-254).

API versioning policy -- what may change within
v1, how v2 would be introduced, deprecation notices
in headers. This slice is that policy, as a complete
slice: the policy is data, every kind of change is
classified before it is made, the road to a v2 is
stated step by step, and the deprecation headers are
specified exactly -- and the policy is recorded in
the REST contract itself (samverk/api_contract.py's
``versioned-base`` rule, docs/API_CONTRACT.md's
Versioning section), where a builder meets it.

- **v1 changes additively, or not at all.**
  ``CHANGES`` classifies fifteen kinds of change:
  seven are allowed inside v1 because a client
  written against the old contract keeps working
  unchanged (a new endpoint, a new response field,
  a new optional request field or header, a new
  refusal for a case that could not occur before,
  widened accepted input, a raised limit), and
  eight are breaking and therefore require a v2
  (removing or renaming anything, changing a
  field's type or meaning, requiring what was
  optional, changing an existing refusal, changing
  pagination or ordering, lowering a limit,
  changing who may see what). The pure
  ``decide_change`` judges a kind by its id; a
  shapeless or unknown kind is
  ``change_kind_invalid`` -- the policy invents no
  classification to answer with.
- **A v2 is introduced alongside, never in place.**
  ``V2_INTRODUCTION`` states the road: a v2 stands
  under its own base /api/v2 as a whole new
  contract, introduced only to carry breaking
  changes, while /api/v1 keeps serving every v1
  client unchanged -- never mutated, never
  redirected. Both versions run concurrently for
  at least MIN_V1_OVERLAP_DAYS (365) after v2
  lands, v2 ships with a migration guide mapping
  every v1 resource and field it changes, and v1
  is deprecated only once v2 stands -- by the
  header law below, never silently.
- **Deprecation is announced in headers, with
  time to act.** A deprecated surface answers
  every response with three headers, specified in
  ``HEADER_SPECS``: ``Deprecation`` (the HTTP-date
  deprecation began, RFC 9745), ``Sunset`` (the
  HTTP-date the surface stops answering, RFC
  8594) and ``Link`` carrying
  ``rel="deprecation"`` to the notice a person
  reads. The sunset stands at least
  MIN_DEPRECATION_NOTICE_DAYS (180) after the
  deprecation date -- ``validate_deprecation_notice``
  refuses a shorter runway in words -- and
  ``deprecation_headers`` builds the exact header
  set from a valid notice and refuses an invalid
  one (``deprecation_notice_invalid``). Deprecation
  changes no behaviour by itself: a deprecated
  endpoint keeps its shapes, permissions and
  refusals until its sunset.
- **A pure read, like S-202, S-237 and S-253.**
  This module holds no store, writes no row and
  audits nothing: a policy about change changes
  nothing by being read. No migration (schema
  stays 99), no taxonomy event (131 stand:
  33 auth / 85 repo / 13 admin). The full policy
  also lives in docs/API_VERSIONING.md, where a
  person who never opens this module can read it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from email.utils import format_datetime

from .api_contract import API_BASE, API_RESOURCES, audit_api_contract
from .escaping import escape_html_text

__all__ = [
    "ALLOWED_IN_V1", "BREAKING", "CHANGES",
    "CURRENT_VERSION", "DEPRECATION_LINK_REL",
    "HEADER_SPECS", "MIN_DEPRECATION_NOTICE_DAYS",
    "MIN_V1_OVERLAP_DAYS", "V2_BASE", "V2_INTRODUCTION",
    "ApiVersioningError", "ChangeKind",
    "DeprecationHeaderSpec", "DeprecationNotice",
    "VersioningAudit", "audit_api_versioning",
    "decide_change", "deprecation_headers",
    "get_change", "get_header_spec",
    "render_api_versioning_page",
    "validate_deprecation_notice",
]

CURRENT_VERSION = "v1"
V2_BASE = "/api/v2"

# The two floors of the policy, in days. A
# deprecated surface gives its callers at least
# half a year between the deprecation date and
# its sunset, and a v1 keeps serving for at least
# a full year after its v2 lands -- time for a
# village instance's scripts to be found, read
# and moved, stated now so no future deprecation
# negotiates them down in a hurry.
MIN_DEPRECATION_NOTICE_DAYS = 180
MIN_V1_OVERLAP_DAYS = 365

ALLOWED_IN_V1 = "allowed-in-v1"
BREAKING = "requires-v2"

DEPRECATION_LINK_REL = "deprecation"


class ApiVersioningError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ChangeKind:
    """One kind of API change, classified: a stable
    id, the plain title a reader sees, the verdict
    (ALLOWED_IN_V1 or BREAKING), and why that
    verdict holds."""
    id: str
    title: str
    verdict: str
    detail: str


CHANGES: tuple[ChangeKind, ...] = (
    ChangeKind(
        id="add-endpoint",
        title="Add an endpoint",
        verdict=ALLOWED_IN_V1,
        detail=(
            "A new resource, or a new method on an "
            "existing resource, at a path no v1 client "
            "was promised would stay empty. Existing "
            "paths, methods and shapes are untouched, "
            "so every client written against the old "
            "contract keeps working unchanged.")),
    ChangeKind(
        id="add-response-field",
        title="Add a field to a response",
        verdict=ALLOWED_IN_V1,
        detail=(
            "A representation gains a field it did not "
            "carry. The contract's shapes are plain "
            "JSON objects whose documented fields keep "
            "their names, types and meanings; a client "
            "reads the fields it knows and the new one "
            "is simply there when it wants it.")),
    ChangeKind(
        id="add-optional-request-field",
        title="Add an optional request field",
        verdict=ALLOWED_IN_V1,
        detail=(
            "A request gains an optional field whose "
            "absence means exactly what the old request "
            "meant -- the default preserves the old "
            "behaviour, never approximates it. A field "
            "whose absence changes the outcome is not "
            "optional in this sense and is judged as "
            "requiring it (see "
            "require-previously-optional).")),
    ChangeKind(
        id="add-optional-header",
        title="Add an optional header",
        verdict=ALLOWED_IN_V1,
        detail=(
            "A request or response gains a header no "
            "client is required to send or read -- the "
            "deprecation headers of this very policy "
            "arrive this way. A header a client must "
            "send to keep an old outcome is a tightening "
            "and is breaking, not an addition.")),
    ChangeKind(
        id="add-refusal-for-new-case",
        title="Add a refusal for a case that could not occur before",
        verdict=ALLOWED_IN_V1,
        detail=(
            "A new error reason, registered in S-240's "
            "registry with its own title and status, "
            "for a case the old contract could not "
            "reach -- a new resource's own refusals, or "
            "a state a new field makes possible. Every "
            "existing reason keeps its title, status "
            "and meaning; changing one of those is "
            "change-existing-refusal, and breaking.")),
    ChangeKind(
        id="widen-accepted-input",
        title="Widen what a request accepts",
        verdict=ALLOWED_IN_V1,
        detail=(
            "An endpoint accepts values it previously "
            "refused -- a new filter value, a new format "
            "variant -- while every previously accepted "
            "value keeps its old meaning and outcome. "
            "Accepting more cannot strand a client that "
            "only ever sent the old values.")),
    ChangeKind(
        id="raise-a-limit",
        title="Raise a limit",
        verdict=ALLOWED_IN_V1,
        detail=(
            "A cap goes up: a page-size bound, a payload "
            "bound, a rate bucket. A client written "
            "against the lower cap asks for no more "
            "than it ever did and is answered as "
            "before. Lowering a cap is the breaking "
            "mirror of this kind (lower-a-limit): a "
            "client may already rely on the room.")),
    ChangeKind(
        id="remove-endpoint",
        title="Remove an endpoint",
        verdict=BREAKING,
        detail=(
            "A resource or a method stops answering. "
            "Every script that calls it breaks at once, "
            "with no additive way to warn it inside the "
            "contract it speaks -- which is what the "
            "deprecation headers and a v2 exist for.")),
    ChangeKind(
        id="remove-or-rename-field",
        title="Remove or rename a field",
        verdict=BREAKING,
        detail=(
            "A documented field disappears from a "
            "representation, or the same fact moves to "
            "a new name. A rename is a removal plus an "
            "addition as far as every existing client "
            "is concerned: the name it reads is gone.")),
    ChangeKind(
        id="change-field-meaning-or-type",
        title="Change a field's type or meaning",
        verdict=BREAKING,
        detail=(
            "A field keeps its name but its type changes "
            "(a number becomes a string, a timestamp "
            "changes format) or the same value comes to "
            "mean a different fact. This is the quietest "
            "break of all -- the client's code runs and "
            "its answers are wrong -- so it is breaking "
            "however small the change looks.")),
    ChangeKind(
        id="require-previously-optional",
        title="Require what was optional",
        verdict=BREAKING,
        detail=(
            "A request field or header that was optional "
            "becomes required, or a default is withdrawn "
            "so an old request is refused or answered "
            "differently. Requests that were valid under "
            "v1 must stay valid under v1; that is the "
            "whole content of the version number.")),
    ChangeKind(
        id="change-existing-refusal",
        title="Change an existing refusal",
        verdict=BREAKING,
        detail=(
            "An existing error reason changes its "
            "status, its title's meaning, or the "
            "circumstances that raise it, or the one "
            "problem format (S-240) changes its fields. "
            "Clients branch on reasons and statuses; "
            "the refusal vocabulary is contract exactly "
            "as the success shapes are.")),
    ChangeKind(
        id="change-pagination-or-ordering",
        title="Change pagination or ordering semantics",
        verdict=BREAKING,
        detail=(
            "Cursor semantics (S-239), the stable "
            "ordering a cursor walks, or the list "
            "envelope's keys and honesty facts change "
            "their meaning. A client mid-walk under the "
            "old semantics is silently mis-paged under "
            "new ones; the envelope is contract.")),
    ChangeKind(
        id="lower-a-limit",
        title="Lower a limit",
        verdict=BREAKING,
        detail=(
            "A cap comes down: page size, payload size, "
            "a rate bucket, a retention window a client "
            "reads against. Requests the old contract "
            "accepted are refused or truncated, so the "
            "change is breaking even when the new cap "
            "still looks generous.")),
    ChangeKind(
        id="change-permission-semantics",
        title="Change who may see or do what",
        verdict=BREAKING,
        detail=(
            "The permission judgement behind a resource "
            "changes -- a rung moves on S-189's ladder, "
            "a private resource becomes visible to a "
            "wider audience, or a write is re-gated. "
            "Widening is breaking too: a client (or an "
            "instance's own audit expectations) built "
            "on the old boundary is silently wrong "
            "under the new one.")),
)


def get_change(change_id: object) -> ChangeKind:
    """One classified change kind by its id. An
    unknown id is refused change_unknown -- the
    policy does not invent a kind to answer with."""
    for change in CHANGES:
        if change.id == change_id:
            return change
    raise ApiVersioningError(
        "change_unknown", "No such change kind is "
        "classified.")


def decide_change(change_id: object) -> str:
    """Pure versioning judgement: the verdict for
    one kind of change. A classified kind answers
    its verdict (``allowed-in-v1`` or
    ``requires-v2``); a shapeless or unknown kind
    (not text, no text, or no such classification)
    is ``change_kind_invalid`` -- an unclassified
    change is never waved through as additive."""
    if not isinstance(change_id, str) or not change_id.strip():
        return "change_kind_invalid"
    for change in CHANGES:
        if change.id == change_id:
            return change.verdict
    return "change_kind_invalid"


V2_INTRODUCTION: tuple[str, ...] = (
    "A v2 is introduced only to carry breaking "
    "changes -- one or more changes this policy "
    "classifies requires-v2, named in the v2 "
    "contract with the v1 behaviour each replaces. "
    "Cosmetic or additive work never justifies a "
    "new version; it lands in v1.",
    "The v2 stands under its own base, /api/v2, as "
    "a whole new contract in the S-237 shape: its "
    "own resources, verbs, shapes and rules, "
    "ratified before its code, in its own contract "
    "document beside this one.",
    "Introducing v2 changes nothing under /api/v1: "
    "no v1 path is mutated to v2 behaviour, and no "
    "v1 request is redirected to v2. A client moves "
    "by changing the base it speaks to, in its own "
    "time, or it does not move.",
    "Both versions are served concurrently. v1 "
    "keeps every v1 promise -- shapes, refusals, "
    "permissions, limits no lower -- for at least "
    "365 days (MIN_V1_OVERLAP_DAYS) after the v2 "
    "lands, however little traffic it still "
    "carries.",
    "The v2 ships with a migration guide that maps "
    "every v1 resource, field and refusal the v2 "
    "changes: the v1 shape, the v2 shape, and the "
    "mechanical move between them, so a client "
    "migrates by reading, not by reverse-engineering.",
    "Only once the v2 stands may v1 be deprecated, "
    "and then only by this policy's header law: "
    "Deprecation, Sunset and the deprecation Link "
    "on every v1 response, the sunset at least 180 "
    "days out, and the contract documents updated "
    "in the same slice that starts the clock. v1 "
    "stops answering only after its sunset date "
    "has passed.",
)


@dataclass(frozen=True)
class DeprecationHeaderSpec:
    """One deprecation header, specified: its exact
    name, the shape its value takes, and when it is
    carried."""
    id: str
    name: str
    shape: str
    carried_when: str


HEADER_SPECS: tuple[DeprecationHeaderSpec, ...] = (
    DeprecationHeaderSpec(
        id="deprecation-date",
        name="Deprecation",
        shape=(
            "An HTTP-date (RFC 9745): the date the "
            "surface was deprecated, in GMT, as in "
            "Tue, 10 Nov 2026 00:00:00 GMT."),
        carried_when=(
            "On every response from a deprecated "
            "surface, from the deprecation date until "
            "the surface stops answering.")),
    DeprecationHeaderSpec(
        id="sunset-date",
        name="Sunset",
        shape=(
            "An HTTP-date (RFC 8594): the date the "
            "surface stops answering, in GMT. It "
            "stands at least 180 days "
            "(MIN_DEPRECATION_NOTICE_DAYS) after the "
            "Deprecation date."),
        carried_when=(
            "On every response from a deprecated "
            "surface, alongside Deprecation, whenever "
            "a removal date has been set -- and a "
            "deprecation under this policy always "
            "sets one.")),
    DeprecationHeaderSpec(
        id="deprecation-link",
        name="Link",
        shape=(
            "One link-value naming the deprecation "
            "notice a person reads, in the form "
            "<URL>; rel=\"deprecation\" (RFC 9745). "
            "The URL is the notice for this surface "
            "(its replacement and its migration road), "
            "never a generic homepage."),
        carried_when=(
            "On every response from a deprecated "
            "surface, alongside Deprecation and "
            "Sunset.")),
)


def get_header_spec(spec_id: object) -> DeprecationHeaderSpec:
    """One deprecation header spec by its id. An
    unknown id is refused header_spec_unknown."""
    for spec in HEADER_SPECS:
        if spec.id == spec_id:
            return spec
    raise ApiVersioningError(
        "header_spec_unknown", "No such deprecation "
        "header is specified.")


@dataclass(frozen=True)
class DeprecationNotice:
    """One surface's deprecation, as data: what is
    deprecated (a resource id, a field path, or a
    whole version's base), the day deprecation
    begins, the sunset day it stops answering, and
    the URL of the notice a person reads."""
    surface: str
    deprecated_on: date
    sunset_on: date
    notice_url: str


def validate_deprecation_notice(
        notice: object) -> tuple[str, ...]:
    """Judge one deprecation notice against the
    policy: the problems found, as stable words,
    empty when the notice is lawful. A notice must
    name its surface and its notice URL, its
    sunset must follow its deprecation date, and
    the runway between them must be at least
    MIN_DEPRECATION_NOTICE_DAYS -- a shorter notice
    is refused in words here, never discovered by
    the surface's callers at the sunset."""
    if not isinstance(notice, DeprecationNotice):
        return ("notice_invalid",)
    problems: list[str] = []
    if not isinstance(notice.surface, str) \
            or not notice.surface.strip():
        problems.append("surface_missing")
    if not isinstance(notice.notice_url, str) \
            or not notice.notice_url.strip():
        problems.append("notice_url_missing")
    if not isinstance(notice.deprecated_on, date) \
            or not isinstance(notice.sunset_on, date):
        problems.append("dates_invalid")
        return tuple(problems)
    if notice.sunset_on <= notice.deprecated_on:
        problems.append("sunset_not_after_deprecation")
    elif (notice.sunset_on - notice.deprecated_on).days \
            < MIN_DEPRECATION_NOTICE_DAYS:
        problems.append("notice_period_too_short")
    return tuple(problems)


def _http_date(day: date) -> str:
    return format_datetime(
        datetime.combine(day, time.min, tzinfo=timezone.utc),
        usegmt=True)


def deprecation_headers(notice: DeprecationNotice) -> dict[str, str]:
    """The exact headers a deprecated surface
    answers with, built from its notice: the three
    HEADER_SPECS, in spec order. An unlawful notice
    is refused ``deprecation_notice_invalid`` --
    headers announcing an unlawful sunset are
    never emitted."""
    problems = validate_deprecation_notice(notice)
    if problems:
        raise ApiVersioningError(
            "deprecation_notice_invalid",
            "That deprecation notice breaks the "
            "policy: " + ", ".join(problems) + ".")
    return {
        "Deprecation": _http_date(notice.deprecated_on),
        "Sunset": _http_date(notice.sunset_on),
        "Link": (
            f"<{notice.notice_url}>; "
            f'rel="{DEPRECATION_LINK_REL}"'),
    }


@dataclass(frozen=True)
class VersioningAudit:
    """The policy checked against the live
    contract: the REST contract's own ratification,
    the version actually served, every resource
    claiming a future version's base, and whether
    every classified change hangs from the standing
    versioned-base rule. The policy holds only when
    the REST audit ratifies, the served base is the
    current version, no resource claims v2 early,
    and the rule check holds."""
    current_version: str
    served_base: str
    rest_ratified: bool
    rule_ok: bool
    rest_resources_checked: int
    future_version_resources: tuple[str, ...]

    @property
    def policy_holds(self) -> bool:
        return (self.rest_ratified
                and self.rule_ok
                and self.served_base == API_BASE
                and self.current_version == CURRENT_VERSION
                and not self.future_version_resources)


def audit_api_versioning() -> VersioningAudit:
    """Check the policy against the live contract:
    the REST contract audit must still ratify, the
    served base must be the current version's, no
    ratified resource may claim a future version's
    base (a v2 arriving unnamed, ahead of its own
    contract, would be the introduction law broken
    by a back door), and the versioned-base rule
    the policy hangs from must stand in the
    contract. Pure read."""
    rest = audit_api_contract()
    from .api_contract import CONTRACT_RULES
    rule_ok = any(
        rule.id == "versioned-base" for rule in CONTRACT_RULES)
    claimed = tuple(
        r.id for r in API_RESOURCES
        if not (r.path == API_BASE
                or r.path.startswith(API_BASE + "/")))
    return VersioningAudit(
        current_version=CURRENT_VERSION,
        served_base=API_BASE,
        rest_ratified=rest.ratified,
        rule_ok=rule_ok,
        rest_resources_checked=rest.resources_checked,
        future_version_resources=claimed)


def render_api_versioning_page(
        audit: VersioningAudit | None = None) -> str:
    """The policy, rendered: the current version
    said plainly, every classified change with its
    verdict, the road to a v2 step by step, the
    deprecation headers specified exactly, and the
    checked proof when an audit rides along --
    every value escaped through S-010, the verdict
    said in words, never colour-only."""
    parts = [
        "<h1>API versioning policy (S-254)</h1>",
        "<p>Current version: <strong>v1</strong>, "
        "served under /api/v1. Inside v1, changes "
        "are additive only: what a v1 client was "
        "promised keeps its name, type, meaning, "
        "permission and refusal. A breaking change "
        "is never landed in v1 -- it waits for a "
        "v2, introduced by the road below. This page "
        "is the policy in full, and the same words "
        "live in docs/API_VERSIONING.md.</p>",
        "<h2>What may change inside v1 -- and what "
        "may not</h2>",
        "<ul>",
    ]
    for change in CHANGES:
        parts.append(
            f"<li><strong>{escape_html_text(change.title)}"
            f"</strong> ({escape_html_text(change.verdict)}): "
            f"{escape_html_text(change.detail)}</li>")
    parts.append("</ul>")
    parts.append("<h2>How a v2 would be introduced</h2>")
    parts.append("<ul>")
    for step in V2_INTRODUCTION:
        parts.append(f"<li>{escape_html_text(step)}</li>")
    parts.append("</ul>")
    parts.append("<h2>Deprecation notices, in headers</h2>")
    parts.append("<ul>")
    for spec in HEADER_SPECS:
        parts.append(
            f"<li><strong>{escape_html_text(spec.name)}"
            f"</strong>: {escape_html_text(spec.shape)} "
            f"{escape_html_text(spec.carried_when)}</li>")
    parts.append("</ul>")
    parts.append(
        f"<p>A deprecation gives at least "
        f"{MIN_DEPRECATION_NOTICE_DAYS} days between "
        f"its Deprecation date and its Sunset date, "
        f"and v1 is served for at least "
        f"{MIN_V1_OVERLAP_DAYS} days after a v2 "
        f"lands. Deprecation changes no behaviour by "
        f"itself: a deprecated endpoint keeps its "
        f"shapes, permissions and refusals until its "
        f"sunset.</p>")
    if audit is not None:
        if audit.policy_holds:
            parts.append(
                "<p>Checked, not just claimed: the "
                "REST contract was compared with the "
                f"live code over "
                f"{audit.rest_resources_checked} "
                "resources and still ratifies; the "
                "served base is /api/v1, the current "
                "version, and no resource claims a "
                "future version's base -- no v2 has "
                "arrived ahead of its own contract.</p>")
        else:
            found = ", ".join(
                audit.future_version_resources
                + (("REST contract no longer ratifies",)
                   if not audit.rest_ratified else ())
                + (("the versioned-base rule is missing",)
                   if not audit.rule_ok else ())
                + ((f"served base is {audit.served_base}",)
                   if audit.served_base != API_BASE else ()))
            parts.append(
                "<p>Checked, and not clean: the "
                "policy no longer holds as stated -- "
                f"{escape_html_text(found)} -- and "
                "that is a defect against S-254, to "
                "be fixed where it lies.</p>")
    parts.append(
        "<p>The policy is also recorded in the REST "
        "contract itself (samverk/api_contract.py, "
        "rule versioned-base; docs/API_CONTRACT.md), "
        "so a future builder meets it in the "
        "contract it governs, not only here.</p>")
    return "\n".join(parts)
