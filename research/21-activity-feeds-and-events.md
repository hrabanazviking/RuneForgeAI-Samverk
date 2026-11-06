# Samverk research 21 — Durable events for feeds, audit, webhook and notifications

**Research dossier, 2026-11-06.** Original technical synthesis of public material; engineering guidance, not proof of shipped functionality. Roadmap: **S-007–S-008, S-090, S-139, S-219–S-235**.

## What the technology requires

- Audit is a security record; an activity feed is a user-facing projection; a webhook is an external delivery. They may share a source event without having identical retention or visibility.
- Exactly-once external delivery across a network is generally not available. Durable at-least-once attempts plus deduplication keys are achievable with an outbox.
- Event order should be defined at least within each repository; wall-clock timestamps alone are not an ordering guarantee.

## Recommended architecture

- Use monotonic database event sequence and immutable event ID; generate all durable effects within the application transaction, with outbox delivery after commit.
- Require event version, actor kind/id, resource scope, safe metadata and created time; never serialize secret or full sensitive content merely to support future consumers.
- Build feed projections idempotently; store consumer cursor and replay after crash. Keep an audit-integrity chain separate from presentation redaction requirements.
- Control event publication by resource privacy and team membership when reading, not merely by filtering at initial write time.

## Risks, failure modes and honest limits

- Worker crashes after HTTP delivery but before ACK; two events with same timestamp; rename changes display path; deleted account; privacy revoked after feed cache.
- Do not promise total order across all instances unless a centralized sequencing authority exists.

## Acceptance tests and review questions

- Simulate worker restart and replay; compare outbox rows, feed counters and webhook attempts for no missing committed events.
- Attempt private event read through feeds and webhooks under three roles; prove uniform denial.

## Traceability requirements

Before declaring this study's roadmap slices finished, identify source modules, live HTTP/SSH route reachability, role and scope checks, data persistence, test commands, actual results and skips. Record accepted/rejected choices as engineering decisions. Update the memory map and claims register, never infer production readiness from a backend module alone. Study the referenced specifications at implementation time, because some evolve.

## Public references

1. https://www.sqlite.org/wal.html
2. https://www.rfc-editor.org/rfc/rfc9110.html
3. https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
