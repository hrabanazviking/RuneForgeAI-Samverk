"""Security tab (S-307).

Roadmap S-307: Security tab -- per-repo home for
secret/dependency/code-scanning alerts with counts
and states (the surface S-297--S-304 report into).

Part XV built the three alert families one by one
and left each standing in its own room: secret
alerts (S-291's findings, S-294's lifecycle),
dependency alerts (S-297's graph x S-298's advisory
snapshot, joined by S-299) and code-scanning alerts
(S-302's SARIF uploads, S-303's dedup, S-304's
dismissal surface). A person asking the simplest
question -- *how does this repository stand?* --
had to visit all three rooms and add the numbers
up themselves. This slice is the home the roadmap
names for that question: one per-repository tab
that gathers the three families' standing counts
and states, says the whole position in words, and
points onward to each family's own surface.

- **Counts and states, gathered -- never
  re-judged.** The tab reads the standing rows the
  families already keep (migration 115's
  ``secret_alerts``, migration 121's
  ``dependency_alerts``, migration 124's
  ``code_scanning_alerts`` with S-304's dismissal
  columns) and counts them as they stand. It
  creates no alert, moves no alert and re-decides
  nothing: a family's own store remains the only
  judge of its alerts, and this surface is a pure
  read over their record. The one piece of
  judgement here is presentational and pure:
  ``decide_family_standing`` (a family with no
  alerts at all stands *clear*; one whose alerts
  are all answered stands *answered*; one with
  live alerts stands *open*) and
  ``decide_headline`` (the tab's one-line verdict:
  how many alerts stand open across the families,
  and which family carries the most of them).
- **Each family in its own vocabulary.** Secret
  and dependency alerts count by their lifecycle
  states (``open`` / ``reopened`` / ``resolved``;
  the live count is open + reopened). Dependency
  alerts also count their *live* alerts by
  severity (``critical`` / ``high`` / ``moderate``
  / ``low`` -- the shape S-299's
  ``counts_by_severity`` already promises this tab
  and S-308's rollup). Code-scanning alerts count
  by their *effective* state, exactly as S-304
  reads them: ``dismissed`` while a dismissal
  stands, else the scanner state (``open`` /
  ``fixed``); a dismissed alert counts once, as
  dismissed, never also under its scanner state.
  Live code-scanning alerts also count by SARIF
  level (``error`` / ``warning`` / ``note`` /
  ``none``). A stored value outside its family's
  vocabulary is never silently folded into a
  known bucket: it counts toward the family total
  and stands named in the family's ``unrecognised``
  count, and ``audit_security_tab`` reports it.
- **The advisory age stands on the tab.** S-298's
  law -- the snapshot's age is displayed wherever
  alerts are shown -- binds this home above all:
  the tab carries the standing snapshot's
  ``SnapshotInfo`` and every render carries the
  advisory banner (date + age words through
  ``render_advisory_banner``). The store reads the
  bundled snapshot by default, or the
  ``AdvisoryStore`` it is handed (the seam S-300's
  refreshed store lands through). Where no usable
  snapshot can be loaded the tab still stands and
  the banner says *age unknown* -- never nothing,
  never *fresh*.
- **Recent alerts, in their non-secret faces.**
  Beneath the counts the tab lists each family's
  most recent alerts (newest first, a stated cap):
  for a secret alert its path, detector and state
  -- never the matched text and never even the
  redacted preview, which stays behind S-294's
  own door; for a dependency alert its package,
  advisory and severity; for a code-scanning alert
  its rule, level, artifact and line. The tab is a
  home and an index: the answering of an alert
  (resolve, reopen, dismiss) stays on the family's
  own surface, under that family's own law.
- **The door is the display door.** This is a
  display surface over already-gated families, so
  its reads follow S-305/S-306's display law: the
  repository is resolved and S-054's ``can_read``
  decides -- a public repository's tab is readable
  by anyone, and a stranger to a private
  repository gets the uniform ``repo_not_found``
  before any count is named. The tab shows counts,
  states and the non-secret faces above -- the
  same restraint S-308's rollup is built on
  (counts only, no code content) -- while each
  family's detail pages keep their stricter
  any-role read law untouched.
- **Unwitnessed in the audit taxonomy -- said
  plainly.** No new taxonomy event: 135 stand
  (33 auth / 89 repo / 13 admin). Reading standing
  rows changes no code, lands no push and moves no
  alert; there is no act here to witness. The
  honesty re-proof is ``audit_security_tab``: every
  alert row's state (and severity / level) stands
  inside its family's vocabulary, every resolved
  secret/dependency row carries a known resolution
  kind and a recorded resolution time, every
  dismissed code-scanning row carries a known
  dismissal kind with its dismisser and reason,
  and every alert row names a standing repository.

Storage: none of its own. This slice adds **no
migration** (schema 127 stands) and moves no
standing pin; it reads the families' tables as
they already stand.
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
from .repositories import RepositoryError, RepositoryStore

__all__ = [
    "CODE_LEVELS", "CODE_SCANNER_STATES",
    "CODE_STATES", "DEPENDENCY_STATES",
    "FAMILIES", "LIVE_STATES", "RECENT_LIMIT_MAX",
    "SECRET_STATES", "SEVERITIES",
    "FamilySummary", "RecentAlert", "SecurityTab",
    "SecurityTabError", "SecurityTabStore",
    "audit_security_tab", "decide_family_standing",
    "decide_headline", "render_security_tab_page",
    "security_tab_to_dict",
]

#: The three families the tab is the home for, in
#: the order every surface shows them.
FAMILIES = ("secret", "dependency", "code_scanning")

FAMILY_LABELS = {
    "secret": "Secret scanning",
    "dependency": "Dependency alerts",
    "code_scanning": "Code scanning",
}

#: The lifecycle vocabulary secret (S-294) and
#: dependency (S-299) alerts share, word for word.
SECRET_STATES = ("open", "reopened", "resolved")
DEPENDENCY_STATES = ("open", "reopened", "resolved")

#: The states a lifecycle alert may be *live* in.
LIVE_STATES = frozenset({"open", "reopened"})

#: Dependency severities, most severe first (the
#: order S-298/S-299 display in).
SEVERITIES = ("critical", "high", "moderate", "low")

#: Code scanning's scanner states (S-303) and the
#: effective states this tab counts (S-304's law:
#: dismissed while a dismissal stands).
CODE_SCANNER_STATES = ("open", "fixed")
CODE_STATES = ("open", "fixed", "dismissed")

#: SARIF levels (S-302's vocabulary).
CODE_LEVELS = ("error", "warning", "note", "none")

#: The resolution kinds each lifecycle family may
#: stand resolved under (S-294's and S-299's sets),
#: for the audit re-proof.
SECRET_RESOLUTIONS = frozenset(
    {"revoked", "false_positive", "used_in_test"})
DEPENDENCY_RESOLUTIONS = frozenset(
    {"fixed", "false_positive", "risk_accepted"})

#: S-304's dismissal kinds, for the audit re-proof.
CODE_DISMISSALS = frozenset(
    {"false_positive", "wont_fix", "used_in_tests"})

#: The recent-alerts list never grows past this,
#: however large the ask: the tab is a home, not
#: the families' own list pages.
RECENT_LIMIT_MAX = 50
RECENT_LIMIT_DEFAULT = 10


class SecurityTabError(RepositoryError):
    """A security-tab error: a RepositoryError
    carrying `.reason`, in the house shape."""


# ---------------------------------------------------------------------
# The pure judgements
# ---------------------------------------------------------------------

def decide_family_standing(total: object,
                           live: object) -> str:
    """One family's standing, pure: ``clear`` when
    no alert has ever stood, ``answered`` when
    alerts stand but none is live, ``open`` while
    any alert is live. Counts that cannot describe
    a family (negative, or live past total) are
    refused by name rather than dressed up."""
    try:
        total_n = int(total)  # type: ignore[arg-type]
        live_n = int(live)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise SecurityTabError(
            "counts_invalid",
            "Alert counts must be whole numbers.") from None
    if total_n < 0 or live_n < 0 or live_n > total_n:
        raise SecurityTabError(
            "counts_invalid",
            f"Alert counts cannot stand: {live_n} live "
            f"of {total_n} total.")
    if total_n == 0:
        return "clear"
    if live_n == 0:
        return "answered"
    return "open"


def decide_headline(secret_live: object,
                    dependency_live: object,
                    code_live: object) -> tuple[int, str]:
    """The tab's headline, pure: (open_total,
    lead_family). The lead is the family carrying
    the most live alerts; ties break in the tab's
    family order (secret, then dependency, then
    code scanning), and with nothing live anywhere
    the lead is the empty string -- no family is
    dressed up as the story when there is none."""
    counts = {
        "secret": int(secret_live),  # type: ignore[arg-type]
        "dependency": int(dependency_live),  # type: ignore[arg-type]
        "code_scanning": int(code_live),  # type: ignore[arg-type]
    }
    total = sum(counts.values())
    if total == 0:
        return (0, "")
    lead = max(FAMILIES, key=lambda name: counts[name])
    return (total, lead)


# ---------------------------------------------------------------------
# The records
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class FamilySummary:
    """One family's standing on the tab: its total,
    its live count, its counts in its own state
    vocabulary, and -- for dependency alerts -- the
    live counts by severity, for code scanning the
    live counts by level. ``unrecognised`` counts
    stored values outside the family's vocabulary:
    they stand in the total, named, never folded
    into a known bucket."""
    family: str
    total: int
    live: int
    by_state: dict
    by_severity: dict
    by_level: dict
    unrecognised: int

    @property
    def label(self) -> str:
        return FAMILY_LABELS[self.family]

    @property
    def standing(self) -> str:
        return decide_family_standing(self.total, self.live)

    @property
    def answered(self) -> int:
        return self.total - self.live

    def words(self) -> str:
        """The family's position in one sentence, in
        words -- never colour alone."""
        if self.standing == "clear":
            return f"No {self.label.lower()} alerts stand."
        states = ", ".join(
            f"{n} {state}" for state, n in self.by_state.items()
            if n)
        base = (
            f"{self.live} of {self.total} "
            f"{self.label.lower()} alerts stand open"
            if self.live else
            f"All {self.total} {self.label.lower()} alerts "
            "stand answered")
        if states:
            base += f" ({states})"
        base += "."
        if self.by_severity:
            severe = ", ".join(
                f"{n} {name}" for name, n
                in self.by_severity.items() if n)
            if severe:
                base += f" Live by severity: {severe}."
        if self.by_level:
            levels = ", ".join(
                f"{n} {name}" for name, n
                in self.by_level.items() if n)
            if levels:
                base += f" Live by level: {levels}."
        if self.unrecognised:
            base += (
                f" {self.unrecognised} stored value(s) stand "
                "outside this family's vocabulary and are "
                "counted in the total only.")
        return base

    def to_dict(self) -> dict:
        return {
            "family": self.family,
            "label": self.label,
            "total": self.total,
            "live": self.live,
            "answered": self.answered,
            "standing": self.standing,
            "by_state": dict(self.by_state),
            "by_severity": dict(self.by_severity),
            "by_level": dict(self.by_level),
            "unrecognised": self.unrecognised,
            "words": self.words(),
        }


@dataclass(frozen=True)
class RecentAlert:
    """One recent alert in its non-secret face: the
    family, the alert's own id (its position on its
    family's own surface), its standing state, and
    the family's one-line naming of it -- path and
    detector for a secret alert (never the matched
    text, never the redacted preview), package and
    advisory for a dependency alert, rule and
    location for a code-scanning alert."""
    family: str
    alert_id: int
    state: str
    title: str
    detail: str
    created_at: int

    def words(self) -> str:
        return (f"{self.title} -- {self.detail} "
                f"[{self.state}]")

    def to_dict(self) -> dict:
        return {
            "family": self.family,
            "id": self.alert_id,
            "state": self.state,
            "title": self.title,
            "detail": self.detail,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class SecurityTab:
    """One repository's whole security standing: the
    three family summaries in tab order, the recent
    alerts across the families, and the advisory
    snapshot's standing info (S-298's age law)."""
    repo_id: int
    full_name: str
    families: tuple
    recent: tuple
    snapshot: SnapshotInfo

    @property
    def open_total(self) -> int:
        return sum(f.live for f in self.families)

    @property
    def total(self) -> int:
        return sum(f.total for f in self.families)

    @property
    def lead_family(self) -> str:
        live = {f.family: f.live for f in self.families}
        return decide_headline(
            live.get("secret", 0), live.get("dependency", 0),
            live.get("code_scanning", 0))[1]

    @property
    def headline_words(self) -> str:
        if self.open_total == 0:
            if self.total == 0:
                return (
                    f"No security alerts stand in "
                    f"{self.full_name}: secret scanning, "
                    "dependency alerts and code scanning "
                    "all stand clear.")
            return (
                f"No security alerts stand open in "
                f"{self.full_name}: all {self.total} "
                "alerts across secret scanning, dependency "
                "alerts and code scanning stand answered.")
        lead = FAMILY_LABELS[self.lead_family].lower()
        return (
            f"{self.open_total} security alerts stand open "
            f"in {self.full_name} across secret scanning, "
            f"dependency alerts and code scanning; the "
            f"most stand in {lead}.")

    def family(self, name: str) -> FamilySummary:
        for summary in self.families:
            if summary.family == name:
                return summary
        raise SecurityTabError(
            "family_unknown", f"No such family: {name!r}.")

    def to_dict(self) -> dict:
        return security_tab_to_dict(self)


def security_tab_to_dict(tab: SecurityTab) -> dict:
    return {
        "repository": tab.full_name,
        "open_total": tab.open_total,
        "total": tab.total,
        "lead_family": tab.lead_family or None,
        "headline": tab.headline_words,
        "families": [f.to_dict() for f in tab.families],
        "recent": [r.to_dict() for r in tab.recent],
        "advisory_snapshot": tab.snapshot.to_dict(),
    }


# ---------------------------------------------------------------------
# The store: the gathered read over the families' rows
# ---------------------------------------------------------------------

class SecurityTabStore:
    """The per-repository security tab: the three
    alert families' standing counts and states,
    gathered behind the display door. It writes
    nothing and judges no alert; the families' own
    stores remain the only judges of their alerts."""

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
        tab stands either way, and its banner says
        *age unknown* rather than guessing."""
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

    # -- the door ---------------------------------------------------

    def _resolve_repo(self, viewer: User | None, owner, repo):
        """The repository, through the display door:
        a missing repository answers `repo_not_found`;
        so does a repository S-054's `can_read` does
        not open to this viewer -- a stranger to a
        private repository hears nothing, not even
        that its counts exist."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise SecurityTabError(
                "repo_not_found", "No such repository.")
        return current

    # -- gathering ----------------------------------------------------

    def _lifecycle_counts(self, table: str, states: tuple,
                          repo_id: int):
        """(by_state, total, live, unrecognised) for a
        lifecycle family, counted as the rows stand."""
        by_state = {name: 0 for name in states}
        total = 0
        unrecognised = 0
        rows = self._conn.execute(
            f"SELECT state, COUNT(*) AS n FROM {table}"
            " WHERE repo_id = ? GROUP BY state",
            (repo_id,)).fetchall()
        for row in rows:
            n = int(row["n"])
            total += n
            if row["state"] in by_state:
                by_state[row["state"]] = n
            else:
                unrecognised += n
        live = sum(n for state, n in by_state.items()
                   if state in LIVE_STATES)
        return by_state, total, live, unrecognised

    def _secret_family(self, repo_id: int) -> FamilySummary:
        by_state, total, live, unrec = self._lifecycle_counts(
            "secret_alerts", SECRET_STATES, repo_id)
        return FamilySummary(
            family="secret", total=total, live=live,
            by_state=by_state, by_severity={}, by_level={},
            unrecognised=unrec)

    def _dependency_family(self, repo_id: int) -> FamilySummary:
        by_state, total, live, unrec = self._lifecycle_counts(
            "dependency_alerts", DEPENDENCY_STATES, repo_id)
        by_severity = {name: 0 for name in SEVERITIES}
        rows = self._conn.execute(
            "SELECT severity, COUNT(*) AS n FROM"
            " dependency_alerts WHERE repo_id = ?"
            " AND state IN ('open', 'reopened')"
            " GROUP BY severity", (repo_id,)).fetchall()
        for row in rows:
            if row["severity"] in by_severity:
                by_severity[row["severity"]] = int(row["n"])
            else:
                unrec += int(row["n"])
        return FamilySummary(
            family="dependency", total=total, live=live,
            by_state=by_state, by_severity=by_severity,
            by_level={}, unrecognised=unrec)

    def _code_family(self, repo_id: int) -> FamilySummary:
        by_state = {name: 0 for name in CODE_STATES}
        by_level = {name: 0 for name in CODE_LEVELS}
        total = 0
        unrec = 0
        rows = self._conn.execute(
            "SELECT state, dismissed_at, level, COUNT(*) AS n"
            " FROM code_scanning_alerts WHERE repo_id = ?"
            " GROUP BY state, dismissed_at IS NOT NULL, level",
            (repo_id,)).fetchall()
        for row in rows:
            n = int(row["n"])
            total += n
            if row["dismissed_at"] is not None:
                effective = "dismissed"
            elif row["state"] in CODE_SCANNER_STATES:
                effective = row["state"]
            else:
                effective = ""
                unrec += n
            if effective:
                by_state[effective] += n
            if effective == "open":
                if row["level"] in by_level:
                    by_level[row["level"]] += n
                else:
                    unrec += n
        return FamilySummary(
            family="code_scanning", total=total,
            live=by_state["open"], by_state=by_state,
            by_severity={}, by_level=by_level,
            unrecognised=unrec)

    def _recent(self, repo_id: int, limit: int) -> tuple:
        """Each family's most recent alerts, newest
        first within the family, families in tab
        order -- in their non-secret faces only."""
        recent: list[RecentAlert] = []
        rows = self._conn.execute(
            "SELECT id, path, detector_id, state, created_at"
            " FROM secret_alerts WHERE repo_id = ?"
            " ORDER BY id DESC LIMIT ?",
            (repo_id, limit)).fetchall()
        for row in rows:
            recent.append(RecentAlert(
                family="secret", alert_id=int(row["id"]),
                state=row["state"],
                title=row["path"],
                detail=f"secret alert, {row['detector_id']}",
                created_at=int(row["created_at"])))
        rows = self._conn.execute(
            "SELECT id, ecosystem, dependency_name,"
            " advisory_id, severity, state, created_at"
            " FROM dependency_alerts WHERE repo_id = ?"
            " ORDER BY id DESC LIMIT ?",
            (repo_id, limit)).fetchall()
        for row in rows:
            recent.append(RecentAlert(
                family="dependency", alert_id=int(row["id"]),
                state=row["state"],
                title=(f"{row['ecosystem']}: "
                       f"{row['dependency_name']}"),
                detail=(f"{row['advisory_id']}, severity "
                        f"{row['severity']}"),
                created_at=int(row["created_at"])))
        rows = self._conn.execute(
            "SELECT id, rule_id, tool_name, level,"
            " artifact_uri, start_line, state, dismissed_at,"
            " created_at FROM code_scanning_alerts"
            " WHERE repo_id = ? ORDER BY id DESC LIMIT ?",
            (repo_id, limit)).fetchall()
        for row in rows:
            state = ("dismissed" if row["dismissed_at"] is not None
                     else row["state"])
            recent.append(RecentAlert(
                family="code_scanning",
                alert_id=int(row["id"]), state=state,
                title=row["rule_id"] or row["tool_name"],
                detail=(f"{row['tool_name']}, level "
                        f"{row['level']}, at "
                        f"{row['artifact_uri']}:"
                        f"{row['start_line']}"),
                created_at=int(row["created_at"])))
        return tuple(recent)

    # -- the read -----------------------------------------------------

    def security_tab(self, viewer: User | None, owner, repo, *,
                     recent_limit: int = RECENT_LIMIT_DEFAULT
                     ) -> SecurityTab:
        """The repository's whole security standing:
        the three families' counts and states, the
        recent alerts in their non-secret faces, and
        the advisory snapshot's age standing."""
        current = self._resolve_repo(viewer, owner, repo)
        clamped = max(0, min(int(recent_limit), RECENT_LIMIT_MAX))
        families = (
            self._secret_family(current.id),
            self._dependency_family(current.id),
            self._code_family(current.id),
        )
        return SecurityTab(
            repo_id=current.id, full_name=current.full_name,
            families=families,
            recent=self._recent(current.id, clamped)
            if clamped else (),
            snapshot=self._snapshot_info())

    def counts(self, viewer: User | None, owner, repo) -> dict:
        """The tab's counts alone, as data: per family
        the by-state counts, the live and total counts
        and the standing -- the shape S-308's rollup
        will read across repositories."""
        tab = self.security_tab(viewer, owner, repo,
                                recent_limit=0)
        return {f.family: f.to_dict() for f in tab.families}


