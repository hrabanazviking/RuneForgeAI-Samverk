"""Dependency review on PRs (S-301).

Roadmap S-301: Dependency review on PRs -- a PR's
manifest changes summarised with new vulnerabilities
flagged, as a check (S-246) the branch rules can
require.

S-297 graphs a repository's manifests at its default
branch's tip; S-298 bundles the dated advisory
snapshot; S-299 joins the two into standing alerts
for the graph that stands. A pull request is none of
those: it is a proposed change, and what a reviewer
needs to know is what the change itself does to the
repository's dependency position -- which manifests
it touches, which dependencies it adds, removes or
moves, and which vulnerabilities it would newly
introduce. This slice is that review, computed over
the pull request's own recorded base and head
snapshots (the oids S-141's store stamped when the
pull request was opened), and published as a check
in S-246/S-157's one shape so a branch rule
(S-169/S-174) can require it by its standing name,
``dependency-review``.

- **The diff is per manifest, in the graph's own
  vocabulary.** Both snapshots are read through
  S-297's batch object reader and judged by S-297's
  own isolated parsers, under the graph's own limits
  and skip law: vendored and submodule manifests,
  oversized and binary manifests, and manifests whose
  text will not parse are recorded skipped by named
  reason, exactly as the graph records them. A
  dependency's identity is (manifest, ecosystem,
  normalised name, scope); a dependency present on
  both sides whose specifier, extras or marker moved
  is *changed*, one present on one side only is
  *added* or *removed*. Lockfiles are not manifests
  (S-297's law) and are not reviewed here either --
  the summary covers manifests only, and says so.
- **New means new.** A vulnerability is flagged only
  when the head side of an added or changed
  dependency matches an advisory in the standing
  snapshot (S-300's standing snapshot -- the last
  landed refresh, or S-298's bundled one where no
  refresh has landed) under S-299's own pure
  judgement, and the base side did not already match
  that same advisory. A vulnerability the base
  already carried is standing business for S-299's
  alerts, not something this pull request introduces,
  and it is never laid at the pull request's door. A
  match the change removes -- a dependency deleted,
  or moved out of the affected range -- is reported
  as resolved by the change, in words.
- **Unjudged is said, never cleared.** A specifier
  S-299's judgement cannot reach (a direct URL or
  VCS reference, a range with no judgeable shape)
  that names a
  package the snapshot carries advisories for is
  counted unjudged, and the review stands
  *incomplete*: it cannot honestly certify what it
  could not judge. A changed manifest that was
  skipped on either side, a manifest cap, or an
  unjudged new specifier each make the review
  incomplete, and an incomplete review's check is
  *failed* -- a gate that requires this check is
  never passed by a review that did not finish.
- **The check is S-246's shape, recorded through
  S-157's seam.** ``publish_check`` records one
  result under the context ``dependency-review``
  against the pull request's head commit through
  ``PullRequestChecksStore.record_result`` -- the
  same row the checks panel lists and the
  required-checks gate (S-174) reads, updated in
  place when the review is published again. The
  conclusion maps in words: *clean* and
  *no manifest changes* publish as ``passed``; *new
  vulnerabilities* and *incomplete* publish as
  ``failed``, with the one-line summary as the
  result's description. Reviewing itself is a pure
  read: it writes nothing, records nothing, and can
  be recomputed at any time -- the review is derived
  data over two git snapshots and a dated advisory
  snapshot, rebuildable like S-297's graph, so this
  slice adds no migration (schema 122 stands) and no
  audit event (134 stand: 33 auth / 88 repo /
  13 admin); the durable artefact is the check row
  itself, and docs/AUDIT_TAXONOMY.md records the
  slice on that basis.
- **Honest limits, said plainly.** The review stands
  on the pull request's recorded base and head oids;
  if the branches have moved since, a fresh review
  of the standing pull request still judges those
  recorded snapshots, and publishing again after the
  pull request is updated is the road to a current
  verdict. No network fetch is made or claimed: the
  advisory data is the instance's standing snapshot,
  whose date and age stand on every rendered surface
  (S-298's law). A head snapshot that cannot be read
  from the base repository at all (a cross-fork head
  never fetched into it) is refused by the object
  reader's own named reason, never passed over in
  silence. Reads ride S-141's seam, so a stranger to
  a private repository gets the uniform
  ``pull_request_not_found`` before any dependency
  is named. Every rendered value escapes through
  S-010, and standing is always said in words beside
  any mark -- never a colour alone.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .advisory_data import (
    SEVERITY_ORDER, AdvisoryStore, SnapshotInfo)
from .advisory_refresh import AdvisoryRefreshStore
from .dependency_alerts import judge_dependency
from .dependency_graph import (
    MAX_DEPENDENCIES_PER_MANIFEST, MAX_MANIFEST_BYTES,
    MAX_MANIFESTS_PER_REPO, DependencyGraphError,
    DependencyGraphStore, ParsedDependency, is_manifest_path,
    is_vendored_path, manifest_kind_for, parse_manifest)
from .escaping import escape_html_text
from .issues import IssueStore
from .objects import ObjectError, ObjectReader
from .pull_request_checks import (
    PullRequestCheck, PullRequestChecksStore)
from .pull_requests import PullRequestStore
from .repositories import RepositoryError, RepositoryStore

__all__ = [
    "CHECK_CONTEXT", "CONCLUSION_CLEAN", "CONCLUSION_INCOMPLETE",
    "CONCLUSION_NO_CHANGES", "CONCLUSION_VULNERABILITIES",
    "CONCLUSIONS", "DependencyReview", "DependencyReviewError",
    "DependencyReviewStore", "DepChange", "ManifestChange",
    "ManifestSnapshot", "VulnFlag", "check_state_for",
    "decide_conclusion", "diff_snapshots", "flag_vulnerabilities",
    "render_dependency_review", "render_dependency_review_page",
]

#: The check's standing name -- the context a branch
#: rule names when it requires this review, recorded
#: verbatim on the head commit through S-157's seam.
CHECK_CONTEXT = "dependency-review"

#: The review's conclusions, in words.
CONCLUSION_CLEAN = "clean"
CONCLUSION_NO_CHANGES = "no_changes"
CONCLUSION_VULNERABILITIES = "vulnerabilities_found"
CONCLUSION_INCOMPLETE = "incomplete"
CONCLUSIONS = frozenset({
    CONCLUSION_CLEAN, CONCLUSION_NO_CHANGES,
    CONCLUSION_VULNERABILITIES, CONCLUSION_INCOMPLETE})

_CONCLUSION_WORDS = {
    CONCLUSION_CLEAN: "Clean",
    CONCLUSION_NO_CHANGES: "No manifest changes",
    CONCLUSION_VULNERABILITIES: "New vulnerabilities",
    CONCLUSION_INCOMPLETE: "Incomplete",
}

#: DepChange.change / VulnFlag.change vocabularies.
ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"

_BINARY_PROBE_BYTES = 8192


class DependencyReviewError(RepositoryError):
    """A dependency-review error: a RepositoryError
    carrying `.reason`, in the house shape."""


# ------------------------------------------------------------------
# Snapshot shapes
# ------------------------------------------------------------------

@dataclass(frozen=True)
class ManifestSnapshot:
    """One manifest at one commit, as S-297's parsers
    judged it: parsed with its dependencies, partial
    under the dependency cap, or skipped by named
    reason -- the graph's own standing words."""
    path: str
    ecosystem: str
    kind: str
    status: str               # 'parsed' | 'partial' | 'skipped'
    reason: str = ""
    dependencies: tuple = ()
    blob_oid: str = ""

    @property
    def readable(self) -> bool:
        return self.status == "parsed"


