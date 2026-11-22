"""Health and status (S-359).

Roadmap S-359: a `/healthz`-style endpoint and an
admin status page (disk, DB, index lag S-215, job
backlog) with honest numbers.

Before this slice the server's health route
(S-002) answered a constant: `ok`, whether or not
the database under the instance could be read at
all. A corrupt database behind a cheerful health
route is a false ok, and an operator had no one
page that said how the instance stands. This slice
makes both faces honest:

- **/healthz probes, it does not assert.** Every
  answer is computed at request time from the real
  database file at the configured data root, opened
  read-only (a health read never creates or migrates
  anything): the file's presence, a real `SELECT 1`,
  and the schema version read through S-004's own
  `schema_version`, judged by the pure `judge_probe`
  against the current migration head. A database
  file that stands but cannot be read, or whose
  schema is not the current one, answers **down**
  with HTTP 503 -- never a false ok. A data root
  with no database file yet is the bare-checkout
  state S-002's acceptance stands on (the server
  itself is up; nothing has been initialised), and
  it is said plainly in the payload -- `db: missing`,
  `schema_version: null` -- never dressed as a
  checked database. The payload carries no sensitive
  numbers beyond up/down, the database word, and
  the schema version: no disk figures, no counts,
  no paths.
- **The admin status page gathers at request time.**
  `HealthStatus.status` is a site-admin door in
  S-215's exact shape (`no_such_user` for an unknown
  viewer, `not_site_admin` for a signed-in
  non-admin, checked before anything is read). It
  stores nothing and caches nothing: disk free/used
  for the data root's filesystem and the data tree's
  own bytes are walked fresh, the database's size,
  schema version and row counts are read fresh, the
  index section *is* S-215's `instance_health` (its
  queue lag is the index lag -- the age of the oldest
  waiting index job, with the waiting count beside
  it, so an un-indexed change shows as lag and as a
  number), and the job backlog is counted fresh from
  the real queue tables: `index_jobs` (S-205),
  `webhook_deliveries` (S-250) and `weekly_digests`
  (S-235). A changed world changes the page; the
  battery proves it by changing the world.
- **The overall word is judged purely.**
  `decide_overall_status` folds the probe, the index
  headline, the layout check (S-347) and the dead
  work into one word: `down` when the probe is down,
  `degraded` when the index stands stale or failed,
  when any queue holds dead work, or when the data
  layout is damaged -- and `ok` otherwise. Work
  merely waiting is backlog, shown as numbers; it
  is not dressed as degradation and never hidden.
- **The seam for S-351.** The admin panel slice
  (S-351) is not on this base; the status page here
  stands on the standing admin seams (the account
  store's `is_admin`, S-215's door shape) and is
  served at `GET /admin/status`, resolving the
  caller's session cookie through S-006's store.
  When the panel lands it links this route; nothing
  here depends on it.

No migration (the slice reads standing tables and
writes nothing) and no new taxonomy event (health
reads audit nothing, exactly as S-215's reads do):
the schema stands at 140 and the taxonomy at 142
(coordinator pin sweep at S-359 banking: S-355/S-358 landed
after this slice was built).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import __version__, db
from .accounts import AccountStore, User
from .data_layout import LayoutReport, check_layout
from .escaping import escape_html_text
from .index_architecture import SearchIndexStore
from .index_health import IndexHealth, InstanceIndexHealth

__all__ = [
    "BACKLOG_SOURCES", "EXPECTED_SCHEMA_VERSION",
    "BacklogReport", "BacklogSource", "DatabaseStatus",
    "DiskFacts", "HealthStatus", "HealthStatusError",
    "InstanceStatus", "ProbeFacts", "ProbeReport",
    "decide_overall_status", "gather_disk_facts",
    "healthz_payload", "judge_probe", "probe_connection",
    "probe_database", "render_status_page",
    "summarise_backlog",
]

EXPECTED_SCHEMA_VERSION = db.MIGRATIONS[-1][0]

# Overall / probe words.
OK = "ok"
DEGRADED = "degraded"
DOWN = "down"

# Database words for the health payload.
DB_UP = "up"
DB_DOWN = "down"
DB_MISSING = "missing"


class HealthStatusError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# -- the probe (the /healthz judgement) -----------------------

@dataclass(frozen=True)
class ProbeFacts:
    """What one probe saw, before judgement: the
    database file's presence, whether a real query
    answered, the schema version it reported, and
    the failure's shape when it did not answer."""
    db_file_exists: bool
    db_reachable: bool
    schema_version: int | None
    error: str = ""


