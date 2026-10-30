"""Audit log core (S-007) — study 35's design as code.

An append-only, hash-chained witness:

- Every entry's `entry_hash` is SHA-256 over a canonical serialisation
  of the entry *including the previous entry's hash* — editing or
  deleting history breaks the chain at the first touched link.
- The chain starts from a fixed genesis hash (a published constant,
  below), so even the first entry is anchored to something checkable.
- Appends are serialised through one lock + one transaction, so
  sequence numbers and chain links can never interleave (study 42's
  writer-queue rule for hot paths).
- There is deliberately **no** update or delete API. Corrections are
  new entries that reference the entry they correct (study 35 §3).
- `verify_chain` recomputes the whole chain and reports the first
  broken sequence number, if any — S-007's acceptance shape.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Callable

GENESIS_HASH = hashlib.sha256(b"samverk/audit-genesis/v1").hexdigest()
_SEP = "\x1f"  # unit separator: unambiguous, never in normal fields


def _canonical(seq: int, ts: int, actor_kind: str, actor_id: int | None,
               action: str, target_kind: str, target_id: str | None,
               source_ip: str | None, outcome: str, detail: str | None,
               prev_hash: str) -> str:
    fields = [
        str(seq), str(ts), actor_kind,
        "" if actor_id is None else str(actor_id),
        action, target_kind,
        "" if target_id is None else target_id,
        "" if source_ip is None else source_ip,
        outcome, "" if detail is None else detail,
        prev_hash,
    ]
    return _SEP.join(fields)


def _entry_hash(canonical: str) -> str:
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, conn: sqlite3.Connection,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._now = time_fn
        self._lock = threading.Lock()

    def append(self, *, actor_kind: str, action: str, target_kind: str,
               outcome: str, actor_id: int | None = None,
               target_id: str | None = None, source_ip: str | None = None,
               detail: dict | None = None) -> int:
        """Append one event; return its sequence number."""
        detail_text = (
            json.dumps(detail, sort_keys=True, separators=(",", ":"))
            if detail is not None else None
        )
        ts = int(self._now())
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM audit_log"
            ).fetchone()
            seq = int(row["max_seq"]) + 1
            if seq == 1:
                prev_hash = GENESIS_HASH
            else:
                prev = self._conn.execute(
                    "SELECT entry_hash FROM audit_log WHERE seq = ?",
                    (seq - 1,),
                ).fetchone()
                prev_hash = prev["entry_hash"]
            canonical = _canonical(
                seq, ts, actor_kind, actor_id, action, target_kind,
                target_id, source_ip, outcome, detail_text, prev_hash)
            entry_hash = _entry_hash(canonical)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO audit_log (seq, ts, actor_kind, actor_id,"
                    " action, target_kind, target_id, source_ip, outcome,"
                    " detail, prev_hash, entry_hash)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (seq, ts, actor_kind, actor_id, action, target_kind,
                     target_id, source_ip, outcome, detail_text,
                     prev_hash, entry_hash),
                )
        return seq


def verify_chain(conn: sqlite3.Connection) -> tuple[bool, int | None, int]:
    """Recompute the chain from genesis.

    Returns (ok, first_bad_seq, entries_checked). A gap in sequence
    numbers, a wrong prev_hash link, or a wrong entry_hash all count
    as a break at the first offending sequence number.
    """
    rows = conn.execute(
        "SELECT seq, ts, actor_kind, actor_id, action, target_kind,"
        " target_id, source_ip, outcome, detail, prev_hash, entry_hash"
        " FROM audit_log ORDER BY seq"
    ).fetchall()
    prev_hash = GENESIS_HASH
    expected_seq = 1
    for row in rows:
        if row["seq"] != expected_seq:
            return False, expected_seq, expected_seq - 1
        if row["prev_hash"] != prev_hash:
            return False, row["seq"], expected_seq - 1
        canonical = _canonical(
            row["seq"], row["ts"], row["actor_kind"], row["actor_id"],
            row["action"], row["target_kind"], row["target_id"],
            row["source_ip"], row["outcome"], row["detail"], prev_hash)
        if _entry_hash(canonical) != row["entry_hash"]:
            return False, row["seq"], expected_seq - 1
        prev_hash = row["entry_hash"]
        expected_seq += 1
    return True, None, len(rows)
