# Samverk research 39 — Samtal and Samverk as sovereign cooperating applications

**Research dossier, 2026-11-06.** Clean-room synthesis from public protocols, standards and testable observations; guidance, **not a declaration of implementation**. Roadmap: **S-361–S-380, S-045, S-329–S-344**.

## Core facts and constraints

- A self-hosted forge and a conversation system represent distinct authorization and data lifecycles. An integration must not collapse accounts, permissions, backup ownership or audit trails.
- Identity linking can be mutual and revocable while each service remains runnable alone. Transport Git authentication must not silently become a Samtal chat session.
- Embedding UI in a longhouse conversation is a presentation and deep-link choice; it is not authority to access all repositories or all messages.

## Samverk engineering direction

- Document both standalone API contracts before coupling: account link/unlink, linked principal proofs, repo references, event delivery and export boundaries.
- Use short-lived, audience-bound signed assertions with replay prevention and explicit user consent for linking. Store mapping records under each application's own authority.
- Build an outbound event bridge with idempotent delivery and privacy-aware payloads; Samtal receives only events explicitly authorized and filtered by repo/chat membership.
- Preserve direct Samverk login, Git SSH/HTTP and admin recovery when Samtal is offline. Make integration optional and disabled by default.

## Threats and tricky cases

- Samtal session revoked but Samverk account active, same username belonging to different users, chat member sees private repo link, webhook retry duplicated message.
- Two apps disagree on user deletion or permission revocation; avoid automatic destructive cascade without documented owner action.

## Acceptance and experiment plan

- Run both apps independently; assert every Samverk function works with Samtal disabled.
- Link/unlink two accounts with signed proof, test replay and wrong-audience refusal, and verify private events never leak into public chat.
- Kill Samtal mid-push and restore later; no Git data or audit event is lost.

## Review checklist

Record current source modules, whether features are routable from the real server, exact authorization points, schema/recovery implications, and a passing test transcript on named hardware. If a claim is not tested, label it **NOT PROVEN**. For every accepted change, update relevant roadmap gate, claims register and project memory map with new evidence; preserve historical keeper entries. Do not copy closed-source code or proprietary UI assets.

## Primary sources

1. https://www.rfc-editor.org/rfc/rfc7519
2. https://www.rfc-editor.org/rfc/rfc9110.html
3. https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
