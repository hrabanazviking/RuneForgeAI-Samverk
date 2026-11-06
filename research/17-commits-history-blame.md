# Samverk research 17 — History, diff, blame, caches and stable permalinks

**Research dossier • 2026-11-06 • Engineering guidance, not a completion claim.** Original work based on public specifications and observable behavior, with no copied proprietary code or UI. Roadmap: **S-051–S-052, S-072–S-073, S-097–S-120**.

## What the protocols and user workflows require

- Commit history is a DAG; merges create multiple parents and the visual graph cannot assume a single linear chain.
- Blame attributes surviving lines according to Git's chosen heuristics and options; it is not a moral assertion of authorship or code responsibility.
- Displaying a branch path directly is unstable across pushes; stable permalinks should pin commit OID and line location.

## Architecture and implementation decisions to evaluate

- Use stock `git log`, `blame`, `diff` and commit-graph operations through bounded subprocesses; parse machine-readable NUL-delimited formats where possible.
- Implement capped pagination using cursor/commit OID rather than unbounded offsets. Invalidate head-sensitive caches when refs move; content-addressed results keyed by immutable OID can stay cached.
- Render huge diffs with honest omitted-line/file counts and per-file navigation; enforce binary detection and output escaping.
- Keep author/committer identity distinct, and label verified commit signatures only when actual cryptographic checks succeeded.

## Failure modes and difficult cases

- Octopus merge, file rename/copy, CRLF lines, non-UTF8 content, history rewrite, deep shallow clone, path with tabs/newlines.
- Cache of private content must include authorization boundary in key/use; shared mutable cache must not leak across users.

## Acceptance checks for development agents

- Compare paginated history and blame to stock Git on fixtures with merges, renames and rewritten branches.
- Measure 10k-object graph traversal and large-diff latency/memory with documented hardware, not ungrounded speed claims.
- Ask unauthenticated user for a private blob permalink; assert indistinguishable missing response.

## Integration, evidence and scope

Document the exact modules and API/HTTP entry points touched, the permission decision, security boundary and failure handling. A green module-level test does not prove an end-to-end user-visible feature; test the assembled `samverk serve` process separately. Use explicit NOT PROVEN labels for unexercised SSH, browser, OS and recovery matrix cells. Record fresh commands and result counts. Keep the claims register and project memory map consistent with actual commits; retain history rather than rewriting earlier reports.

## Standards and research references

1. https://git-scm.com/docs/git-log
2. https://git-scm.com/docs/git-blame
3. https://git-scm.com/docs/git-diff
4. https://git-scm.com/docs/git-commit-graph
