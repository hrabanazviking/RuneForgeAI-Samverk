"""Site settings (S-352).

Roadmap S-352: **instance name and description, registration
mode (open / invite / closed), default repo visibility,
upload and repo size limits.**

Where these live, and why: S-346's configuration layer does
not exist on this base (the campaign stands at S-343), and
the boot configuration in samverk/config.py is explicitly
*boot-only* -- the facts that must exist before the database
can open. Everything else, its own docstring says, lives in
the database settings table. So site settings are a sibling
module over that standing ``settings`` table (the same home
S-068's instance quota default, S-038's API defences and the
two-factor policy already use): **no migration** (schema
stays 139) and **no new taxonomy event** (138 stand; changes
ride the standing ``admin.settings.change``).

Settings must take effect, not just be stored:

- **Registration mode gates real signups.** AccountStore
  accepts this service as its optional ``site_settings``
  seam; when wired, ``register`` consults
  ``check_registration`` before creating anything. Closed
  refuses everyone; invite refuses anyone without a valid
  single-use invite code (an admin mints codes here; only
  SHA-256 hashes are stored, a code is consumed by the
  signup it admits); open admits as before. Unwired stores
  keep the historic open behaviour, so no standing caller
  changes meaning.
- **Default repo visibility applies to real creation.**
  RepositoryStore accepts the same seam; a creation that
  does not name a visibility is born with the site default
  (the API door passes an unnamed visibility through as
  None, so API creations follow the site default too).
  An explicitly named visibility always wins.
- **Upload limit refuses real oversize uploads.**
  ``upload_policy`` returns S-012's UploadPolicy carrying
  the site's cap, and ``enforce_upload`` runs S-012's own
  inspection under it, answering an oversize upload with a
  plain-words refusal naming the size and the limit.
- **Repo size limit is the instance quota default.**
  Setting it writes S-068's standing
  ``repo_quota_default_bytes`` key in the same transaction,
  so QuotaService's receive-time enforcement -- per-repo
  quota wins, instance default next -- enforces exactly
  the number the admin set here. Clearing it clears both.

Only instance admins change site settings or mint invite
codes; every change is audit-logged ``admin.settings.change``
with the keys and the from/to values named. The judgements
(``decide_registration``, ``decide_upload_size``,
``parse_site_settings``) are pure.
"""
from __future__ import annotations
import hashlib, json, secrets, sqlite3, time
from collections.abc import Callable
from dataclasses import dataclass
from .accounts import AccountStore
from .audit import AuditLog
from .escaping import escape_html_text
from .repo_quotas import DEFAULT_QUOTA_SETTING
from .repositories import VISIBILITIES
from .uploads import UploadPolicy, UploadRejected, inspect_upload

KEY_INSTANCE_NAME = "site.instance_name"
KEY_INSTANCE_DESCRIPTION = "site.instance_description"
KEY_REGISTRATION_MODE = "site.registration_mode"
KEY_DEFAULT_VISIBILITY = "site.default_repo_visibility"
KEY_UPLOAD_MAX_BYTES = "site.upload_max_bytes"
KEY_REPO_SIZE_LIMIT = "site.repo_size_limit_bytes"
KEY_INVITE_HASHES = "site.invite_code_hashes"
SETTING_KEYS = (KEY_INSTANCE_NAME, KEY_INSTANCE_DESCRIPTION, KEY_REGISTRATION_MODE, KEY_DEFAULT_VISIBILITY, KEY_UPLOAD_MAX_BYTES, KEY_REPO_SIZE_LIMIT)
REGISTRATION_MODES = frozenset({"open", "invite", "closed"})
DEFAULT_INSTANCE_NAME = "Samverk"
DEFAULT_INSTANCE_DESCRIPTION = ""
DEFAULT_REGISTRATION_MODE = "open"
DEFAULT_REPO_VISIBILITY = "private"
DEFAULT_UPLOAD_MAX_BYTES = 10 * 1024 * 1024
UPLOAD_MAX_BYTES_CAP = 2 * 1024 * 1024 * 1024
NAME_MAX = 80
DESCRIPTION_MAX = 500
_UNSET = object()

class SiteSettingsError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message); self.reason = reason

@dataclass(frozen=True)
class SiteSettings:
    instance_name: str = DEFAULT_INSTANCE_NAME
    instance_description: str = DEFAULT_INSTANCE_DESCRIPTION
    registration_mode: str = DEFAULT_REGISTRATION_MODE
    default_repo_visibility: str = DEFAULT_REPO_VISIBILITY
    upload_max_bytes: int = DEFAULT_UPLOAD_MAX_BYTES
    repo_size_limit_bytes: int | None = None

