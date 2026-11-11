"""Storage accounting (S-268).

S-058 taught Samverk to measure a repository: the
bare directory walked file by file -- git objects,
LFS objects, and everything else -- and shown to
owners and admins. S-068 put a quota on that
number, enforced at receive time. But a repository
holds more than its bare directory now: S-259's
release assets live under
``<data_root>/release-assets/`` and S-266's CI
artifacts under ``<data_root>/ci-artifacts/`` --
outside the walk, so outside the accounting and
outside the quota. A repository could hold
gigabytes of assets and artifacts while its
measured size -- and its quota -- saw none of it.

This slice joins them, under four laws:

- **One number, measured the same way
  everywhere.** A repository's storage is S-058's
  walk (git objects + LFS + other, read from
  `samverk.repo_size.measure_path`, never
  re-walked here) plus the release-asset bytes
  plus the CI-artifact bytes. The upload stores'
  bytes are counted from their standing rows:
  each row's `size` is the measured size
  `inspect_upload` proved at promotion (S-012),
  so the count is measured, never estimated.
  Bytes are content-addressed, and each store is
  counted at its own disk layout: artifacts
  share one file per digest within a repository,
  so a digest is counted once however many rows
  name it; release assets share one file per
  digest within a release, so a digest is
  counted once per release that holds it. The
  report keeps every category separate -- git,
  LFS, other, release assets, artifacts -- and
  the categories always sum to the total.
- **S-068-style quotas, on the joined number.**
  The quota itself is S-068's and no other: the
  per-repository quota wins, the instance default
  applies next, otherwise the repository is
  unlimited (`QuotaService.effective_quota` is
  the one judge; no second quota store stands
  here). What changes is the usage judged
  against it: `check_upload` / `enforce_upload`
  judge an incoming release-asset or artifact
  upload against the *joined* total, as a
  decision object first and an exception second,
  exactly S-068's shape, with a refusal message
  that says in plain numbers how much the
  repository holds, what its limit is, and how
  much the upload tried to add. S-068's own
  receive-time gate is untouched: it still
  guards pushes with the S-058 number it has
  always used, and S-354 will widen the surfaces;
  this slice gives the upload stores the same
  style of gate on the honest total.
- **Standing rows are the account.** An artifact
  past its retention stamp still counts until
  S-267's sweep removes its row and its bytes
  together -- until then the bytes are on disk
  and the accounting says so. A deleted asset or
  artifact stops counting the moment its row
  goes. Nothing is cached and nothing is
  projected: every report reads the walk and the
  rows as they stand.
- **Owners and admins only** (S-058's law,
  restated): anyone else is refused
  `permission_denied`, and a private repository's
  storage never leaks to a stranger. Reading
  appends no audit entry and takes no taxonomy
  verb -- accounting is a measurement, not an
  act: 133 events stand (33 auth / 87 repo /
  13 admin), as at S-267. No migration: the
  report reads the rows migrations 102 and 105
  already keep (schema 105 stands).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .escaping import escape_html_text
from .repo_quotas import QuotaService
from .repo_size import measure_path
from .repositories import Repository, RepositoryStore

# The upload stores this accounting joins, and the
# grouping that matches each store's disk layout:
# a digest's bytes are counted once per group.
_STORES = {
    "release": ("release_assets", "release_id, sha256"),
    "artifact": ("ci_artifacts", "sha256"),
}

__all__ = [
    "StorageAccounting", "StorageDecision", "StorageError",
    "StorageReport", "decide_storage", "render_storage_page",
    "storage_to_dict", "storage_words", "validate_incoming",
    "validate_store",
]


class StorageError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class StorageReport:
    """One repository's whole storage account:
    S-058's three walked categories, the two
    upload stores (bytes counted once per shared
    file, with the standing row count and the
    shared-file count kept beside them), and the
    S-068 quota the total stands against."""
    full_name: str
    git_objects_bytes: int
    lfs_bytes: int
    other_bytes: int
    release_assets_bytes: int
    release_asset_count: int
    release_asset_files: int
    artifacts_bytes: int
    artifact_count: int
    artifact_files: int
    quota_bytes: int | None       # None = unlimited

    @property
    def repo_bytes(self) -> int:
        """S-058's number: the bare directory."""
        return (self.git_objects_bytes + self.lfs_bytes
                + self.other_bytes)

    @property
    def uploads_bytes(self) -> int:
        """The joined stores: releases + artifacts."""
        return self.release_assets_bytes + self.artifacts_bytes

    @property
    def total_bytes(self) -> int:
        return self.repo_bytes + self.uploads_bytes

    @property
    def headroom_bytes(self) -> int | None:
        """Bytes left under the quota (None when
        unlimited; never negative)."""
        if self.quota_bytes is None:
            return None
        return max(0, self.quota_bytes - self.total_bytes)

    @property
    def over_quota(self) -> bool:
        return (self.quota_bytes is not None
                and self.total_bytes > self.quota_bytes)


