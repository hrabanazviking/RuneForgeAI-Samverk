"""Private originals (S-337).

Roadmap S-337: **private originals -- with a read-scoped
GitHub credential in place, the private originals mirror
too, landing as *private* mirrors always.**

S-335 defined the private originals as pending pull
mirrors and S-336's first pass counted them as skipped:
they wait for a credential, because a private source
cannot be fetched anonymously. This slice runs them,
under three laws that are never relaxed:

- **The credential gate.** A private original syncs only
  when its mirror names an S-330 credential (an S-003
  instance-secret name -- never a value), that secret is
  loaded, and the operator declares the credential's
  scope and the declaration is read-only. Any write or
  admin token in the declared scope refuses the sync
  before any fetch is attempted: Samverk mirrors private
  originals with a credential that could not change them
  even if it leaked into the wrong hands on the source.
  A missing credential, an unloaded secret, or an
  undeclared scope is likewise a refusal, stated in
  plain words and recorded -- never a silent skip.
- **Private always.** The census already lands private
  originals as private mirrors (S-335), but visibility
  can drift after definition. Before any sync this
  service checks the landing: a mirror that does not
  stand ``private`` is set ``private`` first, through
  the owner's own audited visibility road (S-050), and
  the enforcement is written into the run's detail.
  After the sync the landing is checked again; a mirror
  that does not stand private is a failed run, however
  the fetch went.
- **Proof, again.** Each synced mirror is verified
  ref-for-ref against its source exactly as S-336
  verifies the public pass (the S-014 ls-remote seam,
  here carrying the resolved token so a private source
  can answer), and every run -- verified, failed, or
  refused at the gate -- is recorded in the standing
  run log (``first_pass_mirror_runs``, phase
  ``private``). No new audit event is claimed; the
  taxonomy stands at 138, and the schema stands at 138:
  this slice reuses the seams and tables its
  predecessors built, on purpose.

Scope law, inherited from the census: only entries
S-335 recorded as ``defined`` with classification
``original-private`` take part. Public originals are
S-336's pass and held uncertain entries are never
auto-mirrored; this run counts both as skipped and
touches neither.

The judgements are pure. ``decide_credential`` states
whether a credential position opens the gate and writes
nothing; ``plan_private_originals`` chooses the run's
entries from census records and writes nothing;
``landing_is_private`` judges one visibility word.
The service acts on the judgements and records
every outcome.
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
from .first_pass_mirroring import (
    FAILED, VERIFIED, FirstPassMirroringService, FirstPassRunRecord)
from .mirror_credentials import (
    MirrorCredentialError, MirrorCredentialService)
from .proc import ProcRefused, run_git_ls_remote_refs
from .pull_mirrors import PullMirrorService
from .repositories import RepositoryStore
from .secrets import Secrets

PHASE_PRIVATE = "private"

ACTION_ALLOW = "allow"
ACTION_REFUSE = "refuse"

# The read-only scope words this gate accepts, after
# normalisation (lowercase, split on commas, spaces,
# and colons kept inside a word such as "contents:read").
READ_SCOPE_WORDS = frozenset({
    "read", "read-only", "readonly", "contents:read",
    "metadata:read", "repo:read",
})
WRITE_SCOPE_MARKERS = ("write", "admin", "delete", "workflow")


class PrivateOriginalsError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class CredentialDecision:
    action: str                # ACTION_ALLOW | ACTION_REFUSE
    reason: str


def _scope_words(declared_scope: object) -> tuple[str, ...]:
    if not isinstance(declared_scope, str):
        return ()
    text = declared_scope.lower().replace(",", " ")
    return tuple(w for w in text.split() if w)


def decide_credential(has_credential: bool,
                      declared_scope: object) -> CredentialDecision:
    """The credential gate, stated purely: a private
    original syncs only behind a credential that is in
    place and declared read-scoped. A declaration naming
    any write or admin power refuses -- the gate reads
    the whole declaration, so one read word cannot launder
    a write word standing beside it."""
    if not has_credential:
        return CredentialDecision(
            action=ACTION_REFUSE,
            reason=("no credential is named on this mirror; "
                    "name a read-scoped GitHub credential "
                    "(S-330) before a private original can sync"))
    words = _scope_words(declared_scope)
    if not words:
        return CredentialDecision(
            action=ACTION_REFUSE,
            reason=("the credential's scope is not declared; "
                    "declare it read-only before a private "
                    "original can sync"))
    for word in words:
        if any(marker in word for marker in WRITE_SCOPE_MARKERS):
            return CredentialDecision(
                action=ACTION_REFUSE,
                reason=(f"the declared scope names {word!r}, "
                        "which is not read-only; private "
                        "originals mirror only behind a "
                        "read-scoped credential"))
        if word not in READ_SCOPE_WORDS:
            return CredentialDecision(
                action=ACTION_REFUSE,
                reason=(f"the declared scope word {word!r} is "
                        "not a read scope this gate recognises"))
    return CredentialDecision(
        action=ACTION_ALLOW,
        reason="a credential is in place and declared read-scoped")


def landing_is_private(visibility: object) -> bool:
    """One word judged purely: a private original lands
    as a private mirror, always -- no other visibility
    is a landing."""
    return visibility == "private"


@dataclass(frozen=True)
class PrivateOriginalsPlan:
    entries: tuple[CensusFixtureRecord, ...]
    skipped_public: int
    skipped_held: int


def plan_private_originals(
        records: list[CensusFixtureRecord]) -> PrivateOriginalsPlan:
    """Choose the run's entries from census records.
    Pure. Defined private originals take part, in name
    order. Public definitions (S-336's pass) and held
    names (the owner's word governs each) are counted,
    never taken."""
    private = sorted(
        (r for r in records
         if r.state == DEFINED and r.classification == CLASS_PRIVATE),
        key=lambda r: r.name)
    return PrivateOriginalsPlan(
        entries=tuple(private),
        skipped_public=sum(
            1 for r in records
            if r.state == DEFINED and r.classification == CLASS_PUBLIC),
        skipped_held=sum(1 for r in records if r.state == HELD))


@dataclass
class PrivateOriginalsReport:
    runs: list[FirstPassRunRecord] = field(default_factory=list)
    skipped_public: int = 0
    skipped_held: int = 0
    note: str = ""

    @property
    def verified_count(self) -> int:
        return sum(1 for r in self.runs if r.state == VERIFIED)

    @property
    def failed(self) -> list[FirstPassRunRecord]:
        return [r for r in self.runs if r.state == FAILED]

    @property
    def headline(self) -> str:
        if not self.runs and not self.note:
            return ("private originals: no private originals are "
                    "defined; nothing was mirrored")
        return (f"private originals: {self.verified_count} verified, "
                f"{len(self.failed)} failed or refused, "
                f"{self.skipped_public} public skipped (S-336), "
                f"{self.skipped_held} held skipped")


class PrivateOriginalsService:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time,
                 ls_remote_fn: Callable[..., object] = run_git_ls_remote_refs):
        self._conn = conn
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._now = time_fn
        self._ls_remote = ls_remote_fn
        self._census = CensusFixtureService(
            conn, data_root, accounts, repositories,
            audit=audit, time_fn=time_fn)
        self._credentials = MirrorCredentialService(
            conn, data_root, accounts, repositories,
            audit=audit, time_fn=time_fn)
        self._pull = PullMirrorService(
            conn, data_root, accounts, repositories,
            audit=audit, time_fn=time_fn)
        self._first = FirstPassMirroringService(
            conn, data_root, accounts, repositories,
            audit=audit, time_fn=time_fn, ls_remote_fn=ls_remote_fn)

    # -- records ---------------------------------------------------
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
            " AND phase = ? ORDER BY run_at, id",
            (full_name, PHASE_PRIVATE)).fetchall()
        return [FirstPassRunRecord(
            full_name=row["full_name"], phase=row["phase"],
            state=row["state"], refs_matched=row["refs_matched"],
            refs_missing=row["refs_missing"],
            refs_extra=row["refs_extra"],
            refs_diverged=row["refs_diverged"],
            detail=row["detail"], run_at=row["run_at"])
            for row in rows]

    def _failed(self, full_name: str, repo_id: int, detail: str,
                run_at: int) -> FirstPassRunRecord:
        record = FirstPassRunRecord(
            full_name=full_name, phase=PHASE_PRIVATE, state=FAILED,
            refs_matched=0, refs_missing=0, refs_extra=0,
            refs_diverged=0, detail=detail, run_at=run_at)
        self._store(record, repo_id)
        return record

    # -- the landing -------------------------------------------------
    def _enforce_private(self, owner, name: str) -> str:
        """Make the landing private before any sync, and
        say what was done: '' when it already stood
        private, a note when drift had to be repaired
        through the owner's audited visibility road."""
        repo = self._repos.get_repository(owner, name)
        if repo is None:
            raise PrivateOriginalsError(
                "no_such_repo", f"{owner}/{name} does not exist.")
        if landing_is_private(repo.visibility):
            return ""
        actor = self._accounts.get_by_username(repo.owner)
        if actor is None:
            raise PrivateOriginalsError(
                "no_such_user",
                f"The owner of {repo.full_name} cannot be found.")
        self._repos.update_metadata(
            actor.id, repo.owner, repo.name, visibility="private")
        return (f"landing repaired: visibility stood "
                f"{repo.visibility!r} and was set private before "
                f"the sync; ")

    # -- verification --------------------------------------------------
    def _verify(self, owner, name: str, token: str | None):
        """Ref-for-ref, as S-336 -- except the ls-remote
        seam carries the resolved token, so a private
        source can answer. A seam that takes no token
        (a test double) is called without it."""
        mirror = self._pull.pull_mirror_for(owner, name)
        source: str | Path = (Path(mirror.source)
                              if mirror.source_kind == "local"
                              else mirror.source)
        try:
            result = self._ls_remote(source, timeout=120.0, token=token)
        except TypeError:
            result = self._ls_remote(source, timeout=120.0)
        except ProcRefused as exc:
            raise PrivateOriginalsError(
                "source_refs_unreadable", str(exc)) from exc
        if result.returncode != 0:
            detail = result.stderr.decode(
                "utf-8", "replace").strip()[:200] or "ls-remote failed"
            raise PrivateOriginalsError("source_refs_unreadable", detail)
        from .first_pass_mirroring import compare_ref_maps, parse_ls_remote
        source_refs = parse_ls_remote(
            result.stdout.decode("utf-8", "replace"))
        return compare_ref_maps(
            source_refs, self._first.mirror_refs(owner, name))

    # -- the run -------------------------------------------------------
    def run_one(self, owner, name: str, *,
                secrets: Secrets | None,
                declared_scope: object) -> FirstPassRunRecord:
        """Sync one defined private original behind the
        credential gate, landing private always, verified
        ref-for-ref. Every outcome is recorded; a refusal
        at the gate syncs nothing."""
        mirror = self._pull.pull_mirror_for(owner, name)
        if mirror is None:
            raise PrivateOriginalsError(
                "not_a_mirror",
                f"{owner}/{name} is not a defined pull mirror.")
        run_at = int(self._now())
        cred = self._credentials.credential_for(owner, name)
        gate = decide_credential(
            bool(cred and cred.has_credential), declared_scope)
        if gate.action == ACTION_REFUSE:
            return self._failed(
                mirror.full_name, mirror.repo_id,
                f"credential gate refused: {gate.reason}", run_at)
        try:
            token = self._credentials.resolve_token(
                owner, name, secrets)
        except MirrorCredentialError as exc:
            return self._failed(
                mirror.full_name, mirror.repo_id,
                f"credential gate refused: {exc}", run_at)
        try:
            landing_note = self._enforce_private(owner, name)
        except Exception as exc:  # stated, never hidden
            return self._failed(
                mirror.full_name, mirror.repo_id,
                f"landing could not be made private: {exc}", run_at)
        result = self._credentials.sync_mirror(
            owner, name, secrets=secrets)
        if result.status != "ok":
            return self._failed(
                mirror.full_name, mirror.repo_id,
                f"{landing_note}sync failed: {result.detail}", run_at)
        repo = self._repos.get_repository(owner, name)
        if repo is None or not landing_is_private(repo.visibility):
            return self._failed(
                mirror.full_name, mirror.repo_id,
                f"{landing_note}the mirror does not stand private "
                f"after the sync; a private original never lands "
                f"any other way", run_at)
        try:
            comparison = self._verify(owner, name, token)
        except Exception as exc:  # stated, never hidden
            return self._failed(
                mirror.full_name, mirror.repo_id,
                f"{landing_note}verification could not run: {exc}",
                run_at)
        record = FirstPassRunRecord(
            full_name=mirror.full_name, phase=PHASE_PRIVATE,
            state=VERIFIED if comparison.verified else FAILED,
            refs_matched=comparison.matched,
            refs_missing=len(comparison.missing),
            refs_extra=len(comparison.extra),
            refs_diverged=len(comparison.diverged),
            detail=landing_note + comparison.headline, run_at=run_at)
        self._store(record, mirror.repo_id)
        return record

    def run_private_originals(self, owner, *,
                              secrets: Secrets | None,
                              declared_scope: object
                              ) -> PrivateOriginalsReport:
        """The private-originals run over one owner's
        census: each defined private original behind the
        credential gate, in name order; public and held
        entries counted as skipped and never touched.
        One repo's outcome never hides another's."""
        prefix = f"{owner}/"
        plan = plan_private_originals(
            [r for r in self._census.entries()
             if r.full_name.startswith(prefix)])
        report = PrivateOriginalsReport(
            skipped_public=plan.skipped_public,
            skipped_held=plan.skipped_held)
        if not plan.entries:
            report.note = ("no private originals are defined in the "
                           "census fixture; nothing was mirrored")
            return report
        for entry in plan.entries:
            entry_owner, _, entry_name = entry.full_name.partition("/")
            report.runs.append(self.run_one(
                entry_owner, entry_name,
                secrets=secrets, declared_scope=declared_scope))
        return report


def render_private_originals_page(report: PrivateOriginalsReport) -> str:
    """The private-originals page: every run named with
    its verdict -- verified, failed, or refused at the
    gate, in words, never colour-only. All text escaped."""
    parts = ["<h1>Private originals mirroring</h1>",
             f"<p>{escape_html_text(report.headline)}.</p>"]
    if report.note:
        parts.append(f"<p>{escape_html_text(report.note)}</p>")
    if report.runs:
        parts.append("<ul>")
        for record in report.runs:
            parts.append(
                f"<li>{escape_html_text(record.headline)}</li>")
        parts.append("</ul>")
    return "\n".join(parts)
