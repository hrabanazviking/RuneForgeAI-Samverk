"""Operator key custody (S-020).

Instance keys — the signing/encryption roots later parts build
on (token signing, at-rest encryption in Part XVII's CI secrets,
webhook signatures) — are *operator custody*, and this module is
the custodian:

- **Generated at install.** `ensure_instance_key` creates the
  current key for a purpose from the CSPRNG (256 bits) the first
  time it is asked, and returns the existing one thereafter —
  generation is idempotent and never silently replaces a key.
- **Files, never the database** (S-003's law, applied to keys):
  key material lives only in `<data_root>/keys/`, one file per
  version — `instance-<purpose>-v<N>.key`, hex-encoded, mode
  600 written with `os.open` so the file is never world-readable
  for a single instant. Loading a key file with loose
  permissions is refused, fail-closed, the fix named — the same
  stance as the secrets file. The database may learn a key's
  *fingerprint* (below); it never learns key material.
- **Identified by fingerprint.** A key's public name is the
  first 16 hex of its SHA-256 — safe to log, show in UIs, and
  write in audit entries; useless for reconstructing the key.
- **Rotatable, with history kept.** `rotate_key` mints version
  N+1 and makes it current; earlier versions stay loadable by
  version number, because signatures and ciphertexts made under
  them must keep verifying — rotation is a drill, not a bonfire.
  When an audit log is supplied, rotation writes
  `admin.key.rotate` (S-008 taxonomy) with old and new
  fingerprints. There is deliberately **no delete**: retiring a
  version is an operator act on files, per the runbook
  (`docs/KEY_CUSTODY_RUNBOOK.md`), after every consumer of that
  version is gone.

Purposes are a small validated shape (`signing`, `encryption`,
… — lowercase slug), not a registry: a new purpose is a new
key family, created by the slice that first needs it.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets as _secrets
from dataclasses import dataclass
from pathlib import Path

from . import platform_seam
from .platform_seam import ensure_dir

KEY_BYTES = 32
_PURPOSE_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_FILE_RE = re.compile(r"^instance-([a-z][a-z0-9-]*)-v(\d+)\.key$")

ROTATE_EVENT = "admin.key.rotate"


class KeyCustodyError(Exception):
    """A custody-law violation: bad purpose, loose permissions,
    or missing key material."""


@dataclass(frozen=True)
class KeyRecord:
    purpose: str
    version: int
    fingerprint: str
    path: Path


def _validate_purpose(purpose: object) -> str:
    if not isinstance(purpose, str) or not _PURPOSE_RE.match(purpose):
        raise KeyCustodyError(f"unlawful key purpose {purpose!r}")
    return purpose


def keys_dir(data_root: Path) -> Path:
    return Path(data_root) / "keys"


def fingerprint_of(material: bytes) -> str:
    return hashlib.sha256(material).hexdigest()[:16]


def _versions(data_root: Path, purpose: str) -> list[int]:
    directory = keys_dir(data_root)
    if not directory.is_dir():
        return []
    found = []
    for entry in directory.iterdir():
        match = _FILE_RE.match(entry.name)
        if match and match.group(1) == purpose:
            found.append(int(match.group(2)))
    return sorted(found)


def _path_for(data_root: Path, purpose: str, version: int) -> Path:
    return keys_dir(data_root) / f"instance-{purpose}-v{version}.key"


def _write_key_file(path: Path, material: bytes) -> None:
    """Write key material with mode 600 from the first instant:
    the mode goes to os.open, not a chmod after the fact."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, material.hex().encode("ascii") + b"\n")
    finally:
        os.close(fd)


def _record(data_root: Path, purpose: str, version: int) -> KeyRecord:
    material = load_key(data_root, purpose, version)
    return KeyRecord(
        purpose=purpose, version=version,
        fingerprint=fingerprint_of(material),
        path=_path_for(data_root, purpose, version))


def _mint(data_root: Path, purpose: str, version: int) -> KeyRecord:
    ensure_dir(keys_dir(data_root))
    path = _path_for(data_root, purpose, version)
    _write_key_file(path, _secrets.token_bytes(KEY_BYTES))
    return _record(data_root, purpose, version)


def ensure_instance_key(data_root: Path, purpose: str = "signing") -> KeyRecord:
    """The current key for *purpose*, generated if none exists.
    Idempotent: an existing current key is returned, never
    replaced."""
    purpose = _validate_purpose(purpose)
    versions = _versions(data_root, purpose)
    if versions:
        return _record(data_root, purpose, versions[-1])
    return _mint(data_root, purpose, 1)


def current_key(data_root: Path, purpose: str = "signing") -> KeyRecord | None:
    purpose = _validate_purpose(purpose)
    versions = _versions(data_root, purpose)
    return _record(data_root, purpose, versions[-1]) if versions else None


def list_key_versions(data_root: Path, purpose: str = "signing") -> list[KeyRecord]:
    purpose = _validate_purpose(purpose)
    return [_record(data_root, purpose, v)
            for v in _versions(data_root, purpose)]


def load_key(data_root: Path, purpose: str = "signing",
             version: int | None = None) -> bytes:
    """The raw key material for *purpose* (current version unless
    *version* names one). Refuses a loosely-permissioned file,
    fail-closed, exactly like the S-003 secrets file."""
    purpose = _validate_purpose(purpose)
    versions = _versions(data_root, purpose)
    if not versions:
        raise KeyCustodyError(f"no key exists for purpose {purpose!r}")
    chosen = versions[-1] if version is None else version
    path = _path_for(data_root, purpose, chosen)
    if not path.is_file():
        raise KeyCustodyError(
            f"no version {chosen} of the {purpose!r} key exists")
    if not platform_seam.secret_file_is_private(path):
        raise KeyCustodyError(
            f"key file {path} is readable by group/other users; "
            f"refusing to load it. Fix: chmod 600 {path}")
    try:
        return bytes.fromhex(path.read_text(encoding="ascii").strip())
    except ValueError:
        raise KeyCustodyError(
            f"key file {path} does not contain hex key material") from None


def rotate_key(data_root: Path, purpose: str = "signing",
               audit=None) -> KeyRecord:
    """Mint the next version and make it current; earlier
    versions remain loadable. With *audit* (an AuditLog), the
    rotation is recorded as `admin.key.rotate` with the old and
    new fingerprints — never key material."""
    purpose = _validate_purpose(purpose)
    versions = _versions(data_root, purpose)
    old = _record(data_root, purpose, versions[-1]) if versions else None
    new = _mint(data_root, purpose, (versions[-1] + 1) if versions else 1)
    if audit is not None:
        audit.append(
            actor_kind="operator",
            action=ROTATE_EVENT,
            target_kind="instance_key",
            target_id=purpose,
            outcome="rotated",
            detail={
                "from_version": old.version if old else None,
                "from_fingerprint": old.fingerprint if old else None,
                "to_version": new.version,
                "to_fingerprint": new.fingerprint,
            },
        )
    return new
