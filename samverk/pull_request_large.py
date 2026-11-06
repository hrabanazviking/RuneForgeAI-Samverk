"""Pull request large-diff behaviour (S-166).

Large-PR behaviour — diffs beyond budget fold by file
with honest totals; review remains possible per-file.
S-145's files view renders every file's patch (subject
only to S-104's per-file fold limit); a pull request
with thousands of patch lines across dozens of files
would bury a reviewer under the whole change at once.
This slice lays a *total* budget over that view:

- **The budget is a count of patch lines, spent in
  diff order.** Files unfold while the running total
  of patch lines stays within the budget (default
  1,000 lines). The first file that would take the
  total past the budget folds, and every file after
  it folds too — folding is by whole file, never a
  part-shown file that looks smaller than it is. A
  single file whose own patch alone passes the budget
  folds on its own. A file landing exactly on the
  budget still unfolds: the budget is a limit, not a
  tripwire below it.
- **Totals are always the true totals.** Folded files
  count in full — file count, patch lines, additions,
  deletions — in every total and in the summary words.
  Folding hides patch text, never numbers: the view
  says how many files are shown, how many are folded,
  and what the folded files truly contain.
- **Review remains possible per-file.** `file_for`
  returns one named file unfolded in full, however
  far beyond the budget it stood in the whole-PR view
  and however large its own patch is, with the
  reviewer's viewed state (S-145) still laid over it.
  That is the road a reviewer walks through a large
  change: file by file, each one complete.
- **Nothing here is a new record.** The view is a pure
  read over S-145's files view (which rides S-141's
  seam, so a stranger to a private repository gets the
  uniform `pull_request_not_found`, and marking-style
  errors stay S-145's `file_not_found`). No migration
  is claimed (schema stays 64), no audit row is
  written, and no taxonomy event is added (the
  taxonomy stands at 119 events).
- **The budget is judged, not trusted.** A budget
  that is not a positive whole number of lines is
  refused `budget_invalid` before any diff is read.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import IssueStore
from .print_export import stylesheet_link_tag
from .pull_request_files import PrFileView, PullRequestFilesStore
from .pull_requests import PullRequestError
from .repositories import RepositoryStore

__all__ = [
    "DEFAULT_BUDGET_LINES", "LargePrFileView", "LargePrView",
    "PullRequestLargeStore", "render_large_file_page",
    "render_large_files_page",
]

DEFAULT_BUDGET_LINES = 1000


def _checked_budget(budget: object) -> int:
    if isinstance(budget, bool) or not isinstance(budget, int) \
            or budget < 1:
        raise PullRequestError(
            "budget_invalid",
            "The diff budget must be a positive whole number "
            "of patch lines.")
    return budget


@dataclass(frozen=True)
class LargePrFileView:
    entry: PrFileView
    folded: bool

    @property
    def path(self) -> str:
        return self.entry.path

    @property
    def patch_lines(self) -> int:
        return len(self.entry.file.lines)

    @property
    def additions(self) -> int:
        return self.entry.file.additions

    @property
    def deletions(self) -> int:
        return self.entry.file.deletions

    @property
    def fold_words(self) -> str:
        """Whether this file's patch is shown, in words —
        never a colour or an icon alone."""
        if self.folded:
            return (f"Folded — {self.patch_lines} patch lines "
                    f"not shown; open this file on its own "
                    f"to review it")
        return "Shown in full"


@dataclass(frozen=True)
class LargePrView:
    full_name: str
    number: int
    base_branch: str
    head_branch: str
    budget_lines: int
    files: tuple                 # of LargePrFileView, diff order

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def shown_files(self) -> int:
        return sum(1 for f in self.files if not f.folded)

    @property
    def folded_files(self) -> int:
        return self.total_files - self.shown_files

    @property
    def total_patch_lines(self) -> int:
        return sum(f.patch_lines for f in self.files)

    @property
    def shown_patch_lines(self) -> int:
        return sum(f.patch_lines for f in self.files if not f.folded)

    @property
    def additions(self) -> int:
        return sum(f.additions for f in self.files)

    @property
    def deletions(self) -> int:
        return sum(f.deletions for f in self.files)

    @property
    def is_large(self) -> bool:
        return self.folded_files > 0

    @property
    def summary_words(self) -> str:
        base = (f"{self.total_files} files changed · "
                f"{self.total_patch_lines} patch lines · "
                f"+{self.additions} −{self.deletions}")
        if not self.is_large:
            return base + " — every file shown in full"
        return (base + f" — {self.shown_files} files shown, "
                f"{self.folded_files} files folded beyond the "
                f"{self.budget_lines}-line diff budget; folded "
                f"files count in full in these totals and each "
                f"one can be opened on its own")


class PullRequestLargeStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._files = PullRequestFilesStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    def large_files_for(self, viewer: User | None, owner: object,
                        repo: object, number: object, *,
                        budget_lines: int = DEFAULT_BUDGET_LINES,
                        ignore_whitespace: bool = False) -> LargePrView:
        """The files view under the total diff budget:
        files unfold in diff order while the running
        patch-line total stays within the budget; the
        rest fold by whole file with their true counts
        still carried in every total."""
        budget = _checked_budget(budget_lines)
        view = self._files.files_for(
            viewer, owner, repo, number,
            ignore_whitespace=ignore_whitespace)
        spent = 0
        folding = False
        files = []
        for entry in view.files:
            lines = len(entry.file.lines)
            if not folding and spent + lines <= budget:
                spent += lines
                files.append(LargePrFileView(entry=entry, folded=False))
            else:
                folding = True
                files.append(LargePrFileView(entry=entry, folded=True))
        return LargePrView(
            full_name=view.full_name, number=view.number,
            base_branch=view.base_branch, head_branch=view.head_branch,
            budget_lines=budget, files=tuple(files))

    def file_for(self, viewer: User | None, owner: object,
                 repo: object, number: object, path: object, *,
                 ignore_whitespace: bool = False) -> LargePrFileView:
        """One named file, unfolded in full — the per-file
        review road. However far beyond the budget the
        file stood in the whole-PR view, here its whole
        patch is present. A path outside the current
        diff is refused `file_not_found` (S-145's word)
        and nothing is shown."""
        view = self._files.files_for(
            viewer, owner, repo, number,
            ignore_whitespace=ignore_whitespace)
        if not isinstance(path, str) or not path:
            raise PullRequestError(
                "file_not_found", "No such file in this pull request.")
        for entry in view.files:
            if entry.path == path:
                return LargePrFileView(entry=entry, folded=False)
        raise PullRequestError(
            "file_not_found",
            f"{path!r} is not one of the files this pull request "
            "changes.")


def _render_patch(entry: PrFileView) -> list:
    file = entry.file
    if file.is_binary:
        return ['<p class="binary">Binary file — no patch shown.</p>']
    parts = ['<table class="diff unified">']
    for line in file.lines:
        old = "" if line.old_number is None else str(line.old_number)
        new = "" if line.new_number is None else str(line.new_number)
        parts.append(
            f'<tr class="dl-{line.kind}"><td class="no">{old}</td>'
            f'<td class="no">{new}</td>'
            f"<td><code>{escape_html_text(line.text)}</code>"
            "</td></tr>")
    parts.append("</table>")
    return parts


def _file_label(entry: PrFileView) -> str:
    file = entry.file
    label = escape_html_text(file.path)
    if file.old_path and file.new_path and file.old_path != file.new_path:
        label = (f"{escape_html_text(file.old_path)} → "
                 f"{escape_html_text(file.new_path)}")
    return label


def render_large_files_page(view: LargePrView) -> str:
    """The large-PR files page: the honest totals in
    words first, then each file — shown files with
    their full patch, folded files named with their
    true counts and the per-file road said in words."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(view.full_name)} — pull request "
        f"#{view.number} — files — Samverk</title>",
        stylesheet_link_tag(),
        "</head>",
        "<body>",
        f"<h1>Files changed — {escape_html_text(view.full_name)} "
        f"#{view.number}</h1>",
        f'<p class="meta">{escape_html_text(view.head_branch)} into '
        f"{escape_html_text(view.base_branch)}</p>",
        f'<p class="large-summary">'
        f"{escape_html_text(view.summary_words)}</p>",
    ]
    if not view.files:
        parts.append(
            '<p class="empty">This pull request changes no files '
            "between its base and head branches as they stand now.</p>")
    for item in view.files:
        entry = item.entry
        file = entry.file
        parts.append('<details class="file-diff">')
        parts.append(
            f"<summary>{_file_label(entry)} +{file.additions} "
            f"−{file.deletions} · "
            f"{escape_html_text(entry.state_words)} · "
            f"{escape_html_text(item.fold_words)}</summary>")
        if item.folded:
            parts.append(
                '<p class="diff-folded">This file is folded: '
                f"{item.patch_lines} patch lines, +{file.additions} "
                f"−{file.deletions}, are not shown here. The counts "
                "are the file's true counts. Open this file on its "
                "own to review its full patch.</p>")
        else:
            parts.extend(_render_patch(entry))
        parts.append("</details>")
    parts.append("</body></html>")
    return "\n".join(parts)


def render_large_file_page(view: LargePrView,
                           item: LargePrFileView) -> str:
    """One file's own page: its full patch, its true
    counts, and the reviewer's viewed state in words —
    the page a reviewer lands on from a folded file."""
    entry = item.entry
    file = entry.file
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(view.full_name)} — pull request "
        f"#{view.number} — {escape_html_text(item.path)} — "
        "Samverk</title>",
        stylesheet_link_tag(),
        "</head>",
        "<body>",
        f"<h1>{_file_label(entry)} — "
        f"{escape_html_text(view.full_name)} #{view.number}</h1>",
        f'<p class="meta">{item.patch_lines} patch lines · '
        f"+{file.additions} −{file.deletions} · "
        f"{escape_html_text(entry.state_words)} · "
        f"{escape_html_text(item.fold_words)}</p>",
    ]
    parts.extend(_render_patch(entry))
    parts.append("</body></html>")
    return "\n".join(parts)
