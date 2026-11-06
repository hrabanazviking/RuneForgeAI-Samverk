# Delivery-critical path, architectural risks and maturity gates

**Samverk implementation research | 2026-11-06.** Guidance for coding agents and project directors, not a declaration of shipping or certified behavior. Roadmap references: S-153–S-168; S-331–S-344; S-345–S-416. Preserve all original 416 slices and clean-room/no-Docker laws.

## Context and engineering facts

- The 416-numbered-slice roadmap remains canonical. This plan is a risk/dependency overlay, not a renumbering or declaration that work has been completed.
- Samverk's most urgent functional risks are incomplete merge algorithms, feature modules absent from live server routes, and insufficient end-to-end security/interop proof.
- An installable, recoverable and understandable application is the product goal; isolated module counts are not a completion percentage.

## Concrete development plan

- Workstream A: execute S-153 merge commit, S-154 squash, S-155 rebase, S-156 conflict surfacing and later S-168 review gate with atomic ref updates and outbox reconciliation.
- Workstream B: inventory HTTP entrypoints, securely compose browser/session routes, token API and binary Git routes, and deliver real repo/issue/PR navigation.
- Workstream C: prepare repeatable native project CI, actual Git HTTP and real sshd test lab, and guarded performance/failure-injection matrix.
- Workstream D: verify native install, backup export and restore, mirror freshness, privilege checks and platform support.
- Workstream E: execute Cyber-Viking design usability, grayscale, scaling, keyboard and screen-reader criteria.
- Release promotion happens only when a full user journey, security review, portability and claims audit align with actual evidence.

## Failure cases and decision hazards

- A team may polish UI while server lacks routes. A route may return a demo page with no persisted writes. Both are incomplete vertical slices.
- Stale branch protection review/check results can permit wrong merge if mergeability is not revalidated at ref update.
- Pressure to advertise feature parity before backup and trust boundaries are proven risks user's intellectual work.

## Testable completion criteria

- Developer preview gate: account login, repo creation and stock-Git push plus issue/PR read over live server.
- Self-hosted beta gate: PR merge through live interface, security denials, native install and scratch restore.
- v1.0 gate: required S-393–S-416 proof, known skips named, final claims register, signed release, founder usability walk.

## Proof and provenance obligations

At the next implementation checkpoint record exact module paths, whether routes are mounted in the real server, actor/permission behavior, schema changes, actual host/toolchain, full test totals, all skips and an independently reproducible demo when needed. Update the claims register and project memory map only with evidence. Historical entries are not overwritten, and any missing capability remains NOT PROVEN.

## References

1. https://asvs.owasp.org/
2. https://docs.python.org/3/library/http.server.html
3. https://www.w3.org/TR/WCAG22/
