"""Raw and download (S-100).

The bytes themselves, exactly as git stores them — or, for
an LFS file, exactly as the LFS store holds them.

- **Correct content types.** A file's type comes from one
  extension table, with a content sniff as the fallback for
  unknown names (UTF-8 text without NULs is `text/plain`;
  anything else is `application/octet-stream`). Text types
  carry `charset=utf-8`. SVG is served only as an
  attachment download, never inline — unsanitised SVG is a
  script carrier (S-012's law, applied at this door).
- **Downloads are attachments.** `download` answers carry
  `Content-Disposition: attachment` with the file's base
  name (validated through the path law, so the name can
  never smuggle a header or a directory).
- **Never a silent truncation.** There is no size cap on
  this door and no partial answer: a large file's bytes
  come back whole. (S-099's blob *view* refuses oversized
  files by name and points here; this door is where they
  land.)
- **LFS is shown, not faked.** A file whose blob is an LFS
  pointer resolves to the real bytes when the object is in
  this repo's LFS store (its size is checked against the
  pointer before a byte is served). When the object is not
  here, the result is the pointer itself, flagged: the
  caller shows the pointer page (`render_pointer_page`) —
  oid, promised size, and the honest words that the bytes
  are not on this instance — instead of serving pointer
  text dressed as the file.
- Permission, ref and path law are S-097's shared helpers.
"""

from __future__ import annotations

from dataclasses import dataclass

from .accounts import User
from .escaping import escape_html_text
from .lfs_store import LFSError, LFSStore, parse_pointer
from .objects import ObjectReader
from .permissions import can_read
from .repo_home import RepoHomeError, blob_at, resolve_commit, validate_repo_path
from .repositories import RepositoryStore

CONTENT_TYPES = {
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".py": "text/x-python; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".ts": "text/typescript; charset=utf-8",
    ".json": "application/json",
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".xml": "application/xml",
    ".csv": "text/csv; charset=utf-8",
    ".toml": "text/plain; charset=utf-8",
    ".yaml": "text/plain; charset=utf-8",
    ".yml": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".gz": "application/gzip",
}

# Types safe to render inline in a browser on this origin.
_INLINE_TYPES = frozenset({
    "text/plain; charset=utf-8", "image/png", "image/jpeg",
    "image/gif", "image/webp", "application/pdf",
})


def content_type_for(filename: str, data: bytes) -> str:
    name = filename.rsplit("/", 1)[-1].lower()
    dot = name.rfind(".")
    if dot > 0 and name[dot:] in CONTENT_TYPES:
        return CONTENT_TYPES[name[dot:]]
    if b"\x00" not in data[:8192]:
        try:
            data[:8192].decode("utf-8")
            return "text/plain; charset=utf-8"
        except UnicodeDecodeError:
            pass
    return "application/octet-stream"


class RawError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class RawFile:
    full_name: str
    path: str
    filename: str                 # base name, for the download header
    content_type: str
    data: bytes | None            # None only for an unresolved LFS pointer
    size: int                     # the real file's size
    is_lfs_pointer: bool = False
    lfs_oid: str | None = None
    lfs_size: int | None = None

    @property
    def download_available(self) -> bool:
        return self.data is not None

    @property
    def disposition(self) -> str:
        """The Content-Disposition for serving this result:
        inline only for the small safe set, attachment for
        everything else — and always attachment for SVG."""
        if self.content_type in _INLINE_TYPES and \
                not self.path.lower().endswith(".svg"):
            return "inline"
        return f'attachment; filename="{self.filename}"'


class RawDownloadService:
    def __init__(self, repositories: RepositoryStore):
        self._repos = repositories

    def raw(self, viewer: User | None, owner: object, repo: object,
            ref: object = None, path: object = None) -> RawFile:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise RawError("repo_not_found", "No such repository.")
        repo_path = self._repos.path_for(current.owner, current.name)
        requested = current.default_branch if ref is None else ref
        try:
            parts = validate_repo_path(path)
            if not parts:
                raise RepoHomeError("path_invalid", "A file path is required.")
            _, commit_oid = resolve_commit(repo_path, requested)
            reader = ObjectReader(repo_path)
            entry = blob_at(reader, commit_oid, parts)
        except RepoHomeError as exc:
            raise RawError(exc.reason, str(exc)) from None
        data = reader.read_blob(entry.oid)
        joined = "/".join(parts)
        filename = parts[-1]
        try:
            pointer = parse_pointer(data)
        except LFSError:
            pointer = None
        if pointer is not None:
            store = LFSStore(repo_path)
            if store.has(pointer.oid):
                real = store.read(pointer.oid)
                if len(real) != pointer.size:
                    raise RawError(
                        "lfs_size_mismatch",
                        "The stored LFS object does not match its "
                        "pointer's size; refusing to serve it.")
                return RawFile(
                    full_name=current.full_name, path=joined,
                    filename=filename,
                    content_type=content_type_for(joined, real),
                    data=real, size=len(real), is_lfs_pointer=True,
                    lfs_oid=pointer.oid, lfs_size=pointer.size)
            return RawFile(
                full_name=current.full_name, path=joined,
                filename=filename, content_type="text/plain; charset=utf-8",
                data=None, size=pointer.size, is_lfs_pointer=True,
                lfs_oid=pointer.oid, lfs_size=pointer.size)
        return RawFile(
            full_name=current.full_name, path=joined, filename=filename,
            content_type=content_type_for(joined, data),
            data=data, size=len(data))


def render_pointer_page(raw: RawFile) -> str:
    """The page an unresolved LFS file shows: the pointer,
    in words, and what to do about it. Also usable for a
    resolved file's info — the download fact is stated."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(raw.full_name)} — "
        f"{escape_html_text(raw.path)} — Samverk</title></head>",
        "<body>",
        f"<h1>{escape_html_text(raw.path)}</h1>",
        "<p>This file is stored with Git LFS.</p>",
        f"<p>Object: {escape_html_text(raw.lfs_oid or '')}<br>"
        f"Size: {raw.lfs_size} bytes</p>",
    ]
    if raw.download_available:
        parts.append(
            "<p>The file's bytes are stored on this instance and "
            "can be downloaded.</p>")
    else:
        parts.append(
            "<p>The file's bytes are not stored on this instance, "
            "so there is nothing to download here yet. The pointer "
            "above is everything this repository holds for it.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
