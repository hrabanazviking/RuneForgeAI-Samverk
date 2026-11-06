# Native worker queues, retries, idempotency and overload management

**Samverk implementation research, 2026-11-06.** This document provides proposed technical policy and acceptance work, not evidence that a feature has shipped. Existing roadmap references: S-331–S-343; S-345; S-219–S-235. Maintain the clean-room rule and no-Docker decision.

## Established context

- Mirror sync, index builds, webhook delivery, notifications, backups and CI scheduling all require background execution, but they have different latency and trust requirements.
- Network delivery can be repeated when a worker crashes after the receiver accepts an event. Exact-once delivery should not be promised; durable outbox and idempotency keys are realistic.
- Repeated memory contention and EDQUOT entries in historical project map are concrete reasons to design capacity-aware tests and workers from the beginning.

## Concrete engineering plan

- Persist job ID, type, repository scope, source event ID, priority, payload version, attempt, next attempt, lease owner/expiry and last safe error in SQLite. Claims must be transactional.
- Classify interactive Git and web actions ahead of background full-index rebuilds. Enforce bounded concurrency, process limits, temporary disk quota and memory budget per job class.
- On network timeout and 5xx, use capped exponential backoff plus jitter; treat invalid credentials as needs-operator instead of retrying endlessly; treat permission revocation as terminal.
- Expose pause/resume, retry, cancel and a truthful blocked-by-resources status in an administrator panel. Keep secret-bearing payloads out of logs.
- Reclaim expired worker leases after crash. Use idempotency keys for outward deliveries and deterministic file staging before marking a backup or export complete.

## Cases likely to break naive implementations

- Worker crashes after outbound 200 but before ACK; retry may reach receiver twice. Send same delivery ID.
- Disk full during manifest write should not cause a green backup status.
- Long index job or full test suite must not make health endpoint unresponsive indefinitely.

## Counted acceptance evidence required

- Terminate worker mid-job, restart and prove task resumes or safely replays without double side-effects.
- Inject ENOSPC/EDQUOT, unavailable network and stale lease; verify queue status and resource cleanup.
- Run simultaneous long job plus login/health checks and report actual latency and resource limits.

## Handoff rule

For every accepted implementation, identify the module and actual server entry point, submit an unauthorized-action test, document schema or migration effects, and verify both success and refusal behavior through the live process where relevant. Record the full test count, the host, and every skip. Update PROJECT_MEMORY_MAP and CLAIMS_REGISTER only with real evidence; do not silently upgrade an untested capability to PROVEN.

## Primary references

1. https://www.sqlite.org/lang_transaction.html
2. https://www.rfc-editor.org/rfc/rfc9110.html
3. https://docs.python.org/3/library/concurrent.futures.html
