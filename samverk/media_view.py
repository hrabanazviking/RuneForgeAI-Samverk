"""Binary and image files (S-114).

The view S-099 points at when a file is not text: images
render as images, everything else binary is described —
never dumped.

- **Images render, with real alt text.** A raster image
  (PNG, JPEG, GIF, WebP — recognised by its magic bytes,
  not merely by its name) is shown through S-100's raw
  route at the pinned commit, and the `<img>` always
  carries genuine alt text naming the file and its place
  in the repository (the image-accessibility law: alt is
  a true spoken description, here "Image file <path> in
  <repo>, <W>×<H>" when the header carries dimensions).
  Dimensions are read from the image headers themselves
  (PNG IHDR, GIF logical screen, JPEG SOF, WebP VP8
  family) — stated only when the header proves them.
- **SVG is not rendered inline.** An SVG is markup and a
  script carrier (S-012/S-100's law): it is described as
  a file — size, type, download — and its bytes are
  served attachment-only by S-100. Calling it an "image
  view" would be a lie this module does not tell.
- **Binaries are described, never dumped.** Any other
  binary gets its size, its content type (S-100's one
  table + sniff), and a download action — and the page
  contains none of its bytes: no hex dump, no base64, no
  "preview". A hex dump surprise is exactly what the
  roadmap forbids.
- **Text does not belong here.** A file S-099 can show
  as text is refused by name (`text_file`) pointing back
  at the blob view, so the two views can never disagree
  about what a file is. LFS pointers are reported as
  pointers (oid + promised size), as everywhere.
- Permission, ref and path law are S-097's shared
  helpers; the classification is computed from the blob
  bytes at the pinned commit, so a renamed file cannot
  smuggle a binary past as `.txt` or dress text as `.png`
  — the magic bytes decide the kind, the name only
  refines the content type.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .accounts import User
from .escaping import escape_html_attr, escape_html_text
from .lfs_store import LFSError, parse_pointer
from .objects import ObjectReader
from .permissions import can_read
from .raw_download import content_type_for
from .repo_home import RepoHomeError, blob_at, resolve_commit, validate_repo_path
from .repositories import RepositoryStore

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_GIF_MAGICS = (b"GIF87a", b"GIF89a")
_RIFF_MAGIC = b"RIFF"
_WEBP_MAGIC = b"WEBP"


def sniff_image(data: bytes) -> str | None:
    """The raster format *data* provably is, from its magic
    bytes alone — or None. Names are not consulted."""
    if data[:8] == _PNG_MAGIC:
        return "png"
    if data[:3] == _JPEG_MAGIC:
        return "jpeg"
    if data[:6] in _GIF_MAGICS:
        return "gif"
    if data[:4] == _RIFF_MAGIC and data[8:12] == _WEBP_MAGIC:
        return "webp"
    return None


def image_dimensions(fmt: str, data: bytes) -> tuple[int, int] | None:
    """(width, height) from the image header, or None when
    the header does not carry them legibly. Never guessed."""
    try:
        if fmt == "png" and len(data) >= 24 and data[12:16] == b"IHDR":
            return struct.unpack(">II", data[16:24])
        if fmt == "gif" and len(data) >= 10:
            return struct.unpack("<HH", data[6:10])
        if fmt == "jpeg":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    return None
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2):
                    height, width = struct.unpack(">HH", data[i + 5:i + 9])
                    return width, height
                length = struct.unpack(">H", data[i + 2:i + 4])[0]
                if length < 2:
                    return None
                i += 2 + length
            return None
        if fmt == "webp" and len(data) >= 30:
            if data[12:16] == b"VP8X":
                width = int.from_bytes(data[24:27], "little") + 1
                height = int.from_bytes(data[27:30], "little") + 1
                return width, height
            if data[12:16] == b"VP8L":
                bits = int.from_bytes(data[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            if data[12:16] == b"VP8 ":
                width = struct.unpack("<H", data[26:28])[0] & 0x3FFF
                height = struct.unpack("<H", data[28:30])[0] & 0x3FFF
                return width, height
    except (struct.error, IndexError):
        return None
    return None


def is_text_data(data: bytes) -> bool:
    """S-099's own test, shared so the views agree: text is
    UTF-8-decodable content without NULs in its head."""
    if b"\x00" in data[:8192]:
        return False
    try:
        data[:8192].decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


class MediaError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class MediaView:
    full_name: str
    current_ref: str
    commit_oid: str
    path: str
    kind: str               # 'image' | 'binary' | 'lfs_pointer'
    content_type: str
    size: int
    image_format: str | None = None     # 'png'|'jpeg'|'gif'|'webp'
    width: int | None = None
    height: int | None = None
    lfs_oid: str | None = None
    lfs_size: int | None = None

    @property
    def raw_href(self) -> str:
        base = "/".join(self.path.split("/"))
        return (f"/{self.full_name}/raw/{self.commit_oid}/{base}")

    @property
    def alt_text(self) -> str:
        """A true spoken description of the image (the
        image-accessibility law), built from facts the view
        actually holds."""
        if self.kind != "image":
            return ""
        text = f"Image file {self.path} in {self.full_name}"
        if self.width is not None and self.height is not None:
            text += f", {self.width} by {self.height} pixels"
        return text + f", {self.size} bytes."


class MediaViewer:
    def __init__(self, repositories: RepositoryStore):
        self._repos = repositories

    def view(self, viewer: User | None, owner: object, repo: object,
             ref: object = None, path: object = None) -> MediaView:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise MediaError("repo_not_found", "No such repository.")
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
            raise MediaError(exc.reason, str(exc)) from None
        data = reader.read_blob(entry.oid)
        joined = "/".join(parts)
        try:
            pointer = parse_pointer(data)
        except LFSError:
            pointer = None
        if pointer is not None:
            return MediaView(
                full_name=current.full_name, current_ref=ref_name,
                commit_oid=commit_oid, path=joined, kind="lfs_pointer",
                content_type="text/plain; charset=utf-8",
                size=len(data), lfs_oid=pointer.oid,
                lfs_size=pointer.size)
        fmt = sniff_image(data)
        if fmt is not None:
            dims = image_dimensions(fmt, data)
            return MediaView(
                full_name=current.full_name, current_ref=ref_name,
                commit_oid=commit_oid, path=joined, kind="image",
                content_type=content_type_for(joined, data),
                size=len(data), image_format=fmt,
                width=dims[0] if dims else None,
                height=dims[1] if dims else None)
        if is_text_data(data) and not joined.lower().endswith(".svg"):
            raise MediaError(
                "text_file",
                "This file is text; the blob view shows it.")
        return MediaView(
            full_name=current.full_name, current_ref=ref_name,
            commit_oid=commit_oid, path=joined, kind="binary",
            content_type=content_type_for(joined, data),
            size=len(data))


def render_media_page(view: MediaView) -> str:
    """The media page: an image renders as an image (raw
    route at the pinned commit, real alt text); a binary
    is described in words with a download action and none
    of its bytes; an LFS pointer is named as a pointer."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(view.full_name)} — "
        f"{escape_html_text(view.path)} — Samverk</title></head>",
        "<body>",
        f"<h1>{escape_html_text(view.path)}</h1>",
    ]
    if view.kind == "image":
        parts.append(
            f'<p class="meta">{escape_html_text(view.content_type)} · '
            f"{view.size} bytes"
            + (f" · {view.width}×{view.height}"
               if view.width is not None else "")
            + "</p>")
        parts.append(
            f'<p><img src="{escape_html_attr(view.raw_href)}" '
            f'alt="{escape_html_attr(view.alt_text)}"></p>')
        parts.append(
            f'<p><a href="{escape_html_attr(view.raw_href)}">'
            "Download the original file</a></p>")
    elif view.kind == "lfs_pointer":
        parts.append(
            "<p>This file is stored with Git LFS. "
            f"Its content is {view.lfs_size} bytes "
            f"(object {escape_html_text(view.lfs_oid or '')}); "
            "use the download view for the real bytes.</p>")
    else:
        parts.append(
            '<p class="binary">This is a binary file, so there is '
            "no text preview. Its details:</p>")
        parts.append(
            f'<p class="meta">Type: '
            f"{escape_html_text(view.content_type)} · "
            f"Size: {view.size} bytes</p>")
        parts.append(
            f'<p><a href="{escape_html_attr(view.raw_href)}">'
            "Download this file</a></p>")
    parts.append("</body></html>")
    return "\n".join(parts)
