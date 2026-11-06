"""Branch housekeeping (S-159) — merge hook + restore.

Branch housekeeping: delete head branch on merge
(opt-in), restore branch action, fork sync hint. This
module is the slice's server behaviour: the
merge-completion hook and the restore action. The
data/settings layer it rides is migration 58 (the
`deleted_branches` record and the
`delete_branch_on_merge` column on `repo_settings`,
read through `RepoSettingsService`) and the fork sync
hint is a companion surface, not built here.

- **The hook point is after the merge, never in it.**
  The merge services of S-153 (merge commit), S-154
  (squash) and S-155 (rebase) each finish by marking
  the pull request merged inside their own
  transaction; immediately after that transaction
  commits — never inside it, never before it — the
  merge service calls
  `on_pull_request_merged(actor_id, pr_number,
  merge_oid, source_ip=None)`, where `actor_id` is the
  merging user (for S-158 auto-merge, the user whose
  merge actually executes), `pr_number` is the pull
  request's number in the base repository, and
  `merge_oid` is the resulting commit on the base
  branch. The hook is post-commit by design (the
  commit-before-answer lesson): its outcomes are
  reported, never raised into the merge — a
  housekeeping skip or failure can never roll back,
  block, or half-apply a completed merge. It raises
  only on programmer error (an unknown actor, a
  malformed number, an empty merge oid). The call is
  idempotent: a second call for the same pull request
  finds the branch already gone and does nothing,
  emits nothing.
- **One predicate holds every guard.**
  `is_deletable_branch` (with `deletable_guard_reason`
  saying which guard spoke, in words) is the single
  place deletability is judged, checked in this
  order: (1) the opt-in — `delete_branch_on_merge`
  ON for the repository that OWNS the head branch
  (the base repository for a same-repository pull
  request, the fork for a cross-fork one; the base
  repository's setting never deletes branches in a
  repository it does not own) — OFF stops silently;
  (2) merged — the pull request's state is re-read
  through the one seam `_is_merged_state` and must
  read merged, else the outcome is `not_merged`, so
  no other caller can abuse the seam, and the hook
  never fires on close or on a draft (today
  `issues.state` knows only `open`/`closed` — the
  merge slices' marking plugs into that seam when
  it lands, with no change to the hook); (3) the head branch is not the head
  repository's default branch; (4) for a
  same-repository pull request the head branch is
  not the base branch it landed on; (5) the head
  branch is not the head repository's HEAD target;
  (6) the head branch is not protected —
  `_branch_is_protected` is a named seam returning
  no-rules today because branch protection (Part
  VIII, S-169/S-177) does not exist yet; S-177 wires
  the real rule evaluation into THIS predicate, and
  no caller inlines a weaker copy; (7) the ref still
  resolves. Only branch refs are ever touched —
  never tags, never `refs/remotes/*`.
- **Deletion is exact, in an exact order.** Resolve
  the head oid now (the oid resolved here is the oid
  recorded and the oid deleted); delete through
  S-053's compare-and-swap
  (`RefStore.delete_branch(head, expected_old=oid)`)
  — a `stale_ref` means a push raced the merge, and
  the hook stops: no row, no audit event, the merge
  unaffected; only after the ref is actually deleted,
  insert the `deleted_branches` row in one
  transaction (head-owning `repo_id`, branch name,
  exact `head_oid`, `deleted_by` = the merging
  actor, the pull request's row id and number, the
  `merge_oid`); after that commit, append
  `repo.branch.delete_on_merge`. The pull request's
  stored head oid (migration 46) is history and is
  never rewritten when its branch is deleted.
- **Cross-fork rider.** For a cross-fork pull
  request the deletion happens in the fork, and only
  when the merging actor could have deleted that
  branch directly — the fork's owner, or a writer or
  admin on the fork — or when the pull request's
  `maintainer_can_edit` is 1 AND the actor has write
  on the base repository. Otherwise the hook skips
  silently (no row, no event): a merge must never
  delete in a repository the actor has no rights in
  just because the fork opted in.
- **Restore recreates the branch at the exact
  recorded oid.** `restore_branch(actor_user_id,
  owner, repo, deleted_branch_id)` is the service
  behind `POST /{owner}/{repo}/branches/restore`
  (form/JSON field `deleted_branch_id` only — the
  caller never supplies a branch name or an oid, so
  a restore can never be aimed at a different target
  than the one that was deleted), and
  `deleted_branches(viewer, owner, repo)` backs
  `GET /{owner}/{repo}/branches/deleted`, newest
  first, already-restored rows included and said as
  restored. (Samverk's surface is service-first; the
  routes are named here so neither layer is invented
  later, exactly as the design fixes them.) Restore
  is the repository owner's act, or a writer/admin's
  (the S-163 merge-permission class); a stranger to
  a private repository gets the uniform `no_such_repo`
  before any permission question. Refusals are by
  name, write nothing and emit no event:
  `deleted_branch_not_found` (no row with that id in
  this repository, including a row belonging to
  another repository), `already_restored`,
  `branch_exists` (a branch with that name exists
  now, at any oid — restore never overwrites, moves
  or force-updates an existing branch), and
  `oid_unavailable` (the recorded object no longer
  exists in the repository; checked before any
  creation is attempted, and the message says in
  plain words that the commits are gone). On success,
  in order: create the ref through S-053's
  create-only compare-and-swap (a racing creation
  maps to `branch_exists`), stamp `restored_at` /
  `restored_by` on the SAME row in one transaction,
  then append `repo.branch.restore`. The row is
  never deleted — it is the permanent record. A
  restored branch that later heads another merged
  pull request is deleted again under a NEW row:
  history is one row per deletion act, never one
  row per branch name.
- **Audited only on real change** (taxonomy
  append-only +2, 112 events:
  `repo.branch.delete_on_merge` with detail
  `{number, branch, head_repo, oid, merge}`, and
  `repo.branch.restore` with detail `{branch, oid,
  deleted_branch_id}` — never bodies). The opt-in
  flag itself rides the frozen `repo.settings.change`
  through S-066's settings surface. State is always
  said in words, never a colour alone.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .permissions import can_read, can_write
from .refs import RefError, RefStore, branch_ref
from .repositories import Repository, RepositoryError, RepositoryStore

__all__ = [
    "BranchHousekeepingError", "BranchHousekeepingService",
    "DeletedBranch", "MergeHookOutcome",
    "deletable_guard_reason", "is_deletable_branch",
    "render_deleted_branch", "render_deleted_branches",
    "render_merge_note",
]


class BranchHousekeepingError(RepositoryError):
    """A housekeeping refusal, mirroring SettingsError /
    ForkError: a RepositoryError carrying `.reason`."""


@dataclass(frozen=True)
class DeletedBranch:
    id: int
    repo_id: int               # the head-owning repository
    full_name: str             # that repository, owner/repo
    branch_name: str
    head_oid: str              # the exact oid at deletion
    deleted_at: int
    deleted_by: int
    deleted_by_username: str = ""
    pull_request_id: int = 0   # pull_requests row id
    pr_number: int = 0         # number in the base repository
    merge_oid: str = ""
    restored_at: int | None = None
    restored_by: int | None = None
    restored_by_username: str = ""

    @property
    def is_restored(self) -> bool:
        return self.restored_at is not None

    @property
    def state_words(self) -> str:
        """The record's state in words — never a colour alone."""
        return "restored" if self.is_restored else "deleted"

    @property
    def short_oid(self) -> str:
        return self.head_oid[:7]

    @property
    def words(self) -> str:
        who = (self.deleted_by_username
               or f"account #{self.deleted_by}")
        parts = [f"Branch {self.branch_name} — {self.state_words}",
                 f"was at {self.head_oid}",
                 f"deleted by {who} at {self.deleted_at}"]
        if self.pr_number:
            parts.append(f"on pull request #{self.pr_number}")
        if self.is_restored:
            rwho = (self.restored_by_username
                    or (f"account #{self.restored_by}"
                        if self.restored_by is not None
                        else "unknown"))
            parts.append(
                f"restored by {rwho} at {self.restored_at}")
        return "; ".join(parts) + "."


