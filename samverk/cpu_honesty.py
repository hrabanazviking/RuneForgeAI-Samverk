"""CPU honesty (S-413).

Performance budgets (S-073, S-217, S-395) restated
per hardware class (Pi-class ARM, laptop x86-64,
desktop/server); a budget proven on one class
claims nothing about another — Part XXII's closing
honesty slice.

- **One register, every budget.** S-073 stated the
  clone budget, S-217 the search budgets, S-395 the
  browse budget — each in its own module, each per
  hardware class. This slice restates them in ONE
  register: every budget kind x every hardware
  class, with its source slice named. The register
  is built from the source modules' own dicts at
  import, so a restatement can never drift from
  the budget it restates (the battery pins the
  equality directly).
- **Proven is per class, in words.** S-395's
  verification run measured two classes and
  published the numbers (docs/perf-verification-
  s395.md): Pi-class ARM on a Raspberry Pi 5
  (Mimir) and desktop/server x86-64 on
  purplelongship, every kind within budget. Those
  two classes are MEASURED here, with S-395's
  numbers carried verbatim. Laptop x86-64 was
  measured by NO slice: it is NOT PROVEN in plain
  words, everywhere it appears.
- **No cross-class claims, ever.** A verdict is a
  (kind, class) pair. Asking this register to
  carry a verdict from one class to another is
  refused by name (cross_class_claim) — the law
  is code, not a comment.
- **Fail-closed.** An unknown budget kind or
  hardware class is refused by name
  (kind_unknown / budget_unknown), never
  defaulted to a neighbour's number.
- **No measurement of its own, no stored state.**
  This slice restates and registers; it times
  nothing and claims no new proof. No migration,
  no audit event: a register is data the code
  states, not data the forge keeps.
"""
from __future__ import annotations

from dataclasses import dataclass

from .escaping import escape_html_text
from .perf_verification import BROWSE_BUDGETS_MS
from .repo_budgets import CLONE_BUDGETS_SECONDS
from .search_budgets import HARDWARE_CLASSES, SEARCH_BUDGETS_MS

__all__ = [
    "BUDGET_KINDS", "CLASS_LABELS", "MEASURED", "CpuHonestyError",
    "RegisterEntry", "budget_register", "claim_for", "class_status",
    "cross_class_verdict", "render_cpu_honesty_page", "restatement",
]

BUDGET_KINDS = ("clone", "search_substring", "search_regex", "browse")

CLASS_LABELS = {
    "server_x86_64": "desktop/server x86-64",
    "laptop_x86_64": "laptop x86-64",
    "pi_class_arm": "Pi-class ARM",
}

_KIND_SOURCE = {
    "clone": "S-073", "search_substring": "S-217",
    "search_regex": "S-217", "browse": "S-395",
}
_KIND_UNIT = {"clone": "seconds", "search_substring": "ms p95",
              "search_regex": "ms p95", "browse": "ms p95"}
_KIND_WORKLOAD = {
    "clone": "clone of the S-073 reference repository "
             "(1,000 commits, 2,000 blobs)",
    "search_substring": "substring search of the S-217 reference "
                        "corpus (6 repos, 300 files, 9,000 lines)",
    "search_regex": "regex search of the S-217 reference corpus "
                    "(6 repos, 300 files, 9,000 lines)",
    "browse": "root-tree browse of a reference repository "
              "through S-120's FileBrowser",
}

def _budget(kind: str, cls: str) -> float:
    if kind == "clone":
        return CLONE_BUDGETS_SECONDS[cls]
    if kind == "search_substring":
        return SEARCH_BUDGETS_MS[cls]["substring"]
    if kind == "search_regex":
        return SEARCH_BUDGETS_MS[cls]["regex"]
    return BROWSE_BUDGETS_MS[cls]


# S-395's published measurements, carried verbatim
# from docs/perf-verification-s395.md (raw records:
# hidden_files/perf-pi.json and perf-x86_64.json in
# the measuring worktree). A kind a class never
# measured is absent here, never invented.
MEASURED = {
    "pi_class_arm": {
        "machine": "purpleviking1 (Mimir, Raspberry Pi 5), aarch64",
        "source": "S-395",
        "clone": 0.011, "search_substring": 56.2,
        "search_regex": 12.2, "browse": 10.2},
    "server_x86_64": {
        "machine": "purplelongship, x86_64",
        "source": "S-395",
        "clone": 0.050, "search_substring": 54.8,
        "search_regex": 17.3, "browse": 35.5},
}
# Laptop x86-64 is deliberately absent from
# MEASURED: no slice measured it. Its status is
# NOT PROVEN, stated in words wherever it appears.


