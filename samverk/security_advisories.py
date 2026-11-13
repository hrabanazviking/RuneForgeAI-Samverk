"""Security advisories (private) (S-310).

Roadmap S-310: Security advisories (private) --
maintainers draft an advisory in private, coordinate
a fix, then publish with the alert linkage.

Part XV raised the alerts one family at a time --
secret alerts (S-291/S-294), dependency alerts
(S-297's graph x S-298's snapshot, joined by S-299)
and code-scanning alerts (S-302--S-304) -- and
S-307/S-308 gathered their standing counts. What no
slice yet built is the maintainer's own instrument
for answering a vulnerability that is not ready for
the world: a repository *security advisory*, drafted
in private, worked on in private while a fix is
coordinated, and published only when the fix and
the words are ready -- carrying, at publication,
its linkage to the standing alerts it answers.

- **Private by construction, not by flag.** An
  advisory is born ``draft`` and a draft is visible
  to the repository's maintainers alone -- the
  ``admin`` and ``maintain`` rungs of S-190's
  permission engine, the rungs S-294 trusts to move
  an alert. To everyone else a draft does not
  exist: every read of one answers the uniform
  ``advisory_not_found``, exactly as a stranger to
  a private repository hears ``repo_not_found``.
  There is no surface on which a draft's title,
  severity or existence can be enumerated by a
  non-maintainer, on a public repository any more
  than on a private one.
- **Coordination is recorded while it is private.**
  In its draft life an advisory carries its working
  facts -- title, summary, description, severity,
  the affected dependency (ecosystem, name, affected
  range, fixed version where one is known -- *fix
  unknown*, honestly ``None``, where none is), an
  external identifier (a CVE id) where one stands,
  and the fix reference (the commit or pull request
  the fix rides on). Maintainers edit those facts
  and link standing alerts to the advisory; every
  act -- create, update, link, unlink, publish,
  withdraw -- stands on migration 128's
  ``security_advisory_events`` record, written in
  the same transaction as the change it records,
  so the coordination history is complete before
  anything is published.
- **The alert linkage is the publication's spine.**
  A link names one standing alert of one of the
  three families (``secret`` / ``dependency`` /
  ``code_scanning``) in *this* repository: the
  alert row must stand here or the link is refused
  ``alert_not_found`` -- an advisory can never
  claim another repository's alert, and never a
  number that names nothing. One alert links to
  one advisory once (``alert_already_linked``).
  Links are made and unmade in draft only: at
  publication the linkage freezes as it stands,
  part of the published record.
- **Publication is a judged act.** The pure
  ``decide_publish`` judges the ask in the house
  order -- the advisory's own state first (a
  published advisory is ``advisory_already_published``,
  a withdrawn one ``advisory_withdrawn``), then the
  actor's rung (``advisory_not_permitted``), then
  completeness: a title and a summary in words, a
  severity inside the vocabulary, and the linkage
  or the affected dependency named -- an advisory
  that answers nothing identifiable is refused
  ``advisory_incomplete`` and stays a draft. A
  landed publish stamps publisher and time on the
  row and stands on the events record in the same
  transaction.
- **Published means readable; withdrawn stays
  honest.** A published advisory reads to anyone
  holding any role in the repository (an anonymous
  reader of a public repository included, through
  the engine's visibility role), with its frozen
  linkage and its snapshot of the affected facts.
  A maintainer may withdraw a draft or a published
  advisory, with a stated reason always recorded
  (``reason_required`` / ``reason_too_long``, the
  lifecycle law): a withdrawn advisory stays
  readable in its withdrawn state, its reason in
  words -- it is never silently deleted, and it
  never publishes again.
- **Unwitnessed in the audit taxonomy -- said
  plainly.** No new taxonomy event: 135 stand
  (33 auth / 89 repo / 13 admin), and the battery
  proves the audit log does not move across a
  create, an update, a link, a publish and a
  withdraw. The reasoning is the neighbours':
  S-294's and S-299's lifecycle transitions are
  unwitnessed for the same cause -- they change no
  code and land no push, and their witness is
  their own events record, complete and
  in-transaction. An advisory's witness is its
  events record on the same terms.

Storage is migration 128's ``security_advisories``,
``security_advisory_alerts`` and
``security_advisory_events`` tables (schema
127 -> 128). The affected dependency's name column
is ``dependency_name`` by design: S-264/S-265's
registry audit refuses any schema name carrying
the registry's own words, and an advisory is not
a registry (S-299's lesson, kept).
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .permission_engine import PermissionEngine
from .repositories import RepositoryError, RepositoryStore
from .team_permissions import role_word

__all__ = [
    "FAMILIES", "FAMILY_TABLES", "PERMITTED_ROLES",
    "SEVERITIES", "STATES", "TITLE_MAX", "SUMMARY_MAX",
    "DESCRIPTION_MAX", "REASON_MAX",
    "AdvisoryError", "AdvisoryEvent", "AdvisoryLink",
    "PublishDecision", "SecurityAdvisory",
    "SecurityAdvisoryStore", "advisory_to_dict",
    "audit_security_advisories", "decide_publish",
    "decide_visibility", "render_advisories_page",
    "render_advisory_page", "validate_reason",
    "validate_severity",
]

#: The life of an advisory, in order. ``draft`` is
#: the private working state; ``published`` is the
#: public record; ``withdrawn`` is the honest end
#: of either, with its reason standing.
STATES = ("draft", "published", "withdrawn")

#: The severity vocabulary, S-298/S-299's own,
#: most severe first.
SEVERITIES = ("critical", "high", "moderate", "low")

#: The three alert families an advisory may link,
#: and the table each family's alerts stand in.
FAMILIES = ("secret", "dependency", "code_scanning")
FAMILY_TABLES = {
    "secret": "secret_alerts",
    "dependency": "dependency_alerts",
    "code_scanning": "code_scanning_alerts",
}

#: The rungs that may draft, coordinate and publish:
#: the two that already answer for a repository's
#: safety (S-294's law, S-190's ladder).
PERMITTED_ROLES = frozenset({"admin", "maintain"})

TITLE_MAX = 200
SUMMARY_MAX = 2000
DESCRIPTION_MAX = 10000
REASON_MAX = 500
FIELD_MAX = 500


class AdvisoryError(RepositoryError):
    """A security-advisory error: a RepositoryError
    carrying `.reason`, in the house shape."""


# ---------------------------------------------------------------------
# Validation (named refusals; nothing is defaulted silently)
# ---------------------------------------------------------------------

def _clean_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _validate_title(value: object) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        raise AdvisoryError(
            "title_required",
            "An advisory needs a title: the one line "
            "a reader meets first.")
    if len(cleaned) > TITLE_MAX:
        raise AdvisoryError(
            "title_too_long",
            f"An advisory title is at most {TITLE_MAX} "
            f"characters; this one runs {len(cleaned)}.")
    return cleaned


def _validate_summary(value: object, *, required: bool) -> str:
    cleaned = _clean_text(value)
    if required and not cleaned:
        raise AdvisoryError(
            "summary_required",
            "An advisory needs a summary in words: "
            "what is wrong, said plainly.")
    if len(cleaned) > SUMMARY_MAX:
        raise AdvisoryError(
            "summary_too_long",
            f"An advisory summary is at most "
            f"{SUMMARY_MAX} characters; this one "
            f"runs {len(cleaned)}.")
    return cleaned


def _validate_description(value: object) -> str:
    cleaned = _clean_text(value)
    if len(cleaned) > DESCRIPTION_MAX:
        raise AdvisoryError(
            "description_too_long",
            f"An advisory description is at most "
            f"{DESCRIPTION_MAX} characters; this one "
            f"runs {len(cleaned)}.")
    return cleaned


def _validate_field(name: str, value: object) -> str:
    cleaned = _clean_text(value)
    if len(cleaned) > FIELD_MAX:
        raise AdvisoryError(
            f"{name}_too_long",
            f"An advisory's {name} is at most "
            f"{FIELD_MAX} characters; this one runs "
            f"{len(cleaned)}.")
    return cleaned


def validate_severity(value: object) -> str:
    """The severity, cleaned -- or a named refusal
    naming the four severities that stand."""
    if not isinstance(value, str) or value not in SEVERITIES:
        raise AdvisoryError(
            "severity_invalid",
            f"Unknown severity: {value!r}. An advisory "
            "stands critical, high, moderate or low "
            "-- no other severity stands.")
    return value


def validate_reason(reason: object) -> str:
    """The stated reason, cleaned -- or a named
    refusal (S-294's law: an act without its reason
    is an unaccountable act)."""
    if not isinstance(reason, str) or not reason.strip():
        raise AdvisoryError(
            "reason_required",
            "This act needs a stated reason: the "
            "actor's own words for why. An act "
            "without its reason is unaccountable, "
            "and this slice builds none.")
    cleaned = reason.strip()
    if len(cleaned) > REASON_MAX:
        raise AdvisoryError(
            "reason_too_long",
            f"A stated reason is at most {REASON_MAX} "
            f"characters; this one runs {len(cleaned)}.")
    return cleaned


# ---------------------------------------------------------------------
# The pure judgements
# ---------------------------------------------------------------------

def decide_visibility(*, state: object, role: str | None) -> bool:
    """May a holder of *role* see an advisory in
    *state*? Pure. Published and withdrawn
    advisories are visible to any role (the engine
    already answers None for a person with no
    standing in the repository); a draft is visible
    to the maintainer rungs alone -- to everyone
    else it does not exist. An unknown state is
    visible to no one."""
    if state in ("published", "withdrawn"):
        return role is not None
    if state == "draft":
        return role in PERMITTED_ROLES
    return False


@dataclass(frozen=True)
class PublishDecision:
    """The pure judgement on one publish ask: may
    it land, and if not, under what named code and
    sentence? `words` says the whole position."""
    may_publish: bool
    code: str              # "" when may_publish
    reason: str            # the refusal sentence; "" when may_publish
    words: str


def decide_publish(*, state: object, role: str | None,
                   source: str = "none",
                   actor: str | None = None,
                   full_name: str = "",
                   title: object = "",
                   summary: object = "",
                   severity: object = "",
                   linked_count: int = 0,
                   dependency_name: object = "") -> PublishDecision:
    """Judge one publish ask, in the house order:
    the advisory's own state first, then the
    actor's rung, then completeness (title and
    summary in words, a severity inside the
    vocabulary, and the alert linkage or the
    affected dependency named). Pure: writes
    nothing, records nothing."""
    who = f"'{actor}'" if actor else "an anonymous actor"
    if state == "published":
        return PublishDecision(
            may_publish=False, code="advisory_already_published",
            reason=(
                f"This advisory in {full_name} already "
                "stands published; it cannot be "
                "published again."),
            words=(
                f"The advisory in {full_name} already "
                "stands published: publishing it again "
                "would rewrite the published record."))
    if state == "withdrawn":
        return PublishDecision(
            may_publish=False, code="advisory_withdrawn",
            reason=(
                f"This advisory in {full_name} stands "
                "withdrawn; a withdrawn advisory never "
                "publishes again. Draft a new advisory "
                "if the finding stands anew."),
            words=(
                f"The advisory in {full_name} stands "
                "withdrawn: its record is closed, and "
                "it stays readable in that state."))
    if state != "draft":
        return PublishDecision(
            may_publish=False, code="state_invalid",
            reason=(
                f"This advisory in {full_name} stands "
                f"in state {state!r}, which is not a "
                "state an advisory can publish from."),
            words=(
                f"The advisory in {full_name} stands "
                f"{state!r}: only a draft publishes."))
    if role not in PERMITTED_ROLES:
        held = (f"holds the {role_word(role)} role"
                if role else "holds no role")
        return PublishDecision(
            may_publish=False, code="advisory_not_permitted",
            reason=(
                f"Publishing an advisory in {full_name} "
                f"was refused: {who} {held}, and only "
                "the permitted roles may publish a "
                "security advisory (maintain, admin). "
                "Ask a repository maintainer to act, "
                "or be granted a permitted role first."),
            words=(
                f"{who} may not publish an advisory in "
                f"{full_name}: only maintain and admin "
                "may, and every publication records "
                "its publisher."))
    missing: list[str] = []
    if not _clean_text(title):
        missing.append("a title")
    if not _clean_text(summary):
        missing.append("a summary in words")
    if severity not in SEVERITIES:
        missing.append("a severity inside the vocabulary")
    if linked_count <= 0 and not _clean_text(dependency_name):
        missing.append(
            "the alert linkage or the affected dependency named")
    if missing:
        return PublishDecision(
            may_publish=False, code="advisory_incomplete",
            reason=(
                f"This advisory in {full_name} is not "
                f"ready to publish: it still needs "
                f"{', '.join(missing)}. It stays a "
                "draft until it stands complete."),
            words=(
                f"The advisory in {full_name} stays a "
                f"draft: publication needs "
                f"{', '.join(missing)}."))
    return PublishDecision(
        may_publish=True, code="", reason="",
        words=(
            f"{who} may publish the advisory in "
            f"{full_name} as {role_word(role)}: it "
            "stands complete, with its alert linkage "
            "frozen into the published record."))


# ---------------------------------------------------------------------
# The records
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class AdvisoryLink:
    """One standing link from an advisory to one
    alert of one family in the same repository."""
    id: int
    advisory_id: int
    repo_id: int
    family: str
    alert_id: int
    created_by_id: int
    created_by: str
    created_at: int

    def words(self) -> str:
        return f"{self.family} alert {self.alert_id}"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "advisory_id": self.advisory_id,
            "family": self.family, "alert_id": self.alert_id,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class AdvisoryEvent:
    """One standing act on an advisory's own record:
    who acted, from what state to what state, and
    the act's detail in words."""
    id: int
    advisory_id: int
    repo_id: int
    action: str            # create|update|link|unlink|publish|withdraw
    from_state: str
    to_state: str
    actor_id: int
    actor_username: str
    role: str
    role_source: str
    detail: str
    created_at: int

    def words(self) -> str:
        return (f"{self.actor_username} ({self.action}): "
                f"{self.detail}")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "advisory_id": self.advisory_id,
            "action": self.action,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "actor_id": self.actor_id,
            "actor": self.actor_username,
            "role": self.role, "role_source": self.role_source,
            "detail": self.detail,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class SecurityAdvisory:
    """One repository security advisory with its
    standing facts and its frozen alert linkage."""
    id: int
    repo_id: int
    full_name: str
    advisory_key: str
    title: str
    summary: str
    description: str
    severity: str
    ecosystem: str
    dependency_name: str
    affected: str
    fixed_version: str | None   # None: fix unknown, never invented
    cve_id: str
    fix_reference: str
    state: str
    created_by_id: int
    created_by: str
    published_by_id: int | None
    published_by: str
    published_at: int | None
    withdrawn_by_id: int | None
    withdrawn_by: str
    withdrawn_at: int | None
    withdrawn_reason: str
    created_at: int
    updated_at: int
    links: tuple = ()

    @property
    def is_draft(self) -> bool:
        return self.state == "draft"

    @property
    def is_published(self) -> bool:
        return self.state == "published"

    def fixed_words(self) -> str:
        """The fix position in words: the fixed
        version where one is known, *fix unknown*
        where none is -- never an invented version."""
        if self.fixed_version:
            return f"fixed in {self.fixed_version}"
        return "fix unknown"

    def words(self) -> str:
        """The advisory's position in one sentence."""
        base = (f"{self.advisory_key} [{self.state}] "
                f"{self.title} -- severity {self.severity}, "
                f"{self.fixed_words()}")
        if self.dependency_name:
            base += (f"; affects {self.ecosystem}: "
                     f"{self.dependency_name} "
                     f"({self.affected or 'range unstated'})")
        base += f"; {len(self.links)} linked alert(s)."
        if self.state == "withdrawn":
            base += f" Withdrawn: {self.withdrawn_reason}"
        return base

    def to_dict(self) -> dict:
        return advisory_to_dict(self)


