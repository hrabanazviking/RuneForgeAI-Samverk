"""Village backup unity (S-371).

Samtal's standing backup bundle grows a Samverk section,
so the village's talk and work are kept in one keeping.
The bundle is one manifest over two kinds of sections:
the Samtal sections the caller hands over (its halls and
talk, as named byte payloads — Samtal keeps its own
keeping, this slice only binds it) and the Samverk
section, which is S-341's whole-instance export itself:
the real archive, with its own manifest and checksums,
produced by WholeInstanceExportService at bundle time.
Nothing is re-implemented and nothing is copied by hand:
the bundle manifest records the export archive's name,
sha256, byte count and repo counts beside a sha256 and
byte count for every Samtal section, and verify_bundle
re-checks every recorded hash against the files on disk
— a bundle that does not verify is named, never trusted.

The Samverk section inherits S-341's guards whole: the
export is admin-only (permission_denied) and an instance
with nothing exportable refuses (nothing_to_export) —
a village bundle must never pretend to keep work it
does not hold. Section names are judged: a name that
could escape the bundle directory (path separators,
dot-dot, empty) refuses (section_name_invalid), and a
payload that is not bytes or text refuses
(section_payload_invalid).

Guards: the seam must be enabled (seam_disabled — the
bundle is the seam's keeping, and with the seam off each
application keeps its own backup as before). No
migration, no new taxonomy event: the bundle is files
and a manifest, the export is S-341's own.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .config import Config
from .repositories import RepositoryStore
from .seam_contract import seam_enabled
from .secrets import Secrets
from .whole_instance_export import WholeInstanceExportService

BUNDLE_FORMAT = "samverk-village-bundle/1"
MANIFEST_NAME = "village-bundle.json"
SAMVERK_SECTION = "samverk"


class VillageBackupError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class VillageBundle:
    manifest_path: Path
    export_archive: Path
    samtal_sections: tuple
    samverk_repos: int
    total_bytes: int

    @property
    def headline(self) -> str:
        return (f"village bundle: {len(self.samtal_sections)} Samtal "
                f"sections + Samverk section ({self.samverk_repos} "
                f"repositories), {self.total_bytes} bytes in one keeping")


def _section_bytes(name: object, payload: object) -> tuple:
    if (not isinstance(name, str) or not name.strip()
            or "/" in name or "\\" in name or name.strip() in (".", "..")
            or name == SAMVERK_SECTION):
        raise VillageBackupError(
            "section_name_invalid",
            "A bundle section needs a plain name of its own.")
    if isinstance(payload, str):
        data = payload.encode("utf-8")
    elif isinstance(payload, (bytes, bytearray)):
        data = bytes(payload)
    else:
        raise VillageBackupError(
            "section_payload_invalid",
            "A bundle section payload must be bytes or text.")
    return name.strip(), data


class VillageBackupService:
    """Binds Samtal's sections and S-341's export into one bundle."""

    def __init__(self, conn, data_root: Path, accounts: AccountStore,
                 repositories: RepositoryStore, *, config: Config | None = None,
                 secrets: Secrets | None = None, settings: dict | None = None,
                 audit: AuditLog | None = None, time_fn=None):
        self._settings = settings
        self._now = time_fn or (lambda: 0)
        self._exports = WholeInstanceExportService(
            conn, data_root, accounts, repositories, config=config,
            secrets=secrets, time_fn=time_fn or (lambda: 0))

    def build_bundle(self, actor_user_id: int, samtal_sections: dict,
                     dest_dir: Path) -> VillageBundle:
        """One keeping: Samtal's sections written beside the real
        S-341 export, all of it bound by one checksummed manifest."""
        if not seam_enabled(self._settings):
            raise VillageBackupError(
                "seam_disabled", "The Samtal seam is not enabled.")
        if not isinstance(samtal_sections, dict):
            raise VillageBackupError(
                "section_payload_invalid",
                "Samtal sections arrive as a name-to-payload mapping.")
        cleaned = [_section_bytes(n, p) for n, p in samtal_sections.items()]
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        export = self._exports.export_instance(actor_user_id, dest)
        entries = []
        total = export.archive_bytes
        for name, data in sorted(cleaned):
            path = dest / f"samtal-{name}"
            path.write_bytes(data)
            entries.append({"name": name, "file": path.name,
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "bytes": len(data)})
            total += len(data)
        manifest = {
            "format": BUNDLE_FORMAT,
            "sections": {
                "samtal": entries,
                "samverk": {
                    "archive": export.archive_path.name,
                    "manifest": export.manifest_path.name,
                    "sha256": export.archive_sha256,
                    "bytes": export.archive_bytes,
                    "repos_included": export.repos_included,
                    "repos_excluded": export.repos_excluded,
                    "lfs_objects": export.lfs_objects,
                },
            },
        }
        manifest_path = dest / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, indent=2,
                                            sort_keys=True) + "\n",
                                 encoding="utf-8")
        return VillageBundle(manifest_path=manifest_path,
                             export_archive=export.archive_path,
                             samtal_sections=tuple(e["name"] for e in entries),
                             samverk_repos=export.repos_included,
                             total_bytes=total)


def verify_bundle(manifest_path: Path) -> list:
    """Re-check every hash the bundle manifest records against
    the files on disk. Returns the list of problems (empty = the
    bundle verifies): missing files and hash mismatches named."""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent
    problems = []
    sections = manifest.get("sections", {})
    for entry in sections.get("samtal", []):
        path = root / entry["file"]
        if not path.is_file():
            problems.append(f"missing section file {entry['file']}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            problems.append(f"section {entry['name']} hash mismatch")
    samverk = sections.get("samverk") or {}
    archive = root / samverk.get("archive", "")
    if not samverk or not archive.is_file():
        problems.append("missing Samverk export archive")
    elif hashlib.sha256(archive.read_bytes()).hexdigest() != samverk["sha256"]:
        problems.append("Samverk export archive hash mismatch")
    return problems
