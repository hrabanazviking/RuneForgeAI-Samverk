"""Quotas, owner-visible (S-354).

S-068 put a per-repository quota on a repository,
enforced at receive time at one point
(`samverk.repo_quotas.QuotaService.check_receive`).
S-354 adds the per-user level at that same point and
owes the other half of the roadmap line: the quotas are
**visible to owners before they bite**.

This module is that surface, and nothing else:

- **One account, in words.** `QuotaOverviewService`
  reads S-068/S-354's one judge (`QuotaService`) and
  S-058's one walk -- no second quota store, no second
  measurement -- and builds a `QuotaOverview`: the
  owner's total across every repository they hold,
  the user quota it stands against, and one row per
  repository with its own usage against its own quota.
  Every number is stated in plain words (`overview_words`
  / `RepoQuotaRow.words`): how much is held, what the
  limit is, how much room remains, or by how much a
  limit is already passed -- before any push is refused.
- **Owners and admins only** (S-058's law, restated):
  anyone else is refused `permission_denied`, and one
  user's storage account never leaks to a stranger.
  Reading appends no audit entry and takes no taxonomy
  verb -- an account is a measurement, not an act: the
  taxonomy stands at 138 (33 auth / 92 repo / 13 admin).
- **No migration**: schema 139 stands; the per-user
  values ride the settings table (see
  `samverk.repo_quotas`). Setting the quotas themselves
  stays at S-068's doors plus S-354's admin-only user
  doors on `QuotaService`; this surface only reads.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .escaping import escape_html_text
from .repo_quotas import QuotaError, QuotaService
from .repositories import RepositoryStore

__all__ = [
    "QuotaOverview", "QuotaOverviewService", "RepoQuotaRow",
    "overview_words", "render_quotas_page",
]


@dataclass(frozen=True)
class RepoQuotaRow:
    """One repository's quota account: measured usage
    against its effective per-repository quota."""
    full_name: str
    usage_bytes: int
    quota_bytes: int | None       # None = unlimited

    @property
    def headroom_bytes(self) -> int | None:
        if self.quota_bytes is None:
            return None
        return max(0, self.quota_bytes - self.usage_bytes)

    @property
    def over_quota(self) -> bool:
        return (self.quota_bytes is not None
                and self.usage_bytes > self.quota_bytes)

    @property
    def words(self) -> str:
        if self.quota_bytes is None:
            return (f"{self.full_name} holds {self.usage_bytes} "
                    "bytes and has no repository quota.")
        if self.over_quota:
            return (
                f"{self.full_name} holds {self.usage_bytes} bytes, "
                f"over its {self.quota_bytes}-byte repository quota "
                f"by {self.usage_bytes - self.quota_bytes} bytes.")
        return (
            f"{self.full_name} holds {self.usage_bytes} of "
            f"{self.quota_bytes} bytes under its repository "
            f"quota; {self.headroom_bytes} bytes remain.")


@dataclass(frozen=True)
class QuotaOverview:
    """One owner's whole quota account: the per-user
    total and limit, and every repository's own row."""
    owner: str
    user_usage_bytes: int
    user_quota_bytes: int | None  # None = unlimited
    repos: tuple[RepoQuotaRow, ...]

    @property
    def user_headroom_bytes(self) -> int | None:
        if self.user_quota_bytes is None:
            return None
        return max(0, self.user_quota_bytes - self.user_usage_bytes)

    @property
    def user_over_quota(self) -> bool:
        return (self.user_quota_bytes is not None
                and self.user_usage_bytes > self.user_quota_bytes)


def overview_words(overview: QuotaOverview) -> str:
    """The owner's whole account in plain words -- the
    state stated before any limit bites."""
    if overview.user_quota_bytes is None:
        head = (f"{overview.owner}'s repositories hold "
                f"{overview.user_usage_bytes} bytes in total "
                "and there is no user quota.")
    elif overview.user_over_quota:
        head = (
            f"{overview.owner}'s repositories hold "
            f"{overview.user_usage_bytes} bytes in total, over "
            f"their {overview.user_quota_bytes}-byte user quota "
            f"by {overview.user_usage_bytes - overview.user_quota_bytes} "
            "bytes; new pushes will be refused until content "
            "is removed or a site admin raises the quota.")
    else:
        head = (
            f"{overview.owner}'s repositories hold "
            f"{overview.user_usage_bytes} of "
            f"{overview.user_quota_bytes} bytes under their user "
            f"quota; {overview.user_headroom_bytes} bytes remain.")
    rows = " ".join(row.words for row in overview.repos)
    return f"{head} {rows}" if rows else head


class QuotaOverviewService:
    """Builds the overview from the one judge and the
    one walk; refuses anyone but the owner or an admin."""

    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 quotas: QuotaService | None = None):
        self._accounts = accounts
        self._repos = repositories
        self._quotas = quotas or QuotaService(
            conn, data_root, accounts, repositories)

    def overview_for(self, actor_user_id: int, owner) -> QuotaOverview:
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise QuotaError("no_such_user", "No such account.")
        target = self._accounts.get_by_username(owner)
        if target is None:
            raise QuotaError("no_such_user", "No such account.")
        if not (actor.is_admin
                or actor.username_lower == target.username_lower):
            raise QuotaError(
                "permission_denied",
                "Only the owner or a site admin can see this "
                "quota account.")
        rows = tuple(
            RepoQuotaRow(
                full_name=current.full_name,
                usage_bytes=self._quotas.usage_bytes(
                    current.owner, current.name),
                quota_bytes=self._quotas.effective_quota(
                    current.owner, current.name))
            for current in self._repos.list_for_owner(target.username))
        return QuotaOverview(
            owner=target.username,
            user_usage_bytes=self._quotas.user_usage_bytes(target.username),
            user_quota_bytes=self._quotas.effective_user_quota(
                target.username),
            repos=rows)


def render_quotas_page(overview: QuotaOverview) -> str:
    """The owner's quota account, rendered in plain words
    with every limit named -- states in text, never colour
    alone. S-010 escaped."""
    owner = escape_html_text(overview.owner)
    parts = [
        f"<h1>Storage quotas: {owner}</h1>",
        f"<p>{escape_html_text(overview_words(overview))}</p>",
        "<ul>",
    ]
    for row in overview.repos:
        parts.append(f"<li>{escape_html_text(row.words)}</li>")
    parts.append("</ul>")
    return "\n".join(parts)
