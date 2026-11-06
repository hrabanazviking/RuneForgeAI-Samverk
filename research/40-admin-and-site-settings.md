# Samverk research 40 — Administrator findability, least privilege and safe operations

**Research dossier, 2026-11-06.** Clean-room synthesis from public protocols, standards and testable observations; guidance, **not a declaration of implementation**. Roadmap: **S-345–S-360, S-351–S-359**.

## Core facts and constraints

- The founding complaint motivating Samverk is discoverability: an owner who cannot find routine token, repository or backup controls does not have a usable forge.
- An administrator needs visibility into disk, database, queue health, migration level, security warnings and recent failures, not just a pile of toggles.
- Admin privilege is not unlimited authority to skip data integrity, audit or explicit confirmation for destructive operations.

## Samverk engineering direction

- Organize tasks by what a human wants to do: create token, invite user, manage repo, start mirror, view backup, inspect failures. Put plain-language labels on actual working controls.
- Use fresh sudo-mode reauthentication for keys, user deletion, sensitive config changes and key rotation. Separate super-admin rights from repository owner rights.
- Provide a dry-run and verified-export requirement before destructive whole-instance operations; clarify consequences and allow cancellation.
- Display precise health signals, last successful backup, queue lag, failed migrations and critical resource thresholds. No green status based solely on `/healthz`.

## Threats and tricky cases

- Misleading 'save' no-op, password reset leaves logged-in sessions, quotas unexpectedly block Git pushes, mistaken site shutdown, last administrator removed.
- Admin UI is vulnerable to cross-site requests and stored malicious descriptions; route all through shared CSRF, escaping and permission gates.

## Acceptance and experiment plan

- Run the founder's timed findability script from a fresh login without documentation; record each stumble and adjust navigation.
- Test failed storage/migration/worker states and verify admin sees actionable cause and recovery path.
- Attempt admin actions with repo writer, expired session and forged CSRF token; all must fail without side effects.

## Review checklist

Record current source modules, whether features are routable from the real server, exact authorization points, schema/recovery implications, and a passing test transcript on named hardware. If a claim is not tested, label it **NOT PROVEN**. For every accepted change, update relevant roadmap gate, claims register and project memory map with new evidence; preserve historical keeper entries. Do not copy closed-source code or proprietary UI assets.

## Primary sources

1. https://www.w3.org/TR/WCAG22/
2. https://asvs.owasp.org/
3. https://docs.python.org/3/library/http.server.html
