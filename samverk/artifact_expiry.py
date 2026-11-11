"""Artifact expiry job (S-267).

S-266 stored every artifact's retention policy as
data -- `retention_days` and its computed
`expires_at` on migration 105's `ci_artifacts`
row -- and judged expiry honestly at read time:
listings mark an expired artifact `expired`, and
a download is refused `artifact_expired` and
never counted. What S-266 deliberately did not
do is remove anything: the bytes' removal from
disk was named there as this slice's sweep.

This module is that sweep, under five laws:

- **Off the request path.** Nothing here is
  wired into the web server and no request ever
  sweeps: `ArtifactExpiryJob.sweep` is the job
  (an operator or a scheduler runs it, e.g.
  `python3 -m samverk.artifact_expiry <db-path>
  <data-root>`), exactly as S-235's digest job
  and S-059's gc runner are off-path. Reading
  faces only ever read standing rows.
- **The stamp is the whole law.** An artifact
  is swept exactly when S-266's own pure
  `is_expired` judges it expired at the sweep's
  clock: `expires_at` stands and the clock has
  reached it. Keep-forever rows (`expires_at`
  NULL) are never swept, however old; an
  artifact one second short of its stamp is
  never swept. There is no second judgement
  here -- the job enforces the windows S-266
  stored, it does not invent new ones.
- **UI and disk vanish together.** A swept
  artifact's row is deleted and its
  content-addressed bytes are deleted in the
  same sweep, so after a sweep the artifact is
  gone from listings, from `get_artifact` and
  from download (each answers exactly as for
  an artifact that never stood) and its bytes
  no longer sit on disk. Bytes are
  content-addressed and shared within a
  repository (S-266's delete law, restated): a
  digest's file is removed only when no
  standing row in that repository still names
  it, so sweeping one expired copy never
  breaks a live artifact that happens to hold
  the same bytes. Bytes already missing are
  counted honestly (`bytes_missing`), never
  hidden: the row still goes, because the
  retention window has closed either way.
- **S-071 reconciles.** The sweep and the
  consistency checker judge with one voice:
  S-071's checker now reconciles the artifact
  store too -- a standing expired row is drift
  (`artifact_expired_standing`), a standing
  row whose bytes are gone is drift
  (`artifact_bytes_missing`), and bytes on
  disk no standing row names are drift
  (`artifact_bytes_orphan`) -- reported, never
  silently fixed there, exactly as S-071 has
  always held. This job is the deliberate act
  taken with that report in hand: after a
  sweep, the checker finds no
  `artifact_expired_standing` drift for the
  swept clock. Orphan bytes the sweep did not
  write are not this job's to delete; the
  checker keeps reporting them for an
  operator's deliberate hand.
- **Idempotent and unwitnessed.** A sweep over
  nothing expired removes nothing and says so;
  re-running a sweep never errors and never
  double-counts. The sweep appends no audit
  entry and takes no taxonomy verb: expiry is
  the retention policy executing on schedule,
  not a poster's act -- 133 events stand
  (33 auth / 87 repo / 13 admin), as at S-266.
  No migration: the job reads and deletes the
  rows migration 105 already keeps (schema
  105 stands).
"""

from __future__ import annotations

import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .ci_artifacts import is_expired

_EXTENSION_FOR_TYPE = {
    "image/png": ".png", "image/jpeg": ".jpg",
    "image/gif": ".gif", "image/webp": ".webp",
    "application/pdf": ".pdf", "application/zip": ".zip",
    "application/gzip": ".gz", "text/plain": ".txt",
    "application/octet-stream": ".bin",
}

__all__ = [
    "ArtifactExpiryJob", "ExpiryRun", "artifact_bytes_path",
    "main", "render_artifact_expiry_page", "sweep_words",
]


def artifact_bytes_path(data_root: Path, repo_id: int,
                        sha256: str, content_type: str) -> Path:
    """One artifact's content-addressed bytes, at
    S-266's own address: `<data_root>/ci-artifacts/
    <repo>/<sha256><ext>`, the extension the
    sniffed type earned at promotion."""
    ext = _EXTENSION_FOR_TYPE.get(content_type, ".bin")
    return (Path(data_root) / "ci-artifacts"
            / str(repo_id) / f"{sha256}{ext}")


@dataclass(frozen=True)
class ExpiryRun:
    """One sweep's honest account: how many rows
    stood expired at the sweep's clock, how many
    rows and byte files the sweep removed, how
    many digests' bytes it kept because a live
    row still names them, and how many swept
    rows' bytes were already missing."""
    now: int
    expired: int
    rows_removed: int
    bytes_removed: int
    bytes_kept_shared: int
    bytes_missing: int

    @property
    def words(self) -> str:
        return sweep_words(self)


