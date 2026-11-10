"""Registry core -- the published refusal (S-265).

The roadmap's registry core: namespaced package
publish/fetch with repo-linked permissions. S-264
verdicted the registry DEFER/out -- no ecosystem
is hosted now, OCI containers are refused
outright, Python stands deferred as the first
candidate -- so this slice takes the roadmap's
own verdicted-out road: the published refusal
with the seam documented. This module IS the
registry core's standing shape, with every act
refused:

- **The namespace is a repository.** A package
  is named whole -- ecosystem, the owner/name of
  the repository it is linked to, a package name
  and a version (``PackageRef``) -- and the
  namespace belongs to that repository, exactly
  as S-264's first must-not-break invariant
  (``namespace-follows-permissions``) states.
  There is no registry-only ownership and no
  namespace apart from forge permissions.
- **Permissions are judged for real, first.**
  ``OPERATIONS`` names the four acts a registry
  core would carry -- publish, fetch, list,
  delete -- each with the rung of S-054's
  repository permission law it would require
  (publish: write; fetch and list: read; delete:
  admin, because deletion leaves a tombstone).
  ``RegistryCore`` resolves the linked repository
  through the standing ``RepositoryStore`` and
  the caller's role through S-054's ``role_for``
  before any verdict is spoken: a missing
  repository, and a private repository the caller
  may not read, answer exactly as a missing
  package on fetch and list (S-264's
  ``private-is-missing-on-fetch``, applied to the
  refusal itself -- the refusal must not leak
  what the caller may not read), and as the
  uniform ``repo_not_found`` on publish and
  delete, the forge's standing write-door answer;
  a caller who may read but not write is refused
  ``permission_denied`` on publish, as S-257's
  release door refuses; an anonymous publish or
  delete is refused ``authentication_required``.
- **Only then is the verdict spoken.** A caller
  who passes the permission door meets S-264's
  per-ecosystem answer, delegated to the
  verdict's own ``decide_registry_request`` so
  the two slices can never drift:
  ``registry_deferred`` (Python, JavaScript),
  ``registry_refused`` (OCI containers),
  ``registry_served_by_releases`` (generic
  archives -- publish the file as a release
  asset instead) or ``registry_served_by_git``
  (Go modules -- tag the version in its
  repository instead). Shapeless requests are
  refused at the door storing nothing:
  ``registry_ecosystem_unknown``,
  ``namespace_invalid``, ``package_name_invalid``,
  ``package_version_invalid``,
  ``registry_action_invalid``.
- **The seam is S-264's, imported not forked.**
  ``SEAM_INVARIANTS`` is the verdict's own
  ``MUST_NOT_BREAK`` tuple -- the same objects --
  so the law a future core builds under is
  stated once, in samverk/package_verdict.py,
  and this core already stands inside it: the
  battery pins the identity. What a reopened
  verdict would have to satisfy is the verdict's
  ``REOPEN_CONDITIONS``, named here and in
  docs/REGISTRY_CORE.md.
- **A refusal that writes nothing.** This
  module holds no store, creates no table and
  audits nothing: no act here can succeed, so
  there is nothing to witness -- exactly S-264's
  ``publish-and-fetch-are-witnessed`` invariant
  read honestly for a core with no publish or
  fetch to witness yet. ``audit_registry_core``
  proves the refusal against the live instance:
  the verdict still defers, no table, column or
  audit event carries a package registry, and no
  API contract resource claims one. No migration
  (schema stays 104), no taxonomy event (131
  stand: 33 auth / 85 repo / 13 admin). The
  published refusal also lives in
  docs/REGISTRY_CORE.md, where a person who
  never opens this module can read it.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from .accounts import User
from .api_contract import API_RESOURCES, audit_api_contract
from .escaping import escape_html_text
from .package_verdict import (
    ECOSYSTEMS, MUST_NOT_BREAK, REOPEN_CONDITIONS, VERDICT,
    audit_package_verdict, decide_registry_request)
from .permissions import ROLE_RANK, role_for
from .repositories import (
    RepositoryError, RepositoryStore, canonical_owner_repo)

__all__ = [
    "OPERATIONS", "SEAM_INVARIANTS", "OperationSpec",
    "PackageRef", "RegistryCore", "RegistryCoreAudit",
    "RegistryCoreError", "audit_registry_core",
    "decide_delete", "decide_fetch", "decide_list",
    "decide_publish", "get_operation",
    "render_registry_core_page", "validate_name",
    "validate_namespace", "validate_version",
]

# The seam, stated once in S-264 and imported
# whole: this core stands inside the verdict's
# invariants, it does not restate them.
SEAM_INVARIANTS = MUST_NOT_BREAK

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
NAME_MAX = 100
VERSION_MAX = 64


class RegistryCoreError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class PackageRef:
    """One package, named whole: the ecosystem,
    the linked repository that is its namespace
    (owner and name, display case), the package
    name and the version. A ref names where a
    package WOULD live; naming one creates
    nothing."""
    ecosystem: str
    owner: str
    repo: str
    name: str
    version: str

    @property
    def namespace(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def coordinate(self) -> str:
        return (f"{self.ecosystem}:{self.namespace}"
                f"/{self.name}@{self.version}")


@dataclass(frozen=True)
class OperationSpec:
    """One act the registry core would carry: a
    stable id, the plain title a reader sees, the
    rung of S-054's permission law the act
    requires on the linked repository, and what
    the act would do if a registry stood."""
    id: str
    title: str
    minimum_role: str
    would_do: str


OPERATIONS: tuple[OperationSpec, ...] = (
    OperationSpec(
        id="publish",
        title="Publish a package version",
        minimum_role="write",
        would_do=(
            "Fix a version's bytes and their digest "
            "under the linked repository's namespace, "
            "after quarantine and validation, "
            "witnessed like a release act.")),
    OperationSpec(
        id="fetch",
        title="Fetch a package version",
        minimum_role="read",
        would_do=(
            "Serve one published version's bytes to "
            "a caller who may read the linked "
            "repository, counted like an asset "
            "download.")),
    OperationSpec(
        id="list",
        title="List a package's versions",
        minimum_role="read",
        would_do=(
            "Name the published versions of one "
            "package under its namespace, tombstones "
            "included and said so.")),
    OperationSpec(
        id="delete",
        title="Delete a package version",
        minimum_role="admin",
        would_do=(
            "Withdraw a version leaving a tombstone "
            "with its name, version and digest, so "
            "the name cannot be silently reused for "
            "different bytes.")),
)


def get_operation(operation_id: object) -> OperationSpec:
    """One registry operation by its id. An
    unknown id is refused
    ``registry_action_invalid`` -- the core does
    not invent an act to answer with."""
    for operation in OPERATIONS:
        if operation.id == operation_id:
            return operation
    raise RegistryCoreError(
        "registry_action_invalid",
        "No such registry action exists.")


def validate_namespace(owner: object, repo: object) -> tuple[str, str]:
    """The namespace door: a package namespace is
    a repository's owner/name, judged by the
    repository path law itself (S-013, through
    the repositories module). Returns the display
    (owner, repo) pair; anything shapeless is
    refused ``namespace_invalid`` storing
    nothing."""
    try:
        owner_ok, _, repo_ok, _ = canonical_owner_repo(owner, repo)
    except RepositoryError:
        raise RegistryCoreError(
            "namespace_invalid",
            "A package namespace is a repository's "
            "owner and name, and that is not one.") from None
    return owner_ok, repo_ok


def validate_name(name: object) -> str:
    """One package name, judged at the door: text
    of 1..100, starting with a lowercase letter or
    digit, then lowercase letters, digits, dots,
    dashes and underscores, with no doubled dot
    and no trailing dot or dash -- one canonical
    lowercase shape per ecosystem-neutral rule, so
    a name can never differ from another only by
    case or by a path trick. Refused
    ``package_name_invalid``."""
    if (not isinstance(name, str) or not name
            or len(name) > NAME_MAX or not _NAME_RE.match(name)
            or ".." in name or name.endswith(".")
            or name.endswith("-")):
        raise RegistryCoreError(
            "package_name_invalid",
            "That package name is not valid.")
    return name


def validate_version(version: object) -> str:
    """One package version, judged at the door:
    text of 1..64, starting with a letter or
    digit, then letters, digits, dots, dashes,
    pluses and underscores, with no doubled dot
    and no path separator -- a version names
    bytes, it never paths anywhere. Refused
    ``package_version_invalid``."""
    if (not isinstance(version, str) or not version
            or len(version) > VERSION_MAX
            or not _VERSION_RE.match(version)
            or ".." in version):
        raise RegistryCoreError(
            "package_version_invalid",
            "That package version is not valid.")
    return version


def _validate_ecosystem(ecosystem: object) -> str:
    """The ecosystem door: shapeless is
    ``registry_request_invalid`` (S-264's own
    word for it), a worded ecosystem S-264 never
    assessed is ``registry_ecosystem_unknown``;
    an assessed one returns its id, stripped."""
    if not isinstance(ecosystem, str) or not ecosystem.strip():
        raise RegistryCoreError(
            "registry_request_invalid",
            "That registry request is not valid.")
    candidate = ecosystem.strip()
    for assessed in ECOSYSTEMS:
        if assessed.id == candidate:
            return candidate
    raise RegistryCoreError(
        "registry_ecosystem_unknown",
        "Samverk assessed no such ecosystem: S-264 "
        "judged Python, generic archives, "
        "JavaScript, OCI containers and Go modules, "
        "and hosts none of them.")


def _verdict_reason(ecosystem: str) -> str:
    """S-264's per-ecosystem answer, delegated so
    the verdict is spoken in one place only."""
    return decide_registry_request(ecosystem)


def decide_publish(ecosystem: str, repo_exists: bool,
                   caller_role: str | None) -> str:
    """Pure publish judgement, in order: a missing
    linked repository is the uniform
    ``repo_not_found``; a caller with no role on
    it meets the same answer (an unreadable
    private repository is indistinguishable from
    a missing one, even at the write door); a
    reader who may not write is
    ``permission_denied``; a writer or admin meets
    the verdict's per-ecosystem answer."""
    if not repo_exists or caller_role is None:
        return "repo_not_found"
    if ROLE_RANK.get(caller_role, 0) < ROLE_RANK["write"]:
        return "permission_denied"
    return _verdict_reason(ecosystem)