@dataclass(frozen=True)
class ManifestChange:
    """One manifest the pull request touches: added,
    removed, or modified (its blob moved), with the
    standing each side's snapshot gave it."""
    path: str
    ecosystem: str
    kind: str
    change: str               # 'added' | 'removed' | 'modified'
    base_status: str          # '' when absent on that side
    head_status: str
    base_reason: str = ""
    head_reason: str = ""

    @property
    def words(self) -> str:
        return (f"{self.path} ({self.kind}) — {self.change}.")


@dataclass(frozen=True)
class DepChange:
    """One dependency the pull request moves: added,
    removed, or changed (specifier, extras or marker
    moved under the same identity)."""
    manifest_path: str
    ecosystem: str
    kind: str
    name: str
    name_key: str
    scope: str
    change: str               # 'added' | 'removed' | 'changed'
    old_specifier: str = ""   # '' when added
    new_specifier: str = ""   # '' when removed
    old: ParsedDependency | None = None
    new: ParsedDependency | None = None

    @property
    def words(self) -> str:
        if self.change == ADDED:
            return (f"{self.name} {self.new_specifier} added "
                    f"in {self.manifest_path}.")
        if self.change == REMOVED:
            return (f"{self.name} {self.old_specifier} removed "
                    f"from {self.manifest_path}.")
        return (f"{self.name} changed in {self.manifest_path}: "
                f"{self.old_specifier} -> {self.new_specifier}.")


