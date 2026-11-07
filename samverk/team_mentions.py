"""Team mentions (S-195).

``@org/team`` notifies the team (Part XI), usable in
issues, PRs, and review requests.

- **The token is the address.** Prose — an issue or
  pull request body, a comment — that names
  ``@org/team`` addresses the whole team, exactly as
  a review request that names ``@org/team`` already
  does in S-151/S-152's record. ``parse_team_mentions``
  is the pure shape law: a token is ``@`` plus two
  reviewer-shaped segments (the S-152 owner-token
  shape), the ``@`` not glued to a preceding word,
  address or path character (so an email address or
  a path never reads as a mention), duplicates
  folded in the order written. Code is not prose
  (S-127's law, its fence/inline-span stripping
  mirrored): a token inside a fenced block or an
  inline code span was quoted, not said, and
  notifies nobody.
- **Only proven teams are notified** (S-109's
  honesty law, carried from rendering to notifying).
  A token resolves only when the organization
  exists and a team of that slug lives in it —
  judged by S-187's own slug — and, for prose, only
  when the author may see the team: a *secret* team
  (S-187) named by someone who is neither its
  member nor a site admin resolves to nothing, so a
  mention never leaks a secret team's existence and
  never notifies on a guess. A review request is
  its own act of addressing: a standing S-151/S-152
  team token resolves without the prose visibility
  question (the requester needed write standing to
  make it, and the request is already on the PR's
  record), but its recipients are still gated below.
- **The team is its effective membership.** The
  recipients of a resolved mention are the team's
  S-188 effective members — direct members plus
  every ancestor team's members, each person once —
  judged by the pure ``decide_recipients``: the
  author of the mention is never notified of their
  own act, and nobody is notified who cannot read
  the repository the mention stands in (S-165's
  rule: a notification never reveals work its
  recipient cannot read). The store applies the
  readability half through S-054's ``can_read``.
- **The record follows the text** (S-127's sync
  law). Notifications are materialised per source —
  an issue/PR body, one comment, or a pull
  request's standing team review requests — and
  re-syncing a source replaces its rows with what
  the source says now: an edit that removes a
  mention removes its notifications, a tombstoned
  comment's mentions die with its body, and a
  dismissed review request stops notifying. Syncing
  twice notifies nobody twice (the table's UNIQUE
  source/recipient pair, replaced whole per sync).
  ``sync_issue`` covers a body and its live comments
  in one pass; ``sync_review_requests`` covers the
  standing team tokens of one pull request — the
  expansion S-165 expressly left to this slice, so
  S-165's own store is untouched and still skips
  team tokens exactly as it did.
- **Reasons are stored and said** (the S-223
  vocabulary S-165 stores): a prose mention notifies
  with reason ``mention``; a team review request
  with reason ``review-requested``. Reads are honest
  about whose they are: ``inbox`` takes the
  recipient themselves — there is no cross-user
  read of an inbox — and ``mentions_in`` reads
  through the repository's own read seam, so a
  stranger to a private repository gets the uniform
  ``issue_not_found`` before any notification is
  named.
- **No audit row, no new taxonomy event.** A team
  mention notification is derived, addressed data
  over acts already on the record (the prose's own
  creation/edit audits, the review request's S-152
  audit) — 122 events stand. Storage is migration
  76's ``team_mention_notifications`` (schema 75 to
  76), one row per (source, team, recipient).
"""
from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import IssueError
from .organizations import OrganizationStore
from .permissions import can_read
from .repositories import Repository
from .team_nesting import NestedTeamStore
from .teams import TeamStore

__all__ = [
    "REASON_MENTION", "REASON_REVIEW_REQUESTED", "REASONS",
    "SOURCE_KINDS", "ResolvedMention", "TeamMention",
    "TeamMentionStore", "decide_recipients",
    "parse_team_mentions", "render_team_mention",
    "render_team_mentions_page",
]

REASON_MENTION = "mention"
REASON_REVIEW_REQUESTED = "review-requested"
REASONS = frozenset({REASON_MENTION, REASON_REVIEW_REQUESTED})
SOURCE_KINDS = frozenset(
    {"issue", "pull_request", "comment", "review_request"})

