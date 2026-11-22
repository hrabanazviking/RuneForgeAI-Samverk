"""First-admin creation (S-350).

A fresh instance has no accounts and no way in: registration
is a door for ordinary users, and the reserved-names law
(S-025) rightly refuses to let anyone register as the
instance itself. The first admin is therefore an operator
act, done from the command line by the person who owns the
machine:

    samverk admin create-first-admin --username NAME

- **First means first.** The command refuses whenever any
  admin already exists (`admin_exists`) — it is not a
  general admin-minting door. Ordinary accounts may already
  exist (an instance whose admin was lost is exactly the
  case this door exists for); what it will never do is make
  a *second* first admin.
- **The standing account law applies whole:** username,
  email and password are judged by S-025's own validators
  (reserved names refused, password policy, case-insensitive
  uniqueness), the password is hashed with S-004's scrypt
  through the standing seam, and the plaintext is never
  stored, printed, audited or logged — the CLI reads it from
  a hidden prompt or a named environment variable, never
  from argv.
- **The account is born active and admin:** status `active`,
  `is_admin` set, in one insert — no pending state, because
  there is nobody yet who could approve it. The act is
  audited `admin.user.create` (already in the frozen
  taxonomy) with the method named and never a credential.
- **The first sign-in home** (`FirstAdminHome` +
  `render_first_admin_home`) is the anti-Forgejo gate: the
  admin lands on a home that shows the next three things to
  do, in plain words, each one a link to the real feature:
  create a personal access token, create a repository, set
  up a mirror. A step the admin has already done is marked
  done in words (never colour alone), judged from real state
  — their tokens, their repositories, their mirrors — by
  the pure `decide_next_steps`.
- **Honest surfaces:** token creation's page is the real
  `/settings/tokens` (S-034). Repository creation has no web
  page yet; its landed door is `POST /api/v1/repos` (S-242),
  and the step links there and says so. Mirror setup has no
  standalone page either: a mirror belongs to a repository
  (S-070), so the step links to the admin's first repository
  when one exists and to the repositories door before that,
  and says a mirror is set up on its repository. No dead
  door is drawn as live; docs/FIRST_ADMIN.md records this.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import (
    AccountStore,
    RegistrationError,
    User,
    validate_email,
    validate_password,
    validate_username,
)
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text
from .passwords import hash_password
from .token_management import TOKENS_PATH

REPOSITORIES_PATH = "/api/v1/repos"


class FirstAdminError(ValueError):
    """A first-admin creation refused, clearly: `reason` is a
    stable machine-readable code and the message is safe to
    show the operator."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def decide_first_admin(admin_exists: bool) -> str | None:
    """The pure first-means-first judgement: return the
    refusal reason when a first admin may not be created,
    or None when the door stands open."""
    if admin_exists:
        return "admin_exists"
    return None


@dataclass(frozen=True)
class NextStep:
    key: str            # "token" | "repository" | "mirror"
    label: str          # the plain-words name of the thing to do
    detail: str         # one plain sentence saying what it is for
    href: str           # the real surface the step opens
    done: bool

    @property
    def state_word(self) -> str:
        return "Done" if self.done else "To do"


def decide_next_steps(
    *, has_token: bool, has_repository: bool, has_mirror: bool,
    first_repo_path: str | None,
) -> tuple[NextStep, NextStep, NextStep]:
    """The pure home judgement: exactly the three next
    things, in the order a new admin meets them, each with
    its real door and its done state judged by the caller
    from real records."""
    mirror_href = first_repo_path or REPOSITORIES_PATH
    return (
        NextStep(
            key="token",
            label="Create a personal access token",
            detail=("A token lets your scripts and your git "
                    "client sign in as you, without your "
                    "password. You will see its secret exactly "
                    "once, when you create it."),
            href=TOKENS_PATH, done=has_token),
        NextStep(
            key="repository",
            label="Create a repository",
            detail=("A repository holds one project's files "
                    "and its whole history. Creating one "
                    "starts it empty, ready for your first "
                    "push."),
            href=REPOSITORIES_PATH, done=has_repository),
        NextStep(
            key="mirror",
            label="Set up a mirror",
            detail=("A mirror keeps a copy of a repository "
                    "from somewhere else, updated from its "
                    "source. You set a mirror up on the "
                    "repository it belongs to."),
            href=mirror_href, done=has_mirror),
    )


