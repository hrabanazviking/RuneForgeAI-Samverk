# Package registry — deferred (S-264)

Samverk hosts no package registry, for any
ecosystem, and this page is the recorded verdict
that says why, what would have to change, and
what a future registry must not break. It
concludes the study in research file 26
(`research/26-packages-and-registry.md`), which
made village need the decider and warned that a
smaller, proven registry beats a nominal menu of
insecure formats.

## The verdict

**Deferred.** No ecosystem is hosted now; one
ecosystem (OCI containers) is **refused**
outright. S-265 therefore takes its
verdicted-out road: the published refusal with
the seam documented — the seam being the
invariants below.

## Why deferred — the reasons

- `no-measured-village-need` — No village need
  has been measured. Samverk itself is
  stdlib-first with zero admitted dependencies
  (S-017's register is empty), no village project
  publishes a private package or installs from a
  private index, and research 26's method ranks
  ecosystems by actual project need — a ranking
  with no measured need at its top hosts nothing
  yet.
- `releases-already-serve-distribution` — The
  distribution the village demonstrably uses —
  a versioned file whose bytes a reader can
  check — already stands banked and repo-linked:
  releases (S-257), assets under caps with
  counted downloads (S-259), a generated sha256
  checksums file (S-260) and the signing seam
  (S-263), with CI artifacts next (S-266/S-267).
- `each-ecosystem-is-its-own-surface` — A Python
  wheel, an OCI manifest and an npm package
  carry different metadata, signing, upload and
  dependency semantics; each hosted ecosystem is
  a permanent protocol surface with its own
  threat list (namespace confusion, malicious
  version overwrite, enormous metadata,
  compression bombs, cross-tenant caches).
- `trust-machinery-not-yet-standing` — Research
  26 requires namespace ownership, immutable
  digests, authenticated publishing, quotas,
  tombstones, download authorization,
  content-addressed storage and quarantine
  first. Storage accounting lands at S-268 and
  the signing seam has no verifier yet; a digest
  is not an author identity or build provenance.
- `village-scale-simplicity` — A registry is the
  storage- and bandwidth-heaviest face a forge
  can grow, kept forever by design on village
  hardware. Worth carrying the day a village
  project needs it; speculation until then.

## The ecosystems, judged one by one

- **Python packages** (`python`) —
  deferred-first-candidate. Research 26 ranks it
  first and the village is a Python village, but
  its measured need today is zero: Samverk is
  stdlib-first with no admitted dependencies.
  Release assets carry the village's Python work
  today. This is the first ecosystem a reopened
  verdict considers.
- **Container-less archives** (`generic-archives`)
  — served-by-releases. Versioned archives are
  exactly what releases and their assets already
  host, repo-linked, with checksums and the
  signing seam; a generic store would rebuild
  that road, not open a new one.
- **JavaScript packages** (`javascript`) —
  deferred. No village project is a JavaScript
  package and the forge's web surface is
  server-rendered; research 26 names JavaScript
  only as a candidate to rank by need, and the
  ranking finds no need to rank.
- **Container images** (`oci-containers`) —
  refused. The village runs no Docker, ever —
  Volmarr's standing rule is native installs
  only on all of his machines — so there is no
  container workload for an OCI registry to
  serve, and none coming by that law.
- **Go modules** (`go-modules`) — served-by-git.
  Go modules are fetched from version-control
  tags by design; a tag on a readable Samverk
  repository already is a module version, judged
  by the repository's own permissions.

## What a future registry must not break

These invariants are recorded here and in the
module (`samverk/package_verdict.py`), as the
seam S-265 documents and the law any future
registry core builds under:

- `namespace-follows-permissions` — a namespace
  belongs to its linked repository or
  organization; publishing is judged by S-190
  exactly as the repository's acts are.
- `versions-are-immutable` — a published
  version's bytes never change; replacement is
  refused; byte-identical deduplication never
  leaks a private package's existence.
- `private-is-missing-on-fetch` — a fetch naming
  a private or unreadable package answers
  exactly as a fetch naming nothing, on
  downloads and existence checks alike.
- `digest-is-not-identity` — a digest proves
  bytes, never author identity or build
  provenance; trust language follows S-263's and
  S-305's honest words.
- `quarantine-before-visible` — no upload is
  fetchable until size, checksum and manifest
  validation complete, under caps judged before
  the body is read for meaning.
- `deletion-leaves-a-tombstone` — a deleted
  name, version and digest stay on record, the
  name cannot be silently reused for different
  bytes, and registry bytes join storage
  accounting and quotas (S-268's road).
- `export-or-it-does-not-ship` — no ecosystem is
  declared hosted until whole versions export
  and import with manifests and an example
  installs offline from the export (research
  26's acceptance).
- `publish-and-fetch-are-witnessed` — publish,
  delete and fetch are witnessed in the audit
  log like S-257's release acts, through one
  store, witnessed once.

## When this verdict reopens

- A village project names a concrete
  private-package need release assets cannot
  serve — for example a CI install step that
  must resolve a private Python package by
  name — with its own workload as evidence.
- The reopened verdict considers one ecosystem
  only, Python first, proven small and secure
  before any second ecosystem is discussed.
- The trust machinery stands: the signing
  seam's verifier (the S-305 line), S-268's
  storage accounting, and a
  quarantine-and-validation design judged
  against research 26's threat list.
- The successor roadmap revisits it: S-403
  names refused and deferred items among what
  its seed reconsiders.

## What does not exist

No registry endpoint, no package table, no
publish or fetch road. The module
`samverk/package_verdict.py` inspects the live
instance and reports that absence — no table,
column or audit event carries a package
registry — and its battery plants a
registry-shaped table to prove the inspection
would catch one. A request to use a registry
today is answered per ecosystem:
`registry_deferred` (Python, JavaScript),
`registry_refused` (OCI containers),
`registry_served_by_releases` (generic
archives) or `registry_served_by_git` (Go
modules).
