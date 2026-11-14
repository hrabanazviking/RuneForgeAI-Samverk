"""Jobs and steps model -- what a workflow run
is made of (S-315).

S-313 decided the workflow shape and S-314 gave
its triggers their firing law; this slice owns
what fires *into*: a workflow run decomposes
into jobs, each job is an ordered list of shell
steps on a named runner, jobs are ordered by a
needs-graph, and a job may declare a matrix that
expands it into concrete instances -- before any
runner speaks (S-316), any secret is injected
(S-319) or any check is reported (S-321).

- **Jobs and steps.** A job carries its id, an
  optional display name, its runner labels
  (S-313's ``runner:``), its ``needs``, an
  optional job-level ``timeout-minutes`` and
  ``env``, an optional ``if`` condition kept
  literal (S-313 refused the expression language;
  a condition is data here, never evaluated by
  this slice), and a non-empty ordered list of
  steps. A step is a shell ``run`` and nothing
  else -- ``uses:`` is refused by name, exactly
  as S-313 refuses it -- with an optional name,
  ``env``, ``working-directory``, ``shell`` and
  literal ``if``. Step order is document order
  and is never re-sorted: the order steps are
  written is the order they run.
- **The needs-graph.** ``needs`` names standing
  jobs only: an unknown need is refused
  (``jobs_needs_unknown``), a job needing itself
  is refused (``jobs_needs_self``), and a cycle
  is refused with the cycle named in words
  (``jobs_cycle``) -- S-313 already refused
  cycles at the document door; this slice owns
  the graph itself, so it refuses them again at
  its own door rather than trusting a caller.
  ``schedule_order`` is a deterministic
  topological order (declaration order breaks
  every tie, so the same document always plans
  the same run) and ``schedule_waves`` groups
  jobs into waves: a job's wave is one past the
  latest wave of anything it needs, so every
  job in a wave may run once the waves before
  it have finished.
- **Matrix expansion, honestly scoped.** A job
  may declare ``strategy: {matrix: {...},
  fail-fast: ...}``. The matrix is axes: each
  axis names a non-empty list of scalar values,
  and expansion is the cartesian product, axes
  in declaration order, the last axis varying
  fastest. ``exclude`` entries (partial axis
  assignments) remove the combinations they
  match. The scope is stated, not implied:
  ``include`` is NOT carried -- it is refused
  by name (``matrix_include_not_carried``)
  rather than silently ignored, because an
  include that does nothing would teach the
  author their file says something it does
  not. Matrix values are data only: no
  expression substitutes them into ``run``,
  ``runner`` or anywhere else in this slice.
  Expansion is bounded and the bounds refuse,
  never truncate: at most MAX_MATRIX_AXES
  axes, MAX_MATRIX_VALUES_PER_AXIS values per
  axis, and MAX_MATRIX_COMBINATIONS concrete
  instances from one job -- past any bound the
  whole expansion is refused
  (``matrix_too_large``) with the numbers in
  the message, because a silently shortened
  matrix is a test suite that quietly stopped
  testing what it claims. An ``exclude`` that
  removes every combination is refused too
  (``matrix_empty``): a job that expands to
  nothing is an author's mistake, not a run.
  One honest limit more: S-313's document
  validator does not admit ``strategy`` yet --
  its unknown-key refusal still fires on a
  whole document carrying one. This slice
  judges job mappings (``parse_jobs``) and
  S-313 definitions (``jobs_from_definition``,
  whose jobs carry no matrix); admitting
  ``strategy`` at the document door is a
  format change a later slice must make
  deliberately, not drift this slice smuggles
  into S-313's validator.
- **Instances and the run plan.** Expanding a
  job yields ``JobInstance`` records named in
  the familiar form ``test (linux, 3.12)`` --
  the job id, then the axis values in axis
  order. A non-matrix job expands to exactly
  one instance named by its id. In a run plan
  an instance needs *every* instance of each
  job it needs (the only reading that keeps a
  downstream job honest: it waits for the
  whole matrix, not whichever cell finished
  first). ``build_run_plan`` returns the
  instances, their deterministic scheduling
  order and their waves as one frozen plan.
- **A pure judgement, like S-313 and S-314.**
  This module holds no store, writes no row,
  audits nothing and runs nothing: planning a
  run changes nothing by being planned. No
  migration (schema stays 128), no taxonomy
  event (135 stand: 33 auth / 89 repo / 13
  admin). No workflow job, step or matrix
  table, column or audit event exists yet;
  the audit below proves that absence against
  the live instance, and the battery plants a
  workflow-jobs table to prove the audit would
  catch one arriving ahead of its slice.
  S-316 defines the runner protocol these
  plans are handed to, S-318 builds the
  runner that executes them, and S-327's UI
  renders runs in this model's words.
"""
from __future__ import annotations

