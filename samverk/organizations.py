"""Organizations (S-185).

An organization is a named home for people and
repositories: it is created by an account, carries a
profile, and has a settings home where every control
is findable (the founding user-friendliness law —
Forgejo lost its owner because its controls could not
be found; Samverk answers that failure here).

- **One name, one namespace.** An organization name
  obeys the S-013 owner-name law, is unique
  case-insensitively, never collides with a user
  account name (users and organizations share the
  owner namespace repositories live under), and is
  never a reserved name. Display case is preserved;
  the canonical name_lower is what collides.
- **The profile is S-029 law, restated for orgs.**
  Display name and bio are plain text under the same
  caps (50 / 500) with the same control-character
  refusal; the website must be a real http(s) URL or
  empty; an avatar is S-012 upload law narrowed to
  images, and **every image carries alt text**
  (Volmarr's standing image-accessibility law): an
  avatar without real alt text is refused.
- **Stewardship until membership lands.** S-186 owns
  org membership; until it lands, the creator is the
  recorded steward and only the creator or a site
  admin may change the profile or avatar. Naming
  anyone else a steward is S-186's act, never this
  slice's silent side effect.
- **The settings home is a map, honestly drawn.**
  It lists every settings area the roadmap gives an
  organization — the ones this slice builds say so,
  and the ones later slices build are named with
  their slice and marked not yet built, so a person
  looking for a control always finds where it lives
  and never follows a link to nowhere.
- **Audit:** creation appends auth.organization.create
  and changes append auth.organization.update
  (S-185 taxonomy additions); refused attempts
  change nothing and write nothing.
- **Storage** is migration 68's organizations table
  (schema 67 to 68): one row per organization.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .accounts import RESERVED_USERNAMES, AccountStore
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text
from .platform_seam import ensure_dir
from .profiles import (
    AVATAR_POLICY, ProfileError, validate_avatar_alt)
from .repo_paths import RepoPathError, validate_owner_name
from .uploads import inspect_upload, save_to_quarantine

__all__ = [
    "BIO_MAX", "DISPLAY_NAME_MAX", "WEBSITE_MAX",
    "Organization", "OrganizationError", "OrganizationStore",
    "SETTINGS_AREAS", "render_org_page", "render_settings_home",
    "settings_areas", "validate_website",
]

DISPLAY_NAME_MAX = 50
BIO_MAX = 500
WEBSITE_MAX = 200

_EXTENSION_FOR_TYPE = {
    "image/png": ".png", "image/jpeg": ".jpg",
    "image/gif": ".gif", "image/webp": ".webp",
}

# Every settings area an organization will ever have,
# in the order a person looks for them: (key, title,
# plain description, slice that builds it). S-185
# builds profile/avatar/website; the rest are named
# here so the settings home can point at them.
SETTINGS_AREAS = (
    ("profile", "Profile", "Name, bio and website.", "S-185"),
    ("avatar", "Avatar", "The organization's picture and its alt text.", "S-185"),
    ("members", "Members", "Owners and members of the organization.", "S-186"),
    ("teams", "Teams", "Teams inside the organization.", "S-187"),
    ("team_permissions", "Team repository permissions", "What each team may do in each repository.", "S-189"),
    ("repositories", "Repositories", "Creation policies and the repository list.", "S-196"),
    ("audit_log", "Audit log", "Membership, permission and repository events.", "S-198"),
    ("danger", "Delete organization", "Deleting the organization, with its inventory and grace period.", "S-199"),
)
BUILT_AREAS = frozenset({"profile", "avatar", "members", "teams"})


class OrganizationError(ValueError):
    """An organization act refused, clearly: `reason`
    is a stable machine-readable code and the message
    is safe to show the person who tried."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Organization:
    id: int
    name: str              # display case
    name_lower: str        # canonical
    display_name: str | None
    bio: str | None
    website: str | None
    avatar_sha256: str | None
    avatar_content_type: str | None
    avatar_alt: str | None
    created_by: int
    created_at: int
    updated_at: int

    def effective_display_name(self) -> str:
        return self.display_name or self.name

    @property
    def avatar_filename(self) -> str | None:
        if not self.avatar_sha256 or not self.avatar_content_type:
            return None
        ext = _EXTENSION_FOR_TYPE.get(self.avatar_content_type)
        return f"{self.avatar_sha256}{ext}" if ext else None


