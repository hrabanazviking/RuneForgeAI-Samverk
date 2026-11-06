# Samverk research 18 — Repository-aware code search and indexing

**Research dossier, 2026-11-06.** Original technical synthesis of public material; engineering guidance, not proof of shipped functionality. Roadmap: **S-205–S-218**.

## What the technology requires

- Code search requires intentional tradeoffs: filename/path filters, exact text, regex, tokenization, symbol navigation and freshness cannot all be implemented cheaply by the same index.
- SQLite FTS provides text search but does not automatically understand every programming language or preserve arbitrary binary content. An indexed search can be stale after a push unless freshness is surfaced.
- Search must apply repository permissions *before* displaying results or result counts, including snippets and cached suggestions.

## Recommended architecture

- Define an index key of repo ID + immutable commit OID + file path + content digest; avoid indexing every commit of history by default.
- Start with filename/path and literal text search, then add opt-in regex using a bounded engine or process; do not allow untrusted catastrophic regex to monopolize workers.
- Use a dedicated background index queue with failure/retry state, high-water mark and per-repo status; never block push success on search rebuilding.
- Measure incremental index vs full rebuild separately and publish a coverage statement: ignored files, submodules, binaries, oversized files and branches indexed.

## Risks, failure modes and honest limits

- Search immediately after branch deletion, denied repo rename, private repo leak in autocomplete, Unicode case folding, stale index hit after force-push.

## Acceptance tests and review questions

- Create 100k-file stress fixture; measure indexing throughput, query latency, memory, and exact backlog growth.
- Search a private corpus anonymously and as authorized actor; result and timing leakage must be examined.
- Rebuild index after injected crash; verify no duplicate hits and no lost eventual updates.

## Traceability requirements

Before declaring this study's roadmap slices finished, identify source modules, live HTTP/SSH route reachability, role and scope checks, data persistence, test commands, actual results and skips. Record accepted/rejected choices as engineering decisions. Update the memory map and claims register, never infer production readiness from a backend module alone. Study the referenced specifications at implementation time, because some evolve.

## Public references

1. https://www.sqlite.org/fts5.html
2. https://git-scm.com/docs/git-grep
3. https://www.sqlite.org/wal.html
