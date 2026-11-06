# Samverk — Development Research and Implementation Playbooks

**Collection prepared:** 2026-11-06 · **Scope:** 18 original engineering guides plus the 46 numbered foundational studies under [`research/`](../../research/INDEX.md).

These guides connect the public standards and architecture studied in the numbered research shelf to the actual Samverk backend, Git transports, user interface and 416-slice roadmap. They are **design research and proposed acceptance work**. They are **not** test results, security certification, assertions of shipped behavior, or modifications to the canonical roadmap.

## Start here: the critical delivery chain

The November 6 source inspection found rich Python service code through **S-152**, while the runnable HTTP server remained primarily a root/health shell. **S-153** is the next numbered development slice. Work on merging and full HTTP/browser integration should proceed in coordinated vertical increments, not as competing rewrites.

1. [Current evidence and research method](00-evidence-state-and-research-method.md): distinguish implementation, focused tests, HTTP integration, E2E proof and release claims.
2. [Live HTTP integration](01-live-http-routing-and-composition-blueprint.md): mount existing services safely and differentiate cookie/browser CSRF from token-authenticated binary Git transport.
3. [Merge engine](05-pr-merge-engine-and-atomicity-plan.md): implement S-153 merge, S-154 squash and S-155 rebase with atomic ref transitions and recovery.
4. [Real-user acceptance](03-complete-user-journey-test-battery.md) and [stock Git laboratory](04-stock-git-http-ssh-lfs-interop-lab.md): prove a user can actually operate the forge with a real browser and Git client.
5. [Security boundaries](02-network-security-and-hosting-boundaries.md) and [authorization matrix](07-identity-and-authorization-live-matrix.md): do not ship an unverified network service.
6. [Native CI](08-project-ci-and-quality-gates.md), [worker budgets](09-worker-queues-retries-and-resource-budgets.md), [recovery](12-migration-mirroring-and-disaster-recovery-drills.md) and [native deployment](10-native-install-upgrade-and-platform-profiles.md): build reliable self-hosting before release claims.

## All 18 implementation guides

| Guide | Primary use |
|---|---|
| [00 · evidence state and research method](00-evidence-state-and-research-method.md) | Evidence tiers, source discipline and dated project state |
| [01 · live http routing and composition blueprint](01-live-http-routing-and-composition-blueprint.md) | HTTP route table, security guards and service composition |
| [02 · network security and hosting boundaries](02-network-security-and-hosting-boundaries.md) | HTTP ingress threat review and deployment boundaries |
| [03 · complete user journey test battery](03-complete-user-journey-test-battery.md) | End-to-end account → repo → issue → PR → merge matrix |
| [04 · stock git http ssh lfs interop lab](04-stock-git-http-ssh-lfs-interop-lab.md) | Stock Git, protocol v2, SSH daemon and Git LFS test lab |
| [05 · pr merge engine and atomicity plan](05-pr-merge-engine-and-atomicity-plan.md) | S-153–S-168 merge/ref transaction and conflicts |
| [06 · three store consistency and crash recovery](06-three-store-consistency-and-crash-recovery.md) | SQLite, Git, filesystem crash consistency and backups |
| [07 · identity and authorization live matrix](07-identity-and-authorization-live-matrix.md) | Sessions, PATs, SSH, deploy keys and private access |
| [08 · project ci and quality gates](08-project-ci-and-quality-gates.md) | CI for Samverk development, test evidence and skip accounting |
| [09 · worker queues retries and resource budgets](09-worker-queues-retries-and-resource-budgets.md) | Workers, queue lease, idempotency and overload |
| [10 · native install upgrade and platform profiles](10-native-install-upgrade-and-platform-profiles.md) | Native service install, upgrades and OS/CPU support |
| [11 · usability information architecture and cyber viking ui](11-usability-information-architecture-and-cyber-viking-ui.md) | Founder findability, UX, accessible Cyber-Viking UI |
| [12 · migration mirroring and disaster recovery drills](12-migration-mirroring-and-disaster-recovery-drills.md) | Repository census, GitHub import, mirror/restore proof |
| [13 · observability audit and honest release claims](13-observability-audit-and-honest-release-claims.md) | Telemetry, audit, proof scope and release claims |
| [14 · raspberry pi performance and memory budgets](14-raspberry-pi-performance-and-memory-budgets.md) | Pi performance, memory and filesystem pressure |
| [15 · mythic engineering agent handoff and proof protocol](15-mythic-engineering-agent-handoff-and-proof-protocol.md) | Agent brief → code → test → review → commit → handoff |
| [16 · supply chain signatures and release provenance](16-supply-chain-signatures-and-release-provenance.md) | Checksums, signatures, SLSA and dependency controls |
| [17 · risk driven priority graph and exit criteria](17-risk-driven-priority-graph-and-exit-criteria.md) | Critical dependency graph and maturity exit gates |

## Foundational research: all 46 study areas

The original [numbered research index](../../research/INDEX.md) maps 46 areas to clean-room studies, from Git pack protocols and key management to code review, audit, mirroring, Samtal integration, portability and Cyber-Viking design. **All 46 now contain Markdown text as of this date**: seven were previously populated; the remaining 39 were populated in this research campaign. A completed written study is **not** proof its corresponding feature has shipped.

The standard referenced in a study may evolve. Verify the authoritative source at implementation time. Useful anchors include [Git protocol v2](https://git-scm.com/docs/gitprotocol-v2), [OWASP ASVS 5.0](https://asvs.owasp.org/), [NIST SP 800-63B-4](https://csrc.nist.gov/pubs/sp/800/63/b/4/final), [WebAuthn Level 3](https://www.w3.org/TR/webauthn-3/), [SQLite backup](https://sqlite.org/backup.html), [WCAG 2.2](https://www.w3.org/TR/WCAG22/), and [SLSA 1.2](https://slsa.dev/spec/v1.2/).

## Agent research-to-implementation protocol

For each numbered slice:

1. Read the roadmap slice, matching numbered research file and relevant guides here.
2. Inspect actual source and tests on the latest branch before proposing implementation.
3. Write a decision record: requirements, threats, options, accepted design, migration, rollback and test plan.
4. Prefer existing audited services over parallel rewrites. Identify missing live HTTP routes explicitly.
5. Test a successful path **and** a denied/malformed/racing path. Use real Git, real SSH daemon, browser and OS matrix where claimed.
6. Run a counted suite on a named host, report every skip, and record untested work **NOT PROVEN**.
7. Append actual progress to `PROJECT_MEMORY_MAP.md`, synchronize `docs/CLAIMS_REGISTER.md` and README claims where evidence permits, and keep earlier history intact.

## Important reference boundaries

- [Canonical roadmap](../SAMVERK_MASSIVE_ROADMAP.md): the original 416 slices and cross-cutting integration priority overlay.
- [Claims register](../CLAIMS_REGISTER.md): which claims are scoped PROVEN or NOT PROVEN.
- [Dependency register](../DEPENDENCY_REGISTER.md): admitted runtime dependency and supply-chain policy.
- [Project memory map](../../PROJECT_MEMORY_MAP.md): chronological development events and completed-run evidence.
- [Project README](../../README.md): founding principles, dated engineering state and user-visible links.

**Clean-room and sovereignty law:** do not copy GitHub code, proprietary assets or interface design; no Docker requirement; standalone before Samtal bridge; never claim unrun tests or unproven OS/security gates.