def advisory_to_dict(advisory: SecurityAdvisory) -> dict:
    return {
        "id": advisory.id,
        "repository": advisory.full_name,
        "advisory_key": advisory.advisory_key,
        "title": advisory.title,
        "summary": advisory.summary,
        "description": advisory.description,
        "severity": advisory.severity,
        "ecosystem": advisory.ecosystem or None,
        "dependency_name": advisory.dependency_name or None,
        "affected": advisory.affected or None,
        "fixed_version": advisory.fixed_version,
        "cve_id": advisory.cve_id or None,
        "fix_reference": advisory.fix_reference or None,
        "state": advisory.state,
        "created_by": advisory.created_by,
        "published_by": advisory.published_by or None,
        "published_at": advisory.published_at,
        "withdrawn_by": advisory.withdrawn_by or None,
        "withdrawn_at": advisory.withdrawn_at,
        "withdrawn_reason": advisory.withdrawn_reason or None,
        "created_at": advisory.created_at,
        "updated_at": advisory.updated_at,
        "links": [link.to_dict() for link in advisory.links],
        "words": advisory.words(),
    }


def _row_to_link(row) -> AdvisoryLink:
    return AdvisoryLink(
        id=int(row["id"]), advisory_id=int(row["advisory_id"]),
        repo_id=int(row["repo_id"]), family=row["family"],
        alert_id=int(row["alert_id"]),
        created_by_id=int(row["created_by_id"]),
        created_by=row["created_by"],
        created_at=int(row["created_at"]))


