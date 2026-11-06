"""Pull request revert (S-160).

One click undoes a merged pull request — as a new pull
request of its own, linked both ways, never as a quiet
force-push or a hand edit to the base branch.

- **Merged-only, in words.** A pull request can be
  reverted only once it has landed. The landed pair
  (`merged_oid`, the base tip just after landing, and
  `pre_merge_oid`, the base tip just before) is resolved
  in authority order: an explicit pair passed by the
  caller; a `pull_request_merges` row when that table
  exists (S-153's record, shared by S-154's squash
  rows — only the two columns both schemas share,
  `merge_commit_oid` and `base_oid`, are read); and,
  on a base with no merge record at all, a git
  derivation — the commit on the base branch's
  first-parent chain whose second parent is the landed
  head. A squash or rebase landing with neither a
  record nor an explicit pair is refused
  `pull_request_not_merged` rather than guessed at:
  an open or draft pull request is never merged, and
  a closed-but-unmerged one is named as such.
- **Same repository only.** A cross-fork pull request
  (a `pull_request_forks` row exists) is refused
  `revert_cross_fork` — its head lives in another
  repository, so a revert branch minted here would
  propose nothing it can undo.
- **The git act is revert_git's, unchanged.**
  `land_revert` mints one commit on the current base
  tip (merge-tree inverse, commit-tree commit) and
  creates the branch `revert-<number>-<head branch>`
  by compare-and-swap. Its refusals pass through
  with their reasons (`revert_conflict` with the
  conflicted paths named, `revert_empty`,
  `branch_taken`, `base_not_found`): a refused revert
  creates no pull request and no link row.
- **The revert is an ordinary pull request.** It is
  opened through S-141's `create_pull_request` (so
  it claims the shared number, is born open, and is
  audited `repo.pull_request.create`), with the title
  `Revert "<original title>"` and a body naming the
  pull request it reverts and the landing commit. If
  opening or recording then fails, the just-minted
  branch is deleted again (all-or-nothing, S-137) —
  no half-revert is ever left behind.
- **Linked both ways in one table** (migration 60).
  `pull_request_reverts` carries one row per revert
  PR: which PR it reverts, the landing pair, the
  revert commit, the branch, and who made it.
  Presence of a row IS the link, read forwards as
  `revert_of` and backwards as `reverted_by`.
- **One open revert at a time.** While a revert PR
  for an original is still open, a second attempt is
  refused `already_reverted`, naming its number. A
  revert PR closed unmerged does not block a fresh
  attempt. A revert PR is itself an ordinary pull
  request, so once it merges it can itself be
  reverted — that re-applies the original change,
  and the new link chains onto the old one.
- **Writers only.** Reverting is a writer act on the
  base repository (`permission_denied` for a mere
  reader; a stranger to a private repository gets
  S-141's uniform `pull_request_not_found` before
  any permission question).
- **Audited under its own event** (taxonomy
  append-only +1: `repo.pull_request.revert`, 111
  events on this branch). The detail names the
  original number, the revert number, the revert
  commit, the branch, and the landing commit — never
  the title or body.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issue_conversion import PullRequest
from .issues import IssueStore
from .objects import ObjectError, ObjectReader
from .permissions import can_write
from .proc import run_git_in
from .pull_requests import PullRequestError, PullRequestStore
from .refs import RefError, RefStore, branch_ref
from .repositories import RepositoryStore
from .revert_git import (
    RevertError, compute_revert_tree, default_revert_branch_name,
    default_revert_message, describe_merged_change,
    describe_merged_range, land_revert,
)

__all__ = [
    "PullRequestRevertStore", "RevertLinks", "RevertPreview",
    "RevertRecord", "RevertResult", "render_revert_links",
    "render_revert_preview", "render_revert_result",
]

_REVERT_SELECT = (
    "SELECT r.*,"
    " (SELECT number FROM issues WHERE id ="
    "  (SELECT issue_id FROM pull_requests"
    "   WHERE id = r.pull_request_id)) AS revert_number,"
    " (SELECT number FROM issues WHERE id ="
    "  (SELECT issue_id FROM pull_requests"
    "   WHERE id = r.original_pull_request_id))"
    " AS original_number"
    " FROM pull_request_reverts r")


@dataclass(frozen=True)
class RevertRecord:
    id: int
    pull_request_id: int     # the revert PR's pull_requests.id
    revert_number: int       # the revert PR's #n
    original_pull_request_id: int
    original_number: int     # the reverted PR's #n
    repo_id: int
    merged_oid: str
    pre_merge_oid: str
    revert_commit_oid: str
    revert_branch: str
    base_branch: str
    created_by: int | None
    created_at: int

    @property
    def words(self) -> str:
        return (f"Pull request #{self.revert_number} reverts "
                f"pull request #{self.original_number}, landed "
                f"in commit {self.merged_oid[:12]}, as commit "
                f"{self.revert_commit_oid[:12]} on branch "
                f"{self.revert_branch}.")


@dataclass(frozen=True)
class RevertPreview:
    pull_request: PullRequest
    merged_oid: str          # '' when no landing is known
    pre_merge_oid: str       # '' when no landing is known
    branch_name: str
    plan_words: str
    blockers: tuple          # of str, in words

    @property
    def can_revert(self) -> bool:
        return not self.blockers

    @property
    def words(self) -> str:
        if self.blockers:
            return self.blockers[0]
        return (f"Ready to revert — pull request "
                f"#{self.pull_request.number} landed in commit "
                f"{self.merged_oid[:12]}, and the revert applies "
                f"cleanly to {self.pull_request.base_branch} "
                f"as it stands.")


@dataclass(frozen=True)
class RevertResult:
    original: PullRequest
    revert: PullRequest      # the new, open revert PR
    record: RevertRecord
    commit_oid: str
    branch: str
    merged_oid: str
    pre_merge_oid: str

    @property
    def words(self) -> str:
        return (f"Pull request #{self.revert.number} reverts "
                f"pull request #{self.original.number}: one "
                f"revert commit {self.commit_oid[:12]} on "
                f"branch {self.branch}, proposing into "
                f"{self.original.base_branch}.")


@dataclass(frozen=True)
class RevertLinks:
    number: int
    reverts: RevertRecord | None   # this PR reverts #X, or None
    reverted_by: tuple             # of RevertRecord, this PR was
    # reverted by these PRs, oldest first

    @property
    def words(self) -> str:
        parts = []
        if self.reverts is not None:
            parts.append(
                f"This pull request reverts "
                f"#{self.reverts.original_number}.")
        if self.reverted_by:
            numbers = ", ".join(
                f"#{r.revert_number}" for r in self.reverted_by)
            parts.append(
                f"Pull request #{self.number} was reverted "
                f"by {numbers}.")
        return " ".join(parts) if parts else (
            f"Pull request #{self.number} has no revert link.")


def _row_to_record(row: sqlite3.Row) -> RevertRecord:
    return RevertRecord(
        id=int(row["id"]),
        pull_request_id=int(row["pull_request_id"]),
        revert_number=int(row["revert_number"] or 0),
        original_pull_request_id=int(
            row["original_pull_request_id"]),
        original_number=int(row["original_number"] or 0),
        repo_id=int(row["repo_id"]),
        merged_oid=row["merged_oid"] or "",
        pre_merge_oid=row["pre_merge_oid"] or "",
        revert_commit_oid=row["revert_commit_oid"] or "",
        revert_branch=row["revert_branch"] or "",
        base_branch=row["base_branch"] or "",
        created_by=(int(row["created_by"])
                    if row["created_by"] is not None else None),
        created_at=int(row["created_at"]))


class PullRequestRevertStore:
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
        self._prs = PullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    # -- internals -------------------------------------------------
    def _table_exists(self, name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master"
            " WHERE type = 'table' AND name = ?",
            (name,)).fetchone()
        return row is not None

    def _require_writable_pr(self, actor: User, owner, repo,
                             number):
        """The write-side read: S-141's uniform not-found, then
        the writer gate, then the repository it landed in."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        if not can_write(actor, current):
            raise PullRequestError(
                "permission_denied",
                "Only a repository writer can revert a pull "
                "request in this repository.")
        return pr, current

    def _is_cross_fork(self, pr: PullRequest) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM pull_request_forks"
            " WHERE pull_request_id = ?", (pr.id,)).fetchone()
        return row is not None

    def _merge_record_pair(self, pr: PullRequest):
        """The pair from a S-153/S-154 landing record, when that
        table exists on this instance at all; None otherwise.
        Only the columns both schemas share are read."""
        if not self._table_exists("pull_request_merges"):
            return None
        row = self._conn.execute(
            "SELECT merge_commit_oid, base_oid FROM"
            " pull_request_merges WHERE pull_request_id = ?",
            (pr.id,)).fetchone()
        if row is None or not row["merge_commit_oid"]:
            return None
        return (str(row["merge_commit_oid"]),
                str(row["base_oid"] or ""))

    def _derive_pair(self, pr: PullRequest, current):
        """The pair from git alone: the commit on the base
        branch's first-parent chain whose second parent is the
        landed head (the live head-branch tip when the branch
        still exists — S-159 may have deleted it on merge —
        else the head oid the merge slices refreshed onto the
        PR's row at landing)."""
        path = self._repos.path_for(current.owner, current.name)
        refs = RefStore(path)
        base_oid = refs.resolve(branch_ref(pr.base_branch))
        if base_oid is None:
            return None
        candidates = []
        head_tip = refs.resolve(branch_ref(pr.head_branch))
        if head_tip:
            candidates.append(head_tip)
        if pr.head_oid and pr.head_oid not in candidates:
            candidates.append(pr.head_oid)
        if not candidates:
            return None
        result = run_git_in(
            path, ["rev-list", "--first-parent", base_oid],
            timeout=30.0)
        if result.returncode != 0:
            return None
        reader = ObjectReader(path)
        for line in result.stdout.decode().splitlines():
            oid = line.strip()
            if not oid:
                continue
            try:
                commit = reader.read_commit(oid)
            except ObjectError:
                return None
            if len(commit.parents) >= 2 and any(
                    p in candidates for p in commit.parents[1:]):
                return (oid, commit.parents[0])
            if commit.parents and commit.parents[0] in candidates:
                continue  # walking past the landing, keep going
        return None

    def _resolve_pair(self, pr: PullRequest, current,
                      merged_oid, pre_merge_oid,
                      first_landed_oid):
        """(merged_oid, pre_merge_oid) by the authority order of
        the module docstring, or None when no landing is known.
        An explicit merged_oid with no pre_merge_oid derives the
        pre-merge base from git (one-commit landing, or the
        rebase range when first_landed_oid is given)."""
        if merged_oid is not None:
            path = self._repos.path_for(current.owner, current.name)
            try:
                if first_landed_oid is not None:
                    change = describe_merged_range(
                        path, first_landed_oid, merged_oid)
                else:
                    change = describe_merged_change(
                        path, merged_oid, pre_merge_oid)
            except RevertError as exc:
                raise PullRequestError(
                    exc.reason, str(exc)) from None
            return (change.merged_oid, change.pre_merge_oid)
        if pre_merge_oid is not None:
            raise PullRequestError(
                "merged_invalid",
                "A pre-merge commit was given without the "
                "landing commit it belongs to.")
        pair = self._merge_record_pair(pr)
        if pair is not None and pair[1]:
            return pair
        if pair is not None:
            # A record with no recorded pre-merge base: derive it
            # from the landing commit's first parent.
            path = self._repos.path_for(current.owner, current.name)
            try:
                change = describe_merged_change(path, pair[0])
            except RevertError:
                return pair
            return (change.merged_oid, change.pre_merge_oid)
        return self._derive_pair(pr, current)

    def _open_revert(self, pr: PullRequest) -> RevertRecord | None:
        row = self._conn.execute(
            _REVERT_SELECT
            + " JOIN issues i ON i.id ="
            "  (SELECT issue_id FROM pull_requests"
            "   WHERE id = r.pull_request_id)"
            " WHERE r.original_pull_request_id = ?"
            " AND i.state = 'open' ORDER BY r.id LIMIT 1",
            (pr.id,)).fetchone()
        return _row_to_record(row) if row else None

    def _validate_revertable(self, pr: PullRequest) -> None:
        """The merged-only and one-open-revert gates, shared by
        the preview and the act. Pair resolution stays the
        caller's question — an unknown landing is not the same
        refusal as an unmerged pull request."""
        if pr.state != "closed":
            raise PullRequestError(
                "pull_request_not_merged",
                f"Pull request #{pr.number} has not been "
                "merged; only a merged pull request can be "
                "reverted.")
        if self._is_cross_fork(pr):
            raise PullRequestError(
                "revert_cross_fork",
                f"Pull request #{pr.number} came from a fork; "
                "only a same-repository pull request can be "
                "reverted here.")
        open_revert = self._open_revert(pr)
        if open_revert is not None:
            raise PullRequestError(
                "already_reverted",
                f"Pull request #{pr.number} already has an "
                f"open revert: #{open_revert.revert_number}.")

    # -- preview ---------------------------------------------------
    def preview_revert(self, actor: User, owner: object,
                       repo: object, number: object, *,
                       merged_oid=None, pre_merge_oid=None,
                       first_landed_oid=None) -> RevertPreview:
        """What the one click would do, before it is done: the
        landing pair, the off-path plan's verdict in words, and
        every blocker — nothing is written."""
        pr, current = self._require_writable_pr(
            actor, owner, repo, number)
        branch = default_revert_branch_name(
            pr.number, pr.head_branch)
        blockers: list[str] = []
        pair = None
        try:
            self._validate_revertable(pr)
        except PullRequestError as exc:
            blockers.append(str(exc))
        if not blockers:
            pair = self._resolve_pair(
                pr, current, merged_oid, pre_merge_oid,
                first_landed_oid)
            if pair is None:
                blockers.append(
                    f"No landing is recorded for pull request "
                    f"#{pr.number}: its changes cannot be named, "
                    "so they cannot be reverted.")
        plan_words = ""
        if pair is not None and not blockers:
            path = self._repos.path_for(current.owner, current.name)
            refs = RefStore(path)
            base_oid = refs.resolve(branch_ref(pr.base_branch))
            if base_oid is None:
                blockers.append(
                    f"The base branch {pr.base_branch!r} does "
                    "not exist in this repository yet.")
            else:
                try:
                    plan = compute_revert_tree(
                        path, current_oid=base_oid,
                        merged_oid=pair[0], pre_merge_oid=pair[1])
                    plan_words = plan.words
                    if not plan.is_clean or plan.is_empty:
                        blockers.append(plan.words)
                except RevertError as exc:
                    blockers.append(str(exc))
        return RevertPreview(
            pull_request=pr,
            merged_oid=pair[0] if pair else "",
            pre_merge_oid=pair[1] if pair else "",
            branch_name=branch, plan_words=plan_words,
            blockers=tuple(blockers))

    # -- the one click ------------------------------------------------
    def revert_pull_request(self, actor: User, owner: object,
                            repo: object, number: object, *,
                            merged_oid=None, pre_merge_oid=None,
                            first_landed_oid=None,
                            branch_name: object = None,
                            source_ip: str | None = None
                            ) -> RevertResult:
        """Open the revert pull request for a merged pull
        request. Every refusal is raised before any branch or
        number is claimed, except a git refusal from the revert
        itself, which lands nothing it claims."""
        pr, current = self._require_writable_pr(
            actor, owner, repo, number)
        self._validate_revertable(pr)
        pair = self._resolve_pair(
            pr, current, merged_oid, pre_merge_oid,
            first_landed_oid)
        if pair is None:
            raise PullRequestError(
                "pull_request_not_merged",
                f"No landing is recorded for pull request "
                f"#{pr.number}: its changes cannot be named, "
                "so they cannot be reverted.")
        merged, pre = pair
        branch = (default_revert_branch_name(
            pr.number, pr.head_branch) if branch_name is None
            else branch_name)
        path = self._repos.path_for(current.owner, current.name)
        try:
            landed = land_revert(
                path, base_branch=pr.base_branch,
                merged_oid=merged, pre_merge_oid=pre,
                first_landed_oid=first_landed_oid,
                branch_name=branch,
                author_name=actor.username,
                author_email=(
                    f"{actor.username_lower}@samverk.invalid"),
                message=default_revert_message(
                    pr.number, pr.title, merged))
        except RevertError as exc:
            raise PullRequestError(exc.reason, str(exc)) from None
        title = f'Revert "{pr.title}"'
        body = (f"Reverts #{pr.number}.\n\n"
                f"This reverts pull request #{pr.number}, "
                f"landed in commit {merged}.")
        now = int(self._now())
        try:
            created = self._prs.create_pull_request(
                actor, owner, repo, base_branch=pr.base_branch,
                head_branch=landed.branch, title=title, body=body)
            with self._conn:  # the link lands with the PR
                self._conn.execute(
                    "INSERT INTO pull_request_reverts"
                    " (pull_request_id,"
                    " original_pull_request_id, repo_id,"
                    " merged_oid, pre_merge_oid,"
                    " revert_commit_oid, revert_branch,"
                    " base_branch, created_by, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (created.id, pr.id, current.id, merged, pre,
                     landed.commit_oid, landed.branch,
                     pr.base_branch, actor.id, now))
        except Exception:
            # No half-revert: the minted branch must not
            # outlive the failed claim (S-137's shape).
            try:
                RefStore(path).delete_branch(
                    landed.branch,
                    expected_old=landed.commit_oid)
            except RefError:
                pass
            raise
        record = self.revert_of(actor, owner, repo, created.number)
        assert record is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.pull_request.revert",
                target_kind="repo",
                target_id=f"{current.full_name}#{pr.number}",
                outcome="success", source_ip=source_ip,
                detail={"number": pr.number,
                        "revert_number": created.number,
                        "commit": landed.commit_oid,
                        "branch": landed.branch,
                        "merged_commit": merged})
        return RevertResult(
            original=pr, revert=created, record=record,
            commit_oid=landed.commit_oid, branch=landed.branch,
            merged_oid=merged, pre_merge_oid=pre)

    # -- link reads ----------------------------------------------------
    def revert_of(self, viewer: User | None, owner: object,
                  repo: object, number: object
                  ) -> RevertRecord | None:
        """For the pull request at `number`: the PR it reverts,
        when it is itself a revert, else None."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        row = self._conn.execute(
            _REVERT_SELECT + " WHERE r.pull_request_id = ?",
            (pr.id,)).fetchone()
        return _row_to_record(row) if row else None

    def reverted_by(self, viewer: User | None, owner: object,
                    repo: object, number: object) -> tuple:
        """For the pull request at `number`: every revert PR
        opened against it, oldest first."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        rows = self._conn.execute(
            _REVERT_SELECT
            + " WHERE r.original_pull_request_id = ?"
            " ORDER BY r.id", (pr.id,)).fetchall()
        return tuple(_row_to_record(r) for r in rows)

    def links_for(self, viewer: User | None, owner: object,
                  repo: object, number: object) -> RevertLinks:
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        return RevertLinks(
            number=pr.number,
            reverts=self.revert_of(viewer, owner, repo, number),
            reverted_by=self.reverted_by(
                viewer, owner, repo, number))


