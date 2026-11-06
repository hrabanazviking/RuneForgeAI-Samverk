# Samverk research 11 — Unified authorization and private-repository non-disclosure

**Research dossier • 2026-11-06 • Engineering guidance, not a completion claim.** Original work based on public specifications and observable behavior, with no copied proprietary code or UI. Roadmap: **S-054, S-081–S-089, S-169–S-184, S-204**.

## What the protocols and user workflows require

- A version-control forge has several trust boundaries: repository metadata, Git object/ref reads, Git writes, API calls, browser forms and automation tokens. A role label by itself is insufficient.
- Read access does not imply write, and write does not imply bypassing branch protection. Review dismissal and merge rights need explicit decisions.
- Private repository existence must not leak through distinct errors, timing-unstable lookups, search result counts, LFS error bodies, or reaction/mention endpoints.

## Architecture and implementation decisions to evaluate

- Define one policy decision contract: (principal, action, resource, context) → allow/deny with internal reason; map private-repo denial to a uniform public response.
- Evaluate user status, organization/team grants, repository grants, token scopes, deploy-key capabilities, protected branch rules and sudo-mode freshness where relevant.
- Record authorization decisions in a matrix before wiring them into routes: anonymous/reader/writer/admin/owner, public/private, browser/token/SSH, normal/protected branch.
- Keep denial messages comprehensible for authorized users while hiding private resource existence from strangers. Recheck at execution time, not just at button-render time.

## Failure modes and difficult cases

- A PR author who is not a repository writer, fork maintainer permission, token with narrower scope than account, cross-team membership revocation, race against repo transfer.
- UI hiding alone is never authorization; browser routes and Git receive-pack must enforce the same rules.

## Acceptance checks for development agents

- Generate role × resource × operation matrix tests; run against actual HTTP and Git transports, not only direct store calls.
- Use IDOR attempts, stale grants, org removal and private repo name guesses to check non-disclosure.
- Prove actor cannot merge/review/dismiss/scan/mirror across unauthorized repositories.

## Integration, evidence and scope

Document the exact modules and API/HTTP entry points touched, the permission decision, security boundary and failure handling. A green module-level test does not prove an end-to-end user-visible feature; test the assembled `samverk serve` process separately. Use explicit NOT PROVEN labels for unexercised SSH, browser, OS and recovery matrix cells. Record fresh commands and result counts. Keep the claims register and project memory map consistent with actual commits; retain history rather than rewriting earlier reports.

## Standards and research references

1. https://owasp.org/www-project-application-security-verification-standard/
2. https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
3. https://slsa.dev/spec/v1.2/source-requirements
