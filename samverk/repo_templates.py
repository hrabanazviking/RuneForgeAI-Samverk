"""Repository templates (S-064).

Create a new repository from a template repository, with
variable substitution in the README only — honestly scoped,
exactly as the roadmap words it:

- **What a template is.** Any repository its owner marks
  with `set_template`. Marking is owner-only. A repository
  that is not marked cannot be used as a template
  (`not_a_template`) — there is no silent "any repo is a
  template" widening.
- **What creation copies.** The template's full git content,
  through S-014's local-paths-only clone seam (the S-055 fork
  machinery's road, but a template creation is *not* a fork:
  `fork_of_id` stays empty and `template_of_id` records the
  source). The read gate is S-054's one function — an
  unreadable private template answers as not found — and a
  private template can never produce a public repository.
- **What substitution touches.** The root README file only
  (`README`, `README.md`, `README.txt`, `README.rst`,
  case-insensitive), at the template's default-branch HEAD.
  Placeholders are `{{ key }}`; only keys the caller supplied
  are replaced, unknown placeholders are left exactly as
  written and reported back, and **no other file is ever
  rewritten** — a `{{ key }}` inside code stays byte-identical.
  When at least one substitution lands, the change is one new
  commit on top of the copied HEAD, authored by the creating
  account, saying what it is; when nothing matches, no commit
  is invented and the copied history stands untouched.
- Variables are validated: keys are `[A-Za-z0-9_-]{1,50}`,
  values are text of at most 500 characters with no NUL or
  control characters except tab/newline.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .permissions import can_read
from .platform_seam import ensure_dir
from .proc import run_git_clone_local, run_git_in
from .repo_paths import RepoPathError
from .repositories import (
    Repository, RepositoryError, RepositoryStore, _validate_visibility,
    canonical_owner_repo)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_-]{1,50})\s*\}\}")
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,50}$")
README_NAMES = frozenset({"readme", "readme.md", "readme.txt", "readme.rst"})
VALUE_MAX = 500


class TemplateError(RepositoryError):
    pass


@dataclass(frozen=True)
class TemplateCreation:
    repository: Repository
    readme_changed: bool
    substituted_keys: tuple[str, ...] = ()
    placeholders_left: tuple[str, ...] = ()
    source_full_name: str = ""


def substitute_readme(text: str, variables: dict[str, str]) -> tuple[str, list[str], list[str]]:
    """(new_text, substituted_keys, placeholders_left) — pure."""
    used: list[str] = []
    left: list[str] = []

    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key in variables:
            if key not in used:
                used.append(key)
            return variables[key]
        if key not in left:
            left.append(key)
        return match.group(0)

    return _PLACEHOLDER_RE.sub(repl, text), used, left


def validate_variables(variables: dict | None) -> dict[str, str]:
    if variables is None:
        return {}
    if not isinstance(variables, dict):
        raise TemplateError("variables_invalid", "Variables must be a mapping.")
    out: dict[str, str] = {}
    for key, value in variables.items():
        if not isinstance(key, str) or not _KEY_RE.match(key):
            raise TemplateError(
                "variables_invalid", f"That variable name is not valid: {key!r}")
        if (not isinstance(value, str) or len(value) > VALUE_MAX
                or any((ord(c) < 0x20 and c not in "\t\n") or ord(c) == 0x7F
                       for c in value)):
            raise TemplateError(
                "variables_invalid",
                f"Variable {key!r} must be plain text of at most {VALUE_MAX} characters.")
        out[key] = value
    return out


class TemplateStore:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit

    # -- marking ---------------------------------------------------
    def set_template(self, actor_user_id: int, owner: object,
                     repo: object, is_template: bool) -> Repository:
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise TemplateError("no_such_user", "No such account.")
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise TemplateError("no_such_repo", "No such repository.")
        if actor.username_lower != current.owner_lower:
            raise TemplateError(
                "not_repo_owner", "Only the owner can mark a template.")
        with self._conn:
            self._conn.execute(
                "UPDATE repositories SET is_template = ? WHERE id = ?",
                (1 if is_template else 0, current.id))
        updated = self._repos.get_by_id(current.id)
        assert updated is not None
        return updated

    def is_template(self, owner: object, repo: object) -> bool:
        current = self._repos.get_repository(owner, repo)
        return bool(current and current.is_template)

    # -- creation ----------------------------------------------------
    def create_from_template(
        self, actor_user_id: int, source_owner: object, source_repo: object,
        dest_repo: object = None, *,
        variables: dict | None = None,
        visibility: str | None = None,
        source_ip: str | None = None,
    ) -> TemplateCreation:
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise TemplateError("no_such_user", "No such account.")
        variables = validate_variables(variables)
        source = self._repos.get_repository(source_owner, source_repo)
        if source is None or not can_read(actor, source):
            raise TemplateError("no_such_repo", "No such repository.")
        if not source.is_template:
            raise TemplateError(
                "not_a_template",
                "That repository is not marked as a template.")
        raw_dest = source.name if dest_repo is None else dest_repo
        try:
            _, _, dest_name, dest_lower = canonical_owner_repo(
                actor.username, raw_dest)
        except RepositoryError as exc:
            raise TemplateError(exc.reason, str(exc)) from None
        if self._repos.get_repository(actor.username, dest_name) is not None:
            raise TemplateError(
                "repo_taken", f"{actor.username}/{dest_name} already exists.")
        new_visibility = source.visibility if visibility is None \
            else _validate_visibility(visibility)
        if source.visibility == "private" and new_visibility == "public":
            raise TemplateError(
                "template_visibility_escalation",
                "A private template cannot create a public repository.")
        try:
            dest_path = self._repos.path_for(actor.username, dest_name)
            src_path = self._repos.path_for(source.owner, source.name)
        except RepoPathError as exc:
            raise TemplateError("repo_invalid", str(exc)) from None
        if dest_path.exists():
            raise TemplateError(
                "repo_path_exists", "A directory already exists at that path.")
        ensure_dir(dest_path.parent)
        result = run_git_clone_local(src_path, dest_path, timeout=120.0)
        if result.returncode != 0:
            shutil.rmtree(dest_path, ignore_errors=True)
            raise TemplateError(
                "git_clone_failed",
                "git could not clone the template: "
                + result.stderr.decode("utf-8", "replace").strip()[:200])
        now = int(time.time())
        try:
            with self._conn:
                cur = self._conn.execute(
                    "INSERT INTO repositories (owner, owner_lower, name,"
                    " name_lower, created_by, created_at, description,"
                    " visibility, default_branch, template_of_id)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (actor.username, actor.username_lower, dest_name,
                     dest_lower, actor.id, now, source.description,
                     new_visibility, source.default_branch, source.id))
                new_id = int(cur.lastrowid)
        except Exception:
            shutil.rmtree(dest_path, ignore_errors=True)
            raise
        created = self._repos.get_by_id(new_id)
        assert created is not None
        readme_changed, used, left = self._substitute_readme(
            dest_path, created, actor, source, variables)
        created = self._repos.get_by_id(new_id)
        assert created is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action="repo.create",
                target_kind="repo", target_id=created.full_name,
                outcome="success", source_ip=source_ip,
                detail={"from_template": source.full_name,
                        "readme_substituted": readme_changed})
        return TemplateCreation(
            repository=created, readme_changed=readme_changed,
            substituted_keys=tuple(sorted(used)),
            placeholders_left=tuple(sorted(left)),
            source_full_name=source.full_name)

    # -- the README-only substitution commit -------------------------
    def _substitute_readme(self, dest_path: Path, created: Repository,
                           actor, source: Repository,
                           variables: dict[str, str]) -> tuple[bool, list[str], list[str]]:
        if not variables:
            return False, [], self._readme_placeholders(dest_path, created)
        head = run_git_in(dest_path, ["rev-parse", "--verify", "--quiet", "HEAD"],
                          timeout=15.0)
        if head.returncode != 0:
            return False, [], []  # empty template: nothing to substitute
        head_oid = head.stdout.decode().strip()
        tree = run_git_in(dest_path, ["ls-tree", "HEAD"], timeout=15.0)
        if tree.returncode != 0:
            return False, [], []
        entries: list[str] = []
        readme_entry: tuple[int, str, str, str] | None = None
        for line in tree.stdout.decode("utf-8", "surrogateescape").splitlines():
            meta, _, name = line.partition("\t")
            parts = meta.split()
            if len(parts) != 3:
                continue
            mode, obj_type, oid = parts
            entries.append(line)
            if obj_type == "blob" and name.lower() in README_NAMES:
                readme_entry = (len(entries) - 1, mode, oid, name)
        if readme_entry is None:
            return False, [], []
        idx, mode, blob_oid, name = readme_entry
        blob = run_git_in(dest_path, ["cat-file", "blob", blob_oid], timeout=15.0)
        if blob.returncode != 0:
            return False, [], []
        try:
            text = blob.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return False, [], []  # a binary README is not substituted
        new_text, used, left = substitute_readme(text, variables)
        if not used or new_text == text:
            return False, [], left
        new_blob = run_git_in(
            dest_path, ["hash-object", "-w", "--stdin"],
            input_bytes=new_text.encode("utf-8"), timeout=15.0)
        if new_blob.returncode != 0:
            raise TemplateError("template_substitution_failed",
                                "git could not store the substituted README.")
        entries[idx] = f"{mode} blob {new_blob.stdout.decode().strip()}\t{name}"
        new_tree = run_git_in(
            dest_path, ["mktree"],
            input_bytes=("\n".join(entries) + "\n").encode("utf-8", "surrogateescape"),
            timeout=15.0)
        if new_tree.returncode != 0:
            raise TemplateError("template_substitution_failed",
                                "git could not rebuild the tree.")
        env = {
            "GIT_AUTHOR_NAME": actor.username,
            "GIT_AUTHOR_EMAIL": f"{actor.username_lower}@samverk.invalid",
            "GIT_COMMITTER_NAME": actor.username,
            "GIT_COMMITTER_EMAIL": f"{actor.username_lower}@samverk.invalid",
        }
        commit = run_git_in(
            dest_path,
            ["commit-tree", new_tree.stdout.decode().strip(), "-p", head_oid],
            input_bytes=f"Initialize from template {source.full_name}\n".encode(),
            timeout=15.0, env_extra=env)
        if commit.returncode != 0:
            raise TemplateError("template_substitution_failed",
                                "git could not commit the substituted README.")
        branch_ref = f"refs/heads/{created.default_branch}"
        updated = run_git_in(
            dest_path, ["update-ref", branch_ref,
                        commit.stdout.decode().strip(), head_oid],
            timeout=15.0)
        if updated.returncode != 0:
            raise TemplateError("template_substitution_failed",
                                "git could not move the default branch.")
        return True, used, left

    @staticmethod
    def _readme_placeholders(dest_path: Path, created: Repository) -> list[str]:
        head = run_git_in(dest_path, ["rev-parse", "--verify", "--quiet", "HEAD"],
                          timeout=15.0)
        if head.returncode != 0:
            return []
        tree = run_git_in(dest_path, ["ls-tree", "HEAD"], timeout=15.0)
        if tree.returncode != 0:
            return []
        for line in tree.stdout.decode("utf-8", "surrogateescape").splitlines():
            meta, _, name = line.partition("\t")
            parts = meta.split()
            if len(parts) == 3 and parts[1] == "blob" and name.lower() in README_NAMES:
                blob = run_git_in(dest_path, ["cat-file", "blob", parts[2]],
                                  timeout=15.0)
                if blob.returncode != 0:
                    return []
                try:
                    text = blob.stdout.decode("utf-8")
                except UnicodeDecodeError:
                    return []
                return sorted(set(_PLACEHOLDER_RE.findall(text)))
        return []