@dataclass(frozen=True)
class RegistrationDecision:
    allowed: bool; mode: str; reason: str; message: str

@dataclass(frozen=True)
class UploadSizeDecision:
    allowed: bool; size_bytes: int; limit_bytes: int; message: str

def decide_registration(mode: str, invite_valid: bool) -> RegistrationDecision:
    """Pure: may a signup proceed under *mode*? Invite mode
    admits exactly the holder of a valid invite code."""
    if mode == "open":
        return RegistrationDecision(True, mode, "registration_open", "Registration is open on this instance.")
    if mode == "closed":
        return RegistrationDecision(False, mode, "registration_closed", "Registration is closed on this instance. Ask an instance admin if you need an account.")
    if mode == "invite":
        if invite_valid:
            return RegistrationDecision(True, mode, "registration_invite_accepted", "Registration is by invitation; this invite code is accepted.")
        return RegistrationDecision(False, mode, "registration_invite_required", "Registration on this instance is by invitation only. Enter a valid invite code, or ask an instance admin for one.")
    return RegistrationDecision(False, str(mode), "registration_mode_invalid", f"The instance registration mode {mode!r} is not a lawful mode.")

def decide_upload_size(size_bytes: int, limit_bytes: int) -> UploadSizeDecision:
    """Pure: does an upload of *size_bytes* fit the limit?"""
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise SiteSettingsError("upload_size_invalid", "An upload size is a whole number of bytes, zero or more.")
    if size_bytes <= limit_bytes:
        return UploadSizeDecision(True, size_bytes, limit_bytes, f"This upload is {size_bytes} bytes; the limit is {limit_bytes} bytes.")
    return UploadSizeDecision(False, size_bytes, limit_bytes, f"This upload is {size_bytes} bytes, which is over this instance's upload limit of {limit_bytes} bytes. Make the file smaller, or ask an instance admin to raise the limit.")

