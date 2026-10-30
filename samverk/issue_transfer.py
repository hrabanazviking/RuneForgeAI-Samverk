"""Issue transfer (S-133).

Moving an issue between repositories of the *same owner*,
with a forwarding note left behind at the old address.

- **Same owner only.** A transfer crosses repositories,
  never ownership: the destination's canonical owner must
  equal the source's, or the move is refused
  `different_owner` and nothing changes. (Ownership itself
  moves only through S-057's accepted repo transfer.)
  Transferring to the same repository is refused
  `same_repository`.
- **The issue travels whole.** The issue row itself moves:
  it claims the destination's next shared number (S-121's
  sequence, claimed inside the same transaction, so the
  vacated source number is a permanent gap, never reused)
  and keeps its author, title, body, state and closing
  reason, lock, comments, assignees, reactions, and state
  history — everything keyed by the issue's row id travels
  with it. Repository-scoped dressing is remapped by name
  or dropped, never carried by id into a foreign scope:
  a label whose name exists in the destination is carried
  onto the destination's label of that name, others are
  dropped and named in the result; the milestone likewise
  remaps by title, or clears; a pin belongs to the source
  repository's front page and is left behind.
- **A forwarding note is left behind.** An
  `issue_transfers` row records the vacated
  (repository, number), the destination, the mover, and
  the time. `forwarding_for` is the seam old links read:
  it answers under the source repository's read gate, and
  names the destination only to a viewer who can also
  read it — to anyone else the note says, in words, that
  the issue was transferred to another repository.
- **Permissions ride the repositories'.** The mover must
  be the issue's author or a source-repository writer
  (the hands S-122 trusts with edits), and must be able
  to read the destination (the gate S-122's creation
  requires); a missing or unreadable destination answers
  the uniform `repo_not_found`, and a stranger to the
  source gets S-122's uniform `issue_not_found`.
- **Audited on both sides.** `repo.issue.transfer_out`
  on the source and `repo.issue.transfer_in` on the
  destination (taxonomy append-only +2, 85 events), so
  the destination's timeline (S-131) can say where the
  issue came from and the source's record says where it
  went. Numbers and repository names only — never title
  or body.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import Issue, IssueError, IssueStore
from .permissions import can_read, can_write
from .repositories import Repository, RepositoryStore


@dataclass(frozen=True)
class IssueTransfer:
    """The completed move, as answered to the mover."""
    issue: Issue                 # the issue at its new address
    source_repo: str             # full name it left
    source_number: int
    dest_repo: str               # full name it joined
    dest_number: int
    labels_carried: tuple[str, ...]
    labels_dropped: tuple[str, ...]
    milestone_carried: bool


@dataclass(frozen=True)
class ForwardingNote:
    """The note at a vacated address. `dest_repo` is ''
    and `dest_number` 0 when the viewer may not read the
    destination — the move is said, the address is not."""
    source_repo: str
    source_number: int
    dest_repo: str
    dest_number: int
    transferred_by: int
    created_at: int

    @property
    def words(self) -> str:
        """The note in plain words — never a colour alone."""
        if self.dest_repo:
            return (f"This issue was transferred to "
                    f"{self.dest_repo}#{self.dest_number}")
        return "This issue was transferred to another repository"


def render_forwarding(note: ForwardingNote) -> str:
    """The forwarding note as an HTML paragraph; every
    value passes S-010's escaping seam."""
    return ('<p class="forwarding-note">'
            + escape_html_text(note.words) + "</p>")


