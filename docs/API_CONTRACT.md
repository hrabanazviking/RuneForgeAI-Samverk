# The /api/v1 contract (S-237)

Samverk's API is its own design, informed by the
public habits research file 23 studied, versioned
from day one. This document is written before the
code: Part XII's remaining slices (S-238..S-256)
build against the resources, verbs and shapes
ratified here — they do not invent their own as
they go. The same words render in the app on the
API contract page (`samverk/api_contract.py`), and
that module checks this document's landed shapes
against the live code on every test run: if a
landed payload below stops being true of the code,
the battery fails.

Two faces already stand behind this contract: the
search face (S-216) and the events face (S-231),
built in this shape before it was ratified.
Everything else below is **contracted** — defined
here, not yet built — and each resource names the
slice that builds it. This document never claims a
contracted endpoint exists.

## The law every endpoint obeys

- **versioned-base** — One versioned base, from
  day one. Every API path stands under `/api/v1`.
  The version is in the path, never in a header or
  a query parameter. What may change inside v1, and
  how a v2 would be introduced, is S-254's policy.
- **permission-parity** — Every call resolves
  through S-190's permission engine exactly as the
  web surface behind it is judged (S-238 lands the
  authentication). An unreadable repository
  contributes no row, no name and no count. The API
  is never a hidden route around web or Git
  transport permissions.
- **uniform-not-found** — Private is
  indistinguishable from missing: a missing or
  unreadable repository is the one refusal
  `repo_not_found`; a missing or invisible event is
  `event_not_found`. The API confirms nothing about
  what it hides.
- **json-utf8** — Requests and responses are JSON
  in UTF-8; a body that is not JSON, or not UTF-8,
  is refused, never guessed at. Payloads are plain
  JSON-safe data that round-trip through a JSON
  codec unchanged. Data carries raw values: HTML
  escaping (S-010) is the page's law, not the
  wire's.
- **list-envelope** — A list answer carries its
  filtered total tallied before the cap, the
  returned count the cap allowed, and a `complete`
  flag that says plainly whether the cap truncated
  the answer. Totals are never summed across
  permission boundaries.
- **cursor-pagination** — Cursor pagination tied
  to a stable ordering, `Link` headers, and
  ETag / `If-None-Match` conditional requests
  landed in S-239 (samverk/api_pagination.py):
  keyset cursors over the permission-filtered
  list, page size bounded at 100, Link headers
  walking first / prev / next / last, and a
  strong ETag whose `If-None-Match` match
  answers 304 with no body. The events face
  crawls through it today; the search groups
  keep the envelope's `complete` flag until
  S-245 gives their hits paging keys.
- **error-shape** — Today both landed faces refuse
  with `error` and `detail` — a machine-branchable
  reason and a human sentence. S-240 lands the one
  problem format across all endpoints — `type`,
  `title`, `status`, `detail`, `error_id` — and
  the web UI's refusals will match it.
- **rate-limits** — S-241 contracts per-token
  buckets, limit headers on every response, an
  honest `Retry-After`, and instance-configurable
  limits. Payload size caps and expensive-endpoint
  accounting are S-255's abuse defences.
- **no-back-doors** — Every resource is the
  programmatic face of a capability the web already
  has, at the same permission. An act the API
  performs is witnessed exactly as the same act on
  the web; an act the web refuses, the API refuses.

## The resources

### Landed

- `GET /api/v1/search` — the global search as data
  (S-216; ratified as the public contract by
  S-245). Shape: `query`, `groups`; each group
  carries `type`, `total`, `returned`, `complete`,
  `results`, and the code group additionally
  carries `total_matches` and `total_matched_lines`.
- `GET /api/v1/events` — the instance's public
  activity feed as data (S-231), in the feed
  envelope: `kind`, `subject`, `scope`, `total`,
  `returned`, `complete`, `limit`, `events`.
- `GET /api/v1/users/{username}/events` — one
  person's activity feed as data (S-231), with
  S-229's own per-event filtering.
- `GET /api/v1/repos/{owner}/{repo}/events` — one
  repository's activity feed as data (S-231).
- `GET /api/v1/events/{id}` — one canonical event
  (S-231): `id`, `delivery_id`, `event`, `action`,
  `actor`, `actor_id`, `actor_kind`, `target`,
  `target_kind`, `repository`, `number`, `refs`,
  `detail`, `outcome`, `occurred_at`.

### Contracted

