"""Blob view (S-099).

One file at one ref, rendered for reading: line numbers,
server-side syntax highlighting, and line permalinks.

- **Permalinks pin the commit, not the branch.** A line
  link names the commit oid the ref resolved to when the
  page was built (`/{owner}/{repo}/blob/{commit}/{path}#L{n}`),
  so a link pasted into an issue or a PR still shows the
  line it meant after the branch moves. The view reports
  both the requested ref and the resolved commit.
- **Highlighting is a safe tokeniser, not a parser.** It
  scans line by line with per-language keyword sets and
  comment/string rules, and every raw segment — token or
  plain — passes S-010's escaping before any `<span>` is
  wrapped around it, so code containing markup renders as
  visible text. Languages are detected from one shared
  extension table (S-218 owns the fuller language census;
  this table is its seed), falling back to the shebang for
  extensionless scripts, then to plain text. A language we
  do not highlight is shown plainly, never guessed at.
- **Honest limits.** Binary content is refused by name
  (`binary_file` — S-114 owns the binary view); an LFS
  pointer is reported as a pointer with its oid and size,
  never highlighted as if it were source; a file past the
  view limit (1 MB) answers `view_too_large` naming the
  size and the limit, pointing at S-100's raw/download —
  never a silent truncation.
- Permission and path law are S-097/S-098's shared helpers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .accounts import User
from .escaping import escape_html_attr, escape_html_text
from .lfs_store import LFSError, parse_pointer
from .objects import ObjectReader
from .permissions import can_read
from .proc import run_git_in
from .repo_home import RepoHomeError, blob_at, resolve_commit, validate_repo_path
from .repositories import RepositoryStore

VIEW_MAX_BYTES = 1_000_000

# extension -> language name (the seed of S-218's shared table)
LANGUAGE_BY_EXTENSION = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
    ".go": "go", ".rs": "rust", ".java": "java", ".c": "c",
    ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".cs": "csharp",
    ".rb": "ruby", ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".sql": "sql", ".html": "html", ".css": "css", ".json": "json",
    ".toml": "toml", ".yaml": "yaml", ".yml": "yaml", ".md": "markdown",
    ".lua": "lua", ".pl": "perl", ".php": "php",
}

_KEYWORDS = {
    "python": "and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield True False None print len range str int",
    "javascript": "async await break case catch class const continue debugger default delete do else export extends finally for function if import in instanceof let new return super switch this throw try typeof var void while yield true false null undefined",
    "typescript": "async await break case catch class const continue default delete do else enum export extends finally for function if implements import in instanceof interface let new package private protected public readonly return static switch this throw try type typeof var void while yield true false null undefined",
    "go": "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var true false nil",
    "rust": "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while",
    "java": "abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for if implements import instanceof int interface long native new package private protected public return short static super switch this throw throws transient try void volatile while true false null",
    "c": "auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while",
    "shell": "case do done elif else esac fi for function if in select then until while echo local return export source",
    "sql": "select from where insert into update delete set values create table drop alter join left right inner outer on group by order limit offset as and or not null primary key",
    "ruby": "alias and begin break case class def defined do else elsif end ensure false for if in module next nil not or redo rescue retry return self super then true undef unless until when while yield require puts",
}
_KEYWORDS["cpp"] = _KEYWORDS["java"] + " template typename namespace virtual friend bool nullptr using"
_KEYWORDS["csharp"] = _KEYWORDS["java"] + " namespace using bool string var async await"

_HASH_COMMENT = frozenset({"python", "shell", "ruby", "perl", "yaml", "toml"})
_SLASH_COMMENT = frozenset({"javascript", "typescript", "go", "rust",
                            "java", "c", "cpp", "csharp", "php"})


def detect_language(filename: str, data: bytes) -> str:
    name = filename.rsplit("/", 1)[-1].lower()
    if name in ("makefile", "dockerfile"):
        return "make"
    dot = name.rfind(".")
    if dot > 0 and name[dot:] in LANGUAGE_BY_EXTENSION:
        return LANGUAGE_BY_EXTENSION[name[dot:]]
    first = data.split(b"\n", 1)[0].decode("utf-8", "replace")
    if first.startswith("#!"):
        if "python" in first:
            return "python"
        if "node" in first:
            return "javascript"
        if "sh" in first:
            return "shell"
        if "ruby" in first:
            return "ruby"
        if "perl" in first:
            return "perl"
    return "text"


_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER_RE = re.compile(r"\b(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?)\b")


def _highlight_line(line: str, language: str, state: dict) -> str:
    """One line -> escaped HTML with token spans. `state`
    carries block-comment / triple-string continuation."""
    keywords = frozenset(_KEYWORDS.get(language, "").split())
    segments: list[tuple[str | None, str]] = []

    def plain(text: str):
        if text:
            segments.append((None, text))

    def token(cls: str, text: str):
        if text:
            segments.append((cls, text))

    i, n = 0, len(line)
    while i < n:
        if state.get("block"):
            end = line.find("*/", i)
            if end < 0:
                token("tok-c", line[i:]); i = n
            else:
                token("tok-c", line[i:end + 2]); i = end + 2
                state["block"] = False
            continue
        if state.get("triple"):
            quote = state["triple"]
            end = line.find(quote, i)
            if end < 0:
                token("tok-s", line[i:]); i = n
            else:
                token("tok-s", line[i:end + 3]); i = end + 3
                state["triple"] = None
            continue
        if language in _HASH_COMMENT and line[i] == "#":
            token("tok-c", line[i:]); break
        if language in _SLASH_COMMENT and line.startswith("//", i):
            token("tok-c", line[i:]); break
        if language in _SLASH_COMMENT and line.startswith("/*", i):
            end = line.find("*/", i + 2)
            if end < 0:
                token("tok-c", line[i:]); state["block"] = True; i = n
            else:
                token("tok-c", line[i:end + 2]); i = end + 2
            continue
        if language == "sql" and line.startswith("--", i):
            token("tok-c", line[i:]); break
        ch = line[i]
        if language == "python" and (line.startswith('"""', i)
                                     or line.startswith("'''", i)):
            quote = line[i:i + 3]
            end = line.find(quote, i + 3)
            if end < 0:
                token("tok-s", line[i:]); state["triple"] = quote; i = n
            else:
                token("tok-s", line[i:end + 3]); i = end + 3
            continue
        if ch in "\"'`":
            j = i + 1
            while j < n:
                if line[j] == "\\":
                    j += 2; continue
                if line[j] == ch:
                    j += 1; break
                j += 1
            token("tok-s", line[i:j]); i = j; continue
        number = _NUMBER_RE.match(line, i)
        if number:
            token("tok-n", number.group(0)); i = number.end(); continue
        word = _WORD_RE.match(line, i)
        if word:
            text = word.group(0)
            if text in keywords:
                token("tok-k", text)
            else:
                plain(text)
            i = word.end(); continue
        plain(ch); i += 1
    out = []
    for cls, text in segments:
        escaped = escape_html_text(text)
        out.append(f'<span class="{cls}">{escaped}</span>' if cls else escaped)
    return "".join(out)


