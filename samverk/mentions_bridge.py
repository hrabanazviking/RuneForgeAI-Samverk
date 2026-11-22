"""Mentions bridge (S-369).

@mentions in Samverk notify the linked Samtal principal
there too — one notification, two doors. S-226's router
already delivers a mention exactly once inside Samverk
(one S-223 notification, reason ``mention``, however
many paths in the prose reach the person); this bridge
extends that same exactly-once rule across the seam:
the Samtal-side delivery is a second *door* onto the
same notification, never a second notification.

The bridge ledger rides the settings table, keyed by
source + recipient — the same source identity S-226's
delivery ledger enforces (one piece of primary prose).
Bridging a source that already crossed returns the
standing delivery (already_delivered) and creates
nothing: no duplicate Samverk notification, no
duplicate Samtal door. A different source is a
different mention and delivers its own notification.

The Samtal door exists only where S-362's identity
link stands: the delivery names the linked principal
(read from S-045's IdentityLinkStore, provider
``samtal``); an unlinked recipient is notified through
the Samverk door alone, honestly (doors says so). A
person is never bridged a mention of their own act
(S-226's author-removal law).

Guards: the seam must be enabled (seam_disabled); a
source key and a real recipient are required
(source_required / no_such_user); self-mentions refuse
(self_mention). No migration, no new taxonomy event:
the notification is S-223's own, the ledger rides the
settings table.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .identity_linking import IdentityLinkStore
from .notification_reasons import NotificationStore
from .seam_contract import SEAM_PROVIDER, seam_enabled


class MentionsBridgeError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class BridgeDelivery:
    source_key: str
    recipient_id: int
    username: str
    principal: str | None
    notification_id: int
    already_delivered: bool = False

    @property
    def doors(self) -> tuple:
        """Where this one notification can be read: the
        Samverk door always; the Samtal door too when the
        recipient's principal is linked."""
        if self.principal:
            return ("samverk", "samtal")
        return ("samverk",)


class MentionsBridgeService:
    def __init__(self, conn, accounts: AccountStore,
                 *, settings: dict | None = None, audit: AuditLog | None = None,
                 time_fn=None):
        self._conn = conn
        self._accounts = accounts
        self._settings = settings
        now = time_fn or (lambda: 0)
        self._notifications = NotificationStore(conn, accounts, time_fn=now)
        self._links = IdentityLinkStore(conn, accounts, audit=audit,
                                        time_fn=now)

    def _key(self, source_key: str, recipient_id: int) -> str:
        return f"seam.mention.{source_key}.{recipient_id}"

    def delivery_for(self, source_key: object,
                     recipient_id: int) -> BridgeDelivery | None:
        """The standing bridge delivery for a source + recipient."""
        if not isinstance(source_key, str) or not source_key.strip():
            return None
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (self._key(source_key.strip(), recipient_id),)).fetchone()
        if row is None:
            return None
        data = json.loads(row["value"])
        user = self._accounts.get_by_id(recipient_id)
        return BridgeDelivery(
            source_key=source_key.strip(), recipient_id=recipient_id,
            username=user.username if user else "",
            principal=data["principal"],
            notification_id=data["notification_id"], already_delivered=True)

    def bridge_mention(self, *, source_key: object, recipient: User | None,
                       actor: User | None, target_kind: str = "",
                       target_id: str = "",
                       detail: dict | None = None) -> BridgeDelivery:
        """Deliver one mention across the seam, exactly once.

        Creates the single S-223 notification (reason
        ``mention``) through the standing NotificationStore
        door and records the Samtal door beside it when the
        recipient is linked; re-bridging the same source
        returns the standing delivery and creates nothing.
        """
        if not seam_enabled(self._settings):
            raise MentionsBridgeError(
                "seam_disabled", "The Samtal seam is not enabled.")
        if not isinstance(source_key, str) or not source_key.strip():
            raise MentionsBridgeError(
                "source_required", "A bridged mention needs its source.")
        if recipient is None or self._accounts.get_by_id(recipient.id) is None:
            raise MentionsBridgeError(
                "no_such_user", "The mentioned account does not stand.")
        if actor is not None and actor.id == recipient.id:
            raise MentionsBridgeError(
                "self_mention", "Nobody is notified of their own act.")
        source = source_key.strip()
        standing = self.delivery_for(source, recipient.id)
        if standing is not None:
            return standing
        note = self._notifications.notify(
            recipient, actor, "mention", target_kind=target_kind,
            target_id=target_id, detail=detail or {})
        link = self._links.get(recipient.id, SEAM_PROVIDER)
        principal = link.external_id if link is not None else None
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (self._key(source, recipient.id),
                 json.dumps({"notification_id": note.id,
                             "principal": principal}, sort_keys=True)))
        return BridgeDelivery(source_key=source, recipient_id=recipient.id,
                              username=recipient.username, principal=principal,
                              notification_id=note.id)
