# API versioning policy (S-254)

Samverk's API stands at **v1**, served under
`/api/v1`, and this page is the policy that governs
how it may change: what may change within v1, how
a v2 would be introduced, and how deprecation is
announced in headers. The same policy is data in
`samverk/api_versioning.py` and is recorded in the
REST contract itself (`samverk/api_contract.py`,
rule `versioned-base`; `docs/API_CONTRACT.md`), so
a builder meets it in the contract it governs.

## Within v1: additive only

A client written against v1 keeps working under
v1. Seven kinds of change are allowed inside v1
(`allowed-in-v1`); eight are breaking and require
a v2 (`requires-v2`). The classification is the
policy's centre — a change is judged by its kind
before it is made, and an unclassified kind is
never waved through as additive.

Allowed inside v1:

- `add-endpoint` — a new resource, or a new method
  on an existing resource. Existing paths, methods
  and shapes are untouched.
- `add-response-field` — a representation gains a
  field; documented fields keep their names, types
  and meanings.
- `add-optional-request-field` — a request gains
  an optional field whose absence means exactly
  what the old request meant.
- `add-optional-header` — a request or response
  gains a header no client must send or read (the
  deprecation headers below arrive this way).
- `add-refusal-for-new-case` — a new error reason,
  registered in S-240's registry, for a case the
  old contract could not reach. Existing reasons
  keep their titles, statuses and meanings.
- `widen-accepted-input` — an endpoint accepts
  values it previously refused, while every
  previously accepted value keeps its meaning.
- `raise-a-limit` — a cap goes up (page size,
  payload, rate bucket). Clients written against
  the lower cap are answered as before.

Breaking — these require a v2:

- `remove-endpoint` — a resource or method stops
  answering.
- `remove-or-rename-field` — a documented field
  disappears, or the same fact moves to a new
  name (a rename is a removal to every client).
- `change-field-meaning-or-type` — a field keeps
  its name but its type or meaning changes: the
  quietest break, and breaking however small.
- `require-previously-optional` — an optional
  field or header becomes required, or a default
  is withdrawn. Requests valid under v1 stay
  valid under v1.
- `change-existing-refusal` — an existing reason
  changes its status, meaning or circumstances,
  or the one problem format changes its fields.
- `change-pagination-or-ordering` — cursor
  semantics (S-239), the stable ordering, or the
  list envelope's keys change their meaning.
- `lower-a-limit` — a cap comes down; requests
  the old contract accepted are refused or
  truncated.
- `change-permission-semantics` — the permission
  judgement behind a resource changes, in either
  direction: widening is breaking too, because a
  client built on the old boundary is silently
  wrong under the new one.

## How a v2 would be introduced

- A v2 is introduced only to carry breaking
  changes, each named in the v2 contract with the
  v1 behaviour it replaces. Additive work lands
  in v1 and never justifies a new version.
- The v2 stands under its own base, `/api/v2`, as
  a whole new contract in the S-237 shape —
  resources, verbs, shapes and rules ratified
  before its code, in its own contract document.
- Introducing v2 changes nothing under `/api/v1`:
  no v1 path is mutated to v2 behaviour and no
  v1 request is redirected to v2. A client moves
  by changing the base it speaks to, or it does
  not move.
- Both versions are served concurrently, and v1
  keeps every v1 promise for at least 365 days
  after the v2 lands (`MIN_V1_OVERLAP_DAYS`).
- The v2 ships with a migration guide mapping
  every v1 resource, field and refusal it
  changes: the v1 shape, the v2 shape, and the
  mechanical move between them.
- Only once the v2 stands may v1 be deprecated,
  and then only by the header law below, with the
  contract documents updated in the same slice
  that starts the clock. v1 stops answering only
  after its sunset date has passed.

## Deprecation notices, in headers

A deprecated surface — a resource, a field, or a
whole version — answers every response with three
headers until it stops answering:

- `deprecation-date` — the `Deprecation` header:
  an HTTP-date (RFC 9745), the date the surface
  was deprecated, in GMT.
- `sunset-date` — the `Sunset` header: an
  HTTP-date (RFC 8594), the date the surface
  stops answering. It stands at least 180 days
  after the Deprecation date
  (`MIN_DEPRECATION_NOTICE_DAYS`); a shorter
  runway is refused by the policy's validator,
  in words, before any header is emitted.
- `deprecation-link` — the `Link` header: one
  link-value in the form `<URL>; rel="deprecation"`
  naming the notice a person reads — the surface's
  replacement and migration road, never a generic
  homepage.

Deprecation changes no behaviour by itself: a
deprecated endpoint keeps its shapes, permissions
and refusals until its sunset. There is no silent
deprecation and no deprecation without a sunset:
announcing an end is always paired with the date
of the end and the road away from it.

## What does not exist

No v2: no `/api/v2` base, no v2 resource, no
deprecation in force. The module
`samverk/api_versioning.py` checks the policy
against the live contract — it still ratifies,
the served base is `/api/v1`, and no resource
claims a future version's base — and its battery
plants a v2-claiming resource to prove the check
would catch one. The policy is a pure read: no
migration (schema 99 stands) and no audit event
of its own (131 stand).
