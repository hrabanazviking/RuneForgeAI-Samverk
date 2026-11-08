"""Notification preferences (S-228).

Part XI's one findable page: everything a person can
choose about their own notifications lives in one
place -- email on or off for each of S-223's seven
reasons, the digest cadence those emails follow,
and every repository the person watches, managed
in one list. Before this slice the choices existed
but were scattered exactly as Forgejo scattered
its controls: S-227's unsubscribe links wrote the
opt-out record one scope at a time with no page to
review them on, the digest rhythm was an
instance-wide mode with no per-person word, and
S-222's watches could be set on each repository
but were listed nowhere together. This module is
that one list, under five laws:

- **One page, every control (the findability
  law).** `PREFERENCE_SECTIONS` names the page's
  three sections -- email, digest, watched
  repositories -- in the order a person looks for
  them, each with its plain-words description, and
  `render_preferences_page` renders exactly those
  sections from one aggregated view
  (`NotificationPreferences`). Nothing about a
  person's notifications is chosen anywhere else:
  if a control exists, it is found here.
- **The records are the earlier slices' own --
  never a second copy.** Email on/off is
  migration 91's `email_optouts`, the very record
  S-227's signed unsubscribe links write and its
  delivery law consults: turning a reason off
  here writes the opt-out the link would write,
  and redeeming a link turns the reason off here.
  Watched repositories are migration 86's
  `repo_watches`, read live and changed only
  through S-222's own store, so its permission
  law and its audit verbs (`repo.watch` /
  `repo.unwatch`) remain the only witness. The
  one new record is the digest cadence, which
  had no home before: migration 92's
  `notification_preferences`, one row per
  account, no row meaning the default.
- **Email has two honest levels, both shown.**
  Each reason carries its own choice, and the
  `all` scope S-227 defined is the page's master
  choice: a reason's email reaches the person
  only when its own choice is on *and* all email
  is on -- the pure `decide_email_enabled`. The
  view carries both levels for every reason, so
  a reason held off by the master switch says
  so outright; it never pretends its own switch
  did it, and flipping one reason never silently
  lifts the master choice.
- **The cadence is a small honest vocabulary.**
  `DIGEST_CADENCES` -- `immediate` (one email
  per notification, as it happens), `daily`
  (one digest a day), `weekly` (one digest a
  week) -- judged at the door by
  `validate_digest_cadence`; anything else is
  refused `digest_cadence_invalid` and stores
  nothing. The pure `decide_user_email` is the
  per-person delivery law over the two: a reason
  whose email is off is skipped
  (`preferences_off`); otherwise the cadence
  decides send-now against queue-for-digest.
  S-227's store keeps its instance law; this
  slice owns the person's recorded choices and
  the decision they compose to.
- **Preferences belong to their holder.** Every
  face takes the holder themself and scopes by
  their account id -- in the query itself -- so
  one account can never read or change another's
  preferences, and an anonymous caller is
  refused `authentication_required` (S-223's
  name for the same refusal). The watched list
  is filtered through S-054's `can_read`, as
  S-209's law demands: a repository the holder
  can no longer read is never named, counted,
  or leaked by its absence being explained.
  Every change commits before its answer (the
  commit-before-answer law), and renders say
  every state in plain words through S-010's
  escaping seam -- never an icon or colour alone.

One migration: 92 creates `notification_preferences`
(schema 91 to 92). No new taxonomy event: a
preference is a personal notification state, like
S-224's triage, S-225's overrides and S-227's
opt-outs -- it mutates no shared record, so it is
not a witnessed act; watch changes made from this
page are witnessed by S-222's own verbs, through
S-222's own store; 127 events stand.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .email_notifications import UNSUBSCRIBE_ALL
from .escaping import escape_html_text
from .notification_reasons import (
    NOTIFICATION_REASONS, NotificationError, validate_reason)
from .permissions import can_read
from .repositories import RepositoryStore
from .watch_star import (
    COUNTED_WATCH_MODES, WATCH_MODES, WatchStarError, WatchStarStore)

__all__ = [
    "DEFAULT_DIGEST_CADENCE", "DIGEST_CADENCES",
    "PREFERENCE_SECTIONS", "NotificationPreferences",
    "PreferenceError", "NotificationPreferencesStore",
    "ReasonEmailPreference", "WatchedRepoPreference",
    "cadence_words", "decide_email_enabled",
    "decide_user_email", "preference_sections",
    "render_preferences_page", "render_reason_preference",
    "render_watched_repo", "validate_digest_cadence",
]

# The digest cadences a person may choose, in the
# order the page offers them: stored value -> the
# plain words it is shown under. Insertion order
# is the display order everywhere.
DIGEST_CADENCES: dict[str, str] = {
    "immediate": "one email per notification, as it happens",
    "daily": "one digest email a day",
    "weekly": "one digest email a week",
}

# No row in migration 92's table means this: the
# person has never chosen, and email follows each
# notification as S-227's per-event shape does.
DEFAULT_DIGEST_CADENCE = "immediate"

# The page's sections, in the order a person looks
# for them: (key, title, plain description). The
# page renders exactly these -- the findability map
# is data, so no section can hide and none is
# promised that the page does not carry.
PREFERENCE_SECTIONS = (
    ("email", "Email",
     "Email on or off for each reason a notification "
     "can reach you, and for all email at once."),
    ("digest", "Digest cadence",
     "How email follows your notifications: at once, "
     "or gathered into a daily or weekly digest."),
    ("watched", "Watched repositories",
     "Every repository you watch, in one list, with "
     "its watch mode -- change a mode or stop "
     "watching from here."),
)


class PreferenceError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def validate_digest_cadence(cadence: object) -> str:
    """Pure: the stored cadence for *cadence*, or a
    refusal naming the honest set of three."""
    if not isinstance(cadence, str) or cadence not in DIGEST_CADENCES:
        raise PreferenceError(
            "digest_cadence_invalid",
            "Digest cadences are: "
            + ", ".join(DIGEST_CADENCES) + ".")
    return cadence


def cadence_words(cadence: object) -> str:
    """Pure: the plain words a stored cadence is
    shown under, judged through the same door."""
    return DIGEST_CADENCES[validate_digest_cadence(cadence)]


def decide_email_enabled(reason_on: bool, all_on: bool) -> bool:
    """Pure: a reason's email reaches its holder
    only when both honest levels are on -- the
    reason's own choice and the all-email choice."""
    return bool(reason_on and all_on)


