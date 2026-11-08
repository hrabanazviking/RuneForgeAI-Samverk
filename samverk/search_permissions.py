"""Permission-filtered results (S-209).

Search never reveals a title, snippet, or count
from a repo the searcher cannot read — Part X's
leakage law, discharged over the surfaces S-206
(the issue/PR backend) and S-208 (code search)
built. Both executors named this slice as their
tightening point: each resolved its visible
repositories through S-054's `can_read` before
reading any index row, and left the leakage
battery and the count guarantees to S-209. This
slice makes that seam one law in one place, adds
the counted faces whose totals are computed from
filtered hits only, and proves the guarantees in
tests/test_permission_filtered_search.py.

- **Filter first; everything else second.** The
  one resolution, `visible_repositories`, decides
  every repository a search may touch through
  S-054's `can_read`, before any index row is
  read. Titles, snippets, and counts are computed
  only from what survives that resolution — there
  is no post-hoc redaction step anywhere, because
  a redaction step is exactly where counts leak.
- **Absence, not redaction.** An unreadable
  repository contributes nothing: not a hit, not
  a title, not a snippet, not a match count, and
  not even an existence signal. A global search
  is silently without it; a search scoped to it
  answers the uniform `repo_not_found`, worded
  identically to a repository that does not exist
  (S-054's anti-enumeration answer).
- **Counts are tallies of visible hits.** The
  counted faces (`CodeSearch.search_counted`,
  `IssuePRSearch.search_counted`) tally totals
  over the full filtered result — before any
  result cap is applied — so a count a page shows
  is a count of things the searcher may read,
  never a count of the index. The equivalence the
  battery proves: a searcher's hits and counts
  over a world containing an unreadable repository
  are identical to the same search over a world
  where that repository was never created.
- **One resolution, every surface.** Both Part X
  executors delegate their global resolution to
  `visible_repositories` here; later surfaces
  (S-213's global UI, S-216's search API, S-230's
  feeds) ride the same resolution and the same
  counted faces, so the law cannot drift per
  surface. Per-repository faces (S-135, S-161)
  stay gated by their owning stores' read gates,
  which answer the same uniform not-found.
- **No audit event of its own, no migration.**
  Filtering is a read over reads. 122 events
  stand: 31 auth / 79 repo / 12 admin. Schema
  stays 82.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable

from .accounts import User
from .permissions import can_read
from .repositories import Repository, RepositoryStore

__all__ = [
    "CodeTally", "may_read", "tally_code_hits",
    "visible_repositories",
]


def may_read(viewer: User | None, repo: Repository) -> bool:
    """Whether *viewer* may read *repo*, under
    S-054's one gate — the judgement every search
    surface filters by."""
    return can_read(viewer, repo)


def visible_repositories(
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        viewer: User | None) -> list[Repository]:
    """Every repository a search by *viewer* may
    touch, in id order, resolved through S-054's
    `can_read` before any index row is read. This
    is the one global resolution for Part X: the
    S-206 backend and S-208 code search both
    delegate here (S-209), so no surface keeps a
    second copy of the law."""
    visible: list[Repository] = []
    for found in conn.execute(
            "SELECT id FROM repositories ORDER BY id").fetchall():
        current = repositories.get_by_id(int(found["id"]))
        if current is not None and can_read(viewer, current):
            visible.append(current)
    return visible

@dataclass(frozen=True)
class CodeTally:
    """The counts of one filtered code search:
    files that matched, total matches across them,
    and total matched lines — tallied from the
    filtered hits only, before any result cap, so
    the numbers describe what the searcher may
    read and nothing else."""
    files: int
    matches: int
    matched_lines: int


def tally_code_hits(hits: Iterable) -> CodeTally:
    """Tally *hits* (code-search hits, already
    permission-filtered by construction) into a
    `CodeTally`. The tally reads only the hits it
    is given: a repository filtered out before the
    search ran cannot enter the count here."""
    rows = list(hits)
    return CodeTally(
        files=len(rows),
        matches=sum(h.match_count for h in rows),
        matched_lines=sum(h.matched_lines for h in rows))
