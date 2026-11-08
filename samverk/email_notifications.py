"""Email notifications (S-227).

Part XI's second door: S-223's notifications also
leave the instance as email -- via the instance
SMTP when it is configured, per-event or as a
digest, with signed unsubscribe links, and never
at all when SMTP is absent (the in-app inbox still
works exactly as S-223/S-224 left it). Before this
slice the only mail in Samverk was S-026's
verification seam; nothing a person was notified
about ever reached their mailbox. This module is
that delivery, under six laws:

- **SMTP is a configuration, never an assumption.**
  The instance's SMTP is named by an `SmtpConfig`
  (host, port, from-address, optional credentials
  and TLS flag), judged whole by the pure
  `smtp_config_from`: no settings at all means
  *absent* (None), a complete set means configured,
  and a half-set is refused `smtp_config_invalid`
  -- fail-closed, exactly as S-015's TLS pair is
  both-or-neither. The transport itself is a seam
  in S-026's shape -- a mailer callable taking
  ``(address, subject, body)`` -- and `smtp_mailer`
  builds the real one over `smtplib` for a
  configured instance. With no mailer the store
  still records every delivery decision, honestly
  marked skipped; email is the only thing absent.
- **Per-event or digest, decided purely.** The
  instance mode is one of two (`EMAIL_MODES`),
  judged at the door by `validate_email_mode`
  (anything else is `email_mode_invalid`, stores
  nothing). The pure `decide_email` is the whole
  delivery law: SMTP absent -> skip (`smtp_absent`);
  no address on the account -> skip
  (`no_email_address`); an unsubscribe covering
  this reason or all mail -> skip (`unsubscribed`);
  otherwise send now under `per-event`, or queue
  under `digest`. A digest queues silently and
  leaves only when flushed: one letter per
  recipient carrying every queued notification,
  and the flush re-judges each queued row, so an
  unsubscribe recorded after queueing still stops
  that mail (the row is marked skipped, never sent).
- **Exactly once per notification.** Migration 91's
  `email_deliveries` is UNIQUE on the S-223
  notification it delivers, so delivering the same
  notification twice -- a retry, a second caller --
  returns the standing row and sends nothing twice.
  A transport failure is recorded on the row
  (`failed`) and never raised into the caller's
  mutation: email trouble cannot break the in-app
  notification, which was committed first and
  stands regardless of what any delivery row says.
- **Unsubscribe links are signed and scoped.**
  Every letter carries an unsubscribe link for its
  own scope -- the notification's reason, or `all`
  -- whose token is HMAC-SHA256 over
  ``user:scope`` under the instance signing key
  (S-003's secret law: the key is handed in, never
  stored in the database), URL-safe and compared
  with `hmac.compare_digest`. `unsubscribe` redeems
  a token generically: a forged, tampered,
  wrong-key or shapeless token is the one refusal
  `unsubscribe_token_invalid`, indistinguishable in
  kind, so the endpoint cannot be probed for which
  tokens ever existed. Redemption is idempotent, a
  signed-in `resubscribe` undoes it, and the opt-out
  is consulted at decision time -- per reason, with
  `all` covering every reason. Per-user choices
  beyond the link (per-reason page, cadence) are
  S-228's slice; this slice owns the link and the
  opt-out record it writes.
- **The letter says why it came.** The pure
  composers build plain-text letters whose subject
  and body say the notification's stored reason in
  S-223's plain words, who acted, and on what --
  meaning never rides on markup -- and every letter
  ends with its unsubscribe link(s). The page
  renderers say mode, status and reason outright
  through S-010's escaping seam.
- **Deliveries belong to their recipient.** Every
  read is scoped by the recipient's account id in
  the query itself; an anonymous caller is refused
  `authentication_required` on writes and sees
  nothing on reads. Every state change commits
  before its answer (the commit-before-answer law).

No new taxonomy event: delivering a notification
is the delivery of a mutation already witnessed
under its own verb, and an opt-out is a personal
notification state like S-224's triage and S-225's
overrides; 127 events stand. One migration: 91
creates `email_deliveries` and `email_optouts`
(schema 90 to 91).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import smtplib
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .notification_reasons import (
    Notification, NotificationStore, validate_reason)

__all__ = [
    "EMAIL_MODES", "UNSUBSCRIBE_ALL", "EmailDelivery",
    "EmailError", "EmailNotificationStore", "Mailer",
    "SmtpConfig", "compose_digest", "compose_email",
    "decide_email", "make_unsubscribe_token",
    "parse_unsubscribe_token", "render_email_deliveries",
    "render_email_delivery", "smtp_config_from",
    "smtp_mailer", "unsubscribe_url", "validate_email_mode",
    "validate_scope",
]

# The instance's two delivery modes, in roadmap
# order: stored value -> the plain words it is
# shown under. Insertion order is display order.
EMAIL_MODES: dict[str, str] = {
    "per-event": "one email per notification",
    "digest": "queued and sent as one digest email",
}

# The scope that unsubscribes from every reason.
UNSUBSCRIBE_ALL = "all"

Mailer = Callable[[str, str, str], None]


class EmailError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class SmtpConfig:
    """The instance SMTP, named whole: a host, a
    port, and the from-address letters leave under.
    Credentials and TLS are the operator's choices.
    Nothing here is a secret store -- a password
    arrives from the operator's config and is held
    only in memory, per S-003."""
    host: str
    port: int
    from_address: str
    username: str = ""
    password: str = ""
    use_tls: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.host and self.from_address
                    and self.port > 0)


def smtp_config_from(settings: object) -> SmtpConfig | None:
    """Pure: the instance's SMTP from a settings
    mapping (keys `host`, `port`, `from_address`,
    and optionally `username`, `password`,
    `use_tls`). Absent or empty means the instance
    has no SMTP -- None, and no email is ever sent.
    A half-named SMTP (some of host / port /
    from_address, not all) is refused
    `smtp_config_invalid`, fail-closed: a silently
    dropped notification is worse than a loud
    refusal at configuration time."""
    if settings is None:
        return None
    if not isinstance(settings, dict):
        raise EmailError(
            "smtp_config_invalid",
            "SMTP settings must name host, port and "
            "from_address together, or be absent.")
    host = str(settings.get("host") or "").strip()
    from_address = str(
        settings.get("from_address") or "").strip()
    raw_port = settings.get("port") or 0
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        raise EmailError(
            "smtp_config_invalid",
            "SMTP port must be a number.") from None
    named = [bool(host), port > 0, bool(from_address)]
    if not any(named):
        return None
    if not all(named):
        raise EmailError(
            "smtp_config_invalid",
            "SMTP settings must name host, port and "
            "from_address together, or be absent.")
    return SmtpConfig(
        host=host, port=port, from_address=from_address,
        username=str(settings.get("username") or ""),
        password=str(settings.get("password") or ""),
        use_tls=bool(settings.get("use_tls")))


def smtp_mailer(config: SmtpConfig) -> Mailer:
    """The real transport for a configured instance:
    a mailer callable over `smtplib`, in S-026's
    seam shape. Building it opens no connection --
    each send connects, delivers one letter, and
    closes. Transport errors raise to the store,
    which records them on the delivery row."""
    def send(address: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = config.from_address
        message["To"] = address
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(config.host, config.port,
                          timeout=30) as smtp:
            if config.use_tls:
                smtp.starttls()
            if config.username:
                smtp.login(config.username, config.password)
            smtp.send_message(message)
    return send


def validate_email_mode(mode: object) -> str:
    """Pure: the stored mode for *mode*, or a refusal
    naming the honest pair."""
    if not isinstance(mode, str) or mode not in EMAIL_MODES:
        raise EmailError(
            "email_mode_invalid",
            "Email modes are: "
            + ", ".join(EMAIL_MODES) + ".")
    return mode


def validate_scope(scope: object) -> str:
    """Pure: an unsubscribe scope -- `all`, or one of
    S-223's seven reasons judged through its own
    door. Anything else is refused `scope_invalid`."""
    if scope == UNSUBSCRIBE_ALL:
        return UNSUBSCRIBE_ALL
    try:
        return validate_reason(scope)
    except ValueError:
        raise EmailError(
            "scope_invalid",
            "An unsubscribe scope is 'all' or one of "
            "the notification reasons.") from None


def decide_email(*, smtp_configured: bool,
                 email_address: str | None, mode: str,
                 unsubscribed_all: bool,
                 unsubscribed_reason: bool,
                 ) -> tuple[str, str]:
    """Pure: the whole delivery law. Returns
    ``(action, why)`` -- action is `send` (deliver
    now), `queue` (hold for the digest) or `skip`
    (no email, ever, for this notification); why
    names the ground in one stored word:
    `smtp_absent`, `no_email_address`,
    `unsubscribed`, `per_event` or `digest`. The
    mode is judged through its door first, so a
    shapeless mode is refused before any ground is
    weighed. Order is honesty order: an absent SMTP
    is the instance's fact and is said first."""
    stored_mode = validate_email_mode(mode)
    if not smtp_configured:
        return ("skip", "smtp_absent")
    if not email_address:
        return ("skip", "no_email_address")
    if unsubscribed_all or unsubscribed_reason:
        return ("skip", "unsubscribed")
    if stored_mode == "digest":
        return ("queue", "digest")
    return ("send", "per_event")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(key: bytes, user_id: int, scope: str) -> bytes:
    return hmac.new(key, f"{user_id}:{scope}".encode("utf-8"),
                    hashlib.sha256).digest()