def decide_user_email(*, enabled: bool, cadence: object,
                      ) -> tuple[str, str]:
    """Pure: the per-person delivery law. Returns
    ``(action, why)`` -- `skip` (this person's
    choices send no email for this reason,
    `preferences_off`), `send` (deliver now, the
    `immediate` cadence, `per_event`), or `queue`
    (hold for the digest the cadence names,
    `digest_daily` / `digest_weekly`). The cadence
    is judged through its door first, so a
    shapeless cadence is refused before any
    choice is weighed."""
    stored = validate_digest_cadence(cadence)
    if not enabled:
        return ("skip", "preferences_off")
    if stored == "immediate":
        return ("send", "per_event")
    return ("queue", f"digest_{stored}")


def preference_sections() -> list[dict]:
    """The findability map as data: every section
    of the one page, in order, with its plain
    description. The page renders exactly this."""
    return [
        {"key": key, "title": title, "description": desc}
        for key, title, desc in PREFERENCE_SECTIONS]


@dataclass(frozen=True)
class ReasonEmailPreference:
    """One reason's standing on the page: its own
    recorded choice, the master choice above it,
    and the effective truth the two compose to --
    all three carried, so the page can say which
    level is doing what."""
    reason: str          # one of S-223's seven, stored
    reason_words: str    # S-223's plain words for it
    own_on: bool         # no per-reason opt-out row
    all_on: bool         # no `all` opt-out row

    @property
    def enabled(self) -> bool:
        """The effective truth: email for this
        reason reaches the holder."""
        return decide_email_enabled(self.own_on, self.all_on)

    @property
    def words(self) -> str:
        """This reason's email standing in plain
        words -- its own switch, and the master
        switch named whenever it is the one
        holding the reason off."""
        state = "on" if self.own_on else "off"
        text = (f"{self.reason} ({self.reason_words}): "
                f"email {state}")
        if not self.all_on:
            text += (" -- held off because all "
                     "notification email is off")
        elif self.enabled:
            text += " -- email will be sent"
        else:
            text += " -- no email will be sent"
        return text


