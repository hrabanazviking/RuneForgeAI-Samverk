"""API contract document (S-237).

Resources, verbs, and shapes written before code:
research file 23 holds the study; this slice
ratifies Samverk's own `/api/v1`. Part XII's
remaining slices (S-238..S-256) build against the
contract stated here -- they do not invent their
own shapes as they go.

- **The contract as data.** ``API_RESOURCES`` is
  the route table: every resource of `/api/v1`,
  its methods, the shape its representations
  carry, whether it is already landed or still
  contracted, and the slice that builds it.
  ``CONTRACT_RULES`` states the cross-cutting law
  every endpoint obeys. One page renders from
  that data (``render_api_contract_page`` at
  CONTRACT_PATH) and docs/API_CONTRACT.md says
  the same words for a reader who never opens
  the page.
- **Landed means landed; contracted means
  contracted.** Three faces stand behind this
  contract: the search face (S-216) and the
  events face (S-231), built in this shape before
  it was ratified and named by their own slices
  as Part XII work, and the repositories family
  (S-242, samverk/api_repositories.py: the root,
  the collection, one repository, its branches,
  its contents, and its forks), and the issues
  and pulls families (S-243,
  samverk/api_issues_pulls.py: issues with their
  comments, labels, assignees and milestones,
  and pull requests with their conversation,
  reviews and merge). Everything else
  in the table is a promise with a named builder:
  S-238 auth, S-239 pagination and conditional
  requests, S-240 the one problem format, S-241
  rate limits, S-244 the remaining
  resource family, S-245 the search
  ratification, S-246 statuses and checks, S-248
  webhooks. The contract never
  claims a contracted endpoint exists.
- **No API-only back doors.** Every resource is
  the programmatic face of a capability the web
  already has (the S-242 law, stated here for
  the whole API): the API can do nothing a
  signed-in person cannot, and every call
  resolves through S-190's permission engine
  with the same filtering as the surface it
  stands behind -- an unreadable repository
  contributes no row, no name and no count, and
  a private resource is indistinguishable from
  a missing one (the uniform not-found the
  landed faces already keep: `repo_not_found`,
  `event_not_found`).
- **Proven, not just claimed.**
  audit_api_contract reads the landed faces'
  own serialisers and refusals and compares
  their shapes with the shapes documented here:
  if a landed payload drifts from the contract,
  the audit stops being clean and the page says
  so in words -- the document then disagrees
  with the code, which is a defect in one of
  them, to be fixed where it lies. The route
  table itself is checked mechanically: every
  path under the versioned base, no method and
  path claimed twice, every contracted resource
  naming a builder inside Part XII.
- **A pure read, like S-202 and S-219.** This
  module holds no store, writes no row and
  audits nothing: a contract about the API is
  a document, and reading it changes nothing.
  No migration (schema stays 94), no taxonomy
  event (129 stand: 33 auth / 83 repo / 13
  admin).
"""
from __future__ import annotations

import ast
import dataclasses
from dataclasses import dataclass
from pathlib import Path

from .escaping import escape_html_text

__all__ = [
    "API_BASE", "API_RESOURCES", "CONTRACT_PATH",
    "CONTRACT_RULES", "CURRENT_ERROR_FIELDS",
    "EVENT_FIELDS", "FEED_ENVELOPE_FIELDS",
    "HTTP_METHODS", "PROBLEM_FIELDS",
    "SEARCH_GROUP_FIELDS", "SEARCH_RESULT_FIELDS",
    "ApiContractAudit", "ApiContractError",
    "ApiResource", "ContractRule",
    "audit_api_contract", "get_resource",
    "get_rule", "resource_ids", "rule_ids",
    "render_api_contract_page",
]

API_BASE = "/api/v1"
CONTRACT_PATH = "/api/contract"

HTTP_METHODS = ("GET", "POST", "PATCH", "DELETE")

# The list envelope both landed faces already
# speak (S-216 groups, S-231 feeds): the filtered
# total tallied before the cap, how many the cap
# returned, whether the answer is complete under
# that cap, and -- on feeds -- the limit honoured.
FEED_ENVELOPE_FIELDS = (
    "kind", "subject", "scope", "total", "returned",
    "complete", "limit", "events")

