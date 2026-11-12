"""Scan on push (S-291).

Roadmap S-291: Scan on push -- every accepted push
scanned across its full introduced history; findings
create alerts (S-294).

S-289 gave Samverk a detector set for the major
public token formats (``samverk/secret_scanning.py``)
and S-290 a generic entropy-and-context judgement
(``samverk/generic_secret_detection.py``). Both are
pure judgements over text handed to them: no storage,
no history, no push. This slice is the road from an
accepted push to those judgements -- and from a
judgement to a standing alert a human can act on:

- **Full introduced history, never just the tip.**
  For every ref update in the push, the introduced
  commits are the commits reachable from the new oid
  and not reachable from the old oid (a creation:
  not reachable from any ref tip the repository held
  before the push; a deletion introduces nothing).
  Force-pushes follow the same law -- the rewritten
  commits are new oids, so they are introduced, and
  the abandoned line is not rescanned. Every
  introduced commit is scanned, oldest first, so a
  secret buried three commits under the tip is found
  exactly as a tip secret is.
- **Every introduced blob version.** A commit is
  scanned through the blobs it introduces: its tree
  flattened against its first parent's tree (a root
  commit: against the empty tree). A blob a commit
  merely inherits was introduced by an ancestor and
  is scanned there. A merge's second-parent line is
  scanned at the commits that introduced it, which
  are themselves in the introduced set. Blobs are
  deduplicated by oid across the whole scan: the
  same content at two paths is judged once and its
  findings land at both places. Within one scan a
  (path, blob) pair alerts only at its oldest
  introducing commit -- a merge that meets its side
  branch's blob again does not re-alert it. Gitlinks are never
  scanned (their content lives in another
  repository); symlink blobs are scanned as the
  text they are (a target string).
- **Findings create alerts.** One alert per finding,
  standing open in migration 115's ``secret_alerts``
  -- the rows S-294's lifecycle (open -> resolved /
  reopened) will govern. An alert carries the commit,
  the path, the blob, the detector, the line and
  column, the redacted preview and the fingerprint:
  where and what shape, never the secret. The
  matched text is never stored, rendered or logged
  by this module, exactly as S-289/S-290 hold.
- **Exactly once per push.** A scan is keyed by the
  repository and a hash of its exact ref updates
  (``push_key``): scanning the same accepted push
  twice returns the standing scan and creates no
  second alert. Alert identity is likewise unique
  per (repository, commit, path, detector,
  fingerprint), so an overlapping rescan can never
  duplicate an alert.
- **Caps are said, never silent.** A scan judges at
  most ``MAX_COMMITS_PER_SCAN`` commits,
  ``MAX_BLOBS_PER_SCAN`` distinct blobs and
  ``MAX_BLOB_BYTES`` per blob; binary blobs (a NUL
  in the first ``BINARY_SNIFF_BYTES``) are skipped
  unjudged. Anything skipped or cut is counted on
  the scan record, and a scan cut by a cap stands
  ``partial`` naming the cap -- never a clean bill
  for history that was not read.
- **The detector seam is lazy and honest.** Neither
  detector module is imported at load. At scan time
  each layer is probed and used when present; a
  layer that is absent is recorded on the scan
  (``pattern_available`` / ``generic_available``)
  and the scan stands on the layers it has -- on a
  base without S-289/S-290 the scan still records
  the full history walk, saying plainly that no
  detector judged it. A caller may inject one
  ``scanner`` callable instead (the battery's road,
  and the seam a future combined detector plugs
  into); an injected scanner's findings are
  normalised through the same redaction law.
- **Unwitnessed.** The push itself is already
  witnessed (``repo.push`` at the transports, the
  push event in S-090's store). Scanning is a
  judgement over that record, like S-289/S-290's:
  no new taxonomy event -- 133 stand (33 auth /
  87 repo / 13 admin).

Storage is migration 115's ``push_scans``,
``push_scan_updates`` and ``secret_alerts`` tables
(schema 114 -> 115).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .hooks import RefUpdate
from .repositories import RepositoryStore

_OID_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")
TRANSPORTS = frozenset({"http", "ssh", "local"})
ACTOR_KINDS = frozenset({"user", "deploy_key", "system"})
ALERT_STATES = frozenset({"open", "resolved", "reopened"})

MAX_COMMITS_PER_SCAN = 1000
MAX_BLOBS_PER_SCAN = 10000
MAX_BLOB_BYTES = 1_000_000
BINARY_SNIFF_BYTES = 8192

GITLINK_MODE = "160000"


class PushScanError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _is_zero_oid(oid: str) -> bool:
    return bool(oid) and set(oid) == {"0"}


def _validate_oid(oid: object) -> str:
    if not isinstance(oid, str) or not _OID_RE.match(oid.lower()):
        raise PushScanError(
            "update_invalid", f"Not an object id: {oid!r}")
    return oid.lower()


def _validate_update(update: object) -> RefUpdate:
    if not isinstance(update, RefUpdate):
        raise PushScanError(
            "update_invalid", f"Not a ref update: {update!r}")
    _validate_oid(update.old_oid)
    _validate_oid(update.new_oid)
    if update.old_oid == update.new_oid:
        raise PushScanError(
            "update_invalid",
            f"Ref {update.ref!r} does not move ({update.old_oid}); "
            "a scan records movement, not stillness.")
    return update


def push_key_for(updates) -> str:
    """The exactly-once key of one accepted push."""
    payload = json.dumps(
        [{"ref": u.ref, "old": u.old_oid, "new": u.new_oid}
         for u in sorted(updates, key=lambda u: u.ref)],
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- history: the introduced-walk over a repository ---------------


class GitHistory:
    """The history road over a bare repository, through
    S-051's ObjectReader (one cat-file batch process
    per read). Duck-typed with the battery's in-memory
    history: commit_parents / commit_tree /
    flatten_tree / read_blob."""

    def __init__(self, repo_path: Path):
        from .objects import ObjectReader
        self._reader = ObjectReader(Path(repo_path))

    def commit_parents(self, oid: str) -> tuple:
        return self._reader.read_commit(oid).parents

    def commit_tree(self, oid: str) -> str:
        return self._reader.read_commit(oid).tree

    def flatten_tree(self, tree_oid: str) -> dict:
        out: dict = {}
        self._flatten(tree_oid, "", out)
        return out

    def _flatten(self, tree_oid: str, prefix: str, out: dict) -> None:
        for entry in self._reader.read_tree(tree_oid):
            path = f"{prefix}{entry.name}" if not prefix \
                else f"{prefix}/{entry.name}"
            if entry.type == "tree":
                self._flatten(entry.oid, path, out)
            else:
                out[path] = (entry.mode, entry.oid)

    def read_blob(self, oid: str) -> bytes:
        return self._reader.read_blob(oid)


def _closure(history, tips) -> set:
    """Every commit reachable from any of `tips`."""
    seen: set = set()
    stack = [t for t in tips if t and not _is_zero_oid(t)]
    while stack:
        oid = stack.pop()
        if oid in seen:
            continue
        seen.add(oid)
        stack.extend(history.commit_parents(oid))
    return seen


def introduced_commits(history, updates, prior_tips=()) -> list:
    """The full introduced history of a push, oldest first.

    Introduced = reachable from a new oid and not
    reachable from the matching old oid nor from any
    prior ref tip (what the repository already held).
    Deletions introduce nothing. Parents always stand
    before their children in the result.
    """
    excluded: set = set()
    for tip in prior_tips:
        excluded |= _closure(history, [tip])
    ordered: list = []
    placed: set = set()

    def visit(oid: str) -> None:
        # Iterative post-order: parents before children.
        stack = [(oid, False)]
        while stack:
            current, expanded = stack.pop()
            if current in placed or current in excluded:
                continue
            if expanded:
                placed.add(current)
                ordered.append(current)
                continue
            stack.append((current, True))
            for parent in history.commit_parents(current):
                if parent not in placed and parent not in excluded:
                    stack.append((parent, False))

    for update in updates:
        if _is_zero_oid(update.new_oid):
            continue
        excluded_for_update = excluded | _closure(
            history, [update.old_oid])
        saved = excluded
        excluded = excluded_for_update
        visit(update.new_oid)
        excluded = saved | set(ordered)
    return ordered


def introduced_blobs(history, commit_oid: str) -> list:
    """(path, mode, blob_oid) a commit introduces:
    its flattened tree against its first parent's."""
    tree = history.flatten_tree(history.commit_tree(commit_oid))
    parents = history.commit_parents(commit_oid)
    parent_tree: dict = {}
    if parents:
        parent_tree = history.flatten_tree(
            history.commit_tree(parents[0]))
    out = []
    for path in sorted(tree):
        mode, blob_oid = tree[path]
        if mode == GITLINK_MODE:
            continue
        if parent_tree.get(path) == (mode, blob_oid):
            continue
        if path in parent_tree and parent_tree[path][1] == blob_oid:
            continue
        out.append((path, mode, blob_oid))
    return out