import itertools
import re
import sqlite3
from dataclasses import dataclass

from . import taxonomy
from .escaping import escape_html_text
from .workflow_format import WorkflowDefinition

__all__ = [
    "JOB_KEYS", "MAX_JOBS_PER_WORKFLOW",
    "MAX_MATRIX_AXES", "MAX_MATRIX_COMBINATIONS",
    "MAX_MATRIX_VALUES_PER_AXIS",
    "MAX_STEPS_PER_JOB", "STEP_KEYS",
    "STRATEGY_KEYS", "JobDef", "JobInstance",
    "JobStep", "JobsAudit", "JobsError",
    "MatrixSpec", "RunPlan", "audit_workflow_jobs",
    "build_run_plan", "expand_job", "expand_matrix",
    "jobs_from_definition", "parse_jobs",
    "parse_matrix", "render_workflow_jobs_page",
    "schedule_order", "schedule_waves",
]

JOB_KEYS = frozenset({
    "name", "runner", "needs", "if", "env",
    "timeout-minutes", "steps", "strategy"})
STEP_KEYS = frozenset({
    "name", "run", "env", "working-directory",
    "shell", "if"})
STRATEGY_KEYS = frozenset({"matrix", "fail-fast"})
MAX_JOBS_PER_WORKFLOW = 256
MAX_STEPS_PER_JOB = 100
MAX_MATRIX_AXES = 16
MAX_MATRIX_VALUES_PER_AXIS = 64
MAX_MATRIX_COMBINATIONS = 256
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_AXIS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


class JobsError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _invalid(message: str) -> JobsError:
    return JobsError("jobs_invalid", message)


def _no_expression(value: object, where: str) -> None:
    if isinstance(value, str) and "${{" in value:
        raise JobsError(
            "jobs_expression_refused",
            f"{where}: expressions (${{{{ ... }}}}) are not "
            "part of Samverk's workflow format yet; use a "
            "literal value.")


# ------------------------------------------------------------------
# The model: steps, matrices, jobs, instances, plans.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class JobStep:
    """One shell step: the only step kind Samverk
    carries. Order within its job is run order."""
    name: str
    run: str
    env: tuple = ()
    working_directory: str = ""
    shell: str = ""
    condition: str = ""


@dataclass(frozen=True)
class MatrixSpec:
    """One declared matrix: axes in declaration
    order, each a non-empty tuple of scalar
    values, plus exclude entries as tuples of
    (axis, value) pairs in axis order."""
    axes: tuple = ()
    exclude: tuple = ()

    @property
    def combinations(self) -> int:
        total = 1
        for _name, values in self.axes:
            total *= len(values)
        return total


@dataclass(frozen=True)
class JobDef:
    """One job of a workflow: shell steps on a
    named runner, ordered by its needs."""
    id: str
    name: str
    runner: tuple
    needs: tuple
    steps: tuple
    env: tuple = ()
    timeout_minutes: int | None = None
    condition: str = ""
    matrix: MatrixSpec | None = None
    fail_fast: bool = True