# One event as S-231's event_to_dict emits it:
# S-221's payload shape carried unchanged on its
# shared keys, extended with the resource's own
# addressing facts.
EVENT_FIELDS = (
    "id", "delivery_id", "event", "action", "actor",
    "actor_id", "actor_kind", "target", "target_kind",
    "repository", "number", "refs", "detail",
    "outcome", "occurred_at")

# One search as S-216's results_to_dict emits it,
# and one group inside it (group_to_dict; the code
# group additionally carries total_matches and
# total_matched_lines).
SEARCH_RESULT_FIELDS = ("query", "groups")
SEARCH_GROUP_FIELDS = (
    "type", "total", "returned", "complete", "results")

# The one problem format S-240 landed across
# all endpoints (its roadmap line names the five
# fields): every face's error_to_dict renders
# exactly these keys, in this order, through
# samverk/error_shape.py -- and the web UI's
# refusals match it. CURRENT_ERROR_FIELDS is
# the name S-238/S-239 pinned for the refusal
# shape of their day; it now names these fields.
PROBLEM_FIELDS = (
    "type", "title", "status", "detail", "error_id")
CURRENT_ERROR_FIELDS = PROBLEM_FIELDS


class ApiContractError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ContractRule:
    """One cross-cutting law of the API: a stable
    id, the plain title a reader sees, and the
    statement of the law, grounded in the banked
    engine or the named slice that builds it."""
    id: str
    title: str
    statement: str


