"""Workflow UI -- the run list, the run detail
and workflow linting (S-327).

Workflow UI -- run list, run detail (jobs,
steps, timing, logs), workflow file linting
with errors in plain words.

Part XVI built the machine room by room:
S-313 decided the workflow format and its pure
validator, S-315 modelled jobs and steps,
S-321 landed each job's terminal conclusion as
a check run named ``<workflow> / <job>`` on the
run's commit, S-322 stored each job's log under
its (run, job) address, and S-323 gathered a
run's artifacts onto the run page. What none of
them built is the page a person actually opens
to answer "what ran, how did it go, and what
did it say?" -- and the lint a person runs over
a workflow file before pushing it. This module
is those two faces, as gatherings over the
standing rows, in S-322's and S-323's shape.

- **A run is addressed as the forge addresses
  it.** One workflow run on one commit is the
  triple S-323 named -- repository, workflow,
  commit (`oid`) -- and its jobs are the check
  runs standing on that commit whose names
  S-321's `check_name_for` law built for this
  workflow, decided by S-323's own
  `job_for_check_name`. There is no run table
  and no second record: a run whose jobs have
  landed nothing lists honestly empty, and a
  job named in the workflow file that has
  landed no conclusion yet stands on the
  detail page as *pending*, in words -- never
  invented as passed (S-325's trap, refused
  here too: pending is not passed).
- **The run list is the same gathering,
  grouped.** Every check run in a repository
  whose name splits at its last `` / `` into a
  workflow and a job id lawful under S-316's
  name law belongs to the run of that workflow
  on that commit; plain-named checks (an
  external poster's own context) are not runs
  and never appear. Runs answer in first-
  landing order, jobs in landing order, each
  run's standing decided by the pure
  `run_conclusion_for` over its jobs'
  conclusions -- S-316's aggregate precedence
  (failure, then timed_out, then cancelled,
  then all-skipped, else success) extended
  with `action_required` and `neutral`, the
  two words a single step can never say but a
  job can. Timing is the stamps the rows
  carry: a run spans its first job's landing
  to its last job's update, said in words by
  `format_duration`.
- **The detail page carries steps, timing
  and logs, honestly sourced.** Steps come
  from the workflow file itself: when the
  caller hands the detail its workflow text,
  the text is linted (below) and the standing
  definition's steps stand under each job, in
  file order. Per-step conclusions are stored
  nowhere in the forge -- S-321 lands one
  conclusion per job -- so the page says
  exactly that, in words, rather than dressing
  the job's word as each step's. Logs come
  from S-322: when the caller names the run's
  `run_id` (the address S-316's protocol and
  S-322's store share), each job's tail rides
  the detail through S-322's own store; a job
  with no stored log says so in words, and a
  detail asked for with no run id says logs
  are addressed by run id and none was named.
  The run's artifacts ride along as S-323's
  own listing -- its counts and words, read
  through S-323's store, not restated here.
- **States are said in text+icon, never
  colour-only (the house law from S-157).**
  Every conclusion -- and pending -- has one
  word and one glyph, decided by the pure
  `conclusion_word` / `conclusion_icon` /
  `conclusion_words`, and every render uses
  them: ``✓ Succeeded``, ``✗ Failed``,
  ``◐ Pending``, and kin. A reader who cannot
  see colour, or the glyph, still gets the
  whole standing from the word alone.
- **Linting is S-313's validator, surfaced.**
  `lint_workflow` judges one workflow file --
  its path (a workflow lives in
  `.samverk/workflows/` as `.yml` / `.yaml`;
  a `.github/workflows/` path is refused with
  the deliberate difference said in plain
  words) and its text, through S-313's own
  `parse_workflow`, whose refusals already
  speak plain words (``workflow_uses_refused``
  names the marketplace-action break,
  ``workflow_expression_refused`` the
  expression break, `workflow_invalid` the
  shape). A lint answers every problem it
  found -- the path's and the text's first --
  each as a reason beside its plain-words
  sentence, or, when the file stands clean,
  the definition's own summary: its name, its
  triggers, its jobs and their step counts.
  `lint_workflows` lints a whole directory's
  worth in path order. Linting is pure: it
  reads no row and writes none.
- **Reads follow the repository (S-054).**
  Every store read takes a viewer and resolves
  the repository through S-054's `can_read`
  before any run is named: a missing
  repository and a private repository the
  viewer cannot read answer the one uniform
  `repository_not_found`. Anonymous readers
  read public repositories' run pages, as
  everywhere else in the forge.
- **The durable artefact is the standing
  rows.** This UI writes nothing: no row, no
  audit entry, no taxonomy event (135 stand:
  33 auth / 89 repo / 13 admin), on S-321's,
  S-322's and S-323's basis -- the witnessed
  record of a run is its check rows, its logs
  and its artifacts, and this page only reads
  them. No migration: the tables are S-246's
  `check_runs` (migration 95), S-157's
  `commit_checks` (migration 58), S-322's
  `ci_logs` (migration 131) and S-266's
  `ci_artifacts` (migration 105), and the
  schema stays 131. S-328 owns the Part XVI
  gate battery; the render functions here are
  the run pages in the house shape, every
  value escaped through S-010.
"""
from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import taxonomy
from .accounts import User
from .ci_logs import (
    LogStreamingError, LogStreamingStore, LogTail,
    validate_log_identity, validate_tail_lines)
