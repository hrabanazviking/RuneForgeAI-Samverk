"""Code indexing (S-207).

On push, changed blobs extracted to the index within
the size/language budgets; LFS pointers indexed as
pointers, honestly — Part X's code extractor over the
S-205 index architecture, written from research
file 18. S-205 fixed the law (what code is, when it
indexes, and what coverage means); S-206 built the
issue/PR backend on it. This slice is the worker
that fills the code side of the registry: it reads
the default branch's tip snapshot from git, diffs
it against the previously indexed snapshot, and
extracts exactly the blobs that changed.

- **Changed blobs only.** A push indexes the delta,
  never the whole tree again: `diff_snapshots` is
  the pure delta law over two path -> (mode, blob
  oid) snapshots — a file whose blob oid and mode
  stand unchanged is the same document (S-205's key:
  repository, commit oid, path, content digest) and
  its bytes are never re-read. A first index (no
  previous snapshot) treats every file as changed;
  an explicit rebuild replaces the repository's
  rows whole, so a rebuild converges with no stale
  rows for files that no longer exist. Deletions
  are part of the delta: a file that leaves the
  snapshot leaves the index, in the same run.
- **The budgets are S-205's law, executed.** Every
  changed blob is judged by S-205's own
  `decide_code_disposition`, never by a second
  coverage law invented here: text within
  `MAX_CODE_BLOB_BYTES` (1 MiB) is indexed; a blob
  past it is skipped `oversized`; a binary blob
  (a NUL byte in its first bytes, git's own test)
  is skipped `binary`; an empty blob is skipped
  `empty`; a submodule gitlink — which carries no
  blob at all — is skipped `submodule`; a path the
  snapshot's own `.gitignore` ignores is skipped
  `ignored`. The language of every indexed file is
  detected from S-099's shared extension table (the
  seed S-218 grows) and recorded on its document;
  content no table can name is plain `text`, never
  guessed at. Every changed file's verdict — indexed,
  pointer, or skipped, each with its named reason —
  is returned in the run's report: what the index
  left out is said, file by file, never shrugged.
- **LFS pointers are indexed as pointers.** A blob
  that parses as a Git LFS pointer (S-060's strict
  parser) is indexed as the pointer it is: the
  indexed text is the pointer's own text, the
  document's disposition says `index_pointer`, and
  the pointer's target oid and size are recorded
  as what they are — claims about a file that
  lives in the LFS store, not in this snapshot.
  The pointee's bytes are never fetched, never
  indexed in the pointer's place, and never
  counted as if they were here (research 18's
  honesty law, fixed as S-205's `index_pointer`
  disposition so no later slice can quietly index
  the pointee instead). A file at an LFS path that
  is not a valid pointer is judged on its own
  bytes like any other blob.
- **The index is an FTS table plus the registry.**
  Indexed text lives in migration 82's `code_fts`
  (SQLite FTS5, the founding engine Part X names):
  path and text are the indexed text; repository,
  snapshot commit, content digest (the blob oid —
  the digest git itself proves), language,
  disposition, and the LFS facts ride as structured
  fields. Each indexed file also registers in
  S-205's document registry under the research-18
  key shape (`code:<path>` with its commit oid,
  path, and digest), so the architecture's document
  counts tell the truth about this extractor.
  Skipped files register nothing — the registry
  counts what is indexed, and the run's report is
  where skips are counted instead. Querying this
  index is S-208's slice; permission filtering of
  anything it returns is S-209's. This slice only
  fills the index and reads its own rows back.
- **A damaged repository refuses loudly.** A tip
  or blob that cannot be read answers by name
  (`commit_not_found`, `object_not_found`, ...)
  before anything is written — extraction computes
  the whole delta first, so a failed run leaves
  the previous index exactly as it stood.
- **No audit event of its own.** Indexing is
  derived data over the push's own S-090 record,
  rebuildable from the bare repository at any
  time; it writes only the FTS rows and S-205's
  registry. 122 events stand: 31 auth / 79 repo /
  12 admin. Storage is migration 82 (schema 81
  to 82).
"""

