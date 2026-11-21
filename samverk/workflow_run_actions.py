"""Workflow run actions -- re-run and cancel
(S-324).

Re-run and cancel -- re-run all/failed jobs,
cancel running workflows; every action
audit-logged.

Part XVI's runs stand, by S-321's and S-323's
law, as check runs: one workflow run on one
commit is addressed by the triple every
neighbouring face already uses -- repository,
workflow, commit (`oid`) -- and its jobs are
the check runs standing on that commit whose
names S-321's `check_name_for` law built for
this workflow (``<workflow> / <job>``). Until
this slice those rows could only move forward:
a job concluded, and its word stood. This
slice is the two hands a maintainer actually
reaches for on the run page -- re-run, and
cancel -- and every reach is witnessed.

- **Re-run, all or failed only.** `rerun_all`
  re-runs every job of a completed run;
  `rerun_failed_jobs` re-runs only the failed
  ones. A job counts as failed when its
  conclusion is one of `FAILED_CONCLUSIONS`
  -- `failure`, `timed_out`, `action_required`:
  the conclusions S-246's fold records as
  failed, minus `cancelled`, because a
  cancelled job was stopped on purpose, not
  beaten; re-run all is the road that covers
  it. Re-running resets each chosen job's
  check run to `queued` with no conclusion
  and folds its S-157 panel row back to
  `pending` through S-157's own
  `record_result`, so a required check
  (S-174) the re-run touches blocks the gate
  again until the new attempt's conclusion
  lands -- through S-321, whose landing law
  already says a re-run's latest word stands
  on the same row. A run with any job still
  unfinished cannot be re-run
  (`run_still_running`: cancel it first), a
  run that never stood cannot be re-run
  (`run_not_found`), and a failed-only re-run
  with no failed job is refused
  (`rerun_no_failed_jobs`) rather than
  silently re-running nothing. Each accepted
  re-run opens the next attempt: a run's
  attempt is 1 plus the re-runs recorded for
  it in this slice's table.
- **Cancel stops what is still moving.** A
  run with any job unfinished (queued or in
  progress) can be cancelled: every unfinished
  job's check run completes as `cancelled`
  and folds to the panel's `failed`, exactly
  as S-246's fold judges a cancelled run;
  jobs that already concluded keep their
  words untouched -- cancelling a run never
  rewrites its finished history. A run that
  already completed cannot be cancelled
  (`run_not_running`), and a run that never
  stood cannot be cancelled either
  (`run_not_found`). Cancelling opens no new
  attempt; the action row records the attempt
  it stopped.
- **The durable artefact is the action row.**
  Every accepted action lands one row in
  migration 132's `ci_run_actions` (schema
  131 to 132): the run's address, the kind,
  the attempt, the job check names acted on
  in run order, who acted and when. The row
  is this slice's own record, beside the
  check rows it moved; `list_run_actions`
  reads the run's whole action history back
  in landing order, and `get_run` reads the
  run's standing -- its jobs, its attempt,
  and whether it stands running or completed
  -- in the same address.
- **Every action audit-logged.** An accepted
  re-run or cancel appends exactly one entry
  to S-007's chain under its own event --
  taxonomy append-only +3:
  `repo.workflow_run.rerun_all`,
  `repo.workflow_run.rerun_failed`,
  `repo.workflow_run.cancel` (138 stand:
  33 auth / 92 repo / 13 admin), each naming
  the workflow, the commit, the attempt and
  the jobs acted on, with S-247 webhook
  rulings for all three verbs (checks
  category, repository scope). A refused
  action stores nothing and audits nothing:
  the chain witnesses acts, not attempts.
- **Permission is S-054's, at write rung.**
  Actions are write acts on the repository:
  the actor must be a signed-in user who
  `can_write` it. Reads (`get_run`,
  `list_run_actions`) follow `can_read`.
  Every entry point resolves the repository
  through that seam first, so a missing
  repository and a private repository the
  caller cannot read answer the one uniform
  `repository_not_found`; a reader who can
  see the run but not write the repository
  is refused `permission_denied` for the
  action, by name.
- **Honest scope.** This slice records the
  re-run and re-queues the checks; it does
  not wake a runner. Dispatch is S-316's
  poll seam, owned by the scheduler that
  speaks it -- a re-run's jobs stand `queued`
  and `pending` in the record until a runner
  takes them and S-321 lands their new
  conclusions, and nothing here pretends
  otherwise. S-327 owns the routed run pages;
  the render here is this face in the house
  shape, every value escaped through S-010.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import taxonomy
from .accounts import AccountStore, User
from .api_checks import (
    CHECK_RUN_CONCLUSIONS, decide_check_run_panel_state)
from .audit import AuditLog
from .check_reporting import check_name_for
from .escaping import escape_html_text
from .issues import IssueStore
from .permissions import can_read, can_write
from .pull_request_checks import PullRequestChecksStore
from .pull_requests import PullRequestError
from .repositories import RepositoryStore

__all__ = [
    "ACTION_CANCEL", "ACTION_KINDS", "ACTION_RERUN_ALL",
    "ACTION_RERUN_FAILED", "EVENT_BY_ACTION",
    "FAILED_CONCLUSIONS", "RunAction", "RunJob",
    "RunStanding", "WorkflowRunActionsAudit",
    "WorkflowRunActionsError",
    "WorkflowRunActionsStore",
    "audit_workflow_run_actions", "is_failed_conclusion",
    "is_run_check_name", "job_for_check_name",
    "render_run_actions_page", "run_action_to_dict",
    "run_check_prefix", "run_job_to_dict",
    "run_standing_to_dict", "standing_for_statuses",
    "validate_run_address",
]

#: The three acts this slice performs, in the
#: words the action row keeps.
ACTION_RERUN_ALL = "rerun_all"
ACTION_RERUN_FAILED = "rerun_failed"
ACTION_CANCEL = "cancel"
ACTION_KINDS = (
    ACTION_RERUN_ALL, ACTION_RERUN_FAILED, ACTION_CANCEL)

#: The audit event each act is witnessed under
#: (taxonomy append-only +3, S-324).
EVENT_BY_ACTION = {
    ACTION_RERUN_ALL: "repo.workflow_run.rerun_all",
    ACTION_RERUN_FAILED: "repo.workflow_run.rerun_failed",
    ACTION_CANCEL: "repo.workflow_run.cancel",
}

#: The conclusions that count as *failed* for a
#: failed-only re-run: S-246's panel-failed set
#: minus `cancelled` -- a cancelled job was
#: stopped on purpose, not beaten, and re-run
#: all is the road that covers it.
FAILED_CONCLUSIONS = (
    "failure", "timed_out", "action_required")

_SURFACE_WORD = "workflow_run_actions"
_TABLE = "ci_run_actions"


class WorkflowRunActionsError(ValueError):
    """One refused workflow-run-action call: a
    machine-branchable reason with its human
    detail, in the house shape."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def run_check_prefix(workflow: object) -> str:
    """The prefix every check name of one
    workflow's jobs carries: ``<workflow> / ``,
    S-321's `check_name_for` separator verbatim.
    The workflow validates first (non-blank
    text, stripped). Pure."""
    if not isinstance(workflow, str) or not workflow.strip():
        raise WorkflowRunActionsError(
            "run_workflow_invalid",
            "run_workflow_invalid -- a run names "
            "its workflow. Nothing was recorded.")
    return f"{workflow.strip()} / "


