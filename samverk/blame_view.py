"""Blame view (S-101).

Per-line commit attribution for one file at one ref, via
``git blame --line-porcelain``, paginated for long files.

- **Pagination is by line.** The caller asks for one page
  (default 100 lines, clamped 1..500); the view always
  reports the file's true total line count, the page count,
  and whether a next/previous page exists, so a long file
  is walked honestly — never silently truncated to the
  first page and never loaded into a page whole.
- **Attribution is git's, stated plainly.** Each line
  carries the commit that last touched it, that commit's
  author, author time, and summary, the line's number in
  its original commit (`original_number`), and the name
  the line lived under in that commit (`filename`).
- **Honest about rename limits.** This view runs blame
  without copy/move tracing (no ``-C``/``-M``): lines
  copied or moved *in from other files* are attributed to
  the commit that brought them into this file, not to
  their earlier home. The per-line `filename` is shown
  precisely so a rename in the file's own past is visible
  rather than hidden. The page states this limit in words.
- **Same refusals as the blob view (S-099).** Binary
  content is refused by name (`binary_file`); an LFS
  pointer is reported as a pointer, never blamed as if it
  were source; a file past the view limit (1 MB) answers
  `view_too_large`, pointing at S-100's raw/download.
- Permission and path law are S-097/S-098's shared helpers.
"""

from __future__ import annotations

from dataclasses import dataclass

from .accounts import User
from .blob_view import VIEW_MAX_BYTES
from .escaping import escape_html_attr, escape_html_text
from .lfs_store import LFSError, parse_pointer
from .objects import ObjectReader
from .permissions import can_read
from .proc import run_git_in
from .repo_home import RepoHomeError, blob_at, resolve_commit, validate_repo_path
from .repositories import RepositoryStore

DEFAULT_PER_PAGE = 100
MAX_PER_PAGE = 500

RENAME_LIMIT_NOTE = (
    "Attribution follows this file at this path, without "
    "copy/move tracing: a line copied or moved in from "
    "another file is credited to the commit that brought "
    "it here. The name shown beside a line is the name it "
    "lived under in its own commit, so a rename in this "
    "file's past stays visible."
)


class BlameError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class BlameLine:
    number: int             # line number in the viewed file
    original_number: int    # line number in its own commit
    commit_oid: str
    author: str
    author_time: int        # unix seconds, 0 when git omits it
    summary: str
    filename: str           # the name this line lived under
    text: str
    is_boundary: bool = False


@dataclass(frozen=True)
class BlameView:
    full_name: str
    current_ref: str
    commit_oid: str
    path: str
    total_lines: int
    page: int
    per_page: int
    total_pages: int
    lines: tuple[BlameLine, ...]
    is_lfs_pointer: bool = False
    lfs_oid: str | None = None
    lfs_size: int | None = None
    rename_note: str = RENAME_LIMIT_NOTE

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


def _parse_line_porcelain(output: str) -> list[BlameLine]:
    """Parse `git blame --line-porcelain` output.

    Each block is a header (`<oid> <orig> <final> <group>`),
    key/value lines, and one content line starting with a
    tab. Malformed output raises `object_unreadable` rather
    than guessing at attribution."""
    lines: list[BlameLine] = []
    fields: dict[str, str] = {}
    header: tuple[str, int, int] | None = None
    for raw in output.split("\n"):
        if raw.startswith("\t"):
            if header is None:
                raise BlameError("object_unreadable",
                                 "Blame output could not be read.")
            oid, original, final = header
            lines.append(BlameLine(
                number=final, original_number=original, commit_oid=oid,
                author=fields.get("author", ""),
                author_time=int(fields.get("author-time", "0") or 0),
                summary=fields.get("summary", ""),
                filename=fields.get("filename", ""),
                text=raw[1:], is_boundary="boundary" in fields))
            fields = {}
            header = None
            continue
        parts = raw.split(" ", 3)
        if len(parts) == 4 and len(parts[0]) == 40 and parts[1].isdigit() \
                and parts[2].isdigit():
            header = (parts[0], int(parts[1]), int(parts[2]))
            fields = {}
            continue
        if header is not None:
            key, _, value = raw.partition(" ")
            fields[key] = value
    if header is not None:
        raise BlameError("object_unreadable",
                         "Blame output could not be read.")
    lines.sort(key=lambda line: line.number)
    return lines


