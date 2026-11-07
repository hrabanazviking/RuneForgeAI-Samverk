"""Internal visibility (S-197).

A third visibility beside ``public`` and ``private``:
an *internal* repository is readable by every member
of the organization that owns it — and by no one
else. For a personally owned repository the owning
organization does not exist, so internal means every
signed-in member of the instance, and still never an
anonymous visitor.

- **Distinct by construction.** ``internal`` is a
  value of the one visibility vocabulary
  (``samverk/repositories.py``, S-050): it is stored
  in the same column, validated by the same
  validator, and offered by the same creation doors.
  It is not a flag beside visibility, so a repository
  is always exactly one of public, internal, or
  private, and surfaces that switch on visibility
  meet it by name.
- **Enforced by S-190, in the one function.** The
  contribution lives in
  ``samverk/permission_engine.py``: an internal
  repository contributes ``read`` (source
  ``internal``) to a member of the owning
  organization, or, for a personal repository, to
  any signed-in instance member. This module holds
  no second judgement — its pure
  ``decide_internal_read`` states the same law over
  plain facts for callers that hold facts rather
  than rows, and its store resolves through the
  engine, so the two can never drift: the battery
  proves them equal cell by cell.
- **A floor, never more.** Internal grants ``read``
  and nothing above it: writing still needs a team
  grant, a collaborator grant, the org default, or
  ownership, exactly as on a private repository. A
  higher grant is never lowered by the floor.
- **Not-found, not forbidden.** A person who is not
  a member resolves to role ``None`` on an internal
  repository, exactly as on a private one (S-054's
  law): surfaces answer *not found*, so an internal
  repository's existence is itself visible only to
  members.
- **Creation policy speaks it too.** S-196's org
  creation policies name visibilities from the same
  vocabulary, so a policy may allow or refuse
  ``internal`` like any other; the shipped default
  (public and private) is unchanged, so an
  organization opts in by setting its policy.
- **A pure read.** Resolution writes nothing and
  audits nothing, and this slice claims no migration
  and no taxonomy event (122 stand): the visibility
  column has held text since S-050, and ``internal``
  is a new word in it, not a new shape.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .permission_engine import PermissionEngine, Resolution
from .repositories import Repository, _row_to_repo, _validate_visibility

__all__ = [
    "INTERNAL", "InternalDecision", "InternalVisibilityStore",
    "decide_internal_read", "is_internal", "render_internal_page",
]

INTERNAL = "internal"


def is_internal(visibility: object) -> bool:
    """True exactly when *visibility* is the internal
    word of the S-050 vocabulary."""
    return _validate_visibility(visibility) == INTERNAL


@dataclass(frozen=True)
class InternalDecision:
    """The pure outcome for one reader of one
    internal repository: whether the internal floor
    grants them read, and why, in plain words."""
    allowed: bool
    reason: str
    detail: str


def decide_internal_read(
    *, visibility: object, is_member: bool,
    scope: str = "organization",
) -> InternalDecision:
    """The internal law over plain facts. Pure: no
    storage is read here. ``scope`` is
    ``organization`` for an org-owned repository
    (membership of that organization) or ``instance``
    for a personally owned one (any signed-in member
    of the instance); an anonymous visitor is a
    member of neither, so callers pass
    ``is_member=False`` for them. A repository that
    is not internal is refused ``not_internal`` —
    this judge speaks only for internal ones."""
    clean = _validate_visibility(visibility)
    if clean != INTERNAL:
        return InternalDecision(
            allowed=False, reason="not_internal",
            detail="the repository is not internal, so "
                   "the internal floor does not apply")
    if is_member:
        if scope == "instance":
            detail = ("the repository is internal, and "
                      "internal repositories are readable "
                      "by every signed-in member of the "
                      "instance")
        else:
            detail = ("the repository is internal, and "
                      "internal repositories are readable "
                      "by every member of the "
                      "organization that owns it")
        return InternalDecision(
            allowed=True, reason="member", detail=detail)
    return InternalDecision(
        allowed=False, reason="not_a_member",
        detail="the repository is internal and they "
               "are not a member, so its existence "
               "stays private: surfaces answer not "
               "found, not forbidden")


class InternalVisibilityStore:
    """The storefront for the internal law: every
    answer is resolved through S-190's engine, in the
    one function, so no second judgement can drift
    from it. Reads only."""

    def __init__(
        self, conn: sqlite3.Connection,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn
        self._engine = PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)

    def resolution(self, viewer: User | None,
                   repo: Repository) -> Resolution:
        """The viewer's S-190 resolution in *repo*,
        whole: role, source, and reason."""
        return self._engine.resolve(viewer, repo)

    def can_read(self, viewer: User | None,
                 repo: Repository) -> bool:
        """True exactly when the viewer resolves to
        at least ``read`` in *repo*."""
        return self._engine.can(viewer, repo, "read")

    def _repos_of(self, owner: str) -> list[Repository]:
        rows = self._conn.execute(
            "SELECT * FROM repositories"
            " WHERE owner_lower = ? ORDER BY name_lower",
            (owner.lower(),)).fetchall()
        return [_row_to_repo(r) for r in rows]

    def internal_repositories(
            self, owner: str) -> list[Repository]:
        """Every internal repository *owner* holds,
        in name order — the owner's own inventory,
        unfiltered by any viewer."""
        return [r for r in self._repos_of(owner)
                if r.visibility == INTERNAL]

    def readable_internal_repositories(
            self, viewer: User | None,
            owner: str) -> list[Repository]:
        """The internal repositories of *owner* the
        viewer may read, in name order: for a member
        that is all of them (the floor is read), for
        anyone else only the ones another grant
        already opens — an internal repository never
        leaks through this list to a non-member."""
        return [r for r in self.internal_repositories(owner)
                if self.can_read(viewer, r)]


def render_internal_page(owner: str,
                         repos: list[Repository]) -> str:
    """The internal repositories of one owner, as an
    escaped page that states the law in plain words
    beside the list, so the word *internal* is never
    a colour or an icon alone."""
    lines = [
        "<h1>", escape_html_text(owner),
        " — internal repositories</h1>",
        "<p>Internal repositories are readable by "
        "every member of the organization that owns "
        "them, and by no one else. They are not "
        "public, and they are not private.</p>",
    ]
    if not repos:
        lines.append(
            "<p>No internal repositories.</p>")
    for repo in repos:
        lines.append(
            "<p>" + escape_html_text(repo.full_name)
            + " — Internal</p>")
    return "".join(lines)
