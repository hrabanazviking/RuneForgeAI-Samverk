"""Security overview (S-308).

Roadmap S-308: Security overview -- org/instance
rollup: open alerts by severity and repos affected;
counts only, no code content (safe for wider admin
read).

S-307 gave every repository a security tab: one
home gathering its three alert families' standing
counts. The question this slice answers is the
same question one level up -- *how does the whole
organization stand? how does the whole instance
stand?* -- for the people who carry the wider
view: an organization's members watching their
shared estate, and the instance's site admins
watching everything. This module is that rollup:
one pure read that gathers the families' *live*
alerts across many repositories and says the
position in counts and words.

- **Live alerts only, each family in its own
  vocabulary.** The rollup counts alerts that
  stand open today, exactly as S-307 defines
  *live*: secret and dependency alerts in state
  ``open`` or ``reopened`` (S-294/S-299's
  lifecycle; resolved alerts are answered and
  never counted), and code-scanning alerts whose
  effective state is ``open`` (S-304's law:
  ``dismissed`` while a dismissal stands, else
  the scanner state -- so dismissed and fixed
  alerts are answered and never counted). Open
  alerts stand by severity in each family's own
  vocabulary, never silently merged: dependency
  alerts by severity (``critical`` / ``high`` /
  ``moderate`` / ``low``), code-scanning alerts
  by SARIF level (``error`` / ``warning`` /
  ``note`` / ``none``), and secret alerts as the
  secret family's own total (that family keeps no
  severity vocabulary, and none is invented for
  it). A stored value outside its family's
  vocabulary is never silently folded into a
  known bucket: a live row whose severity or
  level is unrecognised counts toward its
  family's live total and stands named in the
  family's ``unrecognised`` count, a row whose
  state is unrecognised stands named there too
  (it cannot be proven live, so it is not
  counted live), and ``audit_security_overview``
  reports every such row.
- **Repos affected.** Alongside the alert counts
  the rollup counts distinct repositories
  carrying at least one live alert -- overall
  (a repository with live alerts in two families
  counts once) and per family (it counts once in
  each family it carries). A repository with
  only answered alerts is not affected.
- **Counts only, no code content.** Nothing in
  this surface names an alert: no matched secret
  text, no redacted preview, no file contents, no
  finding messages, no per-alert detail of any
  kind -- counts, standings in words, and (under
  the naming law below) repository names. That
  restraint is what makes the rollup safe for the
  wider readership its two doors allow.
- **The two doors, decided conservatively.** An
  *organization* rollup covers the repositories
  the organization owns (the shared S-185 owner
  namespace: ``owner_lower`` is the organization's
  canonical name) and is readable by the
  organization's members and owners under
  S-186's membership -- and by site admins,
  whose instance administration is never theatre
  (S-054's law). Anyone else -- a stranger, an
  anonymous visitor, or a person asking after an
  organization that does not stand -- hears the
  uniform ``org_not_found``: a rollup they may
  not read is not distinguished from one that
  does not exist. An *instance* rollup covers
  every repository on the instance and is
  readable by **site admins only**; anyone else
  hears the uniform ``overview_not_found``.
  Membership is judged by a pure read of the
  standing membership rows (the founding owner
  stands as owner exactly as S-186 seeds them,
  judged here without writing the seed): this
  surface writes nothing and audits nothing, not
  even a first-touch seed row.
- **Repository names follow S-054.** The counts
  above cover every repository in scope, named
  or not. A repository's *identity* stands in
  the rollup's named list only where S-054's
  ``can_read`` opens that repository to this
  viewer; an affected repository the viewer
  cannot read contributes to every count and is
  itself counted in ``hidden_repos_affected``,
  but is never named -- a private repository's
  existence is itself private.
- **The advisory age stands on the overview.**
  S-298's law -- the snapshot's age is displayed
  wherever alerts are shown -- binds here too:
  every rollup carries the standing snapshot's
  ``SnapshotInfo`` and every render carries the
  advisory banner (date + age words through
  ``render_advisory_banner``); where no usable
  snapshot loads the banner says *age unknown*,
  never nothing, never *fresh*.
- **Unwitnessed in the audit taxonomy -- said
  plainly.** No new taxonomy event: 135 stand
  (33 auth / 89 repo / 13 admin). Reading standing
  rows changes no code, lands no push and moves
  no alert; there is no act here to witness. The
  honesty re-proof is
  ``audit_security_overview``: every alert row's
  state (and severity / level) stands inside its
  family's vocabulary, and every alert row names
  a standing repository.

Storage: none of its own. This slice adds **no
migration** (schema 127 stands) and moves no
standing pin; it reads the families' tables, the
organizations, memberships and repositories
tables as they already stand.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .advisory_data import (
    AdvisoryStore, SnapshotInfo, render_advisory_banner)
from .escaping import escape_html_text
from .permissions import can_read
from .repositories import RepositoryError, RepositoryStore, _row_to_repo
from .security_tab import (
    CODE_LEVELS, CODE_SCANNER_STATES, DEPENDENCY_STATES,
    FAMILIES, FAMILY_LABELS, LIVE_STATES, SECRET_STATES,
    SEVERITIES, decide_headline)

__all__ = [
    "FamilyRollup", "SecurityOverview",
    "SecurityOverviewError", "SecurityOverviewStore",
    "audit_security_overview", "decide_overview_standing",
    "render_security_overview_page",
    "security_overview_to_dict",
]


class SecurityOverviewError(RepositoryError):
    """A security-overview error: a RepositoryError
    carrying `.reason`, in the house shape."""


# ---------------------------------------------------------------------
# The pure judgements
# ---------------------------------------------------------------------

def decide_overview_standing(live: object) -> str:
    """A rollup standing, pure: ``clear`` when no
    live alert stands in scope, ``open`` while any
    does. A count that cannot describe a rollup
    (not a whole number, or negative) is refused
    by name rather than dressed up."""
    try:
        live_n = int(live)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise SecurityOverviewError(
            "counts_invalid",
            "Alert counts must be whole numbers.") from None
    if live_n < 0:
        raise SecurityOverviewError(
            "counts_invalid",
            f"Alert counts cannot stand: {live_n} live.")
    return "clear" if live_n == 0 else "open"


# ---------------------------------------------------------------------
# The records
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class FamilyRollup:
    """One family's live standing across a whole
    scope: how many alerts stand open, across how
    many distinct repositories, the live counts in
    the family's own severity or level vocabulary
    (dependency severities, code-scanning SARIF
    levels; the secret family keeps neither, so
    both stand empty and its severity is its live
    total), and the ``unrecognised`` count of
    stored values outside the family's vocabulary
    -- counted and named, never folded away."""
    family: str
    live: int
    repos_affected: int
    by_severity: dict
    by_level: dict
    unrecognised: int

    @property
    def label(self) -> str:
        return FAMILY_LABELS[self.family]

    @property
    def standing(self) -> str:
        return decide_overview_standing(self.live)

    def words(self) -> str:
        """The family's position in one sentence, in
        words -- never colour alone."""
        noun = self.label.lower()
        if not noun.endswith("alerts"):
            noun += " alerts"
        if self.live == 0:
            base = f"No {noun} stand open."
        else:
            repos = ("1 repository" if self.repos_affected == 1
                     else f"{self.repos_affected} repositories")
            base = (f"{self.live} {noun} "
                    f"stand open across {repos}.")
        if self.by_severity:
            severe = ", ".join(
                f"{n} {name}" for name, n
                in self.by_severity.items() if n)
            if severe:
                base += f" Open by severity: {severe}."
        if self.by_level:
            levels = ", ".join(
                f"{n} {name}" for name, n
                in self.by_level.items() if n)
            if levels:
                base += f" Open by level: {levels}."
        if self.unrecognised:
            base += (
                f" {self.unrecognised} stored value(s) stand "
                "outside this family's vocabulary and are "
                "named here, never folded into a known "
                "bucket.")
        return base

    def to_dict(self) -> dict:
        return {
            "family": self.family,
            "label": self.label,
            "live": self.live,
            "repos_affected": self.repos_affected,
            "standing": self.standing,
            "by_severity": dict(self.by_severity),
            "by_level": dict(self.by_level),
            "unrecognised": self.unrecognised,
            "words": self.words(),
        }


@dataclass(frozen=True)
class SecurityOverview:
    """One scope's whole live security standing:
    the three family rollups in tab order, the
    distinct repositories affected overall, the
    affected repositories this viewer may be told
    by name (S-054), the count of affected
    repositories counted but never named to this
    viewer, and the advisory snapshot's standing
    info (S-298's age law). Counts only -- no
    alert of any kind is named here."""
    scope: str
    scope_name: str
    families: tuple
    repos_affected: int
    named_repos: tuple
    hidden_repos_affected: int
    snapshot: SnapshotInfo

    @property
    def open_total(self) -> int:
        return sum(f.live for f in self.families)

    @property
    def standing(self) -> str:
        return decide_overview_standing(self.open_total)

    @property
    def lead_family(self) -> str:
        live = {f.family: f.live for f in self.families}
        return decide_headline(
            live.get("secret", 0), live.get("dependency", 0),
            live.get("code_scanning", 0))[1]

    @property
    def headline_words(self) -> str:
        if self.open_total == 0:
            return (
                f"No security alerts stand open in "
                f"{self.scope_name}: secret scanning, "
                "dependency alerts and code scanning "
                "all stand clear.")
        repos = ("1 repository" if self.repos_affected == 1
                 else f"{self.repos_affected} repositories")
        lead = FAMILY_LABELS[self.lead_family].lower()
        return (
            f"{self.open_total} security alerts stand open "
            f"in {self.scope_name} across {repos}; the "
            f"most stand in {lead}.")

    def family(self, name: str) -> FamilyRollup:
        for rollup in self.families:
            if rollup.family == name:
                return rollup
        raise SecurityOverviewError(
            "family_unknown", f"No such family: {name!r}.")

    def to_dict(self) -> dict:
        return security_overview_to_dict(self)


def security_overview_to_dict(overview: SecurityOverview) -> dict:
    return {
        "scope": overview.scope,
        "scope_name": overview.scope_name,
        "open_total": overview.open_total,
        "repos_affected": overview.repos_affected,
        "lead_family": overview.lead_family or None,
        "headline": overview.headline_words,
        "families": [f.to_dict() for f in overview.families],
        "named_repos": list(overview.named_repos),
        "hidden_repos_affected": overview.hidden_repos_affected,
        "advisory_snapshot": overview.snapshot.to_dict(),
    }


# ---------------------------------------------------------------------
# The store: the gathered live read over the families' rows
# ---------------------------------------------------------------------

class SecurityOverviewStore:
    """The org / instance security overview: the
    three alert families' live counts gathered
    across a scope of repositories, behind the two
    doors the module docstring decides. It writes
    nothing, audits nothing and judges no alert;
    the families' own stores remain the only
    judges of their alerts."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 accounts: AccountStore,
                 advisories: AdvisoryStore | None = None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._advisories = advisories
        self._time = time_fn

    # -- the snapshot ---------------------------------------------

    def _snapshot_info(self) -> SnapshotInfo:
        """The standing snapshot's info, honestly
        unknown where no usable snapshot loads: the
        overview stands either way, and its banner
        says *age unknown* rather than guessing."""
        store = self._advisories
        if store is None:
            try:
                store = AdvisoryStore.bundled(
                    now=int(self._time()))
            except Exception:
                return SnapshotInfo(
                    source=None, snapshot_date=None,
                    advisory_count=0, age_days=None,
                    freshness="unknown")
            self._advisories = store
        return store.snapshot_info(now=int(self._time()))

    # -- the doors --------------------------------------------------

    def _org_role(self, viewer: User | None, org_row) -> str | None:
        """The viewer's standing in the organization,
        judged by pure read: a site admin stands as
        ``site_admin``; a standing membership row
        gives its S-186 role; and where the
        organization has no membership rows at all
        its creator stands as founding ``owner``,
        exactly as S-186's seed would place them --
        judged here without writing that seed,
        because this surface writes nothing."""
        if viewer is None:
            return None
        if viewer.is_admin:
            return "site_admin"
        row = self._conn.execute(
            "SELECT role FROM organization_members"
            " WHERE org_id = ? AND user_id = ?",
            (org_row["id"], viewer.id)).fetchone()
        if row is not None:
            return row["role"]
        if viewer.id == org_row["created_by"]:
            count = self._conn.execute(
                "SELECT COUNT(*) AS n FROM"
                " organization_members WHERE org_id = ?",
                (org_row["id"],)).fetchone()["n"]
            if int(count) == 0:
                return "owner"
        return None

    def _resolve_org(self, viewer: User | None, org_name):
        """The organization row, through the org door:
        a missing organization answers
        ``org_not_found``; so does one this viewer
        neither belongs to nor administers -- a
        rollup they may not read is not told apart
        from one that does not stand."""
        if not isinstance(org_name, str) or not org_name.strip():
            raise SecurityOverviewError(
                "org_not_found", "No such organization.")
        row = self._conn.execute(
            "SELECT * FROM organizations WHERE name_lower = ?",
            (org_name.strip().lower(),)).fetchone()
        if row is None or self._org_role(viewer, row) is None:
            raise SecurityOverviewError(
                "org_not_found", "No such organization.")
        return row

    # -- gathering ----------------------------------------------------

    def _placeholders(self, repo_ids: list) -> str:
        return ", ".join("?" for _ in repo_ids)

    def _lifecycle_rollup(self, family: str, table: str,
                          repo_ids: list):
        """(live, affected repo ids, unrecognised) for
        a lifecycle family: live is open + reopened;
        a state outside the vocabulary is named
        unrecognised and never counted live."""
        live = 0
        affected: set = set()
        unrec = 0
        if repo_ids:
            rows = self._conn.execute(
                f"SELECT repo_id, state, COUNT(*) AS n FROM {table}"
                f" WHERE repo_id IN ({self._placeholders(repo_ids)})"
                " GROUP BY repo_id, state", repo_ids).fetchall()
            for row in rows:
                n = int(row["n"])
                if row["state"] in LIVE_STATES:
                    live += n
                    affected.add(int(row["repo_id"]))
                elif row["state"] not in SECRET_STATES:
                    unrec += n
        return live, affected, unrec

    def _secret_rollup(self, repo_ids: list) -> FamilyRollup:
        live, affected, unrec = self._lifecycle_rollup(
            "secret", "secret_alerts", repo_ids)
        return FamilyRollup(
            family="secret", live=live,
            repos_affected=len(affected), by_severity={},
            by_level={}, unrecognised=unrec)

    def _dependency_rollup(self, repo_ids: list) -> FamilyRollup:
        live, affected, unrec = self._lifecycle_rollup(
            "dependency", "dependency_alerts", repo_ids)
        by_severity = {name: 0 for name in SEVERITIES}
        if repo_ids:
            rows = self._conn.execute(
                "SELECT severity, COUNT(*) AS n FROM"
                " dependency_alerts WHERE repo_id IN"
                f" ({self._placeholders(repo_ids)})"
                " AND state IN ('open', 'reopened')"
                " GROUP BY severity", repo_ids).fetchall()
            for row in rows:
                if row["severity"] in by_severity:
                    by_severity[row["severity"]] = int(row["n"])
                else:
                    unrec += int(row["n"])
        return FamilyRollup(
            family="dependency", live=live,
            repos_affected=len(affected),
            by_severity=by_severity, by_level={},
            unrecognised=unrec)

    def _code_rollup(self, repo_ids: list) -> FamilyRollup:
        by_level = {name: 0 for name in CODE_LEVELS}
        live = 0
        affected: set = set()
        unrec = 0
        if repo_ids:
            rows = self._conn.execute(
                "SELECT repo_id, state, dismissed_at, level,"
                " COUNT(*) AS n FROM code_scanning_alerts"
                " WHERE repo_id IN"
                f" ({self._placeholders(repo_ids)})"
                " GROUP BY repo_id, state,"
                " dismissed_at IS NOT NULL, level",
                repo_ids).fetchall()
            for row in rows:
                n = int(row["n"])
                if row["dismissed_at"] is not None:
                    continue  # dismissed: answered, never live
                if row["state"] not in CODE_SCANNER_STATES:
                    unrec += n
                    continue
                if row["state"] != "open":
                    continue  # fixed: answered, never live
                live += n
                affected.add(int(row["repo_id"]))
                if row["level"] in by_level:
                    by_level[row["level"]] += n
                else:
                    unrec += n
        return FamilyRollup(
            family="code_scanning", live=live,
            repos_affected=len(affected), by_severity={},
            by_level=by_level, unrecognised=unrec)

    def _build(self, scope: str, scope_name: str,
               viewer: User | None, repo_rows: list) -> SecurityOverview:
        repo_ids = [int(r["id"]) for r in repo_rows]
        families = (
            self._secret_rollup(repo_ids),
            self._dependency_rollup(repo_ids),
            self._code_rollup(repo_ids),
        )
        affected_ids: set = set()
        # Affected overall is the union of the families'
        # affected repositories: a repository carrying
        # live alerts in two families counts once.
        for family_name, table in (
                ("secret", "secret_alerts"),
                ("dependency", "dependency_alerts")):
            if repo_ids:
                rows = self._conn.execute(
                    f"SELECT DISTINCT repo_id FROM {table}"
                    f" WHERE repo_id IN ({self._placeholders(repo_ids)})"
                    " AND state IN ('open', 'reopened')",
                    repo_ids).fetchall()
                affected_ids.update(int(r["repo_id"]) for r in rows)
        if repo_ids:
            rows = self._conn.execute(
                "SELECT DISTINCT repo_id FROM"
                " code_scanning_alerts WHERE repo_id IN"
                f" ({self._placeholders(repo_ids)})"
                " AND dismissed_at IS NULL AND state = 'open'",
                repo_ids).fetchall()
            affected_ids.update(int(r["repo_id"]) for r in rows)
        by_id = {int(r["id"]): r for r in repo_rows}
        named: list = []
        for repo_id in sorted(affected_ids,
                              key=lambda i: by_id[i]["name_lower"]):
            repo = _row_to_repo(by_id[repo_id])
            if can_read(viewer, repo):
                named.append(repo.full_name)
        return SecurityOverview(
            scope=scope, scope_name=scope_name,
            families=families,
            repos_affected=len(affected_ids),
            named_repos=tuple(named),
            hidden_repos_affected=len(affected_ids) - len(named),
            snapshot=self._snapshot_info())

    # -- the reads -----------------------------------------------------

    def org_overview(self, viewer: User | None, org_name) -> SecurityOverview:
        """The organization rollup: live alerts across
        the repositories the organization owns, for
        its members and owners and for site admins."""
        org_row = self._resolve_org(viewer, org_name)
        repo_rows = self._conn.execute(
            "SELECT * FROM repositories WHERE owner_lower = ?"
            " ORDER BY name_lower", (org_row["name_lower"],)).fetchall()
        return self._build(
            "org", org_row["name"], viewer, repo_rows)

    def instance_overview(self, viewer: User | None) -> SecurityOverview:
        """The instance rollup: live alerts across
        every repository on the instance, for site
        admins only -- anyone else hears the uniform
        ``overview_not_found``."""
        if viewer is None or not viewer.is_admin:
            raise SecurityOverviewError(
                "overview_not_found",
                "No such security overview.")
        repo_rows = self._conn.execute(
            "SELECT * FROM repositories"
            " ORDER BY owner_lower, name_lower").fetchall()
        return self._build(
            "instance", "the instance", viewer, repo_rows)


# ---------------------------------------------------------------------
# Rendering (S-010 escaped; the advisory banner stands on the page)
# ---------------------------------------------------------------------

def render_security_overview_page(overview: SecurityOverview,
                                  title: str = "Security overview") -> str:
    """The overview's face: the headline in words,
    the advisory banner (S-298's age law), one
    section per family with its live counts said
    in words, and the affected repositories --
    named only where this viewer may read them,
    the rest counted in a plain sentence, never
    named. Standing is always in words, never
    colour alone, and no alert content of any
    kind stands here."""
    sections = ""
    for family in overview.families:
        detail = ""
        for name, n in family.by_severity.items():
            if n:
                detail += ("<li>" + escape_html_text(name)
                           + ": " + str(n) + "</li>")
        for name, n in family.by_level.items():
            if n:
                detail += ("<li>" + escape_html_text(name)
                           + ": " + str(n) + "</li>")
        sections += (
            '<section class="security-family security-'
            + escape_html_text(family.family) + '"><h3>'
            + escape_html_text(family.label) + "</h3><p>"
            + escape_html_text(family.words())
            + "</p>" + ("<ul>" + detail + "</ul>" if detail else "")
            + "</section>")
    if overview.named_repos:
        items = "".join(
            "<li>" + escape_html_text(name) + "</li>"
            for name in overview.named_repos)
    else:
        items = "<li>No affected repository is named here.</li>"
    affected = (
        '<section class="security-affected"><h3>Repositories '
        "affected</h3><p>" + str(overview.repos_affected)
        + " repositories carry live alerts.</p><ul>" + items
        + "</ul>")
    if overview.hidden_repos_affected:
        affected += (
            "<p>" + str(overview.hidden_repos_affected)
            + " further affected repositories are counted "
            "above but not named here: this view does not "
            "open them to you.</p>")
    affected += "</section>"
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title) + " -- "
        + escape_html_text(overview.scope_name)
        + "</title></head><body><h1>"
        + escape_html_text(title) + " -- "
        + escape_html_text(overview.scope_name) + "</h1><p>"
        + escape_html_text(overview.headline_words) + "</p>"
        + render_advisory_banner(overview.snapshot)
        + sections + affected + "</body></html>")


