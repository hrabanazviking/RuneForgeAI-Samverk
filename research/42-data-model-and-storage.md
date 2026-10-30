# Study 42 — Data Model and Storage

*Study question (from `research/INDEX.md`): What lives in SQLite, what
lives in the filesystem object store, and what lives in git itself —
and how do the three stay consistent under crash and concurrent load?*

*Status: complete 2026-10-29. This is the storage constitution for the
whole roadmap: Part I's skeleton (S-002), secrets law (S-003), audit
core (S-007), and all of Part III stand on it. Method: clean-room —
SQLite's public documentation and well-known operating discipline, the
public git object model, and hard lessons from Samtal's production
operation (WAL behaviour, commit-before-answer discipline), restated
as Samverk's own design.*

---

## 1. The three stores and the one rule

Samverk keeps state in exactly three places, each doing the job it is
provably good at:

1. **SQLite** — all *metadata and state*: users, permissions,
   repository records, issues, sessions, tokens, the audit chain, the
   event store. One database file per instance.
2. **The filesystem** — *bulk bytes that are not history*: bare
   repository directories (whose internal layout belongs to git),
   uploaded assets and release files, LFS objects, quarantined uploads
   awaiting verdicts. Addressed by content hash where the bytes are
   immutable.
3. **Git itself** — *history*: commits, trees, blobs, tags. Samverk
   never re-implements the object model and never stores a second copy
   of history in SQLite; it stores *pointers* (repository id, ref name,
   oid) and asks git for the rest, through plumbing commands only
   (roadmap architecture stance; study 04).

**The one rule:** for any fact, exactly one store is its home. Other
stores may cache or index it, but caches are rebuildable and are
labelled as such in the schema (`cache_` prefix) so nobody mistakes a
cache for a truth.

## 2. SQLite discipline (the Samtal lessons, made law)

Samtal's production history taught us, at real cost, how a threaded
Python server and SQLite must be handled. Those lessons are Samverk's
founding storage law:

- **WAL journal mode** (`PRAGMA journal_mode=WAL`) — readers do not
  block the writer; the village stays responsive under load.
- **`synchronous=FULL`** — a commit that returns is a commit that
  survives a power cut. We pay the fsync; durability is not the place
  to be clever. (This pairing — WAL + FULL — is the durability law.)
- **`foreign_keys=ON`** on every connection, no exceptions; a
  connection factory is the *only* way application code gets a
  connection, so pragmas cannot be forgotten at a call site.
- **`busy_timeout`** set generously (5 s) so brief writer contention
  resolves itself instead of surfacing as errors.
- **Commit-before-answer:** a handler that issues anything a client
  will immediately rely on (a credential, a token, a state change the
  next request assumes) must commit *before* the response is sent.
  Samtal shipped this race four times (a just-issued credential refused
  by the very next request) before it became law; Samverk inherits the
  law without re-paying the tuition. Acceptance tests in later parts
  include "use the thing you were just handed, immediately" cases.
- **One writer queue for hot paths** where ordering matters (audit
  chain appends, ref-update records): serialised in-process, so the
  hash chain and sequence numbers never interleave.
- **Migrations are numbered, transactional, and boring.** Schema
  version lives in the database (`PRAGMA user_version` or a
  `schema_meta` table); each migration runs in one transaction; a
  failed migration leaves the previous version intact and the server
  refuses to start against a half-migrated file.
- **Backups are SQLite's own**: the online backup API (or
  `VACUUM INTO`) produces a consistent file from a live instance —
  never a raw copy of a WAL-mode database file taken mid-flight.
  (Part XVII/XVIII runbooks build on this.)

## 3. What lives where (the allocation table)

| Fact | Home | Why |
|---|---|---|
| Users, credentials (hashes only), 2FA state | SQLite | Relational, transactional, must join with permissions. |
| Sessions, API/access tokens (hashed) | SQLite | Revocation must be instant and queryable (studies 07/09). |
| Instance configuration that is data (settings) | SQLite, `settings` table | Auditable changes (study 35) need transactional old→new. |
| Instance configuration that is *boot* (data dir, listen address, secret file path) | Config file + env | Must exist before the DB can open (S-002/S-003). |
| Instance secrets (signing/sealing keys) | **Never SQLite.** Env or a mode-600 file (S-003) | A leaked DB must not be a working keyring (threat model T-03). |
| Repository records (owner, name, visibility, default branch) | SQLite | The *record*; the bytes are git's. |
| Bare repository contents (objects, refs on disk) | Filesystem, managed by git | Git's own store is the most audited object store we will ever have. |
| Ref state Samverk must reason about transactionally (protection, last-push records) | SQLite, reconciled with git | Git refs are the truth for *history*; SQLite mirrors only what queries need, and reconciliation treats git as senior. |
| Issues, PRs, comments, reviews | SQLite | Forge-native data; git never sees it. Cross-references store oids as text. |
| The event store / audit chain | SQLite, append-only tables | One truth for audit/feeds/webhooks (study 35). |
| Uploaded assets, release binaries, avatars | Filesystem, content-addressed (`objects/sha256/aa/bb…`) | Immutable bytes; SQLite holds name/size/hash/owner metadata. Deduplication is free. |
| LFS objects | Filesystem, content-addressed by their SHA-256 oid | That *is* the LFS design (study 06). |
| Quarantined uploads | Filesystem, separate quarantine tree | Never inside the served tree until cleared (S-012). |
| Search indexes | SQLite (FTS5) or derived files, `cache_` labelled | Rebuildable from homes; losing them is an inconvenience, never data loss (Part X). |
| Logs | Filesystem, plain files, rotated by the operator's platform tools | Not state; redacted at write (S-018). |

