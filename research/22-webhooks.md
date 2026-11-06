# Samverk research 22 — Signed webhooks, queues, retries, and SSRF defense

**Research dossier, 2026-11-06.** Original technical synthesis of public material; engineering guidance, not proof of shipped functionality. Roadmap: **S-247–S-256**.

## What the technology requires

- A webhook target is a user-controlled URL that makes the Samverk server issue outbound HTTP requests. This is a classic server-side request forgery boundary.
- Receivers can be offline or slow. A timeout after sending is ambiguous: the remote may have processed the event even though Samverk did not receive its acknowledgment.
- Signatures authenticate payload integrity under a shared secret only if the receiver verifies the exact raw bytes and protects its secret.

## Recommended architecture

- Design a per-subscription outbox with event ID, delivery ID, attempt count, next attempt, response code and redacted error; use exponential backoff plus jitter and bounded expiry.
- HMAC-sign the exact request body, include signature version and timestamp, and use constant-time comparison when verifying test endpoint behavior.
- Restrict outbound destinations: canonicalize DNS/IP and block loopback, link-local, metadata endpoints, internal nets and redirects to forbidden destinations; recheck DNS resolution at connection time.
- Set strict connect/read timeouts, maximum response body and concurrency; no automatic forwarding of Git credentials, cookies or operator secrets.

## Risks, failure modes and honest limits

- DNS rebinding, 302 to private IP, slowloris receiver, queue floods, recycled event signatures, subscription edited during retry.
- An HTTP 200 delivery status is an acknowledged attempt, not proof the recipient performed business work.

## Acceptance tests and review questions

- Run local mock receivers that time out and return 5xx/429; verify retry count and idempotency identifiers.
- Attempt destination at 127.0.0.1, IPv6 loopback, link-local, RFC1918, redirect and DNS rebinding; all must be blocked by policy.

## Traceability requirements

Before declaring this study's roadmap slices finished, identify source modules, live HTTP/SSH route reachability, role and scope checks, data persistence, test commands, actual results and skips. Record accepted/rejected choices as engineering decisions. Update the memory map and claims register, never infer production readiness from a backend module alone. Study the referenced specifications at implementation time, because some evolve.

## Public references

1. https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
2. https://cheatsheetseries.owasp.org/cheatsheets/Webhook_Security_Guidelines_Cheat_Sheet.html
3. https://www.rfc-editor.org/rfc/rfc9110.html
