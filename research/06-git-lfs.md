# Samverk research 06 — Git LFS pointers, transfer API, and storage integrity

**Research and engineering brief | 2026-11-06 | Status: proposed design guidance, not a shipped-feature claim.**

This study fills the originally empty numbered research shelf. It uses public standards and observable Git behavior, not GitHub proprietary code or assets. Apply it under Samverk's clean-room, AGPL, no-Docker, security-first and standalone-first laws. Relevant roadmap: **S-060–S-061, S-068, S-090–S-094, S-340**.

## Protocol facts and engineering implications

- Git LFS commits a small pointer into Git while placing large object bytes in an independent SHA-256-addressed store. Git transport success alone does not establish LFS completeness.
- The LFS batch API announces requested objects and supplies upload/download/verify actions. Locking is a separate optional protocol surface, and real `git-lfs` clients must be tested instead of merely emulating request JSON.
- Signed action URLs are bearer capabilities: an attacker with an unexpired URL may exercise the authorized operation, so expiry, scope and log redaction matter.

## Recommended Samverk architecture and contracts

- Reuse `samverk/lfs_store.py`, `lfs_api.py`, `lfs_locks.py`; bind object OID, repository, operation, expiry and identity authorization to each action. Only consider an upload complete after digest and size verification.
- Use bounded streaming, temp files and atomic publish/rename where supported. Quarantine incomplete uploads and make cleanup idempotent; refuse symlink escapes out of LFS storage roots.
- Enforce read/write scope at batch issuance and again at action fulfillment where feasible; do not leak object existence of private repositories through subtly different errors.
- Count LFS bytes in quotas, exports and mirror consistency. A mirror lacking LFS content should be visibly incomplete and not advertised as a successful recovery copy.

## Failure modes and less-obvious cases

- Object wrong digest, wrong declared length, zero bytes, huge sparse upload, reused action URL, expired URL, simultaneous clients uploading same OID, overlapping lock holder identities.
- Do not promise resumable upload unless a specific transfer adapter and its recovery semantics have been implemented and tested.

## Testable acceptance work

- Run a real git-lfs push/clone against assembled Samverk HTTP routes with files above ordinary Git blob budgets and under non-owner credentials.
- Fuzz batch requests and action tokens; assert wrong digest never materializes and hidden/private objects remain hidden.
- Interrupt an upload halfway, restart, and prove cleanup; export, restore and verify LFS OIDs against committed pointers.

## Evidence and decision discipline

- Compare each recommendation against current implementations and tests before coding. Existing modules are **evidence of implementation**, not proof they are wired to the live `samverk/server.py` HTTP surface.
- Record decisions (accepted/deferred/rejected), exact test command and host, passing/failing/skipped counts, and any changes to `docs/CLAIMS_REGISTER.md` and `PROJECT_MEMORY_MAP.md`.
- Do not promote interoperability, security or portability to PROVEN without a fresh end-to-end run in the specified environment.

## Public technical references

1. https://github.com/git-lfs/git-lfs/blob/main/docs/api/README.md
2. https://github.com/git-lfs/git-lfs/blob/main/docs/api/batch.md
3. https://github.com/git-lfs/git-lfs/blob/main/docs/api/locking.md
