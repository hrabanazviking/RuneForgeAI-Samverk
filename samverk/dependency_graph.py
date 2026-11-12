"""Dependency graph (S-297).

Roadmap S-297: Dependency graph -- manifests parsed
on push (requirements.txt, package.json, go.mod,
Cargo.toml, and the study file's list) into a
dependency table per repo.

Research file 33 fixes the shape: a dependency graph
is derived from manifests and lockfiles, not from
every file in the repository; parsers are built in
isolation per ecosystem; and the table stores the
package name, the version or range as written, the
origin path, the resolved/unresolved state and the
parser provenance. This slice is that graph for the
four manifest kinds the roadmap names. Lockfiles
(package-lock.json, Cargo.lock, go.sum, Pipfile.lock)
are not named by S-297 and are not parsed here --
the table honestly covers manifests only, and says
so wherever it is shown. S-298 brings advisory data
and S-299 the alerts this graph feeds; S-301 reviews
a pull request's manifest changes against it. None
of that is pre-built here.

- **Parsed on push, from the default branch's tip.**
  Like S-207's code index, the graph moves only when
  a push moves the default branch: any other push
  returns None -- the graph honestly did not move.
  A push that creates the default branch graphs its
  tip whole; a push that deletes it clears the
  repository's rows (the snapshot they described is
  gone) and reports the removals. The graphed
  snapshot is the new tip's full tree: every file
  whose basename is one of the four manifest names,
  at any depth, is a manifest of the graph.
- **Each ecosystem's parser is isolated and pure.**
  `parse_requirements` (Python), `parse_package_json`
  (npm), `parse_go_mod` (Go) and `parse_cargo_toml`
  (Rust, through the standard library's `tomllib`)
  judge text handed to them: no storage, no git, no
  network. `parse_manifest` dispatches on the
  basename alone, so the same text under an unknown
  name is refused `manifest_unknown`, never guessed
  at. A manifest whose whole text cannot be parsed
  (broken JSON, broken TOML) raises
  `manifest_invalid` from the pure layer; the graph
  records that manifest as skipped for that named
  reason and still graphs the rest -- coverage is
  said per manifest, never shrugged, and never a
  clean bill for a manifest that was not read.
- **Resolved means pinned, in the ecosystem's own
  semantics.** A dependency is `resolved` only when
  its specifier pins one exact version under its
  own ecosystem's rules (`is_exact_pin`): Python
  `==1.2.3` with no wildcard; npm a bare or `=`-
  prefixed exact version; Go module versions, which
  are always exact; Cargo only `=1.2.3` -- a bare
  Cargo `1.2.3` is a caret range and is honestly
  unresolved. Ranges, URLs, paths, VCS references,
  `*`, `latest` and bare names are unresolved: the
  graph records what the manifest says, never a
  version it would merely resolve to elsewhere.
- **No credential is ever stored.** Manifests can
  carry credentials -- a requirements option line
  naming an index URL with userinfo, a direct
  reference or a Cargo `git` source embedding a
  token. Specifiers pass through
  `redact_url_credentials`, which replaces the
  userinfo of any `://` URL with `***`; skipped
  requirement lines are recorded by line number
  and reason only, never by content. The graph
  table therefore holds package names and version
  shapes, and nothing a secret could ride in on.
- **Vendored manifests are not the repository's.**
  A manifest under a `node_modules` directory is a
  vendored copy of someone else's package: it is
  recorded as skipped `vendored`, never parsed
  into the table, so a dependency's own dependencies
  are not silently promoted to the repository's.
- **Caps are said, never silent.** A manifest past
  `MAX_MANIFEST_BYTES` is skipped `oversized`; a
  binary manifest (a NUL byte in its first bytes,
  git's own test) is skipped `binary`; a manifest
  past `MAX_DEPENDENCIES_PER_MANIFEST` parsed
  entries is cut there, stands `partial` naming the
  cap, and a graph past `MAX_MANIFESTS_PER_REPO`
  manifests stands partial likewise. Every skipped
  or cut manifest is an outcome on the run report.
- **Exactly once per snapshot, atomically.** The
  graph of a tip is computed whole -- every manifest
  read and judged -- before anything is written, so
  a damaged repository refuses by name
  (`commit_not_found`, `object_not_found`, ...)
  leaving the previous graph exactly as it stood.
  The replacement then lands in one transaction:
  the repository's manifest rows, dependency rows
  and graph state move together or not at all.
  Re-graphing the tip the graph already stands at
  returns the standing graph and writes nothing.
- **Reads follow the repository's own permission
  law.** The dependency table is read through
  S-190's permission engine, never re-derived: any
  standing role may read it; a public repository's
  table is readable by anyone, signed in or not; a
  stranger to a private or internal repository gets
  the uniform `repo_not_found`, before any manifest
  or dependency position is named.
- **Unwitnessed.** The push itself is already
  witnessed (`repo.push` at the transports, the
  push event in S-090's store). The graph is derived
  data over that record, rebuildable from the bare
  repository at any time: no new taxonomy event --
  134 stand (33 auth / 88 repo / 13 admin).

Storage is migration 120's `dependency_graph_states`,
`dependency_manifests` and `repo_dependencies` tables
(schema 119 -> 120 on this base; the keeper
renumbers at banking -- S-294 takes 117 first, then
S-295, S-296, in banking order).
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .escaping import escape_html_text
from .hooks import RefUpdate
from .objects import ObjectError, ObjectReader
from .refs import RefStore
from .repositories import Repository, RepositoryStore

__all__ = [
    "ECOSYSTEMS", "MANIFEST_KINDS", "MAX_DEPENDENCIES_PER_MANIFEST",
    "MAX_MANIFESTS_PER_REPO", "MAX_MANIFEST_BYTES",
    "Dependency", "DependencyGraphError", "DependencyGraphReport",
    "DependencyGraphStore", "GraphState", "ManifestOutcome",
    "ManifestRecord", "ParsedDependency", "ParsedManifest",
    "SkippedLine", "is_exact_pin", "is_manifest_path",
    "is_vendored_path", "manifest_kind_for", "normalise_name",
    "parse_cargo_toml", "parse_go_mod", "parse_manifest",
    "parse_package_json", "parse_requirements",
    "redact_url_credentials", "render_dependency_graph_page",
    "render_dependency_table_page",
]

ECOSYSTEMS = frozenset({"python", "npm", "go", "rust"})

#: Basename -> (ecosystem, kind): the whole of what
#: S-297 graphs. A file is a manifest by its basename
#: alone, at any depth in the snapshot.
MANIFEST_KINDS = {
    "requirements.txt": ("python", "requirements"),
    "package.json": ("npm", "package_json"),
    "go.mod": ("go", "go_mod"),
    "Cargo.toml": ("rust", "cargo_toml"),
}

MAX_MANIFEST_BYTES = 1_000_000
MAX_MANIFESTS_PER_REPO = 1_000
MAX_DEPENDENCIES_PER_MANIFEST = 5_000

_BINARY_PROBE_BYTES = 8192
_ZERO_OID = "0" * 40
_VENDORED_DIR = "node_modules"


class DependencyGraphError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# ------------------------------------------------------------------
# Pure law: discovery, names, pins, credential redaction
# ------------------------------------------------------------------

def manifest_kind_for(path: object) -> tuple[str, str] | None:
    """The (ecosystem, kind) a path is a manifest of,
    by its basename alone -- or None when the file is
    no manifest this slice graphs."""
    if not isinstance(path, str) or not path:
        return None
    return MANIFEST_KINDS.get(path.rsplit("/", 1)[-1])


def is_manifest_path(path: object) -> bool:
    return manifest_kind_for(path) is not None


def is_vendored_path(path: str) -> bool:
    """Whether *path* lives under a `node_modules`
    directory: a vendored copy, not the repository's
    own manifest."""
    return _VENDORED_DIR in path.split("/")[:-1]


def normalise_name(ecosystem: str, name: str) -> str:
    """The identity key of a package name under its
    own ecosystem's equivalence rules: Python's
    PEP 503 (lowercase, runs of -_. become -), npm's
    lowercase, Cargo's (lowercase, _ becomes -).
    Go module paths are case-significant and stand
    as written."""
    if ecosystem == "python":
        return re.sub(r"[-_.]+", "-", name.strip().lower())
    if ecosystem == "npm":
        return name.strip().lower()
    if ecosystem == "rust":
        return name.strip().lower().replace("_", "-")
    return name.strip()


_URL_USERINFO_RE = re.compile(r"(://)[^/@\s]*@")


def redact_url_credentials(specifier: str) -> str:
    """*specifier* with the userinfo of every URL in
    it replaced by `***`: a manifest may embed a
    credential in an index, direct-reference or git
    URL, and the graph stores version shapes, never
    credentials."""
    return _URL_USERINFO_RE.sub(r"\1***@", specifier)


_EXACT_SEMVER_RE = re.compile(
    r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def is_exact_pin(ecosystem: str, specifier: str) -> bool:
    """Whether *specifier* pins one exact version
    under *ecosystem*'s own semantics. See the
    module docstring for the four laws; anything
    unrecognised is unresolved, never guessed."""
    spec = specifier.strip()
    if not spec:
        return False
    if ecosystem == "python":
        if "," in spec or "*" in spec:
            return False
        if spec.startswith("=="):
            return bool(_EXACT_SEMVER_RE.match(spec[2:].strip())) \
                or bool(re.fullmatch(r"[0-9][0-9A-Za-z.-]*", spec[2:].strip()))
        return False
    if ecosystem == "npm":
        if spec.startswith("="):
            spec = spec[1:].strip()
        return bool(_EXACT_SEMVER_RE.match(spec))
    if ecosystem == "go":
        return bool(re.fullmatch(r"v[0-9][0-9A-Za-z.+-]*", spec))
    if ecosystem == "rust":
        if spec.startswith("="):
            return bool(_EXACT_SEMVER_RE.match(spec[1:].strip()))
        return False
    return False


# ------------------------------------------------------------------
# Parsed shapes
# ------------------------------------------------------------------

@dataclass(frozen=True)
class ParsedDependency:
    """One dependency as its manifest states it: the
    name as written and its normalised identity key,
    the specifier as written (credentials redacted),
    any extras, the scope the manifest states, the
    environment marker when one rides along, and
    whether the specifier pins one exact version."""
    name: str
    name_key: str
    ecosystem: str
    specifier: str
    scope: str                # 'direct' | 'dev' | 'peer' | ...
    resolved: bool
    extras: str = ""
    marker: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name, "name_key": self.name_key,
            "ecosystem": self.ecosystem,
            "specifier": self.specifier, "scope": self.scope,
            "resolved": self.resolved, "extras": self.extras,
            "marker": self.marker,
        }


@dataclass(frozen=True)
class SkippedLine:
    """One manifest line the parser did not turn into
    a dependency, said by number and reason only --
    never by content, which may carry a credential."""
    line: int
    reason: str               # 'option_line' | 'malformed_line' | ...


@dataclass(frozen=True)
class ParsedManifest:
    """One manifest parsed: its dependencies in
    manifest order and every line it skipped."""
    dependencies: tuple
    skipped: tuple


def _dep(ecosystem: str, name: str, specifier: str, scope: str,
         *, extras: str = "", marker: str = "",
         resolved: bool | None = None) -> ParsedDependency:
    spec = redact_url_credentials(specifier.strip())
    return ParsedDependency(
        name=name.strip(),
        name_key=normalise_name(ecosystem, name),
        ecosystem=ecosystem, specifier=spec, scope=scope,
        resolved=is_exact_pin(ecosystem, spec)
        if resolved is None else resolved,
        extras=extras.strip(), marker=marker.strip())


# ------------------------------------------------------------------
# Pure parsers, one per ecosystem
# ------------------------------------------------------------------

_REQ_NAME_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]|[A-Za-z0-9])"
    r"(?:\[([^\]]*)\])?\s*(.*)$")


def parse_requirements(text: str) -> ParsedManifest:
    """Parse a Python `requirements.txt`: one
    dependency per line, in the PEP 508 shape the
    file's ecosystem actually writes. Blank lines
    and comments carry nothing; option lines
    (`-r`, `-e`, `--index-url`, ...) are skipped
    `option_line` by number only; a line that does
    not open with a package name is skipped
    `malformed_line`. Backslash continuations are
    joined before judging. An environment marker
    after `;` is recorded as the marker it is."""
    joined: list[tuple[int, str]] = []
    buffer = ""
    buffer_line = 0
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if buffer:
            buffer += line.strip()
        else:
            buffer, buffer_line = line, number
        if buffer.endswith("\\"):
            buffer = buffer[:-1]
            continue
        joined.append((buffer_line, buffer))
        buffer = ""
    if buffer:
        joined.append((buffer_line, buffer))
    deps: list[ParsedDependency] = []
    skipped: list[SkippedLine] = []
    for number, raw in joined:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            skipped.append(SkippedLine(number, "option_line"))
            continue
        hash_at = line.find(" #")
        if hash_at != -1:
            line = line[:hash_at].rstrip()
        main, _, marker = line.partition(";")
        main = main.strip()
        if " @ " in main:
            name_part, _, url = main.partition(" @ ")
            match = _REQ_NAME_RE.match(name_part.strip())
            if match is None or match.group(3).strip():
                skipped.append(SkippedLine(number, "malformed_line"))
                continue
            deps.append(_dep(
                "python", match.group(1),
                "@ " + url.strip(), "direct",
                extras=match.group(2) or "", marker=marker,
                resolved=False))
            continue
        match = _REQ_NAME_RE.match(main)
        if match is None:
            skipped.append(SkippedLine(number, "malformed_line"))
            continue
        deps.append(_dep(
            "python", match.group(1), match.group(3), "direct",
            extras=match.group(2) or "", marker=marker))
    return ParsedManifest(tuple(deps), tuple(skipped))


_PACKAGE_JSON_SCOPES = (
    ("dependencies", "direct"),
    ("devDependencies", "dev"),
    ("peerDependencies", "peer"),
    ("optionalDependencies", "optional"),
)


def parse_package_json(text: str) -> ParsedManifest:
    """Parse an npm `package.json`: the four
    dependency sections, each under its own scope
    word. The document must be a JSON object or the
    manifest is refused whole (`manifest_invalid`) --
    a package file that cannot be read names no
    dependencies at all. A section that is not an
    object, and an entry whose specifier is not a
    string, are skipped by name, never coerced."""
    try:
        data = json.loads(text)
    except ValueError:
        raise DependencyGraphError(
            "manifest_invalid",
            "package.json is not valid JSON.") from None
    if not isinstance(data, dict):
        raise DependencyGraphError(
            "manifest_invalid",
            "package.json must hold a JSON object.")
    deps: list[ParsedDependency] = []
    skipped: list[SkippedLine] = []
    for section, scope in _PACKAGE_JSON_SCOPES:
        entries = data.get(section)
        if entries is None:
            continue
        if not isinstance(entries, dict):
            skipped.append(SkippedLine(0, "section_not_object"))
            continue
        for name in sorted(entries):
            value = entries[name]
            if not isinstance(value, str):
                skipped.append(
                    SkippedLine(0, "specifier_not_string"))
                continue
            deps.append(_dep("npm", name, value, scope))
    return ParsedManifest(tuple(deps), tuple(skipped))


_GO_VERSION_RE = re.compile(r"^v[0-9]\S*$")


def parse_go_mod(text: str) -> ParsedManifest:
    """Parse a Go `go.mod`: the `require` directives,
    single-line and block form alike. A require
    carrying the `// indirect` comment is scope
    `indirect`; every other require is `direct`.
    The module's own `module` line is not a
    dependency, and `replace` / `exclude` /
    `retract` directives are not dependencies --
    they are passed over, and the graph says only
    what `require` says. A require whose version is
    not a module version is skipped `malformed_line`."""
    deps: list[ParsedDependency] = []
    skipped: list[SkippedLine] = []
    in_block = False
    for number, raw in enumerate(text.splitlines(), 1):
        code, _, comment = raw.partition("//")
        line = code.strip()
        indirect = "indirect" in comment.split()
        if in_block:
            if line == ")":
                in_block = False
                continue
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2 or not _GO_VERSION_RE.match(parts[1]):
                skipped.append(SkippedLine(number, "malformed_line"))
                continue
            deps.append(_dep(
                "go", parts[0], parts[1],
                "indirect" if indirect else "direct"))
            continue
        if line == "require (":
            in_block = True
            continue
        if line.startswith("require "):
            parts = line[len("require "):].split()
            if len(parts) != 2 or not _GO_VERSION_RE.match(parts[1]):
                skipped.append(SkippedLine(number, "malformed_line"))
                continue
            deps.append(_dep(
                "go", parts[0], parts[1],
                "indirect" if indirect else "direct"))
    return ParsedManifest(tuple(deps), tuple(skipped))


_CARGO_SECTIONS = (
    ("dependencies", "direct"),
    ("dev-dependencies", "dev"),
    ("build-dependencies", "build"),
    ("workspace.dependencies", "workspace"),
)


def _cargo_section(data: dict, dotted: str) -> object:
    current: object = data
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _cargo_entries(deps: list, skipped: list, section: object,
                   scope: str) -> None:
    if section is None:
        return
    if not isinstance(section, dict):
        skipped.append(SkippedLine(0, "section_not_table"))
        return
    for key in sorted(section):
        value = section[key]
        if isinstance(value, str):
            deps.append(_dep("rust", key, value, scope))
            continue
        if not isinstance(value, dict):
            skipped.append(SkippedLine(0, "specifier_not_string"))
            continue
        name = value.get("package", key)
        if not isinstance(name, str) or not name:
            name = key
        version = value.get("version")
        git = value.get("git")
        path = value.get("path")
        if isinstance(version, str) and version:
            specifier = version
        elif isinstance(git, str) and git:
            specifier = "git+" + git
        elif isinstance(path, str) and path:
            specifier = "path+" + path
        else:
            specifier = ""
        deps.append(_dep("rust", name, specifier, scope))


def parse_cargo_toml(text: str) -> ParsedManifest:
    """Parse a Rust `Cargo.toml` through the standard
    library's TOML reader: the `dependencies`,
    `dev-dependencies` and `build-dependencies`
    tables, the workspace dependency table, and any
    target-specific dependency tables (scope
    `target`). A string value is the version
    requirement as written; a table value speaks by
    its `version`, else its `git` source, else its
    `path` -- and a `package` key renames the
    dependency to the package it truly names. A
    document that is not valid TOML is refused
    whole (`manifest_invalid`)."""
    try:
        data = tomllib.loads(text)
    except ValueError:
        raise DependencyGraphError(
            "manifest_invalid",
            "Cargo.toml is not valid TOML.") from None
    deps: list[ParsedDependency] = []
    skipped: list[SkippedLine] = []
    for dotted, scope in _CARGO_SECTIONS:
        _cargo_entries(deps, skipped, _cargo_section(data, dotted), scope)
    targets = data.get("target")
    if isinstance(targets, dict):
        for cfg in sorted(targets):
            table = targets[cfg]
            if isinstance(table, dict):
                _cargo_entries(
                    deps, skipped, table.get("dependencies"), "target")
    return ParsedManifest(tuple(deps), tuple(skipped))


_PARSERS = {
    "requirements": parse_requirements,
    "package_json": parse_package_json,
    "go_mod": parse_go_mod,
    "cargo_toml": parse_cargo_toml,
}


def parse_manifest(path: str, text: str) -> ParsedManifest:
    """Parse one manifest by its basename's own
    parser. An unknown basename is refused
    `manifest_unknown` -- text is never guessed into
    an ecosystem it did not declare."""
    found = manifest_kind_for(path)
    if found is None:
        raise DependencyGraphError(
            "manifest_unknown",
            f"No manifest kind is known for {path!r}.")
    _ecosystem, kind = found
    return _PARSERS[kind](text)


# ------------------------------------------------------------------
# Stored shapes and run results
# ------------------------------------------------------------------

@dataclass(frozen=True)
class ManifestOutcome:
    """One manifest's outcome in a graph run: parsed
    with its dependency count, or skipped / partial /
    removed with its named reason."""
    path: str
    ecosystem: str
    kind: str
    status: str               # 'parsed' | 'skipped' | 'partial' | 'removed'
    reason: str = ""
    dependencies_count: int = 0
    blob_oid: str = ""
    size: int = 0


@dataclass(frozen=True)
class DependencyGraphReport:
    """One graph run, whole: the snapshot it graphed,
    the snapshot that stood before ('' when none),
    every manifest's outcome in path order, and every
    dependency the run stands behind."""
    repo_id: int
    full_name: str
    commit_oid: str
    previous_oid: str
    outcomes: tuple
    dependencies: tuple
    partial_reason: str = ""

    @property
    def status(self) -> str:
        return "partial" if self.partial_reason else "complete"

    @property
    def manifests_parsed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "parsed")

    @property
    def manifests_skipped(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "skipped")

    @property
    def dependencies_count(self) -> int:
        return len(self.dependencies)


@dataclass(frozen=True)
class GraphState:
    """Where one repository's graph stands: the
    snapshot it describes and its counted size."""
    repo_id: int
    full_name: str
    commit_oid: str
    manifests_count: int
    dependencies_count: int
    updated_at: int

    def to_dict(self) -> dict:
        return {
            "repository": self.full_name,
            "commit": self.commit_oid,
            "manifests": self.manifests_count,
            "dependencies": self.dependencies_count,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ManifestRecord:
    """One manifest row as the table holds it."""
    id: int
    repo_id: int
    path: str
    ecosystem: str
    kind: str
    status: str
    reason: str
    dependencies_count: int
    blob_oid: str

    def to_dict(self) -> dict:
        return {
            "id": self.id, "path": self.path,
            "ecosystem": self.ecosystem, "kind": self.kind,
            "status": self.status, "reason": self.reason,
            "dependencies": self.dependencies_count,
            "blob": self.blob_oid,
        }


@dataclass(frozen=True)
class Dependency:
    """One dependency row as the table holds it:
    a parsed dependency plus the manifest it came
    from."""
    id: int
    repo_id: int
    manifest_path: str
    kind: str
    dependency: ParsedDependency

    def to_dict(self) -> dict:
        out = self.dependency.to_dict()
        out["id"] = self.id
        out["manifest"] = self.manifest_path
        out["kind"] = self.kind
        return out


@dataclass(frozen=True)
class _Leaf:
    path: str
    mode: str
    oid: str


# ------------------------------------------------------------------
# The store: git snapshots in, dependency table out
# ------------------------------------------------------------------

class DependencyGraphStore:
    """The S-297 graph. It reads snapshots from the
    bare repository through S-051's batch object
    reader, judges each manifest through the pure
    parsers, and writes migration 120's tables. It
    grants no permission of its own: reads resolve
    through S-190's engine, exactly as the rest of
    the house reads a repository."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 accounts=None,
                 *, time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._now = time_fn
        self._engine = None
        if accounts is not None:
            from .permission_engine import PermissionEngine
            self._engine = PermissionEngine(
                conn, accounts, audit=None, time_fn=time_fn)

    # -- resolution -------------------------------------

    def _resolve(self, owner: object, repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise DependencyGraphError(
                "repo_not_found", "No such repository.")
        return current

    def _resolve_read(self, viewer, owner: object,
                      repo: object) -> Repository:
        current = self._resolve(owner, repo)
        if self._engine is not None:
            resolution = self._engine.resolve(viewer, current)
            if viewer is None or resolution.role is None:
                if current.visibility != "public":
                    raise DependencyGraphError(
                        "repo_not_found", "No such repository.")
        elif current.visibility != "public":
            if viewer is None or getattr(viewer, "username", None) \
                    != current.owner:
                raise DependencyGraphError(
                    "repo_not_found", "No such repository.")
        return current

    # -- snapshots ---------------------------------------

    def snapshot(self, owner: object, repo: object,
                 commit_oid: object) -> dict:
        """The full leaf map of one commit, read by
        walking its trees through the batch reader.
        An unreadable commit is refused by name."""
        current = self._resolve(owner, repo)
        if not isinstance(commit_oid, str) or not commit_oid:
            raise DependencyGraphError(
                "commit_not_found", "A commit oid is required.")
        reader = ObjectReader(
            self._repos.path_for(current.owner, current.name))
        try:
            commit = reader.read_commit(commit_oid)
        except ObjectError as exc:
            raise DependencyGraphError(
                exc.reason, str(exc)) from None
        leaves: dict[str, _Leaf] = {}
        stack: list[tuple[str, str]] = [("", commit.tree)]
        while stack:
            prefix, tree_oid = stack.pop()
            try:
                entries = reader.read_tree(tree_oid)
            except ObjectError as exc:
                raise DependencyGraphError(
                    exc.reason, str(exc)) from None
            for entry in entries:
                path = f"{prefix}{entry.name}"
                if entry.type == "tree":
                    stack.append((path + "/", entry.oid))
                else:
                    leaves[path] = _Leaf(
                        path=path, mode=entry.mode, oid=entry.oid)
        return leaves

    def _state_row(self, repo_id: int):
        return self._conn.execute(
            "SELECT repo_id, commit_oid, manifests_count,"
            " dependencies_count, updated_at"
            " FROM dependency_graph_states WHERE repo_id = ?",
            (repo_id,)).fetchone()

    # -- graphing ------------------------------------------

    def graph_tip(self, owner: object, repo: object,
                  commit_oid: object) -> DependencyGraphReport:
        """Graph one snapshot whole: every manifest in
        it parsed into the repository's dependency
        table, replacing the graph that stood before.

        The whole graph is computed before anything
        is written, and the replacement lands in one
        transaction. Graphing the tip the graph
        already stands at returns the standing graph
        and writes nothing."""
        current = self._resolve(owner, repo)
        if not isinstance(commit_oid, str) or not commit_oid \
                or commit_oid == _ZERO_OID:
            raise DependencyGraphError(
                "commit_not_found", "A commit oid is required.")
        standing = self._state_row(current.id)
        previous = standing["commit_oid"] if standing else ""
        if previous == commit_oid:
            return self._standing_report(current)
        snap = self.snapshot(owner, repo, commit_oid)
        manifest_paths = sorted(
            p for p in snap if is_manifest_path(p))
        partial_reason = ""
        if len(manifest_paths) > MAX_MANIFESTS_PER_REPO:
            partial_reason = "manifest_cap"
        reader = ObjectReader(
            self._repos.path_for(current.owner, current.name))
        outcomes: list[ManifestOutcome] = []
        rows: list[tuple[str, ParsedDependency]] = []
        for index, path in enumerate(manifest_paths):
            leaf = snap[path]
            ecosystem, kind = manifest_kind_for(path) or ("", "")
            if index >= MAX_MANIFESTS_PER_REPO:
                outcomes.append(ManifestOutcome(
                    path=path, ecosystem=ecosystem, kind=kind,
                    status="skipped", reason="manifest_cap",
                    blob_oid=leaf.oid))
                continue
            if leaf.mode == "160000":
                outcomes.append(ManifestOutcome(
                    path=path, ecosystem=ecosystem, kind=kind,
                    status="skipped", reason="submodule",
                    blob_oid=leaf.oid))
                continue
            if is_vendored_path(path):
                outcomes.append(ManifestOutcome(
                    path=path, ecosystem=ecosystem, kind=kind,
                    status="skipped", reason="vendored",
                    blob_oid=leaf.oid))
                continue
            try:
                data = reader.read_blob(leaf.oid)
            except ObjectError as exc:
                raise DependencyGraphError(
                    exc.reason, str(exc)) from None
            if len(data) > MAX_MANIFEST_BYTES:
                outcomes.append(ManifestOutcome(
                    path=path, ecosystem=ecosystem, kind=kind,
                    status="skipped", reason="oversized",
                    blob_oid=leaf.oid, size=len(data)))
                continue
            if b"\x00" in data[:_BINARY_PROBE_BYTES]:
                outcomes.append(ManifestOutcome(
                    path=path, ecosystem=ecosystem, kind=kind,
                    status="skipped", reason="binary",
                    blob_oid=leaf.oid, size=len(data)))
                continue
            try:
                parsed = parse_manifest(
                    path, data.decode("utf-8", "replace"))
            except DependencyGraphError as exc:
                outcomes.append(ManifestOutcome(
                    path=path, ecosystem=ecosystem, kind=kind,
                    status="skipped", reason=exc.reason,
                    blob_oid=leaf.oid, size=len(data)))
                continue
            deps = parsed.dependencies
            status, reason = "parsed", ""
            if len(deps) > MAX_DEPENDENCIES_PER_MANIFEST:
                deps = deps[:MAX_DEPENDENCIES_PER_MANIFEST]
                status, reason = "partial", "dependency_cap"
                if not partial_reason:
                    partial_reason = "dependency_cap"
            outcomes.append(ManifestOutcome(
                path=path, ecosystem=ecosystem, kind=kind,
                status=status, reason=reason,
                dependencies_count=len(deps),
                blob_oid=leaf.oid, size=len(data)))
            rows.extend((path, dep) for dep in deps)
        updated_at = int(self._now())
        with self._conn:
            self._conn.execute(
                "DELETE FROM repo_dependencies WHERE repo_id = ?",
                (current.id,))
            self._conn.execute(
                "DELETE FROM dependency_manifests WHERE repo_id = ?",
                (current.id,))
            for outcome in outcomes:
                self._conn.execute(
                    "INSERT INTO dependency_manifests ("
                    " repo_id, path, ecosystem, kind, status,"
                    " reason, dependencies_count, blob_oid)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (current.id, outcome.path, outcome.ecosystem,
                     outcome.kind, outcome.status, outcome.reason,
                     outcome.dependencies_count, outcome.blob_oid))
            kinds = {o.path: o.kind for o in outcomes}
            for path, dep in rows:
                self._conn.execute(
                    "INSERT INTO repo_dependencies ("
                    " repo_id, manifest_path, ecosystem, kind,"
                    " name, name_key, specifier, extras, scope,"
                    " resolved, marker)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (current.id, path, dep.ecosystem, kinds[path],
                     dep.name, dep.name_key, dep.specifier,
                     dep.extras, dep.scope,
                     1 if dep.resolved else 0, dep.marker))
            self._conn.execute(
                "INSERT OR REPLACE INTO dependency_graph_states ("
                " repo_id, commit_oid, manifests_count,"
                " dependencies_count, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (current.id, commit_oid, len(outcomes),
                 len(rows), updated_at))
        return DependencyGraphReport(
            repo_id=current.id, full_name=current.full_name,
            commit_oid=commit_oid, previous_oid=previous,
            outcomes=tuple(outcomes),
            dependencies=tuple(dep for _p, dep in rows),
            partial_reason=partial_reason)

    def graph_push(self, owner: object, repo: object,
                   updates) -> DependencyGraphReport | None:
        """Graph what one accepted push changed, per
        the trigger law: only a push that moves the
        default branch moves the graph. Any other push
        returns None. A push that deletes the default
        branch clears the graph and reports the
        removals."""
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
        return self.graph_tip(owner, repo, update.new_oid)

    def graph_repository(self, owner: object, repo: object,
                         commit_oid: object = None,
                         ) -> DependencyGraphReport:
        """Graph one repository at the named commit,
        or at the default branch's current tip when
        none is named. An empty repository is refused
        `commit_not_found`."""
        current = self._resolve(owner, repo)
        if commit_oid is None:
            repo_path = self._repos.path_for(
                current.owner, current.name)
            tip = RefStore(repo_path).resolve(current.default_branch)
            if tip is None:
                raise DependencyGraphError(
                    "commit_not_found",
                    "This repository has no commits yet.")
            commit_oid = tip
        return self.graph_tip(owner, repo, commit_oid)

    def rebuild_repository(self, owner: object, repo: object,
                           commit_oid: object = None,
                           ) -> DependencyGraphReport:
        """Rebuild one repository's graph whole -- the
        same road as `graph_repository`."""
        return self.graph_repository(owner, repo, commit_oid)

    def _clear(self, current: Repository) -> DependencyGraphReport:
        rows = self._manifest_rows(current.id)
        previous = ""
        standing = self._state_row(current.id)
        if standing:
            previous = standing["commit_oid"]
        with self._conn:
            self._conn.execute(
                "DELETE FROM repo_dependencies WHERE repo_id = ?",
                (current.id,))
            self._conn.execute(
                "DELETE FROM dependency_manifests WHERE repo_id = ?",
                (current.id,))
            self._conn.execute(
                "DELETE FROM dependency_graph_states"
                " WHERE repo_id = ?", (current.id,))
        return DependencyGraphReport(
            repo_id=current.id, full_name=current.full_name,
            commit_oid="", previous_oid=previous,
            outcomes=tuple(
                ManifestOutcome(
                    path=r.path, ecosystem=r.ecosystem,
                    kind=r.kind, status="removed",
                    reason="deleted", blob_oid=r.blob_oid)
                for r in rows),
            dependencies=())

    def remove_repository(self, owner: object, repo: object) -> int:
        """Purge one repository's graph rows (the
        repository-deletion seam). Returns how many
        manifests were removed."""
        current = self._resolve(owner, repo)
        return len(self._clear(current).outcomes)

    # -- rows and reads --------------------------------------

    def _manifest_rows(self, repo_id: int) -> tuple:
        rows = self._conn.execute(
            "SELECT id, repo_id, path, ecosystem, kind, status,"
            " reason, dependencies_count, blob_oid"
            " FROM dependency_manifests WHERE repo_id = ?"
            " ORDER BY path", (repo_id,)).fetchall()
        return tuple(ManifestRecord(
            id=r["id"], repo_id=r["repo_id"], path=r["path"],
            ecosystem=r["ecosystem"], kind=r["kind"],
            status=r["status"], reason=r["reason"],
            dependencies_count=int(r["dependencies_count"]),
            blob_oid=r["blob_oid"]) for r in rows)

    def _dependency_rows(self, repo_id: int) -> tuple:
        rows = self._conn.execute(
            "SELECT id, repo_id, manifest_path, ecosystem, kind,"
            " name, name_key, specifier, extras, scope, resolved,"
            " marker FROM repo_dependencies WHERE repo_id = ?"
            " ORDER BY ecosystem, name_key, manifest_path, scope",
            (repo_id,)).fetchall()
        return tuple(Dependency(
            id=r["id"], repo_id=r["repo_id"],
            manifest_path=r["manifest_path"], kind=r["kind"],
            dependency=ParsedDependency(
                name=r["name"], name_key=r["name_key"],
                ecosystem=r["ecosystem"],
                specifier=r["specifier"], scope=r["scope"],
                resolved=bool(r["resolved"]),
                extras=r["extras"], marker=r["marker"]))
            for r in rows)

    def _standing_report(self,
                         current: Repository) -> DependencyGraphReport:
        standing = self._state_row(current.id)
        manifests = self._manifest_rows(current.id)
        deps = self._dependency_rows(current.id)
        return DependencyGraphReport(
            repo_id=current.id, full_name=current.full_name,
            commit_oid=standing["commit_oid"] if standing else "",
            previous_oid=standing["commit_oid"] if standing else "",
            outcomes=tuple(ManifestOutcome(
                path=m.path, ecosystem=m.ecosystem, kind=m.kind,
                status=m.status, reason=m.reason,
                dependencies_count=m.dependencies_count,
                blob_oid=m.blob_oid) for m in manifests),
            dependencies=tuple(d.dependency for d in deps))

    def graph_state_for(self, owner: object, repo: object,
                        viewer=None) -> GraphState | None:
        """Where the repository's graph stands, or None
        when it has never been graphed -- read under
        the repository's permission law."""
        current = self._resolve_read(viewer, owner, repo)
        standing = self._state_row(current.id)
        if standing is None:
            return None
        return GraphState(
            repo_id=current.id, full_name=current.full_name,
            commit_oid=standing["commit_oid"],
            manifests_count=int(standing["manifests_count"]),
            dependencies_count=int(standing["dependencies_count"]),
            updated_at=int(standing["updated_at"]))

    def manifests_for(self, owner: object, repo: object,
                      viewer=None) -> tuple:
        """Every manifest row of the standing graph, in
        path order -- parsed, skipped and partial
        alike, each with its named standing."""
        current = self._resolve_read(viewer, owner, repo)
        return self._manifest_rows(current.id)

    def dependencies_for(self, owner: object, repo: object,
                         viewer=None, *,
                         ecosystem: object = None) -> tuple:
        """The repository's dependency table: every
        dependency row of the standing graph, ordered
        by ecosystem, name, manifest and scope. An
        `ecosystem` filter narrows to one ecosystem;
        an unknown one is refused `ecosystem_unknown`."""
        current = self._resolve_read(viewer, owner, repo)
        if ecosystem is not None and ecosystem not in ECOSYSTEMS:
            raise DependencyGraphError(
                "ecosystem_unknown",
                f"Unknown ecosystem: {ecosystem!r}.")
        rows = self._dependency_rows(current.id)
        if ecosystem is not None:
            rows = tuple(
                r for r in rows if r.dependency.ecosystem == ecosystem)
        return rows

    def dependency_graph(self, owner: object, repo: object,
                         viewer=None) -> dict:
        """The whole table as one JSON-safe dict: the
        graph state (or None), its manifests and its
        dependencies, under the read law. This is
        the shape S-299's alerts and S-307's security
        tab will read."""
        current = self._resolve_read(viewer, owner, repo)
        state = self.graph_state_for(owner, repo, viewer)
        return {
            "repository": current.full_name,
            "state": state.to_dict() if state else None,
            "manifests": [m.to_dict()
                          for m in self._manifest_rows(current.id)],
            "dependencies": [d.to_dict()
                             for d in self._dependency_rows(current.id)],
        }


