"""First-pass mirroring run (S-336).

Roadmap S-336: **the first-pass mirroring run -- the
public originals mirrored and verified ref-for-ref
against GitHub (the proof-first pattern: one small repo
verified before the batch).**

S-335 imported the census as mirror *definitions*:
pending pull mirrors, nothing fetched. This slice runs
the first pass over the public originals, and it runs
proof-first, the founding pattern of this part:

- **The proof.** One public original -- the first by
  name, a small deterministic choice a person can
  predict -- is synced (S-329) and then *verified
  ref-for-ref*: every ``refs/heads/*`` and
  ``refs/tags/*`` ref the source advertises (read
  through the S-014 ``ls-remote`` seam,
  ``run_git_ls_remote_refs``) must stand in the mirror
  at the same object id, with nothing missing, nothing
  extra, and nothing diverged. Equality of the ref maps
  is the proof; a green fetch alone is not.
- **The gate.** The batch runs only when the proof
  verifies. A failed proof stops the pass: the report
  says the batch was not started, and no other mirror
  is synced. Proof-first means the batch never inherits
  an unproven road.
- **The batch.** Each remaining public original is
  synced and verified the same way, one at a time, and
  every outcome is recorded -- a batch failure is
  stated per repo and does not hide the others, and it
  does not stop the rest of the batch (the gate was the
  proof, not each repo).

Scope law, inherited from the census: only entries
S-335 recorded as ``defined`` with classification
``original-public`` take part. Private originals are
S-337's (they wait for a read-scoped credential) and
held uncertain entries are never auto-mirrored -- this
pass counts both as skipped and touches neither.

The judgements are pure. ``compare_ref_maps`` judges
two ref maps and writes nothing; ``plan_first_pass``
chooses the proof and the batch order from census
records and writes nothing; ``decide_batch`` states
whether a proof outcome opens the batch gate. The
service acts on the judgements and records every run
in migration 138 (``first_pass_mirror_runs``): phase,
state, the four ref counts, and the plain detail.
Sync rides S-329/S-070, which record their own status;
no new audit event is claimed -- the taxonomy stands
at 138.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .census_fixture import (
    CLASS_PRIVATE, CLASS_PUBLIC, DEFINED, HELD, CensusFixtureRecord,
    CensusFixtureService)
from .escaping import escape_html_text
from .proc import ProcRefused, run_git_ls_remote_refs
from .pull_mirrors import PullMirrorError, PullMirrorService
from .refs import RefStore
from .repositories import RepositoryStore

PHASE_PROOF = "proof"
PHASE_BATCH = "batch"

VERIFIED = "verified"
FAILED = "failed"

ACTION_RUN_BATCH = "run_batch"
ACTION_BLOCK_BATCH = "block_batch"


class FirstPassError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class RefComparison:
    """The pure verdict over two ref maps."""
    matched: int
    missing: tuple[str, ...]      # advertised by the source, absent in the mirror
    extra: tuple[str, ...]        # in the mirror, not advertised by the source
    diverged: tuple[str, ...]     # in both, at different object ids
    source_refs: int

    @property
    def verified(self) -> bool:
        """Ref-for-ref means exact: the source advertises at
        least one ref, and every advertised ref stands in the
        mirror at the same id, with nothing extra standing."""
        return (self.source_refs > 0 and not self.missing
                and not self.extra and not self.diverged)

    @property
    def headline(self) -> str:
        if self.source_refs == 0:
            return "the source advertises no refs; there is nothing to verify"
        if self.verified:
            return (f"verified ref-for-ref: {self.matched} refs match "
                    f"the source exactly")
        parts = [f"{self.matched} refs match"]
        if self.missing:
            parts.append(f"{len(self.missing)} missing from the mirror")
        if self.extra:
            parts.append(f"{len(self.extra)} extra in the mirror")
        if self.diverged:
            parts.append(f"{len(self.diverged)} diverged")
        return "not verified: " + ", ".join(parts)


def _mirror_scope(ref: str) -> bool:
    """The mirror refspec's scope (S-070): heads and tags."""
    return ref.startswith("refs/heads/") or ref.startswith("refs/tags/")


