"""Branch list, deleted-branch and settings surfaces (S-159).

The UI half of S-159's branch housekeeping, composing
the slice's records into the pages a person actually
meets. The state itself lives elsewhere — the
deleted-branch tombstone is migration 58's table
(written by the housekeeping service when a merge
deletes a head branch), the restore *service* that
recreates a branch from a tombstone is that service's
companion work, and the delete-head-branch-on-merge
flag is carried on S-066's `RepoSettings` through
`RepoSettingsService` — this module owns none of that
state. It owns the surfaces:

- **The branch list** (`branch_list` / `render_branch_list`):
  every live branch in the ref listing's order with the
  default branch named in words, the fork sync hint
  line when the repository is a fork behind its
  upstream (`samverk/fork_sync.py`, shown only when
  behind > 0), and the deleted branches that can still
  be restored, each with its restore affordance.
- **The deleted-branches page** (`render_deleted_branches_page`):
  the listing the design names
  `GET /{owner}/{repo}/branches/deleted` — every
  unrestored tombstone record in words, each one
  carrying its restore form. The form posts to
  `/{owner}/{repo}/branches/restore` with the record's
  id in the `deleted_branch_id` field, exactly the
  shape the restore service answers; an affordance is
  a real form naming what it restores, never a bare
  icon. (There are no server routes in this codebase —
  S-002's skeleton routes nothing beyond /healthz and
  every slice since S-141 ships at the service+render
  layer; these renders are that layer's answer to the
  design's named routes, and the progress file says so.)
- **The settings form** (`render_housekeeping_settings_form`):
  the delete-head-branch-on-merge opt-in as a labelled
  checkbox on S-066's settings surface, its position
  always said in words under the box (never the
  checkbox alone), following S-149's settings pattern
  of a policy stated plainly beside its control.

Tombstone reads are plain SQL against migration 58's
shape: a record is restorable while its `restored_at`
is NULL; a restored record is history and leaves the
affordance list, exactly as S-152's dismissal leaves a
request restorable-no-longer while the row stays.

Reads ride the S-054 seam: a repository the viewer
cannot read answers with the uniform `repo_not_found`.
Every user-controlled value reaches HTML only through
S-010's escaping seam, and state is always said in
words, never colour alone.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text
from .fork_sync import (
    ForkSyncError, ForkSyncStatus, ForkSyncStore, render_fork_sync_hint)
from .permissions import can_read
from .refs import RefStore
from .repo_settings import RepoSettings
from .repositories import RepositoryStore

__all__ = [
    "BranchListView", "BranchRow", "BranchViewError",
    "BranchViewStore", "DeletedBranchRow",
    "render_branch_list", "render_deleted_branches_page",
    "render_housekeeping_settings_form", "render_restore_form",
]


class BranchViewError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class DeletedBranchRow:
    """One migration-58 tombstone, as the surfaces show
    it. Restored rows are history: `is_restorable` is
    the affordance's whole question."""
    id: int
    branch_name: str
    head_oid: str
    deleted_at: int
    deleted_by: int
    pr_number: int
    merge_oid: str = ""
    restored_at: int | None = None
    restored_by: int | None = None

    @property
    def is_restorable(self) -> bool:
        return self.restored_at is None

    @property
    def words(self) -> str:
        text = (f"Branch {self.branch_name} — deleted; "
                f"was at {self.head_oid}; deleted on merge "
                f"of pull request #{self.pr_number}")
        if self.is_restorable:
            return text + "; it can be restored."
        return text + f"; restored at {self.restored_at}."


@dataclass(frozen=True)
class BranchRow:
    name: str
    oid: str
    is_default: bool = False


@dataclass(frozen=True)
class BranchListView:
    full_name: str
    owner: str
    name: str
    branches: tuple          # of BranchRow, ref listing order
    deleted: tuple           # of DeletedBranchRow, unrestored, oldest first
    fork_sync: ForkSyncStatus


class BranchViewStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._sync = ForkSyncStore(repositories)

    def deleted_branches(self, viewer: User | None, owner: object,
                         repo: object, *,
                         include_restored: bool = False) -> tuple:
        """This repository's tombstone records, oldest
        first — unrestored only, unless `include_restored`
        asks for the whole provable history."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise BranchViewError("repo_not_found", "No such repository.")
        sql = "SELECT * FROM deleted_branches WHERE repo_id = ?"
        if not include_restored:
            sql += " AND restored_at IS NULL"
        sql += " ORDER BY id"
        return tuple(
            DeletedBranchRow(
                id=int(r["id"]), branch_name=r["branch_name"],
                head_oid=r["head_oid"],
                deleted_at=int(r["deleted_at"]),
                deleted_by=int(r["deleted_by"]),
                pr_number=int(r["pr_number"]),
                merge_oid=r["merge_oid"] or "",
                restored_at=r["restored_at"],
                restored_by=r["restored_by"])
            for r in self._conn.execute(sql, (current.id,)).fetchall())

    def branch_list(self, viewer: User | None, owner: object,
                    repo: object) -> BranchListView:
        """The branch list's whole read model in one call:
        the live branches, the deleted branches that can
        still be restored, and the fork sync position
        (always present; `unknown` when it could not be
        checked, so the page never guesses)."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise BranchViewError("repo_not_found", "No such repository.")
        path = self._repos.path_for(current.owner, current.name)
        rows = tuple(
            BranchRow(name=ref.short, oid=ref.oid,
                      is_default=ref.short == current.default_branch)
            for ref in RefStore(path).list_branches())
        deleted = self.deleted_branches(viewer, owner, repo)
        try:
            sync = self._sync.fork_sync_status(
                viewer, current.owner, current.name)
        except ForkSyncError:
            sync = ForkSyncStatus(
                full_name=current.full_name, state="unknown",
                branch=current.default_branch,
                behind=None, ahead=None)
        return BranchListView(
            full_name=current.full_name, owner=current.owner,
            name=current.name, branches=rows, deleted=deleted,
            fork_sync=sync)


def _restore_form(record: DeletedBranchRow, owner: str, name: str) -> str:
    """One deleted branch's restore affordance: a real
    form posting the record's id to the restore route,
    its button naming the branch it restores."""
    action = escape_html_attr(f"/{owner}/{name}/branches/restore")
    return (
        f'<form method="post" class="restore-branch" '
        f'action="{action}">'
        f'<input type="hidden" name="deleted_branch_id" '
        f'value="{record.id}">'
        f'<button type="submit">Restore branch '
        f"{escape_html_text(record.branch_name)}</button></form>")


def render_restore_form(record: DeletedBranchRow, owner: str,
                        name: str) -> str:
    """The restore affordance for one record, on its own."""
    return _restore_form(record, owner, name)


def _deleted_section(view: BranchListView) -> str:
    if not view.deleted:
        return ('<section class="deleted-branches">'
                "<h2>Deleted branches</h2>"
                '<p class="empty">There are no deleted branches '
                "to restore.</p></section>")
    items = []
    for record in view.deleted:
        items.append(
            '<li class="deleted-branch">'
            f"{escape_html_text(record.words)} "
            f"{_restore_form(record, view.owner, view.name)}</li>")
    return ('<section class="deleted-branches">'
            "<h2>Deleted branches</h2><ul>"
            + "".join(items) + "</ul></section>")


def render_deleted_branches_page(view: BranchListView) -> str:
    """The deleted-branches listing (the design's
    `GET /{owner}/{repo}/branches/deleted` surface):
    every unrestored record in words, each with its
    restore form; an empty ledger says so plainly."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(view.full_name)} — deleted "
        "branches — Samverk</title></head>",
        "<body>",
        f"<h1>Deleted branches — "
        f"{escape_html_text(view.full_name)}</h1>",
        _deleted_section(view),
        "</body></html>",
    ]
    return "\n".join(parts)


def render_branch_list(view: BranchListView) -> str:
    """The branch list: every live branch in words (the
    default branch named as such), the fork sync hint
    line when the fork is behind its upstream, and the
    deleted branches with their restore forms."""
    parts = ['<section class="branches"><h2>Branches</h2>']
    if view.branches:
        parts.append("<ul>")
        for row in view.branches:
            marker = " (default branch)" if row.is_default else ""
            parts.append(
                '<li class="branch">'
                f"{escape_html_text(row.name)}"
                f"{escape_html_text(marker)} "
                f'<span class="oid">'
                f"{escape_html_text(row.oid[:12])}</span></li>")
        parts.append("</ul>")
    else:
        parts.append(
            '<p class="empty">This repository has no branches '
            "yet.</p>")
    parts.append("</section>")
    hint = render_fork_sync_hint(view.fork_sync)
    if hint:
        parts.append(hint)
    parts.append(_deleted_section(view))
    return "".join(parts)


def render_housekeeping_settings_form(settings: RepoSettings) -> str:
    """The delete-head-branch-on-merge opt-in on the
    repository settings surface: a labelled checkbox
    carrying the current state, the position said in
    words under it, and the save button — the S-149
    settings pattern of a policy stated plainly beside
    its control. The flag itself is read and written
    through `RepoSettingsService` (S-066); this is only
    its form."""
    if settings.delete_branch_on_merge:
        words = ("Head branches are deleted on merge in "
                 "this repository.")
    else:
        words = ("Head branches are kept on merge in this "
                 "repository (the default).")
    checked = " checked" if settings.delete_branch_on_merge else ""
    return (
        '<form method="post" class="branch-housekeeping-settings">'
        "<label>Delete the head branch when a pull request "
        "is merged "
        f'<input type="checkbox" name="delete_branch_on_merge"'
        f"{checked}></label>"
        f'<p class="setting-words">{escape_html_text(words)}</p>'
        '<button type="submit">Save branch housekeeping '
        "settings</button></form>")