def decide_fetch(ecosystem: str, repo_exists: bool,
                 caller_role: str | None) -> str:
    """Pure fetch judgement, in order: a missing
    linked repository, or one the caller may not
    read, is the uniform ``package_not_found`` --
    missing, private and merely unpublished are
    one answer, S-264's private-is-missing
    invariant applied to the refusal itself; a
    reader meets the verdict's per-ecosystem
    answer."""
    if not repo_exists or caller_role is None:
        return "package_not_found"
    return _verdict_reason(ecosystem)


def decide_list(ecosystem: str, repo_exists: bool,
                caller_role: str | None) -> str:
    """Pure list judgement: listing names what a
    namespace holds, so it is judged exactly as
    fetch is judged -- ``package_not_found`` for
    the missing and the unreadable alike, the
    verdict's answer for a reader."""
    return decide_fetch(ecosystem, repo_exists, caller_role)


def decide_delete(ecosystem: str, repo_exists: bool,
                  caller_role: str | None) -> str:
    """Pure delete judgement, in order: a missing
    linked repository, or one the caller has no
    role on, is the uniform ``repo_not_found``; a
    reader or writer who is not an admin of the
    linked repository is ``permission_denied``
    (deletion leaves a tombstone, an admin act);
    an admin meets the verdict's per-ecosystem
    answer."""
    if not repo_exists or caller_role is None:
        return "repo_not_found"
    if caller_role != "admin":
        return "permission_denied"
    return _verdict_reason(ecosystem)


