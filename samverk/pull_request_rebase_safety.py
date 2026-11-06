"""Pull request rebase safety (S-155, refusal side).

S-155 lands a pull request by *rebase*: the head branch's
commits are replayed, one by one, onto the base branch.
This module is the refusal half of that slice — the part
that makes "refused loudly when conflicts would result
(no silent half-states)" true. The replay engine itself
lives in Builder-1's module and *calls* this one; nothing
here moves a branch or a pull request on its own.

- **Pre-flight is a pure dry run.** `plan_rebase` replays
  the head commits against the base *in the object store
  only*, before anything is mutated: for each head commit,
  in oldest-first order, `git merge-tree --write-tree`
  performs the same three-way merge a real replay would
  (the commit's own parent is the merge base), and a clean
  step's tree is turned into a dangling commit with
  `commit-tree` so the next step merges against the true
  replayed state. No ref is written, no index exists (the
  store is bare), no working tree is touched, and no
  database row is read or written — the only writes are
  content-addressed git objects, unreachable until the
  engine chooses to point a ref at them, exactly like
  S-150's `hash-object -w` on the road to an apply.
- **The refusal is loud and typed.** When a step would
  conflict, `plan_rebase` raises `RebaseConflictError` —
  a `PullRequestError` (the house error style: a stable
  `reason`, here always `rebase_conflict`, plus a plain-
  words message) whose payload names *which* commit would
  conflict (oid and subject) and *which paths* in it, so
  the caller can say exactly that to the author instead
  of discovering it mid-replay. A head commit that is a
  merge commit replays by its first-parent diff, exactly
  as the engine does (DESIGN A3), so the dry run judges
  the same replay the landing would perform.
  Simulation stops at the first conflicting commit:
  every later step's outcome depends on how that one is
  resolved, so claiming more would be inventing results.
- **No half-state, enforced — not just promised.** The
  refusal path cannot leave one: it runs before any
  mutation and itself mutates nothing reachable. For the
  replay path, `RebaseStateGuard` snapshots every ref's
  oid before the engine starts; used as a context
  manager (or via an explicit `abort()`), any exception
  or abort restores each moved ref by compare-and-swap
  to its snapshot value and deletes refs the attempt
  created, so refs, and therefore every branch a pull
  request points at, end exactly as they stood. The
  engine's database transition stays in its own single
  transaction, as everywhere in the house; this guard
  covers the git side, and `differences()` lets a caller
  *prove* the guarantee afterwards instead of asserting
  it. The pull request row is never touched by this
  module at all, so a refused (or aborted) rebase leaves
  PR state exactly as before by construction.
- **Mid-replay conflicts abort the same way.** Should a
  conflict somehow appear during a real replay despite a
  clean pre-flight (the base moved in between), the
  engine aborts through the guard: refs roll back to the
  snapshot and the attempt is reported as refused, never
  left half-replayed. A base or head that moved since
  the plan was computed is itself a refusal
  (`rebase_stale_plan`) before the first real step.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .escaping import escape_html_text
from .proc import run_git_in
from .pull_requests import PullRequestError
from .refs import RefError, RefStore

__all__ = [
    "RebaseConflict",
    "RebaseConflictError",
    "RebasePlan",
    "RebaseStateGuard",
    "RebaseStep",
    "plan_rebase",
    "render_rebase_refusal",
    "restore_refs",
    "snapshot_refs",
]

# git's empty tree: the merge base of a root commit.
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_ZERO_OID = "0" * 40


@dataclass(frozen=True)
class RebaseConflict:
    """One commit that cannot be replayed cleanly."""

    commit_oid: str          # the head commit, as written
    subject: str             # its subject line, in words
    paths: tuple             # of str, conflicted paths (() if n/a)
    kind: str                # 'content'


@dataclass(frozen=True)
class RebaseStep:
    """One clean replay step, proven by the dry run."""

    source_oid: str          # the head commit, as written
    subject: str
    tree_oid: str            # the tree the replay produces
    replayed_oid: str        # dangling commit carrying it


@dataclass(frozen=True)
class RebasePlan:
    """A proven-clean replay: every step, in order."""

    base_oid: str            # the base the plan was made on
    head_oid: str            # the head the plan was made from
    steps: tuple             # of RebaseStep, oldest first

    @property
    def replayed_head_oid(self) -> str:
        """Where the head lands if every step is taken:
        the base itself when there is nothing to replay."""
        if self.steps:
            return self.steps[-1].replayed_oid
        return self.base_oid


class RebaseConflictError(PullRequestError):
    """The loud refusal: replaying would conflict.

    `reason` is always `rebase_conflict`; the payload is
    `conflicts` (a tuple of `RebaseConflict`, the first —
    and honestly only knowable — commit that would not
    replay, with its paths), plus the base/head oids the
    judgement was made against. The message says the same
    in plain words, so log, page and API all refuse
    identically loudly.
    """

    def __init__(self, conflicts, *, base_oid: str,
                 head_oid: str):
        self.conflicts = tuple(conflicts)
        self.base_oid = base_oid
        self.head_oid = head_oid
        lines = [
            "This pull request cannot be rebased onto its "
            "base branch: replaying the head commits would "
            "conflict. Nothing was changed — the branches "
            "and the pull request are exactly as they were."
        ]
        for conflict in self.conflicts:
            short = conflict.commit_oid[:12]
            if conflict.paths:
                lines.append(
                    f"Commit {short} ({conflict.subject}) "
                    "conflicts in: "
                    + ", ".join(conflict.paths) + ".")
            else:
                lines.append(
                    f"Commit {short} ({conflict.subject}) "
                    "conflicts.")
        lines.append(
            "Resolve the conflict on the head branch and "
            "push again, then rebase once it replays cleanly.")
        super().__init__("rebase_conflict", "\n".join(lines))


# -- internals ---------------------------------------------------


def _git(repo_path: Path, args: list[str], **kw):
    return run_git_in(repo_path, args, timeout=30.0, **kw)


def _resolve_commit(repo_path: Path, oid: object, reason: str) -> str:
    if not isinstance(oid, str) or not oid:
        raise PullRequestError(reason, "No such commit.")
    result = _git(repo_path, ["rev-parse", "--verify", "--quiet",
                              f"{oid}^{{commit}}"])
    if result.returncode != 0:
        raise PullRequestError(reason, "No such commit.")
    return result.stdout.decode().strip()


def _commit_facts(repo_path: Path, oid: str):
    """(parents tuple, subject, message bytes, env dict)
    for one commit — everything a faithful replay needs."""
    result = _git(repo_path, [
        "show", "-s",
        "--format=%P%x00%an%x00%ae%x00%ad%x00%cn%x00%ce%x00%cd",
        "--date=raw", oid])
    if result.returncode != 0:
        raise PullRequestError(
            "rebase_preflight_failed",
            "git could not read a head commit; nothing was changed.")
    fields = result.stdout.decode(
        "utf-8", "surrogateescape").rstrip("\n").split("\x00")
    if len(fields) != 7:
        raise PullRequestError(
            "rebase_preflight_failed",
            "git could not read a head commit; nothing was changed.")
    parents = tuple(fields[0].split()) if fields[0] else ()
    env = {
        "GIT_AUTHOR_NAME": fields[1],
        "GIT_AUTHOR_EMAIL": fields[2],
        "GIT_AUTHOR_DATE": fields[3],
        "GIT_COMMITTER_NAME": fields[4],
        "GIT_COMMITTER_EMAIL": fields[5],
        "GIT_COMMITTER_DATE": fields[6],
    }
    shown = _git(repo_path, ["show", "-s", "--format=%B", oid])
    message = shown.stdout if shown.returncode == 0 else b""
    subject = message.decode(
        "utf-8", "replace").split("\n", 1)[0].strip()
    return parents, subject, message, env


def _simulate_step(repo_path: Path, current_oid: str,
                   commit_oid: str, merge_base: str):
    """One three-way replay step, off-path.

    Returns (tree_oid, conflicted_paths tuple). An empty
    paths tuple means the step is clean.
    """
    result = _git(repo_path, [
        "merge-tree", "--write-tree", "--name-only",
        "--merge-base", merge_base, current_oid, commit_oid])
    if result.returncode not in (0, 1):
        raise PullRequestError(
            "rebase_preflight_failed",
            "git could not test the rebase; nothing was changed.")
    lines = result.stdout.decode(
        "utf-8", "surrogateescape").split("\n")
    tree_oid = lines[0].strip() if lines else ""
    if result.returncode == 0:
        return tree_oid, ()
    paths = []
    for line in lines[1:]:
        if not line:
            break
        paths.append(line)
    return tree_oid, tuple(paths)


# -- pre-flight ----------------------------------------------------


def plan_rebase(repo_path: Path, base_oid: object,
                head_oid: object) -> RebasePlan:
    """Dry-run the whole replay; return the proven plan.

    Raises `RebaseConflictError` (reason `rebase_conflict`)
    carrying the first commit that would conflict and its
    paths, or a plain `PullRequestError` when a target does
    not resolve (`rebase_commit_not_found`) or git itself
    fails (`rebase_preflight_failed`). Mutates nothing
    reachable: no ref moves, no row changes — the dry run
    writes only unreachable objects.
    """
    repo_path = Path(repo_path)
    base = _resolve_commit(
        repo_path, base_oid, "rebase_commit_not_found")
    head = _resolve_commit(
        repo_path, head_oid, "rebase_commit_not_found")
    based = _git(repo_path, ["merge-base", base, head])
    if based.returncode != 0:
        raise PullRequestError(
            "rebase_preflight_failed",
            "The base and head share no common ancestor; "
            "nothing was changed.")
    merge_base_oid = based.stdout.decode().strip()
    listed = _git(repo_path, [
        "rev-list", "--reverse", f"{merge_base_oid}..{head}"])
    if listed.returncode != 0:
        raise PullRequestError(
            "rebase_preflight_failed",
            "git could not list the head commits; "
            "nothing was changed.")
    oids = [line.strip() for line in
            listed.stdout.decode().splitlines() if line.strip()]
    current = base
    steps: list[RebaseStep] = []
    for oid in oids:
        parents, subject, message, env = _commit_facts(
            repo_path, oid)
        # A merge commit replays by its first-parent diff
        # (DESIGN A3): the merge base is its first parent,
        # so the walk flattens it like the engine does.
        merge_base = parents[0] if parents else _EMPTY_TREE
        tree_oid, conflicts = _simulate_step(
            repo_path, current, oid, merge_base)
        if conflicts:
            raise RebaseConflictError(
                [RebaseConflict(commit_oid=oid, subject=subject,
                                paths=conflicts, kind="content")],
                base_oid=base, head_oid=head)
        made = _git(repo_path, ["commit-tree", tree_oid,
                                "-p", current],
                    input_bytes=message, env_extra=env)
        if made.returncode != 0:
            raise PullRequestError(
                "rebase_preflight_failed",
                "git could not stage the replay; "
                "nothing was changed.")
        current = made.stdout.decode().strip()
        steps.append(RebaseStep(
            source_oid=oid, subject=subject,
            tree_oid=tree_oid, replayed_oid=current))
    return RebasePlan(base_oid=base, head_oid=head,
                      steps=tuple(steps))


# -- the no-half-state guard ---------------------------------------


def snapshot_refs(repo_path: Path) -> dict:
    """Every ref's oid today: {full_ref_name: oid}."""
    return {ref.name: ref.oid
            for ref in RefStore(Path(repo_path)).list_refs()}


