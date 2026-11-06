"""Revert git mechanics (S-160, git layer).

The change-producing half of the revert slice: given a
pull request that has landed on a base branch, produce
one new commit, on a fresh branch off the base branch
as it stands today, whose tree is the base with the
landed change undone — the commit a revert pull
request then proposes. The database / pull-request
layer lives elsewhere; this module knows only git.

- **The merged change is named by two commits.** A
  landed pull request, however it landed, is a pair:
  `merged_oid`, the base tip just after landing (for
  S-153's merge that is the merge commit itself; for
  S-154's squash the single squashed commit; for
  S-155's rebase the last replayed commit), and
  `pre_merge_oid`, the base tip just before landing.
  `describe_merged_change` derives the second from
  the first when the landing was one commit (its
  first parent is the pre-merge base);
  `describe_merged_range` derives it for a replayed
  range (the first landed commit's first parent).
  Callers that recorded both oids at merge time pass
  both — the recorded pair is the authority, this
  derivation is the fallback.
- **The inverse is a real three-way merge, computed
  by git, off-path.** `compute_revert_tree` runs
  `git merge-tree --write-tree` with the merged
  commit as the merge base, the current base tip as
  one side, and the pre-merge commit as the other:
  the merged-to-pre-merge direction *is* the inverse
  change, and the merged-to-current direction is
  every later landing, so git's own merge machinery
  undoes exactly the pull request — line-level where
  later work touched neighbouring lines, whole-file
  where it did not — with rename handling, mode
  changes, additions and deletions all carried by
  git, never by a hand-rolled patch reversal. No
  worktree, no index, no branch moves: a tree oid
  comes back, or the conflict is named.
- **Conflicts are a clean refusal, never a force.**
  When the inverse does not apply cleanly (later
  work changed the very lines the pull request had
  changed), merge-tree exits non-zero and names the
  conflicted paths; this layer surfaces them as
  `revert_conflict` with the paths in the message
  and on the error, creates no commit and no
  branch, and leaves every ref exactly as it stood.
  A revert whose tree equals the current base tree
  is refused `revert_empty` — there is nothing to
  propose.
- **The commit is plumbing, in the house shape.**
  A clean tree becomes one commit through
  `commit-tree` (S-150's road): parent is the
  current base tip, author and committer are the
  actor's Samverk identity. The branch is created
  through S-053's compare-and-swap (`create_branch`
  against the zero oid), so a name that already
  exists is refused `branch_taken`, never
  overwritten. If branch creation fails after the
  commit is written, the commit is an unreferenced
  object — inert, garbage-collectable, and never
  claimed as landed.
- **Branch naming follows the house derivation.**
  `revert-<number>-<head branch>`, sanitised to the
  branch-name law and length-capped like S-137's
  issue-derived names, so the branch itself says
  which pull request it reverts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .objects import ObjectError, ObjectReader
from .proc import run_git_in
from .refs import RefError, RefStore, branch_ref
from .repositories import RepositoryError, validate_branch_name

__all__ = [
    "LandedRevert", "MergedChange", "RevertCommit",
    "RevertError", "RevertPlan", "build_revert_commit",
    "compute_revert_tree", "create_revert_branch",
    "default_revert_branch_name", "default_revert_message",
    "describe_merged_change", "describe_merged_range",
    "land_revert", "samverk_identity",
]

_OID_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")
ZERO_OID = "0" * 40


class RevertError(ValueError):
    """A revert refused by the git layer; `reason` is a
    stable code, `paths` the conflicted paths when the
    reason is `revert_conflict`."""

    def __init__(self, reason: str, message: str = "",
                 paths: tuple = ()):
        super().__init__(message or reason)
        self.reason = reason
        self.paths = tuple(paths)


def _validate_oid(value: object, reason: str) -> str:
    if not isinstance(value, str) or not _OID_RE.match(value.lower()):
        raise RevertError(reason, f"Not a commit id: {value!r}")
    return value.lower()


def _read_commit(repo_path: Path, oid: str, reason: str):
    try:
        return ObjectReader(repo_path).read_commit(oid)
    except ObjectError:
        raise RevertError(
            reason, f"No such commit: {oid}") from None


@dataclass(frozen=True)
class MergedChange:
    """A landed pull request, as git sees it: the base
    tip just after landing, the base tip just before,
    and the head commit that landed (the merge's
    second parent, or the empty string for a squash
    or rebase landing)."""
    merged_oid: str
    pre_merge_oid: str
    head_oid: str
    parents: tuple           # of str, merged_oid's parents
    kind: str                # 'merge' | 'single' | 'range'

    @property
    def words(self) -> str:
        if self.kind == "merge":
            return (f"merge commit {self.merged_oid[:12]} "
                    f"(head {self.head_oid[:12]})")
        if self.kind == "range":
            return (f"landed range ending at "
                    f"{self.merged_oid[:12]}")
        return f"landed commit {self.merged_oid[:12]}"


def describe_merged_change(repo_path: Path, merged_oid: object,
                           pre_merge_oid: object = None
                           ) -> MergedChange:
    """The landed change for a one-commit landing (a
    merge commit or a squash commit). Without an
    explicit `pre_merge_oid`, the merged commit's
    first parent is the pre-merge base — true for
    both shapes by construction. A merged commit with
    no parents landed on an empty base and cannot be
    reverted by this road (`no_parent`)."""
    repo_path = Path(repo_path)
    merged = _validate_oid(merged_oid, "merged_invalid")
    commit = _read_commit(repo_path, merged, "merged_not_found")
    if pre_merge_oid is None:
        if not commit.parents:
            raise RevertError(
                "no_parent",
                "That pull request landed as the first "
                "commit on its base branch; there is no "
                "earlier base state to revert to.")
        pre = commit.parents[0]
    else:
        pre = _validate_oid(pre_merge_oid, "pre_merge_invalid")
        _read_commit(repo_path, pre, "pre_merge_not_found")
    kind = "merge" if len(commit.parents) >= 2 else "single"
    head = commit.parents[1] if len(commit.parents) >= 2 else ""
    return MergedChange(
        merged_oid=merged, pre_merge_oid=pre, head_oid=head,
        parents=tuple(commit.parents), kind=kind)


def describe_merged_range(repo_path: Path,
                          first_landed_oid: object,
                          merged_oid: object) -> MergedChange:
    """The landed change for a rebase landing: a range
    of commits replayed onto the base, named by its
    first replayed commit and the base tip it ended
    at. The pre-merge base is the first replayed
    commit's first parent."""
    repo_path = Path(repo_path)
    merged = _validate_oid(merged_oid, "merged_invalid")
    _read_commit(repo_path, merged, "merged_not_found")
    first = _validate_oid(first_landed_oid, "merged_invalid")
    first_commit = _read_commit(
        repo_path, first, "merged_not_found")
    if not first_commit.parents:
        raise RevertError(
            "no_parent",
            "That pull request landed from the very "
            "first commit on its base branch; there is "
            "no earlier base state to revert to.")
    return MergedChange(
        merged_oid=merged,
        pre_merge_oid=first_commit.parents[0], head_oid="",
        parents=tuple(first_commit.parents), kind="range")