@dataclass(frozen=True)
class JobInstance:
    """One concrete job a run would execute: a
    job, expanded over one matrix combination
    (empty values for a non-matrix job)."""
    id: str
    job_id: str
    name: str
    runner: tuple
    needs: tuple
    steps: tuple
    matrix_values: tuple = ()
    timeout_minutes: int | None = None


@dataclass(frozen=True)
class RunPlan:
    """A whole workflow's plan: every concrete
    instance, in deterministic scheduling order,
    grouped into waves."""
    instances: tuple
    order: tuple
    waves: tuple


# ------------------------------------------------------------------
# Parsing helpers: env, steps, matrix.
# ------------------------------------------------------------------

def _env(value: object, where: str) -> tuple:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise _invalid(f"{where}: env is a mapping of names to values.")
    out: list = []
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise _invalid(f"{where}: every env name is text.")
        if isinstance(item, (dict, list)):
            raise _invalid(f"{where}: env value for {key!r} is a scalar.")
        _no_expression(item, f"{where}: env {key}")
        out.append((key, item))
    return tuple(out)


def _steps(value: object, job_id: str) -> tuple:
    if not isinstance(value, list) or not value:
        raise _invalid(f"Job {job_id!r}: steps is a non-empty list.")
    if len(value) > MAX_STEPS_PER_JOB:
        raise JobsError(
            "jobs_too_large",
            f"Job {job_id!r}: {len(value)} steps is past the "
            f"limit of {MAX_STEPS_PER_JOB} steps per job; the "
            "job is refused whole, never truncated.")
    out: list = []
    for index, item in enumerate(value, start=1):
        where = f"Job {job_id!r} step {index}"
        if not isinstance(item, dict):
            raise _invalid(f"{where}: a step is a mapping.")
        if "uses" in item:
            raise JobsError(
                "jobs_uses_refused",
                f"{where}: uses: is not part of Samverk's format "
                "-- there are no marketplace actions; write the "
                "shell in run: instead.")
        unknown = sorted(set(item) - STEP_KEYS)
        if unknown:
            raise _invalid(
                f"{where}: unknown step key(s): "
                + ", ".join(unknown) + ".")
        run = item.get("run")
        if not isinstance(run, str) or not run.strip():
            raise _invalid(f"{where}: a step needs its run: shell.")
        _no_expression(run, where)
        name = item.get("name")
        if name is not None and not isinstance(name, str):
            raise _invalid(f"{where}: a step name is text.")
        working = item.get("working-directory")
        if working is not None and not isinstance(working, str):
            raise _invalid(f"{where}: working-directory is text.")
        shell = item.get("shell")
        if shell is not None and not isinstance(shell, str):
            raise _invalid(f"{where}: shell is text.")
        condition = item.get("if")
        if condition is not None and not isinstance(condition, str):
            raise _invalid(f"{where}: if is text.")
        if condition:
            _no_expression(condition, where)
        out.append(JobStep(
            name=name or "", run=run, env=_env(item.get("env"), where),
            working_directory=working or "", shell=shell or "",
            condition=condition or ""))
    return tuple(out)


def _scalar(value: object, where: str):
    if isinstance(value, bool) or isinstance(value, (str, int, float)):
        if isinstance(value, str):
            _no_expression(value, where)
        return value
    raise JobsError(
        "matrix_invalid",
        f"{where}: a matrix value is a scalar (text, number "
        "or boolean), never a mapping or a list.")


