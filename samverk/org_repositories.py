"""Org repositories (S-196).

Creation policies (who may create, allowed
visibilities) and the org repo list with filters.

- **One policy per organization.** Who may create
  repositories in an organization is one of
  ``owners`` (organization owners only — the
  default), ``members`` (any member of the
  organization), or ``none`` (creation closed until
  an owner opens it again). The allowed
  visibilities are a non-empty subset of the
  repository visibilities S-050 knows — ``public``
  and ``private`` today; both are allowed by
  default, and S-197's ``internal`` joins the set
  when that slice lands. An organization that never
  set a policy lives under the default, stated in
  words wherever the policy is shown.
- **The judgement is pure.** ``decide_creation``
  takes the actor's organization role (S-186), a
  site-admin flag, the policy and the wanted
  visibility, and returns a refusal reason or
  ``None``: ``creation_disabled`` when the policy
  closes creation, ``not_org_member`` for a person
  who is not a member at all, ``owner_only`` when
  the policy is owners-only and the actor is a
  plain member, and ``visibility_not_allowed``
  when the wanted visibility is outside the
  allowed set. A site admin passes the who gates
  (instance administration is never theatre,
  S-054/S-190) but never the visibility gate: the
  allowed-visibilities policy binds everyone.
- **This slice is the creation door for
  organization repositories.** S-049's
  ``RepositoryStore.create_repository`` requires
  the actor to *be* the owner account, which no
  person is for an organization (the gap S-194's
  battery already named). ``create_repository``
  here judges the policy first, then performs
  exactly S-049's creation — S-013 path, bare
  ``git init`` through S-014's subprocess law,
  metadata row and S-124 default labels in one
  transaction that commits before the answer, the
  on-disk repo removed again if the row cannot be
  written — and audits the existing ``repo.create``
  event. A refusal changes nothing, creates
  nothing and audits nothing.
- **Only stewardship sets the policy.** Setting
  the policy is an organization owner / site admin
  act (the S-186 guard, mirrored; ``not_org_owner``
  otherwise, ``org_not_found`` for an organization
  that does not exist, ``no_such_user`` for an
  actor that does not). Setting the values already
  in effect is a no-op success that writes nothing
  and audits nothing (the same-value law every
  neighbour slice keeps).
- **The list is filtered and never leaks.** The
  org repo list filters by visibility and by a
  plain-text query over name and description (the
  pure ``repo_matches_filters``). ``list_visible``
  additionally keeps only repositories the viewer
  can read under S-190's engine — a private
  repository a viewer has no role in does not
  appear at all, not even as a count (S-054's law:
  a private repository's existence is itself
  private). Site admins see the whole list.
- **Audit:** a policy change rides the existing
  ``auth.organization.update`` event (no new
  taxonomy event — 122 stand: 31 auth / 79 repo /
  12 admin) with detail ``{"fields":
  "repositories", "action": "set_policy", ...}``;
  a creation rides ``repo.create``. Refusals and
  no-op sets write nothing and audit nothing.
- **Storage** is migration 77's
  ``org_repo_policies`` table (schema 76 to 77):
  one row per organization that has a policy set;
  no row means the default. Organizations,
  memberships and repositories stay S-185/S-186/
  S-049 ground and are only read here, except the
  repositories this slice's own door creates.
"""
from __future__ import annotations

import shutil
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .organization_members import OrgMembershipStore
from .organizations import OrganizationError
from .permission_engine import PermissionEngine
from .platform_seam import ensure_dir
from .proc import run_git
from .repo_paths import RepoPathError
from .repositories import (
    Repository, RepositoryError, RepositoryStore, VISIBILITIES,
    _row_to_repo, _validate_description, _validate_visibility,
    canonical_owner_repo, validate_branch_name)

