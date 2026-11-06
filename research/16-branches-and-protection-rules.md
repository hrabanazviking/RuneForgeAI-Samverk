# Samverk research 16 — Branch protection as a single push-and-merge policy engine

**Research dossier • 2026-11-06 • Engineering guidance, not a completion claim.** Original work based on public specifications and observable behavior, with no copied proprietary code or UI. Roadmap: **S-169–S-184, S-089, S-164**.

## What the protocols and user workflows require

- Branch rules decide whether a proposed ref transition is allowed, not merely whether a UI button should appear.
- Required checks, approvals, code-owner reviews, signed commits, linear history and bypass identities are independent requirements that must compose deterministically.
- Every bypass should be explicit, narrow and auditable; an administrator exemption accidentally left implicit defeats the meaning of branch protection.

## Architecture and implementation decisions to evaluate

- Write a pure policy evaluator that takes current repo policy, actor, old/new OID, commit metadata, review and check snapshots; return typed allowed/denied reasons.
- Call the same evaluator at Git receive-pack and merge service boundaries. Recheck immediately before atomic ref update because prior checks can go stale.
- Make ruleset inheritance and conflicts deterministic; when overlapping rules conflict, choose documented restrictive behavior rather than random row order.
- Expose why a push was denied in a safe protocol message and a linked admin-friendly audit event; do not disclose hidden branch names to outsiders.

## Failure modes and difficult cases

- Push update vs PR merge, direct tag push, force push, branch deletion, bypass rights revoked mid-operation, partially succeeded multi-ref push.
- External check statuses may be stale or spoofed; bind each status to an authorized poster and exact commit OID.

## Acceptance checks for development agents

- Table-drive every rule × role × transport with normal/force/delete/ref race cases.
- Require failed checks and missing approvals to block both UI merges and `git push`, when that rule applies.
- Prove authorized bypass writes an audit record and unauthorized bypass cannot be smuggled through an API token.

## Integration, evidence and scope

Document the exact modules and API/HTTP entry points touched, the permission decision, security boundary and failure handling. A green module-level test does not prove an end-to-end user-visible feature; test the assembled `samverk serve` process separately. Use explicit NOT PROVEN labels for unexercised SSH, browser, OS and recovery matrix cells. Record fresh commands and result counts. Keep the claims register and project memory map consistent with actual commits; retain history rather than rewriting earlier reports.

## Standards and research references

1. https://git-scm.com/docs/git-receive-pack
2. https://git-scm.com/docs/git-update-ref
3. https://slsa.dev/spec/v1.2/source-requirements
