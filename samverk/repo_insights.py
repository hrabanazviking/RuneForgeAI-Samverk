"""Repository insights-lite (S-115).

Traffic-free, honest statistics: this page shows what
the instance truly knows and names — in words, on the
page — what it does not know. No number is dressed up
as knowledge it is not.

- **What we know, from the stores that hold it:**
  commits, branches, tags and contributors from S-106's
  cached derivations (with the same fresh/cached honesty
  about their computation); accepted pushes from S-090's
  event store, counted exactly (`push_count`, and the
  time of the most recent one — an event-store fact, not
  an estimate); recorded clone/fetch transfers of this
  repository from the S-094 transport audit — whose own
  law records private-repository reads and no others,
  so for a public repository that count is stated as
  recorded-fetches-of-private-repos = inapplicable, never
  as "zero clones"; and the repository's size on disk
  from the filesystem walk (S-058's measure).
- **What we do not track, named:** clone counts for
  anonymous/public reads (S-094 refuses to record them —
  public content is public and its readers are not
  surveilled), page views, unique visitors, and referrers.
  These ride in `NOT_TRACKED` and the rendered page lists
  them under "Not tracked" with the reason, so a reader
  can never mistake an absent number for a zero.
- **No invented traffic.** There is deliberately no
  `clone_count` field anywhere in this module: the one
  dishonest number this page could offer is made
  structurally absent, the same shape as S-112's absent
  disabled buttons.
- Permission is S-054's `can_read`, as everywhere — a
  private repository's statistics are as private as its
  code (and its chrome is the uniform not-found).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from .accounts import User
from .escaping import escape_html_text
from .permissions import can_read
from .push_events import PushEventStore
from .repo_size import measure_path
from .repo_stats import RepoStatsService, RepoSummary
from .repositories import RepositoryStore

# (statistic, why it is not tracked) — stated on the page.
NOT_TRACKED = (
    ("Clone counts for public and anonymous reads",
     "S-094 records reads of private repositories only; "
     "readers of public work are not surveilled."),
    ("Page views and unique visitors",
     "Samverk keeps no visitor analytics."),
    ("Referrers and traffic sources",
     "Samverk keeps no visitor analytics."),
)


class InsightsError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class RepoInsights:
    full_name: str
    visibility: str
    summary: RepoSummary                # S-106, verbatim
    push_count: int                     # S-090 events, exact
    last_push_at: int | None            # epoch seconds, or None
    recorded_private_fetches: int | None
    # ^ Count of S-094 repo.fetch audit rows for this repo —
    # only meaningful for private repos; None for public
    # repos, where the answer is "not applicable", not 0.
    size_bytes: int                     # on-disk measure


class RepoInsightsService:
    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 stats: RepoStatsService,
                 push_events: PushEventStore):
        self._conn = conn
        self._repos = repositories
        self._stats = stats
        self._pushes = push_events

    def insights(self, viewer: User | None, owner: object,
                 repo: object) -> RepoInsights:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise InsightsError("repo_not_found", "No such repository.")
        summary = self._stats.summary(viewer, current.owner, current.name)
        push_count = self._pushes.count_for_repo(current.owner, current.name)
        last_push_at = None
        if push_count:
            newest = self._pushes.list_for_repo(
                current.owner, current.name, limit=1)
            if newest:
                last_push_at = newest[0].created_at
        if current.visibility == "private":
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM audit_log "
                "WHERE action = 'repo.fetch' AND target_id = ?",
                (current.full_name,)).fetchone()
            recorded = int(row["n"])
        else:
            recorded = None
        size = measure_path(
            self._repos.path_for(current.owner, current.name))
        return RepoInsights(
            full_name=current.full_name, visibility=current.visibility,
            summary=summary, push_count=push_count,
            last_push_at=last_push_at,
            recorded_private_fetches=recorded,
            size_bytes=size.total_bytes)


def _when(epoch: int | None) -> str:
    if epoch is None:
        return "no pushes recorded yet"
    stamp = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return stamp.strftime("%Y-%m-%d %H:%M UTC")


def render_insights_page(insights: RepoInsights) -> str:
    """Only true numbers, each with its source named; the
    not-tracked list is rendered, never omitted."""
    s = insights.summary
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(insights.full_name)} — insights — "
        "Samverk</title></head>",
        "<body>",
        f"<h1>Insights — {escape_html_text(insights.full_name)}</h1>",
        '<p class="honesty">Every number on this page comes from a '
        "record this instance actually keeps. What Samverk does not "
        "track is listed at the bottom — an absent number there "
        "means \u201cnot tracked\u201d, never zero.</p>",
        '<ul class="insights">',
        f"<li>Commits: {s.commit_count} "
        f"({'counted just now' if not s.from_cache else 'from the cached count'})</li>",
        f"<li>Branches: {s.branch_count}</li>",
        f"<li>Tags: {s.tag_count}</li>",
        f"<li>Contributors (author identities in the history): "
        f"{len(s.contributors)}</li>",
        f"<li>Accepted pushes recorded: {insights.push_count} "
        f"(most recent: {escape_html_text(_when(insights.last_push_at))})</li>",
    ]
    if insights.recorded_private_fetches is None:
        parts.append(
            "<li>Recorded read transfers: not applicable — this "
            "repository is public, and reads of public repositories "
            "are not recorded.</li>")
    else:
        parts.append(
            f"<li>Recorded read transfers of this private "
            f"repository: {insights.recorded_private_fetches}</li>")
    parts.append(
        f"<li>Size on disk: {insights.size_bytes} bytes</li>")
    parts.append("</ul>")
    parts.append("<h2>Not tracked</h2>")
    parts.append('<ul class="not-tracked">')
    for name, why in NOT_TRACKED:
        parts.append(
            f"<li>{escape_html_text(name)} — "
            f"{escape_html_text(why)}</li>")
    parts.append("</ul>")
    parts.append("</body></html>")
    return "\n".join(parts)
