"""Repositories API (S-242).

Repositories API -- CRUD, forks, branches, contents
read -- parity with the web's capabilities, no
API-only back doors. S-237's contract named this
slice as the builder of the `/api/v1` root and the
whole repositories family (the collection, one
repository, its branches, its contents, its forks);
this module is that family, in the shape the
contract ratified.

- **No API-only back doors, by construction.**
  Every act delegates to the very store the web
  uses, so the API can do nothing a signed-in
  person cannot, and is refused exactly what the
  web refuses: creation is S-049's
  `RepositoryStore.create_repository`, update is
  S-050's `update_metadata` (and S-050's `rename`
  when a new name rides along), forking is S-055's
  `ForkStore.fork`, branches are S-052's
  `RefStore` listing with each branch's protection
  judged by Part VIII's own evaluation, contents
  are read through S-097's shared Part V helpers
  (`resolve_commit`, `tree_at`, `blob_at`) over
  S-051's object reader, and deletion is S-056's
  process -- a request with its 7-day grace, never
  an instant destroy. The stores' own audits
  witness each act exactly as the same act on the
  web is witnessed (repo.create,
  repo.settings.change, repo.visibility.change,
  repo.fork, and deletion's own events); this face
  adds no event of its own.
- **Every call resolves through S-238 and S-190.**
  The header is resolved by S-238's door
  (`ApiAuthenticator`) and nothing else; each
  repository is then judged by
  `authorize_identity` -- S-190's permission
  engine alone, with the token's scope as a
  ceiling over it, checked after it. A missing or
  unreadable repository is the one refusal
  `repo_not_found`, indistinguishable in reason
  and detail (S-237's uniform not-found rule).
  The collection is filtered repository by
  repository through the same engine before any
  row is serialised, so an unreadable repository
  contributes no row, no name, and no count.
  Writes carry the web's own further law because
  the stores enforce it: update and rename are
  owner-only in S-050 (a site admin the engine
  grants `admin` is still refused `not_repo_owner`
  by the store, exactly as on the web), and
  deletion is owner-only in S-056.
- **Deletion is the web's process, honestly.**
  The web gates a deletion request behind a fresh
  re-authentication (S-056's sudo). An API call is
  session-free and presents its credential fresh
  on this very call (S-238), which is the fresh
  proof the sudo asks for, so `DELETE` requests
  deletion through S-056 with that presentation as
  the verifier: the answer names the pending
  deletion and its scheduled time, the repository
  and its disk stand untouched through the grace,
  and the web's cancel and finalize own what
  happens next. There is no API-only instant
  delete.
- **Contents read, never written.** One path of
  one ref, as data: a tree answers as its entries,
  a blob's bytes are carried base64-encoded (data
  carries raw values; S-010 escaping is the page's
  law, not the wire's). A blob past the read cap
  (1 MB, S-099's view limit) is refused
  `content_too_large` rather than silently
  truncated. The API writes files through Git,
  never around it -- there is no contents write
  here, as the contract states.
- **Shapes are the contract's.** A repository is
  S-237's `_REPO_FIELDS` exactly, a branch is
  (name, tip, protected), a contents answer
  carries (path, kind, oid, size, entries) first
  in the contract's order, and lists speak the
  one envelope -- the filtered `total` tallied
  before the cap, the `returned` count the cap
  allowed, a `complete` flag, and the `limit`
  honoured (default 100, at most 500, the landed
  faces' bounds).
- **Refusals are S-240's shape.** Every refusal
  is a `RepositoriesAPIError` with a
  machine-branchable reason -- S-238's reasons
  verbatim for authentication and scope, the
  stores' own reasons verbatim for the acts they
  refuse -- rendered by `error_to_dict` in the
  one problem format through
  samverk/error_shape.py.
- **What a read witnesses.** Reads write no row
  and audit nothing; the writes are the stores'
  own acts, witnessed by the stores. No migration
  (schema stays 94), no taxonomy event (129
  stand: 33 auth / 83 repo / 13 admin).
"""
from __future__ import annotations

