"""Data directory layout (S-347).

Before this slice, Samverk's data lived in one tree in
fact but nowhere in law: the database at the root
(S-002's ``Config.db_path``), bare repositories under
``repos/`` (S-013), LFS bytes inside each bare repo
(S-060), gists under ``gists/``, instance keys under
``keys/``, avatar assets under ``avatars/``, release
assets and CI artifacts in their own stores, push locks
under ``locks/``, the default secrets file at the root
(S-003) -- each path spelled by its owning slice, none
of them named together. Moving an instance meant
knowing all of that by heart.

This slice names the one tree, in one place:

- **One root, named subtrees.** ``SUBTREES`` is the
  whole layout: every directory or file directly under
  the data root, its owning slice, and its standing
  (required / created-on-use / reserved). ``layout_for``
  resolves every path in the tree from the root, and
  where an owning seam already resolves a path
  (S-013's ``repos_root``, the keys store's
  ``keys_dir``, S-002's ``db_path``, S-003's default
  secrets file) the layout *delegates* to it or is
  proven equal to it by the battery -- there is one
  spelling per path, never two.
- **A layout check that reports health.** Facts are
  gathered from disk once (``gather_facts``); the
  judgement (``judge_layout``) is pure over those
  facts: each subtree is present, missing, or the
  wrong kind (a file where a directory belongs is
  damage, said in words), unclaimed entries at the
  root are named rather than silently tolerated, and
  the tree as a whole is ``sound``, ``incomplete``
  (a required subtree missing -- the state of a fresh
  root before first boot, not an error), or
  ``damaged``. ``ensure_layout`` creates the required
  directories; nothing else here writes.
- **A relocation story that is honest.**
  ``plan_relocation`` is a pure judgement over the
  two roots: it refuses a move onto itself or into
  its own subtree, and its steps say what must stop
  first (every writer: the server and any worker
  processes -- the database, the repositories and
  the keys are all written live), that the tree moves
  as one unit (nothing in the tree holds an absolute
  path to another part of it; configuration names
  the root, so repointing ``SAMVERK_DATA_ROOT`` /
  ``data_root`` at the new root is the whole
  rewiring), what does *not* move (a secrets file or
  TLS material configured *outside* the tree stays
  where it is, and its configured path stays true),
  and the proof that closes the move (the layout
  check at the new root, then first boot against
  it). This is what makes S-341's whole-instance
  export simple: one root, one archive.

No migration (no database state names the layout);
no new taxonomy event (nothing here is audited --
the check is an operator's read, like `config check`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import keys as _keys
from . import platform_seam, repo_paths

# Standing words for a subtree.
REQUIRED = "required"        # created by ensure_layout; a sound tree has it
ON_USE = "on_use"            # created by its owner on first use
RESERVED = "reserved"        # named now, owned by a later slice

# Health words for one entry / the whole tree.
PRESENT = "present"
MISSING = "missing"
WRONG_KIND = "wrong_kind"
SOUND = "sound"
INCOMPLETE = "incomplete"
DAMAGED = "damaged"


@dataclass(frozen=True)
class Subtree:
    name: str          # path under the root ('' = the root itself)
    kind: str          # 'dir' or 'file'
    owner: str         # the slice that owns this subtree
    standing: str      # REQUIRED / ON_USE / RESERVED
    purpose: str


SUBTREES: tuple[Subtree, ...] = (
    Subtree("samverk.db", "file", "S-002/S-004", ON_USE,
            "The instance database (SQLite). Every account, "
            "repository row, setting and audit entry lives here."),
    Subtree("samverk.ini", "file", "S-002/S-346", ON_USE,
            "Boot configuration, when the operator keeps it "
            "with the data. Optional: config may live elsewhere."),
    Subtree("secrets.env", "file", "S-003", ON_USE,
            "The default secrets file (owner-only). Only the "
            "default lives here; a configured secret_file may "
            "point outside the tree."),
    Subtree("repos", "dir", "S-013", REQUIRED,
            "Bare repositories: repos/<owner>/<repo>.git, with "
            "each repo's LFS store inside it (S-060: "
            "<repo>.git/lfs/objects/) and its wiki beside it "
            "(S-273: <repo>.wiki)."),
    Subtree("gists", "dir", "S-277", REQUIRED,
            "Bare gist repositories: gists/<owner>/<id>.git."),
    Subtree("keys", "dir", "S-020", REQUIRED,
            "Instance key material, one file per purpose and "
            "version (instance-<purpose>-v<n>.key), owner-only."),
    Subtree("avatars", "dir", "S-029", ON_USE,
            "Avatar assets (user and organisation), "
            "content-addressed by SHA-256."),
    Subtree("release-assets", "dir", "S-259", ON_USE,
            "Release asset bytes: "
            "release-assets/<repo>/<release>/<file>."),
    Subtree("ci-artifacts", "dir", "S-266", ON_USE,
            "CI artifact bytes, content-addressed per repo."),
    Subtree("quarantine", "dir", "S-266", ON_USE,
            "Quarantined CI artifacts awaiting an operator's "
            "verdict."),
    Subtree("locks", "dir", "S-092", ON_USE,
            "Transient push locks. Safe to lose: a lock left "
            "by a dead process is a stale fact, not data."),
    Subtree("logs", "dir", "S-347", RESERVED,
            "Reserved for file logging. Today the server logs "
            "to stderr (the systemd journal under S-348) and "
            "CI logs live in the database (S-322); no process "
            "writes here yet."),
)

_BY_NAME = {s.name: s for s in SUBTREES}

# Names a healthy root may also carry that are not subtrees:
# SQLite's sidecar files ride beside the database.
_SIDECARS = ("samverk.db-wal", "samverk.db-shm", "samverk.db-journal")


@dataclass(frozen=True)
class DataLayout:
    """Every path in the tree, resolved from one root."""
    root: Path

    def path(self, name: str) -> Path:
        """The path of subtree *name* under the root.

        Unknown names raise KeyError: a path the layout
        does not name is not a path a seam may invent."""
        if name not in _BY_NAME:
            raise KeyError(f"no subtree named {name!r} in the layout")
        return self.root / name

    @property
    def db_path(self) -> Path:
        return self.root / "samverk.db"

    @property
    def secrets_file_default(self) -> Path:
        """S-003's default secrets file, inside the tree."""
        return self.root / "secrets.env"

    @property
    def repos_root(self) -> Path:
        # Delegated: S-013 owns this spelling.
        return repo_paths.repos_root(self.root)

    @property
    def keys_dir(self) -> Path:
        # Delegated: the keys store owns this spelling.
        return _keys.keys_dir(self.root)

    def lfs_objects_dir(self, repo_path: Path) -> Path:
        """S-060's LFS object store inside one bare repo."""
        return Path(repo_path) / "lfs" / "objects"