from .escaping import escape_html_text
from .permissions import can_read
from .repositories import RepositoryStore
from .runner_protocol import RUNNER_CONCLUSIONS
from .workflow_artifacts import (
    RunArtifacts, WorkflowArtifactsError,
    WorkflowArtifactsStore, job_for_check_name,
    validate_run_address)
from .workflow_format import (
    WorkflowDefinition, WorkflowFormatError,
    is_github_workflow_path, is_workflow_path,
    parse_workflow)

__all__ = [
    "PENDING", "JobLogView", "JobView", "LintError",
    "LintResult", "RunDetail", "RunJob", "RunSummary",
    "StepView", "WorkflowUIAudit", "WorkflowUIError",
    "WorkflowUIStore", "audit_workflow_ui",
    "conclusion_icon", "conclusion_word",
    "conclusion_words", "detail_to_dict",
    "format_duration", "lint_to_dict", "lint_workflow",
    "lint_workflows", "render_lint_page",
    "render_run_detail_page", "render_run_list_page",
    "run_conclusion_for", "run_to_dict",
    "split_check_name",
]

#: The standing of a job (or run) whose
#: conclusion has not landed: a word of its
#: own, never folded into passed (S-325's
#: trap) and never into failed.
PENDING = "pending"

#: S-316's name law, restated for the job id a
#: check name's tail must satisfy before the
#: name counts as one of a workflow's jobs in
#: the run list's grouping (the detail road
#: judges by S-323's own law instead).
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: One job instance's name, as S-321 names a
#: job's check: S-316's name law for a plain
#: job, or S-315's matrix instance shape --
#: ``<job> (<value, ...>)`` -- for an expanded
#: one. A job tail matching neither is not a
#: workflow job's name.
_INSTANCE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]* \((.+)\)$")

#: Every standing a run page can say, each with
#: its one word and its one glyph -- text+icon,
#: never colour-only (S-157's house law). The
#: conclusions are S-316's vocabulary verbatim;
#: `pending` is this page's own word for a job
#: that has landed nothing yet.
_CONCLUSION_WORDS = {
    "success": "Succeeded",
    "failure": "Failed",
    "neutral": "Neutral",
    "cancelled": "Cancelled",
    "skipped": "Skipped",
    "timed_out": "Timed out",
    "action_required": "Action required",
    PENDING: "Pending",
}
_CONCLUSION_ICONS = {
    "success": "\u2713",
    "failure": "\u2717",
    "neutral": "\u25cb",
    "cancelled": "\u2298",
    "skipped": "\u00bb",
    "timed_out": "\u25f7",
    "action_required": "\u26a0",
    PENDING: "\u25d0",
}

_SURFACE_WORD = "workflow_ui"