import base64
import json
import sqlite3
import time
from collections.abc import Callable

from .accounts import AccountStore
from .api_auth import (
    ApiAuthError, ApiAuthenticator, ApiIdentity, decide_token_scope)
from .api_contract import API_BASE, resource_ids
from .error_shape import problem_from_error, problem_to_dict
from .escaping import escape_html_text
from .forks import ForkError, ForkStore
from .objects import ObjectError, ObjectReader
from .permission_engine import PermissionEngine
from .protection_rules import ProtectionRuleStore
from .refs import RefStore
from .repo_deletion import GRACE_SECONDS, RepoDeletion, RepoDeletionError
from .repo_home import RepoHomeError, resolve_commit, tree_at, validate_repo_path
from .repositories import Repository, RepositoryError, RepositoryStore

__all__ = [
    "DEFAULT_LIMIT", "MAX_CONTENT_BYTES", "MAX_LIMIT",
    "REPOSITORIES_API_PATH", "RepositoriesAPI",
    "RepositoriesAPIError", "branch_to_dict", "error_to_dict",
    "render_repositories_api_page", "repository_to_dict", "to_json",
]

REPOSITORIES_API_PATH = "/api/repositories"

# The landed faces' own bounds (S-231): an API
# limit lives inside them or is refused -- a
# contract does not silently clamp a caller's
# stated bound the way a page may.
DEFAULT_LIMIT = 100
MAX_LIMIT = 500

# S-099's view limit, carried to the wire: a blob
# past it is refused by name, never truncated.
MAX_CONTENT_BYTES = 1_000_000

_REPO_NOT_FOUND = "No such repository."
_CREATE_KEYS = frozenset(
    {"name", "description", "visibility", "default_branch"})
_UPDATE_KEYS = frozenset(
    {"name", "description", "visibility", "default_branch"})
_FORK_KEYS = frozenset({"name", "visibility"})


class RepositoriesAPIError(ValueError):
    """One refused repositories-API call: a
    machine-branchable reason with its human
    detail."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def error_to_dict(exc: RepositoriesAPIError) -> dict:
    """One refusal as data, in S-240's one problem
    format (samverk/error_shape.py): type, title,
    status, detail, error_id -- nothing else."""
    return problem_to_dict(problem_from_error(exc))


def to_json(payload: dict) -> str:
    """One payload as a JSON text: keys sorted so
    the same answer renders byte-identically
    twice."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# ------------------------------------------------------------------
# Serialisers -- one repository, one branch, as data
# ------------------------------------------------------------------

def repository_to_dict(repo: Repository) -> dict:
    """One repository as JSON-safe data, in
    S-237's contracted field order exactly: id,
    owner, name, full_name, visibility,
    description, default_branch, created_at. Data
    carries the raw values -- S-010 escaping is
    the page's law, not the wire's."""
    return {
        "id": repo.id,
        "owner": repo.owner,
        "name": repo.name,
        "full_name": repo.full_name,
        "visibility": repo.visibility,
        "description": repo.description,
        "default_branch": repo.default_branch,
        "created_at": repo.created_at,
    }


def branch_to_dict(name: str, tip: str, protected: bool) -> dict:
    """One branch as JSON-safe data, in S-237's
    contracted field order: its name, the oid its
    tip names today, and whether any enabled
    protection rule attaches to it (Part VIII's
    own evaluation, in words a script can branch
    on -- a boolean, never a colour)."""
    return {"name": name, "tip": tip, "protected": bool(protected)}


# ------------------------------------------------------------------
# The API face
# ------------------------------------------------------------------

