"""S-409 — Path and encoding discipline.

Roadmap line: stored data (refs, paths in the DB, config) uses
one canonical form; no OS-specific separator or line ending ever
leaks into stored state or the wire.

THE CANONICAL FORM
- Encoding: UTF-8, strict. No BOM, no lone surrogates, no NUL.
- Unicode: NFC. The same text is the same bytes on every OS;
  a decomposed sequence stored on one machine must not become a
  different string when read on another.
- Line endings: LF only. CRLF and lone CR are input dirt to be
  normalised at the seam, never stored forms.
- Path separator: forward slash `/`, on every OS. A stored path
  is a PurePosix-shaped string: relative, no drive letter, no
  empty / `.` / `..` components, no trailing slash, and no
  component ending in a dot or space (Windows silently strips
  those, aliasing two stored paths to one file — the S-013
  trailing-dot law, applied per component here).

THE LAW
1. One seam. Host filesystem paths become stored paths only
   through `stored_form` (which reads the host path's posix
   rendering, never `str(path)` — on Windows `str` yields
   backslashes). Stored text and wire bytes are produced only
   through `canonical_text` / `canonical_bytes`. Files Samverk
   writes as text go through `write_canonical_text`, which pins
   UTF-8 and LF explicitly instead of trusting the platform
   default newline translation.
2. Refuse, never guess. A value that cannot be canonicalised
   (absolute path, drive form, `..`, control characters, invalid
   UTF-8) is refused with a stable machine-readable `reason`
   (the S-013 / S-408 ValueError convention). A value that is
   merely non-canonical (backslashes, CRLF, decomposed unicode)
   is either normalised by the `canonical_*` functions or
   refused by the `check_*` functions — the caller chooses
   explicitly; nothing is silently rewritten at a check seam.
3. Audit, don't assume. `audit_source_tree` scans real bytes:
   any package source carrying CRLF, invalid UTF-8, or non-NFC
   text is named. The S-409 audit findings for the seams that
   existed before this slice live in docs/PATH_ENCODING.md —
   including the honest remainders this slice registers rather
   than rewrites.
"""
from __future__ import annotations

import os
import unicodedata
from pathlib import Path, PurePath

__all__ = [
    "CANONICAL_ENCODING", "CANONICAL_LINE_ENDING", "CANONICAL_SEPARATOR",
    "PathEncodingError", "canonical_text", "is_canonical_text",
    "canonical_path", "check_stored_path", "stored_form",
    "canonical_bytes", "check_wire_bytes", "write_canonical_text",
    "audit_source_tree",
]

CANONICAL_ENCODING = "utf-8"
CANONICAL_LINE_ENDING = "\n"
CANONICAL_SEPARATOR = "/"