def _plain_text(value: object, reason: str, message: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise SiteSettingsError(reason, message)
    text = value.strip()
    if len(text) > max_len or any(ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise SiteSettingsError(reason, message)
    return text

def _whole(value: object, reason: str, message: str) -> int:
    if isinstance(value, bool):
        raise SiteSettingsError(reason, message)
    try:
        number = int(str(value).strip()) if isinstance(value, str) else int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise SiteSettingsError(reason, message) from None
    if isinstance(value, float) and value != number:
        raise SiteSettingsError(reason, message)
    return number

def parse_site_settings(values: dict) -> SiteSettings:
    """Pure: judge stored setting strings into a SiteSettings.
    Absent keys take the defaults; a stored value that cannot
    be read is a loud refusal, never a silent default."""
    name = values.get(KEY_INSTANCE_NAME, DEFAULT_INSTANCE_NAME)
    name = _plain_text(name, "settings_invalid", "The stored instance name is not lawful plain text.", NAME_MAX)
    if not name:
        raise SiteSettingsError("settings_invalid", "The stored instance name is empty.")
    description = _plain_text(values.get(KEY_INSTANCE_DESCRIPTION, DEFAULT_INSTANCE_DESCRIPTION), "settings_invalid", "The stored instance description is not lawful plain text.", DESCRIPTION_MAX)
    mode = values.get(KEY_REGISTRATION_MODE, DEFAULT_REGISTRATION_MODE)
    if mode not in REGISTRATION_MODES:
        raise SiteSettingsError("settings_invalid", f"The stored registration mode {mode!r} is not open, invite, or closed.")
    visibility = values.get(KEY_DEFAULT_VISIBILITY, DEFAULT_REPO_VISIBILITY)
    if visibility not in VISIBILITIES:
        raise SiteSettingsError("settings_invalid", f"The stored default repo visibility {visibility!r} is not public, internal, or private.")
    upload = _whole(values.get(KEY_UPLOAD_MAX_BYTES, DEFAULT_UPLOAD_MAX_BYTES), "settings_invalid", "The stored upload limit is not a whole number of bytes.")
    if upload < 1 or upload > UPLOAD_MAX_BYTES_CAP:
        raise SiteSettingsError("settings_invalid", "The stored upload limit is outside the lawful range.")
    raw_limit = values.get(KEY_REPO_SIZE_LIMIT)
    if raw_limit is None:
        raw_limit = values.get(DEFAULT_QUOTA_SETTING)
    limit = None
    if raw_limit is not None and str(raw_limit).strip() != "":
        limit = _whole(raw_limit, "settings_invalid", "The stored repo size limit is not a whole number of bytes.")
        if limit < 0:
            raise SiteSettingsError("settings_invalid", "The stored repo size limit is negative.")
    return SiteSettings(instance_name=name, instance_description=description, registration_mode=str(mode), default_repo_visibility=str(visibility), upload_max_bytes=upload, repo_size_limit_bytes=limit)

def _hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()

class SiteSettingsService:
    def __init__(self, conn: sqlite3.Connection, accounts: AccountStore, audit: AuditLog | None = None, time_fn: Callable[[], float] = time.time):
        self._conn = conn; self._accounts = accounts; self._audit = audit; self._now = time_fn
    # -- reading ------------------------------------------------
    def _values(self) -> dict:
        rows = self._conn.execute("SELECT key, value FROM settings WHERE key LIKE 'site.%' OR key = ?", (DEFAULT_QUOTA_SETTING,)).fetchall()
        return {row["key"]: row["value"] for row in rows}
    def get_settings(self) -> SiteSettings:
        return parse_site_settings(self._values())
    def registration_mode(self) -> str:
        return self.get_settings().registration_mode
    def default_repo_visibility(self) -> str:
        return self.get_settings().default_repo_visibility
    def upload_max_bytes(self) -> int:
        return self.get_settings().upload_max_bytes
    def repo_size_limit_bytes(self) -> int | None:
        return self.get_settings().repo_size_limit_bytes
    # -- admin gate ----------------------------------------------
    def _require_admin(self, actor_user_id: int):
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise SiteSettingsError("no_such_user", "No such account.")
        if not actor.is_admin:
            raise SiteSettingsError("permission_denied", "Only an instance admin can change site settings.")
        return actor
    # -- writing ---------------------------------------------------
    def update_settings(self, actor_user_id: int, *, instance_name=_UNSET, instance_description=_UNSET, registration_mode=_UNSET, default_repo_visibility=_UNSET, upload_max_bytes=_UNSET, repo_size_limit_bytes=_UNSET, source_ip: str | None = None) -> SiteSettings:
        actor = self._require_admin(actor_user_id)
        current = self.get_settings()
        new = SiteSettings(
            instance_name=current.instance_name if instance_name is _UNSET else _plain_text(instance_name, "instance_name_invalid", f"The instance name is plain text of at most {NAME_MAX} characters.", NAME_MAX),
            instance_description=current.instance_description if instance_description is _UNSET else _plain_text(instance_description, "instance_description_invalid", f"The instance description is plain text of at most {DESCRIPTION_MAX} characters.", DESCRIPTION_MAX),
            registration_mode=current.registration_mode if registration_mode is _UNSET else registration_mode,
            default_repo_visibility=current.default_repo_visibility if default_repo_visibility is _UNSET else default_repo_visibility,
            upload_max_bytes=current.upload_max_bytes if upload_max_bytes is _UNSET else _whole(upload_max_bytes, "upload_limit_invalid", "The upload limit is a whole number of bytes."),
            repo_size_limit_bytes=current.repo_size_limit_bytes if repo_size_limit_bytes is _UNSET else (None if repo_size_limit_bytes is None else _whole(repo_size_limit_bytes, "repo_size_limit_invalid", "The repo size limit is a whole number of bytes.")))
        if not new.instance_name:
            raise SiteSettingsError("instance_name_invalid", "The instance name must not be empty.")
        if new.registration_mode not in REGISTRATION_MODES:
            raise SiteSettingsError("registration_mode_invalid", "Registration mode is 'open', 'invite', or 'closed'.")
        if new.default_repo_visibility not in VISIBILITIES:
            raise SiteSettingsError("visibility_invalid", "Default repo visibility is 'public', 'internal', or 'private'.")
        if new.upload_max_bytes < 1 or new.upload_max_bytes > UPLOAD_MAX_BYTES_CAP:
            raise SiteSettingsError("upload_limit_invalid", f"The upload limit is between 1 and {UPLOAD_MAX_BYTES_CAP} bytes.")
        if new.repo_size_limit_bytes is not None and new.repo_size_limit_bytes < 0:
            raise SiteSettingsError("repo_size_limit_invalid", "The repo size limit is zero or more bytes.")
        rows = [(KEY_INSTANCE_NAME, new.instance_name), (KEY_INSTANCE_DESCRIPTION, new.instance_description), (KEY_REGISTRATION_MODE, new.registration_mode), (KEY_DEFAULT_VISIBILITY, new.default_repo_visibility), (KEY_UPLOAD_MAX_BYTES, str(new.upload_max_bytes))]
        changes = {}
        for key, old, newval in ((KEY_INSTANCE_NAME, current.instance_name, new.instance_name), (KEY_INSTANCE_DESCRIPTION, current.instance_description, new.instance_description), (KEY_REGISTRATION_MODE, current.registration_mode, new.registration_mode), (KEY_DEFAULT_VISIBILITY, current.default_repo_visibility, new.default_repo_visibility), (KEY_UPLOAD_MAX_BYTES, current.upload_max_bytes, new.upload_max_bytes), (KEY_REPO_SIZE_LIMIT, current.repo_size_limit_bytes, new.repo_size_limit_bytes)):
            if old != newval: changes[key] = {"from": old, "to": newval}
        with self._conn:
            self._conn.executemany("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", rows)
            if new.repo_size_limit_bytes is None:
                self._conn.execute("DELETE FROM settings WHERE key IN (?, ?)", (KEY_REPO_SIZE_LIMIT, DEFAULT_QUOTA_SETTING))
            else:
                self._conn.executemany("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", [(KEY_REPO_SIZE_LIMIT, str(new.repo_size_limit_bytes)), (DEFAULT_QUOTA_SETTING, str(new.repo_size_limit_bytes))])
        if self._audit is not None and changes:
            self._audit.append(actor_kind="user", actor_id=actor.id, action="admin.settings.change", target_kind="instance", target_id="site", outcome="success", source_ip=source_ip, detail={"keys": sorted(changes), "changes": changes})
        return self.get_settings()
    # -- invite codes ----------------------------------------------
    def _invite_hashes(self) -> list[str]:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (KEY_INVITE_HASHES,)).fetchone()
        if row is None: return []
        try: data = json.loads(row["value"])
        except ValueError: raise SiteSettingsError("settings_invalid", "The stored invite codes cannot be read.") from None
        return [str(h) for h in data] if isinstance(data, list) else []
    def create_invite_code(self, actor_user_id: int, *, source_ip: str | None = None) -> str:
        actor = self._require_admin(actor_user_id)
        code = secrets.token_hex(8)
        hashes = self._invite_hashes() + [_hash_code(code)]
        with self._conn:
            self._conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (KEY_INVITE_HASHES, json.dumps(hashes)))
        if self._audit is not None:
            self._audit.append(actor_kind="user", actor_id=actor.id, action="admin.settings.change", target_kind="instance", target_id="site", outcome="success", source_ip=source_ip, detail={"keys": [KEY_INVITE_HASHES], "action": "invite_code_create"})
        return code
    def invite_code_valid(self, code: object) -> bool:
        if not isinstance(code, str) or not code.strip(): return False
        return _hash_code(code) in self._invite_hashes()
    def consume_invite_code(self, code: object) -> bool:
        if not self.invite_code_valid(code): return False
        hashes = self._invite_hashes(); hashes.remove(_hash_code(str(code)))
        with self._conn:
            self._conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (KEY_INVITE_HASHES, json.dumps(hashes)))
        return True
    # -- enforcement seams ------------------------------------------
    def check_registration(self, invite_code: object = None) -> RegistrationDecision:
        mode = self.registration_mode()
        valid = self.invite_code_valid(invite_code) if mode == "invite" else False
        return decide_registration(mode, valid)
    def upload_policy(self) -> UploadPolicy:
        return UploadPolicy(max_bytes=self.upload_max_bytes())
    def check_upload_size(self, size_bytes: int) -> UploadSizeDecision:
        return decide_upload_size(size_bytes, self.upload_max_bytes())
    def enforce_upload(self, data: bytes, declared_type: str | None = None):
        """Run S-012's inspection under the site cap; an oversize
        upload is refused in plain words naming size and limit."""
        decision = self.check_upload_size(len(data))
        if not decision.allowed:
            raise SiteSettingsError("upload_too_large", decision.message)
        try:
            return inspect_upload(data, declared_type=declared_type, policy=self.upload_policy())
        except UploadRejected as exc:
            if exc.reason == "too_large":
                raise SiteSettingsError("upload_too_large", decision.message) from None
            raise

def render_site_settings_page(settings: SiteSettings) -> str:
    limit = "No limit" if settings.repo_size_limit_bytes is None else f"{settings.repo_size_limit_bytes} bytes"
    return ("<section class=\"site-settings\">\n<h1>Site settings</h1>\n"
        f"<p class=\"instance-name\">{escape_html_text(settings.instance_name)}</p>\n"
        f"<p class=\"instance-description\">{escape_html_text(settings.instance_description)}</p>\n"
        f"<p>Registration: {escape_html_text(settings.registration_mode)}</p>\n"
        f"<p>Default repository visibility: {escape_html_text(settings.default_repo_visibility)}</p>\n"
        f"<p>Upload limit: {settings.upload_max_bytes} bytes</p>\n"
        f"<p>Repository size limit: {escape_html_text(limit)}</p>\n</section>")
