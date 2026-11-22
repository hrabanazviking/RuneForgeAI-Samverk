"""Admin panel (S-351).

The instance admin's one desk for users, organizations,
and repositories — searchable from one box, with every
destructive act sudo-gated and audit-logged.

- **Admins only.** Every method first judges the actor
  through S-004's account store: a missing account is
  ``no_such_user`` and a non-admin is ``not_admin``, and
  nothing — not even a listing — is answered before that
  judgement passes. Destructive attempts by non-admins
  are additionally witnessed in the audit log under the
  attempted action's own event with outcome ``denied``
  (when an audit log is wired). Read refusals have no
  event in the standing taxonomy, so — like S-198's
  instance audit view — they are refused plainly and
  not witnessed; no event was invented for them.
- **One search box, three subjects.** `search` matches
  one free-text query against users (username and
  email), organizations (name, display name, bio), and
  repositories (owner, name, description): every term
  must hit at least one field of a subject (AND across
  terms, the Part X composition law), judged by the
  pure `matches_query`. This is the *admin* desk, so
  it deliberately differs from S-211's public people
  search in two ways: accounts in every status are
  listed (a suspended account the public cannot find
  is exactly the one an admin must), and email is a
  search field (admins already see the address on the
  row; the S-211 law guards the *public* directory,
  which is untouched). Empty sections answer with an
  honest empty state, in the page and in the result.
- **Destructive acts are sudo-gated, without
  exception.** Create, suspend, delete (user, repo,
  org), and role change all pass `_gate_destructive`
  before anything executes: the panel must hold an
  audit log (else ``audit_required`` — an unaudited
  destructive action is impossible by construction,
  not by discipline) and the acting admin must hold a
  fresh S-036 sudo grant on the calling session (else
  ``sudo_required``, witnessed ``denied``). Only then
  is the act's authorization appended to the audit log
  — *before* the seam executes — under the standing
  taxonomy event (`admin.user.create`,
  `admin.user.suspend`, `admin.user.delete`,
  `admin.user.role_change`, and the seams' own events
  for repo/org deletion), with detail
  ``{"via": "admin_panel", "phase": "authorized"}``;
  the executing seam then adds its own witness entry,
  so every destructive act carries two: who authorized
  it at this desk, and that it landed. No new taxonomy
  event and no migration: schema 139, taxonomy 138
  stand.
- **The seams keep their laws.** Suspension is
  S-044's `AccountSuspension` (reason required, no
  self-suspension, sessions revoked, content hidden
  not deleted). User deletion is S-043's process
  (typed confirmation, 7-day grace, tombstone) — the
  panel supplies a re-auth verifier bound to the
  *acting admin's* fresh grant on the admin's session,
  since S-043's verifier answers "is this act freshly
  re-authenticated?" and the re-authentication an
  admin act can honestly claim is the admin's own.
  Repo deletion stays S-056 owner-only and org
  deletion S-199 owner-only: an instance admin who
  does not own the repo/org is refused by the seam's
  own law, exactly as S-199 documents for site admins
  — the panel invents no bypass. Unsuspend is
  restorative, not destructive: admin-gated and
  audit-logged through S-044, but not sudo-gated.
- **Role change guards.** Promoting is free; demoting
  refuses ``cannot_demote_self`` for the acting admin
  and ``last_admin`` when the target is the instance's
  last remaining admin, so the panel can never lock
  the instance out of itself.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .account_deletion import AccountDeletion, PendingDeletion
from .account_suspension import AccountSuspension, SuspensionRecord
from .accounts import (
    AccountStore,
    RegistrationError,
    User,
    validate_email,
    validate_password,
    validate_username,
)
from .audit import AuditLog
from .escaping import escape_html_text
from .org_deletion import OrgDeletionStore, PendingOrgDeletion
from .organization_members import OrgMembershipStore
from .organizations import Organization, OrganizationStore
from .repo_deletion import PendingRepoDeletion, RepoDeletion
from .repositories import Repository, RepositoryStore
from .sudo_mode import SudoMode

QUERY_MAX = 200
LIMIT_MAX = 200

# The panel's action vocabulary. `DESTRUCTIVE_ACTIONS`
# is the set that must pass the sudo + audit gate;
# `AUDIT_EVENT_FOR` names the standing taxonomy event
# each action is witnessed under (no new events).
ACTION_CREATE_USER = "create_user"
ACTION_SUSPEND_USER = "suspend_user"
ACTION_UNSUSPEND_USER = "unsuspend_user"
ACTION_DELETE_USER = "delete_user"
ACTION_SET_ADMIN = "set_admin"
ACTION_DELETE_REPO = "delete_repo"
ACTION_DELETE_ORG = "delete_org"

DESTRUCTIVE_ACTIONS = frozenset({
    ACTION_CREATE_USER, ACTION_SUSPEND_USER, ACTION_DELETE_USER,
    ACTION_SET_ADMIN, ACTION_DELETE_REPO, ACTION_DELETE_ORG,
})

AUDIT_EVENT_FOR = {
    ACTION_CREATE_USER: "admin.user.create",
    ACTION_SUSPEND_USER: "admin.user.suspend",
    ACTION_UNSUSPEND_USER: "admin.user.unsuspend",
    ACTION_DELETE_USER: "admin.user.delete",
    ACTION_SET_ADMIN: "admin.user.role_change",
    ACTION_DELETE_REPO: "repo.settings.change",
    ACTION_DELETE_ORG: "auth.organization.update",
}


class AdminPanelError(ValueError):
    """A panel act refused, clearly: `reason` is a stable
    machine-readable code and the message is safe to show
    the person who tried."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