def job_for_check_name(workflow: object,
                       check_name: object) -> str | None:
    """The job one check name belongs to under
    one workflow, or None when the name is not
    one of this workflow's job checks: the name
    must be exactly S-321's
    ``<workflow> / <job>`` with a non-blank job.
    Pure."""
    prefix = run_check_prefix(workflow)
    if not isinstance(check_name, str):
        return None
    if not check_name.startswith(prefix):
        return None
    job = check_name[len(prefix):]
    if not job.strip() or job != job.strip():
        return None
    return job


def is_run_check_name(workflow: object,
                      check_name: object) -> bool:
    """Whether one check name is one of this
    workflow's job checks. Pure."""
    return job_for_check_name(workflow, check_name) is not None


def validate_run_address(workflow: object,
                         oid: object) -> tuple:
    """The two names that address one run beside
    its repository, judged whole: a non-blank
    workflow and a non-blank commit, each
    stripped. Pure."""
    run_check_prefix(workflow)
    if not isinstance(oid, str) or not oid.strip():
        raise WorkflowRunActionsError(
            "run_oid_invalid",
            "run_oid_invalid -- a run names the "
            "commit it ran on. Nothing was "
            "recorded.")
    return str(workflow).strip(), str(oid).strip()


def standing_for_statuses(statuses) -> str:
    """One run's standing from its jobs'
    statuses, in words: no jobs -- the run does
    not stand (`not_found`); any job unfinished
    -- `running`; every job completed --
    `completed`. Pure."""
    words = tuple(statuses)
    if not words:
        return "not_found"
    if any(word != "completed" for word in words):
        return "running"
    return "completed"


