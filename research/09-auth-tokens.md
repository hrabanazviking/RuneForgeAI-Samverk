# Samverk research 09 — Personal access tokens, fine-grained grants, revocation

**Research dossier • 2026-11-06 • Engineering guidance, not a completion claim.** Original work based on public specifications and observable behavior, with no copied proprietary code or UI. Roadmap: **S-032–S-034, S-081–S-083, S-239**.

## What the protocols and user workflows require

- A PAT is a bearer credential, not a browser session. Its scope, resource set, principal state and expiry must all be checked on every operation, even when a token hash matches.
- Classic broad-scope tokens and fine-grained repository-specific tokens are different usability/security tradeoffs. The operator should see scope and expiry before minting either.
- Token bytes must be drawn from a cryptographically strong RNG, shown once and stored only as a one-way verifier. Short display prefixes aid identification but are not authentication.

## Architecture and implementation decisions to evaluate

- Keep token authorization in one policy seam used by HTTP Git, APIs and future integrations. Use least-privilege intersection: actor capability ∩ resource grant ∩ token scopes ∩ branch rules.
- Record token hash and safe identifier separately; rotate or revoke without invalidating unrelated credentials. Provide searchable list, creation timestamp, last-used and an unmistakable revoke affordance.
- Treat token values as secrets in request URLs, errors, logs, referrers and CLI traces; prefer authorization headers. Avoid silent default of indefinite expiry or all repositories.
- Document the deliberate difference between account password fallback and token-only operations; avoid treating an API token as permission to bypass web CSRF rules for browser cookie sessions.

## Failure modes and difficult cases

- Expired token during running Git push; revoked token in in-memory resolver; private repo appears differently to insufficiently scoped token; token prefix collision.
- An app/installation token is not a PAT; do not invent that lifecycle before Part XII/identity models specify the trust boundary.

## Acceptance checks for development agents

- Create read-only token and verify write denied; create one-repo write token and verify cross-repo read/write denied.
- Attempt token replay after revoke, account suspension and scope reduction; ensure no cached grant survives.
- Assert token strings never appear in SQLite tables, response bodies, URLs or captured server logs.

## Integration, evidence and scope

Document the exact modules and API/HTTP entry points touched, the permission decision, security boundary and failure handling. A green module-level test does not prove an end-to-end user-visible feature; test the assembled `samverk serve` process separately. Use explicit NOT PROVEN labels for unexercised SSH, browser, OS and recovery matrix cells. Record fresh commands and result counts. Keep the claims register and project memory map consistent with actual commits; retain history rather than rewriting earlier reports.

## Standards and research references

1. https://csrc.nist.gov/pubs/sp/800/63/b/4/final
2. https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html
3. https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
