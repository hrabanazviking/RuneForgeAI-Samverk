"""API authentication (S-238).

Tokens (S-032/S-033) and session-free Basic for
scripts; every API call resolves through S-190.
Part XII's faces (S-216 search, S-231 events, and
every resource S-237 contracted) take a resolved
caller, never a raw header: this module is the
one door that turns an `Authorization` header
into that caller, and the one seam that then
judges the caller against a repository.

- **Two credential roads, no session.** A script
  authenticates per call, statelessly: `Bearer`
  with a personal access token -- classic
  (S-032, `svk_`) or fine-grained (S-033,
  `svkf_`) -- or HTTP `Basic` for scripts, with
  the account password or a token in the
  password slot (the username slot then holds
  the token owner's name or the conventional
  `x-access-token`, S-082's law reused). No
  road consults, creates, or extends an S-006
  session: a session cookie presented as a
  credential authenticates to nothing, and a
  successful authentication writes no session
  row. Browsers use sessions; scripts use this.
- **Identity only from the token stores.** A
  Bearer token is resolved by its own store --
  S-032's or S-033's `authenticate`, which alone
  enforce revocation and expiry and stamp
  last-used -- and a Basic password by S-081's
  git authenticator, whose decoy-hash timing law
  and deactivated-account refusal are reused,
  not reinvented. A token whose owner is not an
  active account authenticates to nothing, as
  its owner's password does. Every failure of a
  presented credential -- malformed, unknown,
  revoked, expired, deactivated, or a token
  under the wrong username -- is the one refusal
  `credentials_invalid`: a caller learns that
  their credential failed, never which part.
- **Missing is its own refusal; invalid never
  downgrades.** No header at all is
  `authentication_required`. A header that is
  present but wrong raises too: it never
  silently falls back to anonymous, or a leaked
  or mistyped credential would quietly read
  whatever the public may read while its owner
  believes it failed.
- **Permission is S-190's alone.**
  `authorize` resolves the caller's role in the
  repository through S-190's `PermissionEngine`
  -- the same function the web surfaces use --
  and through nothing else: this module holds no
  visibility law, no team law, and no ladder of
  its own beyond S-189's shared rank check over
  the resolved role. A repository that does not
  exist and a repository the resolved role
  cannot reach at the asked rung are the one
  refusal `repo_not_found`, indistinguishable
  in reason and detail (S-237's uniform
  not-found rule): the API confirms nothing
  about what it hides.
- **Token scope is a ceiling over S-190,
  checked after it.** A token never widens its
  owner's S-190 role; it can only narrow what
  this call may do. Classic tokens answer by
  their S-032 scopes (a write scope implies its
  read sibling, `token_allows`' law restated
  purely in `decide_token_scope`), fine-grained
  tokens by their S-033 permissions on exactly
  their bound repository (a `repo`-level read
  also stands on the mandatory `metadata:read`
  floor). Password Basic carries the account's
  own standing and no scope ceiling. A caller
  whose S-190 role suffices but whose token
  scope does not is refused
  `insufficient_scope` -- said plainly, because
  the token's owner already knows the
  repository their own token was aimed at.
- **Refusals are S-237's shape.** Every refusal
  is an `ApiAuthError` with a machine-branchable
  reason, rendered by `error_to_dict` as exactly
  `error` and `detail` -- the contract's current
  refusal fields, pinned against
  `CURRENT_ERROR_FIELDS`; S-240's problem
  format is future work and is not claimed.
- **A read that witnesses nothing.**
  Authentication and authorisation write no row
  and audit nothing of their own: the only write
  a call can cause is the token stores' own
  last-used stamp, which is S-032/S-033's law.
  No migration (schema stays 94), no taxonomy
  event (129 stand: 33 auth / 83 repo / 13
  admin).
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .access_tokens import (
    TOKEN_PREFIX as CLASSIC_PREFIX,
    AccessTokenStore)
from .accounts import AccountStore, User
from .escaping import escape_html_text
from .fine_grained_tokens import (
    TOKEN_PREFIX as FINE_PREFIX,
    FineTokenStore)
from .git_auth import (
    TOKEN_USERNAME, GitAuthenticator, parse_basic_credentials)
from .permission_engine import PermissionEngine, Resolution
from .repositories import Repository, RepositoryStore
from .team_permissions import ROLES, role_covers

__all__ = [
    "AUTH_HELP_PATH", "CREDENTIAL_KINDS", "RESOURCES",
    "ApiAuthError", "ApiAuthenticator", "ApiAuthorization",
    "ApiIdentity", "decide_token_scope", "error_to_dict",
    "identity_to_dict", "parse_bearer_token",
    "render_api_auth_page", "scope_requirement",
]

AUTH_HELP_PATH = "/api/authentication"
CREDENTIAL_KINDS = ("password", "classic_token", "fine_token")
RESOURCES = ("repo", "contents", "issues", "pull_requests", "profile")

_REPO_NOT_FOUND = "No such repository."
_CREDENTIALS_INVALID = "That credential does not authenticate."


class ApiAuthError(ValueError):
    """One refused API call: a machine-branchable
    reason with its human detail."""
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def error_to_dict(exc: ApiAuthError) -> dict:
    """One refusal as data, in S-237's current
    shape: the reason and the detail, nothing else."""
    return {"error": exc.reason, "detail": str(exc)}


def parse_bearer_token(header: object) -> str | None:
    """The raw token of a `Bearer` header, or None
    for anything else: a different scheme, a
    missing token, or a token carrying spaces.
    Pure parsing -- nothing is resolved here."""
    if not isinstance(header, str):
        return None
    scheme, sep, payload = header.partition(" ")
    if not sep or scheme.lower() != "bearer":
        return None
    token = payload.strip()
    if not token or any(ch.isspace() for ch in token):
        return None
    return token


def scope_requirement(resource: str, minimum: str) -> tuple[str, str | None]:
    """The (classic scope, fine permission) a call
    at *minimum* on *resource* asks of a token.
    Any rung above read asks the write sibling.
    Fine-grained tokens hold no profile permission:
    their fine answer is None, which no grant
    satisfies. Pure data law, shared by the pure
    judgement below and the authenticator."""
    level = "read" if minimum == "read" else "write"
    if resource in ("repo", "contents"):
        return f"repo:{level}", f"contents:{level}"
    if resource == "issues":
        return f"issues:{level}", f"issues:{level}"
    if resource == "pull_requests":
        return f"repo:{level}", f"pull_requests:{level}"
    if resource == "profile":
        return f"profile:{level}", None
    raise ApiAuthError(
        "resource_unknown", "No such API resource family.")


def _allows(granted: frozenset, required: str) -> bool:
    """One scope question with the write-implies-read
    law (S-032's `token_allows` and S-033's
    `permission_allows` state the same rule over
    their own shapes): held directly, or the read
    sibling of a held write grant."""
    if required in granted:
        return True
    if required.endswith(":read"):
        return (required[:-len(":read")] + ":write") in granted
    return False


def decide_token_scope(
    kind: str, granted: frozenset, resource: str, minimum: str,
    *, bound_matches: bool = True,
) -> bool:
    """May a credential of *kind* holding *granted*
    scopes/permissions act at *minimum* on
    *resource*? Password credentials carry the
    account's own standing (True). Classic tokens
    answer by scope; fine-grained tokens only on
    exactly their bound repository, by permission
    -- with a repo-level read also standing on
    S-033's mandatory `metadata:read` floor.
    Pure: no storage is read here."""
    if kind == "password":
        return True
    classic_scope, fine_permission = scope_requirement(resource, minimum)
    if kind == "classic_token":
        return _allows(granted, classic_scope)
    if kind == "fine_token":
        if not bound_matches:
            return False
        if fine_permission is None:
            return False
        if _allows(granted, fine_permission):
            return True
        return (resource == "repo" and minimum == "read"
                and "metadata:read" in granted)
    return False


@dataclass(frozen=True)
class ApiIdentity:
    """One resolved caller: the account (None for
    the anonymous caller), the credential kind
    (`anonymous`, or one of CREDENTIAL_KINDS), and
    a token's public facts when a token carried
    the call -- its id, title, prefix, granted
    scopes or permissions, and, for a fine-grained
    token, the repository it is bound to. The raw
    token is never part of this view."""
    user: User | None
    kind: str
    token_id: int | None = None
    token_title: str | None = None
    token_prefix: str | None = None
    scopes: frozenset = frozenset()
    permissions: frozenset = frozenset()
    bound_owner: str | None = None
    bound_repo: str | None = None

    @property
    def authenticated(self) -> bool:
        return self.user is not None

    @property
    def username(self) -> str | None:
        return self.user.username if self.user else None


def identity_to_dict(identity: ApiIdentity) -> dict:
    """One caller as JSON-safe data: who, by what
    credential, holding what grants -- sorted, and
    never the raw token or its hash."""
    return {
        "authenticated": identity.authenticated,
        "username": identity.username,
        "credential": identity.kind,
        "token_id": identity.token_id,
        "token_title": identity.token_title,
        "scopes": sorted(identity.scopes),
        "permissions": sorted(identity.permissions),
        "bound_repository": (
            f"{identity.bound_owner}/{identity.bound_repo}"
            if identity.bound_owner else None),
    }


@dataclass(frozen=True)
class ApiAuthorization:
    """One authorised call: the caller, the
    repository, and S-190's own Resolution -- the
    role, its source, and its plain-words reason
    ride along, so an answer stays explainable."""
    identity: ApiIdentity
    repository: Repository
    resolution: Resolution

    @property
    def role(self) -> str | None:
        return self.resolution.role

    @property
    def user(self) -> User | None:
        return self.identity.user


class ApiAuthenticator:
    """The S-238 door: headers to callers, and
    callers judged against repositories through
    S-190 alone. It owns no permission law and no
    credential store of its own -- the token
    stores, the git Basic authenticator, and the
    permission engine are built once here and
    every call delegates to them."""

    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        repositories: RepositoryStore,
        audit=None, time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._repos = repositories
        self._classic = AccessTokenStore(
            conn, accounts, audit=audit, time_fn=time_fn)
        self._fine = FineTokenStore(
            conn, accounts, audit=audit, time_fn=time_fn)
        self._git = GitAuthenticator(conn, accounts)
        self._engine = PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)

    # -- credential resolution ---------------------------
    def _identity_for_token(self, token, kind: str) -> ApiIdentity:
        user = self._accounts.get_by_id(token.user_id)
        if user is None or user.status != "active":
            raise ApiAuthError(
                "credentials_invalid", _CREDENTIALS_INVALID)
        if kind == "classic_token":
            return ApiIdentity(
                user=user, kind=kind, token_id=token.id,
                token_title=token.title, token_prefix=token.prefix,
                scopes=frozenset(token.scopes))
        return ApiIdentity(
            user=user, kind=kind, token_id=token.id,
            token_title=token.title, token_prefix=token.prefix,
            permissions=frozenset(token.permissions),
            bound_owner=token.owner, bound_repo=token.repo)

    def _resolve_presented_token(self, presented: str) -> ApiIdentity:
        if presented.startswith(FINE_PREFIX):
            token = self._fine.authenticate(presented)
            kind = "fine_token"
        elif presented.startswith(CLASSIC_PREFIX):
            token = self._classic.authenticate(presented)
            kind = "classic_token"
        else:
            token = None
            kind = ""
        if token is None:
            raise ApiAuthError(
                "credentials_invalid", _CREDENTIALS_INVALID)
        return self._identity_for_token(token, kind)

    def _authenticate_basic(self, header: str) -> ApiIdentity:
        parsed = parse_basic_credentials(header)
        if parsed is None:
            raise ApiAuthError(
                "credentials_invalid", _CREDENTIALS_INVALID)
        username, credential = parsed
        if credential.startswith((CLASSIC_PREFIX, FINE_PREFIX)):
            identity = self._resolve_presented_token(credential)
            owner = identity.user
            assert owner is not None
            if username.lower() not in (
                    owner.username_lower, TOKEN_USERNAME):
                raise ApiAuthError(
                    "credentials_invalid", _CREDENTIALS_INVALID)
            return identity
        user = self._git.authenticate_basic(header)
        if user is None:
            raise ApiAuthError(
                "credentials_invalid", _CREDENTIALS_INVALID)
        return ApiIdentity(user=user, kind="password")

    def authenticate(self, header: object) -> ApiIdentity:
        """Resolve one `Authorization` header to its
        caller. Missing is `authentication_required`;
        a scheme other than Bearer or Basic is
        `scheme_unsupported`; every failure of a
        presented credential is the one
        `credentials_invalid`. No session is
        consulted, created, or extended."""
        if header is None or (isinstance(header, str)
                              and not header.strip()):
            raise ApiAuthError(
                "authentication_required",
                "This API call needs a credential: a Bearer "
                "token, or Basic authentication for scripts.")
        if not isinstance(header, str):
            raise ApiAuthError(
                "credentials_invalid", _CREDENTIALS_INVALID)
        scheme = header.partition(" ")[0].lower()
        if scheme == "bearer":
            presented = parse_bearer_token(header)
            if presented is None:
                raise ApiAuthError(
                    "credentials_invalid", _CREDENTIALS_INVALID)
            return self._resolve_presented_token(presented)
        if scheme == "basic":
            return self._authenticate_basic(header)
        raise ApiAuthError(
            "scheme_unsupported",
            "Samverk's API takes a Bearer token or Basic "
            "authentication, not that scheme.")

    def resolve_caller(
        self, header: object, *, required: bool = True,
    ) -> ApiIdentity:
        """The caller of one API call: with
        `required=False` a missing header is the
        anonymous caller, while a present-but-wrong
        header still raises -- invalid never
        downgrades to anonymous."""
        if header is None or (isinstance(header, str)
                              and not header.strip()):
            if required:
                raise ApiAuthError(
                    "authentication_required",
                    "This API call needs a credential: a Bearer "
                    "token, or Basic authentication for scripts.")
            return ApiIdentity(user=None, kind="anonymous")
        return self.authenticate(header)

    # -- S-190 resolution ---------------------------------
    def resolution(self, identity: ApiIdentity,
                   repo: Repository) -> Resolution:
        """S-190's answer for this caller in this
        repository -- the engine's own function,
        called directly, the only place permission
        enters this module."""
        return self._engine.resolve(identity.user, repo)

    def authorize_identity(
        self, identity: ApiIdentity, owner: object, repo: object,
        minimum: str = "read", resource: str = "repo",
    ) -> ApiAuthorization:
        """Judge one resolved caller against one
        repository: the repository must exist and
        S-190's resolved role must cover *minimum*
        (both failures are the uniform
        `repo_not_found`), and a token credential
        must additionally carry the scope for
        *resource* at that rung
        (`insufficient_scope`, checked only after
        S-190 has answered, so scope is never a
        side channel around the uniform refusal)."""
        if resource not in RESOURCES:
            raise ApiAuthError(
                "resource_unknown", "No such API resource family.")
        if minimum not in ROLES:
            raise ApiAuthError(
                "role_invalid", "No such permission rung.")
        found = self._repos.get_repository(owner, repo)
        if found is None:
            raise ApiAuthError("repo_not_found", _REPO_NOT_FOUND)
        resolved = self.resolution(identity, found)
        if not role_covers(resolved.role, minimum):
            raise ApiAuthError("repo_not_found", _REPO_NOT_FOUND)
        if identity.kind in ("classic_token", "fine_token"):
            granted = (identity.scopes if identity.kind == "classic_token"
                       else identity.permissions)
            bound = True
            if identity.kind == "fine_token":
                bound = (
                    (identity.bound_owner or "").lower()
                    == found.owner_lower
                    and (identity.bound_repo or "").lower()
                    == found.name_lower)
            if not decide_token_scope(
                    identity.kind, frozenset(granted), resource,
                    minimum, bound_matches=bound):
                raise ApiAuthError(
                    "insufficient_scope",
                    "That token does not carry the scope for "
                    "this call on this repository.")
        return ApiAuthorization(
            identity=identity, repository=found, resolution=resolved)

    def authorize(
        self, header: object, owner: object, repo: object,
        minimum: str = "read", resource: str = "repo",
    ) -> ApiAuthorization:
        """One full API call: resolve the header
        (anonymous when absent, refused when wrong),
        then judge through S-190 as
        `authorize_identity` does."""
        identity = self.resolve_caller(header, required=False)
        return self.authorize_identity(
            identity, owner, repo, minimum=minimum, resource=resource)


def render_api_auth_page(identity: ApiIdentity | None = None) -> str:
    """How a script authenticates, in plain words:
    the two credential roads, the session-free law,
    the refusal shapes, and S-190's sole judgement
    -- with the current caller's standing said in
    words when one rides along. Every value
    escaped through S-010."""
    parts = [
        "<h1>API authentication</h1>",
        "<p>Scripts authenticate per call, with no "
        "session: send a personal access token as a "
        "Bearer credential (a classic token, S-032, "
        "or a fine-grained token bound to one "
        "repository, S-033), or use HTTP Basic with "
        "the account password -- or a token in the "
        "password slot -- for scripts. A browser "
        "session cookie is not an API credential.</p>",
        "<p>Every call is then judged by the "
        "permission engine (S-190), exactly as the "
        "web judges the same person on the same "
        "repository. A repository you may not read "
        "answers exactly as one that does not "
        "exist. A token can narrow its owner's "
        "standing, never widen it.</p>",
        "<p>Refusals carry a machine-branchable "
        "reason and a human sentence: "
        "authentication_required when no credential "
        "was sent, credentials_invalid when one was "
        "sent and failed, insufficient_scope when a "
        "token lacks the scope for the call, and "
        "repo_not_found for a missing or unreadable "
        "repository.</p>",
    ]
    if identity is not None:
        if identity.authenticated:
            parts.append(
                "<p>Current caller: "
                f"{escape_html_text(identity.username or '')} "
                "by "
                f"{escape_html_text(identity.kind)}."
                "</p>")
        else:
            parts.append(
                "<p>Current caller: an anonymous "
                "visitor.</p>")
    return "\n".join(parts)
