"""Permission preview — "view as" for admins (S-201).

See the instance exactly as a chosen member sees it:
the findability and safety tool.

- **What a preview is.** ``PermissionPreviewEngine.
  preview`` answers, for one chosen member (the
  *target*), the question "what can this person
  actually see?" — every repository on the instance
  resolved for the target through S-190's one
  function, ``PermissionEngine.resolve``, keeping
  exactly the repositories the target holds a role
  in, each with its role, its source and its plain-
  words reason. It is the tool an admin reaches for
  when a member says "I cannot find that repository"
  (findability: is it hidden from them, and why?) and
  when a steward asks "have we left anything open to
  this person?" (safety: the whole of what they can
  reach, in one place, nothing understated).
- **Exactness is by construction.** The preview does
  not re-derive a single permission judgement: each
  repository is resolved by the same S-190 call every
  surface uses, so a preview can never disagree with
  the answer the target actually lives under — the
  battery proves the equality repository by
  repository, across ownership, team grants with
  nesting, collaborator grants (S-191), the org
  default (S-192) and every visibility.
- **Site admins only.** The title says "for admins"
  and the guard means it literally: the actor must
  be a site admin (``not_site_admin`` otherwise).
  An organization owner is *not* enough — an org
  owner's preview of a member would name private
  repositories outside their own organization,
  while a site admin already holds admin on every
  repository (S-054's law), so a preview can never
  widen what its viewer could not already see. The
  guard is judged in that order on purpose: actor
  existence, then admin standing, then target
  existence, so a non-admin learns nothing about
  which accounts exist by probing preview targets.
  The pure ``decide_preview`` names every refusal.
- **Hidden repositories are counted, never named.**
  A repository the target holds no role in does not
  appear in the preview at all — not its name, not
  its owner, not its visibility — because a private
  repository's existence is itself private (S-054's
  law, kept by S-190). The preview carries only the
  *count* of hidden repositories, so the admin can
  say "three repositories are hidden from them"
  without the preview itself becoming the leak it
  exists to prevent.
- **A preview changes nothing and impersonates no
  one.** Previewing is a pure read: it writes no
  row, grants no role, and appends no audit entry.
  The absence of an audit entry is deliberate, not
  an oversight — an entry written under the target's
  name would be impersonation leakage (the log would
  claim the member looked at things the admin
  looked at), and an entry is not needed to keep the
  admin honest, because the preview hands the admin
  no power they did not already hold and takes no
  action in anyone's name. After a preview, the
  target's resolved roles are exactly what they
  were before it; the battery proves it.
- **Who may be previewed.** Any existing account,
  named by id or by username (case-insensitively):
  a plain member, an organization owner, another
  site admin, or the previewing admin themself. An
  unknown actor or target is ``no_such_user``. There
  is no anonymous preview: "view as" names a member,
  and the anonymous visitor's one answer (public
  repositories are readable) is already S-190's
  ``resolve`` with no viewer.
- **Shown as a page.** ``render_permission_preview_
  page`` states, in words and never colour-only,
  that this is a preview (not a sign-in), who is
  previewing whom, every visible repository with
  its role and source in the order the repositories
  sort, and the hidden count with the reason hidden
  repositories are not named — every value escaped
  through S-010.
- **No storage, no event.** A preview claims no
  migration of its own (schema stays 78) and no
  taxonomy event (122 stand: 31 auth / 79 repo /
  12 admin): it reads the repositories table and
  lets S-190's engine read everything else, exactly
  where the earlier slices put it.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .organizations import OrganizationError
from .permission_engine import (
    PermissionEngine, Resolution, source_word)
from .team_permissions import ROLES, role_word

__all__ = [
    "ROLES", "PermissionPreview", "PermissionPreviewEngine",
    "decide_preview", "render_permission_preview_page",
    "visible_resolutions",
]


def decide_preview(*, actor_exists: bool, actor_is_admin: bool,
                   target_exists: bool) -> str | None:
    """Pure preview guard: the refusal reason, or None
    when the preview may be computed. Judged in the
    order existence, admin standing, target — a
    non-admin is refused before the target is ever
    looked up, so preview targets cannot be used to
    probe which accounts exist."""
    if not actor_exists:
        return "no_such_user"
    if not actor_is_admin:
        return "not_site_admin"
    if not target_exists:
        return "no_such_user"
    return None


def visible_resolutions(
    resolutions: list[Resolution],
) -> tuple[list[Resolution], int]:
    """Pure visibility filter: the resolutions that
    carry a role, in their given order, and the count
    of those that carry none. A role of None means
    the repository is hidden from that person, so it
    is counted and never carried into the preview."""
    visible = [r for r in resolutions if r.role is not None]
    return visible, len(resolutions) - len(visible)


@dataclass(frozen=True)
class PermissionPreview:
    """The instance exactly as one member sees it:
    who asked, who was previewed, every repository
    the target holds a role in (each a full S-190
    ``Resolution``, in repository order), and how
    many repositories are hidden from the target —
    counted, never named."""
    actor_id: int
    actor_username: str
    target_id: int
    target_username: str
    target_is_admin: bool
    entries: tuple[Resolution, ...]
    hidden_count: int
    total_count: int

    @property
    def visible_count(self) -> int:
        return len(self.entries)

    def role_for(self, full_name: str) -> str | None:
        """The target's role in one visible repository,
        named ``owner/name`` — or None when that
        repository is not in the preview (hidden from
        the target, or not on the instance)."""
        for entry in self.entries:
            if entry.full_name == full_name:
                return entry.role
        return None

    def counts_by_role(self) -> dict[str, int]:
        """How many visible repositories the target
        holds at each ladder rung, in ladder order;
        rungs nobody holds are absent, not zero."""
        counts: dict[str, int] = {}
        for role in ROLES:
            found = sum(1 for e in self.entries if e.role == role)
            if found:
                counts[role] = found
        return counts


class PermissionPreviewEngine:
    """The previewer itself: guard the actor, resolve
    the target in every repository through S-190's
    engine, keep what the target can see. Reads only:
    this class holds no AuditLog and writes nothing,
    so a preview can never impersonate its target."""

    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._now = time_fn
        self._engine = PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)

    def _resolve_target(self, target: object) -> User | None:
        if isinstance(target, User):
            return self._accounts.get_by_id(target.id)
        if isinstance(target, int):
            return self._accounts.get_by_id(target)
        if isinstance(target, str):
            return self._accounts.get_by_username(target)
        return None

    # -- the one act ---------------------------------
    def preview(
        self, actor_id: int, target: object,
    ) -> PermissionPreview:
        """The instance as *target* (an account id or a
        username) sees it, computed for the site admin
        *actor_id*. Refusals, in guard order: an
        unknown actor is ``no_such_user``, a non-admin
        actor is ``not_site_admin``, an unknown target
        is ``no_such_user``. A pure read: nothing is
        written, granted or audited."""
        actor = self._accounts.get_by_id(actor_id)
        target_user = self._resolve_target(target)
        refusal = decide_preview(
            actor_exists=actor is not None,
            actor_is_admin=bool(actor and actor.is_admin),
            target_exists=target_user is not None)
        if refusal == "not_site_admin":
            raise OrganizationError(
                "not_site_admin",
                "Only a site admin can preview the "
                "instance as another member.")
        if refusal is not None:
            raise OrganizationError(
                "no_such_user", "No such account.")
        assert actor is not None and target_user is not None
        rows = self._conn.execute(
            "SELECT * FROM repositories"
            " ORDER BY owner_lower, name_lower").fetchall()
        resolutions = [
            self._engine.resolve(
                target_user,
                PermissionEngine._repo_from_row(row))
            for row in rows]
        entries, hidden = visible_resolutions(resolutions)
        return PermissionPreview(
            actor_id=actor.id, actor_username=actor.username,
            target_id=target_user.id,
            target_username=target_user.username,
            target_is_admin=bool(target_user.is_admin),
            entries=tuple(entries), hidden_count=hidden,
            total_count=len(resolutions))

    def preview_page(
        self, actor_id: int, target: object,
    ) -> str:
        """The preview, rendered: ``preview`` judged
        and guarded, then said as a page."""
        return render_permission_preview_page(
            self.preview(actor_id, target))


def render_permission_preview_page(
    preview: PermissionPreview,
) -> str:
    """One member's view of the instance, for the admin
    who asked: the preview banner said plainly (this
    is a look, not a sign-in; nothing was changed),
    every visible repository with its role and source
    in words, and the hidden repositories counted with
    the reason they are never named — every value
    escaped through S-010."""
    ladder = " / ".join(role_word(r) for r in ROLES)
    target = preview.target_username
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Permission preview — "
        f"{escape_html_text(target)} — Samverk</title></head>",
        "<body>",
        f"<h1>Permission preview — "
        f"{escape_html_text(target)}</h1>",
        f"<p>Preview only: "
        f"{escape_html_text(preview.actor_username)} (a site "
        f"admin) is viewing the instance exactly as "
        f"{escape_html_text(target)} sees it. This is not a "
        "sign-in: no action was taken as that member, "
        "nothing was changed, granted or written, and no "
        "audit entry was made in their name.</p>",
        f"<p>{escape_html_text(target)} can see "
        f"{preview.visible_count} of {preview.total_count} "
        "repositories on this instance.</p>",
        "<h2>Repositories they can see</h2>",
    ]
    if preview.entries:
        parts.append("<ul>")
        for entry in preview.entries:
            parts.append(
                f"<li>{escape_html_text(entry.full_name)} — "
                f"{escape_html_text(entry.role_word())} — "
                f"{escape_html_text(source_word(entry.source))}: "
                f"{escape_html_text(entry.detail)}</li>")
        parts.append("</ul>")
    else:
        parts.append(
            "<p>They can see no repositories on this "
            "instance.</p>")
    parts.append("<h2>Repositories hidden from them</h2>")
    if preview.hidden_count:
        parts.append(
            f"<p>{preview.hidden_count} "
            f"{'repository is' if preview.hidden_count == 1 else 'repositories are'} "
            "hidden from them. Hidden repositories are "
            "counted here, never named: a private "
            "repository's existence is itself private, so "
            "this preview names none of them.</p>")
    else:
        parts.append(
            "<p>No repositories are hidden from them.</p>")
    parts.append(
        f"<p>The permission ladder (S-189) is: "
        f"{escape_html_text(ladder)}. Read may look; triage "
        "may manage issues and pull requests without writing "
        "code; write may push; maintain may manage "
        "non-destructive repository settings; admin is full "
        "control. Every role above was resolved by the "
        "permission engine (S-190), the same function every "
        "surface uses, so this preview is the member's real "
        "view, not a second judgement of it.</p>")
    parts.append(
        "<p>Only a site admin can preview (S-201). An "
        "organization owner cannot: a preview names what a "
        "member can reach across the whole instance, and "
        "site admins already hold admin on every repository, "
        "so a preview never widens what its viewer could "
        "already see.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