def parse_matrix(value: object, job_id: str) -> MatrixSpec:
    """Validate one ``matrix:`` mapping into a
    MatrixSpec. Axes keep declaration order;
    ``include`` is refused by name; ``exclude``
    entries must name standing axes and values
    the axis actually declares."""
    where = f"Job {job_id!r} matrix"
    if not isinstance(value, dict) or not value:
        raise JobsError(
            "matrix_invalid",
            f"{where}: a matrix is a non-empty mapping of "
            "axis names to value lists.")
    if "include" in value:
        raise JobsError(
            "matrix_include_not_carried",
            f"{where}: include is not carried in Samverk's "
            "matrix scope; declare full axes and remove "
            "combinations with exclude instead. An include "
            "that silently did nothing would teach the file "
            "to say something it does not.")
    axes_raw = {k: v for k, v in value.items() if k != "exclude"}
    if not axes_raw:
        raise JobsError(
            "matrix_invalid",
            f"{where}: a matrix declares at least one axis.")
    if len(axes_raw) > MAX_MATRIX_AXES:
        raise JobsError(
            "matrix_too_large",
            f"{where}: {len(axes_raw)} axes is past the limit "
            f"of {MAX_MATRIX_AXES} axes; the matrix is refused "
            "whole, never truncated.")
    axes: list = []
    seen: set = set()
    for axis, values in axes_raw.items():
        axis_where = f"{where} axis {axis!r}"
        if not isinstance(axis, str) or not _AXIS_RE.match(axis):
            raise JobsError(
                "matrix_invalid",
                f"{where}: every axis name is a plain "
                "identifier (letters, digits, '_' or '-').")
        if axis in seen:
            raise JobsError(
                "matrix_invalid",
                f"{where}: axis {axis!r} is declared twice.")
        seen.add(axis)
        if not isinstance(values, (list, tuple)) or not values:
            raise JobsError(
                "matrix_invalid",
                f"{axis_where}: an axis names a non-empty "
                "list of values.")
        if len(values) > MAX_MATRIX_VALUES_PER_AXIS:
            raise JobsError(
                "matrix_too_large",
                f"{axis_where}: {len(values)} values is past "
                f"the limit of {MAX_MATRIX_VALUES_PER_AXIS} "
                "values per axis; the matrix is refused "
                "whole, never truncated.")
        checked = tuple(
            _scalar(item, axis_where) for item in values)
        if len(set(map(repr, checked))) != len(checked):
            raise JobsError(
                "matrix_invalid",
                f"{axis_where}: a value is listed twice; "
                "each combination must be one instance.")
        axes.append((axis, checked))
    total = 1
    for _axis, values in axes:
        total *= len(values)
    if total > MAX_MATRIX_COMBINATIONS:
        raise JobsError(
            "matrix_too_large",
            f"{where}: the axes expand to {total} combinations, "
            f"past the limit of {MAX_MATRIX_COMBINATIONS} "
            "instances from one job; the matrix is refused "
            "whole, never truncated to fit.")
    exclude_raw = value.get("exclude")
    exclude: list = []
    if exclude_raw is not None:
        if not isinstance(exclude_raw, (list, tuple)):
            raise JobsError(
                "matrix_invalid",
                f"{where}: exclude is a list of partial "
                "axis assignments.")
        axis_map = dict(axes)
        for entry in exclude_raw:
            if not isinstance(entry, dict) or not entry:
                raise JobsError(
                    "matrix_invalid",
                    f"{where}: every exclude entry is a "
                    "non-empty mapping of axis names to values.")
            pairs: list = []
            for axis, item in entry.items():
                if axis not in axis_map:
                    raise JobsError(
                        "matrix_invalid",
                        f"{where}: exclude names axis {axis!r}, "
                        "which the matrix does not declare.")
                checked = _scalar(item, f"{where} exclude")
                if checked not in axis_map[axis]:
                    raise JobsError(
                        "matrix_invalid",
                        f"{where}: exclude value {checked!r} "
                        f"is not one of axis {axis!r}'s values.")
                pairs.append((axis, checked))
            order = {name: i for i, (name, _v) in enumerate(axes)}
            pairs.sort(key=lambda pair: order[pair[0]])
            exclude.append(tuple(pairs))
    return MatrixSpec(axes=tuple(axes), exclude=tuple(exclude))


