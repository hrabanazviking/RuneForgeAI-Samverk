"""Advisory data (S-298).

Roadmap S-298: Advisory data -- a bundled, dated
snapshot of public vulnerability data; its age is
displayed wherever alerts are shown.

S-297 (banking ahead of this slice in roadmap
order) graphs a repository's manifests into a
dependency table. Before anything may be *alerted*
on (S-299 joins graph x advisory data), the forge
needs vulnerability data of its own: public,
bundled, and honest about how old it is. This
slice is that data and its laws:

- **Bundled, dated, and shipped in the repo.**
  The snapshot is ``samverk/advisory_snapshot.json``
  -- a small, hand-compiled set of public
  advisories (OSV / the GitHub Advisory Database /
  the NVD are its sources, named in the file),
  carrying its ``snapshot_date`` in the file
  itself. It loads offline, with no network call
  anywhere in this module: an offline instance
  holds exactly this data and says exactly how
  old it is. S-300 is the refresh road; nothing
  here pretends a refresh has happened.
- **The snapshot date is data, never decoration.**
  ``parse_snapshot`` is a pure validator: a
  snapshot whose date is missing, malformed or in
  the future (against the caller's clock) is
  refused by name (``snapshot_date_missing`` /
  ``snapshot_date_invalid`` /
  ``snapshot_date_in_future``) -- never silently
  treated as fresh. A snapshot whose *format* is
  unrecognised is ``snapshot_format_unknown``;
  malformed JSON is ``snapshot_malformed``; an
  empty advisory list is ``snapshot_empty`` (a
  snapshot claiming no vulnerabilities anywhere
  is a broken snapshot, not good news). Every
  advisory row is validated the same way: a known
  ecosystem (the four S-297 graphs:
  ``python`` / ``npm`` / ``go`` / ``rust``), a
  known severity (``critical`` / ``high`` /
  ``moderate`` / ``low``), a non-empty affected
  range, a summary, and a ``fixed_version`` that
  is either a version string or honestly ``None``
  -- *fix unknown*, displayed as such, never
  invented. Duplicate advisory ids are refused
  (``advisory_duplicate``): one id, one record.
- **Age is computed, and it is displayed wherever
  alerts are shown.** ``AdvisorySnapshot.age_days``
  counts whole days from the snapshot date to the
  caller's day; ``freshness`` speaks in three
  honest states -- ``current`` (within
  ``STALE_AFTER_DAYS``), ``stale`` (past it), and
  ``unknown`` (no usable snapshot, so no age can
  be claimed at all). ``age_words`` says it in
  plain words a person reads (*snapshot dated
  2026-11-12, 3 days old*; *age unknown*), and
  every render surface in this module -- the
  banner that alert surfaces carry
  (``render_advisory_banner``), the snapshot page
  and the per-package page -- prints the date and
  the age words, escaped through S-010's seam.
  A stale snapshot is shown as stale; an absent
  or unloadable one is shown as unknown. Nothing
  here ever rounds a stale snapshot down to
  *current*, and there is no surface that shows
  an alert without the age standing beside it.
- **A read-only store over the snapshot.**
  ``AdvisoryStore`` loads the bundled snapshot by
  default (``bundled()``) or any snapshot text /
  path an operator hands it (the seam S-300's
  refresh will land through), and answers the
  lookups S-299 will join on:
  ``for_package(ecosystem, package)`` (package
  names matched under the ecosystem's own
  equivalence -- Python's PEP 503 normalisation,
  npm / Rust case-folding, Go's exact module
  paths), ``get(advisory_id)``, ``counts()`` by
  ecosystem and severity, and ``snapshot_info()``
  carrying date, age and freshness for any
  surface to display. The store holds no database
  rows: the snapshot is a file, this slice adds
  **no migration** of its own (schema 120 stands on the banked line), and
  loading writes nothing.
- **Unwitnessed in the audit taxonomy -- said
  plainly.** No new taxonomy event: 134 stand
  (33 auth / 88 repo / 13 admin). Reading a
  bundled data file changes no code, lands no
  push and opens no alert; there is no act here
  to witness, and S-299's alerts will stand on
  their own record when they exist.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .escaping import escape_html_text
from .repositories import RepositoryError

__all__ = [
    "ADVISORY_DUPLICATE", "ADVISORY_INVALID",
    "ADVISORY_NOT_FOUND", "ECOSYSTEMS",
    "FRESHNESS_CURRENT", "FRESHNESS_STALE",
    "FRESHNESS_UNKNOWN", "SEVERITIES",
    "SNAPSHOT_DATE_IN_FUTURE", "SNAPSHOT_DATE_INVALID",
    "SNAPSHOT_DATE_MISSING", "SNAPSHOT_EMPTY",
    "SNAPSHOT_FORMAT_UNKNOWN", "SNAPSHOT_MALFORMED",
    "SNAPSHOT_NOT_FOUND", "STALE_AFTER_DAYS",
    "Advisory", "AdvisoryError", "AdvisorySnapshot",
    "AdvisoryStore", "SnapshotInfo",
    "age_words", "freshness_for", "normalise_package",
    "parse_snapshot", "render_advisories_page",
    "render_advisory_banner", "render_package_page",
]

#: The ecosystems S-297 graphs, mirrored here so
#: an advisory can only ever name a graphable one.
ECOSYSTEMS = frozenset({"python", "npm", "go", "rust"})

#: The severities an advisory may carry, most
#: severe first in SEVERITY_ORDER for display.
SEVERITIES = frozenset(
    {"critical", "high", "moderate", "low"})
SEVERITY_ORDER = ("critical", "high", "moderate", "low")

#: Past this many days a snapshot is *stale*, and
#: every surface says so. Thirty days: public
#: vulnerability data moves faster than that.
STALE_AFTER_DAYS = 30

#: The three honest freshness states. ``unknown``
#: is the state of having no usable snapshot at
#: all -- no age may be claimed for it.
FRESHNESS_CURRENT = "current"
FRESHNESS_STALE = "stale"
FRESHNESS_UNKNOWN = "unknown"

SNAPSHOT_MALFORMED = "snapshot_malformed"
SNAPSHOT_NOT_FOUND = "snapshot_not_found"
SNAPSHOT_FORMAT_UNKNOWN = "snapshot_format_unknown"
SNAPSHOT_DATE_MISSING = "snapshot_date_missing"
SNAPSHOT_DATE_INVALID = "snapshot_date_invalid"
SNAPSHOT_DATE_IN_FUTURE = "snapshot_date_in_future"
SNAPSHOT_EMPTY = "snapshot_empty"
ADVISORY_INVALID = "advisory_invalid"
ADVISORY_DUPLICATE = "advisory_duplicate"
ADVISORY_NOT_FOUND = "advisory_not_found"

_SNAPSHOT_FORMAT = 1
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BUNDLED_PATH = Path(__file__).with_name("advisory_snapshot.json")


class AdvisoryError(RepositoryError):
    """An advisory-data error: a RepositoryError
    carrying `.reason`, in the house shape."""


def _fail(reason: str, message: str) -> AdvisoryError:
    return AdvisoryError(reason, message)


def _parse_date(value: object) -> date | None:
    """A strict YYYY-MM-DD date, or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _today(now: object) -> date:
    """The caller's day: a date, a datetime, epoch
    seconds, or -- with nothing handed in -- the
    real UTC today. Injectable so the battery can
    stand at any day it names."""
    if now is None:
        return datetime.now(timezone.utc).date()
    if isinstance(now, datetime):
        return now.date()
    if isinstance(now, date):
        return now
    if isinstance(now, (int, float)):
        return datetime.fromtimestamp(now, timezone.utc).date()
    if isinstance(now, str):
        parsed = _parse_date(now)
        if parsed is not None:
            return parsed
    raise _fail(SNAPSHOT_DATE_INVALID,
                "now must be a date, datetime, epoch seconds "
                "or a YYYY-MM-DD date")


