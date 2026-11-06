# Audit integrity, observability, incident diagnosis and honest public claims

**Samverk implementation research | 2026-11-06.** Guidance for coding agents and project directors, not a declaration of shipping or certified behavior. Roadmap references: S-007–S-008; S-356; S-393–S-404. Preserve all original 416 slices and clean-room/no-Docker laws.

## Context and engineering facts

- Operational health, audit integrity and feature readiness answer different questions. A process responding to /healthz proves the listener works but cannot certify backups or Git transports.
- Audit events carry actor and action evidence; normal telemetry tracks latency, queues and failures; README claims require versioned acceptance results.
- Hash-chained audit records detect certain tampering but do not guarantee the host cannot be compromised or that all events were successfully written.

## Concrete development plan

- Define separate status panels for HTTP, DB integrity, Git consistency, audit-chain verification, mirror freshness, job backlog, disk capacity, index age and recent security failures.
- Use structured logs with opaque correlation identifiers. Redact credentials, private repo content, LFS action URLs, SSH fingerprints where sensitive, HTTP Authorization, session cookies, and webhook signing secrets.
- Keep privacy and retention explicit: site admins can inspect protected logs, ordinary users see only permitted repo-level events, and private content never crosses audience boundary.
- For public release statements, attach exact commit SHA, test command, environment, passed/failed/skipped counts, fresh install/restore evidence and portability matrix.
- Before a release, verify signed artifacts, checksum manifest and any supply-chain provenance rather than describing a published tag as proof of trustworthy software.

## Failure cases and decision hazards

- Crash after Git ref update but before audit persistence; reconciliation must flag discrepancy instead of fabricating an actor.
- An observability dashboard can itself leak private repository names through search counts or error details.
- Do not report passing tests from partial log progress, especially after historical VM overload.

## Testable completion criteria

- Tamper with test-only audit row and verify chain checker catches it; verify error path logs remain redacted.
- Simulate worker outage, stale mirror and unhealthy DB; status dashboard must show distinct reasons.
- Require an explicit list of NOT PROVEN claims at every release checkpoint.

## Proof and provenance obligations

At the next implementation checkpoint record exact module paths, whether routes are mounted in the real server, actor/permission behavior, schema changes, actual host/toolchain, full test totals, all skips and an independently reproducible demo when needed. Update the claims register and project memory map only with evidence. Historical entries are not overwritten, and any missing capability remains NOT PROVEN.

## References

1. https://asvs.owasp.org/
2. https://slsa.dev/spec/v1.2/provenance
3. https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