CONTRACT_RULES: tuple[ContractRule, ...] = (
    ContractRule(
        id="versioned-base",
        title="One versioned base, from day one",
        statement=(
            "Every API path stands under /api/v1. "
            "The version is in the path, never in a "
            "header or a query parameter, so a script "
            "can see the contract it is speaking to "
            "in the address itself. What may change "
            "inside v1, and how a v2 would be "
            "introduced, is S-254's policy; this "
            "contract is the v1 it will govern.")),
    ContractRule(
        id="permission-parity",
        title="Every call resolves through S-190, with the web's own filtering",
        statement=(
            "An API call is judged by S-190's "
            "permission engine exactly as the web "
            "surface behind it is judged (S-238 "
            "lands the authentication; the judging "
            "is S-190's either way). The filtering "
            "is identical, not similar: the landed "
            "faces delegate to the very stores and "
            "engines the pages use, and an unreadable "
            "repository contributes no row, no name "
            "and no count. The API is never a hidden "
            "route around web or Git transport "
            "permissions (research file 23's law).")),
    ContractRule(
        id="uniform-not-found",
        title="Private is indistinguishable from missing",
        statement=(
            "A resource the caller may not read "
            "answers exactly as a resource that does "
            "not exist: the landed faces already keep "
            "this law (a missing or unreadable "
            "repository is the one refusal "
            "repo_not_found; a missing or invisible "
            "event is event_not_found), and every "
            "contracted resource inherits it. The "
            "API confirms nothing about what it "
            "hides.")),
    ContractRule(
        id="json-utf8",
        title="JSON only, UTF-8, honest content types",
        statement=(
            "Requests and responses are JSON in "
            "UTF-8; a body that is not JSON, or not "
            "UTF-8, is refused, never guessed at. "
            "Payloads are plain JSON-safe data "
            "(objects, arrays, strings, numbers, "
            "booleans, nulls) that round-trip through "
            "a JSON codec unchanged -- the landed "
            "faces already hold this shape. Data "
            "carries raw values: HTML escaping "
            "(S-010) is the page's law, not the "
            "wire's.")),
    ContractRule(
        id="list-envelope",
        title="Lists speak one envelope, and say when they are cut",
        statement=(
            "A list answer carries its filtered "
            "total tallied before the cap, the "
            "returned count the cap allowed, and a "
            "complete flag that says plainly whether "
            "the cap truncated the answer -- the "
            "envelope the landed search groups and "
            "event feeds already speak. Totals are "
            "never summed across permission "
            "boundaries. A caller who needs more "
            "than the cap is told so by complete, "
            "never silently short-changed.")),
    ContractRule(
        id="cursor-pagination",
        title="Cursor pagination and conditional requests (landed in S-239)",
        statement=(
            "Cursor pagination tied to a stable "
            "ordering, Link headers, and "
            "ETag / If-None-Match conditional "
            "requests landed in S-239 "
            "(samverk/api_pagination.py): keyset "
            "cursors over the filtered list, page "
            "size bounded at 100, Link headers "
            "walking first / prev / next / last, "
            "and a strong ETag whose If-None-Match "
            "match answers 304 with no body. The "
            "events face crawls through it today; "
            "the search groups keep the envelope's "
            "complete flag until S-245 gives their "
            "hits paging keys. Permission filtering "
            "still runs before paging on every "
            "request, so a cursor never widens "
            "what a caller may see.")),
    ContractRule(
        id="error-shape",
        title="One problem format across all endpoints (landed in S-240)",
        statement=(
            "Every endpoint refuses with the one "
            "problem format (type, title, status, "
            "detail, error id), shaped in one place "
            "(samverk/error_shape.py): the type is "
            "the reason's stable address under "
            "/api/v1/problems/, the title its "
            "plain-words summary, the status the "
            "registry's mapping, the detail the "
            "occurrence's own sentence, and the "
            "error id S-019's opaque bridge to the "
            "server log. The audit below pins "
            "exactly that on every API face, and "
            "the web UI's refusals match it: the "
            "server's S-019 body and S-113's error "
            "pages speak the same titles and "
            "details. S-240 landed this format; "
            "before it, the faces refused with two "
            "fields, and the contract said so.")),
    ContractRule(
        id="rate-limits",
        title=(
            "Rate limits are per-token, headed, and honest "
            "(landed in S-241)"),
        statement=(
            "S-241 landed the limiting itself, in "
            "samverk/api_rate_limit.py: per-token "
            "buckets judged at the API door over "
            "S-238's resolved callers (a password "
            "call is judged by its account, an "
            "anonymous call by the one tighter "
            "anonymous bucket), the limit headers "
            "(X-RateLimit-Limit, "
            "X-RateLimit-Remaining, "
            "X-RateLimit-Reset) on every judgement, "
            "an honest Retry-After computed from "
            "the bucket's own state on the "
            "rate_limited refusal (429, in the one "
            "problem format), and limits an "
            "instance configures in its settings "
            "table. No endpoint in this contract "
            "is unbounded by design; payload size "
            "caps and expensive-endpoint "
            "accounting are S-255's abuse "
            "defences.")),
    ContractRule(
        id="no-back-doors",
        title="No API-only back doors",
        statement=(
            "Every resource is the programmatic "
            "face of a capability the web already "
            "has, at the same permission (S-242's "
            "acceptance, generalised here to the "
            "whole table). An act the API performs "
            "is witnessed exactly as the same act "
            "on the web is witnessed; an act the "
            "web refuses, the API refuses. There "
            "is no endpoint whose only purpose is "
            "to bypass a page's law.")),
)


@dataclass(frozen=True)
class ApiResource:
    """One row of the route table: a stable id,
    the path pattern under the versioned base
    ({name} segments are path parameters), the
    methods it answers, a plain summary, the
    fields of its primary representation, its
    standing -- landed (a banked face stands
    behind it) or contracted (defined here,
    built by the named slice) -- and the slice
    that built it or will."""
    id: str
    path: str
    methods: tuple[str, ...]
    summary: str
    fields: tuple[str, ...]
    standing: str
    slice: str


_REPO_FIELDS = (
    "id", "owner", "name", "full_name", "visibility",
    "description", "default_branch", "created_at")
_ISSUE_FIELDS = (
    "id", "repository", "number", "title", "body",
    "state", "author", "labels", "assignees",
    "milestone", "created_at", "updated_at")
