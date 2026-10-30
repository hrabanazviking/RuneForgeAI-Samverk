"""Contributors and counts (S-106).

The repository summary — commits, branches, tags,
contributors — from cached derivations.

- **Headline numbers are S-072's graph cache.** The
  counts come from `GraphCache` (its fingerprint-keyed
  store over the ref set): a fresh cache row is served
  as-is with its computation time; a missing or stale
  one is refreshed on the spot and the summary says it
  was freshly computed (`from_cache=False`), so no
  number is ever dressed up as fresher than it is.
- **Per-contributor counts** group the same history walk
  by author identity (`name <email>`), sorted by commits
  descending, then name — a contributor is an author
  identity in the history, stated as such; it is not a
  claim about accounts on this instance.
- An empty repository (no commits yet) answers with
  zeroes and no contributors — a true summary, not an
  error.
"""

from __future__ import annotations

from dataclasses import dataclass

from .accounts import User
from .escaping import escape_html_text
from .graph_cache import GraphCache
from .permissions import can_read
from .proc import run_git_in
from .repositories import RepositoryStore


class RepoStatsError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ContributorCount:
    identity: str           # "Name <email>", as authored
    commits: int


@dataclass(frozen=True)
class RepoSummary:
    full_name: str
    commit_count: int
    branch_count: int
    tag_count: int
    contributors: tuple[ContributorCount, ...]
    computed_at: int
    from_cache: bool


class RepoStatsService:
    def __init__(self, repositories: RepositoryStore, graph_cache: GraphCache):
        self._repos = repositories
        self._cache = graph_cache

    def summary(self, viewer: User | None, owner: object,
                repo: object) -> RepoSummary:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise RepoStatsError("repo_not_found", "No such repository.")
        stats = self._cache.cached_stats(current.owner, current.name)
        from_cache = stats is not None
        if stats is None:
            stats = self._cache.refresh(current.owner, current.name)
        repo_path = self._repos.path_for(current.owner, current.name)
        counts: dict[str, int] = {}
        if stats.commit_count:
            result = run_git_in(
                repo_path, ["log", "--all", "--format=%an%x00%ae"],
                timeout=30.0)
            if result.returncode != 0:
                raise RepoStatsError("object_unreadable",
                                     "Contributors cannot be counted.")
            for line in result.stdout.decode("utf-8", "replace").split("\n"):
                if not line:
                    continue
                name, _, email = line.partition("\x00")
                identity = f"{name} <{email}>"
                counts[identity] = counts.get(identity, 0) + 1
        contributors = tuple(
            ContributorCount(identity=identity, commits=count)
            for identity, count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])))
        return RepoSummary(
            full_name=current.full_name, commit_count=stats.commit_count,
            branch_count=stats.branch_count, tag_count=stats.tag_count,
            contributors=contributors, computed_at=stats.computed_at,
            from_cache=from_cache)


def render_summary_page(summary: RepoSummary) -> str:
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(summary.full_name)} — summary — "
        "Samverk</title></head>",
        "<body>",
        f"<h1>Summary — {escape_html_text(summary.full_name)}</h1>",
        f'<p class="meta">{summary.commit_count} commits · '
        f"{summary.branch_count} branches · {summary.tag_count} tags · "
        f"{len(summary.contributors)} contributors</p>",
    ]
    if not summary.contributors:
        parts.append(
            '<p class="empty">No commits yet, so no contributors. '
            "Push a first commit and this page will count it.</p>")
    else:
        parts.append('<ul class="contributors">')
        for contributor in summary.contributors:
            parts.append(
                f'<li><span class="identity">'
                f"{escape_html_text(contributor.identity)}</span> — "
                f"{contributor.commits} commits</li>")
        parts.append("</ul>")
    parts.append("</body></html>")
    return "\n".join(parts)