# --- the detector seam ---------------------------------------------


def pattern_layer_available() -> bool:
    try:
        return importlib.util.find_spec(
            "samverk.secret_scanning") is not None
    except Exception:
        return False


def generic_layer_available() -> bool:
    try:
        return importlib.util.find_spec(
            "samverk.generic_secret_detection") is not None
    except Exception:
        return False


@dataclass(frozen=True)
class ScanFinding:
    """One normalised finding. Never the secret."""
    source: str          # pattern | generic | injected
    detector_id: str
    line: int
    column: int
    redacted: str
    fingerprint: str

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "detector_id": self.detector_id,
            "line": self.line,
            "column": self.column,
            "redacted": self.redacted,
            "fingerprint": self.fingerprint,
        }


def _normalise_injected(raw) -> ScanFinding:
    if isinstance(raw, ScanFinding):
        return raw
    if isinstance(raw, dict):
        return ScanFinding(
            source=str(raw.get("source", "injected")),
            detector_id=str(raw.get("detector_id", "injected")),
            line=int(raw.get("line", 0)),
            column=int(raw.get("column", 0)),
            redacted=str(raw.get("redacted", "")),
            fingerprint=str(raw.get("fingerprint", "")))
    return ScanFinding(
        source="injected",
        detector_id=str(getattr(raw, "detector_id", "injected")),
        line=int(getattr(raw, "line", 0)),
        column=int(getattr(raw, "column", 0)),
        redacted=str(getattr(raw, "redacted", "")),
        fingerprint=str(getattr(raw, "fingerprint", "")))