class PathEncodingError(ValueError):
    """A value refused by the S-409 law; `reason` is stable."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _check_text_basics(text):
    if not isinstance(text, str):
        raise PathEncodingError("not_text", repr(type(text)))
    if "\x00" in text:
        raise PathEncodingError("nul_character", "NUL in stored text")
    for ch in text:
        if ord(ch) < 0x20 and ch not in "\n\t":
            raise PathEncodingError(
                "control_character", f"U+{ord(ch):04X} in stored text")
    try:
        text.encode(CANONICAL_ENCODING)
    except UnicodeEncodeError:
        raise PathEncodingError(
            "unencodable", "text is not encodable as UTF-8 "
            "(lone surrogate?)")


def canonical_text(text):
    """The canonical form of stored text: NFC, LF endings.
    Refuses NUL, stray control characters, and text that is not
    UTF-8-encodable. Idempotent by construction."""
    if not isinstance(text, str):
        raise PathEncodingError("not_text", repr(type(text)))
    # Line endings normalise FIRST: CR is input dirt here, not a
    # control-character offence — the basics check below then
    # judges the normalised text (a path, which never passes
    # through here, still refuses CR via _check_text_basics).
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    _check_text_basics(text)
    return unicodedata.normalize("NFC", text)


def is_canonical_text(text):
    """True iff *text* already stands in canonical form."""
    try:
        return canonical_text(text) == text
    except PathEncodingError:
        return False


def canonical_path(path):
    """The canonical form of a stored (repository-relative) path.

    Accepts a string in either separator flavour or a host path
    object (read through its posix rendering). Backslashes are
    normalised to `/`; the result is NFC with no empty, `.` or
    `..` components. Absolute forms, drive forms, trailing
    slashes, and components ending in a dot or space are REFUSED
    (they alias or escape on some OS), never silently repaired.
    """
    if isinstance(path, PurePath):
        text = path.as_posix()
    else:
        text = str(path)
    _check_text_basics(text)
    text = unicodedata.normalize("NFC", text.replace("\\", "/"))
    if not text:
        raise PathEncodingError("empty_path", "stored path is empty")
    if text.startswith("/"):
        raise PathEncodingError("absolute_path", repr(text))
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha():
        raise PathEncodingError("drive_path", repr(text))
    if text.endswith("/"):
        raise PathEncodingError("trailing_separator", repr(text))
    parts = text.split("/")
    for part in parts:
        if part == "":
            raise PathEncodingError("empty_component", repr(text))
        if part == ".":
            raise PathEncodingError("dot_component", repr(text))
        if part == "..":
            raise PathEncodingError("dotdot_component", repr(text))
        if part.endswith(".") or part.endswith(" "):
            raise PathEncodingError(
                "trailing_dot_or_space",
                f"component {part!r} would alias on Windows")
    return "/".join(parts)


def check_stored_path(path):
    """Validate a value that claims to already be a stored path.
    Returns it unchanged when canonical; raises with reason
    'not_canonical' (naming the canonical form) when it is merely
    un-normalised, or the specific refusal reason otherwise."""
    text = path.as_posix() if isinstance(path, PurePath) else str(path)
    canon = canonical_path(text)
    if canon != text:
        raise PathEncodingError(
            "not_canonical", f"{text!r} canonicalises to {canon!r}")
    return text


def stored_form(host_path):
    """THE seam from a host filesystem path to stored form.
    Reads the path's posix rendering — never `str(path)`, which
    leaks backslashes on Windows — then canonicalises."""
    p = Path(host_path)
    return canonical_path(p.as_posix())


def canonical_bytes(data):
    """The canonical wire/stored bytes: strict UTF-8 decode,
    canonical text, UTF-8 encode. Invalid UTF-8 is refused."""
    if not isinstance(data, (bytes, bytearray)):
        raise PathEncodingError("not_bytes", repr(type(data)))
    try:
        text = bytes(data).decode(CANONICAL_ENCODING)
    except UnicodeDecodeError as exc:
        raise PathEncodingError("invalid_utf8", str(exc))
    return canonical_text(text).encode(CANONICAL_ENCODING)


def check_wire_bytes(data):
    """Validate bytes that claim to already be canonical wire
    form; returns them unchanged or raises 'not_canonical'."""
    canon = canonical_bytes(data)
    if canon != bytes(data):
        raise PathEncodingError(
            "not_canonical", "bytes differ from their canonical form")
    return bytes(data)


def write_canonical_text(path, text):
    """Write *text* to *path* in canonical form: the text is
    canonicalised, then written as UTF-8 with newline translation
    pinned to LF — the platform default (CRLF on Windows) never
    decides what lands on disk. Returns the path."""
    p = Path(path)
    with p.open("w", encoding=CANONICAL_ENCODING, newline="\n") as fh:
        fh.write(canonical_text(text))
    return p


def audit_source_tree(root):
    """Audit real bytes under *root*: every `.py` file is read as
    bytes and checked for CRLF/CR line endings, invalid UTF-8,
    and non-NFC text. Returns a dict of sorted name lists plus
    `clean`. This audits byte facts, not intentions."""
    root = Path(root)
    crlf_files, non_utf8_files, non_nfc_files = [], [], []
    scanned = 0
    for entry in sorted(root.rglob("*.py")):
        if not entry.is_file():
            continue
        scanned += 1
        data = entry.read_bytes()
        rel = entry.relative_to(root).as_posix()
        if b"\r" in data:
            crlf_files.append(rel)
        try:
            text = data.decode(CANONICAL_ENCODING)
        except UnicodeDecodeError:
            non_utf8_files.append(rel)
            continue
        if unicodedata.normalize("NFC", text) != text:
            non_nfc_files.append(rel)
    return {
        "files_scanned": scanned,
        "crlf_files": crlf_files,
        "non_utf8_files": non_utf8_files,
        "non_nfc_files": non_nfc_files,
        "clean": not (crlf_files or non_utf8_files or non_nfc_files),
    }
