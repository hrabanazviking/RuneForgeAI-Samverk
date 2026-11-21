"""Census fixture (S-335).

Roadmap S-335: **the Volmarr census fixture -- the
54-originals inventory imported as mirror definitions;
uncertain-classified repos are *not* auto-mirrored (his
word governs each).**

Part XVII's founding duty is that Volmarr's original work
must never live only on someone else's computer. The
classified inventory already exists (``classification.json``
in the forgejo-backup keeping): three buckets judged by a
person, not by this code --

- ``include``   -- the 54 originals (43 public, 11 private
  at census time). These are imported here as mirror
  *definitions*: a repository plus an S-329 pull-mirror
  record in the ``pending`` state. A definition is not a
  sync -- no fetch runs in this slice. S-336 runs the
  first pass and proves it ref-for-ref; S-337 brings the
  private originals in under a read-scoped credential.
- ``uncertain`` -- repos whose classification a person
  could not settle (17 at census time). They are **held**:
  recorded in ``census_fixture_entries`` with state
  ``held``, no repository created, no mirror defined,
  nothing fetched. A held repo becomes a mirror only by
  the owner's word, one repo at a time, through
  ``release_held`` -- never by a bulk rule, never by this
  importer changing its mind.
- ``exclude``   -- forks of other people's work and the
  like (84 at census time). Not originals; not imported,
  not recorded as entries -- counted in the report and
  nowhere else.

The judgements are pure. ``decide_census_entry`` judges
one (bucket, entry) pair and writes nothing; the importer
acts on the judgements and reports every outcome --
defined, held, skipped, already-present, and refused with
its reason -- so an import never silently drops a name.

Source law. A census entry names a repository, not a URL.
The mirror source is built here, and only here, as
``https://github.com/<github_owner>/<name>.git`` from the
owner account the caller names. No credential can ride
in: the name and owner are validated as single path
segments, and S-329 strips userinfo at its own door as a
second lock. Private originals are defined as *private*
mirrors, public ones as public -- the census's own
``private`` flag governs, stated per entry.

Storage is migration 137 (``census_fixture_entries``):
one row per imported name -- its classification, its
state (``defined`` | ``held``), the mirror repository it
was defined as (NULL while held), its source, and the
census note, kept verbatim. No new audit event: defining
a mirror rides S-329's creation, which rides
``repo.create``; holding a name is a record, not an act
on a repository. The taxonomy stands at 138.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .escaping import escape_html_text
from .pull_mirrors import PullMirrorError, PullMirrorService
from .repositories import RepositoryStore

BUCKET_INCLUDE = "include"
BUCKET_EXCLUDE = "exclude"
BUCKET_UNCERTAIN = "uncertain"
BUCKETS = (BUCKET_INCLUDE, BUCKET_UNCERTAIN, BUCKET_EXCLUDE)

DEFINED = "defined"
HELD = "held"

CLASS_PUBLIC = "original-public"
CLASS_PRIVATE = "original-private"
CLASS_UNCERTAIN = "uncertain"

ACTION_DEFINE = "define"
ACTION_HOLD = "hold"
ACTION_SKIP = "skip"
ACTION_REFUSE = "refuse"


class CensusFixtureError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class CensusEntry:
    name: str
    private: bool = False
    fork: bool = False
    parent: str = ""
    note: str = ""


@dataclass(frozen=True)
class CensusDecision:
    name: str
    bucket: str
    action: str                # ACTION_DEFINE | HOLD | SKIP | REFUSE
    classification: str | None  # CLASS_* when defined or held
    reason: str


def decide_census_entry(bucket: str, entry: CensusEntry) -> CensusDecision:
    """Judge one census entry. Pure: reads nothing, writes
    nothing. The bucket is the person's classification; this
    function only states what the bucket means."""
    if bucket == BUCKET_INCLUDE:
        classification = CLASS_PRIVATE if entry.private else CLASS_PUBLIC
        return CensusDecision(
            name=entry.name, bucket=bucket, action=ACTION_DEFINE,
            classification=classification,
            reason="classified as an original; defined as a mirror")
    if bucket == BUCKET_UNCERTAIN:
        return CensusDecision(
            name=entry.name, bucket=bucket, action=ACTION_HOLD,
            classification=CLASS_UNCERTAIN,
            reason="classification uncertain; held for the owner's word")
    if bucket == BUCKET_EXCLUDE:
        return CensusDecision(
            name=entry.name, bucket=bucket, action=ACTION_SKIP,
            classification=None,
            reason="classified as not an original; not imported")
    return CensusDecision(
        name=entry.name, bucket=bucket, action=ACTION_REFUSE,
        classification=None,
        reason=f"unknown census bucket {bucket!r}")


def _parse_entry(bucket: str, raw: object) -> CensusEntry:
    if not isinstance(raw, dict):
        raise CensusFixtureError(
            "inventory_invalid",
            f"A {bucket} census entry is not an object.")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CensusFixtureError(
            "inventory_invalid",
            f"A {bucket} census entry carries no usable name.")
    private = raw.get("private", False)
    if not isinstance(private, bool):
        raise CensusFixtureError(
            "inventory_invalid",
            f"Census entry {name!r} carries a non-boolean private flag.")
    return CensusEntry(
        name=name, private=private,
        fork=bool(raw.get("fork", False)),
        parent=str(raw.get("parent", "") or ""),
        note=str(raw.get("note", "") or ""))


def parse_classification(text: str) -> dict[str, list[CensusEntry]]:
    """Parse the classified inventory (the forgejo-backup
    ``classification.json`` shape) into its three buckets.
    Raises CensusFixtureError in plain words on any shape
    this importer will not guess at."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise CensusFixtureError(
            "inventory_invalid",
            "The census inventory is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise CensusFixtureError(
            "inventory_invalid",
            "The census inventory must be an object of buckets.")
    parsed: dict[str, list[CensusEntry]] = {}
    for bucket in BUCKETS:
        raw_list = data.get(bucket, [])
        if not isinstance(raw_list, list):
            raise CensusFixtureError(
                "inventory_invalid",
                f"The census bucket {bucket!r} is not a list.")
        parsed[bucket] = [_parse_entry(bucket, raw) for raw in raw_list]
    return parsed


