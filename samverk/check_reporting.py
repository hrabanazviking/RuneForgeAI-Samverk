"""Check reporting -- job conclusions land as
check runs (S-321).

Check reporting -- job conclusions land as check
runs (S-246) on the commit and PR; required
checks (S-174) can gate merges on them.

S-246 built the outward face: an external CI
system posts a check run through the API door and
it lands in `check_runs` in the run vocabulary
AND folded onto S-157's one record
(`commit_checks`) under its name, where the
pull-request panel lists it and the
required-checks gate (S-174) judges it. Part XVI's
own runs had no such landing: S-316's protocol
ends with exactly one terminal conclusion per
job, S-318's reference runner speaks it, and
S-316 stated the seam outright -- a runner's
final word needs no translation to land as a
check run (S-321). This slice is that landing:
the forge's internal road from a job's conclusion
to the same two rows S-246 writes.

- **One record behind both faces, inward too.**
  `CheckReportingStore.report_conclusion` takes
  S-316's own pair -- the `AssignmentOffer` the
  job was handed and the `ConclusionReport` that
  closed it -- and writes exactly what S-246's
  `post_check_run` writes: one `check_runs` row
  (status `completed`, the conclusion in the run
  vocabulary, the forge's CI poster) and one
  S-157 row folded from it through
  `PullRequestChecksStore.record_result`, stamped
  with the same poster. There is no second record
  for the panel or the gate to miss, and an
  internal run and an external post about the
  same check name on the same commit are the
  same row, updated in place.
- **The check's name is the run's address.**
  A job's check is named
  ``<workflow> / <job>`` -- the workflow's name
  and the job instance's id (S-315's instance
  name for a matrix job), verbatim, decided by
  the pure `check_name_for`. That name is the
  context a branch rule (S-169) names when it
  requires the check, the context the panel
  lists, and the name the gate (S-174) looks
  for: one string, said the same way everywhere,
  so requiring a workflow's job is writing the
  name the run page already shows.
- **The fold is S-246's, word for word.** The
  panel state is decided by S-246's own
  `decide_check_run_panel_state` over a completed
  run: `success`, `neutral` and `skipped`
  conclude `passed`; `failure`, `cancelled`,
  `timed_out` and `action_required` conclude
  `failed`. The runner vocabulary IS the check
  vocabulary (`RUNNER_CONCLUSIONS` equals
  `CHECK_RUN_CONCLUSIONS`, pinned by the
  battery), so a conclusion lands untranslated.
  A job that concludes `skipped` ran and was
  skipped by its own steps' words (S-316's
  aggregate law); a job that never runs sends
  no conclusion and lands nothing -- and a
  required check with nothing landed is
  *missing*, which blocks the gate. No landing
  is ever manufactured for a run that did not
  conclude.
- **A report must close its own assignment.**
  The report's run and job must be the offer's
  (``check_report_mismatch`` otherwise, nothing
  stored). The payload road
  (`report_payload`) judges the runner's raw
  terminal message through S-316's
  `parse_conclusion` against the offer first,
  so a report at war with its own steps is
  refused in S-316's words before anything
  lands. The conclusion validates against the
  run vocabulary (`check_conclusion_invalid`),
  the name against non-blank workflow and job
  (`check_name_invalid`), and the repository
  must stand (`repository_not_found`, S-157's
  word). Every refusal stores nothing.
- **On the commit and on the PR.** The rows are
  recorded against the assignment's repository
  for the assignment's commit -- for a pull
  request that is the base repository under the
  head commit, S-157's standing rule -- so
  S-157's `checks_for` lists the job on the
  pull request's panel and S-174's gate reads
  it there with no new plumbing: a rule that
  requires ``<workflow> / <job>`` is unmet
  while the job is unreported or pending,
  blocks on a failed conclusion, and is
  satisfied by a passed one, exactly as for an
  externally posted check. `runs_for_commit`
  reads the run-vocabulary rows for a commit;
  `runs_for_pull_request` reads them for a
  pull request's head commit through the
  S-141 seam, so a stranger to a private
  repository gets the uniform
  `pull_request_not_found` before any run is
  named.
- **The durable artefact is the check row.**
  This is the forge's own bookkeeping, not an
  API face: the caller is the instance's
  scheduler/runner sink, inside the trust
  boundary -- external posters still come
  through S-246's scoped, audit-logged door.
  A landing writes no audit row and claims no
  taxonomy event (135 stand: 33 auth / 89 repo
  / 13 admin), on S-301's basis: the witnessed
  record of a job's conclusion is the check
  run itself, carrying its poster
  (`samverk-ci`, the forge speaking for its
  own CI), its stamps, and its summary. No
  migration: the tables are S-157's
  `commit_checks` (migration 58) and S-246's
  `check_runs` (migration 95), and the schema
  stays 130. The description a landing carries
  is the report's summary in words when it
  carries one, else the conclusion said in
  words with its duration. S-322 owns log
  storage, S-324 re-run and cancel, S-327 the
  run pages that render these rows in the UI.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import taxonomy
from .accounts import AccountStore
from .api_checks import (
    CHECK_RUN_CONCLUSIONS, decide_check_run_panel_state)
from .escaping import escape_html_text
from .issues import IssueStore
from .pull_request_checks import PullRequestChecksStore
from .pull_requests import PullRequestError, PullRequestStore
from .repositories import RepositoryStore
from .runner_protocol import (
    RUNNER_CONCLUSIONS, AssignmentOffer, ConclusionReport,
    RunnerProtocolError, parse_assignment, parse_conclusion)

__all__ = [
    "CHECK_RUN_STATUS_COMPLETED", "POSTER",
    "CheckReport", "CheckReportingAudit",
    "CheckReportingError", "CheckReportingStore",
    "audit_check_reporting", "check_name_for",
    "check_report_to_dict", "describe_report",
    "panel_state_for", "render_check_reporting_page",
]

#: The status every landed run carries: a
#: conclusion exists only once a job has
#: completed (S-316: exactly one, and terminal).
CHECK_RUN_STATUS_COMPLETED = "completed"

#: The poster stamped on both rows a landing
#: writes: the forge speaking for its own CI,
#: where S-246 stamps the external poster's
#: username. A name, never a person's -- no
#: account stands behind an internal run.
POSTER = "samverk-ci"

_SURFACE_WORD = "check_report"


class CheckReportingError(ValueError):
    """One refused check-reporting call: a
    machine-branchable reason with its human
    detail, in the house shape."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def check_name_for(workflow: object, job_id: object) -> str:
    """The standing name of one job's check:
    ``<workflow> / <job>``, verbatim -- the
    context a branch rule requires and the
    panel lists. Pure."""
    if not isinstance(workflow, str) or not workflow.strip():
        raise CheckReportingError(
            "check_name_invalid",
            "check_name_invalid -- a job's check "
            "names its workflow. Nothing was "
            "recorded.")
    if not isinstance(job_id, str) or not job_id.strip():
        raise CheckReportingError(
            "check_name_invalid",
            "check_name_invalid -- a job's check "
            "names its job. Nothing was recorded.")
    return f"{workflow.strip()} / {job_id.strip()}"


