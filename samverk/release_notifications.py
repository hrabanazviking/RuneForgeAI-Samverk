"""Release notifications (S-262).

Watchers are notified when a release is **published**
— and only then. S-222 gave a repository three watch
modes (`all`, `releases_only`, `ignore`); S-257/S-258
gave releases their states, and publication its one
witness, the standing audit verb
`repo.release.publish`. This slice is the wire
between them, under six laws:

- **Publication is the witnessed act, so the
  witness is the source.** Every door that
  publishes — a web or API creation that is not a
  draft, a tag push, and `publish_release` on a
  draft — writes exactly one
  `repo.release.publish` audit row (S-257), and a
  draft creation or a draft edit writes none: a
  draft is not a publication, and S-257 witnesses
  nothing for it. This store materialises those
  rows into addressed notifications, so draft
  saves notify nobody *by construction* — there
  is no row to derive from — and no publishing
  door can forget to notify, because none of them
  carries the duty: the witness does.
- **Derived exactly once.** One delivery per
  (audit row, recipient), enforced by migration
  103's `release_notification_deliveries` ledger
  with its UNIQUE pair — syncing twice notifies
  nobody twice, a refused or no-op act (which
  never reached the audit log) notifies nobody at
  all, and a second publication is a second audit
  row and rightly a second notification. The
  pattern is S-165's, over the release verb.
- **Both counted watch modes are notified —
  releases-only watchers expressly included.**
  The pure `decide_release_notify` is the whole
  addressing law: `all` notifies, `releases_only`
  notifies (a release publication is exactly what
  that mode means — the contrast is S-225, where
  `releases_only` does *not* notify thread
  activity), and `ignore` — a stored opt-out, not
  a watch — and no watch row notify nobody. A
  prerelease publication is a publication (it
  stands published, S-258) and notifies like any
  other; only drafts are silent, because only
  drafts are unpublished.
- **Addressed means resolvable, readable, and
  not oneself** (S-165/S-209's law at emission):
  the publisher is never notified of their own
  publication, a watch whose holder can no
  longer read the repository delivers nothing
  (a notification never reveals a release its
  recipient cannot read), and the watch standing
  is judged as it stands at delivery — the sync
  reads the watch rows that stand when it runs,
  as S-165 judges readability when it runs.
- **The delivery is an ordinary S-223
  notification.** Each delivery is created
  through `NotificationStore.notify` under
  S-223's reason `subscribed` — the watch itself
  is why it reached the recipient — with the
  verb, the repository, the tag, and the watch
  mode that carried it kept in the detail, so
  the inbox, its filters, its triage, and email
  all see release deliveries with no second
  model. The ledger row points at the
  notification it delivered.
- **Reads belong to their holder.** A
  recipient's delivery list takes the recipient
  themself and syncs first, so it is never
  stale; the per-release listing reads through
  the release's own gate (S-258), so a draft
  answers `release_not_found` to a non-writer
  and a private repository `repo_not_found` to
  a stranger — a delivery never names a release
  its viewer may not see. Renders say every
  state in plain words through S-010's seam.

One migration: 103 creates
`release_notification_deliveries` (schema 102 to
103). No new taxonomy event: delivery is the
echo of a publication already witnessed under
its own verb, as S-165's and S-223's stores
record nothing of their own; 131 events stand
(33 auth / 85 repo / 13 admin).
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .notification_reasons import (
    NOTIFICATION_REASONS, NotificationStore)
from .permissions import can_read
from .releases import ReleaseError, ReleaseStore
from .repositories import Repository, RepositoryStore
from .watch_star import COUNTED_WATCH_MODES

__all__ = [
    "NOTIFYING_WATCH_MODES", "PUBLISH_VERB", "REASON",
    "ReleaseDelivery", "ReleaseNotificationError",
    "ReleaseNotificationStore", "decide_release_notify",
    "decide_release_recipients", "delivery_to_dict",
    "render_release_notification",
    "render_release_notifications",
]

# The one witnessed act this store derives from:
# S-257's publication verb, standing in the frozen
# taxonomy since its founding.
PUBLISH_VERB = "repo.release.publish"

# The S-223 reason every release delivery carries:
# the recipient's own watch is why it reached them.
REASON = "subscribed"

# The watch modes a release publication notifies:
# both of S-222's counted modes. `ignore` is a
# stored choice, not a watch, and is absent on
# purpose — see decide_release_notify.
NOTIFYING_WATCH_MODES = COUNTED_WATCH_MODES


class ReleaseNotificationError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def decide_release_notify(watch_mode: object) -> bool:
    """Pure: whether a release publication notifies
    a holder of *watch_mode*. Both counted modes
    notify — `all`, and `releases_only` expressly
    (a publication is the one act that mode exists
    for); `ignore`, no watch row (None), and any
    other value do not."""
    return watch_mode in NOTIFYING_WATCH_MODES


def decide_release_recipients(
        watchers: Iterable[tuple[int, str]],
        actor_id: int | None) -> tuple[tuple[int, str], ...]:
    """Pure: the (user_id, watch_mode) pairs one
    publication notifies, from the repository's
    standing watch rows in their stored order:
    counted modes only, the publisher removed
    (nobody is notified of their own act), each
    holder once — the first standing row for a
    holder is their mode."""
    out: list[tuple[int, str]] = []
    seen: set[int] = set()
    for user_id, mode in watchers:
        if not decide_release_notify(mode):
            continue
        if actor_id is not None and user_id == actor_id:
            continue
        if user_id in seen:
            continue
        seen.add(user_id)
        out.append((user_id, mode))
    return tuple(out)


@dataclass(frozen=True)
class ReleaseDelivery:
    """One addressed release notification: the
    ledger row, naming the S-223 notification it
    delivered, the publication it derived from,
    and the watch mode that carried it."""
    id: int
    notification_id: int
    audit_seq: int
    repo_id: int
    repository: str      # full name, display case
    release_id: int | None
    tag: str
    recipient_id: int
    recipient: str       # display case; '' when unknown
    actor_id: int | None
    actor: str           # display case; '' when none
    watch_mode: str      # the mode that carried it
    reason: str          # stored; REASON today
    created_at: int

    @property
    def reason_words(self) -> str:
        return NOTIFICATION_REASONS.get(self.reason, self.reason)

    @property
    def words(self) -> str:
        """The delivery said in plain words — who
        published, what, where, the watch that
        carried it, and the reason it reached this
        recipient, said outright."""
        who = self.actor or "Someone"
        return (f"{who} published release {self.tag} in "
                f"{self.repository} (watch: "
                f"{self.watch_mode}; reason: "
                f"{self.reason_words}).")


def delivery_to_dict(delivery: ReleaseDelivery) -> dict:
    """One delivery as plain data, in a stable
    field order — the programmatic face of the
    same record the renderers say in words."""
    return {
        "repository": delivery.repository,
        "tag": delivery.tag,
        "release_id": delivery.release_id,
        "recipient": delivery.recipient,
        "actor": delivery.actor,
        "watch_mode": delivery.watch_mode,
        "reason": delivery.reason,
        "verb": PUBLISH_VERB,
        "notification_id": delivery.notification_id,
        "created_at": delivery.created_at,
    }


class ReleaseNotificationStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        releases: ReleaseStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._releases = releases if releases is not None else (
            ReleaseStore(conn, repositories, accounts,
                         audit=audit, time_fn=time_fn))
        self._notifications = NotificationStore(
            conn, accounts, time_fn=time_fn)
        self._now = time_fn

    # -- materialisation ----------------------------------
    def sync_repo(self, owner: object, repo: object) -> int:
        """Materialise this repository's witnessed
        publications into watcher notifications;
        returns how many deliveries were newly made
        (0 on a re-sync — exactly-once is the
        ledger's UNIQUE pair doing its work)."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise ReleaseNotificationError(
                "repo_not_found", "No such repository.")
        return self._sync(current)

    def sync_all(self) -> int:
        """Materialise every repository's new
        release notifications; returns the total
        newly delivered."""
        total = 0
        rows = self._conn.execute(
            "SELECT id FROM repositories ORDER BY id").fetchall()
        for row in rows:
            current = self._repos.get_by_id(int(row["id"]))
            if current is not None:
                total += self._sync(current)
        return total

    def _sync(self, current: Repository) -> int:
        rows = self._conn.execute(
            "SELECT seq, ts, actor_id, detail FROM audit_log"
            " WHERE action = ? AND target_kind = 'repo'"
            " AND target_id = ? ORDER BY seq",
            (PUBLISH_VERB, current.full_name)).fetchall()
        if not rows:
            return 0
        watchers = tuple(
            (int(r["user_id"]), r["mode"]) for r in
            self._conn.execute(
                "SELECT user_id, mode FROM repo_watches"
                " WHERE repo_id = ? ORDER BY created_at, id",
                (current.id,)).fetchall())
        delivered = 0
        for row in rows:
            try:
                detail = json.loads(row["detail"] or "{}")
            except ValueError:
                detail = {}
            if not isinstance(detail, dict):
                detail = {}
            tag = detail.get("tag")
            if not isinstance(tag, str) or not tag:
                continue  # a witness that names no release
            actor_id = row["actor_id"]
            actor = (self._accounts.get_by_id(int(actor_id))
                     if actor_id else None)
            release_id = self._release_id(current.id, tag)
            for user_id, mode in decide_release_recipients(
                    watchers, actor_id):
                if self._delivered(int(row["seq"]), user_id):
                    continue  # already delivered — exactly once
                recipient = self._accounts.get_by_id(user_id)
                if recipient is None or not can_read(
                        recipient, current):
                    continue  # never reveal what they cannot read
                note = self._notifications.notify(
                    recipient, actor, REASON, verb=PUBLISH_VERB,
                    target_kind="release",
                    target_id=current.full_name,
                    detail={"repo": current.full_name,
                            "tag": tag, "watch_mode": mode})
                with self._conn:
                    cur = self._conn.execute(
                        "INSERT OR IGNORE INTO"
                        " release_notification_deliveries"
                        " (notification_id, audit_seq,"
                        " recipient_id, actor_id, repo_id,"
                        " release_id, tag, watch_mode,"
                        " created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (note.id, int(row["seq"]), user_id,
                         actor_id, current.id, release_id,
                         tag, mode, int(row["ts"])))
                delivered += int(cur.rowcount)
        return delivered

    def _delivered(self, audit_seq: int, user_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 AS x FROM release_notification_deliveries"
            " WHERE audit_seq = ? AND recipient_id = ?",
            (audit_seq, user_id)).fetchone()
        return row is not None

    def _release_id(self, repo_id: int,
                    tag: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM releases WHERE repo_id = ?"
            " AND tag = ?", (repo_id, tag)).fetchone()
        return int(row["id"]) if row else None

    # -- reads ----------------------------------------------
    def deliveries_for_recipient(
            self, user: User | None, *, limit: int = 100
            ) -> list[ReleaseDelivery]:
        """The recipient's own release deliveries,
        oldest first. Syncs every repository first,
        so the answer is never stale; an inbox
        belongs to its recipient, so there is no
        cross-user read and an anonymous caller has
        none at all."""
        if user is None:
            raise ReleaseNotificationError(
                "authentication_required",
                "Sign in to see your release notifications.")
        self.sync_all()
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT * FROM release_notification_deliveries"
            " WHERE recipient_id = ? ORDER BY id LIMIT ?",
            (user.id, clamped)).fetchall()
        return [self._to_delivery(r) for r in rows]

    def count_for_recipient(self, user: User | None) -> int:
        if user is None:
            raise ReleaseNotificationError(
                "authentication_required",
                "Sign in to see your release notifications.")
        self.sync_all()
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM"
            " release_notification_deliveries"
            " WHERE recipient_id = ?", (user.id,)).fetchone()
        return int(row["n"])

    def deliveries_for_release(
            self, viewer: User | None, owner: object,
            repo: object, tag: object, *, limit: int = 100
            ) -> list[ReleaseDelivery]:
        """Every delivery addressed for this release,
        oldest first. The release is read through
        its own gate first (S-258), so a stranger to
        a private repository gets the uniform
        `repo_not_found` and a draft the viewer may
        not see answers `release_not_found` — in
        this store's error shape — before any
        delivery is named; the repository syncs
        before the listing, so it is never stale."""
        try:
            release = self._releases.get_release(
                viewer, owner, repo, tag)
        except ReleaseError as exc:
            raise ReleaseNotificationError(
                exc.reason, str(exc)) from None
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        self._sync(current)
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT * FROM release_notification_deliveries"
            " WHERE repo_id = ? AND release_id = ?"
            " ORDER BY id LIMIT ?",
            (current.id, release.id, clamped)).fetchall()
        return [self._to_delivery(r, current) for r in rows]

    def _to_delivery(self, row: sqlite3.Row,
                     current: Repository | None = None
                     ) -> ReleaseDelivery:
        if current is None:
            current = self._repos.get_by_id(int(row["repo_id"]))
        recipient = self._accounts.get_by_id(
            int(row["recipient_id"]))
        actor = (self._accounts.get_by_id(int(row["actor_id"]))
                 if row["actor_id"] else None)
        tag = row["tag"]
        return ReleaseDelivery(
            id=int(row["id"]),
            notification_id=int(row["notification_id"]),
            audit_seq=int(row["audit_seq"]),
            repo_id=int(row["repo_id"]),
            repository=(current.full_name
                        if current is not None else ""),
            release_id=row["release_id"],
            tag=tag,
            recipient_id=int(row["recipient_id"]),
            recipient=recipient.username if recipient else "",
            actor_id=row["actor_id"],
            actor=actor.username if actor else "",
            watch_mode=row["watch_mode"], reason=REASON,
            created_at=int(row["created_at"]))


def render_release_notification(delivery: ReleaseDelivery) -> str:
    """One release delivery, in plain words."""
    return (
        '<li class="release-notification">'
        f"{escape_html_text(delivery.words)}</li>")


def render_release_notifications(rows) -> str:
    """Release deliveries in plain words — each
    one's publisher, release, repository, watch
    mode, and stored reason said outright. Never
    a colour alone; every value escapes through
    S-010. The empty state teaches the law: only
    a publication notifies, and drafts never do."""
    rows = list(rows)
    if not rows:
        return ('<p class="release-notifications">No release '
                "notifications yet. When a repository you "
                "watch — for all activity, or for releases "
                "only — publishes a release, it will be "
                "said here. Drafts are saved silently: "
                "only a publication notifies.</p>")
    items = "".join(render_release_notification(r) for r in rows)
    return f'<ul class="release-notifications">{items}</ul>'