@dataclass(frozen=True)
class StorageDecision:
    """Would one upload keep the repository in
    quota? A decision object first (surfaces show
    the state before an upload), exactly S-068's
    `ReceiveDecision` shape."""
    allowed: bool
    full_name: str
    store: str
    usage_bytes: int
    quota_bytes: int | None       # None = unlimited
    incoming_bytes: int
    message: str


def validate_store(value: object) -> str:
    if value not in _STORES:
        raise StorageError(
            "store_invalid",
            "A storage upload names its store: "
            "'release' or 'artifact'.")
    return str(value)


def validate_incoming(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StorageError(
            "incoming_invalid",
            "An incoming size is a whole number of bytes, zero or more.")
    return value


def decide_storage(full_name: str, store: str, usage_bytes: int,
                   quota_bytes: int | None,
                   incoming_bytes: int) -> StorageDecision:
    """The pure judgement: does accepting
    `incoming_bytes` into `store` keep the
    repository at or under its quota? At the
    limit exactly is allowed; one byte over is
    refused, with the plain-numbers message."""
    if quota_bytes is None:
        return StorageDecision(
            allowed=True, full_name=full_name, store=store,
            usage_bytes=usage_bytes, quota_bytes=None,
            incoming_bytes=incoming_bytes,
            message=f"{full_name} has no quota; "
                    f"it currently holds {usage_bytes} bytes.")
    if usage_bytes + incoming_bytes <= quota_bytes:
        return StorageDecision(
            allowed=True, full_name=full_name, store=store,
            usage_bytes=usage_bytes, quota_bytes=quota_bytes,
            incoming_bytes=incoming_bytes,
            message=f"{full_name} holds {usage_bytes} of "
                    f"{quota_bytes} bytes; this upload adds "
                    f"{incoming_bytes}.")
    return StorageDecision(
        allowed=False, full_name=full_name, store=store,
        usage_bytes=usage_bytes, quota_bytes=quota_bytes,
        incoming_bytes=incoming_bytes,
        message=(
            f"Storage quota exceeded for {full_name}: "
            f"it holds {usage_bytes} bytes of its {quota_bytes}-byte "
            f"quota, and this upload adds {incoming_bytes} bytes. "
            "Remove or shrink content, or ask the repository's "
            "owner or a site admin to raise the quota."))


def storage_to_dict(report: StorageReport) -> dict:
    return {
        "full_name": report.full_name,
        "git_objects_bytes": report.git_objects_bytes,
        "lfs_bytes": report.lfs_bytes,
        "other_bytes": report.other_bytes,
        "repo_bytes": report.repo_bytes,
        "release_assets_bytes": report.release_assets_bytes,
        "release_asset_count": report.release_asset_count,
        "release_asset_files": report.release_asset_files,
        "artifacts_bytes": report.artifacts_bytes,
        "artifact_count": report.artifact_count,
        "artifact_files": report.artifact_files,
        "uploads_bytes": report.uploads_bytes,
        "total_bytes": report.total_bytes,
        "quota_bytes": report.quota_bytes,
        "headroom_bytes": report.headroom_bytes,
        "over_quota": report.over_quota,
    }


def storage_words(report: StorageReport) -> str:
    """One repository's account in plain words."""
    quota = ("no quota" if report.quota_bytes is None
             else f"of a {report.quota_bytes}-byte quota")
    return (
        f"{report.full_name} holds {report.total_bytes} bytes "
        f"({quota}): {report.git_objects_bytes} git objects, "
        f"{report.lfs_bytes} LFS, {report.other_bytes} other, "
        f"{report.release_assets_bytes} in "
        f"{report.release_asset_count} release assets, "
        f"{report.artifacts_bytes} in "
        f"{report.artifact_count} CI artifacts.")


class StorageAccounting:
    """The joined account: S-058's walk plus the
    release-asset and CI-artifact stores, judged
    against S-068's one quota."""

    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 quotas: QuotaService | None = None):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._quotas = quotas or QuotaService(
            conn, self._data_root, accounts, repositories)

    # -- gates -------------------------------------------------
    def _authorised_repo(self, actor_user_id: int, owner,
                         repo) -> Repository:
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise StorageError("no_such_user", "No such account.")
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise StorageError("no_such_repo", "No such repository.")
        if not (actor.is_admin
                or actor.username_lower == current.owner_lower):
            raise StorageError(
                "permission_denied",
                "Repository storage is shown to owners and admins.")
        return current

    def _repo(self, owner, repo) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise StorageError("no_such_repo", "No such repository.")
        return current

    # -- measurement --------------------------------------------
    def _store_account(self, repo_id: int,
                       store: str) -> tuple[int, int, int]:
        """(bytes, standing rows, shared files) for
        one upload store: bytes summed once per
        content-addressed file, at the store's own
        disk grouping."""
        table, group = _STORES[store]
        row = self._conn.execute(
            f"SELECT COUNT(*) AS files,"
            f" COALESCE(SUM(size), 0) AS bytes FROM"
            f" (SELECT MAX(size) AS size FROM {table}"
            f" WHERE repo_id = ? GROUP BY {group})",
            (repo_id,)).fetchone()
        count = int(self._conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE repo_id = ?",
            (repo_id,)).fetchone()["c"])
        return int(row["bytes"]), count, int(row["files"])

    def _report(self, current: Repository) -> StorageReport:
        measured = measure_path(
            self._repos.path_for(current.owner, current.name))
        rel_bytes, rel_count, rel_files = self._store_account(
            current.id, "release")
        art_bytes, art_count, art_files = self._store_account(
            current.id, "artifact")
        return StorageReport(
            full_name=current.full_name,
            git_objects_bytes=measured.git_objects_bytes,
            lfs_bytes=measured.lfs_bytes,
            other_bytes=measured.other_bytes,
            release_assets_bytes=rel_bytes,
            release_asset_count=rel_count,
            release_asset_files=rel_files,
            artifacts_bytes=art_bytes,
            artifact_count=art_count,
            artifact_files=art_files,
            quota_bytes=self._quotas.effective_quota(
                current.owner, current.name))

    # -- reports --------------------------------------------------
    def report_for(self, actor_user_id: int, owner,
                   repo) -> StorageReport:
        return self._report(
            self._authorised_repo(actor_user_id, owner, repo))

    def reports_for_owner(self, actor_user_id: int,
                          owner) -> list[StorageReport]:
        return [self.report_for(actor_user_id, r.owner, r.name)
                for r in self._repos.list_for_owner(owner)]

    # -- upload quota gate (S-068-style) ---------------------------
    def check_upload(self, owner, repo, store: object,
                     incoming_bytes: object) -> StorageDecision:
        """Would accepting `incoming_bytes` into
        `store` ('release' or 'artifact') keep the
        repository in quota, judged on the joined
        total?"""
        current = self._repo(owner, repo)
        store_name = validate_store(store)
        incoming = validate_incoming(incoming_bytes)
        usage = self._report(current).total_bytes
        quota = self._quotas.effective_quota(
            current.owner, current.name)
        return decide_storage(
            current.full_name, store_name, usage, quota, incoming)

    def enforce_upload(self, owner, repo, store: object,
                       incoming_bytes: object) -> StorageDecision:
        """The upload gate itself: returns the
        decision when the upload fits, raises
        `StorageError` carrying the plain refusal
        message when it does not."""
        decision = self.check_upload(
            owner, repo, store, incoming_bytes)
        if not decision.allowed:
            raise StorageError("quota_exceeded", decision.message)
        return decision


