# Samverk research 41 — Accessible forge navigation and user-control findability

**Research dossier, 2026-11-06.** Clean-room synthesis from public protocols, standards and testable observations; guidance, **not a declaration of implementation**. Roadmap: **S-097–S-120, S-381–S-392, S-414**.

## Core facts and constraints

- WCAG 2.2 AA success criterion 2.5.8 defines at least 24×24 CSS pixels or defined exceptions/spacing for pointer targets; Samverk's **44×44 target law** is a deliberately stricter project requirement, not the WCAG 2.2 AA minimum.
- Accessible design is not a final color contrast pass: labels, focus order, keyboard operation, error recovery and readable hierarchy are architectural decisions.
- A user needs to find token creation, repository creation, permissions, SSH key setup and mirrors unaided. A beautiful but confusing UI fails the founding virtue.

## Samverk engineering direction

- Design one persistent navigation model grouped by user tasks: Dashboard, Repositories, Issues/PRs, Security & Keys, Settings and Administration (when authorized).
- Implement semantic headings, forms with explicit labels/errors, keyboard focus management, skip links, meaningful link text, and no keyboard trap inside file diff or modal.
- Keep all status words and icons meaningful with color removed; respect reduced motion and 125%-200% text scaling.
- Treat responsive mobile and tablet views as primary testing targets, not a squeezed desktop screenshot. A quiet high-contrast mode should be supported without sacrificing visual identity.

## Threats and tricky cases

- A code diff with 30k lines, sticky header covering skip target, hidden settings behind hover-only menu, keyboard focus lost after deleting item.
- Active neon/glow effects can obscure text; test with them off, in grayscale and at multiple zoom levels.

## Acceptance and experiment plan

- Run end-to-end task-finding usability tests with a fresh reader: mint/revoke token, create repo, add SSH key, configure mirror.
- Keyboard-only and real screen-reader walk through login, repo, issue, PR and settings; fix missing labels and focus traps.
- Automate target size and contrast checks; keep results separate from human validation.

## Review checklist

Record current source modules, whether features are routable from the real server, exact authorization points, schema/recovery implications, and a passing test transcript on named hardware. If a claim is not tested, label it **NOT PROVEN**. For every accepted change, update relevant roadmap gate, claims register and project memory map with new evidence; preserve historical keeper entries. Do not copy closed-source code or proprietary UI assets.

## Primary sources

1. https://www.w3.org/TR/WCAG22/
2. https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum
3. https://www.w3.org/WAI/WCAG22/Understanding/focus-visible
