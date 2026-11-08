"""Watch and star (S-222).

Wires S-119: the repository header has carried watch
and star counts as `None` -- named missing, never
faked -- since Part V, waiting for the actions
themselves. This slice is those actions, under four
laws:

- **Counts are real actions, counted live.** A watch
  is a stored row with a mode; a star is a stored
  row. Counts are `COUNT(*)` over those rows at read
  time -- never a cached counter that could drift,
  never a dressed-up zero. The header's seam is fed
  directly: `WatchStarStore.watch_count` and
  `.star_count` are exactly the `Counter` callables
  `RepoHeaderService` accepts.
- **Watch has three modes, and ignore is not
  watching.** `all` (every notification), `releases_only`
  (release publications only), and `ignore` (an
  explicit opt-out, stored so the choice is the
  user's own record). The watcher count counts `all`
  and `releases_only` rows only: a person who chose
  to ignore a repository is not its watcher. Setting
  a mode replaces the old one; clearing removes the
  row entirely.
- **Only real changes are witnessed.** Re-setting the
  mode you already hold, re-starring, un-starring
  what you never starred, and clearing a watch you
  never set are quiet no-ops -- retries are safe, and
  the audit log (`repo.watch` / `repo.unwatch` /
  `repo.star` / `repo.unstar`) records a change only
  when one happened, so S-221's event store sees
  exactly the real mutations.
- **Permission is S-054's `can_read`, as everywhere.**
  Watching and starring are reader acts: a stranger
  to a private repository gets the uniform
  `repo_not_found` for reads and writes alike, and a
  refusal stores nothing and emits nothing. Mutations
  need a signed-in account (`login_required`);
  anonymous visitors may read counts on public
  repositories but hold no watch and no star.

One migration: 86 creates `repo_watches` and
`repo_stars`. Four taxonomy additions (append-only):
the watch/star verbs above; 127 events stand.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .permissions import can_read
from .repositories import Repository, RepositoryStore

# stored mode -> plain-words label. Insertion order is
# the display order everywhere.
WATCH_MODES: dict[str, str] = {
    "all": "all activity",
    "releases_only": "releases only",
    "ignore": "ignore",
}

# The modes that make someone a watcher of the
# repository. `ignore` is a stored choice, not a watch.
COUNTED_WATCH_MODES = ("all", "releases_only")


class WatchStarError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class WatchStarSummary:
    full_name: str
    watch_count: int          # counted modes only, live
    star_count: int           # live
    my_watch_mode: str | None  # the viewer's own mode
    my_starred: bool           # the viewer's own star


def validate_watch_mode(mode: object) -> str:
    """Pure: the stored watch mode for *mode*, or a
    refusal naming the honest set."""
    if not isinstance(mode, str) or mode not in WATCH_MODES:
        raise WatchStarError(
            "watch_mode_invalid",
            "Watch modes are: " + ", ".join(WATCH_MODES) + ".")
    return mode


def decide_watch(current: str | None, requested: str) -> bool:
    """Pure: True when setting *requested* over
    *current* is a real change worth storing and
    witnessing; False for a retry of the same mode."""
    return current != requested


def decide_star(starred: bool, want: bool) -> bool:
    """Pure: True when moving to *want* changes the
    stored star state."""
    return starred != want


class WatchStarStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    # -- watch ------------------------------------------------
    def set_watch(self, actor: User | None, owner: object,
                  repo: object, mode: object,
                  *, source_ip: str | None = None
                  ) -> WatchStarSummary:
        """Set (or change) the actor's watch mode.
        A retry of the held mode is a quiet no-op."""
        actor = self._require_actor(actor)
        current_repo = self._resolve(actor, owner, repo)
        new_mode = validate_watch_mode(mode)
        old_mode = self._watch_mode_row(current_repo.id, actor.id)
        if decide_watch(old_mode, new_mode):
            now = int(self._now())
            with self._conn:  # commits before the answer
                self._conn.execute(
                    "INSERT INTO repo_watches (repo_id, user_id,"
                    " mode, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT (repo_id, user_id) DO UPDATE"
                    " SET mode = excluded.mode,"
                    " updated_at = excluded.updated_at",
                    (current_repo.id, actor.id, new_mode, now, now))
            self._emit(actor, "repo.watch", current_repo,
                       {"mode": new_mode, "previous": old_mode},
                       source_ip)
        return self.summary(actor, owner, repo)

    def clear_watch(self, actor: User | None, owner: object,
                    repo: object,
                    *, source_ip: str | None = None
                    ) -> WatchStarSummary:
        """Remove the actor's watch row entirely, any
        mode. Clearing no watch is a quiet no-op."""
        actor = self._require_actor(actor)
        current_repo = self._resolve(actor, owner, repo)
        old_mode = self._watch_mode_row(current_repo.id, actor.id)
        if old_mode is not None:
            with self._conn:
                self._conn.execute(
                    "DELETE FROM repo_watches WHERE repo_id = ?"
                    " AND user_id = ?",
                    (current_repo.id, actor.id))
            self._emit(actor, "repo.unwatch", current_repo,
                       {"previous": old_mode}, source_ip)
        return self.summary(actor, owner, repo)

    def watch_mode_for(self, viewer: User | None, owner: object,
                       repo: object) -> str | None:
        """The viewer's own stored mode, or None (no
        row, or an anonymous viewer, who holds none)."""
        current_repo = self._resolve(viewer, owner, repo)
        if viewer is None:
            return None
        return self._watch_mode_row(current_repo.id, viewer.id)

    def list_watchers(self, viewer: User | None, owner: object,
                      repo: object) -> tuple[tuple[str, str], ...]:
        """Who watches, in the order they began:
        (username, mode) for the counted modes only --
        an `ignore` choice is not a watch and its holder
        is not named a watcher."""
        current_repo = self._resolve(viewer, owner, repo)
        rows = self._conn.execute(
            "SELECT u.username AS username, w.mode AS mode"
            " FROM repo_watches w JOIN users u ON u.id = w.user_id"
            " WHERE w.repo_id = ? AND w.mode IN (?, ?)"
            " ORDER BY w.created_at, w.id",
            (current_repo.id, *COUNTED_WATCH_MODES)).fetchall()
        return tuple((r["username"], r["mode"]) for r in rows)

    # -- star ---------------------------------------------------
    def star(self, actor: User | None, owner: object,
             repo: object,
             *, source_ip: str | None = None) -> WatchStarSummary:
        """Star the repository: a bookmark and a public
        signal in one stored row. Re-starring is a
        quiet no-op."""
        actor = self._require_actor(actor)
        current_repo = self._resolve(actor, owner, repo)
        if decide_star(self._starred_row(current_repo.id, actor.id), True):
            with self._conn:
                self._conn.execute(
                    "INSERT OR IGNORE INTO repo_stars"
                    " (repo_id, user_id, created_at) VALUES (?, ?, ?)",
                    (current_repo.id, actor.id, int(self._now())))
            self._emit(actor, "repo.star", current_repo, {}, source_ip)
        return self.summary(actor, owner, repo)

    def unstar(self, actor: User | None, owner: object,
               repo: object,
               *, source_ip: str | None = None) -> WatchStarSummary:
        """Take the actor's own star back. Un-starring
        what was never starred is a quiet no-op; there
        is no seam that removes another account's star."""
        actor = self._require_actor(actor)
        current_repo = self._resolve(actor, owner, repo)
        if decide_star(self._starred_row(current_repo.id, actor.id), False):
            with self._conn:
                self._conn.execute(
                    "DELETE FROM repo_stars WHERE repo_id = ?"
                    " AND user_id = ?", (current_repo.id, actor.id))
            self._emit(actor, "repo.unstar", current_repo, {}, source_ip)
        return self.summary(actor, owner, repo)

    def is_starred(self, viewer: User | None, owner: object,
                   repo: object) -> bool:
        current_repo = self._resolve(viewer, owner, repo)
        if viewer is None:
            return False
        return self._starred_row(current_repo.id, viewer.id)

    def list_starred_repos(self, viewer: User | None,
                           username: object) -> tuple[str, ...]:
        """The full names of the repositories *username*
        has starred, oldest star first, filtered to what
        this viewer may read -- a private repository's
        star is as invisible as the repository itself."""
        subject = (self._accounts.get_by_username(username)
                   if isinstance(username, str) else None)
        if subject is None:
            raise WatchStarError("no_such_user", "No such account.")
        rows = self._conn.execute(
            "SELECT repo_id FROM repo_stars WHERE user_id = ?"
            " ORDER BY created_at, id", (subject.id,)).fetchall()
        names: list[str] = []
        for row in rows:
            target = self._repos.get_by_id(int(row["repo_id"]))
            if target is not None and can_read(viewer, target):
                names.append(target.full_name)
        return tuple(names)

    # -- counts and summary (the S-119 seam) ---------------------
    def watch_count(self, repo: Repository) -> int:
        """The header's watch counter: counted rows in
        the counted modes, at read time."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM repo_watches"
            " WHERE repo_id = ? AND mode IN (?, ?)",
            (repo.id, *COUNTED_WATCH_MODES)).fetchone()
        return int(row["c"])

    def star_count(self, repo: Repository) -> int:
        """The header's star counter: counted star rows,
        at read time."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM repo_stars WHERE repo_id = ?",
            (repo.id,)).fetchone()
        return int(row["c"])

    def summary(self, viewer: User | None, owner: object,
                repo: object) -> WatchStarSummary:
        current_repo = self._resolve(viewer, owner, repo)
        mode = None
        starred = False
        if viewer is not None:
            mode = self._watch_mode_row(current_repo.id, viewer.id)
            starred = self._starred_row(current_repo.id, viewer.id)
        return WatchStarSummary(
            full_name=current_repo.full_name,
            watch_count=self.watch_count(current_repo),
            star_count=self.star_count(current_repo),
            my_watch_mode=mode, my_starred=starred)

    # -- internals -------------------------------------------------
    def _resolve(self, viewer: User | None, owner: object,
                 repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise WatchStarError(
                "repo_not_found", "No such repository.")
        return current

    @staticmethod
    def _require_actor(actor: User | None) -> User:
        if actor is None:
            raise WatchStarError(
                "login_required",
                "Watching and starring need a signed-in account.")
        return actor

    def _watch_mode_row(self, repo_id: int, user_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT mode FROM repo_watches"
            " WHERE repo_id = ? AND user_id = ?",
            (repo_id, user_id)).fetchone()
        return row["mode"] if row else None

    def _starred_row(self, repo_id: int, user_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 AS x FROM repo_stars"
            " WHERE repo_id = ? AND user_id = ?",
            (repo_id, user_id)).fetchone()
        return row is not None

    def _emit(self, actor: User, action: str, repo: Repository,
              detail: dict, source_ip: str | None) -> None:
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action=action,
                target_kind="repo", target_id=repo.full_name,
                outcome="success", source_ip=source_ip, detail=detail)


def render_watch_star(summary: WatchStarSummary) -> str:
    """The watch/star panel in words: the counts, and
    the viewer's own state named plainly -- meaning
    never rides on an icon or a colour alone. Every
    value passes S-010's seam."""
    if summary.my_watch_mode is None:
        watch_word = "not watching"
    else:
        watch_word = ("watching: "
                      + WATCH_MODES[summary.my_watch_mode])
    star_word = "starred by you" if summary.my_starred else "not starred by you"
    return "\n".join([
        '<section class="repo-watch-star">',
        f"<p>Watchers: {summary.watch_count} - "
        f"{escape_html_text(watch_word)}</p>",
        f"<p>Stars: {summary.star_count} - "
        f"{escape_html_text(star_word)}</p>",
        "</section>",
    ])