# ---------------------------------------------------------------------
# Rendering (S-010 escaped; the advisory banner stands on the page)
# ---------------------------------------------------------------------

def render_security_tab_page(tab: SecurityTab,
                             title: str = "Security") -> str:
    """The tab's face: the headline in words, the
    advisory banner (S-298's age law), one section
    per family with its counts said in words, and
    the recent alerts in their non-secret faces.
    Standing is always in words -- never colour
    alone -- and no secret text of any kind stands
    here."""
    sections = ""
    for family in tab.families:
        states = "".join(
            "<li>" + escape_html_text(state) + ": "
            + str(n) + "</li>"
            for state, n in family.by_state.items())
        sections += (
            '<section class="security-family security-'
            + escape_html_text(family.family) + '"><h3>'
            + escape_html_text(family.label) + "</h3><p>"
            + escape_html_text(family.words())
            + "</p><ul>" + states + "</ul></section>")
    if tab.recent:
        items = "".join(
            "<li>[" + escape_html_text(r.family) + "] "
            + escape_html_text(r.words()) + "</li>"
            for r in tab.recent)
    else:
        items = "<li>No alerts to list.</li>"
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title) + " -- "
        + escape_html_text(tab.full_name)
        + "</title></head><body><h1>"
        + escape_html_text(title) + " -- "
        + escape_html_text(tab.full_name) + "</h1><p>"
        + escape_html_text(tab.headline_words) + "</p>"
        + render_advisory_banner(tab.snapshot)
        + sections
        + '<section class="security-recent"><h3>Recent '
        "alerts</h3><ul>" + items
        + "</ul></section></body></html>")


