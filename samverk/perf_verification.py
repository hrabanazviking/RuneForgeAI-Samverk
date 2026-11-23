"""Performance verification (S-395).

Clone/search/browse budgets (S-073, S-217)
re-measured on Pi-class hardware and published
with the numbers — Part XXI's proof slice. S-073
stated the clone budget per hardware class and
measured it on x86-64 only; S-217 did the same
for search. Both said plainly that the Pi-class
cell was NOT PROVEN and that S-395 owns its
re-measurement. This slice is that
re-measurement's machinery and its publication:

- **One publication, every budget kind.** A
  publication gathers the measurements a single
  run took — the S-073 clone measurement, the
  S-217 search measurements, and this slice's
  browse measurement — and publishes each with
  its raw numbers: the clone's seconds against
  its stated budget, each search's p95 against
  its stated budget, the browse p95 against the
  browse budget stated below. No number is
  rounded into passing and no kind is silently
  dropped: a kind a run did not measure is
  absent from the publication, never reported
  as met.
- **The browse budget is stated here.** Browsing
  the root tree of a reference repository
  through S-120's FileBrowser is the forge's
  most ordinary read; BROWSE_BUDGETS_MS states
  its p95 latency budget per hardware class, in
  S-217's shape. measure_browse times the
  browser's own browse call, after one warm-up
  pass, and judges it by S-217's summarise/judge
  law — one percentile law, never a second.
- **CPU honesty: measured, not asserted (the
  S-073/S-413 law).** A publication claims only
  the hardware class its measurements ran on:
  every measurement in one publication must
  carry the same class or the publication is
  refused (class_mismatch) — numbers from two
  classes are never blended into one verdict.
  Every other class is published as unmeasured,
  NOT PROVEN, in words. A budget proven on one
  class claims nothing about another, and this
  slice does not restate any budget per class:
  that restatement is S-413's work. The numbers
  this slice's own verification run measured —
  on x86-64 and on Pi-class hardware — are
  published in docs/perf-verification-s395.md.
- **Fail-closed refusals.** An empty publication,
  a class mismatch, an unknown hardware class,
  or a bad repetition count is refused with a
  named reason (measurements_empty,
  class_mismatch, budget_unknown,
  repetitions_invalid) — a verification that
  cannot be judged is never quietly published
  as within budget.
- **Permission is not weakened for speed.** The
  browse measurement runs through the same
  FileBrowser as every other browse: the battery
  proves a stranger's browse of a private
  repository is refused exactly as at rest, and
  the timed browse is an owner's browse of a
  public reference repository.
- **No audit event of its own.** Measuring a
  read is a read. No migration: this slice adds
  no schema and no stored state; a publication
  is data a run produces, not data the forge
  keeps.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .platform_seam import machine as seam_machine
from .escaping import escape_html_text
from .file_browser import FileBrowser
from .repo_budgets import hardware_class
from .search_budgets import HARDWARE_CLASSES, judge, summarise

__all__ = [
    "BROWSE_BUDGETS_MS", "BrowseMeasurement", "PerfError",
    "browse_budget_for", "measure_browse", "publication",
    "render_perf_page",
]

# Stated p95 latency budgets, milliseconds, per
# hardware class, for browsing the root tree of a
# reference repository. Only a class whose
# measurement actually ran may claim its budget
# (the CPU-honesty law).
BROWSE_BUDGETS_MS = {
    "server_x86_64": 1000.0,
    "laptop_x86_64": 2000.0,
    "pi_class_arm": 4000.0,
}


class PerfError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def browse_budget_for(hardware: str) -> float:
    """The stated browse p95 budget in milliseconds
    for one hardware class. An unknown class is
    refused by name — never defaulted."""
    if hardware not in BROWSE_BUDGETS_MS:
        raise PerfError(
            "budget_unknown",
            f"No stated browse budget for hardware "
            f"class {hardware!r}.")
    return BROWSE_BUDGETS_MS[hardware]


# ------------------------------------------------------------------
# The browse measurement, over S-120's FileBrowser
# ------------------------------------------------------------------

@dataclass(frozen=True)
class BrowseMeasurement:
    """One measured browse: the repository browsed
    (owner/name), how many entries its root tree
    carried, the latency summary in milliseconds
    (S-217's summarise law), the class it ran on
    (with the machine string beside it, S-073's
    honesty), its stated budget, and the verdict."""
    repo: str
    entries: int
    summary: object
    hardware_class: str
    machine: str
    budget_ms: float
    within_budget: bool


def measure_browse(browser: FileBrowser, viewer, owner: str,
                   repo: str, *, repetitions: int = 5,
                   hardware: str | None = None,
                   ) -> BrowseMeasurement:
    """Time root-tree browses of one repository
    through *browser* (S-120's FileBrowser) as
    *viewer*: one warm-up pass, then *repetitions*
    timed passes, each timed with a monotonic
    clock around the browse call itself. A bad
    repetition count refuses repetitions_invalid
    before anything is timed; a browse the
    browser refuses (a private repository browsed
    by a stranger) propagates as its own refusal —
    it is never timed into a number."""
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) \
            or repetitions < 1:
        raise PerfError(
            "repetitions_invalid",
            "Repetitions is a positive count.")
    cls = hardware if hardware is not None else hardware_class()
    budget = browse_budget_for(cls)
    first = browser.browse(viewer, owner, repo)
    entries = len(first.entries)
    samples = []
    for _ in range(repetitions):
        started = time.perf_counter()
        view = browser.browse(viewer, owner, repo)
        samples.append((time.perf_counter() - started) * 1000.0)
        entries = len(view.entries)
    summary = summarise(samples)
    return BrowseMeasurement(
        repo=f"{owner}/{repo}", entries=entries, summary=summary,
        hardware_class=cls, machine=seam_machine(),
        budget_ms=budget, within_budget=judge(summary, budget))


# ------------------------------------------------------------------
# The publication: one run's numbers, published whole
# ------------------------------------------------------------------

def publication(*, clone=None, searches=(), browse=None) -> dict:
    """The whole verification story as JSON-safe
    data: one entry per measured budget kind with
    its raw numbers and verdict, and one entry per
    hardware class — the measured class carries
    its verdicts, every other class is marked
    unmeasured. All measurements must carry one
    hardware class: a mixed-class publication is
    refused class_mismatch, and a publication with
    no measurements at all is refused
    measurements_empty. Nothing here sums or
    averages across kinds or classes."""
    measured = []
    if clone is not None:
        measured.append(clone)
    measured.extend(searches)
    if browse is not None:
        measured.append(browse)
    if not measured:
        raise PerfError(
            "measurements_empty",
            "A publication with no measurements "
            "publishes nothing.")
    classes_seen = {m.hardware_class for m in measured}
    if len(classes_seen) != 1:
        raise PerfError(
            "class_mismatch",
            "One publication, one hardware class: "
            f"{sorted(classes_seen)} were mixed.")
    cls = measured[0].hardware_class
    if cls not in HARDWARE_CLASSES:
        raise PerfError(
            "budget_unknown",
            f"No stated budgets for hardware class {cls!r}.")
    machine = measured[0].machine
    entries = []
    if clone is not None:
        entries.append({
            "kind": "clone", "seconds": clone.seconds,
            "budget_seconds": clone.budget_seconds,
            "total_bytes": clone.total_bytes,
            "file_count": clone.file_count,
            "within_budget": clone.within_budget})
    for m in searches:
        entries.append({
            "kind": "search", "query_kind": m.kind,
            "pattern": m.pattern,
            "total_files": m.total_files,
            "total_matches": m.total_matches,
            "count": m.summary.count,
            "min_ms": m.summary.minimum_ms,
            "mean_ms": m.summary.mean_ms,
            "p50_ms": m.summary.p50_ms,
            "p95_ms": m.summary.p95_ms,
            "max_ms": m.summary.maximum_ms,
            "budget_ms": m.budget_ms,
            "within_budget": m.within_budget})
    if browse is not None:
        entries.append({
            "kind": "browse", "repo": browse.repo,
            "entries": browse.entries,
            "count": browse.summary.count,
            "min_ms": browse.summary.minimum_ms,
            "mean_ms": browse.summary.mean_ms,
            "p50_ms": browse.summary.p50_ms,
            "p95_ms": browse.summary.p95_ms,
            "max_ms": browse.summary.maximum_ms,
            "budget_ms": browse.budget_ms,
            "within_budget": browse.within_budget})
    classes = {}
    for name in HARDWARE_CLASSES:
        if name == cls:
            classes[name] = {
                "status": "measured",
                "within_budget": all(
                    e["within_budget"] for e in entries)}
        else:
            classes[name] = {"status": "unmeasured",
                             "within_budget": None}
    return {"hardware_class": cls, "machine": machine,
            "entries": entries, "classes": classes}


def render_perf_page(pub: dict) -> str:
    """The publication page: every measured kind
    with its raw numbers against its stated budget
    and its verdict in words, and every hardware
    class named — the measured class with its
    verdict, unmeasured classes said plainly to be
    NOT PROVEN. A number published here claims
    only the class it was measured on (S-413
    restates every budget per class). Every value
    passes through S-010 escaping."""
    parts = [
        "<h1>Performance verification</h1>",
        f"<p>Measured on {escape_html_text(pub['hardware_class'])} "
        f"({escape_html_text(pub['machine'])}). Budgets are "
        "S-073's clone budget, S-217's search budgets and "
        "S-395's browse budget, re-measured — not asserted. "
        "A number claims only the class it ran on.</p>",
        '<ul class="perf-entries">',
    ]
    for e in pub["entries"]:
        verdict = "within budget" if e["within_budget"] else "OVER BUDGET"
        if e["kind"] == "clone":
            text = (f"clone: {e['seconds']:.2f} s against a budget "
                    f"of {e['budget_seconds']:.0f} s; "
                    f"{e['total_bytes']} bytes, {e['file_count']} "
                    f"files — {verdict}")
        elif e["kind"] == "search":
            text = (f"search ({e['query_kind']}) for {e['pattern']}: "
                    f"p95 {e['p95_ms']:.1f} ms against a budget of "
                    f"{e['budget_ms']:.0f} ms; {e['total_files']} "
                    f"files, {e['total_matches']} matches — {verdict}")
        else:
            text = (f"browse of {e['repo']} root tree "
                    f"({e['entries']} entries): p95 "
                    f"{e['p95_ms']:.1f} ms against a budget of "
                    f"{e['budget_ms']:.0f} ms — {verdict}")
        parts.append(f"<li>{escape_html_text(text)}</li>")
    parts.append("</ul>")
    parts.append('<ul class="perf-classes">')
    for cls in HARDWARE_CLASSES:
        entry = pub["classes"][cls]
        if entry["status"] == "measured":
            words = ("measured — within budget"
                     if entry["within_budget"]
                     else "measured — OVER BUDGET")
        else:
            words = "unmeasured — NOT PROVEN on this class"
        parts.append(
            f"<li>{escape_html_text(cls)}: "
            f"{escape_html_text(words)}.</li>")
    parts.append("</ul>")
    return "\n".join(parts)
