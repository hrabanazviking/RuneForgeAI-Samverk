"""Repositories (S-049 bare creation; S-050 metadata model).

A repository is two halves that must agree: a bare git repository
on disk under S-013's traversal-proof path, and a metadata row in
SQLite (study 42: the record is ours, the bytes are git's).

- **Creation (S-049).** `create_repository` validates both name
  halves under S-013, requires the actor to be the owner account,
  runs `git init --bare` through S-014's subprocess law, and only
  then writes the metadata row — in a transaction that commits
  before the repository is answered with (Samtal's
  commit-before-answer law, so a returned repository is
  immediately visible to other connections). If the row cannot
  be written, the just-created on-disk repo is removed again:
  creation is all-or-nothing, never a half-registered repo. A
  path that already exists on disk is refused, never adopted
  silently (that is drift, and S-071's checker owns naming it).
- **Metadata (S-050).** Description, visibility (`public` /
  `private`, default `private` — security is the spine), and
  default branch live on the row. `update_metadata` is
  owner-only; a visibility change audits `repo.visibility.change`,
  other setting changes audit `repo.settings.change`. Setting
  the default branch also moves the bare repo's HEAD symbolic
  ref, so the metadata and git agree. `rename` moves the row
  and the on-disk directory together: the directory move is a
  single `os.rename` inside the one repositories root (same
  filesystem, so the move is atomic at the OS level), the row
  updates in one transaction, and if the row update fails the
  directory is moved back.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .platform_seam import ensure_dir
from .proc import run_git, run_git_in
from .repo_paths import RepoPathError, repo_path, validate_owner_name, validate_repo_name

VISIBILITIES = frozenset({"public", "private"})
DEFAULT_VISIBILITY = "private"
DEFAULT_BRANCH = "main"
DESCRIPTION_MAX = 350

_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class RepositoryError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Repository:
    id: int
    owner: str            # display case
    owner_lower: str      # canonical
    name: str             # display case (no .git suffix)
    name_lower: str       # canonical
    created_by: int
    created_at: int
    description: str = ""
    visibility: str = DEFAULT_VISIBILITY
    default_branch: str = DEFAULT_BRANCH
    fork_of_id: int | None = None   # S-055: direct upstream repo id
    is_template: bool = False       # S-064: marked as a template repo
    template_of_id: int | None = None  # S-064: template source, if any

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


def validate_branch_name(name: object) -> str:
    if (not isinstance(name, str) or not name or len(name) > 100
            or not _BRANCH_RE.match(name) or ".." in name
            or "//" in name or "@{" in name
            or name.endswith("/") or name.endswith(".")
            or name.endswith(".lock") or "//" in name):
        raise RepositoryError(
            "branch_invalid", f"That branch name is not valid: {name!r}")
    return name


def canonical_owner_repo(owner: object, repo: object) -> tuple[str, str, str, str]:
    """(owner_display, owner_lower, repo_display, repo_lower)."""
    try:
        owner_ok = validate_owner_name(owner)
        repo_ok = validate_repo_name(repo)
    except RepoPathError as exc:
        raise RepositoryError("repo_invalid", str(exc)) from None
    return owner_ok, owner_ok.lower(), repo_ok, repo_ok.lower()


def _row_to_repo(row: sqlite3.Row) -> Repository:
    keys = row.keys()
    return Repository(
        id=row["id"], owner=row["owner"], owner_lower=row["owner_lower"],
        name=row["name"], name_lower=row["name_lower"],
        created_by=row["created_by"], created_at=row["created_at"],
        description=row["description"] if "description" in keys else "",
        visibility=row["visibility"] if "visibility" in keys else DEFAULT_VISIBILITY,
        default_branch=row["default_branch"] if "default_branch" in keys else DEFAULT_BRANCH,
        fork_of_id=row["fork_of_id"] if "fork_of_id" in keys else None,
        is_template=bool(row["is_template"]) if "is_template" in keys else False,
        template_of_id=row["template_of_id"] if "template_of_id" in keys else None)


class RepositoryStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        data_root: Path,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    # -- paths ---------------------------------------------------
    def path_for(self, owner: object, repo: object) -> Path:
        return repo_path(self._data_root, owner, repo)  # S-013 law

    # -- lookups -------------------------------------------------
    def get_repository(self, owner: object, repo: object) -> Repository | None:
        try:
            _, owner_lower, _, repo_lower = canonical_owner_repo(owner, repo)
        except RepositoryError:
            return None
        row = self._conn.execute(
            "SELECT * FROM repositories WHERE owner_lower = ? AND name_lower = ?",
            (owner_lower, repo_lower)).fetchone()
        return _row_to_repo(row) if row else None

    def get_by_id(self, repo_id: int) -> Repository | None:
        row = self._conn.execute(
            "SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone()
        return _row_to_repo(row) if row else None

    def list_for_owner(self, owner: object) -> list[Repository]:
        try:
            _, owner_lower, _, _ = canonical_owner_repo(owner, "x")
        except RepositoryError:
            return []
        rows = self._conn.execute(
            "SELECT * FROM repositories WHERE owner_lower = ? ORDER BY name_lower",
            (owner_lower,)).fetchall()
        return [_row_to_repo(r) for r in rows]

    # -- S-049: creation ------------------------------------------
    def create_repository(
        self, actor_user_id: int, owner: object, repo: object,
        *, description: str = "", visibility: str = DEFAULT_VISIBILITY,
        default_branch: str = DEFAULT_BRANCH,
        source_ip: str | None = None,
    ) -> Repository:
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise RepositoryError("no_such_user", "No such account.")
        owner_disp, owner_lower, repo_disp, repo_lower = canonical_owner_repo(owner, repo)
        if actor.username_lower != owner_lower:
            raise RepositoryError(
                "not_repo_owner",
                "Only the owner account can create its repositories.")
        description = _validate_description(description)
        visibility = _validate_visibility(visibility)
        default_branch = validate_branch_name(default_branch)
        if self.get_repository(owner_lower, repo_lower) is not None:
            raise RepositoryError(
                "repo_taken", f"{owner_disp}/{repo_disp} already exists.")
        try:
            path = self.path_for(owner_disp, repo_disp)
        except RepoPathError as exc:
            raise RepositoryError("repo_invalid", str(exc)) from None
        if path.exists():
            raise RepositoryError(
                "repo_path_exists",
                "A directory already exists at that repository's path; "
                "refusing to adopt it silently.")
        ensure_dir(path.parent)
        result = run_git(
            ["init", "--bare", f"--initial-branch={default_branch}", str(path)],
            timeout=30.0)
        if result.returncode != 0:
            shutil.rmtree(path, ignore_errors=True)
            raise RepositoryError(
                "git_init_failed",
                "git could not create the repository: "
                + result.stderr.decode("utf-8", "replace").strip()[:200])
        now = int(self._now())
        try:
            with self._conn:  # commits before the answer (module docstring)
                cur = self._conn.execute(
                    "INSERT INTO repositories (owner, owner_lower, name,"
                    " name_lower, created_by, created_at, description,"
                    " visibility, default_branch)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (owner_disp, owner_lower, repo_disp, repo_lower,
                     actor.id, now, description, visibility, default_branch))
        except sqlite3.IntegrityError:
            shutil.rmtree(path, ignore_errors=True)
            raise RepositoryError(
                "repo_taken", f"{owner_disp}/{repo_disp} already exists.") from None
        created = self.get_by_id(int(cur.lastrowid))
        assert created is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.create", target_kind="repo",
                target_id=created.full_name, outcome="success",
                source_ip=source_ip,
                detail={"visibility": created.visibility})
        return created

    # -- S-050: metadata ------------------------------------------
    def update_metadata(
        self, actor_user_id: int, owner: object, repo: object, *,
        description: object = None, visibility: object = None,
        default_branch: object = None,
        source_ip: str | None = None,
    ) -> Repository:
        actor, current = self._require_owner(actor_user_id, owner, repo)
        new_description = current.description if description is None else _validate_description(description)  # type: ignore[arg-type]
        new_visibility = current.visibility if visibility is None else _validate_visibility(visibility)  # type: ignore[arg-type]
        new_branch = current.default_branch if default_branch is None else validate_branch_name(default_branch)
        if new_branch != current.default_branch:
            # HEAD moves first claim: if git refuses, metadata must not lie.
            path = self.path_for(current.owner, current.name)
            res = run_git_in(path, ["symbolic-ref", "HEAD", f"refs/heads/{new_branch}"], timeout=15.0)
            if res.returncode != 0:
                raise RepositoryError(
                    "git_head_failed",
                    "git could not move HEAD to the new default branch.")
        with self._conn:
            self._conn.execute(
                "UPDATE repositories SET description = ?, visibility = ?,"
                " default_branch = ? WHERE id = ?",
                (new_description, new_visibility, new_branch, current.id))
        if self._audit is not None:
            if new_visibility != current.visibility:
                self._audit.append(
                    actor_kind="user", actor_id=actor.id,
                    action="repo.visibility.change", target_kind="repo",
                    target_id=current.full_name, outcome="success",
                    source_ip=source_ip,
                    detail={"from": current.visibility, "to": new_visibility})
            if (new_description != current.description
                    or new_branch != current.default_branch):
                self._audit.append(
                    actor_kind="user", actor_id=actor.id,
                    action="repo.settings.change", target_kind="repo",
                    target_id=current.full_name, outcome="success",
                    source_ip=source_ip,
                    detail={"key": "metadata",
                            "description": new_description,
                            "default_branch": new_branch})
        updated = self.get_by_id(current.id)
        assert updated is not None
        return updated

    def rename(
        self, actor_user_id: int, owner: object, repo: object,
        new_name: object, *, source_ip: str | None = None,
    ) -> Repository:
        """Rename a repository: directory and row move together."""
        actor, current = self._require_owner(actor_user_id, owner, repo)
        _, _, new_disp, new_lower = canonical_owner_repo(current.owner, new_name)
        if new_lower == current.name_lower:
            if new_disp == current.name:
                raise RepositoryError("rename_same", "That is already the repository's name.")
            # Case-only rename: filesystem may be case-insensitive;
            # move via a temp name so the row and disk never diverge.
            old_path = self.path_for(current.owner, current.name)
            new_path = self.path_for(current.owner, new_disp)
            if old_path != new_path:
                tmp_path = old_path.with_name(old_path.name + ".rename-tmp")
                os.rename(old_path, tmp_path)
                try:
                    os.rename(tmp_path, new_path)
                except OSError:
                    os.rename(tmp_path, old_path)
                    raise
            with self._conn:
                self._conn.execute(
                    "UPDATE repositories SET name = ? WHERE id = ?",
                    (new_disp, current.id))
            return self._finish_rename(actor, current, source_ip)
        if self.get_repository(current.owner_lower, new_lower) is not None:
            raise RepositoryError("repo_taken", "That name is already taken in this account.")
        old_path = self.path_for(current.owner, current.name)
        new_path = self.path_for(current.owner, new_disp)
        if new_path.exists():
            raise RepositoryError(
                "repo_path_exists",
                "A directory already exists at the new name's path.")
        os.rename(old_path, new_path)  # atomic within the one root
        try:
            with self._conn:
                self._conn.execute(
                    "UPDATE repositories SET name = ?, name_lower = ? WHERE id = ?",
                    (new_disp, new_lower, current.id))
        except Exception:
            os.rename(new_path, old_path)  # roll the disk back with the row
            raise
        return self._finish_rename(actor, current, source_ip)

    def _finish_rename(self, actor, current: Repository, source_ip) -> Repository:
        renamed = self.get_by_id(current.id)
        assert renamed is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.settings.change", target_kind="repo",
                target_id=renamed.full_name, outcome="success",
                source_ip=source_ip,
                detail={"key": "rename", "from": current.full_name,
                        "to": renamed.full_name})
        return renamed

    def _require_owner(self, actor_user_id: int, owner: object, repo: object):
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise RepositoryError("no_such_user", "No such account.")
        current = self.get_repository(owner, repo)
        if current is None:
            raise RepositoryError("no_such_repo", "No such repository.")
        if actor.username_lower != current.owner_lower:
            raise RepositoryError(
                "not_repo_owner", "Only the repository's owner can change it.")
        return actor, current


def _validate_description(description: object) -> str:
    if description is None:
        return ""
    if not isinstance(description, str):
        raise RepositoryError("description_invalid", "Description must be text.")
    text = description.strip()
    if len(text) > DESCRIPTION_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise RepositoryError(
            "description_invalid",
            f"Descriptions are at most {DESCRIPTION_MAX} characters of plain text.")
    return text


def _validate_visibility(visibility: object) -> str:
    if visibility not in VISIBILITIES:
        raise RepositoryError(
            "visibility_invalid",
            "Visibility is 'public' or 'private'.")
    return str(visibility)