def render_storage_page(report: StorageReport) -> str:
    """One repository's storage account, rendered
    in plain words with every category named --
    states in text, never colour alone. S-010
    escaped."""
    name = escape_html_text(report.full_name)
    if report.quota_bytes is None:
        quota_line = "This repository has no quota."
    elif report.over_quota:
        quota_line = (
            f"This repository is over its "
            f"{report.quota_bytes}-byte quota by "
            f"{report.total_bytes - report.quota_bytes} bytes.")
    else:
        quota_line = (
            f"This repository may hold "
            f"{report.quota_bytes} bytes; "
            f"{report.headroom_bytes} bytes remain.")
    parts = [
        f"<h1>Storage: {name}</h1>",
        f"<p>{escape_html_text(storage_words(report))}</p>",
        "<ul>",
        f"<li>Git objects: {report.git_objects_bytes} bytes</li>",
        f"<li>LFS objects: {report.lfs_bytes} bytes</li>",
        f"<li>Other repository files: {report.other_bytes} bytes</li>",
        f"<li>Release assets: {report.release_assets_bytes} bytes "
        f"in {report.release_asset_count} assets "
        f"({report.release_asset_files} files)</li>",
        f"<li>CI artifacts: {report.artifacts_bytes} bytes "
        f"in {report.artifact_count} artifacts "
        f"({report.artifact_files} files)</li>",
        f"<li>Total: {report.total_bytes} bytes</li>",
        "</ul>",
        f"<p>{escape_html_text(quota_line)}</p>",
    ]
    return "\n".join(parts)