## 4. Consistency between the stores (crash honesty)

Three stores means three failure seams. The design rules:

1. **Order of writing for creations:** bytes first, record second.
   Write the file/object (to a temporary name in the same filesystem),
   fsync, atomically rename into place, *then* commit the SQLite row
   that points at it. A crash between the steps leaves an orphan file
   (harmless, swept by a janitor pass), never a database row pointing
   at nothing (a lie).
2. **Order for deletions:** record first (tombstone), bytes second.
   Mark the row deleted in a transaction; a background sweep removes
   the bytes. A crash leaves a tombstone and orphan bytes — again
   harmless, again sweepable. Nothing is ever *un*-deletable because
   its bytes vanished first.
3. **Git operations are the third seam.** A push changes git state
   outside any SQLite transaction. Samverk's rule: git is senior for
   history. Post-receive, Samverk records what git reports (ref, old,
   new) into SQLite + audit in one transaction; if that recording
   fails, the push still happened (git said so) and a reconciler
   re-derives the record from git's reflog/state on next start. We
   never pretend a database rollback can un-happen a pack.
4. **Startup reconciliation:** on boot, Samverk runs a cheap
   consistency pass: repositories whose directories are missing are
   flagged (not silently dropped), cache tables are marked stale if
   their build marker is absent, the audit chain head is verified
   (full verification is the operator command of study 35; boot does
   head + last-N spot checks so a Pi boots fast).
5. **IDs are integers internally, opaque externally.** SQLite rowids
   stay inside; anything shown to the world (URLs, API) uses public
   ids that do not leak counts or creation order across tenants.

## 5. Filesystem layout (one data root)

Everything Samverk owns lives under one operator-chosen **data root**
(config file, S-002), so backup = "the data root + the SQLite backup
file" and sovereignty = "it is all in one place you control":

```
<data-root>/
  samverk.db            (plus -wal/-shm while running)
  repos/<owner>/<name>.git/     bare repositories (git's layout inside)
  objects/sha256/…              assets, LFS, release files (content-addressed)
  quarantine/                   uploads awaiting verdict (S-012)
  tmp/                          in-flight writes (same filesystem → atomic rename)
  secrets/                      mode-600/700 secret files if not env (S-003)
  logs/                         when the operator chooses files over journal
```

Owner/name → path mapping is *never* string concatenation at call
sites: one resolver (S-013) validates owner and name against the
naming law, resolves symlinks, and proves the result stays inside
`repos/` — on every platform, with that platform's case and separator
rules (threat model TB8; study 45).

## 6. Scale honesty

This design targets village-to-small-city scale: one machine, one
SQLite writer, thousands of repositories, tens of thousands of users
at the outside. SQLite under WAL+FULL on Pi-class storage sustains
that comfortably; the design deliberately does *not* chase horizontal
scaling. The seams that would allow a future move (connection factory,
single event store, content-addressed bytes) are kept clean, and the
claims register must state the tested scale, not an imagined one
(Part XXI measures it).

## 7. Design decisions taken

1. SQLite (WAL, FULL, FK on, busy timeout) via one connection factory;
   commit-before-answer as testable law.
2. Bytes content-addressed on the filesystem; git owns history;
   tombstone-then-sweep deletions; bytes-then-record creations.
3. Git senior for history; SQLite reconciles, never overrules.
4. One data root; one path resolver; secrets never in the DB.
5. Migrations numbered and transactional; backups only via SQLite's
   online backup machinery.

## 8. Slices this study feeds

S-002 (skeleton: config, data root, connection factory shape), S-003
(secrets law), S-007 (audit appends through the writer queue), S-013
(path resolver), Part III (repository storage), Part XVII (backup and
mirror duties), Part XVIII (install/upgrade runbooks).
