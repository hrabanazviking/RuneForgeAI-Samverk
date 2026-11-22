# Restore drill (S-342)

Roadmap S-342: export restored onto a scratch instance;
repos clone, users sign in, counts match the manifest;
the drill is a test, not a hope.

## What stands

- `samverk/restore_drill.py` — `RestoreDrill.run(archive,
  scratch_root, username, password)` restores one S-341
  whole-instance export onto a fresh scratch instance and
  proves the restore, end to end, against real seams.
- The archive is re-verified first with S-341's
  `verify_export`; an archive that does not verify restores
  nothing (`export_unverified`). The scratch destination
  must be fresh: a non-empty destination is refused
  (`scratch_not_empty`) — a drill never restores over a
  live instance.
- The database snapshot lands in the scratch data root and
  is opened there; its schema must equal the manifest's
  `schema_version`. Every included repository is rebuilt
  from its S-074 bundle through the S-014 local-clone seam
  (`run_git_clone_local`), and its LFS objects are
  re-stored through the S-060 `LFSStore`, which re-hashes
  every object to its oid on the way in.

## What the drill proves

- **Repos clone.** Every restored repository is cloned
  again from the restored instance, and the clone's
  default-branch tip must equal the tip recorded in the
  S-074 metadata inside the archive. A mismatch is named
  per repository.
- **Users sign in.** A restored user signs in through the
  real S-027 `LoginService` on the restored database, and
  the session must resolve back to that same user. A wrong
  password is a named failure, and a drill run without
  credentials reports sign-in as *not attempted* — never
  as passed.
- **Counts match the manifest exactly.** Repositories
  restored, LFS objects restored, repository rows in the
  restored database (included + excluded), and archive
  members (manifest entries plus the manifest itself) are
  judged against the manifest by the pure
  `compare_drill_counts`. Users are judged against the
  count taken from the archive's own database snapshot —
  the manifest carries no user count, so the snapshot, a
  manifest-verified member, is the honest source. Every
  mismatch is reported by name; nothing is rounded away.
  Repositories S-341 excluded by name (empty, missing on
  disk) stay excluded: they hold rows in the restored
  database but no bundle, and the drill accounts for them
  as rows, never as restored repositories.

## The honest remainder: secrets

S-341 deliberately excludes secret values and the TLS
private key, so a restored instance cannot invent them.
The drill report names each one as an operator step,
judged purely by `operator_steps` from the manifest's
exclusions and the exported config's secret *names*:
re-provide each named secret, re-provide the secrets file,
re-provision the TLS private key file. Names only — never
values, never silently invented. Until an operator does
those steps, the restored instance runs without its
secrets and without TLS, and the drill says so.

## Pins

No migration and no new taxonomy event: schema stands at
139, taxonomy stands at 138.