_REASON_WORDS = {
    REASON_MENTION: "mentioned",
    REASON_REVIEW_REQUESTED: "review requested from",
}

# The S-152 reviewer-token shape, addressed in prose:
# the @ must not be glued to a word, address or path
# character before it, so volmarr@crew/forge (an
# address) and x/@crew/forge (a path) are not prose
# mentions, while " (@crew/forge)" is.
_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9._@/-])"
    r"@([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9][A-Za-z0-9._-]*)")
_REVIEW_TOKEN_RE = re.compile(
    r"^@([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9][A-Za-z0-9._-]*)$")
_FENCE_RE = re.compile(r"^\s{0,3}(```+|~~~+)")
_INLINE_CODE_RE = re.compile(r"``.+?``|`[^`\n]+`", re.DOTALL)


def _prose_only(text: str) -> str:
    """The text with code removed (S-127's helper,
    mirrored): fenced blocks dropped line by line,
    inline spans blanked. What remains is what the
    author *said*."""
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


def parse_team_mentions(text: object) -> list[tuple[str, str]]:
    """Every ``@org/team`` a piece of prose makes, as
    (org, team) pairs in the order written, duplicates
    folded, both halves lowercased for resolution.
    Pure: existence is the store's question, not the
    parser's. Code spans and fences never parse."""
    if not isinstance(text, str) or not text:
        return []
    prose = _prose_only(text)
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _TOKEN_RE.finditer(prose):
        pair = (match.group(1).lower(), match.group(2).lower())
        if pair not in seen:
            seen.add(pair)
            found.append(pair)
    return found


def parse_review_token(owner_ref: object) -> tuple[str, str] | None:
    """The (org, team) a stored S-151/S-152 review
    token names, lowercased — or None when the token
    is not a team token (a plain ``@username`` names
    a person, an address names nobody here)."""
    if not isinstance(owner_ref, str):
        return None
    match = _REVIEW_TOKEN_RE.match(owner_ref.strip())
    if match is None:
        return None
    return match.group(1).lower(), match.group(2).lower()


def decide_recipients(member_ids, actor_id: int | None) -> tuple:
    """Pure recipient law: the team's effective
    members, each once, in the order given, with the
    actor removed — nobody is notified of their own
    act. Readability is the store's half."""
    out: list[int] = []
    seen: set[int] = set()
    for user_id in member_ids:
        if user_id in seen or user_id == actor_id:
            continue
        seen.add(user_id)
        out.append(user_id)
    return tuple(out)


@dataclass(frozen=True)
class ResolvedMention:
    """One ``@org/team`` token proven to name a team,
    with the recipients it would notify right now —
    the preview a surface can show before anything is
    recorded (``preview_mentions`` writes nothing)."""
    org_id: int
    org_name: str            # display case
    team_id: int
    team_name: str           # display case
    mention: str             # canonical "@org/team", lowercased
    recipient_ids: tuple     # of int, decide_recipients order
    recipients: tuple        # of username, display case, same order

    @property
    def words(self) -> str:
        if not self.recipients:
            return (f"{self.mention} names the "
                    f"{self.team_name} team, and would "
                    f"notify nobody right now.")
        return (f"{self.mention} names the {self.team_name} "
                f"team, and would notify "
                f"{', '.join(self.recipients)}.")


@dataclass(frozen=True)
class TeamMention:
    """One addressed notification: a member of a
    mentioned team hears that the team was addressed,
    where, by whom, and why."""
    id: int
    org_id: int
    org_name: str            # display case
    team_id: int
    team_name: str           # display case
    mention: str             # canonical "@org/team", lowercased
    recipient_id: int
    recipient: str           # display case
    actor_id: int | None
    actor: str               # display case; '' when unrecorded
    source_kind: str         # SOURCE_KINDS
    repo_id: int
    repository: str          # "owner/name", display case
    number: int              # the issue / PR number the source stands on
    comment_id: int          # issue_comments id; 0 unless a comment
    pull_request_id: int     # pull_requests id; 0 unless a review request
    reason: str              # REASONS
    created_at: int

    @property
    def source_words(self) -> str:
        """Where the mention stands, in words a
        person reads."""
        if self.source_kind == "review_request":
            return (f"{self.repository} pull request "
                    f"#{self.number}")
        if self.source_kind == "comment":
            return (f"a comment on {self.repository} "
                    f"#{self.number}")
        kind = ("pull request" if self.source_kind == "pull_request"
                else "issue")
        return f"{self.repository} {kind} #{self.number}"

    @property
    def words(self) -> str:
        """The notification in one plain sentence:
        who addressed the team, where, and why the
        recipient hears it."""
        who = self.actor or "Someone"
        if self.reason == REASON_REVIEW_REQUESTED:
            return (f"{who} asked {self.mention} to review "
                    f"{self.source_words}; you hear this as a "
                    f"member of {self.team_name}.")
        return (f"{who} mentioned {self.mention} in "
                f"{self.source_words}; you hear this as a "
                f"member of {self.team_name}.")


