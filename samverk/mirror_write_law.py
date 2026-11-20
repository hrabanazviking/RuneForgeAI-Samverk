"""Mirror write law (S-334).

Roadmap S-334: **mirrors are read-only for local changes;
the UI and transports refuse pushes to a mirror with the
reason stated.**

S-070 made a mirror an ordinary repository plus a record
in ``repo_mirrors``; S-329..S-333 built the pull, credential,
schedule, status and push-mirror roads on that record. What
none of them stated as law was the other half of what a
mirror *is*: its content is owned by its source. A local
change to a mirror is a lie twice over -- it claims the
mirror says something its source never said, and the next
sync (S-070's fetch: every head and tag, pruned) silently
takes it away. So the law refuses the change at the door,
with the reason stated, instead of letting it land and be
erased.

- **The judgement is pure and read-only.**
  ``decide_mirror_write`` judges one mirror record (or its
  absence); ``MirrorWriteLaw.judge`` reads the record
  through S-070's ``MirrorService``. Neither writes
  anything and neither is witnessed: a refusal is not an
  act on the repository, so the taxonomy is unmoved
  (138 events stand) and no migration is claimed (schema
  stays 136) -- mirror-ness already stands in
  ``repo_mirrors``.
- **The reason is always stated.** A refusal names the
  repository, names its source, and says the way through:
  change the source repository and let the mirror sync.
  The machine reason is ``mirror_read_only`` everywhere --
  this module, the receive gate, and both transports -- so
  no door invents its own spelling.
- **The doors.** (1) The transports: smart HTTP
  (``SmartHttpService``, S-077) refuses a receive-pack
  advertisement or POST to a mirror, and the SSH door
  (``SshServeService``, S-086/S-087) refuses
  ``git-receive-pack`` to a mirror -- both after the
  standing permission gate and before any pack byte moves,
  with the reason in the refusal. Reads (upload-pack,
  upload-archive, advertisement for fetch) are untouched:
  a mirror is read-only, not unreadable. (2) The
  pre-receive gate (S-089): ``gate_plugin`` plugs into the
  protection stage, so any caller that runs pushes through
  ``ReceiveGate`` refuses mirrors on the same words.
  (3) The UI: ``render_mirror_write_law_page`` and
  ``render_mirror_read_only_notice`` state the law on the
  repo page in words (never colour-only), escaped through
  S-010.
- **Sync is not a local change.** The mirror's own sync
  seam (S-070's fetch, and every road over it) does not
  pass through the transports or the gate, and this law
  never judges it: a mirror still converges to its source
  exactly as before. Push mirrors (S-333) are likewise
  untouched -- mirroring a repository *onward* is a read
  of this repository, not a change to it. Detaching the
  mirror record (S-070) ends the law for that repository:
  it is an ordinary repository again, writable on the
  standing permissions.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .escaping import escape_html_text
from .mirrors import Mirror, MirrorService
from .receive_gate import GateVeto
from .repositories import RepositoryStore

__all__ = [
    "REASON_MIRROR_READ_ONLY", "MirrorWriteError",
    "MirrorWriteLaw", "WriteDecision", "decide_mirror_write",
    "decision_to_dict", "mirror_row_for",
    "render_mirror_read_only_notice",
    "render_mirror_write_law_page", "write_refusal_message",
]

REASON_MIRROR_READ_ONLY = "mirror_read_only"


def write_refusal_message(full_name: str, source: str) -> str:
    """The one refusal sentence, stated the same way at
    every door: the repository, its source, the law, and
    the way through."""
    return (
        f"{full_name} is a mirror of {source} and mirrors are "
        "read-only for local changes, so this change is refused. "
        "Change the source repository instead and let the mirror "
        "sync.")


class MirrorWriteError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class WriteDecision:
    full_name: str
    is_mirror: bool
    source: str | None        # the mirror's source, when a mirror
    allowed: bool
    reason: str               # "ok" | "mirror_read_only"
    message: str              # the law, stated in words


def decide_mirror_write(full_name: str,
                        mirror: Mirror | None) -> WriteDecision:
    """Pure: judge one repository by its mirror record.

    A repository with no mirror record is writable (the
    standing permissions still judge *who* may write; this
    law judges only mirror-ness). A mirror is refused, with
    the reason stated."""
    if mirror is None:
        return WriteDecision(
            full_name=full_name, is_mirror=False, source=None,
            allowed=True, reason="ok",
            message=(f"{full_name} is not a mirror; local changes "
                     "are judged by the standing permissions."))
    return WriteDecision(
        full_name=full_name, is_mirror=True, source=mirror.source,
        allowed=False, reason=REASON_MIRROR_READ_ONLY,
        message=write_refusal_message(full_name, mirror.source))


def decision_to_dict(decision: WriteDecision) -> dict:
    """The public facts of one judgement -- names, words,
    and the source a mirror itself advertises; no secret
    can exist here because a stored source never holds one
    (S-070/S-014)."""
    return {
        "full_name": decision.full_name,
        "is_mirror": decision.is_mirror,
        "source": decision.source,
        "allowed": decision.allowed,
        "reason": decision.reason,
        "message": decision.message,
    }


def mirror_row_for(conn: sqlite3.Connection,
                   repo_id: int) -> tuple[str, str] | None:
    """(source, source_kind) for one repository id, read
    straight from S-070's record -- the transports' fast
    check, which must not build a service to ask one
    question. None when the repository is not a mirror."""
    row = conn.execute(
        "SELECT source, source_kind FROM repo_mirrors"
        " WHERE repo_id = ?", (repo_id,)).fetchone()
    if row is None:
        return None
    return row[0], row[1]


class MirrorWriteLaw:
    """The write law over S-070's mirror records. Read-only:
    judging writes nothing and witnesses nothing."""

    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore,
                 repositories: RepositoryStore,
                 mirrors: MirrorService | None = None):
        self._conn = conn
        self._repos = repositories
        self._mirrors = mirrors or MirrorService(
            conn, data_root, accounts, repositories)

    def judge(self, owner, repo) -> WriteDecision:
        """Judge one repository. A missing repository raises
        MirrorWriteError("no_such_repo") -- this law never
        invents a verdict for a repository that is not
        there (callers that must not leak existence, the
        transports, resolve and permission-check first, on
        their own standing shapes, before asking)."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise MirrorWriteError(
                "no_such_repo", "No such repository.")
        mirror = self._mirrors.mirror_for(current.owner, current.name)
        return decide_mirror_write(current.full_name, mirror)

    def require_writable(self, owner, repo) -> WriteDecision:
        """The decision, or MirrorWriteError with reason
        ``mirror_read_only`` and the refusal sentence as the
        message, for a mirror."""
        decision = self.judge(owner, repo)
        if not decision.allowed:
            raise MirrorWriteError(decision.reason, decision.message)
        return decision

    def gate_plugin(self, context) -> bool:
        """The S-089 protection-stage plug-in: refuse a push
        to a mirror with the reason stated, through the
        gate's own veto. Judged on the context's canonical
        owner/repo names; a repository the gate is judging
        has already resolved at its transport."""
        decision = self.judge(context.owner, context.repo_name)
        if not decision.allowed:
            raise GateVeto(decision.message)
        return True


