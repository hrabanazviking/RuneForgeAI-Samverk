"""Repository visibility enforcement (S-054).

One permission function for repositories — `role_for` — and
every surface (web, API, git transports) consults it or the
`can_*` wrappers over it, so there is no second place where
visibility law can quietly differ. Part IX's matrix battery
and Part IX's collaborator model build on this seam; S-190's
permission engine generalises it later without changing the
answers for the cases decided here.

The law, in order:

1. The **owner** holds `admin` over their own repositories.
2. An instance **site admin** holds `admin` (instance
   administration is a real role in Samverk, audited elsewhere;
   hiding repositories from it would be theatre, not security).
3. A **collaborator role** granted on this repository
   (`read` / `write` / `admin`, supplied by the caller until
   Part IX owns the grant store) applies on any visibility.
4. A **public** repository is readable by everyone, including
   anonymous visitors; writing is never granted by visibility.
5. A **private** repository is invisible to everyone else:
   role `None`, which surfaces must render as *not found*,
   not *forbidden* — a private repo's existence is itself
   private (the standard anti-enumeration answer).

Roles rank `read < write < admin`; `can_write` and
`can_admin` are rank checks, never separate rules.
"""

from __future__ import annotations

from .accounts import User
from .repositories import Repository

ROLE_RANK = {"read": 1, "write": 2, "admin": 3}


class PermissionDeniedError(PermissionError):
    """Raised by `require_role`; `reason` is a stable code."""

    def __init__(self, reason: str = "permission_denied"):
        super().__init__(reason)
        self.reason = reason


def role_for(
    viewer: User | None,
    repo: Repository,
    *,
    collaborator_role: str | None = None,
) -> str | None:
    """The viewer's role on *repo*: 'admin', 'write', 'read',
    or None (no access — render as not-found)."""
    if viewer is not None:
        if viewer.username_lower == repo.owner_lower:
            return "admin"
        if viewer.is_admin:
            return "admin"
        if collaborator_role in ROLE_RANK:
            return collaborator_role
    if repo.visibility == "public":
        return "read"
    return None


def can_read(viewer: User | None, repo: Repository, **kw) -> bool:
    role = role_for(viewer, repo, **kw)
    return role is not None and ROLE_RANK[role] >= ROLE_RANK["read"]


def can_write(viewer: User | None, repo: Repository, **kw) -> bool:
    role = role_for(viewer, repo, **kw)
    return role is not None and ROLE_RANK[role] >= ROLE_RANK["write"]


def can_admin(viewer: User | None, repo: Repository, **kw) -> bool:
    return role_for(viewer, repo, **kw) == "admin"


def require_role(viewer: User | None, repo: Repository,
                 minimum: str = "read", **kw) -> str:
    """Return the viewer's role if it meets *minimum*, else
    raise PermissionDeniedError — the guard transports and
    handlers call before serving a repository."""
    role = role_for(viewer, repo, **kw)
    if role is None or ROLE_RANK[role] < ROLE_RANK[minimum]:
        raise PermissionDeniedError()
    return role