def _row_to_event(row) -> AdvisoryEvent:
    return AdvisoryEvent(
        id=int(row["id"]), advisory_id=int(row["advisory_id"]),
        repo_id=int(row["repo_id"]), action=row["action"],
        from_state=row["from_state"], to_state=row["to_state"],
        actor_id=int(row["actor_id"]),
        actor_username=row["actor_username"],
        role=row["role"], role_source=row["role_source"],
        detail=row["detail"],
        created_at=int(row["created_at"]))


# ---------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------

class SecurityAdvisoryStore:
    """The life of a repository's security
    advisories: drafted in private by maintainers,
    coordinated in private, published with their
    alert linkage frozen in."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 accounts: AccountStore,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._now = time_fn
        self._engine = PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)

    # -- the door ---------------------------------------------------

    def _resolve_repo(self, viewer: User | None, owner, repo,
                      *, any_role: bool):
        """(repository, resolution). A missing
        repository answers `repo_not_found`; so does
        a non-public repository the viewer holds no
        role in, before any advisory position is
        named (S-294's door, carried whole)."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise AdvisoryError(
                "repo_not_found", "No such repository.")
        resolution = self._engine.resolve(viewer, current)
        if resolution.role is None \
                and current.visibility != "public":
            raise AdvisoryError(
                "repo_not_found", "No such repository.")
        if any_role and resolution.role is None:
            raise AdvisoryError(
                "repo_not_found", "No such repository.")
        return current, resolution

    def _require_maintainer(self, resolution, actor, full_name,
                            verb: str) -> None:
        if resolution.role not in PERMITTED_ROLES:
            who = (f"'{actor.username}'" if actor is not None
                   else "an anonymous actor")
            held = (f"holds the {role_word(resolution.role)} role"
                    if resolution.role else "holds no role")
            raise AdvisoryError(
                "advisory_not_permitted",
                f"Security-advisory {verb} in {full_name} "
                f"was refused: {who} {held}, and only the "
                "permitted roles may work on a security "
                "advisory (maintain, admin). Ask a "
                "repository maintainer to act, or be "
                "granted a permitted role first.")

    # -- rows ---------------------------------------------------------

    def _links_for(self, advisory_id: int) -> tuple:
        rows = self._conn.execute(
            "SELECT * FROM security_advisory_alerts"
            " WHERE advisory_id = ? ORDER BY id",
            (advisory_id,)).fetchall()
        return tuple(_row_to_link(r) for r in rows)

    def _row_to_advisory(self, row, full_name: str,
                         *, with_links: bool = True
                         ) -> SecurityAdvisory:
        return SecurityAdvisory(
            id=int(row["id"]), repo_id=int(row["repo_id"]),
            full_name=full_name,
            advisory_key=row["advisory_key"],
            title=row["title"], summary=row["summary"],
            description=row["description"],
            severity=row["severity"],
            ecosystem=row["ecosystem"],
            dependency_name=row["dependency_name"],
            affected=row["affected"],
            fixed_version=row["fixed_version"],
            cve_id=row["cve_id"],
            fix_reference=row["fix_reference"],
            state=row["state"],
            created_by_id=int(row["created_by_id"]),
            created_by=row["created_by"],
            published_by_id=row["published_by_id"],
            published_by=row["published_by"] or "",
            published_at=row["published_at"],
            withdrawn_by_id=row["withdrawn_by_id"],
            withdrawn_by=row["withdrawn_by"] or "",
            withdrawn_at=row["withdrawn_at"],
            withdrawn_reason=row["withdrawn_reason"] or "",
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
            links=self._links_for(int(row["id"]))
            if with_links else ())

    def _advisory_row(self, repo_id: int, advisory_id: int):
        row = self._conn.execute(
            "SELECT * FROM security_advisories"
            " WHERE id = ? AND repo_id = ?",
            (advisory_id, repo_id)).fetchone()
        if row is None:
            raise AdvisoryError(
                "advisory_not_found",
                f"No security advisory {advisory_id} "
                "stands in this repository.")
        return row

    def _record_event(self, *, advisory_id: int, repo_id: int,
                      action: str, from_state: str, to_state: str,
                      actor: User, resolution,
                      detail: str, created_at: int) -> None:
        """One row on the advisory's own record.
        Always called inside the transaction that
        makes the change it records."""
        self._conn.execute(
            "INSERT INTO security_advisory_events ("
            " advisory_id, repo_id, action, from_state,"
            " to_state, actor_id, actor_username, role,"
            " role_source, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (advisory_id, repo_id, action, from_state,
             to_state, actor.id, actor.username,
             resolution.role, resolution.source,
             detail, created_at))

    # -- the acts -----------------------------------------------------

    def create_advisory(self, actor: User | None, owner, repo, *,
                        title: object, summary: object = "",
                        description: object = "",
                        severity: object = "moderate",
                        ecosystem: object = "",
                        dependency_name: object = "",
                        affected: object = "",
                        fixed_version: object = None,
                        cve_id: object = "",
                        fix_reference: object = ""
                        ) -> SecurityAdvisory:
        """Draft a new advisory in private. Only a
        maintainer may draft; the draft is born
        invisible to everyone else."""
        current, resolution = self._resolve_repo(
            actor, owner, repo, any_role=False)
        self._require_maintainer(
            resolution, actor, current.full_name, "create")
        clean_title = _validate_title(title)
        clean_summary = _validate_summary(summary, required=False)
        clean_description = _validate_description(description)
        clean_severity = validate_severity(severity)
        clean_ecosystem = _validate_field("ecosystem", ecosystem)
        clean_dependency = _validate_field(
            "dependency_name", dependency_name)
        clean_affected = _validate_field("affected", affected)
        clean_fixed = _validate_field(
            "fixed_version", fixed_version) or None
        clean_cve = _validate_field("cve_id", cve_id)
        clean_fix_ref = _validate_field(
            "fix_reference", fix_reference)
        now = int(self._now())
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO security_advisories ("
                " repo_id, advisory_key, title, summary,"
                " description, severity, ecosystem,"
                " dependency_name, affected, fixed_version,"
                " cve_id, fix_reference, state,"
                " created_by_id, created_by, created_at,"
                " updated_at) VALUES (?, '', ?, ?, ?, ?,"
                " ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)",
                (current.id, clean_title, clean_summary,
                 clean_description, clean_severity,
                 clean_ecosystem, clean_dependency,
                 clean_affected, clean_fixed, clean_cve,
                 clean_fix_ref, actor.id, actor.username,
                 now, now))
            advisory_id = int(cursor.lastrowid)
            key = f"SAMVERK-ADV-{advisory_id:04d}"
            self._conn.execute(
                "UPDATE security_advisories SET advisory_key = ?"
                " WHERE id = ?", (key, advisory_id))
            self._record_event(
                advisory_id=advisory_id, repo_id=current.id,
                action="create", from_state="", to_state="draft",
                actor=actor, resolution=resolution,
                detail=f"drafted in private: {clean_title}",
                created_at=now)
        return self._get(current, advisory_id)

    def update_advisory(self, actor: User | None, owner, repo,
                        advisory_id: int, *,
                        title: object = None,
                        summary: object = None,
                        description: object = None,
                        severity: object = None,
                        ecosystem: object = None,
                        dependency_name: object = None,
                        affected: object = None,
                        fixed_version: object = ...,
                        cve_id: object = None,
                        fix_reference: object = None
                        ) -> SecurityAdvisory:
        """Edit a draft's working facts. A published
        or withdrawn advisory is a record, not a
        draft: it refuses `advisory_not_editable`."""
        current, resolution = self._resolve_repo(
            actor, owner, repo, any_role=False)
        self._require_maintainer(
            resolution, actor, current.full_name, "update")
        row = self._advisory_row(current.id, advisory_id)
        if row["state"] != "draft":
            raise AdvisoryError(
                "advisory_not_editable",
                f"This advisory in {current.full_name} "
                f"stands {row['state']}: only a draft "
                "can be edited. Its record stands as "
                "published or withdrawn.")
        updates: dict[str, object] = {}
        if title is not None:
            updates["title"] = _validate_title(title)
        if summary is not None:
            updates["summary"] = _validate_summary(
                summary, required=False)
        if description is not None:
            updates["description"] = _validate_description(description)
        if severity is not None:
            updates["severity"] = validate_severity(severity)
        if ecosystem is not None:
            updates["ecosystem"] = _validate_field(
                "ecosystem", ecosystem)
        if dependency_name is not None:
            updates["dependency_name"] = _validate_field(
                "dependency_name", dependency_name)
        if affected is not None:
            updates["affected"] = _validate_field("affected", affected)
        if fixed_version is not ...:
            updates["fixed_version"] = _validate_field(
                "fixed_version", fixed_version) or None
        if cve_id is not None:
            updates["cve_id"] = _validate_field("cve_id", cve_id)
        if fix_reference is not None:
            updates["fix_reference"] = _validate_field(
                "fix_reference", fix_reference)
        if not updates:
            raise AdvisoryError(
                "update_empty",
                "An advisory update must change at "
                "least one field; this one changes none.")
        now = int(self._now())
        assignments = ", ".join(f"{name} = ?" for name in updates)
        with self._conn:
            self._conn.execute(
                f"UPDATE security_advisories SET {assignments},"
                " updated_at = ? WHERE id = ?",
                (*updates.values(), now, advisory_id))
            self._record_event(
                advisory_id=advisory_id, repo_id=current.id,
                action="update", from_state="draft",
                to_state="draft", actor=actor,
                resolution=resolution,
                detail=("updated fields: "
                        + ", ".join(sorted(updates))),
                created_at=now)
        return self._get(current, advisory_id)

    def link_alert(self, actor: User | None, owner, repo,
                   advisory_id: int, *, family: object,
                   alert_id: object) -> SecurityAdvisory:
        """Link one standing alert of this repository
        to a draft advisory -- the linkage that will
        freeze at publication."""
        current, resolution = self._resolve_repo(
            actor, owner, repo, any_role=False)
        self._require_maintainer(
            resolution, actor, current.full_name, "link")
        row = self._advisory_row(current.id, advisory_id)
        if row["state"] != "draft":
            raise AdvisoryError(
                "advisory_not_editable",
                f"This advisory in {current.full_name} "
                f"stands {row['state']}: its alert "
                "linkage froze at publication and "
                "cannot change now.")
        if family not in FAMILIES:
            raise AdvisoryError(
                "family_invalid",
                f"Unknown alert family: {family!r}. An "
                "advisory links secret, dependency or "
                "code_scanning alerts -- no other family "
                "stands.")
        try:
            alert_n = int(alert_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise AdvisoryError(
                "alert_not_found",
                f"No {family} alert {alert_id!r} stands "
                f"in {current.full_name}.") from None
        table = FAMILY_TABLES[family]  # type: ignore[index]
        found = self._conn.execute(
            f"SELECT id FROM {table} WHERE id = ? AND repo_id = ?",
            (alert_n, current.id)).fetchone()
        if found is None:
            raise AdvisoryError(
                "alert_not_found",
                f"No {family} alert {alert_n} stands in "
                f"{current.full_name}: an advisory links "
                "only its own repository's standing alerts.")
        existing = self._conn.execute(
            "SELECT id FROM security_advisory_alerts"
            " WHERE advisory_id = ? AND family = ?"
            " AND alert_id = ?",
            (advisory_id, family, alert_n)).fetchone()
        if existing is not None:
            raise AdvisoryError(
                "alert_already_linked",
                f"{family} alert {alert_n} already "
                "stands linked to this advisory.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO security_advisory_alerts ("
                " advisory_id, repo_id, family, alert_id,"
                " created_by_id, created_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (advisory_id, current.id, family, alert_n,
                 actor.id, actor.username, now))
            self._conn.execute(
                "UPDATE security_advisories SET updated_at = ?"
                " WHERE id = ?", (now, advisory_id))
            self._record_event(
                advisory_id=advisory_id, repo_id=current.id,
                action="link", from_state="draft",
                to_state="draft", actor=actor,
                resolution=resolution,
                detail=f"linked {family} alert {alert_n}",
                created_at=now)
        return self._get(current, advisory_id)

    def unlink_alert(self, actor: User | None, owner, repo,
                     advisory_id: int, *, family: object,
                     alert_id: object) -> SecurityAdvisory:
        """Unmake one link while the advisory still
        stands a draft."""
        current, resolution = self._resolve_repo(
            actor, owner, repo, any_role=False)
        self._require_maintainer(
            resolution, actor, current.full_name, "unlink")
        row = self._advisory_row(current.id, advisory_id)
        if row["state"] != "draft":
            raise AdvisoryError(
                "advisory_not_editable",
                f"This advisory in {current.full_name} "
                f"stands {row['state']}: its alert "
                "linkage froze at publication and "
                "cannot change now.")
        if family not in FAMILIES:
            raise AdvisoryError(
                "family_invalid",
                f"Unknown alert family: {family!r}.")
        try:
            alert_n = int(alert_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise AdvisoryError(
                "link_not_found",
                f"No link to {family} alert {alert_id!r} "
                "stands on this advisory.") from None
        existing = self._conn.execute(
            "SELECT id FROM security_advisory_alerts"
            " WHERE advisory_id = ? AND family = ?"
            " AND alert_id = ?",
            (advisory_id, family, alert_n)).fetchone()
        if existing is None:
            raise AdvisoryError(
                "link_not_found",
                f"No link to {family} alert {alert_n} "
                "stands on this advisory.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "DELETE FROM security_advisory_alerts"
                " WHERE id = ?", (int(existing["id"]),))
            self._conn.execute(
                "UPDATE security_advisories SET updated_at = ?"
                " WHERE id = ?", (now, advisory_id))
            self._record_event(
                advisory_id=advisory_id, repo_id=current.id,
                action="unlink", from_state="draft",
                to_state="draft", actor=actor,
                resolution=resolution,
                detail=f"unlinked {family} alert {alert_n}",
                created_at=now)
        return self._get(current, advisory_id)

    def judge_publish(self, actor: User | None, owner, repo,
                      advisory_id: int) -> PublishDecision:
        """May this actor publish this advisory? A
        pure read: writes nothing, records nothing."""
        current, resolution = self._resolve_repo(
            actor, owner, repo, any_role=False)
        row = self._advisory_row(current.id, advisory_id)
        return decide_publish(
            state=row["state"], role=resolution.role,
            source=resolution.source,
            actor=actor.username if actor is not None else None,
            full_name=current.full_name, title=row["title"],
            summary=row["summary"], severity=row["severity"],
            linked_count=len(self._links_for(advisory_id)),
            dependency_name=row["dependency_name"])

    def publish_advisory(self, actor: User | None, owner, repo,
                         advisory_id: int) -> SecurityAdvisory:
        """Publish a complete draft, freezing its
        alert linkage into the public record, with
        publisher and time recorded -- all before
        this answers."""
        current, resolution = self._resolve_repo(
            actor, owner, repo, any_role=False)
        row = self._advisory_row(current.id, advisory_id)
        # A draft does not exist to a non-maintainer,
        # even at the publish door.
        if row["state"] == "draft" \
                and resolution.role not in PERMITTED_ROLES:
            raise AdvisoryError(
                "advisory_not_found",
                f"No security advisory {advisory_id} "
                "stands in this repository.")
        decision = decide_publish(
            state=row["state"], role=resolution.role,
            source=resolution.source,
            actor=actor.username if actor is not None else None,
            full_name=current.full_name, title=row["title"],
            summary=row["summary"], severity=row["severity"],
            linked_count=len(self._links_for(advisory_id)),
            dependency_name=row["dependency_name"])
        if not decision.may_publish:
            raise AdvisoryError(decision.code, decision.reason)
        now = int(self._now())
        link_count = len(self._links_for(advisory_id))
        with self._conn:
            self._conn.execute(
                "UPDATE security_advisories SET"
                " state = 'published', published_by_id = ?,"
                " published_by = ?, published_at = ?,"
                " updated_at = ? WHERE id = ?",
                (actor.id, actor.username, now, now, advisory_id))
            self._record_event(
                advisory_id=advisory_id, repo_id=current.id,
                action="publish", from_state="draft",
                to_state="published", actor=actor,
                resolution=resolution,
                detail=(f"published with {link_count} "
                        "linked alert(s)"),
                created_at=now)
        return self._get(current, advisory_id)

    def withdraw_advisory(self, actor: User | None, owner, repo,
                          advisory_id: int, *,
                          reason: object = "") -> SecurityAdvisory:
        """Withdraw a draft or a published advisory,
        with the stated reason always recorded. A
        withdrawn advisory stays readable in its
        withdrawn state and never publishes again."""
        current, resolution = self._resolve_repo(
            actor, owner, repo, any_role=False)
        self._require_maintainer(
            resolution, actor, current.full_name, "withdraw")
        row = self._advisory_row(current.id, advisory_id)
        if row["state"] == "withdrawn":
            raise AdvisoryError(
                "advisory_withdrawn",
                f"This advisory in {current.full_name} "
                "already stands withdrawn; it cannot "
                "be withdrawn again.")
        clean_reason = validate_reason(reason)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE security_advisories SET"
                " state = 'withdrawn', withdrawn_by_id = ?,"
                " withdrawn_by = ?, withdrawn_at = ?,"
                " withdrawn_reason = ?, updated_at = ?"
                " WHERE id = ?",
                (actor.id, actor.username, now, clean_reason,
                 now, advisory_id))
            self._record_event(
                advisory_id=advisory_id, repo_id=current.id,
                action="withdraw", from_state=row["state"],
                to_state="withdrawn", actor=actor,
                resolution=resolution, detail=clean_reason,
                created_at=now)
        return self._get(current, advisory_id)

    # -- the reads ------------------------------------------------------

    def _get(self, current, advisory_id: int) -> SecurityAdvisory:
        row = self._advisory_row(current.id, advisory_id)
        return self._row_to_advisory(row, current.full_name)

    def get_advisory(self, viewer: User | None, owner, repo,
                     advisory_id: int) -> SecurityAdvisory:
        """One advisory, behind the privacy door: a
        draft answers `advisory_not_found` to every
        non-maintainer, on any repository."""
        current, resolution = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        row = self._advisory_row(current.id, advisory_id)
        if not decide_visibility(
                state=row["state"], role=resolution.role):
            raise AdvisoryError(
                "advisory_not_found",
                f"No security advisory {advisory_id} "
                "stands in this repository.")
        return self._row_to_advisory(row, current.full_name)

    def list_advisories(self, viewer: User | None, owner, repo, *,
                        state: str | None = None,
                        limit: int = 100) -> tuple:
        """The advisories this viewer may see, newest
        first. Drafts stand in the list for
        maintainers alone; no filter can surface a
        draft to anyone else."""
        current, resolution = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        if state is not None and state not in STATES:
            raise AdvisoryError(
                "state_invalid",
                f"Unknown advisory state: {state!r}. An "
                "advisory stands draft, published or "
                "withdrawn.")
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT * FROM security_advisories"
            " WHERE repo_id = ? ORDER BY id DESC",
            (current.id,)).fetchall()
        visible = [
            self._row_to_advisory(r, current.full_name)
            for r in rows
            if decide_visibility(
                state=r["state"], role=resolution.role)
            and (state is None or r["state"] == state)]
        return tuple(visible[:clamped])

    def count_advisories(self, viewer: User | None, owner, repo
                         ) -> dict:
        """The visible counts by state, for this
        viewer: a non-maintainer's draft count is
        zero because drafts do not exist to them."""
        current, resolution = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        counts = {name: 0 for name in STATES}
        rows = self._conn.execute(
            "SELECT state, COUNT(*) AS n FROM"
            " security_advisories WHERE repo_id = ?"
            " GROUP BY state", (current.id,)).fetchall()
        for row in rows:
            if row["state"] in counts and decide_visibility(
                    state=row["state"], role=resolution.role):
                counts[row["state"]] = int(row["n"])
        counts["total"] = sum(counts[name] for name in STATES)
        return counts

    def events_for(self, viewer: User | None, owner, repo,
                   advisory_id: int) -> tuple:
        """The advisory's own record, under the same
        door as the advisory itself: at publication
        the coordination history becomes part of the
        public record."""
        advisory = self.get_advisory(
            viewer, owner, repo, advisory_id)
        rows = self._conn.execute(
            "SELECT * FROM security_advisory_events"
            " WHERE advisory_id = ? ORDER BY id",
            (advisory.id,)).fetchall()
        return tuple(_row_to_event(r) for r in rows)


