"""Release checksums (S-260).

Every release (S-257) that carries assets (S-259)
also carries one more file, and this one is never
uploaded: a **generated checksums file** naming the
SHA-256 of every asset on the release, downloadable
beside the assets under the fixed name
``SHA256SUMS.txt``. A reader who downloads the
assets can prove each file is the file the release
published — byte for byte — before trusting it.

The laws:

- **Generated, never stored.** The file is built
  fresh from migration 102's `release_assets` rows
  on every read: `build_checksums_text` is a pure
  function of the asset list, one line per asset in
  name order, each line the stored SHA-256 (the
  digest S-259's promotion computed over the
  assembled bytes), two spaces, and the asset name —
  exactly the format `sha256sum` writes, so the
  standard tools read it back without translation.
  Adding or deleting an asset changes the file the
  next moment it is asked for; there is no stored
  copy to drift stale and no row to keep in step,
  so this slice needs no migration (schema 102
  stands) and the file itself is never one of the
  assets it lists. A release with no assets has an
  empty checksums file — zero lines, still
  downloadable, honestly saying there is nothing
  to verify yet.
- **Downloadable beside the assets.** `get_checksums`
  and `download_checksums` answer the same generated
  bytes; the download names the file
  ``SHA256SUMS.txt``, serves it as
  ``text/plain; charset=utf-8``, and reports the
  file's own size and SHA-256. The generated file
  has no row of its own, so its download is not
  counted on any asset's `download_count` — the
  counts stay the assets' own (S-259). An uploaded
  asset that happens to share the name is an
  ordinary asset like any other: it is listed in
  the file by its own digest, and the generated
  download is a separate door, never a name lookup,
  so the two never collide.
- **Verification is stated, and checkable here.**
  The rendered section carries the instructions in
  words beside the download: on a POSIX system,
  save the file beside the downloaded assets and
  run ``sha256sum -c SHA256SUMS.txt`` (on macOS,
  ``shasum -a 256 -c SHA256SUMS.txt``); every asset
  must answer OK, and any other answer means that
  file is not the published bytes and must not be
  trusted. The same judgement exists in code for
  callers that hold the bytes: `parse_checksums`
  reads a checksums file strictly (a malformed
  line is refused `checksums_invalid` by line
  number), and `verify_checksums` compares it
  against a name-to-digest mapping, naming every
  mismatch, missing, and unexpected entry.
- **Visibility is the release's own (S-258).**
  Every door resolves through S-259's asset
  listing, so a draft's checksums are private to
  writers (the uniform `release_not_found` for
  everyone else), a private repository's checksums
  answer the uniform `repo_not_found`, and a
  release that does not stand answers
  `release_not_found`. Permissions ride the
  repository's (S-054), exactly as the assets do.

Checksums acts carry no verb of their own in the
frozen taxonomy vocabulary and are not witnessed —
no new taxonomy event: 131 stand (33 auth /
85 repo / 13 admin). The latest pointer is S-261;
release packaging (S-400) builds on this machinery.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .release_assets import ReleaseAsset, ReleaseAssetStore
from .releases import Release, ReleaseStore
from .repositories import RepositoryStore

CHECKSUMS_FILENAME = "SHA256SUMS.txt"
CHECKSUMS_CONTENT_TYPE = "text/plain; charset=utf-8"
VERIFY_COMMAND_POSIX = f"sha256sum -c {CHECKSUMS_FILENAME}"
VERIFY_COMMAND_MACOS = f"shasum -a 256 -c {CHECKSUMS_FILENAME}"
_DOWNLOAD_BLOCK = 64 * 1024
_LINE_RE = re.compile(r"^([0-9a-f]{64})  (.+)$")

__all__ = [
    "CHECKSUMS_CONTENT_TYPE", "CHECKSUMS_FILENAME",
    "VERIFY_COMMAND_MACOS", "VERIFY_COMMAND_POSIX",
    "ChecksumEntry", "ChecksumsDownload", "GeneratedChecksums",
    "ReleaseChecksumError", "ReleaseChecksumStore",
    "Verification", "build_checksums_text", "checksums_bytes",
    "checksums_to_dict", "parse_checksums",
    "render_checksums_section", "verify_checksums",
]


class ReleaseChecksumError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ChecksumEntry:
    name: str
    sha256: str


@dataclass(frozen=True)
class GeneratedChecksums:
    """One generated checksums file: the release it
    belongs to, the assets it lists (in file order),
    and the file's exact bytes with their own digest."""

    release: Release
    filename: str
    content_type: str
    text: str
    data: bytes
    sha256: str
    entries: tuple[ChecksumEntry, ...]

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def asset_count(self) -> int:
        return len(self.entries)