def normalise_package(ecosystem: str, package: str) -> str:
    """A package name under its ecosystem's own
    equivalence (mirroring S-297's normalise_name):
    Python folds runs of -_. to one dash and
    lowercases (PEP 503); npm and Rust fold case;
    Go module paths are exact."""
    name = str(package).strip()
    if ecosystem == "python":
        return re.sub(r"[-_.]+", "-", name).lower()
    if ecosystem in ("npm", "rust"):
        return name.lower()
    return name


@dataclass(frozen=True)
class Advisory:
    """One public vulnerability advisory, as the
    snapshot carries it. ``fixed_version`` is None
    where no fix is known -- *fix unknown*, said
    as such on every surface, never invented."""
    id: str
    ecosystem: str
    package: str
    severity: str
    affected: str
    fixed_version: str | None
    summary: str
    published: str
    references: tuple = ()

    @property
    def fixed_words(self) -> str:
        if self.fixed_version is None:
            return "fix unknown"
        return "fixed in " + self.fixed_version

    def to_dict(self) -> dict:
        return {
            "id": self.id, "ecosystem": self.ecosystem,
            "package": self.package,
            "severity": self.severity,
            "affected": self.affected,
            "fixed_version": self.fixed_version,
            "fixed_words": self.fixed_words,
            "summary": self.summary,
            "published": self.published,
            "references": list(self.references),
        }


