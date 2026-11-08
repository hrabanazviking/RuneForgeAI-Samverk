"""Event store completion (S-221).

Part XI's canonical event store: one record shape for
every mutation in Parts III-X -- (actor, verb, target,
refs, timestamp) -- that notifications (S-223+), feeds
(S-229/S-230/S-234), the events API (S-231) and webhooks
(S-247) all read, instead of each re-deriving history
from the witness or from family stores.

- **Derived from the witness, exactly once.** Every
  mutation in Parts III-X already writes exactly one
  audit row (the slices' standing law: real changes
  only, retries and refusals quiet). This store
  materialises those rows -- one canonical event per
  audit `seq` under a UNIQUE constraint, inserted with
  OR IGNORE -- so syncing twice emits nothing twice,
  a refused or rolled-back mutation (which never
  reached the audit log) emits nothing at all, and a
  mutation that somehow escaped auditing is a visible
  gap between the two records, never a silent second
  truth. S-090's push store and S-139's issue outbox
  remain the family stores they are; this is the one
  canonical store over all of them, keyed to the same
  witness they derive from.
- **The canonical record.** `actor` is the acting
  principal (kind, account id, and the account's name
  resolved at read time); `verb` is the audit action
  itself, from the frozen taxonomy (123 verbs stand);
  `target` is the audit target (kind and id, carried
  unchanged); `refs` are the references a feed needs
  to place the event, derived purely by `derive_refs`
  (the repository as `repo:<owner>/<name>`, a numbered
  item as `number:<n>`, and a push's moved refs by
  name, from the witness's own detail); `timestamp`
  is the audit row's `ts` -- the moment the mutation
  was witnessed, never a second clock. The audit's
  safe detail and outcome ride unchanged.
- **Reads sync first and respect permission by
  construction.** Every read materialises first, so
  an answer is never stale. A repository's events
  require read access to that repository (S-054's
  gate; a stranger to a private repository gets the
  uniform `repo_not_found`, and its events are
  invisible in every other face too). An actor feed
  filters event by event: repository events the
  viewer cannot read never appear, in rows or in
  counts; non-repository events are visible only to
  the actor themself and to site admins, except
  organization events, which are public directory
  facts (S-211's law). The public feed carries only
  events on public repositories (S-230's rule).
- **One migration, no new taxonomy event.**
  Migration 85 creates the `events` table (schema
  84 to 85); the store records no verb of its own
  and audits nothing -- materialising is a read of
  the witness, and syncing is idempotent, so a sync
  can never manufacture history.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .permissions import can_read
from .repositories import Repository, RepositoryStore

__all__ = [
    "CanonicalEvent", "EventStore", "EventStoreError",
    "derive_refs", "event_payload", "event_visible_to",
    "payload_json", "render_events_page", "repository_of",
]


class EventStoreError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def repository_of(target_id: str | None) -> str | None:
    """The repository full name a target names, or None.

    Audit targets name a repository as `<owner>/<name>`,
    optionally suffixed `#<number>` for a numbered item
    (the S-139 shape). The repository is the part before
    any `#`, kept only when it is exactly two path
    segments -- a bare username or an org name is not a
    repository, and a longer path is not one either.
    """
    if not target_id:
        return None
    base = target_id.split("#", 1)[0].strip()
    parts = base.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return base


def derive_refs(verb: str, target_kind: str,
                target_id: str | None,
                detail: dict | None) -> tuple[str, ...]:
    """Pure refs law: the references that place one
    event, judged only from its verb, target and the
    witness's safe detail.

    In order: the repository (`repo:<owner>/<name>`)
    when the target names one; the numbered item
    (`number:<n>`) from a `#<n>` target suffix or an
    integer `number` in the detail; then a push's
    moved refs by name, from the detail's `refs` list
    (S-094's shape). Duplicates collapse, order holds.
    Nothing else is a ref: transports, reasons and
    other detail facts stay in the detail, where a
    reader can find them without pretending they
    reference an object.
    """
    refs: list[str] = []

    def add(ref: str) -> None:
        if ref not in refs:
            refs.append(ref)

    repo = repository_of(target_id)
    if repo is not None:
        add(f"repo:{repo}")
    if target_id and "#" in target_id:
        tail = target_id.split("#", 1)[1]
        if tail.isdigit():
            add(f"number:{int(tail)}")
    if isinstance(detail, dict):
        number = detail.get("number")
        if isinstance(number, int) and not isinstance(number, bool):
            add(f"number:{number}")
        raw_refs = detail.get("refs")
        if isinstance(raw_refs, list):
            for item in raw_refs:
                if isinstance(item, str) and item:
                    add(item)
    return tuple(refs)


@dataclass(frozen=True)
class CanonicalEvent:
    id: int
    audit_seq: int
    actor_kind: str
    actor_id: int | None
    actor: str           # account name; '' when unknown
    verb: str
    target_kind: str
    target_id: str | None
    refs: tuple[str, ...]
    detail: dict
    outcome: str
    created_at: int      # the timestamp: the witness's ts

    @property
    def action(self) -> str:
        return self.verb.rsplit(".", 1)[-1]

    @property
    def repository(self) -> str | None:
        return repository_of(self.target_id)

    @property
    def number(self) -> int | None:
        for ref in self.refs:
            if ref.startswith("number:"):
                return int(ref.split(":", 1)[1])
        return None


def event_payload(event: CanonicalEvent) -> dict:
    """The event in Samverk's payload shape (the
    S-139 shape, generalised): stable fields, refs
    as a list, detail carried unchanged, and a
    delivery id (`evt-<event id>`) that is stable
    across redelivery so a receiver can dedupe."""
    return {
        "delivery_id": f"evt-{event.id}",
        "event": event.verb,
        "action": event.action,
        "actor": event.actor or None,
        "target": event.target_id,
        "repository": event.repository,
        "number": event.number,
        "refs": list(event.refs),
        "detail": event.detail,
        "occurred_at": event.created_at,
    }


def payload_json(event: CanonicalEvent) -> str:
    """The payload as canonical JSON (sorted keys,
    tight separators) -- the bytes a signing road
    would sign."""
    return json.dumps(event_payload(event), sort_keys=True,
                      separators=(",", ":"))


class EventStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts

    # -- materialisation ---------------------------------
    def sync_all(self) -> int:
        """Materialise every witnessed mutation into
        the canonical store; returns how many events
        were newly emitted (0 on a re-sync -- exactly-
        once is the UNIQUE audit_seq doing its work)."""
        rows = self._conn.execute(
            "SELECT seq, ts, actor_kind, actor_id, action,"
            " target_kind, target_id, outcome, detail"
            " FROM audit_log ORDER BY seq").fetchall()
        return self._sync(rows)

    def sync_repo(self, owner: object, repo: object) -> int:
        """Materialise one repository's witnessed
        mutations; returns how many were newly emitted.
        A missing repository is named, never faked."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise EventStoreError(
                "repo_not_found", "No such repository.")
        rows = self._conn.execute(
            "SELECT seq, ts, actor_kind, actor_id, action,"
            " target_kind, target_id, outcome, detail"
            " FROM audit_log ORDER BY seq").fetchall()
        mine = [r for r in rows
                if repository_of(r["target_id"]) == current.full_name]
        return self._sync(mine)

    def _sync(self, rows) -> int:
        emitted = 0
        with self._conn:  # the batch lands whole, or not at all
            for row in rows:
                detail = _parse_detail(row["detail"])
                refs = derive_refs(
                    row["action"], row["target_kind"],
                    row["target_id"], detail)
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO events"
                    " (audit_seq, actor_kind, actor_id, verb,"
                    " target_kind, target_id, refs_json,"
                    " detail_json, outcome, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (int(row["seq"]), row["actor_kind"],
                     row["actor_id"], row["action"],
                     row["target_kind"], row["target_id"],
                     json.dumps(list(refs), separators=(",", ":")),
                     row["detail"] or "{}", row["outcome"],
                     int(row["ts"])))
                emitted += int(cur.rowcount)
        return emitted

    # -- visibility ----------------------------------------
    def _repo_for(self, event: CanonicalEvent) -> Repository | None:
        full = event.repository
        if full is None:
            return None
        owner, _, name = full.partition("/")
        return self._repos.get_repository(owner, name)

    def visible_to(self, viewer: User | None,
                   event: CanonicalEvent) -> bool:
        return event_visible_to(
            viewer, event, self._repo_for(event))

    # -- reads (each syncs first: never stale) -------------
    def list_for_repo(self, viewer: User | None, owner: object,
                      repo: object, *, limit: int = 100,
                      verb_prefix: str | None = None
                      ) -> list[CanonicalEvent]:
        """One repository's canonical events, newest
        first. Read access is the gate: a stranger to
        a private repository gets the uniform
        `repo_not_found`."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise EventStoreError(
                "repo_not_found", "No such repository.")
        self.sync_repo(owner, repo)
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT * FROM events ORDER BY id DESC").fetchall()
        events = [self._to_event(r) for r in rows
                  if repository_of(r["target_id"]) == current.full_name]
        if verb_prefix is not None:
            events = [e for e in events
                      if e.verb.startswith(verb_prefix)]
        return events[:clamped]

    def count_for_repo(self, viewer: User | None, owner: object,
                       repo: object) -> int:
        return len(self.list_for_repo(viewer, owner, repo, limit=500))

    def list_for_actor(self, viewer: User | None, actor: object,
                       *, limit: int = 100
                       ) -> list[CanonicalEvent]:
        """One actor's events, newest first, filtered
        event by event to what this viewer may see --
        the S-230 rule applied at the store, so no
        caller can forget it. An unknown actor is
        `no_such_user`."""
        subject = self._resolve_actor(actor)
        self.sync_all()
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT * FROM events WHERE actor_id = ?"
            " ORDER BY id DESC", (subject.id,)).fetchall()
        events = [e for e in (self._to_event(r) for r in rows)
                  if self.visible_to(viewer, e)]
        return events[:clamped]

    def count_for_actor(self, viewer: User | None,
                        actor: object) -> int:
        return len(self.list_for_actor(viewer, actor, limit=500))

    def list_public(self, *, limit: int = 100
                    ) -> list[CanonicalEvent]:
        """The instance's public-activity face (S-229):
        events on public repositories only, newest
        first. Private repositories contribute no row,
        and non-repository events never appear here."""
        self.sync_all()
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT * FROM events ORDER BY id DESC").fetchall()
        events: list[CanonicalEvent] = []
        for row in rows:
            event = self._to_event(row)
            repo = self._repo_for(event)
            if repo is not None and repo.visibility == "public":
                events.append(event)
                if len(events) >= clamped:
                    break
        return events

    def get_event(self, viewer: User | None,
                  event_id: object) -> CanonicalEvent:
        """One event by id, under the same visibility
        law as every other face: an event this viewer
        may not see is `event_not_found`, exactly like
        one that does not exist."""
        if isinstance(event_id, bool) or not isinstance(event_id, int):
            raise EventStoreError(
                "event_not_found", "No such event.")
        self.sync_all()
        row = self._conn.execute(
            "SELECT * FROM events WHERE id = ?",
            (event_id,)).fetchone()
        if row is None:
            raise EventStoreError(
                "event_not_found", "No such event.")
        event = self._to_event(row)
        if not self.visible_to(viewer, event):
            raise EventStoreError(
                "event_not_found", "No such event.")
        return event

    # -- helpers -------------------------------------------
    def _resolve_actor(self, actor: object) -> User:
        subject: User | None = None
        if isinstance(actor, int) and not isinstance(actor, bool):
            subject = self._accounts.get_by_id(actor)
        elif isinstance(actor, User):
            subject = self._accounts.get_by_id(actor.id)
        elif isinstance(actor, str):
            subject = self._accounts.get_by_username(actor)
        if subject is None:
            raise EventStoreError(
                "no_such_user", "No such account.")
        return subject

    def _to_event(self, row: sqlite3.Row) -> CanonicalEvent:
        try:
            refs = tuple(json.loads(row["refs_json"] or "[]"))
        except ValueError:
            refs = ()
        actor = (self._accounts.get_by_id(int(row["actor_id"]))
                 if row["actor_id"] else None)
        return CanonicalEvent(
            id=int(row["id"]), audit_seq=int(row["audit_seq"]),
            actor_kind=row["actor_kind"], actor_id=row["actor_id"],
            actor=actor.username if actor else "",
            verb=row["verb"], target_kind=row["target_kind"],
            target_id=row["target_id"],
            refs=tuple(str(r) for r in refs),
            detail=_parse_detail(row["detail_json"]),
            outcome=row["outcome"], created_at=int(row["created_at"]))


def _parse_detail(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def event_visible_to(viewer: User | None, event: CanonicalEvent,
                     repo: Repository | None) -> bool:
    """Pure visibility law for one canonical event.

    Judged in order: the actor themself and site
    admins see the event; a repository event is
    visible exactly when the viewer can read that
    repository (S-054's `can_read`, so public repos
    are visible to everyone, including anonymous
    viewers, and private repos to no stranger); an
    organization event names a public directory fact
    and is visible to everyone; every other event
    (account and instance facts) is visible to no
    one else. A repository target that no longer
    resolves fails closed.
    """
    if viewer is not None:
        if viewer.is_admin:
            return True
        if event.actor_id is not None and viewer.id == event.actor_id:
            return True
    if event.repository is not None:
        if repo is None:
            return False
        return can_read(viewer, repo)
    if event.target_kind == "organization":
        return True
    return False


def render_events_page(events, *, heading: str = "Activity") -> str:
    """A plain feed page: every event in words --
    who did what to what, and when -- with all
    user-controlled text escaped through S-010's
    seam. Counts are stated in text, never by
    colour alone; an empty feed says so and teaches
    the model in one line."""
    lines = [
        f"<h1>{escape_html_text(heading)}</h1>",
        f"<p>{len(events)} event(s).</p>",
    ]
    if not events:
        lines.append(
            "<p>No activity yet. Events appear here when"
            " something changes: an issue opened, a push"
            " landed, a repository created.</p>")
        return "\n".join(lines)
    lines.append("<ul>")
    for event in events:
        actor = escape_html_text(event.actor or event.actor_kind)
        verb = escape_html_text(event.verb)
        target = escape_html_text(event.target_id or event.target_kind)
        refs = escape_html_text(", ".join(event.refs))
        ref_part = f" ({refs})" if refs else ""
        lines.append(
            f"<li>{actor} - {verb} - {target}{ref_part}"
            f" - {event.created_at}</li>")
    lines.append("</ul>")
    return "\n".join(lines)
