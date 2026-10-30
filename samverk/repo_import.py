"""Import by clone URL (S-069).

Any public git address becomes a Samverk repository: the
bytes arrive by a real `git clone --bare` through S-014's
dedicated remote-clone seam, and the metadata row is written
only after the clone has landed — creation is all-or-nothing
exactly as in S-049 (a failed clone leaves no directory and
no row; a failed row write removes the cloned directory).

Private imports take a **token through the credential seam**:
the caller hands the token to this service, the service
hands it to the clone seam's askpass environment, and it is
never stored, never audited, never placed in the URL or in
an error message. The audit row and every refusal name only
the source **host** — enough for an operator to recognise
the import, useless to anyone hunting a credential.

The address law itself lives with the seam
(`proc.validate_remote_url`): remote schemes only, no local
paths, no `file:`/`ext::` transports, no credentials inside
the URL.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from .accounts import AccountStore
from .audit import AuditLog
from .platform_seam import ensure_dir
from .proc import ProcRefused, run_git_clone_remote, run_git_in, validate_remote_url
from .repo_paths import RepoPathError
from .repositories import (
    DEFAULT_BRANCH,
    Repository,
    RepositoryError,
    RepositoryStore,
    _validate_description,
    _validate_visibility,
    canonical_owner_repo,
)


class ImportError_(ValueError):
    """An import refusal; `reason` is a stable code. (The
    trailing underscore keeps the name from shadowing the
    builtin exception in reader's eyes — callers import it
    as `RepoImportError`.)"""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


RepoImportError = ImportError_


class ImportService:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time,
                 clone_timeout: float = 120.0):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._now = time_fn
        self._clone_timeout = clone_timeout

    def import_repository(
        self, actor_user_id: int, owner: object, repo: object, url: object,
        *, description: str = "", visibility: str = "private",
        token: str | None = None,
        source_ip: str | None = None,
    ) -> Repository:
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise RepoImportError("no_such_user", "No such account.")
        owner_disp, owner_lower, repo_disp, repo_lower = canonical_owner_repo(
            owner, repo)
        if actor.username_lower != owner_lower:
            raise RepoImportError(
                "not_repo_owner",
                "Only the owner account can import its repositories.")
        description = _validate_description(description)
        visibility = _validate_visibility(visibility)
        try:
            url = validate_remote_url(url)
        except ProcRefused as exc:
            raise RepoImportError("clone_url_invalid", str(exc)) from None
        source_host = urlparse(url).hostname or ""
        if self._repos.get_repository(owner_lower, repo_lower) is not None:
            raise RepoImportError(
                "repo_taken", f"{owner_disp}/{repo_disp} already exists.")
        try:
            path = self._repos.path_for(owner_disp, repo_disp)
        except RepoPathError as exc:
            raise RepositoryError("repo_invalid", str(exc)) from None
        if path.exists():
            raise RepoImportError(
                "repo_path_exists",
                "A directory already exists at that repository's path; "
                "refusing to adopt it silently.")
        ensure_dir(path.parent)
        try:
            result = run_git_clone_remote(
                url, path, timeout=self._clone_timeout, token=token)
        except Exception:
            shutil.rmtree(path, ignore_errors=True)
            raise RepoImportError(
                "clone_failed",
                f"git could not clone a repository from {source_host}.") \
                from None
        if result.returncode != 0:
            shutil.rmtree(path, ignore_errors=True)
            raise RepoImportError(
                "clone_failed",
                f"git could not clone a repository from {source_host}.")
        default_branch = self._cloned_default_branch(path)
        now = int(self._now())
        try:
            with self._conn:  # commits before the answer
                cur = self._conn.execute(
                    "INSERT INTO repositories (owner, owner_lower, name,"
                    " name_lower, created_by, created_at, description,"
                    " visibility, default_branch)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (owner_disp, owner_lower, repo_disp, repo_lower,
                     actor.id, now, description, visibility, default_branch))
        except sqlite3.IntegrityError:
            shutil.rmtree(path, ignore_errors=True)
            raise RepoImportError(
                "repo_taken", f"{owner_disp}/{repo_disp} already exists.") \
                from None
        created = self._repos.get_by_id(int(cur.lastrowid))
        assert created is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.create", target_kind="repo",
                target_id=created.full_name, outcome="success",
                source_ip=source_ip,
                detail={"visibility": created.visibility,
                        "import": "clone", "source_host": source_host})
        return created

    @staticmethod
    def _cloned_default_branch(path: Path) -> str:
        """The branch the clone's HEAD names, or the standard
        default when the source repository is empty."""
        try:
            result = run_git_in(path, ["symbolic-ref", "HEAD"], timeout=15.0)
        except Exception:
            return DEFAULT_BRANCH
        if result.returncode != 0:
            return DEFAULT_BRANCH
        ref = result.stdout.decode("utf-8", "replace").strip()
        prefix = "refs/heads/"
        if ref.startswith(prefix) and len(ref) > len(prefix):
            return ref[len(prefix):]
        return DEFAULT_BRANCH