@dataclass
class ChecksumsDownload:
    """One opened checksums download: the generated
    file's name, type, size and own digest, with the
    bytes behind a chunk iterator (the S-259
    AssetDownload shape)."""

    filename: str
    content_type: str
    size: int
    sha256: str
    asset_count: int
    _data: bytes

    def __iter__(self) -> Iterator[bytes]:
        for start in range(0, len(self._data), _DOWNLOAD_BLOCK):
            yield self._data[start:start + _DOWNLOAD_BLOCK]

    def read_all(self) -> bytes:
        return self._data


@dataclass(frozen=True)
class Verification:
    """The verdict of `verify_checksums`: how many
    entries were checked, and the names that failed —
    a digest that differs (`mismatched`), a listed
    file the caller does not hold (`missing`), and a
    held file the checksums file does not list
    (`unexpected`). `ok` is true only when every
    list is empty and at least the listed files were
    all present and true."""

    checked: int
    mismatched: tuple[str, ...]
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not (self.mismatched or self.missing
                    or self.unexpected)


def build_checksums_text(assets: list[ReleaseAsset]) -> str:
    """The checksums file for one asset list, pure:
    one ``<sha256>  <name>`` line per asset, assets
    in name order (ties by id, so the order is total),
    each line newline-terminated. Asset names carry
    no control characters (S-259's validation), so a
    name can never break the line format. The empty
    list builds the empty file."""
    ordered = sorted(assets, key=lambda a: (a.name, a.id))
    return "".join(f"{a.sha256}  {a.name}\n" for a in ordered)


def checksums_bytes(assets: list[ReleaseAsset]) -> bytes:
    return build_checksums_text(assets).encode("utf-8")


def parse_checksums(text: object) -> list[ChecksumEntry]:
    """Read a checksums file strictly: every non-final
    line is ``<64 lowercase hex>  <name>``; anything
    else is refused `checksums_invalid` naming the
    line. The empty file parses to no entries."""
    if not isinstance(text, str):
        raise ReleaseChecksumError(
            "checksums_invalid", "A checksums file is text.")
    entries: list[ChecksumEntry] = []
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        match = _LINE_RE.match(line)
        if match is None:
            raise ReleaseChecksumError(
                "checksums_invalid",
                f"Line {number} of the checksums file is not "
                "a '<sha256>  <name>' line.")
        digest, name = match.group(1), match.group(2)
        if name in seen:
            raise ReleaseChecksumError(
                "checksums_invalid",
                f"Line {number} lists {name!r} a second time.")
        seen.add(name)
        entries.append(ChecksumEntry(name=name, sha256=digest))
    return entries


def verify_checksums(text: object,
                     actual: Mapping[str, str]) -> Verification:
    """Judge held files against a checksums file:
    `actual` maps each held file's name to the
    SHA-256 of its bytes. Every listed name must be
    held with the listed digest, and every held name
    must be listed — anything else is named in the
    verdict, never silently passed."""
    entries = parse_checksums(text)
    mismatched: list[str] = []
    missing: list[str] = []
    for entry in entries:
        held = actual.get(entry.name)
        if held is None:
            missing.append(entry.name)
        elif held != entry.sha256:
            mismatched.append(entry.name)
    listed = {e.name for e in entries}
    unexpected = [name for name in actual if name not in listed]
    return Verification(
        checked=len(entries),
        mismatched=tuple(sorted(mismatched)),
        missing=tuple(sorted(missing)),
        unexpected=tuple(sorted(unexpected)))


