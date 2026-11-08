"""Performance budget (S-217).

Reference corpus (the instance's own mirrored
repos, Part XVII) searched within the stated
latency budget on Pi-class hardware; measured,
not asserted — Part X's proof slice, written from
research file 14 and in S-073's shape. S-208 fixed
the code search executor and said plainly that
S-217 measures the latency budget; this slice
states the budget, builds the corpus it is
measured over, and takes the measurement.

- **The reference corpus is defined in code.**
  `corpus_files` generates it deterministically:
  REFERENCE_REPOS repositories in the shape of
  Part XVII mirrors (ordinary repositories an
  instance holds for its owner), each with
  REFERENCE_FILES_PER_REPO files of
  REFERENCE_LINES_PER_FILE lines — the same
  corpus on every machine, so a number measured
  here and a number measured on a Pi are numbers
  about the same workload. Two needles are
  planted by construction: NEEDLE_COMMON appears
  in every file (the worst case for hit volume)
  and NEEDLE_RARE appears in exactly one file
  (the pinpoint case). The battery builds the
  corpus as real repositories and fills the index
  through S-207's own indexer; nothing here
  writes index rows behind its back.
- **The budget is stated per hardware class.**
  SEARCH_BUDGETS_MS names, for each class in
  HARDWARE_CLASSES, the p95 latency budget in
  milliseconds for a substring search and for a
  regex search over the reference corpus. The
  classes are S-073's (server_x86_64,
  laptop_x86_64, pi_class_arm), and the class of
  the machine a measurement ran on comes from
  S-073's own hardware_class — one definition,
  never a second guess at the same question.
- **CPU honesty: measured, not asserted.** A
  measurement claims only the class it ran on.
  budget_report carries a verdict for the class
  that was measured and marks every other class
  unmeasured, in words — on this slice's build
  machine (laptop x86-64, classed server_x86_64
  by S-073's coarse law) the Pi-class budget is
  stated and remains NOT PROVEN: S-395 re-measures
  on Pi-class hardware and S-413 restates every
  budget per class. A budget that was never
  measured is never reported as met.
- **The measurement is the executor's own.**
  measure_searches times S-208's CodeSearch
  (search_counted, so the S-209 filtered totals
  are part of the timed work) over the planted
  needles, after one warm-up pass, for a stated
  number of repetitions. The summary is the pure
  summarise law (count, minimum, mean, p50, p95,
  maximum — percentiles by nearest rank), and
  the verdict is the pure judge law: the p95
  must land within the class budget for that
  query kind. No number is rounded into passing:
  the raw summary rides in every record.
- **Fail-closed refusals.** An unknown hardware
  class, an unknown query kind, an empty sample
  set, a non-positive budget, or a bad repetition
  count is refused with a named reason
  (budget_unknown, query_kind_unknown,
  samples_empty, repetitions_invalid) — a
  measurement that cannot be judged is never
  quietly reported as within budget.
- **Permission is not weakened for speed.** The
  timed searches run through the same S-209
  filtered executor as every other code search:
  the battery times a stranger's searches over a
  corpus holding a private repository and proves
  the private needle contributes no hit and no
  count, at speed exactly as at rest.
- **No audit event of its own.** Measuring a
  read is a read. 123 events stand: 31 auth /
  79 repo / 13 admin. No migration: schema
  stays 84.
"""
from __future__ import annotations

import platform
import time
from dataclasses import dataclass

from .code_search import CodeSearch
from .escaping import escape_html_text
from .repo_budgets import hardware_class

__all__ = [
    "HARDWARE_CLASSES", "NEEDLE_COMMON", "NEEDLE_RARE",
    "MEASURED_QUERIES", "QUERY_KINDS", "REFERENCE_FILES_PER_REPO",
    "REFERENCE_LINES_PER_FILE", "REFERENCE_REPOS",
    "SEARCH_BUDGETS_MS", "CorpusSpec", "LatencySummary",
    "QueryMeasurement", "SearchBudgetError", "budget_for",
    "budget_report", "corpus_files", "corpus_spec", "judge",
    "measure_searches", "percentile", "render_search_budget_page",
    "summarise",
]

