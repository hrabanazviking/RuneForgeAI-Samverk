"""Final census to Volmarr (S-404).

Roadmap S-404: **Final census to Volmarr -- what
stands proven, what stands NOT PROVEN, what stands
refused -- counted, plain, and complete. The roadmap
closes; the together-work continues.**

This module is that census as data plus judgement.
It has two halves. The slice accounting reconciles
the whole 416-slice roadmap: every slice is banked,
founder-pending, built-but-unbanked, this slice, or
not yet done, and the counts sum to 416 exactly.
The findings half states, in plain words, what the
campaign's own counted evidence proves, what it
leaves NOT PROVEN, what it refused, what it deferred,
and what stands open. No status is upgraded here:
a counted run with failures is not green, an unplaced
tag is NOT PLACED, an unsigned package is NOT PROVEN
as signed, and the founder walk (S-402) is NOT DONE
until Volmarr walks it himself.

Sources, all read from disk at build time:
- Remote + WAVE_PLAN.md at the seat: banked 401/416,
  origin/main 080cf8e, last banked S-401 at
  2026-11-22 18:15 EST (ls-remote verified).
- S-402 (roadmap text): Volmarr's own unaided
  usability walk -- founder-only, NOT DONE.
- S-403 (team-02 commit ad97af2 on base 080cf8e):
  built + committed, battery 13 OK, neighbours
  102 OK -- held unmerged, banks only after S-402.
- Wave verdicts in WAVE_PLAN.md: wave380 Ran 6029,
  fails 15; S-393 counted master run Ran 6129,
  Passed 6110, Failed 15, Skipped 4; wave400
  Ran 6190, skipped 4, fails 12, wall 2511.9s
  (hidden_files/shards-wave400-launch.log). Every
  failure in all three runs is the known stale
  schema/taxonomy-pin class (families actual
  {auth:34, repo:92, admin:16} vs pinned {auth:33,
  repo:92, admin:13}; verbs 142 vs 138); no failure
  outside that class, and no run is green.
- S-399 claims register final (17 rows): 8 proven,
  4 proven scoped, 3 NOT PROVEN (F-02, F-10, F-11),
  1 open (F-17), 1 historical; F-01's real-sshd
  cell a scoped NOT PROVEN remainder.
- S-400: the release package ships unsigned -- no
  maintainer key on this box, none fabricated; as
  a proof of signing it stands NOT PROVEN (the
  S-403 seed carries the remainder itself as open,
  owned by Volmarr; nothing here upgrades either
  statement).
- S-403 seed census: 24 items -- 6 deferred,
  5 refused, 5 NOT PROVEN, 5 open, 1 founder,
  2 served by existing roads.
- Roadmap Part XXII: S-405..S-416 not yet done.

No migration and no new taxonomy event: the schema
stands at 140 and the taxonomy stands at 142.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["SLICE_ROWS", "FINDING_ROWS", "ALL_ROWS",
    "CensusRow", "STATUSES", "ROADMAP_SLICES",
    "BANKED_SLICES", "EXPECTED_SLICE_ROWS",
    "EXPECTED_FINDING_ROWS", "judge_census",
    "census_counts", "slice_accounting",
    "rows_by_status", "audit_census",
    "render_census", "render_census_log"]

STATUSES = ("banked", "founder_pending",
    "built_unbanked", "this_slice", "not_yet_done",
    "not_green", "proven", "not_proven", "open",
    "historical", "refused", "deferred")
ROADMAP_SLICES = 416
BANKED_SLICES = 401
EXPECTED_SLICE_ROWS = 16
EXPECTED_FINDING_ROWS = 27
CENSUS_DOC = "docs/FINAL_CENSUS.md"


@dataclass(frozen=True)
class CensusRow:
    row_id: str
    title: str
    source: str      # slice / run / register deciding it
    status: str      # one of STATUSES
    count: int       # slices counted (slice rows); 0 else
    note: str


def _r(rid, title, source, status, count, note):
    return CensusRow(rid, title, source, status, count, note)


SLICE_ROWS = (
    _r("slices-banked-401", "Slices S-001..S-401 banked", "WAVE_PLAN.md / git ls-remote (origin/main 080cf8e)",
        "banked", 401,
        "Banked strictly in roadmap order, one slice per commit, ls-remote verified. Last banked: S-401 at 2026-11-22 18:15 EST."),
    _r("s402-founder-walk", "S-402 Volmarr's usability walk", "S-402",
        "founder_pending", 1,
        "NOT DONE. Founder-only by the roadmap's own text: Volmarr, unaided, on a fresh instance -- account, token, repo, push, mirror. No worker can build it and this census claims nothing about its outcome. Banking head: S-403 banks only after this slice."),
    _r("s403-successor-seed", "S-403 Successor roadmap seed", "S-403 (team-02 ad97af2 on base 080cf8e)",
        "built_unbanked", 1,
        "BUILT + COMMITTED, NOT banked: commit ad97af2, own battery 13 OK, neighbours 102 OK. Held unmerged in roadmap order; it banks only after S-402 lands."),
    _r("s404-final-census", "S-404 Final census to Volmarr", "S-404 (this slice, team-03)",
        "this_slice", 1,
        "This census itself: built on banked base 080cf8e, banks only after S-402 and S-403 in roadmap order. Its own battery and neighbours are counted in its counted log; it claims no banking."),
    _r("s405-support-matrix", "S-405 Support matrix ratified", "S-405 (Part XXII)",
        "not_yet_done", 1,
        "NOT YET DONE. The support promise (Linux, Windows, macOS; x86-64 and ARM64, Pi 5 floor) is not yet written down as the ratified matrix; every cell stands NOT PROVEN until its battery runs in that cell."),
    _r("s406-platform-seam", "S-406 Platform seam audit", "S-406 (Part XXII)",
        "not_yet_done", 1, "NOT YET DONE. No seam audit has run; stray platform calls outside one platform module are uncounted."),
    _r("s407-dependency-register", "S-407 Dependency replaceability register", "S-407 (Part XXII)",
        "not_yet_done", 1, "NOT YET DONE. No replaceability register exists yet for the git binaries, SQLite, or the admitted cryptography dependency."),
    _r("s408-filesystem-law", "S-408 Filesystem law", "S-408 (Part XXII)",
        "not_yet_done", 1, "NOT YET DONE. Case-sensitive vs case-insensitive storage correctness, including the two-names-differing-only-by-case collision, is untested as this slice's battery."),
    _r("s409-path-encoding", "S-409 Path and encoding discipline", "S-409 (Part XXII)",
        "not_yet_done", 1, "NOT YET DONE. One canonical stored form for refs, paths and config is not yet proven as this slice's battery."),
    _r("s410-windows-service", "S-410 Windows service", "S-410 (Part XXII)",
        "not_yet_done", 1, "NOT YET DONE. Samverk as a native Windows service (no Docker, no WSL requirement) is NOT PROVEN."),
    _r("s411-macos-service", "S-411 macOS service", "S-411 (Part XXII)",
        "not_yet_done", 1, "NOT YET DONE. Samverk under launchd is NOT PROVEN."),
    _r("s412-linux-parity", "S-412 Linux services parity", "S-412 (Part XXII)",
        "not_yet_done", 1, "NOT YET DONE. The systemd units are not yet re-verified as one of three equal service citizens in this part."),
    _r("s413-cpu-honesty", "S-413 CPU honesty", "S-413 (Part XXII)",
        "not_yet_done", 1, "NOT YET DONE. Performance budgets are not yet restated per hardware class; a budget proven on one class claims nothing about another."),
    _r("s414-browser-reach", "S-414 Browser and device reach", "S-414 (Part XXII)",
        "not_yet_done", 1, "NOT YET DONE. The web UI is not yet verified across Chrome, Firefox, Safari, Edge and phone/tablet browsers as this slice's matrix."),
    _r("s415-battery-arm", "S-415 Battery port: Linux on ARM", "S-415 (Part XXII)",
        "not_yet_done", 1, "NOT YET DONE. The full battery has not run green on the Raspberry Pi 5 as this slice's counted run; the Linux x ARM64 cell stands NOT PROVEN."),
    _r("s416-battery-ports-gate", "S-416 Battery ports: Windows and macOS + the portability gate", "S-416 (Part XXII)",
        "not_yet_done", 1, "NOT YET DONE. No Windows or macOS battery run exists; the portability gate has not been judged. The founding law is declared kept only for proven cells, and no Part XXII cell is proven yet."),
)


FINDING_ROWS = (
    _r("wave380-counted-run", "Wave 371-380 counted run", "WAVE_PLAN.md (sharded runner, shards-wave380)",
        "not_green", 0,
        "Ran 6029, skipped 4, fails 15. Every failure is the known stale schema/taxonomy-pin class (families actual {auth:34, repo:92, admin:16} vs pinned {auth:33, repo:92, admin:13}; verbs 142 vs 138). No failure outside that class; the run is NOT GREEN."),
    _r("s393-counted-master-run", "S-393 counted master run (wave 381-390 counted run)", "S-393 / docs/COUNTED_MASTER_RUN.md",
        "not_green", 0,
        "Ran 6129, Passed 6110, Failed 15, Skipped 4 (all named). Same stale-pin class as wave380. A counted run with 15 failures is NOT GREEN, however familiar the class."),
    _r("wave400-counted-run", "Wave 391-400 counted run (wave400)", "WAVE_PLAN.md keeper note 2026-11-22 18:32 EST / hidden_files/shards-wave400-launch.log",
        "not_green", 0,
        "FINISHED: Ran 6190, skipped 4, fails 12, wall 2511.9s, FAILED. All 12 failures classified from the shard logs: every one is the known stale schema/taxonomy-pin class; NO failure outside that class, so no fix-forward work arises. The run is NOT GREEN."),
    _r("v1-tag-placement", "S-401 v1.0 tag placement", "S-401 / samverk/v1_tag.py",
        "not_proven", 0,
        "Tag NOT PLACED and NOT PROVEN as placed. S-401's law tags only a counted-GREEN tree; the wave400 counted run over the counted tree 6ede324e is not green (12 stale-pin fails), so the tag stays honestly pending. The road is fix forward, a fresh counted run over the fixed tree, then the tag -- a changed tree is not the counted tree. Never claim green."),
    _r("claims-proven", "Claims register: proven claims", "S-399 / docs/claims-register-final-s399.md",
        "proven", 0,
        "8 of 17 final claims stand PROVEN: F-05 native CI, F-06 fresh install, F-07 upgrade drill, F-08 Samtal seam, F-09 v1.0 acceptance battery, F-12 guides walked live, F-13 research corpus, F-15 AGPL-3.0."),
    _r("claims-proven-scoped", "Claims register: proven-scoped claims", "S-399 / docs/claims-register-final-s399.md",
        "proven", 0,
        "4 of 17 final claims stand PROVEN within their stated scope only: F-01 git client interop, F-03 design lawbook gate, F-04 mirroring of Volmarr's originals, F-14 native systemd running with no Docker. The scope is part of the claim; nothing wider is proven."),
    _r("claims-f02-platform-matrix", "Claim F-02: server on Windows, macOS, ARM to Pi", "S-399 (claim F-02)",
        "not_proven", 0, "NOT PROVEN. Owned by Part XXII (S-405..S-416), all not yet done; no matrix cell has a counted battery run."),
    _r("claims-f10-live-composition", "Claim F-10: feature services composed into one running forge", "S-399 (claim F-10)",
        "not_proven", 0, "NOT PROVEN. The founder walk (S-402) owns part of this proof and is NOT DONE; the composition claim flips only on that live proof."),
    _r("claims-f11-full-suite-green", "Claim F-11: the full suite is green", "S-399 (claim F-11) / counted runs",
        "not_proven", 0, "NOT PROVEN. The latest counted run (wave400) reads Ran 6190, fails 12 -- not green. No counted run at the close of this census reads zero failures."),
    _r("claims-f01-real-sshd-cell", "Claim F-01 scoped remainder: real-sshd cell", "S-399 (claim F-01)",
        "not_proven", 0, "NOT PROVEN as a scoped remainder: F-01 stands proven scoped, but its real-sshd cell remains a named NOT PROVEN remainder owned by Part XXII."),
    _r("claims-f17-readme-wordings", "Claim F-17: two README wordings", "S-399 (claim F-17)",
        "open", 0, "OPEN, owned by Volmarr alone: two README wordings only he can settle. This census does not touch any README.md."),
    _r("claims-historical", "Claims register: historical rows", "S-399 / docs/claims-register-final-s399.md",
        "historical", 0, "1 of 17 final rows is historical (F-16): dated position statements, true of their dates, claiming nothing about the present tree."),
    _r("release-signing-s400", "S-400 release package signing", "S-400 / WAVE_PLAN.md coordinator note 2026-11-22 17:45 EST",
        "not_proven", 0,
        "NOT PROVEN. The S-400 package ships unsigned (tarball SHA-256 d49482e6c3c8b4c4dda9e2a13f93078f2bedf780173d23a702e03497eb015693 re-verified at banking): there is no maintainer key on this box and none was fabricated. The S-403 seed carries the signing remainder as open, owned by Volmarr; as a proof that the package is signed, it stands NOT PROVEN."),
    _r("refused-oci", "Refused: OCI container packages", "S-264 / S-403 seed",
        "refused", 0, "REFUSED at the S-264 package verdict and carried refused in the S-403 seed. Revisited only by Volmarr's word."),
    _r("refused-docker", "Refused: Docker", "roadmap standing exclusions (founding) / S-264",
        "refused", 0, "REFUSED as standing law: not for Samverk, not for its runner, not for its docs' examples. Native installs only."),
    _r("refused-federation", "Refused: federation between instances", "roadmap standing exclusions (founding)",
        "refused", 0, "REFUSED at founding: no federation between Samverk instances or Samtal villages."),
    _r("refused-hosted-service", "Refused: hosted-service ambitions", "roadmap standing exclusions (founding)",
        "refused", 0, "REFUSED at founding: Samverk is software its owner runs, not a platform operated for strangers."),
    _r("refused-invented-facts", "Refused: AI features that invent facts", "roadmap standing exclusions (founding)",
        "refused", 0, "REFUSED at founding: no generated summaries presented as truth; anything automated is labelled and checkable."),
    _r("deferred-graphql", "Deferred: GraphQL API layer", "S-253 / S-403 seed",
        "deferred", 0, "DEFERRED at the S-253 verdict, revisited and kept deferred by S-403. No endpoint, schema or resolver exists."),
    _r("deferred-package-python", "Deferred: Python package registry", "S-264 / S-403 seed",
        "deferred", 0, "DEFERRED at the S-264 package verdict; no Python registry is built or claimed."),
    _r("deferred-package-javascript", "Deferred: JavaScript package registry", "S-264 / S-403 seed",
        "deferred", 0, "DEFERRED at the S-264 package verdict; no JavaScript registry is built or claimed."),
    _r("deferred-discussion-polls", "Deferred: discussion polls", "S-282 / S-286 / S-403 seed",
        "deferred", 0, "DEFERRED: discussions core landed (S-283..S-285); polls were deferred and S-286 published the polls position. Not built."),
    _r("deferred-discussion-badges", "Deferred: rich discussion badges", "S-282 / S-403 seed",
        "deferred", 0, "DEFERRED at the S-282 discussions verdict. Not built."),
    _r("deferred-signing-verifier", "Deferred: signing verifier", "S-263 / S-305 / S-403 seed",
        "deferred", 0, "DEFERRED in the S-403 seed (signing seam S-263, verifier road S-305). No verifier is claimed as built."),
    _r("open-study-24", "Open study 24 (GraphQL)", "S-398 (research corpus audit)",
        "open", 0, "OPEN: study 24 of the 46-file research corpus stands honestly open, owned forward by the successor roadmap (S-403 seed)."),
    _r("open-study-26", "Open study 26 (packages)", "S-398 (research corpus audit)",
        "open", 0, "OPEN: study 26 stands honestly open, owned forward by the successor roadmap (S-403 seed)."),
    _r("open-study-30", "Open study 30 (discussions)", "S-398 (research corpus audit)",
        "open", 0, "OPEN: study 30 stands honestly open, owned forward by the successor roadmap (S-403 seed). The other 43 study files hold completed studies (S-398)."),
)

ALL_ROWS = SLICE_ROWS + FINDING_ROWS


def slice_accounting(rows=SLICE_ROWS) -> dict:
    """Slices counted per slice-row status; the
    accounting holds only when total == 416."""
    out = {}
    for row in rows:
        out[row.status] = out.get(row.status, 0) + row.count
    out["total"] = sum(r.count for r in rows)
    return out


def census_counts(rows=ALL_ROWS) -> dict:
    counts = {s: 0 for s in STATUSES}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    counts["total"] = len(rows)
    return counts


def rows_by_status(status, rows=ALL_ROWS) -> tuple:
    return tuple(r for r in rows if r.status == status)


def judge_census(slice_rows=SLICE_ROWS,
                 finding_rows=FINDING_ROWS) -> tuple:
    """Problems with the census as data; empty =
    lawful. The slice accounting must reconcile the
    whole roadmap (416 = 401 banked + S-402 + S-403 +
    S-404 + S-405..S-416), every row must name its
    source and carry a lawful status, and the census
    must name at least one NOT PROVEN row, one
    refused row, and the unplaced v1.0 tag -- a
    census that upgrades any of those is unlawful."""
    problems = []
    if len(slice_rows) != EXPECTED_SLICE_ROWS:
        problems.append("slice rows %d, expected %d"
                        % (len(slice_rows), EXPECTED_SLICE_ROWS))
    if len(finding_rows) != EXPECTED_FINDING_ROWS:
        problems.append("finding rows %d, expected %d"
                        % (len(finding_rows), EXPECTED_FINDING_ROWS))
    acct = slice_accounting(slice_rows)
    if acct["total"] != ROADMAP_SLICES:
        problems.append("slice accounting totals %d, expected %d"
                        % (acct["total"], ROADMAP_SLICES))
    if acct.get("banked", 0) != BANKED_SLICES:
        problems.append("banked count %d, expected %d"
                        % (acct.get("banked", 0), BANKED_SLICES))
    if acct.get("not_yet_done", 0) != 12:
        problems.append("not-yet-done slices %d, expected 12 (S-405..S-416)"
                        % acct.get("not_yet_done", 0))
    seen = set()
    for row in slice_rows + finding_rows:
        if row.row_id in seen:
            problems.append("duplicate row id %s" % row.row_id)
        seen.add(row.row_id)
        if row.status not in STATUSES:
            problems.append("%s: status %r is not a census status"
                            % (row.row_id, row.status))
        for field in ("title", "source", "note"):
            if not getattr(row, field).strip():
                problems.append("%s: empty %s" % (row.row_id, field))
    ids = {r.row_id for r in slice_rows + finding_rows}
    for needed in ("s402-founder-walk", "s403-successor-seed",
                   "s404-final-census", "wave400-counted-run",
                   "v1-tag-placement", "release-signing-s400"):
        if needed not in ids:
            problems.append("required row %s missing" % needed)
    counts = census_counts(slice_rows + finding_rows)
    if counts["not_proven"] == 0:
        problems.append("census names no NOT PROVEN row")
    if counts["refused"] == 0:
        problems.append("census names no refused row")
    if counts["not_green"] == 0:
        problems.append("census names no not-green counted run")
    return tuple(problems)


def audit_census(root) -> tuple:
    """Check the census against disk: the census
    document exists and carries every row id, and
    states NOT PROVEN and NOT PLACED in words."""
    problems = list(judge_census())
    path = Path(root) / CENSUS_DOC
    if not path.exists():
        return tuple(problems + ["census doc missing: %s" % CENSUS_DOC])
    text = path.read_text(encoding="utf-8")
    for row in ALL_ROWS:
        if row.row_id not in text:
            problems.append("census doc omits row %s" % row.row_id)
    if "NOT PROVEN" not in text:
        problems.append("census doc never states NOT PROVEN")
    if "NOT PLACED" not in text:
        problems.append("census doc never states the tag NOT PLACED")
    return tuple(problems)


def _status_words(status):
    if status == "not_proven":
        return "NOT PROVEN"
    if status == "not_green":
        return "NOT GREEN"
    if status == "founder_pending":
        return "FOUNDER PENDING -- NOT DONE"
    if status == "built_unbanked":
        return "BUILT, NOT BANKED"
    if status == "this_slice":
        return "THIS SLICE"
    if status == "not_yet_done":
        return "NOT YET DONE"
    return status.replace("_", " ").upper()


def render_census(rows=ALL_ROWS) -> str:
    """The census document: the final census to
    Volmarr. Plain words first; the roadmap counted
    whole, then every finding with its status in
    words, its source, and its note."""
    acct = slice_accounting()
    counts = census_counts(rows)
    lines = [
        "# Final census to Volmarr (S-404)",
        "",
        "In plain words: this is the counted close of",
        "the first roadmap's census point. Of 416 slices,",
        "401 stand banked. One slice is Volmarr's alone",
        "to walk (S-402) and stands NOT DONE. One stands",
        "built but unbanked behind it (S-403). This census",
        "is S-404. Twelve slices (S-405..S-416, Part XXII)",
        "stand not yet done, and every cell they promise",
        "stands NOT PROVEN until its battery runs there.",
        "The v1.0 tag is NOT PLACED: the wave400 counted",
        "run reads Ran 6190 with 12 failures, all in the",
        "known stale-pin class, and a run with failures",
        "is not green however familiar its class. The",
        "S-400 package stands unsigned -- NOT PROVEN as",
        "signed. What was refused stays refused, what was",
        "deferred stays deferred. The roadmap closes;",
        "the together-work continues.",
        "",
        "The law module is `samverk/final_census.py`;",
        "its battery is `tests/test_final_census.py`;",
        "the runner is `tools/run_final_census.py`;",
        "the counted log ships at",
        "`docs/final-census-s404.md`.",
        "",
        "## Roadmap accounting (416 slices, counted whole)",
        "",
        "- Banked: %d" % acct["banked"],
        "- Founder pending (S-402): %d" % acct["founder_pending"],
        "- Built, not banked (S-403): %d" % acct["built_unbanked"],
        "- This slice (S-404): %d" % acct["this_slice"],
        "- Not yet done (S-405..S-416): %d" % acct["not_yet_done"],
        "- Total: %d of %d" % (acct["total"], ROADMAP_SLICES),
        "",
        "## Census rows",
        "",
        "- Census rows: %d" % counts["total"],
        "- NOT PROVEN rows: %d" % counts["not_proven"],
        "- Refused rows: %d" % counts["refused"],
        "- Deferred rows: %d" % counts["deferred"],
        "- Not-green counted runs: %d" % counts["not_green"],
        "- Schema 140, taxonomy 142 stand (no migration,",
        "  no new taxonomy event in this slice)",
        "",
        "## The census",
        "",
    ]
    for row in rows:
        lines += [
            "### %s -- %s" % (row.row_id, row.title),
            "",
            "- Status: %s" % _status_words(row.status),
            "- Source: %s" % row.source,
            "- Note: %s" % row.note,
            "",
        ]
    lines += [
        "## What this census does not claim",
        "",
        "- It does not claim S-402: the founder walk is",
        "  Volmarr's alone and stands NOT DONE.",
        "- It does not claim the v1.0 tag: NOT PLACED,",
        "  because no counted run over the counted tree",
        "  reads green at this census.",
        "- It does not claim a signed release: the S-400",
        "  package is unsigned and signing stands",
        "  NOT PROVEN.",
        "- It does not close Part XXII: S-405..S-416",
        "  stand not yet done and their cells NOT PROVEN.",
        "- The successor roadmap seed (S-403) carries",
        "  the deferred, refused and open remainder",
        "  forward; this census is its counted witness.",
        "",
    ]
    return "\n".join(lines)


def render_census_log(rows=ALL_ROWS) -> str:
    acct = slice_accounting()
    counts = census_counts(rows)
    lines = [
        "# Final census -- S-404",
        "",
        "The final census to Volmarr, judged at 401/416",
        "against the tree as it stands (S-402, the founder",
        "walk, still open in roadmap order; S-403 built but",
        "unbanked behind it; this slice banks after both).",
        "The full census ships at `docs/FINAL_CENSUS.md`;",
        "this is its counted log.",
        "",
        "Census rows judged: %d" % counts["total"],
        "",
        "Slice accounting: banked %d + founder %d + built %d"
        " + this slice %d + not yet done %d = %d of %d"
        % (acct["banked"], acct["founder_pending"],
           acct["built_unbanked"], acct["this_slice"],
           acct["not_yet_done"], acct["total"], ROADMAP_SLICES),
        "",
    ]
    for status in STATUSES:
        lines.append("- %s: %d" % (status, counts[status]))
    lines += ["", "| ID | Status | Source |", "|---|---|---|"]
    for row in rows:
        lines.append("| %s | %s | %s |"
                     % (row.row_id, row.status, row.source))
    lines += [
        "",
        "Counted runs: wave380 Ran 6029 fails 15; S-393 Ran 6129 fails 15; wave400 Ran 6190 fails 12 -- all stale-pin class, none green.",
        "v1.0 tag: NOT PLACED. S-400 signing: NOT PROVEN.",
        "",
        "Verdict: **COUNTED**", ""]
    return "\n".join(lines)