def _row_to_org(row: sqlite3.Row) -> Organization:
    return Organization(
        id=row["id"], name=row["name"],
        name_lower=row["name_lower"],
        display_name=row["display_name"], bio=row["bio"],
        website=row["website"],
        avatar_sha256=row["avatar_sha256"],
        avatar_content_type=row["avatar_content_type"],
        avatar_alt=row["avatar_alt"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"])


def _clean_text(value: object, *, max_len: int, field: str,
                allow_newlines: bool = False) -> str | None:
    """S-029's text law: strip; empty clears; over the
    cap or carrying controls is refused."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise OrganizationError(
            f"{field}_invalid", f"That {field} is not valid.")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise OrganizationError(
            f"{field}_too_long",
            f"That {field} is too long (at most {max_len} characters).")
    for ch in text:
        if ord(ch) == 0x7F or (ord(ch) < 0x20
                and not (allow_newlines and ch in "\n\t")):
            raise OrganizationError(
                f"{field}_invalid",
                f"That {field} contains characters that cannot be shown.")
    return text


def validate_website(value: object) -> str | None:
    """A website is a real http(s) URL or nothing:
    empty clears the field; any other shape — no
    scheme, a foreign scheme, no host, spaces or
    controls, over the cap — is refused plainly."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise OrganizationError("website_invalid", "That website is not valid.")
    text = value.strip()
    if not text:
        return None
    if len(text) > WEBSITE_MAX or any(
            ord(c) < 0x21 or ord(c) == 0x7F for c in text):
        raise OrganizationError("website_invalid", "That website is not valid.")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise OrganizationError(
            "website_invalid",
            "A website must start with http:// or https:// and name a host.")
    return text


def _validate_org_name(name: object) -> tuple[str, str]:
    try:
        display = validate_owner_name(name)
    except RepoPathError as exc:
        raise OrganizationError("org_invalid", str(exc)) from None
    return display, display.lower()


def settings_areas() -> list[dict]:
    """The settings map as data: every area, what it
    does in plain words, the slice that builds it, and
    whether it is available today. The settings home
    renders exactly this — no area is hidden and none
    is promised before its slice."""
    return [
        {"key": key, "title": title, "description": desc,
         "slice": built_by, "available": key in BUILT_AREAS}
        for key, title, desc, built_by in SETTINGS_AREAS]


class OrganizationStore:
    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    # -- lookups --------------------------------------
    def get_by_name(self, name: object) -> Organization | None:
        if not isinstance(name, str) or not name.strip():
            return None
        row = self._conn.execute(
            "SELECT * FROM organizations WHERE name_lower = ?",
            (name.strip().lower(),)).fetchone()
        return _row_to_org(row) if row else None

    def get_by_id(self, org_id: int) -> Organization | None:
        row = self._conn.execute(
            "SELECT * FROM organizations WHERE id = ?",
            (org_id,)).fetchone()
        return _row_to_org(row) if row else None

    def list_organizations(self) -> list[Organization]:
        rows = self._conn.execute(
            "SELECT * FROM organizations ORDER BY name_lower").fetchall()
        return [_row_to_org(r) for r in rows]

    # -- guards ---------------------------------------
    def _require_org(self, org_id: int) -> Organization:
        org = self.get_by_id(org_id)
        if org is None:
            raise OrganizationError("org_not_found", "No such organization.")
        return org

    def _require_steward(self, actor_user_id: int,
                         org: Organization):
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise OrganizationError("no_such_user", "No such account.")
        if actor.id != org.created_by and not actor.is_admin:
            raise OrganizationError(
                "not_org_steward",
                "Only the organization's steward or a site admin "
                "can change this organization until membership lands (S-186).")
        return actor

    # -- S-185: creation -------------------------------
    def create_organization(
        self, actor_user_id: int, name: object, *,
        display_name: object = None, bio: object = None,
        website: object = None, source_ip: str | None = None,
    ) -> Organization:
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise OrganizationError("no_such_user", "No such account.")
        display, name_lower = _validate_org_name(name)
        if name_lower in RESERVED_USERNAMES:
            raise OrganizationError(
                "org_reserved", "That organization name is reserved.")
        if self._accounts.get_by_username(name_lower) is not None:
            raise OrganizationError(
                "org_name_is_user",
                "That name belongs to a user account; organizations "
                "and users share one name space.")
        if self.get_by_name(name_lower) is not None:
            raise OrganizationError(
                "org_taken", f"{display} is already an organization.")
        shown = _clean_text(display_name, max_len=DISPLAY_NAME_MAX,
                            field="display_name")
        bio_clean = _clean_text(bio, max_len=BIO_MAX, field="bio",
                                allow_newlines=True)
        site = validate_website(website)
        now = int(self._now())
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO organizations (name, name_lower,"
                " display_name, bio, website, created_by,"
                " created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (display, name_lower, shown, bio_clean, site,
                 actor.id, now, now))
            org_id = int(cur.lastrowid)
        org = self._require_org(org_id)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="auth.organization.create",
                target_kind="organization", target_id=org.name_lower,
                outcome="success", source_ip=source_ip,
                detail={"org": org.name_lower})
        return org

    # -- S-185: profile and avatar ----------------------
    def update_profile(
        self, actor_user_id: int, org_id: int, *,
        display_name: object = None, bio: object = None,
        website: object = None, source_ip: str | None = None,
    ) -> Organization:
        """Set display name, bio and website (each field
        is passed through its cleaner: a submitted empty
        value clears it). Steward-only until S-186."""
        org = self._require_org(org_id)
        actor = self._require_steward(actor_user_id, org)
        shown = _clean_text(display_name, max_len=DISPLAY_NAME_MAX,
                            field="display_name")
        bio_clean = _clean_text(bio, max_len=BIO_MAX, field="bio",
                                allow_newlines=True)
        site = validate_website(website)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE organizations SET display_name = ?,"
                " bio = ?, website = ?, updated_at = ? WHERE id = ?",
                (shown, bio_clean, site, now, org.id))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="auth.organization.update",
                target_kind="organization", target_id=org.name_lower,
                outcome="success", source_ip=source_ip,
                detail={"fields": "text"})
        return self._require_org(org.id)

    def set_avatar(
        self, actor_user_id: int, org_id: int, data: bytes, *,
        data_root: Path, declared_type: str | None = None,
        alt_text: object = None, source_ip: str | None = None,
    ) -> Organization:
        """Avatar upload under S-012 law + the alt-text
        law. Refusals (disguised payload, non-image,
        oversize, missing alt) store and change nothing."""
        org = self._require_org(org_id)
        actor = self._require_steward(actor_user_id, org)
        try:
            alt = validate_avatar_alt(alt_text)
        except ProfileError as exc:
            raise OrganizationError(exc.reason, str(exc)) from None
        quarantine_path = save_to_quarantine(
            Path(data_root), data, declared_type=declared_type,
            policy=AVATAR_POLICY)
        inspected = inspect_upload(
            data, declared_type=declared_type, policy=AVATAR_POLICY)
        ext = _EXTENSION_FOR_TYPE[inspected.detected_type]
        avatars_dir = ensure_dir(Path(data_root) / "avatars")
        promoted = avatars_dir / f"{inspected.sha256}{ext}"
        if not promoted.exists():
            promoted.write_bytes(quarantine_path.read_bytes())
            try:
                promoted.chmod(0o600)
            except OSError:
                pass
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE organizations SET avatar_sha256 = ?,"
                " avatar_content_type = ?, avatar_alt = ?,"
                " updated_at = ? WHERE id = ?",
                (inspected.sha256, inspected.detected_type, alt,
                 now, org.id))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="auth.organization.update",
                target_kind="organization", target_id=org.name_lower,
                outcome="success", source_ip=source_ip,
                detail={"fields": "avatar"})
        return self._require_org(org.id)


