"""Workflow format decision -- Samverk's own YAML
shape, adopted (S-313).

Part XVI opens here. Research file 25's study
separates the two products a forge's CI holds:
workflows defined by repository code, and
independent runners executing jobs -- Samverk
defines workflows and talks to runners; it does
not pretend a runner is a forge feature. This
slice is the format decision every later Part XVI
slice builds under, as a complete slice: the
shape is data, the mapping from the GitHub shape
people already know is recorded field by field,
the deliberate differences are stated as
differences (never silent drift), and a pure
validator judges a workflow document against the
decided shape today -- before any trigger fires
(S-314), any job runs (S-315) or any runner
exists (S-316/S-318).

- **The decision is ADOPT our own shape.**
  Workflows live in ``.samverk/workflows/`` as
  ``*.yml`` / ``*.yaml`` files, one workflow per
  file. The structure is GitHub-familiar on
  purpose -- ``name``, ``on``, ``jobs``, steps
  with ``run`` -- because authors arrive knowing
  that shape and familiarity is a feature; the
  format is documented as ours because the
  directory, the vocabulary and the refusals are
  Samverk's own, and a file copied unchanged from
  a GitHub repository is NOT promised to run:
  ``MAPPINGS`` says what carries over, what is
  renamed and what is not carried at all, and
  ``DIFFERENCES`` states each deliberate break.
- **The sharpest differences, up front.** No
  marketplace actions: a step is a shell ``run``
  and nothing else in this format -- ``uses:`` is
  refused by name (``workflow_uses_refused``),
  because arbitrary third-party action code is
  exactly the untrusted-code surface research 25
  warns about, and Samverk's runner contract
  (S-316) speaks jobs of shell steps (S-315). No
  expression language yet: ``${{ ... }}`` is
  refused (``workflow_expression_refused``)
  rather than half-honoured; values are literal
  until a later slice designs expressions with
  their governance. A job names its runner by
  labels (``runner:``), never by a vendor image
  name (``runs-on:`` is the mapping's one
  rename). And ``on`` is a word, never a boolean:
  YAML 1.1 parsers famously read the bare key
  ``on`` as ``true``; Samverk's parser (the
  standing YAML subset of S-162's issue forms,
  reused whole) keeps keys as text, and the
  validator refuses a boolean trigger key loudly
  instead of silently losing the workflow.
- **A pure judgement, like S-253, S-264 and
  S-282.** This module holds no store, writes no
  row and audits nothing: deciding a file format
  changes nothing by being read. Parsing reuses
  ``samverk.issue_templates.parse_yaml_subset``
  -- Samverk is stdlib-first (S-017) and admits no
  YAML dependency for a second parser. No
  migration (schema stays 128), no taxonomy
  event (135 stand: 33 auth / 89 repo / 13
  admin). No table, route or runner exists yet;
  the audit below proves that absence against the
  live instance, and the battery plants a
  workflow-shaped table to prove the audit would
  catch one arriving ahead of its slice. The full
  reasoning also lives in docs/WORKFLOW_FORMAT.md,
  where a person who never opens this module can
  read it -- the study file the roadmap asks for.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from . import taxonomy
from .escaping import escape_html_text
from .issue_templates import TemplateError, parse_yaml_subset

__all__ = [
    "DECISION", "DIFFERENCES", "GITHUB_DIRECTORY",
    "MAPPINGS", "MUST_NOT_BREAK", "TOP_LEVEL_KEYS",
    "TRIGGER_EVENTS", "WORKFLOW_DIRECTORY",
    "DeliberateDifference", "FieldMapping",
    "VerdictInvariant", "WorkflowAudit",
    "WorkflowDefinition", "WorkflowFormatError",
    "WorkflowJob", "WorkflowStep",
    "audit_workflow_format", "discover_workflows",
    "get_difference", "get_invariant", "get_mapping",
    "is_github_workflow_path", "is_workflow_path",
    "parse_workflow", "render_workflow_format_page",
    "validate_workflow",
]

DECISION = "adopted"
WORKFLOW_DIRECTORY = ".samverk/workflows"
GITHUB_DIRECTORY = ".github/workflows"
FILE_EXTENSIONS = (".yml", ".yaml")

TOP_LEVEL_KEYS = frozenset({
    "name", "on", "env", "permissions",
    "concurrency", "jobs"})
JOB_KEYS = frozenset({
    "name", "runner", "needs", "if", "env",
    "timeout-minutes", "steps"})
STEP_KEYS = frozenset({
    "name", "run", "env", "working-directory",
    "shell", "if"})
# The trigger vocabulary S-313 names; S-314 owns
# each trigger's semantics and firing law.
TRIGGER_EVENTS = (
    "push", "pull_request", "tag", "schedule",
    "workflow_dispatch")
PERMISSION_VALUES = frozenset({"read", "write", "none"})
PERMISSION_SHORTHANDS = frozenset({
    "read-all", "write-all", "none"})
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class WorkflowFormatError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _invalid(message: str) -> WorkflowFormatError:
    return WorkflowFormatError("workflow_invalid", message)


@dataclass(frozen=True)
class FieldMapping:
    """One row of the GitHub-to-Samverk mapping:
    the GitHub field, the Samverk field (empty
    when nothing carries over), the relation --
    ``same``, ``renamed``, ``ours`` (Samverk-only)
    or ``not-carried`` -- and the note a migrating
    author needs."""
    id: str
    github: str
    samverk: str
    relation: str
    note: str


MAPPINGS: tuple[FieldMapping, ...] = (
    FieldMapping(
        id="location", github=".github/workflows/",
        samverk=".samverk/workflows/", relation="renamed",
        note=("The directory is ours. A workflow file "
              "moves, unchanged in name; Samverk never "
              "reads the GitHub directory, so the two "
              "forges never fight over one file.")),
    FieldMapping(
        id="name", github="name", samverk="name",
        relation="same",
        note=("The workflow's display name, optional "
              "in both shapes; the file stem names the "
              "workflow when it is absent.")),
    FieldMapping(
        id="triggers", github="on", samverk="on",
        relation="same",
        note=("Same word, same place. Samverk keeps the "
              "key as text -- never the YAML 1.1 boolean "
              "``true`` -- and S-314 owns what each "
              "trigger does.")),
    FieldMapping(
        id="jobs", github="jobs", samverk="jobs",
        relation="same",
        note=("Jobs keyed by job id in both shapes. "
              "S-315 owns the jobs-and-steps model "
              "this key holds.")),
    FieldMapping(
        id="runs-on", github="runs-on", samverk="runner",
        relation="renamed",
        note=("GitHub names a hosted image; Samverk "
              "names runner labels (S-317), because a "
              "village instance's runners are its own "
              "machines, not a vendor catalogue. One "
              "label or a list of labels.")),
    FieldMapping(
        id="needs", github="needs", samverk="needs",
        relation="same",
        note=("The needs-graph between jobs, one id or "
              "a list; it must name standing jobs and "
              "never cycle (S-315 expands it)."),
    ),
    FieldMapping(
        id="steps-run", github="steps[].run",
        samverk="steps[].run", relation="same",
        note=("A shell step is a shell step: the one "
              "step kind Samverk's format carries.")),
    FieldMapping(
        id="steps-uses", github="steps[].uses",
        samverk="", relation="not-carried",
        note=("Marketplace actions are not carried. A "
              "step that would ``uses:`` an action is "
              "refused by name; write the shell the "
              "action would have run.")),
    FieldMapping(
        id="env", github="env", samverk="env",
        relation="same",
        note=("Literal name/value pairs at workflow, "
              "job and step level. No expression "
              "language evaluates them yet.")),
    FieldMapping(
        id="permissions", github="permissions",
        samverk="permissions", relation="same",
        note=("Same vocabulary (read / write / none, "
              "read-all / write-all), stricter default: "
              "an undeclared workflow runs read-only. "
              "S-320 tightens fork workflows further, "
              "in the scheduler.")),
    FieldMapping(
        id="concurrency", github="concurrency",
        samverk="concurrency", relation="same",
        note=("A group name, or a mapping with a "
              "``group``; queueing semantics land with "
              "the scheduler slices.")),
    FieldMapping(
        id="expressions", github="${{ ... }}",
        samverk="", relation="not-carried",
        note=("The expression language is not carried "
              "in this format. ``${{`` in a workflow is "
              "refused, never half-evaluated; contexts "
              "and secrets arrive only as the slices "
              "that govern them land (S-319)."),
    ),
    FieldMapping(
        id="matrix", github="strategy.matrix",
        samverk="", relation="not-carried",
        note=("Matrix expansion is S-315's to scope "
              "honestly; this format does not carry "
              "``strategy`` yet, and an unknown key is "
              "refused rather than ignored.")),
)


@dataclass(frozen=True)
class DeliberateDifference:
    """One deliberate difference from the GitHub
    shape: a stable id, the plain title, and the
    difference stated with its reason."""
    id: str
    title: str
    detail: str


DIFFERENCES: tuple[DeliberateDifference, ...] = (
    DeliberateDifference(
        id="ours-directory",
        title="The directory is .samverk/workflows/",
        detail=("Samverk reads only its own directory. "
                "A repository may carry both directories "
                "while it migrates; neither forge "
                "executes the other's files, and no "
                "file is ever read from both.")),
    DeliberateDifference(
        id="no-marketplace-actions",
        title="No uses: -- steps are shell, only",
        detail=("Research 25 names arbitrary workflow "
                "code as intentionally untrusted. A "
                "marketplace action is third-party code "
                "fetched by name at run time; Samverk's "
                "format carries the shell itself instead, "
                "so what runs is what the repository "
                "says, reviewable in the same diff.")),
    DeliberateDifference(
        id="runner-labels-not-images",
        title="runner: labels, not runs-on: images",
        detail=("A village instance schedules onto "
                "runners its own people registered "
                "(S-317), matched by labels. There is "
                "no hosted-image catalogue to name, so "
                "the format does not pretend one.")),
    DeliberateDifference(
        id="on-is-a-word",
        title="on is a word, never a boolean",
        detail=("YAML 1.1 reads the bare word ``on`` "
                "as boolean true; more than one "
                "workflow has vanished that way. "
                "Samverk's parser keeps mapping keys "
                "as text, and the validator refuses a "
                "boolean trigger key with the reason "
                "stated, instead of losing the file.")),
    DeliberateDifference(
        id="no-expression-language-yet",
        title="No ${{ }} expression language yet",
        detail=("Expressions mix data, secrets and "
                "control flow in one stringly syntax. "
                "This format keeps values literal and "
                "refuses ``${{`` outright; if expressions "
                "are designed later, they arrive with "
                "their own governance, not by drift.")),
    DeliberateDifference(
        id="read-by-default",
        title="Permissions default to read-only",
        detail=("An undeclared ``permissions:`` means "
                "read-only, stated here so S-314's "
                "scheduler and S-320's fork rule inherit "
                "the strict reading, not the permissive "
                "one.")),
    DeliberateDifference(
        id="unknown-keys-refused",
        title="Unknown keys are refused, never ignored",
        detail=("A misspelled or not-yet-carried key "
                "(``strategy``, ``defaults``, a typo'd "
                "``runs-on``) fails validation in plain "
                "words. A format that ignores what it "
                "does not know teaches authors their "
                "file says something it does not.")),
)


@dataclass(frozen=True)
class VerdictInvariant:
    """One thing the Part XVI build must not
    break, recorded now while stating it is cheap:
    a stable id, the title, and the invariant."""
    id: str
    title: str
    statement: str


MUST_NOT_BREAK: tuple[VerdictInvariant, ...] = (
    VerdictInvariant(
        id="runner-is-not-the-forge",
        title="A runner is not a forge feature",
        statement=("Samverk defines workflows and "
                   "speaks the runner protocol (S-316); "
                   "execution happens on registered "
                   "runners (S-317/S-318), never inside "
                   "the forge process serving web "
                   "traffic.")),
    VerdictInvariant(
        id="no-docker-anywhere",
        title="No Docker, anywhere in Part XVI",
        statement=("The reference runner (S-318) is a "
                   "small native program executing in a "
                   "working directory. No slice in this "
                   "part may make a workflow depend on a "
                   "container runtime.")),
    VerdictInvariant(
        id="fork-safety-in-the-scheduler",
        title="Fork safety lives in the scheduler",
        statement=("Workflows from fork pull requests "
                   "run with no secrets and read-only "
                   "tokens by default (S-320) -- enforced "
                   "where jobs are scheduled, not merely "
                   "written in documentation.")),
    VerdictInvariant(
        id="secrets-masked-and-scoped",
        title="Secrets are scoped, injected, masked",
        statement=("CI secrets (S-319) are encrypted "
                   "at rest, injected as environment "
                   "only to authorised jobs, and masked "
                   "in logs by S-018's filter. A workflow "
                   "file never carries a secret value.")),
    VerdictInvariant(
        id="checks-bound-to-the-commit",
        title="Checks bind to the commit that ran",
        statement=("Job conclusions land as check runs "
                   "(S-321) on the exact commit; a stale "
                   "green never satisfies a new head, and "
                   "required checks (S-174) gate on the "
                   "current head only.")),
    VerdictInvariant(
        id="skipped-is-not-passed",
        title="Skipped is never passed",
        statement=("Skip markers (S-325) suppress a "
                   "run; a required check treats the "
                   "skipped workflow as not passed, "
                   "never as passed -- the known trap, "
                   "named here before the scheduler "
                   "exists.")),
    VerdictInvariant(
        id="schedule-on-default-branch",
        title="Schedules read the default branch only",
        statement=("A cron trigger (S-326) is read "
                   "from the default branch's workflow "
                   "files; a branch cannot schedule "
                   "itself into existence.")),
    VerdictInvariant(
        id="every-action-audited",
        title="Run actions are audit-logged",
        statement=("Re-run and cancel (S-324) and "
                   "every later run-changing act are "
                   "witnessed in the audit chain; a "
                   "workflow run's history is never "
                   "silent. When those slices land they "
                   "mint their events then -- this slice "
                   "mints none.")),
)


def get_mapping(mapping_id: object) -> FieldMapping:
    for mapping in MAPPINGS:
        if mapping.id == mapping_id:
            return mapping
    raise WorkflowFormatError(
        "mapping_unknown", "No such mapping row is stated.")


def get_difference(diff_id: object) -> DeliberateDifference:
    for difference in DIFFERENCES:
        if difference.id == diff_id:
            return difference
    raise WorkflowFormatError(
        "difference_unknown",
        "No such deliberate difference is recorded.")


def get_invariant(invariant_id: object) -> VerdictInvariant:
    for invariant in MUST_NOT_BREAK:
        if invariant.id == invariant_id:
            return invariant
    raise WorkflowFormatError(
        "invariant_unknown", "No such invariant is recorded.")


# ------------------------------------------------------------------
# Paths: which repository paths are workflow files.
# ------------------------------------------------------------------

def _normalise(path: object) -> str:
    if not isinstance(path, str):
        return ""
    text = path.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _workflow_stem(path: str, directory: str) -> str | None:
    prefix = directory + "/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix):]
    if "/" in rest:
        return None
    for ext in FILE_EXTENSIONS:
        if rest.endswith(ext):
            stem = rest[:-len(ext)]
            return stem if _NAME_RE.match(stem) else None
    return None


def is_workflow_path(path: object) -> bool:
    """True only for ``.samverk/workflows/<name>.yml``
    (or ``.yaml``), exactly one level deep, with a
    file stem of letters, digits, '.', '_' or '-'."""
    return _workflow_stem(_normalise(path), WORKFLOW_DIRECTORY) is not None


def is_github_workflow_path(path: object) -> bool:
    """True for the GitHub directory's shape -- named
    so a migration tool can find what would move."""
    return _workflow_stem(_normalise(path), GITHUB_DIRECTORY) is not None


def discover_workflows(paths) -> tuple[str, ...]:
    """The workflow paths among ``paths``, sorted:
    exactly the files Samverk would read as
    workflows, nothing from the GitHub directory."""
    try:
        items = list(paths)
    except TypeError:
        raise _invalid("Workflow discovery needs a list of paths.")
    found = {_normalise(p) for p in items if is_workflow_path(p)}
    return tuple(sorted(found))


# ------------------------------------------------------------------
# The validator: parsed YAML -> WorkflowDefinition.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowStep:
    name: str
    run: str


@dataclass(frozen=True)
class WorkflowJob:
    id: str
    name: str
    runner: tuple[str, ...]
    needs: tuple[str, ...]
    steps: tuple[WorkflowStep, ...]


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    triggers: tuple[str, ...]
    jobs: tuple[WorkflowJob, ...]


def _no_expression(value: object, where: str) -> None:
    if isinstance(value, str) and "${{" in value:
        raise WorkflowFormatError(
            "workflow_expression_refused",
            f"{where}: expressions (${{{{ ... }}}}) are not "
            "part of Samverk's workflow format yet; use a "
            "literal value.")


def _env(value: object, where: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise _invalid(f"{where}: env is a mapping of names to values.")
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise _invalid(f"{where}: every env name is text.")
        if isinstance(item, (dict, list)):
            raise _invalid(f"{where}: env value for {key!r} is a scalar.")
        _no_expression(item, f"{where}: env {key}")


def _triggers(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        events = [value]
    elif isinstance(value, list):
        events = value
    elif isinstance(value, dict):
        events = list(value.keys())
        for event, config in value.items():
            if config is not None and not isinstance(config, (dict, list)):
                raise _invalid(
                    f"Trigger {event!r}: its configuration is a mapping.")
    else:
        raise _invalid(
            "on: names one trigger, a list of triggers, or a "
            "mapping of triggers to their configuration.")
    out: list[str] = []
    for event in events:
        if not isinstance(event, str) or event not in TRIGGER_EVENTS:
            raise _invalid(
                "on: a trigger is one of: "
                + ", ".join(TRIGGER_EVENTS) + ".")
        if event not in out:
            out.append(event)
    if not out:
        raise _invalid("on: at least one trigger is required.")
    return tuple(out)


def _permissions(value: object) -> None:
    if value is None:
        return
    if isinstance(value, str):
        if value not in PERMISSION_SHORTHANDS:
            raise _invalid(
                "permissions: is read-all, write-all, none, or a "
                "mapping of scopes to read / write / none.")
        return
    if not isinstance(value, dict):
        raise _invalid("permissions: is a shorthand or a mapping.")
    for scope, level in value.items():
        if level not in PERMISSION_VALUES:
            raise _invalid(
                f"permissions: scope {scope!r} is read, write or none.")


def _steps(value: object, job_id: str) -> tuple[WorkflowStep, ...]:
    if not isinstance(value, list) or not value:
        raise _invalid(f"Job {job_id!r}: steps is a non-empty list.")
    out: list[WorkflowStep] = []
    for index, item in enumerate(value, start=1):
        where = f"Job {job_id!r} step {index}"
        if not isinstance(item, dict):
            raise _invalid(f"{where}: a step is a mapping.")
        if "uses" in item:
            raise WorkflowFormatError(
                "workflow_uses_refused",
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
        _env(item.get("env"), where)
        name = item.get("name")
        if name is not None and not isinstance(name, str):
            raise _invalid(f"{where}: a step name is text.")
        out.append(WorkflowStep(name=name or "", run=run))
    return tuple(out)


def _jobs(value: object) -> tuple[WorkflowJob, ...]:
    if not isinstance(value, dict) or not value:
        raise _invalid("jobs: is a non-empty mapping of job ids.")
    out: list[WorkflowJob] = []
    for job_id, spec in value.items():
        if not isinstance(job_id, str) or not _NAME_RE.match(job_id):
            raise _invalid(f"Job id {job_id!r} is not a valid job id.")
        if not isinstance(spec, dict):
            raise _invalid(f"Job {job_id!r}: a job is a mapping.")
        if "uses" in spec:
            raise WorkflowFormatError(
                "workflow_uses_refused",
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
            needs: tuple[str, ...] = ()
        elif isinstance(needs_raw, str):
            needs = (needs_raw,)
        elif (isinstance(needs_raw, list)
              and all(isinstance(x, str) for x in needs_raw)):
            needs = tuple(needs_raw)
        else:
            raise _invalid(
                f"Job {job_id!r}: needs: is one job id or a list.")
        timeout = spec.get("timeout-minutes")
        if timeout is not None and (
                not isinstance(timeout, int)
                or isinstance(timeout, bool) or timeout <= 0):
            raise _invalid(
                f"Job {job_id!r}: timeout-minutes is a positive "
                "whole number.")
        _env(spec.get("env"), f"Job {job_id!r}")
        name = spec.get("name")
        if name is not None and not isinstance(name, str):
            raise _invalid(f"Job {job_id!r}: a job name is text.")
        out.append(WorkflowJob(
            id=job_id, name=name or "", runner=runner,
            needs=needs, steps=_steps(spec.get("steps"), job_id)))
    known = {job.id for job in out}
    for job in out:
        for need in job.needs:
            if need == job.id:
                raise _invalid(f"Job {job.id!r}: a job cannot need itself.")
            if need not in known:
                raise _invalid(
                    f"Job {job.id!r}: needs unknown job {need!r}.")
    # Cycle check over the needs graph (iterative DFS).
    graph = {job.id: job.needs for job in out}
    state: dict[str, int] = {}
    def visit(node: str, trail: list[str]) -> None:
        state[node] = 1
        for nxt in graph[node]:
            if state.get(nxt) == 1:
                raise _invalid(
                    "jobs: the needs graph cycles through "
                    + " -> ".join(trail + [node, nxt]) + ".")
            if state.get(nxt, 0) == 0:
                visit(nxt, trail + [node])
        state[node] = 2
    for job in out:
        if state.get(job.id, 0) == 0:
            visit(job.id, [])
    return tuple(out)


def validate_workflow(parsed: object) -> WorkflowDefinition:
    """Judge one parsed workflow document against the
    decided shape. Returns the definition on success;
    raises WorkflowFormatError -- workflow_invalid for
    shape, workflow_uses_refused for uses:,
    workflow_expression_refused for ${{ -- with the
    reason in plain words. Pure."""
    if not isinstance(parsed, dict) or not parsed:
        raise _invalid("A workflow is a non-empty mapping.")
    for key in parsed:
        if isinstance(key, bool):
            raise _invalid(
                "A workflow key arrived as a boolean -- this is "
                "the YAML 1.1 trap: the bare word on: reads as "
                "true in some parsers. Quote the key ('on':) "
                "so it stays a word.")
        if not isinstance(key, str):
            raise _invalid("Every workflow key is text.")
    unknown = sorted(set(parsed) - TOP_LEVEL_KEYS)
    if unknown:
        raise _invalid(
            "Unknown top-level key(s): " + ", ".join(unknown)
            + ". Samverk's shape carries: "
            + ", ".join(sorted(TOP_LEVEL_KEYS)) + ".")
    if "on" not in parsed:
        raise _invalid("A workflow needs its on: triggers.")
    if "jobs" not in parsed:
        raise _invalid("A workflow needs its jobs:.")
    name = parsed.get("name")
    if name is not None and not isinstance(name, str):
        raise _invalid("A workflow's name is text.")
    _env(parsed.get("env"), "Workflow")
    _permissions(parsed.get("permissions"))
    concurrency = parsed.get("concurrency")
    if concurrency is not None:
        if isinstance(concurrency, dict):
            if not isinstance(concurrency.get("group"), str):
                raise _invalid(
                    "concurrency: a mapping names its group:.")
        elif not isinstance(concurrency, str):
            raise _invalid(
                "concurrency: is a group name or a mapping.")
    return WorkflowDefinition(
        name=name or "", triggers=_triggers(parsed["on"]),
        jobs=_jobs(parsed["jobs"]))


def parse_workflow(text: object) -> WorkflowDefinition:
    """Parse workflow YAML text with the standing YAML
    subset and validate it as one act. YAML outside
    the subset and shape failures both answer
    WorkflowFormatError."""
    if not isinstance(text, str):
        raise _invalid("A workflow file is text.")
    try:
        parsed = parse_yaml_subset(text)
    except TemplateError as exc:
        raise WorkflowFormatError(
            getattr(exc, "reason", "workflow_invalid"),
            str(exc)) from exc
    return validate_workflow(parsed)


# ------------------------------------------------------------------
# The audit: the decision checked against the live instance.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowAudit:
    """The format decision checked against one live
    instance: the decision data's own integrity, how
    much schema was inspected, and every
    workflow-shaped name found in it. The decision
    stands cleanly only while no table, column or
    audit event carries a workflow yet -- S-314 and
    later slices mint theirs when they land."""
    decision: str
    mapping_relations_ok: bool
    mapping_ids_unique: bool
    difference_ids_unique: bool
    tables_scanned: int
    columns_scanned: int
    events_scanned: int
    offending_tables: tuple[str, ...]
    offending_columns: tuple[str, ...]
    offending_events: tuple[str, ...]

    @property
    def decided_cleanly(self) -> bool:
        return (self.decision == "adopted"
                and self.mapping_relations_ok
                and self.mapping_ids_unique
                and self.difference_ids_unique
                and not self.offending_tables
                and not self.offending_columns
                and not self.offending_events)


def audit_workflow_format(conn: sqlite3.Connection) -> WorkflowAudit:
    """Check the decision against the live instance:
    the mapping's relations stay inside their
    vocabulary and every id is unique, and no table,
    column or audit event carries the word workflow
    -- a CI surface arriving ahead of S-314 would be
    the decision broken by a back door. Pure read."""
    relations = {"same", "renamed", "ours", "not-carried"}
    mapping_relations_ok = all(
        m.relation in relations for m in MAPPINGS)
    mapping_ids_unique = len({m.id for m in MAPPINGS}) == len(MAPPINGS)
    difference_ids_unique = (
        len({d.id for d in DIFFERENCES}) == len(DIFFERENCES))
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    offending_tables: list[str] = []
    offending_columns: list[str] = []
    columns_scanned = 0
    for table in tables:
        if "workflow" in table.lower():
            offending_tables.append(table)
        safe = table.replace('"', '""')
        for row in conn.execute(
                f'PRAGMA table_info("{safe}")').fetchall():
            columns_scanned += 1
            if "workflow" in str(row[1]).lower():
                offending_columns.append(f"{table}.{row[1]}")
    events = sorted(taxonomy.AUDIT_EVENTS)
    offending_events = [
        e for e in events if "workflow" in e.lower()]
    return WorkflowAudit(
        decision=DECISION,
        mapping_relations_ok=mapping_relations_ok,
        mapping_ids_unique=mapping_ids_unique,
        difference_ids_unique=difference_ids_unique,
        tables_scanned=len(tables),
        columns_scanned=columns_scanned,
        events_scanned=len(events),
        offending_tables=tuple(offending_tables),
        offending_columns=tuple(offending_columns),
        offending_events=tuple(offending_events))


def render_workflow_format_page(
        audit: WorkflowAudit | None = None) -> str:
    """The decision, rendered: adopted said plainly,
    the mapping row by row, the deliberate
    differences, the must-not-break invariants, and
    the checked proof when an audit rides along --
    every value escaped, the state said in words,
    never colour-only."""
    parts = [
        "<h1>Workflow format -- ours, adopted (S-313)</h1>",
        "<p>Decision: <strong>adopted</strong>. Samverk "
        "workflows live in <code>.samverk/workflows/</code> "
        "as YAML files in Samverk's own shape: "
        "GitHub-familiar in structure, documented as "
        "ours. The mapping and the deliberate "
        "differences below are the study record "
        "(research file 25); the same words live in "
        "docs/WORKFLOW_FORMAT.md.</p>",
        "<h2>The mapping, GitHub to Samverk</h2>", "<ul>"]
    for mapping in MAPPINGS:
        parts.append(
            f"<li><strong>{escape_html_text(mapping.github)}"
            f"</strong> -&gt; "
            f"<strong>{escape_html_text(mapping.samverk or '(not carried)')}"
            f"</strong> ({escape_html_text(mapping.relation)}): "
            f"{escape_html_text(mapping.note)}</li>")
    parts.append("</ul>")
    parts.append("<h2>The deliberate differences</h2>")
    parts.append("<ul>")
    for difference in DIFFERENCES:
        parts.append(
            f"<li><strong>{escape_html_text(difference.title)}"
            f"</strong>: {escape_html_text(difference.detail)}</li>")
    parts.append("</ul>")
    parts.append("<h2>What Part XVI must not break</h2>")
    parts.append("<ul>")
    for invariant in MUST_NOT_BREAK:
        parts.append(
            f"<li><strong>{escape_html_text(invariant.title)}"
            f"</strong>: {escape_html_text(invariant.statement)}</li>")
    parts.append("</ul>")
    if audit is not None:
        state = ("stands cleanly" if audit.decided_cleanly
                 else "does NOT stand cleanly")
        parts.append("<h2>Checked against this instance</h2>")
        parts.append(
            f"<p>The decision {escape_html_text(state)}: "
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
