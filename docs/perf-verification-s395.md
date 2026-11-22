# Performance verification — S-395

Clone/search/browse budgets (S-073, S-217) re-measured and
published with the numbers, 2026-11-22. Measured with
`tools/run_perf_verification.py` (5 repetitions after one
warm-up pass per query kind): the clone of S-073's reference
repository (1,000 commits, 2,000 blobs, cloned bare through
S-055's seam), S-217's reference corpus searched through
S-208's executor (6 repositories, 300 files, 9,000 lines),
and the root tree of `volmarr/mirror-00` browsed through
S-120's FileBrowser.

A number claims only the hardware class it was measured on
(the S-073 honesty law). This publication does not restate
any budget per class — that is S-413's work.

## Pi-class hardware — MEASURED

Machine: purpleviking1 (Mimir, Raspberry Pi 5), `aarch64`,
classed `pi_class_arm` by S-073's law. Raw run record:
`hidden_files/perf-pi.json` in the measuring worktree.

| Kind | Measurement | Budget (p95) | Verdict |
| --- | --- | --- | --- |
| clone | 0.011 s (884,101 bytes, 20 files) | 60 s | within budget |
| search substring `samverk` | p95 56.2 ms, mean 44.8 ms (300 files, 8,999 matches) | 2,000 ms | within budget |
| search substring `quixotic-anvil-7` | p95 10.2 ms, mean 9.1 ms (1 file, 1 match) | 2,000 ms | within budget |
| search regex `quixotic-anvil-[0-9]` | p95 12.2 ms, mean 11.8 ms (1 file, 1 match) | 4,000 ms | within budget |
| browse `volmarr/mirror-00` root (1 entry) | p95 10.2 ms, mean 8.2 ms | 4,000 ms | within budget |

The Pi-class cells S-073 and S-217 left NOT PROVEN are
proven by this run, for this workload, on this machine.

## Server x86-64 — MEASURED

Machine: purplelongship, `x86_64`, classed `server_x86_64`
by S-073's coarse law. Raw run record:
`hidden_files/perf-x86_64.json` in the measuring worktree.

| Kind | Measurement | Budget (p95) | Verdict |
| --- | --- | --- | --- |
| clone | 0.050 s (886,420 bytes, 21 files) | 30 s | within budget |
| search substring `samverk` | p95 54.8 ms, mean 48.3 ms (300 files, 8,999 matches) | 1,000 ms | within budget |
| search substring `quixotic-anvil-7` | p95 23.0 ms, mean 13.5 ms (1 file, 1 match) | 1,000 ms | within budget |
| search regex `quixotic-anvil-[0-9]` | p95 17.3 ms, mean 15.3 ms (1 file, 1 match) | 2,000 ms | within budget |
| browse `volmarr/mirror-00` root (1 entry) | p95 35.5 ms, mean 32.9 ms | 1,000 ms | within budget |

## Laptop x86-64 — NOT PROVEN

No laptop-class machine was measured by this slice: the
class is stated in S-073/S-217/S-395 and remains
unmeasured, NOT PROVEN, in those words.
