# Path and Encoding Discipline (S-409)

Roadmap: *stored data (refs, paths in the DB, config) uses one
canonical form; no OS-specific separator or line ending ever
leaks into stored state or the wire.*

Module: `samverk/path_encoding.py` · Battery:
`tests/test_path_encoding.py` · Runner: `tools/run_path_encoding.py`

## The canonical form

- **Encoding:** UTF-8, strict — no BOM, no lone surrogates, no NUL.
- **Unicode:** NFC. Decomposed text is a different byte string;
  stored state must not depend on which OS produced it.
- **Line endings:** LF only. CRLF / CR are input dirt, normalised
  at the seam, never a stored form.
- **Paths:** forward slash `/` on every OS; relative; no drive
  form; no empty, `.` or `..` components; no trailing slash; no
  component ending in a dot or space (Windows strips those,
  aliasing two stored paths to one file — S-013's law, per
  component).

## The law

1. **One seam.** Host paths become stored paths only through
   `stored_form()` (posix rendering, never `str(path)` — that is
   the backslash leak on Windows). Stored text and wire bytes are
   produced via `canonical_text()` / `canonical_bytes()`; text
   files are written via `write_canonical_text()`, which pins
   UTF-8 and `newline="\n"` instead of trusting platform default
   newline translation.
2. **Refuse, never guess.** Un-canonicalisable values (absolute,
   drive, `..`, control characters, invalid UTF-8) are refused
   with stable `reason` codes (`PathEncodingError`, the S-013 /
   S-408 convention). Merely un-normalised values are normalised
   by the `canonical_*` functions or refused as `not_canonical`
   by the `check_*` functions — the caller chooses explicitly.
3. **Audit, don't assume.** `audit_source_tree()` reads real
   bytes and names any `.py` file carrying CR bytes, invalid
   UTF-8, or non-NFC text.

## Audit of the seams that existed before S-409 (read from the tree)

- **Refs (S-052/S-053):** ref names are validated ASCII with `/`
  separators by `refs.py` before reaching git — canonical by
  construction.
- **DB path columns** (`path` / `file_path TEXT` in `db.py`):
  values arrive from git plumbing output, which is `/`-separated
  UTF-8 on every OS — canonical at the source. BUT no seam
  enforced it: nothing rejected a backslash, a CRLF, or a
  decomposed value if one ever arrived from a non-git source.
  That missing enforcement is the gap this slice closes in law;
  see remainders for call-site status.
- **Archive member names** (`whole_instance_export.py`,
  `release_packaging.py`): built as forward-slash f-strings
  (`config/config.json`, `lfs/{stem}/{oid}`) — canonical by
  construction, verified by reading the code.
- **Filesystem walks** (`consistency.py`, `repo_size.py`): use
  `Path.parts` tuples, never string joins — no separator leak.
- **Unicode normalisation:** `unicodedata.normalize` appeared
  NOWHERE in the tree before this slice. NFC is a new law here,
  not a discovered convention.
- **Display-only `str(Path)` sites** (`configuration.py`
  `ConfigCheck.file_path`, `wiki_transports.py` `wiki_path`,
  `consistency.py` drift messages): host-local paths rendered
  for a human on the same host. Not stored state, not wire —
  named here as out of the law's scope, honestly.

## What is proven / NOT PROVEN

- PROVEN on this host (Linux): the full battery — canonical
  text/path/bytes law, every refusal reason, real on-disk LF
  writes, the audit catching planted CRLF / invalid-UTF-8 /
  non-NFC files, and the real package tree audit: 368 `.py`
  files scanned, zero CR bytes, zero invalid UTF-8, zero
  non-NFC (measured at build time; the battery re-asserts it).
- PROVEN by construction: the law is pure string/byte logic;
  backslash inputs are exercised directly, so the Windows
  separator behaviour is proven without a Windows machine.
- NOT PROVEN: a run on a real Windows host (no Windows run is
  claimed); the behaviour of git plumbing path output on
  Windows is git's documented form, not measured here.
- REMAINDER, registered plainly (not fixed in this slice):
  (1) pre-existing call sites do not yet route stored paths /
  text through the S-409 seam — the law and seam now exist;
  migrating each store is future work, and no store is claimed
  migrated. (2) Several pre-existing `write_text` sites omit
  `newline=` (and one, the askpass script in `proc.py`, omits
  `encoding=` too): on Linux they emit LF, but on Windows the
  default translation would emit CRLF into written files. Named
  here as a known leak class with its fix (`write_canonical_text`)
  standing; rewriting those call sites is follow-up work, not
  done in S-409 and not claimed.