@dataclass(frozen=True)
class AdvisorySnapshot:
    """A dated snapshot of public vulnerability
    data: where it came from, the day it stands
    at, and its advisories. The date is part of
    the data -- every age answer derives from it."""
    source: str
    snapshot_date: date
    advisories: tuple

    def age_days(self, now: object = None) -> int:
        """Whole days from the snapshot date to the
        caller's day. Never negative: parse refuses
        future dates, and a hand-built snapshot that
        slips one past is clamped to 0 only after
        freshness has already refused it -- see
        freshness_for."""
        return max(0, (_today(now) - self.snapshot_date).days)

    def freshness(self, now: object = None) -> str:
        return freshness_for(self, now)

    def to_dict(self, now: object = None) -> dict:
        return {
            "source": self.source,
            "snapshot_date": self.snapshot_date.isoformat(),
            "advisory_count": len(self.advisories),
            "age_days": self.age_days(now),
            "freshness": self.freshness(now),
            "age_words": age_words(self, now),
        }


@dataclass(frozen=True)
class SnapshotInfo:
    """What any alert surface needs to display the
    snapshot's age honestly: the date, the age in
    days and words, and the freshness state. With
    no snapshot at all, ``snapshot_date`` is None
    and freshness is ``unknown``."""
    source: str | None
    snapshot_date: date | None
    advisory_count: int
    age_days: int | None
    freshness: str

    @property
    def age_words(self) -> str:
        if self.snapshot_date is None or self.age_days is None:
            return "advisory snapshot age unknown"
        return age_words_for(self.snapshot_date, self.age_days,
                             self.freshness)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "snapshot_date": (self.snapshot_date.isoformat()
                              if self.snapshot_date else None),
            "advisory_count": self.advisory_count,
            "age_days": self.age_days,
            "freshness": self.freshness,
            "age_words": self.age_words,
        }


def freshness_for(snapshot: AdvisorySnapshot | None,
                  now: object = None) -> str:
    """The freshness law, pure: no snapshot -- or
    one dated in the future against the caller's
    clock -- is ``unknown`` (no honest age exists);
    a snapshot older than STALE_AFTER_DAYS is
    ``stale``; anything younger is ``current``."""
    if snapshot is None:
        return FRESHNESS_UNKNOWN
    today = _today(now)
    if snapshot.snapshot_date > today:
        return FRESHNESS_UNKNOWN
    if (today - snapshot.snapshot_date).days > STALE_AFTER_DAYS:
        return FRESHNESS_STALE
    return FRESHNESS_CURRENT