- `GET /api/v1` — the root (built by S-242): the
  base, the version, and the resource families the
  contract holds, so a script can discover the
  table from its front door.
- `GET, POST /api/v1/repos` — the repositories the
  caller may read, in the list envelope; POST
  creates one under the caller's own name (S-242).
- `GET, PATCH, DELETE /api/v1/repos/{owner}/{repo}`
  — one repository: read, update, or delete it,
  each judged exactly as the web judges the same
  act (S-242). A repository representation carries
  `id`, `owner`, `name`, `full_name`, `visibility`,
  `description`, `default_branch`, `created_at`.
- `GET /api/v1/repos/{owner}/{repo}/branches` —
  the repository's branches, each with its tip
  (S-242).
- `GET /api/v1/repos/{owner}/{repo}/contents/{path}`
  — contents read: one path of one ref, as data.
  Read only: the API writes files through Git,
  never around it (S-242).
- `GET, POST /api/v1/repos/{owner}/{repo}/forks` —
  the repository's forks; POST forks it under the
  caller's name with S-055's own law (S-242).
- `GET, POST /api/v1/repos/{owner}/{repo}/issues`
  — the repository's issues in the list envelope;
  POST opens one (S-243). An issue carries `id`,
  `repository`, `number`, `title`, `body`, `state`,
  `author`, `labels`, `assignees`, `milestone`,
  `created_at`, `updated_at`.
- `GET, PATCH /api/v1/repos/{owner}/{repo}/issues/{number}`
  — one issue by its number (S-243).
- `GET, POST /api/v1/repos/{owner}/{repo}/issues/{number}/comments`
  — an issue's comments; POST adds one (S-243).
- `GET, POST /api/v1/repos/{owner}/{repo}/pulls` —
  the repository's pull requests; POST opens one
  (S-243). A pull request carries `id`,
  `repository`, `number`, `title`, `body`, `state`,
  `author`, `head`, `base`, `merged`, `created_at`,
  `updated_at`.
- `GET, PATCH /api/v1/repos/{owner}/{repo}/pulls/{number}`
  — one pull request by its number (S-243).
- `POST /api/v1/repos/{owner}/{repo}/pulls/{number}/merge`
  — merge the pull request, judged by the web's own
  merge law — protection, approvals and permission
  included, never an API shortcut around them
  (S-243).
- `GET, POST /api/v1/repos/{owner}/{repo}/pulls/{number}/reviews`
  — a pull request's reviews; POST submits one with
  the review law the web enforces (S-243).
- `GET /api/v1/users/{username}` — one person's
  public profile as data: exactly the facts the
  profile page shows a reader with this caller's
  standing, and no more (S-244).
- `GET, PATCH /api/v1/orgs/{org}` — one
  organization: read it, or administer it as the
  web's org settings do (S-244).
- `GET /api/v1/orgs/{org}/members` — the
  organization's members in the list envelope, each
  with the role the web records for them (S-244).
- `GET, POST /api/v1/orgs/{org}/teams` — the
  organization's teams; POST creates one under the
  team machinery the web uses (S-244).
- `GET, POST /api/v1/repos/{owner}/{repo}/statuses/{oid}`
  — commit statuses: external CI posts a status for
  a commit; readers list them as S-157's checks
  panel does. The poster's identity is scoped and
  audit-logged (S-246).
- `GET, POST /api/v1/repos/{owner}/{repo}/check-runs`
  — check runs against a commit, consumed by
  S-157's panel; the poster is scoped and
  audit-logged exactly as for statuses (S-246).
- `GET, POST /api/v1/repos/{owner}/{repo}/hooks` —
  webhook subscriptions on one repository: event
  filters, active or inactive, and a secret set at
  creation and never shown again. The event
  taxonomy is S-247's, the signing S-249's, delivery
  S-250's; this resource is built by S-248.
- `GET, POST /api/v1/orgs/{org}/hooks` — webhook
  subscriptions at the organization level, under
  the same law as repository hooks (S-248).

## What this contract does not do

It builds no endpoint: authentication is S-238's,
pagination S-239's, the problem format S-240's,
rate limiting S-241's, the resource families
S-242..S-246's and S-248's, the GraphQL verdict
S-253's, and the versioning policy S-254's. The
Part XII gate (S-256) will exercise every
documented endpoint against its contract tests;
until a resource's builder lands, its row here is
a ratified promise, and this document says so
wherever the promise is made.