# -- pure judgements ---------------------------------------------------


def normalize_query(query: object) -> str:
    """Clean one search-box query, or refuse it:
    non-text, control characters, and over-long queries
    are `query_invalid` (fail closed, the S-211 law —
    a mangled query is never silently widened)."""
    if query is None:
        return ""
    if not isinstance(query, str):
        raise AdminPanelError("query_invalid", "That search is not text.")
    text = query.strip()
    if len(text) > QUERY_MAX or any(ord(c) < 32 for c in text):
        raise AdminPanelError("query_invalid", "That search is not usable.")
    return text


def matches_query(fields: Iterable[object], query: object) -> bool:
    """True when every term of the (already normalized)
    query appears, case-insensitively, in at least one
    of the subject's fields. An empty query matches
    every subject (the unfiltered desk)."""
    text = normalize_query(query)
    if not text:
        return True
    haystacks = [str(f).lower() for f in fields if f]
    return all(
        any(term in hay for hay in haystacks)
        for term in text.lower().split())


def is_destructive_action(action: object) -> bool:
    return isinstance(action, str) and action in DESTRUCTIVE_ACTIONS


def audit_event_for(action: object) -> str | None:
    if not isinstance(action, str):
        return None
    return AUDIT_EVENT_FOR.get(action)


# -- rows ----------------------------------------------------------------


@dataclass(frozen=True)
class AdminUserRow:
    user: User
    repo_count: int


@dataclass(frozen=True)
class AdminOrgRow:
    org: Organization
    member_count: int
    repo_count: int


@dataclass(frozen=True)
class AdminRepoRow:
    repo: Repository


@dataclass(frozen=True)
class PanelSearchResults:
    query: str
    users: list[AdminUserRow] = field(default_factory=list)
    orgs: list[AdminOrgRow] = field(default_factory=list)
    repos: list[AdminRepoRow] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.users) + len(self.orgs) + len(self.repos)

    @property
    def headline(self) -> str:
        if not self.query:
            return (f"{len(self.users)} users, {len(self.orgs)} "
                    f"organizations, {len(self.repos)} repositories")
        return (f"{self.total} matches for \u201c{self.query}\u201d: "
                f"{len(self.users)} users, {len(self.orgs)} "
                f"organizations, {len(self.repos)} repositories")


@dataclass(frozen=True)
class PanelOverview:
    users: int
    suspended: int
    admins: int
    orgs: int
    repos: int


# -- the service ---------------------------------------------------------