# ------------------------------------------------------------------
# Rendering (S-010 escaped)
# ------------------------------------------------------------------

def render_dependency_graph_page(report: DependencyGraphReport) -> str:
    """One graph run rendered for a person: the
    snapshot it graphed, the counts in words --
    manifests only, lockfiles honestly not covered
    -- and every manifest with its standing."""
    parts = [
        f"<h1>Dependency graph -- "
        f"{escape_html_text(report.full_name)}</h1>",
        f"<p>Snapshot {escape_html_text(report.commit_oid or 'none')}"
        f" graphed: {report.manifests_parsed} manifests parsed, "
        f"{report.manifests_skipped} manifests skipped, "
        f"{report.dependencies_count} dependencies in the table. "
        f"The graph is derived from manifests only; lockfiles "
        f"are not parsed.</p>",
        "<ul>",
    ]
    if report.partial_reason:
        parts.append(
            f"<li>Graph partial ({escape_html_text(report.partial_reason)})")
    for outcome in report.outcomes:
        if outcome.status == "parsed":
            words = (f"parsed ({outcome.ecosystem}): "
                     f"{outcome.dependencies_count} dependencies")
        elif outcome.status == "partial":
            words = (f"partial ({outcome.reason}): "
                     f"{outcome.dependencies_count} dependencies")
        elif outcome.status == "removed":
            words = "removed (no longer in the snapshot)"
        else:
            words = f"skipped ({outcome.reason})"
        parts.append(
            f"<li>{escape_html_text(outcome.path)} -- "
            f"{escape_html_text(words)}</li>")
    parts.append("</ul>")
    return "\n".join(parts)


