"""CI logs -- log streaming and storage (S-322).

Log streaming and storage -- live log tail in
the UI, stored logs with retention (S-267's
machinery), download as text.

S-316's protocol already speaks logs: a runner
streams a job's output as numbered `log_chunk`
messages (per step, per-step sequence, stdout or
stderr), and S-318's reference runner sends them.
Until this slice those chunks had nowhere to
land -- a run's output existed only while the
runner held it. This module is the landing: the
stored log a job leaves behind, the tail the UI
polls while the job still runs, and the text
download a reader keeps afterwards.

- **One stored log per job.** A log is addressed
  by the triple every neighbouring face already
  uses -- repository, `run_id`, `job_id` (S-316's
  own identity, judged by S-316's name law) --
  and holds the job's whole output as one text:
  chunks and appends concatenate verbatim, in
  arrival order, so the stored text is exactly
  the stream the runner sent. `append_log` is
  the text road, `append_chunk` the S-316
  `LogChunk` road, and `append_payload` the raw
  wire road: a runner's `log_chunk` message is
  judged whole by S-316's `parse_log_chunk`
  (against the caller's expected sequence when
  one is known) before a byte lands, and S-316's
  refusals ride this face's error verbatim. The
  appends are the forge's own sink, inside the
  trust boundary like S-321's landing: the
  caller is the instance's scheduler/runner
  sink, and a repository that does not stand is
  refused `repository_not_found`. Every refusal
  validates whole and stores nothing -- a
  refused append leaves a standing log exactly
  as it stood.
- **Redacted before storage, always.** No text
  reaches the row unfiltered: every append
  passes through S-018's `redact_text` (with
  any caller-named extra secrets handed to it),
  so a credential a step printed -- a bearer
  token, a `password=` pair, a registered
  secret's literal value -- is struck to the
  visible `[REDACTED]` marker before it is
  stored, and no read, tail, page or download
  can ever serve what was never stored. The
  battery sweeps the stored row itself for a
  seeded secret and finds only the marker.
- **Retention is S-266's data, enforced
  S-267's way.** A log is born with one of
  S-266's retention choices (`RETENTION_CHOICES`:
  0 keeps forever, else 7, 30, 90, 180 or 365
  days; default 90), chosen at its first
  append and standing for its life -- an
  append naming a different retention is
  refused `log_retention_mismatch`, and one
  naming a different workflow than the log
  stands under is refused
  `log_workflow_mismatch`. The row stores the
  choice and the expiry stamp S-266's own
  `decide_expiry` computes. Reads judge expiry
  with S-266's own `is_expired`: an expired log
  answers every read -- get, tail, list,
  download -- exactly as a log that never
  stood (`log_not_found`), from the moment its
  stamp is reached. The off-path sweep
  (`LogExpiryJob`, below, and this module's
  command line) is S-267's pattern restated
  for logs: run by an operator or a scheduler,
  never on the request path, it deletes every
  expired row, so after a sweep the log has
  vanished from storage and from reads
  together. The sweep is idempotent and
  unwitnessed, exactly as S-267's is. An append
  that arrives after its log expired starts a
  fresh log at the append's clock -- the
  expired text never resurrects.
- **Reads follow the repository (S-054).**
  Every read takes a viewer and resolves the
  repository through S-054's `can_read` before
  any log is named: a missing repository and a
  private repository the viewer cannot read
  answer the one uniform
  `repository_not_found`, so a stranger learns
  nothing about a private repository's runs.
  Anonymous readers read public repositories'
  logs, as everywhere else in the forge.
- **The tail is a window, never a truncation
  of the record.** `tail_log` answers the last
  N lines of the stored text (default
  `DEFAULT_TAIL_LINES`, at most
  `MAX_TAIL_LINES` -- a larger ask is refused
  `log_tail_invalid`, never silently served
  short) with the log's total line count, the
  1-based number of the first line shown, and
  whether earlier lines stand above the
  window: exactly what a polling UI needs to
  say "showing the last 100 of 4,213 lines"
  and to notice the log grow between polls.
  Line counting is one law everywhere
  (`count_lines`: `splitlines`, so a final
  unterminated line still counts), and the
  stored row carries the count the audit
  re-proves. `download_log` answers the whole
  stored text as `text/plain` under the bare
  filename `<run_id>-<job_id>.log` -- the run
  and job names are S-316-lawful names, so the
  filename is never a path.
- **Bounded, and the bound refuses.** A stored
  log holds at most `MAX_LOG_CHARS`
  characters; an append that would cross the
  bound is refused whole (`log_too_large`)
  and the standing log is untouched -- a
  flooded job loses its later output loudly,
  never its earlier record silently.
- **The durable artefact is the log row.**
  Appends, reads and sweeps write no audit
  row and claim no taxonomy event (135 stand:
  33 auth / 89 repo / 13 admin), on S-321's
  basis for appends and S-267's for the sweep:
  the witnessed record of a job's output is
  the log itself. Storage is migration 131
  (schema 130 to 131): `ci_logs` -- one row
  per (repository, run, job), the redacted
  text, its line count, its retention choice
  and expiry stamp. S-327 owns the routed run
  pages that render these rows; the render
  function here is the log view in the house
  shape, every value escaped through S-010.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import taxonomy
from .accounts import User
from .ci_artifacts import (
    DEFAULT_RETENTION_DAYS, RETENTION_CHOICES,
    decide_expiry, is_expired)
from .escaping import escape_html_text
from .log_redaction import redact_text
from .permissions import can_read
from .repositories import RepositoryStore
from .runner_protocol import (
    LogChunk, RunnerProtocolError, parse_log_chunk)

__all__ = [
    "DEFAULT_TAIL_LINES", "MAX_LOG_CHARS",
    "MAX_TAIL_LINES", "JobLog", "LogDownload",
    "LogExpiryJob", "LogStreamingAudit",
    "LogStreamingError", "LogStreamingStore",
    "LogSweep", "LogTail", "audit_log_streaming",
    "count_lines", "download_filename_for",
    "is_log_expired", "log_to_dict", "main",
    "render_log_page", "sweep_words",
    "tail_lines", "tail_to_dict",
    "validate_log_identity", "validate_retention_days",
    "validate_tail_lines",
]

#: Lines a tail answers when the caller names
#: no count: enough for a screen, cheap to poll.
DEFAULT_TAIL_LINES = 100

#: The largest tail window one read may ask
#: for. Past it the ask is refused whole, in
#: the house shape -- a UI pages by polling,
#: and the download road serves the whole log.
MAX_TAIL_LINES = 1000

#: The most characters one job's stored log
#: may hold. An append crossing the bound is
#: refused whole; the standing log stands.
MAX_LOG_CHARS = 1_000_000

#: S-316's name law, restated for the two ids
#: that address a log (the protocol judges its
#: own messages; this store judges its calls).
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_SURFACE_WORD = "ci_logs"


class LogStreamingError(ValueError):
    """One refused log-streaming call: a
    machine-branchable reason with its human
    detail, in the house shape."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def validate_retention_days(value: object) -> int:
    """One retention choice, judged whole:
    absent is S-266's default; a standing
    choice is one of `RETENTION_CHOICES`
    (0 keeps forever). Pure."""
    if value is None:
        return DEFAULT_RETENTION_DAYS
    if (isinstance(value, bool) or not isinstance(value, int)
            or value not in RETENTION_CHOICES):
        raise LogStreamingError(
            "retention_invalid",
            "retention_invalid -- retention is one "
            "of 0 (keep forever), 7, 30, 90, 180 or "
            "365 days. Nothing was recorded.")
    return value


