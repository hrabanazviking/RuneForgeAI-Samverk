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

The search face (S-216) and the events face
(S-231) were built in this shape before it was
ratified; the repositories (S-242), issues and
pulls (S-243), and users, orgs and teams (S-244)
families then landed against it, S-245
ratified the search face as the public contract,
and S-246 landed the status and checks face.
What remains below as **contracted** — defined
here, not yet built — names the slice that builds
it. This document never claims a contracted
endpoint exists.

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
  crawls through it today; since S-245 the
  search groups carry paging keys too — one
  group at a time, re-filtered on every page,
  its `complete` flag true only at the group's
  true total.
- **error-shape** -- Every endpoint refuses with
  the one problem format -- `type`, `title`,
  `status`, `detail`, `error_id` -- shaped in one
  place (samverk/error_shape.py), and the web UI's
  refusals match it (landed in S-240; before it,
  the faces refused with `error` and `detail`).
- **rate-limits** — Per-token buckets judged at
  the API door over S-238's resolved callers (a
  password call is judged by its account, an
  anonymous call by the one tighter anonymous
  bucket), the limit headers
  (`X-RateLimit-Limit`, `X-RateLimit-Remaining`,
  `X-RateLimit-Reset`) on every judgement, an
  honest `Retry-After` computed from the bucket's
  own state on the `rate_limited` refusal (429,
  in the one problem format), and limits an
  instance configures in its settings table
  (landed in S-241, samverk/api_rate_limit.py).
  Payload size caps and expensive-endpoint
  accounting are S-255's abuse defences.
- **graphql-deferred** — GraphQL is deferred
  (S-253, samverk/graphql_verdict.py): there is
  no GraphQL endpoint, schema or resolver, and
  this REST contract is the programmatic
  surface. A future GraphQL layer is additive
  only and must not break this contract — the
  invariants are recorded in the GraphQL
  section below and in full in
  docs/GRAPHQL_VERDICT.md.
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
  S-245 (samverk/api_search.py) answers the face
  through the API door (S-238) and pages one
  group at a time by cursor (S-239): a page
  carries `query`, `type`, `total`, `returned`,
  `complete`, `per_page`, `has_next`,
  `has_previous`, `next_cursor`,
  `previous_cursor`, `results` (the code group
  additionally its match totals).
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

- `GET /api/v1` — the root (S-242): the
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
  profile page shows (S-244). A user carries
  `username`, `display_name`, `bio`, `created_at`.
- `GET, POST /api/v1/orgs` — the instance's
  organizations in the list envelope; POST creates
  one under S-185's own creation law (S-244). An
  organization carries `id`, `name`,
  `display_name`, `description`, `created_at`.
- `GET, PATCH /api/v1/orgs/{org}` — one
  organization: read it, or administer its profile
  as the web's org settings do (S-244).
- `GET, POST /api/v1/orgs/{org}/members` — the
  organization's members in the list envelope,
  each with the role the web records for them;
  POST adds one (S-244). A member carries
  `username`, `role`, `since`.
- `GET, PATCH, DELETE /api/v1/orgs/{org}/members/{username}`
  — one membership: read it, set its role, or
  remove the member, through S-186's own store
  with its last-owner invariant (S-244).
- `GET, POST /api/v1/orgs/{org}/teams` — the
  organization's teams, filtered by S-187's
  viewer law; POST creates one under the team
  machinery the web uses (S-244). A team carries
  `id`, `slug`, `name`, `privacy`.
- `GET, PATCH /api/v1/orgs/{org}/teams/{team}` —
  one team: read it under the viewer law, or
  change its description and privacy. The web has
  no team deletion and no rename, so neither does
  the API (S-244).
- `GET, POST /api/v1/orgs/{org}/teams/{team}/members`
  — one team's members in the list envelope;
  POST adds one who already belongs to the
  organization (S-244).
- `DELETE /api/v1/orgs/{org}/teams/{team}/members/{username}`
  — remove one member from one team (S-244).
- `GET, POST /api/v1/orgs/{org}/teams/{team}/repos`
  — one team's direct repository permissions in
  the list envelope (org owners and site admins);
  POST links one of the organization's
  repositories and may grade it in the same call
  (S-244). A team permission carries `repository`,
  `permission`.