def parse_ls_remote(text: str) -> dict[str, str]:
    """Parse ``git ls-remote`` output into a ref map, scoped
    to heads and tags. Peeled ``^{}`` lines are dropped: the
    mirror stores the tag ref at the tag object, exactly as
    ``for-each-ref`` reports it, so the peeled line would
    double-count one ref. Malformed lines are refused in
    plain words -- a verification never guesses at its input."""
    refs: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        oid, _, ref = line.partition("\t")
        oid, ref = oid.strip(), ref.strip()
        if ref == "HEAD":
            continue  # the source's default-branch pointer, not a ref
        if not oid or not ref.startswith("refs/"):
            raise FirstPassError(
                "source_refs_unreadable",
                f"The source ref listing carries a line this "
                f"verification will not guess at: {line[:80]!r}.")
        if ref.endswith("^{}") or not _mirror_scope(ref):
            continue
        refs[ref] = oid
    return refs


def compare_ref_maps(source: dict[str, str],
                     mirror: dict[str, str]) -> RefComparison:
    """Judge two ref maps. Pure: reads nothing, writes
    nothing. Only heads and tags are judged -- the scope
    the mirror sync itself converges (S-070's refspec)."""
    src = {r: o for r, o in source.items() if _mirror_scope(r)}
    mir = {r: o for r, o in mirror.items() if _mirror_scope(r)}
    missing = tuple(sorted(r for r in src if r not in mir))
    extra = tuple(sorted(r for r in mir if r not in src))
    diverged = tuple(sorted(
        r for r in src if r in mir and src[r] != mir[r]))
    matched = sum(1 for r in src if r in mir and src[r] == mir[r])
    return RefComparison(
        matched=matched, missing=missing, extra=extra,
        diverged=diverged, source_refs=len(src))


@dataclass(frozen=True)
class FirstPassPlan:
    proof: CensusFixtureRecord | None
    batch: tuple[CensusFixtureRecord, ...]
    skipped_private: int
    skipped_held: int


def plan_first_pass(records: list[CensusFixtureRecord]) -> FirstPassPlan:
    """Choose the proof and the batch from census records.
    Pure. Public defined originals take part, in name
    order; the first is the proof, the rest the batch.
    Private definitions (S-337's) and held names (the
    owner's word governs each) are counted, never taken."""
    public = sorted(
        (r for r in records
         if r.state == DEFINED and r.classification == CLASS_PUBLIC),
        key=lambda r: r.name)
    return FirstPassPlan(
        proof=public[0] if public else None,
        batch=tuple(public[1:]),
        skipped_private=sum(
            1 for r in records
            if r.state == DEFINED and r.classification == CLASS_PRIVATE),
        skipped_held=sum(1 for r in records if r.state == HELD))


@dataclass(frozen=True)
class BatchDecision:
    action: str                # ACTION_RUN_BATCH | ACTION_BLOCK_BATCH
    reason: str


def decide_batch(proof_state: str) -> BatchDecision:
    """The proof-first gate, stated purely: the batch runs
    only behind a verified proof."""
    if proof_state == VERIFIED:
        return BatchDecision(
            action=ACTION_RUN_BATCH,
            reason="the proof repo verified ref-for-ref; the batch may run")
    return BatchDecision(
        action=ACTION_BLOCK_BATCH,
        reason="the proof repo did not verify; the batch is not started")


@dataclass(frozen=True)
class FirstPassRunRecord:
    full_name: str
    phase: str                 # PHASE_PROOF | PHASE_BATCH
    state: str                 # VERIFIED | FAILED
    refs_matched: int
    refs_missing: int
    refs_extra: int
    refs_diverged: int
    detail: str
    run_at: int

    @property
    def headline(self) -> str:
        return (f"{self.full_name} ({self.phase}): {self.state} -- "
                f"{self.detail}")