class CpuHonestyError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _require_kind(kind: str) -> None:
    if kind not in BUDGET_KINDS:
        raise CpuHonestyError(
            "kind_unknown", f"No budget kind {kind!r} is registered.")


def _require_class(cls: str) -> None:
    if cls not in HARDWARE_CLASSES:
        raise CpuHonestyError(
            "budget_unknown",
            f"No stated budgets for hardware class {cls!r}.")


@dataclass(frozen=True)
class RegisterEntry:
    """One cell of the register: one budget kind on
    one hardware class — its stated budget, its
    source slice, the workload it governs, its
    proof status in words, and (only where a real
    run measured it) the measured number."""
    kind: str
    hardware_class: str
    class_label: str
    budget: float
    unit: str
    source: str
    workload: str
    status: str  # "measured" or "NOT PROVEN"
    measured: float | None
    machine: str | None


def budget_register() -> tuple[RegisterEntry, ...]:
    """The whole register: every kind x every class,
    kinds in BUDGET_KINDS order, classes in
    HARDWARE_CLASSES order."""
    out = []
    for kind in BUDGET_KINDS:
        for cls in HARDWARE_CLASSES:
            rec = MEASURED.get(cls)
            hit = rec is not None and kind in rec
            out.append(RegisterEntry(
                kind=kind, hardware_class=cls,
                class_label=CLASS_LABELS[cls],
                budget=_budget(kind, cls), unit=_KIND_UNIT[kind],
                source=_KIND_SOURCE[kind],
                workload=_KIND_WORKLOAD[kind],
                status="measured" if hit else "NOT PROVEN",
                measured=rec[kind] if hit else None,
                machine=rec["machine"] if hit else None))
    return tuple(out)


def claim_for(kind: str, cls: str) -> RegisterEntry:
    """The register cell for one (kind, class) pair.
    Unknown kind or class is refused by name."""
    _require_kind(kind)
    _require_class(cls)
    for entry in budget_register():
        if entry.kind == kind and entry.hardware_class == cls:
            return entry
    raise AssertionError("register is complete by construction")


def class_status(cls: str) -> str:
    """One class's proof status in words: \"measured\"
    only where S-395's run measured every kind on
    it, otherwise \"NOT PROVEN\"."""
    _require_class(cls)
    cells = [e for e in budget_register() if e.hardware_class == cls]
    if all(e.status == "measured" for e in cells):
        return "measured"
    return "NOT PROVEN"


def cross_class_verdict(kind: str, proven_on: str,
                        claimed_for: str) -> bool:
    """May a verdict proven on one class be claimed
    for another? Same class: the claim is the
    class's own (True only if that cell is actually
    measured). Any other class: refused by name —
    a budget proven on one class claims NOTHING
    about another (the S-413 law)."""
    _require_kind(kind)
    _require_class(proven_on)
    _require_class(claimed_for)
    if proven_on != claimed_for:
        raise CpuHonestyError(
            "cross_class_claim",
            f"A {kind} budget proven on {proven_on} claims "
            f"nothing about {claimed_for}.")
    return claim_for(kind, claimed_for).status == "measured"


def restatement() -> dict:
    """The register as JSON-safe data: one entry per
    cell, plus each class's status in words."""
    return {
        "entries": [{
            "kind": e.kind, "hardware_class": e.hardware_class,
            "class_label": e.class_label, "budget": e.budget,
            "unit": e.unit, "source": e.source,
            "workload": e.workload, "status": e.status,
            "measured": e.measured, "machine": e.machine}
            for e in budget_register()],
        "classes": {cls: class_status(cls) for cls in HARDWARE_CLASSES},
    }


def render_cpu_honesty_page(data: dict) -> str:
    """The restatement page: every cell with its
    budget, source and status in words; NOT PROVEN
    cells say so plainly and carry no number but
    the stated budget. All values pass through
    S-010 escaping."""
    parts = [
        "<h1>CPU honesty — budgets per hardware class</h1>",
        "<p>Every performance budget (S-073 clone, S-217 "
        "search, S-395 browse) restated per hardware class. "
        "A budget proven on one class claims nothing about "
        "another.</p>",
        '<ul class="cpu-honesty-register">']
    for e in data["entries"]:
        if e["status"] == "measured":
            words = (f"measured {e['measured']} {e['unit']} on "
                     f"{e['machine']} ({e['source']})")
        else:
            words = "NOT PROVEN on this class"
        text = (f"{e['kind']} on {e['class_label']}: budget "
                f"{e['budget']} {e['unit']} ({e['source']}) — {words}")
        parts.append(f"<li>{escape_html_text(text)}</li>")
    parts.append("</ul>")
    return "\n".join(parts)