def is_failed_conclusion(conclusion: object) -> bool:
    """Whether one concluded job counts as
    failed for a failed-only re-run, by
    `FAILED_CONCLUSIONS`. Pure."""
    return conclusion in FAILED_CONCLUSIONS


@dataclass(frozen=True)
class RunJob:
    """One job of a run, as its check run
    stands: the check's row, its job name under
    S-321's law, its status and conclusion in
    S-246's vocabulary, and the S-157 panel
    state S-246's fold decides for it."""
    check_run_id: int
    name: str          # <workflow> / <job>
    job_id: str
    status: str        # queued | in_progress | completed
    conclusion: str    # '' until completed
    panel_state: str   # pending | passed | failed
    poster: str
    description: str
    updated_at: int

    @property
    def words(self) -> str:
        if self.status == "completed":
            return (
                f"{self.name} -- completed, "
                f"{self.conclusion} (recorded as "
                f"{self.panel_state}).")
        return f"{self.name} -- {self.status}."


def run_job_to_dict(record: RunJob) -> dict:
    """One run job as JSON-safe data. Data
    carries the raw values -- S-010 escaping is
    the page's law, not the wire's."""
    return {
        "check_run_id": record.check_run_id,
        "name": record.name,
        "job_id": record.job_id,
        "status": record.status,
        "conclusion": record.conclusion,
        "panel_state": record.panel_state,
        "poster": record.poster,
        "description": record.description,
        "updated_at": record.updated_at,
    }


@dataclass(frozen=True)
class RunStanding:
    """One workflow run's standing: its address,
    its jobs in check-run order, the attempt it
    stands on (1 plus its recorded re-runs),
    and its standing in words."""
    full_name: str
    workflow: str
    oid: str
    jobs: tuple
    attempt: int

    @property
    def standing(self) -> str:
        return standing_for_statuses(
            job.status for job in self.jobs)

    @property
    def exists(self) -> bool:
        return bool(self.jobs)

    @property
    def failed_jobs(self) -> tuple:
        return tuple(
            job for job in self.jobs
            if job.status == "completed"
            and is_failed_conclusion(job.conclusion))

    @property
    def running_jobs(self) -> tuple:
        return tuple(
            job for job in self.jobs
            if job.status != "completed")

    @property
    def words(self) -> str:
        if not self.exists:
            return (
                f"Workflow {self.workflow} on "
                f"{self.oid} has not run.")
        if self.standing == "running":
            return (
                f"Workflow {self.workflow} on "
                f"{self.oid} is running (attempt "
                f"{self.attempt}): "
                f"{len(self.running_jobs)} of "
                f"{len(self.jobs)} jobs still "
                f"unfinished.")
        return (
            f"Workflow {self.workflow} on "
            f"{self.oid} completed (attempt "
            f"{self.attempt}): {len(self.jobs)} "
            f"jobs, {len(self.failed_jobs)} "
            f"failed.")


