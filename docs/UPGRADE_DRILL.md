# Upgrade drill (S-396)

Roadmap S-396: an RC instance with real-shaped data
upgraded per S-357 and verified; the drill log is a
release artifact.

The drill (`samverk/upgrade_drill.py`, run by
`tools/run_upgrade_drill.py`) exercises the S-357
upgrade procedure — export, verify export, stop,
migrate, start, verify counts, with rollback to the
export on failure — against an instance shaped like
a real one, not the minimal scratch instance of the
S-357 battery: three users, four repositories under
different owners with mixed visibility, chained real
git history with a side branch and a tag on every
repository, and LFS objects in two repositories.

Two legs run, each on a fresh RC instance:

- **Leg A (upgrade)** applies a stand-in next
  migration (pretend schema 141, drill instance only;
  no such migration ships) through S-357, then
  verifies independently of the procedure's own count
  check: every ref resolves to its pre-upgrade commit,
  every LFS payload is byte-identical, counts match
  the RC shape, and the migration's rehearsal row is
  present at schema 141.
- **Leg B (rollback)** applies a migration that
  commits a destructive change and throws mid-way.
  S-357 must roll the instance back to the export:
  schema back at 140, the deleted user restored, the
  half-migrated table gone, refs and LFS identical.

The drill passes only when both legs pass with no
named problem. The log of the verification run is
the release artifact: `docs/upgrade-drill-s396.md`
(markdown) with its raw record produced alongside it
by the runner. A leg that cannot honestly run is
recorded as a named problem and the verdict is
NOT PASSED — never dressed up as a pass.

No migration of this slice's own and no new taxonomy
event: schema stands at 140, taxonomy stands at 142.