HARDWARE_CLASSES = ("server_x86_64", "laptop_x86_64", "pi_class_arm")
QUERY_KINDS = ("substring", "regex")

# The reference corpus shape (see module docstring).
REFERENCE_REPOS = 6
REFERENCE_FILES_PER_REPO = 50
REFERENCE_LINES_PER_FILE = 30
NEEDLE_COMMON = "samverk"
NEEDLE_RARE = "quixotic-anvil-7"

# Stated p95 latency budgets, milliseconds, per
# hardware class and query kind, over the reference
# corpus. Only a class whose measurement actually
# ran may claim its budget (the CPU-honesty law).
SEARCH_BUDGETS_MS = {
    "server_x86_64": {"substring": 1000.0, "regex": 2000.0},
    "laptop_x86_64": {"substring": 2000.0, "regex": 4000.0},
    "pi_class_arm": {"substring": 2000.0, "regex": 4000.0},
}

# The measured queries: (kind, pattern). The
# substring kinds hunt the planted needles; the
# regex kind hunts the rare needle's shape.
MEASURED_QUERIES = (
    ("substring", NEEDLE_COMMON),
    ("substring", NEEDLE_RARE),
    ("regex", r"quixotic-anvil-[0-9]"),
)


class SearchBudgetError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# ------------------------------------------------------------------
# The reference corpus, generated deterministically
# ------------------------------------------------------------------

@dataclass(frozen=True)
class CorpusSpec:
    """The reference corpus as numbers: how many
    repositories, files, lines and bytes a budget
    measurement ran over, and how many files carry
    each planted needle."""
    repos: int
    files: int
    lines: int
    total_bytes: int
    common_files: int
    rare_files: int


def _file_text(repo_index: int, file_index: int) -> str:
    lines = []
    for line_no in range(REFERENCE_LINES_PER_FILE):
        lines.append(
            f"# samverk mirror corpus repo {repo_index} "
            f"file {file_index} line {line_no}: the forge "
            f"keeps its own counsel and its own records.")
    if repo_index == 0 and file_index == 0:
        lines[0] = f"# {NEEDLE_RARE} marks the one rare file."
    return "\n".join(lines) + "\n"


def corpus_files() -> tuple[tuple[str, str, str], ...]:
    """Every file of the reference corpus as
    (repository name, path, text), in a fixed
    order — the same corpus on every machine."""
    out = []
    for r in range(REFERENCE_REPOS):
        repo = f"mirror-{r:02d}"
        for f in range(REFERENCE_FILES_PER_REPO):
            out.append((repo, f"src/module_{f:03d}.py",
                        _file_text(r, f)))
    return tuple(out)


def corpus_spec() -> CorpusSpec:
    files = corpus_files()
    total_bytes = 0
    total_lines = 0
    common = 0
    rare = 0
    for _repo, _path, text in files:
        total_bytes += len(text.encode("utf-8"))
        total_lines += text.count("\n")
        if NEEDLE_COMMON in text:
            common += 1
        if NEEDLE_RARE in text:
            rare += 1
    return CorpusSpec(
        repos=REFERENCE_REPOS, files=len(files), lines=total_lines,
        total_bytes=total_bytes, common_files=common, rare_files=rare)


# ------------------------------------------------------------------
# Pure law: percentiles, summaries, budgets, verdicts
# ------------------------------------------------------------------