from __future__ import annotations

import fnmatch
import sqlite3
from dataclasses import dataclass

from .blob_view import detect_language
from .escaping import escape_html_text
from .hooks import RefUpdate
from .index_architecture import (
    SearchIndexStore, decide_code_disposition)
from .lfs_store import LFSError, LFSPointer, parse_pointer
from .objects import ObjectError, ObjectReader
from .refs import RefStore
from .repositories import Repository, RepositoryStore

__all__ = [
    "POINTER_LANGUAGE", "BlobJudgement", "CodeDocument",
    "CodeIndexError", "CodeIndexReport", "CodeIndexer",
    "FileOutcome", "TreeBlob", "diff_snapshots", "is_binary_data",
    "is_ignored_path", "judge_blob", "parse_gitignore",
    "render_code_index_page",
]

POINTER_LANGUAGE = "lfs-pointer"
_BINARY_PROBE_BYTES = 8192
_ZERO_OID = "0" * 40


class CodeIndexError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# ------------------------------------------------------------------
# Pure law: snapshots, deltas, ignore patterns, blob judgement
# ------------------------------------------------------------------

@dataclass(frozen=True)
class TreeBlob:
    """One leaf of a commit snapshot: its path, its
    tree mode (`100644`, `100755`, `120000`, or the
    gitlink's `160000`), and its blob oid (for a
    gitlink, the submodule's commit oid — there is
    no blob behind it in this repository)."""
    path: str
    mode: str
    oid: str

    @property
    def is_submodule(self) -> bool:
        return self.mode == "160000"


