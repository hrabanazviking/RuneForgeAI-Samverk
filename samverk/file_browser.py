"""File browser (S-098).

Tree navigation at any ref: a directory listing whose every
entry carries the last commit that touched it, with a
breadcrumb back to the root.

- **Permission and refs are S-097's shared law** — the
  browser resolves through the same helpers the home uses
  (`can_read`'s uniform not-found, refs resolved before any
  object is read, repo paths validated component by
  component so `..` can never climb out of the tree).
- **Last-commit-per-entry is computed, never stored stale.**
  One `git log --name-only` walk from the viewed commit,
  newest first, assigns each entry the first commit that
  touched it (for a directory entry, a touch of anything
  under it). The walk is the data S-072's graph cache
  exists to make cheap at repository scale; this slice
  takes the honest walk itself and names its limit: on
  very long histories the walk is the cost, and the
  per-directory answers are exact for the ref viewed —
  never a cached row served for a different ref. Rename
  detection is off: a renamed file's history follows the
  new path only (git's own default for path walks).
- **Directories sort before files**, each group by name —
  the order every forge visitor already reads.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .accounts import User
from .escaping import escape_html_attr, escape_html_text
from .objects import ObjectReader
from .permissions import can_read
from .proc import run_git_in
from .repo_home import (RepoHomeError, resolve_commit, tree_at,
                        validate_repo_path)
from .repositories import RepositoryStore


class BrowseError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class LastCommit:
    oid: str
    author: str
    timestamp: int
    subject: str


@dataclass(frozen=True)
class BrowseEntry:
    name: str
    type: str               # 'tree' | 'blob' | 'commit'
    oid: str
    mode: str
    last_commit: LastCommit | None


@dataclass(frozen=True)
class TreeView:
    full_name: str
    owner: str
    name: str
    current_ref: str
    commit_oid: str
    path: str                          # "" at the root
    breadcrumb: tuple[tuple[str, str], ...]   # (label, path)
    entries: tuple[BrowseEntry, ...]


def _wrap(fn):
    try:
        return fn()
    except RepoHomeError as exc:
        raise BrowseError(exc.reason, str(exc)) from None


class FileBrowser:
    def __init__(self, repositories: RepositoryStore):
        self._repos = repositories

    def browse(self, viewer: User | None, owner: object, repo: object,
               ref: object = None, path: object = None) -> TreeView:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise BrowseError("repo_not_found", "No such repository.")
        repo_path = self._repos.path_for(current.owner, current.name)
        requested = current.default_branch if ref is None else ref
        parts = _wrap(lambda: validate_repo_path(path))
        ref_name, commit_oid = _wrap(
            lambda: resolve_commit(repo_path, requested))
        reader = ObjectReader(repo_path)
        raw_entries = _wrap(lambda: tree_at(reader, commit_oid, parts))
        lasts = self._last_commits(repo_path, commit_oid, parts,
                                   [e.name for e in raw_entries])
        entries = tuple(
            BrowseEntry(name=e.name, type=e.type, oid=e.oid, mode=e.mode,
                        last_commit=lasts.get(e.name))
            for e in sorted(raw_entries,
                            key=lambda e: (e.type != "tree", e.name.lower())))
        breadcrumb = tuple(
            (part, "/".join(parts[:i + 1]))
            for i, part in enumerate(parts))
        return TreeView(
            full_name=current.full_name, owner=current.owner,
            name=current.name, current_ref=ref_name,
            commit_oid=commit_oid, path="/".join(parts),
            breadcrumb=breadcrumb, entries=entries)

    # -- last-commit walk ---------------------------------------------
    @staticmethod
    def _last_commits(repo_path: Path, commit_oid: str,
                      parts: tuple[str, ...],
                      names: list[str]) -> dict[str, LastCommit]:
        if not names:
            return {}
        prefix = "/".join(parts)
        # The record marker leads the format: git prints a
        # commit's file names AFTER its log line, so a trailing
        # marker would attach each commit's names to the next
        # commit's header (a battery-found parsing bug, fixed
        # in-slice).
        args = ["log", "--format=%x1e%H%x00%an <%ae>%x00%at%x00%s",
                "--name-only", commit_oid]
        if prefix:
            args += ["--", prefix]
        result = run_git_in(repo_path, args, timeout=60.0)
        if result.returncode != 0:
            return {}
        wanted = set(names)
        found: dict[str, LastCommit] = {}
        records = result.stdout.decode(
            "utf-8", "surrogateescape").split("\x1e")
        for record in records:
            if len(found) == len(wanted):
                break
            record = record.strip("\n")
            if not record:
                continue
            header, _, names_block = record.partition("\n")
            fields = header.split("\x00")
            if len(fields) != 4:
                continue
            oid, author, ts, subject = fields
            try:
                stamp = int(ts)
            except ValueError:
                continue
            commit = LastCommit(oid=oid, author=author,
                                timestamp=stamp, subject=subject)
            for touched in names_block.splitlines():
                touched = touched.strip()
                if not touched:
                    continue
                if prefix:
                    if not touched.startswith(prefix + "/"):
                        continue
                    relative = touched[len(prefix) + 1:]
                else:
                    relative = touched
                entry_name = relative.split("/", 1)[0]
                if entry_name in wanted and entry_name not in found:
                    found[entry_name] = commit
        return found


def _stamp(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def render_tree_page(view: TreeView) -> str:
    """The tree page: breadcrumb, then one row per entry with
    its last commit. All user-controlled values pass S-010."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(view.full_name)} — "
        f"{escape_html_text(view.path or 'root')} — Samverk</title></head>",
        "<body>",
        f"<h1>{escape_html_text(view.full_name)}</h1>",
        '<nav class="breadcrumb" aria-label="Breadcrumb">',
        f'<a href="/{escape_html_attr(view.owner)}/'
        f'{escape_html_attr(view.name)}/tree/'
        f'{escape_html_attr(view.current_ref)}">'
        f"{escape_html_text(view.name)}</a>",
    ]
    for label, path in view.breadcrumb:
        href = (f"/{view.owner}/{view.name}/tree/{view.current_ref}/{path}")
        parts.append(
            f' / <a href="{escape_html_attr(href)}">'
            f"{escape_html_text(label)}</a>")
    parts.append("</nav>")
    if not view.entries:
        parts.append(
            '<p class="empty">This directory is empty.</p>')
    parts.append('<table class="tree"><thead><tr><th>Name</th>'
                 "<th>Last commit</th><th>Author</th><th>Date</th>"
                 "</tr></thead><tbody>")
    base = (f"/{view.owner}/{view.name}")
    here = f"/{view.path}" if view.path else ""
    for entry in view.entries:
        if entry.type == "tree":
            href = f"{base}/tree/{view.current_ref}{here}/{entry.name}"
        else:
            href = f"{base}/blob/{view.current_ref}{here}/{entry.name}"
        last = entry.last_commit
        subject = escape_html_text(last.subject) if last else "—"
        author = escape_html_text(last.author) if last else "—"
        date = _stamp(last.timestamp) if last else "—"
        parts.append(
            f'<tr><td><a href="{escape_html_attr(href)}">'
            f"{escape_html_text(entry.name)}</a></td>"
            f"<td>{subject}</td><td>{author}</td><td>{date}</td></tr>")
    parts.append("</tbody></table>")
    parts.append("</body></html>")
    return "\n".join(parts)