@dataclass(frozen=True)
class VulnFlag:
    """One advisory match the pull request newly
    introduces -- or, with ``change == 'resolved'``,
    one it removes. Carries the advisory's own facts
    exactly as published."""
    manifest_path: str
    ecosystem: str
    name: str
    specifier: str            # the side the match stands on
    change: str               # 'added' | 'changed' | 'resolved'
    advisory_id: str
    severity: str
    affected: str
    fixed_version: str | None
    summary: str
    basis: str                # 'pinned' | 'range' (S-299)
    pinned_version: str = ""

    @property
    def fixed_words(self) -> str:
        if self.fixed_version is None:
            return "fix unknown"
        return "fixed in " + self.fixed_version

    @property
    def words(self) -> str:
        verb = "resolved" if self.change == "resolved" \
            else "introduced"
        return (f"{self.advisory_id} ({self.severity}) "
                f"{verb} by {self.name} {self.specifier} in "
                f"{self.manifest_path}: affected "
                f"{self.affected}, {self.fixed_words}.")


# ------------------------------------------------------------------
# The pure diff
# ------------------------------------------------------------------

def _dep_key(manifest_path: str, dep: ParsedDependency) -> tuple:
    return (manifest_path, dep.ecosystem, dep.name_key, dep.scope)


def _dep_moved(old: ParsedDependency, new: ParsedDependency) -> bool:
    return (old.specifier, old.extras, old.marker) != \
        (new.specifier, new.extras, new.marker)


def diff_snapshots(base: dict, head: dict) -> tuple:
    """The pure diff of two manifest snapshots
    (path -> ManifestSnapshot): (manifest_changes,
    dep_changes), each in path / identity order.
    Pure: no storage, no git, no snapshot data.
    Dependencies are diffed wherever the manifest
    was read on the side it stands on: an added
    manifest's dependencies are added, a removed
    manifest's are removed. A manifest skipped on
    either side contributes its manifest change and
    no dependency rows -- the review's
    incompleteness is decided by the caller from
    the manifest changes themselves."""
    manifest_changes: list[ManifestChange] = []
    dep_changes: list[DepChange] = []
    for path in sorted(set(base) | set(head)):
        before = base.get(path)
        after = head.get(path)
        if before is not None and after is not None \
                and before.blob_oid == after.blob_oid:
            continue
        if before is None:
            change = ADDED
        elif after is None:
            change = REMOVED
        else:
            change = "modified"
        standing = after if after is not None else before
        manifest_changes.append(ManifestChange(
            path=path, ecosystem=standing.ecosystem,
            kind=standing.kind, change=change,
            base_status=before.status if before else "",
            head_status=after.status if after else "",
            base_reason=before.reason if before else "",
            head_reason=after.reason if after else ""))
        if (before is not None
                and before.status == "skipped") \
                or (after is not None
                    and after.status == "skipped"):
            continue
        base_deps = {_dep_key(path, d): d
                     for d in before.dependencies} \
            if before is not None else {}
        head_deps = {_dep_key(path, d): d
                     for d in after.dependencies} \
            if after is not None else {}
        for key in sorted(set(base_deps) | set(head_deps)):
            old = base_deps.get(key)
            new = head_deps.get(key)
            if old is not None and new is not None \
                    and not _dep_moved(old, new):
                continue
            if old is None:
                dep_changes.append(DepChange(
                    manifest_path=path, ecosystem=new.ecosystem,
                    kind=after.kind, name=new.name,
                    name_key=new.name_key, scope=new.scope,
                    change=ADDED, new_specifier=new.specifier,
                    new=new))
            elif new is None:
                dep_changes.append(DepChange(
                    manifest_path=path, ecosystem=old.ecosystem,
                    kind=before.kind, name=old.name,
                    name_key=old.name_key, scope=old.scope,
                    change=REMOVED, old_specifier=old.specifier,
                    old=old))
            else:
                dep_changes.append(DepChange(
                    manifest_path=path, ecosystem=new.ecosystem,
                    kind=after.kind, name=new.name,
                    name_key=new.name_key, scope=new.scope,
                    change=CHANGED, old_specifier=old.specifier,
                    new_specifier=new.specifier,
                    old=old, new=new))
    return tuple(manifest_changes), tuple(dep_changes)


