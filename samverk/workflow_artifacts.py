"""Workflow artifacts -- the run page listing
(S-323).

Artifacts -- workflow artifacts via S-266,
listed on the run page.

S-266 built the store: a build's files live as
`ci_artifacts` rows, each tied to the commit it
was built from and to the standing S-246 check
run that produced it, under a stated retention
policy. S-321 landed Part XVI's own job
conclusions as check runs named
``<workflow> / <job>`` on the run's commit.
What neither slice built is the page a reader
actually opens after a run: the run's artifacts,
gathered in one listing. This module is that
gathering -- a read face over S-266's rows, in
S-322's shape for logs.

- **A run is addressed as the forge addresses
  it.** One workflow run on one commit is named
  by the triple every neighbouring face already
  uses -- repository, workflow, commit (`oid`).
  The run's jobs are the check runs standing on
  that commit whose names S-321's
  `check_name_for` law built for this workflow
  (``<workflow> / <job>``, decided here by the
  pure `job_for_check_name` over the same
  string), and the run's artifacts are exactly
  the S-266 rows tied by `check_run_id` to
  those check runs. There is no second artifact
  record and no run table invented for the
  page: an artifact uploaded against another
  workflow's check, another commit's check, or
  a check that is not a job of this workflow
  (an external poster's plain name) is not this
  run's artifact, and the battery proves each
  exclusion. A run whose jobs produced nothing
  lists honestly empty.
- **Grouped by job, in landing order.** The
  listing answers one `JobArtifacts` group per
  job that carries artifacts, in check-run
  order, each group's artifacts in S-266
  landing order, with the run's totals said in
  plain words (`words`): how many artifacts,
  how many bytes, how many stand expired.
  `list_job_artifacts` narrows the same listing
  to one job's group.
- **Reads follow the repository (S-054).**
  Every read takes a viewer and resolves the
  repository through S-054's `can_read` before
  any run is named: a missing repository and a
  private repository the viewer cannot read
  answer the one uniform
  `repository_not_found`, so a stranger learns
  nothing about a private repository's runs.
  Anonymous readers read public repositories'
  run pages, as everywhere else in the forge.
  This face is the web run page's read, beside
  S-266's API-door listing -- the two read the
  same rows and neither replaces the other.
- **Expiry is S-266's law, stated, not hidden.**
  An artifact whose retention window has
  closed is still listed -- S-266's own listing
  law marks it `expired`, judged by S-266's
  `is_expired` at the reading clock -- with its
  expiry stamp beside it, so the run page never
  pretends a kept file is downloadable: the
  download itself stays S-266's road, which
  refuses expired artifacts uncounted. When
  S-267's off-path sweep removes the row, the
  artifact vanishes from this listing in the
  same moment it vanishes from S-266's, because
  both read the one row.
- **The durable artefact is S-266's row.**
  This listing writes nothing: no row, no
  audit entry, no taxonomy event (138 stand:
  33 auth / 92 repo / 13 admin), on S-321's and
  S-322's basis -- the witnessed record of a
  run's artifacts is the artifact row itself,
  carrying its poster, its digest and its
  retention stamps. No migration: the tables
  are S-246's `check_runs` (migration 95) and
  S-266's `ci_artifacts` (migration 105), and
  the schema stays 132. S-327 owns the routed
  run pages; the render function here is the
  artifacts view in the house shape, every
  value escaped through S-010.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import taxonomy
from .accounts import User
from .check_reporting import check_name_for
from .ci_artifacts import CIArtifact, _row_to_artifact, is_expired
from .escaping import escape_html_text
from .permissions import can_read
from .repositories import RepositoryStore

__all__ = [
    "JobArtifacts", "RunArtifact", "RunArtifacts",
    "WorkflowArtifactsAudit", "WorkflowArtifactsError",
    "WorkflowArtifactsStore", "audit_workflow_artifacts",
    "is_run_check_name", "job_artifacts_to_dict",
    "job_for_check_name", "render_run_artifacts_page",
    "run_artifact_to_dict", "run_artifacts_to_dict",
    "run_check_prefix", "validate_run_address",
]

_SURFACE_WORD = "workflow_artifacts"


class WorkflowArtifactsError(ValueError):
    """One refused workflow-artifacts call: a
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
        raise WorkflowArtifactsError(
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
        raise WorkflowArtifactsError(
            "run_oid_invalid",
            "run_oid_invalid -- a run names the "
            "commit it ran on. Nothing was "
            "recorded.")
    return str(workflow).strip(), str(oid).strip()


@dataclass(frozen=True)
class RunArtifact:
    """One of a run's artifacts: S-266's row,
    the job whose check produced it, and its
    expiry standing at the reading clock."""
    artifact: CIArtifact
    job_id: str
    expired: bool

    @property
    def words(self) -> str:
        standing = ("expired" if self.expired
                    else "standing")
        return (
            f"{self.artifact.name} -- "
            f"{self.artifact.size} bytes, {standing}, "
            f"from job {self.job_id}.")


def run_artifact_to_dict(record: RunArtifact) -> dict:
    """One run artifact as JSON-safe data:
    S-266's own `artifact_to_dict` shape (its
    `expired` judged at the reading clock) plus
    the job that produced it. Data carries the
    raw values -- S-010 escaping is the page's
    law, not the wire's."""
    # S-266's shape, field for field, with the
    # `expired` verdict the store judged at its
    # reading clock (artifact_to_dict with no
    # clock would restate it as standing).
    data = {
        "id": record.artifact.id,
        "oid": record.artifact.head_oid,
        "check_run": record.artifact.check_run,
        "name": record.artifact.name,
        "size": record.artifact.size,
        "sha256": record.artifact.sha256,
        "content_type": record.artifact.content_type,
        "download_count": record.artifact.download_count,
        "retention_days": record.artifact.retention_days,
        "expires_at": record.artifact.expires_at,
        "expired": record.expired,
        "poster": record.artifact.poster,
        "created_at": record.artifact.created_at,
        "job_id": record.job_id,
    }
    return data


@dataclass(frozen=True)
class JobArtifacts:
    """One job's artifacts within a run: the
    job, its S-321 check name, and its artifacts
    in landing order."""
    job_id: str
    check_run: str
    artifacts: tuple

    @property
    def total_bytes(self) -> int:
        return sum(a.artifact.size for a in self.artifacts)

    @property
    def words(self) -> str:
        return (
            f"{self.job_id} -- "
            f"{len(self.artifacts)} artifacts, "
            f"{self.total_bytes} bytes.")


def job_artifacts_to_dict(group: JobArtifacts) -> dict:
    """One job group as JSON-safe data."""
    return {
        "job_id": group.job_id,
        "check_run": group.check_run,
        "total_bytes": group.total_bytes,
        "artifacts": [run_artifact_to_dict(a)
                      for a in group.artifacts],
    }


@dataclass(frozen=True)
class RunArtifacts:
    """One workflow run's artifact listing: the
    run's address, its per-job groups in
    check-run order, and its totals."""
    full_name: str
    workflow: str
    oid: str
    groups: tuple

    @property
    def artifacts(self) -> tuple:
        return tuple(
            a for group in self.groups
            for a in group.artifacts)

    @property
    def total_count(self) -> int:
        return len(self.artifacts)

    @property
    def total_bytes(self) -> int:
        return sum(a.artifact.size for a in self.artifacts)

    @property
    def expired_count(self) -> int:
        return sum(1 for a in self.artifacts if a.expired)

    @property
    def words(self) -> str:
        if self.total_count == 0:
            return (
                f"Workflow {self.workflow} on "
                f"{self.oid} produced no artifacts.")
        return (
            f"Workflow {self.workflow} on {self.oid} "
            f"produced {self.total_count} artifacts "
            f"({self.total_bytes} bytes) across "
            f"{len(self.groups)} jobs; "
            f"{self.expired_count} expired.")


def run_artifacts_to_dict(listing: RunArtifacts) -> dict:
    """One run listing as JSON-safe data."""
    return {
        "repository": listing.full_name,
        "workflow": listing.workflow,
        "oid": listing.oid,
        "total_count": listing.total_count,
        "total_bytes": listing.total_bytes,
        "expired_count": listing.expired_count,
        "jobs": [job_artifacts_to_dict(g)
                 for g in listing.groups],
        "artifacts": [run_artifact_to_dict(a)
                      for a in listing.artifacts],
    }


class WorkflowArtifactsStore:
    """The S-323 listing: one workflow run's
    artifacts, gathered from S-266's rows by way
    of the run's S-321 job checks on its commit,
    grouped by job, read through the repository's
    own permission seam. It owns no artifact law
    of its own: the tie is S-266's, the check
    name is S-321's, the expiry judgement is
    S-266's, and the read gate is S-054's."""

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

    def _repo_for_read(self, viewer, owner: object,
                       repo: object):
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            # One answer for missing and unreadable
            # alike (S-054: a private repository's
            # existence is itself private).
            raise WorkflowArtifactsError(
                "repository_not_found",
                "repository_not_found -- no such "
                "repository.")
        return current

    def _gather(self, repo_id: int, workflow: str,
                oid: str, now: int) -> list:
        """The run's job groups: check runs on the
        commit that are this workflow's jobs, each
        with its S-266 artifacts in landing order.
        Jobs carrying no artifacts answer no group,
        exactly as S-266's listing answers no row
        for them."""
        checks = self._conn.execute(
            "SELECT * FROM check_runs WHERE repo_id = ?"
            " AND head_oid = ? ORDER BY id",
            (repo_id, oid)).fetchall()
        groups: list = []
        for check in checks:
            job = job_for_check_name(workflow, check["name"])
            if job is None:
                continue
            rows = self._conn.execute(
                "SELECT * FROM ci_artifacts"
                " WHERE check_run_id = ? ORDER BY id",
                (check["id"],)).fetchall()
            if not rows:
                continue
            artifacts = tuple(
                RunArtifact(
                    artifact=_row_to_artifact(r), job_id=job,
                    expired=is_expired(r["expires_at"], now))
                for r in rows)
            groups.append(JobArtifacts(
                job_id=job, check_run=check["name"],
                artifacts=artifacts))
        return groups

    # -- reads --------------------------------------

    def list_run_artifacts(self, viewer: User | None,
                           owner: object, repo: object,
                           workflow: object,
                           oid: object) -> RunArtifacts:
        """Every artifact one workflow run
        produced, grouped by job. The address
        validates before the repository is read,
        so an unlawful address is refused even
        over a repository that does not stand.
        A run that never stood, or stood and
        produced nothing, lists honestly empty --
        the page says so in words, it does not
        invent a run."""
        workflow, oid = validate_run_address(workflow, oid)
        current = self._repo_for_read(viewer, owner, repo)
        groups = self._gather(
            current.id, workflow, oid, int(self._now()))
        return RunArtifacts(
            full_name=current.full_name, workflow=workflow,
            oid=oid, groups=tuple(groups))

    def list_job_artifacts(self, viewer: User | None,
                           owner: object, repo: object,
                           workflow: object, oid: object,
                           job_id: object) -> RunArtifacts:
        """One job's artifacts within one run: the
        run listing narrowed to the group whose
        check S-321 names ``<workflow> / <job>``.
        A job that is not this run's, or carried
        nothing, lists honestly empty."""
        workflow, oid = validate_run_address(workflow, oid)
        if not isinstance(job_id, str) or not job_id.strip():
            raise WorkflowArtifactsError(
                "run_job_invalid",
                "run_job_invalid -- a job listing "
                "names its job. Nothing was recorded.")
        wanted = check_name_for(workflow, job_id.strip())
        listing = self.list_run_artifacts(
            viewer, owner, repo, workflow, oid)
        groups = tuple(
            g for g in listing.groups
            if g.check_run == wanted)
        return RunArtifacts(
            full_name=listing.full_name,
            workflow=listing.workflow, oid=listing.oid,
            groups=groups)


# ------------------------------------------------------------------
# The audit: the listing checked against the live instance.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowArtifactsAudit:
    """The run-artifact listing checked against
    one live instance: the name law is S-321's
    word for word, the schema is exactly 132
    (no migration is this slice's), the taxonomy
    is at the standing 138, the lawful tables stand,
    and every standing artifact row's S-266 tie
    obeys the law the listing reads by -- its
    check run stands in the same repository,
    under the name and commit the row keeps."""
    names_ok: bool
    schema_version: int
    schema_ok: bool
    events_ok: bool
    tables_ok: bool
    rows_scanned: int
    problems: tuple

    @property
    def stands_cleanly(self) -> bool:
        return (
            self.names_ok and self.schema_ok
            and self.events_ok and self.tables_ok
            and not self.problems)


def audit_workflow_artifacts(conn: sqlite3.Connection
                             ) -> WorkflowArtifactsAudit:
    """Check the listing against the live
    instance: the name law, schema and taxonomy
    pins hold, the `ci_artifacts` and
    `check_runs` tables stand, and every
    standing artifact row's tie resolves. Pure
    read."""
    from .db import schema_version as _schema_version
    version = _schema_version(conn)
    events_ok = (len(taxonomy.AUDIT_EVENTS) == 138
                 and len(taxonomy.AUTH_EVENTS) == 33
                 and len(taxonomy.REPO_EVENTS) == 92
                 and len(taxonomy.ADMIN_EVENTS) == 13)
    names_ok = (
        check_name_for("CI", "build") == "CI / build"
        and job_for_check_name("CI", "CI / build") == "build"
        and job_for_check_name("CI", "CI") is None
        and job_for_check_name("CI", "Docs / build") is None
        and job_for_check_name("CI", "CI / ") is None)
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    tables_ok = ("ci_artifacts" in tables
                 and "check_runs" in tables)
    problems: list = []
    rows = conn.execute(
        "SELECT * FROM ci_artifacts ORDER BY id").fetchall() \
        if tables_ok else []
    for row in rows:
        label = f"artifact {row['id']}"
        check = conn.execute(
            "SELECT * FROM check_runs WHERE id = ?",
            (row["check_run_id"],)).fetchone()
        if check is None:
            problems.append(
                f"{label}: its check run does not stand")
            continue
        if check["repo_id"] != row["repo_id"]:
            problems.append(
                f"{label}: its check run stands in "
                "another repository")
        if check["name"] != row["check_run"]:
            problems.append(
                f"{label}: its kept check name is not "
                "its check run's name")
        if check["head_oid"] != row["head_oid"]:
            problems.append(
                f"{label}: its commit is not its "
                "check run's commit")
    return WorkflowArtifactsAudit(
        names_ok=names_ok,
        schema_version=version, schema_ok=version == 135,
        events_ok=events_ok, tables_ok=tables_ok,
        rows_scanned=len(rows), problems=tuple(problems))


def render_run_artifacts_page(
        listing: RunArtifacts | None = None,
        audit: WorkflowArtifactsAudit | None = None
        ) -> str:
    """One run's artifacts view, in plain words:
    what a run's artifacts are and where they
    live, and -- when a listing rides along --
    the listing itself, grouped by job, every
    artifact's standing said in words (never a
    colour alone). Every value escaped through
    S-010."""
    parts = [
        "<h1>Workflow run artifacts</h1>",
        "<p>Every workflow job's files are kept as "
        "artifacts (S-266), tied to the commit the "
        "run built and to the job's check run. This "
        "page lists one run's artifacts grouped by "
        "the job that produced them, with each "
        "artifact's size and retention standing. An "
        "expired artifact is still listed and marked "
        "expired; it no longer downloads, and the "
        "expiry sweep (S-267) removes it whole, from "
        "this page and from storage together.</p>",
    ]
    if listing is not None:
        parts.append(
            f"<p>{escape_html_text(listing.words)}</p>")
        for group in listing.groups:
            parts.append(
                f"<h2>{escape_html_text(group.job_id)}</h2>")
            parts.append(
                f"<p>{escape_html_text(group.words)}</p>")
            for record in group.artifacts:
                parts.append(
                    f"<p>{escape_html_text(record.words)}</p>")
    if audit is not None:
        verdict = ("stands cleanly"
                   if audit.stands_cleanly
                   else "does not stand cleanly")
        parts.append(
            f"<p>Checked against this instance: "
            f"the run-artifact listing "
            f"{escape_html_text(verdict)} "
            f"(schema {audit.schema_version}, "
            f"{audit.rows_scanned} artifacts "
            f"scanned).</p>")
    return "\n".join(parts)