def validate_log_identity(run_id: object,
                          job_id: object) -> tuple:
    """The two ids that address one job's log,
    judged by S-316's name law: letters, digits,
    '.', '_' or '-', starting alphanumeric.
    Pure."""
    for label, value in (("run", run_id), ("job", job_id)):
        if not isinstance(value, str) \
                or not _NAME_RE.match(value):
            raise LogStreamingError(
                "log_identity_invalid",
                f"log_identity_invalid -- a log's "
                f"{label} id is a name: letters, "
                "digits, '.', '_' or '-', starting "
                "alphanumeric. Nothing was recorded.")
    return str(run_id), str(job_id)


def validate_tail_lines(value: object) -> int:
    """One tail window's size, judged whole:
    absent is the default; a standing ask is a
    whole number from 1 to `MAX_TAIL_LINES`.
    Pure."""
    if value is None:
        return DEFAULT_TAIL_LINES
    if (isinstance(value, bool) or not isinstance(value, int)
            or value < 1 or value > MAX_TAIL_LINES):
        raise LogStreamingError(
            "log_tail_invalid",
            f"log_tail_invalid -- a tail asks for "
            f"a whole number of lines, from 1 to "
            f"{MAX_TAIL_LINES}. Nothing was "
            "recorded.")
    return value