def run_standing_to_dict(standing: RunStanding) -> dict:
    """One run's standing as JSON-safe data."""
    return {
        "repository": standing.full_name,
        "workflow": standing.workflow,
        "oid": standing.oid,
        "standing": standing.standing,
        "attempt": standing.attempt,
        "jobs": [run_job_to_dict(job)
                 for job in standing.jobs],
    }


@dataclass(frozen=True)
class RunAction:
    """One recorded act on one run: the action
    row itself -- its kind, the attempt it
    opened (a re-run) or stopped (a cancel),
    the job check names it acted on in run
    order, who acted and when."""
    id: int
    repo_id: int
    full_name: str
    workflow: str
    oid: str
    kind: str          # one of ACTION_KINDS
    attempt: int
    jobs: tuple        # of check names, run order
    actor_id: int
    actor: str         # the actor's username
    created_at: int

    @property
    def words(self) -> str:
        return (
            f"{self.kind} on workflow "
            f"{self.workflow} ({self.oid}), "
            f"attempt {self.attempt}: "
            f"{len(self.jobs)} jobs, by "
            f"{self.actor}.")


def run_action_to_dict(record: RunAction) -> dict:
    """One recorded action as JSON-safe data."""
    return {
        "id": record.id,
        "repository": record.full_name,
        "workflow": record.workflow,
        "oid": record.oid,
        "kind": record.kind,
        "attempt": record.attempt,
        "jobs": list(record.jobs),
        "actor_id": record.actor_id,
        "actor": record.actor,
        "created_at": record.created_at,
    }