def highlight(text: str, language: str) -> list[str]:
    """The whole text -> one escaped HTML string per line."""
    state: dict = {}
    return [_highlight_line(line, language, state)
            for line in text.split("\n")]


class BlobError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class BlobLine:
    number: int
    text: str
    html: str
    permalink: str


@dataclass(frozen=True)
class BlobView:
    full_name: str
    current_ref: str
    commit_oid: str
    path: str
    language: str
    size: int
    lines: tuple[BlobLine, ...]
    is_lfs_pointer: bool = False
    lfs_oid: str | None = None
    lfs_size: int | None = None

    def line_permalink(self, number: int) -> str:
        if number < 1 or number > len(self.lines):
            raise BlobError("line_out_of_range", f"No line {number}.")
        return self.lines[number - 1].permalink


class BlobViewer:
    def __init__(self, repositories: RepositoryStore):
        self._repos = repositories

    def view(self, viewer: User | None, owner: object, repo: object,
             ref: object = None, path: object = None) -> BlobView:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise BlobError("repo_not_found", "No such repository.")
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
            raise BlobError(exc.reason, str(exc)) from None
        # Size first, bytes second: cat-file -s answers without
        # loading the blob, so an oversized file is refused
        # before its bytes are ever read.
        size_result = run_git_in(repo_path, ["cat-file", "-s", entry.oid],
                                 timeout=15.0)
        try:
            raw_size = int(size_result.stdout.decode().strip())
        except ValueError:
            raise BlobError("object_unreadable", "That file cannot be read.") from None
        if raw_size > VIEW_MAX_BYTES:
            raise BlobError(
                "view_too_large",
                f"This file is {raw_size} bytes; the blob view limit is "
                f"{VIEW_MAX_BYTES} bytes. Use the raw/download view.")
        data = reader.read_blob(entry.oid)
        joined = "/".join(parts)
        try:
            pointer = parse_pointer(data)
        except LFSError:
            pointer = None
        if pointer is not None:
            return BlobView(
                full_name=current.full_name, current_ref=ref_name,
                commit_oid=commit_oid, path=joined, language="text",
                size=len(data), lines=(), is_lfs_pointer=True,
                lfs_oid=pointer.oid, lfs_size=pointer.size)
        if b"\x00" in data[:8192]:
            raise BlobError(
                "binary_file",
                "This file is binary; the blob view shows text. "
                "Use the raw/download view for its bytes.")
        text = data.decode("utf-8", "replace")
        if text.endswith("\n"):
            text = text[:-1]
        language = detect_language(joined, data)
        html_lines = highlight(text, language) if text else []
        raw_lines = text.split("\n") if text else []
        base = f"/{current.owner}/{current.name}/blob/{commit_oid}/{joined}"
        lines = tuple(
            BlobLine(number=i + 1, text=raw_lines[i], html=html_lines[i],
                     permalink=f"{base}#L{i + 1}")
            for i in range(len(raw_lines)))
        return BlobView(
            full_name=current.full_name, current_ref=ref_name,
            commit_oid=commit_oid, path=joined, language=language,
            size=len(data), lines=lines)


def render_blob_page(view: BlobView) -> str:
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(view.full_name)} — "
        f"{escape_html_text(view.path)} — Samverk</title></head>",
        "<body>",
        f"<h1>{escape_html_text(view.path)}</h1>",
        f'<p class="meta">{escape_html_text(view.full_name)} · '
        f"{escape_html_text(view.language)} · {view.size} bytes · "
        f"at {escape_html_text(view.commit_oid[:12])}</p>",
    ]
    if view.is_lfs_pointer:
        parts.append(
            '<p class="lfs">This file is stored with Git LFS. '
            f"Its content is {view.lfs_size} bytes "
            f"(object {escape_html_text(view.lfs_oid or '')}); "
            "use the download view for the real bytes.</p>")
    elif not view.lines:
        parts.append('<p class="empty">This file is empty.</p>')
    else:
        parts.append('<div class="blob">')
        for line in view.lines:
            parts.append(
                f'<div class="line" id="L{line.number}">'
                f'<a class="line-no" href="#L{line.number}">'
                f"{line.number}</a> "
                f"<code>{line.html if line.html else ' '}</code></div>")
        parts.append("</div>")
    parts.append("</body></html>")
    return "\n".join(parts)