_VERDICT_MESSAGES = {
    "registry_deferred": (
        "Samverk hosts no package registry: S-264 "
        "deferred it, with reasons, and S-265 is "
        "the published refusal. Distribution today "
        "is by releases and their assets."),
    "registry_refused": (
        "Samverk does not host container images: "
        "S-264 refused the OCI ecosystem, and the "
        "village runs no Docker by standing law. "
        "Workloads here are installed natively, "
        "not pulled as images."),
    "registry_served_by_releases": (
        "There is no generic package store: S-264 "
        "found generic archives already served by "
        "releases (S-257..S-263) -- publish the "
        "file as a release asset, with its "
        "checksums, instead."),
    "registry_served_by_git": (
        "There is no Go module registry: S-264 "
        "found Go modules already served by the "
        "git transports -- tag the module version "
        "in its repository and clients fetch it "
        "from there."),
}


class RegistryCore:
    """The registry core's standing doors. Every
    method judges its request whole -- shape,
    then the linked repository's permissions,
    then S-264's verdict -- and refuses; nothing
    here can succeed, write a row, or audit an
    event, because no registry stands to succeed
    against."""

    def __init__(self, repositories: RepositoryStore):
        self._repos = repositories

    # -- judging -------------------------------------------------
    def _judge(self, operation: str, actor: User | None,
               ecosystem: object, owner: object, repo: object,
               *, collaborator_role: str | None = None) -> None:
        """Judge one act in the core's one order
        and raise its refusal -- every path raises,
        because no act here can succeed; shape
        refusals raise before any repository is
        read."""
        spec = get_operation(operation)
        if operation in ("publish", "delete") and actor is None:
            raise RegistryCoreError(
                "authentication_required",
                "That registry act needs a signed-in "
                "account.")
        eco = _validate_ecosystem(ecosystem)
        owner_ok, repo_ok = validate_namespace(owner, repo)
        current = self._repos.get_repository(owner_ok, repo_ok)
        role = (role_for(actor, current,
                         collaborator_role=collaborator_role)
                if current is not None else None)
        if operation == "publish":
            reason = decide_publish(eco, current is not None, role)
        elif operation == "delete":
            reason = decide_delete(eco, current is not None, role)
        elif operation == "list":
            reason = decide_list(eco, current is not None, role)
        else:
            reason = decide_fetch(eco, current is not None, role)
        if reason == "repo_not_found":
            raise RegistryCoreError(
                reason, "No such repository.")
        if reason == "package_not_found":
            raise RegistryCoreError(
                reason, "No such package.")
        if reason == "permission_denied":
            raise RegistryCoreError(
                reason,
                f"Only a repository {spec.minimum_role} "
                "may do that with this namespace.")
        raise RegistryCoreError(
            reason, _VERDICT_MESSAGES[reason])

    # -- the four doors -------------------------------------------
    def publish(self, actor: User | None, ecosystem: object,
                owner: object, repo: object, name: object,
                version: object, *,
                collaborator_role: str | None = None) -> None:
        """Refuse a publish: shape first (ecosystem,
        namespace, name, version -- storing
        nothing), then the write rung on the
        linked repository, then S-264's verdict."""
        validate_name(name)
        validate_version(version)
        self._judge("publish", actor, ecosystem, owner, repo,
                    collaborator_role=collaborator_role)

    def fetch(self, viewer: User | None, ecosystem: object,
              owner: object, repo: object, name: object,
              version: object, *,
              collaborator_role: str | None = None) -> None:
        """Refuse a fetch: shape first, then the
        read rung -- the missing and the unreadable
        answering as one ``package_not_found`` --
        then S-264's verdict."""
        validate_name(name)
        validate_version(version)
        self._judge("fetch", viewer, ecosystem, owner, repo,
                    collaborator_role=collaborator_role)

    def list_versions(self, viewer: User | None, ecosystem: object,
                      owner: object, repo: object, name: object, *,
                      collaborator_role: str | None = None) -> None:
        """Refuse a version listing: judged exactly
        as fetch is judged, because a listing names
        what a namespace holds."""
        validate_name(name)
        self._judge("list", viewer, ecosystem, owner, repo,
                    collaborator_role=collaborator_role)

    def delete(self, actor: User | None, ecosystem: object,
               owner: object, repo: object, name: object,
               version: object, *,
               collaborator_role: str | None = None) -> None:
        """Refuse a deletion: shape first, then the
        admin rung on the linked repository (a
        tombstone is an admin act), then S-264's
        verdict."""
        validate_name(name)
        validate_version(version)
        self._judge("delete", actor, ecosystem, owner, repo,
                    collaborator_role=collaborator_role)


