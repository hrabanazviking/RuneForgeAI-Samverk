"""Thread subscription (S-225).

Part XI's per-thread layer over S-222's repository
watch: a person may subscribe to, or mute, one
issue or pull request, and that choice overrides
the repository-level watch -- honestly and
visibly. S-222 judges whether activity in a
repository reaches a person at all; S-223 stores
the reason a notification carries (`subscribed`
is one of its seven); this slice is the
per-thread decision between them, under five
laws:

- **A thread is named whole, or not at all.** A
  thread is a repository (`owner/name`), a kind
  (`issue` or `pull_request` -- the S-121 shared
  numbering's own kinds), and a positive number.
  The kind and the number are judged at the door
  (`thread_kind_invalid` / `thread_number_invalid`
  name the honest set, and a refusal stores
  nothing), and the thread itself must provably
  exist: existence is read through S-121's
  `IssueStore.resolve_number`, the one seam that
  says what a `#n` means in a repository, kind
  included. A number that names no thread, or a
  thread of the other kind, answers the uniform
  `thread_not_found` -- the same answer a missing
  repository and a repository the caller cannot
  read give, so no face leaks which part failed.
- **Two overrides, and inherit.** The stored
  states are `subscribed` and `muted`; the
  absence of a row is the third standing,
  inherit -- no override, the repository watch
  decides. Setting a state replaces the old one;
  clearing removes the row entirely and restores
  inherit. Re-setting the held state and
  clearing no override are quiet no-ops, so
  retries are safe. Judged through
  `validate_subscription_state` at the door --
  anything else is refused
  `subscription_state_invalid`, storing nothing.
  (Inherit is never a stored state: it is named
  by clearing, never by setting.)
- **The override wins, in both directions.**
  The pure `decide_notify` is the whole law: a
  muted thread never notifies, whatever the
  repository watch says -- mute beats watch
  `all`. A subscribed thread always notifies,
  with S-223's reason `subscribed`, whatever
  the repository watch says -- subscribe beats
  `ignore`, beats `releases_only`, beats no
  watch at all. With no override, the
  repository watch decides as S-222 left it:
  `all` notifies; `releases_only` does not
  notify thread activity (it is releases only);
  `ignore` and no watch row do not notify.
- **The override is honest and visible.** No
  face ever reports the thread's standing
  without the repository level underneath it:
  every view carries the stored override, the
  repository watch mode, the effective
  decision, and the explanation said in plain
  words by the pure `explain_effective` --
  "muted -- overrides repository watch: all
  activity", "subscribed -- overrides
  repository watch: ignore", "inherited from
  repository watch: all activity". When the
  override agrees with the watch (subscribed
  under `all`, muted under `ignore`) the words
  say so -- it confirms, it does not pretend
  to override -- and the renderers say the
  explanation outright, never an icon or a
  colour alone, every value through S-010.
- **A subscription belongs to its holder.**
  Every face takes the holder themself and
  scopes by their account id -- in the query
  itself -- so one account can never see or
  change another's subscription, and an
  anonymous caller holds none at all
  (`authentication_required`, S-223/S-224's
  name for the same refusal). Permission is
  S-054's `can_read`, as everywhere: a stranger
  to a private repository gets the uniform
  `thread_not_found` for reads and writes
  alike, and a refusal stores nothing.

One migration: 89 creates `thread_overrides` --
the table is named for the override it stores,
because S-202's billing audit forbids
billing-shaped names for tables, and a
notification subscription is not a billing
subscription.
No new taxonomy event: a thread subscription is
a personal notification state, like S-224's
inbox triage and S-214's saved searches -- it
mutates no shared record, so it is not a
witnessed act; 127 events stand.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .permissions import can_read
from .repositories import Repository, RepositoryStore
from .watch_star import WATCH_MODES

__all__ = [
    "OVERRIDE_STATES", "THREAD_KINDS", "EffectiveDecision",
    "ThreadSubscription", "ThreadSubscriptionError",
    "ThreadSubscriptionStore", "decide_notify",
    "decide_subscription", "explain_effective",
    "render_thread_subscription", "render_thread_subscriptions",
    "validate_subscription_state", "validate_thread_kind",
    "validate_thread_number",
]

# Thread kinds: stored value -> plain words. The
# kinds are S-121's shared-numbering kinds.
THREAD_KINDS: dict[str, str] = {
    "issue": "issue",
    "pull_request": "pull request",
}

# Stored override states: stored value -> plain
# words. Inherit is deliberately absent: it is
# the absence of a row, never a stored state.
OVERRIDE_STATES: dict[str, str] = {
    "subscribed": "subscribed",
    "muted": "muted",
}


class ThreadSubscriptionError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def validate_thread_kind(kind: object) -> str:
    """Pure: the stored thread kind for *kind*, or
    a refusal naming the honest set of two."""
    if not isinstance(kind, str) or kind not in THREAD_KINDS:
        raise ThreadSubscriptionError(
            "thread_kind_invalid",
            "A thread is an issue or a pull request.")
    return kind


def validate_thread_number(number: object) -> int:
    """Pure: the thread number as a positive int,
    or a refusal. Booleans are not numbers here,
    and neither are strings or floats -- a thread
    number is the integer S-121 claimed."""
    if isinstance(number, bool) or not isinstance(number, int) \
            or number <= 0:
        raise ThreadSubscriptionError(
            "thread_number_invalid",
            "A thread number is a positive whole number.")
    return number


def validate_subscription_state(state: object) -> str:
    """Pure: the stored override state for *state*,
    or a refusal naming the honest set. Inherit is
    refused here on purpose: it is reached by
    clearing the override, never by storing it."""
    if not isinstance(state, str) or state not in OVERRIDE_STATES:
        raise ThreadSubscriptionError(
            "subscription_state_invalid",
            "Thread subscription states are: "
            + ", ".join(OVERRIDE_STATES)
            + ". To inherit the repository watch, "
            "clear the override instead.")
    return state


def decide_subscription(current: str | None,
                        requested: str) -> bool:
    """Pure: True when setting *requested* over
    *current* is a real change worth storing;
    False for a retry of the held state."""
    return current != requested


def _watch_words(watch_mode: str | None) -> str:
    if watch_mode is None:
        return "not watching"
    return WATCH_MODES[watch_mode]


def decide_notify(override: str | None,
                  watch_mode: str | None) -> bool:
    """Pure: whether activity on the thread
    notifies its holder. A thread override wins
    in both directions; with no override the
    repository watch decides -- only `all`
    notifies thread activity."""
    if override == "muted":
        return False
    if override == "subscribed":
        return True
    return watch_mode == "all"


@dataclass(frozen=True)
class EffectiveDecision:
    """The effective standing of one thread for
    one holder, with the why kept beside the
    what: the stored override, the repository
    watch underneath it, whether activity
    notifies, the S-223 reason when the
    subscription itself is why (`subscribed`,
    else None), and the explanation in plain
    words."""
    override: str | None
    watch_mode: str | None
    notify: bool
    reason: str | None
    explanation: str


def explain_effective(override: str | None,
                      watch_mode: str | None) -> str:
    """Pure: the standing said in plain words,
    the repository level always named -- the
    override is never shown without what it
    overrides, confirms, or inherits."""
    watch = _watch_words(watch_mode)
    if override == "muted":
        if watch_mode in ("ignore", None):
            return (f"muted -- confirms repository watch: "
                    f"{watch} -- no notifications")
        return (f"muted -- overrides repository watch: "
                f"{watch} -- no notifications")
    if override == "subscribed":
        if watch_mode == "all":
            return ("subscribed -- confirms repository "
                    "watch: all activity -- notifications "
                    "flow (reason: subscribed)")
        return (f"subscribed -- overrides repository "
                f"watch: {watch} -- notifications flow "
                "(reason: subscribed)")
    if watch_mode == "all":
        return ("inherited from repository watch: all "
                "activity -- notifications flow")
    if watch_mode == "releases_only":
        return ("inherited from repository watch: "
                "releases only -- thread activity does "
                "not notify")
    if watch_mode == "ignore":
        return ("inherited from repository watch: "
                "ignore -- no notifications")
    return ("inherited -- no repository watch set -- "
            "no notifications for this thread")


def effective_decision(override: str | None,
                       watch_mode: str | None) -> EffectiveDecision:
    """Pure: the whole effective standing for one
    (override, repository watch) pair."""
    notify = decide_notify(override, watch_mode)
    return EffectiveDecision(
        override=override, watch_mode=watch_mode,
        notify=notify,
        reason="subscribed" if override == "subscribed" else None,
        explanation=explain_effective(override, watch_mode))


@dataclass(frozen=True)
class ThreadSubscription:
    """One holder's standing on one thread: the
    thread named whole, the stored override (None
    is inherit), the repository watch underneath
    it, and the effective decision with its
    explanation -- the override and the level it
    sits on, always together."""
    user_id: int
    username: str
    repo_id: int
    repo_full_name: str      # owner/name, display case
    kind: str                # issue | pull_request
    number: int
    override: str | None     # subscribed | muted | None
    watch_mode: str | None   # all | releases_only | ignore | None
    created_at: int | None
    updated_at: int | None

    @property
    def label(self) -> str:
        return f"{self.repo_full_name}#{self.number}"

    @property
    def kind_words(self) -> str:
        return THREAD_KINDS.get(self.kind, self.kind)

    @property
    def decision(self) -> EffectiveDecision:
        return effective_decision(self.override, self.watch_mode)

    @property
    def notify(self) -> bool:
        return self.decision.notify

    @property
    def explanation(self) -> str:
        return self.decision.explanation

    @property
    def state_words(self) -> str:
        if self.override is None:
            return "inherited"
        return OVERRIDE_STATES[self.override]

    @property
    def words(self) -> str:
        """The standing said in plain words: the
        thread, its kind, and the explanation --
        override and repository level together."""
        return (f"{self.label} ({self.kind_words}): "
                f"{self.explanation}.")


class ThreadSubscriptionStore:
    """Per-thread subscriptions over S-222's
    `repo_watches` (read for the repository level)
    plus this slice's `thread_overrides`
    (migration 89). Thread existence is judged
    through S-121's `IssueStore.resolve_number`
    when an issue store is wired; without one,
    only the repository gate and the reference
    shape are judged -- see the module docstring:
    no existence is ever faked. Every write is
    owner-scoped and commits before the answer,
    like every house store."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        watch_store=None,
        issues=None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._watch = watch_store
        self._issues = issues
        self._now = time_fn

    # -- guards and resolution -------------------------
    @staticmethod
    def _require_user(user: User | None) -> User:
        if user is None:
            raise ThreadSubscriptionError(
                "authentication_required",
                "Sign in to manage thread subscriptions.")
        return user

    def _resolve(self, viewer: User, owner: object,
                 repo: object, kind: object,
                 number: object) -> tuple[Repository, str, int]:
        """The thread named whole, or the uniform
        `thread_not_found`: the kind and number
        shapes are judged first (their refusals
        name the honest sets and store nothing),
        then repository, read permission, and --
        when S-121's store is wired -- the
        thread's own existence and kind, all under
        the one uniform answer."""
        kind = validate_thread_kind(kind)
        number = validate_thread_number(number)
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise ThreadSubscriptionError(
                "thread_not_found", "No such thread.")
        if self._issues is not None:
            item = self._issues.resolve_number(owner, repo, number)
            if item is None or item.kind != kind:
                raise ThreadSubscriptionError(
                    "thread_not_found", "No such thread.")
        return current, kind, number

    def _watch_mode(self, viewer: User, repo: Repository) -> str | None:
        if self._watch is not None:
            return self._watch.watch_mode_for(
                viewer, repo.owner, repo.name)
        row = self._conn.execute(
            "SELECT mode FROM repo_watches"
            " WHERE repo_id = ? AND user_id = ?",
            (repo.id, viewer.id)).fetchone()
        return row["mode"] if row else None

    def _override_row(self, user_id: int, repo_id: int,
                      kind: str, number: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM thread_overrides"
            " WHERE user_id = ? AND repo_id = ?"
            " AND thread_kind = ? AND thread_number = ?",
            (user_id, repo_id, kind, number)).fetchone()

    def _view(self, user: User, repo: Repository, kind: str,
              number: int,
              row: sqlite3.Row | None) -> ThreadSubscription:
        return ThreadSubscription(
            user_id=user.id, username=user.username,
            repo_id=repo.id, repo_full_name=repo.full_name,
            kind=kind, number=number,
            override=row["state"] if row else None,
            watch_mode=self._watch_mode(user, repo),
            created_at=int(row["created_at"]) if row else None,
            updated_at=int(row["updated_at"]) if row else None)

    # -- writes ------------------------------------------
    def set_subscription(self, user: User | None, owner: object,
                         repo: object, kind: object,
                         number: object,
                         state: object) -> ThreadSubscription:
        """Set (or change) the holder's override on
        one thread: `subscribed` or `muted`, judged
        at the door. A retry of the held state is a
        quiet no-op."""
        holder = self._require_user(user)
        stored = validate_subscription_state(state)
        current, kind, number = self._resolve(
            holder, owner, repo, kind, number)
        row = self._override_row(holder.id, current.id, kind, number)
        held = row["state"] if row else None
        if decide_subscription(held, stored):
            now = int(self._now())
            with self._conn:  # commits before the answer
                self._conn.execute(
                    "INSERT INTO thread_overrides"
                    " (user_id, repo_id, thread_kind,"
                    " thread_number, state, created_at,"
                    " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT (user_id, repo_id,"
                    " thread_kind, thread_number) DO UPDATE"
                    " SET state = excluded.state,"
                    " updated_at = excluded.updated_at",
                    (holder.id, current.id, kind, number,
                     stored, now, now))
            row = self._override_row(holder.id, current.id,
                                     kind, number)
        return self._view(holder, current, kind, number, row)

    def clear_subscription(self, user: User | None, owner: object,
                           repo: object, kind: object,
                           number: object) -> ThreadSubscription:
        """Remove the holder's override entirely:
        the thread inherits the repository watch
        again. Clearing no override is a quiet
        no-op."""
        holder = self._require_user(user)
        current, kind, number = self._resolve(
            holder, owner, repo, kind, number)
        row = self._override_row(holder.id, current.id, kind, number)
        if row is not None:
            with self._conn:  # commits before the answer
                self._conn.execute(
                    "DELETE FROM thread_overrides"
                    " WHERE user_id = ? AND repo_id = ?"
                    " AND thread_kind = ? AND thread_number = ?",
                    (holder.id, current.id, kind, number))
            row = None
        return self._view(holder, current, kind, number, row)

    # -- reads ---------------------------------------------
    def get_subscription(self, user: User | None, owner: object,
                         repo: object, kind: object,
                         number: object) -> ThreadSubscription:
        """The holder's own standing on one thread:
        override, repository watch, effective
        decision, and the explanation -- always
        together, never the override alone."""
        holder = self._require_user(user)
        current, kind, number = self._resolve(
            holder, owner, repo, kind, number)
        row = self._override_row(holder.id, current.id, kind, number)
        return self._view(holder, current, kind, number, row)

    def effective_for(self, user: User | None, owner: object,
                      repo: object, kind: object,
                      number: object) -> EffectiveDecision:
        """The pure decision, judged on the stored
        facts: would activity on this thread notify
        this holder, and why."""
        return self.get_subscription(
            user, owner, repo, kind, number).decision

    def list_subscriptions(self, user: User | None) -> list[ThreadSubscription]:
        """The holder's own explicit overrides, in
        thread order -- only rows that still name a
        repository the holder may read; inherit
        standings have no row and are never listed
        as overrides."""
        holder = self._require_user(user)
        rows = self._conn.execute(
            "SELECT * FROM thread_overrides"
            " WHERE user_id = ?"
            " ORDER BY repo_id, thread_kind, thread_number",
            (holder.id,)).fetchall()
        views: list[ThreadSubscription] = []
        for row in rows:
            repo = self._repos.get_by_id(int(row["repo_id"]))
            if repo is None or not can_read(holder, repo):
                continue
            views.append(self._view(
                holder, repo, row["thread_kind"],
                int(row["thread_number"]), row))
        return views

    def list_for_repo(self, user: User | None, owner: object,
                      repo: object) -> list[ThreadSubscription]:
        """The holder's own overrides in one
        repository, in thread order. A repository
        the holder cannot read answers the uniform
        `thread_not_found`."""
        holder = self._require_user(user)
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(holder, current):
            raise ThreadSubscriptionError(
                "thread_not_found", "No such thread.")
        return [v for v in self.list_subscriptions(holder)
                if v.repo_id == current.id]


# -- renders -------------------------------------------------

def render_thread_subscription(view: ThreadSubscription) -> str:
    """One thread's standing in plain words: the
    thread, its kind, and the explanation --
    override and repository level said outright.
    Every value escapes through S-010."""
    return ('<li class="thread-subscription">'
            f"{escape_html_text(view.words)}</li>")


def render_thread_subscriptions(views) -> str:
    """A holder's thread subscriptions panel: each
    standing with its explanation, the repository
    level never hidden. An empty panel teaches the
    model in plain words: subscribe, mute, or
    inherit."""
    rows = list(views)
    if not rows:
        return ('<p class="thread-subscriptions">No thread '
                "subscriptions yet. On any issue or pull "
                "request you can subscribe to follow just "
                "that thread, or mute it to hear nothing "
                "from it; with neither, the thread inherits "
                "your repository watch. An override is "
                "always shown with the repository watch it "
                "sits on.</p>")
    items = "".join(render_thread_subscription(v) for v in rows)
    return ('<section class="thread-subscriptions">'
            f"<ul>{items}</ul></section>")
