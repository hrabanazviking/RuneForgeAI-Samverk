"""Reactions (S-128).

The small honest set, under three laws:

- **A small, closed set.** Eight reactions, the set
  GitHub-class users already know, each with a name in
  plain words beside its glyph — `REACTIONS` maps the
  stored name (`thumbs_up`) to its label and glyph, and
  anything outside the set is refused `reaction_invalid`.
  A reaction is stored by *name*, never by glyph alone,
  so the record stays searchable and screen-readable.
- **Counts are counted, and who is named.** Summaries
  are counted live from the reaction rows — never a
  cached counter that could drift — and every summary
  carries the who-reacted list (usernames in the order
  they reacted). `render_summary` prints glyph, name,
  count, and names as text: the meaning never rides on
  a glyph or a colour alone.
- **Yours to give, yours to take back.** Reacting is a
  reader act (S-054; strangers to a private repository
  get the uniform `issue_not_found`). Adding a reaction
  you already gave, or removing one you never gave, is
  a quiet no-op — retries are safe, and only a real
  change is audited (`repo.issue.reaction_add` /
  `repo.issue.reaction_remove`). You can only remove
  your own: there is no seam that takes another
  account's reaction away.

Targets are an issue or one of its comments; the two
never mix — a comment's reactions are its own.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .issues import IssueError, IssueStore
from .repositories import RepositoryStore

# name -> (plain-words label, glyph). Insertion order is
# the display order everywhere.
REACTIONS: dict[str, tuple[str, str]] = {
    "thumbs_up": ("thumbs up", "👍"),
    "thumbs_down": ("thumbs down", "👎"),
    "laugh": ("laugh", "😄"),
    "hooray": ("hooray", "🎉"),
    "confused": ("confused", "😕"),
    "heart": ("heart", "❤️"),
    "rocket": ("rocket", "🚀"),
    "eyes": ("eyes", "👀"),
}


class ReactionError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ReactionSummary:
    reaction: str      # stored name, e.g. 'thumbs_up'
    label: str         # plain words, e.g. 'thumbs up'
    glyph: str
    count: int
    users: tuple[str, ...]  # who reacted, in reaction order


class ReactionStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._audit = audit
        self._now = time_fn

    # -- give / take back ---------------------------------------------
    def add_reaction(self, actor: User, owner: object, repo: object,
                     number: object, reaction: object,
                     *, comment_id: int | None = None,
                     source_ip: str | None = None
                     ) -> list[ReactionSummary]:
        issue, target_comment = self._resolve(
            actor, owner, repo, number, comment_id)
        name = _validate_reaction(reaction)
        now = int(self._now())
        with self._conn:  # commits before the answer
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO reactions (issue_id, comment_id,"
                " user_id, reaction, created_at) VALUES (?, ?, ?, ?, ?)",
                (issue.id, target_comment, actor.id, name, now))
        if cur.rowcount:
            self._emit(actor, "repo.issue.reaction_add", owner, repo,
                       issue.number, name, comment_id, source_ip)
        return self.summaries_for(actor, owner, repo, number,
                                  comment_id=comment_id)

    def remove_reaction(self, actor: User, owner: object, repo: object,
                        number: object, reaction: object,
                        *, comment_id: int | None = None,
                        source_ip: str | None = None
                        ) -> list[ReactionSummary]:
        issue, target_comment = self._resolve(
            actor, owner, repo, number, comment_id)
        name = _validate_reaction(reaction)
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM reactions WHERE issue_id = ?"
                " AND comment_id = ? AND user_id = ? AND reaction = ?",
                (issue.id, target_comment, actor.id, name))
        if cur.rowcount:
            self._emit(actor, "repo.issue.reaction_remove", owner, repo,
                       issue.number, name, comment_id, source_ip)
        return self.summaries_for(actor, owner, repo, number,
                                  comment_id=comment_id)

    # -- reads -----------------------------------------------------------
    def summaries_for(self, viewer: User | None, owner: object,
                      repo: object, number: object,
                      *, comment_id: int | None = None
                      ) -> list[ReactionSummary]:
        issue, target_comment = self._resolve(
            viewer, owner, repo, number, comment_id)
        rows = self._conn.execute(
            "SELECT r.reaction AS reaction, u.username AS username"
            " FROM reactions r JOIN users u ON u.id = r.user_id"
            " WHERE r.issue_id = ? AND r.comment_id = ? ORDER BY r.id",
            (issue.id, target_comment)).fetchall()
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(row["reaction"], []).append(row["username"])
        return [ReactionSummary(
            reaction=name, label=REACTIONS[name][0],
            glyph=REACTIONS[name][1], count=len(users),
            users=tuple(users))
            for name, users in sorted(
                grouped.items(),
                key=lambda kv: list(REACTIONS).index(kv[0]))]

    def has_reacted(self, viewer: User | None, owner: object,
                    repo: object, number: object, reaction: object,
                    *, comment_id: int | None = None) -> bool:
        if viewer is None:
            return False
        name = _validate_reaction(reaction)
        return any(s.reaction == name and viewer.username in s.users
                   for s in self.summaries_for(viewer, owner, repo, number,
                                               comment_id=comment_id))

    # -- internals ---------------------------------------------------------
    def _resolve(self, viewer, owner, repo, number, comment_id):
        # get_issue enforces read access + the uniform private
        # answer before any target is resolved.
        issue = self._issues.get_issue(viewer, owner, repo, number)
        if comment_id is None:
            return issue, 0
        row = self._conn.execute(
            "SELECT id, deleted_at FROM issue_comments"
            " WHERE id = ? AND issue_id = ?",
            (comment_id, issue.id)).fetchone()
        if row is None or row["deleted_at"] is not None:
            raise IssueError("comment_not_found", "No such comment.")
        return issue, int(row["id"])

    def _emit(self, actor: User, action: str, owner: object,
              repo: object, number: int, reaction: str,
              comment_id: int | None, source_ip: str | None) -> None:
        if self._audit is not None:
            current = self._repos.get_repository(owner, repo)
            target = (f"{current.full_name}#{number}"
                      if current is not None else f"#{number}")
            detail: dict = {"number": number, "reaction": reaction}
            if comment_id is not None:
                detail["comment_id"] = comment_id
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action=action,
                target_kind="repo", target_id=target,
                outcome="success", source_ip=source_ip, detail=detail)


def _validate_reaction(reaction: object) -> str:
    if not isinstance(reaction, str) or reaction not in REACTIONS:
        raise ReactionError(
            "reaction_invalid",
            "Reactions are the small honest set: "
            + ", ".join(REACTIONS) + ".")
    return reaction


def render_summary(summary: ReactionSummary) -> str:
    """One summary as text: glyph, name, count, and who —
    meaning never rides on the glyph alone."""
    who = ", ".join(summary.users)
    return f"{summary.glyph} {summary.label}: {summary.count} ({who})"
