"""Pull request files view (S-145).

The files view is where a reviewer actually reads the
change: the shared diff engine (S-104) over the pull
request's current base and head, with one piece of
personal progress — which files this reviewer has
already viewed, in words.

- **The diff is S-104's engine, unchanged.** A
  same-repository pull request compares its base and
  head branches as they stand today through S-105's
  compare seam, so the files view shows the same
  numbers and the same patch the compare page shows.
  A cross-fork pull request (S-142) compares through
  that slice's cross-repository compare — the base
  branch's current tip read into the fork under its
  scratch ref, deleted in every outcome. The
  whitespace toggle is git's own (`-w`, through the
  engine), never a renderer hiding lines after
  counting them.
- **Viewed state is per reviewer, per file.** Marking
  a file viewed records, for that reviewer alone, the
  file's path and a SHA-256 hash of the patch they
  actually saw (migration 50). Another reviewer's
  marks are theirs; the author's marks do not vouch
  for anyone else. Unmarking removes the record.
  There is no audit event of its own — a personal
  reading preference, the S-136 pattern: the taxonomy
  stands at 95 events.
- **A changed file does not stay viewed.** When a new
  push changes a file's patch, its hash changes, so
  the stored mark no longer matches: the file reads
  as *changed since you viewed it* — not viewed, and
  the difference is said in words, never a silent
  unchecking and never a stale checkmark claiming a
  review that did not happen. A push that leaves a
  file's patch untouched leaves its mark standing.
- **Progress is said in words.** The view counts
  viewed files against the true file total
  (`viewed_count`, `progress_words` — "2 of 3 files
  viewed"), never a colour or a bar alone. An
  anonymous reader of a public repository sees the
  files themselves and no personal state: every file
  not viewed, because there is no reviewer to hold a
  mark for.
- **Permissions ride the pull request's.** Every read
  and mark goes through S-141's pull-request seam: a
  stranger to a private repository gets the uniform
  `pull_request_not_found` for the files view and for
  marking alike, and marking a file that is not in
  the current diff is refused `file_not_found` and
  stores nothing.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .compare_view import CompareService
from .diff_engine import FOLD_LIMIT, DiffFile, DiffSet, range_diff
from .escaping import escape_html_text
from .issues import IssueStore
from .print_export import stylesheet_link_tag
from .pull_request_forks import ForkPullRequestStore
from .pull_requests import PullRequestError, PullRequestStore
from .repositories import RepositoryStore

__all__ = [
    "PrFileView", "PrFilesView", "PullRequestFilesStore",
    "patch_hash", "render_files_page",
]


def patch_hash(file: DiffFile) -> str:
    """The fingerprint of one file's patch as shown:
    paths, binary fact, and every numbered line. Any
    change to what the reviewer would read changes it."""
    digest = hashlib.sha256()
    digest.update((file.old_path or "").encode("utf-8"))
    digest.update(b"\x00")
    digest.update((file.new_path or "").encode("utf-8"))
    digest.update(b"\x00binary\x00" if file.is_binary else b"\x00text\x00")
    for line in file.lines:
        digest.update(line.kind.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(line.old_number or "").encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(line.new_number or "").encode("utf-8"))
        digest.update(b"\x00")
        digest.update(line.text.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


@dataclass(frozen=True)
class PrFileView:
    file: DiffFile
    is_viewed: bool
    changed_since_viewed: bool   # a mark exists, its patch moved
    viewed_at: int               # 0 when never marked

    @property
    def path(self) -> str:
        return self.file.path

    @property
    def state_words(self) -> str:
        """The viewed state in words — never a colour
        or a checkbox alone."""
        if self.is_viewed:
            return "Viewed"
        if self.changed_since_viewed:
            return "Changed since you viewed it — not viewed"
        return "Not viewed"


@dataclass(frozen=True)
class PrFilesView:
    full_name: str
    number: int
    base_branch: str
    head_branch: str
    base_oid: str
    head_oid: str
    diff: DiffSet
    files: tuple                 # of PrFileView, in diff order

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def viewed_count(self) -> int:
        return sum(1 for f in self.files if f.is_viewed)

    @property
    def additions(self) -> int:
        return self.diff.additions

    @property
    def deletions(self) -> int:
        return self.diff.deletions

    @property
    def progress_words(self) -> str:
        return f"{self.viewed_count} of {self.total_files} files viewed"


class PullRequestFilesStore:
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
        self._compare = CompareService(repositories)
        self._forks = ForkPullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    # -- internals ---------------------------------------------------
    def _diff_for(self, viewer, owner, repo, pr, *,
                  ignore_whitespace: bool = False) -> tuple:
        """The current diff for this pull request, plus
        its base/head oids — cross-fork through S-142's
        compare when a fork record exists, otherwise
        S-105's same-repository compare. The whitespace
        toggle rides the engine in both cases: S-105's
        compare carries it directly, and a cross-fork
        diff is re-run in the head repository (whose
        object store the fork compare's fetch has just
        stocked with the base commit) with `-w`."""
        fork = self._forks.get_cross_fork(viewer, owner, repo, pr.number)
        if fork is not None:
            base = self._repos.get_by_id(pr.repo_id)
            head_row = self._conn.execute(
                "SELECT head_repo_id FROM pull_request_forks"
                " WHERE pull_request_id = ?", (pr.id,)).fetchone()
            head = self._repos.get_by_id(int(head_row["head_repo_id"]))
            assert base is not None and head is not None
            view = self._forks._cross_compare(
                base, head, pr.base_branch, pr.head_branch)
            if not ignore_whitespace:
                return view.diff, view.base_oid, view.head_oid
            head_path = self._repos.path_for(head.owner, head.name)
            diff = range_diff(head_path, view.base_oid, view.head_oid,
                              ignore_whitespace=True)
            return diff, view.base_oid, view.head_oid
        view = self._compare.compare(
            viewer, owner, repo, pr.base_branch, pr.head_branch,
            ignore_whitespace=ignore_whitespace)
        return view.diff, view.base_oid, view.head_oid

    def _view(self, viewer, owner, repo, number, *,
              ignore_whitespace: bool = False) -> PrFilesView:
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        diff, base_oid, head_oid = self._diff_for(
            viewer, owner, repo, pr, ignore_whitespace=ignore_whitespace)
        marks: dict[str, sqlite3.Row] = {}
        if viewer is not None:
            for row in self._conn.execute(
                    "SELECT * FROM pull_request_file_views"
                    " WHERE pull_request_id = ? AND user_id = ?",
                    (pr.id, viewer.id)).fetchall():
                marks[row["file_path"]] = row
        files = []
        for file in diff.files:
            row = marks.get(file.path)
            if row is None:
                files.append(PrFileView(
                    file=file, is_viewed=False,
                    changed_since_viewed=False, viewed_at=0))
            else:
                matches = row["patch_hash"] == patch_hash(file)
                files.append(PrFileView(
                    file=file, is_viewed=matches,
                    changed_since_viewed=not matches,
                    viewed_at=int(row["viewed_at"])))
        return PrFilesView(
            full_name=current.full_name, number=pr.number,
            base_branch=pr.base_branch, head_branch=pr.head_branch,
            base_oid=base_oid, head_oid=head_oid, diff=diff,
            files=tuple(files))

    def _file_in_diff(self, view: PrFilesView, path: object) -> PrFileView:
        if not isinstance(path, str) or not path:
            raise PullRequestError(
                "file_not_found", "No such file in this pull request.")
        for entry in view.files:
            if entry.path == path:
                return entry
        raise PullRequestError(
            "file_not_found",
            f"{path!r} is not one of the files this pull request "
            "changes.")

    # -- reads ---------------------------------------------------------
    def files_for(self, viewer: User | None, owner: object, repo: object,
                  number: object, *,
                  ignore_whitespace: bool = False) -> PrFilesView:
        """The files view: S-104's diff over the pull
        request's current branches, with the viewer's
        own per-file viewed state laid over it."""
        return self._view(viewer, owner, repo, number,
                          ignore_whitespace=ignore_whitespace)

    # -- viewed state ----------------------------------------------------
    def mark_viewed(self, actor: User, owner: object, repo: object,
                    number: object, path: object) -> PrFileView:
        """Mark one file viewed for this reviewer, at
        the patch as it stands now. Re-marking a changed
        file records the new patch — that is how a
        reviewer vouches for the new version."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        view = self._view(actor, owner, repo, number)
        entry = self._file_in_diff(view, path)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO pull_request_file_views"
                " (pull_request_id, user_id, file_path, head_oid,"
                " patch_hash, viewed_at) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (pull_request_id, user_id, file_path)"
                " DO UPDATE SET head_oid = excluded.head_oid,"
                " patch_hash = excluded.patch_hash,"
                " viewed_at = excluded.viewed_at",
                (pr.id, actor.id, entry.path, view.head_oid,
                 patch_hash(entry.file), now))
        return PrFileView(file=entry.file, is_viewed=True,
                          changed_since_viewed=False, viewed_at=now)

    def mark_unviewed(self, actor: User, owner: object, repo: object,
                      number: object, path: object) -> PrFileView:
        """Remove this reviewer's viewed mark for one
        file. A file with no mark is a quiet no-op —
        it is already not viewed."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        view = self._view(actor, owner, repo, number)
        entry = self._file_in_diff(view, path)
        with self._conn:
            self._conn.execute(
                "DELETE FROM pull_request_file_views"
                " WHERE pull_request_id = ? AND user_id = ?"
                " AND file_path = ?",
                (pr.id, actor.id, entry.path))
        return PrFileView(file=entry.file, is_viewed=False,
                          changed_since_viewed=False, viewed_at=0)


def render_files_page(view: PrFilesView, *,
                      fold_limit: int = FOLD_LIMIT) -> str:
    """The files page: the progress said in words
    first, then each file with its counts and its
    viewed state in words beside a patch rendered
    exactly as S-104 renders it (folding honest, binary
    files named, every line through S-010's seam)."""
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
        f"{escape_html_text(view.base_branch)} · "
        f"{view.total_files} files changed · "
        f"+{view.additions} −{view.deletions}</p>",
        f'<p class="viewed-progress">'
        f"{escape_html_text(view.progress_words)}</p>",
    ]
    if not view.files:
        parts.append(
            '<p class="empty">This pull request changes no files '
            "between its base and head branches as they stand now.</p>")
    for entry in view.files:
        file = entry.file
        parts.append('<details class="file-diff">')
        label = escape_html_text(file.path)
        if file.old_path and file.new_path and file.old_path != file.new_path:
            label = (f"{escape_html_text(file.old_path)} → "
                     f"{escape_html_text(file.new_path)}")
        parts.append(
            f"<summary>{label} +{file.additions} −{file.deletions} · "
            f"{escape_html_text(entry.state_words)}</summary>")
        if file.is_binary:
            parts.append(
                '<p class="binary">Binary file — no patch shown.</p>')
        elif len(file.lines) > fold_limit:
            parts.append(
                '<p class="diff-folded">This change is folded: '
                f"{len(file.lines)} patch lines, +{file.additions} "
                f"−{file.deletions}, are not shown. The counts are "
                "the file's true counts.</p>")
        else:
            parts.append('<table class="diff unified">')
            for line in file.lines:
                old = "" if line.old_number is None else str(line.old_number)
                new = "" if line.new_number is None else str(line.new_number)
                parts.append(
                    f'<tr class="dl-{line.kind}"><td class="no">{old}</td>'
                    f'<td class="no">{new}</td>'
                    f"<td><code>{escape_html_text(line.text)}</code>"
                    "</td></tr>")
            parts.append("</table>")
        parts.append("</details>")
    parts.append("</body></html>")
    return "\n".join(parts)
