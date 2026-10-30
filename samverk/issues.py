"""Issues — model and numbering (S-121); create/read/update (S-122).

Part VI opens with the number. In every GitHub-class forge
the habit users rely on is that ``#n`` names exactly one
thing in a repository: an issue *or* a pull request, never
both, never neither once claimed. That habit is a data law,
and this module is where it lives:

- **One shared sequence per repository.** `repo_counters`
  holds each repository's last-issued number. Claiming a
  number is a single atomic upsert (`INSERT ... ON CONFLICT
  ... RETURNING`), so two claims racing on separate
  connections can never receive the same number, and the
  counter only ever moves forward — a number is never
  reused, even if the row that claimed it is later removed
  (a deleted ``#3`` leaves a gap, never a second ``#3``
  meaning something else; links in prose must stay true).
- **A claim is a row.** `issues` is the numbered-items
  table: every claimed number has exactly one row
  (`UNIQUE (repo_id, number)`) carrying its `kind` —
  ``issue`` today, ``pull_request`` when Part VII claims
  its numbers through this same seam. S-127's
  cross-references and S-109's ``issue_exists`` seam read
  through `resolve_number` / `exists`, never around it.
S-122 fills these rows in (title, body, author, state).
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .repositories import Repository, RepositoryStore

KINDS = frozenset({"issue", "pull_request"})
ISSUE_STATES = frozenset({"open", "closed"})
TITLE_MAX = 256
BODY_MAX = 65536


class IssueError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class NumberedItem:
    repo_id: int
    number: int
    kind: str          # 'issue' | 'pull_request'
    row_id: int


class IssueStore:
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
        self._audit = audit
        self._now = time_fn

    # -- S-121: the shared sequence -------------------------------
    def _next_number_tx(self, repo_id: int) -> int:
        """Claim the next number inside the caller's
        transaction. The upsert is one statement, so the
        increment itself is atomic across connections."""
        row = self._conn.execute(
            "INSERT INTO repo_counters (repo_id, last_number)"
            " VALUES (?, 1)"
            " ON CONFLICT (repo_id) DO UPDATE"
            " SET last_number = last_number + 1"
            " RETURNING last_number",
            (repo_id,)).fetchone()
        return int(row["last_number"])

    def _require_repo(self, owner: object, repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise IssueError("repo_not_found", "No such repository.")
        return current

    def claim_number(self, owner: object, repo: object,
                     kind: object, author_id: int) -> NumberedItem:
        """Claim the next shared number for a new numbered
        item of *kind* in this repository. Commits before
        answering: a returned number is durably claimed."""
        if kind not in KINDS:
            raise IssueError(
                "kind_invalid",
                "A numbered item is an issue or a pull request.")
        author = self._accounts.get_by_id(author_id)
        if author is None:
            raise IssueError("no_such_user", "No such account.")
        current = self._require_repo(owner, repo)
        now = int(self._now())
        with self._conn:  # counter and claim row land together
            number = self._next_number_tx(current.id)
            cur = self._conn.execute(
                "INSERT INTO issues (repo_id, number, kind, author_id,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (current.id, number, kind, author.id, now, now))
        return NumberedItem(repo_id=current.id, number=number,
                            kind=str(kind), row_id=int(cur.lastrowid))

    def resolve_number(self, owner: object, repo: object,
                       number: object) -> NumberedItem | None:
        """What a `#n` means in this repository, or None —
        the seam cross-references (S-127) and prose (S-109)
        read through."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not isinstance(number, int) \
                or isinstance(number, bool) or number <= 0:
            return None
        row = self._conn.execute(
            "SELECT * FROM issues WHERE repo_id = ? AND number = ?",
            (current.id, number)).fetchone()
        if row is None:
            return None
        return NumberedItem(repo_id=current.id, number=row["number"],
                            kind=row["kind"], row_id=row["id"])

    def exists(self, owner: object, repo: object, number: object) -> bool:
        return self.resolve_number(owner, repo, number) is not None

    def last_number(self, owner: object, repo: object) -> int:
        current = self._require_repo(owner, repo)
        row = self._conn.execute(
            "SELECT last_number FROM repo_counters WHERE repo_id = ?",
            (current.id,)).fetchone()
        return int(row["last_number"]) if row else 0
