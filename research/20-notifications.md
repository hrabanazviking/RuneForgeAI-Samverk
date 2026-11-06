# Samverk research 20 — Notification routing, watch states, and humane inbox behavior

**Research dossier, 2026-11-06.** Original technical synthesis of public material; engineering guidance, not proof of shipped functionality. Roadmap: **S-219–S-235**.

## What the technology requires

- Notification is a projection of events and subscriptions, not the canonical audit trail; losing an email send must not roll back a code review event.
- Mentions, review requests, CI failures and repository watches have distinct reasons. Users need to know why they received each alert.
- Large repositories can emit many events. Batching, mute and thread-level subscriptions protect attention without hiding security-critical account notices.

## Recommended architecture

- Persist subscriptions and delivery preferences independently from immutable event rows. Deduplicate by event ID × recipient × reason.
- Route recipient calculation through permissions, excluding actors who cannot see the underlying private resource. On permission revocation, hide or redact previously queued previews.
- Separate in-app inbox, email digest and high-priority security notice policies; do not email raw secret-bearing diff bodies.
- Provide mark read/unread, mute and unsubscribe affordances adjacent to each notice; use stable links and explain source context.

## Risks, failure modes and honest limits

- Duplicate webhook replay, self-mention, user muted a PR but assigned reviewer, notification before DB transaction commit, deleted private repo.

## Acceptance tests and review questions

- Test exact reason text per event, per-user de-duplication and retries; prove an event remains durable when outbound email fails.
- Exercise 'mute this conversation' with 50 subsequent events; inbox stays silent except explicitly documented exceptions.

## Traceability requirements

Before declaring this study's roadmap slices finished, identify source modules, live HTTP/SSH route reachability, role and scope checks, data persistence, test commands, actual results and skips. Record accepted/rejected choices as engineering decisions. Update the memory map and claims register, never infer production readiness from a backend module alone. Study the referenced specifications at implementation time, because some evolve.

## Public references

1. https://docs.github.com/en/subscriptions-and-notifications/concepts/about-notifications
2. https://www.rfc-editor.org/rfc/rfc9110.html
