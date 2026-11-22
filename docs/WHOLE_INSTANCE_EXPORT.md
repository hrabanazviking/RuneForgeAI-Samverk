# Whole-instance export (S-341)

Roadmap S-341: one archive: all bare repos, LFS store,
database, and config, with a manifest and checksums
(built on S-074).

## What stands

- `samverk/whole_instance_export.py` —
  `WholeInstanceExportService.export_instance` writes one
  `samverk-instance-<unix-time>.tar.gz` plus a sidecar
  `.manifest.json`, admin-only (the S-074 gate widened to
  the instance: the archive carries every repository's
  entire content).
- Repositories ride S-074 unchanged: each repository with
  refs becomes a verified `git bundle` plus its S-074
  metadata JSON under `repos/`. Empty repositories and
  repositories missing on disk are never faked — each is
  named in the manifest's `repos_excluded` (and the full
  `excluded` list) with its reason. An instance with no
  exportable repository is refused (`nothing_to_export`):
  an archive of nothing is not a backup. An existing
  export at the destination is never overwritten silently
  (`export_exists`).
- The LFS store (S-060) does not ride git bundles, so every
  LFS object of every exported repository is copied under
  `lfs/<owner>-<repo>/<oid>` and re-hashed on the way in;
  an object whose bytes no longer hash to its oid fails
  the whole export (`lfs_corrupt`) rather than shipping
  corrupt.
- The database member (`database/samverk.db`) is a
  consistent snapshot taken through SQLite's backup API,
  never a raw copy of a live file.
- Config is exported as values, never secrets (S-002 /
  S-003): `config/config.json` carries the boot values and
  the *names* of loaded secrets (a restoring operator must
  know which secrets to re-provide — values never travel);
  `config/samverk.ini` rides when one sits in the data
  root; a configured TLS certificate rides as public
  material. The secrets file and the TLS private key are
  named in `excluded` with their reasons, never included
  and never silently dropped. The pure `is_secret_name`
  judges file names against that hold-back law.
- The manifest (`manifest.json` inside the archive, format
  `samverk-instance-export/1`) lists exactly what went in:
  every member with kind, byte count, and SHA-256, the
  included and excluded repositories, and the LFS object
  count. `verify_export` re-opens an archive and checks
  every member against the manifest — a missing, extra,
  resized, or re-hashed member is a named problem (pure
  `verify_manifest`); an unreadable archive is a failed
  verification with the reason named. The pure
  `plan_instance_export` chooses included/excluded
  repositories from plain facts.
  `render_whole_instance_export_page` states the archive's
  counts and checksum in words.

## Deliberate non-changes

No migration and no new audit event: the schema stands
at 138 and the taxonomy stands at 138. This slice reuses
the seams its predecessors built (S-074 bundles, S-060
LFS, S-002 config, S-003 secrets), on purpose. Restore is
S-342's drill, not this slice.
