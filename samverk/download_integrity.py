"""Download integrity (S-271).

Assets served with digests in headers; interrupted
downloads resumable where the client supports ranges.

Every downloadable asset Samverk serves -- a release
asset (S-259), the generated checksums file (S-260),
a CI artifact (S-266) -- already *stores* its SHA-256:
S-012's promotion computed it over the assembled
bytes and the row keeps it. What no door did until
now was *say* it on the wire, or let a client whose
download died at byte 900,000 ask for the rest
instead of starting over. This module is that law,
in one place, over all three doors:

- **Digests in headers, on every answer.** Every
  served download -- full (200), partial (206), and
  even the not-modified answer (304) -- carries the
  asset's digest twice over: `ETag` (the strong tag,
  S-239's quoted-hex shape, so the existing
  conditional machinery judges it unchanged) and
  `Digest` / `Repr-Digest` (RFC 9530: `sha-256=`
  over the raw digest, base64). The hex digest also
  rides the API dict (`sha256`), exactly as the
  stores have always stated it, so a client can
  verify the bytes it holds against three statements
  that must all agree -- and `verify_download` is
  that judgement in code for callers holding bytes.
- **Ranges resume an interrupted download.** A
  download answers `Accept-Ranges: bytes` and
  honours one `Range: bytes=...` per request --
  `start-end`, `start-`, or the `-suffix` form --
  with a 206 whose `Content-Range` names exactly
  the slice served, so a client reassembly is just
  the concatenation of the slices it asked for (the
  battery proves byte-for-byte reassembly of a real
  asset from two ranges). One range only: a
  multi-range request is refused `range_invalid`
  rather than answered with a multipart body no
  face here speaks. A range that cannot be served
  from this file -- it starts at or beyond the end,
  ends before it starts, asks for a zero suffix, or
  the file is empty -- is refused
  `range_not_satisfiable` (416, registered in
  S-240's registry beside `range_invalid` at 400);
  a range is never silently clamped into a
  different slice than the one asked for, except
  the standard's own end-clamp (an end past the
  file serves to the file's end, and says so in
  `Content-Range`).
- **`If-Range` guards the resume.** A resume is
  only honest if the bytes did not change under
  it: when `If-Range` carries the ETag the client
  already holds and it is *strongly* equal to the
  asset's current tag, the range is served; any
  other value -- a different tag, a weak tag, a
  date (this door issues no `Last-Modified`, so a
  date can never be proven equal) -- and the range
  is ignored and the whole current file is served
  with a 200, never a slice of a file the client
  does not hold. `If-None-Match` is judged first,
  with S-239's weak comparison: a match answers
  304 with the digest headers and no body.
- **Counting stays the doors' own (S-259/S-266).**
  The facade plans *before* it opens: the asset is
  read uncounted (`get_asset` / `get_artifact` /
  `get_checksums`), the plan is judged, and only a
  byte-serving answer (200 or 206) opens the
  underlying download -- exactly once, so each
  opens counts exactly once through the door's own
  transaction. A refusal (`range_invalid`,
  `range_not_satisfiable`) and a 304 open nothing
  and count nothing; the battery proves the counts.
  The checksums file has no row and counts nothing,
  as S-260 left it.
- **Visibility is the doors' own.** The facade
  resolves through S-259's, S-260's and S-266's
  gates unchanged and carries their reasons
  verbatim (`repo_not_found`, `release_not_found`,
  `asset_not_found`, `artifact_expired`, ...):
  a draft's asset ranges are as private as the
  asset, and a private repository's are the uniform
  `repo_not_found`. Planning reads the row the gate
  already judged; it widens nothing.

Download acts carry no verb of their own in the
frozen taxonomy vocabulary and are not witnessed --
no new taxonomy event: 133 stand (33 auth / 87 repo
/ 13 admin). No migration: the digests and sizes
this slice serves are the rows migrations 102 and
105 already keep; schema 106 stands. The Part XIII
gate (S-272) counts this battery's checksum
round-trip with the rest of the release battery.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass

from .api_pagination import if_none_match_matches
from .error_shape import problem_from_error, problem_to_dict
from .escaping import escape_html_text

__all__ = [
    "DIGEST_ALGORITHM", "DownloadIntegrityError",
    "DownloadIntegrityStore", "DownloadPlan",
    "DownloadResponse", "RangeSpec", "digest_header_value",
    "digest_of", "error_to_dict", "etag_for_digest",
    "if_range_applies", "integrity_headers", "parse_range_header",
    "plan_download", "render_download_integrity_section",
    "response_to_dict", "serve_bytes", "serve_opened",
    "verify_download",
]

DIGEST_ALGORITHM = "sha-256"
_BLOCK = 64 * 1024


class DownloadIntegrityError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def error_to_dict(exc: DownloadIntegrityError) -> dict:
    """One refusal in S-240's one problem format."""
    return problem_to_dict(problem_from_error(exc))


