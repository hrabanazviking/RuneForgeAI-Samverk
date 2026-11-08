"""Mention routing (S-226).

Part XI's router: ``@user`` and ``@org/team``
mentions in prose create notifications -- once,
never duplicated by cross-reference echoes. Before
this slice the two doors stood apart and one of
them led nowhere a person could read: ``@org/team``
materialised S-195's own ``team_mention_notifications``
rows, ``@user`` autolinked in S-109's rendering but
notified nobody at all, and S-223's canonical
``notifications`` table carried the ``mention``
reason with no router ever delivering under it.
This module is that router, under six laws:

- **One source, one notification per recipient.**
  A source is one piece of primary prose -- an
  issue or pull request body, or one live comment
  on it. However many mention paths in that source
  lead to the same person -- named directly,
  reached through one mentioned team, reached
  through two -- the person receives exactly one
  S-223 notification (reason ``mention``) for that
  source. The delivery ledger (migration 90's
  ``mention_deliveries``, UNIQUE on source +
  recipient) is the enforcement, and the pure
  ``decide_mention_recipients`` is the law it
  enforces: every resolved recipient id, each
  once, in the order the prose first reaches them,
  the author removed -- nobody is notified of
  their own act. The paths that reached a person
  are kept on the delivery as its ``via`` (the
  ``@user`` token and/or each ``@org/team`` token),
  so the one notification honestly says how it
  arrived, and S-369's bridge inherits the same
  exactly-once rule across the seam.
- **Cross-reference echoes never notify.** Only
  primary prose is ever a source. S-127's
  cross-reference record, the back-reference it
  leaves on the mentioned thread (``mentioned in
  #5``), and the timeline/conversation entries
  derived from it are echoes of prose already
  routed: routing reads bodies and live comments
  only, never the cross-reference table, so
  syncing cross-references before or after
  routing changes no count, and routing the
  *target* thread of a mentioning text creates
  nothing there -- the mention lives where it was
  written, and notifies there once.
- **Only proven mentions are routed** (S-109's
  honesty law, S-195's seam). A ``@user`` resolves
  only when the account exists; an ``@org/team``
  resolves only through S-195's own resolution --
  the organization and team must exist, and a
  *secret* team named by someone who may not see
  it resolves to nothing, so a mention never leaks
  a secret team's existence. The team's recipients
  are its S-188 effective members, exactly as
  S-195 expands them. Nobody is notified who
  cannot read the repository the mention stands
  in (S-054's ``can_read``: a notification never
  reveals work its recipient cannot read), and
  code is not prose: tokens inside fenced blocks
  or inline spans were quoted, not said, and
  route to nobody (S-127/S-195's stripping,
  mirrored).
- **The record follows the text, and read state
  is kept.** Routing is a sync, not an append:
  re-syncing a source whose mentions still stand
  keeps each standing delivery's notification --
  the same row, its read state untouched -- so a
  re-save, a retry, or a second sync can never
  duplicate. An edit that adds a mention delivers
  to the newly named; an edit that removes one
  withdraws its delivery whole (notification,
  inbox triage, and ledger row together), and a
  tombstoned comment's mentions die with its
  body. ``sync_issue`` covers a body and its live
  comments in one pass.
- **A mute still mutes** (S-225). A recipient who
  has muted the thread receives no mention
  delivery for it -- the per-thread override wins
  over a mention as it wins over every other
  thread notification -- and clearing the mute
  and re-syncing delivers what stands. A
  ``subscribed`` override changes nothing here:
  the mention reason is why the notification
  exists, and it still arrives exactly once.
- **Reasons are stored and said** (S-223). Every
  delivery is an ordinary S-223 notification
  under reason ``mention``, created through
  ``NotificationStore.notify`` -- so the inbox,
  its filters, and its triage all see mention
  deliveries with no second model -- and the
  renderers say the reason's plain words
  outright, every value through S-010.

No new taxonomy event: routing is the delivery
of acts already witnessed under their own verbs
(the prose's creation/edit, judged like S-195's
and S-223's own stores, which record nothing of
their own); 127 events stand. One migration: 90
creates ``mention_deliveries``.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .issues import IssueError
from .notification_reasons import NotificationStore
from .permissions import can_read
from .repositories import Repository
from .team_mentions import TeamMentionStore

__all__ = [
    "SOURCE_KINDS", "MentionDelivery", "MentionToken",
    "MentionRoutingStore", "decide_mention_recipients",
    "parse_mention_tokens", "parse_user_mentions",
    "render_mention_deliveries", "render_mention_delivery",
]

SOURCE_KINDS = frozenset({"issue", "pull_request", "comment"})

# The mention shape, one pass over prose: ``@user``
# or ``@org/team``. The leading guard is S-195's:
# the ``@`` must not be glued to a word, address or
# path character before it, so an email address or
# a path never reads as a mention. Both segments
# carry the S-152 reviewer-token shape.
_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9._@/-])"
    r"@([A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:/([A-Za-z0-9][A-Za-z0-9._-]*))?")
_FENCE_RE = re.compile(r"^\s{0,3}(```+|~~~+)")
_INLINE_CODE_RE = re.compile(r"``.+?``|`[^`\n]+`", re.DOTALL)


def _prose_only(text: str) -> str:
    """The text with code removed (S-127/S-195's
    helper, mirrored): fenced blocks dropped line
    by line, inline spans blanked. What remains is
    what the author *said*."""
    kept: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        marker = _FENCE_RE.match(line)
        if marker:
            run = marker.group(1)
            if fence is None:
                fence = run[0]
                continue
            if run[0] == fence:
                fence = None
                continue
        if fence is None:
            kept.append(line)
    return _INLINE_CODE_RE.sub(" ", "\n".join(kept))


@dataclass(frozen=True)
class MentionToken:
    """One mention a piece of prose makes: a direct
    ``@user`` (``kind == \"user\"``, ``team == \"\"``)
    or an ``@org/team`` (``kind == \"team\"``). Names
    are lowercased for resolution; ``text`` is the
    canonical token as addressed."""
    kind: str        # 'user' | 'team'
    user: str        # the username, or the org name
    team: str        # the team slug; '' for a user

    @property
    def text(self) -> str:
        if self.kind == "team":
            return f"@{self.user}/{self.team}"
        return f"@{self.user}"


def parse_mention_tokens(text: object) -> list[MentionToken]:
    """Every mention a piece of prose makes -- direct
    and team tokens together, in the order written,
    duplicates folded. Pure: existence is the
    store's question, not the parser's. Code spans
    and fences never parse."""
    if not isinstance(text, str) or not text:
        return []
    prose = _prose_only(text)
    found: list[MentionToken] = []
    seen: set[tuple[str, str, str]] = set()
    for match in _TOKEN_RE.finditer(prose):
        if match.group(2) is not None:
            token = MentionToken(
                kind="team", user=match.group(1).lower(),
                team=match.group(2).lower())
        else:
            token = MentionToken(
                kind="user", user=match.group(1).lower(), team="")
        key = (token.kind, token.user, token.team)
        if key not in seen:
            seen.add(key)
            found.append(token)
    return found


def parse_user_mentions(text: object) -> list[str]:
    """The direct ``@user`` names a piece of prose
    makes, lowercased, in the order written,
    duplicates folded. An ``@org/team`` token is a
    team mention, never a user mention of the org."""
    return [t.user for t in parse_mention_tokens(text)
            if t.kind == "user"]


def decide_mention_recipients(ordered_ids, actor_id: int | None) -> tuple:
    """Pure recipient law: the resolved recipient
    ids, each once, in the order given, with the
    actor removed -- nobody is notified of their
    own act, and no path to a person counts twice."""
    out: list[int] = []
    seen: set[int] = set()
    for user_id in ordered_ids:
        if user_id in seen or user_id == actor_id:
            continue
        seen.add(user_id)
        out.append(user_id)
    return tuple(out)


@dataclass(frozen=True)
class MentionDelivery:
    """One exactly-once delivery: a recipient heard
    a mention in one source, under S-223's reason
    ``mention``, by the paths named in ``via``."""
    id: int
    notification_id: int
    recipient_id: int
    recipient: str           # display case
    actor_id: int | None
    actor: str               # display case; '' when unrecorded
    source_kind: str         # SOURCE_KINDS
    repo_id: int
    repository: str          # "owner/name", display case
    number: int              # the issue / PR number the source stands on
    comment_id: int          # issue_comments id; 0 unless a comment
    via: tuple               # of canonical mention tokens, in prose order
    created_at: int

    @property
    def source_words(self) -> str:
        if self.source_kind == "comment":
            return (f"a comment on {self.repository} "
                    f"#{self.number}")
        kind = ("pull request" if self.source_kind == "pull_request"
                else "issue")
        return f"{self.repository} {kind} #{self.number}"

    @property
    def words(self) -> str:
        """The delivery in one plain sentence: who
        mentioned whom, where, by which path, and
        the reason it reached this recipient, said
        outright (S-223's words for `mention`)."""
        who = self.actor or "Someone"
        paths = " and ".join(self.via) if self.via else "a mention"
        return (f"{who} mentioned you via {paths} in "
                f"{self.source_words} "
                f"(reason: you were mentioned).")


class MentionRoutingStore:
    """Mention routing materialised as exactly-once
    S-223 notifications. The ``audit`` argument is
    accepted for signature parity with the
    neighbouring stores and is never used -- a
    routed delivery is derived data and audits
    nothing."""

    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        audit=None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._now = time_fn
        self._notifications = NotificationStore(
            conn, accounts, time_fn=time_fn)
        self._team_mentions = TeamMentionStore(
            conn, accounts, audit=None, time_fn=time_fn)

    # -- repository / item plumbing (S-195's shapes) ------
    def _repo_by_name(self, owner: object,
                      repo: object) -> Repository | None:
        if not isinstance(owner, str) or not isinstance(repo, str):
            return None
        row = self._conn.execute(
            "SELECT * FROM repositories WHERE owner_lower = ?"
            " AND name_lower = ?",
            (owner.strip().lower(), repo.strip().lower())).fetchone()
        if row is None:
            return None
        keys = row.keys()
        return Repository(
            id=row["id"], owner=row["owner"],
            owner_lower=row["owner_lower"], name=row["name"],
            name_lower=row["name_lower"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            description=row["description"] if "description" in keys else "",
            visibility=(row["visibility"] if "visibility" in keys
                        else "public"))

    def _require_item(self, owner: object, repo: object,
                      number: object):
        current = self._repo_by_name(owner, repo)
        if current is None:
            raise IssueError("repo_not_found", "No such repository.")
        if not isinstance(number, int) or isinstance(number, bool) \
                or number <= 0:
            raise IssueError("issue_not_found", "No such issue.")
        row = self._conn.execute(
            "SELECT * FROM issues WHERE repo_id = ? AND number = ?",
            (current.id, number)).fetchone()
        if row is None:
            raise IssueError("issue_not_found", "No such issue.")
        return current, row

    # -- resolution ----------------------------------------
    def _recipients_for(self, text: object, repo: Repository,
                        thread_kind: str, number: int,
                        author_id: int | None):
        """(ordered recipient ids, {recipient_id: via})
        for one source's prose: tokens in prose order,
        direct users resolved through the account
        store, team tokens through S-195's own
        resolution (preview_mentions -- secret-team
        visibility and effective membership included),
        every recipient gated on reading the
        repository and on not having muted the
        thread (S-225)."""
        tokens = parse_mention_tokens(text)
        if not tokens:
            return (), {}
        team_preview = {}
        if any(t.kind == "team" for t in tokens):
            for resolved in self._team_mentions.preview_mentions(
                    text, author_id):
                team_preview[resolved.mention] = resolved
        ordered: list[int] = []
        via: dict[int, list[str]] = {}

        def _offer(user_id: int, token_text: str) -> None:
            ordered.append(user_id)
            paths = via.setdefault(user_id, [])
            if token_text not in paths:
                paths.append(token_text)

        for token in tokens:
            if token.kind == "user":
                user = self._accounts.get_by_username(token.user)
                if user is None:
                    continue
                if user.id == author_id:
                    continue
                if not can_read(user, repo):
                    continue
                _offer(user.id, token.text)
                continue
            resolved = team_preview.get(token.text)
            if resolved is None:
                continue
            for user_id in resolved.recipient_ids:
                user = self._accounts.get_by_id(user_id)
                if user is None or not can_read(user, repo):
                    continue
                _offer(user_id, token.text)
        kept: list[int] = []
        for user_id in decide_mention_recipients(ordered, author_id):
            if self._is_muted(user_id, repo.id, thread_kind, number):
                continue
            kept.append(user_id)
        return tuple(kept), {uid: tuple(via[uid]) for uid in kept}

    def _is_muted(self, user_id: int, repo_id: int,
                  thread_kind: str, number: int) -> bool:
        row = self._conn.execute(
            "SELECT state FROM thread_overrides"
            " WHERE user_id = ? AND repo_id = ?"
            " AND thread_kind = ? AND thread_number = ?",
            (user_id, repo_id, thread_kind, number)).fetchone()
        return row is not None and row["state"] == "muted"

    # -- sync ------------------------------------------------
    def _sync_source(self, *, source_kind: str, repo: Repository,
                     item, comment_id: int, text: object,
                     author_id: int | None) -> int:
        """Reconcile one source's deliveries with what
        its prose says now: standing recipients keep
        their notification (and its read state), new
        recipients are delivered to once, withdrawn
        mentions are withdrawn whole. Returns how
        many deliveries now stand on the source."""
        number = int(item["number"])
        thread_kind = ("pull_request" if item["kind"] == "pull_request"
                       else "issue")
        wanted, via = self._recipients_for(
            text, repo, thread_kind, number, author_id)
        existing = self._conn.execute(
            "SELECT * FROM mention_deliveries"
            " WHERE source_kind = ? AND repo_id = ? AND number = ?"
            " AND comment_id = ?",
            (source_kind, repo.id, number, comment_id)).fetchall()
        existing_by_recipient = {r["recipient_id"]: r for r in existing}
        actor = (self._accounts.get_by_id(author_id)
                 if author_id is not None else None)
        label = f"{repo.owner}/{repo.name}#{number}"
        now = int(self._now())
        for user_id in wanted:
            if user_id in existing_by_recipient:
                continue  # already delivered -- exactly once
            recipient = self._accounts.get_by_id(user_id)
            if recipient is None:
                continue
            note = self._notifications.notify(
                recipient, actor, "mention", verb="mention",
                target_kind="thread", target_id=label,
                detail={"repo": f"{repo.owner}/{repo.name}",
                        "number": number,
                        "source_kind": source_kind,
                        "comment_id": comment_id,
                        "via": list(via.get(user_id, ()))})
            with self._conn:
                self._conn.execute(
                    "INSERT INTO mention_deliveries (notification_id,"
                    " recipient_id, actor_id, source_kind, repo_id,"
                    " number, comment_id, via_json, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (note.id, user_id, author_id, source_kind,
                     repo.id, number, comment_id,
                     json.dumps(list(via.get(user_id, ())),
                                sort_keys=False), now))
        for user_id, row in existing_by_recipient.items():
            if user_id in wanted:
                continue  # the mention still stands -- keep it
            with self._conn:
                self._conn.execute(
                    "DELETE FROM inbox_triage WHERE notification_id = ?",
                    (row["notification_id"],))
                self._conn.execute(
                    "DELETE FROM notifications WHERE id = ?",
                    (row["notification_id"],))
                self._conn.execute(
                    "DELETE FROM mention_deliveries WHERE id = ?",
                    (row["id"],))
        return len(wanted)

    def sync_issue(self, owner: object, repo: object,
                   number: object) -> int:
        """Re-route every mention standing on one issue
        or pull request: its body (source kind from the
        item's own kind) and each live comment, each
        source reconciled with what its text says now.
        Tombstoned comments are cleared, never re-read.
        Returns how many deliveries stand on the item.
        Cross-references are never read here: an echo
        is not a source."""
        current, item = self._require_item(owner, repo, number)
        total = 0
        body_kind = ("pull_request" if item["kind"] == "pull_request"
                     else "issue")
        total += self._sync_source(
            source_kind=body_kind, repo=current, item=item,
            comment_id=0, text=item["body"],
            author_id=item["author_id"])
        comments = self._conn.execute(
            "SELECT id, author_id, body, deleted_at FROM issue_comments"
            " WHERE issue_id = ? ORDER BY id", (item["id"],)).fetchall()
        live_ids: set[int] = set()
        for comment in comments:
            if comment["deleted_at"] is not None:
                continue
            live_ids.add(comment["id"])
            total += self._sync_source(
                source_kind="comment", repo=current, item=item,
                comment_id=comment["id"], text=comment["body"],
                author_id=comment["author_id"])
        stale = self._conn.execute(
            "SELECT DISTINCT comment_id FROM mention_deliveries"
            " WHERE source_kind = 'comment' AND repo_id = ?"
            " AND number = ?", (current.id, item["number"])).fetchall()
        for row in stale:
            if row["comment_id"] not in live_ids:
                orphans = self._conn.execute(
                    "SELECT id, notification_id FROM mention_deliveries"
                    " WHERE source_kind = 'comment' AND repo_id = ?"
                    " AND number = ? AND comment_id = ?",
                    (current.id, item["number"],
                     row["comment_id"])).fetchall()
                with self._conn:
                    for orphan in orphans:
                        self._conn.execute(
                            "DELETE FROM inbox_triage"
                            " WHERE notification_id = ?",
                            (orphan["notification_id"],))
                        self._conn.execute(
                            "DELETE FROM notifications WHERE id = ?",
                            (orphan["notification_id"],))
                    self._conn.execute(
                        "DELETE FROM mention_deliveries"
                        " WHERE source_kind = 'comment' AND repo_id = ?"
                        " AND number = ? AND comment_id = ?",
                        (current.id, item["number"], row["comment_id"]))
        return total

    # -- reads -----------------------------------------------
    def _row_to_delivery(self, row: sqlite3.Row) -> MentionDelivery:
        recipient = self._accounts.get_by_id(row["recipient_id"])
        actor = (self._accounts.get_by_id(row["actor_id"])
                 if row["actor_id"] is not None else None)
        repo = self._conn.execute(
            "SELECT owner, name FROM repositories WHERE id = ?",
            (row["repo_id"],)).fetchone()
        try:
            via = json.loads(row["via_json"] or "[]")
        except ValueError:
            via = []
        return MentionDelivery(
            id=row["id"], notification_id=row["notification_id"],
            recipient_id=row["recipient_id"],
            recipient=recipient.username if recipient else "",
            actor_id=row["actor_id"],
            actor=actor.username if actor else "",
            source_kind=row["source_kind"], repo_id=row["repo_id"],
            repository=(f"{repo['owner']}/{repo['name']}"
                        if repo else ""),
            number=row["number"], comment_id=row["comment_id"],
            via=tuple(via) if isinstance(via, list) else (),
            created_at=row["created_at"])

    def deliveries_for(self, user: User | None, *,
                       limit: int = 100) -> list[MentionDelivery]:
        """The recipient's own mention deliveries,
        newest first. There is no cross-user read: a
        missing user simply has no deliveries."""
        if user is None:
            return []
        rows = self._conn.execute(
            "SELECT * FROM mention_deliveries"
            " WHERE recipient_id = ? ORDER BY id DESC LIMIT ?",
            (user.id, int(limit))).fetchall()
        return [self._row_to_delivery(r) for r in rows]

    def mentions_in(self, viewer: User | None, owner: object,
                    repo: object, number: object) -> list[MentionDelivery]:
        """Every mention delivery standing on one issue
        or pull request, oldest first -- read through
        the repository's own seam: a viewer who cannot
        read the repository gets the uniform
        ``issue_not_found``, exactly as the item itself
        would answer."""
        current, item = self._require_item(owner, repo, number)
        if not can_read(viewer, current):
            raise IssueError("issue_not_found", "No such issue.")
        rows = self._conn.execute(
            "SELECT * FROM mention_deliveries"
            " WHERE repo_id = ? AND number = ? ORDER BY id",
            (current.id, item["number"])).fetchall()
        return [self._row_to_delivery(r) for r in rows]


def render_mention_delivery(delivery: MentionDelivery) -> str:
    """One delivery as a list item, in its plain
    words -- every value escaped through S-010."""
    return f"<li>{escape_html_text(delivery.words)}</li>"


def render_mention_deliveries(rows) -> str:
    """Deliveries in plain words -- who mentioned the
    recipient, where, by which path, and the reason
    said outright. Never a colour alone; every value
    escapes through S-010."""
    rows = list(rows)
    if not rows:
        return ('<p class="mention-deliveries">No mention has '
                "reached you yet. When someone names you, or a "
                "team you belong to, in an issue, a pull request "
                "or a comment, it will be said here -- once, "
                "with the reason it reached you.</p>")
    items = "".join(render_mention_delivery(r) for r in rows)
    return f'<ul class="mention-deliveries">{items}</ul>'
