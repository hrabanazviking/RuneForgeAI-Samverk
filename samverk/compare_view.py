"""Compare view (S-105).

Any two refs compared: the commits one side has that the
other does not, and the files changed between them — the
pre-PR workhorse (Part VII's PR creation opens here).

- **Both directions are counted.** `ahead` is commits in
  head that base lacks; `behind` is commits in base that
  head lacks. A diverged pair says so in numbers instead
  of pretending head is simply "newer".
- **The commit list is capped honestly.** At most
  `MAX_LISTED_COMMITS` commit rows are listed; the true
  ahead count is always reported, and a capped list says
  how many it is not showing.
- **The diff is S-104's engine** over the two resolved
  commits (`range_diff`), with its whitespace toggle and
  its folding — one diff reading everywhere.
- Refs resolve through S-097's law before anything is
  read; comparing a ref with itself is a true, empty
  comparison, not an error.
"""

from __future__ import annotations

from dataclasses import dataclass

from .accounts import User
from .commit_list import _FORMAT, parse_log_output
from .diff_engine import DiffSet, range_diff
from .escaping import escape_html_text
from .permissions import can_read
from .print_export import stylesheet_link_tag
from .proc import run_git_in
from .repo_home import RepoHomeError, resolve_commit
from .repositories import RepositoryStore
from .diff_engine import render_unified

MAX_LISTED_COMMITS = 250


class CompareError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class CompareView:
    full_name: str
    base_ref: str
    head_ref: str
    base_oid: str
    head_oid: str
    ahead: int
    behind: int
    commits: tuple          # of commit_list.CommitSummary, newest first
    commits_truncated: int  # ahead rows not listed (0 when complete)
    diff: DiffSet

    @property
    def files_changed(self) -> int:
        return len(self.diff.files)


class CompareService:
    def __init__(self, repositories: RepositoryStore):
        self._repos = repositories

    def compare(self, viewer: User | None, owner: object, repo: object,
                base_ref: object, head_ref: object, *,
                ignore_whitespace: bool = False) -> CompareView:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise CompareError("repo_not_found", "No such repository.")
        repo_path = self._repos.path_for(current.owner, current.name)
        try:
            base_name, base_oid = resolve_commit(repo_path, base_ref)
            head_name, head_oid = resolve_commit(repo_path, head_ref)
        except RepoHomeError as exc:
            raise CompareError(exc.reason, str(exc)) from None

        def _count(revspec: str) -> int:
            result = run_git_in(repo_path, ["rev-list", "--count", revspec],
                                timeout=15.0)
            try:
                return int(result.stdout.decode().strip())
            except ValueError:
                raise CompareError("object_unreadable",
                                   "Comparison could not be counted.") from None

        ahead = _count(f"{base_oid}..{head_oid}")
        behind = _count(f"{head_oid}..{base_oid}")
        listed = min(ahead, MAX_LISTED_COMMITS)
        commits: tuple = ()
        if listed:
            result = run_git_in(
                repo_path,
                ["log", f"--max-count={listed}",
                 f"--format={_FORMAT}", f"{base_oid}..{head_oid}"],
                timeout=30.0)
            if result.returncode != 0:
                raise CompareError("object_unreadable",
                                   "Comparison could not be read.")
            commits = tuple(parse_log_output(
                result.stdout.decode("utf-8", "replace")))
        diff = range_diff(repo_path, base_oid, head_oid,
                          ignore_whitespace=ignore_whitespace)
        return CompareView(
            full_name=current.full_name, base_ref=base_name,
            head_ref=head_name, base_oid=base_oid, head_oid=head_oid,
            ahead=ahead, behind=behind, commits=commits,
            commits_truncated=ahead - listed, diff=diff)


def render_compare_page(view: CompareView) -> str:
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(view.full_name)} — compare — "
        "Samverk</title>",
        stylesheet_link_tag(),
        "</head>",
        "<body>",
        f"<h1>Compare — {escape_html_text(view.full_name)}</h1>",
        f'<p class="meta">{escape_html_text(view.base_ref)} … '
        f"{escape_html_text(view.head_ref)} · {view.ahead} ahead · "
        f"{view.behind} behind · {view.files_changed} files changed · "
        f"+{view.diff.additions} −{view.diff.deletions}</p>",
    ]
    if view.ahead == 0 and view.behind == 0:
        parts.append(
            '<p class="empty">These two refs name the same commit. '
            "There is nothing to compare.</p>")
    else:
        if view.commits:
            parts.append('<ol class="commits">')
            for commit in view.commits:
                parts.append(
                    f'<li class="commit"><span class="oid">'
                    f"{escape_html_text(commit.oid[:12])}</span> "
                    f'<span class="subject">'
                    f"{escape_html_text(commit.subject)}</span> "
                    f'<span class="author">'
                    f"{escape_html_text(commit.author_name)}</span></li>")
            parts.append("</ol>")
            if view.commits_truncated:
                parts.append(
                    f'<p class="truncated">{view.commits_truncated} '
                    "further commits are not listed; the count above "
                    "is the true total.</p>")
        if view.diff.files:
            parts.append(render_unified(view.diff))
        else:
            parts.append(
                '<p class="empty">No file changes between these '
                "commits.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