# ------------------------------------------------------------------
# Digests and tags
# ------------------------------------------------------------------

def digest_of(data: bytes) -> str:
    """The SHA-256 of held bytes, hex -- the digest
    every store here keeps and every header states."""
    return hashlib.sha256(data).hexdigest()


def verify_download(data: bytes, sha256: object) -> bool:
    """Whether held bytes are the bytes a digest
    names. A digest that is not a string proves
    nothing and judges False, never an exception."""
    return isinstance(sha256, str) and digest_of(data) == sha256


def etag_for_digest(sha256: str) -> str:
    """The strong ETag of one asset: its SHA-256,
    quoted as HTTP requires (S-239's shape)."""
    return f'"{sha256}"'


def digest_header_value(sha256: str) -> str:
    """The RFC 9530 digest header value for one
    hex SHA-256: `sha-256=:<base64 of the raw
    digest bytes>:`. The same digest the ETag
    states in hex, stated here in the digest
    headers' own encoding -- both must agree."""
    raw = bytes.fromhex(sha256)
    return f"{DIGEST_ALGORITHM}=:{base64.b64encode(raw).decode('ascii')}:"


# ------------------------------------------------------------------
# Ranges
# ------------------------------------------------------------------

@dataclass(frozen=True)
class RangeSpec:
    """One satisfiable byte range of one file:
    `start` and `end` are inclusive byte offsets
    in a file of `size` bytes."""

    start: int
    end: int
    size: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @property
    def content_range(self) -> str:
        return f"bytes {self.start}-{self.end}/{self.size}"


def _range_int(text: str) -> int | None:
    if not text or not text.isdigit():
        return None
    return int(text)


def parse_range_header(header: object, size: int) -> RangeSpec | None:
    """Read one `Range` header against a file of
    *size* bytes. None (the header itself) means no
    range was asked for and the whole file is owed.
    One range only, in the three standard forms;
    anything malformed is refused `range_invalid`,
    anything well-formed that this file cannot
    serve is refused `range_not_satisfiable` --
    a range is never silently rewritten."""
    if header is None:
        return None
    if not isinstance(header, str):
        raise DownloadIntegrityError(
            "range_invalid", "A Range header is a header string.")
    text = header.strip()
    unit, sep, spec = text.partition("=")
    if sep != "=" or unit.strip().lower() != "bytes" or not spec.strip():
        raise DownloadIntegrityError(
            "range_invalid",
            "A Range header reads 'bytes=<range>'.")
    spec = spec.strip()
    if "," in spec:
        raise DownloadIntegrityError(
            "range_invalid",
            "One range at a time: ask again for the next part.")
    first, dash, last = spec.partition("-")
    if dash != "-" or "-" in last:
        raise DownloadIntegrityError(
            "range_invalid",
            "A range reads '<start>-<end>', '<start>-' or '-<suffix>'.")
    first, last = first.strip(), last.strip()
    if not first and not last:
        raise DownloadIntegrityError(
            "range_invalid",
            "A range names a start, an end, or a suffix length.")
    if size <= 0:
        raise DownloadIntegrityError(
            "range_not_satisfiable",
            "This file is empty; it has no byte range to serve.")
    if not first:
        suffix = _range_int(last)
        if suffix is None:
            raise DownloadIntegrityError(
                "range_invalid", "A suffix length is a whole number.")
        if suffix == 0:
            raise DownloadIntegrityError(
                "range_not_satisfiable",
                "A range of the last zero bytes serves nothing.")
        return RangeSpec(start=max(size - suffix, 0), end=size - 1,
                         size=size)
    start = _range_int(first)
    if start is None:
        raise DownloadIntegrityError(
            "range_invalid", "A range start is a whole number.")
    if start >= size:
        raise DownloadIntegrityError(
            "range_not_satisfiable",
            f"Byte {start} is beyond this file's {size} bytes.")
    if not last:
        return RangeSpec(start=start, end=size - 1, size=size)
    end = _range_int(last)
    if end is None:
        raise DownloadIntegrityError(
            "range_invalid", "A range end is a whole number.")
    if end < start:
        raise DownloadIntegrityError(
            "range_not_satisfiable",
            "A range ends before it starts.")
    return RangeSpec(start=start, end=min(end, size - 1), size=size)


