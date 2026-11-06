# Samverk research 23 — Predictable REST resources, pagination and contract tests

**Research dossier, 2026-11-06.** Original technical synthesis of public material; engineering guidance, not proof of shipped functionality. Roadmap: **S-237–S-256**.

## What the technology requires

- HTTP method semantics, preconditions, caches and status codes are defined by RFC 9110; compatibility with GitHub's resource habits need not mean copying proprietary implementation.
- API pagination and conditional retrieval affect large repos, and a client may race with concurrent writes between pages.
- Scope must be checked on every endpoint. A future API cannot be a hidden route around web or Git transport permissions.

## Recommended architecture

- Publish a versioned route/resource table with request/response examples and structured error shape; keep public and private not-found cases safe.
- Use cursor pagination tied to stable ordering, cap page size and document duplicate/missing behavior under mutation; avoid unbounded OFFSET for giant collections.
- Support ETag/If-None-Match for immutable representations and If-Match for resource updates where feasible; use stable commit OIDs for blob content and separate validators for mutable metadata.
- Budget JSON body sizes and nesting, enforce content types and UTF-8 policy, and uniformly rate-limit credentials and IPs.

## Risks, failure modes and honest limits

- One page deleted between cursors, stale ETag, case-folded repo rename, wrong Content-Type, anonymous get of private path.

## Acceptance tests and review questions

- Generate contract tests from resource table; execute unauthorized/expired-token/large-page/error cases on live HTTP service.
- Try repeated conditional GET and concurrent PUT; verify 304/412 where specified and no lost update.

## Traceability requirements

Before declaring this study's roadmap slices finished, identify source modules, live HTTP/SSH route reachability, role and scope checks, data persistence, test commands, actual results and skips. Record accepted/rejected choices as engineering decisions. Update the memory map and claims register, never infer production readiness from a backend module alone. Study the referenced specifications at implementation time, because some evolve.

## Public references

1. https://www.rfc-editor.org/rfc/rfc9110.html
2. https://docs.github.com/en/rest/using-the-rest-api/getting-started-with-the-rest-api
3. https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html
