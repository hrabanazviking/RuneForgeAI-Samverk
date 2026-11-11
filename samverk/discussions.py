"""Discussion categories and threads (S-283).

Roadmap S-283: Discussion categories and threads
(if verdicted in) -- categories, question/discussion
kinds, pinned posts; if out, the published refusal
with the seam noted. S-282 verdicted the core IN
(docs/DISCUSSIONS_VERDICT.md), so this slice BUILDS
it, under the verdict's eight must-not-break
invariants:

- **Permissions follow the repository (S-190).**
  Every act -- read, create, reply, pin, moderate --
  is judged by S-190's ``PermissionEngine`` on the
  owning repository, exactly as the repository's own
  acts are judged. There is no discussion-only role
  and no board-level back door. Category kinds carry
  their own minimum rungs as data (``KIND_SPECS``):
  question and open-discussion threads are opened
  and answered by any reader; announcement threads
  are opened only by repository writers, while any
  reader may reply. Creating or changing a category,
  pinning, and locking are administrator acts --
  announcement moderation and pinned items are
  owner-controlled, as research 30 requires.
- **Private is missing everywhere.** A discussion
  in a repository the caller cannot read answers
  exactly as one that does not exist: the uniform
  ``discussion_not_found`` for thread and reply
  operations, ``repo_not_found`` for the board
  itself, and lists, counts and the filtered search
  in this module are all gated by the same read
  door first, so no title, snippet or count can
  confirm what the caller may not read. Search
  joins the Part X index only through S-287's road;
  nothing here registers a discussion anywhere else.
- **One timeline holds the conversation.** A
  thread's replies and its happenings -- creation,
  pins, locks, closes, reopens and moderation --
  live in one ordered stream (``timeline``): every
  happening is a ``discussion_events`` row written
  in the same transaction as the act, attributable
  and in order, and moderation is said in words on
  the thread itself, never done silently.
- **Categories carry explicit states and powers.**
  Every kind declares, before any thread opens, its
  allowed thread states (``open`` / ``closed``) and
  the rungs that may create and reply in it
  (``KIND_SPECS`` / the pure ``decide_power``). A
  thread's kind is its category's kind and cannot
  change in this slice; conversion is S-285's road.
- **The conversation machinery is S-123's, reused.**
  Reply bodies are judged by S-123's own validator
  (``comment_required`` / ``comment_invalid`` under
  the one ``BODY_MAX`` cap, translated here from
  ``IssueError`` to ``DiscussionError``); editing a
  reply records the previous body in
  ``discussion_reply_edits`` before the new body
  lands, and deletion is S-123's tombstone -- body
  cleared, ``deleted_at`` / ``deleted_by`` stamped,
  list views skip it, and the deletion stands on
  the timeline as a moderation event in words.
  Editing is the author's alone; deletion is by the
  author, a repository administrator (the moderator
  here), or a site admin. Thread titles ride
  S-122's title law (``TITLE_MAX``).
- **States are said in words.** A thread's state --
  open, closed, pinned, locked -- is rendered in
  words everywhere (``state_words`` and the render
  functions), never by colour alone, and the
  composer rendered here is labelled-field HTML:
  every input carries its ``<label>``, so it is
  keyboard- and mobile-first by construction.

What this slice does NOT build: answer marking is
S-284 (a question thread here carries no accepted
answer yet), conversion is S-285, polls stay
deferred (S-286 records the refusal on S-282's
verdict), and subscriptions ride S-219 from a later
seam -- no parallel notifier is created here.

Storage is migration 112's ``discussion_categories``,
``discussion_threads``, ``discussion_counters``,
``discussion_replies``, ``discussion_reply_edits``
and ``discussion_events`` tables (schema 111 ->
112). Thread numbers are per-repository, claimed
from ``discussion_counters`` by the same atomic
upsert S-121 uses for issue numbers, and never
reused. Discussion acts carry no verb of their own
in the frozen taxonomy vocabulary -- the thread's
own timeline is their attributable record -- so no
new taxonomy event: 133 stand (33 auth / 87 repo /
13 admin).
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issue_comments import _validate_comment_body
from .issues import IssueError, _validate_body, _validate_title
from .permission_engine import PermissionEngine
from .repositories import Repository, RepositoryStore
from .team_permissions import role_covers

__all__ = [
    "CATEGORY_NAME_MAX", "DESCRIPTION_MAX",
    "KIND_ANNOUNCEMENT", "KIND_DISCUSSION", "KIND_QUESTION",
    "KIND_SPECS", "THREAD_STATES", "CategoryKind",
    "Discussion", "DiscussionCategory", "DiscussionError",
    "DiscussionEvent", "DiscussionReply", "DiscussionReplyEdit",
    "DiscussionStore", "TimelineEntry", "category_to_dict",
    "decide_power", "describe_timeline_entry", "kind_spec",
    "render_board_page", "render_composer_form",
    "render_thread_page", "reply_to_dict", "thread_to_dict",
]

KIND_QUESTION = "question"
KIND_ANNOUNCEMENT = "announcement"
KIND_DISCUSSION = "discussion"

THREAD_STATES = frozenset({"open", "closed"})
CATEGORY_NAME_MAX = 80
DESCRIPTION_MAX = 350


class DiscussionError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class CategoryKind:
    """One category kind, declared whole before any
    thread opens: its words, the thread states it
    allows, and the S-190 rungs that may create a
    thread and reply in it."""
    kind: str
    title: str
    words: str
    allowed_states: tuple[str, ...]
    create_min_role: str
    reply_min_role: str


KIND_SPECS: dict[str, CategoryKind] = {
    KIND_QUESTION: CategoryKind(
        kind=KIND_QUESTION, title="Question",
        words=("Questions neighbours ask and answer; "
               "an answer can be marked from S-284."),
        allowed_states=("open", "closed"),
        create_min_role="read", reply_min_role="read"),
    KIND_ANNOUNCEMENT: CategoryKind(
        kind=KIND_ANNOUNCEMENT, title="Announcement",
        words=("Announcements from the repository's "
               "writers; any reader may reply."),
        allowed_states=("open", "closed"),
        create_min_role="write", reply_min_role="read"),
    KIND_DISCUSSION: CategoryKind(
        kind=KIND_DISCUSSION, title="Discussion",
        words=("Open discussion that never has to "
               "pretend it can be closed as work."),
        allowed_states=("open", "closed"),
        create_min_role="read", reply_min_role="read"),
}


def kind_spec(kind: object) -> CategoryKind:
    """One kind's declared spec. An unknown kind is
    refused kind_invalid -- a category kind is never
    smuggled in by convention."""
    if not isinstance(kind, str) or kind not in KIND_SPECS:
        raise DiscussionError(
            "kind_invalid",
            "A discussion category is a question, an "
            "announcement or an open discussion.")
    return KIND_SPECS[kind]


def decide_power(kind: object, action: object,
                 role: str | None) -> bool:
    """Pure power judgement: may a holder of *role*
    (an S-190 rung, or None) take *action* -- 'create'
    or 'reply' -- in a category of *kind*? Category
    administration, pinning and locking are not kind
    powers: they are the administrator rung, judged
    by the store. Unknown kinds or actions hold no
    power."""
    if not isinstance(kind, str) or kind not in KIND_SPECS:
        return False
    spec = KIND_SPECS[kind]
    if action == "create":
        return role_covers(role, spec.create_min_role)
    if action == "reply":
        return role_covers(role, spec.reply_min_role)
    return False


@dataclass(frozen=True)
class DiscussionCategory:
    id: int
    repo_id: int
    name: str
    kind: str
    description: str
    created_by: int
    created_at: int
    updated_at: int

    @property
    def kind_title(self) -> str:
        return KIND_SPECS[self.kind].title


@dataclass(frozen=True)
class Discussion:
    """One discussion thread."""
    id: int
    repo_id: int
    category_id: int
    number: int
    author_id: int
    title: str
    body: str
    state: str          # 'open' | 'closed'
    pinned: bool
    locked: bool
    created_at: int
    updated_at: int
    edited_at: int | None = None

    @property
    def ref(self) -> str:
        return f"#{self.number}"

    @property
    def state_words(self) -> str:
        """The state in words, never colour alone:
        'open', 'closed', with 'pinned' and 'locked'
        said as well when they stand."""
        words = [self.state]
        if self.pinned:
            words.append("pinned")
        if self.locked:
            words.append("locked")
        return ", ".join(words)


@dataclass(frozen=True)
class DiscussionReply:
    id: int
    thread_id: int
    author_id: int
    body: str           # '' once deleted (tombstone)
    created_at: int
    updated_at: int
    edited_at: int | None
    deleted_at: int | None
    deleted_by: int | None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def was_edited(self) -> bool:
        return self.edited_at is not None


@dataclass(frozen=True)
class DiscussionReplyEdit:
    reply_id: int
    editor_id: int
    previous_body: str
    edited_at: int


@dataclass(frozen=True)
class DiscussionEvent:
    id: int
    thread_id: int
    actor_id: int
    kind: str           # created|pinned|unpinned|locked|unlocked|
                        # closed|reopened|reply_deleted
    detail: str
    created_at: int


@dataclass(frozen=True)
class TimelineEntry:
    """One entry of a thread's one timeline: a reply
    (``reply`` set) or a happening (``event`` set),
    in stream order."""
    created_at: int
    reply: DiscussionReply | None = None
    event: DiscussionEvent | None = None

    @property
    def is_reply(self) -> bool:
        return self.reply is not None


_EVENT_WORDS = {
    "created": "opened this discussion",
    "pinned": "pinned this discussion",
    "unpinned": "unpinned this discussion",
    "locked": "locked this conversation",
    "unlocked": "unlocked this conversation",
    "closed": "closed this discussion",
    "reopened": "reopened this discussion",
    "reply_deleted": "removed a reply",
}


def describe_timeline_entry(
        entry: TimelineEntry,
        authors: dict[int, str] | None = None) -> str:
    """One timeline entry in plain words."""
    authors = authors or {}
    if entry.reply is not None:
        name = authors.get(
            entry.reply.author_id,
            f"user {entry.reply.author_id}")
        if entry.reply.is_deleted:
            return f"{name} replied (this reply was removed)"
        return f"{name} replied"
    assert entry.event is not None
    name = authors.get(
        entry.event.actor_id, f"user {entry.event.actor_id}")
    words = _EVENT_WORDS.get(entry.event.kind, entry.event.kind)
    return f"{name} {words}"


def category_to_dict(category: DiscussionCategory) -> dict:
    spec = KIND_SPECS[category.kind]
    return {
        "id": category.id, "repo_id": category.repo_id,
        "name": category.name, "kind": category.kind,
        "kind_title": spec.title, "kind_words": spec.words,
        "allowed_states": list(spec.allowed_states),
        "create_min_role": spec.create_min_role,
        "reply_min_role": spec.reply_min_role,
        "description": category.description,
        "created_by": category.created_by,
        "created_at": category.created_at,
        "updated_at": category.updated_at,
    }


def thread_to_dict(thread: Discussion) -> dict:
    return {
        "id": thread.id, "repo_id": thread.repo_id,
        "category_id": thread.category_id,
        "number": thread.number, "ref": thread.ref,
        "author_id": thread.author_id,
        "title": thread.title, "body": thread.body,
        "state": thread.state,
        "state_words": thread.state_words,
        "pinned": thread.pinned, "locked": thread.locked,
        "created_at": thread.created_at,
        "updated_at": thread.updated_at,
        "edited_at": thread.edited_at,
    }


def reply_to_dict(reply: DiscussionReply) -> dict:
    return {
        "id": reply.id, "thread_id": reply.thread_id,
        "author_id": reply.author_id, "body": reply.body,
        "created_at": reply.created_at,
        "updated_at": reply.updated_at,
        "edited_at": reply.edited_at,
        "deleted_at": reply.deleted_at,
        "deleted_by": reply.deleted_by,
        "is_deleted": reply.is_deleted,
        "was_edited": reply.was_edited,
    }


def _row_to_category(row: sqlite3.Row) -> DiscussionCategory:
    return DiscussionCategory(
        id=row["id"], repo_id=row["repo_id"], name=row["name"],
        kind=row["kind"], description=row["description"],
        created_by=row["created_by"],
        created_at=row["created_at"], updated_at=row["updated_at"])


def _row_to_thread(row: sqlite3.Row) -> Discussion:
    return Discussion(
        id=row["id"], repo_id=row["repo_id"],
        category_id=row["category_id"], number=row["number"],
        author_id=row["author_id"], title=row["title"],
        body=row["body"], state=row["state"],
        pinned=bool(row["pinned"]), locked=bool(row["locked"]),
        created_at=row["created_at"], updated_at=row["updated_at"],
        edited_at=row["edited_at"])


def _row_to_reply(row: sqlite3.Row) -> DiscussionReply:
    return DiscussionReply(
        id=row["id"], thread_id=row["thread_id"],
        author_id=row["author_id"], body=row["body"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        edited_at=row["edited_at"], deleted_at=row["deleted_at"],
        deleted_by=row["deleted_by"])


def _validate_category_name(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise DiscussionError(
            "category_required", "A category needs a name.")
    text = name.strip()
    if len(text) > CATEGORY_NAME_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise DiscussionError(
            "category_invalid",
            f"Category names are at most {CATEGORY_NAME_MAX} "
            "characters of plain text.")
    return text


def _validate_description(description: object) -> str:
    if description is None:
        return ""
    if not isinstance(description, str):
        raise DiscussionError(
            "category_invalid", "A category description is text.")
    text = description.strip()
    if len(text) > DESCRIPTION_MAX or any(
            (ord(c) < 0x20 and c not in "\n\t") or ord(c) == 0x7F
            for c in text):
        raise DiscussionError(
            "category_invalid",
            f"Category descriptions are at most "
            f"{DESCRIPTION_MAX} characters of plain text.")
    return text


class DiscussionStore:
    """The per-repository discussion board: categories,
    threads, replies and the one timeline, judged
    throughout by S-190 on the owning repository."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        engine: PermissionEngine | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._audit = audit
        self._engine = engine or PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)
        self._now = time_fn

    # -- the doors -------------------------------------------

    def _repo(self, owner: object, repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise DiscussionError(
                "repo_not_found", "No such repository.")
        return current

    def _role(self, viewer: User | None,
              current: Repository) -> str | None:
        return self._engine.role_for(viewer, current)

    def _repo_for_read(self, viewer: User | None, owner: object,
                       repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None or not role_covers(
                self._role(viewer, current), "read"):
            raise DiscussionError(
                "repo_not_found", "No such repository.")
        return current

    def _require_signed_in(self, actor: User | None) -> User:
        if actor is None:
            raise DiscussionError(
                "permission_denied",
                "Only a signed-in user can do that.")
        return actor

    def _require_admin(self, actor: User | None,
                       current: Repository) -> str:
        self._require_signed_in(actor)
        role = self._role(actor, current)
        if not role_covers(role, "admin"):
            raise DiscussionError(
                "permission_denied",
                "Only a repository administrator can do that.")
        return role or ""

    # -- translated S-122 / S-123 validators ------------------

    def _validate_title(self, title: object) -> str:
        try:
            return _validate_title(title)
        except IssueError as exc:
            raise DiscussionError(
                "title_required" if exc.reason == "title_required"
                else "title_invalid", str(exc)) from None

    def _validate_thread_body(self, body: object) -> str:
        try:
            return _validate_body(body)
        except IssueError as exc:
            raise DiscussionError(exc.reason, str(exc)) from None

    def _validate_reply_body(self, body: object) -> str:
        try:
            return _validate_comment_body(body)
        except IssueError as exc:
            raise DiscussionError(exc.reason, str(exc)) from None

    # -- internals ---------------------------------------------

    def _category_by_id(
            self, repo_id: int,
            category_id: object) -> DiscussionCategory | None:
        if not isinstance(category_id, int) \
                or isinstance(category_id, bool):
            return None
        row = self._conn.execute(
            "SELECT * FROM discussion_categories"
            " WHERE repo_id = ? AND id = ?",
            (repo_id, category_id)).fetchone()
        return _row_to_category(row) if row else None

    def _thread_by_id(self, thread_id: int) -> Discussion | None:
        row = self._conn.execute(
            "SELECT * FROM discussion_threads WHERE id = ?",
            (thread_id,)).fetchone()
        return _row_to_thread(row) if row else None

    def _reply_by_id(self, reply_id: object) -> DiscussionReply | None:
        if not isinstance(reply_id, int) \
                or isinstance(reply_id, bool):
            return None
        row = self._conn.execute(
            "SELECT * FROM discussion_replies WHERE id = ?",
            (reply_id,)).fetchone()
        return _row_to_reply(row) if row else None

    def _record_event(self, thread_id: int, actor_id: int,
                      kind: str, detail: str, now: int) -> None:
        """One happening on the thread's timeline, written
        inside the caller's transaction."""
        self._conn.execute(
            "INSERT INTO discussion_events"
            " (thread_id, actor_id, kind, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (thread_id, actor_id, kind, detail, now))

    def _next_number_tx(self, repo_id: int) -> int:
        """Claim the next discussion number inside the
        caller's transaction (S-121's atomic upsert)."""
        row = self._conn.execute(
            "INSERT INTO discussion_counters (repo_id, last_number)"
            " VALUES (?, 1)"
            " ON CONFLICT (repo_id) DO UPDATE"
            " SET last_number = last_number + 1"
            " RETURNING last_number",
            (repo_id,)).fetchone()
        return int(row["last_number"])

    # -- categories ---------------------------------------------

    def create_category(self, actor: User | None, owner: object,
                        repo: object, name: object, kind: object,
                        description: object = "") -> DiscussionCategory:
        """Create a category: an administrator act. The
        kind is declared whole (KIND_SPECS) before any
        thread opens in it."""
        current = self._repo_for_read(actor, owner, repo)
        self._require_admin(actor, current)
        assert actor is not None
        spec = kind_spec(kind)
        text = _validate_category_name(name)
        desc = _validate_description(description)
        now = int(self._now())
        try:
            with self._conn:
                cur = self._conn.execute(
                    "INSERT INTO discussion_categories"
                    " (repo_id, name, name_lower, kind, description,"
                    " created_by, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (current.id, text, text.lower(), spec.kind,
                     desc, actor.id, now, now))
        except sqlite3.IntegrityError:
            raise DiscussionError(
                "category_exists",
                f"A category named {text!r} already stands "
                "in this repository.") from None
        found = self._category_by_id(current.id, int(cur.lastrowid))
        assert found is not None
        return found

    def list_categories(self, viewer: User | None, owner: object,
                        repo: object) -> list[DiscussionCategory]:
        current = self._repo_for_read(viewer, owner, repo)
        rows = self._conn.execute(
            "SELECT * FROM discussion_categories WHERE repo_id = ?"
            " ORDER BY name_lower", (current.id,)).fetchall()
        return [_row_to_category(r) for r in rows]

    def get_category(self, viewer: User | None, owner: object,
                     repo: object,
                     category_id: object) -> DiscussionCategory:
        current = self._repo_for_read(viewer, owner, repo)
        found = self._category_by_id(current.id, category_id)
        if found is None:
            raise DiscussionError(
                "category_not_found", "No such category.")
        return found

    def update_category(self, actor: User | None, owner: object,
                        repo: object, category_id: object, *,
                        name: object = None,
                        description: object = None
                        ) -> DiscussionCategory:
        """Rename or re-describe a category: an
        administrator act. The kind never changes --
        a kind change is a new category, not an edit."""
        current = self._repo_for_read(actor, owner, repo)
        self._require_admin(actor, current)
        found = self._category_by_id(current.id, category_id)
        if found is None:
            raise DiscussionError(
                "category_not_found", "No such category.")
        new_name = found.name if name is None \
            else _validate_category_name(name)
        new_desc = found.description if description is None \
            else _validate_description(description)
        now = int(self._now())
        try:
            with self._conn:
                self._conn.execute(
                    "UPDATE discussion_categories"
                    " SET name = ?, name_lower = ?, description = ?,"
                    " updated_at = ? WHERE id = ?",
                    (new_name, new_name.lower(), new_desc,
                     now, found.id))
        except sqlite3.IntegrityError:
            raise DiscussionError(
                "category_exists",
                f"A category named {new_name!r} already stands "
                "in this repository.") from None
        updated = self._category_by_id(current.id, found.id)
        assert updated is not None
        return updated

    def delete_category(self, actor: User | None, owner: object,
                        repo: object,
                        category_id: object) -> DiscussionCategory:
        """Remove an empty category: an administrator
        act. A category holding threads is refused
        category_not_empty -- its threads are never
        orphaned or silently moved."""
        current = self._repo_for_read(actor, owner, repo)
        self._require_admin(actor, current)
        found = self._category_by_id(current.id, category_id)
        if found is None:
            raise DiscussionError(
                "category_not_found", "No such category.")
        count = self._conn.execute(
            "SELECT COUNT(*) AS n FROM discussion_threads"
            " WHERE category_id = ?", (found.id,)).fetchone()["n"]
        if count:
            raise DiscussionError(
                "category_not_empty",
                "This category still holds discussions; "
                "it cannot be removed.")
        with self._conn:
            self._conn.execute(
                "DELETE FROM discussion_categories WHERE id = ?",
                (found.id,))
        return found

    # -- threads --------------------------------------------------

    def create_thread(self, actor: User | None, owner: object,
                      repo: object, category_id: object,
                      title: object, body: object = ""
                      ) -> Discussion:
        """Open a thread in a category. The category
        kind's declared create rung judges the act
        through S-190; the opening stands as the
        timeline's first event, in the same
        transaction as the thread itself."""
        current = self._repo_for_read(actor, owner, repo)
        self._require_signed_in(actor)
        assert actor is not None
        category = self._category_by_id(current.id, category_id)
        if category is None:
            raise DiscussionError(
                "category_not_found", "No such category.")
        role = self._role(actor, current)
        if not decide_power(category.kind, "create", role):
            raise DiscussionError(
                "permission_denied",
                f"Opening a {KIND_SPECS[category.kind].title.lower()} "
                "thread needs a stronger repository role.")
        text = self._validate_title(title)
        prose = self._validate_thread_body(body)
        now = int(self._now())
        with self._conn:  # number, thread and event land together
            number = self._next_number_tx(current.id)
            cur = self._conn.execute(
                "INSERT INTO discussion_threads"
                " (repo_id, category_id, number, author_id, title,"
                " body, state, pinned, locked, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'open', 0, 0, ?, ?)",
                (current.id, category.id, number, actor.id,
                 text, prose, now, now))
            thread_id = int(cur.lastrowid)
            self._record_event(thread_id, actor.id, "created", "", now)
        found = self._thread_by_id(thread_id)
        assert found is not None
        return found

    def get_thread(self, viewer: User | None, owner: object,
                   repo: object, number: object) -> Discussion:
        """One thread by its per-repository number. A
        repository the viewer cannot read, and a
        number never claimed, answer the same
        discussion_not_found."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not role_covers(
                self._role(viewer, current), "read"):
            raise DiscussionError(
                "discussion_not_found", "No such discussion.")
        if not isinstance(number, int) or isinstance(number, bool) \
                or number <= 0:
            raise DiscussionError(
                "discussion_not_found", "No such discussion.")
        row = self._conn.execute(
            "SELECT * FROM discussion_threads"
            " WHERE repo_id = ? AND number = ?",
            (current.id, number)).fetchone()
        if row is None:
            raise DiscussionError(
                "discussion_not_found", "No such discussion.")
        return _row_to_thread(row)

    def list_threads(self, viewer: User | None, owner: object,
                     repo: object, *,
                     category_id: object = None,
                     kind: object = None,
                     state: object = None,
                     author_id: object = None,
                     pinned: bool | None = None,
                     query: object = None) -> list[Discussion]:
        """The board's threads, filtered in words:
        category, kind, state, author, pinned, and a
        plain-text query over title and body. Pinned
        threads stand first, then newest. The read
        door judges first, so a private board's list
        is its not-found answer, never a filtered
        leak. This filtered list is also the slice's
        search seam: it only ever returns what the
        caller may read (the Part X index joins
        through S-287)."""
        current = self._repo_for_read(viewer, owner, repo)
        if state is not None and state not in THREAD_STATES:
            raise DiscussionError(
                "state_invalid",
                "A discussion is 'open' or 'closed'.")
        if kind is not None:
            kind_spec(kind)
        sql = ("SELECT t.* FROM discussion_threads t"
               " JOIN discussion_categories c ON c.id = t.category_id"
               " WHERE t.repo_id = ?")
        params: list = [current.id]
        if category_id is not None:
            if not isinstance(category_id, int) \
                    or isinstance(category_id, bool):
                raise DiscussionError(
                    "category_not_found", "No such category.")
            sql += " AND t.category_id = ?"
            params.append(category_id)
        if kind is not None:
            sql += " AND c.kind = ?"
            params.append(kind)
        if state is not None:
            sql += " AND t.state = ?"
            params.append(state)
        if author_id is not None:
            sql += " AND t.author_id = ?"
            params.append(author_id)
        if pinned is not None:
            sql += " AND t.pinned = ?"
            params.append(1 if pinned else 0)
        if query is not None:
            if not isinstance(query, str):
                raise DiscussionError(
                    "query_invalid", "A discussion search is text.")
            needle = query.strip().lower()
            if needle:
                sql += (" AND (lower(t.title) LIKE ?"
                        " OR lower(t.body) LIKE ?)")
                params.extend([f"%{needle}%", f"%{needle}%"])
        sql += " ORDER BY t.pinned DESC, t.id DESC"
        return [_row_to_thread(r) for r in
                self._conn.execute(sql, params).fetchall()]

    def thread_count(self, viewer: User | None, owner: object,
                     repo: object) -> int:
        current = self._repo_for_read(viewer, owner, repo)
        return int(self._conn.execute(
            "SELECT COUNT(*) AS n FROM discussion_threads"
            " WHERE repo_id = ?", (current.id,)).fetchone()["n"])

    def update_thread(self, actor: User | None, owner: object,
                      repo: object, number: object, *,
                      title: object = None,
                      body: object = None) -> Discussion:
        """Edit a thread's title or body: the author's,
        or a repository writer's (S-122's hands)."""
        thread = self.get_thread(actor, owner, repo, number)
        current = self._repo(owner, repo)
        role = self._role(actor, current)
        if actor is None or (actor.id != thread.author_id
                             and not role_covers(role, "write")):
            raise DiscussionError(
                "permission_denied",
                "Only the author or a repository writer can "
                "edit this discussion.")
        new_title = thread.title if title is None \
            else self._validate_title(title)
        new_body = thread.body if body is None \
            else self._validate_thread_body(body)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE discussion_threads SET title = ?, body = ?,"
                " edited_at = ?, updated_at = ? WHERE id = ?",
                (new_title, new_body, now, now, thread.id))
        found = self._thread_by_id(thread.id)
        assert found is not None
        return found

    # -- thread moderation: pins, locks, closes -------------------

    def _moderate(self, actor: User | None, owner: object,
                  repo: object, number: object, kind: str,
                  sql: str, already: bool) -> Discussion:
        thread = self.get_thread(actor, owner, repo, number)
        current = self._repo(owner, repo)
        self._require_admin(actor, current)
        assert actor is not None
        if already:
            return thread  # a quiet no-op: retries are safe
        now = int(self._now())
        with self._conn:
            self._conn.execute(sql, (now, thread.id))
            self._record_event(thread.id, actor.id, kind, "", now)
        found = self._thread_by_id(thread.id)
        assert found is not None
        return found

    def pin_thread(self, actor: User | None, owner: object,
                   repo: object, number: object) -> Discussion:
        """Pin a thread: an administrator act --
        pinned items are owner-controlled."""
        thread = self.get_thread(actor, owner, repo, number)
        return self._moderate(
            actor, owner, repo, number, "pinned",
            "UPDATE discussion_threads SET pinned = 1,"
            " updated_at = ? WHERE id = ?", thread.pinned)

    def unpin_thread(self, actor: User | None, owner: object,
                     repo: object, number: object) -> Discussion:
        thread = self.get_thread(actor, owner, repo, number)
        return self._moderate(
            actor, owner, repo, number, "unpinned",
            "UPDATE discussion_threads SET pinned = 0,"
            " updated_at = ? WHERE id = ?", not thread.pinned)

    def lock_thread(self, actor: User | None, owner: object,
                    repo: object, number: object) -> Discussion:
        """Lock a conversation: an administrator act.
        A locked thread refuses new replies from
        everyone except repository writers."""
        thread = self.get_thread(actor, owner, repo, number)
        return self._moderate(
            actor, owner, repo, number, "locked",
            "UPDATE discussion_threads SET locked = 1,"
            " updated_at = ? WHERE id = ?", thread.locked)

    def unlock_thread(self, actor: User | None, owner: object,
                      repo: object, number: object) -> Discussion:
        thread = self.get_thread(actor, owner, repo, number)
        return self._moderate(
            actor, owner, repo, number, "unlocked",
            "UPDATE discussion_threads SET locked = 0,"
            " updated_at = ? WHERE id = ?", not thread.locked)

    def close_thread(self, actor: User | None, owner: object,
                     repo: object, number: object) -> Discussion:
        """Close a thread: its author's, or a
        repository writer's. Closing a closed thread
        is a quiet no-op."""
        thread = self.get_thread(actor, owner, repo, number)
        current = self._repo(owner, repo)
        role = self._role(actor, current)
        if actor is None or (actor.id != thread.author_id
                             and not role_covers(role, "write")):
            raise DiscussionError(
                "permission_denied",
                "Only the author or a repository writer can "
                "close this discussion.")
        if thread.state == "closed":
            return thread
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE discussion_threads SET state = 'closed',"
                " updated_at = ? WHERE id = ?", (now, thread.id))
            self._record_event(thread.id, actor.id, "closed", "", now)
        found = self._thread_by_id(thread.id)
        assert found is not None
        return found

    def reopen_thread(self, actor: User | None, owner: object,
                      repo: object, number: object) -> Discussion:
        """Reopen a closed thread: the same hands that
        may close it. Reopening an open thread is a
        quiet no-op."""
        thread = self.get_thread(actor, owner, repo, number)
        current = self._repo(owner, repo)
        role = self._role(actor, current)
        if actor is None or (actor.id != thread.author_id
                             and not role_covers(role, "write")):
            raise DiscussionError(
                "permission_denied",
                "Only the author or a repository writer can "
                "reopen this discussion.")
        if thread.state == "open":
            return thread
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE discussion_threads SET state = 'open',"
                " updated_at = ? WHERE id = ?", (now, thread.id))
            self._record_event(
                thread.id, actor.id, "reopened", "", now)
        found = self._thread_by_id(thread.id)
        assert found is not None
        return found

    # -- replies ----------------------------------------------------

    def add_reply(self, actor: User | None, owner: object,
                  repo: object, number: object,
                  body: object) -> DiscussionReply:
        """Reply in a thread. The category kind's
        declared reply rung judges the act through
        S-190; a closed thread refuses everyone, and
        a locked thread refuses everyone except
        repository writers (S-132's road)."""
        thread = self.get_thread(actor, owner, repo, number)
        self._require_signed_in(actor)
        assert actor is not None
        current = self._repo(owner, repo)
        role = self._role(actor, current)
        if thread.state == "closed":
            raise DiscussionError(
                "discussion_closed",
                "This discussion is closed; it takes no "
                "new replies.")
        if thread.locked and not role_covers(role, "write"):
            raise DiscussionError(
                "conversation_locked",
                "This conversation is locked; only "
                "repository writers can still reply.")
        category = self._category_by_id(
            current.id, thread.category_id)
        assert category is not None
        if not decide_power(category.kind, "reply", role):
            raise DiscussionError(
                "permission_denied",
                "Replying here needs a stronger "
                "repository role.")
        text = self._validate_reply_body(body)
        now = int(self._now())
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO discussion_replies"
                " (thread_id, author_id, body, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (thread.id, actor.id, text, now, now))
            self._conn.execute(
                "UPDATE discussion_threads SET updated_at = ?"
                " WHERE id = ?", (now, thread.id))
        found = self._reply_by_id(int(cur.lastrowid))
        assert found is not None
        return found

    def list_replies(self, viewer: User | None, owner: object,
                     repo: object, number: object
                     ) -> list[DiscussionReply]:
        """The thread's live replies, in order.
        Tombstones never reach a list."""
        thread = self.get_thread(viewer, owner, repo, number)
        rows = self._conn.execute(
            "SELECT * FROM discussion_replies WHERE thread_id = ?"
            " AND deleted_at IS NULL ORDER BY id",
            (thread.id,)).fetchall()
        return [_row_to_reply(r) for r in rows]

    def get_reply(self, viewer: User | None, owner: object,
                  repo: object, number: object,
                  reply_id: object) -> DiscussionReply:
        """One reply, tombstones included: a reader
        who follows a link to a removed reply is told
        it was removed, not that it never existed."""
        thread = self.get_thread(viewer, owner, repo, number)
        found = self._reply_by_id(reply_id)
        if found is None or found.thread_id != thread.id:
            raise DiscussionError(
                "reply_not_found", "No such reply.")
        return found

    def reply_count(self, viewer: User | None, owner: object,
                    repo: object, number: object) -> int:
        thread = self.get_thread(viewer, owner, repo, number)
        return int(self._conn.execute(
            "SELECT COUNT(*) AS n FROM discussion_replies"
            " WHERE thread_id = ? AND deleted_at IS NULL",
            (thread.id,)).fetchone()["n"])

    def edit_reply(self, actor: User | None, owner: object,
                   repo: object, number: object, reply_id: object,
                   body: object) -> DiscussionReply:
        """Edit a reply: the author's alone. The
        previous body is recorded before the new one
        lands, in the same transaction (S-123)."""
        reply = self.get_reply(actor, owner, repo, number, reply_id)
        if actor is None or actor.id != reply.author_id:
            raise DiscussionError(
                "permission_denied",
                "Only the author can edit this reply.")
        if reply.is_deleted:
            raise DiscussionError(
                "reply_not_found", "No such reply.")
        text = self._validate_reply_body(body)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO discussion_reply_edits"
                " (reply_id, editor_id, previous_body, edited_at)"
                " VALUES (?, ?, ?, ?)",
                (reply.id, actor.id, reply.body, now))
            self._conn.execute(
                "UPDATE discussion_replies SET body = ?,"
                " edited_at = ?, updated_at = ? WHERE id = ?",
                (text, now, now, reply.id))
        found = self._reply_by_id(reply.id)
        assert found is not None
        return found

    def edits_for(self, viewer: User | None, owner: object,
                  repo: object, number: object,
                  reply_id: object) -> list[DiscussionReplyEdit]:
        """A reply's visible edit history, oldest
        first, for any reader of the thread."""
        reply = self.get_reply(viewer, owner, repo, number, reply_id)
        rows = self._conn.execute(
            "SELECT * FROM discussion_reply_edits"
            " WHERE reply_id = ? ORDER BY id",
            (reply.id,)).fetchall()
        return [DiscussionReplyEdit(
            reply_id=r["reply_id"], editor_id=r["editor_id"],
            previous_body=r["previous_body"],
            edited_at=r["edited_at"]) for r in rows]

    def delete_reply(self, actor: User | None, owner: object,
                     repo: object, number: object,
                     reply_id: object) -> DiscussionReply:
        """Remove a reply: S-123's tombstone. The
        author, a repository administrator (the
        moderator here) or a site admin may remove;
        the removal stands on the thread's timeline
        as an event in words, in the same
        transaction."""
        thread = self.get_thread(actor, owner, repo, number)
        reply = self.get_reply(actor, owner, repo, number, reply_id)
        current = self._repo(owner, repo)
        role = self._role(actor, current)
        if actor is None or (actor.id != reply.author_id
                             and not role_covers(role, "admin")):
            raise DiscussionError(
                "permission_denied",
                "Only the author or a repository "
                "administrator can remove this reply.")
        if reply.is_deleted:
            return reply  # already a tombstone: a quiet no-op
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE discussion_replies SET body = '',"
                " deleted_at = ?, deleted_by = ?, updated_at = ?"
                " WHERE id = ?",
                (now, actor.id, now, reply.id))
            self._record_event(
                thread.id, actor.id, "reply_deleted",
                f"reply {reply.id}", now)
        found = self._reply_by_id(reply.id)
        assert found is not None
        return found

    # -- the one timeline -------------------------------------------

    def timeline(self, viewer: User | None, owner: object,
                 repo: object, number: object
                 ) -> list[TimelineEntry]:
        """One thread's one timeline: its live replies
        and its happenings interleaved by time, then
        by a named tie-break (happenings before
        replies inside one second, then record id),
        so the stream is deterministic. Tombstoned
        replies leave the stream; their removal
        stands as its event."""
        thread = self.get_thread(viewer, owner, repo, number)
        entries: list[tuple[int, int, int, TimelineEntry]] = []
        for row in self._conn.execute(
                "SELECT * FROM discussion_replies"
                " WHERE thread_id = ? AND deleted_at IS NULL"
                " ORDER BY id", (thread.id,)).fetchall():
            reply = _row_to_reply(row)
            entries.append((reply.created_at, 1, reply.id,
                            TimelineEntry(
                                created_at=reply.created_at,
                                reply=reply)))
        for row in self._conn.execute(
                "SELECT * FROM discussion_events"
                " WHERE thread_id = ? ORDER BY id",
                (thread.id,)).fetchall():
            event = DiscussionEvent(
                id=row["id"], thread_id=row["thread_id"],
                actor_id=row["actor_id"], kind=row["kind"],
                detail=row["detail"],
                created_at=row["created_at"])
            entries.append((event.created_at, 0, event.id,
                            TimelineEntry(
                                created_at=event.created_at,
                                event=event)))
        entries.sort(key=lambda item: (item[0], item[1], item[2]))
        return [item[3] for item in entries]


