"""GraphQL verdict -- deferred, with reasons (S-253).

Research file 24's study concludes: build, defer, or
refuse, with reasons; if deferred, the REST contract
records what a future GraphQL layer must not break.
This slice is that conclusion, as a complete slice:
the verdict is data, the reasons are stated, the
three concrete clients research 24 names are judged
one by one, and the invariants a future layer must
not break are recorded here AND in the REST contract
itself (samverk/api_contract.py's ``graphql-deferred``
rule, docs/API_CONTRACT.md's GraphQL section).

- **The verdict is DEFER.** Not build: no client
  Samverk serves today needs GraphQL -- the landed
  REST families (S-242 repositories, S-243 issues and
  pulls, S-244 users/orgs/teams, S-245 search,
  S-246 statuses and checks) cover the issue board,
  the PR review page and organization administration
  in bounded calls, and nothing has measured an
  overfetch pain for GraphQL to cure. Not refuse:
  the PR review page is a genuinely graph-shaped
  read, a second independent consumer could change
  the balance, and S-403's successor seed already
  names this verdict as one to revisit. Defer is
  research 24's own recommended road when only one
  in-house consumer would use GraphQL and REST
  already meets measured needs -- both halves of
  that condition hold here, and ``REOPEN_CONDITIONS``
  states what would have to change.
- **Deferral is not an endpoint.** There is no
  GraphQL route, no schema, no resolver and no
  table: a request to execute GraphQL today is
  refused ``graphql_deferred`` by the pure
  ``decide_graphql_request`` (a shapeless request
  is ``graphql_action_invalid``), exactly as
  S-202's hole refuses every billing act. The
  audit below proves the absence against the live
  instance -- no contract resource, no schema name
  carries GraphQL -- and the battery plants a
  GraphQL-shaped table to prove the audit would
  catch one arriving by a back door.
- **What a future layer must not break is the
  REST contract itself.** ``MUST_NOT_BREAK`` states
  eight invariants, each tied to a standing
  CONTRACT_RULES id: permission parity judged per
  object AND per field through S-190, private
  indistinguishable from missing even by node id,
  REST v1 shapes and stable ids as the source of
  truth (GraphQL additive only, never a rename),
  list honesty carried by S-239 cursor connections,
  errors in S-240's one problem format, S-241's
  buckets plus the cost governance in
  ``GOVERNANCE_CAPS``, mutations through the same
  stores witnessed by the same verbs (idempotent,
  never partially writing), and a schema designed
  from the resources -- never the tables exposed
  one-to-one.
- **A pure read, like S-202 and S-237.** This
  module holds no store, writes no row and audits
  nothing: a verdict about an API that does not
  exist changes nothing by being read. No
  migration (schema stays 99), no taxonomy event
  (131 stand: 33 auth / 85 repo / 13 admin). The
  full reasoning also lives in
  docs/GRAPHQL_VERDICT.md, where a person who
  never opens this module can read it.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import taxonomy
from .api_contract import API_RESOURCES, CONTRACT_RULES, audit_api_contract
from .escaping import escape_html_text

__all__ = [
    "CLIENTS", "GOVERNANCE_CAPS", "MUST_NOT_BREAK",
    "REASONS", "REOPEN_CONDITIONS", "VERDICT",
    "ClientAssessment", "GovernanceCap",
    "GraphQLVerdictAudit", "GraphQLVerdictError",
    "VerdictInvariant", "VerdictReason",
    "audit_graphql_verdict", "decide_graphql_request",
    "get_client", "get_invariant", "get_reason",
    "render_graphql_verdict_page",
]

VERDICT = "deferred"

# The cost governance a future GraphQL layer must
# enforce from its first day (research 24: cap
# nesting depth, overall query cost, response
# bytes and execution time, and govern aliases and
# recursive fragments). Stated now, while deferring
# is cheap, so a future builder inherits the caps
# as contract, not as afterthought.
MAX_QUERY_DEPTH = 8
MAX_QUERY_COST = 1000
MAX_RESPONSE_BYTES = 1_000_000
MAX_EXECUTION_SECONDS = 10
MAX_ALIASES = 30


class GraphQLVerdictError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class VerdictReason:
    """One reason the verdict is defer: a stable
    id, the plain title a reader sees, and the
    reasoning in full."""
    id: str
    title: str
    detail: str


REASONS: tuple[VerdictReason, ...] = (
    VerdictReason(
        id="rest-meets-measured-needs",
        title="REST already meets the measured needs",
        detail=(
            "Every face a GraphQL layer would serve "
            "already stands in REST: repositories, "
            "issues and pulls with reviews and merge, "
            "users, organizations and teams, search "
            "and checks (S-242..S-246), each in the "
            "list envelope with cursor pagination "
            "(S-239). No client has measured an "
            "overfetch or call-count pain for GraphQL "
            "to cure; research 24 asks for that "
            "benchmark before adoption, and there is "
            "nothing yet to benchmark against except "
            "a need nobody has shown.")),
    VerdictReason(
        id="one-in-house-consumer",
        title="Only one in-house consumer would use it",
        detail=(
            "The only consumer a GraphQL endpoint "
            "would have today is Samverk's own web "
            "UI, which already speaks to the same "
            "stores the REST faces delegate to. "
            "Research 24's stated rule is to prefer "
            "an intentional deferral in exactly this "
            "case; a second, independent consumer is "
            "one of the reopen conditions below.")),
    VerdictReason(
        id="a-second-permanent-surface",
        title="A schema is a second permanent API surface",
        detail=(
            "A GraphQL schema, its field-level "
            "authorization and its query-cost "
            "governance are a long-lived maintenance "
            "commitment: every future resource would "
            "have to be designed, permissioned and "
            "tested twice, once per surface, while "
            "Part XII's own remaining law (S-254 "
            "versioning, S-255 abuse defences) has "
            "not yet landed even for the first "
            "surface. Deferring costs a documented "
            "verdict; adopting early costs that "
            "commitment forever.")),
    VerdictReason(
        id="a-new-abuse-class",
        title="Graph traversal is a new abuse class",
        detail=(
            "Nested graph traversal can generate "
            "multiplicative queries; recursive "
            "fragments and alias bombing complicate "
            "rate limits and abuse detection; a node "
            "lookup by id is a new road at private "
            "objects. None of that governance exists "
            "yet -- S-255's abuse defences are still "
            "contracted for REST alone -- and "
            "shipping the surface before its "
            "governance would invert Samverk's "
            "security-first founding order.")),
    VerdictReason(
        id="village-scale-simplicity",
        title="Village scale rewards the simpler contract",
        detail=(
            "Samverk is a sovereign forge for "
            "instances its people run themselves, "
            "stdlib-first, with dependencies admitted "
            "one at a time for a written reason. A "
            "GraphQL runtime and its tooling would "
            "need that admission against a benefit "
            "no measured need currently states. The "
            "REST contract is the one contract a "
            "village instance must keep honest; this "
            "verdict keeps it the only one, for now.")),
)


@dataclass(frozen=True)
class ClientAssessment:
    """Research 24's three concrete clients, judged
    one by one: what the client needs, what REST
    gives it today, what GraphQL would add, and the
    judgement for that client."""
    id: str
    title: str
    need: str
    rest_today: str
    graphql_gain: str
    judgement: str


CLIENTS: tuple[ClientAssessment, ...] = (
    ClientAssessment(
        id="issue-board",
        title="The issue board",
        need=(
            "Lists of issues with labels, assignees, "
            "milestone and state, filtered and paged."),
        rest_today=(
            "S-243's issues family in the list "
            "envelope, paged by S-239 cursors, with "
            "the filtered total and complete flag "
            "stated on every answer."),
        graphql_gain=(
            "Marginal: a board could trim a few "
            "fields per row, at the price of a second "
            "query language for the commonest list "
            "in the product."),
        judgement="rest-suffices"),
    ClientAssessment(
        id="pr-review-page",
        title="The PR review page",
        need=(
            "One pull request with its conversation, "
            "reviews, checks and merge state -- the "
            "deepest relationship read Samverk has."),
        rest_today=(
            "S-243's pull, reviews and merge "
            "resources plus S-246's checks, in a "
            "small bounded set of calls, each judged "
            "by the same stores the web page uses."),
        graphql_gain=(
            "Real but unmeasured: one graph query "
            "could replace that bounded set. This is "
            "the strongest future case, and the "
            "first client a reopened verdict must "
            "benchmark (research 24's acceptance)."),
        judgement="rest-suffices-today"),
    ClientAssessment(
        id="organization-administration",
        title="Organization administration",
        need=(
            "Members, teams, team repository "
            "permissions and the default permission, "
            "automatable end to end."),
        rest_today=(
            "S-244's family does exactly this, "
            "through S-186/S-187/S-189's own stores, "
            "and its acceptance is that end-to-end "
            "automation."),
        graphql_gain=(
            "Negligible: administration is writes "
            "and small reads, where GraphQL's "
            "relationship-read strength does not "
            "apply and its mutation idempotency "
            "burden would be new."),
        judgement="rest-suffices"),
)


@dataclass(frozen=True)
class VerdictInvariant:
    """One thing a future GraphQL layer must not
    break: a stable id, the standing REST contract
    rule it hangs from, and the invariant stated."""
    id: str
    contract_rule: str
    title: str
    statement: str


MUST_NOT_BREAK: tuple[VerdictInvariant, ...] = (
    VerdictInvariant(
        id="permission-parity-per-field",
        contract_rule="permission-parity",
        title="Permission parity, per object and per field",
        statement=(
            "Every object and every field resolves "
            "through S-190's permission engine "
            "exactly as the REST face and the web "
            "surface behind it are judged. A field "
            "the caller may not read is absent, never "
            "present-but-redacted, and no resolver "
            "may widen what its REST twin would show.")),
    VerdictInvariant(
        id="private-is-missing-by-node-id",
        contract_rule="uniform-not-found",
        title="Private is indistinguishable from missing, by node id too",
        statement=(
            "A node lookup naming a private or "
            "unreadable object answers exactly as a "
            "lookup naming nothing: the uniform "
            "not-found. Global ids are opaque "
            "encodings of the REST resources' stable "
            "ids and grant no information by existing.")),
    VerdictInvariant(
        id="rest-shapes-are-the-source-of-truth",
        contract_rule="versioned-base",
        title="REST v1 shapes and stable ids are the source of truth",
        statement=(
            "A GraphQL layer is additive only: it "
            "maps from the REST contract's resources, "
            "fields and stable ids and never renames, "
            "removes or re-meanings a REST shape, "
            "inside v1 or by forcing a v2. If the "
            "two surfaces ever disagree, the REST "
            "contract governs until it is amended.")),
    VerdictInvariant(
        id="connections-keep-list-honesty",
        contract_rule="cursor-pagination",
        title="Connections keep the list envelope's honesty",
        statement=(
            "GraphQL connections are S-239's keyset "
            "cursors over the permission-filtered "
            "list, and carry the list envelope's "
            "honesty with them: the filtered total "
            "before the cap and a complete flag that "
            "says when an answer is cut. Totals are "
            "never summed across permission "
            "boundaries, and filtering runs before "
            "paging on every request.")),
    VerdictInvariant(
        id="errors-stay-typed-and-shared",
        contract_rule="error-shape",
        title="Errors stay in the one problem format's vocabulary",
        statement=(
            "A GraphQL error carries the refusing "
            "store's own reason from S-240's registry "
            "-- the same type, title and status the "
            "REST face answers for the same refusal "
            "-- so a client learns one refusal "
            "vocabulary, not two. No resolver invents "
            "an unregistered reason.")),
    VerdictInvariant(
        id="cost-governance-from-day-one",
        contract_rule="rate-limits",
        title="S-241's buckets and the query-cost caps both apply",
        statement=(
            "Every GraphQL call is judged by S-241's "
            "per-token buckets AND by query-cost "
            "governance: maximum depth, maximum "
            "cost, maximum response bytes, maximum "
            "execution time and a maximum alias "
            "count, at the values GOVERNANCE_CAPS "
            "states, with introspection available "
            "to authenticated callers only. An "
            "over-budget query is refused whole, "
            "never answered in part.")),
    VerdictInvariant(
        id="mutations-share-stores-and-witness",
        contract_rule="no-back-doors",
        title="Mutations share the stores, the witness and the law",
        statement=(
            "A GraphQL mutation performs its act "
            "through the very store the web and REST "
            "use, is witnessed by the same audit verb "
            "carrying the same detail, and is refused "
            "wherever they are refused. Mutations "
            "are idempotent by client-supplied key, "
            "and a batched mutation never writes in "
            "part: it lands whole or refuses whole.")),
    VerdictInvariant(
        id="schema-from-resources-not-tables",
        contract_rule="no-back-doors",
        title="The schema is designed from resources, never tables",
        statement=(
            "The public schema is designed from the "
            "REST contract's resources and the "
            "product's own concepts. Database tables "
            "and columns are never exposed "
            "one-to-one: storage stays free to change "
            "under both surfaces, and no field exists "
            "merely because a column does.")),
)


@dataclass(frozen=True)
class GovernanceCap:
    """One stated cap of GOVERNANCE_CAPS: what is
    capped, at what value, and why."""
    id: str
    title: str
    value: int
    unit: str


GOVERNANCE_CAPS: tuple[GovernanceCap, ...] = (
    GovernanceCap(
        id="max-depth", title="Maximum query depth",
        value=MAX_QUERY_DEPTH, unit="levels"),
    GovernanceCap(
        id="max-cost", title="Maximum query cost",
        value=MAX_QUERY_COST, unit="cost points"),
    GovernanceCap(
        id="max-response-bytes",
        title="Maximum response size",
        value=MAX_RESPONSE_BYTES, unit="bytes"),
    GovernanceCap(
        id="max-execution-seconds",
        title="Maximum execution time",
        value=MAX_EXECUTION_SECONDS, unit="seconds"),
    GovernanceCap(
        id="max-aliases", title="Maximum aliases per query",
        value=MAX_ALIASES, unit="aliases"),
)

REOPEN_CONDITIONS: tuple[str, ...] = (
    "A second, independent consumer (beyond "
    "Samverk's own web UI) needs relationship reads "
    "that REST serves poorly, and says so with its "
    "own workload.",
    "A benchmark in research 24's acceptance shape "
    "-- representative queries against equivalent "
    "REST calls, recording latency, query count and "
    "developer effort -- shows the PR review page "
    "(the strongest case) materially worse over "
    "REST.",
    "The governance a GraphQL layer needs already "
    "exists: S-255's abuse defences have landed for "
    "REST and extend to query cost, so the new "
    "surface is not shipped ahead of its defences.",
    "The successor roadmap revisits the verdict: "
    "S-403 already names the GraphQL verdict among "
    "the deferred items its seed reconsiders, and "
    "a reopened verdict is decided there, on the "
    "evidence above, not by drift.",
)


def get_reason(reason_id: object) -> VerdictReason:
    """One deferral reason by its id. An unknown
    id is refused reason_unknown -- the verdict
    does not invent a reason to answer with."""
    for reason in REASONS:
        if reason.id == reason_id:
            return reason
    raise GraphQLVerdictError(
        "reason_unknown", "No such verdict reason "
        "is stated.")


def get_client(client_id: object) -> ClientAssessment:
    """One assessed client by its id. An unknown
    id is refused client_unknown."""
    for client in CLIENTS:
        if client.id == client_id:
            return client
    raise GraphQLVerdictError(
        "client_unknown", "No such client was "
        "assessed.")


def get_invariant(invariant_id: object) -> VerdictInvariant:
    """One must-not-break invariant by its id. An
    unknown id is refused invariant_unknown."""
    for invariant in MUST_NOT_BREAK:
        if invariant.id == invariant_id:
            return invariant
    raise GraphQLVerdictError(
        "invariant_unknown", "No such invariant "
        "is recorded.")


def decide_graphql_request(action: object) -> str:
    """Pure GraphQL judgement: the refusal reason
    for any request to execute GraphQL today. A
    worded request is refused ``graphql_deferred``
    -- the layer is deferred, not built, whatever
    the operation -- and a shapeless action (not
    text, or no text) is
    ``graphql_action_invalid``."""
    if not isinstance(action, str) or not action.strip():
        return "graphql_action_invalid"
    return "graphql_deferred"


@dataclass(frozen=True)
class GraphQLVerdictAudit:
    """The deferral checked against one live
    instance: the REST contract's own ratification,
    how much schema was inspected, and every
    GraphQL-shaped name found in it. The deferral
    is clean only when the REST audit ratifies, no
    contract resource claims GraphQL, and every
    offender list is empty."""
    verdict: str
    rest_ratified: bool
    invariant_rules_ok: bool
    rest_resources_checked: int
    graphql_contract_resources: tuple[str, ...]
    tables_scanned: int
    columns_scanned: int
    events_scanned: int
    offending_tables: tuple[str, ...]
    offending_columns: tuple[str, ...]
    offending_events: tuple[str, ...]

    @property
    def deferred_cleanly(self) -> bool:
        return (self.verdict == "deferred"
                and self.rest_ratified
                and self.invariant_rules_ok
                and not self.graphql_contract_resources
                and not self.offending_tables
                and not self.offending_columns
                and not self.offending_events)


def audit_graphql_verdict(
        conn: sqlite3.Connection) -> GraphQLVerdictAudit:
    """Check the deferral against the live
    instance: the REST contract audit must still
    ratify, no ratified resource may claim GraphQL
    in its id or path, and no table, column or
    audit event may carry the word -- a GraphQL
    layer arriving unnamed would be the deferral
    broken by a back door. Pure read."""
    rest = audit_api_contract()
    rule_ids = {rule.id for rule in CONTRACT_RULES}
    invariant_rules_ok = all(
        invariant.contract_rule in rule_ids
        for invariant in MUST_NOT_BREAK)
    claimed = tuple(
        r.id for r in API_RESOURCES
        if "graphql" in r.id.lower()
        or "graphql" in r.path.lower())
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    offending_tables: list[str] = []
    offending_columns: list[str] = []
    columns_scanned = 0
    for table in tables:
        if "graphql" in table.lower():
            offending_tables.append(table)
        safe = table.replace('"', '""')
        for row in conn.execute(
                f'PRAGMA table_info("{safe}")').fetchall():
            columns_scanned += 1
            if "graphql" in str(row[1]).lower():
                offending_columns.append(f"{table}.{row[1]}")
    events = sorted(taxonomy.AUDIT_EVENTS)
    offending_events = [
        e for e in events if "graphql" in e.lower()]
    return GraphQLVerdictAudit(
        verdict=VERDICT,
        rest_ratified=rest.ratified,
        invariant_rules_ok=invariant_rules_ok,
        rest_resources_checked=rest.resources_checked,
        graphql_contract_resources=claimed,
        tables_scanned=len(tables),
        columns_scanned=columns_scanned,
        events_scanned=len(events),
        offending_tables=tuple(offending_tables),
        offending_columns=tuple(offending_columns),
        offending_events=tuple(offending_events))


def attempt_graphql_action(action: object) -> None:
    """Refuse a request to execute GraphQL, always:
    the layer is deferred. Raises
    ``GraphQLVerdictError`` carrying the pure
    decision's reason; writes nothing and audits
    nothing (there is no GraphQL event to write)."""
    reason = decide_graphql_request(action)
    if reason == "graphql_action_invalid":
        raise GraphQLVerdictError(
            reason, "That GraphQL request is not valid.")
    raise GraphQLVerdictError(
        reason,
        "Samverk has no GraphQL layer: S-253 deferred "
        "it, with reasons, and the REST contract in "
        "docs/API_CONTRACT.md records what a future "
        "layer must not break. The REST API under "
        "/api/v1 is the programmatic surface.")


def render_graphql_verdict_page(
        audit: GraphQLVerdictAudit | None = None) -> str:
    """The verdict, rendered: deferred said plainly,
    the reasons, the three clients judged one by
    one, the must-not-break invariants with the
    contract rule each hangs from, the governance
    caps, the reopen conditions, and the checked
    proof when an audit rides along -- every value
    escaped through S-010, the state said in words,
    never colour-only."""
    parts = [
        "<h1>GraphQL -- deferred (S-253)</h1>",
        "<p>Verdict: <strong>deferred</strong>. "
        "Samverk does not build a GraphQL layer "
        "now, and does not refuse one forever. "
        "There is no GraphQL endpoint, schema or "
        "resolver; the REST API under /api/v1 is "
        "the programmatic surface. This page is "
        "the study's conclusion (research file 24), "
        "and the same words live in "
        "docs/GRAPHQL_VERDICT.md.</p>",
        "<h2>Why deferred</h2>",
        "<ul>",
    ]
    for reason in REASONS:
        parts.append(
            f"<li><strong>{escape_html_text(reason.title)}"
            f"</strong>: {escape_html_text(reason.detail)}"
            "</li>")
    parts.append("</ul>")
    parts.append("<h2>The three clients, judged</h2>")
    parts.append("<ul>")
    for client in CLIENTS:
        parts.append(
            f"<li><strong>{escape_html_text(client.title)}"
            f"</strong> ({escape_html_text(client.judgement)}): "
            f"needs {escape_html_text(client.need)} "
            f"REST today: {escape_html_text(client.rest_today)} "
            f"GraphQL gain: {escape_html_text(client.graphql_gain)}"
            "</li>")
    parts.append("</ul>")
    parts.append(
        "<h2>What a future GraphQL layer must not break</h2>")
    parts.append("<ul>")
    for invariant in MUST_NOT_BREAK:
        parts.append(
            f"<li><strong>{escape_html_text(invariant.title)}"
            f"</strong> (REST contract rule: "
            f"{escape_html_text(invariant.contract_rule)}): "
            f"{escape_html_text(invariant.statement)}</li>")
    parts.append("</ul>")
    parts.append("<h2>Governance caps, stated now</h2>")
    parts.append("<ul>")
    for cap in GOVERNANCE_CAPS:
        parts.append(
            f"<li>{escape_html_text(cap.title)}: "
            f"{cap.value} {escape_html_text(cap.unit)}</li>")
    parts.append("</ul>")
    parts.append("<h2>When this verdict reopens</h2>")
    parts.append("<ul>")
    for condition in REOPEN_CONDITIONS:
        parts.append(f"<li>{escape_html_text(condition)}</li>")
    parts.append("</ul>")
    if audit is not None:
        if audit.deferred_cleanly:
            parts.append(
                "<p>Checked, not just claimed: the "
                "REST contract was compared with the "
                f"live code over "
                f"{audit.rest_resources_checked} "
                "resources and still ratifies; this "
                "instance was inspected for a GraphQL "
                f"layer -- {audit.tables_scanned} "
                f"tables, {audit.columns_scanned} "
                f"columns and {audit.events_scanned} "
                "audit events -- and none was found: "
                "no GraphQL resource, table, column "
                "or event exists here.</p>")
        else:
            found = ", ".join(
                audit.graphql_contract_resources
                + audit.offending_tables
                + audit.offending_columns
                + audit.offending_events
                + (("REST contract no longer ratifies",)
                   if not audit.rest_ratified else ())
                + (("an invariant names no standing rule",)
                   if not audit.invariant_rules_ok else ()))
            parts.append(
                "<p>Checked, and not clean: the "
                "deferral no longer holds as stated -- "
                f"{escape_html_text(found)} -- and "
                "that is a defect against S-253, to "
                "be fixed where it lies.</p>")
    parts.append(
        "<p>The invariants above are also recorded "
        "in the REST contract itself "
        "(samverk/api_contract.py, rule "
        "graphql-deferred; docs/API_CONTRACT.md), "
        "so a future builder meets them in the "
        "contract they must not break, not only "
        "here.</p>")
    return "\n".join(parts)