def render_org_page(org: Organization) -> str:
    """The organization profile page. Every value the
    org controls reaches HTML only through S-010; the
    avatar <img>, when present, always carries its
    stored alt text in an escaped attribute."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(org.effective_display_name())} — Samverk</title></head>",
        "<body>",
        f"<h1>{escape_html_text(org.effective_display_name())}</h1>",
        f'<p class="org-name">@{escape_html_text(org.name)}</p>',
    ]
    filename = org.avatar_filename
    if filename is not None and org.avatar_alt:
        src = escape_html_attr(f"/avatars/{filename}")
        alt = escape_html_attr(org.avatar_alt)
        parts.append(f'<img class="avatar" src="{src}" alt="{alt}">')
    if org.bio:
        bio_html = escape_html_text(org.bio).replace("\n", "<br>\n")
        parts.append(f'<p class="bio">{bio_html}</p>')
    if org.website:
        href = escape_html_attr(org.website)
        label = escape_html_text(org.website)
        parts.append(f'<p class="website"><a href="{href}">{label}</a></p>')
    parts.append("</body></html>")
    return "\n".join(parts)


def render_settings_home(org: Organization) -> str:
    """The settings home: every settings area listed
    with a plain description; available areas link to
    their control, areas a later slice builds are
    named with that slice and marked not yet built —
    findable always, promised never early."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Settings — {escape_html_text(org.name)} — Samverk</title></head>",
        "<body>",
        f"<h1>Settings for {escape_html_text(org.effective_display_name())}</h1>",
        "<ul>",
    ]
    for area in settings_areas():
        title = escape_html_text(area["title"])
        desc = escape_html_text(area["description"])
        if area["available"]:
            href = escape_html_attr(
                f"/orgs/{org.name_lower}/settings/{area['key']}")
            parts.append(
                f'<li><a href="{href}">{title}</a> — {desc}</li>')
        else:
            parts.append(
                f"<li>{title} — {desc} "
                f"(Not yet built — lands with {escape_html_text(area['slice'])}.)</li>")
    parts.append("</ul></body></html>")
    return "\n".join(parts)
