"""Pull request rebase (S-155).

Merge: rebase — the head branch's commits are replayed,
one by one, onto the current tip of the base branch, and
the base branch is moved to the replayed tip. The head
branch itself is never written by this slice: the work
lands *into* the base, the head stays exactly where it
was, and the pull request row is never rewritten (its
oid snapshots stay the open-time records they are in
every landed slice).

- **Permission and readiness come first.** The pull
  request is read through S-141's uniform seam
  (`pull_request_not_found` for a missing repository, an
  unreadable repository, a bad number, or a missing pull
  request); the actor must be the pull request's author
  or a writer or admin on the base repository, else
  `permission_denied`. A draft or closed pull request is
  refused through S-143's `merge_blocker` seam before
  any git work happens — `pull_request_closed` when it
  is closed, `pull_request_draft` when it is a draft —
  with the blocker's own words as the message.
- **Pre-flight proves the replay before it runs.** The
  refusal half of this slice (S-155's safety module,
  `pull_request_rebase_safety.plan_rebase`) walks the
  head commits oldest-first as a pure dry run — for each
  commit, `git merge-tree --write-tree` against the
  replayed state so far, with the commit's first parent
  as the merge base (the empty tree for a root commit,
  so a merge commit in the head history replays by its
  first-parent diff and is flattened, per the design's
  recorded assumption A3). A commit that would conflict
  raises the safety module's `RebaseConflictError` —
  reason `rebase_conflict`, the message and payload
  naming the commit (short oid and subject) and the
  conflicted paths merge-tree reported — before this
  engine creates a single replayed commit. The dry run
  writes only unreachable git objects; no ref moves, so
  a refusal leaves the base ref, the head ref, and the
  pull request row exactly as they were.
- **Replay preserves the commits.** Each proven step is
  created for real with `commit-tree`: the tree the dry
  run proved, parented on the running tip, with the
  source commit's message and author preserved verbatim
  (parsed from `cat-file commit`, author date included)
  and its committer name and email preserved; the
  committer date is this moment, from the store's clock.
  Everything created here is still unreachable — no ref
  has moved — so abandoning the walk at any point
  changes nothing anyone can see.
- **Landing is one compare-and-swap.** The base ref is
  moved to the replayed tip with `expected_old` set to
  the tip the walk started from. A racer who moved the
  base first fails the landing as `stale_ref`, surfaced
  as a `PullRequestError` the caller can simply retry;
  nothing is torn. (The safety module's
  `RebaseStateGuard` is not wrapped around the landing:
  the compare-and-swap is already the atomic guard the
  design names, and no other ref is ever written here,
  so there is nothing for a snapshot to restore.)
- **Up to date is a no-op.** When there is nothing to
  replay, or the head already stands on the current
  base tip, the report says so (`up_to_date`): no ref
  moves and nothing is audited. The same report covers
  a call after a landing (invariant I6): the landed
  commits are patch-identical to the head commits, so
  a `--cherry-pick` walk of the head range against the
  base finds nothing the base does not already
  contain, and the call reports up to date before any
  pre-flight runs.
- **Audited only on real change** (taxonomy append-only
  +1, 111 events: `repo.pull_request.rebase`; the detail
  names the pull request number, the replayed count,
  and the base oids before and after — never bodies).
  Refusals and up-to-date no-ops emit nothing.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import IssueStore
from .permissions import can_write
from .proc import run_git_in
from .pull_request_drafts import merge_blocker
from .pull_request_rebase_safety import plan_rebase
from .pull_requests import PullRequestError, PullRequestStore
from .refs import RefError, RefStore, branch_ref
from .repositories import RepositoryStore

__all__ = [
    "PullRequestRebaseStore", "RebaseReport",
    "render_rebase_report",
]

_IDENT_RE = re.compile(r"^(.*) <(.*)> (\d+) ([+-]\d{4})$")


@dataclass(frozen=True)
class RebaseReport:
    full_name: str           # owner/repo of the base repository
    number: int              # the pull request's #n
    base_branch: str
    head_branch: str
    replayed: tuple          # of (old_oid, new_oid), replay order
    base_before: str         # base tip before the call
    base_after: str          # base tip after (== before if no-op)
    head_oid: str            # the untouched head tip
    up_to_date: bool = False

    @property
    def replayed_count(self) -> int:
        return len(self.replayed)

    @property
    def words(self) -> str:
        """The outcome in plain words — never a colour alone."""
        if self.up_to_date:
            return (
                f"Pull request #{self.number} in {self.full_name} "
                f"is already up to date: its head branch "
                f"{self.head_branch} already stands on the current "
                f"tip of {self.base_branch}. Nothing was moved.")
        count = len(self.replayed)
        noun = "commit" if count == 1 else "commits"
        return (
            f"Pull request #{self.number} in {self.full_name} "
            f"was rebased: {count} head {noun} replayed onto "
            f"{self.base_branch}, which moved from "
            f"{self.base_before} to {self.base_after}. "
            f"The head branch {self.head_branch} was not moved.")


@dataclass(frozen=True)
class _CommitFacts:
    parents: tuple           # of str, in recorded order
    author_name: str
    author_email: str
    author_date: str         # "<unix> <tz>", verbatim
    committer_name: str
    committer_email: str
    message: bytes           # the commit message, verbatim
    subject: str             # its first line, in words


def _parse_ident(raw: bytes, oid: str) -> tuple:
    """One `Name <email> ts tz` ident line, split into
    (name, email, "<unix> <tz>") with the date kept in
    git's raw form so it can ride back out verbatim."""
    match = _IDENT_RE.match(
        raw.decode("utf-8", "surrogateescape"))
    if match is None:
        raise PullRequestError(
            "rebase_preflight_failed",
            "git could not read a head commit; "
            "nothing was changed.")
    return (match.group(1), match.group(2),
            f"{match.group(3)} {match.group(4)}")