# ---------------------------------------------------------------------
# Rendering (S-010 escaped)
# ---------------------------------------------------------------------

def render_advisory_page(advisory: SecurityAdvisory,
                         title: str = "Security advisory") -> str:
    """One advisory's face: its state and severity
    in words, its affected facts with *fix unknown*
    said where no fix is known, its frozen linkage,
    and -- while withdrawn -- its reason. Standing
    is always in words, never colour alone."""
    links = "".join(
        "<li>" + escape_html_text(link.words()) + "</li>"
        for link in advisory.links) or "<li>No linked alerts.</li>"
    withdrawn = ""
    if advisory.state == "withdrawn":
        withdrawn = ("<p>Withdrawn: "
                     + escape_html_text(advisory.withdrawn_reason)
                     + "</p>")
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title) + " -- "
        + escape_html_text(advisory.advisory_key)
        + "</title></head><body><h1>"
        + escape_html_text(advisory.title) + "</h1><p>"
        + escape_html_text(advisory.words()) + "</p><p>"
        + escape_html_text(advisory.summary) + "</p><p>"
        + escape_html_text(advisory.description) + "</p>"
        + withdrawn
        + '<section class="advisory-links"><h3>Linked '
        "alerts</h3><ul>" + links
        + "</ul></section></body></html>")


