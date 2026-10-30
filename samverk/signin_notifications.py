"""New-sign-in notification (S-041).

When an account signs in from somewhere it has never signed
in from, the owner hears about it — **once per new device**,
never per sign-in. A "device" here is the pair the sign-in
arrived with: its device label (S-040) and its source
address. The pair is remembered in `known_devices` under a
SHA-256 key; a repeat sign-in from the same pair quietly
updates `last_seen_at` and fires nothing.

Two channels, in order of trust:

1. **In-app notice** — always. A row lands in the owner's
   notice inbox carrying the device label, the address, and
   the time, until the owner marks it read.
2. **Email** — when the instance has a mailer seam *and*
   the account has an address. Email is best-effort by
   nature: the in-app row is committed first, and a mailer
   failure never unmakes it (or the sign-in).

The very first sign-in of an account fires too: nothing is
known yet, so everything is new — the same answer real
forges give. Every firing is audited `auth.signin.notify`
(S-041's append-only taxonomy addition) with the device
facts, so the security record exists even if both channels
are later cleared by their owner.

The notifier is a seam on S-027's login service
(`signin_notifier=`): unwired instances behave exactly as
before, and the login itself never depends on the mailer.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore
from .audit import AuditLog

# (account email address, plain-text message) — a seam, not
# an SMTP client, exactly like S-026's mailer.
NotifyMailer = Callable[[str, str], None]


def _device_key(device_label: str | None,
                source_ip: str | None) -> str:
    material = f"{device_label or ''}|{source_ip or ''}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SignInNotice:
    id: int
    user_id: int
    device_label: str | None
    source_ip: str | None
    created_at: int
    read_at: int | None

    @property
    def unread(self) -> bool:
        return self.read_at is None


class SignInNotifier:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        mailer: NotifyMailer | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._mailer = mailer
        self._now = time_fn

    def record_signin(
        self, user_id: int, source_ip: str | None = None,
        device_label: str | None = None,
    ) -> bool:
        """The login service's seam. Returns True exactly
        when this sign-in was from a new device and a notice
        fired; a known device returns False and only its
        last-seen stamp moves."""
        user = self._accounts.get_by_id(user_id)
        if user is None:
            return False
        key = _device_key(device_label, source_ip)
        now = int(self._now())
        row = self._conn.execute(
            "SELECT device_key FROM known_devices"
            " WHERE user_id = ? AND device_key = ?",
            (user.id, key)).fetchone()
        if row is not None:
            with self._conn:
                self._conn.execute(
                    "UPDATE known_devices SET last_seen_at = ?"
                    " WHERE user_id = ? AND device_key = ?",
                    (now, user.id, key))
            return False
        with self._conn:  # device + notice land together
            self._conn.execute(
                "INSERT INTO known_devices (user_id, device_key,"
                " device_label, source_ip, first_seen_at, last_seen_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (user.id, key, device_label, source_ip, now, now))
            self._conn.execute(
                "INSERT INTO signin_notifications (user_id,"
                " device_label, source_ip, created_at, read_at)"
                " VALUES (?, ?, ?, ?, NULL)",
                (user.id, device_label, source_ip, now))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.signin.notify", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip,
                detail={"device": device_label or "unknown"})
        if self._mailer is not None and user.email:
            stamp = time.strftime(
                "%Y-%m-%d %H:%M UTC", time.gmtime(now))
            message = (
                f"A new sign-in to your Samverk account "
                f"({user.username}) was recorded.\n\n"
                f"Device: {device_label or 'Unknown device'}\n"
                f"Address: {source_ip or 'unknown'}\n"
                f"Time: {stamp}\n\n"
                "If this was not you, change your password and "
                "revoke the session from Settings → Security "
                "and sessions.")
            try:
                self._mailer(user.email, message)
            except Exception:
                # Email is the second channel, best-effort by
                # nature; the in-app notice above is the record
                # and it has already landed.
                pass
        return True

    # -- the owner's inbox --------------------------------------
    def list_notices(self, user_id: int,
                     unread_only: bool = False) -> list[SignInNotice]:
        sql = ("SELECT * FROM signin_notifications WHERE user_id = ?"
               + (" AND read_at IS NULL" if unread_only else "")
               + " ORDER BY id")
        rows = self._conn.execute(sql, (user_id,)).fetchall()
        return [SignInNotice(
            id=r["id"], user_id=r["user_id"],
            device_label=r["device_label"], source_ip=r["source_ip"],
            created_at=r["created_at"], read_at=r["read_at"])
            for r in rows]

    def unread_count(self, user_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM signin_notifications"
            " WHERE user_id = ? AND read_at IS NULL",
            (user_id,)).fetchone()
        return int(row["n"])

    def mark_read(self, user_id: int, notice_id: int) -> bool:
        """Owner-only in the query itself."""
        with self._conn:
            cur = self._conn.execute(
                "UPDATE signin_notifications SET read_at = ?"
                " WHERE id = ? AND user_id = ? AND read_at IS NULL",
                (int(self._now()), notice_id, user_id))
        return cur.rowcount > 0

    def mark_all_read(self, user_id: int) -> int:
        with self._conn:
            cur = self._conn.execute(
                "UPDATE signin_notifications SET read_at = ?"
                " WHERE user_id = ? AND read_at IS NULL",
                (int(self._now()), user_id))
        return cur.rowcount