# -- rendering (S-010-escaped; states in words) ---------------------


def render_board_page(
        categories: list[DiscussionCategory],
        threads: list[Discussion],
        authors: dict[int, str] | None = None) -> str:
    """The board in words: every category with its
    kind, its declared powers and its description,
    then the threads, pinned first, each with its
    state said in words and its author named."""
    authors = authors or {}
    parts = ["<h1>Discussions</h1>", "<h2>Categories</h2>"]
    if not categories:
        parts.append(
            '<p class="empty">No discussion categories yet.</p>')
    else:
        parts.append('<ul class="discussion-categories">')
        for category in categories:
            spec = KIND_SPECS[category.kind]
            parts.append(
                '<li class="discussion-category">'
                f"<strong>{escape_html_text(category.name)}</strong> "
                f"({escape_html_text(spec.title)}): "
                f"{escape_html_text(spec.words)} "
                f"Opening a thread needs the "
                f"{escape_html_text(spec.create_min_role)} role; "
                f"replying needs the "
                f"{escape_html_text(spec.reply_min_role)} role."
                + (f" {escape_html_text(category.description)}"
                   if category.description else "")
                + "</li>")
        parts.append("</ul>")
    parts.append("<h2>Threads</h2>")
    if not threads:
        parts.append(
            '<p class="empty">No discussions yet.</p>')
    else:
        parts.append('<ol class="discussion-threads">')
        for thread in threads:
            name = authors.get(
                thread.author_id, f"user {thread.author_id}")
            parts.append(
                '<li class="discussion-thread">'
                f'<span class="thread-ref">'
                f"{escape_html_text(thread.ref)}</span> "
                f"<strong>{escape_html_text(thread.title)}</strong> "
                f"by {escape_html_text(name)} "
                f"({escape_html_text(thread.state_words)})</li>")
        parts.append("</ol>")
    return "\n".join(parts)