def count_lines(text: str) -> int:
    """One log text's line count, the one law
    every face uses: `splitlines`, so a final
    line without its newline still counts, and
    the empty text has no lines. Pure."""
    if not text:
        return 0
    return len(text.splitlines())


def tail_lines(text: str, count: int) -> tuple:
    """The last *count* lines of *text*, in
    order -- the pure window `tail_log` serves.
    Pure."""
    lines = text.splitlines()
    if count >= len(lines):
        return tuple(lines)
    return tuple(lines[len(lines) - count:])


def is_log_expired(expires_at: int | None, now: int) -> bool:
    """Whether one log stands expired at *now*,
    by S-266's own judgement (S-267's stamp law):
    forever never expires; at the stamp itself
    the log is already expired. Pure."""
    return is_expired(expires_at, now)


def download_filename_for(run_id: str, job_id: str) -> str:
    """The bare filename one log downloads
    under: `<run_id>-<job_id>.log`. The ids are
    S-316-lawful names, so the filename carries
    no separator and is never a path. Pure."""
    return f"{run_id}-{job_id}.log"


@dataclass(frozen=True)
class JobLog:
    """One job's stored log: its address, its
    whole redacted text, its line count, and
    the retention law it stands under."""
    id: int            # ci_logs row id
    repo_id: int
    full_name: str
    run_id: str
    job_id: str
    workflow: str
    text: str
    line_count: int
    retention_days: int
    expires_at: int | None
    created_at: int
    updated_at: int

    @property
    def words(self) -> str:
        return (
            f"{self.run_id} / {self.job_id} -- "
            f"{self.line_count} lines, "
            f"{len(self.text)} characters.")


