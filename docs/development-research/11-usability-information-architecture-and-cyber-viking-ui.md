# Findability, quiet information architecture and Cyber-Viking design discipline

**Samverk implementation research, 2026-11-06.** This document provides proposed technical policy and acceptance work, not evidence that a feature has shipped. Existing roadmap references: S-381–S-392; S-097–S-120; S-402. Maintain the clean-room rule and no-Docker decision.

## Established context

- Samverk was founded partly to eliminate the common self-hosted forge failure where its own owner cannot find token and admin controls.
- The design law requires a coherent Cyber-Viking visual identity, but function and navigability have priority over decorative runes.
- WCAG 2.2 AA target-size minimum uses 24 CSS pixels or defined spacing/exceptions; Samverk's 44-pixel target rule is intentionally stricter.

## Concrete engineering plan

- Draft navigation around user tasks: Home; Repositories; Issues and PRs; Search; Activity; Account Security/Tokens/SSH; Repository Settings; Admin People/Storage/Backups.
- Put Create repository, Mint token, Add SSH key and Configure mirror where an unaided person expects them, with explicit labels and next-step guidance.
- Design semantic tokens for surfaces, text, focus, danger, success, accent, glow and spacing. Every visual embellishment must improve hierarchy and survive grayscale and effects-off modes.
- Keep typography and icons legible at 125%–200% scaling. Use real headings, labels, focus order and keyboard operation. Never encode status in color alone.
- Test the interface on touch phones and tablets plus desktop browsers. Large source diffs must retain accessible navigation without 10,000 focus traps.

## Cases likely to break naive implementations

- Glow obscures keyboard focus; hidden hover-only destructive action; token page buried under several icons; invisible pending/failed check state.
- A beautiful screenshot with no functional server route is a design preview, not a delivered feature.
- Rune glyphs should be historically checked and not replace plain-language instructions.

## Counted acceptance evidence required

- Run timed unaided task-finding sessions for token, repository, SSH key, mirror and PR merge; record each wrong turn.
- Perform keyboard-only and screen-reader walkthrough, reduced-motion and grayscale checks with no color-only signals.
- Validate UI on a real running HTTP service and not just rendered mockup HTML.

## Handoff rule

For every accepted implementation, identify the module and actual server entry point, submit an unauthorized-action test, document schema or migration effects, and verify both success and refusal behavior through the live process where relevant. Record the full test count, the host, and every skip. Update PROJECT_MEMORY_MAP and CLAIMS_REGISTER only with real evidence; do not silently upgrade an untested capability to PROVEN.

## Primary references

1. https://www.w3.org/TR/WCAG22/
2. https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum
3. https://www.w3.org/WAI/WCAG22/Understanding/focus-visible