class WorkflowRunActionsStore:
    """The S-324 hands on a run: re-run all of
    a completed run's jobs, re-run only its
    failed jobs, or cancel a running run --
    each act recorded in `ci_run_actions` and
    witnessed once in S-007's chain. The store
    owns no check vocabulary of its own: the
    names are S-321's, the fold is S-246's, the
    panel row is S-157's, and the permission
    seam is S-054's."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._audit = audit
        self._now = time_fn
        self._checks = PullRequestChecksStore(
            conn, repositories, accounts, issues,
            time_fn=time_fn)

    # -- internals --------------------------------

    def _repo_for_read(self, viewer, owner: object,
                       repo: object):
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            # One answer for missing and unreadable
            # alike (S-054: a private repository's
            # existence is itself private).
            raise WorkflowRunActionsError(
                "repository_not_found",
                "repository_not_found -- no such "
                "repository.")
        return current

    def _repo_for_action(self, actor, owner: object,
                         repo: object):
        """The repository an act lands on: read
        standing first (the uniform not-found),
        then the write rung -- an act is a write
        on the repository, by S-054's law."""
        current = self._repo_for_read(actor, owner, repo)
        if actor is None or not can_write(actor, current):
            raise WorkflowRunActionsError(
                "permission_denied",
                "permission_denied -- re-running or "
                "cancelling a workflow run is a "
                "write act on its repository. "
                "Nothing was recorded.")
        return current

    def _run_rows(self, repo_id: int, workflow: str,
                  oid: str) -> list:
        """The run's (check row, job) pairs, in
        check-run order: the rows on the commit
        whose names are this workflow's jobs."""
        rows = self._conn.execute(
            "SELECT * FROM check_runs WHERE repo_id = ?"
            " AND head_oid = ? ORDER BY id",
            (repo_id, oid)).fetchall()
        picked = []
        for row in rows:
            job = job_for_check_name(workflow, row["name"])
            if job is not None:
                picked.append((row, job))
        return picked

    def _job_from_row(self, row, job: str) -> RunJob:
        return RunJob(
            check_run_id=row["id"], name=row["name"],
            job_id=job, status=row["status"],
            conclusion=row["conclusion"],
            panel_state=decide_check_run_panel_state(
                row["status"], row["conclusion"]),
            poster=row["poster"],
            description=row["description"],
            updated_at=row["updated_at"])

    def _attempt(self, repo_id: int, workflow: str,
                 oid: str) -> int:
        """The attempt a run stands on: 1 plus
        the re-runs recorded for it (cancels
        open no attempt)."""
        row = self._conn.execute(
            "SELECT COUNT(*) c FROM ci_run_actions"
            " WHERE repo_id = ? AND workflow = ?"
            " AND head_oid = ? AND kind IN (?, ?)",
            (repo_id, workflow, oid,
             ACTION_RERUN_ALL, ACTION_RERUN_FAILED)
        ).fetchone()
        return 1 + int(row["c"])

    def _action_from_row(self, row,
                         full_name: str) -> RunAction:
        return RunAction(
            id=row["id"], repo_id=row["repo_id"],
            full_name=full_name,
            workflow=row["workflow"],
            oid=row["head_oid"], kind=row["kind"],
            attempt=row["attempt"],
            jobs=tuple(json.loads(row["jobs"] or "[]")),
            actor_id=row["actor_id"],
            actor=row["actor"],
            created_at=row["created_at"])

    def _fold(self, current, oid: str, row,
              panel_state: str,
              description: str) -> None:
        """Fold one moved job onto S-157's panel
        record through its own seam, carrying the
        standing details link through untouched."""
        try:
            self._checks.record_result(
                current.owner, current.name, oid,
                row["name"], panel_state,
                target_url=row["target_url"],
                description=description)
        except PullRequestError as exc:
            raise WorkflowRunActionsError(
                exc.reason, str(exc)) from None

    def _audit_append(self, actor: User, kind: str,
                      current, workflow: str, oid: str,
                      attempt: int, jobs: list,
                      source_ip: str | None) -> None:
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action=EVENT_BY_ACTION[kind],
                target_kind="repo",
                target_id=current.full_name,
                outcome="success", source_ip=source_ip,
                detail={"workflow": workflow, "oid": oid,
                        "attempt": attempt, "jobs": jobs})

    # -- reads --------------------------------------

    def get_run(self, viewer: User | None,
                owner: object, repo: object,
                workflow: object,
                oid: object) -> RunStanding:
        """One run's standing: its jobs in
        check-run order, the attempt it stands
        on, and its standing in words. A run
        that never stood answers with no jobs --
        the page says so in words, it does not
        invent a run. The address validates
        before the repository is read."""
        workflow, oid = validate_run_address(workflow, oid)
        current = self._repo_for_read(viewer, owner, repo)
        jobs = tuple(
            self._job_from_row(row, job)
            for row, job in self._run_rows(
                current.id, workflow, oid))
        return RunStanding(
            full_name=current.full_name,
            workflow=workflow, oid=oid, jobs=jobs,
            attempt=self._attempt(
                current.id, workflow, oid))

    def list_run_actions(self, viewer: User | None,
                         owner: object, repo: object,
                         workflow: object,
                         oid: object) -> tuple:
        """Every act recorded on one run, in
        landing order: the run's own history of
        re-runs and cancels, read through the
        repository's read seam."""
        workflow, oid = validate_run_address(workflow, oid)
        current = self._repo_for_read(viewer, owner, repo)
        rows = self._conn.execute(
            "SELECT * FROM ci_run_actions"
            " WHERE repo_id = ? AND workflow = ?"
            " AND head_oid = ? ORDER BY id",
            (current.id, workflow, oid)).fetchall()
        return tuple(
            self._action_from_row(row, current.full_name)
            for row in rows)

    # -- the acts -----------------------------------

    def _record_action(self, current, workflow: str,
                       oid: str, kind: str, attempt: int,
                       jobs: list, actor: User,
                       now: int) -> int:
        cur = self._conn.execute(
            "INSERT INTO ci_run_actions"
            " (repo_id, workflow, head_oid, kind,"
            " attempt, jobs, actor_id, actor,"
            " created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (current.id, workflow, oid, kind, attempt,
             json.dumps(jobs), actor.id,
             actor.username, now))
        return int(cur.lastrowid)

    def _fresh_action(self, action_id: int,
                      full_name: str) -> RunAction:
        row = self._conn.execute(
            "SELECT * FROM ci_run_actions WHERE id = ?",
            (action_id,)).fetchone()
        return self._action_from_row(row, full_name)

    def _rerun(self, actor: User, owner: object,
               repo: object, workflow: object,
               oid: object, kind: str,
               source_ip: str | None) -> RunAction:
        workflow, oid = validate_run_address(workflow, oid)
        current = self._repo_for_action(actor, owner, repo)
        picked = self._run_rows(current.id, workflow, oid)
        if not picked:
            raise WorkflowRunActionsError(
                "run_not_found",
                "run_not_found -- no workflow run "
                f"of {workflow} stands on {oid}; "
                "there is nothing to re-run. "
                "Nothing was recorded.")
        if any(row["status"] != "completed"
               for row, _job in picked):
            raise WorkflowRunActionsError(
                "run_still_running",
                "run_still_running -- this run "
                "has not finished; cancel it "
                "before re-running it. Nothing "
                "was recorded.")
        if kind == ACTION_RERUN_ALL:
            targets = picked
        else:
            targets = [
                (row, job) for row, job in picked
                if is_failed_conclusion(row["conclusion"])]
            if not targets:
                raise WorkflowRunActionsError(
                    "rerun_no_failed_jobs",
                    "rerun_no_failed_jobs -- no job "
                    f"of workflow {workflow} on "
                    f"{oid} failed; there is "
                    "nothing to re-run. Nothing "
                    "was recorded.")
        attempt = self._attempt(
            current.id, workflow, oid) + 1
        description = (
            f"Re-run requested by {actor.username} "
            f"(attempt {attempt}); awaiting a "
            "runner.")
        panel_state = decide_check_run_panel_state(
            "queued", "")
        for row, _job in targets:
            self._fold(current, oid, row,
                       panel_state, description)
        now = int(self._now())
        with self._conn:
            for row, _job in targets:
                self._conn.execute(
                    "UPDATE check_runs SET status = 'queued',"
                    " conclusion = '', description = ?,"
                    " updated_at = ? WHERE id = ?",
                    (description, now, row["id"]))
            action_id = self._record_action(
                current, workflow, oid, kind, attempt,
                [row["name"] for row, _job in targets],
                actor, now)
        record = self._fresh_action(action_id,
                                    current.full_name)
        self._audit_append(
            actor, kind, current, workflow, oid,
            attempt, list(record.jobs), source_ip)
        return record

    def rerun_all(self, actor: User, owner: object,
                  repo: object, workflow: object,
                  oid: object, *,
                  source_ip: str | None = None
                  ) -> RunAction:
        """Re-run every job of one completed run:
        each job's check returns to `queued` and
        its panel row to `pending`, opening the
        next attempt. The act is recorded and
        witnessed; dispatch to a runner is
        S-316's seam, not faked here."""
        return self._rerun(
            actor, owner, repo, workflow, oid,
            ACTION_RERUN_ALL, source_ip)

    def rerun_failed_jobs(self, actor: User,
                          owner: object, repo: object,
                          workflow: object,
                          oid: object, *,
                          source_ip: str | None = None
                          ) -> RunAction:
        """Re-run only one completed run's failed
        jobs (`FAILED_CONCLUSIONS`): jobs that
        passed, were skipped or were cancelled
        keep their standing words."""
        return self._rerun(
            actor, owner, repo, workflow, oid,
            ACTION_RERUN_FAILED, source_ip)

    def cancel_run(self, actor: User, owner: object,
                   repo: object, workflow: object,
                   oid: object, *,
                   source_ip: str | None = None
                   ) -> RunAction:
        """Cancel one running run: every
        unfinished job completes as `cancelled`
        (the panel folds it to `failed`, S-246's
        word); jobs that already concluded keep
        their words. The act is recorded and
        witnessed, under the attempt it stopped."""
        workflow, oid = validate_run_address(workflow, oid)
        current = self._repo_for_action(actor, owner, repo)
        picked = self._run_rows(current.id, workflow, oid)
        if not picked:
            raise WorkflowRunActionsError(
                "run_not_found",
                "run_not_found -- no workflow run "
                f"of {workflow} stands on {oid}; "
                "there is nothing to cancel. "
                "Nothing was recorded.")
        targets = [
            (row, job) for row, job in picked
            if row["status"] != "completed"]
        if not targets:
            raise WorkflowRunActionsError(
                "run_not_running",
                "run_not_running -- this run has "
                "already completed; there is "
                "nothing left to cancel. Nothing "
                "was recorded.")
        attempt = self._attempt(
            current.id, workflow, oid)
        description = f"Cancelled by {actor.username}."
        panel_state = decide_check_run_panel_state(
            "completed", "cancelled")
        for row, _job in targets:
            self._fold(current, oid, row,
                       panel_state, description)
        now = int(self._now())
        with self._conn:
            for row, _job in targets:
                self._conn.execute(
                    "UPDATE check_runs SET"
                    " status = 'completed',"
                    " conclusion = 'cancelled',"
                    " description = ?, updated_at = ?"
                    " WHERE id = ?",
                    (description, now, row["id"]))
            action_id = self._record_action(
                current, workflow, oid, ACTION_CANCEL,
                attempt,
                [row["name"] for row, _job in targets],
                actor, now)
        record = self._fresh_action(action_id,
                                    current.full_name)
        self._audit_append(
            actor, ACTION_CANCEL, current, workflow,
            oid, attempt, list(record.jobs), source_ip)
        return record