def default_revert_branch_name(number: int, head_branch: str) -> str:
    """`revert-<number>-<head branch>`, made lawful:
    characters outside the branch-name law become
    dashes, runs collapse, and the whole name is
    capped at the law's 100 characters (the number
    prefix is never truncated away)."""
    raw = f"revert-{int(number)}-{head_branch or ''}"
    cleaned = re.sub(r"[^A-Za-z0-9._/-]+", "-", raw)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    cleaned = cleaned.replace("..", "-").replace("//", "/")
    cleaned = cleaned.strip("/.")
    if len(cleaned) > 100:
        cleaned = cleaned[:100].rstrip("/.-")
    try:
        return validate_branch_name(cleaned)
    except RepositoryError:
        return validate_branch_name(f"revert-{int(number)}")


def default_revert_message(number: int, title: str,
                           merged_oid: str) -> str:
    """The revert commit's message: the landed pull
    request named in the subject, its number and its
    landing commit in the body, so the history itself
    carries the link before any database row does."""
    subject = (f"Revert \"{title}\"" if title
               else f"Revert pull request #{int(number)}")
    return (f"{subject}\n\n"
            f"This reverts pull request #{int(number)}, "
            f"landed in commit {merged_oid}.\n")


def samverk_identity(user) -> tuple[str, str]:
    """(author name, email) for a commit by `user` —
    the S-064/S-150 identity shape."""
    return (user.username,
            f"{user.username_lower}@samverk.invalid")


