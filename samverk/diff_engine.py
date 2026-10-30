"""Diff engine (S-104).

The one patch parser and renderer shared by commit views
(S-103's successor surface) and pull requests (Part VII):
unified and split rendering, a whitespace toggle, and
large-diff folding with honest counts.

- **Structure, not text soup.** `parse_patch` walks hunk
  headers (`@@ -a,b +c,d @@`) and numbers every line on
  both sides, so renderers never guess which column a
  line belongs to. Additions/deletions are counted from
  the hunk lines themselves — the same lines the reader
  sees — so the numbers on the page are the numbers in
  the patch.
- **Whitespace toggle is git's own.** The compute seams
  (`commit_diff`, `range_diff`) re-run git with `-w` when
  the toggle is on: whitespace-only changes disappear
  because git says they do, not because a renderer hid
  them after counting them.
- **Folding is honest.** A file whose patch passes the
  fold limit renders as a folded notice naming its true
  patch-line, addition, and deletion counts — never a
  silent truncation that looks like a small change. The
  parsed data is complete regardless; folding is a
  rendering decision, reversible by raising the limit.
- **Binary changes are named**, with no patch lines, as
  in S-103. Every rendered line passes S-010's seam.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .escaping import escape_html_text
from .proc import run_git_in

FOLD_LIMIT = 400

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$")


class DiffError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class DiffLine:
    kind: str               # context | add | del | meta
    text: str               # without the leading + / - / space
    old_number: int | None
    new_number: int | None


@dataclass(frozen=True)
class DiffFile:
    old_path: str | None
    new_path: str | None
    is_binary: bool
    additions: int
    deletions: int
    lines: tuple[DiffLine, ...]

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""


@dataclass(frozen=True)
class DiffSet:
    files: tuple[DiffFile, ...]

    @property
    def additions(self) -> int:
        return sum(f.additions for f in self.files)

    @property
    def deletions(self) -> int:
        return sum(f.deletions for f in self.files)


def parse_patch(text: str) -> DiffSet:
    chunks: list[list[str]] = []
    current: list[str] | None = None
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            if current is not None:
                chunks.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        chunks.append(current)
    files: list[DiffFile] = []
    for chunk in chunks:
        old_path: str | None = None
        new_path: str | None = None
        header = chunk[0] if chunk else ""
        if header.startswith("diff --git a/"):
            rest = header[len("diff --git a/"):]
            left, sep, right = rest.rpartition(" b/")
            if sep:
                old_path, new_path = left, right
        is_binary = False
        lines: list[DiffLine] = []
        additions = deletions = 0
        old_no: int | None = None
        new_no: int | None = None
        in_hunk = False
        for line in chunk[1:]:
            if line == "":
                # Split artifact of the trailing newline; a
                # real patch line is never empty (an empty
                # context line is a single space).
                continue
            if line.startswith("--- "):
                value = line[4:]
                old_path = None if value == "/dev/null" else value[2:] \
                    if value.startswith("a/") else value
                continue
            if line.startswith("+++ "):
                value = line[4:]
                new_path = None if value == "/dev/null" else value[2:] \
                    if value.startswith("b/") else value
                continue
            if line.startswith("rename from "):
                old_path = line[len("rename from "):]; continue
            if line.startswith("rename to "):
                new_path = line[len("rename to "):]; continue
            if line.startswith("copy from "):
                old_path = line[len("copy from "):]; continue
            if line.startswith("copy to "):
                new_path = line[len("copy to "):]; continue
            if line.startswith("Binary files ") or line == "GIT binary patch":
                is_binary = True
                continue
            hunk = _HUNK_RE.match(line)
            if hunk:
                old_no, new_no = int(hunk.group(1)), int(hunk.group(2))
                in_hunk = True
                lines.append(DiffLine("meta", line, None, None))
                continue
            if not in_hunk:
                continue
            if line.startswith("\\"):
                lines.append(DiffLine("meta", line, None, None))
                continue
            marker, body = (line[0], line[1:]) if line else (" ", "")
            if marker == "+":
                lines.append(DiffLine("add", body, None, new_no))
                if new_no is not None:
                    new_no += 1
                additions += 1
            elif marker == "-":
                lines.append(DiffLine("del", body, old_no, None))
                if old_no is not None:
                    old_no += 1
                deletions += 1
            else:
                lines.append(DiffLine("context", body, old_no, new_no))
                if old_no is not None:
                    old_no += 1
                if new_no is not None:
                    new_no += 1
        files.append(DiffFile(
            old_path=old_path, new_path=new_path, is_binary=is_binary,
            additions=additions, deletions=deletions, lines=tuple(lines)))
    return DiffSet(files=tuple(files))


def _run_patch(repo_path: Path, args: list[str],
               ignore_whitespace: bool) -> DiffSet:
    if ignore_whitespace:
        args = [args[0], "-w", *args[1:]]
    result = run_git_in(repo_path, args, timeout=30.0)
    if result.returncode != 0:
        raise DiffError("object_unreadable", "That diff cannot be read.")
    return parse_patch(result.stdout.decode("utf-8", "replace"))


_OID_RE = re.compile(r"^[0-9a-f]{40}$")


def _oid(value: object, reason: str) -> str:
    text = str(value).lower()
    if not _OID_RE.match(text):
        raise DiffError(reason, f"Not a commit id: {value!r}")
    return text


def commit_diff(repo_path: Path, commit_oid: object, *,
                ignore_whitespace: bool = False) -> DiffSet:
    """One commit against its first parent (or the empty
    tree for a root). Merge commits diff against their
    first parent — the combined-diff reading is named
    future work, not silently substituted here."""
    oid = _oid(commit_oid, "commit_invalid")
    parent = run_git_in(repo_path, ["rev-parse", f"{oid}^"], timeout=15.0)
    if parent.returncode != 0:
        # A root commit: diff against the empty tree.
        return _run_patch(
            repo_path,
            ["diff-tree", "-p", "--root", "--find-renames", "-r", oid],
            ignore_whitespace)
    return range_diff(repo_path, parent.stdout.decode().strip(), oid,
                      ignore_whitespace=ignore_whitespace)


def range_diff(repo_path: Path, base_oid: object, head_oid: object, *,
               ignore_whitespace: bool = False) -> DiffSet:
    base = _oid(base_oid, "commit_invalid")
    head = _oid(head_oid, "commit_invalid")
    return _run_patch(
        repo_path, ["diff", "--find-renames", base, head],
        ignore_whitespace)


def _folded_notice(file: DiffFile) -> str:
    return (
        '<p class="diff-folded">This change is folded: '
        f"{len(file.lines)} patch lines, +{file.additions} "
        f"−{file.deletions}, are not shown. The counts are "
        "the file's true counts.</p>")


def _file_header(file: DiffFile) -> str:
    label = escape_html_text(file.path)
    if file.old_path and file.new_path and file.old_path != file.new_path:
        label = (f"{escape_html_text(file.old_path)} → "
                 f"{escape_html_text(file.new_path)}")
    return (f"<summary>{label} +{file.additions} "
            f"−{file.deletions}</summary>")


def render_unified(diffset: DiffSet, *, fold_limit: int = FOLD_LIMIT) -> str:
    parts: list[str] = []
    for file in diffset.files:
        parts.append('<details class="file-diff">')
        parts.append(_file_header(file))
        if file.is_binary:
            parts.append('<p class="binary">Binary file — no patch shown.</p>')
        elif len(file.lines) > fold_limit:
            parts.append(_folded_notice(file))
        else:
            parts.append('<table class="diff unified">')
            for line in file.lines:
                old = "" if line.old_number is None else str(line.old_number)
                new = "" if line.new_number is None else str(line.new_number)
                parts.append(
                    f'<tr class="dl-{line.kind}"><td class="no">{old}</td>'
                    f'<td class="no">{new}</td>'
                    f"<td><code>{escape_html_text(line.text)}</code></td></tr>")
            parts.append("</table>")
        parts.append("</details>")
    return "\n".join(parts)


def _split_rows(file: DiffFile) -> list[tuple[DiffLine | None, DiffLine | None]]:
    rows: list[tuple[DiffLine | None, DiffLine | None]] = []
    pending_del: list[DiffLine] = []
    pending_add: list[DiffLine] = []

    def flush():
        for i in range(max(len(pending_del), len(pending_add))):
            rows.append((
                pending_del[i] if i < len(pending_del) else None,
                pending_add[i] if i < len(pending_add) else None))
        pending_del.clear(); pending_add.clear()

    for line in file.lines:
        if line.kind == "del":
            pending_del.append(line)
        elif line.kind == "add":
            pending_add.append(line)
        else:
            flush()
            rows.append((line, line))
    flush()
    return rows


def render_split(diffset: DiffSet, *, fold_limit: int = FOLD_LIMIT) -> str:
    parts: list[str] = []
    for file in diffset.files:
        parts.append('<details class="file-diff">')
        parts.append(_file_header(file))
        if file.is_binary:
            parts.append('<p class="binary">Binary file — no patch shown.</p>')
        elif len(file.lines) > fold_limit:
            parts.append(_folded_notice(file))
        else:
            parts.append('<table class="diff split">')
            for left, right in _split_rows(file):
                def cell(line: DiffLine | None, side: str) -> str:
                    if line is None:
                        return '<td class="no"></td><td class="empty"></td>'
                    number = line.old_number if side == "old" else line.new_number
                    return (
                        f'<td class="no">{number or ""}</td>'
                        f'<td class="dl-{line.kind}"><code>'
                        f"{escape_html_text(line.text)}</code></td>")
                parts.append(
                    f"<tr>{cell(left, 'old')}{cell(right, 'new')}</tr>")
            parts.append("</table>")
        parts.append("</details>")
    return "\n".join(parts)
