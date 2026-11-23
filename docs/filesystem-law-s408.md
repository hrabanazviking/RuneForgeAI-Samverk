# S-408 — Filesystem law (slice record)

- Slice: S-408, parent 080cf8e (401/416 banked). HELD ahead-work:
  banking is blocked in roadmap order on founder-only S-402;
  this commit is built + committed in team-07 only, unpushed.
- Delivered: `samverk/filesystem_law.py` (case-fold identity,
  deterministic `case_collision` refusal, filesystem probe,
  directory audit, honest insensitive simulation),
  `tests/test_filesystem_law.py`, `tools/run_filesystem_law.py`,
  `docs/FILESYSTEM_LAW.md`.
- Host kind probed case-sensitive; insensitive kind simulated —
  a real insensitive-FS run is NOT PROVEN (see FILESYSTEM_LAW.md).