class AdminPanel:
    def __init__(
        self,
        conn: sqlite3.Connection,
        data_root: Path,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        sudo: SudoMode | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._audit = audit
        self._sudo = sudo
        self._now = time_fn
        self._repos = RepositoryStore(conn, self._data_root, accounts)
        self._orgs = OrganizationStore(conn, accounts, audit,
                                       time_fn=time_fn)
        self._members = OrgMembershipStore(conn, accounts, audit,
                                           time_fn=time_fn)
        from .sessions import SessionStore
        self._sessions = SessionStore(conn, time_fn=time_fn)
        self._suspension = AccountSuspension(
            conn, accounts, self._sessions, audit, time_fn=time_fn)
        self._deletion = AccountDeletion(conn, accounts, audit,
                                          time_fn=time_fn)
        self._repo_deletion = RepoDeletion(
            conn, self._data_root, accounts, self._repos, audit,
            time_fn=time_fn)
        self._org_deletion = OrgDeletionStore(conn, accounts, audit,
                                              time_fn=time_fn)

    # -- gates ------------------------------------------------------

    def _require_admin(self, actor_id: int, *,
                       action: str | None = None,
                       target_kind: str | None = None,
                       target_id: str | None = None,
                       source_ip: str | None = None) -> User:
        actor = self._accounts.get_by_id(actor_id)
        if actor is None:
            raise AdminPanelError("no_such_user", "No such account.")
        if not actor.is_admin:
            event = audit_event_for(action)
            if event is not None and self._audit is not None:
                self._audit.append(
                    actor_kind="user", actor_id=actor.id, action=event,
                    target_kind=target_kind or "user",
                    target_id=target_id, outcome="denied",
                    source_ip=source_ip, detail={"reason": "not_admin"})
            raise AdminPanelError(
                "not_admin", "Only an instance admin can do that.")
        return actor

    def _gate_destructive(self, actor: User, session_token: object,
                          action: str, *, target_kind: str,
                          target_id: str | None,
                          detail: dict | None = None,
                          source_ip: str | None = None) -> int:
        """The one road every destructive act travels:
        audit log present, fresh sudo grant held, and the
        authorization witnessed — all *before* the seam
        executes. Returns the authorization's audit seq."""
        event = audit_event_for(action)
        assert event is not None  # every destructive action is mapped
        if self._audit is None:
            raise AdminPanelError(
                "audit_required",
                "This panel has no audit log wired, so destructive "
                "actions are impossible here by construction.")
        if (self._sudo is None or not isinstance(session_token, str)
                or not self._sudo.is_fresh(actor.id, session_token)):
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action=event,
                target_kind=target_kind, target_id=target_id,
                outcome="denied", source_ip=source_ip,
                detail={"reason": "sudo_required"})
            raise AdminPanelError(
                "sudo_required",
                "This action needs a fresh password confirmation; "
                "confirm and try again.")
        merged = {"via": "admin_panel", "phase": "authorized"}
        if detail:
            merged.update(detail)
        return self._audit.append(
            actor_kind="user", actor_id=actor.id, action=event,
            target_kind=target_kind, target_id=target_id,
            outcome="success", source_ip=source_ip, detail=merged)

    def _admin_verifier(self, actor: User,
                        session_token: object) -> Callable[[int], bool]:
        """The re-auth verifier handed to the S-043 /
        S-056 / S-199 seams: it answers with the *acting
        admin's* freshness on the admin's session, the
        re-authentication this act can honestly claim."""
        sudo, admin_id = self._sudo, actor.id

        def verify(_user_id: int) -> bool:
            return (sudo is not None and isinstance(session_token, str)
                    and sudo.is_fresh(admin_id, session_token))

        return verify

    # -- reading the desk --------------------------------------------

    def overview(self, actor_id: int) -> PanelOverview:
        self._require_admin(actor_id)

        def count(sql: str) -> int:
            return int(self._conn.execute(sql).fetchone()["c"])

        return PanelOverview(
            users=count("SELECT COUNT(*) AS c FROM users"),
            suspended=count(
                "SELECT COUNT(*) AS c FROM users"
                " WHERE status = 'suspended'"),
            admins=count(
                "SELECT COUNT(*) AS c FROM users WHERE is_admin = 1"),
            orgs=count("SELECT COUNT(*) AS c FROM organizations"),
            repos=count("SELECT COUNT(*) AS c FROM repositories"))

    def search(self, actor_id: int, query: object = None, *,
               kind: str | None = None,
               limit: int = 50) -> PanelSearchResults:
        self._require_admin(actor_id)
        text = normalize_query(query)
        if kind not in (None, "user", "org", "repo"):
            raise AdminPanelError(
                "query_invalid", f"Unknown search kind {kind!r}.")
        if (not isinstance(limit, int) or isinstance(limit, bool)
                or limit < 1 or limit > LIMIT_MAX):
            raise AdminPanelError(
                "query_invalid", "That result limit is not usable.")
        users: list[AdminUserRow] = []
        orgs: list[AdminOrgRow] = []
        repos: list[AdminRepoRow] = []
        if kind in (None, "user"):
            rows = self._conn.execute(
                "SELECT * FROM users ORDER BY username_lower").fetchall()
            from .accounts import _row_to_user
            for row in rows:
                user = _row_to_user(row)
                if matches_query([user.username, user.email], text):
                    users.append(AdminUserRow(user, self._repo_count(
                        user.username_lower)))
        if kind in (None, "org"):
            for org in self._orgs.list_organizations():
                if matches_query(
                        [org.name, org.display_name, org.bio], text):
                    orgs.append(AdminOrgRow(
                        org, self._member_count(org.id),
                        self._repo_count(org.name_lower)))
        if kind in (None, "repo"):
            rows = self._conn.execute(
                "SELECT * FROM repositories"
                " ORDER BY owner_lower, name_lower").fetchall()
            from .repositories import _row_to_repo
            for row in rows:
                repo = _row_to_repo(row)
                if matches_query(
                        [repo.owner, repo.name, repo.description], text):
                    repos.append(AdminRepoRow(repo))
        return PanelSearchResults(
            query=text, users=users[:limit], orgs=orgs[:limit],
            repos=repos[:limit])

    def _repo_count(self, owner_lower: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM repositories WHERE owner_lower = ?",
            (owner_lower,)).fetchone()
        return int(row["c"])

    def _member_count(self, org_id: int) -> int:
        # Through S-186's store, not a raw count: it seeds
        # the founding owner's row on first sight, so a
        # fresh organization's count is honest.
        return len(self._members.list_members(org_id))

    # -- users ---------------------------------------------------------

    def create_user(self, actor_id: int, session_token: object,
                    username: object, password: object,
                    email: object = None, *, make_admin: bool = False,
                    source_ip: str | None = None) -> User:
        actor = self._require_admin(
            actor_id, action=ACTION_CREATE_USER, target_kind="user",
            source_ip=source_ip)
        # Pre-validate everything registration will judge,
        # so the authorization entry never precedes a
        # refusal the panel could have foreseen.
        try:
            name = validate_username(username)
            email_norm = validate_email(email)
            validate_password(password, name)
        except RegistrationError as exc:
            raise AdminPanelError(exc.reason, str(exc)) from None
        if self._accounts.get_by_username(name.lower()) is not None:
            raise AdminPanelError(
                "username_taken", "That username is already taken.")
        if email_norm and self._accounts.get_by_email(
                email_norm.lower()) is not None:
            raise AdminPanelError(
                "email_taken", "That email address is already registered.")
        self._gate_destructive(
            actor, session_token, ACTION_CREATE_USER,
            target_kind="user", target_id=name.lower(),
            detail={"username": name, "make_admin": bool(make_admin)},
            source_ip=source_ip)
        user = self._accounts.register(
            name, password, email_norm, source_ip=source_ip)
        if make_admin:
            with self._conn:
                self._conn.execute(
                    "UPDATE users SET is_admin = 1 WHERE id = ?",
                    (user.id,))
            if self._audit is not None:
                self._audit.append(
                    actor_kind="user", actor_id=actor.id,
                    action="admin.user.role_change", target_kind="user",
                    target_id=str(user.id), outcome="success",
                    source_ip=source_ip,
                    detail={"is_admin": True, "via": "admin_panel",
                            "phase": "create"})
            user = self._accounts.get_by_id(user.id) or user
        return user

    def suspend_user(self, actor_id: int, session_token: object,
                     user_id: int, reason: object, *,
                     source_ip: str | None = None) -> SuspensionRecord:
        actor = self._require_admin(
            actor_id, action=ACTION_SUSPEND_USER, target_kind="user",
            target_id=str(user_id), source_ip=source_ip)
        # Pre-judge S-044's refusals before authorizing.
        target = self._accounts.get_by_id(user_id)
        if target is None:
            raise AdminPanelError("no_such_user", "No such account.")
        if actor.id == target.id:
            raise AdminPanelError(
                "cannot_suspend_self",
                "An admin cannot suspend their own account.")
        if target.status != "active":
            raise AdminPanelError(
                "not_active",
                f"Only an active account can be suspended "
                f"(this one is {target.status}).")
        if not isinstance(reason, str) or not reason.strip():
            raise AdminPanelError(
                "reason_required", "A suspension needs a reason.")
        self._gate_destructive(
            actor, session_token, ACTION_SUSPEND_USER,
            target_kind="user", target_id=str(user_id),
            source_ip=source_ip)
        return self._suspension.suspend(
            actor.id, user_id, reason, source_ip=source_ip)

    def unsuspend_user(self, actor_id: int, user_id: int,
                       reason: object = None, *,
                       source_ip: str | None = None) -> SuspensionRecord:
        actor = self._require_admin(
            actor_id, action=ACTION_UNSUSPEND_USER, target_kind="user",
            target_id=str(user_id), source_ip=source_ip)
        # Restorative, not destructive: no sudo gate;
        # S-044 witnesses it under admin.user.unsuspend.
        return self._suspension.unsuspend(
            actor.id, user_id, reason, source_ip=source_ip)

    def delete_user(self, actor_id: int, session_token: object,
                    user_id: int, typed_confirmation: object, *,
                    source_ip: str | None = None) -> PendingDeletion:
        actor = self._require_admin(
            actor_id, action=ACTION_DELETE_USER, target_kind="user",
            target_id=str(user_id), source_ip=source_ip)
        target = self._accounts.get_by_id(user_id)
        if target is None:
            raise AdminPanelError("no_such_user", "No such account.")
        if self._deletion.pending_for(user_id) is not None:
            raise AdminPanelError(
                "already_pending",
                "Deletion is already scheduled for this account.")
        if (not isinstance(typed_confirmation, str)
                or typed_confirmation.strip().lower()
                != target.username_lower):
            raise AdminPanelError(
                "confirmation_mismatch",
                "Type the account's username exactly to confirm "
                "deletion.")
        self._gate_destructive(
            actor, session_token, ACTION_DELETE_USER,
            target_kind="user", target_id=str(user_id),
            detail={"username": target.username}, source_ip=source_ip)
        return self._deletion.request(
            user_id, typed_confirmation,
            self._admin_verifier(actor, session_token),
            source_ip=source_ip)

    def set_admin(self, actor_id: int, session_token: object,
                  user_id: int, is_admin: bool, *,
                  source_ip: str | None = None) -> User:
        actor = self._require_admin(
            actor_id, action=ACTION_SET_ADMIN, target_kind="user",
            target_id=str(user_id), source_ip=source_ip)
        target = self._accounts.get_by_id(user_id)
        if target is None:
            raise AdminPanelError("no_such_user", "No such account.")
        want = bool(is_admin)
        if target.is_admin and not want:
            if actor.id == target.id:
                raise AdminPanelError(
                    "cannot_demote_self",
                    "An admin cannot demote their own account.")
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE is_admin = 1"
            ).fetchone()
            if int(row["c"]) <= 1:
                raise AdminPanelError(
                    "last_admin",
                    "That is the instance's last admin; the panel "
                    "cannot lock the instance out of itself.")
        self._gate_destructive(
            actor, session_token, ACTION_SET_ADMIN,
            target_kind="user", target_id=str(user_id),
            detail={"is_admin": want}, source_ip=source_ip)
        with self._conn:
            self._conn.execute(
                "UPDATE users SET is_admin = ? WHERE id = ?",
                (1 if want else 0, user_id))
        return self._accounts.get_by_id(user_id) or target

    # -- repositories and organizations --------------------------------

    def delete_repo(self, actor_id: int, session_token: object,
                    owner: object, name: object, *,
                    source_ip: str | None = None) -> PendingRepoDeletion:
        repo = self._repos.get_repository(owner, name)
        actor = self._require_admin(
            actor_id, action=ACTION_DELETE_REPO, target_kind="repo",
            target_id=repo.full_name if repo else None,
            source_ip=source_ip)
        if repo is None:
            raise AdminPanelError("no_such_repo", "No such repository.")
        if actor.username_lower != repo.owner_lower:
            # S-056 is owner-only; the panel invents no
            # bypass, and says so before any gate is spent.
            from .repo_deletion import RepoDeletionError
            raise RepoDeletionError(
                "not_repo_owner",
                "Only the repository's owner can delete it.")
        if self._repo_deletion.pending_for(repo.id) is not None:
            raise AdminPanelError(
                "already_pending", "Deletion is already scheduled.")
        self._gate_destructive(
            actor, session_token, ACTION_DELETE_REPO,
            target_kind="repo", target_id=repo.full_name,
            detail={"key": "deletion_request"}, source_ip=source_ip)
        return self._repo_deletion.request(
            actor.id, repo.owner, repo.name,
            self._admin_verifier(actor, session_token),
            source_ip=source_ip)

    def delete_org(self, actor_id: int, session_token: object,
                   org_id: int, typed_confirmation: object, *,
                   source_ip: str | None = None) -> PendingOrgDeletion:
        org = self._orgs.get_by_id(org_id)
        actor = self._require_admin(
            actor_id, action=ACTION_DELETE_ORG,
            target_kind="organization",
            target_id=org.name if org else None, source_ip=source_ip)
        if org is None:
            raise AdminPanelError("org_not_found", "No such organization.")
        # Pre-judge S-199's refusals before authorizing:
        # owner-only, no repos remaining, no pending
        # request, typed confirmation.
        if self._members.role_for(actor.id, org.id) != "owner":
            from .organizations import OrganizationError
            raise OrganizationError(
                "not_org_owner",
                "Only an organization owner can delete "
                "this organization.")
        if self._org_deletion.pending_for(org.id) is not None:
            raise AdminPanelError(
                "already_pending",
                "Deletion is already scheduled for this organization.")
        if self._org_deletion.inventory(org.id).repositories:
            raise AdminPanelError(
                "repos_remaining",
                "The organization still owns repositories; transfer "
                "or delete them explicitly first.")
        if (not isinstance(typed_confirmation, str)
                or typed_confirmation.strip().lower() != org.name_lower):
            raise AdminPanelError(
                "confirmation_mismatch",
                "Type the organization's name exactly to confirm "
                "deletion.")
        self._gate_destructive(
            actor, session_token, ACTION_DELETE_ORG,
            target_kind="organization", target_id=org.name,
            detail={"fields": "danger", "action": "delete_request"},
            source_ip=source_ip)
        return self._org_deletion.request(
            actor.id, org.id, typed_confirmation,
            self._admin_verifier(actor, session_token),
            source_ip=source_ip)


