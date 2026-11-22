"""Release packaging (S-400).

Roadmap S-400: **Release packaging -- source tarball
with checksums (S-260 machinery), signed by the
maintainer key, notes written in plain words first.**

This slice is the packaging act itself, as pure law
plus one real run (``tools/run_release_packaging.py``)
over this tree:

- **The tarball is deterministic.** `build_tarball_bytes`
  packs the selected source files under one release
  prefix, names in sorted order, every member stamped
  with mtime 0, uid/gid 0, no owner names, mode 0644,
  USTAR format; the gzip wrapper is stamped mtime 0
  too. The same tree therefore packs to the same bytes
  on any machine, and the checksum below means the
  same thing everywhere. Source selection
  (`select_source_files`) is the caller's tracked-file
  list minus machinery that is never source: ``.git``
  internals, ``__pycache__`` and ``.pyc`` files.
- **Checksums are S-260's machinery, reused.** The
  release carries a ``SHA256SUMS.txt`` in exactly the
  format S-260 generates -- one ``<sha256>  <name>``
  line per artifact, name order -- and the audit
  judges it with S-260's own `parse_checksums` and
  `verify_checksums`, so the file a reader downloads
  is verified by the same code the release page
  teaches. A tampered or missing artifact is named,
  never passed over.
- **Signing is honest or it does not happen.** Samverk
  holds no private key (S-263's law: signatures are
  made elsewhere and attached through that seam), and
  this environment holds no maintainer secret key --
  the packaging run probes the operator's keyring and
  `judge_signing` speaks the verdict in words. When no
  maintainer secret key is present, the release ships
  UNSIGNED and the fact is a named remainder owned by
  Volmarr: he signs ``SHA256SUMS.txt`` with the
  maintainer key he holds outside this tree and the
  detached signature attaches through S-263. No key is
  generated here and none is ever presented as the
  maintainer key that is not.
- **Notes are written in plain words first.**
  `render_release_notes` opens with what the release
  is and how to check it, in plain words, before any
  detail; the signing state and the honest remainders
  carried from S-399's final register (F-02, F-10,
  F-11, F-17) are stated, never buried.

No migration and no new taxonomy event: the schema
stands at 140 and the taxonomy stands at 142.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import tarfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .release_checksums import parse_checksums, verify_checksums

RELEASE_NAME = f"samverk-{__version__}"
TARBALL_NAME = f"{RELEASE_NAME}-source.tar.gz"
CHECKSUMS_NAME = "SHA256SUMS.txt"
NOTES_NAME = "RELEASE_NOTES.md"
SIGNING_OWNER = "Volmarr"

__all__ = ["CHECKSUMS_NAME", "NOTES_NAME", "RELEASE_NAME",
    "SIGNING_OWNER", "TARBALL_NAME", "PackagingError",
    "SigningVerdict", "build_checksums", "build_tarball_bytes",
    "judge_signing", "package_files", "render_packaging_log",
    "render_release_notes", "select_source_files",
    "verify_package"]


class PackagingError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class SigningVerdict:
    status: str        # signed | unsigned_remainder
    owner: str         # who owns the signing act / remainder
    detail: str


def select_source_files(paths) -> tuple:
    """The source census, pure: the caller's tracked
    paths minus what is never source -- ``.git``
    internals, ``__pycache__`` parts and ``.pyc``
    files -- in sorted order, duplicates removed."""
    kept = []
    for raw in paths:
        path = str(raw).replace("\\", "/")
        parts = path.split("/")
        if ".git" in parts or "__pycache__" in parts:
            continue
        if path.endswith(".pyc") or not path:
            continue
        kept.append(path)
    return tuple(sorted(set(kept)))


def build_tarball_bytes(files) -> bytes:
    """One deterministic source tarball (gzipped):
    members ``<release>/<path>`` in name order, fixed
    stamps, so identical input packs byte-identically."""
    names = select_source_files(files.keys())
    if not names:
        raise PackagingError("packaging_empty",
            "There is no source to pack.")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w",
                      format=tarfile.USTAR_FORMAT) as tar:
        for name in names:
            data = files[name]
            info = tarfile.TarInfo(f"{RELEASE_NAME}/{name}")
            info.size = len(data)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return gzip.compress(buffer.getvalue(), mtime=0)


def build_checksums(artifacts) -> str:
    """S-260's format over the release artifacts:
    one ``<sha256>  <name>`` line per artifact, name
    order, newline-terminated."""
    lines = []
    for name in sorted(artifacts):
        digest = hashlib.sha256(artifacts[name]).hexdigest()
        lines.append(f"{digest}  {name}\n")
    return "".join(lines)


def judge_signing(secret_key_ids) -> SigningVerdict:
    """The signing verdict, spoken in words. A
    maintainer secret key the environment genuinely
    holds signs; an empty keyring is the named
    remainder -- never a generated substitute."""
    keys = [str(k) for k in secret_key_ids if str(k)]
    if keys:
        return SigningVerdict("signed", SIGNING_OWNER,
            f"Signed with maintainer secret key {keys[0]} "
            "held in the operator's keyring.")
    return SigningVerdict("unsigned_remainder", SIGNING_OWNER,
        "No maintainer secret key is present in this "
        "environment (the operator keyring holds no "
        "secret keys) and Samverk holds no private key "
        "by law (S-263). The release ships unsigned; "
        "Volmarr signs SHA256SUMS.txt with the "
        "maintainer key he holds outside this tree and "
        "the detached signature attaches through the "
        "S-263 release-signature seam.")


def package_files(files, secret_key_ids=()) -> dict:
    """Pack one release from a name-to-bytes mapping:
    the tarball, its S-260 checksums file, and the
    signing verdict. The audit dict is the counted
    record the packaging log renders."""
    names = select_source_files(files.keys())
    tarball = build_tarball_bytes(files)
    artifacts = {TARBALL_NAME: tarball}
    checksums = build_checksums(artifacts)
    verdict = judge_signing(secret_key_ids)
    return {"release": RELEASE_NAME, "version": __version__,
        "source_files": list(names),
        "source_count": len(names),
        "tarball_name": TARBALL_NAME,
        "tarball_size": len(tarball),
        "tarball_sha256": hashlib.sha256(tarball).hexdigest(),
        "checksums": checksums,
        "signing_status": verdict.status,
        "signing_owner": verdict.owner,
        "signing_detail": verdict.detail}


def verify_package(checksums_text, artifacts) -> dict:
    """Judge held artifacts against the checksums file
    with S-260's own verifier: parse strictly, compare
    digests, name every failure."""
    actual = {name: hashlib.sha256(data).hexdigest()
              for name, data in artifacts.items()}
    result = verify_checksums(checksums_text, actual)
    return {"checked": result.checked, "ok": result.ok,
        "mismatched": list(result.mismatched),
        "missing": list(result.missing),
        "unexpected": list(result.unexpected)}


def render_release_notes(audit) -> str:
    """The release notes: plain words first, then the
    detail. The signing state is said in the plain
    words, not buried below them."""
    signed = audit["signing_status"] == "signed"
    signing_plain = ("The maintainer has signed the "
        "checksums file, so you can check both that the "
        "files are whole and that they are his." if signed else
        "This release is not signed yet. That step is "
        "Volmarr's to do, with the maintainer key he "
        "keeps outside this tree; until he signs, the "
        "checksums still prove the files are whole, "
        "but nothing here proves whose hands packed "
        "them.")
    lines = [
        f"# Samverk {audit['version']} -- release notes",
        "",
        "## In plain words",
        "",
        "This is the source of Samverk, packed as one "
        "file. Samverk is our own version-control forge: "
        "the program that holds this source is the "
        "program this source builds. Nothing in the "
        "package needs Docker, and nothing in it phones "
        "home.",
        "",
        "To check that the file you downloaded is the "
        "file that was packed, save SHA256SUMS.txt "
        "beside it and run:",
        "",
        "    sha256sum -c SHA256SUMS.txt",
        "",
        "(on macOS: shasum -a 256 -c SHA256SUMS.txt). "
        "The tarball must answer OK. Any other answer "
        "means the file is not the packed bytes and "
        "must not be trusted.",
        "",
        signing_plain,
        "",
        "## What is in the package",
        "",
        f"- {audit['tarball_name']} -- {audit['source_count']} "
        f"source files, {audit['tarball_size']} bytes packed.",
        "- SHA256SUMS.txt -- the checksum of the tarball, "
        "in the format S-260 generates for every release.",
        "- These notes.",
        "",
        "## Signing",
        "",
        f"Status: {audit['signing_status']}. "
        f"Owner: {audit['signing_owner']}.",
        "",
        audit["signing_detail"],
        "",
        "## What is honestly not finished",
        "",
        "The final claims register (S-399) stands behind "
        "these notes. It records as NOT PROVEN: the "
        "Windows and macOS platform matrix (F-02, owned "
        "by Part XXII), the live server composition "
        "(F-10), and a fully green full-suite run "
        "(F-11 -- the counted master run names its "
        "failures). One README item is OPEN for Volmarr "
        "(F-17). None of that is hidden by this "
        "packaging; the register ships in docs/.",
        ""]
    return "\n".join(lines)


def render_packaging_log(audit, verification) -> str:
    lines = [
        "# Release packaging -- S-400 counted log", "",
        f"Release: {audit['release']} "
        f"(version {audit['version']})", "",
        f"- Source files packed: {audit['source_count']}",
        f"- Tarball: {audit['tarball_name']} -- "
        f"{audit['tarball_size']} bytes",
        f"- Tarball SHA-256: {audit['tarball_sha256']}",
        f"- Signing: {audit['signing_status']} "
        f"(owner {audit['signing_owner']})",
        f"- Verification round-trip (S-260 machinery): "
        f"checked {verification['checked']}, "
        f"ok={verification['ok']}, "
        f"mismatched={verification['mismatched']}, "
        f"missing={verification['missing']}, "
        f"unexpected={verification['unexpected']}", "",
        "## SHA256SUMS.txt", "", "```",
        audit["checksums"].rstrip("\n"), "```", "",
        "## Signing detail", "", audit["signing_detail"], ""]
    return "\n".join(lines)