def load_classification(path: Path) -> dict[str, list[CensusEntry]]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CensusFixtureError(
            "inventory_unreadable",
            f"The census inventory cannot be read: {exc}") from exc
    return parse_classification(text)


@dataclass
class ImportReport:
    defined: int = 0
    held: int = 0
    skipped_excluded: int = 0
    already_defined: int = 0
    already_held: int = 0
    refused: list[tuple[str, str]] = field(default_factory=list)

    @property
    def headline(self) -> str:
        return (f"census import: {self.defined} mirror definitions created, "
                f"{self.held} held for the owner's word, "
                f"{self.skipped_excluded} excluded as not originals, "
                f"{self.already_defined + self.already_held} already present, "
                f"{len(self.refused)} refused")


@dataclass(frozen=True)
class CensusFixtureRecord:
    full_name: str
    name: str
    source: str
    classification: str        # CLASS_PUBLIC | CLASS_PRIVATE | CLASS_UNCERTAIN
    state: str                 # DEFINED | HELD
    repo_id: int | None
    note: str
    imported_at: int

    @property
    def headline(self) -> str:
        if self.state == HELD:
            return (f"{self.name} is held: its classification is "
                    f"uncertain and it is not mirrored until the "
                    f"owner's word releases it.")
        return (f"{self.full_name} is defined as a mirror of "
                f"{self.source} ({self.classification}).")