def log_to_dict(record: JobLog) -> dict:
    """One stored log as JSON-safe data, its
    whole text included. Data carries the raw
    values -- S-010 escaping is the page's law,
    not the wire's."""
    return {
        "id": record.id,
        "repository": record.full_name,
        "run_id": record.run_id,
        "job_id": record.job_id,
        "workflow": record.workflow,
        "text": record.text,
        "line_count": record.line_count,
        "retention_days": record.retention_days,
        "expires_at": record.expires_at,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


@dataclass(frozen=True)
class LogTail:
    """One tail window over a stored log: the
    lines shown, the log's total line count,
    the 1-based number of the first line shown,
    and whether earlier lines stand above the
    window -- a polling UI's whole needs."""
    full_name: str
    run_id: str
    job_id: str
    workflow: str
    lines: tuple
    total_lines: int
    first_line: int
    truncated: bool
    updated_at: int

    @property
    def words(self) -> str:
        if self.truncated:
            return (
                f"Showing the last {len(self.lines)} "
                f"of {self.total_lines} lines of "
                f"{self.run_id} / {self.job_id}.")
        return (
            f"Showing all {self.total_lines} lines "
            f"of {self.run_id} / {self.job_id}.")


def tail_to_dict(tail: LogTail) -> dict:
    """One tail window as JSON-safe data."""
    return {
        "repository": tail.full_name,
        "run_id": tail.run_id,
        "job_id": tail.job_id,
        "workflow": tail.workflow,
        "lines": list(tail.lines),
        "total_lines": tail.total_lines,
        "first_line": tail.first_line,
        "truncated": tail.truncated,
        "updated_at": tail.updated_at,
    }


@dataclass(frozen=True)
class LogDownload:
    """One opened log download: the whole
    stored text as plain text, the bare
    filename to serve it under, and its size
    in characters."""
    filename: str
    content_type: str
    text: str

    @property
    def size(self) -> int:
        return len(self.text)


@dataclass(frozen=True)
class LogSweep:
    """One expiry sweep's honest account: the
    clock it judged at, how many logs stood
    expired, and how many rows it removed."""
    now: int
    expired: int
    rows_removed: int

    @property
    def words(self) -> str:
        return sweep_words(self)


def sweep_words(run: LogSweep) -> str:
    """One sweep in plain words, for the job's
    command line and any operator log."""
    return (
        f"log expiry sweep at {run.now}: "
        f"{run.expired} expired, "
        f"{run.rows_removed} rows removed")


class LogStreamingStore:
    """The S-322 store: a job's streamed output,
    landed as one stored log per (repository,
    run, job) -- appended redacted, read through
    the repository's own permission seam, tailed
    by window, downloaded whole, and held under
    S-266's retention choices until S-267's
    pattern sweeps it. It owns no retention or
    redaction law of its own: the choices and
    the expiry judgement are S-266's, the sweep
    shape is S-267's, the filter is S-018's, and
    the read gate is S-054's."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._now = time_fn

    # -- internals --------------------------------

    def _repo_for_sink(self, owner: object, repo: object):
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise LogStreamingError(
                "repository_not_found",
                "repository_not_found -- no such "
                "repository; nothing was recorded.")
        return current

    def _repo_for_read(self, viewer, owner: object,
                       repo: object):
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            # One answer for missing and unreadable
            # alike (S-054: a private repository's
            # existence is itself private).
            raise LogStreamingError(
                "repository_not_found",
                "repository_not_found -- no such "
                "repository.")
        return current

    def _row(self, repo_id: int, run_id: str, job_id: str):
        return self._conn.execute(
            "SELECT * FROM ci_logs WHERE repo_id = ?"
            " AND run_id = ? AND job_id = ?",
            (repo_id, run_id, job_id)).fetchone()

    def _live_row(self, repo_id: int, run_id: str,
                  job_id: str, now: int):
        """The standing row for one log, or None
        when none stands -- an expired row is
        already gone to every reader, exactly as
        a log that never stood."""
        row = self._row(repo_id, run_id, job_id)
        if row is None:
            return None
        if is_expired(row["expires_at"], now):
            return None
        return row

    def _to_log(self, row, full_name: str) -> JobLog:
        return JobLog(
            id=row["id"], repo_id=row["repo_id"],
            full_name=full_name, run_id=row["run_id"],
            job_id=row["job_id"],
            workflow=row["workflow"],
            text=row["log_text"],
            line_count=row["line_count"],
            retention_days=row["retention_days"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"])

    # -- the sink -----------------------------------

    def append_log(self, owner: object, repo: object,
                   run_id: object, job_id: object,
                   text: object, *,
                   workflow: object = "",
                   retention_days: object = None,
                   extra_secrets: tuple = ()) -> JobLog:
        """Append one piece of a job's output to
        its stored log, creating the log on its
        first append. The piece is redacted
        through S-018 before it lands and
        concatenates verbatim onto the standing
        text. The whole call validates before
        anything is stored: identity, workflow,
        retention and text are judged first, and
        the size bound is judged against the
        combined text, so a refused append
        stores nothing and a standing log stands
        untouched. Retention and workflow are
        chosen at creation and stand for the
        log's life; naming a different one later
        is refused. An append after the standing
        log's expiry starts a fresh log."""
        run_id, job_id = validate_log_identity(run_id, job_id)
        if not isinstance(workflow, str):
            raise LogStreamingError(
                "log_workflow_invalid",
                "log_workflow_invalid -- a log's "
                "workflow name is text. Nothing was "
                "recorded.")
        workflow = workflow.strip()
        retention = validate_retention_days(retention_days)
        retention_named = retention_days is not None
        if not isinstance(text, str) or not text:
            raise LogStreamingError(
                "log_text_invalid",
                "log_text_invalid -- an append "
                "carries the piece's log text; an "
                "empty append says nothing and is "
                "not stored. Nothing was recorded.")
        if "\x00" in text:
            raise LogStreamingError(
                "log_text_invalid",
                "log_text_invalid -- log text "
                "carries no NUL characters. Nothing "
                "was recorded.")
        current = self._repo_for_sink(owner, repo)
        now = int(self._now())
        piece = redact_text(
            text,
            extra_secrets=tuple(
                s for s in extra_secrets
                if isinstance(s, str)))
        with self._conn:
            row = self._row(current.id, run_id, job_id)
            if row is not None and is_expired(
                    row["expires_at"], now):
                # The retention window has closed:
                # the expired log is gone, and this
                # append starts a fresh one.
                self._conn.execute(
                    "DELETE FROM ci_logs WHERE id = ?",
                    (row["id"],))
                row = None
            if row is None:
                if len(piece) > MAX_LOG_CHARS:
                    raise LogStreamingError(
                        "log_too_large",
                        f"log_too_large -- a stored "
                        f"log holds at most "
                        f"{MAX_LOG_CHARS} characters. "
                        "Nothing was recorded.")
                expires_at = decide_expiry(retention, now)
                cur = self._conn.execute(
                    "INSERT INTO ci_logs"
                    " (repo_id, run_id, job_id, workflow,"
                    " log_text, line_count, retention_days,"
                    " expires_at, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (current.id, run_id, job_id, workflow,
                     piece, count_lines(piece), retention,
                     expires_at, now, now))
                row_id = int(cur.lastrowid)
            else:
                if retention_named \
                        and retention != row["retention_days"]:
                    raise LogStreamingError(
                        "log_retention_mismatch",
                        "log_retention_mismatch -- "
                        "this log stands under "
                        f"{row['retention_days']} days; "
                        "retention is chosen at a "
                        "log's first append and stands "
                        "for its life. Nothing was "
                        "recorded.")
                if workflow and row["workflow"] \
                        and workflow != row["workflow"]:
                    raise LogStreamingError(
                        "log_workflow_mismatch",
                        "log_workflow_mismatch -- "
                        "this log stands under "
                        f"workflow {row['workflow']!r}, "
                        f"not {workflow!r}. Nothing "
                        "was recorded.")
                combined = row["log_text"] + piece
                if len(combined) > MAX_LOG_CHARS:
                    raise LogStreamingError(
                        "log_too_large",
                        f"log_too_large -- a stored "
                        f"log holds at most "
                        f"{MAX_LOG_CHARS} characters; "
                        "this append would cross the "
                        "bound. Nothing was recorded.")
                standing_workflow = row["workflow"] or workflow
                self._conn.execute(
                    "UPDATE ci_logs SET log_text = ?,"
                    " line_count = ?, workflow = ?,"
                    " updated_at = ? WHERE id = ?",
                    (combined, count_lines(combined),
                     standing_workflow, now, row["id"]))
                row_id = int(row["id"])
        fresh = self._conn.execute(
            "SELECT * FROM ci_logs WHERE id = ?",
            (row_id,)).fetchone()
        return self._to_log(fresh, current.full_name)

    def append_chunk(self, owner: object, repo: object,
                     chunk: LogChunk, *,
                     workflow: object = "",
                     retention_days: object = None,
                     extra_secrets: tuple = ()) -> JobLog:
        """The S-316 road: one judged `LogChunk`
        lands on its job's stored log. The chunk
        already carries S-316's law (its parser
        judged it on the wire); anything that is
        not a `LogChunk` is refused whole."""
        if not isinstance(chunk, LogChunk):
            raise LogStreamingError(
                "log_chunk_invalid",
                "log_chunk_invalid -- an append on "
                "this road takes S-316's LogChunk. "
                "Nothing was recorded.")
        return self.append_log(
            owner, repo, chunk.run_id, chunk.job_id,
            chunk.text, workflow=workflow,
            retention_days=retention_days,
            extra_secrets=extra_secrets)

    def append_payload(self, owner: object, repo: object,
                       payload: object, *,
                       expected_sequence: int | None = None,
                       workflow: object = "",
                       retention_days: object = None,
                       extra_secrets: tuple = ()) -> JobLog:
        """The wire road: a runner's raw
        `log_chunk` message, judged whole by
        S-316's `parse_log_chunk` (against the
        caller's expected sequence when one is
        known, so a chunk arriving out of turn is
        refused `runner_log_sequence` before
        anything lands) and appended. S-316's
        refusals ride this face's error verbatim."""
        try:
            chunk = parse_log_chunk(
                payload, expected_sequence=expected_sequence)
        except RunnerProtocolError as exc:
            raise LogStreamingError(
                exc.reason, str(exc)) from None
        return self.append_chunk(
            owner, repo, chunk, workflow=workflow,
            retention_days=retention_days,
            extra_secrets=extra_secrets)

    # -- reads --------------------------------------

    def get_log(self, viewer: User | None, owner: object,
                repo: object, run_id: object,
                job_id: object) -> JobLog:
        """One job's whole stored log. The
        repository resolves through S-054 first;
        a log that never stood, and one whose
        retention window has closed, answer the
        one `log_not_found`."""
        run_id, job_id = validate_log_identity(run_id, job_id)
        current = self._repo_for_read(viewer, owner, repo)
        row = self._live_row(
            current.id, run_id, job_id, int(self._now()))
        if row is None:
            raise LogStreamingError(
                "log_not_found",
                "log_not_found -- no stored log "
                "stands for that run and job.")
        return self._to_log(row, current.full_name)

    def tail_log(self, viewer: User | None, owner: object,
                 repo: object, run_id: object,
                 job_id: object,
                 lines: object = None) -> LogTail:
        """The live tail: the last *lines* lines
        of one job's stored log, with the totals
        a polling UI states in words. The window
        validates before the log is read, so an
        unlawful window is refused even over a
        log that does not stand."""
        count = validate_tail_lines(lines)
        record = self.get_log(viewer, owner, repo,
                              run_id, job_id)
        window = tail_lines(record.text, count)
        total = record.line_count
        return LogTail(
            full_name=record.full_name,
            run_id=record.run_id, job_id=record.job_id,
            workflow=record.workflow, lines=window,
            total_lines=total,
            first_line=total - len(window) + 1,
            truncated=len(window) < total,
            updated_at=record.updated_at)

    def list_logs(self, viewer: User | None, owner: object,
                  repo: object,
                  run_id: object = None) -> list:
        """Every standing log in one repository,
        in landing order, optionally narrowed to
        one run. Expired logs are already gone
        from this list, as from every read."""
        current = self._repo_for_read(viewer, owner, repo)
        now = int(self._now())
        if run_id is None:
            rows = self._conn.execute(
                "SELECT * FROM ci_logs WHERE repo_id = ?"
                " ORDER BY id", (current.id,)).fetchall()
        else:
            run_id, _ = validate_log_identity(run_id, "job")
            rows = self._conn.execute(
                "SELECT * FROM ci_logs WHERE repo_id = ?"
                " AND run_id = ? ORDER BY id",
                (current.id, run_id)).fetchall()
        return [self._to_log(r, current.full_name)
                for r in rows
                if not is_expired(r["expires_at"], now)]

    def download_log(self, viewer: User | None,
                     owner: object, repo: object,
                     run_id: object,
                     job_id: object) -> LogDownload:
        """One job's log as a text download: the
        whole stored text, `text/plain`, under
        the bare `<run_id>-<job_id>.log` filename.
        Judged exactly as `get_log` judges, so an
        expired or missing log downloads nothing."""
        record = self.get_log(viewer, owner, repo,
                              run_id, job_id)
        return LogDownload(
            filename=download_filename_for(
                record.run_id, record.job_id),
            content_type="text/plain",
            text=record.text)

    # -- the sweep ----------------------------------

    def sweep_expired(self, now: int | None = None) -> LogSweep:
        """Enforce retention on this store's
        instance: S-267's off-path sweep, run
        through `LogExpiryJob`. Reads already
        hide expired logs; the sweep removes
        their rows, so storage and reads agree."""
        return LogExpiryJob(
            self._conn, time_fn=self._now).sweep(now)