def scan_blob_text(text: str, *, scanner=None) -> tuple:
    """Judge one blob's text. Returns (findings,
    pattern_available, generic_available).

    With an injected scanner, that scanner alone
    judges and the layer flags report False (no
    standing layer was used). Without one, each
    standing layer judges when present; a pattern
    finding and a generic finding over the same
    matched text (same fingerprint and line) are
    one finding -- the pattern's, which names it.
    """
    if scanner is not None:
        return ([_normalise_injected(f) for f in scanner(text)],
                False, False)
    findings: list = []
    pattern_ok = pattern_layer_available()
    generic_ok = generic_layer_available()
    pattern_keys = set()
    if pattern_ok:
        from .secret_scanning import scan_text
        for f in scan_text(text):
            findings.append(ScanFinding(
                source="pattern", detector_id=f.detector_id,
                line=f.line, column=f.column,
                redacted=f.redacted, fingerprint=f.fingerprint))
            pattern_keys.add((f.fingerprint, f.line))
    if generic_ok:
        from .generic_secret_detection import scan_generic
        for f in scan_generic(text):
            if (f.fingerprint, f.line) in pattern_keys:
                continue
            findings.append(ScanFinding(
                source="generic", detector_id="generic_entropy",
                line=f.line, column=f.column,
                redacted=f.redacted, fingerprint=f.fingerprint))
    findings.sort(key=lambda f: (f.line, f.column, f.detector_id))
    return findings, pattern_ok, generic_ok


# --- records ---------------------------------------------------------


@dataclass(frozen=True)
class PushScan:
    id: int
    full_name: str
    repo_id: int
    push_key: str
    actor_kind: str
    actor_id: int | None
    transport: str
    updates: tuple
    status: str            # complete | partial
    partial_reason: str    # "" when complete
    commits_scanned: int
    blobs_scanned: int
    blobs_skipped: int
    findings_count: int
    alerts_created: int
    pattern_available: bool
    generic_available: bool
    created_at: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "repository": self.full_name,
            "push_key": self.push_key,
            "actor_kind": self.actor_kind,
            "actor_id": self.actor_id,
            "transport": self.transport,
            "updates": [
                {"ref": u.ref, "old": u.old_oid, "new": u.new_oid}
                for u in self.updates],
            "status": self.status,
            "partial_reason": self.partial_reason,
            "commits_scanned": self.commits_scanned,
            "blobs_scanned": self.blobs_scanned,
            "blobs_skipped": self.blobs_skipped,
            "findings": self.findings_count,
            "alerts_created": self.alerts_created,
            "pattern_available": self.pattern_available,
            "generic_available": self.generic_available,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class SecretAlert:
    id: int
    repo_id: int
    scan_id: int
    commit_oid: str
    path: str
    blob_oid: str
    source: str
    detector_id: str
    line: int
    column: int
    redacted: str
    fingerprint: str
    state: str
    created_at: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scan_id": self.scan_id,
            "commit": self.commit_oid,
            "path": self.path,
            "blob": self.blob_oid,
            "source": self.source,
            "detector_id": self.detector_id,
            "line": self.line,
            "column": self.column,
            "redacted": self.redacted,
            "fingerprint": self.fingerprint,
            "state": self.state,
            "created_at": self.created_at,
        }


