"""LFS object store (S-060).

Git LFS keeps large files out of git's object store: the repo
carries a small *pointer* file, and the bytes live here,
content-addressed by their SHA-256 (`oid` in LFS language).

Layout — per repository, inside the bare repo directory, the
layout S-058's size accounting already measures:

    <repo>.git/lfs/objects/<ab>/<cd>/<oid>

where `<ab>`/`<cd>` are the oid's first two byte-pairs (the
standard LFS fan-out, so no directory grows unboundedly).

The laws:

- **Integrity is verified by oid on write.** Bytes are hashed
  as they land in a temporary file; only if the digest equals
  the claimed oid (and the length equals the claimed size,
  when one is given) is the file moved into place. A mismatch
  stores *nothing*.
- **Dedupe.** Content already stored is never rewritten: a
  second `put` of the same oid reports `deduped` and the
  existing file is untouched.
- **The oid is the only name.** Oids are validated as exactly
  64 lowercase hex characters before they ever form a path —
  no traversal, no surprises (the S-013 discipline, restated
  for this store).
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

_OID_RE = re.compile(r"^[0-9a-f]{64}$")
_POINTER_VERSION = "version https://git-lfs.github.com/spec/v1"


class LFSError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def validate_oid(oid: object) -> str:
    if not isinstance(oid, str) or not _OID_RE.match(oid):
        raise LFSError("oid_invalid",
                       "An LFS oid is exactly 64 lowercase hex characters.")
    return oid


def oid_for(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_path(repo_path: Path, oid: str) -> Path:
    oid = validate_oid(oid)
    return Path(repo_path) / "lfs" / "objects" / oid[0:2] / oid[2:4] / oid


@dataclass(frozen=True)
class LFSObject:
    oid: str
    size: int
    deduped: bool = False


@dataclass(frozen=True)
class LFSPointer:
    oid: str
    size: int


def make_pointer(oid: str, size: int) -> bytes:
    oid = validate_oid(oid)
    return (f"{_POINTER_VERSION}\noid sha256:{oid}\nsize {size}\n"
            ).encode("utf-8")


def parse_pointer(data: bytes) -> LFSPointer:
    """Parse an LFS pointer file; anything else is refused."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise LFSError("not_a_pointer", "Not an LFS pointer file.") from None
    lines = text.splitlines()
    if not lines or lines[0].strip() != _POINTER_VERSION:
        raise LFSError("not_a_pointer", "Not an LFS pointer file.")
    oid = size = None
    for line in lines[1:]:
        if line.startswith("oid sha256:"):
            oid = line[len("oid sha256:"):].strip()
        elif line.startswith("size "):
            try:
                size = int(line[len("size "):].strip())
            except ValueError:
                raise LFSError("not_a_pointer", "Bad pointer size.") from None
    if oid is None or size is None or size < 0:
        raise LFSError("not_a_pointer", "Pointer is missing its oid or size.")
    return LFSPointer(validate_oid(oid), size)


class LFSStore:
    """The LFS object store of one bare repository."""

    def __init__(self, repo_path: Path):
        self._repo_path = Path(repo_path)

    def path_for(self, oid: str) -> Path:
        return object_path(self._repo_path, oid)

    def has(self, oid: str) -> bool:
        return self.path_for(oid).is_file()

    def put(self, oid: str, data: bytes, *,
            expected_size: int | None = None) -> LFSObject:
        """Store `data` under `oid`, verifying integrity by oid.

        Raises LFSError(`oid_mismatch`) — storing nothing — when
        the bytes do not hash to the claimed oid.
        """
        oid = validate_oid(oid)
        if expected_size is not None and expected_size != len(data):
            raise LFSError("size_mismatch",
                           "The bytes do not match the claimed size.")
        dest = self.path_for(oid)
        if dest.is_file():
            if dest.stat().st_size == len(data) and oid_for(dest.read_bytes()) == oid:
                return LFSObject(oid, len(data), deduped=True)
            raise LFSError("oid_mismatch",
                           "A different object already sits under that oid.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".tmp-{os.getpid()}-{oid[:12]}")
        digest = hashlib.sha256()
        with open(tmp, "wb") as fh:
            digest.update(data)
            fh.write(data)
        if digest.hexdigest() != oid:
            tmp.unlink(missing_ok=True)
            raise LFSError("oid_mismatch",
                           "The bytes do not hash to the claimed oid; "
                           "nothing was stored.")
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)   # atomic publish
        return LFSObject(oid, len(data), deduped=False)

    def read(self, oid: str) -> bytes:
        path = self.path_for(oid)
        if not path.is_file():
            raise LFSError("object_not_found", "No such LFS object.")
        return path.read_bytes()

    def verify(self, oid: str) -> bool:
        """Re-hash the stored object; True only if it still
        matches its oid (bit-rot is named, never hidden)."""
        path = self.path_for(oid)
        if not path.is_file():
            return False
        return oid_for(path.read_bytes()) == oid

    def size_of(self, oid: str) -> int | None:
        path = self.path_for(oid)
        return path.stat().st_size if path.is_file() else None
