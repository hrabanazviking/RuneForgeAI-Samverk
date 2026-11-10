"""Package registry verdict -- deferred, with
reasons (S-264).

Research file 26's study concludes which
ecosystems, if any, Samverk hosts: decided by
village need, recorded with reasons. This slice
is that conclusion, as a complete slice: the
verdict is data, the reasons are stated, the five
candidate ecosystems research 26's ranking names
or implies are judged one by one, and the
invariants a future registry must not break are
recorded here and in docs/PACKAGE_VERDICT.md --
the seam S-265 documents if the registry stays
out, and the law S-265 builds under if a future
verdict ever lets one ecosystem in.

- **The verdict is DEFER.** No ecosystem is
  hosted now. Not build: the roadmap's own
  decider is village need, and no village project
  has measured one -- Samverk itself is
  stdlib-first with zero admitted dependencies
  (S-017), nothing in the village publishes or
  installs private packages, and the distribution
  need that does exist is already served by the
  banked release machinery (S-257..S-263:
  releases, assets under caps, checksums, the
  signing seam) with CI artifacts next
  (S-266/S-267). Not refuse: research 26 ranks
  Python first among the candidates, the village
  is a Python village, and a private-index need
  could honestly arrive -- so Python stands as
  the named first candidate in
  ``REOPEN_CONDITIONS``, and one ecosystem
  (OCI containers) is refused outright, on the
  standing no-Docker law, while the rest defer.
- **Deferral is not an endpoint.** There is no
  registry route, no package table and no publish
  or fetch act: a request to use a registry today
  is answered by the pure
  ``decide_registry_request`` -- a deferred
  ecosystem is refused ``registry_deferred``, the
  refused ecosystem ``registry_refused``, an
  ecosystem the releases or the git transport
  already serve is answered with that standing
  service (``registry_served_by_releases`` /
  ``registry_served_by_git``), and a shapeless or
  unknown request is ``registry_request_invalid``
  / ``registry_ecosystem_unknown``. The audit
  below proves the absence against the live
  instance -- no table, column or audit event
  carries a package registry -- and the battery
  plants a registry-shaped table to prove the
  audit would catch one arriving by a back door.
- **What a future registry must not break is
  stated now, while deferring is cheap.**
  ``MUST_NOT_BREAK`` states eight invariants,
  each grounded in a standing slice's law:
  namespace ownership judged by S-190 exactly as
  repository permissions are, published versions
  immutable and deduplicated without leaking a
  private package's existence, private
  indistinguishable from missing on fetch, a
  digest never spoken of as identity or
  provenance (research 26's honest limit),
  quarantine and validation before an upload is
  visible, deletion leaving a tombstone and
  storage accounting counting registry bytes,
  an offline export path proven before any
  ecosystem is declared hosted, and publish and
  fetch witnessed exactly as release acts are.
- **A pure read, like S-202, S-237 and S-253.**
  This module holds no store, writes no row and
  audits nothing: a verdict about a registry
  that does not exist changes nothing by being
  read. No migration (schema stays 104), no
  taxonomy event (131 stand: 33 auth / 85 repo /
  13 admin). The full reasoning also lives in
  docs/PACKAGE_VERDICT.md, where a person who
  never opens this module can read it.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import taxonomy
from .escaping import escape_html_text

__all__ = [
    "ECOSYSTEMS", "MUST_NOT_BREAK", "REASONS",
    "REOPEN_CONDITIONS", "VERDICT",
    "EcosystemAssessment", "PackageVerdictAudit",
    "PackageVerdictError", "VerdictInvariant",
    "VerdictReason", "audit_package_verdict",
    "attempt_registry_action", "decide_registry_request",
    "get_ecosystem", "get_invariant", "get_reason",
    "render_package_verdict_page",
]

VERDICT = "deferred"


class PackageVerdictError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class VerdictReason:
    """One reason the verdict is defer: a stable
    id, the plain title a reader sees, and the
    reasoning in full."""
    id: str
    title: str
    detail: str


REASONS: tuple[VerdictReason, ...] = (
    VerdictReason(
        id="no-measured-village-need",
        title="No village need has been measured",
        detail=(
            "The roadmap makes village need the "
            "decider, and none has been shown. "
            "Samverk itself is stdlib-first with "
            "zero admitted dependencies (S-017's "
            "register is empty and its battery "
            "proves it), no village project "
            "publishes a private package or "
            "installs from a private index, and "
            "research 26's own method is to rank "
            "candidate ecosystems by actual project "
            "need -- a ranking with no measured "
            "need at the top of it hosts nothing "
            "yet, honestly.")),
    VerdictReason(
        id="releases-already-serve-distribution",
        title="Releases already serve the distribution that exists",
        detail=(
            "The one distribution need the village "
            "demonstrably has -- handing a reader a "
            "versioned file whose bytes they can "
            "check -- already stands banked and "
            "repo-linked: releases binding a tag "
            "and notes (S-257), assets under "
            "per-asset caps with counted downloads "
            "(S-259), a generated sha256 checksums "
            "file (S-260) and the detached-signature "
            "seam (S-263), with CI artifacts tied "
            "to commits next (S-266/S-267). A "
            "registry would duplicate that road "
            "under ecosystem protocols, not open a "
            "new one.")),
    VerdictReason(
        id="each-ecosystem-is-its-own-surface",
        title="Each ecosystem is its own permanent surface",
        detail=(
            "Research 26's first finding is that "
            "registries are not one feature: a "
            "Python wheel, an OCI manifest and an "
            "npm package carry different metadata, "
            "signing, upload and dependency "
            "semantics, and each ecosystem hosted "
            "is a permanent protocol surface with "
            "its own threat list -- namespace "
            "confusion across organizations, "
            "malicious overwrite of a published "
            "version, enormous metadata, compression "
            "bombs and cross-tenant download "
            "caches. Research 26's warning stands: "
            "a smaller, proven registry beats a "
            "nominal menu of insecure formats, and "
            "a menu of zero, until need names one, "
            "is smaller still.")),
    VerdictReason(
        id="trust-machinery-not-yet-standing",
        title="The trust machinery a registry needs is not standing yet",
        detail=(
            "Research 26 requires, before hosting: "
            "namespace ownership, immutable version "
            "digests, authenticated publishing, "
            "quotas, deletion tombstones, download "
            "authorization, content-addressed "
            "storage and quarantine until validation "
            "completes. Samverk's pieces are young: "
            "storage accounting does not join "
            "releases and artifacts until S-268, "
            "and S-263's signing seam has no "
            "verifier standing yet (its honest "
            "language today is unverified). A "
            "registry shipped ahead of its trust "
            "machinery would invert Samverk's "
            "security-first founding order -- and "
            "research 26 is explicit that a digest "
            "is not an author identity or a build "
            "provenance, however it is displayed.")),
    VerdictReason(
        id="village-scale-simplicity",
        title="Village scale rewards the simpler forge",
        detail=(
            "Samverk is a sovereign forge for "
            "instances its people run themselves, "
            "stdlib-first, with dependencies "
            "admitted one at a time for a written "
            "reason. A package registry is the "
            "storage- and bandwidth-heaviest face a "
            "forge can grow: every published version "
            "is kept forever by design, on village "
            "hardware, beside the repositories "
            "themselves. That weight is worth "
            "carrying the day a village project "
            "needs it; carried on speculation, it "
            "is weight taken from the forge the "
            "village already uses.")),
)


@dataclass(frozen=True)
class EcosystemAssessment:
    """One candidate ecosystem, judged on its own:
    what hosting it would mean, what the village
    need for it is today, what serves that need
    instead (if anything), and the judgement for
    that ecosystem."""
    id: str
    title: str
    hosting_means: str
    village_need: str
    served_by: str
    judgement: str


ECOSYSTEMS: tuple[EcosystemAssessment, ...] = (
    EcosystemAssessment(
        id="python",
        title="Python packages (wheels and sdists)",
        hosting_means=(
            "A PEP 503/691 simple index with "
            "authenticated upload: project names "
            "normalized and namespaced, wheels and "
            "sdists stored by digest, pip and uv "
            "as the clients."),
        village_need=(
            "The strongest candidate, and research "
            "26 ranks it first: the village is a "
            "Python village and Samverk itself is a "
            "Python project. But its measured need "
            "today is zero -- Samverk is stdlib-first "
            "with no admitted dependencies, and no "
            "village project publishes a private "
            "Python package or installs one in CI."),
        served_by=(
            "Release assets (S-259): the village's "
            "Python work ships as versioned source "
            "archives and wheels attached to "
            "releases, checksummed by S-260."),
        judgement="deferred-first-candidate"),
    EcosystemAssessment(
        id="generic-archives",
        title="Container-less archives (generic files)",
        hosting_means=(
            "A generic package store: named, "
            "versioned files of any type, published "
            "and fetched under a namespace, outside "
            "the release shape."),
        village_need=(
            "Real but already met: handing out "
            "versioned archives is exactly the "
            "distribution the village uses today."),
        served_by=(
            "Releases themselves (S-257..S-263): "
            "a release binds a tag, title and notes "
            "to assets under caps, with a generated "
            "checksums file, download counts and "
            "the signing seam -- repo-linked "
            "permissions included, which a generic "
            "store would have to rebuild."),
        judgement="served-by-releases"),
    EcosystemAssessment(
        id="javascript",
        title="JavaScript packages (npm)",
        hosting_means=(
            "An npm-protocol registry: scoped and "
            "unscoped names, tarballs by digest, "
            "dist-tags and npm's own token model "
            "reconciled with the forge's."),
        village_need=(
            "None measured: no village project is "
            "a JavaScript package, the forge's own "
            "web surface is server-rendered, and "
            "research 26 names JavaScript only as "
            "a candidate to rank by need -- the "
            "ranking finds no need to rank."),
        served_by=(
            "Nothing, because nothing needs "
            "serving; release assets would carry a "
            "tarball today if one ever had to move."),
        judgement="deferred"),
    EcosystemAssessment(
        id="oci-containers",
        title="Container images (OCI)",
        hosting_means=(
            "An OCI distribution registry: manifests "
            "and layers by digest, tag mutation "
            "rules, and container tooling as the "
            "publishing and pulling clients."),
        village_need=(
            "None, and none coming by standing law: "
            "the village runs no Docker, ever -- "
            "Volmarr's standing rule for every one "
            "of his machines is native installs "
            "only -- so there is no container "
            "workload for an OCI registry to serve."),
        served_by=(
            "Nothing, by design: the workloads an "
            "OCI registry would distribute are run "
            "natively in this village instead."),
        judgement="refused"),
    EcosystemAssessment(
        id="go-modules",
        title="Go modules",
        hosting_means=(
            "A module proxy or index speaking the "
            "Go module protocol: version queries, "
            "info and mod files, zips by version."),
        village_need=(
            "None measured -- and structurally the "
            "least necessary of all: Go modules are "
            "fetched from version-control tags by "
            "design, so a Go module published from a "
            "Samverk repository is already fetchable "
            "through the forge's own git transports "
            "with no registry standing between."),
        served_by=(
            "The git transports themselves: a tag "
            "on a readable repository is a Go "
            "module version, judged by the same "
            "permissions as the repository."),
        judgement="served-by-git"),
)


@dataclass(frozen=True)
class VerdictInvariant:
    """One thing a future registry must not break:
    a stable id, the standing slice or law it is
    grounded in, and the invariant stated."""
    id: str
    ground: str
    title: str
    statement: str


MUST_NOT_BREAK: tuple[VerdictInvariant, ...] = (
    VerdictInvariant(
        id="namespace-follows-permissions",
        ground="S-190",
        title="Namespace ownership is repository permission, judged by S-190",
        statement=(
            "A package namespace belongs to the "
            "repository or organization it is linked "
            "to, and publishing is judged by S-190's "
            "permission engine exactly as the linked "
            "repository's acts are judged. There is "
            "no registry-only ownership, no namespace "
            "squatting apart from forge permissions, "
            "and no publish road around the engine "
            "that guards the repository itself.")),
    VerdictInvariant(
        id="versions-are-immutable",
        ground="research 26",
        title="A published version's bytes never change",
        statement=(
            "Publishing fixes a version's bytes and "
            "their digest. Replacing a published "
            "version is refused, always -- research "
            "26 names malicious overwrite of the "
            "same version as a core failure mode -- "
            "and a corrected package is a new "
            "version. Byte-identical files deduplicate "
            "by digest, and deduplication never leaks "
            "that a private package exists.")),
    VerdictInvariant(
        id="private-is-missing-on-fetch",
        ground="S-190",
        title="Private is indistinguishable from missing, on fetch too",
        statement=(
            "A fetch naming a private or unreadable "
            "package answers exactly as a fetch "
            "naming nothing: the uniform not-found, "
            "extended to downloads and to existence "
            "checks. Download authorization is "
            "judged per package through the linked "
            "repository's visibility, and no cache, "
            "index page or error may confirm what "
            "the caller may not read.")),
    VerdictInvariant(
        id="digest-is-not-identity",
        ground="research 26",
        title="A digest proves bytes, never identity or provenance",
        statement=(
            "A package digest proves the bytes are "
            "the bytes that were published -- nothing "
            "more. Research 26's honest limit is "
            "recorded as law: a digest is not an "
            "author identity and not trustworthy "
            "build provenance, and no page may speak "
            "of it as either. Trust language for "
            "packages follows the honest words of "
            "the signing seam (S-263) and the commit "
            "badges (S-305): the signer named, the "
            "verification state said plainly.")),
    VerdictInvariant(
        id="quarantine-before-visible",
        ground="research 26",
        title="No upload is visible until validation completes",
        statement=(
            "An upload lands in quarantine and "
            "becomes fetchable only after size, "
            "checksum and manifest validation "
            "complete, under caps judged before the "
            "body is read for meaning -- enormous "
            "metadata and compression bombs are "
            "refused in quarantine, never after "
            "publication. A failed validation "
            "publishes nothing and witnesses the "
            "refusal like any other refused act.")),
    VerdictInvariant(
        id="deletion-leaves-a-tombstone",
        ground="S-268",
        title="Deletion leaves a tombstone, and storage accounting counts the bytes",
        statement=(
            "Deleting a package or a version leaves "
            "a tombstone carrying its name, version "
            "and digest: the name cannot be silently "
            "reused for different bytes, and a fetch "
            "of the deleted version answers with the "
            "tombstone's fact, not a fresh not-found "
            "that invites republication. Registry "
            "bytes join the instance's storage "
            "accounting and quotas (S-268's road) "
            "from the first ecosystem, not as a "
            "later reconciliation.")),
    VerdictInvariant(
        id="export-or-it-does-not-ship",
        ground="research 26",
        title="Offline export is proven before any ecosystem is declared hosted",
        statement=(
            "No ecosystem is declared hosted until "
            "research 26's acceptance is met for it: "
            "entire package versions export and "
            "import with their manifests, and an "
            "example package installs offline from "
            "the export. A release must never become "
            "unrecoverable because registry metadata "
            "lived only in one machine's database.")),
    VerdictInvariant(
        id="publish-and-fetch-are-witnessed",
        ground="S-257",
        title="Publish and fetch are witnessed like release acts",
        statement=(
            "Publishing, deleting and fetching a "
            "package are witnessed in the audit log "
            "with the same honesty as S-257's "
            "release acts -- the actor, the package, "
            "the version and the digest -- and a "
            "registry surface invents no unwitnessed "
            "act. What the web, the API and the "
            "ecosystem's own clients do is one act "
            "through one store, witnessed once.")),
)

REOPEN_CONDITIONS: tuple[str, ...] = (
    "A village project names a concrete private-"
    "package need that release assets cannot serve "
    "-- for example an install step in CI that must "
    "resolve a private Python package by name -- "
    "and states it with its own workload.",
    "The reopened verdict considers one ecosystem "
    "only, Python first (research 26's ranking and "
    "the village's own language), proven small and "
    "secure before any second ecosystem is "
    "discussed: the smaller, proven registry "
    "research 26 asks for, never a menu.",
    "The trust machinery the invariants require "
    "already stands: the signing seam's verifier "
    "(the S-305 line), S-268's storage accounting, "
    "and a quarantine-and-validation design judged "
    "against research 26's threat list.",
    "The successor roadmap revisits the verdict: "
    "S-403 already names refused and deferred "
    "items among what its seed reconsiders, and a "
    "reopened verdict is decided there, on the "
    "evidence above, not by drift.",
)


def get_reason(reason_id: object) -> VerdictReason:
    """One deferral reason by its id. An unknown
    id is refused reason_unknown -- the verdict
    does not invent a reason to answer with."""
    for reason in REASONS:
        if reason.id == reason_id:
            return reason
    raise PackageVerdictError(
        "reason_unknown", "No such verdict reason "
        "is stated.")


def get_ecosystem(ecosystem_id: object) -> EcosystemAssessment:
    """One assessed ecosystem by its id. An unknown
    id is refused ecosystem_unknown."""
    for ecosystem in ECOSYSTEMS:
        if ecosystem.id == ecosystem_id:
            return ecosystem
    raise PackageVerdictError(
        "ecosystem_unknown", "No such ecosystem was "
        "assessed.")


def get_invariant(invariant_id: object) -> VerdictInvariant:
    """One must-not-break invariant by its id. An
    unknown id is refused invariant_unknown."""
    for invariant in MUST_NOT_BREAK:
        if invariant.id == invariant_id:
            return invariant
    raise PackageVerdictError(
        "invariant_unknown", "No such invariant "
        "is recorded.")


def decide_registry_request(ecosystem: object) -> str:
    """Pure registry judgement: the answer for any
    request to publish to or fetch from a package
    registry today, naming the ecosystem asked
    for. A deferred ecosystem is refused
    ``registry_deferred``; the refused ecosystem
    ``registry_refused``; an ecosystem the banked
    releases or the git transports already serve
    is answered ``registry_served_by_releases`` /
    ``registry_served_by_git``; a shapeless
    request (not text, or no text) is
    ``registry_request_invalid`` and a worded but
    unassessed ecosystem is
    ``registry_ecosystem_unknown``."""
    if not isinstance(ecosystem, str) or not ecosystem.strip():
        return "registry_request_invalid"
    for assessed in ECOSYSTEMS:
        if assessed.id == ecosystem.strip():
            if assessed.judgement == "refused":
                return "registry_refused"
            if assessed.judgement == "served-by-releases":
                return "registry_served_by_releases"
            if assessed.judgement == "served-by-git":
                return "registry_served_by_git"
            return "registry_deferred"
    return "registry_ecosystem_unknown"


@dataclass(frozen=True)
class PackageVerdictAudit:
    """The deferral checked against one live
    instance: how much schema was inspected, and
    every registry-shaped name found in it. The
    deferral is clean only when every offender
    list is empty -- no registry table, column or
    audit event exists here."""
    verdict: str
    tables_scanned: int
    columns_scanned: int
    events_scanned: int
    offending_tables: tuple[str, ...]
    offending_columns: tuple[str, ...]
    offending_events: tuple[str, ...]

    @property
    def deferred_cleanly(self) -> bool:
        return (self.verdict == "deferred"
                and not self.offending_tables
                and not self.offending_columns
                and not self.offending_events)


def audit_package_verdict(
        conn: sqlite3.Connection) -> PackageVerdictAudit:
    """Check the deferral against the live
    instance: no table, column or audit event may
    carry a package registry -- a registry
    arriving unnamed would be the deferral broken
    by a back door. (The scan hunts the words
    package and registry; the admitted-dependency
    register of S-017 is policy data in code, not
    a hosted registry, and stores no table.)
    Pure read."""
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    offending_tables: list[str] = []
    offending_columns: list[str] = []
    columns_scanned = 0
    for table in tables:
        lowered = table.lower()
        if "package" in lowered or "registry" in lowered:
            offending_tables.append(table)
        safe = table.replace('"', '""')
        for row in conn.execute(
                f'PRAGMA table_info("{safe}")').fetchall():
            columns_scanned += 1
            column = str(row[1]).lower()
            if "package" in column or "registry" in column:
                offending_columns.append(f"{table}.{row[1]}")
    events = sorted(taxonomy.AUDIT_EVENTS)
    offending_events = [
        e for e in events
        if "package" in e.lower() or "registry" in e.lower()]
    return PackageVerdictAudit(
        verdict=VERDICT,
        tables_scanned=len(tables),
        columns_scanned=columns_scanned,
        events_scanned=len(events),
        offending_tables=tuple(offending_tables),
        offending_columns=tuple(offending_columns),
        offending_events=tuple(offending_events))


def attempt_registry_action(ecosystem: object) -> None:
    """Refuse a request to use a package registry,
    always: no ecosystem is hosted. Raises
    ``PackageVerdictError`` carrying the pure
    decision's reason; writes nothing and audits
    nothing (there is no registry event to
    write). Ecosystems the releases or the git
    transports already serve raise their standing
    service's reason, pointing the caller at the
    road that exists."""
    reason = decide_registry_request(ecosystem)
    if reason == "registry_request_invalid":
        raise PackageVerdictError(
            reason, "That registry request is not valid.")
    if reason == "registry_ecosystem_unknown":
        raise PackageVerdictError(
            reason,
            "Samverk assessed no such ecosystem: "
            "S-264 judged Python, generic archives, "
            "JavaScript, OCI containers and Go "
            "modules, and hosts none of them.")
    if reason == "registry_refused":
        raise PackageVerdictError(
            reason,
            "Samverk does not host container images: "
            "S-264 refused the OCI ecosystem, and "
            "the village runs no Docker by standing "
            "law. Workloads here are installed "
            "natively, not pulled as images.")
    if reason == "registry_served_by_releases":
        raise PackageVerdictError(
            reason,
            "There is no generic package store: "
            "S-264 found generic archives already "
            "served by releases (S-257..S-263) -- "
            "publish the file as a release asset, "
            "with its checksums, instead.")
    if reason == "registry_served_by_git":
        raise PackageVerdictError(
            reason,
            "There is no Go module registry: S-264 "
            "found Go modules already served by the "
            "git transports -- tag the module version "
            "in its repository and clients fetch it "
            "from there.")
    raise PackageVerdictError(
        reason,
        "Samverk hosts no package registry: S-264 "
        "deferred it, with reasons, and the seam a "
        "future registry must not break is recorded "
        "in docs/PACKAGE_VERDICT.md. Distribution "
        "today is by releases and their assets.")


def render_package_verdict_page(
        audit: PackageVerdictAudit | None = None) -> str:
    """The verdict, rendered: deferred said plainly,
    the reasons, the five ecosystems judged one by
    one, the must-not-break invariants with the
    ground each hangs from, the reopen conditions,
    and the checked proof when an audit rides
    along -- every value escaped through S-010, the
    state said in words, never colour-only."""
    parts = [
        "<h1>Package registry -- deferred (S-264)</h1>",
        "<p>Verdict: <strong>deferred</strong>. "
        "Samverk hosts no package registry now, for "
        "any ecosystem, and refuses one ecosystem "
        "(OCI containers) outright. There is no "
        "registry endpoint, package table or "
        "publish road; distribution is by releases "
        "and their assets. This page is the study's "
        "conclusion (research file 26), and the "
        "same words live in "
        "docs/PACKAGE_VERDICT.md.</p>",
        "<h2>Why deferred</h2>",
        "<ul>",
    ]
    for reason in REASONS:
        parts.append(
            f"<li><strong>{escape_html_text(reason.title)}"
            f"</strong>: {escape_html_text(reason.detail)}"
            "</li>")
    parts.append("</ul>")
    parts.append("<h2>The ecosystems, judged</h2>")
    parts.append("<ul>")
    for ecosystem in ECOSYSTEMS:
        parts.append(
            f"<li><strong>{escape_html_text(ecosystem.title)}"
            f"</strong> ({escape_html_text(ecosystem.judgement)}): "
            f"hosting would mean {escape_html_text(ecosystem.hosting_means)} "
            f"Village need: {escape_html_text(ecosystem.village_need)} "
            f"Served by: {escape_html_text(ecosystem.served_by)}"
            "</li>")
    parts.append("</ul>")
    parts.append(
        "<h2>What a future registry must not break</h2>")
    parts.append("<ul>")
    for invariant in MUST_NOT_BREAK:
        parts.append(
            f"<li><strong>{escape_html_text(invariant.title)}"
            f"</strong> (grounded in: "
            f"{escape_html_text(invariant.ground)}): "
            f"{escape_html_text(invariant.statement)}</li>")
    parts.append("</ul>")
    parts.append("<h2>When this verdict reopens</h2>")
    parts.append("<ul>")
    for condition in REOPEN_CONDITIONS:
        parts.append(f"<li>{escape_html_text(condition)}</li>")
    parts.append("</ul>")
    if audit is not None:
        if audit.deferred_cleanly:
            parts.append(
                "<p>Checked, not just claimed: this "
                "instance was inspected for a package "
                f"registry -- {audit.tables_scanned} "
                f"tables, {audit.columns_scanned} "
                f"columns and {audit.events_scanned} "
                "audit events -- and none was found: "
                "no registry table, column or event "
                "exists here.</p>")
        else:
            found = ", ".join(
                audit.offending_tables
                + audit.offending_columns
                + audit.offending_events)
            parts.append(
                "<p>Checked, and not clean: the "
                "deferral no longer holds as stated -- "
                f"{escape_html_text(found)} -- and "
                "that is a defect against S-264, to "
                "be fixed where it lies.</p>")
    parts.append(
        "<p>The invariants above are the seam "
        "S-265 documents: if the registry stays "
        "out, that slice is the published refusal "
        "built on this verdict; if a future verdict "
        "ever lets one ecosystem in, it builds "
        "under these invariants, not around "
        "them.</p>")
    return "\n".join(parts)
