# Upgrades (S-357)

Roadmap S-357: documented procedure: export (S-341) ->
stop -> migrate -> start -> verify counts; a failed
migration rolls back to the export, rehearsed in the
drill.

This is the one documented upgrade procedure. It is
implemented as code in `samverk/upgrades.py`
(`UpgradeProcedure.run` + `render_upgrade_report`), so
every numbered step below is a step the code runs, in
this order. The battery pins the document's steps to
the code's steps (`STEP_IDS`), in order, so the guide
cannot drift from the procedure. Steps that belong to
the operator are written as operator steps, plainly:
this procedure stops and starts no real service -- in
code, stop and start are judged preconditions the
operator confirms; in a real upgrade, the operator
does them by their own road between the steps.

## Run it

```sh
python3 - <<'EOF'
from pathlib import Path
from samverk.upgrades import UpgradeProcedure, render_upgrade_report
# conn / accounts / repositories open on the instance,
# which the operator has exported a destination for:
proc = UpgradeProcedure(conn, data_root, accounts, repositories)
report = proc.run(admin_id, Path('/exports/outside/the/data/root'),
                  stopped=True, started=True,
                  signin_username='admin-name',
                  signin_password='the-admin-password')
print(render_upgrade_report(report))
raise SystemExit(0 if report.ok else 1)
EOF
```

The export destination must stand **outside** the data
root: a rollback clears the data root, and an archive
inside it would be destroyed by its own rollback. The
procedure refuses such a destination
(`export_inside_data_root`) before changing anything.
The sign-in credentials are the rollback's proof: if a
rollback happens, the S-342 drill restores the export
and proves a restored user can sign in with them.

## The six steps

### 1. export -- Export the whole instance (S-341)
A whole-instance export of the instance as it stands,
before anything changes: every exportable repository
as a verified bundle, the LFS store, a consistent
database snapshot, and config values (never secret
values), with a manifest and checksums.
Failure mode: export_failed: the export is refused (not an admin, no exportable repository, an LFS object that no longer hashes to its oid, or a destination that already holds an export) -- there is no rollback point, so the upgrade must not begin.
Remedy: fix the named cause and re-run from this step;
never start an upgrade without a completed export.

### 2. verify_export -- Verify the export against its manifest
The archive is re-opened and every member is checked
against the manifest (S-341 `verify_export`): present,
right size, right checksum, nothing unlisted.
Failure mode: export_unverified: a member is missing, resized, or hashes differently than the manifest -- the archive could not restore the instance, so it cannot be the rollback point.
Remedy: discard the bad archive, find why it is
corrupt, take a fresh export, and verify it.

### 3. stop -- Stop the instance (operator step, judged precondition)
The operator stops the instance by their own road and
confirms it (`stopped=True`). The code judges the
confirmation and touches no service.
Failure mode: not_stopped: the operator has not confirmed the instance is stopped -- migrating a live instance could race its writes, so the procedure aborts before changing anything.
Remedy: stop the instance, confirm it, and re-run.
Nothing has changed, so no rollback is needed; the
export is kept.

### 4. migrate -- Apply pending migrations
Pending migrations are applied (`db.migrate`; each
migration runs in its own transaction). In the
dress rehearsal (the battery), a stand-in next
migration is applied to a scratch instance only -- no
stand-in migration ships.
Failure mode: migration_failed: a migration raised mid-way -- the database may hold a half-applied change, so the procedure rolls back to the export and reports the failure in plain words.
Remedy: read the named error, fix the migration or
the data it tripped on, and start the whole procedure
again from a fresh export; never hand-finish a half
migration.

### 5. start -- Start the instance (operator step, judged precondition)
The operator starts the instance by their own road
and confirms it (`started=True`). The code judges the
confirmation and touches no service.
Failure mode: not_started: the operator has not confirmed the instance started again after migration -- counts taken against a stopped instance would prove nothing, so the procedure rolls back.
Remedy: if the instance will not start, the rollback
has already restored the pre-upgrade instance; start
that and read its logs.

### 6. verify_counts -- Verify counts against the export manifest
Users, repository rows, repositories on disk, and LFS
objects after migration are judged against the export
manifest by the pure `compare_upgrade_counts` (users
against the count taken at export time; the schema
against the version the migration step reported).
Every mismatch is named.
Failure mode: counts_mismatch: the counts differ from the export manifest -- the migration changed content it should not have, so the procedure rolls back.
Remedy: read the named mismatches -- they are the
migration's unintended effects. Fix the migration
and start again from a fresh export.

## Rollback, in plain words

Any failure at migrate, start, or verify_counts rolls
the instance back to the export: the data root is
cleared and the archive is restored onto it through
the S-342 restore drill, which re-verifies the
archive, restores the database snapshot, rebuilds
repositories from their bundles, re-stores LFS
objects, and proves a restored user can sign in. The
report then says the upgrade failed and the instance
was rolled back -- it stands exactly as it stood
before the upgrade, not half-migrated, and it is
never claimed as upgraded. The drill also names the
operator steps a restored instance needs (re-provide
the secrets and the TLS private key S-341 never
exports). If the rollback itself fails, the report
names that too, with the drill's problems, and the
export archive is kept: it is the operator's road
back. A failure before migrate (export, verify, or
the stop confirmation) changed nothing, so there is
nothing to roll back and the report says the upgrade
did not proceed.

## The rehearsal

The battery (`tests/test_upgrades.py`) is the drill:
it builds a real scratch instance, exports it, and
runs the whole procedure with a rehearsed stand-in
next migration applied to the scratch database only,
proving counts verify against the manifest. It then
rehearses the failure: a migration that commits a
destructive change and throws mid-way leaves the
instance restored from the export -- counts and
content equal to the pre-upgrade state, the failure
reported in plain words, never a half-migrated
instance claimed as upgraded.

## Pins

No migration of this slice's own and no new taxonomy
event: schema stands at 139, taxonomy stands at 138.
