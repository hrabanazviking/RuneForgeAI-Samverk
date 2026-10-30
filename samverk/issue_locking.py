"""Locking and pinning (S-132).

Two moderator tools over an issue's conversation, under
one law each:

- **Locking closes the conversation, with a reason.**
  A lock carries one reason from a small plain-words
  vocabulary (`off_topic` / `too_heated` / `resolved` /
  `spam`, studied from public forge behaviour) — anything
  else is refused `reason_invalid`, and the reason is
  stored on the issue and said in words
  (`lock_words`: "locked as too heated"), never carried
  by a colour or an icon alone. While an issue is
  locked, new comments are refused for everyone except
  repository writers and admins (enforced at the one
  comment seam, S-123's `add_comment`, as
  `conversation_locked`, naming the reason in words):
  a lock quiets a thread without silencing the people
  responsible for it. Locking is a moderator act
  (repository admins — the owner or a site admin, the
  same hands S-123 trusts with comment deletion);
  the issue's author alone cannot lock their own thread
  against the repository.
- **Pinning lifts at most three issues.** A repository
  pins up to `MAX_PINS` (3) issues — the small set a
  reader sees first — and a fourth pin is refused
  `pin_limit`, naming the cap, rather than silently
  displacing someone else's pin. Pins list in pin
  order. Pinning is likewise a moderator act.
- **Retries are quiet.** Locking a locked issue,
  unlocking an open one, pinning a pinned issue, and
  unpinning an unpinned one are all no-ops that report
  the standing state — a relock never rewrites the
  recorded reason, exactly as S-130's reclose never
  rewrites the closing reason. Only real changes are
  audited (`repo.issue.lock` / `.unlock` / `.pin` /
  `.unpin`, taxonomy append-only +4, 83 events).
- **Permissions ride the repository's.** Every read
  follows S-054 through the issue seam, so a stranger
  to a private repository gets the uniform
  `issue_not_found` for lock and pin state alike.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .issues import Issue, IssueError, IssueStore
from .permissions import can_admin, can_read
from .repositories import Repository, RepositoryStore

MAX_PINS = 3
LOCK_REASONS = frozenset({"off_topic", "too_heated", "resolved", "spam"})
LOCK_REASON_WORDS = {
    "off_topic": "off-topic",
    "too_heated": "too heated",
    "resolved": "resolved",
    "spam": "spam",
}


@dataclass(frozen=True)
class IssueLock:
    locked: bool
    reason: str          # '' while unlocked
    locked_by: int | None
    locked_at: int | None

    @property
    def words(self) -> str:
        """The lock as words: 'not locked', or 'locked as
        too heated' — never a colour or icon alone."""
        if not self.locked:
            return "not locked"
        words = LOCK_REASON_WORDS.get(self.reason, "")
        return f"locked as {words}" if words else "locked"


UNLOCKED = IssueLock(locked=False, reason="", locked_by=None, locked_at=None)