def render_dependency_table_page(full_name: str,
                                 state: GraphState | None,
                                 dependencies: tuple) -> str:
    """The standing dependency table rendered for a
    person: one row per dependency with its
    ecosystem, specifier as written, scope, manifest
    and pinned-or-range standing said in words --
    never colour-only. All user text escaped."""
    parts = [
        f"<h1>Dependencies -- {escape_html_text(full_name)}</h1>",
    ]
    if state is None:
        parts.append(
            "<p>No dependency graph has been built for this "
            "repository yet.</p>")
        return "\n".join(parts)
    parts.append(
        f"<p>{state.dependencies_count} dependencies from "
        f"{state.manifests_count} manifests at snapshot "
        f"{escape_html_text(state.commit_oid)}. The graph is "
        f"derived from manifests only; lockfiles are not "
        f"parsed.</p>")
    parts.append("<ul>")
    for row in dependencies:
        dep = row.dependency
        standing = "pinned" if dep.resolved else "range or reference"
        parts.append(
            f"<li>{escape_html_text(dep.ecosystem)}: "
            f"{escape_html_text(dep.name)} "
            f"{escape_html_text(dep.specifier)} "
            f"({escape_html_text(dep.scope)}, {standing}, "
            f"from {escape_html_text(row.manifest_path)})</li>")
    parts.append("</ul>")
    return "\n".join(parts)