def if_range_applies(header: object, etag: str) -> bool:
    """Whether a `Range` may be honoured under one
    `If-Range` header: no header, the range stands;
    a header strongly equal to the asset's current
    ETag, the range stands; anything else -- a
    different tag, a weak tag, a date this door
    cannot prove -- the range falls and the whole
    current file is owed instead. A header of the
    wrong type is refused `header_invalid`."""
    if header is None:
        return True
    if not isinstance(header, str):
        raise DownloadIntegrityError(
            "header_invalid", "If-Range must be a header string.")
    return header.strip() == etag


# ------------------------------------------------------------------
# The plan and the response
# ------------------------------------------------------------------

@dataclass(frozen=True)
class DownloadPlan:
    """The judgement for one download request,
    before any byte is opened: the status owed
    (200 whole, 206 partial, 304 not modified),
    the inclusive slice owed (None when no body
    is owed), the asset's full size and digest,
    and the exact headers the answer carries."""

    status: int
    size: int
    sha256: str
    etag: str
    spec: RangeSpec | None
    headers: dict

    @property
    def content_length(self) -> int:
        if self.status == 304:
            return 0
        if self.spec is not None:
            return self.spec.length
        return self.size


def integrity_headers(sha256: str, size: int, content_type: str,
                      filename: str, *, status: int = 200,
                      spec: RangeSpec | None = None) -> dict:
    """The headers of one download answer: the
    digest stated as ETag and as RFC 9530 digest
    headers, ranges advertised, the disposition
    an attachment (the doors' own law), and --
    for a partial answer -- the slice named in
    `Content-Range` and a `Content-Length` of the
    slice, never of the whole file."""
    headers = {
        "Content-Type": content_type,
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Accept-Ranges": "bytes",
        "ETag": etag_for_digest(sha256),
        "Digest": digest_header_value(sha256),
        "Repr-Digest": digest_header_value(sha256),
    }
    if status == 206 and spec is not None:
        headers["Content-Range"] = spec.content_range
        headers["Content-Length"] = str(spec.length)
    elif status == 304:
        headers["Content-Length"] = "0"
    else:
        headers["Content-Length"] = str(size)
    return headers


def plan_download(size: int, sha256: str, content_type: str,
                  filename: str, *, range_header: object = None,
                  if_range: object = None,
                  if_none_match: object = None) -> DownloadPlan:
    """Judge one download request against one
    asset's size and stored digest. `If-None-Match`
    is judged first (S-239's weak comparison): a
    match is a 304 owing no body and no range. A
    range is then parsed and judged -- refusals
    raise before anything is opened -- and
    `If-Range` decides whether it stands."""
    etag = etag_for_digest(sha256)
    try:
        matched = if_none_match_matches(if_none_match, etag)
    except Exception as exc:
        reason = getattr(exc, "reason", None)
        if reason is None:
            raise
        raise DownloadIntegrityError(reason, str(exc)) from None
    if matched:
        headers = integrity_headers(
            sha256, size, content_type, filename, status=304)
        return DownloadPlan(status=304, size=size, sha256=sha256,
                            etag=etag, spec=None, headers=headers)
    spec = parse_range_header(range_header, size)
    if spec is not None and not if_range_applies(if_range, etag):
        spec = None
    status = 206 if spec is not None else 200
    headers = integrity_headers(
        sha256, size, content_type, filename, status=status, spec=spec)
    return DownloadPlan(status=status, size=size, sha256=sha256,
                        etag=etag, spec=spec, headers=headers)