def age_words_for(snapshot_date: date, days: int,
                  freshness: str) -> str:
    """Age in plain words a person reads."""
    base = ("advisory snapshot dated "
            + snapshot_date.isoformat())
    if days == 0:
        words = base + ", taken today"
    elif days == 1:
        words = base + ", 1 day old"
    else:
        words = base + ", " + str(days) + " days old"
    if freshness == FRESHNESS_STALE:
        words += " -- stale: refresh advised (S-300)"
    return words


def age_words(snapshot: AdvisorySnapshot | None,
              now: object = None) -> str:
    """The age of a snapshot in plain words. With
    no snapshot -- or a future-dated one -- the
    honest words are *age unknown*: never a guess,
    never *fresh*."""
    if snapshot is None:
        return "advisory snapshot age unknown"
    fresh = freshness_for(snapshot, now)
    if fresh == FRESHNESS_UNKNOWN:
        return "advisory snapshot age unknown"
    return age_words_for(snapshot.snapshot_date,
                         snapshot.age_days(now), fresh)


def _parse_advisory(row: object, index: int) -> Advisory:
    where = "advisory #" + str(index)
    if not isinstance(row, dict):
        raise _fail(ADVISORY_INVALID, where + " is not an object")
    adv_id = row.get("id")
    if not isinstance(adv_id, str) or not adv_id.strip():
        raise _fail(ADVISORY_INVALID, where + " has no id")
    where = "advisory " + adv_id
    ecosystem = row.get("ecosystem")
    if ecosystem not in ECOSYSTEMS:
        raise _fail(ADVISORY_INVALID,
                    where + " names an unknown ecosystem: "
                    + repr(ecosystem))
    package = row.get("package")
    if not isinstance(package, str) or not package.strip():
        raise _fail(ADVISORY_INVALID, where + " has no package")
    severity = row.get("severity")
    if severity not in SEVERITIES:
        raise _fail(ADVISORY_INVALID,
                    where + " names an unknown severity: "
                    + repr(severity))
    affected = row.get("affected")
    if not isinstance(affected, str) or not affected.strip():
        raise _fail(ADVISORY_INVALID,
                    where + " has no affected range")
    fixed = row.get("fixed_version")
    if fixed is not None and (not isinstance(fixed, str)
                              or not fixed.strip()):
        raise _fail(ADVISORY_INVALID,
                    where + " has an unusable fixed_version; "
                    "use null where the fix is unknown")
    summary = row.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise _fail(ADVISORY_INVALID, where + " has no summary")
    published = row.get("published")
    if _parse_date(published) is None:
        raise _fail(ADVISORY_INVALID,
                    where + " has no usable published date")
    refs = row.get("references", [])
    if (not isinstance(refs, list)
            or any(not isinstance(r, str) for r in refs)):
        raise _fail(ADVISORY_INVALID,
                    where + " has unusable references")
    return Advisory(
        id=adv_id.strip(), ecosystem=ecosystem,
        package=package.strip(), severity=severity,
        affected=affected.strip(),
        fixed_version=(fixed.strip() if isinstance(fixed, str)
                       else None),
        summary=summary.strip(), published=published,
        references=tuple(refs))