# --- the store -------------------------------------------------------


class PushScanStore:
    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._repos = repositories
        self._now = time_fn

    # -- the scan ----------------------------------------------------

    def scan_push(self, owner, repo, *, actor_kind: str = "user",
                  actor_id: int | None = None,
                  transport: str = "local", updates,
                  history, prior_tips=(), scanner=None) -> PushScan:
        """Scan one accepted push across its full
        introduced history; findings create alerts.

        Idempotent on the push's exact updates: a
        repeat returns the standing scan unchanged.
        The record, its updates and its alerts are
        written in one transaction and committed
        before the scan is answered.
        """
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise PushScanError("repo_not_found", "No such repository.")
        if actor_kind not in ACTOR_KINDS:
            raise PushScanError(
                "actor_invalid", f"Unknown actor kind: {actor_kind!r}")
        if transport not in TRANSPORTS:
            raise PushScanError(
                "transport_invalid",
                f"Unknown transport: {transport!r}")
        checked = tuple(_validate_update(u) for u in updates)
        if not checked:
            raise PushScanError(
                "updates_empty",
                "An accepted push moves at least one ref; "
                "an empty push scans nothing and records nothing.")
        key = push_key_for(checked)
        existing = self._scan_by_key(current.id, key)
        if existing is not None:
            return existing

        commits = introduced_commits(history, checked, prior_tips)
        partial_reason = ""
        if len(commits) > MAX_COMMITS_PER_SCAN:
            commits = commits[:MAX_COMMITS_PER_SCAN]
            partial_reason = "commit_cap"

        judged: dict = {}       # blob_oid -> findings tuple
        occurrences: list = []  # (commit, path, blob_oid)
        blobs_skipped = 0
        blobs_judged = 0
        pattern_ok = False
        generic_ok = False
        layers_probed = False
        for commit_oid in commits:
            for path, _mode, blob_oid in introduced_blobs(
                    history, commit_oid):
                occurrences.append((commit_oid, path, blob_oid))
                if blob_oid in judged:
                    continue
                if len(judged) >= MAX_BLOBS_PER_SCAN:
                    if not partial_reason:
                        partial_reason = "blob_cap"
                    blobs_skipped += 1
                    judged[blob_oid] = ()
                    continue
                data = history.read_blob(blob_oid)
                if len(data) > MAX_BLOB_BYTES:
                    blobs_skipped += 1
                    judged[blob_oid] = ()
                    continue
                if b"\x00" in data[:BINARY_SNIFF_BYTES]:
                    blobs_skipped += 1
                    judged[blob_oid] = ()
                    continue
                text = data.decode("utf-8", "replace")
                blobs_judged += 1
                found, p_ok, g_ok = scan_blob_text(
                    text, scanner=scanner)
                if not layers_probed:
                    pattern_ok, generic_ok = p_ok, g_ok
                    layers_probed = True
                elif scanner is None:
                    pattern_ok = pattern_ok or p_ok
                    generic_ok = generic_ok or g_ok
                judged[blob_oid] = tuple(found)
        if scanner is None and not layers_probed:
            pattern_ok = pattern_layer_available()
            generic_ok = generic_layer_available()

        findings_count = 0
        alert_rows = []
        alerted_pairs: set = set()
        for commit_oid, path, blob_oid in occurrences:
            if (path, blob_oid) in alerted_pairs:
                # Already introduced earlier in this same
                # scan (a merge meeting its side branch's
                # blob again): alerted at its introduction.
                continue
            alerted_pairs.add((path, blob_oid))
            for f in judged.get(blob_oid, ()):
                findings_count += 1
                alert_rows.append((
                    current.id, commit_oid, path, blob_oid,
                    f.source, f.detector_id, f.line, f.column,
                    f.redacted, f.fingerprint))
        created_at = int(self._now())
        status = "partial" if partial_reason else "complete"
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO push_scans (repo_id, push_key,"
                " actor_kind, actor_id, transport, status,"
                " partial_reason, commits_scanned, blobs_scanned,"
                " blobs_skipped, findings_count, alerts_created,"
                " pattern_available, generic_available, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0,"
                " ?, ?, ?)",
                (current.id, key, actor_kind, actor_id, transport,
                 status, partial_reason, len(commits),
                 blobs_judged,
                 blobs_skipped, findings_count,
                 1 if pattern_ok else 0, 1 if generic_ok else 0,
                 created_at))
            scan_id = int(cursor.lastrowid)
            for u in checked:
                self._conn.execute(
                    "INSERT INTO push_scan_updates (scan_id, ref,"
                    " old_oid, new_oid) VALUES (?, ?, ?, ?)",
                    (scan_id, u.ref, u.old_oid, u.new_oid))
            alerts_created = 0
            for row in alert_rows:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO secret_alerts"
                    " (repo_id, scan_id, commit_oid, path,"
                    " blob_oid, source, detector_id, line,"
                    " column, redacted, fingerprint, state,"
                    " created_at) VALUES (?, ?, ?, ?, ?, ?,"
                    " ?, ?, ?, ?, ?, 'open', ?)",
                    (row[0], scan_id, row[1], row[2], row[3],
                     row[4], row[5], row[6], row[7], row[8],
                     row[9], created_at))
                alerts_created += int(cur.rowcount)
            self._conn.execute(
                "UPDATE push_scans SET alerts_created = ?"
                " WHERE id = ?", (alerts_created, scan_id))
        scan = self.get_scan_by_id(scan_id)
        assert scan is not None
        return scan

    # -- reads ---------------------------------------------------------

    def _scan_by_key(self, repo_id: int, key: str):
        row = self._conn.execute(
            "SELECT id FROM push_scans WHERE repo_id = ?"
            " AND push_key = ?", (repo_id, key)).fetchone()
        if row is None:
            return None
        return self.get_scan_by_id(int(row["id"]))

    def get_scan_by_id(self, scan_id: int):
        row = self._conn.execute(
            "SELECT s.*, r.owner, r.name FROM push_scans s"
            " JOIN repositories r ON r.id = s.repo_id"
            " WHERE s.id = ?", (scan_id,)).fetchone()
        if row is None:
            return None
        return self._to_scan(row)

    def _to_scan(self, row) -> PushScan:
        urows = self._conn.execute(
            "SELECT ref, old_oid, new_oid FROM push_scan_updates"
            " WHERE scan_id = ? ORDER BY id",
            (int(row["id"]),)).fetchall()
        updates = tuple(
            RefUpdate(ref=u["ref"], old_oid=u["old_oid"],
                      new_oid=u["new_oid"]) for u in urows)
        return PushScan(
            id=int(row["id"]),
            full_name=f"{row['owner']}/{row['name']}",
            repo_id=int(row["repo_id"]), push_key=row["push_key"],
            actor_kind=row["actor_kind"], actor_id=row["actor_id"],
            transport=row["transport"], updates=updates,
            status=row["status"],
            partial_reason=row["partial_reason"],
            commits_scanned=int(row["commits_scanned"]),
            blobs_scanned=int(row["blobs_scanned"]),
            blobs_skipped=int(row["blobs_skipped"]),
            findings_count=int(row["findings_count"]),
            alerts_created=int(row["alerts_created"]),
            pattern_available=bool(row["pattern_available"]),
            generic_available=bool(row["generic_available"]),
            created_at=int(row["created_at"]))

    def list_scans(self, owner, repo, *, limit: int = 100
                   ) -> tuple:
        """Newest first; a missing repo is named."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise PushScanError("repo_not_found", "No such repository.")
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT s.*, r.owner, r.name FROM push_scans s"
            " JOIN repositories r ON r.id = s.repo_id"
            " WHERE s.repo_id = ? ORDER BY s.id DESC LIMIT ?",
            (current.id, clamped)).fetchall()
        return tuple(self._to_scan(r) for r in rows)

    def count_scans(self, owner, repo) -> int:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise PushScanError("repo_not_found", "No such repository.")
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM push_scans WHERE repo_id = ?",
            (current.id,)).fetchone()
        return int(row["n"])

    def _to_alert(self, row) -> SecretAlert:
        return SecretAlert(
            id=int(row["id"]), repo_id=int(row["repo_id"]),
            scan_id=int(row["scan_id"]),
            commit_oid=row["commit_oid"], path=row["path"],
            blob_oid=row["blob_oid"], source=row["source"],
            detector_id=row["detector_id"], line=int(row["line"]),
            column=int(row["column"]), redacted=row["redacted"],
            fingerprint=row["fingerprint"], state=row["state"],
            created_at=int(row["created_at"]))

    def list_alerts(self, owner, repo, *, state: str | None = None,
                    limit: int = 100) -> tuple:
        """Newest first; optionally one lifecycle state."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise PushScanError("repo_not_found", "No such repository.")
        if state is not None and state not in ALERT_STATES:
            raise PushScanError(
                "state_invalid", f"Unknown alert state: {state!r}")
        clamped = max(1, min(int(limit), 500))
        if state is None:
            rows = self._conn.execute(
                "SELECT * FROM secret_alerts WHERE repo_id = ?"
                " ORDER BY id DESC LIMIT ?",
                (current.id, clamped)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM secret_alerts WHERE repo_id = ?"
                " AND state = ? ORDER BY id DESC LIMIT ?",
                (current.id, state, clamped)).fetchall()
        return tuple(self._to_alert(r) for r in rows)

    def alerts_for_scan(self, scan_id: int) -> tuple:
        rows = self._conn.execute(
            "SELECT * FROM secret_alerts WHERE scan_id = ?"
            " ORDER BY id", (scan_id,)).fetchall()
        return tuple(self._to_alert(r) for r in rows)

    def count_alerts(self, owner, repo, *,
                     state: str | None = None) -> int:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise PushScanError("repo_not_found", "No such repository.")
        if state is None:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM secret_alerts"
                " WHERE repo_id = ?", (current.id,)).fetchone()
        else:
            if state not in ALERT_STATES:
                raise PushScanError(
                    "state_invalid",
                    f"Unknown alert state: {state!r}")
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM secret_alerts"
                " WHERE repo_id = ? AND state = ?",
                (current.id, state)).fetchone()
        return int(row["n"])