_PULL_FIELDS = (
    "id", "repository", "number", "title", "body",
    "state", "author", "head", "base", "merged",
    "created_at", "updated_at")

API_RESOURCES: tuple[ApiResource, ...] = (
    ApiResource(
        id="root", path="/api/v1", methods=("GET",),
        summary=(
            "The root: the contract's own address "
            "answers with the base, the version, "
            "and the resource families it holds, "
            "so a script can discover the table "
            "from the table's front door."),
        fields=("base", "version", "resources"),
        standing="landed", slice="S-242"),
    ApiResource(
        id="repositories", path="/api/v1/repos",
        methods=("GET", "POST"),
        summary=(
            "The repositories the caller may read, "
            "in the list envelope; POST creates one "
            "under the caller's own name with the "
            "web's own creation law."),
        fields=_REPO_FIELDS,
        standing="landed", slice="S-242"),
    ApiResource(
        id="repository",
        path="/api/v1/repos/{owner}/{repo}",
        methods=("GET", "PATCH", "DELETE"),
        summary=(
            "One repository: read, update its "
            "settings-shaped fields, or delete it "
            "-- each judged exactly as the web "
            "judges the same act on the same "
            "repository."),
        fields=_REPO_FIELDS,
        standing="landed", slice="S-242"),
    ApiResource(
        id="repository-branches",
        path="/api/v1/repos/{owner}/{repo}/branches",
        methods=("GET",),
        summary=(
            "The repository's branches, each with "
            "its tip, in the list envelope."),
        fields=("name", "tip", "protected"),
        standing="landed", slice="S-242"),
    ApiResource(
        id="repository-contents",
        path=("/api/v1/repos/{owner}/{repo}"
              "/contents/{path}"),
        methods=("GET",),
        summary=(
            "Contents read: one path of one ref, "
            "as data -- a blob's bytes carried "
            "encoded, a tree as its entries. Read "
            "only: the API writes files through "
            "Git, never around it."),
        fields=("path", "kind", "oid", "size", "entries"),
        standing="landed", slice="S-242"),
    ApiResource(
        id="repository-forks",
        path="/api/v1/repos/{owner}/{repo}/forks",
        methods=("GET", "POST"),
        summary=(
            "The repository's forks in the list "
            "envelope; POST forks it under the "
            "caller's name with S-055's own law."),
        fields=_REPO_FIELDS,
        standing="landed", slice="S-242"),
    ApiResource(
        id="issues",
        path="/api/v1/repos/{owner}/{repo}/issues",
        methods=("GET", "POST"),
        summary=(
            "The repository's issues in the list "
            "envelope; POST opens one. The full "
            "lifecycle of S-243: comments, labels, "
            "assignees, milestones, close and "
            "reopen ride the issue resource and "
            "its children."),
        fields=_ISSUE_FIELDS,
        standing="landed", slice="S-243"),
    ApiResource(
        id="issue",
        path=("/api/v1/repos/{owner}/{repo}"
              "/issues/{number}"),
        methods=("GET", "PATCH"),
        summary=(
            "One issue by its number: read it, or "
            "change the fields the web lets its "
            "people change, witnessed identically."),
        fields=_ISSUE_FIELDS,
        standing="landed", slice="S-243"),
    ApiResource(
        id="issue-comments",
        path=("/api/v1/repos/{owner}/{repo}"
              "/issues/{number}/comments"),
        methods=("GET", "POST"),
        summary=(
            "An issue's comments in the list "
            "envelope; POST adds one. Pull request "
            "conversation comments ride the same "
            "shape under the pulls resource."),
        fields=(
            "id", "issue", "author", "body",
            "created_at", "updated_at"),
        standing="landed", slice="S-243"),
    ApiResource(
        id="pulls",
        path="/api/v1/repos/{owner}/{repo}/pulls",
        methods=("GET", "POST"),
        summary=(
            "The repository's pull requests in the "
            "list envelope; POST opens one. S-243's "
            "acceptance is a script driving an "
            "entire PR from open to merge through "
            "this family."),
        fields=_PULL_FIELDS,
        standing="landed", slice="S-243"),
    ApiResource(
        id="pull",
        path=("/api/v1/repos/{owner}/{repo}"
              "/pulls/{number}"),
        methods=("GET", "PATCH"),
        summary=(
            "One pull request by its number: read "
            "it, or change what the web lets its "
            "people change."),
        fields=_PULL_FIELDS,
        standing="landed", slice="S-243"),
    ApiResource(
        id="pull-merge",
        path=("/api/v1/repos/{owner}/{repo}"
              "/pulls/{number}/merge"),
        methods=("POST",),
        summary=(
            "Merge the pull request, judged by the "
            "web's own merge law -- protection, "
            "approvals and permission included, "
            "never an API shortcut around them."),
        fields=("merged", "oid", "message"),
        standing="landed", slice="S-243"),
    ApiResource(
        id="pull-reviews",
        path=("/api/v1/repos/{owner}/{repo}"
              "/pulls/{number}/reviews"),
        methods=("GET", "POST"),
        summary=(
            "A pull request's reviews in the list "
            "envelope; POST submits one with the "
            "review law the web enforces."),
        fields=(
            "id", "pull", "author", "state", "body",
            "created_at"),
        standing="landed", slice="S-243"),
    ApiResource(
        id="user", path="/api/v1/users/{username}",
        methods=("GET",),
        summary=(
            "One person's public profile as data: "
            "exactly the facts the profile page "
            "shows a reader with this caller's "
            "standing, and no more."),
        fields=(
            "username", "display_name", "bio",
            "created_at"),
        standing="contracted", slice="S-244"),
    ApiResource(
        id="organization",
        path="/api/v1/orgs/{org}",
        methods=("GET", "PATCH"),
        summary=(
            "One organization: read it, or "
            "administer it as the web's org "
            "settings do, so membership and "
            "permission administration is "
            "automatable end-to-end (S-244)."),
        fields=(
            "id", "name", "display_name",
            "description", "created_at"),
        standing="contracted", slice="S-244"),
    ApiResource(
        id="organization-members",
        path="/api/v1/orgs/{org}/members",
        methods=("GET",),
        summary=(
            "The organization's members in the "
            "list envelope, each with the role "
            "the web records for them."),
        fields=("username", "role", "since"),
        standing="contracted", slice="S-244"),
    ApiResource(
        id="organization-teams",
        path="/api/v1/orgs/{org}/teams",
        methods=("GET", "POST"),
        summary=(
            "The organization's teams in the list "
            "envelope; POST creates one under the "
            "team machinery the web uses."),
        fields=("id", "slug", "name", "privacy"),
        standing="contracted", slice="S-244"),
    ApiResource(
        id="search", path="/api/v1/search",
        methods=("GET",),
        summary=(
            "The global search as data (S-216, "
            "ratified as the public contract by "
            "S-245): the query as typed, then one "
            "group per kind searched, each with "
            "its own filtered total, returned "
            "count and complete flag; totals are "
            "never summed across groups."),
        fields=SEARCH_RESULT_FIELDS,
        standing="landed", slice="S-216"),
    ApiResource(
        id="events", path="/api/v1/events",
        methods=("GET",),
        summary=(
            "The instance's public activity feed "
            "as data (S-231): the feed envelope "
            "over S-229's public feed, judged "
            "event by event for this caller."),
        fields=FEED_ENVELOPE_FIELDS,
        standing="landed", slice="S-231"),
    ApiResource(
        id="user-events",
        path="/api/v1/users/{username}/events",
        methods=("GET",),
        summary=(
            "One person's activity feed as data "
            "(S-231), with S-229's own per-event "
            "filtering: what this caller may not "
            "read contributes no row and no count."),
        fields=FEED_ENVELOPE_FIELDS,
        standing="landed", slice="S-231"),
    ApiResource(
        id="repository-events",
        path=("/api/v1/repos/{owner}/{repo}"
              "/events"),
        methods=("GET",),
        summary=(
            "One repository's activity feed as "
            "data (S-231); a missing or unreadable "
            "repository is the one refusal "
            "repo_not_found."),
        fields=FEED_ENVELOPE_FIELDS,
        standing="landed", slice="S-231"),
    ApiResource(
        id="event", path="/api/v1/events/{id}",
        methods=("GET",),
        summary=(
            "One canonical event by its id "
            "(S-231), read through S-221's store "
            "under its own visibility law; a "
            "missing or invisible event is "
            "event_not_found."),
        fields=EVENT_FIELDS,
        standing="landed", slice="S-231"),
    ApiResource(
        id="statuses",
        path=("/api/v1/repos/{owner}/{repo}"
              "/statuses/{oid}"),
        methods=("GET", "POST"),
        summary=(
            "Commit statuses (S-246): external CI "
            "posts a status for a commit; readers "
            "list them as S-157's checks panel "
            "does. The poster's identity is scoped "
            "and audit-logged."),
        fields=(
            "id", "oid", "state", "context",
            "description", "target_url", "poster",
            "created_at"),
        standing="contracted", slice="S-246"),
    ApiResource(
        id="check-runs",
        path=("/api/v1/repos/{owner}/{repo}"
              "/check-runs"),
        methods=("GET", "POST"),
        summary=(
            "Check runs (S-246): external CI posts "
            "and updates check runs against a "
            "commit, consumed by S-157's panel; "
            "the poster is scoped and audit-logged "
            "exactly as for statuses."),
        fields=(
            "id", "oid", "name", "status",
            "conclusion", "poster", "created_at",
            "updated_at"),
        standing="contracted", slice="S-246"),
    ApiResource(
        id="repository-hooks",
        path="/api/v1/repos/{owner}/{repo}/hooks",
        methods=("GET", "POST"),
        summary=(
            "Webhook subscriptions on one "
            "repository (S-248): event filters, "
            "active or inactive, and a secret set "
            "at creation and never shown again. "
            "The event taxonomy is S-247's, the "
            "signing S-249's, delivery S-250's."),
        fields=(
            "id", "events", "active", "url",
            "created_at"),
        standing="contracted", slice="S-248"),
    ApiResource(
        id="organization-hooks",
        path="/api/v1/orgs/{org}/hooks",
        methods=("GET", "POST"),
        summary=(
            "Webhook subscriptions at the "
            "organization level (S-248), under "
            "the same law as repository hooks."),
        fields=(
            "id", "events", "active", "url",
            "created_at"),
        standing="contracted", slice="S-248"),
)