# ---------------------------------------------------------------------
# Audit: the honesty invariant over the families' rows
# ---------------------------------------------------------------------

def audit_security_tab(conn: sqlite3.Connection) -> list[str]:
    """Re-prove what the tab claims of the standing
    rows: every alert's state stands inside its
    family's vocabulary; dependency severities and
    code-scanning levels stand inside theirs; a
    resolved lifecycle row carries a known
    resolution kind and a recorded resolution time;
    a dismissed code-scanning row carries a known
    dismissal kind with its dismisser and reason;
    and every alert row names a standing
    repository. The tab counts rows as they stand --
    this is where a row that cannot stand is said."""
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
        if row["state"] == "resolved":
            if row["resolution"] not in SECRET_RESOLUTIONS:
                problems.append(
                    f"secret alert {row['id']} stands resolved "
                    f"under resolution {row['resolution']!r}, "
                    "which is not one of the three kinds")
            if row["resolved_at"] is None:
                problems.append(
                    f"secret alert {row['id']} stands resolved "
                    "with no resolution time recorded")
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
        if row["state"] == "resolved":
            if row["resolution"] not in DEPENDENCY_RESOLUTIONS:
                problems.append(
                    f"dependency alert {row['id']} stands "
                    f"resolved under resolution "
                    f"{row['resolution']!r}, which is not one "
                    "of the three kinds")
            if row["resolved_at"] is None:
                problems.append(
                    f"dependency alert {row['id']} stands "
                    "resolved with no resolution time recorded")
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
        if row["dismissed_at"] is not None:
            if row["dismissal"] not in CODE_DISMISSALS:
                problems.append(
                    f"code-scanning alert {row['id']} stands "
                    f"dismissed under dismissal "
                    f"{row['dismissal']!r}, which is not one "
                    "of the three kinds")
            if not row["dismissed_by"] \
                    or not row["dismissal_reason"]:
                problems.append(
                    f"code-scanning alert {row['id']} stands "
                    "dismissed with no dismisser or no stated "
                    "reason recorded")
    return problems
