# Samverk research 46 — Cyber-Viking design system with measurable usability and restraint

**Research dossier, 2026-11-06.** Clean-room synthesis from public protocols, standards and testable observations; guidance, **not a declaration of implementation**. Roadmap: **S-381–S-392, S-097–S-120**.

## Core facts and constraints

- The project defines a distinct modern Cyber-Viking design law: dark-surface hierarchy, controlled runic symbolism and contextual accents. Appearance must communicate structure, not obscure controls.
- Accessibility is not in conflict with aesthetic identity: clear contrast, focus, predictable navigation and motion restraint make the interface feel intentional.
- The founding design team names Hallveig (system), Rannveig (composition), Solveig (implementation), Ljósbera (light), Rúnhildr (type/runes) and Tove (accessibility veto); their offices are design governance roles, not substitute test results.

## Samverk engineering direction

- Build tokens for surfaces, text, focus, borders, states and accents; constrain accent budget and glow under the Lawbook rather than decorating every panel.
- Give navigation a calm hierarchy: first act in three seconds, optional detail disclosed progressively. Place 'New repository', 'Generate token', 'Add SSH key', 'Backup/mirror' where expected.
- Use runes only when verified for historical meaning and not as replacement letters for critical controls. Support theme-neutral accessible icon/text equivalents.
- Document dark/light or high-contrast variant, 44px project touch targets, real keyboard navigation, reduced-motion transitions and grayscale/effects-off behavior.

## Threats and tricky cases

- Status conveyed by red/green alone, low contrast purple-on-black, rune glyph substitute for 'delete', glow hiding focus ring, CPU-heavy animation on Raspberry Pi.
- A screenshot can look perfect while the actual site lacks working routes; require interaction and focus tests, not mockup-only approval.

## Acceptance and experiment plan

- Inspect primary UI at 125% and 200% scaling, grayscale and effects disabled, and in phone/tablet browser.
- Time task-finding scenarios and require plain text labels with icon clarity; Tove's gate cannot be bypassed by cosmetic sign-off.
- Collect screenshot/state fixtures under multiple themes but do not claim the UI complete until live routes pass.

## Review checklist

Record current source modules, whether features are routable from the real server, exact authorization points, schema/recovery implications, and a passing test transcript on named hardware. If a claim is not tested, label it **NOT PROVEN**. For every accepted change, update relevant roadmap gate, claims register and project memory map with new evidence; preserve historical keeper entries. Do not copy closed-source code or proprietary UI assets.

## Primary sources

1. https://www.w3.org/TR/WCAG22/
2. https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum
3. https://www.w3.org/WAI/WCAG22/Understanding/focus-visible
