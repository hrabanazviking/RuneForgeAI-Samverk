# CPU honesty — performance budgets per hardware class (S-413)

Every performance budget Samverk states, restated in one
register per hardware class. The law: **a budget proven on
one class claims nothing about another.** The register lives
in code (`samverk/cpu_honesty.py`), built from the source
modules' own budget dicts so it cannot drift from them;
`tools/run_cpu_honesty.py` prints it. This slice measures
nothing — the measured numbers below are S-395's published
run (docs/perf-verification-s395.md).

## The register

| Kind (source) | Desktop/server x86-64 | Laptop x86-64 | Pi-class ARM |
| --- | --- | --- | --- |
| clone, seconds (S-073) | 30 | 60 | 60 |
| search substring, ms p95 (S-217) | 1,000 | 2,000 | 2,000 |
| search regex, ms p95 (S-217) | 2,000 | 4,000 | 4,000 |
| browse, ms p95 (S-395) | 1,000 | 2,000 | 4,000 |

Workloads: clone of S-073's reference repository (1,000
commits, 2,000 blobs); search over S-217's reference corpus
(6 repos, 300 files, 9,000 lines); root-tree browse of a
reference repository through S-120's FileBrowser. The
substring measured cell carries the common-needle p95, the
higher of S-395's two substring measurements on both
measured classes.

## Proof status per class

- **Pi-class ARM — MEASURED.** Raspberry Pi 5 (Mimir,
  `aarch64`), S-395 run: clone 0.011 s; substring p95
  56.2 ms; regex p95 12.2 ms; browse p95 10.2 ms — all
  within budget, for those workloads, on that machine.
- **Desktop/server x86-64 — MEASURED.** purplelongship
  (`x86_64`, classed server by S-073's coarse law), S-395
  run: clone 0.050 s; substring p95 54.8 ms; regex p95
  17.3 ms; browse p95 35.5 ms — all within budget.
- **Laptop x86-64 — NOT PROVEN.** No slice has ever
  measured a laptop-class machine. The budgets above are
  stated, not proven, and this register claims nothing
  about laptop performance in any cell.

## What this register does not do

It does not average, blend, or transfer verdicts across
classes: asking the code to carry a verdict from one class
to another is refused (`cross_class_claim`). S-073's
`hardware_class()` also cannot distinguish a laptop from a
server on x86-64 — a future measurement run on a laptop
must name its class explicitly, as S-395's browse
measurement already allows; until such a run exists and is
published, the laptop column stays NOT PROVEN.