def render_mirror_read_only_notice(decision: WriteDecision) -> str:
    """The repo-page notice fragment: a mirror states that
    it is read-only, why, and the way through -- in words,
    never colour-only. A non-mirror renders nothing."""
    if not decision.is_mirror:
        return ""
    return (
        '<p class="mirror-read-only">Read-only mirror: '
        f"{escape_html_text(decision.message)}</p>")


def render_mirror_write_law_page(decision: WriteDecision) -> str:
    """The write-law page for one repository: mirror or not,
    writable or refused, and -- for a mirror -- the reason
    stated whole. Every value escaped through S-010."""
    name = escape_html_text(decision.full_name)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Mirror write law -- {name} -- Samverk</title></head>",
        "<body>",
        f"<h1>Mirror write law -- {name}</h1>",
    ]
    if decision.is_mirror:
        parts.append("<p>This repository is a mirror.</p>")
        parts.append(
            "<p>Mirror: yes. Read-only for local changes: yes.</p>")
        parts.append(
            f"<p>Source: {escape_html_text(decision.source or '')}</p>")
        parts.append(
            f"<p>Pushes refused: {escape_html_text(decision.message)}</p>")
    else:
        parts.append("<p>This repository is not a mirror.</p>")
        parts.append(
            "<p>Mirror: no. Read-only for local changes: no.</p>")
        parts.append(
            "<p>Local changes are judged by the standing "
            "permissions.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