def parse_snapshot(raw: object, now: object = None) -> AdvisorySnapshot:
    """Parse and validate snapshot JSON (text,
    bytes, or an already-decoded mapping) into an
    AdvisorySnapshot. Pure: writes nothing, reads
    no clock but the caller's. Every refusal names
    its reason; a future snapshot date is refused,
    never silently treated as fresh."""
    data = raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            data = bytes(raw).decode("utf-8")
        except UnicodeDecodeError:
            raise _fail(SNAPSHOT_MALFORMED,
                        "snapshot is not UTF-8 text")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            raise _fail(SNAPSHOT_MALFORMED,
                        "snapshot is not valid JSON: " + str(exc))
    if not isinstance(data, dict):
        raise _fail(SNAPSHOT_MALFORMED,
                    "snapshot is not a JSON object")
    if data.get("snapshot_format") != _SNAPSHOT_FORMAT:
        raise _fail(SNAPSHOT_FORMAT_UNKNOWN,
                    "unrecognised snapshot_format: "
                    + repr(data.get("snapshot_format")))
    source = data.get("source")
    if not isinstance(source, str) or not source.strip():
        raise _fail(ADVISORY_INVALID,
                    "snapshot names no source for its data")
    raw_date = data.get("snapshot_date")
    if raw_date is None:
        raise _fail(SNAPSHOT_DATE_MISSING,
                    "snapshot carries no snapshot_date; its age "
                    "could never be displayed honestly")
    snap_date = _parse_date(raw_date)
    if snap_date is None:
        raise _fail(SNAPSHOT_DATE_INVALID,
                    "snapshot_date is not a YYYY-MM-DD date: "
                    + repr(raw_date))
    if snap_date > _today(now):
        raise _fail(SNAPSHOT_DATE_IN_FUTURE,
                    "snapshot_date " + snap_date.isoformat()
                    + " is in the future; a snapshot may not "
                    "claim freshness it cannot have")
    rows = data.get("advisories")
    if not isinstance(rows, list):
        raise _fail(ADVISORY_INVALID,
                    "snapshot advisories is not a list")
    if not rows:
        raise _fail(SNAPSHOT_EMPTY,
                    "snapshot carries no advisories; a snapshot "
                    "claiming no vulnerabilities anywhere is a "
                    "broken snapshot, not good news")
    advisories = []
    seen = set()
    for index, row in enumerate(rows):
        adv = _parse_advisory(row, index)
        if adv.id in seen:
            raise _fail(ADVISORY_DUPLICATE,
                        "advisory id appears twice: " + adv.id)
        seen.add(adv.id)
        advisories.append(adv)
    return AdvisorySnapshot(source=source.strip(),
                            snapshot_date=snap_date,
                            advisories=tuple(advisories))


class AdvisoryStore:
    """A read-only store over one advisory
    snapshot. Loading writes nothing and touches
    no database -- the snapshot is a file, and
    this slice adds no migration. ``bundled()``
    loads the snapshot shipped in the repo;
    ``from_text`` / ``from_path`` are the seam an
    operator refresh (S-300) lands through."""

    def __init__(self, snapshot: AdvisorySnapshot):
        self._snapshot = snapshot
        self._by_id = {a.id: a for a in snapshot.advisories}

    @classmethod
    def bundled(cls, now: object = None) -> "AdvisoryStore":
        return cls.from_path(_BUNDLED_PATH, now=now)

    @classmethod
    def from_path(cls, path: object,
                  now: object = None) -> "AdvisoryStore":
        p = Path(str(path))
        if not p.is_file():
            raise _fail(SNAPSHOT_NOT_FOUND,
                        "no advisory snapshot at " + str(p))
        return cls(parse_snapshot(p.read_bytes(), now=now))

    @classmethod
    def from_text(cls, raw: object,
                  now: object = None) -> "AdvisoryStore":
        return cls(parse_snapshot(raw, now=now))

    @property
    def snapshot(self) -> AdvisorySnapshot:
        return self._snapshot

    def snapshot_info(self, now: object = None) -> SnapshotInfo:
        """Date, age and freshness for any surface
        to display -- the S-298 law is that wherever
        alerts are shown, this stands beside them."""
        snap = self._snapshot
        fresh = freshness_for(snap, now)
        return SnapshotInfo(
            source=snap.source, snapshot_date=snap.snapshot_date,
            advisory_count=len(snap.advisories),
            age_days=(snap.age_days(now)
                      if fresh != FRESHNESS_UNKNOWN else None),
            freshness=fresh)

    def get(self, advisory_id: str) -> Advisory:
        adv = self._by_id.get(str(advisory_id))
        if adv is None:
            raise _fail(ADVISORY_NOT_FOUND,
                        "no advisory with id " + str(advisory_id))
        return adv

    def all_advisories(self) -> tuple:
        return self._snapshot.advisories

    def for_package(self, ecosystem: str, package: str) -> tuple:
        """Advisories naming one package, matched
        under the ecosystem's own name equivalence,
        most severe first. An unknown ecosystem is
        refused by name, never silently empty."""
        if ecosystem not in ECOSYSTEMS:
            raise _fail(ADVISORY_INVALID,
                        "unknown ecosystem: " + repr(ecosystem))
        wanted = normalise_package(ecosystem, package)
        found = [a for a in self._snapshot.advisories
                 if a.ecosystem == ecosystem
                 and normalise_package(ecosystem, a.package) == wanted]
        order = {name: i for i, name in enumerate(SEVERITY_ORDER)}
        found.sort(key=lambda a: (order[a.severity], a.id))
        return tuple(found)

    def counts(self) -> dict:
        by_ecosystem: dict = {}
        by_severity: dict = {}
        for adv in self._snapshot.advisories:
            by_ecosystem[adv.ecosystem] = \
                by_ecosystem.get(adv.ecosystem, 0) + 1
            by_severity[adv.severity] = \
                by_severity.get(adv.severity, 0) + 1
        return {"total": len(self._snapshot.advisories),
                "by_ecosystem": by_ecosystem,
                "by_severity": by_severity}


