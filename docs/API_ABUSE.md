# API abuse defences (S-255)

Three defences stand at the API door, beside
S-241's per-token rate buckets, in
`samverk/api_abuse.py`. They are judged where
S-238 judges every API call, against the caller
S-238's door resolved.

## Payload size caps

Every endpoint in the contract's route table is
catalogued with the size class of the body it may
carry: `none` for the bodiless methods (a GET
carries no body this door will read) and `json`
for a JSON request body, capped at the instance's
configured cap — 1 MiB by default
(`api_abuse.payload_cap_bytes`). No v1 endpoint
carries a file body: contents are read-only and
the API writes files through Git, never around
it, so one honest cap governs every body the API
accepts.

A stated size is judged before the body is read
for meaning. A size past its cap is refused
`payload_too_large` in S-240's one problem format
(status 413), is read no further, and is charged
nothing — not accounted, never admitted to a
concurrency slot. A size that is not a whole,
non-negative byte count is refused
`payload_size_invalid` (400).

## Expensive-endpoint accounting

Endpoints are priced in cost units. An ordinary
endpoint costs 1; the four expensive ones cost
10, named because of the work a call sets off:

- `search` — a fan-out over five executors.
- `repository-contents` — blob bytes read and
  carried.
- `repository-forks` — a clone.
- `pull-merge` — a Git merge.

Every admitted call is charged to its caller,
keyed exactly as S-241 keys its buckets (a
token's own ledger, an account's for a
password-Basic call, the one anonymous ledger).
The ledger answers per caller (calls, cost
units, per-endpoint split) and per endpoint
across all callers. Accounting is bookkeeping,
not a brake: it refuses nothing by itself, and
it keeps recording while the defences are
configured off, so turning a brake off never
blinds the operator watching for abuse. A call
the payload cap or the concurrency brake refused
is never in the counts.

## Per-token concurrency limits

A rate bucket prices how *often* a caller may
call; it does not price how *many* calls one
token may hold open at once. The guard admits a
call under the caller's own ceilings — 8 in
flight per token by default
(`api_abuse.max_concurrent_per_token`), 2 for an
expensive endpoint
(`api_abuse.expensive_max_concurrent_per_token`)
— and answers with a lease the caller releases
when the call ends (a context manager, so an
exception still releases). A password call is
limited by its account and the anonymous caller
by the one shared anonymous ceiling.

Past a ceiling the call is refused
`concurrency_limit_exceeded` (429) carrying its
judgement. The refusal carries no `Retry-After`:
a slot frees when a held call ends, not when a
clock says so, and no honest second can be
named. A refused call holds no slot and is
accounted nothing. Releasing a lease twice, or a
lease the guard never issued, is refused
`lease_invalid` — a slot is returned once, by
its holder, or the counts would lie.

## Configuration and witnessing

The defences are instance-configurable in the
settings table under `api_abuse.*` keys: whether
they are on, the payload cap, and the two
concurrency ceilings. A stored value that cannot
be read as its number is refused
`abuse_settings_invalid` rather than silently
replaced. Saving the settings is audited
`admin.settings.change` with the keys named —
the only witnessed act here. Judging, accounting
and holding a slot write no row and audit
nothing: the ledger and the slots are memory,
thread-safe, as S-241's buckets are. No
migration (schema stays 99); no taxonomy event
(131 stand: 33 auth / 85 repo / 13 admin).

The contract's `rate-limits` rule in
`samverk/api_contract.py` (and
docs/API_CONTRACT.md) records these defences as
landed beside S-241's, and
`audit_api_abuse` checks them against the live
contract: it still ratifies, every route-table
resource is catalogued and priced, and every
price is its tier's.
