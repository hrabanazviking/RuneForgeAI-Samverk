"""Push protection (S-292).

Roadmap S-292: Push protection -- receive-pack
refuses pushes containing detected secrets (at the
S-089 gate), naming the file and pattern class,
never echoing the secret.

S-291 scans every *accepted* push and creates
alerts for what it finds; this slice is the other
half of the law -- the same judgement made *before*
acceptance, at S-089's pre-receive gate, where a
finding is not an alert but a refusal:

- **The S-089 gate is the door.** `PushProtection`
  plugs into the gate's `secret_scan` stage (gate
  order: protection, secret_scan, quota, hooks) as
  a plug-in that allows a clean push and vetoes a
  dirty one. The veto reason is the sentence the
  pusher sees, and it names the file and the pattern
  class (the detector's provider and label, e.g.
  "GitHub classic personal access token") and the
  line -- never the secret, never even the redacted
  preview: a refusal travels over the wire and into
  terminal scrollback, so it carries the least that
  still tells the pusher exactly what to remove.
- **The judged history is S-291's introduced
  history.** For every ref update, the commits
  reachable from the new oid and not from the old
  oid nor any prior ref tip, oldest first; every
  blob version a commit introduces, judged once per
  blob oid, alerting (here: refusing) at the oldest
  introducing commit per (path, blob). Deletions
  introduce nothing; gitlinks are never scanned;
  binary blobs and blobs past the byte cap are
  skipped and counted, exactly as S-291 counts them.
- **Findings never carry the secret.** A
  `ProtectionFinding` holds the path, commit, blob,
  detector, pattern class, line, column, the
  detector layer's redacted preview and a SHA-256
  fingerprint -- where and what shape, never the
  matched text. The decision, its `to_dict`, the
  refusal reason and the rendered page all follow
  the same law, and the battery plants a secret and
  greps every surface for it.
- **Caps fail closed.** A push whose introduced
  history exceeds the commit or blob cap cannot be
  proven clean, so it is refused naming the cap --
  a capped scan is never a clean bill (S-291's
  partial law, with the refusal consequence this
  slice exists for). Skips that do not cut the walk
  (binary, oversize) are counted on the decision
  and do not by themselves refuse.
- **The detector seam is lazy and honest,** as in
  S-290/S-291: no detector module is imported at
  load. At judgement time S-291's combined
  `scan_blob_text` is used when present; otherwise
  S-289's patterns and S-290's generic judgement
  are probed directly. When *no* detector layer is
  available and no scanner was injected, the check
  raises `detector_unavailable` -- at the gate that
  is an error outcome, and S-089's law refuses on
  error: push protection that cannot judge does not
  wave pushes through. A caller may inject one
  `scanner` callable instead (the battery's road,
  and the seam a future combined detector plugs
  into); its findings are normalised through the
  same never-the-secret law.
- **No bypass here.** S-293 builds the permitted
  bypass (stated reason, alert + audit event,
  visible to owners) on top of this refusal; this
  slice refuses unconditionally and records
  nothing, so there is nothing to bypass yet and
  nothing hidden.
- **Unwitnessed, no storage, no migration.** A
  refusal is a gate veto, not a stored act: no new
  taxonomy event -- 133 stand (33 auth / 87 repo /
  13 admin) -- and no migration; schema stands at
  114 on this slice's base (S-291's migration 115
  lands before this slice banks and is untouched
  by it). The accepted-push record of a refused
  push is simply that it never happened.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .hooks import RefUpdate
from .receive_gate import GateVeto
from .repositories import RepositoryStore

_OID_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")
GITLINK_MODE = "160000"

MAX_COMMITS_PER_PUSH = 1000
MAX_BLOBS_PER_PUSH = 10000
MAX_BLOB_BYTES = 1_000_000
BINARY_SNIFF_BYTES = 8192


class PushProtectionError(ValueError):
    """A push-protection refusal, named by `reason`."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _is_zero_oid(oid: str) -> bool:
    return bool(oid) and set(oid) == {"0"}


def _validate_oid(oid: object) -> str:
    if not isinstance(oid, str) or not _OID_RE.match(oid.lower()):
        raise PushProtectionError(
            "update_invalid", f"Not an object id: {oid!r}")
    return oid.lower()