@dataclass
class FirstPassReport:
    proof: FirstPassRunRecord | None = None
    batch: list[FirstPassRunRecord] = field(default_factory=list)
    batch_blocked: bool = False
    skipped_private: int = 0
    skipped_held: int = 0
    note: str = ""

    @property
    def verified_count(self) -> int:
        runs = ([self.proof] if self.proof else []) + self.batch
        return sum(1 for r in runs if r.state == VERIFIED)

    @property
    def failed(self) -> list[FirstPassRunRecord]:
        runs = ([self.proof] if self.proof else []) + self.batch
        return [r for r in runs if r.state == FAILED]

    @property
    def headline(self) -> str:
        if self.proof is None:
            return ("first pass: no public originals are defined; "
                    "nothing was mirrored")
        text = (f"first pass: proof {self.proof.full_name} "
                f"{self.proof.state}; "
                f"{self.verified_count} verified, "
                f"{len(self.failed)} failed, "
                f"{self.skipped_private} private skipped (S-337), "
                f"{self.skipped_held} held skipped")
        if self.batch_blocked:
            text += "; the batch was not started"
        return text


class FirstPassMirroringService:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time,
                 ls_remote_fn: Callable[..., object] = run_git_ls_remote_refs):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._pull = PullMirrorService(
            conn, data_root, accounts, repositories,
            audit=audit, time_fn=time_fn)
        self._census = CensusFixtureService(
            conn, data_root, accounts, repositories,
            audit=audit, time_fn=time_fn)
        self._now = time_fn
        self._ls_remote = ls_remote_fn

    # -- ref reading -------------------------------------------------
    def source_refs(self, owner, repo) -> dict[str, str]:
        """The refs the mirror's source advertises right now,
        read through the S-014 ls-remote seam (heads and tags)."""
        mirror = self._pull.pull_mirror_for(owner, repo)
        if mirror is None:
            raise FirstPassError(
                "not_a_mirror",
                "That repository is not a pull mirror.")
        source: str | Path = (Path(mirror.source)
                              if mirror.source_kind == "local"
                              else mirror.source)
        try:
            result = self._ls_remote(source, timeout=120.0)
        except ProcRefused as exc:
            raise FirstPassError("source_refs_unreadable", str(exc)) from exc
        except Exception as exc:  # stated, never hidden
            raise FirstPassError(
                "source_refs_unreadable",
                f"The source refs cannot be read: "
                f"{type(exc).__name__}: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.decode(
                "utf-8", "replace").strip()[:200] or "ls-remote failed"
            raise FirstPassError("source_refs_unreadable", detail)
        return parse_ls_remote(result.stdout.decode("utf-8", "replace"))

    def mirror_refs(self, owner, repo) -> dict[str, str]:
        """The refs standing in the mirror, in mirror scope."""
        path = self._repos.path_for(owner, repo)
        return {ref.name: ref.oid for ref in RefStore(path).list_refs()
                if _mirror_scope(ref.name)}

    def verify_mirror(self, owner, repo) -> RefComparison:
        """Verify one mirror against its source, ref-for-ref.
        Reads both sides; syncs nothing, writes nothing."""
        return compare_ref_maps(self.source_refs(owner, repo),
                                self.mirror_refs(owner, repo))

    # -- records -------------------------------------------------------
    def _record(self, row: sqlite3.Row) -> FirstPassRunRecord:
        return FirstPassRunRecord(
            full_name=row["full_name"], phase=row["phase"],
            state=row["state"], refs_matched=row["refs_matched"],
            refs_missing=row["refs_missing"],
            refs_extra=row["refs_extra"],
            refs_diverged=row["refs_diverged"],
            detail=row["detail"], run_at=row["run_at"])

    def _store(self, record: FirstPassRunRecord, repo_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO first_pass_mirror_runs (full_name, repo_id,"
                " phase, state, refs_matched, refs_missing, refs_extra,"
                " refs_diverged, detail, run_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record.full_name, repo_id, record.phase, record.state,
                 record.refs_matched, record.refs_missing,
                 record.refs_extra, record.refs_diverged,
                 record.detail, record.run_at))

    def runs_for(self, full_name: str) -> list[FirstPassRunRecord]:
        rows = self._conn.execute(
            "SELECT * FROM first_pass_mirror_runs WHERE full_name = ?"
            " ORDER BY run_at, id", (full_name,)).fetchall()
        return [self._record(row) for row in rows]

    def latest_run(self, full_name: str) -> FirstPassRunRecord | None:
        rows = self.runs_for(full_name)
        return rows[-1] if rows else None

    # -- the run ---------------------------------------------------------
    def run_one(self, owner, name: str, phase: str) -> FirstPassRunRecord:
        """Sync one defined mirror and verify it ref-for-ref,
        recording the outcome either way. A sync that fails is
        a failed run with the sync's own words; a sync that
        succeeds still has to prove itself against the source."""
        mirror = self._pull.pull_mirror_for(owner, name)
        if mirror is None:
            raise FirstPassError(
                "not_a_mirror",
                f"{owner}/{name} is not a defined pull mirror.")
        run_at = int(self._now())
        try:
            result = self._pull.sync_pull_mirror(owner, name)
        except PullMirrorError as exc:
            record = FirstPassRunRecord(
                full_name=mirror.full_name, phase=phase, state=FAILED,
                refs_matched=0, refs_missing=0, refs_extra=0,
                refs_diverged=0,
                detail=f"sync refused: {exc}", run_at=run_at)
            self._store(record, mirror.repo_id)
            return record
        if result.state != "ready":
            record = FirstPassRunRecord(
                full_name=mirror.full_name, phase=phase, state=FAILED,
                refs_matched=0, refs_missing=0, refs_extra=0,
                refs_diverged=0,
                detail=f"sync failed: {result.detail}", run_at=run_at)
            self._store(record, mirror.repo_id)
            return record
        try:
            comparison = self.verify_mirror(owner, name)
        except FirstPassError as exc:
            record = FirstPassRunRecord(
                full_name=mirror.full_name, phase=phase, state=FAILED,
                refs_matched=0, refs_missing=0, refs_extra=0,
                refs_diverged=0,
                detail=f"verification could not run: {exc}",
                run_at=run_at)
            self._store(record, mirror.repo_id)
            return record
        record = FirstPassRunRecord(
            full_name=mirror.full_name, phase=phase,
            state=VERIFIED if comparison.verified else FAILED,
            refs_matched=comparison.matched,
            refs_missing=len(comparison.missing),
            refs_extra=len(comparison.extra),
            refs_diverged=len(comparison.diverged),
            detail=comparison.headline, run_at=run_at)
        self._store(record, mirror.repo_id)
        return record

    def run_first_pass(self, owner) -> FirstPassReport:
        """The first pass over the public originals, proof
        first: sync and verify the one proof repo; only a
        verified proof opens the batch gate. Every run is
        recorded; private and held census entries are
        counted as skipped and never touched."""
        prefix = f"{owner}/"
        plan = plan_first_pass(
            [r for r in self._census.entries()
             if r.full_name.startswith(prefix)])
        report = FirstPassReport(
            skipped_private=plan.skipped_private,
            skipped_held=plan.skipped_held)
        if plan.proof is None:
            report.note = ("no public originals are defined in the "
                           "census fixture; nothing was mirrored")
            return report
        proof_owner, _, proof_name = plan.proof.full_name.partition("/")
        proof = self.run_one(proof_owner, proof_name, PHASE_PROOF)
        report.proof = proof
        gate = decide_batch(proof.state)
        if gate.action == ACTION_BLOCK_BATCH:
            report.batch_blocked = True
            report.note = gate.reason
            return report
        for entry in plan.batch:
            entry_owner, _, entry_name = entry.full_name.partition("/")
            report.batch.append(
                self.run_one(entry_owner, entry_name, PHASE_BATCH))
        return report


def render_first_pass_page(report: FirstPassReport) -> str:
    """The first-pass page: the proof named with its verdict,
    the batch listed with theirs, the gate stated in words
    when it stayed shut -- never colour-only. All text is
    escaped."""
    parts = ["<h1>First-pass mirroring run</h1>",
             f"<p>{escape_html_text(report.headline)}.</p>"]
    if report.note:
        parts.append(f"<p>{escape_html_text(report.note)}</p>")
    if report.proof is not None:
        parts += ["<h2>Proof</h2>", "<ul>",
                  f"<li>{escape_html_text(report.proof.headline)}</li>",
                  "</ul>", "<h2>Batch</h2>", "<ul>"]
        for record in report.batch:
            parts.append(
                f"<li>{escape_html_text(record.headline)}</li>")
        parts.append("</ul>")
    return "\n".join(parts)
