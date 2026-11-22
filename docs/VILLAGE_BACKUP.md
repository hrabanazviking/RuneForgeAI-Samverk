# Village backup unity (S-371)

Samtal's standing backup bundle grows a Samverk section, so the
village's talk and work are kept in one keeping.
`VillageBackupService.build_bundle` writes Samtal's sections
(named byte/text payloads handed over by Samtal's side) beside
the real S-341 whole-instance export — produced at bundle time
by `WholeInstanceExportService`, never re-implemented — and
binds all of it in one manifest (`village-bundle.json`, format
`samverk-village-bundle/1`) recording a sha256 and byte count
for every Samtal section and the export archive's own name,
sha256, byte count and repo counts. `verify_bundle` re-checks
every recorded hash against the files on disk; a tampered or
incomplete bundle is named, never trusted, and the Samverk
section itself still verifies under S-341's `verify_export`.

The Samverk section inherits S-341's guards whole: admin-only
(`permission_denied`), nothing-exportable refuses
(`nothing_to_export`). Section names that could escape the
bundle directory refuse (`section_name_invalid`; the name
`samverk` is reserved for the export section), and non-byte
payloads refuse (`section_payload_invalid`). The bundle is the
seam's keeping: seam disabled refuses (`seam_disabled`) and
each application keeps its own backup as before. No migration
and no new taxonomy event.