def render_advisories_page(full_name: str, advisories,
                           title: str = "Security advisories") -> str:
    """The list face: every visible advisory in
    words, drafts named as drafts to the maintainers
    who alone can see them here."""
    if advisories:
        items = "".join(
            "<li>[" + escape_html_text(a.state) + "] "
            + escape_html_text(a.advisory_key) + " -- "
            + escape_html_text(a.title) + " (severity "
            + escape_html_text(a.severity) + ")</li>"
            for a in advisories)
    else:
        items = "<li>No security advisories to list.</li>"
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title) + " -- "
        + escape_html_text(full_name)
        + "</title></head><body><h1>"
        + escape_html_text(title) + " -- "
        + escape_html_text(full_name) + "</h1><ul>"
        + items + "</ul></body></html>")


# ---------------------------------------------------------------------
# Audit: the honesty invariant over the standing rows
# ---------------------------------------------------------------------

def audit_security_advisories(conn: sqlite3.Connection) -> list[str]:
    """Re-prove what the surfaces claim of the
    standing rows: every advisory's state and
    severity stand inside their vocabularies; every
    advisory names a standing repository; a
    published advisory carries its publisher and
    time and no withdrawal; a withdrawn advisory
    carries its withdrawer, time and reason; a
    draft carries neither a publication nor a
    withdrawal; every advisory key is the key its
    id mints; every link names a standing advisory
    of the same repository and a standing alert of
    its family in that repository, once; and every
    event names a standing advisory."""
    problems: list[str] = []
    repo_ids = {int(row["id"]) for row in conn.execute(
        "SELECT id FROM repositories").fetchall()}
    advisory_repo: dict[int, int] = {}
    for row in conn.execute(
            "SELECT * FROM security_advisories").fetchall():
        advisory_repo[int(row["id"])] = int(row["repo_id"])
        if int(row["repo_id"]) not in repo_ids:
            problems.append(
                f"security advisory {row['id']} names "
                f"repository {row['repo_id']}, which "
                "does not stand")
        if row["state"] not in STATES:
            problems.append(
                f"security advisory {row['id']} carries "
                f"state {row['state']!r} outside the "
                "advisory vocabulary")
        if row["severity"] not in SEVERITIES:
            problems.append(
                f"security advisory {row['id']} carries "
                f"severity {row['severity']!r} outside "
                "the severity vocabulary")
        expected_key = f"SAMVERK-ADV-{int(row['id']):04d}"
        if row["advisory_key"] != expected_key:
            problems.append(
                f"security advisory {row['id']} carries "
                f"key {row['advisory_key']!r}, not the "
                f"key its id mints ({expected_key})")
        if row["state"] == "published":
            if row["published_at"] is None \
                    or not row["published_by"]:
                problems.append(
                    f"security advisory {row['id']} stands "
                    "published with no publisher or no "
                    "publication time recorded")
            if row["withdrawn_at"] is not None:
                problems.append(
                    f"security advisory {row['id']} stands "
                    "published and carries a withdrawal")
        if row["state"] == "withdrawn":
            if row["withdrawn_at"] is None \
                    or not row["withdrawn_by"] \
                    or not row["withdrawn_reason"]:
                problems.append(
                    f"security advisory {row['id']} stands "
                    "withdrawn with no withdrawer, no "
                    "time or no stated reason recorded")
        if row["state"] == "draft":
            if row["published_at"] is not None \
                    or row["withdrawn_at"] is not None:
                problems.append(
                    f"security advisory {row['id']} stands "
                    "a draft and carries a publication or "
                    "a withdrawal")
    seen_links: set[tuple] = set()
    for row in conn.execute(
            "SELECT * FROM security_advisory_alerts").fetchall():
        key = (int(row["advisory_id"]), row["family"],
               int(row["alert_id"]))
        if key in seen_links:
            problems.append(
                f"security advisory {row['advisory_id']} "
                f"links {row['family']} alert "
                f"{row['alert_id']} more than once")
        seen_links.add(key)
        if int(row["advisory_id"]) not in advisory_repo:
            problems.append(
                f"advisory link {row['id']} names advisory "
                f"{row['advisory_id']}, which does not stand")
            continue
        if int(row["repo_id"]) != advisory_repo[int(row["advisory_id"])]:
            problems.append(
                f"advisory link {row['id']} names repository "
                f"{row['repo_id']} for an advisory of "
                f"repository "
                f"{advisory_repo[int(row['advisory_id'])]}")
        if row["family"] not in FAMILY_TABLES:
            problems.append(
                f"advisory link {row['id']} names family "
                f"{row['family']!r} outside the alert "
                "families")
            continue
        table = FAMILY_TABLES[row["family"]]
        found = conn.execute(
            f"SELECT id FROM {table} WHERE id = ? AND repo_id = ?",
            (int(row["alert_id"]), int(row["repo_id"]))).fetchone()
        if found is None:
            problems.append(
                f"advisory link {row['id']} names "
                f"{row['family']} alert {row['alert_id']} "
                f"in repository {row['repo_id']}, which "
                "does not stand")
    for row in conn.execute(
            "SELECT * FROM security_advisory_events").fetchall():
        if int(row["advisory_id"]) not in advisory_repo:
            problems.append(
                f"advisory event {row['id']} names advisory "
                f"{row['advisory_id']}, which does not stand")
    return problems