def layout_for(data_root: Path) -> DataLayout:
    return DataLayout(root=Path(data_root))


def subtree(name: str) -> Subtree:
    return _BY_NAME[name]


# -- the layout check -------------------------------------------------

@dataclass(frozen=True)
class EntryFact:
    name: str
    exists: bool
    is_dir: bool = False


@dataclass(frozen=True)
class LayoutFacts:
    root: Path
    root_exists: bool
    entries: tuple[EntryFact, ...] = ()
    unclaimed: tuple[str, ...] = ()


def gather_facts(data_root: Path) -> LayoutFacts:
    """Read the tree once; judgement happens elsewhere."""
    root = Path(data_root)
    if not root.is_dir():
        return LayoutFacts(root=root, root_exists=False)
    entries = []
    for sub in SUBTREES:
        p = root / sub.name
        entries.append(EntryFact(
            name=sub.name, exists=p.exists(),
            is_dir=p.is_dir() if p.exists() else False))
    known = set(_BY_NAME) | set(_SIDECARS)
    unclaimed = tuple(sorted(
        child.name for child in root.iterdir()
        if child.name not in known))
    return LayoutFacts(root=root, root_exists=True,
                       entries=tuple(entries), unclaimed=unclaimed)


@dataclass(frozen=True)
class EntryReport:
    name: str
    owner: str
    standing: str
    health: str        # PRESENT / MISSING / WRONG_KIND
    note: str = ""


@dataclass(frozen=True)
class LayoutReport:
    root: Path
    health: str        # SOUND / INCOMPLETE / DAMAGED
    entries: tuple[EntryReport, ...] = ()
    unclaimed: tuple[str, ...] = ()

    def problems(self) -> tuple[EntryReport, ...]:
        return tuple(e for e in self.entries
                     if e.health == WRONG_KIND
                     or (e.health == MISSING
                         and e.standing == REQUIRED))


