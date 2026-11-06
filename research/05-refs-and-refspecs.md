# Samverk research 05 — References, refspecs, and atomic branch mutation

**Research and engineering brief | 2026-11-06 | Status: proposed design guidance, not a shipped-feature claim.**

This study fills the originally empty numbered research shelf. It uses public standards and observable Git behavior, not GitHub proprietary code or assets. Apply it under Samverk's clean-room, AGPL, no-Docker, security-first and standalone-first laws. Relevant roadmap: **S-052–S-053, S-089, S-169–S-184**.

## Protocol facts and engineering implications

- Refs include branches, tags, remote-tracking names and symbolic refs such as HEAD; loose and packed representations are implementation details handled by Git.
- Refspecs express which references to fetch or push, with force and deletion semantics. Accepting a transport command is not the same as authorizing each ref update.
- An update based on a stale read creates a time-of-check/time-of-use race. The Git `update-ref` old-OID precondition is a compare-and-swap primitive; the receive gate must apply branch policy to the actual proposed old and new values.

## Recommended Samverk architecture and contracts

- Normalize and validate full ref names via Git's own rules; keep display short names separate from stored full refs and never build an arbitrary shell command from a ref.
- Use `git update-ref` / `update-ref --stdin` transactions for compare-and-swap updates and multi-ref atomicity where supported. On contention, fail with `stale_head`; do not overwrite another user's push.
- Distinguish branch creation, force update, deletion, annotated tag creation, tag move and symbolic HEAD change. Policy and audit must name the precise operation.
- Separate role-based permission, token scope, protection rule evaluation, quota, and secret-scanning stages. A write permission alone is not permission to bypass protected branch gates.

## Failure modes and less-obvious cases

- Concurrent updates to same branch; branch rename during PR creation; tag replacement; delete of default branch; case-folding collisions on portable hosts; a ref pointing to nonexistent/corrupt object.
- Closing a PR on merge should happen after the actual Git ref move, with a recoverable event/outbox record if metadata write later fails.

## Testable acceptance work

- Two concurrent writers race with the same expected old OID; exactly one wins and the loser receives an actionable stale-head refusal.
- Test packed refs, symbolic HEAD, normal and forced pushes, deletion, and protected ref bypass audits via stock Git.
- Inject crash between Git ref update and SQLite event persistence; reconciliation must reconstruct/flag the gap without inventing a commit.

## Evidence and decision discipline

- Compare each recommendation against current implementations and tests before coding. Existing modules are **evidence of implementation**, not proof they are wired to the live `samverk/server.py` HTTP surface.
- Record decisions (accepted/deferred/rejected), exact test command and host, passing/failing/skipped counts, and any changes to `docs/CLAIMS_REGISTER.md` and `PROJECT_MEMORY_MAP.md`.
- Do not promote interoperability, security or portability to PROVEN without a fresh end-to-end run in the specified environment.

## Public technical references

1. https://git-scm.com/docs/git-update-ref
2. https://git-scm.com/docs/git-check-ref-format
3. https://git-scm.com/docs/git-fetch
4. https://git-scm.com/docs/git-push
