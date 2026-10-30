"""Repository header summary (S-119).

The header is the strip every repository page opens
with: what this repository is, in one glance — its
visibility, where it came from, and how the community
around it stands. Four laws shape it:

- **Badges are words, never colour alone.** The
  visibility badge is a text label ("Public" /
  "Private") carrying its meaning in a plain sentence
  beside it; the mirror badge likewise says what a
  mirror is and how its last sync ended, in words.
  This is the design law's no-colour-only-status rule
  applied to the smallest surface in Part V.
- **Lineage is told, and told honestly when it
  breaks.** A fork names its direct parent with a link
  to the parent's home. If the parent row is gone
  while the link remains (a dangling link is drift —
  S-071's checker names it — but a header must survive
  any row shape), the header says the parent no longer
  exists instead of linking nowhere or pretending the
  fork is an original.
- **A mirror's source path is never shown.** The
  badge names the source *kind* (a remote address /
  another repository on this instance) and the last
  sync's status word — never the source itself: a
  local source is a filesystem path, and an instance's
  filesystem layout is not header content.
- **Counts are real or named missing, never faked.**
  The fork count is counted from the repositories
  table at read time — the same fact S-055's
  `fork_count` reports. Watch and star counts have no
  store until S-222 (Part XI) wires the actions; until
  a counter is supplied through this module's seam,
  those counts are `None` and the header names them
  as not available yet — an absent number, never a
  dressed-up zero (S-115's honesty law). When S-222
  lands it passes `watch_counter` / `star_counter`
  callables and the counts become real without the
  header's shape changing.
- Permission is S-054's `can_read`, as everywhere: a
  stranger to a private repository gets the uniform
  `repo_not_found` and no header at all.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import User
from .escaping import escape_html_attr, escape_html_text
from .mirrors import MirrorService
from .permissions import can_read
from .repositories import Repository, RepositoryStore

VISIBILITY_WORDS = {
    "public": ("Public", "anyone can read this repository"),
    "private": ("Private", "only people with access can read it"),
}

MIRROR_KIND_WORDS = {
    "url": "mirrored from a remote address",
    "local": "mirrored from another repository on this instance",
}

SYNC_WORDS = {
    "ok": "last sync succeeded",
    "failed": "last sync failed",
}


class HeaderError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class RepoHeader:
    full_name: str
    owner: str
    name: str
    description: str
    visibility: str
    visibility_word: str        # "Public" | "Private"
    visibility_note: str        # the badge's meaning, in words
    is_fork: bool
    fork_parent: str | None     # parent full_name, when it exists
    fork_parent_url: str | None
    fork_parent_missing: bool   # fork_of set, parent row gone
    is_mirror: bool
    mirror_kind_word: str | None
    mirror_sync_word: str | None  # None = never synced
    fork_count: int             # counted at read time, always real
    watch_count: int | None     # None until S-222 wires a counter
    star_count: int | None      # None until S-222 wires a counter


Counter = Callable[[Repository], int]


def _checked_count(counter: Counter | None, repo: Repository,
                   kind: str) -> int | None:
    if counter is None:
        return None
    value = counter(repo)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HeaderError(
            "count_invalid",
            f"The {kind} counter returned {value!r}; counts are "
            "non-negative whole numbers.")
    return value


class RepoHeaderService:
    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 mirrors: MirrorService | None = None,
                 *, watch_counter: Counter | None = None,
                 star_counter: Counter | None = None):
        self._conn = conn
        self._repos = repositories
        self._mirrors = mirrors
        self._watch_counter = watch_counter
        self._star_counter = star_counter

    def header(self, viewer: User | None, owner: object,
               repo: object) -> RepoHeader:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise HeaderError("repo_not_found", "No such repository.")
        word, note = VISIBILITY_WORDS[current.visibility]
        parent = None
        parent_missing = False
        if current.fork_of_id is not None:
            parent = self._repos.get_by_id(current.fork_of_id)
            parent_missing = parent is None
        mirror = None
        if self._mirrors is not None:
            mirror = self._mirrors.mirror_for(current.owner, current.name)
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM repositories WHERE fork_of_id = ?",
            (current.id,)).fetchone()
        return RepoHeader(
            full_name=current.full_name, owner=current.owner,
            name=current.name, description=current.description,
            visibility=current.visibility,
            visibility_word=word, visibility_note=note,
            is_fork=current.fork_of_id is not None,
            fork_parent=parent.full_name if parent else None,
            fork_parent_url=(f"/{parent.owner}/{parent.name}"
                             if parent else None),
            fork_parent_missing=parent_missing,
            is_mirror=mirror is not None,
            mirror_kind_word=(MIRROR_KIND_WORDS.get(
                mirror.source_kind, "mirrored from elsewhere")
                if mirror else None),
            mirror_sync_word=((("never synced")
                               if mirror.last_status is None else
                               SYNC_WORDS.get(
                                   mirror.last_status,
                                   f"last sync: {mirror.last_status}"))
                              if mirror else None),
            fork_count=int(row["c"]),
            watch_count=_checked_count(
                self._watch_counter, current, "watch"),
            star_count=_checked_count(
                self._star_counter, current, "star"))


def _count_line(label: str, count: int | None) -> str:
    if count is None:
        return (f"<li>{label}: not available yet — "
                "watching and starring arrive with notifications "
                "(Part XI)</li>")
    return f"<li>{label}: {count}</li>"


def render_repo_header(header: RepoHeader) -> str:
    """The header strip: name, badges in words, lineage,
    and the counts block. Every value passes S-010."""
    parts = [
        '<header class="repo-header">',
        f"<h1>{escape_html_text(header.full_name)}</h1>",
    ]
    if header.description:
        parts.append(
            f'<p class="repo-description">'
            f"{escape_html_text(header.description)}</p>")
    parts.append('<ul class="repo-badges">')
    parts.append(
        f'<li class="badge badge-visibility">'
        f"{escape_html_text(header.visibility_word)} — "
        f"{escape_html_text(header.visibility_note)}</li>")
    if header.is_fork:
        if header.fork_parent is not None:
            parts.append(
                f'<li class="badge badge-fork">Fork of '
                f'<a href="{escape_html_attr(header.fork_parent_url)}">'
                f"{escape_html_text(header.fork_parent)}</a></li>")
        else:
            parts.append(
                '<li class="badge badge-fork">Fork — the repository '
                "it was forked from no longer exists</li>")
    if header.is_mirror:
        parts.append(
            f'<li class="badge badge-mirror">Mirror — '
            f"{escape_html_text(header.mirror_kind_word or '')}; "
            f"{escape_html_text(header.mirror_sync_word or '')}</li>")
    parts.append("</ul>")
    parts.append('<ul class="repo-counts">')
    parts.append(_count_line("Forks", header.fork_count))
    parts.append(_count_line("Watchers", header.watch_count))
    parts.append(_count_line("Stars", header.star_count))
    parts.append("</ul></header>")
    return "\n".join(parts)
