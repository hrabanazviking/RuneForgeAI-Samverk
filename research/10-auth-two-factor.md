# Samverk research 10 — Multi-factor login, WebAuthn/passkeys, and account recovery

**Research dossier • 2026-11-06 • Engineering guidance, not a completion claim.** Original work based on public specifications and observable behavior, with no copied proprietary code or UI. Roadmap: **S-035–S-039, S-020, S-043**.

## What the protocols and user workflows require

- NIST SP 800-63B-4 superseded the older 800-63B guidance in July 2025; use current authenticator requirements rather than archived defaults.
- W3C WebAuthn Level 3 became a Recommendation on 25 August 2026. RP ID, origin binding, challenge freshness and user verification are security-critical.
- TOTP adds defense in depth but does not provide the phishing resistance of a properly bound public-key authenticator. Recovery codes are exceptional credentials that require one-time use and safe custody.

## Architecture and implementation decisions to evaluate

- Create a single inventory of authenticators per account with enrolled/revoked times and readable names; enforce fresh reauthentication for enrollment, removal and backup code regeneration.
- Require challenge type, TTL, RP ID and expected origin verification on the server, plus signature and credential binding checks. Handle synced passkey counters carefully because non-monotonic counters can be legitimate.
- The existing `samverk/passkeys.py` contains substantial handwritten cryptographic code; require independent protocol/test-vector review and negative tests rather than treating local unit tests as cryptographic certification.
- Keep at least two recoverable methods available to owners before enforcing mandatory 2FA; define an auditable, deliberate recovery policy that does not offer a silent admin backdoor.

## Failure modes and difficult cases

- Cross-origin challenge, duplicate enrollment, replay, lost device, drifted TOTP clock, recovery code reused under concurrency.
- Browsers and platform authenticators differ; don't equate a simulated WebAuthn signature with a real-browser ceremony.

## Acceptance checks for development agents

- Run real-browser enrollment/login with at least two authenticator implementations including one synced passkey when available; verify origin mismatch refused.
- Revoke a credential mid-session and test future authentication denied; regeneration invalidates prior recovery codes.
- Threat-model owner lockout; test a recovery drill on an isolated instance without exposing account secrets.

## Integration, evidence and scope

Document the exact modules and API/HTTP entry points touched, the permission decision, security boundary and failure handling. A green module-level test does not prove an end-to-end user-visible feature; test the assembled `samverk serve` process separately. Use explicit NOT PROVEN labels for unexercised SSH, browser, OS and recovery matrix cells. Record fresh commands and result counts. Keep the claims register and project memory map consistent with actual commits; retain history rather than rewriting earlier reports.

## Standards and research references

1. https://csrc.nist.gov/pubs/sp/800/63/b/4/final
2. https://www.w3.org/TR/webauthn-3/
3. https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html
