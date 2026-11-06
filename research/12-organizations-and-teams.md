# Samverk research 12 — Organizations, team inheritance, invitations, and last-owner safety

**Research dossier • 2026-11-06 • Engineering guidance, not a completion claim.** Original work based on public specifications and observable behavior, with no copied proprietary code or UI. Roadmap: **S-185–S-204, S-054**.

## What the protocols and user workflows require

- Organizations are collections of principals, repositories and policy decisions, not simply display folders. Nested team grants and outside collaborators introduce distinct inheritance paths.
- An invitation is pending authority, not active membership; tokenized invite links need expiry, revocation, target identity and safe audit semantics.
- Team authorization becomes effective on membership change, not at some later login. Last-owner protection is a safety invariant, not a UI hint.

## Architecture and implementation decisions to evaluate

- Model organizations, direct memberships, team membership, parent inheritance and per-repository roles as separate records with explicit provenance.
- Choose a deterministic 'most specific override' or 'maximum grant' rule and document it before coding. Avoid accidental admin privilege inheritance from a child team.
- Require confirmation and audit for team deletion, owner transfer, invitation acceptance and organization deletion; block removing last active owner until succession exists.
- Keep organizational visibility, repository visibility and user profiles independently controlled so private membership is not inferred from public listings.

## Failure modes and difficult cases

- Nested-team cycle, organization renamed mid-invite, suspended user remaining in a team, same user direct+inherited grants, outside collaborator losing access.
- Private org name enumeration and invitation-token leakage through referrer or email are concrete risks.

## Acceptance checks for development agents

- Construct graph fixture with nested teams, outside collaborators and conflicting grants; compare policy evaluator output to a documented matrix.
- Simulate last-owner removal and organization transfer race; both operations must be atomic or refused.
- Revoke team membership and confirm Git, API and browser access all disappear promptly.

## Integration, evidence and scope

Document the exact modules and API/HTTP entry points touched, the permission decision, security boundary and failure handling. A green module-level test does not prove an end-to-end user-visible feature; test the assembled `samverk serve` process separately. Use explicit NOT PROVEN labels for unexercised SSH, browser, OS and recovery matrix cells. Record fresh commands and result counts. Keep the claims register and project memory map consistent with actual commits; retain history rather than rewriting earlier reports.

## Standards and research references

1. https://docs.github.com/en/organizations/organizing-members-into-teams/about-teams
2. https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
