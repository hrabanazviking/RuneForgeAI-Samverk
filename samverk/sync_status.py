"""Sync status (S-332) -- last attempt, last success,
objects moved, and the failure reason in plain words,
shown on the repo page.

S-070 recorded how a mirror's last sync ended, S-329
kept a failed mirror from advertising ready, S-330 gave
mirrors credentials, and S-331 gave them a schedule.
What none of them put in one honest place was the whole
story of a mirror's syncing, readable at a glance:

- **Last attempt** -- when a sync last ran, however it
  ended (``repo_mirrors.last_sync_at``).
- **Last success** -- when a sync last *completed*
  (``repo_mirrors.last_success_at``, migration 135).
  A failed attempt never moves this moment: success is
  a fact about a sync that finished, not about one
  that was tried.
- **Objects moved** -- how many git objects the last
  attempt brought into the mirror
  (``repo_mirrors.last_objects_moved``, migration 135),
  counted around the fetch in S-070's sync seam, so
  every road that syncs through it -- direct, pull
  (S-329), credentialed (S-330), scheduled (S-331) --
  records the same honest count. A sync that changes
  nothing moves zero, said plainly as zero.
- **Failure reason in plain words** -- when the last
  attempt failed, the stored detail is translated into
  a sentence a person can act on. The raw detail stays
  on the record beside the translation; nothing is
  hidden, and nothing raw is dressed up as plain.

**A failed mirror never looks healthy.** The state is
``healthy`` only when the last attempt succeeded.
Failed, syncing, pending, and never-synced mirrors
all read ``healthy == False`` and say their state in
words -- never colour-only, never a green tick borrowed
from an older success.

This surface is read-only: it writes nothing and adds
no audit event (138 stand). Storage is migration 135
(schema 134 -> 135): the two columns above -- times
and counts only, never a credential, never a source.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .escaping import escape_html_text
from .repositories import RepositoryStore

__all__ = [
    "STATE_FAILED", "STATE_HEALTHY", "STATE_NEVER_SYNCED",
    "STATE_PENDING", "STATE_SYNCING", "SyncStatus",
    "SyncStatusService", "plain_failure_reason",
    "render_sync_status_page", "status_to_dict",
]

STATE_HEALTHY = "healthy"
STATE_FAILED = "failed"
STATE_SYNCING = "syncing"
STATE_PENDING = "pending"
STATE_NEVER_SYNCED = "never_synced"

_STATE_WORDS = {
    STATE_HEALTHY: "healthy -- the last sync succeeded",
    STATE_FAILED: "not healthy -- the last sync failed",
    STATE_SYNCING: "syncing now -- not yet known healthy",
    STATE_PENDING: "waiting for its first sync -- not yet healthy",
    STATE_NEVER_SYNCED: "never synced -- not yet healthy",
}


def plain_failure_reason(detail: str | None) -> str:
    """Pure: one stored failure detail, in plain words.

    Known shapes are translated into a sentence a person
    can act on; anything else is said plainly as a failed
    fetch with the detail kept beside it. An empty detail
    is said to be empty -- never invented over."""
    text = (detail or "").strip()
    if not text:
        return ("The last sync failed, and no detail was "
                "recorded for it.")
    low = text.lower()
    if "credential" in low:
        return ("The mirror's credential could not be used, "
                "so the sync could not sign in to its source.")
    if "could not resolve" in low or "name or service not known" in low \
            or "temporary failure in name resolution" in low:
        return ("The source's host name could not be looked "
                "up, so the sync never reached the source.")
    if "connection refused" in low:
        return ("The source refused the connection, so the "
                "sync could not fetch anything.")
    if "timed out" in low or "timeout" in low:
        return ("The sync ran out of time waiting for its "
                "source, so nothing was fetched.")
    if "authentication failed" in low or "permission denied" in low:
        return ("The source refused the sync's sign-in, so "
                "nothing was fetched.")
    if "not found" in low or "does not exist" in low:
        return ("The source could not be found, so the sync "
                "had nothing to fetch.")
    return f"The last sync failed: {text}"


def _state_of(last_status: str | None,
              last_sync_at: int | None) -> str:
    if last_status == "ok":
        return STATE_HEALTHY
    if last_status == "failed":
        return STATE_FAILED
    if last_status == "syncing":
        return STATE_SYNCING
    if last_status == "pending":
        return STATE_PENDING
    if last_sync_at is None and last_status is None:
        return STATE_NEVER_SYNCED
    return STATE_PENDING


@dataclass(frozen=True)
class SyncStatus:
    repo_id: int
    full_name: str
    last_attempt_at: int | None
    last_success_at: int | None
    objects_moved: int | None
    last_status: str | None
    last_detail: str | None

    @property
    def state(self) -> str:
        return _state_of(self.last_status, self.last_attempt_at)

    @property
    def healthy(self) -> bool:
        """Healthy only when the last attempt succeeded --
        a failed mirror never looks healthy."""
        return self.state == STATE_HEALTHY

    @property
    def failure_reason(self) -> str | None:
        if self.state != STATE_FAILED:
            return None
        return plain_failure_reason(self.last_detail)

    @property
    def state_word(self) -> str:
        return _STATE_WORDS[self.state]

    @property
    def headline(self) -> str:
        return f"{self.full_name} sync status: {self.state_word}."


def status_to_dict(status: SyncStatus) -> dict:
    """The public facts of one sync status -- times,
    counts, and words only; no source, no secret."""
    return {
        "full_name": status.full_name,
        "state": status.state,
        "healthy": status.healthy,
        "last_attempt_at": status.last_attempt_at,
        "last_success_at": status.last_success_at,
        "objects_moved": status.objects_moved,
        "failure_reason": status.failure_reason,
    }


class SyncStatusService:
    """The one honest read of a mirror's syncing, over
    S-070's mirror records and migration 135's success
    and object counts. Read-only."""

    def __init__(self, conn: sqlite3.Connection,
                 data_root: Path,
                 accounts: AccountStore,
                 repositories: RepositoryStore):
        self._conn = conn
        self._repos = repositories

    def status_for(self, owner, repo) -> SyncStatus | None:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            return None
        row = self._conn.execute(
            "SELECT * FROM repo_mirrors WHERE repo_id = ?",
            (current.id,)).fetchone()
        if row is None:
            return None
        keys = row.keys()
        return SyncStatus(
            repo_id=row["repo_id"], full_name=current.full_name,
            last_attempt_at=row["last_sync_at"],
            last_success_at=(row["last_success_at"]
                             if "last_success_at" in keys else None),
            objects_moved=(row["last_objects_moved"]
                           if "last_objects_moved" in keys else None),
            last_status=row["last_status"],
            last_detail=row["last_detail"])


def _when(ts: int | None) -> str:
    if ts is None:
        return "never"
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts))


def render_sync_status_page(status: SyncStatus) -> str:
    """The repo-page sync status, rendered: state in
    words (never colour-only), last attempt, last
    success, objects moved, and -- when the last attempt
    failed -- the failure reason in plain words. Every
    value escaped through S-010."""
    name = escape_html_text(status.full_name)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Sync status -- {name} -- Samverk</title></head>",
        "<body>",
        f"<h1>Sync status -- {name}</h1>",
        f"<p>{escape_html_text(status.headline)}</p>",
        f"<p>State: {escape_html_text(status.state_word)}.</p>",
        ("<p>Healthy: yes.</p>" if status.healthy
         else "<p>Healthy: no.</p>"),
        f"<p>Last attempt: {escape_html_text(_when(status.last_attempt_at))}.</p>",
        f"<p>Last success: {escape_html_text(_when(status.last_success_at))}.</p>",
    ]
    if status.objects_moved is None:
        parts.append("<p>Objects moved by the last attempt: not recorded.</p>")
    else:
        parts.append(
            f"<p>Objects moved by the last attempt: {status.objects_moved}.</p>")
    if status.failure_reason is not None:
        parts.append(
            "<p>Failure reason: "
            f"{escape_html_text(status.failure_reason)}</p>")
        if status.last_detail:
            parts.append(
                "<p>Recorded detail: "
                f"{escape_html_text(status.last_detail)}</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