def _validate_update(update: object) -> RefUpdate:
    if not isinstance(update, RefUpdate):
        raise PushProtectionError(
            "update_invalid", f"Not a ref update: {update!r}")
    _validate_oid(update.old_oid)
    _validate_oid(update.new_oid)
    if update.old_oid == update.new_oid:
        raise PushProtectionError(
            "update_invalid",
            f"Ref {update.ref!r} does not move ({update.old_oid}); "
            "a push that moves nothing is refused, not waved.")
    return update


# --- history: the introduced-walk over a repository ---------------
#
# The same walk S-291 judges accepted pushes by,
# implemented here so this slice stands on its own
# base; the laws are identical and the battery
# proves them again at the refusal door.


class GitHistory:
    """The history road over a bare repository,
    through S-051's ObjectReader. Duck-typed with
    the battery's in-memory history: commit_parents /
    commit_tree / flatten_tree / read_blob."""

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
    """The full introduced history of a push, oldest
    first: reachable from a new oid, not reachable
    from the matching old oid nor from any prior ref
    tip. Deletions introduce nothing. Parents always
    stand before their children."""
    excluded: set = set()
    for tip in prior_tips:
        excluded |= _closure(history, [tip])
    ordered: list = []
    placed: set = set()

    def visit(oid: str) -> None:
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


def _try_import(name: str):
    try:
        import importlib
        return importlib.import_module(f"samverk.{name}")
    except Exception:
        return None


def pattern_layer_available() -> bool:
    return _try_import("secret_scanning") is not None


def generic_layer_available() -> bool:
    return _try_import("generic_secret_detection") is not None


def pattern_class_for(detector_id: str, source: str) -> str:
    """The human pattern class of one finding: the
    detector's provider and label when S-289 names
    it, the generic class for S-290's judgement, the
    detector id itself for an injected detector."""
    if source == "generic":
        return "generic high-entropy secret"
    module = _try_import("secret_scanning")
    if module is not None:
        try:
            det = module.detector_by_id(detector_id)
            return f"{det.provider} {det.label}"
        except Exception:
            pass
    return detector_id


@dataclass(frozen=True)
class RawFinding:
    """One detector judgement over one text, before
    it is placed in a file. Never the secret."""
    source: str          # pattern | generic | injected
    detector_id: str
    line: int
    column: int
    redacted: str
    fingerprint: str


def _normalise_raw(raw) -> RawFinding:
    if isinstance(raw, RawFinding):
        return raw
    if isinstance(raw, dict):
        return RawFinding(
            source=str(raw.get("source", "injected")),
            detector_id=str(raw.get("detector_id", "injected")),
            line=int(raw.get("line", 0)),
            column=int(raw.get("column", 0)),
            redacted=str(raw.get("redacted", "")),
            fingerprint=str(raw.get("fingerprint", "")))
    return RawFinding(
        source=str(getattr(raw, "source", "injected")),
        detector_id=str(getattr(raw, "detector_id", "injected")),
        line=int(getattr(raw, "line", 0)),
        column=int(getattr(raw, "column", 0)),
        redacted=str(getattr(raw, "redacted", "")),
        fingerprint=str(getattr(raw, "fingerprint", "")))


def scan_text(text: str, *, scanner=None) -> tuple:
    """Judge one blob's text. Returns (findings,
    pattern_available, generic_available).

    S-291's combined judgement is preferred when it
    is present (it already dedupes a pattern finding
    against a generic one over the same text);
    otherwise the two layers are probed directly
    under the same dedupe law. With an injected
    scanner, that scanner alone judges and the layer
    flags report False. With no layer and no scanner
    the caller is told plainly: both flags False and
    no findings -- the refusal consequence of that
    honesty is `PushProtection`'s, below."""
    if scanner is not None:
        return ([_normalise_raw(f) for f in scanner(text)],
                False, False)
    combined = _try_import("push_scanning")
    if combined is not None and hasattr(combined, "scan_blob_text"):
        found, p_ok, g_ok = combined.scan_blob_text(text)
        return ([_normalise_raw(f) for f in found], p_ok, g_ok)
    findings: list = []
    pattern_ok = False
    generic_ok = False
    pattern_keys = set()
    patterns = _try_import("secret_scanning")
    if patterns is not None:
        pattern_ok = True
        for f in patterns.scan_text(text):
            findings.append(RawFinding(
                source="pattern", detector_id=f.detector_id,
                line=f.line, column=f.column,
                redacted=f.redacted, fingerprint=f.fingerprint))
            pattern_keys.add((f.fingerprint, f.line))
    generic = _try_import("generic_secret_detection")
    if generic is not None:
        generic_ok = True
        for f in generic.scan_generic(text):
            if (f.fingerprint, f.line) in pattern_keys:
                continue
            findings.append(RawFinding(
                source="generic", detector_id="generic_entropy",
                line=f.line, column=f.column,
                redacted=f.redacted, fingerprint=f.fingerprint))
    findings.sort(key=lambda f: (f.line, f.column, f.detector_id))
    return findings, pattern_ok, generic_ok