@dataclass(frozen=True)
class MergeHookOutcome:
    """What `on_pull_request_merged` did, in words. Every
    non-deleting outcome is a silent skip for the merge:
    no row was written and no event emitted."""
    outcome: str   # deleted | opted_out | not_merged |
    # pr_not_found | ambiguous_pr | not_deletable |
    # already_gone | stale_ref | fork_no_rights
    pr_number: int = 0
    branch_name: str = ""
    head_repo_full_name: str = ""
    oid: str = ""
    reason: str = ""
    record: DeletedBranch | None = None

    @property
    def deleted(self) -> bool:
        return self.outcome == "deleted"

    @property
    def words(self) -> str:
        if self.outcome == "deleted":
            return (f"Head branch {self.branch_name} in "
                    f"{self.head_repo_full_name} was deleted "
                    f"at {self.oid} after pull request "
                    f"#{self.pr_number} merged, and recorded "
                    "so it can be restored.")
        if self.reason:
            return (f"Head branch {self.branch_name} was "
                    f"kept: {self.reason}")
        return f"Branch housekeeping outcome: {self.outcome}."


def _is_merged_state(state: object) -> bool:
    """The merged-state seam (guard 2).

    At S-159 there is no merge code yet: `issues.state`
    knows only `open` and `closed`, and no merged
    marker exists. The merge slices (S-153..S-155)
    land the merged marking — expected as the state
    value `merged` — and whatever shape it takes, it
    plugs in HERE, in this one function, so the hook's
    re-read never has to be redesigned: today nothing
    reads as merged until those slices mark it, which
    is the safe direction (the hook can never fire
    early)."""
    return state == "merged"


