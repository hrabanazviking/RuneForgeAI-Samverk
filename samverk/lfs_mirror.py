"""LFS mirror (S-340).

Roadmap S-340: **LFS objects (S-060) sync with their
repos; a mirror without its LFS objects reports itself
incomplete.**

A git mirror sync (S-070) converges the refs, but Git LFS
objects do not travel with a fetch: the repo carries small
pointer files (S-060) and the bytes live beside the bare
repo under ``lfs/objects/``. A mirror can therefore stand
ref-for-ref verified (S-336/S-337) while every large file
in it is a pointer to bytes it does not hold. This slice
closes that gap, under three laws:

- **Completeness is computed, never asserted.** The
  pointers are read out of the mirror's own blobs (every
  blob reachable from its refs, parsed by S-060's
  ``parse_pointer``) and judged against the objects
  actually present in its S-060 store, each present
  object re-verified by oid and size. Missing and
  corrupt objects are named by oid and counted in
  bytes; the verdict is a pure judgement
  (``judge_completeness``) over those facts.
- **Incomplete never looks healthy.** A mirror missing
  or holding corrupt LFS objects states ``incomplete``
  in plain words and ``healthy == False`` -- on its own
  page and in the combined honest status, where the
  S-332 sync verdict and this completeness verdict must
  *both* be good before the mirror may call itself
  healthy. A green git sync cannot borrow health over
  missing LFS bytes.
- **Sync copies through the store, verified.** The LFS
  sync copies each missing (or corrupt) object from the
  source repo's S-060 store into the mirror's through
  ``LFSStore.put``, which verifies integrity by oid on
  write (S-060's law): bytes that do not hash to the
  pointer's oid store nothing. An object the source
  itself does not hold is stated as still missing --
  never papered over. Local sources sync this way; a
  URL source's LFS objects cannot be read through the
  local-store seam, so its sync is recorded failed in
  plain words and the mirror stays incomplete until its
  objects arrive by a road that can carry them.

Every sync outcome -- complete, incomplete, or refused
-- is recorded in the standing run log
(``first_pass_mirror_runs``, phase ``lfs``; the ref
count columns carry the object counts: matched =
objects present, missing = objects missing, diverged =
objects corrupt). No migration and no new audit event:
the schema stands at 138 and the taxonomy stands at
138, reusing S-060's store, S-070's mirror record,
S-332's sync status, and S-336's run log on purpose.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .escaping import escape_html_text
from .first_pass_mirroring import FAILED, VERIFIED, FirstPassRunRecord
from .lfs_store import LFSError, LFSPointer, LFSStore, parse_pointer
from .mirrors import MirrorService
from .proc import run_git_in
from .repositories import RepositoryStore
from .sync_status import SyncStatusService

PHASE_LFS = "lfs"

STATE_COMPLETE = "complete"
STATE_INCOMPLETE = "incomplete"
STATE_NO_LFS = "no_lfs"

_POINTER_MAX_BYTES = 1024
_GIT_OID_RE = re.compile(r"^[0-9a-f]{40,64}$")


class LFSMirrorError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class LFSCompleteness:
    """The pure verdict: a repo's LFS pointers judged
    against the objects its store actually holds."""
    full_name: str
    pointers: tuple[LFSPointer, ...]
    present: tuple[str, ...]
    missing: tuple[str, ...]
    corrupt: tuple[str, ...]

    @property
    def expected(self) -> int:
        return len(self.pointers)

    @property
    def present_count(self) -> int:
        return len(self.present)

    @property
    def expected_bytes(self) -> int:
        return sum(p.size for p in self.pointers)

    @property
    def missing_bytes(self) -> int:
        sizes = {p.oid: p.size for p in self.pointers}
        return sum(sizes[o] for o in self.missing + self.corrupt)

    @property
    def complete(self) -> bool:
        return not self.missing and not self.corrupt

    @property
    def healthy(self) -> bool:
        """Healthy only when complete -- a mirror without
        its LFS objects never looks healthy."""
        return self.complete

    @property
    def state(self) -> str:
        if self.expected == 0:
            return STATE_NO_LFS
        return STATE_COMPLETE if self.complete else STATE_INCOMPLETE

    @property
    def headline(self) -> str:
        if self.expected == 0:
            return (f"{self.full_name}: no LFS pointers in this "
                    f"repository; no LFS objects are needed")
        if self.complete:
            return (f"{self.full_name}: LFS complete -- all "
                    f"{self.expected} LFS objects are present "
                    f"({self.expected_bytes} bytes)")
        parts = [f"{len(self.missing)} missing" if self.missing else "",
                 f"{len(self.corrupt)} corrupt" if self.corrupt else ""]
        named = " and ".join(p for p in parts if p)
        return (f"{self.full_name}: LFS incomplete -- {named} of "
                f"{self.expected} LFS objects "
                f"({self.missing_bytes} bytes not usable); this "
                f"mirror is not complete and not healthy")


def judge_completeness(full_name: str,
                       pointers: Iterable[LFSPointer],
                       present_oids: Iterable[str],
                       corrupt_oids: Iterable[str] = ()) -> LFSCompleteness:
    """Judge pointers against present objects. Pure:
    reads nothing, writes nothing. Pointers dedupe by oid
    (one object, however many files point at it); a
    present object named corrupt counts as not usable,
    never as present."""
    by_oid: dict[str, LFSPointer] = {}
    for pointer in pointers:
        by_oid.setdefault(pointer.oid, pointer)
    ordered = tuple(by_oid[o] for o in sorted(by_oid))
    present_set = set(present_oids)
    corrupt_set = {o for o in corrupt_oids if o in present_set and o in by_oid}
    present = tuple(sorted(
        o for o in by_oid if o in present_set and o not in corrupt_set))
    missing = tuple(sorted(o for o in by_oid if o not in present_set))
    return LFSCompleteness(
        full_name=full_name, pointers=ordered, present=present,
        missing=missing, corrupt=tuple(sorted(corrupt_set)))


def plan_lfs_sync(pointers: Iterable[LFSPointer],
                  present_oids: Iterable[str],
                  corrupt_oids: Iterable[str] = ()) -> tuple[str, ...]:
    """The oids a sync must fetch: missing plus corrupt,
    in oid order. Pure."""
    verdict = judge_completeness("", pointers, present_oids, corrupt_oids)
    return tuple(sorted(verdict.missing + verdict.corrupt))


@dataclass
class LFSMirrorReport:
    full_name: str
    before: LFSCompleteness
    after: LFSCompleteness
    copied: int = 0
    source_missing: tuple[str, ...] = ()
    detail: str = ""
    run: FirstPassRunRecord | None = None

    @property
    def complete(self) -> bool:
        return self.after.complete

    @property
    def headline(self) -> str:
        return self.after.headline


@dataclass(frozen=True)
class HonestMirrorStatus:
    """S-332's sync verdict and S-340's completeness
    verdict, in one honest place."""
    full_name: str
    sync_state: str | None
    sync_healthy: bool
    lfs: LFSCompleteness

    @property
    def healthy(self) -> bool:
        """Healthy only when the last git sync succeeded
        *and* every LFS object is present and sound."""
        return self.sync_healthy and self.lfs.complete

    @property
    def headline(self) -> str:
        if self.healthy:
            return f"{self.full_name}: healthy -- sync and LFS complete."
        if not self.lfs.complete:
            return (f"{self.full_name}: not healthy -- "
                    f"{self.lfs.headline}")
        return (f"{self.full_name}: not healthy -- the last sync "
                f"did not succeed (sync state: {self.sync_state}).")


class LFSMirrorService:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._now = time_fn
        self._mirrors = MirrorService(
            conn, data_root, accounts, repositories,
            audit=audit, time_fn=time_fn)
        self._sync_status = SyncStatusService(
            conn, data_root, accounts, repositories)

    # -- fact reading ------------------------------------------------
    def pointers_in_repo(self, repo_path: Path) -> list[LFSPointer]:
        """Every distinct LFS pointer among the blobs
        reachable from the repo's refs, parsed by S-060.
        A repo with no refs carries no pointers."""
        result = run_git_in(
            Path(repo_path), ["rev-list", "--objects", "--all"],
            timeout=60.0)
        if result.returncode != 0:
            detail = result.stderr.decode(
                "utf-8", "replace").strip()[:200]
            raise LFSMirrorError(
                "repo_unreadable",
                f"The repository's objects cannot be listed: {detail}")
        found: dict[str, LFSPointer] = {}
        seen: set[str] = set()
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            oid = line.split(" ", 1)[0].strip()
            if not _GIT_OID_RE.match(oid) or oid in seen:
                continue
            seen.add(oid)
            kind = run_git_in(Path(repo_path), ["cat-file", "-t", oid],
                              timeout=30.0)
            if kind.returncode != 0 or kind.stdout.decode(
                    "utf-8", "replace").strip() != "blob":
                continue
            size = run_git_in(Path(repo_path), ["cat-file", "-s", oid],
                              timeout=30.0)
            try:
                blob_size = int(size.stdout.decode().strip())
            except (ValueError, UnicodeDecodeError):
                continue
            if blob_size > _POINTER_MAX_BYTES:
                continue
            blob = run_git_in(Path(repo_path), ["cat-file", "blob", oid],
                              timeout=30.0)
            if blob.returncode != 0:
                continue
            try:
                pointer = parse_pointer(blob.stdout)
            except LFSError:
                continue
            found.setdefault(pointer.oid, pointer)
        return [found[o] for o in sorted(found)]

    @staticmethod
    def present_oids(repo_path: Path) -> list[str]:
        root = Path(repo_path) / "lfs" / "objects"
        if not root.is_dir():
            return []
        return sorted(p.name for p in root.rglob("*") if p.is_file())

    def _judge(self, full_name: str, repo_path: Path) -> LFSCompleteness:
        pointers = self.pointers_in_repo(repo_path)
        present = self.present_oids(repo_path)
        store = LFSStore(repo_path)
        sizes = {p.oid: p.size for p in pointers}
        corrupt = [o for o in present if o in sizes
                   and (store.size_of(o) != sizes[o]
                        or not store.verify(o))]
        return judge_completeness(full_name, pointers, present, corrupt)

    def completeness_for(self, owner, repo) -> LFSCompleteness:
        """The completeness verdict for one repository,
        computed from its pointers and its store."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise LFSMirrorError("no_such_repo", "No such repository.")
        return self._judge(current.full_name,
                           self._repos.path_for(owner, repo))

    def honest_status(self, owner, repo) -> HonestMirrorStatus:
        """The S-332 seam, held to S-340's law: git-sync
        health and LFS completeness in one verdict."""
        verdict = self.completeness_for(owner, repo)
        status = self._sync_status.status_for(owner, repo)
        return HonestMirrorStatus(
            full_name=verdict.full_name,
            sync_state=status.state if status else None,
            sync_healthy=bool(status and status.healthy),
            lfs=verdict)

    # -- records -------------------------------------------------------
    def _store_run(self, record: FirstPassRunRecord, repo_id: int) -> None:
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
            (full_name, PHASE_LFS)).fetchall()
        return [FirstPassRunRecord(
            full_name=row["full_name"], phase=row["phase"],
            state=row["state"], refs_matched=row["refs_matched"],
            refs_missing=row["refs_missing"],
            refs_extra=row["refs_extra"],
            refs_diverged=row["refs_diverged"],
            detail=row["detail"], run_at=row["run_at"])
            for row in rows]

    # -- the sync --------------------------------------------------------
    def sync_lfs(self, owner, repo) -> LFSMirrorReport:
        """Sync one mirror's LFS objects from its source.
        Every outcome is recorded in the standing run log;
        an incomplete result is a failed run, stated in
        plain words, however the copying went."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise LFSMirrorError("no_such_repo", "No such repository.")
        mirror = self._mirrors.mirror_for(owner, repo)
        if mirror is None:
            raise LFSMirrorError(
                "not_a_mirror", f"{current.full_name} is not a mirror.")
        mirror_path = self._repos.path_for(owner, repo)
        before = self._judge(current.full_name, mirror_path)
        run_at = int(self._now())
        copied = 0
        source_missing: tuple[str, ...] = ()
        note = ""
        if before.expected == 0:
            note = "no LFS pointers; nothing to sync"
            after = before
        elif mirror.source_kind != "local":
            note = ("the source is a remote URL; its LFS objects "
                    "cannot be read through the local LFS store, "
                    "so none were copied")
            after = before
        else:
            source_path = Path(mirror.source)
            source_store = LFSStore(source_path)
            dest_store = LFSStore(mirror_path)
            wanted = plan_lfs_sync(before.pointers, before.present,
                                   before.corrupt)
            absent: list[str] = []
            for oid in wanted:
                if not source_store.has(oid):
                    absent.append(oid)
                    continue
                data = source_store.read(oid)
                if oid in before.corrupt:
                    dest_store.path_for(oid).unlink(missing_ok=True)
                size = {p.oid: p.size for p in before.pointers}[oid]
                dest_store.put(oid, data, expected_size=size)
                copied += 1
            source_missing = tuple(absent)
            after = self._judge(current.full_name, mirror_path)
            note = f"copied {copied} LFS objects from the source"
            if source_missing:
                note += (f"; the source itself does not hold "
                         f"{len(source_missing)} of the needed "
                         f"objects, which stay missing")
        detail = f"{note}; {after.headline}"
        record = FirstPassRunRecord(
            full_name=current.full_name, phase=PHASE_LFS,
            state=VERIFIED if after.complete else FAILED,
            refs_matched=after.present_count,
            refs_missing=len(after.missing), refs_extra=0,
            refs_diverged=len(after.corrupt), detail=detail,
            run_at=run_at)
        self._store_run(record, current.id)
        return LFSMirrorReport(
            full_name=current.full_name, before=before, after=after,
            copied=copied, source_missing=source_missing,
            detail=detail, run=record)


def render_lfs_mirror_page(report: LFSMirrorReport) -> str:
    """The LFS mirror page: the verdict in words --
    complete, or incomplete with the missing and corrupt
    objects named -- never colour-only, never healthy
    when incomplete. All text escaped."""
    after = report.after
    parts = ["<h1>LFS mirror</h1>",
             f"<p>{escape_html_text(after.headline)}.</p>",
             ("<p>Healthy: yes.</p>" if after.healthy
              else "<p>Healthy: no.</p>"),
             f"<p>{escape_html_text(report.detail)}</p>"]
    if after.missing:
        parts.append("<p>Missing LFS objects:</p><ul>")
        for oid in after.missing:
            parts.append(f"<li>{escape_html_text(oid)}</li>")
        parts.append("</ul>")
    if after.corrupt:
        parts.append("<p>Corrupt LFS objects:</p><ul>")
        for oid in after.corrupt:
            parts.append(f"<li>{escape_html_text(oid)}</li>")
        parts.append("</ul>")
    return "\n".join(parts)


def render_lfs_completeness_page(verdict: LFSCompleteness) -> str:
    """One repo's completeness, rendered alone: the same
    honest words, for a repo page that has no sync run
    to report yet."""
    report = LFSMirrorReport(
        full_name=verdict.full_name, before=verdict, after=verdict,
        detail=verdict.headline)
    return render_lfs_mirror_page(report)
