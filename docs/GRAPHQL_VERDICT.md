# GraphQL — deferred (S-253)

Samverk has no GraphQL layer, and this page is the
recorded verdict that says why, what would have to
change, and what a future layer must not break. It
concludes the study in research file 24
(`research/24-graphql-api-shape.md`), which reserved
GraphQL as a decision, not a mandatory copy of
another forge's API.

## The verdict

**Deferred.** Not built now; not refused forever.

## Why deferred — the reasons

- `rest-meets-measured-needs` — REST already meets
  the measured needs. Every face a GraphQL layer
  would serve already stands in REST (S-242
  repositories, S-243 issues and pulls, S-244
  users/orgs/teams, S-245 search, S-246 statuses
  and checks), each in the list envelope with
  cursor pagination (S-239). No client has
  measured an overfetch or call-count pain for
  GraphQL to cure, and research file 24 asks for
  that benchmark before adoption.
- `one-in-house-consumer` — Only one in-house
  consumer would use it: Samverk's own web UI,
  which already speaks to the same stores the REST
  faces delegate to. Research file 24's stated
  rule is to prefer an intentional deferral in
  exactly this case.
- `a-second-permanent-surface` — A schema is a
  second permanent API surface. Its field-level
  authorization and query-cost governance are a
  long-lived maintenance commitment: every future
  resource would be designed, permissioned and
  tested twice, while S-254's versioning policy
  and S-255's abuse defences have not yet landed
  even for the first surface.
- `a-new-abuse-class` — Graph traversal is a new
  abuse class: nested traversal can generate
  multiplicative queries, recursive fragments and
  alias bombing complicate rate limits, and a node
  lookup by id is a new road at private objects.
  Shipping the surface before its governance
  would invert the security-first founding order.
- `village-scale-simplicity` — Village scale
  rewards the simpler contract. Samverk is
  stdlib-first, with dependencies admitted one at
  a time for a written reason; a GraphQL runtime
  would need that admission against a benefit no
  measured need currently states.

## The three clients research file 24 names

- **The issue board** (`issue-board`) — rest
  suffices. S-243's issues family in the list
  envelope, paged by S-239 cursors, already gives
  the board its lists with labels, assignees,
  milestone and state.
- **The PR review page** (`pr-review-page`) — rest
  suffices today. This is the deepest relationship
  read Samverk has and the strongest future case
  for GraphQL: one graph query could replace a
  small bounded set of REST calls. It is the first
  client a reopened verdict must benchmark.
- **Organization administration**
  (`organization-administration`) — rest suffices.
  S-244's family automates membership and
  permission administration end to end; GraphQL's
  relationship-read strength does not apply to
  writes and small reads.

## What a future GraphQL layer must not break

These invariants are recorded here and in the REST
contract itself (`samverk/api_contract.py`, rule
`graphql-deferred`; `docs/API_CONTRACT.md`), so a
future builder meets them in the contract they
must not break:

- `permission-parity-per-field` — every object and
  every field resolves through S-190's permission
  engine exactly as REST and the web are judged; a
  field the caller may not read is absent, never
  present-but-redacted.
- `private-is-missing-by-node-id` — a node lookup
  naming a private or unreadable object answers
  exactly as a lookup naming nothing; global ids
  are opaque encodings of the REST resources'
  stable ids.
- `rest-shapes-are-the-source-of-truth` — a
  GraphQL layer is additive only; it maps from the
  REST contract's resources, fields and stable ids
  and never renames, removes or re-meanings a REST
  shape.
- `connections-keep-list-honesty` — connections
  are S-239's keyset cursors over the
  permission-filtered list and carry the filtered
  total and the complete flag; totals are never
  summed across permission boundaries.
- `errors-stay-typed-and-shared` — a GraphQL error
  carries the refusing store's own reason from
  S-240's registry, the same type, title and
  status REST answers, so clients learn one
  refusal vocabulary.
- `cost-governance-from-day-one` — S-241's
  per-token buckets and query-cost governance
  both apply: maximum depth 8, maximum cost 1000,
  maximum response 1000000 bytes, maximum
  execution 10 seconds, maximum 30 aliases, and
  introspection for authenticated callers only.
  An over-budget query is refused whole.
- `mutations-share-stores-and-witness` — a
  mutation performs its act through the very store
  the web and REST use, is witnessed by the same
  audit verb, and is idempotent by
  client-supplied key; a batched mutation lands
  whole or refuses whole, never in part.
- `schema-from-resources-not-tables` — the public
  schema is designed from the REST contract's
  resources, never by exposing database tables
  one-to-one.

## When this verdict reopens

- A second, independent consumer needs
  relationship reads REST serves poorly, with its
  own workload as evidence.
- A benchmark in research file 24's acceptance
  shape — representative queries against
  equivalent REST calls, recording latency, query
  count and developer effort — shows the PR review
  page materially worse over REST.
- S-255's abuse defences have landed and extend
  to query cost, so the surface is not shipped
  ahead of its defences.
- The successor roadmap revisits it: S-403 names
  the GraphQL verdict among the deferred items
  its seed reconsiders.

## What does not exist

No GraphQL endpoint, no schema, no resolver, no
table. The module `samverk/graphql_verdict.py`
inspects the live instance and reports that
absence — no contract resource, table, column or
audit event carries GraphQL — and its battery
plants a GraphQL-shaped table to prove the
inspection would catch one. A request to execute
GraphQL today is refused `graphql_deferred`.
