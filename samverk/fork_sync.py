"""Fork sync hint (S-159).

The third leg of S-159's branch housekeeping: when a fork
has fallen behind the repository it was forked from, the
fork's surfaces say so, in words, and say how it can catch
up. The hint is **read-only**: it is computed on read,
stored nowhere, audited nowhere (derived data adds no
event, the S-127/S-131 law), and S-159 ships the hint
only — actually syncing the fork is a write act this
slice does not take, and a hint that pretended to be the
act would be a faked affordance, which this house never
ships.

- **The relationship is S-055's record.** A fork's
  upstream is its direct parent (the `fork_of_id` row) —
  the repository a sync would pull from. Only a
  repository with `fork_of_id` set and a living parent
  can be behind at all; the comparison is between the
  two repositories' **default branches**, the pair a
  sync would move.
- **Behind-ness is counted the S-142 way.** Forks are
  full clones with separate object stores (S-055), so
  the fork's own copy of the upstream branch goes stale
  the moment the upstream moves. The parent default
  branch's current tip is fetched into the fork under
  one scratch ref (`refs/samverk/upstream-default`,
  through S-014's dedicated `run_git_fetch_ref` seam:
  local paths only, one named ref, no branch in either
  repository ever moved) and both directions are counted
  there with `rev-list --count`, the compare_view
  (S-105) pattern carried across repositories exactly
  as S-142 carries it: behind is commits the upstream
  default has that the fork default lacks, ahead is the
  reverse. The scratch ref is deleted again in every
  outcome. When the fork has no default branch yet,
  behind is the upstream default's whole reachable
  count, read in the upstream itself — no fetch is
  needed to know the fork has none of it.
- **Five states, said in words.** `not_a_fork` (no
  `fork_of_id`), `no_upstream` (the parent is gone, or
  the viewer may not read it — see below), `up_to_date`
  (behind is zero), `behind` (behind > 0), and
  `unknown` (the position could not be checked: the
  fetch or a count failed — the status carries no
  counts at all rather than guessed ones). The banner
  is shown **only** when behind > 0; every other state
  is silence on the page, never a badge.
- **The read gate leaks nothing.** The viewer must be
  able to read the fork *and* its upstream (S-142's
  fork bargain). A fork the viewer cannot read answers
  with the uniform `repo_not_found`; an upstream the
  viewer cannot read yields the `no_upstream` state
  with zeroed counts and no banner — the upstream's
  position never leaks through a fork the viewer
  happens to be able to see.
- **Surfaces.** The status is the `fork_sync` object on
  the repository read payload (always present — a
  non-fork carries `not_a_fork`), the banner rendered
  under the repository header on the fork's home
  (`render_fork_sync_hint`), and the fork's row in a
  forks/network listing (`render_fork_network_rows`).
  Every user-controlled value reaches HTML only through
  S-010's escaping seam, and state is always said in
  words, never colour alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from .accounts import User
from .escaping import escape_html_text
from .permissions import can_read
from .proc import ProcRefused, run_git_fetch_ref, run_git_in
from .refs import RefError, RefStore, branch_ref
from .repositories import Repository, RepositoryStore

__all__ = [
    "SCRATCH_REF", "FORK_SYNC_STATES", "ForkSyncError",
    "ForkSyncStatus", "ForkSyncStore",
    "render_fork_sync_hint", "render_fork_network_rows",
]

# The one scratch ref a sync check uses inside the fork.
# It is created by the fetch seam, read by the counts,
# and deleted in every outcome; it is never a branch and
# never survives the call that made it (S-142's law).
SCRATCH_REF = "refs/samverk/upstream-default"

# The closed state set, in the order a reader meets them.
FORK_SYNC_STATES = (
    "not_a_fork", "no_upstream", "up_to_date", "behind", "unknown")


class ForkSyncError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ForkSyncStatus:
    full_name: str
    state: str                       # one of FORK_SYNC_STATES
    upstream_full_name: str | None = None
    branch: str = ""                 # the fork's default branch
    behind: int | None = 0           # None only when state is unknown
    ahead: int | None = 0            # None only when state is unknown

    @property
    def can_show_hint(self) -> bool:
        """The banner exists only when there is something
        to catch up on."""
        return self.state == "behind" and bool(self.behind)

    @property
    def words(self) -> str:
        """The fork's sync position, said plainly. The
        `behind` wording is the design's own sentence."""
        if self.state == "not_a_fork":
            return ("This repository is not a fork; there is "
                    "no upstream to sync from.")
        if self.state == "no_upstream":
            return ("This fork's upstream is not available, "
                    "so no sync position is shown.")
        if self.state == "unknown":
            return ("This fork's sync position could not be "
                    "checked, so no counts are shown rather "
                    "than guessed.")
        if self.state == "behind":
            text = (f"This fork is behind "
                    f"{self.upstream_full_name}: its "
                    f"{self.branch} is {self.behind} commits "
                    "behind")
            if self.ahead:
                text += f" and {self.ahead} commits ahead"
            return (text + ". Open a pull request from the "
                    "upstream repository, or fetch upstream "
                    "locally, to catch up.")
        return (f"This fork is up to date with "
                f"{self.upstream_full_name}: its {self.branch} "
                "has nothing to catch up on.")

    def to_dict(self) -> dict:
        """The `fork_sync` object on the repository read
        payload — always present, counts honest (null
        when the position is unknown)."""
        return {
            "state": self.state,
            "upstream": self.upstream_full_name,
            "branch": self.branch,
            "behind": self.behind,
            "ahead": self.ahead,
        }