def _validate_segment(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CensusFixtureError(
            "source_invalid", f"The {what} must be a non-empty name.")
    if any(c in value for c in "/\\@:?#") or any(
            ord(c) <= 0x20 or ord(c) == 0x7F for c in value):
        raise CensusFixtureError(
            "source_invalid",
            f"The {what} {value!r} is not a single plain name segment.")
    return value


def census_source(github_owner: str, name: str) -> str:
    """The one place a census source URL is built. Names a
    GitHub account and a repository -- never a credential."""
    owner = _validate_segment(github_owner, "GitHub owner")
    repo = _validate_segment(name, "repository name")
    return f"https://github.com/{owner}/{repo}.git"


class CensusFixtureService:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._pull = PullMirrorService(
            conn, data_root, accounts, repositories,
            audit=audit, time_fn=time_fn)
        self._repos = repositories
        self._now = time_fn

    # -- records ---------------------------------------------------
    def _record(self, row: sqlite3.Row) -> CensusFixtureRecord:
        return CensusFixtureRecord(
            full_name=row["full_name"], name=row["name"],
            source=row["source"], classification=row["classification"],
            state=row["state"], repo_id=row["repo_id"],
            note=row["note"], imported_at=row["imported_at"])

    def record_for(self, owner, name: str) -> CensusFixtureRecord | None:
        full_name = f"{owner}/{name}"
        row = self._conn.execute(
            "SELECT * FROM census_fixture_entries WHERE full_name = ?",
            (full_name,)).fetchone()
        return self._record(row) if row is not None else None

    def entries(self, state: str | None = None) -> list[CensusFixtureRecord]:
        if state is None:
            rows = self._conn.execute(
                "SELECT * FROM census_fixture_entries "
                "ORDER BY name").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM census_fixture_entries WHERE state = ? "
                "ORDER BY name", (state,)).fetchall()
        return [self._record(row) for row in rows]

    def held_entries(self) -> list[CensusFixtureRecord]:
        return self.entries(state=HELD)

    def summary(self) -> dict[str, int]:
        counts = {DEFINED: 0, HELD: 0}
        for row in self._conn.execute(
                "SELECT state, COUNT(*) AS n FROM census_fixture_entries "
                "GROUP BY state"):
            counts[row["state"]] = row["n"]
        return counts

    # -- import ------------------------------------------------------
    def import_classification(self, actor_user_id: int, owner,
                              classification: dict[str, list[CensusEntry]],
                              *, github_owner: str) -> ImportReport:
        """Import one parsed classification. Include entries
        become pending mirror definitions; uncertain entries
        are recorded held and nothing more; excluded entries
        are counted and skipped. Re-importing is honest:
        names already recorded are counted as already
        present and never defined twice. A name classified
        into two buckets is refused -- the conflict is a
        person's to settle, not this importer's."""
        _validate_segment(github_owner, "GitHub owner")
        report = ImportReport()
        seen: dict[str, str] = {}
        plan: list[tuple[CensusDecision, CensusEntry]] = []
        for bucket in BUCKETS:
            for entry in classification.get(bucket, []):
                decision = decide_census_entry(bucket, entry)
                if entry.name in seen:
                    report.refused.append((
                        entry.name,
                        "classified in two buckets "
                        f"({seen[entry.name]} and {bucket}); "
                        "the owner's word settles it"))
                    continue
                seen[entry.name] = bucket
                plan.append((decision, entry))
        for decision, entry in plan:
            if decision.action == ACTION_SKIP:
                report.skipped_excluded += 1
                continue
            if decision.action == ACTION_REFUSE:
                report.refused.append((entry.name, decision.reason))
                continue
            existing = self.record_for(owner, entry.name)
            if existing is not None:
                if existing.state == DEFINED:
                    report.already_defined += 1
                else:
                    report.already_held += 1
                continue
            source = census_source(github_owner, entry.name)
            if decision.action == ACTION_HOLD:
                self._insert(owner, entry, source, decision, HELD, None)
                report.held += 1
                continue
            visibility = "private" if entry.private else "public"
            try:
                mirror = self._pull.begin_pull_mirror(
                    actor_user_id, owner, entry.name, source,
                    visibility=visibility)
            except (PullMirrorError, ValueError) as exc:
                reason = getattr(exc, "reason", "define_failed")
                report.refused.append(
                    (entry.name, f"{reason}: {exc}"))
                continue
            self._insert(owner, entry, source, decision, DEFINED,
                         mirror.repo_id)
            report.defined += 1
        return report

    def _insert(self, owner, entry: CensusEntry, source: str,
                decision: CensusDecision, state: str,
                repo_id: int | None) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO census_fixture_entries (full_name, name,"
                " source, classification, state, repo_id, note,"
                " imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"{owner}/{entry.name}", entry.name, source,
                 decision.classification, state, repo_id, entry.note,
                 int(self._now())))

    # -- the owner's word ---------------------------------------------
    def release_held(self, actor_user_id: int, owner, name: str,
                     *, github_owner: str) -> CensusFixtureRecord:
        """Release one held entry by the owner's word: the
        repository is created and defined as a pending pull
        mirror -- as a *private* mirror, the safe landing for
        a repo nobody has classified yet -- and the census
        record turns ``defined``.
        Anything not held is refused in plain words -- a
        release is a decision about an uncertain repo, not
        a second import road."""
        record = self.record_for(owner, name)
        if record is None:
            raise CensusFixtureError(
                "not_in_census",
                f"{name} is not in the census fixture.")
        if record.state != HELD:
            raise CensusFixtureError(
                "not_held",
                f"{record.full_name} is already defined as a mirror; "
                f"there is nothing held to release.")
        source = census_source(github_owner, name)
        try:
            mirror = self._pull.begin_pull_mirror(
                actor_user_id, owner, name, source, visibility="private")
        except (PullMirrorError, ValueError) as exc:
            reason = getattr(exc, "reason", "define_failed")
            raise CensusFixtureError(reason, str(exc)) from exc
        classification = CLASS_PRIVATE
        with self._conn:
            self._conn.execute(
                "UPDATE census_fixture_entries SET state = ?,"
                " classification = ?, source = ?, repo_id = ?"
                " WHERE full_name = ?",
                (DEFINED, classification, source, mirror.repo_id,
                 record.full_name))
        released = self.record_for(owner, name)
        assert released is not None
        return released


def render_census_fixture_page(records: list[CensusFixtureRecord]) -> str:
    """The census page: every imported name, its state said
    in words, held names named as held -- never colour-only.
    All census text is escaped."""
    defined = [r for r in records if r.state == DEFINED]
    held = [r for r in records if r.state == HELD]
    parts = ["<h1>Census fixture</h1>",
             f"<p>{len(defined)} mirror definitions; "
             f"{len(held)} held for the owner&rsquo;s word.</p>",
             "<h2>Defined mirrors</h2>", "<ul>"]
    for record in defined:
        parts.append(
            f"<li>{escape_html_text(record.full_name)} &mdash; "
            f"{escape_html_text(record.classification)}, mirror of "
            f"{escape_html_text(record.source)}</li>")
    parts += ["</ul>", "<h2>Held &mdash; not mirrored</h2>", "<ul>"]
    for record in held:
        parts.append(
            f"<li>{escape_html_text(record.name)} &mdash; held: "
            f"classification uncertain; the owner&rsquo;s word "
            f"governs this repo."
            + (f" Note: {escape_html_text(record.note)}"
               if record.note else "")
            + "</li>")
    parts.append("</ul>")
    return "\n".join(parts)