# ------------------------------------------------------------------
# The pure vulnerability judgement
# ------------------------------------------------------------------

def _advisories_for(lookup, ecosystem: str, name: str,
                    name_key: str) -> tuple:
    """Every advisory naming one dependency, under
    the snapshot's own name equivalence -- S-299's
    lookup law: the written name and the normalised
    key both asked, each advisory counted once."""
    found: list = []
    seen: set = set()
    for candidate in (name, name_key):
        for adv in lookup(ecosystem, candidate):
            if adv.id not in seen:
                seen.add(adv.id)
                found.append(adv)
    return tuple(found)


def flag_vulnerabilities(dep_changes, lookup) -> tuple:
    """Judge the diff against the advisory snapshot:
    (new_flags, resolved_flags, unjudged_count).
    ``lookup`` is AdvisoryStore.for_package's shape:
    (ecosystem, package) -> advisories. Pure but for
    that read seam: no storage is written, no alert
    is created -- standing alerts remain S-299's.
    A flag is *new* only where the head side matches
    and the base side did not; a base-side match the
    change removes is *resolved*; a head-side
    specifier no judgement could reach, where the
    snapshot carries advisories for the package,
    counts the dependency unjudged once."""
    new_flags: list[VulnFlag] = []
    resolved_flags: list[VulnFlag] = []
    unjudged = 0
    severity_rank = {name: i for i, name in
                     enumerate(SEVERITY_ORDER)}
    for change in dep_changes:
        advisories = _advisories_for(
            lookup, change.ecosystem, change.name,
            change.name_key)
        if not advisories:
            continue
        dep_unjudged = False
        for adv in advisories:
            head_verdict = None
            if change.change in (ADDED, CHANGED):
                head_verdict = judge_dependency(
                    change.ecosystem, change.new_specifier,
                    adv.affected)
                if head_verdict.unjudged:
                    dep_unjudged = True
            base_verdict = None
            if change.change in (REMOVED, CHANGED):
                base_verdict = judge_dependency(
                    change.ecosystem, change.old_specifier,
                    adv.affected)
            if head_verdict is not None and head_verdict.matched:
                if base_verdict is not None \
                        and base_verdict.matched:
                    continue  # already carried by the base
                new_flags.append(VulnFlag(
                    manifest_path=change.manifest_path,
                    ecosystem=change.ecosystem,
                    name=change.name,
                    specifier=change.new_specifier,
                    change=change.change,
                    advisory_id=adv.id, severity=adv.severity,
                    affected=adv.affected,
                    fixed_version=adv.fixed_version,
                    summary=adv.summary,
                    basis=head_verdict.basis,
                    pinned_version=head_verdict.pinned_version))
            elif base_verdict is not None \
                    and base_verdict.matched \
                    and (change.change == REMOVED
                         or (head_verdict is not None
                             and not head_verdict.unjudged)):
                resolved_flags.append(VulnFlag(
                    manifest_path=change.manifest_path,
                    ecosystem=change.ecosystem,
                    name=change.name,
                    specifier=change.old_specifier,
                    change="resolved",
                    advisory_id=adv.id, severity=adv.severity,
                    affected=adv.affected,
                    fixed_version=adv.fixed_version,
                    summary=adv.summary,
                    basis=base_verdict.basis,
                    pinned_version=base_verdict.pinned_version))
        if dep_unjudged:
            unjudged += 1

    def order(flag: VulnFlag) -> tuple:
        return (severity_rank.get(flag.severity, 99),
                flag.advisory_id, flag.manifest_path,
                flag.name)

    new_flags.sort(key=order)
    resolved_flags.sort(key=order)
    return tuple(new_flags), tuple(resolved_flags), unjudged