@dataclass(frozen=True)
class ProbeReport:
    status: str            # OK / DOWN
    http_status: int       # 200 / 503
    db: str                # DB_UP / DB_DOWN / DB_MISSING
    schema_version: int | None
    expected_schema_version: int
    reason: str            # '' when ok; a plain word when not
    facts: ProbeFacts


def judge_probe(facts: ProbeFacts,
                expected_schema: int) -> ProbeReport:
    """Pure: probe facts in, the health verdict out.
    A standing-but-unreadable database and a schema
    that is not the current one are both `down`;
    a not-yet-created database is the bare state,
    answered ok and *named* missing."""
    if not facts.db_file_exists:
        return ProbeReport(
            status=OK, http_status=200, db=DB_MISSING,
            schema_version=None,
            expected_schema_version=expected_schema,
            reason="database_not_initialised", facts=facts)
    if not facts.db_reachable:
        return ProbeReport(
            status=DOWN, http_status=503, db=DB_DOWN,
            schema_version=None,
            expected_schema_version=expected_schema,
            reason="database_unreachable", facts=facts)
    if facts.schema_version != expected_schema:
        return ProbeReport(
            status=DOWN, http_status=503, db=DB_UP,
            schema_version=facts.schema_version,
            expected_schema_version=expected_schema,
            reason="schema_mismatch", facts=facts)
    return ProbeReport(
        status=OK, http_status=200, db=DB_UP,
        schema_version=facts.schema_version,
        expected_schema_version=expected_schema,
        reason="", facts=facts)


def probe_connection(conn: sqlite3.Connection, db_path: Path,
                     expected_schema: int =
                     EXPECTED_SCHEMA_VERSION) -> ProbeReport:
    """Judge one already-open connection: a real
    `SELECT 1` and S-004's schema read. The caller
    owns the connection; this writes nothing."""
    path = Path(db_path)
    if not path.is_file():
        return judge_probe(
            ProbeFacts(False, False, None), expected_schema)
    try:
        conn.execute("SELECT 1").fetchone()
        version: int | None = db.schema_version(conn)
    except Exception as exc:  # noqa: BLE001 -- a probe reports, never raises
        return judge_probe(
            ProbeFacts(True, False, None, type(exc).__name__),
            expected_schema)
    return judge_probe(
        ProbeFacts(True, True, version), expected_schema)


def probe_database(db_path: Path,
                   expected_schema: int =
                   EXPECTED_SCHEMA_VERSION) -> ProbeReport:
    """Probe the database file at *db_path* through
    a read-only connection opened for the probe
    alone: a health read creates nothing, migrates
    nothing, and leaves no sidecar behind."""
    path = Path(db_path)
    if not path.is_file():
        return judge_probe(
            ProbeFacts(False, False, None), expected_schema)
    try:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro", uri=True, timeout=5.0)
    except Exception as exc:  # noqa: BLE001
        return judge_probe(
            ProbeFacts(True, False, None, type(exc).__name__),
            expected_schema)
    try:
        conn.row_factory = sqlite3.Row
        return probe_connection(conn, path, expected_schema)
    finally:
        conn.close()


def healthz_payload(report: ProbeReport) -> dict:
    """The /healthz body: up/down, the database
    word, and the schema version -- nothing else.
    No disk figures, no counts, no paths ever ride
    the public health door."""
    payload: dict = {
        "status": report.status,
        "service": "samverk",
        "version": __version__,
        "db": report.db,
        "schema_version": report.schema_version,
    }
    if report.reason:
        payload["reason"] = report.reason
    return payload


# -- disk facts -------------------------------------------------