def render_thread_page(
        thread: Discussion,
        category: DiscussionCategory,
        entries: list[TimelineEntry],
        authors: dict[int, str] | None = None) -> str:
    """One thread in words: its title, kind and
    state, its opening prose, then the one timeline
    -- replies as speech, happenings and moderation
    as events, each said in words."""
    authors = authors or {}
    author = authors.get(
        thread.author_id, f"user {thread.author_id}")
    spec = KIND_SPECS[category.kind]
    parts = [
        f"<h1>{escape_html_text(thread.title)}</h1>",
        f"<p>Category: {escape_html_text(category.name)} "
        f"({escape_html_text(spec.title)}). "
        f"State: {escape_html_text(thread.state_words)}. "
        f"Opened by {escape_html_text(author)}.</p>",
        f'<div class="discussion-body">'
        f"{escape_html_text(thread.body)}</div>",
        '<ol class="discussion-timeline">',
    ]
    for entry in entries:
        words = describe_timeline_entry(entry, authors)
        if entry.reply is not None:
            edited = (' <span class="edited">edited</span>'
                      if entry.reply.was_edited else "")
            parts.append(
                '<li class="timeline-reply">'
                f"<p>{escape_html_text(words)}</p>"
                f'<div class="reply-body">'
                f"{escape_html_text(entry.reply.body)}</div>"
                f"{edited}</li>")
        else:
            parts.append(
                '<li class="timeline-event">'
                f"<p>{escape_html_text(words)}</p></li>")
    parts.append("</ol>")
    return "\n".join(parts)


def render_composer_form(category: DiscussionCategory) -> str:
    """The new-thread composer for one category:
    labelled fields only -- a labelled title input
    and a labelled body textarea -- so it is
    keyboard- and mobile-first, and the category's
    kind and powers are said in words above it."""
    spec = KIND_SPECS[category.kind]
    return "\n".join([
        f"<h2>New {escape_html_text(spec.title.lower())} "
        f"in {escape_html_text(category.name)}</h2>",
        f"<p>{escape_html_text(spec.words)}</p>",
        '<form method="post" class="discussion-composer">',
        '<p><label for="discussion-title">Title</label><br>',
        '<input id="discussion-title" name="title" type="text" '
        f'maxlength="256" required></p>',
        '<p><label for="discussion-body">Body</label><br>',
        '<textarea id="discussion-body" name="body" rows="8" '
        'cols="60" required></textarea></p>',
        '<p><button type="submit">Open discussion</button></p>',
        "</form>",
    ])
