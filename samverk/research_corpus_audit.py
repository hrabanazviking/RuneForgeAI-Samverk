"""Research corpus audit (S-398).

Roadmap S-398: **all 46 study files either hold a
completed study or are honestly marked open with the
roadmap slice that owns them; no file claims what it
does not hold.**

The corpus is ``research/``: 46 numbered study files
plus ``INDEX.md``. Before this slice the shelf's own
index recorded that all 46 files contain written
studies -- true -- but nothing had ever judged, file
by file, whether each study is *complete* under the
index's own definition (observable behaviour, design
questions, a decision or recommendation, and the
roadmap slices it feeds), and three files posed a
verdict question whose verdict was later delivered
elsewhere (S-253, S-264, S-282) without the study
file ever recording it.

This slice:

- names the corpus as data (``STUDIES``): every one
  of the 46 files with the verdict this audit reached
  from reading it -- ``complete`` or ``open`` -- the
  roadmap slice that owns an open file's remainder,
  and the evidence for the verdict;
- audits the tree (``audit_corpus``): the corpus on
  disk is exactly the census (no file missing, no
  unlisted study file), every file is substantive
  (word and section floors), names the roadmap
  slices it feeds, carries an acceptance/test
  element and a design-direction element, carries an
  honest status line (guidance / not proven / not a
  shipped-feature claim), and makes no overclaim;
  every open file carries its S-398 audit marking
  naming its owning slice in the file itself;
- renders the audit artifact
  (``render_audit_log``): the counted census, the
  completed/open split, and the named remainders.

The verdicts are judgements from reading, pinned as
data; the structural law is checked from disk on
every run, so a study that shrinks to a stub, grows
an overclaim, or loses its open marking fails the
audit by name.

No migration and no new taxonomy event: the schema
stands at 140 and the taxonomy stands at 142.
"""
from __future__ import annotations

import platform, re
from dataclasses import dataclass
from pathlib import Path

from . import db, taxonomy

__all__ = ["EXPECTED_COUNT", "STUDIES", "StudyFile",
    "audit_corpus", "judge_audit", "audit_log_dict",
    "render_audit_log", "run_audit"]

EXPECTED_COUNT = 46
MIN_WORDS = 250
MIN_SECTIONS = 4

OVERCLAIM_PHRASES = ("production-proven",
    "production proven", "fully implemented and proven",
    "shipped and proven", "complete and proven")
DIRECTION_MARKERS = ("decision", "recommended",
    "recommendation", "architecture", "engineering direction",
    "design decisions", "slice contracts", "grammar")
ACCEPTANCE_MARKERS = ("acceptance", "testable",
    "failure law", "review questions", "experiment plan", "experiment")
STATUS_MARKERS = ("not a shipped-feature claim",
    "not a completion claim", "not proof of shipped",
    "not proven", "engineering guidance",
    "guidance, not proof", "clean-room study",
    "clean-room research", "research dossier",
    "research and engineering brief", "study question")
SLICE_RE = re.compile(r"S-\d{3}")


@dataclass(frozen=True)
class StudyFile:
    filename: str
    verdict: str          # "complete" or "open"
    owner: str            # owning slice for open files, "" if complete
    evidence: str


def _c(filename, evidence):
    return StudyFile(filename, "complete", "", evidence)


def _o(filename, owner, evidence):
    return StudyFile(filename, "open", owner, evidence)


