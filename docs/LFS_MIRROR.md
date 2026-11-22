# LFS mirror (S-340)

Roadmap S-340: LFS objects (S-060) sync with their
repos; a mirror without its LFS objects reports itself
incomplete.

## What stands

- `samverk/lfs_mirror.py` — `LFSMirrorService` computes
  and syncs one mirror's LFS completeness.
  `completeness_for` reads every LFS pointer out of the
  repo's own reachable blobs (S-060 `parse_pointer`) and
  judges them against the objects actually present in
  its S-060 store, each re-verified by oid and size.
  `sync_lfs` copies each missing or corrupt object from
  a local source's S-060 store through `LFSStore.put`,
  which verifies integrity by oid on write — bytes that
  do not hash to the pointer's oid store nothing.
- Completeness is computed, never asserted (pure
  `judge_completeness` / `plan_lfs_sync`): pointers
  dedupe by oid; missing and corrupt objects are named
  by oid and counted in bytes; a repo with no LFS
  pointers needs no objects and is not incomplete.
- Incomplete never looks healthy: a mirror missing or
  holding corrupt LFS objects states `incomplete` in
  plain words and `healthy == False`, on its page
  (`render_lfs_mirror_page`, never colour-only) and in
  `honest_status`, where the S-332 sync verdict and
  this completeness verdict must both be good before
  the mirror may call itself healthy. A green git sync
  cannot borrow health over missing LFS bytes.
- Honest remainders, stated not hidden: an object the
  source itself does not hold stays missing and is
  named in the run's detail; a remote-URL source's LFS
  objects cannot be read through the local-store seam,
  so its sync is recorded failed in plain words and the
  mirror stays incomplete until its objects arrive by
  a road that can carry them.
- Every sync outcome is recorded in the standing run
  log (`first_pass_mirror_runs`, phase `lfs`; matched =
  objects present, missing = objects missing, diverged
  = objects corrupt).

## Deliberate non-changes

No migration and no new audit event: the schema
stands at 138 and the taxonomy stands at 138. This
slice reuses the seams its predecessors built (S-060
LFS store, S-070 mirror record, S-332 sync status,
S-336 run log), on purpose.