class IssueTransferStore:
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

    # -- the move ------------------------------------------------------
    def transfer_issue(self, actor: User, owner: object, repo: object,
                       number: object, dest_owner: object,
                       dest_repo: object,
                       *, source_ip: str | None = None) -> IssueTransfer:
        issue = self._issues.get_issue(actor, owner, repo, number)
        source = self._repos.get_repository(owner, repo)
        assert source is not None
        if actor.id != issue.author_id and not can_write(actor, source):
            raise IssueError(
                "permission_denied",
                "Only the author or a repository writer can "
                "transfer this issue.")
        dest = self._repos.get_repository(dest_owner, dest_repo)
        if dest is None or not can_read(actor, dest):
            raise IssueError("repo_not_found", "No such repository.")
        if dest.id == source.id:
            raise IssueError(
                "same_repository",
                "An issue cannot be transferred to its own repository.")
        if dest.owner_lower != source.owner_lower:
            raise IssueError(
                "different_owner",
                "An issue can only move between repositories of "
                "the same owner.")
        now = int(self._now())
        # Repository-scoped dressing, read before the move:
        # labels and the milestone remap by name/title.
        label_rows = self._conn.execute(
            "SELECT l.name, l.name_lower FROM labels l"
            " JOIN issue_labels il ON il.label_id = l.id"
            " WHERE il.issue_id = ? ORDER BY l.name_lower",
            (issue.id,)).fetchall()
        dest_labels = {r["name_lower"]: int(r["id"]) for r in
                       self._conn.execute(
                           "SELECT id, name_lower FROM labels"
                           " WHERE repo_id = ?", (dest.id,)).fetchall()}
        carried: list[str] = []
        dropped: list[str] = []
        new_label_ids: list[int] = []
        for row in label_rows:
            if row["name_lower"] in dest_labels:
                carried.append(row["name"])
                new_label_ids.append(dest_labels[row["name_lower"]])
            else:
                dropped.append(row["name"])
        new_milestone_id: int | None = None
        milestone_carried = False
        milestone_row = self._conn.execute(
            "SELECT milestone_id FROM issues WHERE id = ?",
            (issue.id,)).fetchone()
        old_milestone_id = (milestone_row["milestone_id"]
                            if milestone_row is not None else None)
        if old_milestone_id is not None:
            old = self._conn.execute(
                "SELECT title, title_lower FROM milestones WHERE id = ?",
                (old_milestone_id,)).fetchone()
            if old is not None:
                match = self._conn.execute(
                    "SELECT id FROM milestones WHERE repo_id = ?"
                    " AND title_lower = ?",
                    (dest.id, old["title_lower"])).fetchone()
                if match is not None:
                    new_milestone_id = int(match["id"])
                    milestone_carried = True
        with self._conn:  # the move lands whole, or not at all
            new_number = self._issues._next_number_tx(dest.id)
            self._conn.execute(
                "UPDATE issues SET repo_id = ?, number = ?,"
                " milestone_id = ?, version = version + 1,"
                " updated_at = ? WHERE id = ?",
                (dest.id, new_number, new_milestone_id, now, issue.id))
            self._conn.execute(
                "DELETE FROM issue_labels WHERE issue_id = ?", (issue.id,))
            for label_id in new_label_ids:
                self._conn.execute(
                    "INSERT OR IGNORE INTO issue_labels (issue_id,"
                    " label_id, created_at) VALUES (?, ?, ?)",
                    (issue.id, label_id, now))
            self._conn.execute(
                "DELETE FROM issue_pins WHERE issue_id = ?", (issue.id,))
            self._conn.execute(
                "INSERT INTO issue_transfers (issue_id, source_repo_id,"
                " source_number, dest_repo_id, dest_number, actor_id,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (issue.id, source.id, issue.number, dest.id,
                 new_number, actor.id, now))
        moved = self._issues.get_issue(actor, dest_owner, dest_repo,
                                       new_number)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.issue.transfer_out", target_kind="repo",
                target_id=f"{source.full_name}#{issue.number}",
                outcome="success", source_ip=source_ip,
                detail={"number": issue.number, "to": dest.full_name,
                        "to_number": new_number})
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.issue.transfer_in", target_kind="repo",
                target_id=f"{dest.full_name}#{new_number}",
                outcome="success", source_ip=source_ip,
                detail={"number": new_number, "from": source.full_name,
                        "from_number": issue.number})
        return IssueTransfer(
            issue=moved, source_repo=source.full_name,
            source_number=issue.number, dest_repo=dest.full_name,
            dest_number=new_number, labels_carried=tuple(carried),
            labels_dropped=tuple(dropped),
            milestone_carried=milestone_carried)

    # -- the forwarding note --------------------------------------------
    def forwarding_for(self, viewer: User | None, owner: object,
                       repo: object, number: object
                       ) -> ForwardingNote | None:
        """The note at a vacated address, or None when no
        transfer left one (or the address never existed).
        The source's read gate decides who may learn a
        move happened; the destination is named only to a
        viewer who can read it too."""
        source = self._repos.get_repository(owner, repo)
        if source is None or not can_read(viewer, source):
            raise IssueError("repo_not_found", "No such repository.")
        if not isinstance(number, int) or isinstance(number, bool) \
                or number <= 0:
            return None
        row = self._conn.execute(
            "SELECT * FROM issue_transfers WHERE source_repo_id = ?"
            " AND source_number = ?", (source.id, number)).fetchone()
        if row is None:
            return None
        dest = self._repos.get_by_id(int(row["dest_repo_id"]))
        named = dest is not None and can_read(viewer, dest)
        return ForwardingNote(
            source_repo=source.full_name, source_number=int(row["source_number"]),
            dest_repo=dest.full_name if named else "",
            dest_number=int(row["dest_number"]) if named else 0,
            transferred_by=int(row["actor_id"]),
            created_at=int(row["created_at"]))