def resource_ids() -> tuple[str, ...]:
    """The ids of every ratified resource, in
    route-table order."""
    return tuple(r.id for r in API_RESOURCES)


def get_resource(resource_id: object) -> ApiResource:
    """One ratified resource by its id. An unknown
    id is refused resource_unknown -- the contract
    does not invent a resource to answer with."""
    for resource in API_RESOURCES:
        if resource.id == resource_id:
            return resource
    raise ApiContractError(
        "resource_unknown", "No such API resource "
        "is ratified.")


def rule_ids() -> tuple[str, ...]:
    """The ids of every cross-cutting rule, in
    document order."""
    return tuple(rule.id for rule in CONTRACT_RULES)


def get_rule(rule_id: object) -> ContractRule:
    """One cross-cutting rule by its id. An unknown
    id is refused rule_unknown."""
    for rule in CONTRACT_RULES:
        if rule.id == rule_id:
            return rule
    raise ApiContractError(
        "rule_unknown", "No such API contract rule "
        "is stated.")


@dataclass(frozen=True)
class ApiContractAudit:
    """The contract checked against the live code:
    the route table's own soundness, the landed
    faces' serialiser shapes compared with the
    fields documented here, today's refusal shape
    on both landed faces, and S-190's engine
    standing where the contract says it stands.
    Ratified only when every check holds."""
    resources_checked: int
    routes_checked: int
    route_problems: tuple[str, ...]
    landed_shapes_checked: int
    landed_shape_mismatches: tuple[str, ...]
    error_shape_ok: bool
    permission_engine_present: bool

    @property
    def ratified(self) -> bool:
        return (not self.route_problems
                and not self.landed_shape_mismatches
                and self.error_shape_ok
                and self.permission_engine_present)