class TeamMentionStore:
    """Team mentions materialised as addressed
    notifications. The ``audit`` argument is accepted
    for signature parity with the neighbouring stores
    and is never used — a mention notification is
    derived data and audits nothing."""

    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._now = time_fn
        self._orgs = OrganizationStore(
            conn, accounts, audit=None, time_fn=time_fn)
        self._teams = TeamStore(
            conn, accounts, audit=None, time_fn=time_fn)
        self._nesting = NestedTeamStore(
            conn, accounts, audit=None, time_fn=time_fn)

    # -- resolution ------------------------------------
    def _resolve(self, org_name: str, team_name: str,
                 actor_id: int | None, *,
                 addressed: bool) -> ResolvedMention | None:
        """The proven team behind one token, with its
        recipients against ``actor_id`` — or None when
        the token names nothing that may notify. A
        prose mention of a secret team resolves only
        for an author who may see the team (its member
        or a site admin); an addressed token (a review
        request) skips that question, as the module
        docstring states."""
        org = self._orgs.get_by_name(org_name)
        if org is None:
            return None
        team = self._teams.get_team_by_name(org.id, team_name)
        if team is None:
            return None
        if not addressed and team.privacy == "secret":
            actor = (self._accounts.get_by_id(actor_id)
                     if actor_id is not None else None)
            may_see = bool(
                actor is not None and (actor.is_admin or
                                       self._teams.is_team_member(
                                           actor.id, team.id)))
            if not may_see:
                return None
        members = self._nesting.effective_members(org.id, team.id)
        ids = decide_recipients([m.user_id for m in members],
                                actor_id)
        names = {m.user_id: m.username for m in members}
        return ResolvedMention(
            org_id=org.id, org_name=org.name,
            team_id=team.id, team_name=team.name,
            mention=f"@{org.name_lower}/{team.name_lower}",
            recipient_ids=ids,
            recipients=tuple(names[i] for i in ids))

    def preview_mentions(
        self, text: object, actor_id: int | None,
    ) -> list[ResolvedMention]:
        """What a piece of prose would notify, as a
        pure read: the tokens it makes that resolve,
        each with its recipients. Writes nothing."""
        out: list[ResolvedMention] = []
        for org_name, team_name in parse_team_mentions(text):
            resolved = self._resolve(org_name, team_name, actor_id,
                                     addressed=False)
            if resolved is not None:
                out.append(resolved)
        return out

    # -- source plumbing ---------------------------------
    def _repo_by_name(self, owner: object,
                      repo: object) -> Repository | None:
        """One repository by owner/name, read straight
        from its table (the S-194 raw-read pattern; the
        row mapping mirrors repositories._row_to_repo)."""
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
        """(Repository, issue row) for one numbered
        item, or the uniform IssueError refusals the
        neighbouring stores raise."""
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

    def _readable_ids(self, repo: Repository,
                      ids: tuple) -> tuple:
        """The half of the recipient law the store
        owns: keep only recipients who can read the
        repository the mention stands in."""
        out: list[int] = []
        for user_id in ids:
            user = self._accounts.get_by_id(user_id)
            if user is not None and can_read(user, repo):
                out.append(user_id)
        return tuple(out)

    def _replace_source(self, *, source_kind: str,
                        repo: Repository, number: int,
                        comment_id: int, pull_request_id: int,
                        resolved: list[ResolvedMention],
                        actor_id: int | None, reason: str) -> int:
        """Replace one source's notification rows with
        its current expansion, whole, in one
        transaction — the record follows the text.
        Returns how many rows now stand."""
        now = int(self._now())
        rows: list[tuple] = []
        for mention in resolved:
            for user_id in self._readable_ids(
                    repo, mention.recipient_ids):
                rows.append((
                    mention.org_id, mention.team_id, mention.mention,
                    user_id, actor_id, source_kind, repo.id, number,
                    comment_id, pull_request_id, reason, now))
        with self._conn:
            self._conn.execute(
                "DELETE FROM team_mention_notifications"
                " WHERE source_kind = ? AND repo_id = ?"
                " AND number = ? AND comment_id = ?"
                " AND pull_request_id = ?",
                (source_kind, repo.id, number, comment_id,
                 pull_request_id))
            self._conn.executemany(
                "INSERT OR IGNORE INTO"
                " team_mention_notifications (org_id, team_id,"
                " mention, recipient_id, actor_id, source_kind,"
                " repo_id, number, comment_id, pull_request_id,"
                " reason, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows)
        return len(rows)

    # -- sync: prose sources ---------------------------
    def sync_issue(self, owner: object, repo: object,
                   number: object) -> int:
        """Re-materialise every prose mention standing
        on one issue or pull request: its body (source
        kind from the item's own kind) and each live
        comment, each source replaced whole with what
        its text says now. Tombstoned comments are
        cleared, never re-read. Returns how many
        notification rows stand on the item."""
        current, item = self._require_item(owner, repo, number)
        total = 0
        body_kind = ("pull_request" if item["kind"] == "pull_request"
                     else "issue")
        resolved = self.preview_mentions(item["body"],
                                         item["author_id"])
        total += self._replace_source(
            source_kind=body_kind, repo=current, number=item["number"],
            comment_id=0, pull_request_id=0, resolved=resolved,
            actor_id=item["author_id"], reason=REASON_MENTION)
        comments = self._conn.execute(
            "SELECT id, author_id, body, deleted_at FROM issue_comments"
            " WHERE issue_id = ? ORDER BY id", (item["id"],)).fetchall()
        live_ids: set[int] = set()
        for comment in comments:
            if comment["deleted_at"] is not None:
                continue
            live_ids.add(comment["id"])
            resolved = self.preview_mentions(comment["body"],
                                             comment["author_id"])
            total += self._replace_source(
                source_kind="comment", repo=current,
                number=item["number"], comment_id=comment["id"],
                pull_request_id=0, resolved=resolved,
                actor_id=comment["author_id"], reason=REASON_MENTION)
        stale = self._conn.execute(
            "SELECT DISTINCT comment_id FROM team_mention_notifications"
            " WHERE source_kind = 'comment' AND repo_id = ?"
            " AND number = ?", (current.id, item["number"])).fetchall()
        for row in stale:
            if row["comment_id"] not in live_ids:
                with self._conn:
                    self._conn.execute(
                        "DELETE FROM team_mention_notifications"
                        " WHERE source_kind = 'comment' AND repo_id = ?"
                        " AND number = ? AND comment_id = ?",
                        (current.id, item["number"], row["comment_id"]))
        return total

    # -- sync: review requests ---------------------------
    def sync_review_requests(self, owner: object, repo: object,
                             number: object) -> int:
        """Re-materialise the team notifications of one
        pull request's *standing* review requests: every
        S-151/S-152 row still in state ``requested``
        whose token is an ``@org/team`` expands to the
        team's effective members (reason
        ``review-requested``). Dismissed rows notify
        nobody; plain ``@username`` rows stay S-165's
        ground and are never duplicated here. Returns
        how many rows stand."""
        current, item = self._require_item(owner, repo, number)
        if item["kind"] != "pull_request":
            raise IssueError(
                "issue_not_found", "No such pull request.")
        pr = self._conn.execute(
            "SELECT id FROM pull_requests WHERE issue_id = ?",
            (item["id"],)).fetchone()
        if pr is None:
            raise IssueError(
                "issue_not_found", "No such pull request.")
        resolved: list[ResolvedMention] = []
        seen: set[tuple[int, int]] = set()
        rows = self._conn.execute(
            "SELECT owner_ref FROM pull_request_review_requests"
            " WHERE pull_request_id = ? AND state = 'requested'"
            " ORDER BY id", (pr["id"],)).fetchall()
        for row in rows:
            pair = parse_review_token(row["owner_ref"])
            if pair is None:
                continue
            mention = self._resolve(pair[0], pair[1], None,
                                    addressed=True)
            if mention is None:
                continue
            key = (mention.org_id, mention.team_id)
            if key in seen:
                continue
            seen.add(key)
            resolved.append(mention)
        return self._replace_source(
            source_kind="review_request", repo=current,
            number=item["number"], comment_id=0,
            pull_request_id=int(pr["id"]), resolved=resolved,
            actor_id=None, reason=REASON_REVIEW_REQUESTED)

    # -- reads -------------------------------------------
    def _row_to_mention(self, row: sqlite3.Row) -> TeamMention:
        org = self._orgs.get_by_id(row["org_id"])
        team = self._teams.get_team(row["org_id"], row["team_id"])
        recipient = self._accounts.get_by_id(row["recipient_id"])
        actor = (self._accounts.get_by_id(row["actor_id"])
                 if row["actor_id"] is not None else None)
        repo = self._conn.execute(
            "SELECT owner, name FROM repositories WHERE id = ?",
            (row["repo_id"],)).fetchone()
        return TeamMention(
            id=row["id"], org_id=row["org_id"],
            org_name=org.name if org else "",
            team_id=row["team_id"], team_name=team.name,
            mention=row["mention"],
            recipient_id=row["recipient_id"],
            recipient=recipient.username if recipient else "",
            actor_id=row["actor_id"],
            actor=actor.username if actor else "",
            source_kind=row["source_kind"], repo_id=row["repo_id"],
            repository=(f"{repo['owner']}/{repo['name']}"
                        if repo else ""),
            number=row["number"], comment_id=row["comment_id"],
            pull_request_id=row["pull_request_id"],
            reason=row["reason"], created_at=row["created_at"])

    def inbox(self, user: User | None, *,
              limit: int = 100) -> list[TeamMention]:
        """The recipient's own team-mention inbox,
        newest first. There is no cross-user read: a
        missing user simply has no inbox."""
        if user is None:
            return []
        rows = self._conn.execute(
            "SELECT * FROM team_mention_notifications"
            " WHERE recipient_id = ? ORDER BY id DESC LIMIT ?",
            (user.id, int(limit))).fetchall()
        return [self._row_to_mention(r) for r in rows]

    def mentions_in(self, viewer: User | None, owner: object,
                    repo: object, number: object) -> list[TeamMention]:
        """Every team-mention notification standing on
        one issue or pull request, oldest first — read
        through the repository's own seam: a viewer who
        cannot read the repository gets the uniform
        ``issue_not_found``, exactly as the item itself
        would answer."""
        current, item = self._require_item(owner, repo, number)
        if not can_read(viewer, current):
            raise IssueError("issue_not_found", "No such issue.")
        rows = self._conn.execute(
            "SELECT * FROM team_mention_notifications"
            " WHERE repo_id = ? AND number = ? ORDER BY id",
            (current.id, item["number"])).fetchall()
        return [self._row_to_mention(r) for r in rows]


def render_team_mention(mention: TeamMention) -> str:
    """One notification as a list item, in its plain
    words — every value escaped through S-010."""
    return f"<li>{escape_html_text(mention.words)}</li>"


def render_team_mentions_page(recipient: str,
                              mentions: list[TeamMention]) -> str:
    """A recipient's team-mention page: every
    notification in words — who addressed which team,
    where, and why the recipient hears it — every
    value escaped through S-010, the reason in text,
    never colour-only."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Team mentions — {escape_html_text(recipient)} "
        "— Samverk</title></head>",
        "<body>",
        f"<h1>Team mentions for {escape_html_text(recipient)}</h1>",
    ]
    if mentions:
        parts.append("<ul>")
        for mention in mentions:
            parts.append(render_team_mention(mention))
        parts.append("</ul>")
    else:
        parts.append(
            "<p>No team has mentioned you yet.</p>")
    parts.append(
        "<p>A team mention names @org/team in an issue, "
        "a pull request or a comment, or asks @org/team "
        "to review a pull request; every effective member "
        "of the team hears it, except the person who "
        "wrote it.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
