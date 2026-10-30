"""Accounts and registration (S-025).

The users table and the one door that creates rows in it.

- **Username law.** 3-39 characters, ASCII letters / digits /
  hyphen / underscore, starting with a letter or digit and not
  ending with a hyphen or underscore. A username is also an owner
  name under S-013, so it must pass that law too (which refuses
  Windows device names and traversal shapes on every platform).
  Uniqueness is **case-insensitive**: the display case is kept as
  typed, the canonical ``username_lower`` is what collides, so
  ``Volmarr`` and ``volmarr`` are one account, never two.
- **Reserved names.** Instance machinery and impersonation bait —
  ``admin``, ``root``, ``support``, ``samverk``, ``system``,
  ``api``, ``www``, and kin — are refused at registration with a
  clear reason, whoever asks. The set lives here, in one place,
  and S-046 (lookalike defence) builds on it.
- **Email is optional-but-supported.** No email is a lawful
  account (a sovereign local instance must not demand one). An
  email that *is* given must be plausibly shaped (S-021's parser,
  plus a lawful local part) and is unique case-insensitively
  among accounts that have one.
- **Password policy** is study 07 §3.3 as code: minimum 10
  characters, maximum 128, no composition theatre, screened
  against a small bundled common-password list plus the username
  itself. Hashing is S-004's scrypt; the plaintext never persists.
- **Abuse friction** is S-021's `SignupGuard`, consulted when the
  caller supplies one (with an address to charge it against);
  a throttled or domain-refused attempt creates nothing.
- **Audit:** success is ``auth.signup.success``, every refusal is
  ``auth.signup.denied`` with its reason — when an AuditLog is
  supplied. Creation commits before the account is answered with
  (commit-before-answer), so a returned id is immediately usable.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .audit import AuditLog
from .passwords import hash_password
from .repo_paths import RepoPathError, validate_owner_name
from .signup_friction import SignupGuard, domain_of_email

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 39
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128

RESERVED_USERNAMES = frozenset({
    "admin", "administrator", "root", "system", "support",
    "help", "helpdesk", "samverk", "samtal", "api", "www",
    "mail", "email", "login", "logout", "register", "signup",
    "settings", "account", "accounts", "user", "users",
    "moderator", "mod", "staff", "official", "security",
    "abuse", "postmaster", "webmaster", "noreply", "no-reply",
    "anonymous", "guest", "null", "undefined", "deleted",
})

# A small bundled screen, per study 07: an offline corpus, never a
# breach-API call. Operators may extend it; it is a floor, not a
# claim of completeness.
COMMON_PASSWORDS = frozenset({
    "password", "password1", "password123", "1234567890",
    "qwertyuiop", "letmein123", "iloveyou12", "admin12345",
    "welcome123", "changeme12", "samverk123", "123456789a",
})

_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*[A-Za-z0-9]$|^[A-Za-z0-9]$")
_EMAIL_LOCAL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$")


class RegistrationError(ValueError):
    """A registration refused, clearly: `reason` is a stable
    machine-readable code and the message is safe to show the
    person who tried — it names the rule, never another account's
    private facts beyond the collision itself."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class User:
    id: int
    username: str          # display case, as registered
    username_lower: str    # canonical lookup key
    email: str | None
    email_verified: bool
    status: str            # active | pending_verification | pending_approval
    is_admin: bool
    created_at: int


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"], username=row["username"],
        username_lower=row["username_lower"], email=row["email"],
        email_verified=bool(row["email_verified"]),
        status=row["status"], is_admin=bool(row["is_admin"]),
        created_at=row["created_at"])


def validate_username(username: object) -> str:
    """Return the username as typed if lawful, else raise
    RegistrationError with a clear reason."""
    if not isinstance(username, str) or not username:
        raise RegistrationError(
            "username_required", "Choose a username.")
    if len(username) < USERNAME_MIN_LENGTH:
        raise RegistrationError(
            "username_too_short",
            f"Usernames are at least {USERNAME_MIN_LENGTH} characters.")
    if len(username) > USERNAME_MAX_LENGTH:
        raise RegistrationError(
            "username_too_long",
            f"Usernames are at most {USERNAME_MAX_LENGTH} characters.")
    if not _USERNAME_RE.match(username) or ".." in username:
        raise RegistrationError(
            "username_bad_characters",
            "Usernames use letters, digits, hyphens and underscores, "
            "start with a letter or digit, and do not end with a "
            "hyphen or underscore.")
    try:
        validate_owner_name(username)
    except RepoPathError:
        raise RegistrationError(
            "username_bad_characters",
            "That username is not a lawful account name.") from None
    if username.lower() in RESERVED_USERNAMES:
        raise RegistrationError(
            "username_reserved",
            "That username is reserved for the instance itself.")
    return username


def validate_email(email: object) -> str | None:
    """Normalise an optional email: None/empty -> None; a given
    address must be plausibly shaped, and is returned stripped
    with its domain lowercased (the local part keeps its case)."""
    if email is None:
        return None
    if not isinstance(email, str):
        raise RegistrationError("email_invalid", "That email address is not valid.")
    email = email.strip()
    if not email:
        return None
    local, at, domain = email.partition("@")
    if (not at or not local or len(local) > 64
            or not _EMAIL_LOCAL_RE.match(local)
            or local.startswith(".") or local.endswith(".")
            or ".." in local
            or domain_of_email(email) is None):
        raise RegistrationError("email_invalid", "That email address is not valid.")
    return f"{local}@{domain.lower()}"