# -- the one deletability predicate --------------------------------

def _branch_is_protected(repo: Repository, branch: str) -> bool:
    """The protection seam (design S-159 §2.4 guard 6).

    Branch protection does not exist yet (Part VIII:
    the rule model lands in S-169, deletion blocking
    in S-177), so at S-159 no protection rule matches
    and this returns False. S-177 wires the real rule
    evaluation into this one function; every caller
    routes through `is_deletable_branch`, never an
    inlined copy, so a branch matching a protection
    pattern becomes undeletable on the merge path
    with no change to the merge path itself."""
    return False


def deletable_guard_reason(repo: Repository, branch: str, *,
                           base_branch: str | None = None,
                           head_target: str | None = None) -> str:
    """Why `branch` in `repo` may not be deleted, in
    words — empty when it may. Guards 3–6 of the
    design, in order: default branch, base branch
    (same-repository pull requests), HEAD target,
    protected."""
    if branch == repo.default_branch:
        return (f"{branch} is the default branch of "
                f"{repo.full_name}.")
    if base_branch is not None and branch == base_branch:
        return "the head branch is the base branch it landed on."
    if head_target is not None and head_target == branch_ref(branch):
        return (f"{branch} is the branch HEAD points at in "
                f"{repo.full_name}.")
    if _branch_is_protected(repo, branch):
        return f"{branch} is a protected branch."
    return ""


def is_deletable_branch(repo: Repository, branch: str, *,
                        base_branch: str | None = None,
                        head_target: str | None = None) -> bool:
    """The one predicate every deletion decision routes
    through (guards 3–6; the opt-in, merged-state and
    still-resolves guards are the hook's, in
    `BranchHousekeepingService.on_pull_request_merged`)."""
    return not deletable_guard_reason(
        repo, branch, base_branch=base_branch,
        head_target=head_target)


