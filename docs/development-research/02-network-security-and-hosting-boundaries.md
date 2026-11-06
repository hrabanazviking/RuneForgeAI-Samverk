# Network exposure, HTTP hardening, and trust-boundary research

**Important:** Python's own `http.server` documentation explicitly cautions that it is **not recommended for production**; it implements only basic security checks. Samverk's current use of `ThreadingHTTPServer` therefore needs a threat-driven ingress review before anyone exposes it to the internet.

## Trust zones

1. **Untrusted internet:** clients control paths, headers, request framing and body timing.
2. **Front proxy/TLS:** optional native reverse proxy handles certificates and some limits; its existence is not proof application routes are secure.
3. **Samverk HTTP server:** the authoritative parsing, identity, authorization, CSRF and content-security boundary.
4. **Git subprocesses/SSH daemon:** protocol-specific identities, allowed commands, resource limits and child lifecycle.
5. **SQLite, Git bare repos and LFS:** assets must not be cross-visible by URL, path tricks or backup interface.
6. **Outbound mirror/webhook workers:** SSRF and credential leakage threat boundary, distinct from inbound HTTP.

## Hardening questions that require explicit answers

- Which front-end parses chunked encoding? Is disagreement in Content-Length/Transfer-Encoding rejected? Does proxy normalize or forward request target unchanged?
- What header size, body size, request rate, keepalive lifetime, slow-client timeout and simultaneous child-process budget are enforced?
- Are HOST and forwarded-proxy headers accepted only from an explicit trusted proxy and allowed hosts list? Are origin checks meaningful for session routes?
- Does a private repository produce indistinguishable visible errors for unauthenticated versus missing names?
- Does redirect behavior leak credential or path information to third-party origins?
- Is TLS mandatory for non-loopback bind, and how are HSTS, secure cookies, CSP and referrer policy deployed?
- Can exception details, subprocess stderr, pack bytes, tokens, credentials or private file contents enter logs or error templates?

## Server deployment options to decide, not assume

**Option A:** Samverk retains stdlib server bound to loopback behind a hardened reverse proxy, with an explicitly supported production security envelope. **Option B:** introduce a small audited server adapter for HTTP framing while keeping stdlib-first application services. **Option C:** restrict current server to local development until ingress review closes. Record performance, dependencies, security evidence and portability consequences. No Docker is needed for any option.

Do not silently claim that TLS termination fixes application vulnerabilities. HTTP routing, authorization, content limits and body parsing still belong to the application.

## Input-surface attack table

| Surface | Abuse | Required defense | Test |
|---|---|---|---|
| Session form | CSRF/session fixation | cookie session binding, CSRF, rotation | forged mutation yields zero writes |
| Git receive | unauthorized ref update | transport auth + receive gate + CAS | unauthorized push never changes ref |
| Uploaded files/LFS | oversized/malicious bytes | bounded stream, hash, quarantine | malformed/partial upload rejected |
| Webhooks | SSRF/DNS rebinding | IP/URL checks, no private egress | blocked loopback/link-local targets |
| Markdown | stored XSS | safe renderer/CSP | payload inert in browser |
| File paths | directory traversal | canonical path resolver | all escapes refused |
| Workers | resource exhaustion | concurrency, CPU/size/time budget | load test remains bounded |

## Required release gates

Run an adversarial HTTP test suite with raw socket framing and simulated proxy configurations. Include slow-header and slow-body clients, malformed methods, conflicting lengths, path encoding and concurrent streaming disconnect. On a private test network, verify that an ordinary unauthenticated remote cannot list accounts/repos/keys, allocate unbounded resources or produce useful stack traces.

Document threat acceptance and remaining limits in `docs/CLAIMS_REGISTER.md`. Have security review of custom passkey cryptography, network code and authentication before public exposure. Security unit tests are necessary but not sufficient.

## Primary sources

- https://docs.python.org/3/library/http.server.html
- https://asvs.owasp.org/
- https://www.rfc-editor.org/rfc/rfc9110.html
- https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html
- https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