def expand_matrix(spec: MatrixSpec, job_id: str) -> tuple:
    """Expand one matrix into its concrete
    combinations: a tuple of (axis, value) pair
    tuples, axes in declaration order, the last
    axis varying fastest, exclude entries
    removed. Refuses when nothing survives."""
    axes = spec.axes
    names = [name for name, _values in axes]
    combos: list = []
    for product in itertools.product(
            *(values for _name, values in axes)):
        pairs = tuple(zip(names, product))
        pair_map = dict(pairs)
        excluded = any(
            all(pair_map[axis] == item for axis, item in entry)
            for entry in spec.exclude)
        if not excluded:
            combos.append(pairs)
    if not combos:
        raise JobsError(
            "matrix_empty",
            f"Job {job_id!r}: the matrix's exclude entries "
            "remove every combination; a job that expands "
            "to nothing is refused, not planned as an "
            "empty success.")
    return tuple(combos)


# ------------------------------------------------------------------
# Parsing jobs: the S-315 door over job mappings.
# ------------------------------------------------------------------

def _strategy(spec: dict, job_id: str):
    raw = spec.get("strategy")
    if raw is None:
        return None, True
    if not isinstance(raw, dict) or not raw:
        raise _invalid(f"Job {job_id!r}: strategy is a mapping.")
    unknown = sorted(set(raw) - STRATEGY_KEYS)
    if unknown:
        raise _invalid(
            f"Job {job_id!r}: unknown strategy key(s): "
            + ", ".join(unknown)
            + ". Samverk's strategy carries: matrix, fail-fast.")
    if "matrix" not in raw:
        raise _invalid(
            f"Job {job_id!r}: strategy names its matrix:.")
    fail_fast = raw.get("fail-fast", True)
    if not isinstance(fail_fast, bool):
        raise _invalid(
            f"Job {job_id!r}: fail-fast is a boolean.")
    return parse_matrix(raw["matrix"], job_id), fail_fast


def parse_jobs(jobs_value: object) -> tuple:
    """Judge a workflow's ``jobs:`` mapping into
    JobDefs, in declaration order: every job's
    shape, every step, every matrix, and the
    whole needs-graph (standing needs, no
    self-need, no cycle). Pure."""
    if not isinstance(jobs_value, dict) or not jobs_value:
        raise _invalid("jobs: is a non-empty mapping of job ids.")
    if len(jobs_value) > MAX_JOBS_PER_WORKFLOW:
        raise JobsError(
            "jobs_too_large",
            f"jobs: {len(jobs_value)} jobs is past the limit "
            f"of {MAX_JOBS_PER_WORKFLOW} jobs in one workflow; "
            "the workflow is refused whole, never truncated.")
    out: list = []
    for job_id, spec in jobs_value.items():
        if not isinstance(job_id, str) or not _NAME_RE.match(job_id):
            raise _invalid(f"Job id {job_id!r} is not a valid job id.")
        if not isinstance(spec, dict):
            raise _invalid(f"Job {job_id!r}: a job is a mapping.")
        if "uses" in spec:
            raise JobsError(
                "jobs_uses_refused",
                f"Job {job_id!r}: reusable-workflow uses: is not "
                "part of Samverk's format.")
        unknown = sorted(set(spec) - JOB_KEYS)
        if unknown:
            raise _invalid(
                f"Job {job_id!r}: unknown job key(s): "
                + ", ".join(unknown)
                + ". (runs-on: is runner: in Samverk's shape.)")
        runner_raw = spec.get("runner")
        if isinstance(runner_raw, str) and runner_raw.strip():
            runner = (runner_raw.strip(),)
        elif (isinstance(runner_raw, list) and runner_raw
              and all(isinstance(x, str) and x.strip()
                      for x in runner_raw)):
            runner = tuple(x.strip() for x in runner_raw)
        else:
            raise _invalid(
                f"Job {job_id!r}: runner: names one runner label "
                "or a non-empty list of labels.")
        needs_raw = spec.get("needs")
        if needs_raw is None:
            needs: tuple = ()
        elif isinstance(needs_raw, str):
            needs = (needs_raw,)
        elif (isinstance(needs_raw, list)
              and all(isinstance(x, str) for x in needs_raw)):
            needs = tuple(needs_raw)
        else:
            raise _invalid(
                f"Job {job_id!r}: needs: is one job id or a list.")
        if len(set(needs)) != len(needs):
            raise _invalid(
                f"Job {job_id!r}: needs names a job twice.")
        timeout = spec.get("timeout-minutes")
        if timeout is not None and (
                not isinstance(timeout, int)
                or isinstance(timeout, bool) or timeout <= 0):
            raise _invalid(
                f"Job {job_id!r}: timeout-minutes is a positive "
                "whole number.")
        name = spec.get("name")
        if name is not None and not isinstance(name, str):
            raise _invalid(f"Job {job_id!r}: a job name is text.")
        condition = spec.get("if")
        if condition is not None and not isinstance(condition, str):
            raise _invalid(f"Job {job_id!r}: if is text.")
        if condition:
            _no_expression(condition, f"Job {job_id!r}")
        matrix, fail_fast = _strategy(spec, job_id)
        out.append(JobDef(
            id=job_id, name=name or "", runner=runner,
            needs=needs, steps=_steps(spec.get("steps"), job_id),
            env=_env(spec.get("env"), f"Job {job_id!r}"),
            timeout_minutes=timeout, condition=condition or "",
            matrix=matrix, fail_fast=fail_fast))
    _check_graph(tuple(out))
    return tuple(out)