__all__ = [
    "ALLOWED_ORDER", "DEFAULT_ALLOWED_VISIBILITIES",
    "DEFAULT_WHO_MAY_CREATE", "WHO_MAY_CREATE",
    "CreationDecision", "OrgRepoPolicy", "OrgRepoStore",
    "decide_creation", "decide_policy_change",
    "render_policy_page", "render_repo_list_page",
    "repo_matches_filters", "validate_allowed_visibilities",
    "validate_who_may_create", "visibility_word",
    "who_word",
]

WHO_MAY_CREATE = ("owners", "members", "none")
DEFAULT_WHO_MAY_CREATE = "owners"
ALLOWED_ORDER = ("public", "internal", "private")
DEFAULT_ALLOWED_VISIBILITIES = ("public", "private")

_WHO_WORDS = {
    "owners": "Organization owners only",
    "members": "Any organization member",
    "none": "No one (creation is closed)",
}
_VISIBILITY_WORDS = {"public": "Public",
                     "internal": "Internal", "private": "Private"}


def who_word(who: str) -> str:
    """Who may create, said in words a person reads."""
    return _WHO_WORDS.get(who, who)


def visibility_word(visibility: str) -> str:
    """A visibility said in a word a person reads."""
    return _VISIBILITY_WORDS.get(visibility, visibility)


def validate_who_may_create(value: object) -> str:
    """Return the canonical who-may-create value:
    written as text, judged trimmed and
    case-insensitively; anything else is refused
    ``who_may_create_invalid``."""
    if isinstance(value, str) \
            and value.strip().lower() in WHO_MAY_CREATE:
        return value.strip().lower()
    raise OrganizationError(
        "who_may_create_invalid",
        "Who may create is one of: owners, members, none.")


def validate_allowed_visibilities(value: object) -> tuple[str, ...]:
    """Return the canonical allowed-visibilities
    tuple: a non-empty subset of the S-050
    visibilities, de-duplicated and in the
    canonical order (public, private). Accepts an
    iterable of names or one comma-separated
    string. An unknown name is refused
    ``visibility_invalid`` (S-050's reason); an
    empty set is refused ``visibilities_invalid``
    — a policy that allows no visibility at all
    would be a silent creation ban wearing the
    wrong reason, so it is said plainly."""
    if isinstance(value, str):
        parts: list[object] = [
            p for p in value.replace(",", " ").split() if p]
    elif isinstance(value, (list, tuple, set, frozenset)):
        parts = list(value)
    else:
        raise OrganizationError(
            "visibilities_invalid",
            "Allowed visibilities are a list drawn from: "
            "public, private.")
    if not parts:
        raise OrganizationError(
            "visibilities_invalid",
            "At least one visibility must be allowed.")
    seen: set[str] = set()
    for part in parts:
        if not isinstance(part, str) \
                or part.strip().lower() not in VISIBILITIES:
            raise OrganizationError(
                "visibility_invalid",
                "Visibility is 'public' or 'private'.")
        seen.add(part.strip().lower())
    return tuple(v for v in ALLOWED_ORDER if v in seen)


def decide_creation(member_role: str | None,
                    is_site_admin: bool,
                    who_may_create: str,
                    visibility: str,
                    allowed_visibilities: tuple[str, ...],
                    ) -> str | None:
    """Pure creation judgement: the refusal reason,
    or None when this actor may create a repository
    of this visibility under this policy. The who
    gates are judged before the visibility gate, so
    a person who may not create at all hears that
    reason first. A site admin passes the who gates
    but never the visibility gate."""
    if not is_site_admin:
        if who_may_create == "none":
            return "creation_disabled"
        if member_role is None:
            return "not_org_member"
        if who_may_create == "owners" and member_role != "owner":
            return "owner_only"
    if visibility not in allowed_visibilities:
        return "visibility_not_allowed"
    return None


def decide_policy_change(current_who: str,
                         current_allowed: tuple[str, ...],
                         new_who: str,
                         new_allowed: tuple[str, ...],
                         ) -> str:
    """Pure set rule over already-validated values:
    ``"noop"`` when the new policy is the policy
    already in effect, else ``"set"``."""
    if current_who == new_who and current_allowed == new_allowed:
        return "noop"
    return "set"