def judge_layout(facts: LayoutFacts) -> LayoutReport:
    """Pure: facts in, health out. No disk touched."""
    if not facts.root_exists:
        return LayoutReport(
            root=facts.root, health=INCOMPLETE,
            entries=tuple(
                EntryReport(s.name, s.owner, s.standing, MISSING,
                            "the data root itself does not exist yet")
                for s in SUBTREES))
    by_name = {e.name: e for e in facts.entries}
    reports = []
    damaged = False
    incomplete = False
    for sub in SUBTREES:
        fact = by_name.get(sub.name)
        if fact is None or not fact.exists:
            health, note = MISSING, ""
            if sub.standing == REQUIRED:
                incomplete = True
                note = "required subtree is missing"
            elif sub.standing == RESERVED:
                note = "reserved; nothing writes here yet"
            else:
                note = "created on first use"
        elif (sub.kind == "dir") != fact.is_dir:
            health = WRONG_KIND
            damaged = True
            note = (f"a {'file' if not fact.is_dir else 'directory'} "
                    f"stands where a {sub.kind} belongs")
        else:
            health, note = PRESENT, ""
        reports.append(EntryReport(sub.name, sub.owner, sub.standing,
                                   health, note))
    health = DAMAGED if damaged else (INCOMPLETE if incomplete else SOUND)
    return LayoutReport(root=facts.root, health=health,
                        entries=tuple(reports),
                        unclaimed=facts.unclaimed)


def check_layout(data_root: Path) -> LayoutReport:
    """Gather + judge: the operator's one-call layout check."""
    return judge_layout(gather_facts(data_root))


def ensure_layout(data_root: Path) -> DataLayout:
    """Create the root and its REQUIRED directories.

    Files and on-use directories are their owners' to
    create; this only stands up the skeleton a first
    boot needs."""
    layout = layout_for(data_root)
    platform_seam.ensure_dir(layout.root)
    for sub in SUBTREES:
        if sub.kind == "dir" and sub.standing == REQUIRED:
            platform_seam.ensure_dir(layout.root / sub.name)
    return layout


# -- relocation -------------------------------------------------------

@dataclass(frozen=True)
class RelocationPlan:
    old_root: Path
    new_root: Path
    allowed: bool
    refusal: str = ""
    stop_first: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    stays_behind: tuple[str, ...] = ()
    proof: tuple[str, ...] = ()


def plan_relocation(old_root: Path, new_root: Path, *,
                    secret_file: Path | None = None,
                    tls_cert_file: Path | None = None,
                    tls_key_file: Path | None = None) -> RelocationPlan:
    """Pure judgement: may this tree move there, and how?

    The configured file paths are the caller's facts
    (from Config); a configured file outside the old
    tree does not move and is named in stays_behind."""
    old = Path(old_root)
    new = Path(new_root)
    old_r, new_r = old.resolve(), new.resolve()
    if old_r == new_r:
        return RelocationPlan(old, new, False,
                              "the new root is the old root; "
                              "there is nothing to move")
    if old_r in new_r.parents or new_r in old_r.parents:
        return RelocationPlan(old, new, False,
                              "the new root stands inside the old "
                              "tree (or around it); a tree cannot "
                              "move into itself")
    stays = []
    for label, p in (("secrets file", secret_file),
                     ("TLS certificate", tls_cert_file),
                     ("TLS key", tls_key_file)):
        if p is not None:
            resolved = Path(p).resolve()
            if resolved != old_r and old_r not in resolved.parents:
                stays.append(
                    f"the {label} at {p} lives outside the tree; "
                    f"it does not move, and its configured path "
                    f"stays true")
    return RelocationPlan(
        old_root=old, new_root=new, allowed=True,
        stop_first=(
            "the Samverk server process (it writes the database, "
            "the repositories and the keys live)",
            "every Samverk worker process (background jobs write "
            "artifacts, locks and repository state)",
        ),
        steps=(
            f"stop every writer (above); a half-copied database "
            f"or repository is a damaged tree",
            f"copy the whole tree as one unit: {old} -> {new} "
            f"(one copy of one root; never move subtrees "
            f"piecemeal -- the layout is the unit)",
            "repoint the configuration at the new root "
            "(SAMVERK_DATA_ROOT or data_root in samverk.ini); "
            "nothing inside the tree names the root, so this "
            "is the whole rewiring",
            "keep the old tree untouched until the proof "
            "passes; it is the rollback",
        ),
        stays_behind=tuple(stays),
        proof=(
            "run the layout check at the new root: it must "
            "report sound (or the same incompleteness the old "
            "tree honestly had)",
            "start the server against the new root and sign in; "
            "repository counts and the audit chain are the "
            "database's own proof (S-342's restore drill is "
            "this proof, rehearsed)",
            "only then retire the old tree",
        ))
