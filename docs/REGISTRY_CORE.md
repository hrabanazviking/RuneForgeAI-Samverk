# Registry core — the published refusal (S-265)

Samverk has **no package registry**. The roadmap
asked for a registry core — namespaced package
publish/fetch with repo-linked permissions — if
S-264 verdicted one in. S-264 verdicted DEFER/out
(`docs/PACKAGE_VERDICT.md`,
`samverk/package_verdict.py`): no ecosystem is
hosted now, OCI containers are refused outright,
and Python stands deferred as the first
candidate. So this slice is the published refusal
the roadmap names for the verdicted-out road,
with the seam documented. The core's standing
shape lives in `samverk/registry_core.py`; this
page is the same refusal for a reader who never
opens the code.

## The namespace is a repository

A package is named whole: its ecosystem, the
owner and name of the repository it is linked
to, a package name and a version — for example
`python:volmarr/anvil/anvil-kit@1.0`. The
namespace belongs to that repository. There is
no registry-only ownership and no namespace
squatted apart from the forge's permissions.

## The four doors, and the rung each is judged at

- `publish` — requires **write** on the linked
  repository. Would fix a version's bytes and
  digest under the namespace, after quarantine
  and validation, witnessed like a release act.
  Today it refuses.
- `fetch` — requires **read** on the linked
  repository. Would serve one published version's
  bytes to a reader, counted like an asset
  download. Today it refuses.
- `list` — requires **read** on the linked
  repository. Would name a package's published
  versions, tombstones included and said so.
  Today it refuses.
- `delete` — requires **admin** on the linked
  repository, because deletion leaves a
  tombstone. Would withdraw a version leaving
  its name, version and digest on record.
  Today it refuses.

## How a request is answered

In one order, always:

1. **Shape first, storing nothing.** A shapeless
   ecosystem is `registry_request_invalid`, an
   ecosystem S-264 never assessed is
   `registry_ecosystem_unknown`, a namespace
   that is not a repository's owner/name is
   `namespace_invalid`, and a malformed package
   name or version is `package_name_invalid` /
   `package_version_invalid`.
2. **Then the linked repository's permissions**
   (S-054's law, generalised by S-190). An
   anonymous publish or delete is
   `authentication_required`. A missing
   repository — and a private repository the
   caller may not read — answers on fetch and
   list as one `package_not_found`, and on
   publish and delete as the uniform
   `repo_not_found`, so the refusal itself leaks
   nothing about what the caller may not read. A
   reader who may not write is
   `permission_denied` on publish; deletion asks
   the admin rung.
3. **Only then the verdict.** A caller who
   passes the permission door meets S-264's
   per-ecosystem answer, delegated to the
   verdict's own decision so the two slices can
   never drift: `registry_deferred` (Python,
   JavaScript), `registry_refused` (OCI
   containers), `registry_served_by_releases`
   (generic archives — publish the file as a
   release asset instead) or
   `registry_served_by_git` (Go modules — tag
   the version in its repository instead).

## The seam a future registry builds under

The seam is S-264's eight must-not-break
invariants, imported whole by the core — stated
once in `samverk/package_verdict.py`, never
forked:

- `namespace-follows-permissions` — namespace
  ownership is repository permission, judged by
  S-190.
- `versions-are-immutable` — a published
  version's bytes never change; deduplication
  never leaks a private package's existence.
- `private-is-missing-on-fetch` — private is
  indistinguishable from missing, on fetch,
  downloads and existence checks alike — and,
  by this slice, in the refusal itself.
- `digest-is-not-identity` — a digest proves
  bytes, never author identity or build
  provenance.
- `quarantine-before-visible` — no upload is
  fetchable until validation completes, under
  caps judged before the body is read.
- `deletion-leaves-a-tombstone` — deletion
  leaves name, version and digest on record,
  and registry bytes join storage accounting
  (S-268's road).
- `export-or-it-does-not-ship` — offline export
  is proven before any ecosystem is declared
  hosted.
- `publish-and-fetch-are-witnessed` — publish,
  delete and fetch are witnessed like release
  acts. This refusal writes and audits nothing,
  because no act here can succeed: there is
  nothing to witness yet, and the battery proves
  the silence by row and audit counts.

## What exists instead, and when this reopens

Distribution today is by releases and their
assets (S-257..S-263: releases, capped assets
with counted downloads, a generated sha256
checksums file, the signing seam), with CI
artifacts next (S-266/S-267); Go modules are
fetched from repository tags through the git
transports. The verdict reopens only on
S-264's recorded conditions — a named village
need release assets cannot serve, one ecosystem
considered (Python first), the trust machinery
standing (the S-305 verifier line, S-268's
storage accounting, a quarantine design), and
the successor roadmap's revisit at S-403.

## What does not exist

No package table, no registry endpoint, no
publish or fetch road. The core inspects the
live instance and reports that absence — the
verdict still defers cleanly, no table, column
or audit event carries a package registry, the
API contract still ratifies, and no contract
resource claims a package or registry road —
and its battery plants a registry-shaped table
to prove the inspection would catch one.