# --- findings, decisions, and the refusal sentence ------------------


@dataclass(frozen=True)
class ProtectionFinding:
    """One detected secret shape in one pushed file.
    Never the secret."""
    path: str
    commit_oid: str
    blob_oid: str
    source: str
    detector_id: str
    pattern_class: str
    line: int
    column: int
    redacted: str
    fingerprint: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "commit": self.commit_oid,
            "blob": self.blob_oid,
            "source": self.source,
            "detector_id": self.detector_id,
            "pattern_class": self.pattern_class,
            "line": self.line,
            "column": self.column,
            "redacted": self.redacted,
            "fingerprint": self.fingerprint,
        }


def refusal_reason(findings, partial_reason: str = "") -> str:
    """The sentence the pusher sees. Names the file
    and the pattern class of the first finding (and
    counts the rest), or the cap that cut the walk.
    Never the secret, never the redacted preview."""
    if findings:
        first = findings[0]
        sentence = (
            f"push refused: {first.path} contains a detected "
            f"secret ({first.pattern_class}) at line {first.line}; "
            "remove it and push again")
        rest = len(findings) - 1
        if rest:
            files = len({f.path for f in findings})
            sentence += (
                f"; and {rest} more detected secret"
                f"{'s' if rest != 1 else ''} in {files} "
                f"file{'s' if files != 1 else ''} in this push")
        return sentence
    if partial_reason == "commit_cap":
        return ("push refused: the push introduces more history "
                "than push protection can scan, so it cannot be "
                "proven free of detected secrets; push fewer "
                "commits at a time")
    if partial_reason == "blob_cap":
        return ("push refused: the push introduces more files "
                "than push protection can scan, so it cannot be "
                "proven free of detected secrets; push fewer "
                "files at a time")
    return "push refused by push protection"


@dataclass(frozen=True)
class PushProtectionDecision:
    allowed: bool
    findings: tuple
    reason: str            # "" when allowed
    commits_scanned: int
    blobs_scanned: int
    blobs_skipped: int
    partial_reason: str    # "" when the walk completed
    pattern_available: bool
    generic_available: bool

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "findings": [f.to_dict() for f in self.findings],
            "reason": self.reason,
            "commits_scanned": self.commits_scanned,
            "blobs_scanned": self.blobs_scanned,
            "blobs_skipped": self.blobs_skipped,
            "partial_reason": self.partial_reason,
            "pattern_available": self.pattern_available,
            "generic_available": self.generic_available,
        }


def decide(findings, *, commits_scanned: int = 0,
           blobs_scanned: int = 0, blobs_skipped: int = 0,
           partial_reason: str = "",
           pattern_available: bool = False,
           generic_available: bool = False
           ) -> PushProtectionDecision:
    """The pure decision over judged findings: any
    finding refuses; a capped walk refuses; a clean,
    complete walk allows."""
    found = tuple(findings)
    allowed = not found and not partial_reason
    return PushProtectionDecision(
        allowed=allowed, findings=found,
        reason="" if allowed else refusal_reason(found, partial_reason),
        commits_scanned=commits_scanned,
        blobs_scanned=blobs_scanned,
        blobs_skipped=blobs_skipped,
        partial_reason=partial_reason,
        pattern_available=pattern_available,
        generic_available=generic_available)


# --- the protection face ---------------------------------------------


