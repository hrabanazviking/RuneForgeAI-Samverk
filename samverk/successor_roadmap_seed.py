"""Successor roadmap seed (S-403).

Roadmap S-403: **Successor roadmap seed -- the honest
remainder (GraphQL verdict revisited, refused/deferred
items, S-398's open studies) written as the seed of
the next roadmap.**

This module is that seed as data plus judgement. Every
item names its source slice, its real status, its
owner, and the condition that reopens it. Statuses are
never upgraded here: an item deferred at its verdict
slice is deferred here, an item refused is refused,
an item NOT PROVEN at S-399 is NOT PROVEN here, and
the founder walk (S-402) is named founder-owned --
no worker builds it and this seed does not claim it.

Sources, all read from disk at build time:
- S-253 GraphQL verdict (docs/GRAPHQL_VERDICT.md): DEFER.
- S-264 package verdict (docs/PACKAGE_VERDICT.md):
  DEFER all ecosystems, REFUSE OCI containers.
- S-282 discussions verdict (docs/DISCUSSIONS_VERDICT.md):
  core BUILD (landed S-283..S-285); polls and rich
  badges DEFERRED; S-286 published the polls refusal.
- S-398 corpus audit: 43 complete, 3 open studies
  (24, 26, 30), each owned by this slice.
- S-399 final claims: F-02, F-10, F-11 NOT PROVEN;
  F-17 OPEN for Volmarr; F-01's real-sshd cell a
  scoped NOT PROVEN remainder owned by Part XXII.
- S-400: the release package ships unsigned; signing
  is a named remainder owned by Volmarr.
- S-401: the v1.0 tag is NOT placed; placement awaits
  the wave400 counted verdict over the counted tree.
- Roadmap standing exclusions: no Docker, no
  federation, no hosted-service ambitions, no AI
  features that invent facts -- refused at founding,
  revisited only by Volmarr's word.
- Part XXII (S-405..S-416) still stands in THIS
  roadmap after S-403; the seed carries its promise
  forward only for cells still unproven at close.

No migration and no new taxonomy event: the schema
stands at 140 and the taxonomy stands at 142.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["SEED_ITEMS", "SeedItem", "STATUSES",
    "EXPECTED_COUNT", "judge_seed", "seed_counts",
    "items_by_status", "audit_seed", "render_seed",
    "render_seed_log"]

STATUSES = ("deferred", "refused", "not_proven",
    "open", "founder", "served")
EXPECTED_COUNT = 24
SEED_DOC = "docs/SUCCESSOR_ROADMAP_SEED.md"


@dataclass(frozen=True)
class SeedItem:
    item_id: str
    title: str
    source: str      # slice(s) that decided / own it
    status: str      # one of STATUSES
    owner: str       # who carries it forward
    reopen: str      # condition that reopens it
    note: str


def _i(iid, title, source, status, owner, reopen, note):
    return SeedItem(iid, title, source, status, owner,
                    reopen, note)

SEED_ITEMS = (
    _i("graphql-layer", "GraphQL API layer", "S-253",
        "deferred", "successor roadmap",
        "A second independent consumer with measured relationship-read pain, or the PR-review benchmark in research 24's shape showing REST materially worse; S-255 abuse defences extended to query cost",
        "Verdict DEFER in docs/GRAPHQL_VERDICT.md; revisited here as S-403 requires. No endpoint, schema or resolver exists; requests are refused graphql_deferred. The eight must-not-break invariants in the verdict carry into any future build."),
    _i("package-python", "Package registry: Python packages", "S-264",
        "deferred", "successor roadmap",
        "A village project names a concrete private-package need release assets cannot serve, with its workload as evidence; trust machinery (signing verifier, S-268 storage accounting, quarantine design) standing",
        "First candidate in research 26's ranking; measured village need today is zero (Samverk is stdlib-first). Answered registry_deferred."),
    _i("package-javascript", "Package registry: JavaScript packages", "S-264",
        "deferred", "successor roadmap",
        "A village project becomes a JavaScript package with a private-distribution need release assets cannot serve",
        "No village JavaScript package exists; the web surface is server-rendered. Answered registry_deferred."),
    _i("package-oci", "Package registry: OCI container images", "S-264",
        "refused", "Volmarr (standing No Docker law)",
        "Only Volmarr's word overriding the No Docker law",
        "Refused outright at S-264: the village runs no Docker, ever; native installs only. Answered registry_refused. S-265 documented the seam instead of a registry core."),
    _i("package-generic-archives", "Package registry: generic archives", "S-264",
        "served", "S-257/S-259/S-260 (banked)",
        "Nothing to reopen: served today; a successor item arises only if a need appears that releases cannot meet",
        "Versioned archives are what releases and assets already host, repo-linked with checksums and the signing seam. Answered registry_served_by_releases. Recorded so the seed accounts for every ecosystem S-264 judged."),
    _i("package-go-modules", "Package registry: Go modules", "S-264",
        "served", "git tags on readable repositories (banked)",
        "Nothing to reopen: served today by design of the Go module protocol",
        "Go modules are fetched from version-control tags; a tag on a readable Samverk repository already is a module version. Answered registry_served_by_git."),
    _i("discussion-polls", "Discussion polls", "S-282 / S-286",
        "deferred", "successor roadmap",
        "Measured village need plus a fraud-honest design that does not pretend to establish voter identity beyond account scope",
        "Deferred at S-282; S-286 published the refusal on that verdict (judged through S-283's doors and S-190 first, then refused; no poll table exists)."),
    _i("discussion-badges", "Discussion rich badges", "S-282",
        "deferred", "successor roadmap",
        "Measured village need for a signal beyond the accepted-answer mark",
        "Deferred at S-282 in the same sentence as polls; unbuilt and, unlike polls, never refused by any slice. A village trusts an answer because its author is known."),
    _i("signing-verifier", "Signing seam verifier and registry trust machinery", "S-263 / S-305 / S-264",
        "deferred", "successor roadmap",
        "Named as a precondition of any reopened package verdict (S-264 reopen conditions)",
        "S-263's signing seam has no verifier yet and a digest is not an author identity; S-264 names the verifier as trust machinery that must stand before any registry reopens."),
    _i("study-24-graphql", "Open study: research/24-graphql-api-shape.md", "S-398 (study from research 24)",
        "open", "successor roadmap",
        "The revisited GraphQL verdict is recorded in the study file itself, closing the S-398 marking",
        "S-398: the file poses the defer-or-adopt question but records no verdict; the DEFER verdict stands in docs/GRAPHQL_VERDICT.md (S-253). This seed carries the item; it does not edit the study file's verdict into existence."),
    _i("study-26-packages", "Open study: research/26-packages-and-registry.md", "S-398 (study from research 26)",
        "open", "successor roadmap",
        "The package verdicts are recorded in the study file itself, closing the S-398 marking",
        "S-398: the file poses the registry verdict question but records no verdict; DEFER all / REFUSE OCI stands in docs/PACKAGE_VERDICT.md (S-264)."),
    _i("study-30-discussions", "Open study: research/30-discussions.md", "S-398 (study from research 30)",
        "open", "successor roadmap",
        "The discussions verdict is recorded in the study file itself, closing the S-398 marking",
        "S-398: the file poses the verdict question but records no verdict; BUILD (core) stands in docs/DISCUSSIONS_VERDICT.md (S-282), with polls and badges deferred -- the remainder this seed carries above."),
    _i("claims-f02-platform-matrix", "Claims F-02: Windows, macOS and ARM platform matrix", "S-399 (claim C-10)",
        "not_proven", "Part XXII (S-405..S-416), then successor roadmap for any cell still unproven",
        "Each matrix cell flips only when its battery has run green in that cell (Part XXII's own law)",
        "Linux x86-64 proven; Pi-class budgets measured at S-395; Windows, macOS and the full matrix NOT PROVEN. Part XXII stands after S-403 in this roadmap; the seed inherits whatever it leaves unproven."),
    _i("claims-f10-live-composition", "Claims F-10: feature services composed into one running forge", "S-399",
        "not_proven", "S-402 and the successor roadmap",
        "samverk/server.py routes the composed forge end to end and the proof is counted",
        "Only /, /healthz and /admin/status are routed today; the many banked feature services are not composed into one served forge. NOT PROVEN at S-399 and still NOT PROVEN here."),
    _i("claims-f11-full-suite-green", "Claims F-11: the full suite is green", "S-399 (counted run S-393)",
        "not_proven", "Part XXI pin-refresh work and the final census (S-404)",
        "A finished counted run over the final tree reads zero failures",
        "The S-393 counted master run stands 6129 ran / 15 named stale-pin failures / 4 named skips. Later counted runs judge their own trees; no run yet entitles the words 'full suite green'."),
    _i("claims-f01-real-sshd-cell", "Claims F-01 remainder: the real-sshd transport cell", "S-399 (claim C-09)",
        "not_proven", "Part XXII (S-405..S-416)",
        "The transport battery runs against a real sshd in a proven cell, counted green",
        "C-09 is PROVEN scoped: stock-git smart-HTTP and SSH forced-command harnesses are green; the real-sshd cell is still skipped on the proving host and remains NOT PROVEN. The scoped remainder, named so it is never read as whole."),
    _i("claims-f17-readme-wordings", "Claims F-17: two README wordings only Volmarr can settle", "S-399",
        "open", "Volmarr",
        "Volmarr's own word on the founding Status bullet and the 'Samtel' wording",
        "The founding Status bullet ('46 study areas, each an empty file') is false today -- S-398 counted all 46 populated -- and the first paragraph reads 'Samtel' for Samtal. Recorded, never edited: README.md is never touched by this campaign."),
    _i("release-signing", "S-400 release package signing", "S-400",
        "open", "Volmarr",
        "The maintainer signs the package checksums with the key held outside this tree",
        "The S-400 package ships unsigned by design of the slice: signing is a named remainder owned by Volmarr, not a defect and not done."),
    _i("v1-tag-placement", "S-401 v1.0 tag placement", "S-401",
        "not_proven", "keeper, on the wave400 counted verdict",
        "A finished counted run over the counted tree (banked main at 400/416) reads zero failures; only then is the tag placed",
        "The tag law landed at S-401; the tag itself is NOT placed -- the wave400 counted verdict was unfinished when S-401 banked. If the verdict is not green: fix forward, fresh counted run, then the tag."),
    _i("founder-usability-walk", "S-402 Volmarr's usability walk", "S-402",
        "founder", "Volmarr",
        "Volmarr walks a fresh instance unaided: account, token, repo, push, mirror; every stumble is a defect fixed or commissioned on the spot",
        "Founder-dependent by the roadmap's own text. No worker builds it, no battery substitutes for it, and this seed claims nothing about its outcome. It also owns part of the F-10 proof."),
    _i("standing-no-federation", "Standing exclusion: no federation between instances", "roadmap standing exclusions (founding)",
        "refused", "Volmarr (revisited only by his word)",
        "Only Volmarr's word revisiting the founding exclusion",
        "Decided at founding: no federation between Samverk instances or Samtal villages. Carried so the successor roadmap inherits the refusal, not a blank."),
    _i("standing-no-hosted-service", "Standing exclusion: no hosted-service ambitions", "roadmap standing exclusions (founding)",
        "refused", "Volmarr (revisited only by his word)",
        "Only Volmarr's word revisiting the founding exclusion",
        "Samverk is software its owner runs, not a platform operated for strangers."),
    _i("standing-no-invented-facts", "Standing exclusion: no AI features that invent facts", "roadmap standing exclusions (founding)",
        "refused", "Volmarr (revisited only by his word)",
        "Only Volmarr's word revisiting the founding exclusion",
        "No generated summaries presented as truth; anything automated is labelled and checkable -- 'The machine drafts. The human decides.'"),
    _i("standing-no-docker", "Standing exclusion: no Docker", "roadmap standing exclusions (founding) / S-264",
        "refused", "Volmarr (standing law)",
        "Only Volmarr's word overriding the law for a specific case",
        "Not for Samverk, not for its runner, not for its docs' examples. Native installs only. The same law grounds the OCI refusal above; recorded once here as the standing law itself."),
)


def seed_counts(items=SEED_ITEMS) -> dict:
    counts = {s: 0 for s in STATUSES}
    for it in items:
        counts[it.status] = counts.get(it.status, 0) + 1
    counts["total"] = len(items)
    return counts


def items_by_status(status, items=SEED_ITEMS) -> tuple:
    return tuple(it for it in items if it.status == status)


def judge_seed(items=SEED_ITEMS) -> tuple:
    """Problems with the seed as data; empty = lawful.
    Every item must name a source, a real status, an
    owner and a reopen condition, ids unique, and the
    census must hold the three S-398 open studies, the
    revisited GraphQL verdict, and at least one refused
    and one NOT PROVEN item -- the honest remainder is
    the point of the slice."""
    problems = []
    if len(items) != EXPECTED_COUNT:
        problems.append("seed holds %d items, expected %d"
                        % (len(items), EXPECTED_COUNT))
    seen = set()
    for it in items:
        if it.item_id in seen:
            problems.append("duplicate item id %s" % it.item_id)
        seen.add(it.item_id)
        if it.status not in STATUSES:
            problems.append("%s: status %r is not a seed status"
                            % (it.item_id, it.status))
        for field in ("title", "source", "owner", "reopen", "note"):
            if not getattr(it, field).strip():
                problems.append("%s: empty %s" % (it.item_id, field))
    ids = {it.item_id for it in items}
    for needed in ("study-24-graphql", "study-26-packages",
                   "study-30-discussions", "graphql-layer"):
        if needed not in ids:
            problems.append("required item %s missing" % needed)
    counts = seed_counts(items)
    if counts["refused"] == 0:
        problems.append("seed names no refused item")
    if counts["not_proven"] == 0:
        problems.append("seed names no NOT PROVEN item")
    return tuple(problems)


def audit_seed(root) -> tuple:
    """Check the seed against disk: the seed document
    exists and carries every item id and every source
    slice named in the data, and states NOT PROVEN in
    words. Problems returned by name; empty = pass."""
    problems = list(judge_seed())
    path = Path(root) / SEED_DOC
    if not path.exists():
        return tuple(problems + ["seed doc missing: %s" % SEED_DOC])
    text = path.read_text(encoding="utf-8")
    for it in SEED_ITEMS:
        if it.item_id not in text:
            problems.append("seed doc omits item %s" % it.item_id)
    if "NOT PROVEN" not in text:
        problems.append("seed doc never states NOT PROVEN")
    return tuple(problems)


def render_seed(items=SEED_ITEMS) -> str:
    """The seed document: the honest remainder written
    as the seed of the next roadmap. Plain words first;
    every item with its status in words, its source,
    its owner and its reopen condition."""
    counts = seed_counts(items)
    lines = [
        "# Successor roadmap seed (S-403)",
        "",
        "In plain words: the first roadmap (416 slices) is",
        "closing. This seed is its honest remainder -- every",
        "item the campaign deferred, refused, left NOT",
        "PROVEN, left open, or reserved for its founder --",
        "written down with its source, its real status, its",
        "owner, and the condition that reopens it, so the",
        "next roadmap starts from the truth and not from a",
        "blank page. Nothing here upgrades a status: what",
        "was deferred is deferred, what was refused is",
        "refused, what stands NOT PROVEN stands NOT PROVEN.",
        "",
        "The law module is `samverk/successor_roadmap_seed.py`;",
        "its battery is `tests/test_successor_roadmap_seed.py`;",
        "the runner is `tools/run_successor_roadmap_seed.py`;",
        "the counted log ships at",
        "`docs/successor-roadmap-seed-s403.md`.",
        "",
        "## Census",
        "",
        "- Seed items: %d" % counts["total"],
        "- Deferred: %d" % counts["deferred"],
        "- Refused: %d" % counts["refused"],
        "- NOT PROVEN: %d" % counts["not_proven"],
        "- Open: %d" % counts["open"],
        "- Founder-owned: %d" % counts["founder"],
        "- Served by an existing road: %d" % counts["served"],
        "- Schema 140, taxonomy 142 stand (no migration,",
        "  no new taxonomy event in this slice)",
        "",
        "## The seed items",
        "",
    ]
    for it in items:
        lines += [
            "### %s -- %s" % (it.item_id, it.title),
            "",
            "- Status: %s" % it.status.replace("_", " ").upper()
            if it.status != "not_proven" else
            "- Status: NOT PROVEN",
            "- Source: %s" % it.source,
            "- Owner: %s" % it.owner,
            "- Reopens when: %s" % it.reopen,
            "- Note: %s" % it.note,
            "",
        ]
    lines += [
        "## How the successor roadmap grows from this seed",
        "",
        "- Each item becomes a successor slice only when",
        "  its reopen condition is met or its owner calls",
        "  it forward; the seed itself builds none of them.",
        "- Refused items stay refused until Volmarr's word",
        "  revisits them; the seed records the refusal, it",
        "  does not soften it.",
        "- NOT PROVEN items flip only on counted proof in",
        "  the cell they name, never on wording.",
        "- The final census (S-404) closes the first",
        "  roadmap against this seed: proven, NOT PROVEN,",
        "  refused -- counted, plain, and complete.",
        "",
    ]
    return "\n".join(lines)


def render_seed_log(items=SEED_ITEMS) -> str:
    counts = seed_counts(items)
    lines = [
        "# Successor roadmap seed -- S-403",
        "",
        "The honest remainder of the 416-slice roadmap,",
        "judged at 401/416 against the tree as it stands",
        "(S-402, the founder walk, still open in roadmap",
        "order; this slice banks after it). The full seed",
        "ships at `docs/SUCCESSOR_ROADMAP_SEED.md`; this",
        "is its counted log.",
        "",
        "Seed items judged: %d" % counts["total"],
        "",
    ]
    for status in STATUSES:
        lines.append("- %s: %d" % (status, counts[status]))
    lines += ["", "| ID | Status | Source |", "|---|---|---|"]
    for it in items:
        lines.append("| %s | %s | %s |"
                     % (it.item_id, it.status, it.source))
    lines += ["", "Verdict: **SEEDED**", ""]
    return "\n".join(lines)
