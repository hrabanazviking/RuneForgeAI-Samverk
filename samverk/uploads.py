"""Upload handling law (S-012).

Three rules, enforced in one place, in this order:

1. **Size first.** An upload over the policy's cap is refused
   before any other work is spent on it. (Handlers must also cap
   what they *read* off the wire at the same bound — a check after
   an unbounded read is a memory denial-of-service, not a cap.
   S-259 owns the chunked wire path; this module is the law it
   will consult.)
2. **Content sniffing beats declared type.** The type that decides
   acceptance, storage, and later serving is the type the *bytes*
   prove themselves to be (magic numbers for the formats Samverk
   accepts, a strict text test for text), never the type the
   uploader claimed. A concrete declared type that disagrees with
   the sniffed type is a disguise and is refused outright;
   `application/octet-stream` is not a claim and defers to the
   sniff. A disguised *payload* — a script or executable wearing an
   image's name and MIME type — fails here, at the door, which is
   the slice's acceptance shape.
3. **Quarantine first.** Accepted bytes land in a quarantine
   directory under a content-addressed name (SHA-256 of the bytes +
   an extension derived from the *sniffed* type). The uploader's
   filename is never used as a path — so `../../evil.png` is a
   string in a database row, not a route out of quarantine — and
   nothing is served, rendered, or unpacked from quarantine.
   Promotion out of quarantine is always a later, deliberate act
   by the slice that owns the content (avatars S-029, release
   assets S-259, attachments in their turn).

SVG is deliberately not an accepted image type in the default
policy: it is XML that can carry script, and it returns when a
sanitising pipeline (S-010's seam, extended) can vouch for it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .platform_seam import ensure_dir

GENERIC_DECLARED = "application/octet-stream"

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


def sniff_content_type(data: bytes) -> str:
    """The type the bytes prove, from magic numbers / strict text.

    Unknown binary is `application/octet-stream`; callers accept or
    refuse that by policy, but it is never upgraded to a richer type
    on anyone's say-so.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"PK\x03\x04"):
        return "application/zip"
    if data.startswith(b"\x1f\x8b"):
        return "application/gzip"
    if _looks_like_text(data):
        return "text/plain"
    return "application/octet-stream"


def _looks_like_text(data: bytes) -> bool:
    if not data or b"\x00" in data:
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    # Text means printable plus the ordinary whitespace controls.
    return all(c.isprintable() or c in "\t\n\r" for c in text)


@dataclass(frozen=True)
class UploadPolicy:
    max_bytes: int = 10 * 1024 * 1024
    allowed_types: frozenset[str] = frozenset({
        "image/png", "image/jpeg", "image/gif", "image/webp",
        "application/pdf", "text/plain",
    })


DEFAULT_POLICY = UploadPolicy()


class UploadRejected(Exception):
    """An upload refused by the law; `reason` is a stable code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class InspectedUpload:
    detected_type: str
    size: int
    sha256: str


def inspect_upload(
    data: bytes,
    declared_type: str | None = None,
    policy: UploadPolicy = DEFAULT_POLICY,
) -> InspectedUpload:
    """Apply the law to *data*; return what was proven, or raise
    UploadRejected with a reason code (empty / too_large /
    type_not_allowed / type_mismatch)."""
    if not data:
        raise UploadRejected("empty")
    if len(data) > policy.max_bytes:
        raise UploadRejected("too_large")
    detected = sniff_content_type(data)
    if detected not in policy.allowed_types:
        raise UploadRejected("type_not_allowed")
    if declared_type:
        declared = declared_type.split(";")[0].strip().lower()
        if declared and declared != GENERIC_DECLARED and declared != detected:
            raise UploadRejected("type_mismatch")
    return InspectedUpload(
        detected_type=detected,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def save_to_quarantine(
    data_root: Path,
    data: bytes,
    declared_type: str | None = None,
    policy: UploadPolicy = DEFAULT_POLICY,
) -> Path:
    """Inspect *data* and, only if accepted, write it into
    `<data_root>/quarantine/` under its content-addressed name.
    Rejected uploads write nothing. The uploader's filename plays
    no part in the path — it is not a parameter here at all."""
    inspected = inspect_upload(data, declared_type=declared_type, policy=policy)
    quarantine = ensure_dir(Path(data_root) / "quarantine")
    extension = _EXTENSION_FOR_TYPE.get(inspected.detected_type, ".bin")
    path = quarantine / f"{inspected.sha256}{extension}"
    if not path.exists():
        # Owner-only, like the secrets file: quarantined bytes are
        # untrusted until promoted, and untrusted stays private.
        path.write_bytes(data)
        try:
            path.chmod(0o600)
        except OSError:
            pass  # non-POSIX filesystems govern their own ACLs
    return path
