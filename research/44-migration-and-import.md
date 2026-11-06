# Samverk research 44 — GitHub-to-Samverk import with verifiable completeness and consent

**Research dossier, 2026-11-06.** Clean-room synthesis from public protocols, standards and testable observations; guidance, **not a declaration of implementation**. Roadmap: **S-329–S-344, S-236–S-256, S-403**.

## Core facts and constraints

- A bare `git clone --mirror` preserves supported Git refs and reachable objects but does not automatically bring over issues, PR conversations, review decisions, permissions, Actions history, discussions, releases or all LFS content.
- External APIs paginate and rate-limit, and some fields cannot be exported or imported with equivalent identity semantics. A sovereign importer must present its completeness report honestly.
- Importing private repositories involves credential and privacy decisions; a signed-in account should explicitly select source scopes rather than granting broad tokens by default.

## Samverk engineering direction

- Separate stages: source inventory, approval/classification, Git mirror, LFS, wiki, issues/labels/milestones, PR conversations, releases, users/maps, links and final verification.
- Use idempotent source IDs in a staging mapping table; repeated imports should resume and not duplicate issues or votes. Preserve original author attribution as imported metadata, not forged local authority.
- Store import progress and rollback plan; copy source URLs and export timestamps, rate-limit details and per-resource failure reason without secrets.
- Generate a manifest with object refs, LFS digests, issue/comment counts, skipped unsupported fields, source timestamp and explicit 'not imported' sections.

## Threats and tricky cases

- Source force-push mid-import, suspended account, renamed repo, deleted author, incompatible branch protection, webhook disabled during migration, private issue referencing public user.
- Imported 'verified' signature badge must be rechecked in Samverk rather than copied as a trusted boolean.

## Acceptance and experiment plan

- Import same fixture twice and compare stable counts, refs, source mappings and byte-level artifacts.
- Test interrupted pagination at page N then resume without duplicates; verify all limits and missing fields are clearly reported.
- Restore completed import to another isolated Samverk instance and run full clone and UI browse tests.

## Review checklist

Record current source modules, whether features are routable from the real server, exact authorization points, schema/recovery implications, and a passing test transcript on named hardware. If a claim is not tested, label it **NOT PROVEN**. For every accepted change, update relevant roadmap gate, claims register and project memory map with new evidence; preserve historical keeper entries. Do not copy closed-source code or proprietary UI assets.

## Primary sources

1. https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api
2. https://git-scm.com/docs/git-clone
3. https://git-scm.com/docs/git-bundle