class IssueLockPinStore:
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

    # -- locking -----------------------------------------------------
    def lock_issue(self, actor: User, owner: object, repo: object,
                   number: object, reason: object = "resolved",
                   *, source_ip: str | None = None) -> IssueLock:
        if reason not in LOCK_REASONS:
            raise IssueError(
                "reason_invalid",
                "A conversation locks as 'off_topic', 'too_heated', "
                "'resolved', or 'spam'.")
        issue, current = self._moderated_issue(actor, owner, repo, number)
        standing = self._lock_of(issue.id)
        if standing.locked:
            return standing  # a retry, not a second event
        now = int(self._now())
        with self._conn:  # the lock lands whole, or not at all
            self._conn.execute(
                "UPDATE issues SET locked = 1, lock_reason = ?,"
                " locked_by = ?, locked_at = ? WHERE id = ?",
                (str(reason), actor.id, now, issue.id))
        lock = IssueLock(locked=True, reason=str(reason),
                         locked_by=actor.id, locked_at=now)
        self._emit(actor, "repo.issue.lock", current,
                   {"number": issue.number, "reason": str(reason)},
                   source_ip)
        return lock

    def unlock_issue(self, actor: User, owner: object, repo: object,
                     number: object,
                     *, source_ip: str | None = None) -> IssueLock:
        issue, current = self._moderated_issue(actor, owner, repo, number)
        if not self._lock_of(issue.id).locked:
            return UNLOCKED  # a retry, not a second event
        with self._conn:
            self._conn.execute(
                "UPDATE issues SET locked = 0, lock_reason = '',"
                " locked_by = NULL, locked_at = NULL WHERE id = ?",
                (issue.id,))
        self._emit(actor, "repo.issue.unlock", current,
                   {"number": issue.number}, source_ip)
        return UNLOCKED

    def lock_for(self, viewer: User | None, owner: object,
                 repo: object, number: object) -> IssueLock:
        issue = self._issues.get_issue(viewer, owner, repo, number)
        return self._lock_of(issue.id)

    # -- pinning -------------------------------------------------------
    def pin_issue(self, actor: User, owner: object, repo: object,
                  number: object,
                  *, source_ip: str | None = None) -> list[Issue]:
        issue, current = self._moderated_issue(actor, owner, repo, number)
        if self._is_pinned(issue.id):
            return self.pinned_issues(actor, owner, repo)
        count = self._conn.execute(
            "SELECT COUNT(*) AS n FROM issue_pins WHERE repo_id = ?",
            (current.id,)).fetchone()["n"]
        if int(count) >= MAX_PINS:
            raise IssueError(
                "pin_limit",
                f"At most {MAX_PINS} issues can be pinned in one "
                "repository; unpin one first.")
        now = int(self._now())
        with self._conn:  # commits before the answer
            self._conn.execute(
                "INSERT INTO issue_pins (repo_id, issue_id, pinned_by,"
                " created_at) VALUES (?, ?, ?, ?)",
                (current.id, issue.id, actor.id, now))
        self._emit(actor, "repo.issue.pin", current,
                   {"number": issue.number}, source_ip)
        return self.pinned_issues(actor, owner, repo)

    def unpin_issue(self, actor: User, owner: object, repo: object,
                    number: object,
                    *, source_ip: str | None = None) -> list[Issue]:
        issue, current = self._moderated_issue(actor, owner, repo, number)
        if not self._is_pinned(issue.id):
            return self.pinned_issues(actor, owner, repo)
        with self._conn:
            self._conn.execute(
                "DELETE FROM issue_pins WHERE issue_id = ?", (issue.id,))
        self._emit(actor, "repo.issue.unpin", current,
                   {"number": issue.number}, source_ip)
        return self.pinned_issues(actor, owner, repo)

    def is_pinned(self, viewer: User | None, owner: object,
                  repo: object, number: object) -> bool:
        issue = self._issues.get_issue(viewer, owner, repo, number)
        return self._is_pinned(issue.id)

    def pinned_issues(self, viewer: User | None, owner: object,
                      repo: object) -> list[Issue]:
        """The repository's pinned issues, in pin order."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise IssueError("repo_not_found", "No such repository.")
        from .issues import _row_to_issue
        rows = self._conn.execute(
            "SELECT i.* FROM issues i JOIN issue_pins p"
            " ON p.issue_id = i.id WHERE p.repo_id = ?"
            # Pin order is insertion order (the pin row's own
            # id): two pins in the same second must not reorder
            # by issue number — who was pinned first is the
            # record (S-126's law).
            " ORDER BY p.id",
            (current.id,)).fetchall()
        return [_row_to_issue(r) for r in rows]

    # -- internals -----------------------------------------------------
    def _moderated_issue(self, actor: User, owner: object, repo: object,
                         number: object) -> tuple[Issue, Repository]:
        # get_issue enforces read access + the uniform private
        # answer; moderation then requires repository admin.
        issue = self._issues.get_issue(actor, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        if not can_admin(actor, current):
            raise IssueError(
                "permission_denied",
                "Only a repository moderator can lock or pin an issue.")
        return issue, current

    def _lock_of(self, issue_id: int) -> IssueLock:
        row = self._conn.execute(
            "SELECT locked, lock_reason, locked_by, locked_at"
            " FROM issues WHERE id = ?", (issue_id,)).fetchone()
        if row is None or not row["locked"]:
            return UNLOCKED
        return IssueLock(locked=True, reason=row["lock_reason"],
                         locked_by=row["locked_by"],
                         locked_at=row["locked_at"])

    def _is_pinned(self, issue_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM issue_pins WHERE issue_id = ?",
            (issue_id,)).fetchone()
        return row is not None

    def _emit(self, actor: User, action: str, current: Repository,
              detail: dict, source_ip: str | None) -> None:
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action=action,
                target_kind="repo",
                target_id=f"{current.full_name}#{detail['number']}",
                outcome="success", source_ip=source_ip, detail=detail)