def repo_matches_filters(repo: Repository,
                         visibility: str | None = None,
                         query: str | None = None) -> bool:
    """Pure list filter: the repository matches when
    its visibility is the filtered visibility (any
    visibility when unfiltered) and the query, when
    given, appears case-insensitively in its name
    or its description."""
    if visibility is not None and repo.visibility != visibility:
        return False
    if query:
        needle = query.strip().lower()
        if needle and needle not in repo.name_lower \
                and needle not in repo.description.lower():
            return False
    return True


@dataclass(frozen=True)
class OrgRepoPolicy:
    """One organization's repository creation
    policy: who may create, which visibilities are
    allowed, whether it was ever set, who set it
    and when. An unset policy reads as the default
    (owners only; public and private allowed)."""
    org_id: int
    org_name: str
    org_name_lower: str
    who_may_create: str
    allowed_visibilities: tuple[str, ...]
    is_set: bool
    set_by: int | None
    set_by_username: str | None
    created_at: int | None
    updated_at: int | None

    def who_word(self) -> str:
        return who_word(self.who_may_create)

    def allowed_words(self) -> str:
        return " and ".join(
            visibility_word(v) for v in self.allowed_visibilities)


@dataclass(frozen=True)
class CreationDecision:
    """The policy's answer for one actor and one
    wanted visibility: whether creation is allowed,
    the refusal reason when it is not (None when
    allowed), the actor's organization role as
    judged (None for a non-member), and the policy
    the answer came from."""
    allowed: bool
    reason: str | None
    member_role: str | None
    policy: OrgRepoPolicy


_SELECT = (
    "SELECT p.org_id AS org_id,"
    " o.name AS org_name, o.name_lower AS org_name_lower,"
    " p.who_may_create AS who_may_create,"
    " p.allowed_visibilities AS allowed_visibilities,"
    " p.set_by AS set_by, u.username AS set_by_username,"
    " p.created_at AS created_at, p.updated_at AS updated_at"
    " FROM org_repo_policies p"
    " JOIN organizations o ON o.id = p.org_id"
    " LEFT JOIN users u ON u.id = p.set_by")


def _row_to_policy(row: sqlite3.Row) -> OrgRepoPolicy:
    return OrgRepoPolicy(
        org_id=row["org_id"], org_name=row["org_name"],
        org_name_lower=row["org_name_lower"],
        who_may_create=row["who_may_create"],
        allowed_visibilities=validate_allowed_visibilities(
            row["allowed_visibilities"]),
        is_set=True, set_by=row["set_by"],
        set_by_username=row["set_by_username"],
        created_at=row["created_at"],
        updated_at=row["updated_at"])