class LogExpiryJob:
    """The S-322 off-path job, in S-267's shape:
    enforce the retention windows the logs
    stored, deleting expired rows so a swept
    log is gone from storage and from reads
    together. Nothing here is wired into the
    web server and no request ever sweeps: an
    operator or a scheduler runs it (e.g.
    `python3 -m samverk.ci_logs <db-path>`).
    The stamp is the whole law -- S-266's own
    `is_expired` judges, this job invents no
    second judgement. Idempotent and
    unwitnessed, exactly as S-267's sweep."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._now = time_fn

    def expired_rows(self, now: int | None = None) -> list:
        """Every standing row S-266's own
        `is_expired` judges expired at *now*, in
        landing order. Pure read."""
        now = int(self._now()) if now is None else now
        rows = self._conn.execute(
            "SELECT * FROM ci_logs"
            " WHERE expires_at IS NOT NULL"
            " ORDER BY id").fetchall()
        return [r for r in rows
                if is_expired(r["expires_at"], now)]

    def sweep(self, now: int | None = None) -> LogSweep:
        """Remove every expired log's row."""
        now = int(self._now()) if now is None else now
        expired = self.expired_rows(now)
        with self._conn:
            for row in expired:
                self._conn.execute(
                    "DELETE FROM ci_logs WHERE id = ?",
                    (row["id"],))
        return LogSweep(
            now=now, expired=len(expired),
            rows_removed=len(expired))