def diff_snapshots(
        old: dict[str, TreeBlob],
        new: dict[str, TreeBlob],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """The pure delta law: (changed, deleted,
    unchanged) path tuples, each sorted. A path is
    changed when it is new or its (mode, oid) pair
    moved; deleted when it stood in *old* and stands
    no longer; unchanged when the pair stands."""
    changed = tuple(sorted(
        path for path, blob in new.items()
        if path not in old
        or (old[path].mode, old[path].oid) != (blob.mode, blob.oid)))
    deleted = tuple(sorted(path for path in old if path not in new))
    unchanged = tuple(sorted(
        path for path in new
        if path in old
        and (old[path].mode, old[path].oid)
        == (new[path].mode, new[path].oid)))
    return changed, deleted, unchanged


def parse_gitignore(text: str) -> tuple[tuple[bool, str], ...]:
    """The snapshot `.gitignore`'s patterns, as
    (negated, pattern) pairs in file order. Blank
    lines and `#` comments carry no pattern; a
    leading `!` negates; a leading `/` is kept —
    it anchors the pattern to the snapshot root,
    which `is_ignored_path` judges."""
    patterns: list[tuple[bool, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:].strip()
        if line:
            patterns.append((negated, line))
    return tuple(patterns)


def _pattern_matches(pattern: str, path: str) -> bool:
    """One gitignore pattern against one repo-relative
    path, in the documented subset: a pattern naming
    a directory (`name/` or `a/b/`) ignores everything
    under it; a pattern with a slash matches the whole
    path (or a path under it); a pattern without a
    slash matches any single path segment."""
    anchored = pattern.startswith("/")
    pat = pattern[1:] if anchored else pattern
    pat = pat.rstrip("/")
    if not pat:
        return False
    if fnmatch.fnmatchcase(path, pat) \
            or fnmatch.fnmatchcase(path, pat + "/*"):
        return True
    if anchored or "/" in pat:
        return False
    return any(fnmatch.fnmatchcase(part, pat)
               for part in path.split("/"))


def is_ignored_path(path: str,
                    patterns: tuple[tuple[bool, str], ...]) -> bool:
    """Whether *path* is ignored under *patterns*:
    the last matching pattern decides, so a later
    negation un-ignores what an earlier pattern
    ignored (git's own rule)."""
    ignored = False
    for negated, pattern in patterns:
        if _pattern_matches(pattern, path):
            ignored = not negated
    return ignored


def is_binary_data(data: bytes) -> bool:
    """Git's binary test: a NUL byte in the first
    bytes of the content. An empty file is not
    binary (it is `empty`, judged by size)."""
    return b"\x00" in data[:_BINARY_PROBE_BYTES]


def _try_pointer(data: bytes) -> LFSPointer | None:
    try:
        return parse_pointer(data)
    except LFSError:
        return None


@dataclass(frozen=True)
class BlobJudgement:
    """One changed blob judged: its S-205 disposition
    and named reason, the language its document
    carries, the text that is indexed (the blob's
    own text, or the pointer's own text — never the
    pointee's), and the LFS facts when it is one."""
    disposition: str          # 'index' | 'index_pointer' | 'skip'
    reason: str
    language: str = ""
    text: str = ""
    lfs_oid: str = ""
    lfs_size: int = 0


def judge_blob(*, path: str, mode: str, data: bytes | None,
               patterns: tuple[tuple[bool, str], ...] = (),
               ) -> BlobJudgement:
    """Judge one changed file end to end. *data* is
    the blob's bytes, or None for a submodule gitlink
    (which has no blob to read). The verdict is
    S-205's `decide_code_disposition` over facts
    measured here — pointer parsing by S-060's strict
    parser, binariness by git's NUL test, size by the
    byte count — so the coverage law lives in exactly
    one place and this function only gathers facts."""
    if mode == "160000":
        disposition, reason = decide_code_disposition(
            size=0, is_submodule=True)
        return BlobJudgement(disposition, reason)
    raw = data if data is not None else b""
    pointer = _try_pointer(raw)
    disposition, reason = decide_code_disposition(
        size=len(raw),
        is_binary=is_binary_data(raw),
        is_lfs_pointer=pointer is not None,
        is_ignored=is_ignored_path(path, patterns))
    if disposition == "index_pointer" and pointer is not None:
        return BlobJudgement(
            disposition, reason, language=POINTER_LANGUAGE,
            text=raw.decode("utf-8", "replace"),
            lfs_oid=pointer.oid, lfs_size=pointer.size)
    if disposition == "index":
        return BlobJudgement(
            disposition, reason,
            language=detect_language(path, raw),
            text=raw.decode("utf-8", "replace"))
    return BlobJudgement(disposition, reason)


# ------------------------------------------------------------------
# Run results
# ------------------------------------------------------------------

@dataclass(frozen=True)
class FileOutcome:
    """One changed (or deleted) file's outcome in a
    run: what the index did with it, said in the
    disposition and reason words of the law."""
    path: str
    disposition: str          # 'index' | 'index_pointer' | 'skip' | 'removed'
    reason: str
    language: str = ""
    blob_oid: str = ""
    size: int = 0
    lfs_oid: str = ""
    lfs_size: int = 0


@dataclass(frozen=True)
class CodeIndexReport:
    """One indexing run, whole: the snapshot it
    indexed, the snapshot it diffed against ('' when
    there was none), every changed file's outcome in
    path order, and how many files stood unchanged
    and were not re-read."""
    repo_id: int
    full_name: str
    commit_oid: str
    previous_oid: str
    outcomes: tuple[FileOutcome, ...]
    unchanged: int

    @property
    def indexed(self) -> int:
        return sum(1 for o in self.outcomes
                   if o.disposition == "index")

    @property
    def pointers(self) -> int:
        return sum(1 for o in self.outcomes
                   if o.disposition == "index_pointer")

    @property
    def skipped(self) -> int:
        return sum(1 for o in self.outcomes
                   if o.disposition == "skip")

    @property
    def removed(self) -> int:
        return sum(1 for o in self.outcomes
                   if o.disposition == "removed")

    @property
    def changed(self) -> int:
        return len(self.outcomes)


@dataclass(frozen=True)
class CodeDocument:
    """One indexed file as the index holds it: its
    path and indexed text, the snapshot it came
    from, its content digest, its language and
    disposition said in data, and — for a pointer —
    the LFS target it honestly names."""
    repo_id: int
    path: str
    text: str
    commit_oid: str
    digest: str
    language: str
    disposition: str          # 'index' | 'index_pointer'
    lfs_oid: str
    lfs_size: int
    blob_size: int

    @property
    def is_pointer(self) -> bool:
        return self.disposition == "index_pointer"


# ------------------------------------------------------------------
# The extractor: git snapshots in, FTS + registry rows out
# ------------------------------------------------------------------

class CodeIndexer:
    """The S-207 extractor. It reads snapshots from
    the bare repository through S-051's batch object
    reader, judges each changed blob under S-205's
    coverage law, and writes migration 82's FTS rows
    plus S-205's document registry. It owns no query
    language (S-208) and grants no permission
    (S-209): it fills the index, and reads its own
    rows back so callers can verify what landed."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 index_store: SearchIndexStore | None = None):
        self._conn = conn
        self._repos = repositories
        self._index = index_store or SearchIndexStore(
            conn, repositories)

    # -- lookups --------------------------------------

    def _resolve(self, owner: object, repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise CodeIndexError(
                "repo_not_found", "No such repository.")
        return current

    # -- snapshots --------------------------------------

    def snapshot(self, owner: object, repo: object,
                 commit_oid: object) -> dict[str, TreeBlob]:
        """The full leaf map of one commit: every file
        path to its (mode, blob oid), read by walking
        the commit's trees through the batch reader.
        An unreadable commit is refused by name."""
        current = self._resolve(owner, repo)
        if not isinstance(commit_oid, str) or not commit_oid:
            raise CodeIndexError(
                "commit_not_found", "A commit oid is required.")
        reader = ObjectReader(
            self._repos.path_for(current.owner, current.name))
        try:
            commit = reader.read_commit(commit_oid)
        except ObjectError as exc:
            raise CodeIndexError(exc.reason, str(exc)) from None
        leaves: dict[str, TreeBlob] = {}
        stack: list[tuple[str, str]] = [("", commit.tree)]
        while stack:
            prefix, tree_oid = stack.pop()
            try:
                entries = reader.read_tree(tree_oid)
            except ObjectError as exc:
                raise CodeIndexError(exc.reason, str(exc)) from None
            for entry in entries:
                path = f"{prefix}{entry.name}"
                if entry.type == "tree":
                    stack.append((path + "/", entry.oid))
                else:
                    leaves[path] = TreeBlob(
                        path=path, mode=entry.mode, oid=entry.oid)
        return leaves

    def _gitignore_patterns(
            self, reader: ObjectReader,
            snap: dict[str, TreeBlob],
    ) -> tuple[tuple[bool, str], ...]:
        """The root `.gitignore` of the new snapshot,
        parsed; no `.gitignore` means no patterns. A
        `.gitignore` that is itself a pointer or a
        binary carries no readable patterns."""
        entry = snap.get(".gitignore")
        if entry is None or entry.is_submodule:
            return ()
        try:
            raw = reader.read_blob(entry.oid)
        except ObjectError as exc:
            raise CodeIndexError(exc.reason, str(exc)) from None
        if _try_pointer(raw) is not None or is_binary_data(raw):
            return ()
        return parse_gitignore(raw.decode("utf-8", "replace"))

    def _indexed_commit(self, repo_id: int) -> str:
        """The snapshot commit the repository's code
        rows currently stand at ('' when none do):
        every row of one snapshot shares its commit,
        so any row names it."""
        row = self._conn.execute(
            "SELECT commit_oid FROM code_fts WHERE repo_id = ?"
            " LIMIT 1", (repo_id,)).fetchone()
        return row["commit_oid"] if row else ""

    # -- indexing ---------------------------------------

    def index_tip(self, owner: object, repo: object,
                  commit_oid: object, *,
                  previous_oid: object = None,
                  full: bool = False) -> CodeIndexReport:
        """Index the delta between the previously
        indexed snapshot and *commit_oid*.

        The previous snapshot is *previous_oid* when
        one is named, else the snapshot the index
        currently stands at, else none (a first index:
        every file is changed). With *full*, the run
        is a rebuild: the delta is judged against an
        empty previous snapshot and every existing row
        for a file outside the new snapshot is purged,
        so the index afterwards holds exactly the new
        snapshot's indexed files. Only changed blobs
        are read from git; unchanged files keep their
        rows untouched. Writes happen after the whole
        delta is computed and judged, so a damaged
        repository fails before the index moves."""
        current = self._resolve(owner, repo)
        if not isinstance(commit_oid, str) or not commit_oid \
                or commit_oid == _ZERO_OID:
            raise CodeIndexError(
                "commit_not_found", "A commit oid is required.")
        repo_path = self._repos.path_for(current.owner, current.name)
        reader = ObjectReader(repo_path)
        new_snap = self.snapshot(owner, repo, commit_oid)
        if full:
            previous = ""
            old_snap: dict[str, TreeBlob] = {}
        elif previous_oid is not None:
            if not isinstance(previous_oid, str):
                raise CodeIndexError(
                    "commit_not_found",
                    "A previous commit oid is text.")
            previous = previous_oid
            old_snap = self.snapshot(owner, repo, previous) \
                if previous and previous != _ZERO_OID else {}
        else:
            previous = self._indexed_commit(current.id)
            old_snap = self.snapshot(owner, repo, previous) \
                if previous and previous != commit_oid else {}
            if previous == commit_oid:
                old_snap = dict(new_snap)
        changed, deleted, unchanged = diff_snapshots(old_snap, new_snap)
        patterns = self._gitignore_patterns(reader, new_snap)
        if ".gitignore" in changed or ".gitignore" in deleted:
            # The ignore law itself moved: a file whose
            # bytes stand still can still change verdict
            # (newly ignored, or newly welcome), so this
            # run re-judges the whole snapshot. Ordinary
            # pushes never pay this — only pushes that
            # touch .gitignore do.
            changed = tuple(sorted(new_snap))
            unchanged = ()
        blobs: dict[str, bytes] = {}
        wanted = [new_snap[path].oid for path in changed
                  if not new_snap[path].is_submodule]
        if wanted:
            try:
                objects = reader.read_objects(wanted)
            except ObjectError as exc:
                raise CodeIndexError(exc.reason, str(exc)) from None
            by_oid = {obj.oid: obj.data for obj in objects}
            for path in changed:
                blob = new_snap[path]
                if not blob.is_submodule:
                    blobs[path] = by_oid[blob.oid]
        outcomes: list[FileOutcome] = []
        writes: list[tuple[TreeBlob, BlobJudgement, int]] = []
        for path in changed:
            blob = new_snap[path]
            judgement = judge_blob(
                path=path, mode=blob.mode,
                data=blobs.get(path), patterns=patterns)
            size = len(blobs[path]) if path in blobs else 0
            outcomes.append(FileOutcome(
                path=path, disposition=judgement.disposition,
                reason=judgement.reason, language=judgement.language,
                blob_oid=blob.oid, size=size,
                lfs_oid=judgement.lfs_oid,
                lfs_size=judgement.lfs_size))
            if judgement.disposition in ("index", "index_pointer"):
                writes.append((blob, judgement, size))
        removed_paths = list(deleted)
        if full:
            existing = [r["path"] for r in self._conn.execute(
                "SELECT path FROM code_fts WHERE repo_id = ?",
                (current.id,))]
            removed_paths += [p for p in existing if p not in new_snap]
        judged = {o.path for o in outcomes}
        for path in sorted(set(removed_paths)):
            if path not in judged:
                outcomes.append(FileOutcome(
                    path=path, disposition="removed",
                    reason="deleted"))
        outcomes.sort(key=lambda o: o.path)
        written = {blob.path for blob, _, _ in writes}
        # A changed file judged unindexable loses any
        # row its previous content earned: keeping the
        # old text would index bytes the snapshot no
        # longer holds.
        removed_paths += [p for p in changed if p not in written]
        for path in sorted(set(removed_paths)):
            self._remove_row(current, path)
        for blob, judgement, size in writes:
            self._write_row(current, commit_oid, blob, judgement, size)
        if full:
            # A rebuild leaves no registry ghost: files
            # that were indexed once and stand outside
            # the new snapshot lose their documents too.
            for doc in self._index.documents_for(
                    current.owner, current.name, kind="code"):
                if doc.path not in written \
                        and doc.path not in new_snap:
                    self._index.remove_document(
                        current.owner, current.name, kind="code",
                        doc_key=doc.doc_key)
        return CodeIndexReport(
            repo_id=current.id, full_name=current.full_name,
            commit_oid=commit_oid, previous_oid=previous,
            outcomes=tuple(outcomes), unchanged=len(unchanged))

    def index_push(self, owner: object, repo: object,
                   updates) -> CodeIndexReport | None:
        """Index what one accepted push changed, per
        S-205's trigger law: only a push that moves
        the default branch moves the code snapshot.
        Any other push returns None — the code index
        honestly did not move. A push that creates
        the default branch indexes its tip whole; a
        push that deletes it clears the repository's
        code rows (the snapshot it indexed is gone)
        and reports the removals."""
        current = self._resolve(owner, repo)
        default_ref = f"refs/heads/{current.default_branch}"
        update = next(
            (u for u in updates
             if isinstance(u, RefUpdate) and u.ref == default_ref),
            None)
        if update is None:
            return None
        if not update.new_oid or update.new_oid == _ZERO_OID:
            return self._clear(current)
        previous = None
        if update.old_oid and update.old_oid != _ZERO_OID:
            previous = update.old_oid
        return self.index_tip(
            owner, repo, update.new_oid, previous_oid=previous)

    def index_repository(self, owner: object, repo: object,
                         commit_oid: object = None,
                         ) -> CodeIndexReport:
        """A full (re)index of one repository's code:
        the named commit, or the default branch's
        current tip when none is named. An empty
        repository (no tip yet) is refused
        `commit_not_found` — there is no snapshot to
        index, and pretending otherwise would lie."""
        current = self._resolve(owner, repo)
        if commit_oid is None:
            repo_path = self._repos.path_for(
                current.owner, current.name)
            tip = RefStore(repo_path).resolve(current.default_branch)
            if tip is None:
                raise CodeIndexError(
                    "commit_not_found",
                    "This repository has no commits yet.")
            commit_oid = tip
        return self.index_tip(owner, repo, commit_oid, full=True)

    def rebuild_repository(self, owner: object, repo: object,
                           commit_oid: object = None,
                           ) -> CodeIndexReport:
        """Rebuild one repository's code index whole —
        the same road as `index_repository`: the index
        afterwards holds exactly the snapshot's
        indexed files, with no stale rows."""
        return self.index_repository(owner, repo, commit_oid)

    def _clear(self, current: Repository) -> CodeIndexReport:
        """Drop every code row and registry document
        of one repository (its indexed snapshot is
        gone), reporting each removal."""
        rows = self.documents_for(current.owner, current.name)
        previous = rows[0].commit_oid if rows else ""
        for doc in rows:
            self._remove_row(current, doc.path)
        return CodeIndexReport(
            repo_id=current.id, full_name=current.full_name,
            commit_oid="", previous_oid=previous,
            outcomes=tuple(
                FileOutcome(path=d.path, disposition="removed",
                            reason="deleted") for d in rows),
            unchanged=0)

    def remove_repository(self, owner: object, repo: object) -> int:
        """Purge one repository's code rows and
        registry documents (the repository-deletion
        seam, beside S-205's own purge). Returns how
        many indexed files were removed."""
        current = self._resolve(owner, repo)
        return len(self._clear(current).outcomes)

    # -- rows --------------------------------------------

    def _write_row(self, current: Repository, commit_oid: str,
                   blob: TreeBlob, judgement: BlobJudgement,
                   size: int) -> None:
        """Replace one file's FTS row whole and register
        its S-205 document under the research-18 key
        shape: `code:<path>` carrying the snapshot
        commit, the path, and the content digest (the
        blob oid). The registry write follows the FTS
        write, never nested inside its transaction —
        the S-206 order."""
        with self._conn:
            self._conn.execute(
                "DELETE FROM code_fts WHERE repo_id = ? AND path = ?",
                (current.id, blob.path))
            self._conn.execute(
                "INSERT INTO code_fts (path, text, repo_id,"
                " commit_oid, digest, language, disposition,"
                " lfs_oid, lfs_size, blob_size)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (blob.path, judgement.text, current.id, commit_oid,
                 blob.oid, judgement.language, judgement.disposition,
                 judgement.lfs_oid, judgement.lfs_size, size))
        self._index.put_document(
            current.owner, current.name, kind="code",
            doc_key=f"code:{blob.path}", commit_oid=commit_oid,
            path=blob.path, digest=blob.oid)

    def _remove_row(self, current: Repository, path: str) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM code_fts WHERE repo_id = ? AND path = ?",
                (current.id, path))
        self._index.remove_document(
            current.owner, current.name, kind="code",
            doc_key=f"code:{path}")

    # -- reads --------------------------------------------

    def documents_for(self, owner: object, repo: object,
                      ) -> tuple[CodeDocument, ...]:
        """Every indexed file of one repository, in
        path order — the extractor's own rows read
        back, pointers labelled as pointers."""
        current = self._resolve(owner, repo)
        rows = self._conn.execute(
            "SELECT path, text, commit_oid, digest, language,"
            " disposition, lfs_oid, lfs_size, blob_size"
            " FROM code_fts WHERE repo_id = ? ORDER BY path",
            (current.id,)).fetchall()
        return tuple(self._doc_from(current.id, r) for r in rows)

    def document_for(self, owner: object, repo: object,
                     path: object) -> CodeDocument | None:
        """One indexed file by path, or None when the
        index holds no such file — skipped, deleted,
        and never-indexed files are all honestly
        absent here; the run report is where their
        reasons live."""
        current = self._resolve(owner, repo)
        row = self._conn.execute(
            "SELECT path, text, commit_oid, digest, language,"
            " disposition, lfs_oid, lfs_size, blob_size"
            " FROM code_fts WHERE repo_id = ? AND path = ?",
            (current.id, path)).fetchone()
        return self._doc_from(current.id, row) if row else None

    def _doc_from(self, repo_id: int,
                  row: sqlite3.Row) -> CodeDocument:
        return CodeDocument(
            repo_id=repo_id, path=row["path"], text=row["text"],
            commit_oid=row["commit_oid"], digest=row["digest"],
            language=row["language"],
            disposition=row["disposition"],
            lfs_oid=row["lfs_oid"],
            lfs_size=int(row["lfs_size"]),
            blob_size=int(row["blob_size"]))


def render_code_index_page(report: CodeIndexReport) -> str:
    """One indexing run rendered for a person: the
    snapshot it indexed, the counts in words, and
    every changed file with its verdict — pointers
    said as pointers, skips with their reasons.
    All user text through S-010's escaping."""
    parts = [
        f"<h1>Code index — {escape_html_text(report.full_name)}</h1>",
        f"<p>Snapshot {escape_html_text(report.commit_oid or 'none')}"
        f" indexed: {report.indexed} files indexed, "
        f"{report.pointers} LFS pointers indexed as pointers, "
        f"{report.skipped} files skipped, "
        f"{report.removed} files removed, "
        f"{report.unchanged} files unchanged and not re-read.</p>",
        "<ul>",
    ]
    for outcome in report.outcomes:
        if outcome.disposition == "index":
            words = f"indexed ({outcome.language})"
        elif outcome.disposition == "index_pointer":
            words = ("indexed as an LFS pointer — the pointer "
                     "itself, not the file it points at")
        elif outcome.disposition == "removed":
            words = "removed (no longer in the snapshot)"
        else:
            words = f"skipped ({outcome.reason})"
        parts.append(
            f"<li>{escape_html_text(outcome.path)} — "
            f"{escape_html_text(words)}</li>")
    parts.append("</ul>")
    return "\n".join(parts)