class OrgRepoStore:
    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        data_root: Path,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn
        self._org_members = OrgMembershipStore(
            conn, accounts, audit=None, time_fn=time_fn)
        self._repos = RepositoryStore(
            conn, data_root, accounts, audit=None, time_fn=time_fn)
        self._engine = PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)

    # -- guards --------------------------------------
    def _require_org_row(self, org_id: int) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM organizations WHERE id = ?",
            (org_id,)).fetchone()
        if row is None:
            raise OrganizationError(
                "org_not_found", "No such organization.")
        return row

    def _require_actor(self, actor_id: int) -> User:
        actor = self._accounts.get_by_id(actor_id)
        if actor is None:
            raise OrganizationError(
                "no_such_user", "No such account.")
        return actor

    def _require_owner_or_admin(self, actor_id: int,
                                org_row: sqlite3.Row) -> User:
        actor = self._require_actor(actor_id)
        if actor.is_admin:
            return actor
        if self._org_members.role_for(
                actor.id, org_row["id"]) != "owner":
            raise OrganizationError(
                "not_org_owner",
                "Only an organization owner or a site admin "
                "can set this organization's repository "
                "creation policy.")
        return actor

    # -- policy reads ---------------------------------
    def get_policy(self, org_id: int) -> OrgRepoPolicy:
        """The organization's creation policy, whole:
        an organization that never set one reads as
        the default, not set. An unknown organization
        is ``org_not_found``."""
        org_row = self._require_org_row(org_id)
        row = self._conn.execute(
            _SELECT + " WHERE p.org_id = ?",
            (org_id,)).fetchone()
        if row is None:
            return OrgRepoPolicy(
                org_id=org_id, org_name=org_row["name"],
                org_name_lower=org_row["name_lower"],
                who_may_create=DEFAULT_WHO_MAY_CREATE,
                allowed_visibilities=DEFAULT_ALLOWED_VISIBILITIES,
                is_set=False, set_by=None, set_by_username=None,
                created_at=None, updated_at=None)
        return _row_to_policy(row)

    # -- policy writes --------------------------------
    def set_policy(
        self, actor_id: int, org_id: int, *,
        who_may_create: object = None,
        allowed_visibilities: object = None,
        source_ip: str | None = None,
    ) -> OrgRepoPolicy:
        """Set the creation policy. Stewardship only.
        A field left as None keeps its current value
        (S-050's metadata law). Setting the values
        already in effect is a no-op success: nothing
        is written, nothing is audited."""
        org_row = self._require_org_row(org_id)
        actor = self._require_owner_or_admin(actor_id, org_row)
        current = self.get_policy(org_id)
        new_who = current.who_may_create \
            if who_may_create is None \
            else validate_who_may_create(who_may_create)
        new_allowed = current.allowed_visibilities \
            if allowed_visibilities is None \
            else validate_allowed_visibilities(allowed_visibilities)
        if decide_policy_change(
                current.who_may_create,
                current.allowed_visibilities,
                new_who, new_allowed) == "noop":
            return current
        now = int(self._now())
        joined = ",".join(new_allowed)
        with self._conn:
            if current.is_set:
                self._conn.execute(
                    "UPDATE org_repo_policies"
                    " SET who_may_create = ?,"
                    " allowed_visibilities = ?, set_by = ?,"
                    " updated_at = ? WHERE org_id = ?",
                    (new_who, joined, actor.id, now, org_id))
            else:
                self._conn.execute(
                    "INSERT INTO org_repo_policies"
                    " (org_id, who_may_create,"
                    " allowed_visibilities, set_by,"
                    " created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (org_id, new_who, joined, actor.id, now, now))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="auth.organization.update",
                target_kind="organization",
                target_id=org_row["name_lower"],
                outcome="success", source_ip=source_ip,
                detail={"fields": "repositories",
                        "action": "set_policy",
                        "from_who": current.who_may_create,
                        "to_who": new_who,
                        "from_visibilities":
                            ",".join(current.allowed_visibilities),
                        "to_visibilities": joined})
        return self.get_policy(org_id)

    # -- creation judgement -----------------------------
    def decision_for(self, actor_id: int, org_id: int,
                     visibility: object) -> CreationDecision:
        """The policy's answer for this actor and
        wanted visibility, without creating anything:
        the wanted visibility is judged by S-050's
        validator first (``visibility_invalid``),
        then the pure ``decide_creation`` speaks."""
        org_row = self._require_org_row(org_id)
        actor = self._require_actor(actor_id)
        clean_visibility = _validate_visibility(visibility)
        policy = self.get_policy(org_id)
        member_role = self._org_members.role_for(actor.id, org_id)
        reason = decide_creation(
            member_role, bool(actor.is_admin),
            policy.who_may_create, clean_visibility,
            policy.allowed_visibilities)
        return CreationDecision(
            allowed=reason is None, reason=reason,
            member_role=member_role, policy=policy)

    def can_create(self, actor_id: int, org_id: int,
                   visibility: object) -> bool:
        """Just the yes or no of ``decision_for``."""
        return self.decision_for(actor_id, org_id, visibility).allowed

    # -- creation ---------------------------------------
    def create_repository(
        self, actor_id: int, org_id: int, name: object, *,
        description: str = "",
        visibility: str = "private",
        default_branch: str = "main",
        source_ip: str | None = None,
    ) -> Repository:
        """Create a repository owned by the
        organization, through the policy: the policy
        refusal (an ``OrganizationError`` carrying
        decide_creation's reason) comes before any
        name, disk or row work, and changes nothing.
        Past the policy, creation is S-049's exactly:
        bare git init, row + default labels in one
        transaction, disk rolled back on failure."""
        org_row = self._require_org_row(org_id)
        actor = self._require_actor(actor_id)
        clean_visibility = _validate_visibility(visibility)
        policy = self.get_policy(org_id)
        member_role = self._org_members.role_for(actor.id, org_id)
        reason = decide_creation(
            member_role, bool(actor.is_admin),
            policy.who_may_create, clean_visibility,
            policy.allowed_visibilities)
        if reason is not None:
            raise OrganizationError(
                reason, _CREATION_REFUSALS[reason])
        owner_disp, owner_lower, repo_disp, repo_lower = \
            canonical_owner_repo(org_row["name"], name)
        description = _validate_description(description)
        default_branch = validate_branch_name(default_branch)
        if self._repos.get_repository(
                owner_lower, repo_lower) is not None:
            raise RepositoryError(
                "repo_taken",
                f"{owner_disp}/{repo_disp} already exists.")
        try:
            path = self._repos.path_for(owner_disp, repo_disp)
        except RepoPathError as exc:
            raise RepositoryError("repo_invalid", str(exc)) from None
        if path.exists():
            raise RepositoryError(
                "repo_path_exists",
                "A directory already exists at that repository's "
                "path; refusing to adopt it silently.")
        ensure_dir(path.parent)
        result = run_git(
            ["init", "--bare",
             f"--initial-branch={default_branch}", str(path)],
            timeout=30.0)
        if result.returncode != 0:
            shutil.rmtree(path, ignore_errors=True)
            raise RepositoryError(
                "git_init_failed",
                "git could not create the repository: "
                + result.stderr.decode(
                    "utf-8", "replace").strip()[:200])
        now = int(self._now())
        from .labels import seed_defaults_tx
        try:
            with self._conn:
                cur = self._conn.execute(
                    "INSERT INTO repositories (owner, owner_lower,"
                    " name, name_lower, created_by, created_at,"
                    " description, visibility, default_branch)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (owner_disp, owner_lower, repo_disp, repo_lower,
                     actor.id, now, description, clean_visibility,
                     default_branch))
                seed_defaults_tx(self._conn, int(cur.lastrowid), now)
        except sqlite3.IntegrityError:
            shutil.rmtree(path, ignore_errors=True)
            raise RepositoryError(
                "repo_taken",
                f"{owner_disp}/{repo_disp} already exists.") from None
        created = self._repos.get_by_id(int(cur.lastrowid))
        assert created is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.create", target_kind="repo",
                target_id=created.full_name, outcome="success",
                source_ip=source_ip,
                detail={"visibility": created.visibility,
                        "org": owner_lower, "via": "org_policy"})
        return created

    # -- the list ---------------------------------------
    def list_repositories(
        self, org_id: int, *,
        visibility: object = None,
        query: str | None = None,
    ) -> list[Repository]:
        """Every repository the organization owns,
        in name order, narrowed by the filters: a
        visibility filter is judged by S-050's
        validator (``visibility_invalid`` otherwise)
        and the query matches name or description.
        This is the steward's whole list; a viewer's
        list is ``list_visible``."""
        org_row = self._require_org_row(org_id)
        clean_visibility = None if visibility is None \
            else _validate_visibility(visibility)
        rows = self._conn.execute(
            "SELECT * FROM repositories"
            " WHERE owner_lower = ? ORDER BY name_lower",
            (org_row["name_lower"],)).fetchall()
        repos = [_row_to_repo(r) for r in rows]
        return [r for r in repos if repo_matches_filters(
            r, clean_visibility, query)]

    def list_visible(
        self, org_id: int, viewer: User | None, *,
        visibility: object = None,
        query: str | None = None,
    ) -> list[Repository]:
        """The list as this viewer may see it: the
        filtered whole list, minus every repository
        S-190's engine gives the viewer no role in —
        a private repository never appears, not even
        in a count. A site admin sees the whole
        list; an anonymous viewer (None) sees only
        what visibility alone grants."""
        repos = self.list_repositories(
            org_id, visibility=visibility, query=query)
        if viewer is not None and viewer.is_admin:
            return repos
        return [r for r in repos
                if self._engine.role_for(viewer, r) is not None]