@dataclass(frozen=True)
class RevertPlan:
    """The computed inverse: a tree, or the conflict
    that refused it. `tree_oid` is the would-be tree
    even on conflict (merge-tree writes one); callers
    must honour `is_clean` and never land a conflicted
    plan's tree."""
    tree_oid: str
    current_oid: str
    merged_oid: str
    pre_merge_oid: str
    conflicted_paths: tuple = ()
    messages: tuple = ()
    current_tree_oid: str = ""

    @property
    def is_clean(self) -> bool:
        return not self.conflicted_paths

    @property
    def is_empty(self) -> bool:
        """True when the inverse changes nothing on the
        base as it stands — the change is already gone
        (or never differed), so a revert pull request
        would propose nothing."""
        return self.is_clean and bool(self.current_tree_oid) \
            and self.tree_oid == self.current_tree_oid

    @property
    def words(self) -> str:
        if not self.is_clean:
            return ("The revert does not apply cleanly; "
                    "these files conflict: "
                    + ", ".join(self.conflicted_paths) + ".")
        if self.is_empty:
            return ("Reverting this pull request would "
                    "change nothing on the base branch "
                    "as it stands.")
        return ("The revert applies cleanly to the base "
                "branch as it stands.")


def compute_revert_tree(repo_path: Path, *,
                        current_oid: object,
                        merged_oid: object,
                        pre_merge_oid: object) -> RevertPlan:
    """Compute the tree the base would have if the
    landed change were undone, without moving any
    ref. Raises RevertError only for unreadable input
    or a git failure; a content conflict is data on
    the returned plan (`is_clean` False), because
    naming the conflicted files is this seam's job
    for both the refusal path and any preview."""
    repo_path = Path(repo_path)
    current = _validate_oid(current_oid, "current_invalid")
    merged = _validate_oid(merged_oid, "merged_invalid")
    pre = _validate_oid(pre_merge_oid, "pre_merge_invalid")
    current_commit = _read_commit(
        repo_path, current, "current_not_found")
    _read_commit(repo_path, merged, "merged_not_found")
    _read_commit(repo_path, pre, "pre_merge_not_found")
    result = run_git_in(
        repo_path,
        ["merge-tree", "--write-tree", "--name-only", "-z",
         f"--merge-base={merged}", current, pre],
        timeout=60.0)
    fields = result.stdout.split(b"\x00")
    tree_oid = fields[0].decode("ascii", "replace").strip() \
        if fields else ""
    if result.returncode not in (0, 1) or not _OID_RE.match(tree_oid):
        detail = result.stderr.decode(
            "utf-8", "replace").strip()[:200]
        raise RevertError(
            "revert_failed",
            f"git could not compute the revert. {detail}".strip())
    conflicted: tuple = ()
    messages: tuple = ()
    if result.returncode == 1:
        rest = fields[1:]
        paths: list[str] = []
        idx = 0
        while idx < len(rest) and rest[idx] != b"":
            paths.append(rest[idx].decode(
                "utf-8", "surrogateescape"))
            idx += 1
        notes = [f.decode("utf-8", "replace")
                 for f in rest[idx + 1:] if f.strip()]
        conflicted = tuple(paths)
        messages = tuple(notes)
        if not conflicted:
            raise RevertError(
                "revert_failed",
                "git refused the revert without naming "
                "the conflicted files.")
    return RevertPlan(
        tree_oid=tree_oid, current_oid=current,
        merged_oid=merged, pre_merge_oid=pre,
        conflicted_paths=conflicted, messages=messages,
        current_tree_oid=current_commit.tree)


@dataclass(frozen=True)
class RevertCommit:
    commit_oid: str
    tree_oid: str
    parent_oid: str          # the base tip it reverts on top of
    plan: RevertPlan = field(compare=False, default=None)