@dataclass(frozen=True)
class WatchedRepoPreference:
    """One watched repository on the page: its
    full name, its stored S-222 mode, and whether
    that mode counts its holder as a watcher."""
    full_name: str
    mode: str            # one of S-222's three, stored
    mode_words: str      # S-222's plain words for it

    @property
    def counted(self) -> bool:
        return self.mode in COUNTED_WATCH_MODES

    @property
    def words(self) -> str:
        """The watch said in plain words -- the
        repository, its mode, and the counting
        truth said outright (`ignore` is a choice,
        not a watch)."""
        if self.counted:
            tail = "you count as a watcher of this repository"
        else:
            tail = ("you do not count as a watcher -- "
                    "ignore is a stored choice, not a watch")
        return f"{self.full_name}: watching: {self.mode_words} -- {tail}"


@dataclass(frozen=True)
class NotificationPreferences:
    """The whole page as one view: the holder, the
    master email choice, every reason's standing,
    the digest cadence, and the watched list --
    everything S-228 gathers, in roadmap order."""
    user_id: int
    username: str        # display case
    email_address: str | None
    all_email_on: bool
    reasons: tuple[ReasonEmailPreference, ...]
    digest_cadence: str
    watched: tuple[WatchedRepoPreference, ...]

    @property
    def digest_words(self) -> str:
        return DIGEST_CADENCES[self.digest_cadence]

    @property
    def watched_count(self) -> int:
        """How many listed rows count their holder
        as a watcher (S-222's counted modes)."""
        return sum(1 for w in self.watched if w.counted)

    def reason_preference(self, reason: str) -> ReasonEmailPreference:
        for entry in self.reasons:
            if entry.reason == reason:
                return entry
        raise KeyError(reason)

    @property
    def words(self) -> str:
        """The page said in one plain sentence --
        the master choice, the cadence, and the
        watched truth, said outright."""
        master = "on" if self.all_email_on else "off"
        return (f"Notification preferences for {self.username}: "
                f"all email {master}; digest cadence "
                f"{self.digest_cadence} ({self.digest_words}); "
                f"{len(self.watched)} watched "
                f"repositor{'y' if len(self.watched) == 1 else 'ies'} "
                f"listed, {self.watched_count} counting you "
                f"as a watcher.")