# ------------------------------------------------------------------
# The audit: the actions checked against the live instance.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowRunActionsAudit:
    """The run actions checked against one live
    instance: the failed vocabulary is S-246's
    fold minus `cancelled`, the schema is
    exactly 132 (this slice's migration), the
    taxonomy is exactly the standing 138 with
    this slice's three events in the repo
    family, the lawful tables stand, and every
    standing action row obeys the store's law --
    a lawful kind, an attempt of at least 1,
    a non-empty job list of this workflow's own
    check names, a repository that stands, and
    an actor named."""
    vocabulary_ok: bool
    schema_version: int
    schema_ok: bool
    events_ok: bool
    tables_ok: bool
    rows_scanned: int
    problems: tuple

    @property
    def stands_cleanly(self) -> bool:
        return (
            self.vocabulary_ok and self.schema_ok
            and self.events_ok and self.tables_ok
            and not self.problems)


def audit_workflow_run_actions(conn: sqlite3.Connection
                               ) -> WorkflowRunActionsAudit:
    """Check the run actions against the live
    instance: the vocabularies, schema and
    taxonomy pins hold, the `ci_run_actions`,
    `check_runs` and `commit_checks` tables
    stand, and every standing action row obeys
    the store's law. Pure read."""
    from .db import schema_version as _schema_version
    version = _schema_version(conn)
    events_ok = (
        len(taxonomy.AUDIT_EVENTS) == 138
        and len(taxonomy.AUTH_EVENTS) == 33
        and len(taxonomy.REPO_EVENTS) == 92
        and len(taxonomy.ADMIN_EVENTS) == 13
        and all(event in taxonomy.REPO_EVENTS
                for event in EVENT_BY_ACTION.values()))
    vocabulary_ok = (
        ACTION_KINDS == ("rerun_all", "rerun_failed",
                         "cancel")
        and tuple(EVENT_BY_ACTION[kind]
                  for kind in ACTION_KINDS) == (
                      "repo.workflow_run.rerun_all",
                      "repo.workflow_run.rerun_failed",
                      "repo.workflow_run.cancel")
        and all(word in CHECK_RUN_CONCLUSIONS
                for word in FAILED_CONCLUSIONS)
        and "cancelled" not in FAILED_CONCLUSIONS
        and decide_check_run_panel_state(
            "completed", "cancelled") == "failed"
        and decide_check_run_panel_state(
            "queued", "") == "pending"
        and check_name_for("CI", "build") == "CI / build")
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    tables_ok = (_TABLE in tables
                 and "check_runs" in tables
                 and "commit_checks" in tables)
    problems: list = []
    rows = conn.execute(
        "SELECT * FROM ci_run_actions ORDER BY id"
    ).fetchall() if _TABLE in tables else []
    repo_ids = set()
    if "repositories" in tables:
        repo_ids = {r["id"] for r in conn.execute(
            "SELECT id FROM repositories").fetchall()}
    for row in rows:
        label = f"action {row['id']}"
        if row["kind"] not in ACTION_KINDS:
            problems.append(
                f"{label}: its kind is not one of "
                "the standing kinds")
            continue
        if not isinstance(row["attempt"], int) \
                or row["attempt"] < 1:
            problems.append(
                f"{label}: its attempt is not a "
                "standing attempt")
        try:
            jobs = json.loads(row["jobs"] or "[]")
        except ValueError:
            jobs = None
        if not isinstance(jobs, list) or not jobs:
            problems.append(
                f"{label}: its job list does not "
                "stand")
        else:
            for name in jobs:
                if job_for_check_name(
                        row["workflow"], name) is None:
                    problems.append(
                        f"{label}: job {name!r} is "
                        "not one of its workflow's "
                        "checks")
        if repo_ids and row["repo_id"] not in repo_ids:
            problems.append(
                f"{label}: its repository does "
                "not stand")
        if not row["actor"] or row["actor_id"] < 1:
            problems.append(
                f"{label}: its actor does not "
                "stand")
    return WorkflowRunActionsAudit(
        vocabulary_ok=vocabulary_ok,
        schema_version=version, schema_ok=version == 137,
        events_ok=events_ok, tables_ok=tables_ok,
        rows_scanned=len(rows), problems=tuple(problems))