def decide_conclusion(manifest_changes, dep_changes,
                      new_flags, incomplete_reasons) -> str:
    """The review's conclusion, pure: incomplete
    stands first -- a review that could not finish
    certifies nothing -- then newly introduced
    vulnerabilities, then an untouched manifest set,
    then clean."""
    if incomplete_reasons:
        return CONCLUSION_INCOMPLETE
    if new_flags:
        return CONCLUSION_VULNERABILITIES
    if not manifest_changes and not dep_changes:
        return CONCLUSION_NO_CHANGES
    return CONCLUSION_CLEAN


def check_state_for(conclusion: str) -> str:
    """The conclusion in S-157's check vocabulary:
    clean and no-changes pass; new vulnerabilities
    and an incomplete review fail -- a required gate
    is never passed by a review that did not finish
    or that found new vulnerabilities."""
    if conclusion in (CONCLUSION_CLEAN, CONCLUSION_NO_CHANGES):
        return "passed"
    return "failed"


# ------------------------------------------------------------------
# The review record
# ------------------------------------------------------------------

@dataclass(frozen=True)
class DependencyReview:
    """One pull request's dependency review, whole:
    the snapshots it judged, every manifest and
    dependency change, the vulnerabilities newly
    introduced and those resolved, why the review
    stands incomplete where it does, its conclusion,
    the check state that conclusion publishes as, and
    the standing snapshot's date and age (S-298's law:
    wherever alerts are shown, the age stands)."""
    repo_id: int
    full_name: str
    number: int
    base_oid: str
    head_oid: str
    manifest_changes: tuple
    dep_changes: tuple
    new_vulnerabilities: tuple
    resolved_vulnerabilities: tuple
    unjudged: int
    incomplete_reasons: tuple
    conclusion: str
    snapshot_date: str        # '' when no snapshot stands
    age_words: str
    freshness: str

    @property
    def check_state(self) -> str:
        return check_state_for(self.conclusion)

    @property
    def conclusion_words(self) -> str:
        return _CONCLUSION_WORDS[self.conclusion]

    @property
    def added_count(self) -> int:
        return sum(1 for c in self.dep_changes
                   if c.change == ADDED)

    @property
    def removed_count(self) -> int:
        return sum(1 for c in self.dep_changes
                   if c.change == REMOVED)

    @property
    def changed_count(self) -> int:
        return sum(1 for c in self.dep_changes
                   if c.change == CHANGED)

    @property
    def summary(self) -> str:
        """The review in one sentence -- the words the
        check row carries as its description."""
        parts = [
            f"Dependency review: "
            f"{self.conclusion_words.lower()} — "
            f"{len(self.manifest_changes)} manifest(s) changed; "
            f"{self.added_count} dependencies added, "
            f"{self.changed_count} changed, "
            f"{self.removed_count} removed; "
            f"{len(self.new_vulnerabilities)} new "
            f"vulnerabilities, "
            f"{len(self.resolved_vulnerabilities)} resolved"]
        if self.unjudged:
            parts.append(
                f"{self.unjudged} new specifier(s) could not "
                f"be judged")
        if self.incomplete_reasons:
            parts.append(
                "incomplete: "
                + "; ".join(self.incomplete_reasons))
        parts.append(f"advisory snapshot: {self.age_words}")
        return "; ".join(parts) + "."

    @property
    def words(self) -> str:
        return self.summary

    def to_dict(self) -> dict:
        return {
            "repository": self.full_name,
            "pull_request": self.number,
            "base_oid": self.base_oid,
            "head_oid": self.head_oid,
            "conclusion": self.conclusion,
            "check_context": CHECK_CONTEXT,
            "check_state": self.check_state,
            "manifest_changes": [
                {"path": m.path, "kind": m.kind,
                 "change": m.change}
                for m in self.manifest_changes],
            "dependencies": {
                "added": self.added_count,
                "changed": self.changed_count,
                "removed": self.removed_count,
            },
            "new_vulnerabilities": [
                {"advisory": f.advisory_id,
                 "severity": f.severity,
                 "package": f.name,
                 "manifest": f.manifest_path,
                 "affected": f.affected,
                 "fixed_version": f.fixed_version}
                for f in self.new_vulnerabilities],
            "resolved_vulnerabilities": [
                {"advisory": f.advisory_id,
                 "severity": f.severity,
                 "package": f.name,
                 "manifest": f.manifest_path}
                for f in self.resolved_vulnerabilities],
            "unjudged": self.unjudged,
            "incomplete_reasons": list(self.incomplete_reasons),
            "snapshot_date": self.snapshot_date,
            "age_words": self.age_words,
            "freshness": self.freshness,
            "summary": self.summary,
        }