class ForkSyncStore:
    """The sync-position reader. It holds no state of its
    own: every answer is computed from the two bare
    repositories as they stand at the call."""

    def __init__(self, repositories: RepositoryStore):
        self._repos = repositories

    def fork_sync_status(self, viewer: User | None, owner: object,
                         repo: object) -> ForkSyncStatus:
        """This repository's sync position against its
        upstream, judged on read, comparing the two
        default branches."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise ForkSyncError("repo_not_found", "No such repository.")
        branch = current.default_branch
        if current.fork_of_id is None:
            return ForkSyncStatus(
                full_name=current.full_name, state="not_a_fork",
                branch=branch)
        upstream = self._repos.get_by_id(current.fork_of_id)
        if upstream is None or not can_read(viewer, upstream):
            # Gone, or not the viewer's to read: either way
            # no position is shown and no count leaks. The
            # name is lineage the fork's own record already
            # states; it is carried only when the parent
            # row still exists.
            return ForkSyncStatus(
                full_name=current.full_name, state="no_upstream",
                upstream_full_name=(
                    upstream.full_name if upstream is not None else None),
                branch=branch)
        base = dict(full_name=current.full_name,
                    upstream_full_name=upstream.full_name,
                    branch=branch)
        fork_path = self._repos.path_for(current.owner, current.name)
        upstream_path = self._repos.path_for(upstream.owner, upstream.name)
        fork_refs = RefStore(fork_path)
        upstream_refs = RefStore(upstream_path)
        fork_oid = fork_refs.resolve(branch_ref(branch))
        upstream_oid = upstream_refs.resolve(
            branch_ref(upstream.default_branch))
        if fork_oid == upstream_oid:
            # The same tip on both sides (including both
            # empty): nothing to count, nothing to fetch.
            return ForkSyncStatus(state="up_to_date", **base)
        try:
            if upstream_oid is None:
                ahead = self._count(fork_path, str(fork_oid))
                return ForkSyncStatus(
                    state="up_to_date", ahead=ahead, behind=0, **base)
            if fork_oid is None:
                behind = self._count(upstream_path, upstream_oid)
                return ForkSyncStatus(
                    state="behind" if behind > 0 else "up_to_date",
                    ahead=0, behind=behind, **base)
            result = run_git_fetch_ref(
                fork_path, upstream_path,
                branch_ref(upstream.default_branch), SCRATCH_REF)
            if result.returncode != 0:
                return ForkSyncStatus(
                    state="unknown", behind=None, ahead=None, **base)
            fetched = fork_refs.resolve(SCRATCH_REF)
            if fetched != upstream_oid:
                return ForkSyncStatus(
                    state="unknown", behind=None, ahead=None, **base)
            ahead = self._count(fork_path, f"{upstream_oid}..{fork_oid}")
            behind = self._count(fork_path, f"{fork_oid}..{upstream_oid}")
            return ForkSyncStatus(
                state="behind" if behind > 0 else "up_to_date",
                ahead=ahead, behind=behind, **base)
        except ForkSyncError:
            return ForkSyncStatus(
                state="unknown", behind=None, ahead=None, **base)
        finally:
            # The scratch ref never survives the check.
            if upstream_oid is not None and fork_oid is not None:
                try:
                    fork_refs.update_ref(
                        SCRATCH_REF, "0" * 40, expected_old=upstream_oid)
                except (RefError, ProcRefused):
                    pass

    def statuses_for_network(self, viewer: User | None,
                             members) -> tuple:
        """One status per repository in a fork network
        listing (S-055's `network_for` rows): each fork
        member judged against its own upstream, the root
        answering `not_a_fork`. A member the viewer
        cannot read answers `no_upstream` rather than
        raising, so one private member never breaks the
        whole listing's read."""
        out = []
        for member in members:
            assert isinstance(member, Repository)
            try:
                out.append(self.fork_sync_status(
                    viewer, member.owner, member.name))
            except ForkSyncError:
                out.append(ForkSyncStatus(
                    full_name=member.full_name, state="no_upstream",
                    branch=member.default_branch))
        return tuple(out)

    @staticmethod
    def _count(repo_path, revspec: str) -> int:
        out = run_git_in(repo_path, ["rev-list", "--count", revspec],
                         timeout=15.0)
        try:
            return int(out.stdout.decode().strip())
        except ValueError:
            raise ForkSyncError(
                "sync_check_failed",
                "The sync position could not be counted.") from None


def render_fork_sync_hint(status: ForkSyncStatus) -> str:
    """The repository-header banner: the position in
    words, shown only when the fork is behind — every
    other state is silence here, never a badge. Every
    value escapes through S-010."""
    if not status.can_show_hint:
        return ""
    return (f'<p class="fork-sync-hint">'
            f"{escape_html_text(status.words)}</p>")


def render_fork_network_rows(statuses) -> str:
    """The forks/network listing: one row per repository,
    its name always, and the sync position in words on
    the rows where there is something to catch up on."""
    rows = list(statuses)
    if not rows:
        return ('<p class="fork-network">This repository is '
                "not part of a fork network.</p>")
    items = []
    for status in rows:
        hint = ""
        if status.can_show_hint:
            hint = f" — {escape_html_text(status.words)}"
        items.append(
            '<li class="fork-network-row">'
            f"{escape_html_text(status.full_name)}{hint}</li>")
    return ('<ul class="fork-network">'
            + "".join(items) + "</ul>")
