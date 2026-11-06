# Samverk research 04 — Git object model and safe plumbing boundaries

**Research and engineering brief | 2026-11-06 | Status: proposed design guidance, not a shipped-feature claim.**

This study fills the originally empty numbered research shelf. It uses public standards and observable Git behavior, not GitHub proprietary code or assets. Apply it under Samverk's clean-room, AGPL, no-Docker, security-first and standalone-first laws. Relevant roadmap: **S-049–S-053, S-058, S-071–S-076**.

## Protocol facts and engineering implications

- Git stores blob, tree, commit and annotated tag objects under content-addressed identifiers; branches are references, not separate object graphs.
- Loose objects, packfiles and indexes are alternate on-disk representations. Parsing raw `.git/objects` files in Samverk would duplicate Git maintenance logic and create compatibility traps.
- Git repositories may use SHA-1 or SHA-256 object formats. Object-ID length assumptions must come from repository format and tool output, not a fixed 40-character regex used everywhere.

## Recommended Samverk architecture and contracts

- Let `samverk/objects.py` and `samverk/refs.py` call bounded, allowlisted Git plumbing (`cat-file --batch`, `rev-parse`, `for-each-ref`, `update-ref`). Git itself validates object reachability and pack integrity.
- Represent tree paths as bytes at the plumbing boundary where necessary; decode for display with explicit fallback and escape before HTML. Do not treat Git tree file names as trusted filesystem paths.
- Resolve user-supplied ref once to a commit OID before listing files, diffing, blame or producing a permalink; provide a clear `ref_not_found` rather than silently falling back to default branch.
- Keep immutable Git history distinct from mutable SQLite metadata and user-uploaded auxiliary data. After crash, run a reconciliation pass rather than guessing that three stores committed atomically.

## Failure modes and less-obvious cases

- Malformed tree, zero-length blob, submodule gitlink entry, symlink, nested subdirectory, tag that peels to a noncommit, unborn branch, corrupted pack, object-format mismatch.
- Large blobs should be streamed or capped for rendering; never accidentally decode binaries into a syntax highlighter.

## Testable acceptance work

- Round-trip all four object types through stock Git; compare parsed values to `git cat-file` output.
- Inject invalid object IDs and corrupt a test-only pack; assert precise error reason, non-disclosure of private repository existence, and no write to unrelated data.
- Exercise filenames with spaces, UTF-8 and raw non-UTF-8 bytes; test SHA-256-format repositories explicitly or mark that matrix cell unsupported.

## Evidence and decision discipline

- Compare each recommendation against current implementations and tests before coding. Existing modules are **evidence of implementation**, not proof they are wired to the live `samverk/server.py` HTTP surface.
- Record decisions (accepted/deferred/rejected), exact test command and host, passing/failing/skipped counts, and any changes to `docs/CLAIMS_REGISTER.md` and `PROJECT_MEMORY_MAP.md`.
- Do not promote interoperability, security or portability to PROVEN without a fresh end-to-end run in the specified environment.

## Public technical references

1. https://git-scm.com/book/en/v2/Git-Internals-Git-Objects
2. https://git-scm.com/docs/git-cat-file
3. https://git-scm.com/docs/gitformat-pack
4. https://git-scm.com/docs/gitformat-object
