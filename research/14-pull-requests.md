# Samverk research 14 — Pull request state machine, merge methods, conflict and race handling

**Research dossier • 2026-11-06 • Engineering guidance, not a completion claim.** Original work based on public specifications and observable behavior, with no copied proprietary code or UI. Roadmap: **S-141–S-168, S-169–S-184**.

## What the protocols and user workflows require

- A PR represents a proposal to move a base branch toward head changes. Its reviewable diff depends on the current head and a merge-base, and can change after a push.
- Merge commit, squash and rebase create different commit graphs. They are not interchangeable labels on the same operation; authorship, audit trails and branch protections differ.
- Mergeability is derived, may become stale, and must be rechecked under an atomic branch-ref precondition when actually merging.

## Architecture and implementation decisions to evaluate

- Define states open-draft, open-ready, merged and closed-unmerged; store an immutable merge result with base/head OIDs and chosen method.
- For S-153–S-155, implement merge on an isolated temporary work area or Git plumbing path. Publish the final base ref via compare-and-swap; on conflict/ref race, publish nothing.
- Process closing-keyword updates through a recoverable outbox after Git commit succeeds, not before. Reconcile Git and SQLite state if the process dies between steps.
- Display conflict files and review/check failures prior to merge; recalculate at action time. Never let auto-merge silently bypass a gate.

## Failure modes and difficult cases

- Base branch changes after preview, fork deleted, head force-pushed, stale approval, simultaneous merge buttons, unicode commit subject, empty diff.
- Squash/rebase may rewrite commit identities. Record source and resultant commit OIDs for traceability.

## Acceptance checks for development agents

- Construct goldens for three merge strategies and verify graph shape via `git log --graph` and `merge-base`.
- Run conflicting changes and parallel merges; base branch changes exactly once, no partial updates.
- Run a full UI/HTTP PR lifecycle with writer, reviewer and unauthorized stranger; test audit and closing events after restart.

## Integration, evidence and scope

Document the exact modules and API/HTTP entry points touched, the permission decision, security boundary and failure handling. A green module-level test does not prove an end-to-end user-visible feature; test the assembled `samverk serve` process separately. Use explicit NOT PROVEN labels for unexercised SSH, browser, OS and recovery matrix cells. Record fresh commands and result counts. Keep the claims register and project memory map consistent with actual commits; retain history rather than rewriting earlier reports.

## Standards and research references

1. https://git-scm.com/docs/git-merge
2. https://git-scm.com/docs/git-rebase
3. https://git-scm.com/docs/git-merge-tree
4. https://git-scm.com/docs/git-update-ref