_CREATION_REFUSALS = {
    "creation_disabled":
        "Repository creation is closed for this organization.",
    "not_org_member":
        "Only a member of the organization can create "
        "its repositories.",
    "owner_only":
        "Only an organization owner can create "
        "repositories in this organization.",
    "visibility_not_allowed":
        "That visibility is not allowed by this "
        "organization's repository creation policy.",
}


def render_policy_page(policy: OrgRepoPolicy) -> str:
    """The creation policy, shown in effect: who may
    create and which visibilities are allowed, in
    words, with the default said plainly when the
    policy was never set — every value escaped
    through S-010, the state said in text, never
    colour-only."""
    if policy.is_set:
        setter = policy.set_by_username or "an organization owner"
        state = (f"The repository creation policy for "
                 f"{policy.org_name} was set by {setter}.")
    else:
        state = (f"{policy.org_name} has no repository creation "
                 f"policy set: the default policy applies.")
    effect = (f"Who may create repositories: "
              f"{policy.who_word()}. Allowed visibilities: "
              f"{policy.allowed_words()}. A site admin may "
              f"create under any who setting, but the allowed "
              f"visibilities bind everyone, site admins "
              f"included.")
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Repository creation policy — "
        f"{escape_html_text(policy.org_name)} — "
        f"Samverk</title></head>",
        "<body>",
        f"<h1>Repository creation policy — "
        f"{escape_html_text(policy.org_name)}</h1>",
        f"<p>{escape_html_text(state)}</p>",
        f"<p>{escape_html_text(effect)}</p>",
        "<p>Only an organization owner or a site admin can "
        "set this policy. Public repositories can be read "
        "by anyone; private repositories only by the people "
        "the permission engine (S-190) grants a role.</p>",
        "</body></html>",
    ]
    return "\n".join(parts)