@dataclass(frozen=True)
class DiskFacts:
    """The data root's disk truth, gathered fresh:
    the filesystem's total/free/used at the root,
    the data tree's own bytes walked file by file,
    and the database's bytes (file plus sidecars)."""
    root: Path
    root_exists: bool
    total_bytes: int
    free_bytes: int
    used_bytes: int
    tree_bytes: int
    db_bytes: int

    @property
    def used_percent(self) -> int:
        if self.total_bytes <= 0:
            return 0
        return int(self.used_bytes * 100 / self.total_bytes)


def _tree_bytes(root: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            try:
                total += os.path.getsize(
                    os.path.join(dirpath, name))
            except OSError:
                continue  # a file leaving mid-walk is not the walk's lie
    return total


def gather_disk_facts(data_root: Path, db_path: Path,
                      disk_usage_fn: Callable =
                      shutil.disk_usage) -> DiskFacts:
    """Read the disk once, at call time. A missing
    root is a fact (zeros, root_exists False), never
    an exception dressed as health."""
    root = Path(data_root)
    if not root.is_dir():
        return DiskFacts(root, False, 0, 0, 0, 0, 0)
    usage = disk_usage_fn(root)
    db_total = 0
    for candidate in (Path(db_path),
                      Path(str(db_path) + "-wal"),
                      Path(str(db_path) + "-shm")):
        try:
            db_total += candidate.stat().st_size
        except OSError:
            continue
    return DiskFacts(
        root=root, root_exists=True,
        total_bytes=int(usage.total), free_bytes=int(usage.free),
        used_bytes=int(usage.used), tree_bytes=_tree_bytes(root),
        db_bytes=db_total)


# -- the job backlog ----------------------------------------------

@dataclass(frozen=True)
class BacklogSourceSpec:
    name: str
    label: str
    table: str
    backlog_statuses: tuple[str, ...]


# The real queue seams, named once: the search index
# queue (S-205), webhook deliveries (S-250), and the
# weekly digest job's standing rows (S-235). Backlog
# is the work still owed: waiting or in flight, never
# the terminal words (done / delivered / sent / dead
# are history or a verdict, counted separately).
BACKLOG_SOURCES: tuple[BacklogSourceSpec, ...] = (
    BacklogSourceSpec(
        "index", "Search index jobs", "index_jobs",
        ("pending", "running")),
    BacklogSourceSpec(
        "webhooks", "Webhook deliveries", "webhook_deliveries",
        ("queued", "retrying")),
    BacklogSourceSpec(
        "digests", "Weekly digests awaiting send", "weekly_digests",
        ("composed",)),
)


@dataclass(frozen=True)
class BacklogSource:
    name: str
    label: str
    counts: tuple[tuple[str, int], ...] = ()
    error: str = ""

    def count(self, status: str) -> int:
        return dict(self.counts).get(status, 0)


@dataclass(frozen=True)
class BacklogReport:
    sources: tuple[BacklogSource, ...]
    total_backlog: int
    total_dead: int


def summarise_backlog(sources: tuple[BacklogSource, ...],
                      specs: tuple[BacklogSourceSpec, ...] =
                      BACKLOG_SOURCES) -> BacklogReport:
    """Pure: fold per-source status counts into the
    backlog total (work still owed, by each source's
    own backlog words) and the dead total (work that
    will never run without an operator). A source
    whose read failed contributes neither -- its
    error stands on the page instead of a false 0."""
    by_name = {spec.name: spec for spec in specs}
    backlog = 0
    dead = 0
    for source in sources:
        if source.error:
            continue
        spec = by_name.get(source.name)
        if spec is not None:
            backlog += sum(source.count(s) for s in spec.backlog_statuses)
        dead += source.count("dead")
    return BacklogReport(tuple(sources), backlog, dead)


# -- the overall word ----------------------------------------------

def decide_overall_status(probe_status: str, index_worst: str,
                          layout_health: str,
                          total_dead: int) -> str:
    """Pure folding law for the status page's lead
    word. `down` is the probe's alone; `degraded`
    names an instance that serves but owes repair:
    a stale or failed index, dead work in any queue,
    or a damaged data layout. Waiting work alone is
    backlog, not degradation."""
    if probe_status == DOWN:
        return DOWN
    if index_worst in ("stale", "failed"):
        return DEGRADED
    if total_dead > 0:
        return DEGRADED
    if layout_health == "damaged":
        return DEGRADED
    return OK


# -- the status read -------------------------------------------------

@dataclass(frozen=True)
class DatabaseStatus:
    reachable: bool
    schema_version: int | None
    expected_schema_version: int
    size_bytes: int
    user_count: int | None
    repo_count: int | None


@dataclass(frozen=True)
class InstanceStatus:
    """Everything the admin status page shows, as
    gathered at one request: the probe, the disk,
    the database, S-215's index health whole, the
    job backlog, and S-347's layout verdict."""
    generated_at: int
    overall: str
    probe: ProbeReport
    disk: DiskFacts
    database: DatabaseStatus
    index: InstanceIndexHealth
    backlog: BacklogReport
    layout: LayoutReport


class HealthStatus:
    """The S-359 service: the probe behind /healthz
    and the admin status read behind /admin/status.
    Nothing is stored; every face gathers fresh."""

    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        index: SearchIndexStore, data_root: Path,
        time_fn: Callable[[], float] = time.time,
        disk_usage_fn: Callable = shutil.disk_usage,
        expected_schema: int = EXPECTED_SCHEMA_VERSION,
    ):
        self._conn = conn
        self._accounts = accounts
        self._index = index
        self._data_root = Path(data_root)
        self._now = time_fn
        self._disk_usage = disk_usage_fn
        self._expected = expected_schema

    @property
    def db_path(self) -> Path:
        from .data_layout import layout_for
        return layout_for(self._data_root).db_path

    # -- guards (S-215's door, word for word) ----------
    def _require_admin(self, viewer_id: object) -> User:
        viewer = None
        if isinstance(viewer_id, int) and not isinstance(viewer_id, bool):
            viewer = self._accounts.get_by_id(viewer_id)
        if viewer is None:
            raise HealthStatusError(
                "no_such_user", "No such account.")
        if not viewer.is_admin:
            raise HealthStatusError(
                "not_site_admin",
                "Only a site admin can see instance status.")
        return viewer

    # -- the probe face ----------------------------------
    def probe(self) -> ProbeReport:
        """The /healthz verdict for this instance's
        configured database, probed read-only."""
        return probe_database(self.db_path, self._expected)

    # -- the backlog gather --------------------------------
    def _gather_backlog(self) -> BacklogReport:
        sources: list[BacklogSource] = []
        for spec in BACKLOG_SOURCES:
            try:
                rows = self._conn.execute(
                    f"SELECT status, COUNT(*) AS c FROM {spec.table}"
                    " GROUP BY status").fetchall()
                counts = tuple(sorted(
                    (str(row["status"]), int(row["c"])) for row in rows))
                sources.append(BacklogSource(
                    spec.name, spec.label, counts))
            except Exception as exc:  # noqa: BLE001 -- named, never a false 0
                sources.append(BacklogSource(
                    spec.name, spec.label, (), type(exc).__name__))
        return summarise_backlog(tuple(sources))

    # -- the status face -----------------------------------
    def status(self, viewer_id: object) -> InstanceStatus:
        """The whole instance status, for a site
        admin, gathered at this call: probe, disk,
        database, S-215 index health, queue backlog,
        and the S-347 layout check."""
        self._require_admin(viewer_id)
        probe = self.probe()
        disk = gather_disk_facts(
            self._data_root, self.db_path, self._disk_usage)
        users: int | None = None
        repos: int | None = None
        if probe.facts.db_reachable:
            users = int(self._conn.execute(
                "SELECT COUNT(*) AS c FROM users").fetchone()["c"])
            repos = int(self._conn.execute(
                "SELECT COUNT(*) AS c FROM repositories"
            ).fetchone()["c"])
        database = DatabaseStatus(
            reachable=probe.facts.db_reachable,
            schema_version=probe.schema_version,
            expected_schema_version=self._expected,
            size_bytes=disk.db_bytes,
            user_count=users, repo_count=repos)
        index_health = IndexHealth(
            self._conn, self._accounts, self._index,
            time_fn=self._now).instance_health(viewer_id)
        backlog = self._gather_backlog()
        layout = check_layout(self._data_root)
        overall = decide_overall_status(
            probe.status, index_health.worst_status,
            layout.health, backlog.total_dead)
        return InstanceStatus(
            generated_at=int(self._now()), overall=overall,
            probe=probe, disk=disk, database=database,
            index=index_health, backlog=backlog, layout=layout)