class RepositoriesAPI:
    """The S-242 executor: the contract's
    repositories family, answered in data. It owns
    no store and no permission law of its own --
    S-238's door, S-190's engine, and the web's own
    stores (repositories, forks, refs, protection,
    deletion, and Part V's object helpers) are
    built once here and every call delegates to
    them, so parity is by construction, not by
    copy."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        data_root,
        accounts: AccountStore,
        repositories: RepositoryStore,
        audit=None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._auth = ApiAuthenticator(
            conn, accounts, repositories, audit=audit,
            time_fn=time_fn)
        self._engine = PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)
        self._forks = ForkStore(
            conn, data_root, accounts, repositories, audit=audit)
        self._deletion = RepoDeletion(
            conn, data_root, accounts, repositories,
            audit=audit, time_fn=time_fn)
        self._protection = ProtectionRuleStore(
            conn, repositories, accounts, audit=audit,
            time_fn=time_fn)

    # -- shared judgements --------------------------------
    @staticmethod
    def _check_limit(limit: object) -> int:
        if (isinstance(limit, bool) or not isinstance(limit, int)
                or limit < 1 or limit > MAX_LIMIT):
            raise RepositoriesAPIError(
                "limit_invalid",
                f"limit must be an integer between 1 and {MAX_LIMIT}.")
        return limit

    @staticmethod
    def _envelope(kind: str, items: list, *, limit: int) -> dict:
        """One list answer in the contract's
        envelope: the filtered total tallied before
        the cap, how many the cap returned, whether
        the answer is complete under that cap, and
        the limit honoured."""
        page = items[:limit]
        return {
            "total": len(items),
            "returned": len(page),
            "complete": len(items) <= len(page),
            "limit": limit,
            kind: page,
        }

    @staticmethod
    def _payload(payload: object, allowed: frozenset, *,
                 required: bool) -> dict:
        """One request body as a dict of known keys:
        a body that is not an object, or carries a
        key this resource does not take, is refused
        `payload_invalid` -- the API never guesses
        at a body's meaning and never silently drops
        a field its caller named."""
        if payload is None:
            if required:
                raise RepositoriesAPIError(
                    "payload_invalid",
                    "This call needs a JSON object body.")
            return {}
        if not isinstance(payload, dict):
            raise RepositoriesAPIError(
                "payload_invalid",
                "This call needs a JSON object body.")
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise RepositoriesAPIError(
                "payload_invalid",
                "This resource does not take the field "
                f"{unknown[0]!r}.")
        return payload

    def _caller(self, header: object, *, required: bool) -> ApiIdentity:
        """The caller of one call, through S-238's
        door alone: its refusals ride this face's
        error verbatim (reason and detail)."""
        try:
            return self._auth.resolve_caller(header, required=required)
        except ApiAuthError as exc:
            raise RepositoriesAPIError(exc.reason, str(exc)) from None

    def _authorize(self, identity: ApiIdentity, owner: object,
                   repo: object, minimum: str, resource: str):
        """Judge one resolved caller against one
        repository through S-238's seam: S-190 first,
        the token's scope ceiling after it; its
        refusals ride this face's error verbatim."""
        try:
            return self._auth.authorize_identity(
                identity, owner, repo, minimum=minimum,
                resource=resource)
        except ApiAuthError as exc:
            raise RepositoriesAPIError(exc.reason, str(exc)) from None

    def _require_create_scope(self, identity: ApiIdentity) -> None:
        """The scope ceiling for an act that creates
        a repository where none stood: a token must
        carry the write scope for `repo`. A
        fine-grained token is bound to one existing
        repository, so no binding can match a
        repository being created -- it never carries
        this scope. Password callers carry their
        account's own standing."""
        if identity.kind == "password":
            return
        if identity.kind == "classic_token":
            granted = frozenset(identity.scopes)
            bound = True
        elif identity.kind == "fine_token":
            granted = frozenset(identity.permissions)
            bound = False
        else:
            return
        if not decide_token_scope(
                identity.kind, granted, "repo", "write",
                bound_matches=bound):
            raise RepositoriesAPIError(
                "insufficient_scope",
                "That token does not carry the scope for "
                "this call on this repository.")

    @staticmethod
    def _store_error(exc: RepositoryError) -> RepositoriesAPIError:
        """One store refusal carried onto this face:
        the store's reason verbatim -- except a
        store's missing repository, which the API
        has already judged uniformly as
        `repo_not_found` before delegating, so a
        race to the same fact keeps the one shape."""
        if exc.reason == "no_such_repo":
            return RepositoriesAPIError("repo_not_found", _REPO_NOT_FOUND)
        return RepositoriesAPIError(exc.reason, str(exc))

    # -- the root ------------------------------------------
    def root(self, header: object = None) -> dict:
        """The contract's own front door as data:
        the versioned base, the version, and the
        ids of every resource family the contract
        holds, so a script can discover the table
        from the table. Any caller may read it,
        signed in or not -- it names no repository
        and no person."""
        self._caller(header, required=False)
        return {
            "base": API_BASE,
            "version": "v1",
            "resources": list(resource_ids()),
        }

    # -- the collection --------------------------------------
    def list_repositories(self, header: object = None, *,
                          limit: int = DEFAULT_LIMIT) -> dict:
        """The repositories this caller may read,
        in the list envelope: every repository in
        the instance, in id order, filtered through
        S-190's engine for this caller before any
        row is serialised -- an unreadable
        repository contributes no row, no name, and
        no count, exactly as the landed faces keep
        it. Anonymous callers read as the web's
        anonymous."""
        limit = self._check_limit(limit)
        identity = self._caller(header, required=False)
        visible: list[Repository] = []
        for found in self._conn.execute(
                "SELECT id FROM repositories ORDER BY id").fetchall():
            current = self._repos.get_by_id(int(found["id"]))
            if current is None:
                continue
            if self._engine.resolve(identity.user, current).role:
                visible.append(current)
        return self._envelope(
            "repositories",
            [repository_to_dict(repo) for repo in visible],
            limit=limit)

    def create_repository(self, header: object, payload: object, *,
                          source_ip: str | None = None) -> dict:
        """Create one repository under the caller's
        own name, through S-049's own creation: its
        name law, its all-or-nothing disk-and-row
        agreement, and its `repo.create` witness are
        the store's, unchanged. A signed-in caller
        is required; a token must additionally
        carry the write scope."""
        body = self._payload(payload, _CREATE_KEYS, required=True)
        identity = self._caller(header, required=True)
        self._require_create_scope(identity)
        user = identity.user
        assert user is not None
        if "name" not in body:
            raise RepositoriesAPIError(
                "payload_invalid",
                "A repository name is required.")
        try:
            created = self._repos.create_repository(
                user.id, user.username, body["name"],
                description=body.get("description", ""),
                visibility=body.get("visibility", "private"),
                default_branch=body.get("default_branch", "main"),
                source_ip=source_ip)
        except RepositoryError as exc:
            raise self._store_error(exc) from None
        return repository_to_dict(created)

    # -- one repository --------------------------------------
    def get_repository(self, header: object, owner: object,
                       repo: object) -> dict:
        """One repository as data: read access
        judged through S-190 (anonymous callers read
        as the web's anonymous), the uniform
        `repo_not_found` for a missing or unreadable
        one."""
        identity = self._caller(header, required=False)
        auth = self._authorize(identity, owner, repo, "read", "repo")
        return repository_to_dict(auth.repository)

    def update_repository(self, header: object, owner: object,
                          repo: object, payload: object, *,
                          source_ip: str | None = None) -> dict:
        """Update one repository's settings-shaped
        fields, through S-050's own writers: the
        description, visibility, and default branch
        ride `update_metadata`, and a new `name`
        rides `rename` -- each judged exactly as
        the web judges it, owner-only refusal
        (`not_repo_owner`) included. The call first
        asks S-190 for `admin`, so an unreadable or
        merely readable repository keeps the
        uniform shape; the store then applies the
        web's own owner law to the act itself."""
        body = self._payload(payload, _UPDATE_KEYS, required=True)
        if not body:
            raise RepositoriesAPIError(
                "payload_invalid",
                "This call names no field to update.")
        identity = self._caller(header, required=True)
        auth = self._authorize(identity, owner, repo, "admin", "repo")
        user = identity.user
        assert user is not None
        current = auth.repository
        try:
            if any(key in body for key in (
                    "description", "visibility", "default_branch")):
                current = self._repos.update_metadata(
                    user.id, current.owner, current.name,
                    description=body.get("description"),
                    visibility=body.get("visibility"),
                    default_branch=body.get("default_branch"),
                    source_ip=source_ip)
            new_name = body.get("name")
            if new_name is not None and new_name != current.name:
                current = self._repos.rename(
                    user.id, current.owner, current.name, new_name,
                    source_ip=source_ip)
        except RepositoryError as exc:
            raise self._store_error(exc) from None
        return repository_to_dict(current)

    def delete_repository(self, header: object, owner: object,
                          repo: object, *,
                          source_ip: str | None = None) -> dict:
        """Request one repository's deletion,
        through S-056's own process: owner-only,
        with its 7-day grace ahead of any disk
        being reclaimed. The credential this call
        presented fresh is the re-authentication
        the web's sudo asks for (the module
        docstring states the reasoning); the answer
        names the pending deletion and when it is
        scheduled, and the repository stands
        untouched until then."""
        identity = self._caller(header, required=True)
        auth = self._authorize(identity, owner, repo, "admin", "repo")
        user = identity.user
        assert user is not None
        try:
            pending = self._deletion.request(
                user.id, auth.repository.owner, auth.repository.name,
                reauth_verifier=lambda uid: uid == user.id,
                source_ip=source_ip)
        except RepoDeletionError as exc:
            raise self._store_error(exc) from None
        return {
            "repository": repository_to_dict(auth.repository),
            "deletion": "pending",
            "requested_at": pending.requested_at,
            "scheduled_at": pending.scheduled_at,
            "grace_seconds": GRACE_SECONDS,
        }

    # -- branches ---------------------------------------------
    def list_branches(self, header: object, owner: object,
                      repo: object, *,
                      limit: int = DEFAULT_LIMIT) -> dict:
        """The repository's branches in the list
        envelope, in S-052's own listing order: each
        branch's name, the oid its tip names today,
        and whether it is protected -- judged branch
        by branch through Part VIII's own
        evaluation, the same answer the web's
        surfaces act on. Read access is the gate."""
        limit = self._check_limit(limit)
        identity = self._caller(header, required=False)
        auth = self._authorize(identity, owner, repo, "read", "repo")
        current = auth.repository
        path = self._repos.path_for(current.owner, current.name)
        rows = []
        for ref in RefStore(path).list_branches():
            try:
                protected = self._protection.is_protected(
                    identity.user, current.owner, current.name, ref.short)
            except RepositoryError as exc:
                raise self._store_error(exc) from None
            rows.append(branch_to_dict(ref.short, ref.oid, protected))
        answer = self._envelope("branches", rows, limit=limit)
        return {"repository": current.full_name, **answer}

    # -- contents ----------------------------------------------
    def get_contents(self, header: object, owner: object,
                     repo: object, path: object = None, *,
                     ref: object = None) -> dict:
        """Contents read: one path of one ref, as
        data, through Part V's shared helpers -- the
        ref resolved before any object is read, the
        path validated component by component so it
        can never climb out of its tree. A tree
        answers as its entries; a blob answers with
        its bytes base64-encoded; a gitlink answers
        as the commit it names, with no entries and
        no bytes. The default ref is the
        repository's default branch. Read only."""
        identity = self._caller(header, required=False)
        auth = self._authorize(identity, owner, repo, "read", "contents")
        current = auth.repository
        repo_path = self._repos.path_for(current.owner, current.name)
        try:
            parts = validate_repo_path(path)
            ref_name, commit_oid = resolve_commit(
                repo_path, current.default_branch if ref is None else ref)
        except RepoHomeError as exc:
            raise RepositoriesAPIError(exc.reason, str(exc)) from None
        reader = ObjectReader(repo_path)
        base = {
            "repository": current.full_name, "ref": ref_name}
        try:
            if not parts:
                commit = reader.read_commit(commit_oid)
                entries = reader.read_tree(commit.tree)
                return {
                    "path": "", "kind": "tree", "oid": commit.tree,
                    "size": None,
                    "entries": [
                        self._entry_dict(entry, parts) for entry in entries],
                    **base, "content": None, "encoding": None}
            siblings = tree_at(reader, commit_oid, parts[:-1])
        except RepoHomeError as exc:
            raise RepositoriesAPIError(exc.reason, str(exc)) from None
        except ObjectError as exc:
            raise RepositoriesAPIError(exc.reason, str(exc)) from None
        match = next(
            (entry for entry in siblings if entry.name == parts[-1]), None)
        shown = "/".join(parts)
        if match is None:
            raise RepositoriesAPIError(
                "path_not_found", f"No such path: {shown!r}")
        if match.type == "tree":
            try:
                entries = reader.read_tree(match.oid)
            except ObjectError as exc:
                raise RepositoriesAPIError(exc.reason, str(exc)) from None
            return {
                "path": shown, "kind": "tree", "oid": match.oid,
                "size": None,
                "entries": [
                    self._entry_dict(entry, parts) for entry in entries],
                **base, "content": None, "encoding": None}
        if match.type == "commit":
            return {
                "path": shown, "kind": "commit", "oid": match.oid,
                "size": None, "entries": None,
                **base, "content": None, "encoding": None}
        try:
            data = reader.read_blob(match.oid)
        except ObjectError as exc:
            raise RepositoriesAPIError(exc.reason, str(exc)) from None
        if len(data) > MAX_CONTENT_BYTES:
            raise RepositoriesAPIError(
                "content_too_large",
                f"That file is {len(data)} bytes; contents read "
                f"carries at most {MAX_CONTENT_BYTES} bytes -- "
                "fetch it through Git instead.")
        return {
            "path": shown, "kind": "blob", "oid": match.oid,
            "size": len(data), "entries": None,
            **base,
            "content": base64.b64encode(data).decode("ascii"),
            "encoding": "base64"}

    @staticmethod
    def _entry_dict(entry, parent_parts: tuple) -> dict:
        """One tree entry as data: its name, its
        full path from the repository root, its
        kind in git's own vocabulary (tree, blob,
        or commit for a gitlink), its oid, and its
        mode."""
        return {
            "name": entry.name,
            "path": "/".join((*parent_parts, entry.name)),
            "kind": entry.type,
            "oid": entry.oid,
            "mode": entry.mode,
        }

    # -- forks ---------------------------------------------------
    def list_forks(self, header: object, owner: object,
                   repo: object, *,
                   limit: int = DEFAULT_LIMIT) -> dict:
        """The repository's direct forks in the
        list envelope, name-sorted: each fork is
        the repository representation plus the
        `fork_of` it descends from. Every fork is
        filtered through S-190 for this caller
        before it is counted -- a fork its owner
        made private contributes no row and no
        count to a caller who cannot read it."""
        limit = self._check_limit(limit)
        identity = self._caller(header, required=False)
        auth = self._authorize(identity, owner, repo, "read", "repo")
        source = auth.repository
        rows = self._conn.execute(
            "SELECT id FROM repositories WHERE fork_of_id = ?"
            " ORDER BY owner_lower, name_lower", (source.id,)).fetchall()
        items = []
        for row in rows:
            fork = self._repos.get_by_id(int(row["id"]))
            if fork is None:
                continue
            if not self._engine.resolve(identity.user, fork).role:
                continue
            items.append({
                **repository_to_dict(fork),
                "fork_of": source.full_name})
        answer = self._envelope("forks", items, limit=limit)
        return {"repository": source.full_name, **answer}

    def create_fork(self, header: object, owner: object,
                    repo: object, payload: object = None, *,
                    source_ip: str | None = None) -> dict:
        """Fork one repository under the caller's
        own name, through S-055's own fork: its
        read gate, its no-visibility-escalation law,
        and its `repo.fork` witness are the store's,
        unchanged. The caller must read the source
        through S-190, and a token must additionally
        carry the write scope for the repository it
        creates."""
        body = self._payload(payload, _FORK_KEYS, required=False)
        identity = self._caller(header, required=True)
        self._authorize(identity, owner, repo, "read", "repo")
        self._require_create_scope(identity)
        user = identity.user
        assert user is not None
        try:
            fork = self._forks.fork(
                user.id, owner, repo, body.get("name"),
                visibility=body.get("visibility"),
                source_ip=source_ip)
        except ForkError as exc:
            raise self._store_error(exc) from None
        upstream = self._forks.upstream_of(fork)
        return {**repository_to_dict(fork),
                "fork_of": upstream.full_name if upstream else None}

    # -- the wire forms -------------------------------------------
    def root_json(self, header: object = None) -> str:
        return to_json(self.root(header))

    def list_repositories_json(self, header: object = None, **kwargs) -> str:
        return to_json(self.list_repositories(header, **kwargs))

    def get_repository_json(self, header: object, owner: object,
                            repo: object) -> str:
        return to_json(self.get_repository(header, owner, repo))

    def get_contents_json(self, header: object, owner: object,
                          repo: object, path: object = None, **kwargs) -> str:
        return to_json(self.get_contents(header, owner, repo, path, **kwargs))