def jobs_from_definition(
        definition: WorkflowDefinition) -> tuple:
    """Lift an S-313 WorkflowDefinition's jobs
    into JobDefs. S-313's shape carries no
    matrix, so every job here expands to exactly
    one instance; the graph is re-checked at
    this slice's own door."""
    out: list = []
    for job in definition.jobs:
        steps = tuple(
            JobStep(name=step.name, run=step.run)
            for step in job.steps)
        out.append(JobDef(
            id=job.id, name=job.name, runner=tuple(job.runner),
            needs=tuple(job.needs), steps=steps))
    jobs = tuple(out)
    _check_graph(jobs)
    return jobs


# ------------------------------------------------------------------
# The needs-graph: checking, ordering, waves.
# ------------------------------------------------------------------

def _check_graph(jobs: tuple) -> None:
    known = {job.id for job in jobs}
    for job in jobs:
        for need in job.needs:
            if need == job.id:
                raise JobsError(
                    "jobs_needs_self",
                    f"Job {job.id!r}: a job cannot need itself.")
            if need not in known:
                raise JobsError(
                    "jobs_needs_unknown",
                    f"Job {job.id!r}: needs unknown job {need!r}.")
    graph = {job.id: job.needs for job in jobs}
    state: dict = {}

    def visit(node: str, trail: list) -> None:
        state[node] = 1
        for nxt in graph[node]:
            if state.get(nxt) == 1:
                raise JobsError(
                    "jobs_cycle",
                    "jobs: the needs graph cycles through "
                    + " -> ".join(trail + [node, nxt]) + ".")
            if state.get(nxt, 0) == 0:
                visit(nxt, trail + [node])
        state[node] = 2

    for job in jobs:
        if state.get(job.id, 0) == 0:
            visit(job.id, [])


def _topo_order(ids: tuple, needs_map: dict) -> tuple:
    """Deterministic topological order over
    ``ids``: at each step the earliest-declared
    id whose needs are all placed is placed."""
    placed: list = []
    placed_set: set = set()
    remaining = list(ids)
    while remaining:
        for candidate in remaining:
            if all(need in placed_set
                   for need in needs_map[candidate]):
                placed.append(candidate)
                placed_set.add(candidate)
                remaining.remove(candidate)
                break
        else:
            raise JobsError(
                "jobs_cycle",
                "jobs: the needs graph cycles through "
                + ", ".join(remaining) + ".")
    return tuple(placed)