def _slice_blocks(blocks: Iterator[bytes],
                  spec: RangeSpec | None) -> Iterator[bytes]:
    """The blocks of one opened download, cut to
    *spec* (or whole, when spec is None): bytes
    before the slice are passed over, bytes after
    it are never yielded, and the source is not
    read past the slice's end."""
    if spec is None:
        yield from blocks
        return
    remaining_skip = spec.start
    remaining_take = spec.length
    for block in blocks:
        if remaining_take <= 0:
            return
        if remaining_skip:
            if len(block) <= remaining_skip:
                remaining_skip -= len(block)
                continue
            block = block[remaining_skip:]
            remaining_skip = 0
        if len(block) > remaining_take:
            block = block[:remaining_take]
        remaining_take -= len(block)
        if block:
            yield block


@dataclass
class DownloadResponse:
    """One judged download answer: the plan's
    status and headers, the asset's identity, and
    the owed bytes behind a block iterator. A 304
    owes no bytes and its iterator is empty."""

    status: int
    headers: dict
    filename: str
    content_type: str
    size: int
    sha256: str
    etag: str
    spec: RangeSpec | None
    _open: object = None  # Callable[[], Iterator[bytes]] | None

    @property
    def is_partial(self) -> bool:
        return self.status == 206

    @property
    def content_length(self) -> int:
        if self.status == 304:
            return 0
        if self.spec is not None:
            return self.spec.length
        return self.size

    def __iter__(self) -> Iterator[bytes]:
        if self.status == 304 or self._open is None:
            return
        yield from _slice_blocks(self._open(), self.spec)

    def read_all(self) -> bytes:
        return b"".join(self)


def _respond(plan: DownloadPlan, filename: str, content_type: str,
             opener) -> DownloadResponse:
    return DownloadResponse(
        status=plan.status, headers=plan.headers, filename=filename,
        content_type=content_type, size=plan.size, sha256=plan.sha256,
        etag=plan.etag, spec=plan.spec,
        _open=None if plan.status == 304 else opener)


def serve_opened(opened, *, range_header: object = None,
                 if_range: object = None,
                 if_none_match: object = None) -> DownloadResponse:
    """Serve one already-opened download (an
    S-259 `AssetDownload`, an S-266
    `ArtifactDownload`, an S-260
    `ChecksumsDownload` -- anything with filename,
    content type, size, digest and a block
    iterator) under this slice's law. Callers who
    need the counting law judged *before* opening
    go through the store facade below instead."""
    plan = plan_download(
        opened.size, opened.sha256, opened.content_type,
        opened.filename, range_header=range_header,
        if_range=if_range, if_none_match=if_none_match)
    return _respond(plan, opened.filename, opened.content_type,
                    lambda: iter(opened))


def serve_bytes(data: bytes, filename: str, content_type: str, *,
                range_header: object = None,
                if_range: object = None,
                if_none_match: object = None) -> DownloadResponse:
    """Serve held bytes under this slice's law:
    the digest is computed over the bytes, so the
    headers state exactly what is served."""
    plan = plan_download(
        len(data), digest_of(data), content_type, filename,
        range_header=range_header, if_range=if_range,
        if_none_match=if_none_match)

    def opener() -> Iterator[bytes]:
        for start in range(0, len(data), _BLOCK):
            yield data[start:start + _BLOCK]

    return _respond(plan, filename, content_type, opener)


def response_to_dict(response: DownloadResponse) -> dict:
    """One download answer as the API states it:
    the headers' facts as data, so a script can
    plan a resume without parsing header text."""
    return {
        "status": response.status,
        "filename": response.filename,
        "content_type": response.content_type,
        "size": response.size,
        "sha256": response.sha256,
        "etag": response.etag,
        "digest": digest_header_value(response.sha256),
        "accept_ranges": "bytes",
        "content_length": response.content_length,
        "range": (None if response.spec is None else {
            "start": response.spec.start,
            "end": response.spec.end,
            "content_range": response.spec.content_range,
        }),
        "headers": dict(response.headers),
    }


def render_download_integrity_section(filename: str = "") -> str:
    """The integrity law in words, for a download
    page: what the digest headers prove and how a
    stopped download is resumed. Every value
    escaped through S-010."""
    named = (
        f" for {escape_html_text(filename)}" if filename else "")
    return (
        '<section class="download-integrity"><h4>Download integrity</h4>'
        + f"<p>Every download{named} is served with its SHA-256 "
        + "digest in the <code>Digest</code> and <code>ETag</code> "
        + "headers, and with <code>Accept-Ranges: bytes</code>. "
        + "Check the digest of the file you hold against the header: "
        + "if they differ, the file is not the published bytes -- "
        + "do not trust it; download it again. If a download stops "
        + "part-way, resume it instead of starting over: send the "
        + "bytes you still need as one <code>Range: bytes=</code> "
        + "request with the <code>If-Range</code> header set to the "
        + "ETag of the first answer, and the server answers 206 "
        + "with exactly that part -- or, if the file has changed, "
        + "the whole new file, never a slice of a file you do not "
        + "hold.</p></section>")


