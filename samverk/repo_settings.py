"""Repository settings (S-066).

The full settings surface for one repository, building on
S-050's metadata row rather than beside it:

- **Description and visibility and default branch** stay on
  the S-050 row and keep flowing through
  `RepositoryStore.update_metadata` — this module delegates,
  so there is still exactly one writer of those fields.
- **Website and topics** live here (migration 29): a website
  must survive S-010's `safe_url` and be http(s) — a
  `javascript:` or `data:` "website" is refused by name —
  and topics are a closed shape (lowercase letters, digits,
  hyphens; at most 20 topics of at most 50 characters,
  duplicates folded).
- **Default-branch rename** is more than a settings change:
  the branch ref itself moves (S-053's atomic rename), the
  S-050 default follows, HEAD follows the default, and the
  rename is **recorded** so a clone made before the rename
  can be guided to the new name — `rename_guidance` returns
  the exact copyable commands a clone owner runs
  (`git remote set-head origin -a` among them). Guidance,
  honestly named: Samverk cannot reach into a clone it does
  not host, so it records the rename and hands over the
  steps instead of pretending the clone updated itself.
- Every change is owner-only and audited under the frozen
  `repo.settings.change` with the key named.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import safe_url
from .permissions import can_read
from .refs import RefError, RefStore
from .repositories import (
    Repository, RepositoryError, RepositoryStore, validate_branch_name)

TOPIC_MAX_COUNT = 20
TOPIC_MAX_LEN = 50
WEBSITE_MAX = 200
_TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class SettingsError(RepositoryError):
    pass


@dataclass(frozen=True)
class RepoSettings:
    full_name: str
    description: str
    visibility: str
    default_branch: str
    website: str = ""
    topics: tuple[str, ...] = ()


@dataclass(frozen=True)
class BranchRename:
    full_name: str
    old_branch: str
    new_branch: str
    clone_guidance: tuple[str, ...]


def clone_guidance_for(old_branch: str, new_branch: str) -> tuple[str, ...]:
    """The copyable steps a pre-rename clone runs locally."""
    return (
        f"git branch -m {old_branch} {new_branch}",
        "git fetch origin",
        f"git branch -u origin/{new_branch} {new_branch}",
        "git remote set-head origin -a",
    )


def validate_topics(topics: object) -> tuple[str, ...]:
    if topics is None:
        return ()
    if isinstance(topics, str) or not isinstance(topics, (list, tuple)):
        raise SettingsError("topics_invalid", "Topics must be a list of names.")
    out: list[str] = []
    for raw in topics:
        if not isinstance(raw, str):
            raise SettingsError("topics_invalid", "A topic must be text.")
        topic = raw.strip().lower()
        if not topic:
            continue
        if len(topic) > TOPIC_MAX_LEN or not _TOPIC_RE.match(topic) \
                or topic.endswith("-"):
            raise SettingsError(
                "topics_invalid",
                f"That topic is not valid: {raw!r} (lowercase letters, "
                "digits and hyphens, at most 50 characters).")
        if topic not in out:
            out.append(topic)
    if len(out) > TOPIC_MAX_COUNT:
        raise SettingsError(
            "topics_invalid", f"At most {TOPIC_MAX_COUNT} topics.")
    return tuple(out)


def validate_website(website: object) -> str:
    if website is None:
        return ""
    if not isinstance(website, str):
        raise SettingsError("website_invalid", "Website must be text.")
    text = website.strip()
    if not text:
        return ""
    if len(text) > WEBSITE_MAX or safe_url(text) is None \
            or not (text.startswith("https://") or text.startswith("http://")):
        raise SettingsError(
            "website_invalid",
            "Website must be an http(s) URL of at most 200 characters.")
    return text


class RepoSettingsService:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._now = time_fn

    # -- reading -------------------------------------------------------
    def settings_for(self, viewer: User | None,
                     owner: object, repo: object) -> RepoSettings:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise SettingsError("no_such_repo", "No such repository.")
        return self._settings_of(current)

    def _settings_of(self, current: Repository) -> RepoSettings:
        row = self._conn.execute(
            "SELECT website, topics FROM repo_settings WHERE repo_id = ?",
            (current.id,)).fetchone()
        website, topics = "", ()
        if row is not None:
            website = row["website"]
            try:
                topics = tuple(json.loads(row["topics"]))
            except (ValueError, TypeError):
                topics = ()
        return RepoSettings(
            full_name=current.full_name, description=current.description,
            visibility=current.visibility,
            default_branch=current.default_branch,
            website=website, topics=topics)

    # -- writing ---------------------------------------------------------
    def update_settings(self, actor_user_id: int, owner: object,
                        repo: object, *, description: object = None,
                        visibility: object = None,
                        website: object = None,
                        topics: object = None,
                        source_ip: str | None = None) -> RepoSettings:
        actor, current = self._require_owner(actor_user_id, owner, repo)
        # Description/visibility keep their one S-050 writer.
        if description is not None or visibility is not None:
            current = self._repos.update_metadata(
                actor_user_id, owner, repo,
                description=description, visibility=visibility,
                source_ip=source_ip)
        if website is not None or topics is not None:
            existing = self._settings_of(current)
            new_website = existing.website if website is None \
                else validate_website(website)
            new_topics = existing.topics if topics is None \
                else validate_topics(topics)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO repo_settings (repo_id, website, topics)"
                    " VALUES (?, ?, ?)"
                    " ON CONFLICT(repo_id) DO UPDATE SET"
                    " website = excluded.website, topics = excluded.topics",
                    (current.id, new_website, json.dumps(list(new_topics))))
            if self._audit is not None:
                self._audit.append(
                    actor_kind="user", actor_id=actor.id,
                    action="repo.settings.change", target_kind="repo",
                    target_id=current.full_name, outcome="success",
                    source_ip=source_ip,
                    detail={"key": "website_topics",
                            "website": new_website,
                            "topics": list(new_topics)})
        return self._settings_of(self._repos.get_by_id(current.id))

    # -- default-branch rename -------------------------------------------
    def rename_default_branch(self, actor_user_id: int, owner: object,
                              repo: object, new_branch: object, *,
                              source_ip: str | None = None) -> BranchRename:
        actor, current = self._require_owner(actor_user_id, owner, repo)
        new_name = validate_branch_name(new_branch)
        old_name = current.default_branch
        if new_name == old_name:
            raise SettingsError(
                "rename_same", "That is already the default branch.")
        path = self._repos.path_for(current.owner, current.name)
        refs = RefStore(path)
        if refs.head_oid() is not None:
            # A repo with commits: the branch itself must move.
            try:
                refs.rename_branch(old_name, new_name)
            except RefError as exc:
                raise SettingsError(exc.reason, str(exc)) from None
        # The S-050 writer moves HEAD + the recorded default.
        self._repos.update_metadata(
            actor_user_id, owner, repo, default_branch=new_name,
            source_ip=source_ip)
        with self._conn:
            self._conn.execute(
                "INSERT INTO repo_branch_renames"
                " (repo_id, old_branch, new_branch, renamed_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(repo_id, old_branch) DO UPDATE SET"
                " new_branch = excluded.new_branch,"
                " renamed_at = excluded.renamed_at",
                (current.id, old_name, new_name, int(self._now())))
        return BranchRename(
            full_name=current.full_name, old_branch=old_name,
            new_branch=new_name,
            clone_guidance=clone_guidance_for(old_name, new_name))

    def rename_guidance(self, viewer: User | None, owner: object,
                        repo: object, old_branch: object) -> BranchRename | None:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise SettingsError("no_such_repo", "No such repository.")
        row = self._conn.execute(
            "SELECT new_branch FROM repo_branch_renames"
            " WHERE repo_id = ? AND old_branch = ?",
            (current.id, str(old_branch))).fetchone()
        if row is None:
            return None
        return BranchRename(
            full_name=current.full_name, old_branch=str(old_branch),
            new_branch=row["new_branch"],
            clone_guidance=clone_guidance_for(str(old_branch), row["new_branch"]))

    # -- helpers -----------------------------------------------------------
    def _require_owner(self, actor_user_id: int, owner: object, repo: object):
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise SettingsError("no_such_user", "No such account.")
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise SettingsError("no_such_repo", "No such repository.")
        if actor.username_lower != current.owner_lower:
            raise SettingsError(
                "not_repo_owner", "Only the repository's owner can change it.")
        return actor, current