# ------------------------------------------------------------------
# The store: two snapshots in, a review (and a check) out
# ------------------------------------------------------------------

class DependencyReviewStore:
    """The S-301 review. It resolves the pull request
    through S-141's seam, reads both recorded
    snapshots through S-297's graph machinery without
    writing the graph, judges the diff against the
    standing advisory snapshot, and -- on
    ``publish_check`` -- records the verdict as a
    check through S-157's seam. It grants no
    permission of its own and writes nothing but that
    one check row."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 accounts: AccountStore,
                 issues: IssueStore,
                 advisories: AdvisoryStore | None = None,
                 *, time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._now = time_fn
        self._advisories = advisories
        self._refresh = AdvisoryRefreshStore(
            conn, time_fn=time_fn)
        self._graph = DependencyGraphStore(
            conn, repositories, accounts, time_fn=time_fn)
        self._prs = PullRequestStore(
            conn, repositories, accounts, issues, audit=None,
            time_fn=time_fn)
        self._checks = PullRequestChecksStore(
            conn, repositories, accounts, issues,
            time_fn=time_fn)

    # -- the standing snapshot ---------------------------

    def _advisory_store(self, now: object = None) -> AdvisoryStore:
        """The snapshot the review joins against: the
        one handed to the store, or the instance's
        standing snapshot through S-300's seam (the
        last landed refresh, else S-298's bundled)."""
        if self._advisories is not None:
            return self._advisories
        return self._refresh.current_store(now=now)

    def snapshot_info(self, now: object = None) -> SnapshotInfo:
        return self._advisory_store(now).snapshot_info(now)

    # -- reading one commit's manifests -------------------

    def manifests_at(self, owner: object, repo: object,
                     commit_oid: object) -> tuple:
        """Every manifest of one commit, judged by
        S-297's parsers under the graph's own limits
        and skip law, in path order. A pure read of
        git objects: the graph table is not written.
        An unreadable commit is refused by the object
        reader's own named reason."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise DependencyReviewError(
                "repo_not_found", "No such repository.")
        try:
            leaves = self._graph.snapshot(owner, repo, commit_oid)
        except DependencyGraphError as exc:
            raise DependencyReviewError(
                exc.reason, str(exc)) from None
        paths = sorted(p for p in leaves if is_manifest_path(p))
        reader = ObjectReader(
            self._repos.path_for(current.owner, current.name))
        snapshots: list[ManifestSnapshot] = []
        for index, path in enumerate(paths):
            leaf = leaves[path]
            ecosystem, kind = manifest_kind_for(path) or ("", "")
            if index >= MAX_MANIFESTS_PER_REPO:
                snapshots.append(ManifestSnapshot(
                    path=path, ecosystem=ecosystem, kind=kind,
                    status="skipped", reason="manifest_cap",
                    blob_oid=leaf.oid))
                continue
            if leaf.mode == "160000":
                snapshots.append(ManifestSnapshot(
                    path=path, ecosystem=ecosystem, kind=kind,
                    status="skipped", reason="submodule",
                    blob_oid=leaf.oid))
                continue
            if is_vendored_path(path):
                snapshots.append(ManifestSnapshot(
                    path=path, ecosystem=ecosystem, kind=kind,
                    status="skipped", reason="vendored",
                    blob_oid=leaf.oid))
                continue
            try:
                data = reader.read_blob(leaf.oid)
            except ObjectError as exc:
                raise DependencyReviewError(
                    exc.reason, str(exc)) from None
            if len(data) > MAX_MANIFEST_BYTES:
                snapshots.append(ManifestSnapshot(
                    path=path, ecosystem=ecosystem, kind=kind,
                    status="skipped", reason="oversized",
                    blob_oid=leaf.oid))
                continue
            if b"\x00" in data[:_BINARY_PROBE_BYTES]:
                snapshots.append(ManifestSnapshot(
                    path=path, ecosystem=ecosystem, kind=kind,
                    status="skipped", reason="binary",
                    blob_oid=leaf.oid))
                continue
            try:
                parsed = parse_manifest(
                    path, data.decode("utf-8", "replace"))
            except DependencyGraphError as exc:
                snapshots.append(ManifestSnapshot(
                    path=path, ecosystem=ecosystem, kind=kind,
                    status="skipped", reason=exc.reason,
                    blob_oid=leaf.oid))
                continue
            deps = parsed.dependencies
            status, reason = "parsed", ""
            if len(deps) > MAX_DEPENDENCIES_PER_MANIFEST:
                deps = deps[:MAX_DEPENDENCIES_PER_MANIFEST]
                status, reason = "partial", "dependency_cap"
            snapshots.append(ManifestSnapshot(
                path=path, ecosystem=ecosystem, kind=kind,
                status=status, reason=reason,
                dependencies=tuple(deps), blob_oid=leaf.oid))
        return tuple(snapshots)

    # -- the review ----------------------------------------

    def review_pull_request(self, viewer: User | None,
                            owner: object, repo: object,
                            number: object,
                            now: object = None) -> DependencyReview:
        """One pull request's dependency review: the
        manifest diff between its recorded base and
        head snapshots, with new vulnerabilities
        flagged against the standing advisory
        snapshot. A pure read -- writes nothing,
        records nothing. The pull request resolves
        through S-141's seam, so a stranger to a
        private repository is refused
        ``pull_request_not_found`` before any
        dependency is named."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        base_snaps = {s.path: s for s in
                      self.manifests_at(owner, repo, pr.base_oid)}
        head_snaps = {s.path: s for s in
                      self.manifests_at(owner, repo, pr.head_oid)}
        manifest_changes, dep_changes = diff_snapshots(
            base_snaps, head_snaps)
        store = self._advisory_store(now)
        new_flags, resolved_flags, unjudged = \
            flag_vulnerabilities(dep_changes, store.for_package)
        incomplete: list[str] = []
        for change in manifest_changes:
            for side, status, reason in (
                    ("base", change.base_status,
                     change.base_reason),
                    ("head", change.head_status,
                     change.head_reason)):
                if status and status != "parsed":
                    incomplete.append(
                        f"manifest {change.path} could not be "
                        f"fully read at the {side} snapshot "
                        f"({reason or status})")
        if unjudged:
            incomplete.append(
                f"{unjudged} added or changed "
                f"specifier(s) name a package with "
                f"advisories but could not be judged")
        info = store.snapshot_info(now)
        return DependencyReview(
            repo_id=pr.repo_id,
            full_name=current.full_name if current else "",
            number=pr.number, base_oid=pr.base_oid,
            head_oid=pr.head_oid,
            manifest_changes=manifest_changes,
            dep_changes=dep_changes,
            new_vulnerabilities=new_flags,
            resolved_vulnerabilities=resolved_flags,
            unjudged=unjudged,
            incomplete_reasons=tuple(incomplete),
            conclusion=decide_conclusion(
                manifest_changes, dep_changes, new_flags,
                tuple(incomplete)),
            snapshot_date=(info.snapshot_date.isoformat()
                           if info.snapshot_date else ""),
            age_words=info.age_words, freshness=info.freshness)

    def publish_check(self, viewer: User | None,
                      owner: object, repo: object,
                      number: object,
                      now: object = None
                      ) -> tuple[DependencyReview, PullRequestCheck]:
        """Review one pull request and record the
        verdict as a check (S-246) on its head commit,
        under the standing context ``dependency-review``,
        through S-157's seam: the row the checks panel
        lists and the required-checks gate reads.
        Publishing again updates that same row in
        place. Returns (review, check row)."""
        review = self.review_pull_request(
            viewer, owner, repo, number, now=now)
        check = self._checks.record_result(
            owner, repo, review.head_oid, CHECK_CONTEXT,
            review.check_state, description=review.summary)
        return review, check