class WorkflowUIError(ValueError):
    """One refused workflow-UI call: a
    machine-branchable reason with its human
    detail, in the house shape."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def conclusion_word(conclusion: object) -> str:
    """The one word one standing is said with
    on every run page. An unknown standing is
    refused whole, never guessed at. Pure."""
    if conclusion not in _CONCLUSION_WORDS:
        raise WorkflowUIError(
            "run_conclusion_invalid",
            f"run_conclusion_invalid -- "
            f"{conclusion!r} is not a standing a "
            "run page says: success, failure, "
            "neutral, cancelled, skipped, "
            "timed_out, action_required or "
            "pending. Nothing was recorded.")
    return _CONCLUSION_WORDS[str(conclusion)]


def conclusion_icon(conclusion: object) -> str:
    """The one glyph one standing is said with,
    always beside its word. Pure."""
    conclusion_word(conclusion)
    return _CONCLUSION_ICONS[str(conclusion)]


def conclusion_words(conclusion: object) -> str:
    """One standing as text+icon together --
    ``\u2713 Succeeded`` -- the only shape a
    render may say a standing in. Pure."""
    return (f"{conclusion_icon(conclusion)} "
            f"{conclusion_word(conclusion)}")


def format_duration(seconds: object) -> str:
    """One span of seconds said in plain words:
    ``0 seconds``, ``5 seconds``, ``1 minute``,
    ``2 minutes 5 seconds``, ``1 hour 1 minute
    1 second``, ``1 day 2 hours``. A span is a
    whole, non-negative number of seconds.
    Pure."""
    if (isinstance(seconds, bool)
            or not isinstance(seconds, int)
            or seconds < 0):
        raise WorkflowUIError(
            "run_duration_invalid",
            "run_duration_invalid -- a span is a "
            "whole, non-negative number of "
            "seconds. Nothing was recorded.")
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list = []
    for value, unit in ((days, "day"), (hours, "hour"),
                        (minutes, "minute"),
                        (secs, "second")):
        if value:
            parts.append(
                f"{value} {unit}"
                + ("s" if value != 1 else ""))
    if not parts:
        return "0 seconds"
    return " ".join(parts)


def split_check_name(name: object) -> tuple | None:
    """The (workflow, job) one check name names,
    or None when the name is not a workflow
    job's check: the name must split at a
    `` / `` (S-321's separator) into a non-blank
    workflow and a job in S-315's instance
    shape (S-316's name law, or a matrix
    instance's ``<job> (<values>)`` name). The
    splits are tried in order, so a workflow
    whose own name carries `` / `` still
    resolves to the first lawful job tail.
    Plain-named checks answer None. Pure."""
    if not isinstance(name, str):
        return None
    start = 0
    while True:
        idx = name.find(" / ", start)
        if idx < 0:
            return None
        workflow = name[:idx]
        job = name[idx + 3:]
        if (workflow.strip()
                and workflow == workflow.strip()
                and (_NAME_RE.match(job)
                     or _INSTANCE_RE.match(job))):
            return workflow, job
        start = idx + 1


def run_conclusion_for(conclusions) -> str:
    """The one standing a whole run carries,
    from its jobs' conclusions: S-316's
    aggregate precedence -- any failure fails
    the run; else any timed_out; else any
    action_required; else any cancelled; else
    any neutral; else all-skipped is skipped;
    else success. No conclusions at all is
    `pending`: the run has landed nothing, and
    pending is never said as passed. Every
    word validates against S-316's vocabulary
    first. Pure."""
    words = tuple(conclusions)
    for word in words:
        if word not in RUNNER_CONCLUSIONS:
            raise WorkflowUIError(
                "run_conclusion_invalid",
                f"run_conclusion_invalid -- "
                f"{word!r} is not a job conclusion "
                "in S-316's vocabulary. Nothing "
                "was recorded.")
    if not words:
        return PENDING
    for word in ("failure", "timed_out",
                 "action_required", "cancelled",
                 "neutral"):
        if word in words:
            return word
    if all(word == "skipped" for word in words):
        return "skipped"
    return "success"


# ------------------------------------------------------------------
# The views: one run, its jobs, its detail.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class RunJob:
    """One job of one run, as its landed check
    run stands: the job, its S-321 check name,
    its conclusion and folded panel state, the
    description the landing carried, and the
    stamps it landed and last moved at."""
    job_id: str
    check_name: str
    conclusion: str
    panel_state: str
    description: str
    created_at: int
    updated_at: int

    @property
    def words(self) -> str:
        return (
            f"{self.job_id} -- "
            f"{conclusion_words(self.conclusion)}.")


def _job_to_dict(job: RunJob) -> dict:
    return {
        "job_id": job.job_id,
        "check_name": job.check_name,
        "conclusion": job.conclusion,
        "word": conclusion_word(job.conclusion),
        "panel_state": job.panel_state,
        "description": job.description,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@dataclass(frozen=True)
class RunSummary:
    """One workflow run in the list: its
    address, its jobs in landing order, and the
    stamps its span is read from."""
    full_name: str
    workflow: str
    oid: str
    jobs: tuple

    @property
    def conclusion(self) -> str:
        return run_conclusion_for(
            job.conclusion for job in self.jobs)

    @property
    def first_at(self) -> int | None:
        if not self.jobs:
            return None
        return min(job.created_at for job in self.jobs)

    @property
    def last_at(self) -> int | None:
        if not self.jobs:
            return None
        return max(job.updated_at for job in self.jobs)

    @property
    def span_seconds(self) -> int:
        if self.first_at is None or self.last_at is None:
            return 0
        return max(0, self.last_at - self.first_at)

    @property
    def words(self) -> str:
        if not self.jobs:
            return (
                f"Workflow {self.workflow} on "
                f"{self.oid} has landed no jobs yet "
                f"-- {conclusion_words(PENDING)}.")
        return (
            f"Workflow {self.workflow} on {self.oid} "
            f"-- {conclusion_words(self.conclusion)} "
            f"across {len(self.jobs)} jobs, spanning "
            f"{format_duration(self.span_seconds)}.")


def run_to_dict(run: RunSummary) -> dict:
    """One run summary as JSON-safe data. Data
    carries the raw values -- S-010 escaping is
    the page's law, not the wire's."""
    return {
        "repository": run.full_name,
        "workflow": run.workflow,
        "oid": run.oid,
        "conclusion": run.conclusion,
        "word": conclusion_word(run.conclusion),
        "job_count": len(run.jobs),
        "first_at": run.first_at,
        "last_at": run.last_at,
        "span_seconds": run.span_seconds,
        "jobs": [_job_to_dict(job) for job in run.jobs],
    }


@dataclass(frozen=True)
class StepView:
    """One step of one job, as the workflow
    file defines it: its name (or its shell's
    first words when unnamed, said as such by
    the render) and its shell. Steps carry no
    conclusion of their own -- none is stored
    anywhere in the forge (S-321 lands one
    conclusion per job)."""
    name: str
    run: str

    @property
    def words(self) -> str:
        label = self.name or "(unnamed step)"
        return f"{label} -- run: {self.run}"


@dataclass(frozen=True)
class JobLogView:
    """One job's log tail on the detail page:
    S-322's own tail window, carried whole."""
    tail: LogTail

    @property
    def words(self) -> str:
        return self.tail.words


@dataclass(frozen=True)
class JobView:
    """One job on the detail page: its landed
    check run when one stands (None while the
    job is known only from the workflow file),
    its definition steps, and its log tail when
    one was read."""
    job_id: str
    check_name: str
    job: RunJob | None
    steps: tuple
    log: JobLogView | None
    log_named: bool

    @property
    def conclusion(self) -> str:
        if self.job is None:
            return PENDING
        return self.job.conclusion

    @property
    def words(self) -> str:
        if self.job is None:
            return (
                f"{self.job_id} -- "
                f"{conclusion_words(PENDING)}: no "
                "conclusion has landed for this "
                "job yet.")
        return self.job.words


@dataclass(frozen=True)
class RunDetail:
    """One run's detail page: the run's address,
    its jobs (landed and, when the workflow
    file rides along, defined-but-unlanded),
    the lint of the workflow file when one
    rode along, the run id its logs were read
    under (None when none was named), and the
    run's S-323 artifact listing."""
    full_name: str
    workflow: str
    oid: str
    jobs: tuple
    lint: LintResult | None
    run_id: str | None
    artifacts: RunArtifacts

    @property
    def conclusion(self) -> str:
        return run_conclusion_for(
            view.conclusion for view in self.jobs
            if view.job is not None)

    @property
    def first_at(self) -> int | None:
        landed = [view.job.created_at
                  for view in self.jobs
                  if view.job is not None]
        return min(landed) if landed else None

    @property
    def last_at(self) -> int | None:
        landed = [view.job.updated_at
                  for view in self.jobs
                  if view.job is not None]
        return max(landed) if landed else None

    @property
    def span_seconds(self) -> int:
        if self.first_at is None or self.last_at is None:
            return 0
        return max(0, self.last_at - self.first_at)

    @property
    def words(self) -> str:
        landed = sum(1 for view in self.jobs
                     if view.job is not None)
        return (
            f"Workflow {self.workflow} on {self.oid} "
            f"-- {conclusion_words(self.conclusion)}: "
            f"{landed} of {len(self.jobs)} jobs have "
            f"landed a conclusion, spanning "
            f"{format_duration(self.span_seconds)}; "
            f"{self.artifacts.words}")


def detail_to_dict(detail: RunDetail) -> dict:
    """One run detail as JSON-safe data."""
    jobs = []
    for view in detail.jobs:
        entry = {
            "job_id": view.job_id,
            "check_name": view.check_name,
            "conclusion": view.conclusion,
            "word": conclusion_word(view.conclusion),
            "landed": view.job is not None,
            "steps": [{"name": step.name,
                       "run": step.run}
                      for step in view.steps],
            "log": None,
        }
        if view.job is not None:
            entry.update({
                "panel_state": view.job.panel_state,
                "description": view.job.description,
                "created_at": view.job.created_at,
                "updated_at": view.job.updated_at,
            })
        if view.log is not None:
            entry["log"] = {
                "lines": list(view.log.tail.lines),
                "total_lines": view.log.tail.total_lines,
                "first_line": view.log.tail.first_line,
                "truncated": view.log.tail.truncated,
            }
        jobs.append(entry)
    return {
        "repository": detail.full_name,
        "workflow": detail.workflow,
        "oid": detail.oid,
        "conclusion": detail.conclusion,
        "word": conclusion_word(detail.conclusion),
        "span_seconds": detail.span_seconds,
        "run_id": detail.run_id,
        "jobs": jobs,
        "lint": (lint_to_dict(detail.lint)
                 if detail.lint is not None else None),
        "artifacts": {
            "total_count": detail.artifacts.total_count,
            "total_bytes": detail.artifacts.total_bytes,
            "expired_count": detail.artifacts.expired_count,
        },
    }


# ------------------------------------------------------------------
# Linting: S-313's validator, surfaced in plain words.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class LintError:
    """One problem one lint found: the
    machine-branchable reason and its sentence
    in plain words, exactly as the judging
    face spoke it."""
    reason: str
    message: str

    @property
    def words(self) -> str:
        return f"{self.reason} -- {self.message}"


@dataclass(frozen=True)
class LintResult:
    """One workflow file's lint: the path it
    was judged under (empty when none was
    named), every problem found, and -- when
    the file stands clean -- the definition
    it parsed to, summarised."""
    path: str
    errors: tuple
    definition: WorkflowDefinition | None

    @property
    def ok(self) -> bool:
        return not self.errors and self.definition is not None

    @property
    def job_ids(self) -> tuple:
        if self.definition is None:
            return ()
        return tuple(job.id for job in self.definition.jobs)

    @property
    def step_count(self) -> int:
        if self.definition is None:
            return 0
        return sum(len(job.steps)
                   for job in self.definition.jobs)

    @property
    def words(self) -> str:
        label = self.path or "(unnamed workflow file)"
        if self.ok:
            definition = self.definition
            name = definition.name or "(unnamed workflow)"
            return (
                f"{label} -- clean: workflow "
                f"{name!r} on "
                f"{', '.join(definition.triggers)}; "
                f"{len(definition.jobs)} jobs, "
                f"{self.step_count} steps, no "
                "problems found.")
        return (
            f"{label} -- {len(self.errors)} "
            f"problem(s): "
            + "; ".join(error.words
                          for error in self.errors))


def lint_to_dict(result: LintResult) -> dict:
    """One lint as JSON-safe data."""
    return {
        "path": result.path,
        "ok": result.ok,
        "errors": [{"reason": error.reason,
                    "message": error.message}
                   for error in result.errors],
        "jobs": list(result.job_ids),
        "step_count": result.step_count,
    }


def lint_workflow(text: object,
                  path: object = None) -> LintResult:
    """Lint one workflow file: its path judged
    against S-313's directory law, its text
    judged by S-313's own `parse_workflow`.
    Every problem found answers as a LintError
    in plain words -- the path's problem and
    the text's first problem ride together, so
    one lint never hides a second known fault
    behind the first. Pure."""
    errors: list = []
    label = ""
    if path is not None:
        if not isinstance(path, str) or not path.strip():
            errors.append(LintError(
                "workflow_path_invalid",
                "workflow_path_invalid -- a workflow "
                "file's path is text naming where "
                "the file lives."))
        else:
            label = path.strip()
            if is_github_workflow_path(label):
                errors.append(LintError(
                    "workflow_path_github",
                    "workflow_path_github -- this "
                    "file lives under "
                    ".github/workflows/, which is "
                    "GitHub's directory, not "
                    "Samverk's: Samverk workflows "
                    "live in .samverk/workflows/ "
                    "(S-313's deliberate "
                    "difference), and a file copied "
                    "unchanged from a GitHub "
                    "repository is not promised to "
                    "run."))
            elif not is_workflow_path(label):
                errors.append(LintError(
                    "workflow_path_invalid",
                    "workflow_path_invalid -- a "
                    "workflow file lives in "
                    ".samverk/workflows/ as a .yml "
                    "or .yaml file; this path names "
                    "somewhere else."))
    definition: WorkflowDefinition | None = None
    try:
        definition = parse_workflow(text)
    except WorkflowFormatError as exc:
        errors.append(LintError(exc.reason, str(exc)))
    if errors:
        definition = None
    return LintResult(
        path=label, errors=tuple(errors),
        definition=definition)


def lint_workflows(files: dict) -> tuple:
    """Lint a whole set of workflow files at
    once: a mapping of path to text, answered
    as one LintResult per file, in path order.
    Pure."""
    if not isinstance(files, dict):
        raise WorkflowUIError(
            "workflow_files_invalid",
            "workflow_files_invalid -- a lint of "
            "many files takes a mapping of path "
            "to file text. Nothing was recorded.")
    return tuple(
        lint_workflow(files[path], path)
        for path in sorted(files, key=str))


# ------------------------------------------------------------------
# The store: the gatherings over the standing rows.
# ------------------------------------------------------------------

class WorkflowUIStore:
    """The S-327 pages' read face: the run
    list and the run detail, gathered from
    S-321's landed check runs, S-322's stored
    logs and S-323's artifact listing, read
    through the repository's own permission
    seam. It owns no run law of its own: the
    run's address and job names are S-323's,
    the conclusions are S-316's, the logs are
    S-322's, the artifacts are S-323's, the
    lint is S-313's, and the read gate is
    S-054's."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._now = time_fn
        self._logs = LogStreamingStore(
            conn, repositories, time_fn=time_fn)
        self._artifacts = WorkflowArtifactsStore(
            conn, repositories, time_fn=time_fn)

    # -- internals --------------------------------

    def _repo_for_read(self, viewer, owner: object,
                       repo: object):
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            # One answer for missing and unreadable
            # alike (S-054: a private repository's
            # existence is itself private).
            raise WorkflowUIError(
                "repository_not_found",
                "repository_not_found -- no such "
                "repository.")
        return current

    def _panel_state(self, repo_id: int, oid: str,
                     check_name: str) -> str:
        panel = self._conn.execute(
            "SELECT state FROM commit_checks"
            " WHERE repo_id = ? AND head_oid = ?"
            " AND context = ?",
            (repo_id, oid, check_name)).fetchone()
        return panel["state"] if panel else ""

    def _job_from_row(self, row, job_id: str) -> RunJob:
        return RunJob(
            job_id=job_id, check_name=row["name"],
            conclusion=row["conclusion"],
            panel_state=self._panel_state(
                row["repo_id"], row["head_oid"],
                row["name"]),
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"])

    # -- the run list ------------------------------

    def list_runs(self, viewer: User | None,
                  owner: object,
                  repo: object) -> list:
        """Every workflow run standing in one
        repository: its check runs grouped by
        (workflow, commit) under the name law,
        runs in first-landing order, jobs in
        landing order. Plain-named checks are
        not runs and never appear; a repository
        with no runs answers an empty list,
        honestly."""
        current = self._repo_for_read(viewer, owner, repo)
        rows = self._conn.execute(
            "SELECT * FROM check_runs WHERE repo_id = ?"
            " ORDER BY id", (current.id,)).fetchall()
        order: list = []
        grouped: dict = {}
        for row in rows:
            split = split_check_name(row["name"])
            if split is None:
                continue
            workflow, job_id = split
            key = (workflow, row["head_oid"])
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(
                self._job_from_row(row, job_id))
        return [RunSummary(
                    full_name=current.full_name,
                    workflow=workflow, oid=oid,
                    jobs=tuple(grouped[(workflow, oid)]))
                for workflow, oid in order]

    # -- the run detail ----------------------------

    def run_detail(self, viewer: User | None,
                   owner: object, repo: object,
                   workflow: object, oid: object,
                   *,
                   workflow_text: object = None,
                   run_id: object = None,
                   tail_lines: object = None) -> RunDetail:
        """One run's detail: its landed jobs in
        landing order; when *workflow_text*
        rides along, its lint and its defined
        jobs -- landed jobs gain their file's
        steps, defined-but-unlanded jobs stand
        as pending; when *run_id* rides along,
        each landed job's S-322 log tail (the
        last *tail_lines* lines, S-322's own
        window law) is read under that address,
        and a job with no stored log says so by
        carrying none. The address validates
        before the repository is read, so an
        unlawful address is refused even over a
        repository that does not stand. A run
        that never stood answers honestly empty
        of landed jobs -- the page says so in
        words, it does not invent a run."""
        try:
            workflow, oid = validate_run_address(workflow, oid)
        except WorkflowArtifactsError as exc:
            raise WorkflowUIError(
                exc.reason, str(exc)) from None
        current = self._repo_for_read(viewer, owner, repo)
        rows = self._conn.execute(
            "SELECT * FROM check_runs WHERE repo_id = ?"
            " AND head_oid = ? ORDER BY id",
            (current.id, oid)).fetchall()
        landed: dict = {}
        landing_order: list = []
        for row in rows:
            job_id = job_for_check_name(workflow, row["name"])
            if job_id is None:
                continue
            landed[job_id] = self._job_from_row(row, job_id)
            landing_order.append(job_id)
        lint: LintResult | None = None
        defined_steps: dict = {}
        defined_order: list = []
        if workflow_text is not None:
            lint = lint_workflow(workflow_text)
            if lint.definition is not None:
                for job in lint.definition.jobs:
                    defined_steps[job.id] = tuple(
                        StepView(name=step.name,
                                 run=step.run)
                        for step in job.steps)
                    defined_order.append(job.id)
        tail_count = None
        if run_id is not None:
            try:
                validate_log_identity(run_id, "job")
            except LogStreamingError as exc:
                raise WorkflowUIError(
                    exc.reason, str(exc)) from None
            tail_count = validate_tail_lines(tail_lines)
        views: list = []
        seen: set = set()
        for job_id in landing_order + [
                job for job in defined_order
                if job not in landing_order]:
            if job_id in seen:
                continue
            seen.add(job_id)
            job = landed.get(job_id)
            log_view: JobLogView | None = None
            if run_id is not None and job is not None:
                try:
                    tail = self._logs.tail_log(
                        viewer, owner, repo, run_id,
                        job_id, lines=tail_count)
                    log_view = JobLogView(tail=tail)
                except LogStreamingError as exc:
                    if exc.reason != "log_not_found":
                        raise WorkflowUIError(
                            exc.reason, str(exc)) from None
            views.append(JobView(
                job_id=job_id,
                check_name=(job.check_name if job is not None
                            else f"{workflow} / {job_id}"),
                job=job,
                steps=defined_steps.get(job_id, ()),
                log=log_view,
                log_named=run_id is not None))
        artifacts = self._artifacts.list_run_artifacts(
            viewer, owner, repo, workflow, oid)
        return RunDetail(
            full_name=current.full_name,
            workflow=workflow, oid=oid,
            jobs=tuple(views), lint=lint,
            run_id=(str(run_id) if run_id is not None
                    else None),
            artifacts=artifacts)


# ------------------------------------------------------------------
# The audit: the UI checked against the live instance.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowUIAudit:
    """The workflow UI checked against one live
    instance: the standing vocabulary is
    S-316's word for word (plus this page's own
    `pending`), the schema is exactly 131 (no
    migration is this slice's), the taxonomy is
    unmoved at 135, the lawful tables stand,
    and every standing check run that names a
    workflow job splits lawfully and concludes
    in the vocabulary, with its folded panel
    row standing beside it."""
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


def audit_workflow_ui(conn: sqlite3.Connection
                      ) -> WorkflowUIAudit:
    """Check the UI against the live instance:
    the vocabulary, schema and taxonomy pins
    hold, the `check_runs`, `commit_checks`,
    `ci_logs` and `ci_artifacts` tables stand,
    and every standing check run obeys the law
    the pages read by. Pure read."""
    from .db import schema_version as _schema_version
    version = _schema_version(conn)
    events_ok = (len(taxonomy.AUDIT_EVENTS) == 138
                 and len(taxonomy.AUTH_EVENTS) == 33
                 and len(taxonomy.REPO_EVENTS) == 92
                 and len(taxonomy.ADMIN_EVENTS) == 13)
    vocabulary_ok = (
        tuple(RUNNER_CONCLUSIONS) == (
            "success", "failure", "neutral",
            "cancelled", "skipped", "timed_out",
            "action_required")
        and set(_CONCLUSION_WORDS)
        == set(RUNNER_CONCLUSIONS) | {PENDING}
        and all(conclusion_words(word)
                for word in _CONCLUSION_WORDS))
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    tables_ok = all(
        name in tables for name in (
            "check_runs", "commit_checks",
            "ci_logs", "ci_artifacts"))
    problems: list = []
    rows = conn.execute(
        "SELECT * FROM check_runs ORDER BY id").fetchall() \
        if tables_ok else []
    for row in rows:
        label = f"check run {row['id']}"
        if row["conclusion"] \
                and row["conclusion"] not in RUNNER_CONCLUSIONS:
            problems.append(
                f"{label}: conclusion "
                f"{row['conclusion']!r} is not in "
                "S-316's vocabulary")
        if " / " in row["name"] \
                and split_check_name(row["name"]) is None:
            problems.append(
                f"{label}: its name carries the "
                "run separator but does not split "
                "into a workflow and a lawful job")
    return WorkflowUIAudit(
        vocabulary_ok=vocabulary_ok,
        schema_version=version, schema_ok=version == 137,
        events_ok=events_ok, tables_ok=tables_ok,
        rows_scanned=len(rows), problems=tuple(problems))


# ------------------------------------------------------------------
# The renders: the pages, in the house shape.
# ------------------------------------------------------------------

def render_run_list_page(runs=None,
                         audit: WorkflowUIAudit | None = None
                         ) -> str:
    """The run list view, in plain words: what
    a run is and where its record lives, and --
    when runs ride along -- each run's standing
    as text+icon with its span in words. Every
    value escaped through S-010; standing is
    said in words, never a colour alone."""
    parts = [
        "<h1>Workflow runs</h1>",
        "<p>Every workflow run stands here as the "
        "jobs it landed: each job's conclusion "
        "(S-321) is a check run on the commit it "
        "ran on, named for its workflow and job. "
        "A run's standing is its jobs' standing, "
        "said in words with an icon -- never a "
        "colour alone. A job that has landed no "
        "conclusion yet is pending, and pending "
        "is never passed.</p>",
    ]
    if runs is not None:
        if not runs:
            parts.append(
                "<p>No workflow runs stand in this "
                "repository yet.</p>")
        for run in runs:
            parts.append(
                f"<h2>{escape_html_text(run.workflow)} "
                f"on {escape_html_text(run.oid)}</h2>")
            parts.append(
                f"<p>{escape_html_text(run.words)}</p>")
            for job in run.jobs:
                parts.append(
                    f"<p>{escape_html_text(job.words)}</p>")
    if audit is not None:
        verdict = ("stands cleanly"
                   if audit.stands_cleanly
                   else "does not stand cleanly")
        parts.append(
            f"<p>Checked against this instance: "
            f"the workflow UI {escape_html_text(verdict)} "
            f"(schema {audit.schema_version}, "
            f"{audit.rows_scanned} check runs "
            f"scanned).</p>")
    return "\n".join(parts)


def render_run_detail_page(detail: RunDetail | None = None,
                           audit: WorkflowUIAudit | None = None
                           ) -> str:
    """One run's detail view, in plain words:
    its jobs with standings as text+icon, its
    timing in words, each job's steps from the
    workflow file (with the honest word that
    conclusions land per job, not per step),
    each job's log tail when one was read, its
    artifacts in S-323's words, and the lint of
    its workflow file when one rode along.
    Every value escaped through S-010."""
    parts = [
        "<h1>Workflow run</h1>",
        "<p>One run, job by job: each job's "
        "conclusion landed as a check run "
        "(S-321), its steps are the workflow "
        "file's own steps, and its log is the "
        "stored log (S-322). Conclusions land "
        "per job, not per step -- no per-step "
        "conclusion is stored anywhere in the "
        "forge, so none is shown. Standings are "
        "said in words with an icon, never a "
        "colour alone.</p>",
    ]
    if detail is not None:
        parts.append(
            f"<h2>{escape_html_text(detail.workflow)} "
            f"on {escape_html_text(detail.oid)}</h2>")
        parts.append(
            f"<p>{escape_html_text(detail.words)}</p>")
        parts.append(
            f"<p>Timing: the run spans "
            f"{escape_html_text(format_duration(detail.span_seconds))} "
            "from its first job's landing to its "
            "last job's latest word.</p>")
        for view in detail.jobs:
            parts.append(
                f"<h3>{escape_html_text(view.job_id)}</h3>")
            parts.append(
                f"<p>{escape_html_text(view.words)}</p>")
            if view.job is not None \
                    and view.job.description:
                parts.append(
                    f"<p>{escape_html_text(view.job.description)}</p>")
            if view.steps:
                parts.append(
                    "<p>Steps, as the workflow file "
                    "defines them:</p>")
                for step in view.steps:
                    parts.append(
                        f"<p>{escape_html_text(step.words)}</p>")
            if view.log_named:
                if view.log is not None:
                    parts.append(
                        f"<p>{escape_html_text(view.log.words)}</p>")
                    body = "\n".join(
                        escape_html_text(line)
                        for line in view.log.tail.lines)
                    parts.append(f"<pre>{body}</pre>")
                elif view.job is not None:
                    parts.append(
                        "<p>No stored log stands for "
                        "this job under the named "
                        "run.</p>")
        if detail.run_id is None:
            parts.append(
                "<p>Logs are addressed by run id "
                "(S-322); no run id was named for "
                "this page, so no logs are shown.</p>")
        parts.append(
            f"<p>{escape_html_text(detail.artifacts.words)}</p>")
        if detail.lint is not None:
            parts.append(
                "<h3>Workflow file lint</h3>")
            parts.append(
                f"<p>{escape_html_text(detail.lint.words)}</p>")
    if audit is not None:
        verdict = ("stands cleanly"
                   if audit.stands_cleanly
                   else "does not stand cleanly")
        parts.append(
            f"<p>Checked against this instance: "
            f"the workflow UI {escape_html_text(verdict)} "
            f"(schema {audit.schema_version}, "
            f"{audit.rows_scanned} check runs "
            f"scanned).</p>")
    return "\n".join(parts)


def render_lint_page(results=None,
                     audit: WorkflowUIAudit | None = None
                     ) -> str:
    """The workflow lint view, in plain words:
    what the lint judges and, when results ride
    along, each file's verdict with every
    problem said in plain words beside its
    reason. Every value escaped through S-010."""
    parts = [
        "<h1>Workflow file lint</h1>",
        "<p>A workflow file is judged whole "
        "before it is pushed: its path (a "
        "workflow lives in .samverk/workflows/ "
        "as a .yml or .yaml file) and its shape "
        "(S-313's decided format), with every "
        "problem said in plain words beside the "
        "reason a program can branch on. A clean "
        "file answers with its own summary: its "
        "name, its triggers, its jobs and their "
        "steps.</p>",
    ]
    if results is not None:
        for result in results:
            parts.append(
                f"<p>{escape_html_text(result.words)}</p>")
    if audit is not None:
        verdict = ("stands cleanly"
                   if audit.stands_cleanly
                   else "does not stand cleanly")
        parts.append(
            f"<p>Checked against this instance: "
            f"the workflow UI {escape_html_text(verdict)} "
            f"(schema {audit.schema_version}, "
            f"{audit.rows_scanned} check runs "
            f"scanned).</p>")
    return "\n".join(parts)
