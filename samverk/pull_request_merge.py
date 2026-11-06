"""Pull request merge: the merge commit (S-153).

Landing a pull request as a true merge commit — the first
of Part VII's three merge strategies (squash is S-154,
rebase is S-155, and both will ride this slice's plan).

- **A real merge commit, with the pull request's own
  words.** The commit's tree is the head's tree as git's
  own merge computes it; its parents are the base tip and
  the head tip, in that order; its message is the pull
  request's title and body by default — `default_message`
  is the one place that default is composed — and an
  edited message, when the merger supplies one, replaces
  it whole and lands verbatim. The commit is minted with
  `commit-tree` over plumbing (S-014's allowlist), never
  by a checkout: a forge merges branches it may never
  have on disk as work. Author and committer are the
  merging actor, under the S-150 identity law
  (username / username_lower@samverk.invalid) — who
  merged is a fact of the commit, not just of the log.
- **Conflicts are tested, never discovered by merging.**
  Before any commit is minted, `git merge-tree
  --write-tree` runs the merge in memory: exit 1 means
  the branches conflict and the merge is refused
  `merge_conflict`, in words. S-153 extends S-014's
  subcommand allowlist with `merge-tree` for exactly
  this read-only test (S-156 owns *showing* conflicts
  ahead of time; refusing truthfully is this slice's).
- **Validation validates whole, before anything moves**
  — the standing law of every Part VII slice. The pull
  request is read through S-141's uniform seam (a
  stranger to a private repository gets
  `pull_request_not_found` before any other question);
  merging is a write act on the base repository, so a
  mere reader — and the pull request's own author, on
  authorship alone — is refused `permission_denied`;
  S-143's `merge_blocker` speaks for closed
  (`pull_request_closed`) and draft
  (`pull_request_draft`) pull requests, so "drafts
  cannot merge" stays enforced in the one place S-143
  built for it; the branches are resolved as they stand
  now (`base_not_found` / `head_not_found`); a head the
  base already contains is `already_merged`; branches
  with no common ancestor are `unrelated_history`; a
  blank or non-string edited message is
  `message_invalid`. A refused merge burns nothing: no
  commit is claimed, no ref moves, no row changes, no
  audit row is written.
- **Cross-fork heads are fetched, never trusted.** A
  cross-fork pull request's head lives in the fork
  (S-142's `pull_request_forks` record says so); its tip
  is fetched into the base repository under one scratch
  ref through S-142's own `run_git_fetch_ref` seam —
  local paths only, one named ref — the merge commit is
  minted in the base repository, and the scratch ref is
  deleted in every outcome. No branch in either
  repository is moved by the fetch.
- **Landing is all-or-nothing across git and the
  database** (the S-150 shape). The base branch moves
  by RefStore compare-and-swap against the very tip the
  plan was validated on; the record then lands in one
  transaction — the pull request's row closed, its
  recorded base/head oids refreshed to the tips that
  actually landed, a state event in S-130's stream so
  S-144's timeline can say it closed, the merge record
  itself (migration 58), and every closing the merge
  executes. If the record cannot land, the base branch
  is compare-and-swapped back and the merge answers
  `merge_failed` — a merge is never half-true.
- **Closing keywords are executed on landing.** The
  list is S-144's `closing_references` — the pull
  request's body and live comments under S-127's
  parser, existence proven — read at landing time, so
  what executes is what the prose says *now*. Only
  issues close: a referenced pull request is named in
  the preview and left alone. An already-closed issue
  is reported, never re-closed, and gains no second
  event; each target is re-checked open inside the
  landing transaction. A target in a repository the
  merger cannot write is named but not closed — the
  merge acts only where the merger has standing, and
  the preview applies the same rule, so the promise
  always matches the act. Each closing lands with the
  same record shape S-130 writes (state, reason
  'completed', version bump, an `issue_events` row),
  the merger as its actor.
- **Permission is S-163's layer on this path.** The
  write check below is not this slice's private rule:
  it is `pull_request_merge_permission`'s seam over
  S-054 — the same answer governs the merge button's
  presence in the preview below (chrome law, S-112:
  absent for non-writers, never disabled) and the
  refusal a non-writer's merge attempt meets (server
  law). The preview itself is a read: any reader the
  S-141 seam admits may see the plan, with their own
  standing said in words; only landing requires write.
  A refused landing is witnessed as a denied attempt
  under the merge event.
- **Audited under its own event** (taxonomy append-only
  +1: `repo.pull_request.merge`, 111 events). The
  detail names the number, the merge commit, the branch
  pair, and the issues closed — never the message,
  which may carry the pull request's whole body.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text
from .issue_conversion import PullRequest
from .issues import IssueError, IssueStore
from .permissions import can_write, role_for
from .pull_request_merge_permission import (
    MergePermission, merge_permission, permission_words)
from .proc import run_git_in, run_git_fetch_ref
from .pull_request_conversation import PullRequestConversationStore
from .pull_request_drafts import merge_blocker
from .pull_request_forks import ForkPullRequestStore
from .pull_requests import PullRequestError, PullRequestStore
from .refs import RefError, RefStore, branch_ref
from .repositories import Repository, RepositoryStore

__all__ = [
    "MergeClosing", "MergePreview", "MergedPullRequest",
    "PullRequestMergeStore", "MergePermission", "default_message",
    "render_merge", "render_merge_preview",
]

SCRATCH_REF = "refs/samverk-merge/head"


def default_message(pr: PullRequest) -> str:
    """The merge commit's default message: the pull
    request's title, then its body when it has one —
    the words the pull request was opened with are the
    words it lands with, unless the merger edits them."""
    if pr.body:
        return f"{pr.title}\n\n{pr.body}"
    return pr.title


@dataclass(frozen=True)
class MergeClosing:
    target_repo: str     # full name of the target repository
    target_number: int
    target_kind: str     # 'issue' | 'pull_request'
    will_close: bool     # False: already closed, a pull
    # request target, or beyond the merger's standing

    @property
    def label(self) -> str:
        return f"{self.target_repo}#{self.target_number}"

    @property
    def notice(self) -> str:
        if self.will_close:
            return f"Will close {self.label} on merge."
        if self.target_kind == "pull_request":
            return (f"{self.label} is a pull request; merging "
                    "will not close it.")
        return (f"{self.label} will not be closed by this "
                "merge (already closed, or in a repository "
                "the merger cannot write).")


@dataclass(frozen=True)
class MergePreview:
    pull_request: PullRequest
    base_oid: str        # base tip as it stands now
    head_oid: str        # head tip as it stands now
    merge_base_oid: str  # '' when the branches share no history
    ahead: int
    behind: int
    default_message: str
    conflicts: bool
    closings: tuple      # of MergeClosing
    blockers: tuple      # of str, in words
    full_name: str = ""
    viewer_can_merge: bool = False
    viewer_role: str = ""

    @property
    def mergeable(self) -> bool:
        """The pull request's own state raises no
        objection — whoever the viewer is."""
        return not self.blockers

    @property
    def can_merge(self) -> bool:
        """This viewer may land this merge now: the
        pull request is mergeable AND the viewer holds
        write (S-163)."""
        return self.mergeable and self.viewer_can_merge

    @property
    def show_merge_button(self) -> bool:
        """Chrome law (S-112): the button exists only
        for a viewer who can use it — absent, never
        disabled, for everyone else."""
        return self.can_merge

    @property
    def words(self) -> str:
        pr = self.pull_request
        if not self.viewer_can_merge:
            return permission_words(self.full_name)
        if self.blockers:
            return self.blockers[0]
        return (f"Ready to merge — merging will land "
                f"{self.ahead} commit(s) from {pr.head_branch} "
                f"onto {pr.base_branch} as one merge commit.")


@dataclass(frozen=True)
class MergedPullRequest:
    pull_request: PullRequest   # re-read after landing: closed
    merge_commit_oid: str
    base_branch: str
    head_branch: str
    base_oid: str        # first parent: the base tip that landed
    head_oid: str        # second parent: the head tip that landed
    message: str         # as landed, verbatim
    closed_issues: tuple  # of "owner/repo#n", in closing order
    merged_at: int

    @property
    def number(self) -> int:
        return self.pull_request.number

    @property
    def words(self) -> str:
        text = (f"Merged — pull request #{self.number} landed on "
                f"{self.base_branch} as merge commit "
                f"{self.merge_commit_oid[:12]}.")
        if self.closed_issues:
            text += f" Closed on landing: {', '.join(self.closed_issues)}."
        return text


@dataclass(frozen=True)
class _Plan:
    pr: PullRequest
    base_repo: Repository
    cross_fork: bool
    base_oid: str
    head_oid: str
    merge_base_oid: str
    ahead: int
    behind: int
    merged_tree: str
    conflicts: bool
    blockers: tuple
    viewer_can_merge: bool = False
    viewer_role: str = ""


class PullRequestMergeStore:
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
        self._forks = ForkPullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)
        self._conversation = PullRequestConversationStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    # -- the plan ------------------------------------------------------

    def _plan(self, actor: User, owner: object, repo: object,
              number: object, *, require_write: bool = True
              ) -> _Plan:
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        base_repo = self._repos.get_repository(owner, repo)
        assert base_repo is not None
        viewer_role = role_for(actor, base_repo) or ""
        viewer_can_merge = can_write(actor, base_repo)
        if require_write and not viewer_can_merge:
            if self._audit is not None:
                self._audit.append(
                    actor_kind="user",
                    actor_id=actor.id if actor is not None else None,
                    action="repo.pull_request.merge",
                    target_kind="repo",
                    target_id=f"{base_repo.full_name}#{pr.number}",
                    outcome="denied", source_ip=None,
                    detail={"number": pr.number,
                            "reason": "permission_denied"})
            raise PullRequestError(
                "permission_denied",
                permission_words(base_repo.full_name))
        base_path = self._repos.path_for(base_repo.owner,
                                         base_repo.name)
        refs = RefStore(base_path)
        base_oid = refs.resolve(branch_ref(pr.base_branch))
        if base_oid is None:
            raise PullRequestError(
                "base_not_found",
                f"The base branch {pr.base_branch!r} does not "
                f"exist in {base_repo.full_name} yet.")
        record = self._forks.get_cross_fork(actor, owner, repo,
                                             number)
        cross_fork = record is not None
        scratch_live = False
        try:
            if cross_fork:
                assert record is not None
                head_repo = self._repos.get_repository(
                    *record.head_full_name.split("/", 1))
                if head_repo is None:
                    raise PullRequestError(
                        "head_repo_not_found",
                        "No such head repository.")
                head_path = self._repos.path_for(head_repo.owner,
                                                 head_repo.name)
                result = run_git_fetch_ref(
                    base_path, head_path,
                    branch_ref(pr.head_branch), SCRATCH_REF)
                if result.returncode != 0:
                    raise PullRequestError(
                        "merge_failed",
                        "The head branch could not be read "
                        "into the base repository for merging.")
                scratch_live = True
                head_oid = refs.resolve(SCRATCH_REF)
            else:
                head_oid = refs.resolve(branch_ref(pr.head_branch))
            if head_oid is None:
                raise PullRequestError(
                    "head_not_found",
                    f"The head branch {pr.head_branch!r} does "
                    "not exist yet.")
            base = self._merge_base(base_path, base_oid, head_oid)
            if base:
                ahead = self._count(base_path, f"{base}..{head_oid}")
                behind = self._count(base_path, f"{base}..{base_oid}")
            else:
                ahead = self._count(base_path, head_oid)
                behind = self._count(base_path, base_oid)
            contained = bool(base) and base == head_oid
            merged_tree = ""
            conflicts = False
            if base and not contained:
                merged_tree, conflicts = self._merge_tree(
                    base_path, base_oid, head_oid)
            blockers: list[str] = []
            words = merge_blocker(pr)
            if words:
                blockers.append(words)
            if contained:
                blockers.append(
                    "The base branch already contains the head "
                    "branch; there is nothing to merge.")
            if not base:
                blockers.append(
                    "The head and base branches share no "
                    "history, so they cannot be merged.")
            if conflicts:
                blockers.append(
                    "The head branch conflicts with the base "
                    "branch; resolve the conflicts on the head "
                    "branch before merging.")
            return _Plan(
                pr=pr, base_repo=base_repo, cross_fork=cross_fork,
                base_oid=base_oid, head_oid=head_oid,
                merge_base_oid=base, ahead=ahead, behind=behind,
                merged_tree=merged_tree, conflicts=conflicts,
                blockers=tuple(blockers),
                viewer_can_merge=viewer_can_merge,
                viewer_role=viewer_role)
        finally:
            if scratch_live:
                run_git_in(base_path, ["update-ref", "-d",
                                       SCRATCH_REF], timeout=15.0)

    @staticmethod
    def _merge_base(path, base_oid: str, head_oid: str) -> str:
        result = run_git_in(
            path, ["merge-base", base_oid, head_oid], timeout=15.0)
        if result.returncode != 0:
            return ""
        return result.stdout.decode().strip()

    @staticmethod
    def _count(path, revspec: str) -> int:
        result = run_git_in(
            path, ["rev-list", "--count", revspec], timeout=15.0)
        if result.returncode != 0:
            raise PullRequestError(
                "merge_failed",
                "The branches could not be compared for merging.")
        try:
            return int(result.stdout.decode().strip())
        except ValueError:
            raise PullRequestError(
                "merge_failed",
                "The branches could not be compared for "
                "merging.") from None

    @staticmethod
    def _merge_tree(path, base_oid: str, head_oid: str):
        """git's own merge, in memory: exit 0 clean — the
        first output line is the tree the merge produces,
        and the merge commit carries exactly that tree;
        exit 1 conflicted. Anything else is a failure to
        test, said as one — never a guess."""
        result = run_git_in(
            path, ["merge-tree", "--write-tree", base_oid,
                   head_oid], timeout=30.0)
        if result.returncode == 0:
            lines = result.stdout.decode().splitlines()
            if not lines or not lines[0].strip():
                raise PullRequestError(
                    "merge_failed", "git could not test the merge.")
            return lines[0].strip(), False
        if result.returncode == 1:
            return "", True
        raise PullRequestError(
            "merge_failed", "git could not test the merge.")

    # -- closings --------------------------------------------------------

    def _closings_for(self, actor: User, owner: object,
                      repo: object, pr: PullRequest
                      ) -> list[MergeClosing]:
        """What landing would close, under the landing
        rules: S-144's list, each item judged — issue kind,
        still open, and inside the merger's standing."""
        found: list[MergeClosing] = []
        refs = self._conversation.closing_references(
            actor, owner, repo, pr.number)
        for ref in refs:
            target_repo = self._repos.get_repository(
                *ref.target_repo.split("/", 1))
            if target_repo is None:
                continue
            will_close = False
            if ref.target_kind == "issue" \
                    and can_write(actor, target_repo):
                try:
                    item = self._issues.get_issue(
                        actor, target_repo.owner, target_repo.name,
                        ref.target_number)
                    will_close = item.state == "open"
                except IssueError:
                    will_close = False
            found.append(MergeClosing(
                target_repo=ref.target_repo,
                target_number=ref.target_number,
                target_kind=ref.target_kind,
                will_close=will_close))
        return found

    # -- reads -----------------------------------------------------------

    def preview_merge(self, actor: User, owner: object,
                      repo: object, number: object) -> MergePreview:
        """The merge box, before landing: the plan, the
        default message, and the closing list — everything
        said in words, nothing discovered by merging."""
        plan = self._plan(actor, owner, repo, number,
                          require_write=False)
        closings = self._closings_for(actor, owner, repo, plan.pr)
        return MergePreview(
            pull_request=plan.pr, base_oid=plan.base_oid,
            head_oid=plan.head_oid,
            merge_base_oid=plan.merge_base_oid,
            ahead=plan.ahead, behind=plan.behind,
            default_message=default_message(plan.pr),
            conflicts=plan.conflicts, closings=tuple(closings),
            blockers=plan.blockers,
            full_name=plan.base_repo.full_name,
            viewer_can_merge=plan.viewer_can_merge,
            viewer_role=plan.viewer_role)

    def merge_permission_for(self, actor: User, owner: object,
                             repo: object, number: object
                             ) -> MergePermission:
        """The actor's merge standing on this pull
        request, in one object (S-163): the S-141 seam
        answers first — a stranger to a private
        repository gets `pull_request_not_found` — then
        S-054's role, resolved through the permission
        seam. Asking is a read; it never raises
        `permission_denied` and writes no audit row."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        base_repo = self._repos.get_repository(owner, repo)
        assert base_repo is not None
        return merge_permission(actor, base_repo, number=pr.number)

    # -- the merge ---------------------------------------------------------

    def merge_pull_request(self, actor: User, owner: object,
                           repo: object, number: object, *,
                           message: object = None,
                           source_ip: str | None = None
                           ) -> MergedPullRequest:
        """Land the pull request as a merge commit. Every
        refusal is raised before any git object is written;
        a landed merge is atomic across git and the
        database, or the base branch is restored."""
        plan = self._plan(actor, owner, repo, number)
        pr = plan.pr
        if plan.blockers:
            if pr.state == "closed":
                reason = "pull_request_closed"
            elif pr.is_draft:
                reason = "pull_request_draft"
            elif plan.merge_base_oid == pr.head_oid \
                    and plan.merge_base_oid:
                reason = "already_merged"
            elif not plan.merge_base_oid:
                reason = "unrelated_history"
            else:
                reason = "merge_conflict"
            raise PullRequestError(reason, plan.blockers[0])
        if message is None:
            final_message = default_message(pr)
        elif not isinstance(message, str) or not message.strip():
            raise PullRequestError(
                "message_invalid",
                "A merge message must be words; name the merge "
                "or let the pull request's own title and body "
                "speak for it.")
        else:
            final_message = message
        closings = self._closings_for(actor, owner, repo, pr)
        base_path = self._repos.path_for(plan.base_repo.owner,
                                         plan.base_repo.name)
        refs = RefStore(base_path)
        scratch_live = False
        try:
            head_oid = plan.head_oid
            if plan.cross_fork:
                record = self._forks.get_cross_fork(
                    actor, owner, repo, number)
                assert record is not None
                head_repo = self._repos.get_repository(
                    *record.head_full_name.split("/", 1))
                assert head_repo is not None
                head_path = self._repos.path_for(head_repo.owner,
                                                 head_repo.name)
                result = run_git_fetch_ref(
                    base_path, head_path,
                    branch_ref(pr.head_branch), SCRATCH_REF)
                if result.returncode != 0 \
                        or refs.resolve(SCRATCH_REF) != plan.head_oid:
                    raise PullRequestError(
                        "merge_failed",
                        "The head branch moved while the merge "
                        "was being prepared; nothing was merged.")
                scratch_live = True
            elif refs.resolve(branch_ref(pr.head_branch)) \
                    != plan.head_oid:
                raise PullRequestError(
                    "merge_failed",
                    "The head branch moved while the merge was "
                    "being prepared; nothing was merged.")
            tree_oid = plan.merged_tree
            if not tree_oid:
                raise PullRequestError(
                    "merge_failed",
                    "git could not compute the merged tree.")
            env = {
                "GIT_AUTHOR_NAME": actor.username,
                "GIT_AUTHOR_EMAIL":
                    f"{actor.username_lower}@samverk.invalid",
                "GIT_COMMITTER_NAME": actor.username,
                "GIT_COMMITTER_EMAIL":
                    f"{actor.username_lower}@samverk.invalid",
            }
            text = final_message if final_message.endswith("\n") \
                else final_message + "\n"
            commit = run_git_in(
                base_path,
                ["commit-tree", tree_oid,
                 "-p", plan.base_oid, "-p", head_oid],
                input_bytes=text.encode("utf-8"), timeout=15.0,
                env_extra=env)
            if commit.returncode != 0:
                raise PullRequestError(
                    "merge_failed",
                    "git could not mint the merge commit.")
            merge_oid = commit.stdout.decode().strip()
            try:
                refs.update_ref(
                    branch_ref(pr.base_branch), merge_oid,
                    expected_old=plan.base_oid)
            except RefError:
                raise PullRequestError(
                    "merge_failed",
                    "The base branch moved while the merge "
                    "was being made; nothing was merged."
                    ) from None
            now = int(self._now())
            closed_labels: list[str] = []
            try:
                with self._conn:  # the record lands together
                    self._conn.execute(
                        "UPDATE issues SET state = 'closed',"
                        " updated_at = ? WHERE id = ?",
                        (now, pr.row_id))
                    self._conn.execute(
                        "UPDATE pull_requests SET base_oid = ?,"
                        " head_oid = ?, updated_at = ?"
                        " WHERE issue_id = ?",
                        (plan.base_oid, plan.head_oid, now,
                         pr.row_id))
                    self._conn.execute(
                        "INSERT INTO issue_events (issue_id,"
                        " actor_id, kind, reason, created_at)"
                        " VALUES (?, ?, 'closed', 'completed', ?)",
                        (pr.row_id, actor.id, now))
                    self._conn.execute(
                        "INSERT INTO pull_request_merges"
                        " (pull_request_id, repo_id,"
                        " merge_commit_oid, base_branch,"
                        " head_branch, base_oid, head_oid,"
                        " message, merged_by, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (pr.id, plan.base_repo.id, merge_oid,
                         pr.base_branch, pr.head_branch,
                         plan.base_oid, plan.head_oid,
                         final_message, actor.id, now))
                    for closing in closings:
                        if not closing.will_close:
                            continue
                        target = self._repos.get_repository(
                            *closing.target_repo.split("/", 1))
                        if target is None:
                            continue
                        row = self._conn.execute(
                            "SELECT id, state FROM issues"
                            " WHERE repo_id = ? AND number = ?"
                            " AND kind = 'issue'",
                            (target.id,
                             closing.target_number)).fetchone()
                        if row is None or row["state"] != "open":
                            continue  # closed by hand meanwhile:
                            # not closed twice, no second event
                        self._conn.execute(
                            "UPDATE issues SET state = 'closed',"
                            " state_reason = 'completed',"
                            " version = version + 1,"
                            " updated_at = ? WHERE id = ?",
                            (now, int(row["id"])))
                        self._conn.execute(
                            "INSERT INTO issue_events (issue_id,"
                            " actor_id, kind, reason, created_at)"
                            " VALUES (?, ?, 'closed',"
                            " 'completed', ?)",
                            (int(row["id"]), actor.id, now))
                        closed_labels.append(closing.label)
            except Exception:
                try:
                    refs.update_ref(
                        branch_ref(pr.base_branch), plan.base_oid,
                        expected_old=merge_oid)
                except RefError:
                    pass
                raise PullRequestError(
                    "merge_failed",
                    "The merge could not be recorded; the base "
                    "branch was restored.") from None
        finally:
            if scratch_live:
                run_git_in(base_path, ["update-ref", "-d",
                                       SCRATCH_REF], timeout=15.0)
        merged = self._prs.get_pull_request(actor, owner, repo,
                                            pr.number)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.pull_request.merge",
                target_kind="repo",
                target_id=(f"{plan.base_repo.full_name}"
                           f"#{pr.number}"),
                outcome="success", source_ip=source_ip,
                detail={"number": pr.number, "commit": merge_oid,
                        "base": pr.base_branch,
                        "head": pr.head_branch,
                        "closed": closed_labels})
        return MergedPullRequest(
            pull_request=merged, merge_commit_oid=merge_oid,
            base_branch=pr.base_branch, head_branch=pr.head_branch,
            base_oid=plan.base_oid, head_oid=plan.head_oid,
            message=final_message,
            closed_issues=tuple(closed_labels), merged_at=now)


def render_merge_preview(preview: MergePreview) -> str:
    """The merge box in words: readiness or the blockers,
    the default message shown whole, and every closing
    named — meaning in the text, never a colour. The
    merge button is rendered only when the preview's
    viewer may land the merge (S-163 chrome law): for
    anyone else there is no button element at all."""
    pr = preview.pull_request
    parts = [
        f'<div class="merge-preview" data-number="{pr.number}">',
        f"<p>{escape_html_text(preview.words)}</p>",
        '<pre class="merge-message">'
        f"{escape_html_text(preview.default_message)}</pre>",
    ]
    if preview.closings:
        items = "".join(
            f"<li>{escape_html_text(c.notice)}</li>"
            for c in preview.closings)
        parts.append(f'<ul class="closings">{items}</ul>')
    if preview.show_merge_button:
        action = (f"/{preview.full_name}/pulls/{pr.number}/merge")
        parts.append(
            f'<form class="merge-action" method="post" '
            f'action="{escape_html_attr(action)}">'
            f'<button type="submit" class="merge-button">'
            f"Merge pull request</button></form>")
    parts.append("</div>")
    return "\n".join(parts)


def render_merge(result: MergedPullRequest) -> str:
    """One landed merge, said in plain words."""
    return (f'<p class="pull-request merged">'
            f"{escape_html_text(result.words)}</p>")
