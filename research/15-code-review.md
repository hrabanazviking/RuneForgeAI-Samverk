# Samverk research 15 — Review requests, diffs, approval freshness and suggestions

**Research dossier • 2026-11-06 • Engineering guidance, not a completion claim.** Original work based on public specifications and observable behavior, with no copied proprietary code or UI. Roadmap: **S-145–S-152, S-156–S-168**.

## What the protocols and user workflows require

- A review is attached to a particular head commit and verdict. New pushes can stale earlier approvals according to repository policy; the old review remains part of history.
- Line comments reference a side and position in a diff, which may become outdated after an edit. A thread can resolve without deleting previous comments.
- Samverk already has S-151 CODEOWNERS and S-152 manual reviewer-request stores; those are valuable internal services but not proof that browser review is routed.

## Architecture and implementation decisions to evaluate

- Retain immutable submission events and current derived state separately: last counting approval, change requests, resolved/unresolved threads and requested reviewers.
- Track review anchors with path, side, old/new line/commit and original context; show an outdated state with a link to the original diff rather than reassociating arbitrarily.
- Protect suggested-change application against stale head, overlapping patches and wrong author; a batch either creates one commit or does nothing.
- Keep CODEOWNERS requests idempotent and never resurrect dismissed requests on ordinary sync. Surface whether a reviewer was requested manually or by rule.

## Failure modes and difficult cases

- Reviewer who submits after a concurrent push, duplicated request token from team and CODEOWNERS, self-approval, missing codeowner user, review comments on binary files.
- Review status text must not rely on color; accessibility and keyboard focus matter in long diffs.

## Acceptance checks for development agents

- Recompute freshness across head moves with each policy mode; count only appropriate reviews for merge gates.
- Ensure Dismiss/re-request preserves event history, and a private repo outsider sees no reviewer information.
- End-to-end browser tests must submit review, annotate diff, resolve thread, apply suggestion, and enforce required approvals on merge.

## Integration, evidence and scope

Document the exact modules and API/HTTP entry points touched, the permission decision, security boundary and failure handling. A green module-level test does not prove an end-to-end user-visible feature; test the assembled `samverk serve` process separately. Use explicit NOT PROVEN labels for unexercised SSH, browser, OS and recovery matrix cells. Record fresh commands and result counts. Keep the claims register and project memory map consistent with actual commits; retain history rather than rewriting earlier reports.

## Standards and research references

1. https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/about-pull-request-reviews
2. https://git-scm.com/docs/git-diff