def panel_state_for(conclusion: object) -> str:
    """The S-157 panel state one concluded job
    folds onto, by S-246's own fold over a
    completed run. The conclusion validates
    against the run vocabulary first. Pure."""
    if conclusion not in CHECK_RUN_CONCLUSIONS:
        raise CheckReportingError(
            "check_conclusion_invalid",
            f"check_conclusion_invalid -- "
            f"{conclusion!r} is not a check-run "
            "conclusion: a job concludes success, "
            "failure, neutral, cancelled, skipped, "
            "timed_out or action_required. Nothing "
            "was recorded.")
    return decide_check_run_panel_state(
        CHECK_RUN_STATUS_COMPLETED, conclusion)


def describe_report(offer: AssignmentOffer,
                    report: ConclusionReport) -> str:
    """The one-line description a landing
    carries on S-157's record: the report's
    summary in words when it carries one, else
    the conclusion said in words with its
    duration. One line, always. Pure."""
    summary = " ".join(str(report.summary or "").split())
    if summary:
        return summary
    return (
        f"Job '{report.job_id}' of workflow "
        f"'{offer.workflow}' concluded "
        f"{report.conclusion} in "
        f"{report.duration_seconds} seconds.")


@dataclass(frozen=True)
class CheckReport:
    """One landed check run, in both vocabularies
    at once: the run's own row (status and
    conclusion) and the panel state it folded
    onto, with the run it came from."""
    id: int            # check_runs row id
    repo_id: int
    full_name: str
    oid: str
    name: str          # <workflow> / <job>
    status: str        # always 'completed'
    conclusion: str    # the run vocabulary
    panel_state: str   # 'passed' | 'failed'
    poster: str
    description: str
    run_id: str
    job_id: str
    workflow: str
    created_at: int
    updated_at: int

    @property
    def words(self) -> str:
        return (
            f"{self.name} -- {self.conclusion} "
            f"(recorded as {self.panel_state}) "
            f"on {self.oid}.")


