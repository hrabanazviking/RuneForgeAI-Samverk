# Samverk research 13 — Issue lifecycle, cross-references, and human-scale triage

**Research dossier • 2026-11-06 • Engineering guidance, not a completion claim.** Original work based on public specifications and observable behavior, with no copied proprietary code or UI. Roadmap: **S-121–S-140, S-205–S-216**.

## What the protocols and user workflows require

- Issue numbers are a stable shared namespace with PRs, so creating a PR cannot reuse an issue number. Existing Samverk tests already cover this core invariant.
- Labels, milestones, assignees, comments, reactions, edit history, templates and timelines are separate user-visible elements but must share one consistent event order.
- Search qualifiers must have documented semantics; a UI field labelled 'open issues' must not silently mix closed issues or PRs.

## Architecture and implementation decisions to evaluate

- Treat issue create/update/close/reopen as explicit state transitions with timestamp, actor and noneditable history; compute timeline from durable events.
- Prevent cross-reference explosion by indexing edges and breaking cycles in rendering rather than recursive fetches; keep references to private resources hidden from unauthorized readers.
- Enforce role checks for title edits, close/reopen, labels, moderation and deletion; present denied actions as understandable text.
- Use templates as convenience, never as a means to bypass validation. Allow a blank form when site policy permits.

## Failure modes and difficult cases

- Double-close race, duplicate mention, deleted comment with surviving audit history, huge Markdown body, label rename and stale saved filter.
- Public issue body referencing a private PR should not disclose private title or participants.

## Acceptance checks for development agents

- Run two writers claiming numbers concurrently; each issue/PR gets a unique monotonic number.
- Assert timeline event order before and after page refresh, schema migrations and import.
- Use a real browser journey to open/assign/label/close/reopen with proper accessibility and safe HTML output.

## Integration, evidence and scope

Document the exact modules and API/HTTP entry points touched, the permission decision, security boundary and failure handling. A green module-level test does not prove an end-to-end user-visible feature; test the assembled `samverk serve` process separately. Use explicit NOT PROVEN labels for unexercised SSH, browser, OS and recovery matrix cells. Record fresh commands and result counts. Keep the claims register and project memory map consistent with actual commits; retain history rather than rewriting earlier reports.

## Standards and research references

1. https://docs.github.com/en/issues/tracking-your-work-with-issues/about-issues
2. https://www.rfc-editor.org/rfc/rfc9110.html