# --- the page faces ----------------------------------------------------


def render_push_scan_page(scan: PushScan, alerts=(),
                          title: str = "Push scan") -> str:
    """The scan's face: coverage and alerts, in words,
    redacted only -- never a secret."""
    from .escaping import escape_html_text
    rows = "".join(
        "<li>" + escape_html_text(a.path)
        + " — " + escape_html_text(a.detector_id)
        + " (" + escape_html_text(a.source) + ")"
        + ", line " + str(a.line)
        + ": " + escape_html_text(a.redacted)
        + " [" + escape_html_text(a.state) + "]</li>"
        for a in alerts)
    if not rows:
        rows = "<li>No secret alerts from this push.</li>"
    status_words = (
        "complete — the full introduced history was scanned"
        if scan.status == "complete" else
        "partial — the scan stopped at a named cap: "
        + scan.partial_reason)
    layers = (
        "pattern detectors: "
        + ("present" if scan.pattern_available else "absent")
        + "; generic detection: "
        + ("present" if scan.generic_available else "absent"))
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1><p>Scan of "
        + escape_html_text(scan.full_name)
        + ": " + escape_html_text(status_words)
        + ". Commits scanned: " + str(scan.commits_scanned)
        + "; blobs scanned: " + str(scan.blobs_scanned)
        + "; blobs skipped: " + str(scan.blobs_skipped)
        + "; alerts created: " + str(scan.alerts_created)
        + ". Detector layers — "
        + escape_html_text(layers)
        + ".</p><ul>" + rows + "</ul></body></html>")


def render_secret_alerts_page(alerts, title: str = "Secret alerts"
                              ) -> str:
    """The alerts face: places and shapes, never secrets."""
    from .escaping import escape_html_text
    rows = "".join(
        "<li>" + escape_html_text(a.path)
        + " @ " + escape_html_text(a.commit_oid[:12])
        + " — " + escape_html_text(a.detector_id)
        + ", line " + str(a.line)
        + ": " + escape_html_text(a.redacted)
        + " [" + escape_html_text(a.state) + "]</li>"
        for a in alerts)
    if not rows:
        rows = "<li>No secret alerts.</li>"
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1><ul>" + rows + "</ul></body></html>")
