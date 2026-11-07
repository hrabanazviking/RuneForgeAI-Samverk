"""Index architecture (S-205).

What is indexed (issues, PRs, commits, code), when
(on push, on mutation), and how rebuilds work — the
foundation Part X builds on, written from research
file 18. This slice builds the architecture itself:
the catalog, the trigger law, the coverage law, the
background queue, the per-repository state, and the
document registry. The extractors and query engines
that fill and read the registry are the slices that
follow (S-206 issue/PR backend, S-207 code indexing,
S-208 code search, S-212 commit search); nothing here
pretends to be one of them.

- **What is indexed is a catalog, not a habit.**
  ``KIND_SPECS`` names exactly four kinds. *Issues*
  and *pull requests* index the shared numbered row
  (title, body, state, author) plus their structured
  fields (labels, assignees, milestone for issues;
  draft and branch pair for pull requests), keyed by
  (repository, number). *Commits* index message and
  author for the commits a push makes reachable,
  keyed by (repository, oid) — never every object in
  history by default (research 18). *Code* indexes
  the default branch's tip snapshot, one document
  per file, keyed by (repository, commit oid, path,
  content digest) — research 18's index key verbatim
  — so a changed file is a new document and an
  unchanged file is the same one.
- **When is two triggers, said plainly.** Code and
  commits index **on push**: a push that moves any
  branch enqueues a commit job; a push that moves
  the default branch also enqueues a code job (the
  snapshot moved). Issues and pull requests index
  **on mutation**: creating, editing, or changing
  the state of a numbered item enqueues one job for
  that item. ``plan_push`` and ``plan_mutation`` are
  the pure trigger law; the store enqueues what
  they plan. A push never waits for indexing —
  enqueueing is the whole of the push path's duty
  (research 18: never block push success on search
  rebuilding).
- **The queue coalesces and retries honestly.**
  Work waits in migration 80's ``index_jobs``,
  deduplicated by (repository, kind, target): ten
  edits to one issue while its job still waits are
  one job, because the worker reads the item as it
  stands when the job runs, not as it stood at each
  edit. A claimed job that fails returns to pending
  until ``MAX_ATTEMPTS``, then rests ``dead`` with
  its last error kept — never silently dropped, and
  visible in the queue's counts. Workers claim the
  oldest pending job first.
- **State is per (repository, kind) and freshness
  is shown, never hidden.** ``index_state`` carries
  the status in words (``never``, ``queued``,
  ``indexing``, ``current``, ``stale``, ``failed``),
  the high-water mark the worker last completed
  (a commit oid for push kinds, a document key for
  mutation kinds), and the generation. An index
  that lags says so through its state and the
  queue's lag; S-215's admin health page renders
  this same state, it does not invent its own.
- **Rebuilds work by generation.** Requesting a
  rebuild marks the state ``stale`` and enqueues a
  rebuild job carrying the *next* generation. The
  worker writes the fresh documents at that next
  generation while reads keep serving the current
  one whole — a half-rebuilt index is never served
  — and finishing the job flips the served
  generation to the new one and purges the older
  generations' rows. A crash mid-
  rebuild therefore loses nothing that was not
  already stale-marked, and re-running the rebuild
  converges: no duplicate hits, no lost updates
  (research 18's rebuild acceptance, made a
  mechanism).
- **Coverage is a statement, not a shrug.** Code
  coverage is judged by the pure
  ``decide_code_disposition``: text within
  ``MAX_CODE_BLOB_BYTES`` is indexed; an LFS pointer
  is indexed *as a pointer* (its own text, honestly
  labelled — the S-207 law, fixed here so no later
  slice can quietly index the pointee instead);
  binaries, oversized blobs, submodule gitlinks,
  ignored paths, and empty files are not indexed,
  each for its named reason. What branches: only
  the default branch's snapshot for code; commits
  from every branch a push moves.
- **Permission is not this slice's to grant.** The
  registry stores no visibility of its own: every
  later reader must filter through the repository
  read gate before a title, snippet, or count is
  shown (that filtering battery is S-209's, over
  this registry). The architecture page renders no
  repository content at all.
- **No audit event of its own.** Enqueueing is
  derived bookkeeping over acts already on the
  record (the push's S-090 event, the mutation's
  own audit); a rebuild request here is an internal
  seam whose admin-facing, audited door is S-215's.
  122 events stand: 31 auth / 79 repo / 12 admin.
  Storage is migration 80 (schema 79 to 80).
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .escaping import escape_html_text
from .hooks import RefUpdate
from .repositories import Repository, RepositoryStore

__all__ = [
    "INDEX_KINDS", "JOB_STATUSES", "KIND_SPECS",
    "MAX_ATTEMPTS", "MAX_CODE_BLOB_BYTES", "MUTATION_KINDS",
    "PUSH_KINDS", "STATE_STATUSES", "TRIGGERS",
    "IndexDocument", "IndexJob", "IndexKindSpec", "IndexState",
    "PlannedJob", "QueueSnapshot", "SearchIndexError",
    "SearchIndexStore", "decide_code_disposition", "plan_mutation",
    "plan_push", "render_index_architecture_page",
    "render_index_state_page", "spec_for",
]

INDEX_KINDS = ("issue", "pull_request", "commit", "code")
PUSH_KINDS = frozenset({"commit", "code"})
MUTATION_KINDS = frozenset({"issue", "pull_request"})
TRIGGERS = frozenset({"push", "mutation", "rebuild"})
JOB_STATUSES = frozenset({"pending", "running", "done", "failed", "dead"})
STATE_STATUSES = frozenset(
    {"never", "queued", "indexing", "current", "stale", "failed"})
MAX_ATTEMPTS = 3
MAX_CODE_BLOB_BYTES = 1_048_576
ZERO_OID_PREFIX = "0"


class SearchIndexError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class IndexKindSpec:
    """One indexed kind: what it is, where its text
    and structured fields live, when it is indexed,
    and the key its documents carry."""
    kind: str
    title: str
    source: str
    fields: tuple[str, ...]
    triggers: tuple[str, ...]
    key_fields: tuple[str, ...]
    freshness: str


KIND_SPECS: dict[str, IndexKindSpec] = {
    "issue": IndexKindSpec(
        kind="issue", title="Issues",
        source="the shared numbered row (issues, kind 'issue') "
               "with its label, assignee and milestone relations",
        fields=("title", "body", "state", "author", "labels",
                "assignees", "milestone", "repository", "number"),
        triggers=("mutation",),
        key_fields=("repo_id", "number"),
        freshness="re-indexed when the issue is created, edited, "
                  "or changes state, labels, assignees or milestone"),
    "pull_request": IndexKindSpec(
        kind="pull_request", title="Pull requests",
        source="the shared numbered row (issues, kind "
               "'pull_request') with its pull_requests branch pair",
        fields=("title", "body", "state", "author", "labels",
                "draft", "base_branch", "head_branch",
                "repository", "number"),
        triggers=("mutation",),
        key_fields=("repo_id", "number"),
        freshness="re-indexed when the pull request is created, "
                  "edited, or changes state, draft or branches"),
    "commit": IndexKindSpec(
        kind="commit", title="Commits",
        source="the commit objects a push makes reachable from "
               "a branch tip (never every object in history)",
        fields=("message", "author", "oid", "repository"),
        triggers=("push",),
        key_fields=("repo_id", "oid"),
        freshness="indexed when a push moves a branch; the "
                  "high-water mark is the newest tip indexed"),
    "code": IndexKindSpec(
        kind="code", title="Code",
        source="the default branch tip snapshot, one document "
               "per file at that commit",
        fields=("path", "text", "language", "repository"),
        triggers=("push",),
        key_fields=("repo_id", "commit_oid", "path", "digest"),
        freshness="re-indexed when a push moves the default "
                  "branch; the high-water mark is the tip oid"),
}


def spec_for(kind: object) -> IndexKindSpec:
    """The catalog entry for one kind. An unknown
    kind is refused ``kind_invalid`` — the catalog is
    closed, so a typo can never index a fifth thing."""
    if not isinstance(kind, str) or kind not in KIND_SPECS:
        raise SearchIndexError(
            "kind_invalid", f"No such index kind: {kind!r}.")
    return KIND_SPECS[kind]


@dataclass(frozen=True)
class PlannedJob:
    kind: str
    trigger: str
    target: str = ""


def _is_zero_oid(oid: object) -> bool:
    return isinstance(oid, str) and bool(oid) and set(oid) == {"0"}


def plan_push(default_branch: object,
              updates: Iterable[RefUpdate]) -> tuple[PlannedJob, ...]:
    """The pure push trigger law: what one accepted
    push enqueues. Any branch movement (creation,
    update, or deletion under ``refs/heads/``)
    enqueues the commit job; movement of the default
    branch also enqueues the code job, because the
    indexed snapshot is the default branch's tip.
    Tags and other refs enqueue nothing. The target
    of a push job is the repository itself (``''``):
    the worker diffs from the high-water mark when
    the job runs, so rapid pushes coalesce."""
    branch_moves = [
        u for u in updates
        if isinstance(u, RefUpdate) and u.ref.startswith("refs/heads/")]
    if not branch_moves:
        return ()
    plans = [PlannedJob("commit", "push", "")]
    default_ref = f"refs/heads/{default_branch}"
    if any(u.ref == default_ref for u in branch_moves):
        plans.append(PlannedJob("code", "push", ""))
    return tuple(plans)


def plan_mutation(kind: object, target: object) -> tuple[PlannedJob, ...]:
    """The pure mutation trigger law: one job for the
    mutated item. Only issues and pull requests
    mutate; commits and code change only by push, and
    asking to mutation-index them is refused
    ``kind_invalid`` rather than silently queued. The
    target names the item (its document key, e.g.
    ``issue:12``) and must be non-empty text."""
    spec = spec_for(kind)
    if spec.kind not in MUTATION_KINDS:
        raise SearchIndexError(
            "kind_invalid",
            f"{spec.title} are indexed on push, not on mutation.")
    if not isinstance(target, str) or not target.strip():
        raise SearchIndexError(
            "target_invalid", "A mutation job needs its item key.")
    return (PlannedJob(spec.kind, "mutation", target.strip()),)


def decide_code_disposition(*, size: object, is_binary: bool = False,
                            is_lfs_pointer: bool = False,
                            is_submodule: bool = False,
                            is_ignored: bool = False) -> tuple[str, str]:
    """The pure coverage law for one code file, as
    (disposition, reason). Dispositions: ``index``
    (the file's text is indexed), ``index_pointer``
    (an LFS pointer, indexed as the pointer it is),
    and ``skip`` (not indexed, for the named reason).
    The order is the honesty order: a submodule has
    no blob to misread, a pointer is judged before
    its size, and an ignored path is out before its
    bytes are weighed."""
    if is_submodule:
        return ("skip", "submodule")
    if is_lfs_pointer:
        return ("index_pointer", "lfs_pointer")
    if is_ignored:
        return ("skip", "ignored")
    if is_binary:
        return ("skip", "binary")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return ("skip", "size_unknown")
    if size > MAX_CODE_BLOB_BYTES:
        return ("skip", "oversized")
    if size == 0:
        return ("skip", "empty")
    return ("index", "indexed")


@dataclass(frozen=True)
class IndexJob:
    id: int
    repo_id: int
    kind: str
    trigger: str
    target: str
    status: str
    attempts: int
    generation: int
    enqueued_at: int
    started_at: int | None
    finished_at: int | None
    last_error: str


@dataclass(frozen=True)
class IndexState:
    repo_id: int
    kind: str
    status: str
    generation: int
    high_water: str
    document_count: int
    updated_at: int
    last_error: str

    @property
    def is_current(self) -> bool:
        return self.status == "current"


@dataclass(frozen=True)
class IndexDocument:
    id: int
    repo_id: int
    kind: str
    doc_key: str
    commit_oid: str
    path: str
    digest: str
    generation: int
    updated_at: int


@dataclass(frozen=True)
class QueueSnapshot:
    pending: int
    running: int
    done: int
    dead: int
    oldest_pending_at: int | None
    lag_seconds: int


class SearchIndexStore:
    """The index architecture's working store: the
    queue, the per-(repository, kind) state, and the
    document registry of migration 80. Every write
    commits before it answers (the commit-before-
    answer law), so a returned job or state is
    visible to the worker that will claim it."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._repos = repositories
        self._now = time_fn

    # -- lookups --------------------------------------
    def _resolve(self, owner: object, repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise SearchIndexError(
                "repo_not_found", "No such repository.")
        return current

    def _job_from(self, row: sqlite3.Row) -> IndexJob:
        return IndexJob(
            id=int(row["id"]), repo_id=int(row["repo_id"]),
            kind=row["kind"], trigger=row["trigger_kind"],
            target=row["target"], status=row["status"],
            attempts=int(row["attempts"]),
            generation=int(row["generation"]),
            enqueued_at=int(row["enqueued_at"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            last_error=row["last_error"])

    def _state_row(self, repo_id: int, kind: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM index_state WHERE repo_id = ? AND kind = ?",
            (repo_id, kind)).fetchone()

    def _generation(self, repo_id: int, kind: str) -> int:
        row = self._state_row(repo_id, kind)
        return int(row["generation"]) if row else 0

    def _document_count(self, repo_id: int, kind: str,
                        generation: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM index_documents"
            " WHERE repo_id = ? AND kind = ? AND generation = ?",
            (repo_id, kind, generation)).fetchone()
        return int(row["c"])

    def _set_state(self, repo_id: int, kind: str, *, status: str,
                   generation: int | None = None,
                   high_water: str | None = None,
                   last_error: str | None = None) -> None:
        """Upsert one state row inside the caller's
        transaction. Only the named fields move."""
        now = int(self._now())
        row = self._state_row(repo_id, kind)
        if row is None:
            self._conn.execute(
                "INSERT INTO index_state (repo_id, kind, status,"
                " generation, high_water, updated_at, last_error)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (repo_id, kind, status,
                 generation if generation is not None else 0,
                 high_water if high_water is not None else "",
                 now,
                 last_error if last_error is not None else ""))
            return
        self._conn.execute(
            "UPDATE index_state SET status = ?, generation = ?,"
            " high_water = ?, updated_at = ?, last_error = ?"
            " WHERE repo_id = ? AND kind = ?",
            (status,
             generation if generation is not None else int(row["generation"]),
             high_water if high_water is not None else row["high_water"],
             now,
             last_error if last_error is not None else row["last_error"],
             repo_id, kind))

    # -- state reads ------------------------------------
    def state_for(self, owner: object, repo: object,
                  kind: object) -> IndexState:
        """One kind's state for one repository. A kind
        never touched reads as ``never`` at generation
        0 — the state is synthesised, never invented
        as current."""
        spec = spec_for(kind)
        current = self._resolve(owner, repo)
        row = self._state_row(current.id, spec.kind)
        if row is None:
            return IndexState(
                repo_id=current.id, kind=spec.kind, status="never",
                generation=0, high_water="",
                document_count=self._document_count(
                    current.id, spec.kind, 0),
                updated_at=0, last_error="")
        generation = int(row["generation"])
        return IndexState(
            repo_id=current.id, kind=spec.kind, status=row["status"],
            generation=generation, high_water=row["high_water"],
            document_count=self._document_count(
                current.id, spec.kind, generation),
            updated_at=int(row["updated_at"]),
            last_error=row["last_error"])

    def states_for_repo(self, owner: object,
                        repo: object) -> tuple[IndexState, ...]:
        """Every kind's state for one repository, in
        catalog order."""
        return tuple(
            self.state_for(owner, repo, kind) for kind in INDEX_KINDS)

    # -- enqueueing -------------------------------------
    def enqueue(self, owner: object, repo: object, *,
                kind: object, trigger: object,
                target: object = "") -> IndexJob:
        """Enqueue one unit of work, coalesced: a
        pending or running job with the same
        (repository, kind, target) is returned as it
        stands instead of duplicated. Enqueueing
        moves the kind's state to ``queued`` unless a
        worker is already ``indexing`` it."""
        spec = spec_for(kind)
        if not isinstance(trigger, str) or trigger not in TRIGGERS:
            raise SearchIndexError(
                "trigger_invalid", f"No such trigger: {trigger!r}.")
        if trigger == "push" and spec.kind not in PUSH_KINDS:
            raise SearchIndexError(
                "trigger_invalid",
                f"{spec.title} are not indexed on push.")
        if trigger == "mutation" and spec.kind not in MUTATION_KINDS:
            raise SearchIndexError(
                "trigger_invalid",
                f"{spec.title} are not indexed on mutation.")
        if not isinstance(target, str):
            raise SearchIndexError(
                "target_invalid", "A job target is text.")
        target = target.strip()
        if trigger == "mutation" and not target:
            raise SearchIndexError(
                "target_invalid", "A mutation job needs its item key.")
        current = self._resolve(owner, repo)
        dedupe_key = f"{current.id}:{spec.kind}:{target}"
        existing = self._conn.execute(
            "SELECT * FROM index_jobs WHERE dedupe_key = ?"
            " AND status IN ('pending', 'running')",
            (dedupe_key,)).fetchone()
        if existing is not None:
            return self._job_from(existing)
        now = int(self._now())
        generation = self._generation(current.id, spec.kind)
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO index_jobs (repo_id, kind, trigger_kind,"
                " target, dedupe_key, status, attempts, generation,"
                " enqueued_at) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)",
                (current.id, spec.kind, trigger, target, dedupe_key,
                 generation, now))
            row = self._state_row(current.id, spec.kind)
            if row is None or row["status"] != "indexing":
                self._set_state(current.id, spec.kind, status="queued")
            job_id = int(cur.lastrowid)
        found = self._conn.execute(
            "SELECT * FROM index_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_from(found)

    def enqueue_push(self, owner: object, repo: object,
                     updates: Iterable[RefUpdate]) -> tuple[IndexJob, ...]:
        """Enqueue what one accepted push plans, per
        ``plan_push`` over the repository's default
        branch. A push that moves no branch enqueues
        nothing and returns an empty tuple."""
        current = self._resolve(owner, repo)
        plans = plan_push(current.default_branch, list(updates))
        return tuple(
            self.enqueue(owner, repo, kind=p.kind, trigger=p.trigger,
                         target=p.target)
            for p in plans)

    def enqueue_mutation(self, owner: object, repo: object, *,
                         kind: object,
                         target: object) -> IndexJob:
        """Enqueue the one job a mutation plans."""
        plans = plan_mutation(kind, target)
        plan = plans[0]
        return self.enqueue(owner, repo, kind=plan.kind,
                            trigger=plan.trigger, target=plan.target)

    # -- the worker road ---------------------------------
    def claim_next(self) -> IndexJob | None:
        """Claim the oldest pending job: it moves to
        ``running``, its attempt count rises, and its
        kind's state reads ``indexing``. No pending
        job answers None — an idle queue is a state,
        not an error."""
        row = self._conn.execute(
            "SELECT * FROM index_jobs WHERE status = 'pending'"
            " ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return None
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE index_jobs SET status = 'running',"
                " attempts = attempts + 1, started_at = ?,"
                " finished_at = NULL WHERE id = ?", (now, row["id"]))
            self._set_state(int(row["repo_id"]), row["kind"],
                            status="indexing")
        found = self._conn.execute(
            "SELECT * FROM index_jobs WHERE id = ?",
            (row["id"],)).fetchone()
        return self._job_from(found)

    def _require_job(self, job_id: object) -> sqlite3.Row:
        if not isinstance(job_id, int) or isinstance(job_id, bool):
            raise SearchIndexError(
                "job_invalid", "A job is named by its integer id.")
        row = self._conn.execute(
            "SELECT * FROM index_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise SearchIndexError("job_not_found", "No such index job.")
        return row

    def _pending_for(self, repo_id: int, kind: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM index_jobs WHERE repo_id = ?"
            " AND kind = ? AND status IN ('pending', 'running')",
            (repo_id, kind)).fetchone()
        return int(row["c"])

    def complete_job(self, job_id: object, *,
                     high_water: object = "") -> IndexJob:
        """Finish a running job: it rests ``done``;
        a rebuild job first purges every other
        generation's documents and flips the served
        generation to its own, so completion is the
        moment the new generation becomes the whole
        registry. The kind's state reads ``current``
        when no work for it remains waiting, else
        ``queued``; the high-water mark moves only
        when one is named."""
        row = self._require_job(job_id)
        if row["status"] != "running":
            raise SearchIndexError(
                "job_not_running", "Only a running job can complete.")
        if not isinstance(high_water, str):
            raise SearchIndexError(
                "target_invalid", "A high-water mark is text.")
        now = int(self._now())
        repo_id, kind = int(row["repo_id"]), row["kind"]
        with self._conn:
            if row["trigger_kind"] == "rebuild":
                self._conn.execute(
                    "DELETE FROM index_documents WHERE repo_id = ?"
                    " AND kind = ? AND generation != ?",
                    (repo_id, kind, int(row["generation"])))
            self._conn.execute(
                "UPDATE index_jobs SET status = 'done', finished_at = ?"
                " WHERE id = ?", (now, row["id"]))
            remaining = self._pending_for(repo_id, kind)
            flip = int(row["generation"]) if row["trigger_kind"] == "rebuild" else None
            self._set_state(
                repo_id, kind,
                status="queued" if remaining else "current",
                generation=flip,
                high_water=high_water if high_water else None,
                last_error="")
        found = self._conn.execute(
            "SELECT * FROM index_jobs WHERE id = ?",
            (row["id"],)).fetchone()
        return self._job_from(found)

    def fail_job(self, job_id: object, error: object) -> IndexJob:
        """Fail a running job, honestly: below
        ``MAX_ATTEMPTS`` it returns to ``pending``
        for a retry and the kind reads ``stale`` (its
        data is behind and says so); at the limit it
        rests ``dead`` and the kind reads ``failed``.
        The error text is kept on both the job and
        the state — a failure is a fact, not a gap."""
        row = self._require_job(job_id)
        if row["status"] != "running":
            raise SearchIndexError(
                "job_not_running", "Only a running job can fail.")
        message = error if isinstance(error, str) else str(error)
        message = message.strip()[:500] or "indexing failed"
        now = int(self._now())
        repo_id, kind = int(row["repo_id"]), row["kind"]
        dead = int(row["attempts"]) >= MAX_ATTEMPTS
        with self._conn:
            if dead:
                self._conn.execute(
                    "UPDATE index_jobs SET status = 'dead',"
                    " finished_at = ?, last_error = ? WHERE id = ?",
                    (now, message, row["id"]))
                self._set_state(repo_id, kind, status="failed",
                                last_error=message)
            else:
                self._conn.execute(
                    "UPDATE index_jobs SET status = 'pending',"
                    " last_error = ? WHERE id = ?",
                    (message, row["id"]))
                self._set_state(repo_id, kind, status="stale",
                                last_error=message)
        found = self._conn.execute(
            "SELECT * FROM index_jobs WHERE id = ?",
            (row["id"],)).fetchone()
        return self._job_from(found)

    # -- rebuilds -----------------------------------------
    def request_rebuild(self, owner: object, repo: object, *,
                        kind: object = None) -> tuple[IndexJob, ...]:
        """Request a rebuild of one kind, or of every
        kind when none is named: the state reads
        ``stale`` (the old generation is still served
        whole, and is labelled behind), and a rebuild
        job is enqueued carrying the next generation. Any still-waiting job for the
        kind is superseded — deleted, because its work
        is contained in the rebuild — so a rebuild can
        never be overtaken by the work it replaces."""
        current = self._resolve(owner, repo)
        kinds = [spec_for(kind).kind] if kind is not None else list(INDEX_KINDS)
        jobs: list[IndexJob] = []
        for one in kinds:
            with self._conn:
                generation = self._generation(current.id, one) + 1
                self._conn.execute(
                    "DELETE FROM index_jobs WHERE repo_id = ? AND kind = ?"
                    " AND status = 'pending'", (current.id, one))
                now = int(self._now())
                dedupe_key = f"{current.id}:{one}:rebuild:{generation}"
                cur = self._conn.execute(
                    "INSERT INTO index_jobs (repo_id, kind, trigger_kind,"
                    " target, dedupe_key, status, attempts, generation,"
                    " enqueued_at) VALUES (?, ?, 'rebuild', '', ?,"
                    " 'pending', 0, ?, ?)",
                    (current.id, one, dedupe_key, generation, now))
                job_id = int(cur.lastrowid)
                self._set_state(current.id, one, status="stale")
            found = self._conn.execute(
                "SELECT * FROM index_jobs WHERE id = ?",
                (job_id,)).fetchone()
            jobs.append(self._job_from(found))
        return tuple(jobs)

    # -- the document registry -----------------------------
    def put_document(self, owner: object, repo: object, *,
                     kind: object, doc_key: object,
                     commit_oid: object = "", path: object = "",
                     digest: object = "",
                     generation: object = None) -> IndexDocument:
        """Write one indexed document into the
        registry, replacing any row with the same
        (repository, kind, document key). The
        generation defaults to the kind's current
        generation; a rebuild worker passes its job's
        generation explicitly. Writing a document
        never moves the kind's status — freshness is
        the job lifecycle's word, not a side effect."""
        spec = spec_for(kind)
        if not isinstance(doc_key, str) or not doc_key.strip():
            raise SearchIndexError(
                "target_invalid", "A document needs its key.")
        for value in (commit_oid, path, digest):
            if not isinstance(value, str):
                raise SearchIndexError(
                    "target_invalid", "Document key fields are text.")
        current = self._resolve(owner, repo)
        if generation is None:
            generation = self._generation(current.id, spec.kind)
        if not isinstance(generation, int) or isinstance(generation, bool) \
                or generation < 0:
            raise SearchIndexError(
                "target_invalid", "A generation is a non-negative integer.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO index_documents (repo_id, kind, doc_key,"
                " commit_oid, path, digest, generation, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (repo_id, kind, doc_key) DO UPDATE SET"
                " commit_oid = excluded.commit_oid,"
                " path = excluded.path, digest = excluded.digest,"
                " generation = excluded.generation,"
                " updated_at = excluded.updated_at",
                (current.id, spec.kind, doc_key.strip(), commit_oid,
                 path, digest, generation, now))
            row = self._conn.execute(
                "SELECT * FROM index_documents WHERE repo_id = ?"
                " AND kind = ? AND doc_key = ?",
                (current.id, spec.kind, doc_key.strip())).fetchone()
        return IndexDocument(
            id=int(row["id"]), repo_id=int(row["repo_id"]),
            kind=row["kind"], doc_key=row["doc_key"],
            commit_oid=row["commit_oid"], path=row["path"],
            digest=row["digest"], generation=int(row["generation"]),
            updated_at=int(row["updated_at"]))

    def documents_for(self, owner: object, repo: object, *,
                      kind: object) -> tuple[IndexDocument, ...]:
        """The documents a reader may be served: the
        current generation's rows for one kind, in
        document-key order. Older generations — a
        rebuild still in flight — are never served."""
        spec = spec_for(kind)
        current = self._resolve(owner, repo)
        generation = self._generation(current.id, spec.kind)
        rows = self._conn.execute(
            "SELECT * FROM index_documents WHERE repo_id = ? AND kind = ?"
            " AND generation = ? ORDER BY doc_key",
            (current.id, spec.kind, generation)).fetchall()
        return tuple(
            IndexDocument(
                id=int(r["id"]), repo_id=int(r["repo_id"]), kind=r["kind"],
                doc_key=r["doc_key"], commit_oid=r["commit_oid"],
                path=r["path"], digest=r["digest"],
                generation=int(r["generation"]),
                updated_at=int(r["updated_at"]))
            for r in rows)

    def remove_document(self, owner: object, repo: object, *,
                        kind: object, doc_key: object) -> bool:
        """Remove one document (its source was deleted
        or renamed away). True when a row was removed."""
        spec = spec_for(kind)
        current = self._resolve(owner, repo)
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM index_documents WHERE repo_id = ?"
                " AND kind = ? AND doc_key = ?",
                (current.id, spec.kind,
                 doc_key.strip() if isinstance(doc_key, str) else doc_key))
            return cur.rowcount > 0

    def purge_repo(self, owner: object, repo: object) -> None:
        """Erase every index trace of one repository
        (the repository-deletion seam): jobs, state,
        and documents. Search must never keep a ghost
        of a repository that no longer exists."""
        current = self._resolve(owner, repo)
        with self._conn:
            for table in ("index_jobs", "index_state", "index_documents"):
                self._conn.execute(
                    f"DELETE FROM {table} WHERE repo_id = ?", (current.id,))

    # -- queue health ---------------------------------------
    def queue_snapshot(self) -> QueueSnapshot:
        """The whole queue in counts, with its lag:
        the age of the oldest pending job. This is
        the number S-215's health page shows; lag is
        computed, never asserted."""
        counts = {status: 0 for status in JOB_STATUSES}
        for row in self._conn.execute(
                "SELECT status, COUNT(*) AS c FROM index_jobs"
                " GROUP BY status").fetchall():
            counts[row["status"]] = int(row["c"])
        oldest = self._conn.execute(
            "SELECT MIN(enqueued_at) AS m FROM index_jobs"
            " WHERE status = 'pending'").fetchone()["m"]
        lag = 0 if oldest is None else max(0, int(self._now()) - int(oldest))
        return QueueSnapshot(
            pending=counts["pending"], running=counts["running"],
            done=counts["done"], dead=counts["dead"],
            oldest_pending_at=oldest, lag_seconds=lag)


_STATE_WORDS = {
    "never": "never indexed",
    "queued": "waiting to be indexed",
    "indexing": "being indexed now",
    "current": "up to date",
    "stale": "behind — a rebuild or retry is owed",
    "failed": "indexing failed — see the recorded error",
}


def render_index_architecture_page() -> str:
    """The architecture itself, rendered for a person:
    what is indexed, when, how rebuilds work, and the
    coverage statement — all from the catalog and the
    coverage law, so the page cannot drift from the
    code. No repository content appears here."""
    parts = [
        "<h1>Search index</h1>",
        "<p>Samverk search reads an index, not the live "
        "tables and repositories. This page says what is "
        "in that index, when it is updated, and what is "
        "honestly left out.</p>",
        "<h2>What is indexed</h2>",
        "<ul>",
    ]
    for kind in INDEX_KINDS:
        spec = KIND_SPECS[kind]
        parts.append(
            f"<li><strong>{escape_html_text(spec.title)}</strong> — "
            f"from {escape_html_text(spec.source)}; fields: "
            f"{escape_html_text(', '.join(spec.fields))}; keyed by "
            f"{escape_html_text(', '.join(spec.key_fields))}. "
            f"{escape_html_text(spec.freshness.capitalize())}."
            "</li>")
    parts += [
        "</ul>",
        "<h2>When it is indexed</h2>",
        "<p>Commits and code are indexed on push: a push "
        "that moves any branch queues the commit index, "
        "and a push that moves the default branch also "
        "queues the code index. Issues and pull requests "
        "are indexed on mutation — when they are created "
        "or changed. Indexing runs in the background: a "
        "push never waits for it, and the index state "
        "says in words when it is behind.</p>",
        "<h2>How rebuilds work</h2>",
        "<p>A rebuild writes a fresh generation of the "
        "index while the current generation keeps being "
        "served whole. When the rebuild finishes, the "
        "new generation becomes the served one and the "
        "old rows are removed. A rebuild that stops "
        "halfway loses nothing and can simply be run "
        "again.</p>",
        "<h2>What code indexing leaves out</h2>",
        f"<p>Files larger than {MAX_CODE_BLOB_BYTES} bytes, "
        "binary files, submodule entries, ignored paths, "
        "and empty files are not indexed. A Git LFS "
        "pointer is indexed as the pointer it is — the "
        "file it points at is not indexed in its place. "
        "Code is indexed from the default branch only; "
        "commits are indexed from every branch a push "
        "moves.</p>",
    ]
    return "\n".join(parts)


def render_index_state_page(full_name: object,
                            states: tuple[IndexState, ...],
                            snapshot: QueueSnapshot) -> str:
    """One repository's index state, in words: each
    kind's freshness said plainly (never colour
    alone), its document count and high-water mark,
    and the queue's position behind it. All user text
    through S-010."""
    name = escape_html_text(full_name if isinstance(full_name, str) else "")
    parts = [
        f"<h1>Index state — {name}</h1>",
        "<ul>",
    ]
    for state in states:
        spec = KIND_SPECS[state.kind]
        words = _STATE_WORDS.get(state.status, state.status)
        line = (
            f"<li><strong>{escape_html_text(spec.title)}</strong> — "
            f"{escape_html_text(words)}; "
            f"{state.document_count} documents indexed")
        if state.high_water:
            line += f"; high-water mark {escape_html_text(state.high_water)}"
        if state.last_error:
            line += f"; last error: {escape_html_text(state.last_error)}"
        parts.append(line + "</li>")
    parts.append("</ul>")
    parts.append(
        f"<p>Index queue: {snapshot.pending} waiting, "
        f"{snapshot.running} running, {snapshot.dead} dead; "
        f"the oldest waiting job has waited "
        f"{snapshot.lag_seconds} seconds.</p>")
    return "\n".join(parts)