# ------------------------------------------------------------------
# Rendering (S-010 escaped; words, never colour alone)
# ------------------------------------------------------------------

def render_dependency_review(review: DependencyReview) -> str:
    """One review as an HTML fragment: the snapshot's
    age banner first (S-298's law), the conclusion and
    the one-sentence summary in words, then every
    manifest change, dependency change, new
    vulnerability and resolved vulnerability. Every
    value escapes through S-010."""
    parts = [
        '<div class="dependency-review">',
        (f'<p class="advisory-age" data-freshness="'
         f'{escape_html_text(review.freshness)}">'
         f'{escape_html_text(review.age_words)}</p>'),
        (f'<p class="dependency-review-conclusion">'
         f'Dependency review for pull request '
         f'#{review.number}: '
         f'{escape_html_text(review.conclusion_words)} — '
         f'check {escape_html_text(CHECK_CONTEXT)}: '
         f'{escape_html_text(review.check_state)}.</p>'),
        (f'<p class="dependency-review-summary">'
         f'{escape_html_text(review.summary)}</p>'),
    ]
    if review.incomplete_reasons:
        items = "".join(
            f"<li>{escape_html_text(reason)}</li>"
            for reason in review.incomplete_reasons)
        parts.append(
            f'<div class="dependency-review-incomplete">'
            f'<h3>Why this review is incomplete</h3>'
            f'<ul>{items}</ul></div>')
    if review.manifest_changes:
        items = "".join(
            f"<li>{escape_html_text(m.words)}</li>"
            for m in review.manifest_changes)
        parts.append(
            f'<div class="dependency-review-manifests">'
            f'<h3>Manifest changes</h3><ul>{items}</ul></div>')
    if review.dep_changes:
        items = "".join(
            f"<li>{escape_html_text(c.words)}</li>"
            for c in review.dep_changes)
        parts.append(
            f'<div class="dependency-review-dependencies">'
            f'<h3>Dependency changes</h3><ul>{items}</ul></div>')
    if review.new_vulnerabilities:
        items = "".join(
            f"<li>{escape_html_text(f.words)} "
            f"{escape_html_text(f.summary)}</li>"
            for f in review.new_vulnerabilities)
        parts.append(
            f'<div class="dependency-review-vulnerabilities">'
            f'<h3>New vulnerabilities</h3><ul>{items}</ul></div>')
    else:
        parts.append(
            '<p class="dependency-review-vulnerabilities">'
            'No new vulnerabilities.</p>')
    if review.resolved_vulnerabilities:
        items = "".join(
            f"<li>{escape_html_text(f.words)}</li>"
            for f in review.resolved_vulnerabilities)
        parts.append(
            f'<div class="dependency-review-resolved">'
            f'<h3>Resolved by this change</h3>'
            f'<ul>{items}</ul></div>')
    parts.append("</div>")
    return "".join(parts)


def render_dependency_review_page(review: DependencyReview,
                                  title: str = "") -> str:
    """The review as a whole page, headed by the
    review's standing in words."""
    heading = title or (
        f"Dependency review — {review.full_name} "
        f"#{review.number}")
    return ("<!DOCTYPE html><html><head><title>"
            + escape_html_text(heading)
            + "</title></head><body><h1>"
            + escape_html_text(heading) + "</h1>"
            + render_dependency_review(review)
            + "</body></html>")