def checksums_to_dict(generated: GeneratedChecksums,
                      full_name: str = "") -> dict:
    """One generated checksums file as the API answers it."""
    return {
        "repository": full_name,
        "tag": generated.release.tag,
        "filename": generated.filename,
        "content_type": generated.content_type,
        "size": generated.size,
        "sha256": generated.sha256,
        "asset_count": generated.asset_count,
        "entries": [
            {"name": e.name, "sha256": e.sha256}
            for e in generated.entries],
    }


def render_checksums_section(full_name: str, tag: str,
                             assets: list[ReleaseAsset]) -> str:
    """The checksums section of a release page: the
    downloadable file named beside the assets, its
    contents shown escaped, and the verification
    instructions in words (the S-260 page law)."""
    text = build_checksums_text(assets)
    if assets:
        listing = (
            "<pre class=\"release-checksums\">"
            + escape_html_text(text.rstrip("\n")) + "</pre>")
        count = (
            f"It lists {len(assets)} "
            + ("asset." if len(assets) == 1 else "assets."))
    else:
        listing = ""
        count = "This release carries no assets yet."
    return (
        '<section class="release-checksums"><h4>Checksums</h4>'
        + "<p>Download "
        + escape_html_text(CHECKSUMS_FILENAME)
        + " beside the assets of "
        + escape_html_text(full_name) + " "
        + escape_html_text(tag) + ". " + count + "</p>"
        + listing
        + "<p>To verify a download, save "
        + escape_html_text(CHECKSUMS_FILENAME)
        + " in the same folder as the downloaded assets "
        + "and run <code>"
        + escape_html_text(VERIFY_COMMAND_POSIX)
        + "</code> (on macOS: <code>"
        + escape_html_text(VERIFY_COMMAND_MACOS)
        + "</code>). Every asset must answer OK. Any "
        + "other answer means that file is not the "
        + "published bytes — do not trust it; download "
        + "it again.</p></section>")


class ReleaseChecksumStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        releases: ReleaseStore,
        assets: ReleaseAssetStore,
        accounts: AccountStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._releases = releases
        self._assets = assets
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    def get_checksums(self, viewer: User | None, owner: object,
                      repo: object, tag: object) -> GeneratedChecksums:
        """Generate the release's checksums file now.
        The asset listing is the gate: it resolves the
        release under the viewer's own visibility
        (S-258) and raises S-259's error shape, whose
        reasons this store carries unchanged."""
        try:
            release = self._releases.get_release(
                viewer, owner, repo, tag)
            assets = self._assets.list_assets(viewer, owner, repo, tag)
        except Exception as exc:
            reason = getattr(exc, "reason", None)
            if reason is None:
                raise
            raise ReleaseChecksumError(reason, str(exc)) from None
        text = build_checksums_text(assets)
        data = text.encode("utf-8")
        ordered = sorted(assets, key=lambda a: (a.name, a.id))
        return GeneratedChecksums(
            release=release, filename=CHECKSUMS_FILENAME,
            content_type=CHECKSUMS_CONTENT_TYPE, text=text,
            data=data, sha256=hashlib.sha256(data).hexdigest(),
            entries=tuple(
                ChecksumEntry(name=a.name, sha256=a.sha256)
                for a in ordered))

    def download_checksums(self, viewer: User | None, owner: object,
                           repo: object, tag: object) -> ChecksumsDownload:
        """Open the checksums download: the same
        generated bytes `get_checksums` builds, under
        the download shape. Nothing is counted — the
        generated file has no row; the assets' own
        counts are untouched."""
        generated = self.get_checksums(viewer, owner, repo, tag)
        return ChecksumsDownload(
            filename=generated.filename,
            content_type=generated.content_type,
            size=generated.size, sha256=generated.sha256,
            asset_count=generated.asset_count, _data=generated.data)
