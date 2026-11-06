# Samverk research 30 — Forum-like discussion categories, accepted answers and moderation

**Research dossier • 2026-11-06 • Design recommendations / NOT PROVEN until tested.** This is a clean-room synthesis of public specifications and practices. Roadmap **S-282–S-292**.

## Technology and observed constraints

- Discussions are for open-ended knowledge exchange, whereas issues capture actionable work. Conflating both harms search and task closure.
- Category types (question, announcement, open discussion, poll) have different semantics, moderation and notification policies.
- Marking an answer is a reversible, attributable event, not a replacement for original comments or a silent edit.

## Recommended implementation approach

- Design categories with explicit allowed states and permissions, and preserve discussion origin upon conversion to issue.
- One conversation timeline stores replies, revisions and moderation actions; topic subscriptions share S-219+ notifications but have their own digest/mute controls.
- Keep announcement moderation and pinned items owner-controlled; polls require fraud-resistant rules that do not pretend to establish voter identity beyond account scope.
- Include mobile/keyboard-first composer and search filters; defer polls or rich badges if they do not meet a village-scale real need.

## Threats, edge cases and operational limits

- Multiple accepted answers, author deletes accepted post, same question converted twice, private org discussion exposed by public search.

## Acceptance checks

- Role-matrix test create/reply/mark-answer/moderate and ensure audit trail is stable.
- Convert discussion to issue twice concurrently and verify exactly one linked result.

## How to use this study

Before implementation, map each recommendation to current `samverk/` code and tests; identify new versus pre-existing functionality. Every public claim needs a testable scope, a real entry point, and a recorded host. A green unit test does not prove the browser application or real Git transport. Record accepted, deferred and rejected designs and keep `docs/CLAIMS_REGISTER.md` and `PROJECT_MEMORY_MAP.md` consistent. Any unverified security assertion remains NOT PROVEN.

## Primary public references

1. https://docs.github.com/en/discussions
2. https://www.w3.org/TR/WCAG22/