# -- rendering -----------------------------------------------------------


def render_admin_panel_page(results: PanelSearchResults) -> str:
    """The admin desk page: the three searchable
    sections with their counts, every row in words,
    and an honest empty state per section. All
    user-controlled text escaped (S-010's seam)."""
    esc = escape_html_text
    parts = ["<h1>Admin panel</h1>",
             f"<p>{esc(results.headline)}.</p>"]
    parts.append("<h2>Users</h2>")
    if results.users:
        for row in results.users:
            user = row.user
            role = "admin" if user.is_admin else "member"
            parts.append(
                f"<p>{esc(user.username)} — {esc(user.status)}, "
                f"{role}, {row.repo_count} repositories</p>")
    else:
        parts.append("<p>No users match.</p>")
    parts.append("<h2>Organizations</h2>")
    if results.orgs:
        for row in results.orgs:
            org = row.org
            parts.append(
                f"<p>{esc(org.name)} — "
                f"{esc(org.effective_display_name)}, "
                f"{row.member_count} members, "
                f"{row.repo_count} repositories</p>")
    else:
        parts.append("<p>No organizations match.</p>")
    parts.append("<h2>Repositories</h2>")
    if results.repos:
        for row in results.repos:
            repo = row.repo
            parts.append(
                f"<p>{esc(repo.full_name)} — {esc(repo.visibility)}"
                f"</p>")
    else:
        parts.append("<p>No repositories match.</p>")
    return "\n".join(parts)
