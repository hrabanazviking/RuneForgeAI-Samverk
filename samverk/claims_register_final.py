"""Claims register final (S-399).

Roadmap S-399: **every public claim in the README and
docs traced to a proof or reworded; the register ships
with the release.**

S-023 built the register (C-01..C-12, the README's
founding claims) and S-312 extended it over Part XV
(C-13..C-35). Since then Parts XVI-XX landed, Part XXI
banked its counted proofs (S-393..S-398), and the four
register rows left NOT PROVEN at S-312 (C-09..C-12) have
each met their owning part. Nothing re-judged them.

This slice is the final judgement:

- ``FINAL_CLAIMS`` names every remaining public claim
  as data: the four re-judged founding rows, the part
  gates XVI-XX, the Part XXI counted artifacts
  (S-393..S-398), the cross-cutting public claims
  (systemd sovereignty, the AGPL, the live-server
  composition state), the README's dated snapshots,
  and the README items only Volmarr can settle --
  the README itself is NEVER edited by this campaign,
  so a README claim with no proof is registered OPEN
  in his name, never silently passed and never
  "fixed" by editing the file;
- ``audit_register`` checks the judgement from disk:
  every PROVEN row names evidence that exists, every
  NOT PROVEN row names its owning part or slice, every
  OPEN row names Volmarr, the register document
  (``docs/CLAIMS_REGISTER.md``) carries every final
  row and the re-judged C-09..C-12 verdicts, and a
  sweep of ``docs/*.md`` finds no positive overclaim
  phrase left standing;
- ``render_register_log`` renders the counted final
  register -- the release artifact that ships at
  ``docs/claims-register-final-s399.md``.

The verdicts are judgements from reading the tree at
398/416; the structural law is checked from disk on
every run, so a vanished proof, a register row edited
away, or a fresh overclaim in the docs fails the audit
by name.

No migration and no new taxonomy event: the schema
stands at 140 and the taxonomy stands at 142.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["FINAL_CLAIMS", "FinalClaim", "audit_register",
    "judge_register", "register_log_dict", "render_register_log",
    "run_audit", "OVERCLAIM_PHRASES", "EXPECTED_FINAL_COUNT"]

EXPECTED_FINAL_COUNT = 17

# Positive overclaim phrases that may not stand in docs/.
# (Negations -- "not production-ready", "not guaranteed" --
# are honest and are filtered by the audit's negation check.)
OVERCLAIM_PHRASES = ("production-ready forge", "fully proven",
    "completely secure", "drop-in replacement",
    "guaranteed secure", "100% secure", "battle-tested")
NEGATIONS = ("not ", "never ", "no ", "n't ")


@dataclass(frozen=True)
class FinalClaim:
    claim_id: str
    source: str        # where the public claim stands
    claim: str
    status: str        # proven | proven_scoped | not_proven | open | historical
    evidence: tuple    # repo-relative paths that must exist (proof rows)
    owner: str         # owning part/slice for unproven rows; "Volmarr" for open
    note: str


def _p(cid, source, claim, evidence, note, owner=""):
    return FinalClaim(cid, source, claim, "proven", tuple(evidence), owner, note)


def _s(cid, source, claim, evidence, note, owner=""):
    return FinalClaim(cid, source, claim, "proven_scoped", tuple(evidence), owner, note)


def _n(cid, source, claim, owner, note, evidence=()):
    return FinalClaim(cid, source, claim, "not_proven", tuple(evidence), owner, note)


def _o(cid, source, claim, note, evidence=()):
    return FinalClaim(cid, source, claim, "open", tuple(evidence), "Volmarr", note)


def _h(cid, source, claim, note, evidence=()):
    return FinalClaim(cid, source, claim, "historical", tuple(evidence), "", note)


FINAL_CLAIMS = (
    _s("F-01", "README virtue 4 / register C-09",
        "An unmodified git client clones, pushes, and pulls (SSH and smart HTTP)",
        ("tests/test_transport_battery.py", "tests/test_part_iv_gate.py"),
        "Re-judged at S-399: stock-git smart-HTTP and SSH forced-command harnesses are counted green; the real-sshd cell is still skipped on this host (named in docs/COUNTED_MASTER_RUN.md), so the row is scoped -- that cell's remainder is owned by Part XXII (S-405..S-416)."),
    _n("F-02", "README virtue 6 / register C-10",
        "The server runs on Windows and macOS, and on ARM down to a Raspberry Pi",
        "Part XXII (S-405..S-416)",
        "Linux x86-64 is proven everywhere; Pi-class performance budgets were MEASURED on a Raspberry Pi 5 at S-395 (docs/perf-verification-s395.md). Windows, macOS and the full platform matrix have no proof in this tree; the claim stays NOT PROVEN until Part XXII lands.",
        ("docs/perf-verification-s395.md",)),
    _s("F-03", "README founding face claim / register C-11",
        "The face is designed under the Cyber-Viking Visual Design Lawbook and passes its ship gate",
        ("tests/test_part_xx_gate.py", "docs/PART_XX_GATE.md"),
        "Re-judged at S-399: the Part XX gate (S-392) counted the Book XIV ship gate PASSED over the finished UI machinery (S-381..S-391). Scoped: the designed face is proven as rendered machinery; serving it end-to-end waits on the live composition named in F-10."),
    _s("F-04", "README standing duty / register C-12",
        "Samverk mirrors Volmarr's original repositories onto his own machines and keeps them current",
        ("tests/test_part_xvii_gate.py", "docs/PART_XVII_GATE.md"),
        "Re-judged at S-399: the Part XVII gate (S-344) counted mirror freshness and restore proof green. Scoped: the mirroring machinery and its freshness law are proven; a continuously running live fleet is an operational state, not a test result, and is not claimed here."),
    _p("F-05", "Part XVI (CI / Actions, S-313..S-328)",
        "Native CI: a reference runner takes a sample repo from push to a green check on a PR",
        ("tests/test_part_xvi_gate.py",),
        "Part XVI gate battery assembles format, triggers, jobs, the safety law and the runner centre end to end, counted."),
    _p("F-06", "Part XVIII (deployment & admin, S-345..S-360)",
        "A fresh install from the written guide alone reaches a working instance with its first admin",
        ("tests/test_part_xviii_gate.py", "docs/PART_XVIII_GATE.md", "docs/INSTALL_WALK.md"),
        "The gate battery walks S-349's install walk in guide order, timed (2.39 s). The gate record itself states the walk ran on purplelongship x86-64, NOT on Pi-class hardware -- that honesty stands; the Pi install cell belongs to Part XXII."),
    _p("F-07", "S-396 upgrade drill",
        "An RC instance with real-shaped data upgrades per S-357 and verifies",
        ("docs/upgrade-drill-s396.md", "tests/test_upgrade_drill.py"),
        "Drill log is a release artifact; the upgrade path is proven on the drilled data shape."),
    _p("F-08", "Part XIX (Samtal seam, S-361..S-380)",
        "Samverk nests inside Samtal through a seam that is a seam: linked identity, permissions matrix, kill switch",
        ("tests/test_part_xix_gate.py", "docs/PART_XIX_GATE.md"),
        "PART XIX GATE PASSED: 12-step end-to-end walk green, 90-cell permissions matrix counted (68 allowed / 22 denied; both collapses deny all 90), 34-attack security review held, kill-switch drill recorded. Standalone-first (C-07) is untouched by the seam."),
    _p("F-09", "S-394 battery v1",
        "The v1.0 acceptance battery is assembled and runs as one battery",
        ("tests/test_battery_v1.py", "samverk/battery_v1.py"),
        "BATTERY V1 ASSEMBLED at S-394; assembly is the claim -- the v1.0 tag itself is S-401 and is not claimed here."),
    _n("F-10", "README 2026-11-13 update / live composition",
        "The many feature services are composed into one complete running forge served by samverk/server.py",
        "S-402 (founder usability walk) and the successor roadmap",
        "NOT PROVEN, and the README's dated wording still tells the truth: server.py routes GET /, /healthz and /admin/status only, and state-changing routes terminate after the CSRF guard. The machinery is proven slice by slice; the assembled live forge is the honest remainder of Part XXI.",
        ("docs/COUNTED_MASTER_RUN.md",)),
    _n("F-11", "S-393 counted master run",
        "The full suite is green",
        "Part XXI (pin-refresh work; final census S-404)",
        "The counted master run (docs/COUNTED_MASTER_RUN.md) stands at Ran 6129 / Passed 6110 / Failed 15 / Skipped 4 -- every failure the named stale schema/taxonomy-pin class, every skip named. The run is proven as counted; a 0-failed suite is NOT PROVEN and is not claimed.",
        ("docs/COUNTED_MASTER_RUN.md",)),
    _p("F-12", "S-397 documentation completeness",
        "Operator, admin and user guides exist and were walked by a fresh reader against a live instance",
        ("tests/test_docs_completeness.py", "docs/documentation-completeness-s397.md", "docs/OPERATOR_GUIDE.md", "docs/ADMIN_GUIDE.md", "docs/USER_GUIDE.md"),
        "DOCUMENTATION WALK PASSED at S-397: all four guides (with the install walk) walked against a live instance."),
    _p("F-13", "S-398 research corpus audit",
        "All 46 study files either hold a completed study or are honestly marked open with their owning slice",
        ("tests/test_research_corpus_audit.py", "docs/research-corpus-audit-s398.md"),
        "Counted at S-398: 46 files, 43 complete, 3 honestly open and owned by S-403. The scoped split is the claim; 'all complete' is not claimed."),
    _s("F-14", "README virtue 3 (sovereignty)",
        "Samverk runs natively under a systemd unit, data in the owner's own directories, no Docker ever",
        ("docs/SYSTEMD_UNITS.md", "tests/test_claims_register.py"),
        "Unit files ship under deploy/systemd/ with the hardening baseline the doc names; the no-Docker half is C-08's tree scan, counted in the S-023 battery. Scoped to Linux, where systemd lives -- no Windows/macOS service claim is made."),
    _p("F-15", "README licence section",
        "Samverk is AGPL-3.0 free software",
        ("LICENSE",),
        "The AGPL-3.0 LICENSE placed by Volmarr at the founding stands at the tree root."),
    _h("F-16", "README dated snapshots (founding Status; 2026-11-06 and 2026-11-13 updates)",
        "Dated position statements (152/416 and Part VII active; 304/416 and Part XV active; the founding file census)",
        "Each snapshot is dated, names the commit it inspected, and is superseded in place by the next; read as history they are accurate, read as current position they are not -- the current position is 398/416 with Parts I-XX through their gates. This register is the current authority the snapshots themselves point to.",
        ("docs/CLAIMS_REGISTER.md",)),
    _o("F-17", "README founding Status + first line",
        "Two README wordings only Volmarr can settle",
        "OPEN for Volmarr, recorded not edited (README is never touched by this campaign): (1) the founding Status bullet still reads '46 study areas, each an empty file awaiting its study' -- false today (S-398 counted all 46 populated, 43 complete); the bullet is inside a dated founding snapshot, but it is the one stale wording a fresh reader meets without a superseding line beside it. (2) The first paragraph spells the sister project 'Samtel' where every other line says Samtal. Both are named here for his hand; neither is silently passed."),
)


def _register_rows(text):
    rows = {}
    for line in text.splitlines():
        m = re.match(r"\|\s*([CF]-\d+)\s*\|", line.strip())
        if m:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows[m.group(1)] = cells
    return rows


def audit_register(root):
    root = Path(root)
    problems = []
    if len(FINAL_CLAIMS) != EXPECTED_FINAL_COUNT:
        problems.append(f"final census drift: {len(FINAL_CLAIMS)} != {EXPECTED_FINAL_COUNT}")
    ids = [c.claim_id for c in FINAL_CLAIMS]
    if len(ids) != len(set(ids)):
        problems.append("duplicate final claim ids")
    register = root / "docs" / "CLAIMS_REGISTER.md"
    rows = _register_rows(register.read_text(encoding="utf-8")) if register.is_file() else {}
    if not register.is_file():
        problems.append("docs/CLAIMS_REGISTER.md missing")
    for claim in FINAL_CLAIMS:
        if claim.status in ("proven", "proven_scoped"):
            if not claim.evidence:
                problems.append(f"{claim.claim_id}: PROVEN row names no evidence")
            for rel in claim.evidence:
                if not (root / rel).is_file():
                    problems.append(f"{claim.claim_id}: evidence missing: {rel}")
        if claim.status == "not_proven" and "Part" not in claim.owner and "S-" not in claim.owner:
            problems.append(f"{claim.claim_id}: NOT PROVEN row names no owning part/slice")
        if claim.status == "open" and claim.owner != "Volmarr":
            problems.append(f"{claim.claim_id}: OPEN row must name Volmarr")
        if claim.claim_id not in rows:
            problems.append(f"{claim.claim_id}: absent from docs/CLAIMS_REGISTER.md")
    # The re-judged founding rows must carry their S-399 verdicts.
    for cid, want in (("C-09", "PROVEN (scoped"), ("C-10", "NOT PROVEN"),
                      ("C-11", "PROVEN (scoped"), ("C-12", "PROVEN (scoped")):
        cells = rows.get(cid)
        if not cells or len(cells) < 3 or not cells[2].startswith(want):
            problems.append(f"{cid}: register verdict is not {want!r} at S-399")
    # Docs overclaim sweep: no positive overclaim phrase stands.
    for doc in sorted((root / "docs").glob("*.md")):
        if doc.name == "CLAIMS_REGISTER.md":
            continue
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            low = line.lower()
            for phrase in OVERCLAIM_PHRASES:
                idx = low.find(phrase)
                if idx >= 0 and not any(n in low[max(0, idx - 12):idx] for n in NEGATIONS):
                    problems.append(f"overclaim in docs/{doc.name}:{lineno}: {phrase!r}")
    return problems


def judge_register(root):
    problems = audit_register(root)
    counts = {}
    for claim in FINAL_CLAIMS:
        counts[claim.status] = counts.get(claim.status, 0) + 1
    return {"total": len(FINAL_CLAIMS), "counts": counts,
        "open": [c.claim_id for c in FINAL_CLAIMS if c.status == "open"],
        "not_proven": [c.claim_id for c in FINAL_CLAIMS if c.status == "not_proven"],
        "problems": problems, "passed": not problems,
        "verdict": "PASSED" if not problems else "FAILED"}


def register_log_dict(root):
    result = judge_register(root)
    result["claims"] = [{"id": c.claim_id, "status": c.status,
        "source": c.source, "claim": c.claim, "owner": c.owner} for c in FINAL_CLAIMS]
    return result


def render_register_log(log):
    lines = ["# Claims register final -- S-399", "",
        "Every public claim in the README and docs, judged at 398/416",
        "against the tree as it stands. The full register ships at",
        "`docs/CLAIMS_REGISTER.md`; this is its counted final log.", "",
        f"Final claims judged: {log['total']}", ""]
    for status, count in sorted(log["counts"].items()):
        lines.append(f"- {status}: {count}")
    lines += ["", "| ID | Status | Claim |", "|---|---|---|"]
    for c in log["claims"]:
        lines.append(f"| {c['id']} | {c['status']} | {c['claim']} |")
    lines += ["", f"Verdict: **{log['verdict']}**"]
    if log["problems"]:
        lines += ["", "## Problems", ""] + [f"- {p}" for p in log["problems"]]
    lines.append("")
    return "\n".join(lines)


def run_audit(root):
    return register_log_dict(root)