# ------------------------------------------------------------------
# The facade over the three doors
# ------------------------------------------------------------------

class DownloadIntegrityStore:
    """The three asset doors under this slice's
    law. Planning happens on the uncounted read;
    a byte-serving plan opens the door's own
    download exactly once (and so counts exactly
    once, S-259/S-266); a refusal or a 304 opens
    nothing. The doors' errors are carried with
    their reasons verbatim."""

    def __init__(self, assets=None, checksums=None, ci_api=None):
        self._assets = assets
        self._checksums = checksums
        self._ci = ci_api

    @staticmethod
    def _carried(exc: Exception) -> DownloadIntegrityError:
        return DownloadIntegrityError(
            getattr(exc, "reason", "download_failed"), str(exc))

    def download_asset(self, viewer, owner, repo, tag, name, *,
                       range_header: object = None,
                       if_range: object = None,
                       if_none_match: object = None) -> DownloadResponse:
        """One release asset (S-259), with digests
        and ranges: gated by the release's own
        visibility through the asset store, counted
        once per byte-serving answer."""
        try:
            asset = self._assets.get_asset(viewer, owner, repo, tag, name)
        except Exception as exc:
            raise self._carried(exc) from None
        plan = plan_download(
            asset.size, asset.sha256, asset.content_type, asset.name,
            range_header=range_header, if_range=if_range,
            if_none_match=if_none_match)
        if plan.status == 304:
            return _respond(plan, asset.name, asset.content_type, None)
        try:
            opened = self._assets.download_asset(
                viewer, owner, repo, tag, name)
        except Exception as exc:
            raise self._carried(exc) from None
        return _respond(plan, opened.filename, opened.content_type,
                        lambda: iter(opened))

    def download_checksums(self, viewer, owner, repo, tag, *,
                           range_header: object = None,
                           if_range: object = None,
                           if_none_match: object = None) -> DownloadResponse:
        """The generated checksums file (S-260),
        with digests and ranges. It has no row and
        counts nothing, exactly as its own door
        left it; its digest is the digest of the
        generated bytes themselves."""
        try:
            generated = self._checksums.get_checksums(
                viewer, owner, repo, tag)
        except Exception as exc:
            raise self._carried(exc) from None
        plan = plan_download(
            generated.size, generated.sha256, generated.content_type,
            generated.filename, range_header=range_header,
            if_range=if_range, if_none_match=if_none_match)
        if plan.status == 304:
            return _respond(plan, generated.filename,
                            generated.content_type, None)
        opened = self._checksums.download_checksums(
            viewer, owner, repo, tag)
        return _respond(plan, opened.filename, opened.content_type,
                        lambda: iter(opened))

    def download_artifact(self, header, owner, repo, artifact_id, *,
                          range_header: object = None,
                          if_range: object = None,
                          if_none_match: object = None) -> DownloadResponse:
        """One CI artifact (S-266), with digests and
        ranges: resolved through S-238's door by the
        artifacts face itself, retention judged by
        its own download, counted once per
        byte-serving answer."""
        if self._ci is None:
            raise DownloadIntegrityError(
                "resource_unknown",
                "This store carries no CI artifacts door.")
        try:
            info = self._ci.get_artifact(header, owner, repo, artifact_id)
        except Exception as exc:
            raise self._carried(exc) from None
        plan = plan_download(
            int(info["size"]), str(info["sha256"]),
            str(info["content_type"]), str(info["name"]),
            range_header=range_header, if_range=if_range,
            if_none_match=if_none_match)
        if plan.status == 304:
            return _respond(plan, str(info["name"]),
                            str(info["content_type"]), None)
        try:
            opened = self._ci.download_artifact(
                header, owner, repo, artifact_id)
        except Exception as exc:
            raise self._carried(exc) from None
        return _respond(plan, opened.filename, opened.content_type,
                        lambda: iter(opened))