def render_repositories_api_page() -> str:
    """The repositories API, in plain words, where
    a script's author finds it: the root, the
    collection, one repository's read, update and
    deletion request, its branches, its contents,
    and its forks -- each the programmatic face of
    a capability the web already has, judged by
    the same law. Every value escaped through
    S-010."""
    parts = [
        "<h1>Repositories API</h1>",
        "<p>Scripts work with repositories under "
        f"{escape_html_text(API_BASE)}: GET the root "
        "to discover the contract's resource "
        "families; GET and POST /repos to list the "
        "repositories you may read and to create one "
        "under your own name; GET, PATCH and DELETE "
        "one repository to read it, update its "
        "description, visibility, default branch or "
        "name, or request its deletion; GET its "
        "branches and its forks, POST to fork it "
        "under your own name, and GET its contents "
        "to read one path of one ref as data.</p>",
        "<p>Every call is judged exactly as the web "
        "judges the same act on the same repository: "
        "authentication resolves through the API "
        "door (S-238), permission through the one "
        "engine (S-190) with a token's scope as a "
        "ceiling over it, and the act itself runs "
        "through the same store the pages use. A "
        "repository you may not read answers exactly "
        "as one that does not exist. Deletion is the "
        "web's process, not an instant destroy: "
        "DELETE requests the deletion, and the "
        "repository stands through its grace period. "
        "Contents are read-only here -- the API "
        "writes files through Git, never around "
        "it.</p>",
        "<p>Refusals carry a machine-branchable "
        "reason in the one problem format: "
        "authentication_required when no credential "
        "was sent, credentials_invalid when one was "
        "sent and failed, insufficient_scope when a "
        "token lacks the scope for the call, "
        "repo_not_found for a missing or unreadable "
        "repository, and the web stores' own reasons "
        "for the acts they refuse.</p>",
    ]
    return "\n".join(parts)
