"""Release assets (S-259).

A release (S-257) may carry **assets**: named files a
reader downloads — the built tarball, the checksum's
sibling binaries, the manual as a PDF. Assets are the
first content Samverk accepts in pieces, and the laws
are S-012's, applied to a chunked wire:

- **Chunked upload, capped as it flows.** An upload
  opens with `begin_upload` (writer only), which fixes
  the asset's name and, when the uploader declares it,
  its expected size — a declared size over the
  per-asset cap is refused at the door, before a byte
  is read. Bytes then arrive through `upload_chunk`,
  strictly in order (chunk *n* is refused until chunks
  ``0..n-1`` have landed), each chunk at most
  ``CHUNK_MAX_BYTES``, and the running total is judged
  against the per-asset cap the moment it crosses it:
  the session is aborted and its staged bytes are
  deleted, never left to be completed by a retry.
  Staging lives in quarantine
  (``<data_root>/quarantine/release-asset-<id>.part``),
  under a name built from the session id alone — the
  uploader's filename never forms a path, and nothing
  is served, rendered, or unpacked from quarantine.
- **Per-asset size caps.** Every asset is capped by
  the store's policy (``ASSET_POLICY`` by default:
  ``ASSET_MAX_BYTES``); a release carries at most
  ``MAX_ASSETS_PER_RELEASE`` assets. Both caps are
  stated here and on the rendered page, never implied.
- **Content-type by sniffing.** `complete_upload` is
  the promotion S-012 reserves to the owning slice:
  the assembled bytes are judged by
  `samverk.uploads.inspect_upload` under the asset
  policy — the stored and served content type is the
  type the *bytes* prove (magic numbers, strict text
  test), a concrete declared type that disagrees is a
  disguise and is refused (`type_mismatch`), and
  `application/octet-stream` defers to the sniff, so
  a compiled binary — which sniffs as exactly that —
  is a lawful asset. Promotion copies the bytes to
  ``<data_root>/release-assets/<repo>/<release>/``
  under a content-addressed name (SHA-256 + an
  extension derived from the sniffed type), mode 600;
  two assets with the same bytes share one file, and
  the file outlives either name until the last row
  naming it is deleted.
- **Download with counts.** `download_asset` is gated
  by the release's own visibility (S-258: a draft's
  assets are private to writers, answering the uniform
  `release_not_found`; a private repository's assets
  answer the uniform `repo_not_found`), serves the
  sniffed content type, and counts: each opened
  download increments the asset's `download_count` in
  the same transaction that opens it, and the count
  rides every face — the API shape and the rendered
  listing, in words ("Downloaded 3 times"). A download
  whose bytes have vanished from disk is refused
  (`asset_missing`) and is *not* counted.

Permissions ride the repository's (S-054): uploading
and deleting are writer acts; reading follows the
release's visibility. Uploading to a draft is a
writer's ordinary preparation — the draft law governs
who may *see* the asset, not whether it may be built.
Asset acts carry no verb of their own in the frozen
taxonomy vocabulary and are not witnessed — no new
taxonomy event: 131 stand (33 auth / 85 repo /
13 admin). Assets live in migration 102's
`release_assets` row; open upload sessions in its
`release_upload_sessions` row (schema 101 to 102).
Checksums as a generated release file are S-260;
the latest pointer is S-261.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .permissions import can_write
from .platform_seam import ensure_dir
from .releases import Release, ReleaseError, ReleaseStore
from .repositories import Repository, RepositoryStore
from .uploads import UploadPolicy, UploadRejected, inspect_upload

ASSET_NAME_MAX = 255
ASSET_MAX_BYTES = 256 * 1024 * 1024
CHUNK_MAX_BYTES = 1 * 1024 * 1024
MAX_ASSETS_PER_RELEASE = 100
_DOWNLOAD_BLOCK = 64 * 1024

ASSET_POLICY = UploadPolicy(
    max_bytes=ASSET_MAX_BYTES,
    allowed_types=frozenset({
        "image/png", "image/jpeg", "image/gif", "image/webp",
        "application/pdf", "application/zip", "application/gzip",
        "text/plain", "application/octet-stream",
    }),
)

_EXTENSION_FOR_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/gzip": ".gz",
    "text/plain": ".txt",
    "application/octet-stream": ".bin",
}

__all__ = [
    "ASSET_MAX_BYTES", "ASSET_NAME_MAX", "ASSET_POLICY",
    "CHUNK_MAX_BYTES", "MAX_ASSETS_PER_RELEASE", "AssetDownload",
    "ReleaseAsset", "ReleaseAssetError", "ReleaseAssetStore",
    "UploadSession", "asset_to_dict", "render_asset",
    "render_assets_page", "validate_asset_name",
    "validate_expected_size",
]


class ReleaseAssetError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ReleaseAsset:
    id: int
    release_id: int
    repo_id: int
    name: str
    size: int
    sha256: str
    content_type: str
    download_count: int
    uploader_id: int
    created_at: int


@dataclass(frozen=True)
class UploadSession:
    id: int
    release_id: int
    repo_id: int
    name: str
    declared_type: str | None
    expected_size: int | None
    received: int
    chunks: int
    uploader_id: int
    created_at: int
    state: str


@dataclass
class AssetDownload:
    """One opened asset download: the asset as counted
    (its `download_count` already includes this
    download), the sniffed content type to serve, and
    the bytes behind a chunk iterator."""

    asset: ReleaseAsset
    filename: str
    content_type: str
    size: int
    sha256: str
    _path: Path

    def __iter__(self) -> Iterator[bytes]:
        with open(self._path, "rb") as handle:
            while True:
                block = handle.read(_DOWNLOAD_BLOCK)
                if not block:
                    return
                yield block

    def read_all(self) -> bytes:
        return b"".join(self)


def _row_to_asset(row: sqlite3.Row) -> ReleaseAsset:
    return ReleaseAsset(
        id=row["id"], release_id=row["release_id"],
        repo_id=row["repo_id"], name=row["name"],
        size=row["size"], sha256=row["sha256"],
        content_type=row["content_type"],
        download_count=row["download_count"],
        uploader_id=row["uploader_id"],
        created_at=row["created_at"])


def _row_to_session(row: sqlite3.Row) -> UploadSession:
    return UploadSession(
        id=row["id"], release_id=row["release_id"],
        repo_id=row["repo_id"], name=row["name"],
        declared_type=row["declared_type"],
        expected_size=row["expected_size"],
        received=row["received"], chunks=row["chunks"],
        uploader_id=row["uploader_id"],
        created_at=row["created_at"], state=row["state"])


def validate_asset_name(value: object) -> str:
    """An asset name is a bare file name: no path, no
    separators, no controls — it is shown and offered
    as a download filename, never used as a path."""
    if not isinstance(value, str) or not value.strip():
        raise ReleaseAssetError(
            "asset_name_required", "An asset needs a name.")
    name = value.strip()
    if (len(name) > ASSET_NAME_MAX or name in (".", "..")
            or "/" in name or "\\" in name
            or any(ord(c) < 0x20 or ord(c) == 0x7F for c in name)):
        raise ReleaseAssetError(
            "asset_name_invalid",
            f"Asset names are bare file names of at most "
            f"{ASSET_NAME_MAX} characters, with no path "
            "separators or control characters.")
    return name


def validate_expected_size(value: object,
                           policy: UploadPolicy) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ReleaseAssetError(
            "size_invalid",
            "An expected size is a positive whole number of bytes.")
    if value > policy.max_bytes:
        raise ReleaseAssetError(
            "too_large",
            f"An asset is at most {policy.max_bytes} bytes.")
    return value


def asset_to_dict(asset: ReleaseAsset, full_name: str = "",
                  tag: str = "") -> dict:
    """One asset as the API answers it."""
    return {
        "repository": full_name,
        "tag": tag,
        "name": asset.name,
        "size": asset.size,
        "sha256": asset.sha256,
        "content_type": asset.content_type,
        "download_count": asset.download_count,
        "uploader_id": asset.uploader_id,
        "created_at": asset.created_at,
    }


def _download_words(count: int) -> str:
    return "Downloaded 1 time" if count == 1 else (
        f"Downloaded {count} times")


def render_asset(asset: ReleaseAsset) -> str:
    """One asset as an HTML list item: every field
    escaped, the download count in words."""
    return (
        '<li class="release-asset">'
        + escape_html_text(asset.name)
        + f" &middot; {asset.size} bytes &middot; "
        + escape_html_text(asset.content_type)
        + " &middot; "
        + escape_html_text(_download_words(asset.download_count))
        + "</li>")


def render_assets_page(full_name: str, tag: str,
                       assets: list[ReleaseAsset]) -> str:
    """The assets listing for one release, caps stated."""
    if not assets:
        body = "<p>No assets yet.</p>"
    else:
        body = "<ul>" + "".join(
            render_asset(a) for a in assets) + "</ul>"
    return (
        '<section class="release-assets"><h3>Assets of '
        + escape_html_text(full_name) + " "
        + escape_html_text(tag) + "</h3>" + body
        + f"<p>Each asset is at most {ASSET_MAX_BYTES} bytes; "
        + f"a release carries at most {MAX_ASSETS_PER_RELEASE} "
        + "assets. An asset's content type is the type its "
        + "bytes prove, not the type claimed at upload.</p>"
        + "</section>")


class ReleaseAssetStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        releases: ReleaseStore,
        data_root: Path,
        accounts: AccountStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
        policy: UploadPolicy = ASSET_POLICY,
    ):
        self._conn = conn
        self._repos = repositories
        self._releases = releases
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn
        self._policy = policy

    # -- paths ------------------------------------------------
    def _staging_path(self, session_id: int) -> Path:
        return (self._data_root / "quarantine"
                / f"release-asset-{session_id}.part")

    def _asset_path(self, asset: ReleaseAsset) -> Path:
        ext = _EXTENSION_FOR_TYPE.get(asset.content_type, ".bin")
        return (self._data_root / "release-assets"
                / str(asset.repo_id) / str(asset.release_id)
                / f"{asset.sha256}{ext}")

    # -- gates --------------------------------------------------
    def _repo_for_read(self, viewer: User | None, owner: object,
                       repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise ReleaseAssetError(
                "repo_not_found", "No such repository.")
        return current

    def _release_for_read(self, viewer: User | None, owner: object,
                          repo: object, tag: object) -> Release:
        try:
            return self._releases.get_release(viewer, owner, repo, tag)
        except ReleaseError as exc:
            raise ReleaseAssetError(exc.reason, str(exc)) from None

    def _release_for_write(self, actor: User, owner: object,
                           repo: object, tag: object) -> Release:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise ReleaseAssetError(
                "repo_not_found", "No such repository.")
        # get_release answers repo_not_found for a repo the
        # actor cannot read and release_not_found for a
        # draft the actor may not see; a writer sees both.
        release = self._release_for_read(actor, owner, repo, tag)
        if not can_write(actor, current):
            raise ReleaseAssetError(
                "permission_denied",
                "Only a repository writer can manage release assets.")
        return release

    def _session(self, upload_id: object) -> UploadSession:
        if isinstance(upload_id, bool) or not isinstance(upload_id, int):
            raise ReleaseAssetError(
                "upload_not_found", "No such upload.")
        row = self._conn.execute(
            "SELECT * FROM release_upload_sessions WHERE id = ?",
            (upload_id,)).fetchone()
        if row is None:
            raise ReleaseAssetError(
                "upload_not_found", "No such upload.")
        return _row_to_session(row)

    def _open_session(self, actor: User,
                      upload_id: object) -> UploadSession:
        session = self._session(upload_id)
        if session.state != "open":
            raise ReleaseAssetError(
                "upload_closed", "That upload is no longer open.")
        if session.uploader_id != actor.id:
            raise ReleaseAssetError(
                "permission_denied",
                "Only the uploader can continue that upload.")
        return session

    def _abort(self, session: UploadSession) -> None:
        staging = self._staging_path(session.id)
        with self._conn:
            self._conn.execute(
                "UPDATE release_upload_sessions SET state = 'aborted'"
                " WHERE id = ?", (session.id,))
        try:
            staging.unlink()
        except OSError:
            pass

    def _asset_count(self, release_id: int) -> int:
        return int(self._conn.execute(
            "SELECT COUNT(*) c FROM release_assets WHERE release_id = ?",
            (release_id,)).fetchone()["c"])

    def _by_name(self, release_id: int,
                 name: object) -> ReleaseAsset | None:
        if not isinstance(name, str):
            return None
        row = self._conn.execute(
            "SELECT * FROM release_assets WHERE release_id = ?"
            " AND name = ?", (release_id, name)).fetchone()
        return _row_to_asset(row) if row else None

    def _by_id(self, asset_id: int) -> ReleaseAsset | None:
        row = self._conn.execute(
            "SELECT * FROM release_assets WHERE id = ?",
            (asset_id,)).fetchone()
        return _row_to_asset(row) if row else None

    # -- chunked upload -----------------------------------------
    def begin_upload(self, actor: User, owner: object, repo: object,
                     tag: object, name: object, *,
                     declared_type: str | None = None,
                     expected_size: object = None) -> UploadSession:
        release = self._release_for_write(actor, owner, repo, tag)
        name_text = validate_asset_name(name)
        expected = validate_expected_size(expected_size, self._policy)
        if self._by_name(release.id, name_text) is not None:
            raise ReleaseAssetError(
                "asset_taken",
                f"Release {release.tag!r} already carries an asset "
                f"named {name_text!r}.")
        if self._asset_count(release.id) >= MAX_ASSETS_PER_RELEASE:
            raise ReleaseAssetError(
                "too_many_assets",
                f"A release carries at most "
                f"{MAX_ASSETS_PER_RELEASE} assets.")
        now = int(self._now())
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO release_upload_sessions (release_id,"
                " repo_id, name, declared_type, expected_size,"
                " received, chunks, uploader_id, created_at, state)"
                " VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, 'open')",
                (release.id, release.repo_id, name_text,
                 declared_type, expected, actor.id, now))
        session = self._session(int(cur.lastrowid))
        staging = self._staging_path(session.id)
        ensure_dir(staging.parent)
        staging.write_bytes(b"")
        try:
            staging.chmod(0o600)
        except OSError:
            pass  # non-POSIX filesystems govern their own ACLs
        return session

    def upload_chunk(self, actor: User, upload_id: object,
                     chunk_index: object, data: object) -> UploadSession:
        session = self._open_session(actor, upload_id)
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise ReleaseAssetError(
                "chunk_empty", "A chunk carries at least one byte.")
        if len(data) > CHUNK_MAX_BYTES:
            raise ReleaseAssetError(
                "chunk_too_large",
                f"A chunk is at most {CHUNK_MAX_BYTES} bytes.")
        if (isinstance(chunk_index, bool)
                or not isinstance(chunk_index, int)
                or chunk_index != session.chunks):
            raise ReleaseAssetError(
                "chunk_out_of_order",
                f"Chunk {session.chunks} is expected next.")
        received = session.received + len(data)
        if received > self._policy.max_bytes:
            self._abort(session)
            raise ReleaseAssetError(
                "too_large",
                f"An asset is at most {self._policy.max_bytes} bytes.")
        if (session.expected_size is not None
                and received > session.expected_size):
            self._abort(session)
            raise ReleaseAssetError(
                "size_mismatch",
                "The upload is larger than its declared size.")
        staging = self._staging_path(session.id)
        with open(staging, "ab") as handle:
            handle.write(bytes(data))
        with self._conn:
            self._conn.execute(
                "UPDATE release_upload_sessions SET received = ?,"
                " chunks = ? WHERE id = ?",
                (received, session.chunks + 1, session.id))
        return self._session(session.id)

    def complete_upload(self, actor: User,
                        upload_id: object) -> ReleaseAsset:
        session = self._open_session(actor, upload_id)
        staging = self._staging_path(session.id)
        if session.received == 0:
            self._abort(session)
            raise ReleaseAssetError(
                "empty", "An asset carries at least one byte.")
        if (session.expected_size is not None
                and session.received != session.expected_size):
            self._abort(session)
            raise ReleaseAssetError(
                "size_mismatch",
                "The upload is smaller than its declared size.")
        if self._by_name(session.release_id, session.name) is not None:
            self._abort(session)
            raise ReleaseAssetError(
                "asset_taken",
                f"An asset named {session.name!r} already stands "
                "on this release.")
        if self._asset_count(session.release_id) >= MAX_ASSETS_PER_RELEASE:
            self._abort(session)
            raise ReleaseAssetError(
                "too_many_assets",
                f"A release carries at most "
                f"{MAX_ASSETS_PER_RELEASE} assets.")
        data = staging.read_bytes()
        try:
            inspected = inspect_upload(
                data, declared_type=session.declared_type,
                policy=self._policy)
        except UploadRejected as exc:
            self._abort(session)
            raise ReleaseAssetError(exc.reason, str(exc)) from None
        asset = ReleaseAsset(
            id=0, release_id=session.release_id,
            repo_id=session.repo_id, name=session.name,
            size=inspected.size, sha256=inspected.sha256,
            content_type=inspected.detected_type, download_count=0,
            uploader_id=session.uploader_id,
            created_at=int(self._now()))
        final = self._asset_path(asset)
        ensure_dir(final.parent)
        if not final.exists():
            final.write_bytes(data)
            try:
                final.chmod(0o600)
            except OSError:
                pass
        now = int(self._now())
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO release_assets (release_id, repo_id,"
                " name, size, sha256, content_type, download_count,"
                " uploader_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (asset.release_id, asset.repo_id, asset.name,
                 asset.size, asset.sha256, asset.content_type,
                 asset.uploader_id, now))
            self._conn.execute(
                "DELETE FROM release_upload_sessions WHERE id = ?",
                (session.id,))
        try:
            staging.unlink()
        except OSError:
            pass
        created = self._by_id(int(cur.lastrowid))
        assert created is not None
        return created

    def abort_upload(self, actor: User,
                     upload_id: object) -> UploadSession:
        session = self._open_session(actor, upload_id)
        self._abort(session)
        return self._session(session.id)

    # -- reads, download, delete --------------------------------
    def get_asset(self, viewer: User | None, owner: object,
                  repo: object, tag: object,
                  name: object) -> ReleaseAsset:
        release = self._release_for_read(viewer, owner, repo, tag)
        asset = self._by_name(release.id, name)
        if asset is None:
            raise ReleaseAssetError(
                "asset_not_found", "No such asset.")
        return asset

    def list_assets(self, viewer: User | None, owner: object,
                    repo: object, tag: object) -> list[ReleaseAsset]:
        release = self._release_for_read(viewer, owner, repo, tag)
        rows = self._conn.execute(
            "SELECT * FROM release_assets WHERE release_id = ?"
            " ORDER BY created_at, id", (release.id,)).fetchall()
        return [_row_to_asset(r) for r in rows]

    def download_asset(self, viewer: User | None, owner: object,
                       repo: object, tag: object,
                       name: object) -> AssetDownload:
        """Open a download: gated by the release's
        visibility, counted in the transaction that
        opens it, served as the sniffed type. Bytes
        missing from disk refuse (`asset_missing`) and
        are not counted."""
        asset = self.get_asset(viewer, owner, repo, tag, name)
        path = self._asset_path(asset)
        if not path.is_file():
            raise ReleaseAssetError(
                "asset_missing",
                "That asset's bytes are missing from storage.")
        with self._conn:
            self._conn.execute(
                "UPDATE release_assets SET download_count ="
                " download_count + 1 WHERE id = ?", (asset.id,))
        counted = self._by_id(asset.id)
        assert counted is not None
        return AssetDownload(
            asset=counted, filename=counted.name,
            content_type=counted.content_type, size=counted.size,
            sha256=counted.sha256, _path=path)

    def delete_asset(self, actor: User, owner: object, repo: object,
                     tag: object, name: object) -> ReleaseAsset:
        release = self._release_for_write(actor, owner, repo, tag)
        asset = self._by_name(release.id, name)
        if asset is None:
            raise ReleaseAssetError(
                "asset_not_found", "No such asset.")
        path = self._asset_path(asset)
        with self._conn:
            self._conn.execute(
                "DELETE FROM release_assets WHERE id = ?", (asset.id,))
            remaining = int(self._conn.execute(
                "SELECT COUNT(*) c FROM release_assets"
                " WHERE release_id = ? AND sha256 = ?",
                (asset.release_id, asset.sha256)).fetchone()["c"])
        if remaining == 0:
            try:
                path.unlink()
            except OSError:
                pass
        return asset