# ------------------------------------------------------------------
# The audit: the store checked against the live instance.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class LogStreamingAudit:
    """The log store checked against one live
    instance: the retention vocabulary is
    S-266's word for word, the schema is
    exactly 132 (this slice's migration), the
    taxonomy is at the standing 138, the lawful
    table stands, and every standing row obeys
    the store's law -- a lawful retention
    choice, the expiry stamp `decide_expiry`
    computes for it, the line count its text
    counts to, lawful run and job names, and
    the size bound."""
    retention_ok: bool
    schema_version: int
    schema_ok: bool
    events_ok: bool
    tables_ok: bool
    rows_scanned: int
    problems: tuple

    @property
    def stands_cleanly(self) -> bool:
        return (
            self.retention_ok and self.schema_ok
            and self.events_ok and self.tables_ok
            and not self.problems)


def audit_log_streaming(conn: sqlite3.Connection
                        ) -> LogStreamingAudit:
    """Check the store against the live
    instance: the vocabulary, schema and
    taxonomy pins hold, the `ci_logs` table
    stands, and every standing row obeys the
    store's law. Pure read."""
    from .db import schema_version as _schema_version
    version = _schema_version(conn)
    events_ok = (len(taxonomy.AUDIT_EVENTS) == 138
                 and len(taxonomy.AUTH_EVENTS) == 33
                 and len(taxonomy.REPO_EVENTS) == 92
                 and len(taxonomy.ADMIN_EVENTS) == 13)
    retention_ok = (
        tuple(RETENTION_CHOICES) == (0, 7, 30, 90, 180, 365)
        and DEFAULT_RETENTION_DAYS == 90
        and decide_expiry(0, 100) is None
        and decide_expiry(90, 100) == 100 + 90 * 86400
        and is_expired(None, 2 ** 40) is False
        and is_expired(100, 100) is True
        and is_expired(100, 99) is False)
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    tables_ok = _SURFACE_WORD in tables
    problems: list = []
    rows = conn.execute(
        "SELECT * FROM ci_logs ORDER BY id").fetchall() \
        if tables_ok else []
    for row in rows:
        label = f"log {row['id']}"
        if row["retention_days"] not in RETENTION_CHOICES:
            problems.append(
                f"{label}: retention is not one of "
                "the standing choices")
            continue
        expected = decide_expiry(
            row["retention_days"], row["created_at"])
        if row["expires_at"] != expected:
            problems.append(
                f"{label}: expiry stamp is not the "
                "stamp its retention computes")
        if row["line_count"] != count_lines(row["log_text"]):
            problems.append(
                f"{label}: line count does not match "
                "its text")
        if len(row["log_text"]) > MAX_LOG_CHARS:
            problems.append(
                f"{label}: text crosses the size bound")
        try:
            validate_log_identity(row["run_id"], row["job_id"])
        except LogStreamingError:
            problems.append(
                f"{label}: run or job name breaks "
                "the name law")
    return LogStreamingAudit(
        retention_ok=retention_ok,
        schema_version=version, schema_ok=version == 138,
        events_ok=events_ok, tables_ok=tables_ok,
        rows_scanned=len(rows), problems=tuple(problems))


