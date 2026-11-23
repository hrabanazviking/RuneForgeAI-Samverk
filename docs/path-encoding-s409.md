# S-409 — Path and encoding discipline (slice record)

- Slice: S-409, parent 080cf8e (401/416 banked). HELD ahead-work:
  banking is blocked in roadmap order on founder-only S-402;
  this commit is built + committed in team-08 only, unpushed.
- Delivered: `samverk/path_encoding.py` (canonical form — UTF-8,
  NFC, LF, forward slash — with `canonical_text` / `canonical_path`
  / `canonical_bytes` normalisers, `check_stored_path` /
  `check_wire_bytes` check seams, `stored_form` host-path seam,
  `write_canonical_text`, and the byte-level `audit_source_tree`),
  `tests/test_path_encoding.py`, `tools/run_path_encoding.py`,
  `docs/PATH_ENCODING.md`.
- Audit headline: DB path columns were canonical only by
  courtesy of git's output — no seam enforced the form, and NFC
  normalisation existed nowhere in the tree. Both are law now;
  call-site migration and the `write_text` newline remainder are
  registered plainly in PATH_ENCODING.md, not claimed done.
- No Windows run is claimed; the separator law is proven on
  backslash inputs by construction.
