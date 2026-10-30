"""Bulk edit (S-134).

One edit applied across a filtered set of issues —
labelling, assigning, or closing many issues in one act,
with **one audit event per issue** from the seams that
already own those acts.

- **The set is explicit, the filter is a seam.**
  `bulk_edit` takes the set as issue numbers — the
  selection a surface (or S-135's search) already made.
  `select_numbers` computes a set from plain criteria
  (state, label, assignee, milestone, author) through the
  existing read seams, so a filter and a hand-picked list
  arrive at the same door. A set is capped at
  `MAX_BULK_SET` (100): a larger set is refused
  `set_too_large` naming the cap, never silently
  truncated, and an empty set is refused `empty_set`.
- **Operation parameters are validated whole, first.**
  At least one operation is required (`no_operation`);
  a closing reason must be in S-130's vocabulary
  (`reason_invalid`), the label must exist
  (`label_not_found`), and the assignee must be an
  account (`no_such_user`) — all checked before any
  issue is touched, so a misspelled bulk edit changes
  nothing at all rather than half the set.
- **Per-issue outcomes are reported, not hidden.**
  Each issue is then edited through its owning seam —
  S-124's label seam, S-126's assignee seam, S-130's
  close — so permissions are per-issue exactly as the
  single edits decide them (the author may label their
  own issue in a set where a neighbour's refuses), each
  real change writes that seam's own audit event for
  that issue, and the result names every success and
  every failure with its reason. A number that is not
  an issue fails as `issue_not_found` for that number
  alone; the rest of the set still lands.
- **Retries are quiet.** An issue already carrying the
  label, already assigned, or already closed is a
  success that writes no second audit event — the
  seams' standing no-op law, checked here for labels
  (whose seam would otherwise speak) exactly as the
  assignee and close seams check themselves.
- **No audit event of its own.** The bulk act is the
  sum of its per-issue acts, each already witnessed by
  its seam — the S-127/S-131 pattern for composed work.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .accounts import AccountStore, User
from .assignees import AssigneeStore
from .issues import CLOSE_REASONS, IssueError, IssueStore
from .labels import LabelStore
from .repositories import RepositoryStore

MAX_BULK_SET = 100


@dataclass(frozen=True)
class BulkFailure:
    number: int
    reason: str


@dataclass(frozen=True)
class BulkResult:
    succeeded: tuple[int, ...]
    failures: tuple[BulkFailure, ...] = field(default_factory=tuple)

    @property
    def attempted(self) -> int:
        return len(self.succeeded) + len(self.failures)


class BulkEditStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        labels: LabelStore,
        assignees: AssigneeStore,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._labels = labels
        self._assignees = assignees

    # -- the filtered set -----------------------------------------------
    def select_numbers(self, viewer: User | None, owner: object,
                       repo: object, *, state: str | None = None,
                       label: str | None = None,
                       assignee: str | None = None,
                       milestone: str | None = None,
                       author: str | None = None) -> list[int]:
        """The numbers matching every given criterion, in
        number order — the filtered set `bulk_edit` (or a
        surface showing the selection) consumes."""
        selected = self._issues.list_issues(viewer, owner, repo, state=state)
        numbers: list[int] = []
        milestone_titles: dict[int, str] = {}
        if milestone is not None:
            current = self._repos.get_repository(owner, repo)
            assert current is not None
            milestone_titles = {
                int(r["id"]): r["title"] for r in self._conn.execute(
                    "SELECT id, title FROM milestones WHERE repo_id = ?",
                    (current.id,)).fetchall()}
        for issue in selected:
            if label is not None:
                names = {l.name_lower for l in self._labels.labels_for_issue(
                    viewer, owner, repo, issue.number)}
                if label.lower() not in names:
                    continue
            if assignee is not None:
                names = {a.username.lower() for a in
                         self._assignees.assignees_for_issue(
                             viewer, owner, repo, issue.number)}
                if assignee.lower() not in names:
                    continue
            if author is not None:
                writer = self._accounts.get_by_id(issue.author_id)
                if writer is None or writer.username_lower != author.lower():
                    continue
            if milestone is not None:
                row = self._conn.execute(
                    "SELECT milestone_id FROM issues WHERE id = ?",
                    (issue.id,)).fetchone()
                title = milestone_titles.get(row["milestone_id"]) \
                    if row is not None and row["milestone_id"] else None
                if title is None or title.lower() != milestone.lower():
                    continue
            numbers.append(issue.number)
        return numbers

    # -- the edit ----------------------------------------------------------
    def bulk_edit(self, actor: User, owner: object, repo: object,
                  numbers: object, *, add_label: object = None,
                  assign: object = None, close_reason: object = None,
                  source_ip: str | None = None) -> BulkResult:
        if add_label is None and assign is None and close_reason is None:
            raise IssueError(
                "no_operation",
                "A bulk edit must say what it changes: a label, "
                "an assignee, or a closing.")
        if close_reason is not None and close_reason not in CLOSE_REASONS:
            raise IssueError(
                "reason_invalid",
                "An issue closes as 'completed' or 'not_planned'.")
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise IssueError("repo_not_found", "No such repository.")
        # Whole-set validation of the operation parameters:
        # a bad label or assignee changes nothing at all.
        if add_label is not None:
            found = self._conn.execute(
                "SELECT 1 FROM labels WHERE repo_id = ? AND name_lower = ?",
                (current.id, str(add_label).lower())).fetchone()
            if found is None:
                raise IssueError("label_not_found", "No such label.")
        if assign is not None:
            target = self._accounts.get_by_username(assign) \
                if isinstance(assign, str) else None
            if target is None:
                raise IssueError("no_such_user", "No such account.")
        if not isinstance(numbers, (list, tuple)) or not numbers:
            raise IssueError(
                "empty_set", "A bulk edit needs at least one issue.")
        unique = sorted({n for n in numbers
                         if isinstance(n, int) and not isinstance(n, bool)})
        if len(unique) != len(numbers):
            raise IssueError(
                "number_invalid", "Issue numbers must be whole numbers.")
        if not unique:
            raise IssueError(
                "empty_set", "A bulk edit needs at least one issue.")
        if len(unique) > MAX_BULK_SET:
            raise IssueError(
                "set_too_large",
                f"A bulk edit covers at most {MAX_BULK_SET} issues "
                "at once; narrow the set and run it in parts.")
        succeeded: list[int] = []
        failures: list[BulkFailure] = []
        for number in unique:
            try:
                if add_label is not None:
                    present = {l.name_lower for l in
                               self._labels.labels_for_issue(
                                   actor, owner, repo, number)}
                    if str(add_label).lower() not in present:
                        self._labels.add_to_issue(
                            actor, owner, repo, number, add_label,
                            source_ip=source_ip)
                if assign is not None:
                    self._assignees.assign(
                        actor, owner, repo, number, assign,
                        source_ip=source_ip)
                if close_reason is not None:
                    self._issues.close_issue(
                        actor, owner, repo, number, close_reason,
                        source_ip=source_ip)
            except ValueError as exc:  # Issue/Label/Assignee errors
                failures.append(BulkFailure(
                    number=number,
                    reason=getattr(exc, "reason", "failed")))
                continue
            succeeded.append(number)
        return BulkResult(succeeded=tuple(succeeded),
                          failures=tuple(failures))
