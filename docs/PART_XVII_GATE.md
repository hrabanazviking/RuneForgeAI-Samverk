# Part XVII Gate Record — S-344

Gate slice: **S-344 — Part XVII gate — backup battery: mirror
freshness, restore proof, and the census fixture reconciled;
counted green.**

Battery: `tests/test_part_xvii_gate.py`, counted with
`python3 -m unittest tests.test_part_xvii_gate`.
Gate battery: **16 tests, OK** (log:
`hidden_files/s344-battery.log`). Neighbour suites (the twelve
Part XVII seam modules the gate exercises): **Ran 179 tests,
171 passed, 8 failures** (log: `hidden_files/s344-neighbours.log`).
Every one of the 8 failures is exactly `AssertionError: 139 != 138`
in a schema-pin test of a file this slice did not touch
(test_census_fixture, test_first_pass_mirroring,
test_private_originals, test_sync_status, test_sync_scheduler,
test_mirror_write_law, test_push_mirrors, test_pull_mirrors) --
the known standing pin bug left by S-338's migration 139, which
the coordinator has already swept on main (356 replacements,
taxonomy pins untouched). Per the coordinator's order the pins
were **not** swept in this slice; no neighbour failure is a
behaviour failure.

## What was counted

- **Pins** — schema 139, taxonomy 138 audit events
  (33 auth / 92 repo / 13 admin), claims register standing at
  35 rows (C-01..C-35) untouched, and the Part XVII tables
  standing (`repo_mirrors`, `repo_push_mirrors`,
  `census_fixture_entries`, `first_pass_mirror_runs`,
  `metadata_imports`, `metadata_import_runs`). The gate claims
  **no migration and no new taxonomy event**.
- **Census fixture reconciled (S-335)** — the full fixture
  imports as 54 defined mirror definitions, 17 held uncertain,
  84 excluded; every defined entry carries a pull-mirror
  definition that is not yet ready (a definition, not a sync);
  held entries have no repository and no mirror; private
  originals land private, public originals public; re-import
  is idempotent (54 already defined / 17 already held); the
  owner's word releases exactly one held entry.
- **Mirror freshness (S-330..S-338 seams)** —
  - S-336 first pass: proof repo verified ref-for-ref before
    the batch runs; batch verified ref-for-ref; mirror refs
    equal source refs exactly (branches and tags).
  - Drift: after the source advances, re-verification reports
    the diverged ref and refuses to verify; a re-sync restores
    freshness and verification passes again.
  - A failed proof blocks the batch: the batch repo is never
    synced and never reads ready.
  - S-331 scheduler + S-330 credential road: manual sync-now
    brings a mirror fresh (3 objects moved, last success
    recorded); S-332 sync status reads `never_synced` before,
    `healthy` after success, and `failed` — never healthy,
    with a plain-words failure reason and the last success
    unmoved — after the source breaks.
  - S-334 mirror write law: a mirror is refused local writes
    with reason `mirror_read_only`; a plain repository is
    allowed.
  - S-333 push mirrors: a repository pushed onward to a bare
    target lands ref-for-ref and the target reads healthy
    only after the push.
  - S-337 private originals: refused with no credential and
    refused under a write scope (nothing synced either time);
    verified behind a read-scoped credential, landing
    `private` always; the token never stands in a recorded
    detail.
  - S-338 metadata import: refused before any fetch without
    a credential; with one, 1 label, 1 milestone, 1 issue and
    1 release land marked imported with source links, the
    pull-request-shaped item is skipped as a pull request,
    and a second import lands nothing twice.
- **Restore proof (S-074 seams)** — a verified mirror is
  exported through S-074's primitive: bundle + metadata JSON
  agree (format, full name, refs equal to the source refs,
  SHA-256 and byte count recomputed from the bundle file),
  and a stock `git clone --bare` from the bundle restores
  every ref exactly. The export gate itself is counted:
  non-owner refused (`permission_denied`), empty repository
  refused by name (`repo_empty`), and an existing export is
  never overwritten silently (`export_exists`).

## Honest remainder

This gate proves restore over the seams that exist on its
base — S-074's single-repository export/restore primitive.
**S-341 (whole-instance export) and S-342 (restore drill)
are being built in parallel by other teams and are NOT on
this gate's base**; no whole-instance restore is claimed
here. S-339 (wiki mirror), S-340 (LFS mirror) and S-343
(drift census) likewise land after this gate in banking
order, are not on this base, and are named here as the
gate's remainder rather than covered by pretence. When
S-339..S-343 have banked, a future pass can extend this
battery over them.

No Docker was used. README.md was not touched.