def make_unsubscribe_token(key: bytes, user_id: int,
                           scope: object) -> str:
    """Pure: the signed token for one account and
    scope -- payload and HMAC-SHA256 signature,
    URL-safe. The scope is judged through its door,
    so a token can only ever name `all` or one of
    the seven reasons."""
    stored_scope = validate_scope(scope)
    payload = f"{int(user_id)}:{stored_scope}"
    return (_b64(payload.encode("utf-8")) + "."
            + _b64(_signature(key, int(user_id), stored_scope)))


def parse_unsubscribe_token(key: bytes,
                            token: object,
                            ) -> tuple[int, str] | None:
    """Pure: ``(user_id, scope)`` for a genuine
    token, else None -- forged, tampered, wrong-key,
    expired-shape and shapeless tokens are all the
    same None, compared in constant time, so the
    redemption endpoint answers one generic refusal
    and leaks nothing about which tokens exist."""
    if not isinstance(token, str) or token.count(".") != 1:
        return None
    payload_part, sig_part = token.split(".")
    try:
        payload = _unb64(payload_part).decode("utf-8")
        given = _unb64(sig_part)
        user_text, scope = payload.split(":", 1)
        user_id = int(user_text)
        stored_scope = validate_scope(scope)
    except (ValueError, UnicodeDecodeError):
        return None
    if stored_scope != scope or user_id <= 0:
        return None
    expected = _signature(key, user_id, stored_scope)
    if not hmac.compare_digest(given, expected):
        return None
    return (user_id, stored_scope)


