"""Push mirrors (S-333).

Samverk mirrors its own repos **onward** -- to a second
machine's Samverk or to a plain git remote -- with the
same status honesty S-332 gave pull syncing.

S-070 built the inward road: a mirror is an ordinary
repository plus a record in ``repo_mirrors``, and every
fetch through its seam records how the attempt ended.
This slice builds the outward road on the same law:

- A repository may name **push targets** -- each one a
  remote URL (validated by S-014's seam; credentials
  inside a URL are refused there, so a stored target
  can never hold a secret) or an absolute local ``Path``
  naming an existing repository directory on this
  instance's disk (a second Samverk's bare repository,
  or any plain git remote kept on disk). Targets live
  in ``repo_push_mirrors`` (migration 136, schema
  135 -> 136): destinations, times, and counts only --
  never a credential.
- **Push** is one push through the dedicated seam
  (``run_git_push_to``: every head and tag, pruned, so
  the target converges to this repository) -- and the
  outcome is *recorded, never hidden*, exactly as
  S-070 records a fetch: ``last_attempt_at`` /
  ``last_status`` / ``last_detail`` are written for
  failures exactly as for successes, and a failed push
  leaves the target's existing content untouched.
- **Status honesty (S-332's law, carried over whole):**
  ``last_success_at`` is moved by successes only, and
  ``last_objects_moved`` counts the objects the attempt
  carried into the target (counted around the push
  when the target is a local repository; for a remote
  URL target the count cannot be read back, so it is
  recorded as not recorded -- ``None`` -- never
  guessed). The failure reason is spoken in plain
  words beside the raw detail. A target whose last
  attempt failed is **not healthy**, however well an
  older push went: healthy only when the last attempt
  succeeded.

Only the repository's owner manages its push targets
(S-070's owner law for mirror records). This slice
adds no audit event (138 stand): a push outcome is
product data in the target record -- the state the
repo page reads -- exactly as S-070/S-332 kept sync
outcomes.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .escaping import escape_html_text
from .mirrors import MirrorService
from .proc import ProcRefused, run_git_push_to, validate_remote_url
from .repositories import Repository, RepositoryStore

__all__ = [
    "STATE_FAILED", "STATE_HEALTHY", "STATE_NEVER_PUSHED",
    "STATE_PENDING", "PushMirror", "PushMirrorError",
    "PushMirrorService", "PushResult", "plain_push_failure_reason",
    "push_target_to_dict", "render_push_mirrors_page",
]

STATE_HEALTHY = "healthy"
STATE_FAILED = "failed"
STATE_PENDING = "pending"
STATE_NEVER_PUSHED = "never_pushed"

_STATE_WORDS = {
    STATE_HEALTHY: "healthy -- the last push succeeded",
    STATE_FAILED: "not healthy -- the last push failed",
    STATE_PENDING: "waiting for its first push -- not yet healthy",
    STATE_NEVER_PUSHED: "never pushed -- not yet healthy",
}


def plain_push_failure_reason(detail: str | None) -> str:
    """Pure: one stored push failure detail, in plain words.

    Known shapes are translated into a sentence a person
    can act on; anything else is said plainly as a failed
    push with the detail kept beside it. An empty detail
    is said to be empty -- never invented over."""
    text = (detail or "").strip()
    if not text:
        return ("The last push failed, and no detail was "
                "recorded for it.")
    low = text.lower()
    if "credential" in low:
        return ("The push's credential could not be used, "
                "so the push could not sign in to its target.")
    if "could not resolve" in low or "name or service not known" in low \
            or "temporary failure in name resolution" in low:
        return ("The target's host name could not be looked "
                "up, so the push never reached the target.")
    if "connection refused" in low:
        return ("The target refused the connection, so the "
                "push could not send anything.")
    if "timed out" in low or "timeout" in low:
        return ("The push ran out of time waiting for its "
                "target, so nothing was sent.")
    if "authentication failed" in low or "permission denied" in low:
        return ("The target refused the push's sign-in, so "
                "nothing was sent.")
    if "non-fast-forward" in low or "rejected" in low:
        return ("The target refused the push because its own "
                "history has moved on, so nothing was sent.")
    if "not found" in low or "does not exist" in low:
        return ("The target could not be found, so the push "
                "had nowhere to send.")
    return f"The last push failed: {text}"


class PushMirrorError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class PushMirror:
    id: int
    repo_id: int
    full_name: str
    target: str
    target_kind: str              # "url" | "local"
    created_at: int
    last_attempt_at: int | None
    last_success_at: int | None
    last_status: str | None       # "ok" | "failed" | None (never pushed)
    last_detail: str | None
    last_objects_moved: int | None = None

    @property
    def state(self) -> str:
        if self.last_status == "ok":
            return STATE_HEALTHY
        if self.last_status == "failed":
            return STATE_FAILED
        if self.last_attempt_at is None and self.last_status is None:
            return STATE_NEVER_PUSHED
        return STATE_PENDING

    @property
    def healthy(self) -> bool:
        """Healthy only when the last attempt succeeded --
        a failed push mirror never looks healthy."""
        return self.state == STATE_HEALTHY

    @property
    def failure_reason(self) -> str | None:
        if self.state != STATE_FAILED:
            return None
        return plain_push_failure_reason(self.last_detail)

    @property
    def state_word(self) -> str:
        return _STATE_WORDS[self.state]

    @property
    def headline(self) -> str:
        return (f"{self.full_name} push mirror to {self.target}: "
                f"{self.state_word}.")


@dataclass(frozen=True)
class PushResult:
    full_name: str
    target: str
    status: str                   # "ok" | "failed"
    pushed_at: int
    detail: str
    objects_moved: int | None = None


def push_target_to_dict(mirror: PushMirror) -> dict:
    """The public facts of one push target -- destination,
    times, counts, and words only; no secret can exist
    here because none can be stored."""
    return {
        "full_name": mirror.full_name,
        "target": mirror.target,
        "target_kind": mirror.target_kind,
        "state": mirror.state,
        "healthy": mirror.healthy,
        "last_attempt_at": mirror.last_attempt_at,
        "last_success_at": mirror.last_success_at,
        "objects_moved": mirror.last_objects_moved,
        "failure_reason": mirror.failure_reason,
    }


class PushMirrorService:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time,
                 push_timeout: float = 120.0):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._now = time_fn
        self._push_timeout = push_timeout

    # -- target law --------------------------------------------------
    @staticmethod
    def _validate_target(target: object) -> tuple[str, str]:
        """Return (stored_target, kind) or raise PushMirrorError."""
        if isinstance(target, Path):
            if not target.is_absolute() or not target.is_dir():
                raise PushMirrorError(
                    "target_invalid",
                    "A local push target must be an existing "
                    "repository directory given as a full path.")
            return str(target), "local"
        try:
            return validate_remote_url(target), "url"
        except ProcRefused as exc:
            raise PushMirrorError("target_invalid", str(exc)) from None

    # -- record --------------------------------------------------------
    def _repo(self, owner, repo) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise PushMirrorError("no_such_repo", "No such repository.")
        return current

    def _require_owner(self, actor_user_id: int, current: Repository):
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise PushMirrorError("no_such_user", "No such account.")
        if actor.username_lower != current.owner_lower:
            raise PushMirrorError(
                "not_repo_owner",
                "Only the repository's owner can manage its "
                "push mirrors.")
        return actor

    def _row_to_mirror(self, current: Repository, row) -> PushMirror:
        return PushMirror(
            id=row["id"], repo_id=row["repo_id"],
            full_name=current.full_name, target=row["target"],
            target_kind=row["target_kind"],
            created_at=row["created_at"],
            last_attempt_at=row["last_attempt_at"],
            last_success_at=row["last_success_at"],
            last_status=row["last_status"],
            last_detail=row["last_detail"],
            last_objects_moved=row["last_objects_moved"])

    def list_targets(self, owner, repo) -> list[PushMirror]:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            return []
        rows = self._conn.execute(
            "SELECT * FROM repo_push_mirrors WHERE repo_id = ?"
            " ORDER BY id", (current.id,)).fetchall()
        return [self._row_to_mirror(current, row) for row in rows]

    def get_target(self, owner, repo, target_id: int) -> PushMirror | None:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            return None
        row = self._conn.execute(
            "SELECT * FROM repo_push_mirrors WHERE repo_id = ? AND id = ?",
            (current.id, target_id)).fetchone()
        if row is None:
            return None
        return self._row_to_mirror(current, row)

    # -- management ----------------------------------------------------
    def add_target(self, actor_user_id: int, owner, repo,
                   target: object, *,
                   source_ip: str | None = None) -> PushMirror:
        """Name one onward target for a repository. Nothing
        is pushed by naming it -- the first push is its own
        act, and until it succeeds the target reads
        never-pushed and not healthy."""
        current = self._repo(owner, repo)
        actor = self._require_owner(actor_user_id, current)
        stored, kind = self._validate_target(target)
        for existing in self.list_targets(owner, repo):
            if existing.target == stored:
                raise PushMirrorError(
                    "target_exists",
                    f"{current.full_name} already pushes to "
                    f"{stored}; remove that target before "
                    "adding it again.")
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO repo_push_mirrors (repo_id, target,"
                " target_kind, created_at) VALUES (?, ?, ?, ?)",
                (current.id, stored, kind, int(self._now())))
            target_id = cursor.lastrowid
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.settings.change", target_kind="repo",
                target_id=current.full_name, outcome="success",
                source_ip=source_ip,
                detail={"key": "push_mirror_target", "kind": kind})
        added = self.get_target(owner, repo, target_id)
        assert added is not None
        return added

    def remove_target(self, actor_user_id: int, owner, repo,
                      target_id: int) -> None:
        """Remove one push target record; the target's own
        content stays exactly as it is (it simply stops
        being pushed to)."""
        current = self._repo(owner, repo)
        self._require_owner(actor_user_id, current)
        if self.get_target(owner, repo, target_id) is None:
            raise PushMirrorError(
                "push_target_not_found",
                f"{current.full_name} has no such push target.")
        with self._conn:
            self._conn.execute(
                "DELETE FROM repo_push_mirrors WHERE repo_id = ?"
                " AND id = ?", (current.id, target_id))

    # -- push ------------------------------------------------------------
    def push_to_target(self, owner, repo, target_id: int, *,
                       token: str | None = None) -> PushResult:
        """Push this repository to one target and record the
        outcome -- success and failure alike."""
        current = self._repo(owner, repo)
        mirror = self.get_target(owner, repo, target_id)
        if mirror is None:
            raise PushMirrorError(
                "push_target_not_found",
                f"{current.full_name} has no such push target.")
        target: str | Path = (Path(mirror.target)
                              if mirror.target_kind == "local"
                              else mirror.target)
        path = self._repos.path_for(current.owner, current.name)
        now = int(self._now())
        before = (MirrorService._count_objects(Path(mirror.target))
                  if mirror.target_kind == "local" else None)
        try:
            result = run_git_push_to(
                path, target, timeout=self._push_timeout, token=token)
            if result.returncode == 0:
                status, detail = "ok", "push completed"
            else:
                status = "failed"
                detail = result.stderr.decode(
                    "utf-8", "replace").strip()[:200] or "push failed"
        except Exception as exc:  # recorded, never hidden, never raised
            status, detail = "failed", f"{type(exc).__name__}: {exc}"[:200]
        after = (MirrorService._count_objects(Path(mirror.target))
                 if mirror.target_kind == "local" else None)
        moved: int | None = (max(0, after - before)
                             if before is not None and after is not None
                             else None)
        with self._conn:
            if status == "ok":
                # S-332's law: success is recorded as success --
                # the last-success moment moves only here.
                self._conn.execute(
                    "UPDATE repo_push_mirrors SET last_attempt_at = ?,"
                    " last_status = ?, last_detail = ?,"
                    " last_success_at = ?, last_objects_moved = ?"
                    " WHERE id = ?",
                    (now, status, detail, now, moved, mirror.id))
            else:
                self._conn.execute(
                    "UPDATE repo_push_mirrors SET last_attempt_at = ?,"
                    " last_status = ?, last_detail = ?,"
                    " last_objects_moved = ? WHERE id = ?",
                    (now, status, detail, moved, mirror.id))
        return PushResult(full_name=current.full_name,
                          target=mirror.target, status=status,
                          pushed_at=now, detail=detail,
                          objects_moved=moved)

    def push_all(self, owner, repo, *,
                 token: str | None = None) -> list[PushResult]:
        """Push to every named target, in the order the
        targets were added; one target's failure is
        recorded on that target and never stops the rest."""
        return [self.push_to_target(owner, repo, mirror.id, token=token)
                for mirror in self.list_targets(owner, repo)]


def _when(ts: int | None) -> str:
    if ts is None:
        return "never"
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts))


def render_push_mirrors_page(full_name: str,
                             mirrors: list[PushMirror]) -> str:
    """The repo-page push mirrors, rendered: each target's
    state in words (never colour-only), last attempt,
    last success, objects moved, and -- when the last
    attempt failed -- the failure reason in plain words.
    Every value escaped through S-010."""
    name = escape_html_text(full_name)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Push mirrors -- {name} -- Samverk</title></head>",
        "<body>",
        f"<h1>Push mirrors -- {name}</h1>",
    ]
    if not mirrors:
        parts.append(f"<p>{name} has no push mirrors.</p>")
    for mirror in mirrors:
        parts.append(
            f"<p>{escape_html_text(mirror.headline)}</p>")
        parts.append(
            f"<p>State: {escape_html_text(mirror.state_word)}.</p>")
        parts.append("<p>Healthy: yes.</p>" if mirror.healthy
                     else "<p>Healthy: no.</p>")
        parts.append(
            "<p>Last attempt: "
            f"{escape_html_text(_when(mirror.last_attempt_at))}.</p>")
        parts.append(
            "<p>Last success: "
            f"{escape_html_text(_when(mirror.last_success_at))}.</p>")
        if mirror.last_objects_moved is None:
            parts.append(
                "<p>Objects moved by the last attempt: not recorded.</p>")
        else:
            parts.append(
                "<p>Objects moved by the last attempt: "
                f"{mirror.last_objects_moved}.</p>")
        if mirror.failure_reason is not None:
            parts.append(
                "<p>Failure reason: "
                f"{escape_html_text(mirror.failure_reason)}</p>")
            if mirror.last_detail:
                parts.append(
                    "<p>Recorded detail: "
                    f"{escape_html_text(mirror.last_detail)}</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
