"""Support matrix ratified (S-405).

Roadmap S-405: **Support matrix ratified -- the promise
written down: server on Linux, Windows, macOS; CPUs
x86-64 and ARM64, Raspberry Pi 5 as the floor; the
matrix lives in research file 45 with every cell
initially marked NOT PROVEN.**

This module is that matrix as data plus judgement.
The promise is Part XXII's founding law (Volmarr,
2026-10-29: cross platform completely in all ways)
written down as cells. Part XXII's own law governs
every cell: a cell is PROVEN only when its battery
has run in that cell; everything else reads NOT
PROVEN, in those words. At ratification every cell
reads NOT PROVEN -- including Linux x86-64, where
development and the counted runs to date happened:
S-399 judged claim F-02 (C-10) NOT PROVEN, and no
cell flips on wording, only on a counted run in
the cell, owned by the slice named on the cell
(S-415 for Linux ARM, S-416 the portability gate,
S-408 filesystems, S-410..S-412 service forms,
S-414 browser and device reach).

The matrix lives in research file 45
(research/45-cross-platform-architecture.md), whose
engineering direction names the four primary cells
-- Linux x86-64, Linux ARM64 (Pi 5), Windows x86-64,
macOS ARM64 -- and gives filesystems and real
SSH/HTTP deployment their own cells. Windows ARM64
and macOS x86-64 are NOT promised: they are outside
the ratified promise and no cell claims them.

Sources, all read from disk at build time:
- Roadmap Part XXII preamble and S-405..S-416.
- research/45-cross-platform-architecture.md.
- S-399 claims register: F-02 NOT PROVEN
  (docs/CLAIMS_REGISTER.md, claim C-10).
- S-395: Pi-class performance budgets MEASURED on a
  Raspberry Pi 5 -- budgets measured are not a
  battery run; the Linux ARM64 cell stays NOT
  PROVEN until S-415.

No migration and no new taxonomy event: the schema
stands at 140 and the taxonomy stands at 142.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["MATRIX_CELLS", "MatrixCell", "STATUSES",
    "DIMENSIONS", "EXPECTED_COUNT", "judge_matrix",
    "matrix_counts", "cells_by_dimension",
    "audit_matrix", "render_matrix",
    "render_matrix_section", "render_matrix_log"]

STATUSES = ("not_proven",)
DIMENSIONS = ("os_cpu", "filesystem", "deployment",
    "service", "reach")
EXPECTED_COUNT = 12
MATRIX_DOC = "docs/SUPPORT_MATRIX.md"
RESEARCH_FILE = "research/45-cross-platform-architecture.md"
SECTION_BEGIN = "<!-- S-405 support matrix: begin -->"
SECTION_END = "<!-- S-405 support matrix: end -->"
OVERCLAIM_PHRASES = ("production-proven",
    "production proven", "fully implemented and proven",
    "shipped and proven", "complete and proven")


@dataclass(frozen=True)
class MatrixCell:
    cell_id: str
    dimension: str   # one of DIMENSIONS
    title: str
    platform: str    # OS / surface the cell promises
    cpu: str         # CPU family, or the surface kind
    floor: str       # weakest hardware/surface promised
    status: str      # one of STATUSES
    proof_slice: str  # slice that can flip this cell
    proof: str       # the counted run that flips it
    note: str


def _c(cid, dim, title, platform, cpu, floor, slice_,
       proof, note):
    return MatrixCell(cid, dim, title, platform, cpu,
                      floor, "not_proven", slice_,
                      proof, note)

MATRIX_CELLS = (
    _c("linux-x86-64", "os_cpu",
        "Server on Linux, x86-64", "Linux", "x86-64",
        "ordinary laptop, desktop or server",
        "S-416",
        "The full battery (S-394) executed green on a Linux x86-64 host and counted as this cell's run at the portability gate",
        "Development and every counted run to date happened on Linux x86-64 hosts, and S-399 still judged the matrix claim F-02 NOT PROVEN: no run has been counted as this cell's Part XXII proof. Ratified NOT PROVEN like every other cell."),
    _c("linux-arm64-pi5", "os_cpu",
        "Server on Linux, ARM64 -- Raspberry Pi 5 floor", "Linux", "ARM64",
        "Raspberry Pi 5 (the floor: nothing weaker is promised)",
        "S-415",
        "The full battery (S-394) executed green on the Raspberry Pi 5, counted and recorded",
        "Pi-class performance budgets were MEASURED on a Raspberry Pi 5 at S-395; measured budgets are not a battery run. The cell flips only at S-415. Hardware weaker than a Pi 5 is outside the promise."),
    _c("windows-x86-64", "os_cpu",
        "Server on Windows, x86-64", "Windows", "x86-64",
        "ordinary laptop, desktop or server",
        "S-416",
        "The full battery executed green on Windows x86-64 and counted at the portability gate",
        "No Samverk battery has ever run on Windows. Git, SSH and service behaviour differ there (research 45); a Linux pass claims nothing about this cell. Its service form is the windows-service cell (S-410)."),
    _c("macos-arm64", "os_cpu",
        "Server on macOS, Apple silicon", "macOS", "ARM64",
        "Apple silicon Mac",
        "S-416",
        "The full battery executed green on macOS on Apple silicon and counted at the portability gate",
        "The second ARM64 home. No Samverk battery has ever run on macOS. Its service form is the launchd-service cell (S-411). macOS on Intel (x86-64) is not promised and has no cell."),
    _c("fs-case-sensitive", "filesystem",
        "Repository storage on case-sensitive filesystems", "filesystem", "n/a",
        "the filesystems Linux servers ship by default",
        "S-408",
        "The filesystem battery (two names differing only by case handled deterministically) run green on a case-sensitive filesystem",
        "Half of S-408's filesystem law. Correctness here is the common case today but is not counted as this cell's proof until S-408 runs it as one."),
    _c("fs-case-insensitive", "filesystem",
        "Repository storage on case-insensitive filesystems", "filesystem", "n/a",
        "the default filesystems of Windows and macOS",
        "S-408",
        "The filesystem battery run green on a case-insensitive filesystem, the Foo/foo collision handled deterministically",
        "The hard half of S-408's law and a named threat in research 45: two repositories whose names differ only by case collide on these filesystems. Never exercised by any counted run."),
    _c("deploy-real-sshd", "deployment",
        "Real SSH daemon deployment", "deployment", "n/a",
        "a stock sshd on a promised OS",
        "Part XXII (S-415/S-416 cells)",
        "The transport battery runs against a real sshd in a proven cell, counted green",
        "Carries the scoped remainder of claim F-01 (S-399): stock-git smart-HTTP and SSH forced-command harnesses are green, the real-sshd cell was skipped on the proving host and remains NOT PROVEN. Research 45 gives real deployment its own cells."),
    _c("deploy-real-http", "deployment",
        "Real HTTP deployment", "deployment", "n/a",
        "the server answering real HTTP clients on a promised OS",
        "Part XXII (S-415/S-416 cells)",
        "The battery's HTTP transport runs counted green against the real server in a proven cell",
        "Research 45: Python http.server production caveats apply on every OS, so infrastructure security needs platform-by-platform proof. Live-instance walks on Linux exist (S-397); no Part XXII cell run has been counted."),
    _c("service-systemd", "service",
        "Linux service form: systemd", "Linux", "any promised CPU",
        "a systemd Linux host",
        "S-412",
        "The S-348 systemd units re-verified as one of three equal citizens, counted",
        "The units exist (S-348); S-412 re-verifies them as an equal citizen beside the Windows and launchd forms -- no feature may exist on Linux that the service model forbids elsewhere."),
    _c("service-windows", "service",
        "Windows service form: native Windows service", "Windows", "x86-64",
        "a Windows host, no Docker and no WSL requirement",
        "S-410",
        "Samverk installed and running as a native Windows service, install walk documented to Part XVIII's standard, counted",
        "Nothing exists yet: no Windows service wrapper, no install walk. Native install only -- the standing No Docker law binds this cell in its own words (S-410)."),
    _c("service-launchd", "service",
        "macOS service form: launchd", "macOS", "ARM64",
        "an Apple silicon Mac",
        "S-411",
        "Samverk installed and running under launchd, install walk documented to Part XVIII's standard, counted",
        "Nothing exists yet: no launchd plist, no install walk. Service packaging is a platform-specific adapter, never a container workaround (research 45)."),
    _c("browser-device-reach", "reach",
        "Browser and device reach of the web UI", "web UI", "n/a",
        "current Chrome, Firefox, Safari and Edge; phone and tablet browsers",
        "S-414",
        "The web UI verified in each named browser and on phone and tablet browsers (small screens, touch targets per S-386), counted",
        "S-414's own words: the device matrix is the test list. No cross-browser verification has been counted; desktop-only development proves nothing about this cell."),
)


def matrix_counts(cells=MATRIX_CELLS) -> dict:
    counts = {d: 0 for d in DIMENSIONS}
    for cell in cells:
        counts[cell.dimension] = counts.get(cell.dimension, 0) + 1
    counts["not_proven"] = sum(
        1 for cell in cells if cell.status == "not_proven")
    counts["total"] = len(cells)
    return counts


def cells_by_dimension(dimension, cells=MATRIX_CELLS) -> tuple:
    return tuple(c for c in cells if c.dimension == dimension)


def judge_matrix(cells=MATRIX_CELLS) -> tuple:
    """Problems with the matrix as data; empty = lawful.
    Ratification invariants: the census holds, ids are
    unique, every cell names its platform, floor, proof
    slice and proof condition, the four primary OS x CPU
    cells of research 45 are present, the Pi 5 floor is
    named, and -- the point of S-405 -- EVERY cell reads
    NOT PROVEN: no cell may be ratified proven, and no
    cell text may carry an overclaim phrase."""
    problems = []
    if len(cells) != EXPECTED_COUNT:
        problems.append("matrix holds %d cells, expected %d"
                        % (len(cells), EXPECTED_COUNT))
    seen = set()
    for cell in cells:
        if cell.cell_id in seen:
            problems.append("duplicate cell id %s" % cell.cell_id)
        seen.add(cell.cell_id)
        if cell.dimension not in DIMENSIONS:
            problems.append("%s: dimension %r is not a matrix dimension"
                            % (cell.cell_id, cell.dimension))
        if cell.status not in STATUSES:
            problems.append("%s: status %r is not a ratified status -- "
                            "at S-405 every cell is NOT PROVEN"
                            % (cell.cell_id, cell.status))
        for field in ("title", "platform", "cpu", "floor",
                      "proof_slice", "proof", "note"):
            if not getattr(cell, field).strip():
                problems.append("%s: empty %s" % (cell.cell_id, field))
        blob = " ".join((cell.title, cell.note, cell.proof)).lower()
        for phrase in OVERCLAIM_PHRASES:
            if phrase in blob:
                problems.append("%s: overclaim %r" % (cell.cell_id, phrase))
    ids = {c.cell_id for c in cells}
    for needed in ("linux-x86-64", "linux-arm64-pi5",
                   "windows-x86-64", "macos-arm64"):
        if needed not in ids:
            problems.append("primary cell %s missing" % needed)
    by_id = {c.cell_id: c for c in cells}
    pi = by_id.get("linux-arm64-pi5")
    if pi is not None and "Raspberry Pi 5" not in pi.floor:
        problems.append("linux-arm64-pi5: floor does not name the Raspberry Pi 5")
    counts = matrix_counts(cells)
    if counts["not_proven"] != len(cells):
        problems.append("ratified matrix holds a cell that is not NOT PROVEN")
    return tuple(problems)


def audit_matrix(root) -> tuple:
    """Check the matrix against disk: the matrix document
    and research file 45 both exist and carry every cell
    id, and research file 45 carries the ratified matrix
    section with NOT PROVEN stated in words. Problems
    returned by name; empty = pass."""
    problems = list(judge_matrix())
    root = Path(root)
    doc = root / MATRIX_DOC
    if not doc.exists():
        problems.append("matrix doc missing: %s" % MATRIX_DOC)
    else:
        text = doc.read_text(encoding="utf-8")
        for cell in MATRIX_CELLS:
            if cell.cell_id not in text:
                problems.append("matrix doc omits cell %s" % cell.cell_id)
        if "NOT PROVEN" not in text:
            problems.append("matrix doc never states NOT PROVEN")
    research = root / RESEARCH_FILE
    if not research.exists():
        problems.append("research file 45 missing: %s" % RESEARCH_FILE)
    else:
        text = research.read_text(encoding="utf-8")
        if SECTION_BEGIN not in text or SECTION_END not in text:
            problems.append("research file 45 carries no ratified S-405 matrix section")
        for cell in MATRIX_CELLS:
            if cell.cell_id not in text:
                problems.append("research file 45 omits cell %s" % cell.cell_id)
        if "NOT PROVEN" not in text:
            problems.append("research file 45 never states NOT PROVEN")
    return tuple(problems)


def _status_words(status):
    return "NOT PROVEN" if status == "not_proven" else status.upper()


def render_matrix_section(cells=MATRIX_CELLS) -> str:
    """The ratified matrix as it lives in research file
    45: the promise in a table, every cell NOT PROVEN,
    each cell naming the slice whose counted run can
    flip it. Delimited by the S-405 markers so the
    runner can refresh it in place."""
    lines = [
        SECTION_BEGIN,
        "",
        "## Support matrix (ratified at S-405)",
        "",
        "The promise, written down at S-405: the Samverk",
        "server is supported on Linux, Windows and macOS,",
        "on x86-64 and ARM64 CPUs, with the Raspberry Pi 5",
        "as the floor. The law module is",
        "`samverk/support_matrix.py`; the rendered matrix",
        "document is `docs/SUPPORT_MATRIX.md`; the counted",
        "log is `docs/support-matrix-s405.md`.",
        "",
        "A cell is PROVEN only when its battery has run in",
        "that cell (Part XXII's law). At ratification every",
        "cell below is **NOT PROVEN** -- no platform is",
        "claimed proven without a real run on that",
        "platform, and no cell flips on wording.",
        "",
        "| Cell | Dimension | Platform | CPU / surface | Floor | Status | Flips at |",
        "|---|---|---|---|---|---|---|",
    ]
    for cell in cells:
        lines.append("| %s | %s | %s | %s | %s | NOT PROVEN | %s |"
                     % (cell.cell_id, cell.dimension, cell.platform,
                        cell.cpu, cell.floor, cell.proof_slice))
    lines += [
        "",
        "Windows on ARM64 and macOS on x86-64 are not",
        "promised and have no cells. S-415 flips the",
        "Linux ARM64 cell, S-416 is the portability gate",
        "for the Windows and macOS cells, S-408 owns the",
        "filesystem cells, S-410..S-412 the service forms,",
        "and S-414 the browser and device reach cell.",
        "",
        SECTION_END,
    ]
    return "\n".join(lines)


def render_matrix(cells=MATRIX_CELLS) -> str:
    """The matrix document: the promise written down,
    plain words first; every cell with its status in
    words, its floor, and the counted run that can
    flip it."""
    counts = matrix_counts(cells)
    lines = [
        "# Support matrix (S-405)",
        "",
        "In plain words: this is Samverk's cross-platform",
        "promise, written down and ratified. The server is",
        "promised on Linux, Windows and macOS, on x86-64",
        "and ARM64 CPUs, with the Raspberry Pi 5 as the",
        "floor -- nothing weaker is promised. The matrix",
        "lives in research file 45",
        "(`research/45-cross-platform-architecture.md`);",
        "this document is its rendered form, judged from",
        "the law module `samverk/support_matrix.py`.",
        "",
        "Every cell is marked NOT PROVEN. That is the",
        "honest state at ratification: a cell is PROVEN",
        "only when its battery has run in that cell, and",
        "no cell's Part XXII run has been counted yet --",
        "not even Linux x86-64, where the development",
        "happened and where S-399 still judged the matrix",
        "claim (F-02) NOT PROVEN. Cells flip on counted",
        "runs, never on wording.",
        "",
        "The battery is `tests/test_support_matrix.py`;",
        "the runner is `tools/run_support_matrix.py`;",
        "the counted log ships at",
        "`docs/support-matrix-s405.md`.",
        "",
        "## Census",
        "",
        "- Matrix cells: %d" % counts["total"],
        "- NOT PROVEN: %d (every cell)" % counts["not_proven"],
        "- OS x CPU cells: %d" % counts["os_cpu"],
        "- Filesystem cells: %d" % counts["filesystem"],
        "- Deployment cells: %d" % counts["deployment"],
        "- Service-form cells: %d" % counts["service"],
        "- Reach cells: %d" % counts["reach"],
        "- Schema 140, taxonomy 142 stand (no migration,",
        "  no new taxonomy event in this slice)",
        "",
        "## The promise",
        "",
        "- Server operating systems: Linux, Windows, macOS",
        "- CPUs: x86-64 and ARM64",
        "- Floor: Raspberry Pi 5 -- nothing weaker promised",
        "- Not promised: Windows on ARM64, macOS on x86-64,",
        "  hardware weaker than a Raspberry Pi 5",
        "- Installs are native on every platform; no Docker",
        "  anywhere in the promise (standing law)",
        "",
        "## The cells",
        "",
    ]
    for cell in cells:
        lines += [
            "### %s -- %s" % (cell.cell_id, cell.title),
            "",
            "- Status: %s" % _status_words(cell.status),
            "- Dimension: %s" % cell.dimension,
            "- Platform: %s" % cell.platform,
            "- CPU / surface: %s" % cell.cpu,
            "- Floor: %s" % cell.floor,
            "- Flips at: %s" % cell.proof_slice,
            "- Proof that flips it: %s" % cell.proof,
            "- Note: %s" % cell.note,
            "",
        ]
    lines += [
        "## How cells flip",
        "",
        "- S-415 runs the full battery on the Raspberry",
        "  Pi 5: the linux-arm64-pi5 cell flips on its",
        "  counted run, and no other cell moves.",
        "- S-416 is the portability gate: the full battery",
        "  on Windows x86-64 and macOS (Apple silicon),",
        "  and the claims register is published with every",
        "  promised cell PROVEN with its counted run or",
        "  NOT PROVEN in plain words.",
        "- S-408 owns the filesystem cells, S-410..S-412",
        "  the three service forms as equal citizens,",
        "  S-414 the browser and device reach cell.",
        "- A budget measured on a class (S-413) claims",
        "  nothing about another class, and a cell proven",
        "  on one platform claims nothing about any other.",
        "",
    ]
    return "\n".join(lines)


def render_matrix_log(cells=MATRIX_CELLS) -> str:
    counts = matrix_counts(cells)
    lines = [
        "# Support matrix -- S-405",
        "",
        "The cross-platform promise ratified as a matrix,",
        "judged at 401/416 against the tree as it stands",
        "(S-402, the founder walk, still open in roadmap",
        "order; this slice banks after S-402..S-404).",
        "The full matrix ships at `docs/SUPPORT_MATRIX.md`",
        "and lives in research file 45",
        "(`research/45-cross-platform-architecture.md`);",
        "this is its counted log.",
        "",
        "Matrix cells judged: %d" % counts["total"],
        "",
    ]
    for dim in DIMENSIONS:
        lines.append("- %s: %d" % (dim, counts[dim]))
    lines += ["", "| Cell | Status | Flips at |", "|---|---|---|"]
    for cell in cells:
        lines.append("| %s | NOT PROVEN | %s |"
                     % (cell.cell_id, cell.proof_slice))
    lines += ["", "Verdict: **RATIFIED -- every cell NOT PROVEN**", ""]
    return "\n".join(lines)