class BranchHousekeepingService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        data_root: Path,
        accounts: AccountStore,
        repositories: RepositoryStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._now = time_fn

    # -- internals ---------------------------------------------------
    def _username(self, user_id: int | None) -> str:
        if user_id is None:
            return ""
        user = self._accounts.get_by_id(int(user_id))
        return user.username if user is not None else ""

    def _row_to_record(self, row: sqlite3.Row) -> DeletedBranch:
        repo = self._repos.get_by_id(int(row["repo_id"]))
        restored_by = row["restored_by"]
        restored_by = int(restored_by) if restored_by is not None else None
        restored_at = row["restored_at"]
        return DeletedBranch(
            id=int(row["id"]), repo_id=int(row["repo_id"]),
            full_name=repo.full_name if repo is not None else "",
            branch_name=row["branch_name"], head_oid=row["head_oid"],
            deleted_at=int(row["deleted_at"]),
            deleted_by=int(row["deleted_by"]),
            deleted_by_username=self._username(row["deleted_by"]),
            pull_request_id=int(row["pull_request_id"]),
            pr_number=int(row["pr_number"]),
            merge_oid=row["merge_oid"] or "",
            restored_at=(int(restored_at)
                         if restored_at is not None else None),
            restored_by=restored_by,
            restored_by_username=self._username(restored_by))

    def _record_by_id(self, record_id: int) -> DeletedBranch | None:
        row = self._conn.execute(
            "SELECT * FROM deleted_branches WHERE id = ?",
            (record_id,)).fetchone()
        return self._row_to_record(row) if row is not None else None

    def _setting_on(self, repo_id: int) -> bool:
        """The opt-in as the hook reads it: the
        `delete_branch_on_merge` column (migration 58)
        on the head-owning repository's settings row.
        No row means OFF — the opt-in default."""
        row = self._conn.execute(
            "SELECT delete_branch_on_merge FROM repo_settings"
            " WHERE repo_id = ?", (repo_id,)).fetchone()
        return bool(row["delete_branch_on_merge"]) if row else False

    def _head_repo_for(self, pr_row: sqlite3.Row) -> Repository:
        """The repository that owns the head branch: the
        fork when migration 49 has a row for this pull
        request, else the base repository itself."""
        row = self._conn.execute(
            "SELECT head_repo_id FROM pull_request_forks"
            " WHERE pull_request_id = ?",
            (int(pr_row["pr_id"]),)).fetchone()
        if row is not None:
            head = self._repos.get_by_id(int(row["head_repo_id"]))
            if head is not None:
                return head
        base = self._repos.get_by_id(int(pr_row["base_repo_id"]))
        assert base is not None
        return base

    def _fork_rights(self, actor: User, head_repo: Repository,
                     base_repo: Repository,
                     pr_row: sqlite3.Row) -> bool:
        """The cross-fork rider: the merging actor could
        have deleted the fork's branch directly (fork
        owner, or writer/admin on the fork), or the
        pull request allows maintainer edits and the
        actor has write on the base repository."""
        if actor.username_lower == head_repo.owner_lower:
            return True
        if can_write(actor, head_repo):
            return True
        row = self._conn.execute(
            "SELECT maintainer_can_edit FROM pull_request_forks"
            " WHERE pull_request_id = ?",
            (int(pr_row["pr_id"]),)).fetchone()
        if row is not None and int(row["maintainer_can_edit"]) == 1 \
                and can_write(actor, base_repo):
            return True
        return False

    # -- the merge hook ------------------------------------------------
    def on_pull_request_merged(self, actor_id: int, pr_number: int,
                               merge_oid: str, *,
                               source_ip: str | None = None
                               ) -> MergeHookOutcome:
        """Delete the merged pull request's head branch
        under the opt-in, recording it for restore.

        Called by the S-153/S-154/S-155 merge services
        immediately after their merge transaction
        commits. Every guard outcome is a returned
        `MergeHookOutcome`, never an exception, so a
        skip can never disturb the completed merge;
        only programmer error (unknown actor, malformed
        number, empty merge oid) raises."""
        actor = self._accounts.get_by_id(actor_id) \
            if isinstance(actor_id, int) \
            and not isinstance(actor_id, bool) else None
        if actor is None:
            raise BranchHousekeepingError(
                "no_such_user", "No such account.")
        if not isinstance(pr_number, int) \
                or isinstance(pr_number, bool) or pr_number <= 0:
            raise BranchHousekeepingError(
                "pr_number_invalid",
                "A pull request number is a positive integer.")
        if not isinstance(merge_oid, str) or not merge_oid.strip():
            raise BranchHousekeepingError(
                "merge_oid_required",
                "The hook is called with the merge commit "
                "the merge produced; an empty merge oid is "
                "a programming error at the call site.")
        merge_ref = merge_oid.strip()
        rows = self._conn.execute(
            "SELECT p.id AS pr_id, p.repo_id AS base_repo_id,"
            " p.base_branch, p.head_branch, i.number, i.state"
            " FROM pull_requests p JOIN issues i"
            " ON i.id = p.issue_id WHERE i.number = ?",
            (pr_number,)).fetchall()
        if not rows:
            return MergeHookOutcome(
                outcome="pr_not_found", pr_number=pr_number,
                reason="no pull request has that number.")
        merged = [r for r in rows if _is_merged_state(r["state"])]
        if not merged:
            return MergeHookOutcome(
                outcome="not_merged", pr_number=pr_number,
                branch_name=rows[0]["head_branch"],
                reason="the pull request is not merged.")
        pr = merged[0]
        if len(merged) > 1:
            # The same number merged in more than one
            # repository: the merge commit itself, which
            # must be the base branch's tip in exactly
            # one of them, says which merge this is.
            named = []
            for cand in merged:
                base = self._repos.get_by_id(
                    int(cand["base_repo_id"]))
                if base is None:
                    continue
                path = self._repos.path_for(base.owner, base.name)
                try:
                    tip = RefStore(path).resolve(
                        branch_ref(cand["base_branch"]))
                except RefError:
                    tip = None
                if tip is not None and tip == merge_ref:
                    named.append(cand)
            if len(named) != 1:
                return MergeHookOutcome(
                    outcome="ambiguous_pr", pr_number=pr_number,
                    reason="more than one merged pull request "
                           "has that number and the merge "
                           "commit names none of them.")
            pr = named[0]
        base_repo = self._repos.get_by_id(int(pr["base_repo_id"]))
        assert base_repo is not None
        head_repo = self._head_repo_for(pr)
        branch = pr["head_branch"]
        same_repo = head_repo.id == base_repo.id

        def outcome(name, reason="", oid="", record=None):
            return MergeHookOutcome(
                outcome=name, pr_number=pr_number,
                branch_name=branch,
                head_repo_full_name=head_repo.full_name,
                oid=oid, reason=reason, record=record)

        # The merge must have landed: the named merge
        # commit is the base branch's tip in the base
        # repository (the same test the multi-candidate
        # disambiguation above applies). A state flip
        # alone -- closed, or marked merged with no
        # merge commit carried by the base branch --
        # deletes nothing.
        base_path = self._repos.path_for(base_repo.owner,
                                         base_repo.name)
        try:
            base_tip = RefStore(base_path).resolve(
                branch_ref(pr["base_branch"]))
        except RefError:
            base_tip = None
        if base_tip != merge_ref:
            return outcome(
                "not_merged",
                "the merge commit is not the base branch's "
                "tip, so the merge has not landed on the "
                "base branch.")
        # Guard 1: the opt-in, read from the repository
        # that owns the head branch.
        if not self._setting_on(head_repo.id):
            return outcome(
                "opted_out",
                f"{head_repo.full_name} has not opted in to "
                "deleting head branches on merge.")
        head_path = self._repos.path_for(head_repo.owner,
                                         head_repo.name)
        refs = RefStore(head_path)
        # Guards 3–6: the one predicate.
        reason = deletable_guard_reason(
            head_repo, branch,
            base_branch=pr["base_branch"] if same_repo else None,
            head_target=refs.head_ref())
        if reason:
            return outcome("not_deletable", reason)
        # Cross-fork rider: no rights in the fork, no
        # deletion in the fork.
        if not same_repo and not self._fork_rights(
                actor, head_repo, base_repo, pr):
            return outcome(
                "fork_no_rights",
                "the merging actor has no right to delete "
                f"branches in {head_repo.full_name}.")
        # Guard 7: the ref still resolves — and the oid
        # resolved now is the oid recorded and deleted.
        try:
            head_oid = refs.resolve(branch_ref(branch))
        except RefError:
            head_oid = None
        if head_oid is None:
            return outcome(
                "already_gone", "the head branch is already gone.")
        try:
            refs.delete_branch(branch, expected_old=head_oid)
        except RefError:
            # A push raced the merge and moved the branch:
            # silent skip — no row, no event.
            return outcome(
                "stale_ref",
                "the head branch moved after the merge, so "
                "it was not deleted at a different oid than "
                "the one the merge left.", oid=head_oid)
        now = int(self._now())
        with self._conn:  # the record commits before the answer
            cur = self._conn.execute(
                "INSERT INTO deleted_branches"
                " (repo_id, branch_name, head_oid, deleted_at,"
                " deleted_by, pull_request_id, pr_number,"
                " merge_oid, restored_at, restored_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
                (head_repo.id, branch, head_oid, now, actor.id,
                 int(pr["pr_id"]), pr_number, merge_ref))
            record_id = int(cur.lastrowid)
        record = self._record_by_id(record_id)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.branch.delete_on_merge",
                target_kind="repo",
                target_id=f"{base_repo.full_name}#{pr_number}",
                outcome="success", source_ip=source_ip,
                detail={"number": pr_number, "branch": branch,
                        "head_repo": head_repo.full_name,
                        "oid": head_oid, "merge": merge_ref})
        return outcome("deleted", oid=head_oid, record=record)

    # -- restore -------------------------------------------------------
    def restore_branch(self, actor_user_id: int, owner: object,
                       repo: object, deleted_branch_id: object, *,
                       source_ip: str | None = None) -> DeletedBranch:
        """Recreate one deleted branch at its exact
        recorded oid, from its record alone. The
        service behind `POST /{owner}/{repo}/branches/
        restore` (field `deleted_branch_id` only)."""
        actor = self._accounts.get_by_id(actor_user_id) \
            if isinstance(actor_user_id, int) \
            and not isinstance(actor_user_id, bool) else None
        if actor is None:
            raise BranchHousekeepingError(
                "no_such_user", "No such account.")
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(actor, current):
            raise BranchHousekeepingError(
                "no_such_repo", "No such repository.")
        if not can_write(actor, current):
            raise BranchHousekeepingError(
                "permission_denied",
                "permission_denied — only the repository's "
                "owner or a writer or admin on it can restore "
                "its branches.")
        row = None
        if isinstance(deleted_branch_id, int) \
                and not isinstance(deleted_branch_id, bool):
            row = self._conn.execute(
                "SELECT * FROM deleted_branches"
                " WHERE id = ? AND repo_id = ?",
                (deleted_branch_id, current.id)).fetchone()
        if row is None:
            raise BranchHousekeepingError(
                "deleted_branch_not_found",
                "deleted_branch_not_found — there is no "
                "deleted-branch record by that id in this "
                "repository. Nothing was restored.")
        record = self._row_to_record(row)
        if record.is_restored:
            raise BranchHousekeepingError(
                "already_restored",
                "already_restored — that deletion record "
                f"was already restored at {record.restored_at}. "
                "Nothing was restored.")
        path = self._repos.path_for(current.owner, current.name)
        refs = RefStore(path)
        try:
            existing = refs.resolve(branch_ref(record.branch_name))
        except RefError:
            existing = None
        if existing is not None:
            raise BranchHousekeepingError(
                "branch_exists",
                f"branch_exists — a branch named "
                f"{record.branch_name!r} already exists in "
                f"{current.full_name} at {existing}. Restore "
                "never overwrites an existing branch; nothing "
                "was restored.")
        try:
            object_there = refs.resolve(record.head_oid)
        except RefError:
            object_there = None
        if object_there is None:
            raise BranchHousekeepingError(
                "oid_unavailable",
                "oid_unavailable — the commit this branch "
                f"pointed at ({record.head_oid}) is no longer "
                f"in {current.full_name}; the commits are "
                "gone, so the branch cannot be restored. "
                "Nothing was restored.")
        try:
            refs.create_branch(record.branch_name, record.head_oid)
        except RefError:
            raise BranchHousekeepingError(
                "branch_exists",
                f"branch_exists — a branch named "
                f"{record.branch_name!r} already exists in "
                f"{current.full_name}. Nothing was restored."
            ) from None
        now = int(self._now())
        with self._conn:  # the stamp commits before the answer
            self._conn.execute(
                "UPDATE deleted_branches SET restored_at = ?,"
                " restored_by = ? WHERE id = ?",
                (now, actor.id, record.id))
        restored = self._record_by_id(record.id)
        assert restored is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.branch.restore", target_kind="repo",
                target_id=current.full_name, outcome="success",
                source_ip=source_ip,
                detail={"branch": record.branch_name,
                        "oid": record.head_oid,
                        "deleted_branch_id": record.id})
        return restored

    # -- reads -----------------------------------------------------------
    def deleted_branches(self, viewer: User | None, owner: object,
                         repo: object) -> tuple:
        """Every deletion record for this repository,
        newest first, already-restored rows included.
        Backs `GET /{owner}/{repo}/branches/deleted`."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise BranchHousekeepingError(
                "no_such_repo", "No such repository.")
        rows = self._conn.execute(
            "SELECT * FROM deleted_branches WHERE repo_id = ?"
            " ORDER BY id DESC", (current.id,)).fetchall()
        return tuple(self._row_to_record(r) for r in rows)

    def deleted_branch_for_pull_request(
            self, viewer: User | None, owner: object, repo: object,
            number: object) -> DeletedBranch | None:
        """The newest deletion record one pull request's
        merge left, or None — the record the merged-PR
        page renders its note from (never a guess from
        a missing ref)."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise BranchHousekeepingError(
                "no_such_repo", "No such repository.")
        row = self._conn.execute(
            "SELECT d.* FROM deleted_branches d"
            " JOIN pull_requests p ON p.id = d.pull_request_id"
            " JOIN issues i ON i.id = p.issue_id"
            " WHERE p.repo_id = ? AND i.number = ?"
            " ORDER BY d.id DESC LIMIT 1",
            (current.id, number)).fetchone()
        return self._row_to_record(row) if row is not None else None


def render_merge_note(record: DeletedBranch) -> str:
    """The merged pull request page's sentence about its
    head branch, in words — never a colour alone."""
    if record.is_restored:
        return (f'<p class="branch-housekeeping">The head branch '
                f"{escape_html_text(record.branch_name)} was "
                f"restored to {escape_html_text(record.short_oid)}"
                ".</p>")
    return (f'<p class="branch-housekeeping">The head branch '
            f"{escape_html_text(record.branch_name)} was deleted "
            "when this pull request merged.</p>")


def render_deleted_branch(record: DeletedBranch) -> str:
    """One deletion record, in plain words."""
    return ('<li class="deleted-branch">'
            f"{escape_html_text(record.words)}</li>")


def render_deleted_branches(records) -> str:
    """The deleted-branches list: branch name, oid, when,
    by whom, pull request number and restored state, all
    in words — or the honest empty sentence."""
    rows = list(records)
    if not rows:
        return ('<p class="deleted-branches">No branches have '
                "been deleted on merge in this repository.</p>")
    items = "".join(render_deleted_branch(r) for r in rows)
    return f'<ul class="deleted-branches">{items}</ul>'