# ---------------------------------------------------------------------
# Audit: the honesty invariant over the families' rows
# ---------------------------------------------------------------------

def audit_security_overview(conn: sqlite3.Connection) -> list[str]:
    """Re-prove what the overview claims of the
    standing rows: every alert's state stands
    inside its family's vocabulary; dependency
    severities and code-scanning levels stand
    inside theirs; and every alert row names a
    standing repository. The overview counts rows
    as they stand -- this is where a row that
    cannot stand is said."""
    problems: list[str] = []
    repo_ids = {int(row["id"]) for row in conn.execute(
        "SELECT id FROM repositories").fetchall()}

    def check_repo(table: str, row) -> None:
        if int(row["repo_id"]) not in repo_ids:
            problems.append(
                f"{table} row {row['id']} names repository "
                f"{row['repo_id']}, which does not stand")

    for row in conn.execute(
            "SELECT * FROM secret_alerts").fetchall():
        check_repo("secret_alerts", row)
        if row["state"] not in SECRET_STATES:
            problems.append(
                f"secret alert {row['id']} carries state "
                f"{row['state']!r} outside the lifecycle "
                "vocabulary")
    for row in conn.execute(
            "SELECT * FROM dependency_alerts").fetchall():
        check_repo("dependency_alerts", row)
        if row["state"] not in DEPENDENCY_STATES:
            problems.append(
                f"dependency alert {row['id']} carries state "
                f"{row['state']!r} outside the lifecycle "
                "vocabulary")
        if row["severity"] not in SEVERITIES:
            problems.append(
                f"dependency alert {row['id']} carries "
                f"severity {row['severity']!r} outside the "
                "severity vocabulary")
    for row in conn.execute(
            "SELECT * FROM code_scanning_alerts").fetchall():
        check_repo("code_scanning_alerts", row)
        if row["state"] not in CODE_SCANNER_STATES:
            problems.append(
                f"code-scanning alert {row['id']} carries "
                f"scanner state {row['state']!r} outside the "
                "open/fixed vocabulary")
        if row["level"] not in CODE_LEVELS:
            problems.append(
                f"code-scanning alert {row['id']} carries "
                f"level {row['level']!r} outside the SARIF "
                "level vocabulary")
    return problems