class BlameViewer:
    def __init__(self, repositories: RepositoryStore):
        self._repos = repositories

    def blame(self, viewer: User | None, owner: object, repo: object,
              ref: object = None, path: object = None,
              page: object = 1, per_page: object = DEFAULT_PER_PAGE
              ) -> BlameView:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise BlameError("repo_not_found", "No such repository.")
        try:
            page_no = int(page)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            page_no = 1
        try:
            page_size = int(per_page)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            page_size = DEFAULT_PER_PAGE
        page_no = max(1, page_no)
        page_size = min(MAX_PER_PAGE, max(1, page_size))
        repo_path = self._repos.path_for(current.owner, current.name)
        requested = current.default_branch if ref is None else ref
        try:
            parts = validate_repo_path(path)
            if not parts:
                raise RepoHomeError("path_invalid", "A file path is required.")
            ref_name, commit_oid = resolve_commit(repo_path, requested)
            reader = ObjectReader(repo_path)
            entry = blob_at(reader, commit_oid, parts)
        except RepoHomeError as exc:
            raise BlameError(exc.reason, str(exc)) from None
        joined = "/".join(parts)
        size_result = run_git_in(repo_path, ["cat-file", "-s", entry.oid],
                                 timeout=15.0)
        try:
            raw_size = int(size_result.stdout.decode().strip())
        except ValueError:
            raise BlameError("object_unreadable",
                             "That file cannot be read.") from None
        if raw_size > VIEW_MAX_BYTES:
            raise BlameError(
                "view_too_large",
                f"This file is {raw_size} bytes; the blame view limit is "
                f"{VIEW_MAX_BYTES} bytes. Use the raw/download view.")
        data = reader.read_blob(entry.oid)
        try:
            pointer = parse_pointer(data)
        except LFSError:
            pointer = None
        if pointer is not None:
            return BlameView(
                full_name=current.full_name, current_ref=ref_name,
                commit_oid=commit_oid, path=joined, total_lines=0,
                page=1, per_page=page_size, total_pages=0, lines=(),
                is_lfs_pointer=True, lfs_oid=pointer.oid,
                lfs_size=pointer.size)
        if b"\x00" in data[:8192]:
            raise BlameError(
                "binary_file",
                "This file is binary; blame shows text lines. "
                "Use the raw/download view for its bytes.")
        result = run_git_in(
            repo_path,
            ["blame", "--line-porcelain", commit_oid, "--", joined],
            timeout=30.0)
        if result.returncode != 0:
            raise BlameError("object_unreadable",
                             "That file cannot be blamed.")
        all_lines = _parse_line_porcelain(
            result.stdout.decode("utf-8", "replace"))
        total = len(all_lines)
        total_pages = (total + page_size - 1) // page_size if total else 0
        start = (page_no - 1) * page_size
        page_lines = tuple(all_lines[start:start + page_size])
        return BlameView(
            full_name=current.full_name, current_ref=ref_name,
            commit_oid=commit_oid, path=joined, total_lines=total,
            page=page_no, per_page=page_size, total_pages=total_pages,
            lines=page_lines)


def render_blame_page(view: BlameView) -> str:
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(view.full_name)} — blame "
        f"{escape_html_text(view.path)} — Samverk</title></head>",
        "<body>",
        f"<h1>Blame — {escape_html_text(view.path)}</h1>",
        f'<p class="meta">{escape_html_text(view.full_name)} · '
        f"{view.total_lines} lines · "
        f"at {escape_html_text(view.commit_oid[:12])}</p>",
        f'<p class="rename-note">{escape_html_text(view.rename_note)}</p>',
    ]
    if view.is_lfs_pointer:
        parts.append(
            '<p class="lfs">This file is stored with Git LFS. '
            f"Its content is {view.lfs_size} bytes "
            f"(object {escape_html_text(view.lfs_oid or '')}); "
            "there are no source lines to blame.</p>")
    elif not view.lines:
        parts.append('<p class="empty">No lines on this page.</p>')
    else:
        parts.append('<div class="blame">')
        for line in view.lines:
            parts.append(
                f'<div class="line" id="L{line.number}">'
                f'<a class="line-no" href="#L{line.number}">'
                f"{line.number}</a> "
                f'<span class="commit">'
                f"{escape_html_text(line.commit_oid[:12])}</span> "
                f'<span class="author">'
                f"{escape_html_text(line.author)}</span> "
                f'<span class="summary">'
                f"{escape_html_text(line.summary)}</span> "
                f'<span class="filename">'
                f"{escape_html_text(line.filename)}</span> "
                f"<code>{escape_html_text(line.text) if line.text else ' '}"
                "</code></div>")
        parts.append("</div>")
    if view.total_pages > 1:
        nav = ['<nav class="pagination">']
        if view.has_previous:
            nav.append(
                f'<a href="?page={view.page - 1}">Previous</a> ')
        nav.append(
            f"Page {view.page} of {view.total_pages}")
        if view.has_next:
            nav.append(
                f' <a href="?page={view.page + 1}">Next</a>')
        nav.append("</nav>")
        parts.append("".join(nav))
    parts.append("</body></html>")
    return "\n".join(parts)
