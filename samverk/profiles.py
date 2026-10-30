"""Profiles (S-029).

A profile is what the world sees of an account: a display name, a
bio, and an avatar. Three laws shape this slice:

- **Avatar upload is S-012 law, narrowed to images.** The upload
  is inspected by `samverk.uploads` under an image-only policy
  with a 2 MiB cap: sniffing beats the declared type, a disguised
  payload is refused at the door, and accepted bytes land first
  in quarantine under a content-addressed name. Promotion out of
  quarantine — the deliberate act S-012 reserves to the owning
  slice — copies the bytes to `<data_root>/avatars/<sha256><ext>`
  (mode 600). The uploader's filename never forms a path.
- **Every image carries alt text** (Volmarr's standing image-
  accessibility law, 2026-10-19). An avatar without a real alt
  text is refused — empty, whitespace-only, or control-carrying
  alt text is no alt text. The alt text is stored with the
  avatar and is rendered, attribute-escaped, on every profile
  page; a profile page can therefore never emit an `<img>`
  without an `alt`.
- **The profile page escapes through the one seam.** Display
  name, bio, username and alt text reach HTML only via
  `samverk.escaping` (S-010): text contexts through
  `escape_html_text`, the `alt`/`src` attributes through
  `escape_html_attr`. The avatar URL is built by this module
  from the stored SHA-256 + sniffed-type extension, never from
  user input.

Display name and bio are plain text with hard, stated limits
(50 / 500 characters) and no control characters (a newline is
allowed in the bio only). Updates are audit-logged as
`auth.profile.update` (S-029 taxonomy addition).
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text
from .platform_seam import ensure_dir
from .uploads import UploadPolicy, UploadRejected, save_to_quarantine

DISPLAY_NAME_MAX = 50
BIO_MAX = 500
AVATAR_ALT_MAX = 200
AVATAR_MAX_BYTES = 2 * 1024 * 1024

AVATAR_POLICY = UploadPolicy(
    max_bytes=AVATAR_MAX_BYTES,
    allowed_types=frozenset({
        "image/png", "image/jpeg", "image/gif", "image/webp",
    }),
)

_EXTENSION_FOR_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class ProfileError(ValueError):
    """A profile update refused, clearly: `reason` is a stable
    machine-readable code and the message is safe to show."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Profile:
    user_id: int
    display_name: str | None
    bio: str | None
    avatar_sha256: str | None
    avatar_content_type: str | None
    avatar_alt: str | None

    def effective_display_name(self, username: str) -> str:
        return self.display_name or username

    @property
    def avatar_filename(self) -> str | None:
        if not self.avatar_sha256 or not self.avatar_content_type:
            return None
        ext = _EXTENSION_FOR_TYPE.get(self.avatar_content_type)
        return f"{self.avatar_sha256}{ext}" if ext else None


def _clean_text(value: object, *, max_len: int, field: str,
                allow_newlines: bool = False) -> str | None:
    """Strip and law-check a profile text field. None/empty ->
    None (the field is cleared). Controls are refused."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProfileError(f"{field}_invalid", f"That {field} is not valid.")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ProfileError(
            f"{field}_too_long",
            f"That {field} is too long (at most {max_len} characters).")
    for ch in text:
        if ord(ch) < 0x20 and not (allow_newlines and ch in "\n\t"):
            raise ProfileError(
                f"{field}_invalid",
                f"That {field} contains characters that cannot be shown.")
        if ord(ch) == 0x7F:
            raise ProfileError(
                f"{field}_invalid",
                f"That {field} contains characters that cannot be shown.")
    return text


def validate_avatar_alt(value: object) -> str:
    """Alt text is mandatory for an avatar and must be real:
    non-empty after stripping, within the cap, no controls."""
    alt = _clean_text(value, max_len=AVATAR_ALT_MAX, field="avatar_alt")
    if alt is None:
        raise ProfileError(
            "avatar_alt_required",
            "An avatar needs alt text describing the image, "
            "so screen readers can speak it.")
    return alt


class ProfileStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    def _require_user(self, user_id: int):
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise ProfileError("no_such_user", "No such account.")
        return user

    def get_profile(self, user_id: int) -> Profile:
        self._require_user(user_id)
        row = self._conn.execute(
            "SELECT * FROM profiles WHERE user_id = ?",
            (user_id,)).fetchone()
        if row is None:
            return Profile(user_id, None, None, None, None, None)
        return Profile(
            user_id=row["user_id"], display_name=row["display_name"],
            bio=row["bio"], avatar_sha256=row["avatar_sha256"],
            avatar_content_type=row["avatar_content_type"],
            avatar_alt=row["avatar_alt"])

    def update_profile(
        self, user_id: int, *, display_name: object = None,
        bio: object = None, source_ip: str | None = None,
    ) -> Profile:
        """Set display name and/or bio (a None argument leaves
        that field as passed through the cleaner: explicit None
        clears it — callers pass the submitted form values)."""
        user = self._require_user(user_id)
        name = _clean_text(display_name, max_len=DISPLAY_NAME_MAX,
                           field="display_name")
        bio_clean = _clean_text(bio, max_len=BIO_MAX, field="bio",
                                allow_newlines=True)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO profiles (user_id, display_name, bio,"
                " updated_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                " display_name = excluded.display_name,"
                " bio = excluded.bio, updated_at = excluded.updated_at",
                (user.id, name, bio_clean, now))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.profile.update", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip, detail={"fields": "text"})
        return self.get_profile(user.id)

    def set_avatar(
        self, user_id: int, data: bytes, *, data_root: Path,
        declared_type: str | None = None, alt_text: object = None,
        source_ip: str | None = None,
    ) -> Profile:
        """Avatar upload under S-012 law + the alt-text law.

        Refusals (disguised payload, non-image, oversize, missing
        alt) store nothing and change nothing."""
        user = self._require_user(user_id)
        alt = validate_avatar_alt(alt_text)
        # S-012: size, sniff, disguise, quarantine — in that order.
        quarantine_path = save_to_quarantine(
            Path(data_root), data, declared_type=declared_type,
            policy=AVATAR_POLICY)
        # The inspected facts come from the bytes, not the caller.
        from .uploads import inspect_upload
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
                "INSERT INTO profiles (user_id, avatar_sha256,"
                " avatar_content_type, avatar_alt, updated_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                " avatar_sha256 = excluded.avatar_sha256,"
                " avatar_content_type = excluded.avatar_content_type,"
                " avatar_alt = excluded.avatar_alt,"
                " updated_at = excluded.updated_at",
                (user.id, inspected.sha256, inspected.detected_type,
                 alt, now))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.profile.update", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip, detail={"fields": "avatar"})
        return self.get_profile(user.id)


def render_profile_page(username: str, profile: Profile) -> str:
    """The profile page. Every user-controlled value passes the
    S-010 seam; the avatar <img>, when present, always carries
    its stored alt text in an escaped attribute."""
    display = profile.effective_display_name(username)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(display)} — Samverk</title></head>",
        "<body>",
        f"<h1>{escape_html_text(display)}</h1>",
        f'<p class="username">@{escape_html_text(username)}</p>',
    ]
    filename = profile.avatar_filename
    if filename is not None and profile.avatar_alt:
        src = escape_html_attr(f"/avatars/{filename}")
        alt = escape_html_attr(profile.avatar_alt)
        parts.append(f'<img class="avatar" src="{src}" alt="{alt}">')
    if profile.bio:
        bio_html = escape_html_text(profile.bio).replace("\n", "<br>\n")
        parts.append(f'<p class="bio">{bio_html}</p>')
    parts.append("</body></html>")
    return "\n".join(parts)