def validate_password(password: object, username: str) -> str:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
        raise RegistrationError(
            "password_too_short",
            f"Passwords are at least {PASSWORD_MIN_LENGTH} characters.")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise RegistrationError(
            "password_too_long",
            f"Passwords are at most {PASSWORD_MAX_LENGTH} characters.")
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or lowered == username.lower():
        raise RegistrationError(
            "password_too_common",
            "That password is too common or too close to the username; "
            "choose another.")
    return password


class AccountStore:
    """Registration plus the account lookups later slices use."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        audit: AuditLog | None = None,
        signup_guard: SignupGuard | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._audit = audit
        self._guard = signup_guard
        self._now = time_fn

    # -- lookups -------------------------------------------------
    def get_by_id(self, user_id: int) -> User | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None

    def get_by_username(self, username: str) -> User | None:
        """Case-insensitive: any case finds the one account."""
        if not isinstance(username, str):
            return None
        row = self._conn.execute(
            "SELECT * FROM users WHERE username_lower = ?",
            (username.strip().lower(),)).fetchone()
        return _row_to_user(row) if row else None

    def get_by_email(self, email: str) -> User | None:
        if not isinstance(email, str):
            return None
        row = self._conn.execute(
            "SELECT * FROM users WHERE email_lower = ?",
            (email.strip().lower(),)).fetchone()
        return _row_to_user(row) if row else None

    def password_hash_for(self, user_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (user_id,)).fetchone()
        return row["password_hash"] if row else None

    def set_password_hash(self, user_id: int, password_hash: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (password_hash, user_id))

    def set_status(self, user_id: int, status: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE users SET status = ? WHERE id = ?",
                (status, user_id))

    def set_email_verified(self, user_id: int, verified: bool = True) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE users SET email_verified = ? WHERE id = ?",
                (1 if verified else 0, user_id))

    # -- registration ---------------------------------------------
    def register(
        self,
        username: object,
        password: object,
        email: object = None,
        *,
        source_ip: str | None = None,
        verification_mode: str = "none",
    ) -> User:
        """Create an account, or raise RegistrationError clearly.

        verification_mode (S-026's gate, consumed here):
        ``none`` — active at once; ``smtp`` — an account with an
        email waits pending_verification for its token, one
        without waits pending_approval (it cannot receive a
        token); ``operator`` — every account waits
        pending_approval for an operator's word.
        """
        if verification_mode not in ("none", "smtp", "operator"):
            raise ValueError(f"unknown verification_mode {verification_mode!r}")

        def deny(reason: str, message: str) -> RegistrationError:
            if self._audit is not None:
                self._audit.append(
                    actor_kind="anonymous", action="auth.signup.denied",
                    target_kind="user", outcome="denied",
                    source_ip=source_ip, detail={"reason": reason})
            return RegistrationError(reason, message)

        try:
            username = validate_username(username)
            email_norm = validate_email(email)
            password = validate_password(password, username)  # type: ignore[arg-type]
        except RegistrationError as exc:
            raise deny(exc.reason, str(exc)) from None

        if self._guard is not None and source_ip is not None and email_norm:
            decision = self._guard.check(source_ip, email_norm)
            if not decision.allowed:
                raise deny(
                    f"signup_{decision.reason}",
                    "Too many signup attempts just now; try again later."
                    if decision.reason == "throttled" else
                    "That email domain is not accepted on this instance.")

        username_lower = username.lower()  # type: ignore[union-attr]
        if self.get_by_username(username_lower) is not None:
            raise deny("username_taken",
                       "That username is already taken.")
        email_lower = email_norm.lower() if email_norm else None
        if email_lower and self.get_by_email(email_lower) is not None:
            raise deny("email_taken",
                       "That email address is already registered.")

        if verification_mode == "operator":
            status = "pending_approval"
        elif verification_mode == "smtp":
            status = "pending_verification" if email_norm else "pending_approval"
        else:
            status = "active"

        now = int(self._now())
        try:
            with self._conn:  # committed before the account is answered with
                cur = self._conn.execute(
                    "INSERT INTO users (username, username_lower, email,"
                    " email_lower, password_hash, email_verified, status,"
                    " is_admin, created_at) VALUES (?, ?, ?, ?, ?, 0, ?, 0, ?)",
                    (username, username_lower, email_norm, email_lower,
                     hash_password(password), status, now))
        except sqlite3.IntegrityError:
            # A race lost against the UNIQUE indexes is still just a
            # collision, answered clearly, never a 500.
            if self.get_by_username(username_lower) is not None:
                raise deny("username_taken",
                           "That username is already taken.") from None
            raise deny("email_taken",
                       "That email address is already registered.") from None
        user = self.get_by_id(int(cur.lastrowid))
        assert user is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.signup.success", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip, detail={"method": "open"})
        return user