def render_repo_list_page(org_name: str,
                          repos: list[Repository], *,
                          visibility: str | None = None,
                          query: str | None = None) -> str:
    """The org repo list: each repository's full name,
    visibility said in words and its description,
    with the active filters stated in text — every
    value escaped through S-010, never colour-only.
    The list handed in is already the viewer's list
    (``list_visible``); this renderer hides nothing
    and invents nothing."""
    filters = []
    if visibility is not None:
        filters.append(f"visibility is {visibility_word(visibility)}")
    if query:
        filters.append(f"matching “{query}”")
    filter_line = ("Filters: " + "; ".join(filters) + ".") \
        if filters else "No filters."
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Repositories — "
        f"{escape_html_text(org_name)} — Samverk</title></head>",
        "<body>",
        f"<h1>Repositories of {escape_html_text(org_name)}</h1>",
        f"<p>{escape_html_text(filter_line)}</p>",
        f"<p>{len(repos)} "
        f"{'repository' if len(repos) == 1 else 'repositories'}"
        f" shown.</p>",
        "<ul>",
    ]
    for repo in repos:
        line = (f"{repo.full_name} — "
                f"{visibility_word(repo.visibility)}")
        if repo.description:
            line += f" — {repo.description}"
        parts.append(
            f"<li>{escape_html_text(line)}</li>")
    parts.append("</ul></body></html>")
    return "\n".join(parts)