def build_revert_commit(repo_path: Path, *,
                        current_oid: object,
                        merged_oid: object,
                        pre_merge_oid: object,
                        author_name: str, author_email: str,
                        message: str) -> RevertCommit:
    """One commit undoing the landed change, parented
    on the current base tip. A conflicted inverse is
    refused `revert_conflict` (paths named, nothing
    written beyond inert merge by-products); an empty
    inverse is refused `revert_empty`."""
    repo_path = Path(repo_path)
    plan = compute_revert_tree(
        repo_path, current_oid=current_oid,
        merged_oid=merged_oid, pre_merge_oid=pre_merge_oid)
    if not plan.is_clean:
        raise RevertError(
            "revert_conflict",
            "Reverting this pull request does not apply "
            "cleanly to the base branch as it stands; "
            "these files conflict: "
            + ", ".join(plan.conflicted_paths)
            + ". Resolve the later changes first, or "
            "revert by hand.",
            paths=plan.conflicted_paths)
    if plan.is_empty:
        raise RevertError(
            "revert_empty",
            "Reverting this pull request would change "
            "nothing on the base branch as it stands; "
            "its changes are already gone.")
    if not isinstance(message, str) or not message.strip():
        raise RevertError(
            "message_invalid", "A revert commit needs a message.")
    env = {
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author_name,
        "GIT_COMMITTER_EMAIL": author_email,
    }
    commit = run_git_in(
        repo_path,
        ["commit-tree", plan.tree_oid, "-p", plan.current_oid],
        input_bytes=message.encode("utf-8"), timeout=15.0,
        env_extra=env)
    if commit.returncode != 0:
        raise RevertError(
            "revert_failed", "git could not commit the revert.")
    return RevertCommit(
        commit_oid=commit.stdout.decode().strip(),
        tree_oid=plan.tree_oid, parent_oid=plan.current_oid,
        plan=plan)


def create_revert_branch(repo_path: Path, branch_name: object,
                         commit_oid: object) -> str:
    """Create the revert branch at the revert commit,
    compare-and-swap against the zero oid (S-053): a
    name that already exists is refused
    `branch_taken`, never overwritten. Returns the
    validated branch name."""
    repo_path = Path(repo_path)
    try:
        name = validate_branch_name(branch_name)
    except RepositoryError:
        raise RevertError(
            "branch_invalid",
            f"That branch name is not valid: {branch_name!r}"
        ) from None
    commit = _validate_oid(commit_oid, "commit_invalid")
    _read_commit(repo_path, commit, "commit_not_found")
    refs = RefStore(repo_path)
    if refs.resolve(branch_ref(name)) is not None:
        raise RevertError(
            "branch_taken",
            f"A branch named {name!r} already exists.")
    try:
        refs.create_branch(name, commit)
    except RefError:
        raise RevertError(
            "branch_taken",
            f"A branch named {name!r} already exists.") from None
    return name


@dataclass(frozen=True)
class LandedRevert:
    """A revert ready to be proposed: its commit, the
    new branch carrying it, and the base branch (and
    tip) it proposes back into."""
    commit: RevertCommit
    branch: str
    base_branch: str
    base_oid: str
    change: MergedChange

    @property
    def commit_oid(self) -> str:
        return self.commit.commit_oid


def land_revert(repo_path: Path, *, base_branch: object,
                merged_oid: object,
                pre_merge_oid: object = None,
                first_landed_oid: object = None,
                branch_name: object,
                author_name: str, author_email: str,
                message: str) -> LandedRevert:
    """The whole git act in one call: resolve the base
    branch as it stands, describe the landed change
    (explicit pair, one-commit derivation, or rebase
    range, in that order of authority), build the
    revert commit on the base tip, and create the
    revert branch at it. Every refusal — missing
    base (`base_not_found`), conflict, empty, taken
    branch name — is raised before any branch exists;
    the base branch itself is never moved."""
    repo_path = Path(repo_path)
    try:
        base = validate_branch_name(base_branch)
    except RepositoryError:
        raise RevertError(
            "branch_invalid",
            f"That branch name is not valid: {base_branch!r}"
        ) from None
    refs = RefStore(repo_path)
    base_oid = refs.resolve(branch_ref(base))
    if base_oid is None:
        raise RevertError(
            "base_not_found",
            f"The base branch {base!r} does not exist in "
            "this repository yet.")
    if first_landed_oid is not None:
        change = describe_merged_range(
            repo_path, first_landed_oid, merged_oid)
        if pre_merge_oid is not None:
            change = MergedChange(
                merged_oid=change.merged_oid,
                pre_merge_oid=_validate_oid(
                    pre_merge_oid, "pre_merge_invalid"),
                head_oid=change.head_oid,
                parents=change.parents, kind=change.kind)
    else:
        change = describe_merged_change(
            repo_path, merged_oid, pre_merge_oid)
    commit = build_revert_commit(
        repo_path, current_oid=base_oid,
        merged_oid=change.merged_oid,
        pre_merge_oid=change.pre_merge_oid,
        author_name=author_name, author_email=author_email,
        message=message)
    branch = create_revert_branch(repo_path, branch_name,
                                  commit.commit_oid)
    return LandedRevert(
        commit=commit, branch=branch, base_branch=base,
        base_oid=base_oid, change=change)