_OVERALL_WORDS = {
    OK: "ok — the instance is up and nothing stands owed",
    DEGRADED: "degraded — the instance serves, and repair is owed",
    DOWN: "down — the database does not answer honestly",
}

_INDEX_WORDS = {
    "never": "never indexed",
    "queued": "waiting to be indexed",
    "indexing": "being indexed now",
    "current": "up to date",
    "stale": "behind — a rebuild or retry is owed",
    "failed": "indexing failed — see the recorded error",
}


def render_status_page(status: InstanceStatus) -> str:
    """The admin status page, in words: the overall
    word first, then database, disk, index (S-215's
    lag, always shown, even 0), job backlog per real
    queue, and the data layout's verdict. Every
    number is the gathered fact; dynamic text goes
    through S-010."""
    probe = status.probe
    disk = status.disk
    database = status.database
    index = status.index
    queue = index.queue
    overall_words = _OVERALL_WORDS.get(status.overall, status.overall)
    parts = [
        "<h1>Instance status</h1>",
        f"<p>Overall: {escape_html_text(overall_words)}.</p>",
        "<h2>Database</h2>",
    ]
    if database.reachable:
        parts.append(
            f"<p>Database: up; schema version "
            f"{database.schema_version} of "
            f"{database.expected_schema_version}; "
            f"{database.size_bytes} bytes on disk; "
            f"{database.user_count} accounts; "
            f"{database.repo_count} repositories.</p>")
    else:
        parts.append(
            f"<p>Database: {escape_html_text(probe.db)} "
            f"({escape_html_text(probe.reason or 'unreachable')}); "
            f"expected schema version "
            f"{database.expected_schema_version}.</p>")
    parts.append("<h2>Disk</h2>")
    if disk.root_exists:
        parts.append(
            f"<p>Data root {escape_html_text(str(disk.root))}: "
            f"{disk.free_bytes} bytes free of {disk.total_bytes} "
            f"({disk.used_bytes} used, {disk.used_percent}%); "
            f"the data tree holds {disk.tree_bytes} bytes.</p>")
    else:
        parts.append(
            f"<p>Data root {escape_html_text(str(disk.root))} "
            f"does not exist yet.</p>")
    index_words = _INDEX_WORDS.get(index.worst_status, index.worst_status)
    parts += [
        "<h2>Search index</h2>",
        f"<p>Index lag: {queue.lag_seconds} seconds — "
        f"{queue.pending} waiting, {queue.running} running, "
        f"{queue.done} done, {queue.dead} dead.</p>",
        f"<p>{len(index.repos)} repositories; "
        f"{index.current_count} up to date; "
        f"{index.behind_count} behind; "
        f"{index.document_count} documents indexed; "
        f"overall: {escape_html_text(index_words)}.</p>",
        "<h2>Job backlog</h2>",
        f"<p>{status.backlog.total_backlog} jobs waiting or "
        f"in flight across all queues; "
        f"{status.backlog.total_dead} dead.</p>",
        "<ul>",
    ]
    for source in status.backlog.sources:
        if source.error:
            parts.append(
                f"<li><strong>{escape_html_text(source.label)}</strong>"
                f" — could not be counted "
                f"({escape_html_text(source.error)})</li>")
        else:
            counts = ", ".join(
                f"{count} {escape_html_text(name)}"
                for name, count in source.counts) or "no jobs recorded"
            parts.append(
                f"<li><strong>{escape_html_text(source.label)}</strong>"
                f" — {counts}</li>")
    parts += [
        "</ul>",
        "<h2>Data layout</h2>",
        f"<p>Layout: {escape_html_text(status.layout.health)}.</p>",
    ]
    problems = status.layout.problems()
    if problems:
        parts.append("<ul>")
        for problem in problems:
            parts.append(
                f"<li>{escape_html_text(problem.name)} — "
                f"{escape_html_text(problem.health)}: "
                f"{escape_html_text(problem.note)}</li>")
        parts.append("</ul>")
    return "\n".join(parts)