class NotificationPreferencesStore:
    """The one page's store: reads and writes the
    holder's own choices across S-227's opt-out
    record, migration 92's cadence row, and
    S-222's watch rows (changed only through
    S-222's store)."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        repositories: RepositoryStore,
        watches: WatchStarStore,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._repos = repositories
        self._watches = watches
        self._now = time_fn

    # -- guards --------------------------------------------
    @staticmethod
    def _require_user(user: User | None) -> User:
        if user is None:
            raise PreferenceError(
                "authentication_required",
                "Sign in to see your notification preferences.")
        return user

    def _judge_reason(self, reason: object) -> str:
        try:
            return validate_reason(reason)
        except NotificationError as exc:
            raise PreferenceError(exc.reason, str(exc)) from None

    def _opted_out(self, user_id: int, scope: str) -> bool:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM email_optouts"
            " WHERE user_id = ? AND scope = ?",
            (int(user_id), scope)).fetchone()
        return int(row["n"]) > 0

    def _set_opted_out(self, user_id: int, scope: str,
                       opted_out: bool) -> bool:
        """Write S-227's record for one scope: True
        exactly when the record changed. Commits
        before the answer."""
        if opted_out:
            with self._conn:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO email_optouts"
                    " (user_id, scope, created_at) VALUES (?, ?, ?)",
                    (int(user_id), scope, int(self._now())))
            return cur.rowcount > 0
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM email_optouts"
                " WHERE user_id = ? AND scope = ?",
                (int(user_id), scope))
        return cur.rowcount > 0

    # -- the aggregated view ---------------------------------
    def preferences_for(self, user: User | None,
                        ) -> NotificationPreferences:
        """The holder's whole page as data: master
        and per-reason email standing read live
        from S-227's record (so a redeemed
        unsubscribe link is already true here),
        the cadence (the default when never
        chosen), and the watched list."""
        holder = self._require_user(user)
        all_on = not self._opted_out(holder.id, UNSUBSCRIBE_ALL)
        reasons = tuple(
            ReasonEmailPreference(
                reason=reason, reason_words=words,
                own_on=not self._opted_out(holder.id, reason),
                all_on=all_on)
            for reason, words in NOTIFICATION_REASONS.items())
        return NotificationPreferences(
            user_id=holder.id, username=holder.username,
            email_address=holder.email, all_email_on=all_on,
            reasons=reasons,
            digest_cadence=self.digest_cadence_for(holder),
            watched=self.list_watched(holder))

    # -- email choices ----------------------------------------
    def set_email_enabled(self, user: User | None, reason: object,
                          enabled: bool) -> NotificationPreferences:
        """Set one reason's own email choice: off
        writes the S-227 opt-out for that reason,
        on removes it. The master `all` choice is
        never touched by a per-reason change.
        Returns the fresh page."""
        holder = self._require_user(user)
        stored = self._judge_reason(reason)
        self._set_opted_out(holder.id, stored, not bool(enabled))
        return self.preferences_for(holder)

    def set_all_email_enabled(self, user: User | None,
                              enabled: bool,
                              ) -> NotificationPreferences:
        """Set the master choice S-227's `all`
        scope names: off writes the `all` opt-out
        (every reason's email is held off, each
        reason's own choice left standing beneath
        it), on removes it. Returns the fresh
        page."""
        holder = self._require_user(user)
        self._set_opted_out(holder.id, UNSUBSCRIBE_ALL,
                            not bool(enabled))
        return self.preferences_for(holder)

    def email_plan(self, user: User | None, reason: object,
                   ) -> tuple[str, str]:
        """The per-person delivery law applied to
        one reason: the holder's effective standing
        for the reason and their cadence, composed
        through the pure `decide_user_email`."""
        holder = self._require_user(user)
        stored = self._judge_reason(reason)
        view = self.preferences_for(holder)
        entry = view.reason_preference(stored)
        return decide_user_email(
            enabled=entry.enabled, cadence=view.digest_cadence)

    # -- digest cadence ----------------------------------------
    def digest_cadence_for(self, user: User | None) -> str:
        """The holder's stored cadence, or the
        default when they have never chosen."""
        holder = self._require_user(user)
        row = self._conn.execute(
            "SELECT digest_cadence FROM notification_preferences"
            " WHERE user_id = ?", (holder.id,)).fetchone()
        return row["digest_cadence"] if row else DEFAULT_DIGEST_CADENCE

    def set_digest_cadence(self, user: User | None, cadence: object,
                           ) -> NotificationPreferences:
        """Record the holder's cadence, judged at
        the door -- a refused cadence stores
        nothing. Commits before the answer;
        returns the fresh page."""
        holder = self._require_user(user)
        stored = validate_digest_cadence(cadence)
        with self._conn:  # commits before the answer
            self._conn.execute(
                "INSERT INTO notification_preferences"
                " (user_id, digest_cadence, updated_at)"
                " VALUES (?, ?, ?)"
                " ON CONFLICT (user_id) DO UPDATE SET"
                " digest_cadence = excluded.digest_cadence,"
                " updated_at = excluded.updated_at",
                (holder.id, stored, int(self._now())))
        return self.preferences_for(holder)

    # -- watched repositories ----------------------------------
    def list_watched(self, user: User | None,
                     ) -> tuple[WatchedRepoPreference, ...]:
        """Every repository the holder watches, in
        name order, in one list -- every stored
        mode, `ignore` rows included (they are
        managed choices, and this list is where
        they are managed) -- filtered through
        S-054's `can_read`, so a repository the
        holder can no longer read is never named."""
        holder = self._require_user(user)
        rows = self._conn.execute(
            "SELECT w.repo_id AS repo_id, w.mode AS mode"
            " FROM repo_watches w"
            " JOIN repositories r ON r.id = w.repo_id"
            " WHERE w.user_id = ?"
            " ORDER BY r.owner_lower, r.name_lower",
            (holder.id,)).fetchall()
        watched: list[WatchedRepoPreference] = []
        for row in rows:
            repo = self._repos.get_by_id(int(row["repo_id"]))
            if repo is None or not can_read(holder, repo):
                continue
            mode = row["mode"]
            watched.append(WatchedRepoPreference(
                full_name=repo.full_name, mode=mode,
                mode_words=WATCH_MODES.get(mode, mode)))
        return tuple(watched)

    def set_watch_mode(self, user: User | None, owner: object,
                       repo: object, mode: object,
                       ) -> NotificationPreferences:
        """Change one watched repository's mode
        from the page, through S-222's own store
        -- its permission law, its door, and its
        audit witness are the act; this face only
        routes it and returns the fresh page."""
        holder = self._require_user(user)
        try:
            self._watches.set_watch(holder, owner, repo, mode)
        except WatchStarError as exc:
            raise PreferenceError(exc.reason, str(exc)) from None
        return self.preferences_for(holder)

    def unwatch(self, user: User | None, owner: object, repo: object,
                ) -> NotificationPreferences:
        """Stop watching one repository from the
        page, through S-222's own store (which
        witnesses `repo.unwatch` for a real
        removal). Returns the fresh page."""
        holder = self._require_user(user)
        try:
            self._watches.clear_watch(holder, owner, repo)
        except WatchStarError as exc:
            raise PreferenceError(exc.reason, str(exc)) from None
        return self.preferences_for(holder)


# -- renders ---------------------------------------------------

def render_reason_preference(entry: ReasonEmailPreference) -> str:
    """One reason's row on the page, in plain
    words -- the reason, what it means, and its
    email standing said outright."""
    return ('<li class="preference-reason">'
            f"{escape_html_text(entry.words)}</li>")


def render_watched_repo(entry: WatchedRepoPreference) -> str:
    """One watched repository's row on the page,
    in plain words -- the repository, its mode,
    and the counting truth said outright."""
    return ('<li class="preference-watched">'
            f"{escape_html_text(entry.words)}</li>")


def render_preferences_page(view: NotificationPreferences) -> str:
    """The one page itself: every section named in
    `PREFERENCE_SECTIONS`, in order, each carrying
    its choices in plain words -- email (the
    master choice, then all seven reasons),
    digest cadence (the standing choice, then
    every cadence there is), and watched
    repositories (one list, or the teaching empty
    state). Meaning never rides on an icon or a
    colour alone; every value escapes through
    S-010."""
    sections = {s["key"]: s for s in preference_sections()}
    parts = [
        '<section class="notification-preferences">',
        f"<h1>{escape_html_text('Notification preferences for ' + view.username)}</h1>",
        f"<p>{escape_html_text(view.words)}</p>",
    ]
    # -- email ------------------------------------------------
    email = sections["email"]
    parts.append('<section class="preferences-email">')
    parts.append(f"<h2>{escape_html_text(email['title'])}</h2>")
    parts.append(f"<p>{escape_html_text(email['description'])}</p>")
    if view.email_address:
        parts.append(
            "<p>Email address on this account: "
            f"{escape_html_text(view.email_address)}. "
            "Email is sent only when this instance has "
            "SMTP configured; your in-app inbox holds "
            "every notification either way.</p>")
    else:
        parts.append(
            "<p>No email address on this account: these "
            "choices are recorded now and take effect "
            "when an address is added. Your in-app "
            "inbox holds every notification either "
            "way.</p>")
    master = "on" if view.all_email_on else "off"
    parts.append(
        f"<p>All notification email: {escape_html_text(master)}.</p>")
    parts.append('<ul class="preference-reasons">')
    for entry in view.reasons:
        parts.append(render_reason_preference(entry))
    parts.append("</ul></section>")
    # -- digest -----------------------------------------------
    digest = sections["digest"]
    parts.append('<section class="preferences-digest">')
    parts.append(f"<h2>{escape_html_text(digest['title'])}</h2>")
    parts.append(f"<p>{escape_html_text(digest['description'])}</p>")
    parts.append(
        "<p>Your digest cadence: "
        f"{escape_html_text(view.digest_cadence)} -- "
        f"{escape_html_text(view.digest_words)}.</p>")
    parts.append('<ul class="preference-cadences">')
    for cadence, words in DIGEST_CADENCES.items():
        standing = " (your choice)" if cadence == view.digest_cadence else ""
        parts.append(
            f"<li>{escape_html_text(cadence)} -- "
            f"{escape_html_text(words)}{escape_html_text(standing)}</li>")
    parts.append("</ul></section>")
    # -- watched ----------------------------------------------
    watched_section = sections["watched"]
    parts.append('<section class="preferences-watched">')
    parts.append(f"<h2>{escape_html_text(watched_section['title'])}</h2>")
    parts.append(
        f"<p>{escape_html_text(watched_section['description'])}</p>")
    if not view.watched:
        parts.append(
            '<p class="preferences-watched-empty">You are '
            "not watching any repository yet. Watching a "
            "repository -- all activity, releases only, or "
            "ignore -- is set on the repository itself; "
            "every watch you hold will be listed here, in "
            "one list, where its mode can be changed or "
            "the watch removed.</p>")
    else:
        parts.append('<ul class="preference-watched-list">')
        for entry in view.watched:
            parts.append(render_watched_repo(entry))
        parts.append("</ul>")
    parts.append("</section>")
    parts.append("</section>")
    return "".join(parts)
