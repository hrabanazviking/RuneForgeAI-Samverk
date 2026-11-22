"""Migration of the backup duty (S-378) — the Part XVII
mirrors re-point to the Samtal-hosted Samverk instance.

The founding mirrors were pointed at an interim home.
The duty now lives where the village lives: each mirror
whose source stands under the interim prefix is
re-pointed at the same relative path under the
hosted base, re-synced through the standing S-070
MirrorService, and verified ref-for-ref again through
S-336's FirstPassMirroringService — the same proof the
first pass earned, earned again at the new home.

Honesty rules, standing ones kept:
- Only mirrors actually under the interim prefix move;
  any other source refuses not_interim_source, named.
- A re-point that does not verify is REPORTED as
  unverified with its comparison headline; the record
  of the attempt is kept either way (settings table,
  backup_duty.migration.<full name>) — a failed
  migration never looks done.
- The move is detach + attach + sync on the standing
  stores; no mirror content is touched by hand, and
  the mirror's own refs before the move are the old
  source's — after a verified sync they are the new
  source's, ref-for-ref.

No migration, no new taxonomy event: attach/detach ride
the standing repo.settings.change audit (S-070).
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .first_pass_mirroring import FirstPassMirroringService
from .mirrors import MirrorError, MirrorService
from .repositories import RepositoryStore


class BackupDutyMigrationError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class BackupDutyMigrationService:
    def __init__(self, conn: sqlite3.Connection,
                 data_root: Path, accounts: AccountStore,
                 repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._now = time_fn
        self._mirrors = MirrorService(
            conn, data_root, accounts, repositories,
            audit=audit, time_fn=time_fn)
        self._proof = FirstPassMirroringService(
            conn, data_root, accounts, repositories,
            audit=audit, time_fn=time_fn)

    # -- records (settings table) -------------------------
    def _record(self, full_name: str, entry: dict) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO settings "
                "(key, value) VALUES (?, ?)",
                (f"backup_duty.migration.{full_name}",
                 json.dumps(entry, sort_keys=True)))

    def migration_for(self, owner, repo) -> dict | None:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            return None
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (f"backup_duty.migration.{current.full_name}",)
            ).fetchone()
        return None if row is None else json.loads(row[0])

    # -- the move ------------------------------------------
    def repoint(self, actor_user_id: int, owner, repo, *,
                interim_prefix: str,
                hosted_base: str) -> dict:
        """Re-point one mirror from the interim home to
        the Samtal-hosted instance, re-sync, and verify
        ref-for-ref. Returns the migration entry; a
        verification failure is reported in it, never
        raised away and never hidden."""
        mirror = self._mirrors.mirror_for(owner, repo)
        if mirror is None:
            raise BackupDutyMigrationError(
                "not_a_mirror",
                "That repository carries no mirror duty "
                "to migrate.")
        old = mirror.source
        if mirror.source_kind != "local" or \
                not old.startswith(interim_prefix):
            raise BackupDutyMigrationError(
                "not_interim_source",
                f"The mirror's source ({old}) does not "
                f"stand under the interim home "
                f"({interim_prefix}); it is not this "
                f"duty's to move.")
        new = hosted_base + old[len(interim_prefix):]
        try:
            self._mirrors.detach_mirror(actor_user_id, owner, repo)
            self._mirrors.attach_mirror(actor_user_id, owner,
                                        repo, Path(new))
        except MirrorError as exc:
            raise BackupDutyMigrationError(
                exc.reason, str(exc)) from None
        result = self._mirrors.sync_mirror(owner, repo)
        comparison = self._proof.verify_mirror(owner, repo)
        entry = {
            "full_name": mirror.full_name,
            "old_source": old, "new_source": new,
            "at": int(self._now()),
            "sync_status": result.status,
            "verified": bool(comparison.verified),
            "source_refs": comparison.source_refs,
            "headline": comparison.headline,
        }
        self._record(mirror.full_name, entry)
        return entry

    def migrate_duty(self, actor_user_id: int, *,
                     interim_prefix: str,
                     hosted_base: str) -> dict:
        """Every mirror standing under the interim home
        moves, in name order; the report counts moved,
        verified, and failed by name."""
        rows = self._conn.execute(
            "SELECT r.owner, r.name FROM repo_mirrors m "
            "JOIN repositories r ON r.id = m.repo_id "
            "WHERE m.source_kind = 'local' AND m.source "
            "LIKE ? ORDER BY r.owner, r.name",
            (interim_prefix + "%",)).fetchall()
        moved, failed = [], []
        for row in rows:
            try:
                entry = self.repoint(
                    actor_user_id, row["owner"], row["name"],
                    interim_prefix=interim_prefix,
                    hosted_base=hosted_base)
                (moved if entry["verified"] else failed).append(entry)
            except BackupDutyMigrationError as exc:
                failed.append({"owner": row["owner"],
                               "repo": row["name"],
                               "reason": exc.reason})
        return {"moved": moved, "failed": failed,
                "verified": len(moved),
                "total": len(rows)}