def render_run_actions_page(
        standing: RunStanding | None = None,
        actions: tuple = (),
        audit: WorkflowRunActionsAudit | None = None
        ) -> str:
    """One run's actions view, in plain words:
    what re-run and cancel do, what each act
    leaves behind, and -- when a standing and
    its history ride along -- the run itself,
    its jobs and its recorded acts, every
    standing said in words (never a colour
    alone). Every value escaped through
    S-010."""
    parts = [
        "<h1>Workflow run actions</h1>",
        "<p>A completed run can be re-run: every "
        "job, or only the jobs that failed "
        "(failure, timed out or action required "
        "-- a cancelled job was stopped on "
        "purpose and is covered by re-running "
        "all). Re-running returns the chosen "
        "jobs to queued and their checks to "
        "pending, and opens the next attempt; "
        "the new attempt's conclusions land on "
        "the same checks when a runner reports "
        "them. A run that is still going can be "
        "cancelled: its unfinished jobs complete "
        "as cancelled and finished jobs keep "
        "their words. Every re-run and every "
        "cancel is recorded on the run and "
        "written to the audit log with who "
        "acted; a refused action records "
        "nothing.</p>",
    ]
    if standing is not None:
        parts.append(
            f"<p>{escape_html_text(standing.words)}</p>")
        for job in standing.jobs:
            parts.append(
                f"<p>{escape_html_text(job.words)}</p>")
    for record in actions:
        parts.append(
            f"<p>{escape_html_text(record.words)}</p>")
    if audit is not None:
        verdict = ("stands cleanly"
                   if audit.stands_cleanly
                   else "does not stand cleanly")
        parts.append(
            f"<p>Checked against this instance: "
            f"the run actions "
            f"{escape_html_text(verdict)} "
            f"(schema {audit.schema_version}, "
            f"{audit.rows_scanned} actions "
            f"scanned).</p>")
    return "\n".join(parts)