def unsubscribe_url(base_url: str, key: bytes, user_id: int,
                    scope: object) -> str:
    """Pure: the unsubscribe link itself -- the
    instance base ('' for a relative link) plus the
    signed token's path."""
    token = make_unsubscribe_token(key, user_id, scope)
    return f"{base_url.rstrip('/')}/unsubscribe/{token}"


def compose_email(notification: Notification, link: str,
                  all_link: str,
                  ) -> tuple[str, str]:
    """Pure: one notification as one plain-text
    letter -- ``(subject, body)``. The subject and
    the body's first lines say who acted, on what,
    and the stored reason in S-223's plain words;
    the letter ends with its unsubscribe links (this
    reason, and all email) so the way out travels
    with every letter."""
    subject = f"Samverk: {notification.words}"
    lines = [
        notification.words,
        "",
        f"Reason: {notification.reason_words} "
        f"({notification.reason}).",
        f"What: {notification.target_kind or 'activity'} "
        f"{notification.target_id}".rstrip(),
        "",
        "This email was sent because the instance SMTP "
        "is configured; your in-app inbox holds the "
        "same notification either way.",
        f"Unsubscribe from '{notification.reason}' email: "
        f"{link}",
        f"Unsubscribe from all notification email: "
        f"{all_link}",
    ]
    return (subject, "\n".join(lines) + "\n")


def compose_digest(notifications, link: str,
                   all_link: str,
                   ) -> tuple[str, str]:
    """Pure: many notifications as one digest letter
    -- ``(subject, body)``. Every entry is numbered
    and says its reason in plain words; the letter
    ends with the `all` unsubscribe link (a digest
    spans reasons, so its one honest way out is the
    whole door) plus the caller's per-scope link."""
    rows = list(notifications)
    subject = (f"Samverk: {len(rows)} notification"
               f"{'s' if len(rows) != 1 else ''} in your digest")
    lines = [f"Your Samverk digest: {len(rows)} "
             f"notification{'s' if len(rows) != 1 else ''}.", ""]
    for index, note in enumerate(rows, start=1):
        lines.append(f"{index}. {note.words}")
    lines += [
        "",
        "These notifications are also in your in-app "
        "inbox.",
        f"Unsubscribe from all notification email: "
        f"{all_link}",
        f"Unsubscribe: {link}",
    ]
    return (subject, "\n".join(lines) + "\n")


