# Performance and memory discipline on Raspberry Pi and constrained hosts

**Samverk implementation research | 2026-11-06.** Guidance for coding agents and project directors, not a declaration of shipping or certified behavior. Roadmap references: S-073; S-217; S-395; S-413. Preserve all original 416 slices and clean-room/no-Docker laws.

## Context and engineering facts

- The Raspberry Pi 5 is a declared ARM64 target, not a proven performance benchmark at the November 6 snapshot.
- Module-level memory and performance need measurement on the actual target hardware; laptop throughput cannot establish Pi capability.
- Large Git packs, deeply nested diffs, code indexing and backup operations can consume CPU, memory and temporary storage independently.

## Concrete development plan

- Define load fixtures: empty repo, 10k objects, large history, 100k path index, many simultaneous issue writes, large LFS object, 50 concurrent HTTP clients and long-running mirror sync.
- Record p50/p95 latency and CPU/memory peaks for login, repo page, clone, push, compare, search and backup with corpus size, OS, Git/Python versions and cold/warm cache.
- Reuse Git batch plumbing rather than spawning one process per object. Cache immutable content by OID, paginate issue/search results and cap diff output with honest truncation.
- Keep CPU-heavy work out of user request handlers; set per-class worker concurrency and queue budgets, with explicit resource-blocked status.
- Measure SQLite query plans and WAL checkpoint cost, and document power-loss durability tradeoffs rather than disabling synchronous writes for benchmark scores.

## Failure cases and decision hazards

- A synthetic test with unbounded memory can pass on a 128GB developer machine but crash a swapless Pi.
- Concurrent full-suite verification and Git clone can distort latency and produce false failure reports.
- Filesystem/inode quotas can be exhausted even when a naive available-bytes check looks green.

## Testable completion criteria

- Benchmark same fixtures on Pi ARM64 and Linux x86-64; report both instead of extrapolating.
- Under memory and disk pressure, preserve existing Git refs and return bounded errors; no false success.
- Record tail latency and precise hardware/environment metadata, not one unqualified speed number.

## Proof and provenance obligations

At the next implementation checkpoint record exact module paths, whether routes are mounted in the real server, actor/permission behavior, schema changes, actual host/toolchain, full test totals, all skips and an independently reproducible demo when needed. Update the claims register and project memory map only with evidence. Historical entries are not overwritten, and any missing capability remains NOT PROVEN.

## References

1. https://www.sqlite.org/queryplanner.html
2. https://git-scm.com/docs/git-cat-file
3. https://docs.python.org/3/library/tracemalloc.html
