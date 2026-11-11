# Artifact expiry (S-267)

S-266 stored every artifact's retention policy as data -- the
chosen window (`retention_days`: 7, 30, 90, 180 or 365 days, or 0
for keep forever) and its computed `expires_at` stamp on the
`ci_artifacts` row -- and judged expiry at read time: listings
mark an expired artifact, and its download refuses
`artifact_expired`, uncounted. This slice is the enforcement:
`samverk/artifact_expiry.py` (`ArtifactExpiryJob`), an off-path
job an operator or a scheduler runs, e.g.
`python3 -m samverk.artifact_expiry <db-path> <data-root>`.
No migration (schema 105 stands); no new taxonomy event
(133 stand: 33 auth / 87 repo / 13 admin).

## The sweep

The stamp is the whole law. The job sweeps exactly the rows
S-266's own pure `is_expired` judges expired at the sweep's
clock -- at the stamp itself the artifact is already expired;
one second short, it is not swept; keep-forever rows (NULL
`expires_at`) are never swept. There is no second judgement.

A swept artifact vanishes from UI and disk together: its row
is deleted and its content-addressed bytes are deleted in the
same sweep, so afterwards listings omit it and `get` /
download answer `artifact_not_found`, exactly as for an
artifact that never stood. Bytes are shared within a
repository (S-266's delete law): a digest's file is removed
only when no standing row in that repository still names it,
so sweeping an expired copy never breaks a live artifact
holding the same bytes. Bytes already missing are counted
honestly in the run's account (`bytes_missing`); the row
still goes, because the window has closed either way.

The sweep is idempotent (a re-run removes nothing and says
so), appends no audit entry, and takes no taxonomy verb:
expiry is the retention policy executing on schedule, not a
poster's act. Each run answers its honest account --
`ExpiryRun`: expired, rows removed, byte files removed,
kept-shared, already-missing -- in plain words
(`sweep_words` / `run.words`).

## S-071 reconciles

The consistency checker (`samverk/consistency.py`) now
reconciles the artifact store beside repositories and LFS
objects, reporting drift and never fixing it, as it always
has:

- `artifact_expired_standing` -- a row whose stamp the
  checker's clock has reached still stands. This job's
  sweep is the deliberate act that clears exactly these.
- `artifact_bytes_missing` -- a standing row whose bytes
  are not on disk at their content address.
- `artifact_bytes_orphan` -- a byte file under
  `ci-artifacts/<repo>/` named by no standing row. The
  sweep does not delete orphans it did not write; the
  checker keeps reporting them for an operator's hand.

The report counts the rows it reconciled as
`artifacts_checked`.