def sweep_words(run: ExpiryRun) -> str:
    """One sweep in plain words, for the job's
    command line and any operator log."""
    return (
        f"artifact expiry sweep at {run.now}: "
        f"{run.expired} expired, {run.rows_removed} rows removed, "
        f"{run.bytes_removed} byte files removed, "
        f"{run.bytes_kept_shared} kept (still named by a live row), "
        f"{run.bytes_missing} already missing")


class ArtifactExpiryJob:
    """The S-267 off-path job: enforce the
    retention windows S-266 stored, deleting
    expired rows and their bytes together."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        data_root: Path,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._data_root = Path(data_root)
        self._now = time_fn

    def expired_rows(self, now: int | None = None) -> list[sqlite3.Row]:
        """Every standing row S-266's own
        `is_expired` judges expired at *now*, in
        landing order. Pure read."""
        now = int(self._now()) if now is None else now
        rows = self._conn.execute(
            "SELECT * FROM ci_artifacts"
            " WHERE expires_at IS NOT NULL ORDER BY id").fetchall()
        return [r for r in rows if is_expired(r["expires_at"], now)]

    def sweep(self, now: int | None = None) -> ExpiryRun:
        """Remove every expired artifact: its row
        goes, and its bytes go in the same sweep
        unless a standing row in the same
        repository still names the digest."""
        now = int(self._now()) if now is None else now
        expired = self.expired_rows(now)
        bytes_removed = 0
        bytes_kept_shared = 0
        bytes_missing = 0
        paths: list[Path] = []
        with self._conn:
            for row in expired:
                self._conn.execute(
                    "DELETE FROM ci_artifacts WHERE id = ?",
                    (row["id"],))
                remaining = int(self._conn.execute(
                    "SELECT COUNT(*) c FROM ci_artifacts"
                    " WHERE repo_id = ? AND sha256 = ?",
                    (row["repo_id"], row["sha256"])).fetchone()["c"])
                if remaining > 0:
                    bytes_kept_shared += 1
                    continue
                path = artifact_bytes_path(
                    self._data_root, row["repo_id"],
                    row["sha256"], row["content_type"])
                if path.is_file():
                    paths.append(path)
                else:
                    bytes_missing += 1
        for path in paths:
            try:
                path.unlink()
                bytes_removed += 1
            except OSError:
                bytes_missing += 1
        return ExpiryRun(
            now=now, expired=len(expired),
            rows_removed=len(expired),
            bytes_removed=bytes_removed,
            bytes_kept_shared=bytes_kept_shared,
            bytes_missing=bytes_missing)


def render_artifact_expiry_page() -> str:
    """The artifact expiry job in plain words,
    where an operator finds it. S-010 escaped."""
    parts = [
        "<h1>Artifact expiry</h1>",
        "<p>Every build artifact carries the "
        "retention policy chosen at its upload "
        "(S-266): 7, 30, 90, 180 or 365 days, or "
        "keep forever, with the computed expiry "
        "stamp stored on its row. This job -- run "
        "off the request path, by an operator or "
        "a scheduler -- enforces those windows: "
        "an artifact whose stamp the clock has "
        "reached is removed whole, its row and "
        "its bytes together, so it vanishes from "
        "listings and from disk in the same "
        "sweep.</p>",
        "<p>Bytes are content-addressed and may "
        "be shared by a live artifact in the "
        "same repository; a shared file is "
        "removed only when no standing row still "
        "names it. Keep-forever artifacts are "
        "never swept. The consistency checker "
        "(S-071) reconciles the artifact store: "
        "a standing expired row, a row whose "
        "bytes are missing, and bytes no row "
        "names are each reported as drift, and "
        "this sweep is the deliberate act that "
        "clears the expired standing rows.</p>",
    ]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    """The job's command line, run by an operator
    or a scheduler -- the off-request-path entry:
    ``python3 -m samverk.artifact_expiry <db-path>
    <data-root>`` sweeps every artifact expired
    at the wall clock and prints the run's honest
    account."""
    from . import db
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: python3 -m samverk.artifact_expiry "
              "<db-path> <data-root>")
        return 2
    conn = db.init_db(Path(args[0]))
    job = ArtifactExpiryJob(conn, Path(args[1]))
    run = job.sweep()
    print(run.words)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
