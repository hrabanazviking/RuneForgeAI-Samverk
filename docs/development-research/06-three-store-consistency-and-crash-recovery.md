# Three-store consistency: SQLite, Git object store and filesystem

Samverk deliberately has three persisted systems: SQLite for identity/collaboration metadata, Git for immutable history/refs, and filesystem for LFS/assets/mirrors. These do **not** share a distributed atomic transaction.

## Consistency design invariants

1. Never say a push or merge succeeded unless the Git ref update actually landed.
2. Do not acknowledge issue/PR/event creation before its SQLite transaction commits.
3. Keep safe, recoverable intent/outcome records when operations span SQLite and Git.
4. Prefer idempotent replay and a verifier to inventing a global distributed lock.
5. Do not delete the only copy of unverified backup data during cleanup.

## Suggested write protocols

**Repository create:** reserve safe name in SQLite, create bare repo under staging path, initialize and validate HEAD, publish directory, mark SQLite status ready. On crash, scan pending rows and orphan dirs; recover or mark action needed. Never silently adopt unrelated directories.

**Push:** authorize proposed refs and receive gate; accept pack into Git quarantine where supported; validate objects and branch rules; publish ref(s) atomically using Git. Record push event in SQLite. If database event is missing after crash, reconciliation detects OID change against last known state and flags it without fabricating an actor.

**PR merge:** off-path build → CAS base ref → durable merge outcome and audit → outbox. On crash between Git and SQLite, compare expected merge/result OID and PR status in recovery job.

**LFS upload:** write bounded temp file → verify content hash/size → atomic publish → mark metadata. Orphans and pending records must be detectable and cleaned only after retention and safety checks.

## SQLite settings and backup

WAL mode can permit concurrent readers with one writer; `synchronous=FULL` is appropriate when stronger power-loss durability matters, with costs measured on real storage. Explicit `foreign_keys=ON` must be set on every connection. Do not copy a live SQLite main file and assume you captured its WAL state: use the online Backup API or a safe snapshot mechanism. Document how large transactions, checkpoints and disk-full errors behave.

## Recovery and observability

Create a read-only consistency scan that enumerates DB registered repos, actual bare dirs, ref/OID health, LFS pointer completeness, pending jobs, audit chain and queued outbox deliveries. Report classification: healthy / repairable discrepancy / requires operator intervention / unrecoverable. Never auto-delete a divergent repo.

Keep exported manifest: instance ID, schema version, Git repo refs, LFS checksums, key custody data description, DB checksum/snapshot time, and omissions. A backup is PROVEN only after a scratch-instance restore can authenticate and clone successfully.

## Chaos tests

- Power interruption simulation at every stage boundary; restart and run checker.
- `ENOSPC` or EDQUOT on Git ref lock, temp file, SQLite journal and audit append.
- Two competing writers to same ref; one wins via CAS.
- Stale mirror sync after a destructive upstream force-push.
- Interrupted backup; never present incomplete archive as valid.
- Restore onto different machine/filesystem and verify manifest.

## References

- https://www.sqlite.org/wal.html
- https://www.sqlite.org/pragma.html
- https://sqlite.org/backup.html
- https://git-scm.com/docs/git-update-ref
- https://git-scm.com/docs/git-fsck