@dataclass(frozen=True)
class RegistryCoreAudit:
    """The refusal checked against one live
    instance: S-264's verdict audit carried whole
    (its counts and offender lists), the API
    contract's own ratification and resource
    count, and every contract resource claiming a
    package registry. The refusal is clean only
    when the verdict still defers cleanly, the
    contract ratifies, and no resource claims a
    registry."""
    verdict: str
    verdict_deferred_cleanly: bool
    contract_ratified: bool
    contract_resources_checked: int
    registry_contract_resources: tuple[str, ...]
    tables_scanned: int
    columns_scanned: int
    events_scanned: int
    offending_tables: tuple[str, ...]
    offending_columns: tuple[str, ...]
    offending_events: tuple[str, ...]
    operations_defined: int
    seam_invariants: int

    @property
    def refused_cleanly(self) -> bool:
        return (self.verdict == "deferred"
                and self.verdict_deferred_cleanly
                and self.contract_ratified
                and not self.registry_contract_resources)


def audit_registry_core(
        conn: sqlite3.Connection) -> RegistryCoreAudit:
    """Check the published refusal against the
    live instance: S-264's audit must still find
    the deferral clean (no registry table, column
    or audit event), the API contract must still
    ratify, and no contract resource may claim a
    package or registry road -- a registry
    arriving by any door would be the refusal
    broken. Pure read."""
    verdict_audit = audit_package_verdict(conn)
    contract = audit_api_contract()
    claimed = tuple(
        r.id for r in API_RESOURCES
        if "package" in r.id.lower()
        or "registry" in r.id.lower()
        or "package" in r.path.lower()
        or "registry" in r.path.lower())
    return RegistryCoreAudit(
        verdict=VERDICT,
        verdict_deferred_cleanly=verdict_audit.deferred_cleanly,
        contract_ratified=contract.ratified,
        contract_resources_checked=contract.resources_checked,
        registry_contract_resources=claimed,
        tables_scanned=verdict_audit.tables_scanned,
        columns_scanned=verdict_audit.columns_scanned,
        events_scanned=verdict_audit.events_scanned,
        offending_tables=verdict_audit.offending_tables,
        offending_columns=verdict_audit.offending_columns,
        offending_events=verdict_audit.offending_events,
        operations_defined=len(OPERATIONS),
        seam_invariants=len(SEAM_INVARIANTS))