@dataclass(frozen=True)
class EmailDelivery:
    id: int
    notification_id: int
    recipient_id: int
    recipient: str       # display case; '' when unknown
    email_address: str   # the address judged; '' when none
    mode: str            # per-event | digest, as configured
    status: str          # sent | queued | skipped | failed
    why: str             # decision ground, stored
    created_at: int
    sent_at: int | None

    @property
    def words(self) -> str:
        """The delivery said in plain words -- its
        mode, its status, and the ground it stands
        on, said outright."""
        return (f"Email for {self.recipient or 'a recipient'} "
                f"(notification {self.notification_id}): "
                f"{self.status} under "
                f"{EMAIL_MODES.get(self.mode, self.mode)} "
                f"-- {self.why}.")


class EmailNotificationStore:
    """The delivery ledger and the mailer seam.

    ``mailer=None`` is the honest shape of an
    instance with no SMTP configured: deliveries are
    decided and recorded as skipped, and nothing is
    ever sent. ``signing_key`` is the instance secret
    unsubscribe tokens are signed under (S-003: it is
    handed in from the secret store and never lands
    in the database)."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        notifications: NotificationStore,
        mailer: Mailer | None = None,
        signing_key: bytes = b"",
        mode: object = "per-event",
        base_url: str = "",
        time_fn: Callable[[], float] = time.time,
    ):
        if not signing_key:
            raise EmailError(
                "signing_key_required",
                "Email notification needs the instance "
                "signing key to sign unsubscribe links.")
        self._conn = conn
        self._accounts = accounts
        self._notifications = notifications
        self._mailer = mailer
        self._key = bytes(signing_key)
        self._mode = validate_email_mode(mode)
        self._base_url = str(base_url)
        self._now = time_fn

    @property
    def smtp_configured(self) -> bool:
        return self._mailer is not None

    @property
    def mode(self) -> str:
        return self._mode

    # -- links ------------------------------------------------
    def unsubscribe_link(self, user_id: int,
                         scope: object) -> str:
        return unsubscribe_url(
            self._base_url, self._key, user_id, scope)

    # -- opt-outs -----------------------------------------------
    def is_unsubscribed(self, user_id: int,
                        scope: object) -> bool:
        """True when an opt-out row covers *scope* for
        this account -- its own row, or the `all` row
        covering every reason."""
        stored_scope = validate_scope(scope)
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM email_optouts"
            " WHERE user_id = ? AND scope IN (?, ?)",
            (int(user_id), stored_scope, UNSUBSCRIBE_ALL),
        ).fetchone()
        return int(row["n"]) > 0

    def unsubscribe(self, token: object) -> tuple[int, str]:
        """Redeem a signed unsubscribe link: record the
        opt-out it names and return ``(user_id,
        scope)``. One generic refusal for every bad
        token, and a redemption naming an account that
        does not exist is refused the same way -- the
        endpoint cannot be probed. Idempotent: a
        second redemption of the same link records
        nothing new. Commits before the answer."""
        parsed = parse_unsubscribe_token(self._key, token)
        if parsed is None:
            raise EmailError(
                "unsubscribe_token_invalid",
                "That unsubscribe link is invalid.")
        user_id, scope = parsed
        if self._accounts.get_by_id(user_id) is None:
            raise EmailError(
                "unsubscribe_token_invalid",
                "That unsubscribe link is invalid.")
        with self._conn:  # commits before the answer
            self._conn.execute(
                "INSERT OR IGNORE INTO email_optouts"
                " (user_id, scope, created_at)"
                " VALUES (?, ?, ?)",
                (user_id, scope, int(self._now())))
        return (user_id, scope)

    def opt_out(self, user: User | None,
                scope: object) -> bool:
        """The signed-in face of the same record:
        True exactly when this call recorded a new
        opt-out for the caller's own account."""
        if user is None:
            raise EmailError(
                "authentication_required",
                "Sign in to change your email choices.")
        stored_scope = validate_scope(scope)
        with self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO email_optouts"
                " (user_id, scope, created_at)"
                " VALUES (?, ?, ?)",
                (user.id, stored_scope, int(self._now())))
        return cur.rowcount > 0

    def resubscribe(self, user: User | None,
                    scope: object) -> bool:
        """Undo an opt-out for the caller's own
        account: True exactly when a row was removed.
        Commits before the answer."""
        if user is None:
            raise EmailError(
                "authentication_required",
                "Sign in to change your email choices.")
        stored_scope = validate_scope(scope)
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM email_optouts"
                " WHERE user_id = ? AND scope = ?",
                (user.id, stored_scope))
        return cur.rowcount > 0

    # -- delivery -----------------------------------------------
    def deliver(self, notification: Notification,
                ) -> EmailDelivery:
        """Decide and record the email fate of one
        S-223 notification, exactly once: a standing
        delivery row for this notification is returned
        unchanged and nothing is sent twice. Under
        per-event a decided send leaves in this call;
        under digest it queues for `flush_digest`.
        Transport failure is recorded (`failed`) and
        never raised -- the in-app notification
        stands either way. Commits before the
        answer."""
        existing = self._conn.execute(
            "SELECT * FROM email_deliveries"
            " WHERE notification_id = ?",
            (notification.id,)).fetchone()
        if existing is not None:
            return self._to_delivery(existing)
        recipient = self._accounts.get_by_id(
            notification.recipient_id)
        if recipient is None:
            raise EmailError(
                "no_such_user", "No such account.")
        address = recipient.email or ""
        action, why = decide_email(
            smtp_configured=self.smtp_configured,
            email_address=recipient.email,
            mode=self._mode,
            unsubscribed_all=self.is_unsubscribed(
                recipient.id, UNSUBSCRIBE_ALL),
            unsubscribed_reason=self.is_unsubscribed(
                recipient.id, notification.reason))
        status = {"queue": "queued",
                  "skip": "skipped"}.get(action, "")
        sent_at = None
        if action == "send":
            # The letter leaves first and the row is
            # written once, carrying the true outcome:
            # a recorded `sent` always means the
            # transport accepted the letter, and a
            # transport failure is recorded `failed`,
            # never raised into the caller's mutation.
            status, sent_at = self._send_one(
                recipient, notification)
        now = int(self._now())
        with self._conn:  # commits before the answer
            cur = self._conn.execute(
                "INSERT INTO email_deliveries"
                " (notification_id, recipient_id,"
                " email_address, mode, status, why,"
                " created_at, sent_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (notification.id, recipient.id, address,
                 self._mode, status, why, now, sent_at))
            delivery_id = int(cur.lastrowid)
        row = self._conn.execute(
            "SELECT * FROM email_deliveries WHERE id = ?",
            (delivery_id,)).fetchone()
        return self._to_delivery(row)

    def _send_one(self, recipient: User,
                  notification: Notification,
                  ) -> tuple[str, int | None]:
        """Send one per-event letter. Returns
        ``(status, sent_at)`` -- `sent` with the time
        when the transport accepted the letter,
        `failed` with None when it did not; a
        transport error is a status, never an
        exception in the caller's face."""
        assert self._mailer is not None  # decided send
        assert recipient.email is not None
        subject, body = compose_email(
            notification,
            self.unsubscribe_link(recipient.id,
                                  notification.reason),
            self.unsubscribe_link(recipient.id,
                                  UNSUBSCRIBE_ALL))
        try:
            self._mailer(recipient.email, subject, body)
        except Exception:
            return ("failed", None)
        return ("sent", int(self._now()))

    def flush_digest(self, user: User | None) -> int:
        """Send one digest letter carrying every
        queued notification for *user*, and return
        how many notifications it carried (0 when
        nothing was queued or nothing could be sent).
        Each queued row is re-judged at the door of
        the flush: an opt-out recorded since queueing
        marks its row skipped and keeps it out of the
        letter; an SMTP that has gone absent leaves
        the queue standing for a later flush. A
        transport failure leaves the rows queued, so
        nothing is lost and nothing is sent twice.
        Commits before the answer."""
        if user is None:
            raise EmailError(
                "authentication_required",
                "Sign in to receive your digest.")
        rows = self._conn.execute(
            "SELECT * FROM email_deliveries"
            " WHERE recipient_id = ? AND status = 'queued'"
            " ORDER BY id", (user.id,)).fetchall()
        if not rows:
            return 0
        if not self.smtp_configured or not user.email:
            return 0
        notes = []
        sendable = []
        for row in rows:
            note = self._notification_for(row)
            if note is None:
                continue
            if self.is_unsubscribed(user.id, note.reason):
                with self._conn:
                    self._conn.execute(
                        "UPDATE email_deliveries"
                        " SET status = 'skipped',"
                        " why = 'unsubscribed' WHERE id = ?",
                        (int(row["id"]),))
                continue
            notes.append(note)
            sendable.append(int(row["id"]))
        if not notes:
            return 0
        subject, body = compose_digest(
            notes,
            self.unsubscribe_link(user.id, UNSUBSCRIBE_ALL),
            self.unsubscribe_link(user.id, UNSUBSCRIBE_ALL))
        try:
            self._mailer(user.email, subject, body)
        except Exception:
            return 0  # still queued; a later flush retries
        now = int(self._now())
        with self._conn:  # commits before the answer
            for delivery_id in sendable:
                self._conn.execute(
                    "UPDATE email_deliveries"
                    " SET status = 'sent', sent_at = ?"
                    " WHERE id = ?", (now, delivery_id))
        return len(notes)

    # -- reads ------------------------------------------------
    def deliveries_for(self, user: User | None, *,
                       limit: int = 100,
                       ) -> list[EmailDelivery]:
        """The recipient's own delivery rows, oldest
        first. An anonymous caller sees nothing --
        deliveries belong to their recipient."""
        if user is None:
            return []
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT * FROM email_deliveries"
            " WHERE recipient_id = ? ORDER BY id LIMIT ?",
            (user.id, clamped)).fetchall()
        return [self._to_delivery(r) for r in rows]

    def pending_digest_count(self, user: User | None) -> int:
        """How many of the recipient's notifications
        are queued for the next digest."""
        if user is None:
            return 0
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM email_deliveries"
            " WHERE recipient_id = ?"
            " AND status = 'queued'",
            (user.id,)).fetchone()
        return int(row["n"])

    # -- internals ----------------------------------------------
    def _notification_for(self, row: sqlite3.Row,
                          ) -> Notification | None:
        """The S-223 notification one delivery row
        carries, rebuilt from its own table through
        the recipient's list (the canonical store is
        the only reader of its rows)."""
        recipient = self._accounts.get_by_id(
            int(row["recipient_id"]))
        if recipient is None:
            return None
        for note in self._notifications.list_for_recipient(
                recipient, limit=500):
            if note.id == int(row["notification_id"]):
                return note
        return None

    def _to_delivery(self, row: sqlite3.Row) -> EmailDelivery:
        recipient = self._accounts.get_by_id(
            int(row["recipient_id"]))
        return EmailDelivery(
            id=int(row["id"]),
            notification_id=int(row["notification_id"]),
            recipient_id=int(row["recipient_id"]),
            recipient=recipient.username if recipient else "",
            email_address=row["email_address"],
            mode=row["mode"], status=row["status"],
            why=row["why"], created_at=int(row["created_at"]),
            sent_at=row["sent_at"])


def render_email_delivery(delivery: EmailDelivery) -> str:
    """One delivery, in plain words -- its mode,
    status and ground said outright."""
    return (
        '<li class="email-delivery">'
        f"{escape_html_text(delivery.words)}</li>")


def render_email_deliveries(rows) -> str:
    """A recipient's email deliveries in plain words.
    The empty state teaches the model in one screen:
    email exists only when the instance SMTP is
    configured, the in-app inbox works either way,
    and every letter carries its unsubscribe link.
    Never a colour alone; every value escapes
    through S-010."""
    rows = list(rows)
    if not rows:
        return ('<p class="email-deliveries">No notification '
                "email yet. Email is sent only when this "
                "instance has SMTP configured -- per-event "
                "or as a digest -- and your in-app inbox "
                "holds every notification either way. Every "
                "letter carries a signed unsubscribe link "
                "for its reason, and one for all email.</p>")
    items = "".join(render_email_delivery(r) for r in rows)
    return f'<ul class="email-deliveries">{items}</ul>'
