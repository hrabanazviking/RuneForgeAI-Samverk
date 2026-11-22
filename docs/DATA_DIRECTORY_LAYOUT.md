# Data Directory Layout (S-347)

One instance of Samverk keeps everything it owns in **one tree**,
rooted at the *data root*. Configuration names the root and nothing
else about the layout: `SAMVERK_DATA_ROOT`, or `data_root` in
`samverk.ini` (S-002/S-346). The platform default lives in
`samverk/platform_seam.py` (Linux: `$XDG_DATA_HOME/samverk` or
`~/.local/share/samverk`). The code that owns this document is
`samverk/data_layout.py`; this page and that module say the same
thing, and the S-347 battery proves the paths agree with the seams
that spelled them first.

## The tree

```
<data root>/
|-- samverk.db            the instance database (SQLite)      S-002/S-004
|   |-- samverk.db-wal    SQLite sidecars ride beside it
|   |-- samverk.db-shm
|   `-- samverk.db-journal
|-- samverk.ini           boot config, when kept with the data  S-002/S-346
|-- secrets.env           default secrets file, owner-only      S-003
|-- repos/                bare repositories                     S-013
|   `-- <owner>/
|       |-- <repo>.git/         bare repo
|       |   `-- lfs/objects/    LFS bytes, fanned out by oid    S-060
|       `-- <repo>.wiki/        the repo's wiki, a bare repo    S-273
|-- gists/                bare gist repos: gists/<owner>/<id>.git  S-277
|-- keys/                 instance keys, one file per purpose
|                         and version, owner-only               S-020
|-- avatars/              avatar assets, named by SHA-256       S-029
|-- release-assets/       release asset bytes                   S-259
|-- ci-artifacts/         CI artifact bytes                     S-266
|-- quarantine/           quarantined CI artifacts              S-266
|-- locks/                transient push locks (safe to lose)   S-092
`-- logs/                 RESERVED -- nothing writes here yet   S-347
```

Logs today: the server logs to stderr -- under S-348's systemd units
that is the journal -- and CI logs live in the database (S-322).
`logs/` is named and reserved so a future file-logging slice lands
in the tree instead of beside it.

LFS is deliberately **not** a top-level subtree: the bytes live
inside each bare repository (`<repo>.git/lfs/objects/<ab>/<cd>/<oid>`,
S-060), so a repository copied alone is complete, and the tree
copied whole cannot lose them.

## Standings

- **Required** (`repos/`, `gists/`, `keys/`): created by
  `ensure_layout` at first boot; a tree missing one is *incomplete*.
- **On use** (everything else above): created by its owner the
  first time it is needed; absence is normal, not damage.
- **Reserved** (`logs/`): named, owned, unwritten.

## The layout check

`samverk.data_layout.check_layout(root)` gathers the facts of a
tree once and judges them purely. Each subtree reports *present*,
*missing*, or *wrong kind* (a file where a directory belongs is
damage, in those words). Entries at the root that the layout does
not claim are named as *unclaimed* -- never silently tolerated.
The tree as a whole is:

- **sound** -- every required subtree present, nothing wrong-kind;
- **incomplete** -- a required subtree (or the root itself) is
  missing: the honest state of a fresh root before first boot;
- **damaged** -- something stands in the wrong kind.

## Moving an instance (relocation)

The tree is movable as a unit -- this is what makes the S-341
whole-instance export one archive of one root.
`samverk.data_layout.plan_relocation(old, new, ...)` judges a
proposed move purely and spells the story:

1. **Stop every writer first.** The server and any worker
   processes write the database, repositories and keys live. A
   half-copied database or repository is a damaged tree.
2. **Copy the whole tree as one unit.** Never move subtrees
   piecemeal; the layout is the unit.
3. **Repoint the configuration** (`SAMVERK_DATA_ROOT` /
   `data_root`) at the new root. Nothing inside the tree names
   the root, so this is the whole rewiring.
4. **What does not move:** a secrets file or TLS material
   configured *outside* the tree stays where it is -- its
   configured path stays true, and the plan names it. (The
   *default* secrets file, `<root>/secrets.env`, is inside the
   tree and moves with it.)
5. **Proof, then retire.** Run the layout check at the new root
   (it must report sound, or the same incompleteness the old tree
   honestly had), start the server against it and sign in --
   repository counts and the audit chain are the database's own
   proof. Only then retire the old tree, which until that moment
   is the rollback. S-342's restore drill is this proof,
   rehearsed.

A move onto the same root, or into the tree's own subtree, is
refused by the plan: a tree cannot move into itself.
