"""Drift census (S-343) -- a weekly read-only job
comparing mirror heads against source heads; drift
beyond the sync interval is reported to the owner,
quietly and factually.

Part XVII gave Samverk mirrors a schedule (S-331), an
honest status (S-332), a first verified pass (S-336),
private originals (S-337), and imported metadata
(S-338). What none of those did was *look again later*:
a mirror can fall behind its source and stay behind,
and nothing said so. This module is that look, under
four laws:

- **Read-only, always.** The census compares and
  reports. It never syncs, never fetches into a mirror,
  never writes a mirror record, and never touches a
  source. Source heads are read through S-014's
  ``ls-remote`` seam (``run_git_ls_remote_refs`` -- a
  listing, not a fetch); mirror heads are read from
  the mirror's own refs through S-051's ``RefStore``.
  A census run leaves every ref and every
  ``repo_mirrors`` row exactly as it found them.
- **Drift is a fact about time, not a feeling.** A
  mirror whose heads differ from its source's heads is
  *behind*. It is *drifted* only when it has stayed
  behind beyond its own sync interval (S-331's
  per-mirror interval, the 24-hour founding cadence by
  default), measured from its last successful sync
  (S-332's ``last_success_at`` -- a failed attempt never
  moves that moment). Behind within the interval is
  the ordinary state between syncs and is reported as
  behind, not as drift. A mirror that has never synced
  successfully is said to be never synced; a source
  that cannot be read is said to be unreadable, with
  the recorded detail beside the words. Nothing is
  guessed: unknown ages and unreadable sources are
  stated as what they are.
- **Weekly, off the request path.** ``run_census`` is
  the job entry point: an operator or a scheduler runs
  it (``python3 -m samverk.drift_census <db-path>
  <repos-root>``), at most once a week by the pure
  ``census_due`` judgement. Nothing here is called by
  a request handler; the render page only displays a
  report a census already made.
- **Quiet and factual.** The report counts what it
  checked and states each mirror's state in plain
  words. It carries no alarm language: drift is a
  fact to act on at the owner's pace, stated once,
  exactly as found.

The judgements are pure. ``assess_drift`` judges one
mirror's two ref maps, its last success, the moment,
and its interval, and writes nothing; ``census_due``
judges the week and writes nothing. The service reads
both sides of every mirror and records nothing -- the
report exists only where the caller keeps it. No
migration (schema 139 stands) and no new audit event
(the taxonomy stands at 138): a read-only job that
wrote records to report on records would be neither.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .accounts import AccountStore
from .escaping import escape_html_text
from .first_pass_mirroring import compare_ref_maps, parse_ls_remote
from .proc import ProcRefused, run_git_ls_remote_refs
from .refs import RefStore
from .repositories import RepositoryStore
from .sync_scheduler import DEFAULT_INTERVAL_SECONDS

__all__ = [
    "CENSUS_INTERVAL_SECONDS", "STATE_BEHIND", "STATE_DRIFTED",
    "STATE_IN_SYNC", "STATE_NEVER_SYNCED", "STATE_UNREADABLE",
    "DriftAssessment", "DriftCensusEntry", "DriftCensusReport",
    "DriftCensusService", "assess_drift", "census_due",
    "census_to_dict", "entry_to_dict", "main",
    "render_drift_census_page",
]

CENSUS_INTERVAL_SECONDS = 7 * 86400  # the weekly cadence

STATE_IN_SYNC = "in_sync"
STATE_BEHIND = "behind"
STATE_DRIFTED = "drifted"
STATE_NEVER_SYNCED = "never_synced"
STATE_UNREADABLE = "unreadable"

_STATE_WORDS = {
    STATE_IN_SYNC: "in sync -- the mirror's heads match its source",
    STATE_BEHIND: ("behind -- the source has moved since the last "
                   "successful sync, within the sync interval"),
    STATE_DRIFTED: ("drifted -- the source moved beyond the sync "
                    "interval since the last successful sync"),
    STATE_NEVER_SYNCED: "never synced -- no successful sync is recorded",
    STATE_UNREADABLE: "unreadable -- the source's heads could not be read",
}


@dataclass(frozen=True)
class DriftAssessment:
    """The pure verdict for one mirror."""
    state: str
    matched: int
    missing: int          # advertised by the source, absent in the mirror
    extra: int            # in the mirror, not advertised by the source
    diverged: int         # in both, at different object ids
    age_seconds: int | None   # now - last success; None when never synced
    interval_seconds: int

    @property
    def heads_match(self) -> bool:
        return (self.missing == 0 and self.extra == 0
                and self.diverged == 0)

    @property
    def state_word(self) -> str:
        return _STATE_WORDS[self.state]


def assess_drift(source_refs: dict[str, str],
                 mirror_refs: dict[str, str],
                 last_success_at: int | None,
                 now: int, interval_seconds: int) -> DriftAssessment:
    """Judge one mirror's drift. Pure: reads nothing,
    writes nothing.

    Heads that match are in sync at any age. Heads that
    differ are behind; behind becomes drift only when
    the time since the last successful sync is *beyond*
    the interval -- exactly at the interval is still
    within it. With no successful sync recorded, differing
    heads are never-synced, however old the mirror is:
    the census does not invent a success to measure from."""
    comparison = compare_ref_maps(source_refs, mirror_refs)
    counts = dict(matched=comparison.matched,
                  missing=len(comparison.missing),
                  extra=len(comparison.extra),
                  diverged=len(comparison.diverged),
                  interval_seconds=int(interval_seconds))
    if comparison.missing == () and comparison.extra == () \
            and comparison.diverged == ():
        age = (int(now) - int(last_success_at)
               if last_success_at is not None else None)
        return DriftAssessment(state=STATE_IN_SYNC, age_seconds=age,
                               **counts)
    if last_success_at is None:
        return DriftAssessment(state=STATE_NEVER_SYNCED,
                               age_seconds=None, **counts)
    age = int(now) - int(last_success_at)
    state = (STATE_DRIFTED if age > int(interval_seconds)
             else STATE_BEHIND)
    return DriftAssessment(state=state, age_seconds=age, **counts)


def census_due(last_census_at: int | None, now: int) -> bool:
    """Pure: the weekly cadence -- a census is due when
    none has run, or when the last one is a week or more
    old."""
    if last_census_at is None:
        return True
    return int(now) - int(last_census_at) >= CENSUS_INTERVAL_SECONDS


@dataclass(frozen=True)
class DriftCensusEntry:
    full_name: str
    state: str
    interval_seconds: int
    last_success_at: int | None
    age_seconds: int | None
    matched: int
    missing: int
    extra: int
    diverged: int
    detail: str = ""

    @property
    def state_word(self) -> str:
        return _STATE_WORDS[self.state]

    @property
    def headline(self) -> str:
        return f"{self.full_name}: {self.state_word}."


def entry_to_dict(entry: DriftCensusEntry) -> dict:
    """The public facts of one census entry -- names,
    states, times, and counts only; no source, no secret."""
    return {
        "full_name": entry.full_name,
        "state": entry.state,
        "interval_seconds": entry.interval_seconds,
        "last_success_at": entry.last_success_at,
        "age_seconds": entry.age_seconds,
        "refs_matched": entry.matched,
        "refs_missing": entry.missing,
        "refs_extra": entry.extra,
        "refs_diverged": entry.diverged,
        "detail": entry.detail,
    }


@dataclass
class DriftCensusReport:
    census_at: int
    entries: list[DriftCensusEntry] = field(default_factory=list)

    def _count(self, state: str) -> int:
        return sum(1 for e in self.entries if e.state == state)

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def in_sync_count(self) -> int:
        return self._count(STATE_IN_SYNC)

    @property
    def behind_count(self) -> int:
        return self._count(STATE_BEHIND)

    @property
    def drifted(self) -> list[DriftCensusEntry]:
        return [e for e in self.entries if e.state == STATE_DRIFTED]

    @property
    def headline(self) -> str:
        """The census in one quiet, factual sentence."""
        if self.total == 0:
            return ("Drift census: no mirrors are recorded; "
                    "nothing was compared.")
        noun = "mirror" if self.total == 1 else "mirrors"
        text = (f"Drift census: {self.total} {noun} compared; "
                f"{self.in_sync_count} in sync, "
                f"{self.behind_count} behind within their sync "
                f"interval, {len(self.drifted)} drifted beyond "
                f"their sync interval, "
                f"{self._count(STATE_NEVER_SYNCED)} never synced, "
                f"{self._count(STATE_UNREADABLE)} unreadable.")
        return text


def census_to_dict(report: DriftCensusReport) -> dict:
    return {
        "census_at": report.census_at,
        "total": report.total,
        "in_sync": report.in_sync_count,
        "behind": report.behind_count,
        "drifted": len(report.drifted),
        "never_synced": report._count(STATE_NEVER_SYNCED),
        "unreadable": report._count(STATE_UNREADABLE),
        "entries": [entry_to_dict(e) for e in report.entries],
    }


class DriftCensusService:
    """The weekly census over every recorded mirror:
    read each source's heads through the S-014 seam,
    read each mirror's own heads, judge purely, and
    report. Read-only -- it holds no write path at all."""

    def __init__(self, conn: sqlite3.Connection,
                 data_root: Path,
                 accounts: AccountStore,
                 repositories: RepositoryStore,
                 time_fn: Callable[[], float] = time.time,
                 ls_remote_fn: Callable[..., object] = run_git_ls_remote_refs):
        self._conn = conn
        self._repos = repositories
        self._now = time_fn
        self._ls_remote = ls_remote_fn

    # -- reading both sides -----------------------------------
    def _source_refs(self, source: str, source_kind: str) -> dict[str, str]:
        target: str | Path = (Path(source) if source_kind == "local"
                              else source)
        result = self._ls_remote(target, timeout=120.0)
        if result.returncode != 0:
            detail = result.stderr.decode(
                "utf-8", "replace").strip()[:200] or "ls-remote failed"
            raise ValueError(detail)
        return parse_ls_remote(result.stdout.decode("utf-8", "replace"))

    def _mirror_refs(self, owner: str, name: str) -> dict[str, str]:
        path = self._repos.path_for(owner, name)
        return {ref.name: ref.oid for ref in RefStore(path).list_refs()
                if ref.name.startswith("refs/heads/")
                or ref.name.startswith("refs/tags/")}

    # -- the census ----------------------------------------------
    def run_census(self, now: int | None = None) -> DriftCensusReport:
        """Compare every mirror against its source and
        report. One mirror's unreadable source is that
        mirror's entry, stated plainly; it never stops
        the census and never hides the other mirrors."""
        moment = int(self._now()) if now is None else int(now)
        rows = self._conn.execute(
            "SELECT m.*, r.owner AS owner, r.name AS name"
            " FROM repo_mirrors m"
            " JOIN repositories r ON r.id = m.repo_id"
            " ORDER BY r.owner, r.name").fetchall()
        report = DriftCensusReport(census_at=moment)
        for row in rows:
            keys = row.keys()
            owner, name = row["owner"], row["name"]
            full_name = f"{owner}/{name}"
            stored = (row["sync_interval_seconds"]
                      if "sync_interval_seconds" in keys else None)
            interval = (stored if stored is not None
                        else DEFAULT_INTERVAL_SECONDS)
            last_success = (row["last_success_at"]
                            if "last_success_at" in keys else None)
            try:
                source_refs = self._source_refs(
                    row["source"], row["source_kind"])
                mirror_refs = self._mirror_refs(owner, name)
            except Exception as exc:  # stated, never hidden, never raised
                report.entries.append(DriftCensusEntry(
                    full_name=full_name, state=STATE_UNREADABLE,
                    interval_seconds=interval,
                    last_success_at=last_success, age_seconds=None,
                    matched=0, missing=0, extra=0, diverged=0,
                    detail=f"{type(exc).__name__}: {exc}"[:200]))
                continue
            verdict = assess_drift(source_refs, mirror_refs,
                                   last_success, moment, interval)
            report.entries.append(DriftCensusEntry(
                full_name=full_name, state=verdict.state,
                interval_seconds=interval,
                last_success_at=last_success,
                age_seconds=verdict.age_seconds,
                matched=verdict.matched, missing=verdict.missing,
                extra=verdict.extra, diverged=verdict.diverged))
        return report


def _when(ts: int | None) -> str:
    if ts is None:
        return "never"
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts))


def render_drift_census_page(report: DriftCensusReport) -> str:
    """The owner-facing census page: the headline count,
    then each mirror's state in words with its last
    success and ref counts -- never colour-only, never
    alarm language. Every value escaped through S-010."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>Drift census -- Samverk</title></head>",
        "<body>",
        "<h1>Drift census</h1>",
        f"<p>{escape_html_text(report.headline)}</p>",
        f"<p>Census taken: {escape_html_text(_when(report.census_at))}.</p>",
        "<ul>",
    ]
    for entry in report.entries:
        line = (f"{entry.headline} Last successful sync: "
                f"{_when(entry.last_success_at)}. Refs: "
                f"{entry.matched} matched, {entry.missing} missing, "
                f"{entry.extra} extra, {entry.diverged} diverged.")
        if entry.detail:
            line += f" Recorded detail: {entry.detail}"
        parts.append(f"<li>{escape_html_text(line)}</li>")
    parts += ["</ul>", "</body></html>"]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    """The job's command line, run by an operator or a
    scheduler -- the off-request-path entry:
    ``python3 -m samverk.drift_census <db-path>
    <repos-root>`` compares every mirror against its
    source, prints the census headline and one line per
    mirror, and writes nothing."""
    from . import db
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: python3 -m samverk.drift_census "
              "<db-path> <repos-root>")
        return 2
    conn = db.init_db(Path(args[0]))
    accounts = AccountStore(conn)
    repos = RepositoryStore(conn, Path(args[1]), accounts)
    service = DriftCensusService(conn, Path(args[1]), accounts, repos)
    report = service.run_census()
    print(report.headline)
    for entry in report.entries:
        print(entry.headline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