def restore_refs(repo_path: Path, snapshot: dict) -> list:
    """Roll refs back to `snapshot`; return the names that
    had moved (and were restored or deleted). Each restore
    is a compare-and-swap against the value found, so a
    ref a third party moved *again* after the attempt is
    left alone and reported as unrestored by omission —
    callers check `differences` to prove the end state."""
    store = RefStore(Path(repo_path))
    now = snapshot_refs(repo_path)
    restored: list[str] = []
    for name in sorted(set(now) | set(snapshot)):
        if now.get(name) == snapshot.get(name):
            continue
        try:
            if name not in snapshot:
                # Created by the attempt: delete it.
                store.update_ref(name, _ZERO_OID,
                                 expected_old=now[name])
            elif name not in now:
                store.update_ref(name, snapshot[name],
                                 expected_old=_ZERO_OID)
            else:
                store.update_ref(name, snapshot[name],
                                 expected_old=now[name])
        except RefError:
            continue
        restored.append(name)
    return restored


class RebaseStateGuard:
    """Snapshot/restore armour around a real replay.

    Usage: `with RebaseStateGuard(repo_path) as guard:` —
    an exception inside the block restores every ref and
    re-raises; `guard.abort()` restores on demand (the
    mid-replay conflict road); a clean exit leaves the
    replay standing. `differences()` names any ref whose
    oid differs from the snapshot, so "exactly as before"
    is checkable, never merely claimed.
    """

    def __init__(self, repo_path: Path):
        self._repo = Path(repo_path)
        self.snapshot = snapshot_refs(self._repo)

    def __enter__(self) -> "RebaseStateGuard":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.abort()
        return False

    def differences(self) -> dict:
        """{ref: (snapshot_oid, current_oid)} for every
        ref that differs; empty means exactly as before."""
        now = snapshot_refs(self._repo)
        out = {}
        for name in sorted(set(now) | set(self.snapshot)):
            if now.get(name) != self.snapshot.get(name):
                out[name] = (self.snapshot.get(name),
                             now.get(name))
        return out

    def abort(self) -> list:
        """Restore the snapshot now; return restored refs."""
        return restore_refs(self._repo, self.snapshot)

    def assert_plan_fresh(self, plan: RebasePlan,
                          base_ref: str, head_ref: str) -> None:
        """Refuse a replay whose ground moved: the refs
        must still name the oids the plan was proven on."""
        store = RefStore(self._repo)
        if store.resolve(base_ref) != plan.base_oid \
                or store.resolve(head_ref) != plan.head_oid:
            raise PullRequestError(
                "rebase_stale_plan",
                "The base or head branch moved since the "
                "rebase was checked; nothing was changed. "
                "Check the rebase again.")


# -- render ---------------------------------------------------------


def render_rebase_refusal(error: RebaseConflictError) -> str:
    """The refusal in plain words, for the PR page: what
    would conflict, in which commit, in which files —
    said in text, never colour alone. Every value escapes
    through S-010."""
    parts = [
        '<section class="rebase-refusal">',
        "<h2>Rebase refused — it would conflict</h2>",
        "<p>This pull request was not rebased. The "
        "branches and the pull request are exactly as "
        "they were.</p>",
        '<ul class="conflicts">',
    ]
    for conflict in error.conflicts:
        short = escape_html_text(conflict.commit_oid[:12])
        subject = escape_html_text(conflict.subject)
        paths = ", ".join(
            escape_html_text(p) for p in conflict.paths)
        parts.append(
            f'<li class="conflict">Commit {short} '
            f"({subject}) conflicts in: {paths}.</li>")
    parts.append("</ul>")
    parts.append(
        "<p>Resolve the conflict on the head branch and "
        "push again, then rebase once it replays "
        "cleanly.</p>")
    parts.append("</section>")
    return "\n".join(parts)