# --- render surfaces (S-010 escaped) ----------------
#
# Every surface that can stand beside an alert
# carries the snapshot's date and age words. There
# is deliberately no render function here that can
# show an advisory without them.


def render_advisory_banner(info: SnapshotInfo) -> str:
    """The banner alert surfaces carry: the
    snapshot's date and age, in words. With no
    usable snapshot the banner says *age unknown*
    -- never nothing, never *fresh*."""
    return ('<p class="advisory-age" data-freshness="'
            + escape_html_text(info.freshness) + '">'
            + escape_html_text(info.age_words) + "</p>")


def _advisory_list_html(advisories) -> str:
    items = ""
    for adv in advisories:
        items += ("<li><strong>" + escape_html_text(adv.id)
                  + "</strong> " + escape_html_text(adv.package)
                  + " (" + escape_html_text(adv.ecosystem)
                  + ") -- " + escape_html_text(adv.severity)
                  + ", affected " + escape_html_text(adv.affected)
                  + ", " + escape_html_text(adv.fixed_words)
                  + ": " + escape_html_text(adv.summary) + "</li>")
    return "<ul>" + items + "</ul>"


def render_advisories_page(store: AdvisoryStore,
                           now: object = None,
                           title: str = "Advisory data") -> str:
    """The snapshot page: source, date, age and
    every advisory -- age first, never buried."""
    info = store.snapshot_info(now)
    counts = store.counts()
    body = ("<h1>" + escape_html_text(title) + "</h1>"
            + render_advisory_banner(info)
            + "<p>Source: " + escape_html_text(info.source or "")
            + "</p><p>" + escape_html_text(str(counts["total"]))
            + " advisories in this snapshot.</p>"
            + _advisory_list_html(store.all_advisories()))
    return ("<!DOCTYPE html><html><head><title>"
            + escape_html_text(title)
            + "</title></head><body>" + body + "</body></html>")


def render_package_page(store: AdvisoryStore, ecosystem: str,
                        package: str, now: object = None) -> str:
    """One package's advisories -- the shape an
    alert list takes -- with the snapshot age
    standing at its head, as the law requires
    wherever alerts are shown."""
    info = store.snapshot_info(now)
    found = store.for_package(ecosystem, package)
    title = "Advisories for " + str(package)
    if found:
        listing = _advisory_list_html(found)
    else:
        listing = ("<p>No advisories in this snapshot name "
                   "this package.</p>")
    body = ("<h1>" + escape_html_text(title) + "</h1>"
            + render_advisory_banner(info) + listing)
    return ("<!DOCTYPE html><html><head><title>"
            + escape_html_text(title)
            + "</title></head><body>" + body + "</body></html>")