def percentile(samples, q: float) -> float:
    """The q-th percentile (0..100) of *samples* by
    nearest rank. An empty sample set is refused
    samples_empty — a percentile of nothing is not
    zero, it is unknown, and unknown never passes."""
    values = sorted(float(s) for s in samples)
    if not values:
        raise SearchBudgetError(
            "samples_empty", "No samples to summarise.")
    if q <= 0:
        return values[0]
    if q >= 100:
        return values[-1]
    rank = -(-len(values) * q // 100)  # ceil(n*q/100)
    return values[max(1, int(rank)) - 1]


@dataclass(frozen=True)
class LatencySummary:
    count: int
    minimum_ms: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    maximum_ms: float


def summarise(samples) -> LatencySummary:
    """One set of millisecond samples as a summary:
    count, minimum, mean, p50, p95 and maximum,
    unrounded — the raw truth a verdict rests on."""
    values = [float(s) for s in samples]
    if not values:
        raise SearchBudgetError(
            "samples_empty", "No samples to summarise.")
    return LatencySummary(
        count=len(values), minimum_ms=min(values),
        mean_ms=sum(values) / len(values),
        p50_ms=percentile(values, 50),
        p95_ms=percentile(values, 95),
        maximum_ms=max(values))


def budget_for(hardware: str, kind: str) -> float:
    """The stated p95 budget in milliseconds for one
    hardware class and query kind. An unknown class
    or kind is refused by name — never defaulted."""
    if hardware not in SEARCH_BUDGETS_MS:
        raise SearchBudgetError(
            "budget_unknown",
            f"No stated budget for hardware class {hardware!r}.")
    if kind not in QUERY_KINDS:
        raise SearchBudgetError(
            "query_kind_unknown",
            f"No stated budget for query kind {kind!r}.")
    return SEARCH_BUDGETS_MS[hardware][kind]


def judge(summary: LatencySummary, budget_ms: float) -> bool:
    """The verdict law: a measurement is within its
    budget exactly when its p95 lands at or under
    the stated budget. A non-positive budget is
    refused, never judged."""
    if budget_ms <= 0:
        raise SearchBudgetError(
            "budget_unknown",
            "A budget must be a positive number of milliseconds.")
    return summary.p95_ms <= budget_ms


# ------------------------------------------------------------------
# The measurement itself, over S-208's executor
# ------------------------------------------------------------------

@dataclass(frozen=True)
class QueryMeasurement:
    """One measured query kind over the reference
    corpus: the pattern hunted, the filtered totals
    the timed searches returned, the latency summary
    in milliseconds, the class it ran on (with the
    machine string beside it, S-073's honesty), its
    stated budget, and the verdict."""
    kind: str
    pattern: str
    total_files: int
    total_matches: int
    summary: LatencySummary
    hardware_class: str
    machine: str
    budget_ms: float
    within_budget: bool


def measure_searches(search: CodeSearch, viewer, *,
                     repetitions: int = 5,
                     hardware: str | None = None,
                     ) -> tuple[QueryMeasurement, ...]:
    """Time the measured queries through *search*
    (S-208's CodeSearch, S-209-filtered) as *viewer*
    over the indexed reference corpus: one warm-up
    pass, then *repetitions* timed passes per query,
    each timed with a monotonic clock around
    search_counted. Returns one QueryMeasurement
    per measured query, in MEASURED_QUERIES order.
    A bad repetition count refuses repetitions_invalid
    before anything is timed."""
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) \
            or repetitions < 1:
        raise SearchBudgetError(
            "repetitions_invalid",
            "Repetitions is a positive count.")
    cls = hardware if hardware is not None else hardware_class()
    machine = platform.machine()
    measurements = []
    for kind, pattern in MEASURED_QUERIES:
        mode = "regex" if kind == "regex" else "substring"
        first = search.search_counted(
            viewer, pattern=pattern, mode=mode)
        samples = []
        totals = (first.total_files, first.total_matches)
        for _ in range(repetitions):
            started = time.perf_counter()
            result = search.search_counted(
                viewer, pattern=pattern, mode=mode)
            samples.append((time.perf_counter() - started) * 1000.0)
            totals = (result.total_files, result.total_matches)
        summary = summarise(samples)
        budget = budget_for(cls, kind)
        measurements.append(QueryMeasurement(
            kind=kind, pattern=pattern,
            total_files=totals[0], total_matches=totals[1],
            summary=summary, hardware_class=cls, machine=machine,
            budget_ms=budget, within_budget=judge(summary, budget)))
    return tuple(measurements)


