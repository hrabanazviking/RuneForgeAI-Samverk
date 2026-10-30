"""Archive downloads (S-063).

A repository snapshot at any ref, as a zip or tar.gz, produced
by `git archive` under S-014's subprocess law and **streamed**:
the bytes flow from git's stdout to the caller in chunks, and
Samverk never holds a whole archive in memory on the serving
path (the convenience `download_bytes` exists for tests and
small programmatic uses, and is built on the same stream).

The law:

1. **Permission first.** The download is gated by S-054's one
   `can_read` function before any git process is spawned. A
   repository the viewer cannot read — and a repository that
   does not exist — answer identically (`repo_not_found`), so
   a private repo's existence never leaks through this door.
2. **The ref is resolved before it is archived.** Branch,
   tag, HEAD, a full ref, or an object id are resolved through
   S-052; an unknown ref is refused by name (`ref_not_found`)
   and spawns nothing that could serve something else. A ref
   can never be read as a git flag (names starting with `-`
   fail S-052's validation).
3. **Counted as it flows.** Every chunk is counted and hashed
   as it passes, so a completed stream reports its exact byte
   count and SHA-256. For a fixed ref that checksum is stable
   across downloads — `git archive` derives its timestamps
   from the commit itself (the slice's acceptance).
4. **Bounded.** A stream carries a deadline (default 120 s);
   a git process that outlives it is killed, never waited on
   forever, and the stream raises `archive_timeout`.
5. **Formats are a closed set.** `zip` and `tar.gz`, nothing
   else; the archive's top-level directory is
   `<repo>-<ref>/` with the ref's slashes folded to dashes,
   and the download filename follows the same shape.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .permissions import can_read
from .proc import popen_git_in
from .refs import RefError, RefStore
from .repositories import RepositoryStore

CHUNK_SIZE = 64 * 1024
DEFAULT_TIMEOUT = 120.0

# format -> (file extension, content type, git --format value)
FORMATS = {
    "zip": (".zip", "application/zip", "zip"),
    "tar.gz": (".tar.gz", "application/gzip", "tar.gz"),
}

_OID_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")


class ArchiveError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass
class ArchiveStream:
    """One opened archive download: metadata up front, the byte
    count and checksum known once the stream is exhausted."""

    full_name: str
    ref: str             # as requested (validated)
    oid: str              # the commit/tree the ref resolved to
    format: str           # 'zip' | 'tar.gz'
    filename: str
    content_type: str
    _chunks: Iterator[bytes]
    bytes_counted: int = 0
    sha256: str | None = None   # set when the stream completes cleanly
    completed: bool = False

    def __iter__(self) -> Iterator[bytes]:
        yield from self._chunks

    def read_all(self) -> bytes:
        return b"".join(self)

    def write_to(self, writer) -> int:
        """Stream into a binary writer (an HTTP response body,
        a file); returns the byte count."""
        written = 0
        for chunk in self:
            writer.write(chunk)
            written += len(chunk)
        return written


def _ref_slug(ref: str) -> str:
    slug = ref
    for prefix in ("refs/heads/", "refs/tags/", "refs/remotes/", "refs/"):
        if slug.startswith(prefix):
            slug = slug[len(prefix):]
            break
    return slug.replace("/", "-").strip("-.") or "head"


class ArchiveService:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories

    def open_archive(
        self,
        viewer: User | None,
        owner: object,
        repo: object,
        ref: object = "HEAD",
        format: object = "zip",
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> ArchiveStream:
        """Open a streamed archive download, permission-gated.

        `viewer` is the resolved account, or None for an
        anonymous caller (who may still read public repos,
        per S-054).
        """
        if format not in FORMATS:
            raise ArchiveError(
                "format_invalid",
                "Archive format is 'zip' or 'tar.gz'.")
        fmt = str(format)
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            # One answer for missing and unreadable alike
            # (S-054: a private repo's existence is private).
            raise ArchiveError("repo_not_found", "No such repository.")
        path = self._repos.path_for(current.owner, current.name)
        ref_store = RefStore(path)
        ref_name = self._validate_ref(ref)
        oid = ref_store.resolve(ref_name)
        if oid is None:
            raise ArchiveError(
                "ref_not_found", f"No such ref in this repository: {ref!r}")
        extension, content_type, git_format = FORMATS[fmt]
        prefix = f"{current.name}-{_ref_slug(ref_name)}/"
        filename = f"{current.name}-{_ref_slug(ref_name)}{extension}"
        proc = popen_git_in(path, [
            "archive", f"--format={git_format}",
            f"--prefix={prefix}", ref_name])
        assert proc.stdout is not None
        hasher = hashlib.sha256()
        state = {"count": 0}

        def chunks() -> Iterator[bytes]:
            deadline = time.monotonic() + timeout
            try:
                while True:
                    if time.monotonic() > deadline:
                        proc.kill()
                        raise ArchiveError(
                            "archive_timeout",
                            "The archive did not finish in time.")
                    chunk = proc.stdout.read(CHUNK_SIZE)  # type: ignore[union-attr]
                    if not chunk:
                        break
                    state["count"] += len(chunk)
                    hasher.update(chunk)
                    yield chunk
            finally:
                try:
                    proc.stdout.close()  # type: ignore[union-attr]
                except Exception:
                    pass
            # stdout is at EOF; collect the verdict.
            try:
                proc.wait(timeout=max(1.0, deadline - time.monotonic()))
            except Exception:
                proc.kill()
                raise ArchiveError(
                    "archive_timeout",
                    "The archive did not finish in time.") from None
            if proc.returncode != 0:
                detail = ""
                if proc.stderr is not None:
                    detail = proc.stderr.read().decode(
                        "utf-8", "replace").strip()[:200]
                raise ArchiveError("archive_failed", detail)
            if proc.stderr is not None:
                try:
                    proc.stderr.close()
                except Exception:
                    pass
            stream.bytes_counted = state["count"]
            stream.sha256 = hasher.hexdigest()
            stream.completed = True

        stream = ArchiveStream(
            full_name=current.full_name, ref=ref_name, oid=oid,
            format=fmt, filename=filename, content_type=content_type,
            _chunks=chunks())
        return stream

    def download_bytes(self, viewer: User | None, owner: object,
                       repo: object, ref: object = "HEAD",
                       format: object = "zip") -> tuple[ArchiveStream, bytes]:
        """The whole archive as bytes, via the stream (tests and
        small programmatic uses). Returns (stream, data) with the
        stream's count/checksum filled in."""
        stream = self.open_archive(viewer, owner, repo, ref, format)
        return stream, stream.read_all()

    @staticmethod
    def _validate_ref(ref: object) -> str:
        if not isinstance(ref, str) or not ref:
            raise ArchiveError("ref_invalid", f"Not a ref: {ref!r}")
        if ref == "HEAD" or _OID_RE.match(ref.lower()):
            return ref
        # Branch/tag/full-ref shapes ride on S-052's validator,
        # which refuses leading dashes (flag smuggling) and the
        # other malformed shapes.
        from .refs import validate_ref_name
        try:
            return validate_ref_name(ref)
        except RefError:
            raise ArchiveError(
                "ref_invalid", f"Not a ref: {ref!r}") from None