class FirstAdminService:
    """The one door that creates the first admin."""

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

    def admin_exists(self) -> bool:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE is_admin = 1"
        ).fetchone()
        return int(row["n"]) > 0

    def create_first_admin(
        self,
        username: object,
        password: object,
        email: object = None,
        *,
        source_ip: str | None = None,
    ) -> User:
        """Create the first admin, or refuse clearly.

        Refusals: `admin_exists` when any admin already
        stands (first means first); every S-025 validation
        and collision refusal, carried through unchanged.
        The password is judged by the standing policy and
        hashed by the standing seam; it appears in no row,
        no audit detail and no message."""

        def deny(reason: str, message: str) -> FirstAdminError:
            if self._audit is not None:
                self._audit.append(
                    actor_kind="anonymous",
                    action="admin.user.create",
                    target_kind="user", outcome="denied",
                    source_ip=source_ip, detail={"reason": reason})
            return FirstAdminError(reason, message)

        refusal = decide_first_admin(self.admin_exists())
        if refusal is not None:
            raise deny(
                refusal,
                "An admin already exists on this instance; "
                "the first admin can only be created once.")
        try:
            username = validate_username(username)
            email_norm = validate_email(email)
            password = validate_password(password, username)  # type: ignore[arg-type]
        except RegistrationError as exc:
            raise deny(exc.reason, str(exc)) from None

        username_lower = username.lower()  # type: ignore[union-attr]
        if self._accounts.get_by_username(username_lower) is not None:
            raise deny("username_taken",
                       "That username is already taken.")
        email_lower = email_norm.lower() if email_norm else None
        if email_lower and self._accounts.get_by_email(email_lower) is not None:
            raise deny("email_taken",
                       "That email address is already registered.")

        now = int(self._now())
        try:
            with self._conn:  # committed before the account is answered with
                cur = self._conn.execute(
                    "INSERT INTO users (username, username_lower, email,"
                    " email_lower, password_hash, email_verified, status,"
                    " is_admin, created_at)"
                    " VALUES (?, ?, ?, ?, ?, 0, 'active', 1, ?)",
                    (username, username_lower, email_norm, email_lower,
                     hash_password(password), now))
        except sqlite3.IntegrityError:
            if self._accounts.get_by_username(username_lower) is not None:
                raise deny("username_taken",
                           "That username is already taken.") from None
            raise deny("email_taken",
                       "That email address is already registered.") from None
        user = self._accounts.get_by_id(int(cur.lastrowid))
        assert user is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="admin.user.create", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip,
                detail={"method": "cli_first_admin"})
        return user


class FirstAdminHome:
    """The first sign-in home's facts: the admin's three
    next steps, judged from their real tokens, repositories
    and mirrors."""

    def __init__(
        self,
        accounts: AccountStore,
        classic: object,
        fine: object,
        repositories: object,
        mirrors: object,
    ):
        self._accounts = accounts
        self._classic = classic
        self._fine = fine
        self._repos = repositories
        self._mirrors = mirrors

    def steps_for(self, user_id: int) -> tuple[NextStep, ...]:
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise FirstAdminError("no_such_user", "No such account.")
        has_token = bool(self._classic.list_tokens(user_id)) or bool(
            self._fine.list_tokens(user_id))
        owned = self._repos.list_for_owner(user.username)
        has_mirror = any(
            self._mirrors.is_mirror(user.username, repo.name)
            for repo in owned)
        first_repo_path = (
            f"/{user.username}/{owned[0].name}" if owned else None)
        return decide_next_steps(
            has_token=has_token, has_repository=bool(owned),
            has_mirror=has_mirror, first_repo_path=first_repo_path)


def render_first_admin_home(
    username: str, steps: tuple[NextStep, ...] | list[NextStep],
) -> str:
    """The home the first admin lands on: a welcome in plain
    words and exactly the three next things to do, each a
    link to its real surface and each carrying its state in
    words. Every value is escaped through S-010."""
    who = escape_html_text(username)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Home — {who} — Samverk</title></head>",
        "<body>",
        f"<h1>Welcome, {who}</h1>",
        "<p>This is your instance, and you are its first "
        "admin. Three things will get you started:</p>",
        "<ol>",
    ]
    for step in steps:
        parts.append(
            f'<li><a href="{escape_html_attr(step.href)}">'
            f"{escape_html_text(step.label)}</a> "
            f"— {escape_html_text(step.detail)} "
            f"({escape_html_text(step.state_word)})</li>")
    parts += ["</ol>", "</body></html>"]
    return "\n".join(parts)