def _waves(ids: tuple, needs_map: dict,
           order: tuple) -> tuple:
    level: dict = {}
    for node in order:
        needs = needs_map[node]
        level[node] = (
            0 if not needs
            else 1 + max(level[need] for need in needs))
    if not level:
        return ()
    waves: list = [[] for _ in range(max(level.values()) + 1)]
    for node in ids:
        waves[level[node]].append(node)
    return tuple(tuple(wave) for wave in waves)


def schedule_order(jobs: tuple) -> tuple:
    """The jobs' ids in deterministic scheduling
    order: every job after everything it needs,
    declaration order breaking ties."""
    jobs = tuple(jobs)
    _check_graph(jobs)
    needs_map = {job.id: job.needs for job in jobs}
    return _topo_order(
        tuple(job.id for job in jobs), needs_map)


def schedule_waves(jobs: tuple) -> tuple:
    """The jobs grouped into waves: wave 0 needs
    nothing; every later job sits one wave past
    the latest wave of its needs. Ids keep
    declaration order inside a wave."""
    jobs = tuple(jobs)
    _check_graph(jobs)
    needs_map = {job.id: job.needs for job in jobs}
    order = _topo_order(tuple(job.id for job in jobs), needs_map)
    return _waves(tuple(job.id for job in jobs), needs_map, order)


# ------------------------------------------------------------------
# Expansion and the run plan.
# ------------------------------------------------------------------

def expand_job(job: JobDef) -> tuple:
    """Expand one job into its concrete
    instances: one for a non-matrix job, one
    per surviving matrix combination for a
    matrix job, in expansion order."""
    if job.matrix is None:
        return (JobInstance(
            id=job.id, job_id=job.id, name=job.name,
            runner=job.runner, needs=job.needs,
            steps=job.steps, matrix_values=(),
            timeout_minutes=job.timeout_minutes),)
    out: list = []
    for pairs in expand_matrix(job.matrix, job.id):
        label = ", ".join(str(value) for _axis, value in pairs)
        out.append(JobInstance(
            id=f"{job.id} ({label})", job_id=job.id,
            name=job.name, runner=job.runner, needs=job.needs,
            steps=job.steps, matrix_values=pairs,
            timeout_minutes=job.timeout_minutes))
    return tuple(out)


def build_run_plan(jobs: tuple) -> RunPlan:
    """Plan a whole workflow: expand every job,
    wire instance needs to *every* instance of
    each needed job, and return the instances
    with their scheduling order and waves."""
    jobs = tuple(jobs)
    _check_graph(jobs)
    by_job: dict = {}
    instances: list = []
    for job in jobs:
        expanded = expand_job(job)
        by_job[job.id] = expanded
        instances.extend(expanded)
    wired: list = []
    for instance in instances:
        needs: list = []
        for need_job in instance.needs:
            needs.extend(inst.id for inst in by_job[need_job])
        wired.append(JobInstance(
            id=instance.id, job_id=instance.job_id,
            name=instance.name, runner=instance.runner,
            needs=tuple(needs), steps=instance.steps,
            matrix_values=instance.matrix_values,
            timeout_minutes=instance.timeout_minutes))
    wired_tuple = tuple(wired)
    needs_map = {inst.id: inst.needs for inst in wired_tuple}
    ids = tuple(inst.id for inst in wired_tuple)
    order = _topo_order(ids, needs_map)
    return RunPlan(
        instances=wired_tuple, order=order,
        waves=_waves(ids, needs_map, order))


# ------------------------------------------------------------------
# The audit: the model checked against the live instance.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class JobsAudit:
    """The jobs-and-steps model checked against
    one live instance: the limits' own sanity,
    how much schema was inspected, and every
    workflow job/step/matrix-shaped name found
    in it. The model stands cleanly only while
    no table, column or audit event carries one
    -- the runner slices mint theirs when they
    land."""
    limits_ok: bool
    tables_scanned: int
    columns_scanned: int
    events_scanned: int
    offending_tables: tuple
    offending_columns: tuple
    offending_events: tuple

    @property
    def stands_cleanly(self) -> bool:
        return (self.limits_ok
                and not self.offending_tables
                and not self.offending_columns
                and not self.offending_events)


