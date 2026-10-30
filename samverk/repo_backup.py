"""Repository backup primitive (S-074).

One repository out of the instance, whole and restorable:

- **The bundle** — `git bundle create <file> --all`: every
  ref and its objects in a single file a stock git can clone
  from, verified after creation (`git bundle verify`) so an
  export that cannot be restored is never reported as one.
- **The metadata JSON** — the repository row (owner, name,
  description, visibility, default branch, lineage), its
  refs, its measured size, and the bundle's SHA-256 and byte
  count, so a restore can check the file it was handed
  before trusting it.

This is a *primitive*: single-repo export that Part XVII's
mirror duty and S-341's whole-instance export build on.
Scheduling, retention, and off-site transport are those
parts', not this slice's.

Export is owner-or-admin only (the S-058 shape): a backup
carries the repository's entire content, so its gate is the
strictest read gate the instance has.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .proc import run_git_in
from .refs import RefStore
from .repo_size import measure_path
from .repositories import RepositoryStore


class BackupError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class RepoExport:
    full_name: str
    bundle_path: Path
    metadata_path: Path
    bundle_sha256: str
    bundle_bytes: int
    exported_at: int


class RepoBackup:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._accounts = accounts
        self._repos = repositories
        self._now = time_fn

    def export_repo(self, actor_user_id: int, owner, repo,
                    dest_dir: Path) -> RepoExport:
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise BackupError("no_such_user", "No such account.")
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise BackupError("no_such_repo", "No such repository.")
        if not (actor.is_admin or actor.username_lower == current.owner_lower):
            raise BackupError(
                "permission_denied",
                "Repository exports are for owners and admins.")
        path = self._repos.path_for(current.owner, current.name)
        if not path.is_dir():
            raise BackupError(
                "repo_missing_on_disk",
                "The repository's disk half is missing (S-071 names "
                "this drift); there is nothing honest to export.")
        if not RefStore(path).list_refs():
            raise BackupError(
                "repo_empty",
                "This repository is empty: git bundle refuses to "
                "create an empty bundle, and an export file that "
                "restored to nothing would be a false backup. "
                "Export again after its first push.")
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        stem = f"{current.owner_lower}-{current.name_lower}"
        bundle_path = dest / f"{stem}.bundle"
        metadata_path = dest / f"{stem}.json"
        if bundle_path.exists() or metadata_path.exists():
            raise BackupError(
                "export_exists",
                "An export already sits at that destination; "
                "refusing to overwrite a backup silently.")
        result = run_git_in(
            path, ["bundle", "create", str(bundle_path), "--all"],
            timeout=300.0)
        if result.returncode != 0:
            bundle_path.unlink(missing_ok=True)
            raise BackupError(
                "bundle_failed",
                "git bundle could not export this repository: "
                + result.stderr.decode("utf-8", "replace").strip()[:200])
        verify = run_git_in(
            path, ["bundle", "verify", str(bundle_path)], timeout=120.0)
        if verify.returncode != 0:
            bundle_path.unlink(missing_ok=True)
            raise BackupError(
                "bundle_unverifiable",
                "The exported bundle did not verify; it was removed "
                "rather than reported as a backup.")
        bundle_bytes = bundle_path.read_bytes()
        digest = hashlib.sha256(bundle_bytes).hexdigest()
        refs = RefStore(path).list_refs()
        size = measure_path(path)
        now = int(self._now())
        metadata = {
            "format": "samverk-repo-export/1",
            "full_name": current.full_name,
            "owner": current.owner, "name": current.name,
            "description": current.description,
            "visibility": current.visibility,
            "default_branch": current.default_branch,
            "created_at": current.created_at,
            "fork_of_id": current.fork_of_id,
            "is_template": current.is_template,
            "template_of_id": current.template_of_id,
            "refs": {r.name: r.oid for r in refs},
            "repo_bytes": size.total_bytes,
            "bundle_file": bundle_path.name,
            "bundle_sha256": digest,
            "bundle_bytes": len(bundle_bytes),
            "exported_at": now,
        }
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        return RepoExport(
            full_name=current.full_name, bundle_path=bundle_path,
            metadata_path=metadata_path, bundle_sha256=digest,
            bundle_bytes=len(bundle_bytes), exported_at=now)