def render_revert_preview(preview: RevertPreview) -> str:
    """The revert box, in words: readiness or the blockers,
    the branch the revert would land on, and the plan's
    verdict — meaning in the text, never a colour."""
    pr = preview.pull_request
    parts = [
        f'<div class="revert-preview" data-number="{pr.number}">',
        f"<p>{escape_html_text(preview.words)}</p>",
    ]
    if preview.plan_words:
        parts.append(
            f"<p>{escape_html_text(preview.plan_words)}</p>")
    if preview.can_revert:
        parts.append(
            f"<p>Branch: {escape_html_text(preview.branch_name)} "
            f"into {escape_html_text(pr.base_branch)}</p>")
    parts.append("</div>")
    return "\n".join(parts)


def render_revert_result(result: RevertResult) -> str:
    """One landed revert, said in plain words."""
    return (f'<p class="pull-request revert">'
            f"{escape_html_text(result.words)}</p>")


def render_revert_links(links: RevertLinks) -> str:
    """Both directions of the link on a pull request's page,
    in plain words — nothing at all when no link exists."""
    if links.reverts is None and not links.reverted_by:
        return ""
    parts = ['<div class="revert-links">']
    if links.reverts is not None:
        parts.append(
            f"<p>This pull request reverts "
            f"#{links.reverts.original_number}.</p>")
    for record in links.reverted_by:
        parts.append(
            f"<p>Pull request #{links.number} was reverted "
            f"by #{record.revert_number}.</p>")
    parts.append("</div>")
    return "\n".join(parts)