_WORDS = ("job", "step", "matrix")


def _workflow_surface(name: str) -> bool:
    text = name.lower()
    return "workflow" in text and any(
        word in text for word in _WORDS)


def audit_workflow_jobs(conn: sqlite3.Connection) -> JobsAudit:
    """Check the model against the live instance:
    the expansion limits are positive and
    ordered, and no table, column or audit event
    carries a workflow job, step or matrix
    surface -- one arriving ahead of its slice
    would be the model broken by a back door.
    Pure read."""
    limits_ok = (
        0 < MAX_MATRIX_AXES
        and 0 < MAX_MATRIX_VALUES_PER_AXIS
        and 0 < MAX_MATRIX_COMBINATIONS
        and 0 < MAX_JOBS_PER_WORKFLOW
        and 0 < MAX_STEPS_PER_JOB)
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    offending_tables: list = []
    offending_columns: list = []
    columns_scanned = 0
    for table in tables:
        if _workflow_surface(table):
            offending_tables.append(table)
        safe = table.replace('"', '""')
        for row in conn.execute(
                f'PRAGMA table_info("{safe}")').fetchall():
            columns_scanned += 1
            if _workflow_surface(str(row[1])):
                offending_columns.append(f"{table}.{row[1]}")
    events = sorted(taxonomy.AUDIT_EVENTS)
    offending_events = [
        e for e in events if _workflow_surface(e)]
    return JobsAudit(
        limits_ok=limits_ok,
        tables_scanned=len(tables),
        columns_scanned=columns_scanned,
        events_scanned=len(events),
        offending_tables=tuple(offending_tables),
        offending_columns=tuple(offending_columns),
        offending_events=tuple(offending_events))


def render_workflow_jobs_page(
        audit: JobsAudit | None = None) -> str:
    """The jobs-and-steps model, rendered: jobs
    of shell steps on a runner, the needs-graph
    and its waves, and the matrix scope stated
    with its limits -- every value escaped, the
    state said in words, never colour-only."""
    parts = [
        "<h1>Workflow jobs and steps (S-315)</h1>",
        "<p>A workflow run is <strong>jobs</strong>: "
        "each job is an ordered list of shell "
        "<strong>steps</strong> on a named runner. "
        "Jobs order themselves by a "
        "<strong>needs-graph</strong> -- a job runs "
        "only after everything it needs, grouped "
        "into waves -- and needs must name standing "
        "jobs and never cycle.</p>",
        "<h2>Matrix, honestly scoped</h2>",
        f"<p>A job may declare a matrix of axes; "
        f"expansion is the cartesian product, at "
        f"most {MAX_MATRIX_AXES} axes, "
        f"{MAX_MATRIX_VALUES_PER_AXIS} values per "
        f"axis and {MAX_MATRIX_COMBINATIONS} "
        "instances from one job. Past a limit the "
        "expansion is refused whole, never "
        "truncated. <strong>exclude</strong> "
        "removes combinations; "
        "<strong>include</strong> is not carried "
        "and is refused by name. Matrix values "
        "are data only -- no expression "
        "substitutes them anywhere in this "
        "slice.</p>",
    ]
    if audit is not None:
        state = ("stands cleanly" if audit.stands_cleanly
                 else "does NOT stand cleanly")
        parts.append("<h2>Checked against this instance</h2>")
        parts.append(
            f"<p>The jobs model {escape_html_text(state)}: "
            f"{audit.tables_scanned} tables and "
            f"{audit.columns_scanned} columns scanned, "
            f"{audit.events_scanned} audit events scanned; "
            f"offending tables: "
            f"{escape_html_text(', '.join(audit.offending_tables) or 'none')}; "
            f"offending columns: "
            f"{escape_html_text(', '.join(audit.offending_columns) or 'none')}; "
            f"offending events: "
            f"{escape_html_text(', '.join(audit.offending_events) or 'none')}.</p>")
    return "\n".join(parts)
