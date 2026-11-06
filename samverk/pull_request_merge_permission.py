"""Merge permission (S-163).

Only users with write may merge. That one sentence is
enforced in two places, on purpose, because they answer
two different questions:

- **Server law (S-054).** The merge itself — S-153's
  landing path in `pull_request_merge` — consults this
  seam before anything moves: a mere reader, and the
  pull request's own author on authorship alone, are
  refused `permission_denied`, in words, under the
  house shape. A refused merge burns nothing and is
  witnessed in the audit log as a denied attempt under
  the merge event S-153 already owns.
- **Chrome law (S-112).** The merge button is a view
  of the same answer: it is rendered only for a viewer
  who may actually land this merge now, and is *absent*
  — never greyed, never `disabled`, never present-but-
  inert — for everyone else. A reader can still open
  the merge preview and read the plan in words; the
  preview is a read act, gated by the S-141 seam like
  every read (a stranger to a private repository gets
  `pull_request_not_found` before any permission
  question is asked).

The seam itself is S-054's one permission function and
nothing else: `can_merge` is `can_write` said in this
slice's words, and a role is whatever `role_for`
resolves — owner and site admin hold `admin`, a
caller-supplied collaborator role applies as granted
(the grant store is Part IX's, exactly as S-054 leaves
it), and a public repository's readability never grants
write. There is no second place where merge permission
can quietly differ.
"""

from __future__ import annotations

from dataclasses import dataclass

from .accounts import User
from .permissions import can_write, role_for
from .repositories import Repository

__all__ = [
    "MergePermission", "PERMISSION_DENIED", "can_merge",
    "merge_permission", "permission_words",
]

PERMISSION_DENIED = "permission_denied"


def permission_words(full_name: str) -> str:
    """The refusal, in words — the one wording the
    server raise, the preview, and this seam all use:
    who may merge, and what standing it takes."""
    return (f"Only a writer on {full_name} can merge this "
            f"pull request; merging needs write permission "
            f"on the repository it proposes into.")


def can_merge(viewer: User | None, repo: Repository,
              *, collaborator_role: str | None = None) -> bool:
    """May *viewer* merge into *repo*? Write is the
    whole law (S-163 over S-054's rank check)."""
    return can_write(viewer, repo,
                     collaborator_role=collaborator_role)


@dataclass(frozen=True)
class MergePermission:
    allowed: bool
    role: str | None     # the viewer's role, in words;
    # None only when the seam was asked about a
    # repository the viewer cannot even read
    full_name: str
    number: int | None = None

    @property
    def reason(self) -> str:
        return "" if self.allowed else PERMISSION_DENIED

    @property
    def words(self) -> str:
        if self.allowed:
            return (f"You may merge into {self.full_name} "
                    f"— your role is {self.role}, and "
                    f"merging needs write.")
        return permission_words(self.full_name)


def merge_permission(viewer: User | None, repo: Repository,
                     *, collaborator_role: str | None = None,
                     number: int | None = None) -> MergePermission:
    """The viewer's merge standing on *repo*, resolved
    once through S-054 — the answer the button's
    presence and the server's refusal both read."""
    return MergePermission(
        allowed=can_merge(viewer, repo,
                          collaborator_role=collaborator_role),
        role=role_for(viewer, repo,
                      collaborator_role=collaborator_role),
        full_name=repo.full_name, number=number)