def budget_report(measurements, spec: CorpusSpec) -> dict:
    """The whole budget story as JSON-safe data: the
    corpus as numbers, one entry per measured query
    with its raw summary and verdict, and one entry
    per hardware class — the measured class carries
    its verdicts, every other class is marked
    unmeasured in words. Nothing here sums or
    averages across classes."""
    measured_class = measurements[0].hardware_class if measurements else ""
    classes = {}
    for cls in HARDWARE_CLASSES:
        if cls == measured_class:
            classes[cls] = {
                "status": "measured",
                "within_budget": all(
                    m.within_budget for m in measurements),
            }
        else:
            classes[cls] = {"status": "unmeasured",
                            "within_budget": None}
    return {
        "corpus": {
            "repos": spec.repos, "files": spec.files,
            "lines": spec.lines, "bytes": spec.total_bytes,
            "common_files": spec.common_files,
            "rare_files": spec.rare_files},
        "queries": [
            {"kind": m.kind, "pattern": m.pattern,
             "total_files": m.total_files,
             "total_matches": m.total_matches,
             "count": m.summary.count,
             "min_ms": m.summary.minimum_ms,
             "mean_ms": m.summary.mean_ms,
             "p50_ms": m.summary.p50_ms,
             "p95_ms": m.summary.p95_ms,
             "max_ms": m.summary.maximum_ms,
             "hardware_class": m.hardware_class,
             "machine": m.machine,
             "budget_ms": m.budget_ms,
             "within_budget": m.within_budget}
            for m in measurements],
        "classes": classes,
    }


def render_search_budget_page(report: dict) -> str:
    """The budget page: the corpus in numbers, each
    measured query with its p95 against its stated
    budget and its verdict in words, and every
    hardware class named — measured classes with
    their verdict, unmeasured classes said plainly
    to be NOT PROVEN (S-395 re-measures them).
    Every value passes through S-010 escaping."""
    corpus = report["corpus"]
    parts = [
        "<h1>Search performance budget</h1>",
        f"<p>Reference corpus: {corpus['repos']} repositories, "
        f"{corpus['files']} files, {corpus['lines']} lines, "
        f"{corpus['bytes']} bytes. Budgets are p95 latency "
        "in milliseconds, measured — not asserted.</p>",
        '<ul class="budget-queries">',
    ]
    for q in report["queries"]:
        verdict = "within budget" if q["within_budget"] else "OVER BUDGET"
        parts.append(
            f"<li>{escape_html_text(q['kind'])} search for "
            f"{escape_html_text(q['pattern'])}: p95 "
            f"{q['p95_ms']:.1f} ms against a budget of "
            f"{q['budget_ms']:.0f} ms on "
            f"{escape_html_text(q['hardware_class'])} "
            f"({escape_html_text(q['machine'])}) — "
            f"{escape_html_text(verdict)}; "
            f"{q['total_files']} files, {q['total_matches']} "
            "matches.</li>")
    parts.append("</ul>")
    parts.append('<ul class="budget-classes">')
    for cls in HARDWARE_CLASSES:
        entry = report["classes"][cls]
        if entry["status"] == "measured":
            words = ("measured — within budget"
                     if entry["within_budget"]
                     else "measured — OVER BUDGET")
        else:
            words = ("unmeasured — NOT PROVEN on this class; "
                     "S-395 re-measures it")
        parts.append(
            f"<li>{escape_html_text(cls)}: "
            f"{escape_html_text(words)}.</li>")
    parts.append("</ul>")
    return "\n".join(parts)