class PullRequestRebaseStore:
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

    # -- internals ---------------------------------------------------
    def _require_permission(self, actor: User, owner, repo, number):
        """The PR through S-141's uniform seam, plus the
        rebase permission: the pull request's author, or a
        writer or admin on the base repository (the S-152
        pattern)."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        if actor.id != pr.author_id and not can_write(actor, current):
            raise PullRequestError(
                "permission_denied",
                "permission_denied — only the pull request's "
                "author or a writer or admin on the base "
                "repository can rebase this pull request.")
        return pr, current

    def _emit(self, actor: User, owner, repo, number: int,
              detail: dict, source_ip: str | None) -> None:
        if self._audit is not None:
            current = self._repos.get_repository(owner, repo)
            target = (f"{current.full_name}#{number}"
                      if current is not None else f"#{number}")
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.pull_request.rebase",
                target_kind="repo", target_id=target,
                outcome="success", source_ip=source_ip,
                detail=detail)

    @staticmethod
    def _git(repo_path: Path, args: list, **kw):
        return run_git_in(repo_path, args, timeout=30.0, **kw)

    def _commit_facts(self, repo_path: Path,
                      oid: str) -> _CommitFacts:
        """Everything a faithful replay needs from one
        commit, parsed from `cat-file commit` output:
        parents in order, author and committer idents,
        and the message bytes verbatim (everything after
        the first blank line)."""
        result = self._git(repo_path, ["cat-file", "commit", oid])
        if result.returncode != 0:
            raise PullRequestError(
                "rebase_preflight_failed",
                "git could not read a head commit; "
                "nothing was changed.")
        head, sep, message = result.stdout.partition(b"\n\n")
        if not sep:
            message = b""
        parents: list = []
        author = committer = None
        for line in head.split(b"\n"):
            if line.startswith(b"parent "):
                parents.append(line[7:].decode())
            elif line.startswith(b"author "):
                author = line[7:]
            elif line.startswith(b"committer "):
                committer = line[10:]
        if author is None or committer is None:
            raise PullRequestError(
                "rebase_preflight_failed",
                "git could not read a head commit; "
                "nothing was changed.")
        a_name, a_email, a_date = _parse_ident(author, oid)
        c_name, c_email, _c_date = _parse_ident(committer, oid)
        subject = (message.decode("utf-8", "replace")
                   .split("\n", 1)[0].strip() or "no subject")
        return _CommitFacts(
            parents=tuple(parents), author_name=a_name,
            author_email=a_email, author_date=a_date,
            committer_name=c_name, committer_email=c_email,
            message=message, subject=subject)

    # -- the rebase ----------------------------------------------------
    def rebase_pull_request(self, actor: User, owner: object,
                            repo: object, number: object,
                            source_ip: str | None = None
                            ) -> RebaseReport:
        """Replay the pull request's head commits onto the
        current base tip and move the base branch to the
        replayed tip. Refuses loudly — before any replayed
        commit is created — when a replayed commit would
        conflict; an already-up-to-date pull request is a
        quiet no-op report. The head branch never moves."""
        pr, current = self._require_permission(
            actor, owner, repo, number)
        blocker = merge_blocker(pr)
        if blocker:
            reason = ("pull_request_closed"
                      if pr.state == "closed"
                      else "pull_request_draft")
            raise PullRequestError(reason, blocker)
        repo_path = self._repos.path_for(owner, repo)
        refs = RefStore(repo_path)
        base_ref = branch_ref(pr.base_branch)
        head_ref = branch_ref(pr.head_branch)
        base_tip = refs.resolve(base_ref)
        head_tip = refs.resolve(head_ref)
        if base_tip is None or head_tip is None:
            missing = (pr.base_branch if base_tip is None
                       else pr.head_branch)
            raise PullRequestError(
                "branch_not_found",
                f"branch_not_found — the branch {missing} no "
                "longer exists, so this pull request cannot "
                "be rebased. Nothing was changed.")
        based = self._git(
            repo_path, ["merge-base", base_tip, head_tip])
        if based.returncode != 0:
            raise PullRequestError(
                "rebase_preflight_failed",
                "The base and head branches share no common "
                "ancestor, so this pull request cannot be "
                "rebased. Nothing was changed.")
        merge_base = based.stdout.decode().strip()
        listed = self._git(
            repo_path,
            ["rev-list", "--reverse", f"{merge_base}..{head_tip}"])
        if listed.returncode != 0:
            raise PullRequestError(
                "rebase_preflight_failed",
                "git could not list the head commits; "
                "nothing was changed.")
        oids = [line.strip() for line
                in listed.stdout.decode().splitlines()
                if line.strip()]
        if not oids or merge_base == base_tip:
            return RebaseReport(
                full_name=current.full_name, number=pr.number,
                base_branch=pr.base_branch,
                head_branch=pr.head_branch, replayed=(),
                base_before=base_tip, base_after=base_tip,
                head_oid=head_tip, up_to_date=True)
        # Already landed once (invariant I6): if every
        # head change is patch-identical to a change the
        # base already contains, there is nothing to do.
        contained = self._git(
            repo_path,
            ["rev-list", "--cherry-pick", "--right-only",
             f"{base_tip}...{head_tip}"])
        if contained.returncode != 0:
            raise PullRequestError(
                "rebase_preflight_failed",
                "git could not list the head commits; "
                "nothing was changed.")
        if not contained.stdout.decode().strip():
            return RebaseReport(
                full_name=current.full_name, number=pr.number,
                base_branch=pr.base_branch,
                head_branch=pr.head_branch, replayed=(),
                base_before=base_tip, base_after=base_tip,
                head_oid=head_tip, up_to_date=True)
        # Pre-flight: the safety module's dry run proves
        # every step (and raises the loud rebase_conflict
        # refusal) before the replay below creates anything.
        plan = plan_rebase(repo_path, base_tip, head_tip)
        # Replay: create the proven steps for real, oldest
        # first, every head commit exactly once, preserving
        # message and author verbatim.
        tip = base_tip
        replayed: list = []
        for step in plan.steps:
            facts = self._commit_facts(repo_path, step.source_oid)
            env = {
                "GIT_AUTHOR_NAME": facts.author_name,
                "GIT_AUTHOR_EMAIL": facts.author_email,
                "GIT_AUTHOR_DATE": facts.author_date,
                "GIT_COMMITTER_NAME": facts.committer_name,
                "GIT_COMMITTER_EMAIL": facts.committer_email,
                "GIT_COMMITTER_DATE": f"{int(self._now())} +0000",
            }
            made = self._git(
                repo_path,
                ["commit-tree", step.tree_oid, "-p", tip],
                input_bytes=facts.message, env_extra=env)
            if made.returncode != 0:
                raise PullRequestError(
                    "rebase_preflight_failed",
                    "git could not create a replayed commit; "
                    "nothing was changed.")
            tip = made.stdout.decode().strip()
            replayed.append((step.source_oid, tip))
        # Land: one atomic compare-and-swap of the base ref.
        try:
            refs.update_ref(base_ref, tip, expected_old=base_tip)
        except RefError:
            raise PullRequestError(
                "stale_ref",
                "stale_ref — the base branch moved while this "
                "pull request was being rebased, so nothing "
                "was landed. Rebase again to retry.") from None
        report = RebaseReport(
            full_name=current.full_name, number=pr.number,
            base_branch=pr.base_branch,
            head_branch=pr.head_branch, replayed=tuple(replayed),
            base_before=base_tip, base_after=tip,
            head_oid=head_tip, up_to_date=False)
        self._emit(
            actor, owner, repo, pr.number,
            {"number": pr.number, "replayed": len(replayed),
             "base_before": base_tip, "base_after": tip},
            source_ip)
        return report


def render_rebase_report(report: RebaseReport) -> str:
    """One rebase report, in plain words — the report's
    own words, escaped through S-010; never a colour
    alone."""
    return (
        '<div class="rebase-report">'
        f"<p>{escape_html_text(report.words)}</p></div>")