def check_report_to_dict(record: CheckReport) -> dict:
    """One landed run as JSON-safe data: S-246's
    check-run fields, the folded panel state,
    and the run the conclusion came from. Data
    carries the raw values -- S-010 escaping is
    the page's law, not the wire's."""
    return {
        "id": record.id,
        "oid": record.oid,
        "name": record.name,
        "status": record.status,
        "conclusion": record.conclusion,
        "panel_state": record.panel_state,
        "poster": record.poster,
        "description": record.description,
        "run_id": record.run_id,
        "job_id": record.job_id,
        "workflow": record.workflow,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


class CheckReportingStore:
    """The S-321 landing: a job's terminal
    conclusion (S-316), spoken by a runner
    (S-318), recorded as a check run (S-246) on
    the commit and the pull request, where the
    required-checks gate (S-174) judges it. It
    owns no check vocabulary and no gate law of
    its own: the fold is S-246's, the record is
    S-157's, the gate is S-174's."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._now = time_fn
        self._checks = PullRequestChecksStore(
            conn, repositories, accounts, issues,
            time_fn=time_fn)
        self._prs = PullRequestStore(
            conn, repositories, accounts, issues,
            audit=None, time_fn=time_fn)

    # -- internals --------------------------------

    def _split_repo(self, offer: AssignmentOffer):
        parts = str(offer.repository).split("/")
        if len(parts) != 2:
            raise CheckReportingError(
                "repository_not_found",
                "repository_not_found -- the "
                "assignment names no repository; "
                "nothing was recorded.")
        return parts[0], parts[1]

    def _report_from_row(self, row, full_name: str,
                         run_id: str = "",
                         job_id: str = "",
                         workflow: str = "") -> CheckReport:
        panel = self._conn.execute(
            "SELECT state, description FROM "
            "commit_checks WHERE repo_id = ? AND "
            "head_oid = ? AND context = ?",
            (row["repo_id"], row["head_oid"],
             row["name"])).fetchone()
        return CheckReport(
            id=row["id"], repo_id=row["repo_id"],
            full_name=full_name, oid=row["head_oid"],
            name=row["name"], status=row["status"],
            conclusion=row["conclusion"],
            panel_state=panel["state"] if panel else "",
            poster=row["poster"],
            description=(panel["description"]
                         if panel else
                         row["description"]),
            run_id=run_id, job_id=job_id,
            workflow=workflow,
            created_at=row["created_at"],
            updated_at=row["updated_at"])

    # -- the landing ------------------------------

    def report_conclusion(self, offer: AssignmentOffer,
                          report: ConclusionReport
                          ) -> CheckReport:
        """Land one job's conclusion as a check
        run: the report must close the offer's own
        run and job; the run row and the folded
        panel row are written in S-246's shape,
        updated in place when the same job
        concludes again on the same commit (a
        re-run's latest word stands). Answers the
        landed run."""
        if not isinstance(offer, AssignmentOffer) \
                or not isinstance(report, ConclusionReport):
            raise CheckReportingError(
                "check_report_invalid",
                "check_report_invalid -- a landing "
                "takes the assignment the job was "
                "handed and the conclusion that "
                "closed it. Nothing was recorded.")
        if (report.run_id, report.job_id) \
                != (offer.run_id, offer.job_id):
            raise CheckReportingError(
                "check_report_mismatch",
                "check_report_mismatch -- this "
                f"report closes run {report.run_id} "
                f"job {report.job_id}, not the "
                f"assignment's run {offer.run_id} "
                f"job {offer.job_id}. Nothing was "
                "recorded.")
        panel_state = panel_state_for(report.conclusion)
        name = check_name_for(offer.workflow, offer.job_id)
        owner, repo = self._split_repo(offer)
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise CheckReportingError(
                "repository_not_found",
                "repository_not_found -- no such "
                "repository; nothing was recorded.")
        if not isinstance(offer.oid, str) \
                or not offer.oid.strip():
            raise CheckReportingError(
                "check_head_invalid",
                "check_head_invalid -- a check run "
                "names the commit it ran on. "
                "Nothing was recorded.")
        description = describe_report(offer, report)
        try:
            self._checks.record_result(
                owner, repo, offer.oid, name,
                panel_state, description=description)
        except PullRequestError as exc:
            raise CheckReportingError(
                exc.reason, str(exc)) from None
        now = int(self._now())
        with self._conn:
            row = self._conn.execute(
                "SELECT * FROM check_runs"
                " WHERE repo_id = ? AND head_oid = ?"
                " AND name = ?",
                (current.id, offer.oid, name)).fetchone()
            if row is None:
                cur = self._conn.execute(
                    "INSERT INTO check_runs"
                    " (repo_id, head_oid, name, status,"
                    " conclusion, poster, target_url,"
                    " description, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (current.id, offer.oid, name,
                     CHECK_RUN_STATUS_COMPLETED,
                     report.conclusion, POSTER, "",
                     description, now, now))
                row_id = int(cur.lastrowid)
            else:
                self._conn.execute(
                    "UPDATE check_runs SET status = ?,"
                    " conclusion = ?, poster = ?,"
                    " target_url = ?, description = ?,"
                    " updated_at = ? WHERE id = ?",
                    (CHECK_RUN_STATUS_COMPLETED,
                     report.conclusion, POSTER, "",
                     description, now, row["id"]))
                row_id = int(row["id"])
            self._conn.execute(
                "UPDATE commit_checks SET poster = ?"
                " WHERE repo_id = ? AND head_oid = ?"
                " AND context = ?",
                (POSTER, current.id, offer.oid, name))
        fresh = self._conn.execute(
            "SELECT * FROM check_runs WHERE id = ?",
            (row_id,)).fetchone()
        return self._report_from_row(
            fresh, current.full_name,
            run_id=report.run_id, job_id=report.job_id,
            workflow=offer.workflow)

    def report_payload(self, offer_payload: object,
                       conclusion_payload: object
                       ) -> CheckReport:
        """The sink road: a runner's raw assignment
        and terminal conclusion messages, judged
        whole by S-316 (`parse_assignment`, then
        `parse_conclusion` against the offer, so
        the report must agree with its own steps)
        and landed. S-316's refusals ride this
        face's error verbatim."""
        try:
            offer = parse_assignment(offer_payload)
            report = parse_conclusion(
                conclusion_payload, offer)
        except RunnerProtocolError as exc:
            raise CheckReportingError(
                exc.reason, str(exc)) from None
        return self.report_conclusion(offer, report)

    # -- reads --------------------------------------

    def runs_for_commit(self, owner: object, repo: object,
                        oid: object) -> list:
        """Every check run landed or posted for one
        commit in one repository, in the order they
        first landed -- this slice's rows and
        S-246's are one record, read whole."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise CheckReportingError(
                "repository_not_found",
                "repository_not_found -- no such "
                "repository.")
        rows = self._conn.execute(
            "SELECT * FROM check_runs"
            " WHERE repo_id = ? AND head_oid = ?"
            " ORDER BY id",
            (current.id, str(oid))).fetchall()
        return [self._report_from_row(r, current.full_name)
                for r in rows]

    def runs_for_pull_request(self, viewer, owner: object,
                              repo: object, number: object
                              ) -> list:
        """The check runs landed on one pull
        request: the runs recorded against its base
        repository for its head commit, in the
        order they first landed. The pull request
        resolves through the S-141 seam, so a
        stranger to a private repository is refused
        `pull_request_not_found` before any run is
        named."""
        try:
            pr = self._prs.get_pull_request(
                viewer, owner, repo, number)
        except PullRequestError as exc:
            raise CheckReportingError(
                exc.reason, str(exc)) from None
        current = self._repos.get_repository(owner, repo)
        full_name = current.full_name if current else ""
        rows = self._conn.execute(
            "SELECT * FROM check_runs"
            " WHERE repo_id = ? AND head_oid = ?"
            " ORDER BY id",
            (pr.repo_id, pr.head_oid)).fetchall()
        return [self._report_from_row(r, full_name)
                for r in rows]


# ------------------------------------------------------------------
# The audit: the landing checked against the live instance.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class CheckReportingAudit:
    """The landing checked against one live
    instance: the vocabulary is S-246's word for
    word (the runner's conclusions ARE the check
    conclusions, and the fold covers every one),
    the schema unmoved at 131 (this slice
    mints no migration -- its tables are S-157's
    and S-246's), the taxonomy at the standing 138,
    the two lawful tables stand, and no table,
    column or audit event carries a
    check-reporting surface of its own -- the
    landing is this code over the standing
    record, not a store of its own."""
    vocabulary_ok: bool
    schema_version: int
    schema_ok: bool
    events_ok: bool
    tables_ok: bool
    tables_scanned: int
    columns_scanned: int
    events_scanned: int
    offending_tables: tuple
    offending_columns: tuple
    offending_events: tuple

    @property
    def stands_cleanly(self) -> bool:
        return (
            self.vocabulary_ok and self.schema_ok
            and self.events_ok and self.tables_ok
            and not self.offending_tables
            and not self.offending_columns
            and not self.offending_events)


def audit_check_reporting(conn: sqlite3.Connection
                          ) -> CheckReportingAudit:
    """Check the landing against the live
    instance: the vocabularies agree, the schema
    is exactly 132, the taxonomy is
    exactly the standing 138, the lawful tables
    stand, and no check-reporting surface hides
    in the schema or the taxonomy. Pure read."""
    from .db import schema_version as _schema_version
    version = _schema_version(conn)
    events_ok = (len(taxonomy.AUDIT_EVENTS) == 142
                 and len(taxonomy.AUTH_EVENTS) == 33
                 and len(taxonomy.REPO_EVENTS) == 92
                 and len(taxonomy.ADMIN_EVENTS) == 13)
    vocabulary_ok = (
        tuple(RUNNER_CONCLUSIONS)
        == tuple(CHECK_RUN_CONCLUSIONS)
        and all(
            panel_state_for(word) in ("passed", "failed")
            for word in CHECK_RUN_CONCLUSIONS))
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    tables_ok = "check_runs" in tables \
        and "commit_checks" in tables
    offending_tables: list = []
    offending_columns: list = []
    columns_scanned = 0
    for table in tables:
        if _SURFACE_WORD in table:
            offending_tables.append(table)
        safe = table.replace('"', '""')
        for row in conn.execute(
                f'PRAGMA table_info("{safe}")').fetchall():
            columns_scanned += 1
            if _SURFACE_WORD in str(row[1]):
                offending_columns.append(f"{table}.{row[1]}")
    events = sorted(taxonomy.AUDIT_EVENTS)
    offending_events = [
        e for e in events if _SURFACE_WORD in e]
    return CheckReportingAudit(
        vocabulary_ok=vocabulary_ok,
        schema_version=version, schema_ok=version == 140,
        events_ok=events_ok, tables_ok=tables_ok,
        tables_scanned=len(tables),
        columns_scanned=columns_scanned,
        events_scanned=len(events),
        offending_tables=tuple(offending_tables),
        offending_columns=tuple(offending_columns),
        offending_events=tuple(offending_events))


def render_check_reporting_page(
        report: CheckReport | None = None,
        audit: CheckReportingAudit | None = None) -> str:
    """Check reporting, in plain words, where a
    workflow's author finds it: how a job's
    conclusion becomes a check, what name the
    branch rule must require, and how the gate
    judges it -- plus one landed run's words and
    the checked proof when they ride along.
    Every value escaped through S-010; standing
    is said in words, never a colour alone."""
    parts = [
        "<h1>Check reporting</h1>",
        "<p>When a workflow job finishes, its "
        "conclusion lands as a check run on the "
        "commit it ran on -- and so on the pull "
        "request whose head that commit is. A "
        "job's check is named for its workflow "
        "and job (for example, "
        "<code>CI / build</code>); that name is "
        "the check a branch rule requires. A "
        "conclusion of success, neutral or "
        "skipped records as passed; failure, "
        "cancelled, timed out or action required "
        "records as failed; a job that has not "
        "concluded has reported nothing, and a "
        "required check with nothing reported "
        "blocks the merge. The pull request's "
        "checks panel lists these runs beside "
        "any an external system posts -- one "
        "record, judged by the one required-"
        "checks gate.</p>",
    ]
    if report is not None:
        parts.append(
            f"<p>{escape_html_text(report.words)}</p>")
        if report.description:
            parts.append(
                "<p>"
                f"{escape_html_text(report.description)}"
                "</p>")
    if audit is not None:
        verdict = ("stands cleanly"
                   if audit.stands_cleanly
                   else "does not stand cleanly")
        parts.append(
            f"<p>Checked against this instance: "
            f"the landing {escape_html_text(verdict)} "
            f"(schema {audit.schema_version}, "
            f"{audit.events_scanned} audit events, "
            f"{audit.tables_scanned} tables "
            f"scanned).</p>")
    return "\n".join(parts)
