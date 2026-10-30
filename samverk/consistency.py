"""Consistency checker (S-071).

An fsck-style sweep reconciling Samverk's three stores —
study 42's three stores under one roof:

- **SQLite rows** — every `repositories` row must name a bare
  repository that exists on disk at its S-013 path, and every
  repository-scoped record (mirror, fork/template lineage)
  must point at a row that exists.
- **Disk repositories** — every ``<owner>/<repo>.git``
  directory under the repositories root must be registered
  by a row; a directory nobody registered is drift, not a
  discovery to adopt silently (S-049's creation law, restated
  from the other side).
- **LFS objects** — every object file in a registered
  repository's S-060 layout must sit at the fan-out path its
  oid names, and its bytes must still hash to that oid.

The law of this checker: **drift is reported, never silently
"fixed".** The sweep is read-only — it opens no write
transaction, creates nothing, deletes nothing, and renames
nothing. Repair is a separate, deliberate operator act taken
with this report in hand; a checker that quietly healed
would also quietly hide the evidence of how the drift
happened.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .repo_paths import repos_root
from .repositories import RepositoryStore


@dataclass(frozen=True)
class Drift:
    kind: str          # see kinds in ConsistencyChecker.check
    repo: str          # canonical owner/name, or "" when not repo-scoped
    detail: str


@dataclass(frozen=True)
class ConsistencyReport:
    repos_checked: int
    disk_repos_seen: int
    lfs_objects_checked: int
    drifts: tuple[Drift, ...] = ()

    @property
    def is_clean(self) -> bool:
        return not self.drifts

    def by_kind(self, kind: str) -> list[Drift]:
        return [d for d in self.drifts if d.kind == kind]


class ConsistencyChecker:
    """Read-only reconciliation of rows ↔ disk ↔ LFS objects."""

    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 repositories: RepositoryStore):
        self._conn = conn
        self._data_root = Path(data_root)
        self._repos = repositories

    def check(self) -> ConsistencyReport:
        drifts: list[Drift] = []
        rows = self._conn.execute(
            "SELECT * FROM repositories ORDER BY owner_lower, name_lower"
        ).fetchall()
        registered: dict[tuple[str, str], object] = {}
        lfs_checked = 0
        for row in rows:
            key = (row["owner_lower"], row["name_lower"])
            registered[key] = row
            full = f"{row['owner']}/{row['name']}"
            try:
                path = self._repos.path_for(row["owner"], row["name"])
            except Exception as exc:  # a row its own path law refuses
                drifts.append(Drift(
                    "repo_path_unresolvable", full,
                    f"row resolves to no lawful path: {exc}"))
                continue
            if not path.is_dir():
                drifts.append(Drift(
                    "repo_missing_on_disk", full,
                    f"row exists but {path} does not"))
                continue
            if not (path / "HEAD").is_file() or not (path / "objects").is_dir():
                drifts.append(Drift(
                    "repo_not_bare_on_disk", full,
                    "directory exists but lacks a bare repository's "
                    "HEAD/objects layout"))
                continue
            lfs_checked += self._check_lfs(path, full, drifts)
            # Lineage links must point at rows that exist.
            for column, kind in (("fork_of_id", "fork_link_dangling"),
                                 ("template_of_id", "template_link_dangling")):
                target = row[column] if column in row.keys() else None
                if target is not None and self._repos.get_by_id(int(target)) is None:
                    drifts.append(Drift(
                        kind, full,
                        f"{column} names repository id {target}, "
                        "which has no row"))

        # Disk → rows: every on-disk bare repo must be registered.
        disk_seen = 0
        root = repos_root(self._data_root)
        if root.is_dir():
            for owner_dir in sorted(p for p in root.iterdir() if p.is_dir()):
                for entry in sorted(owner_dir.iterdir()):
                    if not entry.is_dir() or not entry.name.endswith(".git"):
                        continue
                    disk_seen += 1
                    key = (owner_dir.name.lower(),
                           entry.name[:-4].lower())
                    if key not in registered:
                        drifts.append(Drift(
                            "repo_unregistered_on_disk",
                            f"{owner_dir.name}/{entry.name[:-4]}",
                            "bare repository on disk has no metadata row; "
                            "reported, never adopted silently"))

        # Repository-scoped records must not be orphans.
        orphan_rows = self._conn.execute(
            "SELECT m.repo_id FROM repo_mirrors m"
            " LEFT JOIN repositories r ON r.id = m.repo_id"
            " WHERE r.id IS NULL").fetchall()
        for orphan in orphan_rows:
            drifts.append(Drift(
                "mirror_record_orphan", "",
                f"repo_mirrors row names repository id "
                f"{orphan['repo_id']}, which has no row"))

        return ConsistencyReport(
            repos_checked=len(rows), disk_repos_seen=disk_seen,
            lfs_objects_checked=lfs_checked, drifts=tuple(drifts))

    # -- LFS ------------------------------------------------------
    def _check_lfs(self, repo_path: Path, full: str,
                   drifts: list[Drift]) -> int:
        objects_root = repo_path / "lfs" / "objects"
        if not objects_root.is_dir():
            return 0
        checked = 0
        for entry in sorted(objects_root.rglob("*")):
            if entry.is_symlink() or not entry.is_file():
                continue
            rel = entry.relative_to(objects_root)
            parts = rel.parts
            oid = entry.name
            if (len(parts) != 3 or len(parts[0]) != 2 or len(parts[1]) != 2
                    or len(oid) != 64
                    or any(c not in "0123456789abcdef" for c in oid)
                    or any(c not in "0123456789abcdef" for c in parts[0] + parts[1])):
                drifts.append(Drift(
                    "lfs_object_misplaced", full,
                    f"{rel} does not sit at its oid's fan-out path"))
                continue
            if parts[0] != oid[0:2] or parts[1] != oid[2:4]:
                drifts.append(Drift(
                    "lfs_object_misplaced", full,
                    f"{rel} sits under the wrong fan-out for its oid"))
                continue
            checked += 1
            digest = hashlib.sha256(entry.read_bytes()).hexdigest()
            if digest != oid:
                drifts.append(Drift(
                    "lfs_object_corrupt", full,
                    f"object {oid} hashes to {digest}; bytes no "
                    "longer match the oid they are stored under"))
        return checked
