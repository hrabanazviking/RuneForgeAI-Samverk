# Mythic Engineering coding-agent handoff and proof discipline

**Samverk implementation research | 2026-11-06.** Guidance for coding agents and project directors, not a declaration of shipping or certified behavior. Roadmap references: All slices; project memory map. Preserve all original 416 slices and clean-room/no-Docker laws.

## Context and engineering facts

- Samverk is built collaboratively through human architecture direction and specialized AI coding agents; transparent handoffs reduce duplicated work, contradictory plans and false confidence.
- The roadmap expresses planned work. The project memory map describes historical progress. The claims register states what may be said publicly. These cannot be substituted for one another.
- The repository's development history contains resource-contention interruptions; a tool returning partial logs must not be treated as successful full-suite evidence.

## Concrete development plan

- Before a slice, read README, relevant roadmap part, research XX study, implementation modules, tests, claims register and current memory map; inspect actual HEAD and working tree.
- Write a small task contract naming slice ID, user-visible behavior, source modules to reuse, threat boundaries, data migrations, test fixtures, resource budget and exact proof required.
- Build one vertical increment: first design and negative tests, then minimal implementation, then focused tests, affected-suites run, and full-suite replay only when host resources permit.
- Review for injection, IDOR, private resource leaks, data races, secret handling, migration safety and findability. Do not claim a screen exists because an HTML helper renders.
- At handoff, include changed files/commit SHA, test commands and complete results, unexplored matrix cells, rollback plan, owner decisions and next narrow task.
- Parallel agents may research different domains but must not write competing updates to same file/branch without explicit coordination; serialize expensive tests on constrained machines.

## Failure cases and decision hazards

- A coding agent may accidentally replicate a working store instead of mounting it behind HTTP; require cross-reference to existing modules before new code.
- One agent marks S-153 DONE because merge logic compiles while another discovers UI and permission gaps. Mark implemented vs integrated vs end-to-end separately.
- An unsafe automated edit can silently change AGPL license or no-Docker law; these are explicit invariant checks.

## Testable completion criteria

- Every slice has a machine-readable proof receipt and a human-readable handoff; rerun tests on exact committed SHA.
- Record negative security tests and one user-visible check for features that require UI.
- Verify chronology remains intact; append new evidence without rewriting older keeper entries.

## Proof and provenance obligations

At the next implementation checkpoint record exact module paths, whether routes are mounted in the real server, actor/permission behavior, schema changes, actual host/toolchain, full test totals, all skips and an independently reproducible demo when needed. Update the claims register and project memory map only with evidence. Historical entries are not overwritten, and any missing capability remains NOT PROVEN.

## References

1. https://git-scm.com/docs/git
2. https://asvs.owasp.org/
3. https://www.w3.org/TR/WCAG22/