class PushProtection:
    """Push protection over one instance's
    repositories: the refusal side of Part XV's
    scanning line, at the S-089 gate."""

    def __init__(self, repositories: RepositoryStore | None = None,
                 *, scanner=None,
                 max_commits: int = MAX_COMMITS_PER_PUSH,
                 max_blobs: int = MAX_BLOBS_PER_PUSH,
                 max_blob_bytes: int = MAX_BLOB_BYTES):
        self._repos = repositories
        self._scanner = scanner
        self._max_commits = max_commits
        self._max_blobs = max_blobs
        self._max_blob_bytes = max_blob_bytes
        self._last_decision = None

    @property
    def last_decision(self):
        """The most recent decision this face made
        (the gate plug-in's included) -- the road a
        caller behind the gate reads the findings
        through, since the gate copies the context
        payload and a stash there would not survive."""
        return self._last_decision

    # -- the text door (no history) ---------------------------------

    def check_texts(self, items) -> PushProtectionDecision:
        """Judge (path, text) pairs directly -- the
        door for callers that already hold the incoming
        content (and the battery's pure road). Findings
        carry no commit or blob (both "")."""
        findings: list = []
        pattern_ok = generic_ok = False
        probed = False
        judged_count = 0
        for path, text in items:
            judged_count += 1
            found, p_ok, g_ok = scan_text(text, scanner=self._scanner)
            if not probed:
                pattern_ok, generic_ok = p_ok, g_ok
                probed = True
            elif self._scanner is None:
                pattern_ok = pattern_ok or p_ok
                generic_ok = generic_ok or g_ok
            for f in found:
                findings.append(ProtectionFinding(
                    path=str(path), commit_oid="", blob_oid="",
                    source=f.source, detector_id=f.detector_id,
                    pattern_class=pattern_class_for(
                        f.detector_id, f.source),
                    line=f.line, column=f.column,
                    redacted=f.redacted, fingerprint=f.fingerprint))
        if self._scanner is None and not probed:
            pattern_ok = pattern_layer_available()
            generic_ok = generic_layer_available()
        self._require_detector(pattern_ok, generic_ok)
        findings.sort(key=lambda f: (f.path, f.line, f.column,
                                     f.detector_id))
        decision = decide(findings, blobs_scanned=judged_count,
            pattern_available=pattern_ok,
            generic_available=generic_ok)
        self._last_decision = decision
        return decision

    def _require_detector(self, pattern_ok: bool,
                          generic_ok: bool) -> None:
        if self._scanner is None and not pattern_ok and not generic_ok:
            raise PushProtectionError(
                "detector_unavailable",
                "push protection cannot judge this push: no "
                "secret detector is available (neither S-289's "
                "patterns nor S-290's generic detection), and a "
                "gate that cannot judge does not wave pushes "
                "through")

    # -- the push door ------------------------------------------------

    def check_push(self, owner, repo, updates, *, history=None,
                   prior_tips=()) -> PushProtectionDecision:
        """Judge one incoming push across its full
        introduced history and answer allow or refuse.
        A refusal is a decision, not an exception;
        malformed updates, a missing repository and a
        missing detector are named errors."""
        if self._repos is not None:
            current = self._repos.get_repository(owner, repo)
            if current is None:
                raise PushProtectionError(
                    "repo_not_found", "No such repository.")
        checked = tuple(_validate_update(u) for u in updates)
        if not checked:
            raise PushProtectionError(
                "updates_empty",
                "A push moves at least one ref; an empty push "
                "is refused, not waved.")
        if history is None:
            if self._repos is None:
                raise PushProtectionError(
                    "history_unavailable",
                    "push protection needs the repository's "
                    "history to judge a push")
            history = GitHistory(self._repos.path_for(owner, repo))
        commits = introduced_commits(history, checked, prior_tips)
        partial_reason = ""
        if len(commits) > self._max_commits:
            commits = commits[:self._max_commits]
            partial_reason = "commit_cap"
        judged: dict = {}
        occurrences: list = []
        blobs_skipped = 0
        blobs_judged = 0
        pattern_ok = generic_ok = False
        probed = False
        for commit_oid in commits:
            for path, _mode, blob_oid in introduced_blobs(
                    history, commit_oid):
                occurrences.append((commit_oid, path, blob_oid))
                if blob_oid in judged:
                    continue
                if len(judged) >= self._max_blobs:
                    if not partial_reason:
                        partial_reason = "blob_cap"
                    blobs_skipped += 1
                    judged[blob_oid] = ()
                    continue
                data = history.read_blob(blob_oid)
                if len(data) > self._max_blob_bytes:
                    blobs_skipped += 1
                    judged[blob_oid] = ()
                    continue
                if b"\x00" in data[:BINARY_SNIFF_BYTES]:
                    blobs_skipped += 1
                    judged[blob_oid] = ()
                    continue
                text = data.decode("utf-8", "replace")
                blobs_judged += 1
                found, p_ok, g_ok = scan_text(
                    text, scanner=self._scanner)
                if not probed:
                    pattern_ok, generic_ok = p_ok, g_ok
                    probed = True
                elif self._scanner is None:
                    pattern_ok = pattern_ok or p_ok
                    generic_ok = generic_ok or g_ok
                judged[blob_oid] = tuple(found)
        if self._scanner is None and not probed:
            pattern_ok = pattern_layer_available()
            generic_ok = generic_layer_available()
        self._require_detector(pattern_ok, generic_ok)
        findings: list = []
        reported: set = set()
        for commit_oid, path, blob_oid in occurrences:
            if (path, blob_oid) in reported:
                continue
            reported.add((path, blob_oid))
            for f in judged.get(blob_oid, ()):
                findings.append(ProtectionFinding(
                    path=path, commit_oid=commit_oid,
                    blob_oid=blob_oid, source=f.source,
                    detector_id=f.detector_id,
                    pattern_class=pattern_class_for(
                        f.detector_id, f.source),
                    line=f.line, column=f.column,
                    redacted=f.redacted, fingerprint=f.fingerprint))
        findings.sort(key=lambda f: (f.path, f.line, f.column,
                                     f.detector_id))
        decision = decide(
            findings, commits_scanned=len(commits),
            blobs_scanned=blobs_judged, blobs_skipped=blobs_skipped,
            partial_reason=partial_reason,
            pattern_available=pattern_ok,
            generic_available=generic_ok)
        self._last_decision = decision
        return decision

    # -- the S-089 gate plug-in ---------------------------------------

    def receive_gate_plugin(self):
        """This refusal as an S-089 `secret_scan`-stage
        plug-in: a callable over the gate context that
        allows (returns None) or vetoes with the
        refusal sentence (raises GateVeto). A push the
        context carries no ref updates for cannot be
        content-judged at this door and is allowed --
        the wire transports pass none today (pack
        contents are git's business, S-078's law);
        callers that know the updates are judged in
        full. The decision itself is kept on this face
        as `last_decision`, so the caller behind the
        gate can read the findings behind the verdict. A missing detector raises inside
        `check_push`, and the gate's fail-closed law
        turns that error into a refusal -- protection
        that cannot judge never waves a push through."""
        def plugin(context):
            if not context.updates:
                return None
            history = context.payload.get("history")
            prior_tips = context.payload.get("prior_tips", ())
            decision = self.check_push(
                context.owner, context.repo_name, context.updates,
                history=history, prior_tips=tuple(prior_tips))
            if not decision.allowed:
                raise GateVeto(decision.reason)
            return None
        return plugin


# --- the page face ----------------------------------------------------


def render_push_protection_page(decision: PushProtectionDecision,
                                title: str = "Push protection"):
    """The decision face: verdict, files and pattern
    classes, escaped through S-010 -- never a secret."""
    from .escaping import escape_html_text
    if decision.allowed:
        verdict = "<p>Push allowed: no detected secrets found.</p>"
        rows = ""
    else:
        verdict = ("<p>Push refused: "
                   + escape_html_text(decision.reason) + "</p>")
        rows = "".join(
            "<li>"
            + escape_html_text(f.path)
            + " -- "
            + escape_html_text(f.pattern_class)
            + " (line " + str(f.line) + "): "
            + escape_html_text(f.redacted)
            + "</li>"
            for f in decision.findings)
        if rows:
            rows = "<ul>" + rows + "</ul>"
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1>"
        + verdict
        + rows
        + "</body></html>")