def render_log_page(tail: LogTail | None = None,
                    audit: LogStreamingAudit | None = None
                    ) -> str:
    """One job's log view, in plain words: what
    a stored log is, how its tail window and
    retention work, and -- when a tail rides
    along -- the window itself, its lines
    rendered as visible text in a <pre> block.
    Every value escaped through S-010; standing
    is said in words, never a colour alone."""
    parts = [
        "<h1>Job log</h1>",
        "<p>Every workflow job's output is stored "
        "as one log, redacted before it lands, and "
        "kept under the retention chosen when the "
        "log began (7, 30, 90, 180 or 365 days, or "
        "kept forever). While a job runs, this "
        "page's tail shows its latest lines; when "
        "the retention window closes the log is "
        "removed whole, and this page answers "
        "exactly as for a job that never ran. The "
        "whole log can be downloaded as plain "
        "text.</p>",
    ]
    if tail is not None:
        parts.append(
            f"<p>{escape_html_text(tail.words)}</p>")
        body = "\n".join(
            escape_html_text(line) for line in tail.lines)
        parts.append(f"<pre>{body}</pre>")
    if audit is not None:
        verdict = ("stands cleanly"
                   if audit.stands_cleanly
                   else "does not stand cleanly")
        parts.append(
            f"<p>Checked against this instance: "
            f"the log store {escape_html_text(verdict)} "
            f"(schema {audit.schema_version}, "
            f"{audit.rows_scanned} logs "
            f"scanned).</p>")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    """The expiry job's command line, run by an
    operator or a scheduler -- the
    off-request-path entry, in S-267's shape:
    ``python3 -m samverk.ci_logs <db-path>``
    sweeps every log expired at the wall clock
    and prints the run's honest account."""
    from . import db
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python3 -m samverk.ci_logs "
              "<db-path>")
        return 2
    conn = db.init_db(Path(args[0]))
    run = LogExpiryJob(conn).sweep()
    print(run.words)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