def render_registry_core_page(
        audit: RegistryCoreAudit | None = None) -> str:
    """The published refusal, rendered: no registry
    said plainly, the namespace law, the four
    operations with the permission rung each is
    judged at, the per-ecosystem answers, the
    seam invariants with the ground each hangs
    from, what to use instead, the reopen pointer,
    and the checked proof when an audit rides
    along -- every value escaped through S-010,
    the state said in words, never colour-only."""
    parts = [
        "<h1>Registry core -- no registry (S-265)</h1>",
        "<p>Samverk has <strong>no package "
        "registry</strong>. S-264 deferred it, with "
        "reasons (docs/PACKAGE_VERDICT.md), and this "
        "slice is the published refusal the roadmap "
        "names for the verdicted-out road: the "
        "registry core's doors stand defined -- "
        "namespaced publish and fetch, judged by "
        "the linked repository's permissions -- and "
        "every one of them refuses. There is no "
        "package table, no publish road and no "
        "fetch road; distribution is by releases "
        "and their assets, and Go modules by git "
        "tags.</p>",
        "<h2>The namespace is a repository</h2>",
        "<p>A package is named by its ecosystem, "
        "the owner and name of the repository it is "
        "linked to, a package name and a version. "
        "The namespace belongs to that repository: "
        "publishing is judged by the repository's "
        "own permissions (S-054's law, generalised "
        "by S-190), never by a registry-only "
        "ownership, and a namespace cannot be "
        "squatted apart from the forge's "
        "permissions.</p>",
        "<h2>The four doors, and the rung each is judged at</h2>",
        "<ul>",
    ]
    for operation in OPERATIONS:
        parts.append(
            f"<li><strong>{escape_html_text(operation.title)}"
            f"</strong> ({escape_html_text(operation.id)}; "
            f"requires {escape_html_text(operation.minimum_role)} "
            f"on the linked repository): "
            f"{escape_html_text(operation.would_do)} "
            "Today it refuses.</li>")
    parts.append("</ul>")
    parts.append("<h2>How a request is answered</h2>")
    parts.append(
        "<p>Shape first, storing nothing; then the "
        "linked repository's permissions -- a "
        "missing repository, and a private one the "
        "caller may not read, answer on fetch and "
        "listing as one package_not_found, and on "
        "publish and delete as the uniform "
        "repo_not_found, so the refusal itself "
        "leaks nothing; a reader who may not write "
        "is permission_denied on publish, and "
        "deletion asks the admin rung. Only a "
        "caller who passes that door meets the "
        "verdict's answer for the ecosystem:</p>")
    parts.append("<ul>")
    for ecosystem in ECOSYSTEMS:
        answer = decide_registry_request(ecosystem.id)
        parts.append(
            f"<li><strong>{escape_html_text(ecosystem.title)}"
            f"</strong> ({escape_html_text(ecosystem.id)}): "
            f"{escape_html_text(answer)} -- "
            f"{escape_html_text(ecosystem.served_by)}</li>")
    parts.append("</ul>")
    parts.append(
        "<h2>The seam a future registry builds under</h2>")
    parts.append("<ul>")
    for invariant in SEAM_INVARIANTS:
        parts.append(
            f"<li><strong>{escape_html_text(invariant.title)}"
            f"</strong> (grounded in: "
            f"{escape_html_text(invariant.ground)}): "
            f"{escape_html_text(invariant.statement)}</li>")
    parts.append("</ul>")
    parts.append("<h2>When this reopens</h2>")
    parts.append("<ul>")
    for condition in REOPEN_CONDITIONS:
        parts.append(f"<li>{escape_html_text(condition)}</li>")
    parts.append("</ul>")
    if audit is not None:
        if audit.refused_cleanly:
            parts.append(
                "<p>Checked, not just claimed: the "
                "verdict was re-inspected for this "
                f"instance -- {audit.tables_scanned} "
                f"tables, {audit.columns_scanned} "
                f"columns and {audit.events_scanned} "
                "audit events, none carrying a "
                "package registry -- and the API "
                "contract was compared with the live "
                f"code over "
                f"{audit.contract_resources_checked} "
                "resources and still ratifies, with "
                "no resource claiming a package or "
                "registry road.</p>")
        else:
            found = ", ".join(
                audit.registry_contract_resources
                + audit.offending_tables
                + audit.offending_columns
                + audit.offending_events
                + (("S-264 verdict no longer defers "
                    "cleanly",)
                   if not audit.verdict_deferred_cleanly
                   else ())
                + (("API contract no longer ratifies",)
                   if not audit.contract_ratified else ()))
            parts.append(
                "<p>Checked, and not clean: the "
                "refusal no longer holds as stated -- "
                f"{escape_html_text(found)} -- and "
                "that is a defect against S-265, to "
                "be fixed where it lies.</p>")
    parts.append(
        "<p>The full verdict lives in "
        "docs/PACKAGE_VERDICT.md (S-264); this "
        "refusal's own record is "
        "docs/REGISTRY_CORE.md.</p>")
    return "\n".join(parts)