def _returned_dict_keys(module_name: str,
                        function_name: str) -> tuple[str, ...]:
    """The literal keys of the dict one serialiser
    function returns, read from its own source by
    ast: the function's first top-level return of
    a dict literal, keys in source order. Pure
    introspection -- nothing is called."""
    path = Path(__file__).with_name(f"{module_name}.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    def keys_of(dict_node: ast.Dict) -> tuple[str, ...]:
        return tuple(
            key.value for key in dict_node.keys
            if isinstance(key, ast.Constant))

    for node in ast.walk(tree):
        if (isinstance(node, ast.FunctionDef)
                and node.name == function_name):
            assigned: dict[str, ast.Dict] = {}
            for stmt in ast.walk(node):
                if (isinstance(stmt, ast.Assign)
                        and isinstance(stmt.value, ast.Dict)):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            assigned[target.id] = stmt.value
                if isinstance(stmt, ast.Return):
                    if isinstance(stmt.value, ast.Dict):
                        return keys_of(stmt.value)
                    if (isinstance(stmt.value, ast.Name)
                            and stmt.value.id in assigned):
                        return keys_of(
                            assigned[stmt.value.id])
    return ()


def audit_api_contract() -> ApiContractAudit:
    """Check this contract against the live code:
    the route table (paths under the base, known
    methods, no method+path twice, standings
    honest, contracted resources naming a Part
    XII builder); the landed faces' shapes read
    from their own serialisers (S-231's feed and
    event dicts, S-216's search result and group
    dicts) against the fields documented here;
    every API face's refusals (S-216, S-231,
    S-238, S-239) against CURRENT_ERROR_FIELDS;
    and S-190's
    PermissionEngine standing importable. Pure
    read: imports and introspection only."""
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    routes = 0
    for resource in API_RESOURCES:
        if resource.path != API_BASE and not (
                resource.path.startswith(API_BASE + "/")):
            problems.append(f"{resource.id}:path")
        if resource.standing not in ("landed", "contracted"):
            problems.append(f"{resource.id}:standing")
        if resource.standing == "contracted" and not (
                resource.slice.startswith("S-2")
                and 238 <= int(resource.slice[2:]) <= 256):
            problems.append(f"{resource.id}:builder")
        if not resource.fields:
            problems.append(f"{resource.id}:fields")
        for method in resource.methods:
            routes += 1
            if method not in HTTP_METHODS:
                problems.append(f"{resource.id}:{method}")
            if (method, resource.path) in seen:
                problems.append(
                    f"{resource.id}:duplicate:{method}")
            seen.add((method, resource.path))
    mismatches: list[str] = []
    landed = {
        "feed_to_dict": (
            "events_api", FEED_ENVELOPE_FIELDS),
        "event_to_dict": ("events_api", EVENT_FIELDS),
        "results_to_dict": (
            "search_api", SEARCH_RESULT_FIELDS),
        "group_to_dict": (
            "search_api", SEARCH_GROUP_FIELDS),
        "repository_to_dict": (
            "api_repositories", _REPO_FIELDS),
        "issue_to_dict": (
            "api_issues_pulls", _ISSUE_FIELDS),
        "pull_to_dict": (
            "api_issues_pulls", _PULL_FIELDS),
        "comment_to_dict": (
            "api_issues_pulls", (
                "id", "issue", "author", "body",
                "created_at", "updated_at")),
        "review_to_dict": (
            "api_issues_pulls", (
                "id", "pull", "author", "state", "body",
                "created_at")),
    }
    for function_name, (module_name, documented) in (
            landed.items()):
        live = _returned_dict_keys(module_name, function_name)
        if tuple(live) != tuple(documented):
            mismatches.append(function_name)
    from . import (
        api_auth, api_issues_pulls, api_pagination,
        api_rate_limit, api_repositories, events_api,
        search_api)
    error_ok = True
    for module, exc_type in (
            (events_api, events_api.EventsAPIError),
            (search_api, search_api.SearchAPIError),
            (api_auth, api_auth.ApiAuthError),
            (api_rate_limit, api_rate_limit.ApiRateLimitError),
            (api_pagination, api_pagination.ApiPaginationError),
            (api_repositories,
             api_repositories.RepositoriesAPIError),
            (api_issues_pulls,
             api_issues_pulls.IssuesPullsAPIError)):
        rendered = module.error_to_dict(
            exc_type("audit_probe", "probe"))
        if tuple(rendered.keys()) != CURRENT_ERROR_FIELDS:
            error_ok = False
    from .permission_engine import PermissionEngine
    return ApiContractAudit(
        resources_checked=len(API_RESOURCES),
        routes_checked=routes,
        route_problems=tuple(problems),
        landed_shapes_checked=len(landed),
        landed_shape_mismatches=tuple(mismatches),
        error_shape_ok=error_ok,
        permission_engine_present=(
            PermissionEngine is not None))


def render_api_contract_page(
        audit: ApiContractAudit | None = None) -> str:
    """The contract, rendered where integrators
    find it: the base and the rules in plain
    words, the whole route table in order with
    each resource's standing said aloud, the
    checked proof when an audit rides along, and
    the pointer to the same words in
    docs/API_CONTRACT.md. Every value escaped
    through S-010; standing is said in words,
    never colour-only."""
    parts = [
        "<h1>The /api/v1 contract</h1>",
        "<p>Samverk's API is its own design, "
        "versioned from day one. This page is the "
        "contract the Part XII slices build "
        "against: the resources, the verbs, the "
        "shapes, and the law every endpoint obeys. "
        "A resource marked contracted is defined "
        "here and not yet built; the table names "
        "the slice that builds it.</p>",
    ]
    for rule in CONTRACT_RULES:
        parts.append(
            f'<h2 id="rule-{escape_html_text(rule.id)}">'
            f"{escape_html_text(rule.title)}</h2>")
        parts.append(f"<p>{escape_html_text(rule.statement)}</p>")
    parts.append("<h2>The resources</h2>")
    parts.append("<ul>")
    for resource in API_RESOURCES:
        standing = (
            "landed" if resource.standing == "landed"
            else f"contracted -- built by {resource.slice}")
        parts.append(
            "<li>"
            f"<strong>{escape_html_text(' '.join(resource.methods))} "
            f"{escape_html_text(resource.path)}</strong> "
            f"({escape_html_text(standing)}): "
            f"{escape_html_text(resource.summary)} "
            "Fields: "
            f"{escape_html_text(', '.join(resource.fields))}."
            "</li>")
    parts.append("</ul>")
    if audit is not None:
        if audit.ratified:
            parts.append(
                "<p>Checked, not just claimed: this "
                "contract was compared with the live "
                f"code -- {audit.routes_checked} "
                "routes over "
                f"{audit.resources_checked} resources "
                "are sound, "
                f"{audit.landed_shapes_checked} landed "
                "shapes match the fields written here, "
                "every API face refuses with the one "
                "problem format, and S-190's "
                "permission engine stands where the "
                "contract says it stands.</p>")
        else:
            problems = ", ".join(
                audit.route_problems
                + audit.landed_shape_mismatches
                + (("error shape drifted",)
                   if not audit.error_shape_ok else ())
                + (("permission engine missing",)
                   if not audit.permission_engine_present
                   else ()))
            parts.append(
                "<p>Checked, and no longer exact: "
                "this contract disagrees with the "
                f"live code -- {escape_html_text(problems)} "
                "-- and that is a defect against "
                "S-237, in the contract or in the "
                "code, to be fixed where it lies.</p>")
    parts.append(
        "<p>The same contract lives in "
        "docs/API_CONTRACT.md for a reader who "
        "never opens this page. The study behind "
        "it is research file 23; the GraphQL "
        "verdict is S-253's, and the versioning "
        "policy is S-254's.</p>")
    return "\n".join(parts)
