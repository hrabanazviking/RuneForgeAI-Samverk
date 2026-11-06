# Samverk research 24 — GraphQL cost-benefit and defer-or-adopt decision

**Research dossier, 2026-11-06.** Original technical synthesis of public material; engineering guidance, not proof of shipped functionality. Roadmap: **S-237–S-256, S-403**.

## What the technology requires

- GraphQL reduces overfetching for complex relationship reads, but its schema, field-level authorization, query depth and cost governance are a long-lived maintenance commitment.
- Nested graph traversal can generate multiplicative queries; introspection and aliases complicate rate limits and abuse detection.
- The founding roadmap explicitly reserves GraphQL as a decision, not a mandatory copy of another forge's API.

## Recommended architecture

- Write a decision record comparing REST plus batch endpoints against GraphQL on three concrete clients: issue board, PR review page and organization administration.
- If adopted, make identity and permission checks per object and field; cap nesting depth, overall query cost, response bytes and execution time.
- Adopt cursor connections, stable IDs and typed errors with documented mutation idempotency; do not expose tables one-to-one as public schema.
- Prefer an intentional deferral when only one in-house consumer would use GraphQL and REST already meets measured needs.

## Risks, failure modes and honest limits

- Recursive fragments, alias bombing, unauthorized node lookup, batched mutations partially writing, overfetch of private relationship edges.

## Acceptance tests and review questions

- Benchmark representative queries against equivalent REST calls; record latency, query count and developer effort.
- Attempt deeply nested queries, huge alias counts and private node IDs; prove policy and budget boundaries.

## Traceability requirements

Before declaring this study's roadmap slices finished, identify source modules, live HTTP/SSH route reachability, role and scope checks, data persistence, test commands, actual results and skips. Record accepted/rejected choices as engineering decisions. Update the memory map and claims register, never infer production readiness from a backend module alone. Study the referenced specifications at implementation time, because some evolve.

## Public references

1. https://graphql.org/learn/
2. https://cheatsheetseries.owasp.org/cheatsheets/GraphQL_Cheat_Sheet.html