- `PATCH, DELETE /api/v1/orgs/{org}/teams/{team}/repos/{repo}`
  — set one linked repository's S-189 ladder role,
  or unlink it (S-244).
- `GET, PATCH /api/v1/orgs/{org}/default-permission`
  — the organization's default repository
  permission (S-192): the role every member holds
  at least, and whether an owner ever set it
  (S-244). It carries `role`, `is_set`.
- `GET, POST /api/v1/repos/{owner}/{repo}/collaborators`
  — one repository's outside collaborators in the
  list envelope; POST grants one a ladder role,
  judged through S-190 at the admin rung (S-244).
  A grant carries `username`, `role`, `repository`.
- `PATCH, DELETE /api/v1/repos/{owner}/{repo}/collaborators/{username}`
  — move one outside grant up or down the ladder,
  or revoke it; DELETE answers with the grant that
  was removed (S-244).
- `GET, POST /api/v1/repos/{owner}/{repo}/statuses/{oid}`
  — commit statuses: external CI posts a status
  for a commit through S-157's one record; readers
  list them as S-157's checks panel does. A status
  carries `id`, `oid`, `state`, `context`,
  `description`, `target_url`, `poster`,
  `created_at`. The poster's identity is scoped
  (S-238's door, S-190 at the write rung, the
  token scope as a ceiling) and audit-logged on
  repo.status.post (S-246).
- `GET, POST /api/v1/repos/{owner}/{repo}/check-runs`
  — check runs against a commit, kept in the run
  vocabulary and folded onto S-157's record under
  their name, consumed by S-157's panel. A run
  carries `id`, `oid`, `name`, `status`,
  `conclusion`, `poster`, `created_at`,
  `updated_at`. The poster is scoped and
  audit-logged on repo.check_run.post exactly as
  for statuses (S-246).

### Contracted

- `GET, POST /api/v1/repos/{owner}/{repo}/hooks` —
  webhook subscriptions on one repository: event
  filters, active or inactive, and a secret set at
  creation and never shown again. The event
  taxonomy is S-247's (samverk/webhook_events.py,
  documented per event in docs/WEBHOOK_EVENTS.md:
  repository-scope and organization-scope verbs
  are deliverable, account and administration
  verbs never are), the signing S-249's, delivery
  S-250's; this resource is built by S-248.
- `GET, POST /api/v1/orgs/{org}/hooks` — webhook
  subscriptions at the organization level, under
  the same law as repository hooks (S-248).

## GraphQL — deferred (S-253)

There is no GraphQL endpoint. S-253's verdict,
concluding research file 24's study, is
**deferred**: REST meets the measured needs of
the three clients the study names (the issue
board, the PR review page, organization
administration), only one in-house consumer
would use a GraphQL layer today, and the
governance its abuse class needs does not yet
exist. The full verdict, reasons and reopen
conditions live in docs/GRAPHQL_VERDICT.md
(module: samverk/graphql_verdict.py).

If a future layer is ever built, it must not
break this contract. The recorded invariants:

- `permission-parity-per-field` — per object
  and per field through S-190.
- `private-is-missing-by-node-id` — private is
  indistinguishable from missing, by node id
  too.
- `rest-shapes-are-the-source-of-truth` —
  additive only; REST v1 shapes and stable ids
  govern.
- `connections-keep-list-honesty` — S-239
  cursors, filtered totals, complete flag.
- `errors-stay-typed-and-shared` — S-240's
  registered reasons only.
- `cost-governance-from-day-one` — S-241's
  buckets plus depth, cost, bytes, time and
  alias caps.
- `mutations-share-stores-and-witness` — same
  stores, same audit verbs, idempotent, never
  partially writing.
- `schema-from-resources-not-tables` — schema
  designed from resources, never tables
  one-to-one.

## What this contract does not do

It builds no endpoint: authentication is S-238's,
pagination S-239's, the problem format S-240's,
rate limiting S-241's, the resource families
S-242..S-246's and S-248's, and the versioning
policy S-254's. The GraphQL verdict (S-253)
has landed as a deferral, recorded above. The
Part XII gate (S-256) will exercise every
documented endpoint against its contract tests;
until a resource's builder lands, its row here is
a ratified promise, and this document says so
wherever the promise is made.