STUDIES = (
    _c("01-git-protocol-smart-http.md", "Deep study: observable behaviour, design questions, Decision taken, Feeds (S-077..S-096)."),
    _c("02-git-protocol-ssh.md", "Deep study: observable behaviour, alternatives, Decision taken, slice contracts, Feeds."),
    _c("03-pack-negotiation-and-transfers.md", "Brief: protocol facts, recommended architecture, failure modes, testable acceptance, references; honest proposed-guidance status."),
    _c("04-repository-object-model.md", "Brief: facts, recommended architecture, failure modes, testable acceptance, references."),
    _c("05-refs-and-refspecs.md", "Brief: facts, recommended architecture, failure modes, testable acceptance, references."),
    _c("06-git-lfs.md", "Brief: facts, recommended architecture, failure modes, testable acceptance, references."),
    _c("07-auth-passwords-and-sessions.md", "Deep study: standards, observed behaviour, password and session decisions, deliberate exclusions, slices fed."),
    _c("08-auth-ssh-keys.md", "Brief: facts, recommended architecture, failure modes, testable acceptance, references."),
    _c("09-auth-tokens.md", "Dossier: requirements, architecture decisions to evaluate, failure modes, acceptance checks, references; honestly not a completion claim."),
    _c("10-auth-two-factor.md", "Dossier: requirements, architecture, failure modes, acceptance checks, references."),
    _c("11-permissions-model.md", "Dossier: requirements, architecture, failure modes, acceptance checks, references."),
    _c("12-organizations-and-teams.md", "Dossier: requirements, architecture, failure modes, acceptance checks, references."),
    _c("13-issues.md", "Dossier: requirements, architecture, failure modes, acceptance checks, references."),
    _c("14-pull-requests.md", "Dossier: requirements, architecture, failure modes, acceptance checks, references."),
    _c("15-code-review.md", "Dossier: requirements, architecture, failure modes, acceptance checks, references."),
    _c("16-branches-and-protection-rules.md", "Dossier: requirements, architecture, failure modes, acceptance checks, references."),
    _c("17-commits-history-blame.md", "Dossier: requirements, architecture, failure modes, acceptance checks, references."),
    _c("18-code-search.md", "Dossier: technology requirements, recommended architecture, honest limits, acceptance tests, references. S-205 owns the index architecture written from it."),
    _c("19-issue-search-and-queries.md", "Deep study: query grammar, qualifier table, failure law, permissions. The full grammar reserved for S-206 is named in the file itself -- an in-file remainder, not an unmarked gap."),
    _c("20-notifications.md", "Dossier: requirements, recommended architecture, honest limits, acceptance tests, references."),
    _c("21-activity-feeds-and-events.md", "Dossier: requirements, recommended architecture, honest limits, acceptance tests, references."),
    _c("22-webhooks.md", "Dossier: requirements, recommended architecture, honest limits, acceptance tests, references."),
    _c("23-rest-api-shape.md", "Dossier: requirements, recommended architecture, honest limits, acceptance tests, references; ratified by S-237."),
    _o("24-graphql-api-shape.md", "S-403", "Poses the defer-or-adopt question and recommends writing a decision record, but records no verdict. The verdict (DEFER) was delivered by S-253 in docs/GRAPHQL_VERDICT.md and never recorded in this file; S-403's seed owns the revisited verdict."),
    _c("25-ci-actions-concepts.md", "Dossier: requirements, recommended architecture, honest limits, acceptance tests, references."),
    _o("26-packages-and-registry.md", "S-403", "Poses the registry verdict question (rank ecosystems, decide by village need) but records no verdict. The verdict (DEFER all, REFUSE OCI) was delivered by S-264 in docs/PACKAGE_VERDICT.md and never recorded in this file; refused/deferred items are S-403 seed material."),
    _c("27-releases-and-artifacts.md", "Dossier: requirements, recommended architecture, honest limits, acceptance tests, references."),
    _c("28-wiki.md", "Dossier: requirements, recommended architecture, honest limits, acceptance tests, references."),
    _c("29-gists-and-snippets.md", "Dossier: constraints, recommended approach, threats, acceptance checks, references; honestly NOT PROVEN until tested."),
    _o("30-discussions.md", "S-403", "Poses the discussions verdict question but records no verdict. The verdict (BUILD) was delivered by S-282 in docs/DISCUSSIONS_VERDICT.md and never recorded in this file; S-403's seed carries the refused/deferred remainder (polls and badges were deferred in its own text)."),
    _c("31-threat-model.md", "Deep study: assets, attackers, boundaries, threat register, honest limits, design decisions taken, slices fed; ratified by S-001."),
    _c("32-secret-scanning.md", "Dossier: constraints, recommended approach, threats, acceptance checks, references."),
    _c("33-dependency-alerts.md", "Dossier: constraints, recommended approach, threats, acceptance checks, references."),
    _c("34-code-scanning.md", "Dossier: constraints, recommended approach, threats, acceptance checks, references."),
    _c("35-audit-log.md", "Deep study: record shape, tamper evidence, taxonomy sketch, read scopes, retention, design decisions taken, slices fed."),
    _c("36-signed-commits.md", "Dossier: constraints, recommended approach, threats, acceptance checks, references."),
    _c("37-mirroring-and-backup.md", "Dossier: constraints, recommended approach, threats, acceptance checks, references."),
    _c("38-standalone-deployment.md", "Dossier: constraints, recommended approach, threats, acceptance checks, references."),
    _c("39-samtal-integration-seam.md", "Dossier: core facts, engineering direction, threats, acceptance plan, sources; seam ratified by S-361."),
    _c("40-admin-and-site-settings.md", "Dossier: core facts, engineering direction, threats, acceptance plan, sources."),
    _c("41-accessibility-and-ui-principles.md", "Dossier: core facts, engineering direction, threats, acceptance plan, sources."),
    _c("42-data-model-and-storage.md", "Deep study: three stores, SQLite discipline, allocation table, crash honesty, scale honesty, design decisions taken, slices fed."),
    _c("43-markdown-and-rendering.md", "Dossier: core facts, engineering direction, threats, acceptance plan, sources."),
    _c("44-migration-and-import.md", "Dossier: core facts, engineering direction, threats, acceptance plan, sources."),
    _c("45-cross-platform-architecture.md", "Dossier: core facts, engineering direction, threats, acceptance plan, sources. The support-matrix ratification is S-405's deliverable, named in the file's roadmap line -- future proof work, not a gap in the study."),
    _c("46-visual-design-cyber-viking.md", "Dossier: core facts, engineering direction, threats, acceptance plan, sources."),
)


def audit_corpus(root: Path) -> list:
    """Audit the research corpus on disk against the census.

    Pure file reads. Returns problem strings; empty is sound.
    """
    problems = []
    research = root / "research"
    on_disk = sorted(p.name for p in research.glob("[0-9]*.md")) if research.is_dir() else []
    census = [s.filename for s in STUDIES]
    if len(census) != EXPECTED_COUNT:
        problems.append(f"census holds {len(census)} files, roadmap says {EXPECTED_COUNT}")
    if on_disk != sorted(census):
        missing = sorted(set(census) - set(on_disk))
        extra = sorted(set(on_disk) - set(census))
        if missing:
            problems.append(f"study files missing on disk: {', '.join(missing)}")
        if extra:
            problems.append(f"study files on disk not in census: {', '.join(extra)}")
    for s in STUDIES:
        path = research / s.filename
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        low = text.lower()
        words = len(text.split())
        if words < MIN_WORDS:
            problems.append(f"{s.filename}: only {words} words (floor {MIN_WORDS}) -- a stub, not a study")
        sections = sum(1 for line in text.splitlines() if line.startswith("## "))
        if sections < MIN_SECTIONS:
            problems.append(f"{s.filename}: only {sections} sections (floor {MIN_SECTIONS})")
        if not SLICE_RE.search(text):
            problems.append(f"{s.filename}: names no roadmap slice it feeds")
        if not any(m in low for m in DIRECTION_MARKERS):
            problems.append(f"{s.filename}: no design-direction or decision element")
        if not any(m in low for m in ACCEPTANCE_MARKERS):
            problems.append(f"{s.filename}: no acceptance or test element")
        if not any(m in low for m in STATUS_MARKERS):
            problems.append(f"{s.filename}: no honest status line (guidance / not proven / clean-room)")
        for phrase in OVERCLAIM_PHRASES:
            if phrase in low:
                problems.append(f"{s.filename}: overclaim {phrase!r} -- claims what it does not hold")
        if s.verdict == "open":
            if "audit status" not in low or "s-398" not in low or s.owner.lower() not in low:
                problems.append(f"{s.filename}: open but not honestly marked in-file with its owner {s.owner}")
    return problems


def judge_audit(problems: list, studies=STUDIES) -> bool:
    """Pure verdict: no problems and the census is full."""
    return not problems and len(studies) == EXPECTED_COUNT


def audit_log_dict(problems: list) -> dict:
    complete = [s.filename for s in STUDIES if s.verdict == "complete"]
    open_ = [{"file": s.filename, "owner": s.owner, "evidence": s.evidence} for s in STUDIES if s.verdict == "open"]
    return {"machine": platform.machine(),
            "platform": platform.platform(),
            "schema": db.MIGRATIONS[-1][0],
            "taxonomy_events": len(taxonomy.AUDIT_EVENTS),
            "total": len(STUDIES), "complete": len(complete),
            "open": open_, "problems": problems,
            "passed": judge_audit(problems),
            "verdict": "RESEARCH CORPUS AUDIT PASSED" if judge_audit(problems) else "RESEARCH CORPUS AUDIT NOT PASSED"}


def run_audit(root: Path) -> dict:
    return audit_log_dict(audit_corpus(root))


def render_audit_log(log: dict) -> str:
    lines = ["# Research corpus audit -- S-398", "",
        "Release artifact: all 46 study files in `research/` judged one by one --",
        "each either holds a completed study or is honestly marked open, in the",
        "file itself, with the roadmap slice that owns its remainder. No file",
        "claims what it does not hold. Generated by `tools/run_research_audit.py`",
        "from a real read of the corpus; no verdict in this log is asserted",
        "without reading the file it names.", "",
        f"- Machine: `{log['machine']}` ({log['platform']})",
        f"- Schema: {log['schema']}; taxonomy events: {log['taxonomy_events']}",
        f"- Corpus: {log['total']} study files -- {log['complete']} complete, {len(log['open'])} open", "",
        "## Open studies (honestly marked, owner named)", ""]
    for o in log["open"]:
        lines.append(f"- {o['file']} -- OPEN, owned by {o['owner']}: {o['evidence']}")
    lines += ["", "## Problems", ""]
    if log["problems"]:
        lines += [f"- {p}" for p in log["problems"]]
    else:
        lines.append("- none: the corpus on disk matches the census, every file is substantive, and no file overclaims.")
    lines += ["", "## Verdict", "", log["verdict"], ""]
    return "\n".join(lines)
