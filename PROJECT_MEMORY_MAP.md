# Samverk — Project Memory Map

*The living map of this project, per the Forge Protocol: updated in the
same session as any work it records. If it is not written here, it did
not happen.*

## What this is

**Samverk** — our own clean-room, open-source version-control application.
An extremely robust, highly secure equivalent of GitHub's feature set,
studied from public behaviour and documentation, copying no code, assets,
or proprietary design. Standalone-first; integrable into Samtal as its
code-and-file-sharing heart; bearer of the standing duty to mirror
Volmarr's original repos onto his own machines.

- Repo: `hrabanazviking/RuneForgeAI-Samverk` (public)
- Licence: AGPL-3.0 (placed by Volmarr at the founding; never alter)
- Name: chosen by Volmarr 2026-10-29 from the Skald's five candidates
  (*Samverk* = the together-work; siblings: Samtal the together-talk,
  Samkoma the together-gathering)

## Founding decisions (2026-10-29)

- **Commissioned by Volmarr** in a voice call after Forgejo — installed on
  purplelongship, reset after a lost password — proved unusable to its
  owner (everyday controls unfindable). Samverk's founding virtues answer
  that failure: user-friendliness is law; security is the spine;
  sovereignty (native installs, **no Docker ever**); standard git;
  standalone first, Samtal seam second.
- **Clean-room rule:** features and behaviour are studied; no GitHub code,
  assets, or proprietary UI are copied. Stated in the roadmap preamble
  and `research/INDEX.md`, binding on every slice and study.
- **Architecture stance:** Python, stdlib-first, Samtal-pattern (SQLite
  state, one program family); git plumbing does git's work; three stores
  (SQLite / filesystem / git) under one event store.
- **Cross-platform law** (Volmarr, 2026-10-29, founding): Samverk is
  cross-platform completely — server on Linux, Windows, macOS; x86-64
  and ARM down to Raspberry Pi-class hardware; UI reachable from any
  modern browser/device. Roadmap virtue 6, Part I commitment, and
  Part XXII (S-405–S-416) carries the proof: a matrix cell is PROVEN
  only when its battery ran there, NOT PROVEN until then.
- **Design law** (Volmarr, 2026-10-29, founding): Samverk must look
  *really nice* in his modern Cyber-Viking design language. Its face is
  designed under the Cyber-Viking Visual Design Lawbook, with the
  design warband seated in roadmap Part XX by office — Hallveig
  (design-system architecture), Rannveig (composition), Solveig
  (design-to-code contracts), Ljósbera (colour/light), Rúnhildr
  (type/runes), Tove (accessibility; holds the Book XIV ship-gate
  veto). Ship gate bound as acceptance: grayscale coherence, 125–200%
  scaling, effects-off coherence, no colour-only status.
- **Roadmap:** `docs/SAMVERK_MASSIVE_ROADMAP.md` — **416 slices, 22
  parts**, slice sequence machine-verified continuous (S-001–S-416).
- **Research corpus:** `research/` — 46 empty study files +
  `INDEX.md` carrying each study question (Volmarr's exact founding ask:
  empty files first; words land as studies are done).
- **Standing exclusions:** no Docker; no federation; no hosted-service
  ambitions; no AI features that invent facts.

## Current state

- **Phase: Part IV next** (Part I gate passed 2026-10-30;
  Part II gate S-048 passed 2026-10-30 at 368/368; Part III
  gate S-076 passed 2026-10-30 at 510/510).
  Campaign branch: `yrsa/samverk-part1` (local banking continues
  on the same branch until a Part II branch is struck).
- **Part I research complete (2026-10-29):** studies 31 (threat
  model), 35 (audit log), 42 (data model & storage), 07 (passwords &
  sessions) written and committed.
- **S-001 DONE (2026-10-29)** — threat model ratified: threat register
  T-01…T-20, trust boundaries TB1…TB8, honest limits §6 of study 31.
- **S-002 DONE (2026-10-29)** — project skeleton: `samverk/` package
  (config loading, platform seam, `samverk serve`), `pyproject.toml`
  (stdlib-only), acceptance battery `tests/test_skeleton.py`:
  **10 passed / 0 failed** on Linux x86-64 (this VM), including the
  literal acceptance — a fresh `python -m samverk serve` process
  answering `/healthz`. Platform cells beyond this machine (Pi,
  Windows, macOS) are **NOT PROVEN** — Part XXII owns their proof;
  the skeleton's platform touchpoints exist only behind
  `samverk/platform_seam.py`, mechanically checked by test.
- **S-003 DONE (2026-10-29)** — secrets law: `samverk/secrets.py`
  (env or mode-600 file only, fail-closed on loose permissions,
  values never repr'd), `samverk/db.py` connection factory (WAL +
  synchronous=FULL + foreign_keys=ON + busy_timeout 5000, numbered
  transactional migrations), battery `tests/test_secrets.py`:
  **9 passed / 0 failed**, including the literal acceptance — a
  seeded DB (with a `secret:NAME` reference row) greps clean of both
  file- and env-sourced secret values. Cumulative battery: 19/19.
- **S-004 DONE (2026-10-29)** — password hashing: `samverk/passwords.py`
  — scrypt (stdlib `hashlib`, n=32768/r=8/p=1, ~32 MiB) with per-user
  128-bit salts, self-describing stored format, legacy pbkdf2-sha256
  verify-only rows, upgrade-on-login via `verify_and_upgrade`.
  Battery `tests/test_passwords.py`: **9 passed / 0 failed** —
  known-answer vectors for both algorithms, wrong-password and
  malformed-row rejection, timing floor proving the work factor,
  upgrade path end-to-end. (One test-authoring slip found and fixed
  during the run: a hand-typed base64 salt in the KAT strings; the
  KDF digests were verified byte-exact against fresh computation.)
  Cumulative battery: 28/28.
- **S-005 DONE (2026-10-29)** — `samverk/throttle.py`:
  `constant_time_equal` (the single comparison seam for secrets;
  `passwords.py` refactored onto it) and `LoginThrottle` (per-account
  exponential backoff: 3 free failures, then 2s doubling to a 300s
  cap; delays, never locks). Battery `tests/test_throttle.py`:
  **7 passed / 0 failed** — trip after N failures, release after
  backoff, growth + cap, success-clears, per-account independence.
  Cumulative battery: 35/35.
- **S-006 DONE (2026-10-29)** — session tokens: `samverk/sessions.py`
  (schema migration 2) — 256-bit CSPRNG tokens, only SHA-256 hashes
  stored, absolute (30 d) + idle (7 d) expiry, tombstone revocation
  incl. `revoke_all`, commit-before-answer on creation. Battery
  `tests/test_sessions.py`: **9 passed / 0 failed**, including the
  literal acceptance — values stolen from a seeded DB presented as
  tokens are refused, and the raw token appears nowhere in the DB
  file. (The S-003 migration test was updated to assert against the
  latest migration number rather than a hard-coded 1 — intent
  preserved.) Cumulative battery: 44/44.
- **S-007 DONE (2026-10-29)** — audit log core: `samverk/audit.py`
  (schema migration 3) — append-only hash-chained table (canonical
  serialisation fixed in code, genesis-anchored), serialised appends
  under lock + transaction, `verify_chain` verifier, and the
  `samverk audit verify` operator command. Battery
  `tests/test_audit.py`: **6 passed / 0 failed** — clean chain
  verifies, a tampered row is detected at its seq, a deleted row is
  detected, chain linkage/genesis checked, no update/delete API,
  CLI verify exits 0 clean / 1 broken. Cumulative battery: 50/50.
- **S-008 DONE (2026-10-29)** — audit taxonomy v1:
  `docs/AUDIT_TAXONOMY.md` + `samverk/taxonomy.py` — 37 frozen event
  names (15 auth, 13 repo, 9 admin); `AuditLog.append` refuses
  unknown names, so no call site can invent events. Battery
  `tests/test_taxonomy.py`: **6 passed / 0 failed** — doc and code
  name exactly the same set, every event emittable, unknown names
  refused and enter nothing. Cumulative battery: **56/56**.
- **S-009 DONE (2026-10-30)** — HTTP security baseline:
  `samverk/http_security.py` — session cookies (`HttpOnly` always,
  `Secure` when the operator declares HTTPS via the new
  `secure_cookies` config flag, `SameSite=Lax`, `Path=/`, no
  `Domain`, plain `session` name, header-injection values refused)
  and CSRF synchroniser tokens (HMAC-SHA256 keyed by the session
  token itself: unforgeable without the session, reveals nothing
  about it, stores nothing, rotates with the session; validation
  via the S-005 constant-time seam, fails closed on missing /
  foreign / tampered tokens). The server enforces the gate *before
  routing* every state-changing method, so later routes inherit it
  by construction. Battery `tests/test_http_security.py`:
  **17 passed / 0 failed**, including the literal acceptance —
  forged cross-site POSTs (no token, foreign token, no session)
  refused 403 over real HTTP, legitimate header- and form-token
  POSTs pass the gate. Cumulative battery: **73/73**.
- **S-010 DONE (2026-10-30)** — output-escaping standard:
  `samverk/escaping.py` is the one seam (mechanically enforced like
  the platform seam: no other module may escape directly) —
  `escape_html_text` for content, `escape_html_attr` for quoted
  attributes, `safe_url` as the href/src sanitiser (http/https/
  mailto + instance-relative only; `javascript:`/`data:`/obfuscated
  and protocol-relative URLs refused; the check also runs on the
  entity-decoded form — a battery-found bypass, `&#106;avascript:`,
  fixed in-slice). No JS-string escaper by design (no inline-script
  interpolation; S-016's CSP will forbid them). Battery
  `tests/test_escaping.py`: **12 passed / 0 failed**, including the
  stored-XSS payload battery rendered through a profile snippet.
  Cumulative battery: **85/85**.
- **S-011 DONE (2026-10-30)** — rate limiting:
  `samverk/rate_limit.py` — thread-safe token buckets (burst to
  capacity, then the refill rate; refusals carry a truthful
  `Retry-After`) in a keyed `RateLimiter` deciding per-IP and
  per-account together: a request is charged to both buckets or
  neither, so one dimension's refusal never drains the other, and
  an account hopping IPs still meets its own bucket. Distinct
  from S-005's login-failure backoff by design (different layers
  of the same door). Fully-refilled idle buckets are pruned.
  Battery `tests/test_rate_limit.py`: **11 passed / 0 failed**,
  including the burst test and a 20-thread race granting exactly
  capacity. Cumulative battery: **96/96**.
- **S-012 DONE (2026-10-30)** — upload handling law:
  `samverk/uploads.py` — size cap first, then content sniffing
  beats declared type (magic-number / strict-text sniff; a
  concrete declared type that disagrees with the sniff is a
  disguise and is refused; generic `application/octet-stream`
  defers to the sniff), then quarantine: accepted bytes land
  content-addressed (SHA-256 + sniffed-type extension, mode 600)
  in `<data_root>/quarantine/`, the uploader's filename never
  forms a path, rejected uploads write nothing. SVG is refused
  by the default policy until a sanitiser can vouch for it.
  Battery `tests/test_uploads.py`: **10 passed / 0 failed**,
  including the literal acceptance — script/executable/HTML
  payloads declaring themselves `image/png` all rejected.
  Cumulative battery: **106/106**.
- **S-013 DONE (2026-10-30)** — repository path resolution:
  `samverk/repo_paths.py` — the one mapping from names to disk
  paths (`<data_root>/repos/<owner>/<repo>.git`). Two defences:
  a strict name law (allowlist shape, no `..`/separators/controls,
  no trailing dot, Windows device names refused on every OS,
  a single trailing `.git` canonicalised away) and a containment
  law (the candidate is fully resolved and must land strictly
  inside the resolved repos root, so a planted symlink — owner
  dir or repo path — pointing outside is refused at resolve
  time, on every call, never cached). Battery
  `tests/test_repo_paths.py`: **10 passed / 0 failed**,
  including the literal acceptance — the `..`/symlink escape
  battery. Cumulative battery: **116/116**.
- **S-014 DONE (2026-10-30)** — subprocess discipline:
  `samverk/proc.py` — git (the only allowlisted program) is run
  with no shell, ever; argv[0] is resolved from the logical name
  `git` via the module's own allowlist, never from user input;
  the first argument must be an allowlisted subcommand
  (`GIT_SUBCOMMANDS`, extended only here, with reasons), so the
  global-option position (`-c`, `--git-dir`, …) is unreachable;
  dangerous redirect flags are refused in any position; the
  repository is a trusted parameter (`run_git_in`, path from
  S-013) inserted as `--git-dir` by the module itself;
  `GIT_DIR`/`GIT_CONFIG_*` and kin are stripped from the
  inherited environment and `GIT_TERMINAL_PROMPT=0`; every spawn
  carries a mandatory timeout. Battery `tests/test_proc.py`:
  **8 passed / 0 failed**, including the literal acceptance —
  shell-metacharacter injections arrive as inert single argv
  entries and create nothing, and real git work (init /
  hash-object / cat-file) flows through the law. (One design
  flaw found by the battery and fixed in-slice: `rev-parse
  --git-dir` is a read-only query, not a redirect — the bare
  query token is now allowed for rev-parse alone; every
  `--git-dir=<path>` form stays refused everywhere.)
  Cumulative battery: **124/124**.
- **S-015 DONE (2026-10-30)** — TLS and secure defaults:
  `samverk/tls_policy.py` + config fields (`tls_cert_file`,
  `tls_key_file`, `allow_plaintext_http`; file + env). The bind
  law is enforced in `serve()` before anything listens:
  loopback is literal (`localhost`, 127.0.0.0/8, ::1 — wildcards
  and DNS names are *not* loopback, and no DNS is consulted);
  non-loopback plaintext is **refused**, not warned; TLS
  configured with both files takes the `tls` posture (socket
  wrapped in `serve`, TLS ≥ 1.2, and S-009's Secure-cookie flag
  becomes a fact of the bind); exactly one TLS file is refused
  as half-configured in every posture; the operator override
  only exists when audit-logged — `enforce_bind_policy` raises
  `override_requires_audit` without an `AuditLog`, and with one
  it writes `admin.plaintext_http_override` before returning.
  Battery `tests/test_tls_policy.py`: **9 passed / 0 failed**,
  including the literal acceptance — refusal outside loopback,
  and the override landing exactly one verifiable audit row.
  Cumulative battery: **133/133**.
- **S-016 DONE (2026-10-30)** — content security policy:
  `samverk/csp.py` — one canonical policy (`default-src 'self'`
  with every fetch directive spelled out, `object-src 'none'`,
  `frame-ancestors 'none'`, `base-uri`/`form-action 'self'`,
  and no `unsafe-inline`/`unsafe-eval` anywhere — the browser
  half of S-010's no-inline-scripts promise), sent by the
  server's single send path so no route can forget it. The
  acceptance lifecycle is a config switch (`csp_mode`,
  file + env): `report-only` sends the *identical* policy value
  under `Content-Security-Policy-Report-Only`, `enforce`
  (default) under `Content-Security-Policy`; an unknown mode
  raises at startup rather than silently shipping no CSP.
  Battery `tests/test_csp.py`: **5 passed / 0 failed**,
  including real-HTTP checks that every core response
  (health, root, 404, and the CSRF gate's 403) carries the
  enforced header and that report-only mode swaps the header
  name only. Cumulative battery: **138/138**.
- **S-017 DONE (2026-10-30)** — dependency policy:
  `samverk/dependencies.py` (the code register:
  `ADMITTED_DEPENDENCIES`, today empty) +
  `docs/DEPENDENCY_REGISTER.md` (the human register). Admission
  requires all three of: a register entry with distribution,
  exact `==` pin, import name, and a reason line naming what
  the stdlib cannot do; the doc row; and the pinned pyproject
  requirement — in one commit. Battery
  `tests/test_dependencies.py`: **5 passed / 0 failed** — it
  parses pyproject (stdlib `tomllib`) and requires the declared
  runtime dependencies to equal the register exactly, checks
  every admission carries a reason + exact pin and is named in
  the doc, and AST-scans the package *and* the test suite so
  every import must be stdlib, intra-package, or admitted
  (with a guard test proving the scan really sees the package).
  The register's emptiness is now a proven fact per run.
  Cumulative battery: **143/143**.
- **S-018 DONE (2026-10-30)** — log redaction:
  `samverk/log_redaction.py` — a `RedactingFilter` for the
  logging stack (installed on the root logger by `serve()`),
  applying three layers in `redact_text`: registered literal
  secrets (`register_secret`, min length 4, longest-first);
  auth shapes struck whole (`Bearer`/`Basic`,
  `Authorization:`/`Cookie:`/`Set-Cookie:` header values); and
  sensitive-key pairs (`key=value`, `key: value`, JSON pairs)
  whose key is sensitive as a whole `_`/`-`-separated segment —
  `csrf_token`/`auth_token`/`x-api-key` strike, `author` does
  not. Keys survive so logs stay debuggable; bare hex is
  deliberately *not* struck (git SHAs belong in logs). Battery
  `tests/test_log_redaction.py`: **7 passed / 0 failed**,
  including the literal acceptance — seeded secrets in plain,
  format-arg, cookie, and JSON shapes never appear in captured
  logs. (One flaw found by the battery and fixed in-slice: the
  first key pattern's word boundary let compound keys like
  `csrf_token='…'` leak; the segment-aware pattern replaced
  it.) Cumulative battery: **150/150**.
- **S-019 DONE (2026-10-30)** — error law:
  `samverk/errors.py` — clients receive exactly
  `{"error": <registered code>, "error_id": <64-bit CSPRNG
  hex>}` and nothing else; codes are a frozen registry (like
  the S-008 taxonomy — an unregistered code raises in-process,
  never reaches a client); handlers may raise `PublicError`, and
  the server's dispatch is guarded so any unexpected exception
  becomes an opaque 500 under a fresh error id while the full
  detail lands in the server log under the *same* id via
  `log_internal_error` — which renders the traceback itself and
  redacts before writing (a bare `logger.exception` would carry
  exception text past S-018's filter, since logging appends
  tracebacks after filters run; this function exists for that
  reason). The base class's HTML error pages (malformed
  requests, unknown methods) are replaced wholesale with the
  JSON shape. The S-002 skeleton test's exact 404 assertion was
  updated to the extended shape, intent preserved. Battery
  `tests/test_errors.py`: **7 passed / 0 failed**, including a
  handler rigged to raise a secret-carrying exception — the 500
  body leaks neither message, path, nor traceback, and the
  captured server log holds the detail under the id, redacted.
  Cumulative battery: **157/157**.
- **S-020 DONE (2026-10-30)** — operator key custody:
  `samverk/keys.py` + `docs/KEY_CUSTODY_RUNBOOK.md` + `samverk
  keys ensure|status|rotate` CLI. Keys are generated at install
  (`ensure_instance_key`, 256-bit CSPRNG, idempotent — never
  silently replaced), stored as files only under
  `<data_root>/keys/` (`instance-<purpose>-v<N>.key`, hex,
  mode 600 from the first instant via `os.open`; loosely-
  permissioned or corrupt files refused fail-closed), and
  identified publicly by a 16-hex SHA-256 fingerprint that is
  safe to log. Rotation mints N+1 and keeps every earlier
  version loadable by number; the CLI's rotation is
  audit-logged (`admin.key.rotate`, fingerprints only). The
  runbook carries backup/restore/compromise duties, including
  the fingerprint comparison that proves a restore. Battery
  `tests/test_keys.py`: **8 passed / 0 failed**, including the
  literal acceptance — the full rotation drill on a scratch
  instance (generate → rotate ×2 → all versions load, all
  material distinct, key bytes and hex absent from the DB
  file) and the CLI drill end to end. Cumulative battery:
  **165/165**.
- **S-021 DONE (2026-10-30)** — signup abuse friction:
  `samverk/signup_friction.py` — a `SignupGuard` that decides
  (registration itself is S-025's, and consumes the decision).
  Friction is ours alone, **no third-party captcha**: S-011
  buckets aimed at signup (per-IP 5 attempts refilling 5/hour
  + per-email 3 refilling 3/hour, charged both-or-neither, so
  one-IP floods and one-address-many-IP retries both die), and
  disposable-domain *policy hooks* — a plain callable over the
  parsed domain; shipped policies are allow-all (default) and
  an operator blocklist (listed domains + their subdomains);
  no third-party disposable list is bundled or fetched.
  Decision order is deliberate: malformed → refused as
  malformed; domain-refused → refused without spending throttle
  tokens; only plausible attempts are charged. Battery
  `tests/test_signup_friction.py`: **8 passed / 0 failed**,
  including the literal acceptance — a scripted 20-attempt
  flood from one IP is throttled after 5 with truthful
  retry-afters, and buckets refill on the fake clock. (One
  parser flaw found by the battery and fixed in-slice:
  `a@.com` — an empty domain label — initially passed; the
  parser now requires ≥2 non-empty labels.) Cumulative
  battery: **173/173**.
- **S-022 DONE (2026-10-30)** — security battery v1:
  `tests/test_security_battery.py` — **9 passed / 0 failed**,
  attacking the *assembled* Part I system (real HTTP server,
  real session store, real seams): fabricated session cookies
  buy nothing and cross-site POSTs are refused 403; a DB-leak
  drill (stolen session-table values presented back)
  authenticates no one; SQL injection is stored as inert data
  with the audit chain intact; shell injection through git
  argv creates nothing; cookie header injection is refused;
  stored-XSS payloads render inert. **Named honestly in the
  file:** classic IDOR has no surface yet (no accounts or
  per-user resources exist in Part I), so the identifier class
  strikes the identifier surfaces that exist — repo names and
  URL paths — and Part II's gate (S-048) inherits the file.
  Cumulative battery: **182/182**.
- **S-023 DONE (2026-10-30)** — claims register:
  `docs/CLAIMS_REGISTER.md` — 12 claims (C-01…C-12) drawn from
  the README, each **PROVEN** with its counted evidence or
  **NOT PROVEN** with the roadmap part that owns its proof.
  Proven (some scoped, scope named in the row): DB-leak ≠
  credential leak, threat-model-first, audit tamper evidence,
  CSRF fail-closed, escaping seam + CSP, opaque error ids,
  stdlib-only/standalone, no-Docker construction. NOT PROVEN:
  unmodified-git-client transport (Part III), Windows/macOS/
  ARM-Pi cells (Part XXII), the design-lawbook face (Part XX),
  the mirror duty (Part XVII). Battery
  `tests/test_claims_register.py`: **4 passed / 0 failed** —
  anchor coverage for every tracked claim, PROVEN rows must
  name evidence files that exist, NOT PROVEN rows must name
  their owning part, and a tree scan keeps container
  artifacts out. The README's Status section was hand-updated
  in place (his text preserved; the stale "no code exists"
  paragraph replaced with the Part I position + a register
  pointer). Gate hardening in the same stretch: S-015's TLS
  wrap, previously unexercised on the wire, was proven
  end-to-end (real handshake + HTTPS health route + plaintext
  refused by the TLS port; commit 4ee3b61). Cumulative
  battery: **187/187** (recounted at the S-024 gate below).
- **S-024 DONE (2026-10-30) — PART I GATE.** Counted security
  run executed fresh at the gate on this VM (Linux x86-64):
  `python3 -m unittest discover -s tests` → **187 passed /
  0 failed**, including the S-022 attack battery (9) against
  the assembled system. Every Part I slice S-001…S-023 is
  banked with its own counted battery green at its commit.
  **Open findings, named, none hidden:**
  (1) Platform cells beyond Linux x86-64 are **NOT PROVEN** —
  Windows, macOS, ARM/Pi (claims C-10; Part XXII owns proof).
  (2) Classic IDOR has no surface yet — no accounts or
  per-user resources exist; the S-022 battery strikes the
  identifier surfaces that exist and is inherited by Part
  II's gate (S-048), where the IDOR class grows teeth.
  (3) CSP report-only mode has no server-side report
  endpoint yet — reports are the browser's half; collection
  lands with the web UI parts.
  (4) The TLS posture is proven end-to-end with a scratch
  self-signed cert (4ee3b61); operator-certificate handling
  at install time belongs to Part XVIII.
  (5) Everything banked this campaign sits on local `main` /
  `yrsa/samverk-part1` only — **no GitHub push made**: pushes
  stay gated on Volmarr's explicit word.
  **Part I is complete.** Next: Part II — Accounts & Identity,
  opening at S-025 registration.
- **S-025 DONE (2026-10-30)** — registration: `samverk/accounts.py`
  + schema migration 4 (`users`: display case kept, canonical
  `username_lower`/`email_lower` UNIQUE keys, email nullable so
  NULLs never collide). Username law: 3–39 chars, letters/digits/
  hyphen/underscore, no leading/trailing separator shape, must
  also pass S-013's owner law; reserved names (admin/root/
  support/samverk/api/www + Windows devices via S-013) refused
  with a clear reason. Email optional-but-supported: given
  addresses are shape-checked (S-021 parser + local-part law)
  and unique case-insensitively. Password policy is study 07
  §3.3: min 10 / max 128, no composition rules, screened against
  a bundled common list + the username; stored only as S-004
  scrypt. S-021's SignupGuard is consulted when supplied.
  Refusals create nothing and are audit-logged
  (`auth.signup.denied` with reason); successes commit before
  answering and log `auth.signup.success`. The
  `verification_mode` gate (none/smtp/operator) sets the new
  account's status for S-026. Battery `tests/test_accounts.py`:
  **12 passed / 0 failed**, including the literal acceptance —
  duplicate (any case) and reserved attempts refused clearly.
  Cumulative battery: **199/199**.
- **S-026 DONE (2026-10-30)** — email verification:
  `samverk/email_verification.py` + schema migration 5
  (`email_verification_tokens`, hashes only). Two roads, chosen
  by what the instance has: with a mailer seam (SMTP configured)
  a 256-bit token is minted, only its SHA-256 stored, the raw
  token handed to the mailer once; redemption is single-use,
  24 h expiry, a fresh request retires older tokens, and success
  marks the email verified and activates a
  `pending_verification` account. Without a mailer no token is
  minted or pretended — the account moves to `pending_approval`
  and `approve_user` (the operator's word, audited as
  `admin.user.approve` with the operator named) activates it;
  no-email accounts can only take this road. Failures answer
  generically (`invalid_or_expired` — invalid, expired, and
  used are indistinguishable). Taxonomy grew append-only by two
  events (`auth.email.verify`, `admin.user.approve`; 39 total,
  doc + code + counts updated together). Battery
  `tests/test_email_verification.py`: **10 passed / 0 failed**,
  including the DB-leak test (stored hashes redeem nothing, raw
  token absent from the DB file) and audit checks for both
  roads. Cumulative battery: **209/209**.
- **S-027 DONE (2026-10-30)** — login/logout: `samverk/login.py`
  (`LoginService` over S-025 accounts + S-006 sessions + S-005
  throttle). Every refusal — no such user, wrong password,
  pending/suspended status, throttled — raises the same
  `LoginFailed` with the same generic message, and a nonexistent
  user still costs a scrypt verify against a decoy hash so
  timing cannot enumerate accounts. Failures are audited
  (`auth.login.failure`, attempted name only, never a password)
  and feed the per-account exponential throttle (delays, never
  locks; success clears it); success audits
  `auth.login.success`, persists any S-004 hash upgrade, and
  issues a fresh session. Logout tombstones the session token
  itself and audits `auth.logout`; a second logout is a quiet
  no-op. **Bug found by this battery and fixed in-slice:**
  `SessionStore.revoke` reported True for an already-revoked
  token (SQLite counted the re-matched row); it now only
  revokes a live session (`AND revoked = 0`), verified against
  the S-006 and S-022 batteries too. Battery
  `tests/test_login.py`: **7 passed / 0 failed**. Cumulative
  battery: **216/216**.
- **S-028 DONE (2026-10-30)** — password change and reset:
  `samverk/password_reset.py` + schema migration 6
  (`password_reset_tokens`, hashes only, `via` recorded).
  Change requires the current password (a wrong one changes
  nothing — no hash moves, no session dies), enforces S-025's
  policy, and on success revokes **all** sessions. Reset:
  `request_reset` always answers identically (no enumeration);
  a letter is minted only for an existing active account with
  an email when a mailer is configured — 256-bit, SHA-256 at
  rest, **single-use, 1-hour expiry**, fresh requests retire
  older tokens. The operator road (`issue_operator_reset`)
  mints host-side for the no-mail instance, same redemption,
  audit records `via: operator`. Redemption validates the new
  password *before* consuming the token (a refused password
  does not burn the letter), then replaces the hash and revokes
  all sessions. Audited: `auth.password.change`,
  `auth.password.reset`. Battery `tests/test_password_reset.py`:
  **10 passed / 0 failed**, including the DB-leak test and the
  acceptance in literal form (single-use, expiring,
  all-sessions-revoked). Cumulative battery: **226/226**.
- **S-029 DONE (2026-10-30)** — profiles: `samverk/profiles.py`
  + schema migration 7 (`profiles`, one row per account).
  Display name (≤50) and bio (≤500, newlines allowed) are
  control-character-free plain text. Avatar upload is S-012 law
  narrowed to images (2 MiB cap, image-only policy): sniff beats
  declared, disguised/non-image payloads refused, quarantine
  first, then promotion to `<data_root>/avatars/<sha256><ext>`
  (mode 600) under the content-addressed name. **Alt text is
  mandatory** (Volmarr's image-accessibility law): an avatar
  with empty/missing alt is refused and stores nothing. The
  profile page (`render_profile_page`) renders only through
  S-010's escaping seam and always emits the stored alt on the
  avatar `<img>`. Taxonomy grew append-only by one event
  (`auth.profile.update`; 40 total, doc + code + counts updated
  together). Battery `tests/test_profiles.py`: **10 passed /
  0 failed**, including the literal acceptance (avatar under
  S-012 law + every image carries alt text). Cumulative
  battery: **236/236**.
- **S-030 DONE (2026-10-30)** — SSH keys: `samverk/ssh_keys.py`
  + schema migration 8 (`ssh_keys`, fingerprint globally
  UNIQUE). Parsing is strict: admitted algorithms only
  (ed25519, ecdsa nistp256/384/521, rsa — legacy ssh-dss
  refused), strict base64, and the blob's inner algorithm
  string must match its outer label. Fingerprint is the
  OpenSSH shape (`SHA256:<base64, padding stripped>`); list
  shows title, fingerprint, created and last-used
  (`record_use` stamps it for Part III's transport). **Key
  add requires sudo-mode re-auth through a fail-closed seam:**
  `SshKeyStore` takes a `reauth_verifier` callable (S-036
  supplies the real sudo mode); no verifier or a "no" answer
  refuses the add `sudo_required` and stores nothing —
  S-036's battery inherits the seam. One key, one account:
  re-registering your own key or another account's key is
  refused alike. Delete is owner-only and audit-logged with
  the fingerprint (`auth.ssh_key.add` / `auth.ssh_key.remove`,
  both already in the frozen taxonomy). Battery
  `tests/test_ssh_keys.py`: **8 passed / 0 failed**, including
  the literal acceptance (add gated on re-auth). Cumulative
  battery: **244/244**.
- **S-031 DONE (2026-10-30)** — deploy keys:
  `samverk/deploy_keys.py` + schema migration 9
  (`deploy_keys`, fingerprint UNIQUE). A deploy key binds to
  **exactly one repository** by canonical owner/repo (both
  halves under S-013's name law; repositories themselves land
  in Part III, the binding is by identity). **Read-only by
  default**; read/write is an explicit `can_write=True` grant
  at creation — no silent widening later (a grant change is a
  delete + re-add, two audit rows). `authorize(fingerprint,
  owner, repo, write=)` returns the key only for its own repo
  and only within its grant — another repo, another owner, or
  a write asked of a read-only key all answer None; S-088
  proves it on the wire. A fingerprint may not be both a
  personal and a deploy key, nor serve two repos. Adds/removes
  are owner-only and audit-logged as `repo.settings.change`
  with fingerprint + grant (never key material beyond the
  public blob). Battery `tests/test_deploy_keys.py`: **7
  passed / 0 failed**, including the literal acceptance (a
  deploy key cannot reach other repos). One battery-found
  flaw fixed in-slice: the new test's cross-test import
  (`tests.test_ssh_keys`) tripped S-017's import scan —
  helpers inlined instead. Cumulative battery: **251/251**.
- **S-032 DONE (2026-10-30)** — personal access tokens,
  classic shape: `samverk/access_tokens.py` + schema
  migration 10 (`access_tokens`, hashes only). Tokens are
  `svk_` + 256-bit CSPRNG, **shown once** at creation; only
  the SHA-256 hash is stored (S-006 law), with a 12-char
  identifying prefix for lists. **Scopes are required and
  closed** (`CLASSIC_SCOPES`: repo/issues/profile read+write;
  unknown scopes refused; write implies its read sibling via
  the one `token_allows` seam). **Expiry is required**, at
  most one year out; expired/revoked tokens authenticate to
  nothing. Revocation is owner-only; create/revoke audit as
  `auth.token.create` / `auth.token.revoke` (already in the
  frozen taxonomy; detail carries id + scopes, never the
  token). Battery `tests/test_access_tokens.py`: **9 passed /
  0 failed**, including the literal acceptance — the DB-leak
  test (stored hashes and prefix authenticate no one; the raw
  token is absent from the DB file). Cumulative battery:
  **260/260**.
- **S-033 DONE (2026-10-30)** — fine-grained tokens:
  `samverk/fine_grained_tokens.py` + schema migration 11
  (`fine_grained_tokens`, hashes only). A token binds to
  **exactly one repository** (canonical owner/repo, S-031's
  shape) and a per-resource permission set (contents /
  issues / pull_requests, read+write, plus `metadata:read`
  always held as the mandatory floor — stored, never hidden).
  Write implies only its own read sibling. `authorize` is the
  permission-matrix seam: wrong repo, wrong owner, ungranted
  or unknown permission, and expired/revoked tokens all
  answer None. S-032's law carries over: `svkf_` + 256-bit,
  shown once, expiry required (≤1 year), owner-only
  revocation, audited create/revoke without the token.
  Battery `tests/test_fine_grained_tokens.py`: **9 passed /
  0 failed**, including the literal acceptance — the full
  permission matrix (every permission × granted/ungranted ×
  own/other repo). Cumulative battery: **269/269**.
- **S-034 DONE (2026-10-30)** — token management UI
  (surface): `samverk/token_management.py` — one management
  home over both token stores. `TokenManagement.list_all`
  unifies classic + fine-grained tokens with title, prefix,
  scopes/permissions, target repo, created, **last-used**,
  expiry, and a status word (Active / Expired / Revoked —
  text, never colour alone); `revoke(user, kind, id)` is the
  one-click revocation, dispatched to the owning store whose
  owner-only law guards it. **Findability (the anti-Forgejo
  test):** `render_settings_home` links `/settings/tokens`
  in one click; the token page renders a revoke form (with
  the S-009 CSRF field) only for live tokens, and an empty
  state that teaches what a token is. All user text passes
  S-010's escaping seam. Battery
  `tests/test_token_management.py`: **7 passed / 0 failed**,
  including the findability walk (settings home → token
  page) and one-call revocation of both kinds. Cumulative
  battery: **276/276**.
- **S-035 DONE (2026-10-30)** — two-factor TOTP enrolment:
  `samverk/totp.py` + schema migration 12 (`totp_credentials`).
  RFC 6238/4226 HMAC-SHA1 TOTP (30 s step, 6 digits, ±1-step
  skew window) proven against the RFC known-answer vectors.
  Enrolment offers the provisioning URI (the QR encodes it)
  + the Base32 secret for manual entry; enabling is a step-up
  act through S-030's re-auth seam, failing closed, and only a
  live code confirms (`auth.twofactor.enable`, method totp).
  The 160-bit secret is stored **encrypted** under a caller-
  supplied 256-bit instance key (HMAC-SHA256 keystream, fresh
  nonce per enrolment; no key → enrolment refuses), never
  plain, and each counter may be spent once (`last_counter`
  replay law). Battery `tests/test_totp.py`: **10 passed /
  0 failed**, including the DB-leak test (the plaintext
  secret appears neither in the stored value nor the DB
  file). (Two test-authoring slips fixed in-slice: two RFC
  vectors first typed from the table's SHA-256 column, and
  the provisioning label's colon over-encoded.) Cumulative
  battery: **286/286**.
- **S-036 DONE (2026-10-30)** — sudo mode: `samverk/sudo_mode.py`
  + schema migration 13 (`sudo_grants`). Re-entering the
  account password (S-004 verify, decoy-hash timing for unknown
  accounts, upgrade persisted as in S-027) opens a 15-minute
  freshness window bound to **one session**, keyed by the
  session token's SHA-256 — the raw token never touches the
  table. Wrong password / unknown account is one generic
  `SudoFailed` and grants nothing; expired grants answer
  False and are swept. `as_verifier(session)` returns exactly
  the re-auth seam S-030/S-035 consume, fulfilling S-030's
  promise: its battery drives the real verifier through the
  SSH key-add gate (refused before the grant, allowed inside
  the window, refused after expiry). Battery
  `tests/test_sudo_mode.py`: **6 passed / 0 failed**,
  including the DB-leak test (grant rows hold hashes only,
  and a stored hash itself buys no freshness). Cumulative
  battery: **292/292**.
- **S-037 DONE (2026-10-30)** — recovery codes:
  `samverk/recovery_codes.py` + schema migration 14. A set is
  ten codes (10 chars, unambiguous alphabet, `XXXXX-XXXXX`),
  shown once and stored only as SHA-256 hashes; redemption
  is single-use (race-safe spend) and every failure is the
  same False. Regeneration deletes the whole old set in the
  same transaction that mints the new one and **reports how
  many codes died** (`invalidated`), so the surface can warn
  loudly. Gates: confirmed S-035 two-factor required, and
  generation is sudo-gated through the S-036 seam. Taxonomy
  grew append-only by two events (`auth.recovery.generate` /
  `auth.recovery.use`, detail carries counts, never codes;
  42 total, doc + code + counts updated together). Battery
  `tests/test_recovery_codes.py`: **6 passed / 0 failed**,
  including the DB-leak sweep for every plaintext code.
  Cumulative battery: **298/298**.
- **S-038 DONE (2026-10-30)** — two-factor enforcement policy:
  `samverk/twofactor_policy.py` over the instance `settings`
  table (no new migration). An instance may require two-factor
  for **admins**: turning it on starts a grace clock once
  (default 7 days; re-saving never restarts it), inside grace
  an admin without S-035 two-factor is warned in plain words
  naming the time left, after grace `is_blocked` answers True,
  and enrolment satisfies the policy at any point. Non-admins
  are outside it entirely. Changes are audited
  `admin.settings.change`. **Org scope is refused with its
  reason named** (`org_scope_not_available`) — organisations
  land in a later part, and pretending to evaluate org
  adminship now would be a claim, not a control. Battery
  `tests/test_twofactor_policy.py`: **7 passed / 0 failed**.
  Cumulative battery: **305/305**.
- **S-039 DONE (2026-10-30)** — passkeys/WebAuthn:
  `samverk/passkeys.py` + schema migration 15
  (`passkey_challenges` hashed-only/single-use/5-minute;
  `passkey_credentials`, credential id globally UNIQUE).
  The WebAuthn Level 2 ceremonies implemented clean-room
  from the public W3C spec on the stdlib alone — own CBOR
  decoder, own COSE parsing, own pure-Python signature
  verification (ES256, RS256, EdDSA). Registration is
  sudo-gated through the S-036 seam, verifies client-data
  type/challenge/origin, RP-ID hash, user presence, and the
  attestation format (`none` accepted; `packed`
  self-attestation verified with the credential's own key;
  certificate chains and other formats refused by name).
  Authentication serves both roadmap doors with one
  ceremony — account-bound challenge = second factor,
  unbound = passwordless (the verified credential names the
  account; the caller mints the ordinary S-006 session).
  A signature counter that fails to move forward is refused
  as `cloned_authenticator`. Taxonomy grew append-only by
  three events (`auth.passkey.add` / `auth.passkey.remove` /
  `auth.passkey.login`; 45 total, doc + code + counts
  updated together). Battery `tests/test_passkeys.py`:
  **13 passed / 0 failed**, including the literal
  acceptance — interop proven against **two independent
  software authenticators written in the battery itself**
  (ES256 with DER signatures + packed self-attestation, and
  Ed25519 with RFC 8032 mathematics), sharing no code with
  the server. Cumulative battery: **318/318**.
- **S-040 DONE (2026-10-30)** — session management:
  `samverk/session_management.py` over the S-006 store,
  extended in place (schema migration 16 adds
  `device_label` / `source_ip` to sessions; `SessionStore`
  gains `list_for_user`, owner-scoped `revoke_by_id`, and
  `revoke_all(except_id=…)`; S-027 login now records the
  device label + address at sign-in). The owner sees every
  session — device, address, sign-in and last-active times,
  a status word (Active / Revoked / Expired, text never
  colour alone), and a *this session* marker — one click
  from the settings home via S-034's existing "Security
  and sessions" link. `revoke_one` is owner-only in the
  query itself; `revoke_all` can spare the current session
  so the remedy does not lock out its wielder. Every landed
  revocation is audited under the taxonomy's long-frozen
  `auth.session.revoke` (`{"scope": "one"|"all"}` — no new
  events). The page renders device labels (hostile text)
  only through S-010's seam and offers revoke forms only
  for live, non-current sessions. Battery
  `tests/test_session_management.py`: **7 passed /
  0 failed**, including the literal acceptance — a revoked
  session's token resolves to nobody on its very next
  request while its sibling session lives on. Cumulative
  battery: **325/325**.
- **S-041 DONE (2026-10-30)** — new-sign-in notification:
  `samverk/signin_notifications.py` + schema migration 17
  (`known_devices`, keyed by a SHA-256 of the label+address
  pair; `signin_notifications`, the in-app inbox). A device
  is the pair a sign-in arrived with (S-040's label +
  address): first sighting fires, repeats only move
  `last_seen_at` — **once per new device, never per
  sign-in**, and an account's first-ever sign-in fires too
  (nothing is known yet; everything is new). Two channels in
  trust order: the in-app notice always (device, address,
  time; owner-only read marks), then email through a mailer
  seam when the instance has one and the account has an
  address — best-effort, committed notice first, a mailer
  failure unmakes nothing. Wired into S-027's login service
  as the optional `signin_notifier=` seam (unwired instances
  behave exactly as before). Taxonomy grew append-only by
  one event (`auth.signin.notify`; 46 total, doc + code +
  counts updated together). Battery
  `tests/test_signin_notifications.py`: **6 passed /
  0 failed**, including the literal acceptance driven
  through the real login service (two identical logins →
  exactly one notice and one audit row). Cumulative
  battery: **331/331**.
- **S-042 DONE (2026-10-30)** — account rename:
  `AccountStore.rename` in `samverk/accounts.py` + schema
  migration 18 (`username_tombstones`). The rename applies
  the full S-025 username law to the new name and refuses
  collisions clearly — live names (any case), reserved
  names, and other accounts' unexpired tombstones. The old
  canonical name is held as a **90-day tombstone**:
  `resolve_user` / `redirect_for` route it to the account's
  new name (the resolution seam Part III's repository URLs
  will ride on), registration refuses the held name, and
  the owner may rename back onto their own tombstone
  (reclaiming it leaves the intermediate name tombstoned
  instead). A case-only change moves the display case and
  leaves no tombstone. Sessions, keyed by account id, are
  untouched. Every outcome is audited under the append-only
  taxonomy addition `auth.username.change` (47 events
  total; doc + code + counts updated together). Battery
  `tests/test_account_rename.py`: **7 passed / 0 failed**,
  including tombstone lapse (after 90 days the name frees
  and the redirect ends). Cumulative battery: **338/338**.
- **S-043 DONE (2026-10-30)** — account deletion:
  `samverk/account_deletion.py` + schema migration 19
  (`account_deletions`). Deletion is a process: an
  **inventory** counts everything the account holds across
  every store before the act; the request needs the
  username **typed** as confirmation and fresh sudo
  re-auth through the S-036 seam (fail-closed); a **7-day
  grace period** follows (status `pending_deletion`, login
  refused, nothing destroyed, `cancel` restores the account
  whole); only after grace does execution delete every
  per-user row and the user row in one transaction, leaving
  the name tombstoned 90 days against instant impersonation.
  The audit log is never deleted — it is the witness — and
  request/cancel/execute are audited under taxonomy
  additions `auth.deletion.request` / `.cancel` / `.execute`.
  Battery `tests/test_account_deletion.py`: **4 passed /
  0 failed**. Cumulative battery: **342/342**.
- **S-044 DONE (2026-10-30)** — account suspension:
  `samverk/account_suspension.py` + schema migration 20
  (`account_suspensions`). Admin-only (self-suspension
  refused), **reason required** and kept on the record;
  suspension sets status `suspended`, revokes all sessions
  at once, and hides the account's content through the one
  `is_content_visible` policy seam — **never deletes**:
  profile and every other row survive, and `unsuspend`
  restores the account whole. Audited `admin.user.suspend`
  / `admin.user.unsuspend` (taxonomy additions; 54 events
  total with S-043/S-045: 29 auth, 13 repo, 12 admin).
  Battery `tests/test_account_suspension.py`: **3 passed /
  0 failed**. Cumulative battery: **345/345**.
- **S-045 DONE (2026-10-30)** — identity-linking data
  shape: `samverk/identity_linking.py` + schema migration
  21 (`external_identities`, UNIQUE (provider, external_id)
  and (user_id, provider)). An account links one external
  principal per provider — **Samtal first** (`samtal`) —
  and a principal can be claimed by only one account;
  re-linking is unlink + link, both audited
  (`auth.identity.link` / `.unlink`). **Shape only**, by
  the roadmap's word: no seam, no sync, no external login,
  no federation; the store deliberately exposes no
  authenticate seam (asserted by the battery). Battery
  `tests/test_identity_linking.py`: **5 passed / 0 failed**.
  Cumulative battery: **350/350**.
- **S-046 DONE (2026-10-30)** — reserved and impersonation
  defence: `samverk/lookalike.py` — warnings, not refusals
  (refusal stays S-025's for exact names). A candidate's
  skeleton lowercases, drops separators, folds leetspeak
  and the visual confusables `rn`→`m` / `vv`→`w`; equal
  skeletons or edit distance 1 against reserved names or
  live accounts produce a plain-language warning naming
  what it resembles. `registration_warnings` reads the
  live account set. Battery `tests/test_lookalike.py`:
  **5 passed / 0 failed**. (Two flaws found by the battery
  and fixed in-slice: leet `1` folds to `i`, not `l`
  — `adm1n` is admin — and `rn`-for-`m` is two edits wide
  but one glance wide, so it belongs in the skeleton.)
  Cumulative battery: **355/355**.
- **S-047 DONE (2026-10-30)** — login history:
  `samverk/login_history.py` — the owner-visible record
  read from the audit log itself: rows where the account
  is actor, target of an admin act, or the attempted name
  on a failed login (shown as an attempt, per study 35
  §4). Newest first, limit clamped 1..500, a sign-ins-only
  filter, and a page rendering every value through S-010's
  seam. There is no cross-account view in this seam.
  Battery `tests/test_login_history.py`: **5 passed /
  0 failed**. Cumulative battery: **360/360**.
- **S-048 DONE (2026-10-30) — PART II GATE.** Gate battery
  `tests/test_identity_battery.py`: **8 passed / 0 failed**,
  striking the *assembled* Part II system across accounts —
  fabricated credentials authenticate no one, cross-account
  token and session revocation fail, the fine-grained
  permission matrix holds, histories and identity links do
  not cross accounts, a DB leak buys no identity, and the
  **token findability walk is recorded**: settings home →
  `/settings/tokens` in one click → token listed with its
  revoke form → one-call revocation → status word Revoked.
  Full counted run at the gate on this VM:
  `python3 -m unittest discover -s tests` → **368 passed /
  0 failed**. Open findings, named: (1) S-045 is shape
  only — the Samtal seam is Part XIX, by design; (2)
  platform cells beyond Linux x86-64 remain NOT PROVEN
  (Part XXII); (3) everything banked sits on local `main`
  only — **no GitHub push**: pushes stay gated on
  Volmarr's explicit word. **Part II is complete.**
  Next: Part III — Git Core, opening at S-049 bare
  repository creation.
- **S-049 DONE (2026-10-30)** — bare repository creation:
  `samverk/repositories.py` + schema migration 22
  (`repositories`: canonical lowercase owner/name UNIQUE,
  display case kept; the row also carries S-050's metadata
  columns with defaults so no second migration is needed).
  Creation validates both halves under S-013, requires the
  actor to be the owner account, runs `git init --bare
  --initial-branch=<default>` through S-014, and only then
  writes the row — committing before the answer, so a separate
  connection sees it at once. All-or-nothing: a failed row
  write removes the just-created directory, and a directory
  already on disk is refused, never silently adopted (drift
  is S-071's to name). Audited `repo.create`. Battery
  `tests/test_repositories.py`: **6 passed / 0 failed**,
  including the separate-connection visibility check.
  Cumulative battery: **374/374**.
- **S-050 DONE (2026-10-30)** — repository metadata model:
  description (≤350 plain-text chars), visibility (`public` /
  `private`, default `private`) and default branch live on the
  S-049 row (columns landed with migration 22, so this slice
  needed no new migration). `RepositoryStore.update_metadata`
  is owner-only and validated; a default-branch change moves
  the bare repo's HEAD symbolic ref first, so metadata never
  claims a branch git does not point at, and a visibility
  change audits `repo.visibility.change` separately from
  `repo.settings.change`. `rename` moves directory and row
  together — a single `os.rename` inside the one repos root,
  the row in one transaction, and a failed row update rolls
  the directory back. Battery `tests/test_repo_metadata.py`:
  **6 passed / 0 failed**. Cumulative battery: **380/380**.
- **S-051 DONE (2026-10-30)** — object reading:
  `samverk/objects.py` — blob/tree/commit reads through one
  `cat-file --batch` spawn per call (S-014 law), never one
  spawn per object. Object ids are hex-validated before they
  reach git; a missing object is a named refusal
  (`object_not_found`), never empty content. Tree payloads
  parse to (mode, name, oid) entries; commits parse to tree,
  parents, author/committer and message. Battery
  `tests/test_objects.py`: **3 passed / 0 failed**, including
  the latency proof — 2,000 distinct blobs batch-read with
  content verified, far inside a 5-second ceiling a
  spawn-per-object reader would blow. (The roadmap's 10k
  figure re-verifies at the Part III gate, S-076.)
  Cumulative battery: **383/383**.
- **S-052 DONE (2026-10-30)** — ref listing and resolution:
  `samverk/refs.py` — one `for-each-ref` spawn returns every
  ref with oid, type and peeled oid (annotated tags peel to
  their commit); HEAD is read through `symbolic-ref`, the
  indirection itself, and resolution goes through
  `rev-parse --verify`. Packed-refs stay git's business.
  Ref names are validated before reaching git, so a name can
  never be read as a flag. Battery `tests/test_refs.py`:
  **3 passed / 0 failed**, including annotated-tag peeling
  and the empty-repo case (no refs, HEAD on the default
  branch, no head oid). Cumulative battery: **386/386**.
- **S-053 DONE (2026-10-30)** — atomic ref updates:
  `RefStore.update_ref` in `samverk/refs.py` — branch
  create/delete/rename and general updates through
  `update-ref` with compare-and-swap: naming the expected
  old value makes git check-and-set under its own lock, and
  a loser is refused as `stale_ref` instead of tearing the
  ref. Rename is a create+delete pair in one
  `update-ref --stdin` invocation, verified against the old
  value. Battery `tests/test_ref_updates.py`: **3 passed /
  0 failed**, including the race — ten threads CAS the same
  ref from the same expected value and exactly one wins.
  Cumulative battery: **389/389** (full counted run on this
  VM at this slice).
- **S-054 DONE (2026-10-30)** — repository visibility
  enforcement: `samverk/permissions.py` — one function,
  `role_for(viewer, repo, collaborator_role=...)`, decides
  every repository permission, and web/API/transports must
  consult it or its `can_read`/`can_write`/`can_admin`
  wrappers. Owner and site admin hold `admin`; a granted
  collaborator role applies on any visibility (the grant
  store is Part IX's; the seam takes the role until then);
  public means world-readable and never world-writable;
  private means role `None` for everyone else, which
  surfaces render as not-found, not forbidden — a private
  repo's existence is itself private. Battery
  `tests/test_permissions.py`: **6 passed / 0 failed** —
  the Part IX matrix (owner / collaborator / stranger /
  anonymous x public / private x read / write / admin) run
  early, as the roadmap asks. Cumulative battery:
  **395/395** (full counted run on this VM at this slice).
  Next: S-055 forking.
- **S-055 DONE (2026-10-30)** — forking: `samverk/forks.py` +
  schema migration 23 (`repositories.fork_of_id`) — a fork is a
  server-side bare clone through S-014's dedicated
  local-paths-only seam (`run_git_clone_local`; generic
  `clone` stays refused — corrected in the fix entry below
  after the S-014 battery caught the first cut allowlisting
  it) with its own object store, so upstream
  damage can never break it; the row records the direct
  upstream link. Forking is gated by S-054's `can_read` (an
  unreadable private repo answers as not-found), a private
  source can never be forked public, `fork_count` counts direct
  forks, and `network_for` walks to the root and lists the
  whole network. Audited `repo.fork` (taxonomy append-only +1
  event, 55 total; doc and code updated together). Battery
  `tests/test_forks.py`: **5 passed / 0 failed**, including
  fork independence (a ref deleted in the fork leaves the
  upstream untouched). Cumulative battery: **400/400**.
  Next: S-056 repository deletion.
- **S-056 DONE (2026-10-30)** — repository deletion:
  `samverk/repo_deletion.py` + schema migration 24
  (`repo_deletions`) — the S-043 process shape for repos:
  owner-only and sudo-gated (fail-closed verifier seam), a
  7-day tombstone grace during which the disk is untouched
  and `cancel` restores the repo whole, and execution only
  at/after the scheduled time — row deleted, bare directory
  reclaimed, and forks (independent clones since S-055)
  survive with their upstream link cleared. Audited:
  request/cancel under `repo.settings.change`, execution
  under the frozen `repo.delete`. Battery
  `tests/test_repo_deletion.py`: **4 passed / 0 failed**,
  including not-due execution destroying nothing and the
  disk surviving the whole grace. Cumulative battery:
  **404/404**. Next: S-057 repository transfer.
- **S-057 DONE (2026-10-30)** — repository transfer:
  `samverk/repo_transfer.py` + schema migration 25
  (`repo_transfers`, `repo_redirects`) — ownership moves only
  with the recipient's acceptance: the owner initiates (a
  missing recipient, a self-transfer, a pending offer, or a
  recipient name collision are each refused by name), nothing
  moves until the named recipient — and only they — accepts,
  and then the directory and row move together under the
  S-050 rollback discipline and a redirect from the old
  canonical name is left behind for 90 days. Decline (recipient)
  and cancel (owner) move nothing. This slice also extends
  S-056's execution to clear a pending transfer when its repo
  is deleted — sequenced here because the table arrives here;
  the intermediate S-056-only tree was caught referencing it
  early by its own battery and fixed before this slice landed.
  Audited under the frozen `repo.transfer`. Battery
  `tests/test_repo_transfer.py`: **4 passed / 0 failed**.
  Cumulative battery: **408/408**. Next: S-058 size accounting.
- **S-058 DONE (2026-10-30)** — repository size accounting:
  `samverk/repo_size.py` (no migration) — a file-by-file walk
  of the bare directory (symlinks never followed) split into
  git objects (`objects/`), LFS objects (`lfs/`, the per-repo
  layout S-060 will fill — 0 until then, never invented), and
  other (refs/config/future assets alongside), the three
  always summing to the total. Shown to owners and site
  admins only; anyone else is refused and a missing repo is
  named. Battery `tests/test_repo_size.py`: **4 passed /
  0 failed**, including a planted LFS object counted to the
  byte and real git content growing the object category.
  Cumulative battery: **412/412** (full counted run on this
  VM at this slice). Next: S-059 garbage-collection scheduling.
- **FIX (2026-10-30, same keeper run)** — the final full
  recount caught S-055's first cut breaking S-014's battery:
  allowlisting generic `clone` made `run_git(["clone", url])`
  stop being refused. Fixed in scope per the never-leave-a-bug
  law: `clone` is off the allowlist again, and forking goes
  through `run_git_clone_local` in `samverk/proc.py` — both
  paths are trusted resolved `Path` objects from S-013, the
  function builds its own argv, and no caller string can be a
  clone source. The S-055 entry above is corrected to match.
- **S-059 DONE (2026-10-30)** — garbage-collection scheduling:
  `samverk/repo_gc.py` + schema migration 26 (`repo_gc_state`).
  Policy is a pure function of measured facts (size from
  S-058's walk, loose-object count): no loose objects → not
  needed; large (≥32 MiB or ≥500 loose) → daily aggressive;
  medium (≥1 MiB or ≥50 loose) → weekly; small → monthly.
  `gc`/`count-objects` joined the S-014 allowlist here, with
  reasons. The acceptance — *no request waits on gc* — is
  structural: `GCScheduler.assess` only measures and records
  a due time (it spawns nothing, proven by the battery: loose
  objects stay loose after assessing), and `run_due` is the
  sole gc spawner, an off-path entry point for a background
  worker/operator; outcomes (ok/failed) and the next due
  time are recorded per repo. Battery
  `tests/test_repo_gc.py`: **4 passed / 0 failed**, including
  a real `git gc` packing 5 loose objects to 0 and the
  not-due-until-the-interval-passes check. Cumulative
  battery: **416/416** (full counted run on this VM at this
  slice). Next: S-060 LFS object store.
- **S-060 DONE (2026-10-30)** — LFS object store:
  `samverk/lfs_store.py` (no migration) — per-repo
  content-addressed layout `<repo>.git/lfs/objects/<ab>/<cd>/<oid>`
  (the standard LFS fan-out; the layout S-058 already
  measures). Integrity is verified by oid on write: bytes
  land in a temp file, are SHA-256-hashed as written, and
  are atomically published only when the digest equals the
  claimed oid (and the length the claimed size) — a mismatch
  stores nothing. Dedupe: an object already present and
  verified is never rewritten (mtime-proven in the battery).
  Oids are validated as exactly 64 lowercase hex before they
  form any path. Pointer files (`make_pointer` /
  `parse_pointer`, the LFS spec v1 text shape) round-trip
  here so S-061's API and real clients share one parser.
  Battery `tests/test_lfs_store.py`: **6 passed / 0 failed**,
  including S-058's accounting seeing stored LFS bytes to
  the byte. Cumulative battery: **422/422** (full counted
  run on this VM at this slice). Next: S-061 LFS batch API.
  (Environment note: `git-lfs` was not installed on this VM;
  installed natively via apt this run — no Docker — so
  S-061/S-062's real-client interop acceptances can be
  proven, not skipped.)
- **S-061 DONE (2026-10-30)** — LFS batch API:
  `samverk/lfs_api.py` (no migration) — the batch operation
  real git-lfs clients speak, plus `make_lfs_handler`, an
  HTTP adapter serving `/<owner>/<repo>/info/lfs/…` and the
  action URLs (the main server's route table adopts these
  with Part IV's transports, whose S-081/S-082 supply the
  real actor resolvers). Per object, the server answers
  with expiring **signed action URLs**: HMAC-SHA256 tokens
  naming exactly one repo, one oid, one operation
  (upload/download/verify), expiring in one hour, verified
  through the S-005 constant-time seam — tampered, expired,
  and wrong-operation tokens are all refused in the battery.
  Permissions come from S-054's one function (upload needs
  write, download needs read, an unreadable private repo
  answers 404); an already-stored object gets no upload
  actions; a missing download object gets the spec's
  per-object 404; the verify action re-hashes the stored
  bytes (S-060) before telling a client success. Battery
  `tests/test_lfs_api.py`: **6 passed / 0 failed**,
  including the literal acceptance — a **stock git-lfs
  3.6.1 client round-trip**: `git lfs push --all` uploaded
  a 1 MiB object through the batch API into S-060's store
  (verified there by oid), and a fresh repo's checkout
  smudge downloaded it back through the batch API to
  byte-identical content. Cumulative battery: **428/428**
  (full counted run on this VM at this slice, git-lfs on
  PATH). Two honest notes: (1) this VM's system layer does
  not persist apt installs between sessions, so a pristine
  git-lfs 3.6.1 release binary is kept at
  `~/workspace/.tools/git-lfs` for keeper runs (the battery
  skips the client test where no git-lfs exists, per the
  standing skip pattern); (2) a threaded HTTP server cannot
  use a same-thread sqlite connection — the battery harness
  opens its connection cross-thread, and Part IV's wiring
  must do the same (or per-thread connections). Next:
  S-062 LFS locking.
- **S-062 DONE (2026-10-30)** — LFS locking:
  `samverk/lfs_locks.py` + schema migration 27 (`lfs_locks`,
  UNIQUE (repo_id, path)) — the public LFS lock API:
  lock / unlock / list / verify, served through the S-061
  handler when a locking service is attached. Locks name
  *paths*, not objects; ids are 128-bit random hex.
  Locking needs S-054 write, listing/verifying read; a
  conflict refuses 403 naming the existing lock (holder
  included, so a client can show who has it); only the
  lock's owner may release it, or a repo admin with an
  explicit `force`. `verify` splits ours/theirs for the
  push-time check. Battery `tests/test_lfs_locks.py`:
  **6 passed / 0 failed**, including the literal
  acceptance — stock git-lfs 3.6.1 `lock` / `locks` /
  `unlock` against Samverk's endpoint. (Two battery-design
  lessons, fixed in the tests, not the code: a stranger
  rightly cannot write-lock a public repo under S-054, so
  conflicts are exercised by an admin; and git-lfs itself
  refuses to unlock a file with uncommitted changes, so
  the interop repo commits first.) Cumulative battery:
  **434/434** (full counted run on this VM at this slice).
  Next: S-063 archive downloads.
- **S-063 DONE (2026-10-30)** — archive downloads:
  `samverk/archives.py` + `archive` on S-014's allowlist and a
  streamed-spawn seam (`popen_git_in` in `samverk/proc.py`,
  same validation/environment law, caller owns the deadline).
  Zip and tar.gz of any ref via `git archive`: S-054's
  `can_read` gates before any spawn, and missing and
  unreadable repos answer identically (`repo_not_found`);
  the ref is resolved through S-052 before archiving
  (unknown → `ref_not_found`, flag-shaped → `ref_invalid`,
  nothing spawned); bytes stream in 64 KiB chunks and are
  counted + SHA-256-hashed as they flow, under a 120 s
  deadline that kills an overrunning git. The top-level
  directory and filename are `<repo>-<ref>`. Battery
  `tests/test_archives.py`: **6 passed / 0 failed**,
  including the literal acceptance — both formats are
  checksum-stable across repeated downloads of a fixed
  ref, contents verify against the fixture files, a
  320 KB incompressible payload streams in multiple
  chunks, and HEAD-vs-branch prefix naming is honoured.
  (Two test-design flaws fixed in-slice, code untouched:
  compressible payloads made single-chunk archives, and
  an equality check first compared archives whose
  `<repo>-<ref>` prefixes rightly differ.) Cumulative
  battery: **440/440** (full counted run on this VM at
  this slice). Next: S-064 repository templates.
- **S-064 DONE (2026-10-30)** — repository templates:
  `samverk/repo_templates.py` + schema migration 28
  (`repositories.is_template`, `template_of_id`). A repo is
  a template only when its owner marks it (`set_template`,
  owner-only); unmarked repos refuse as `not_a_template`.
  Creation rides S-014's local clone seam under S-054's
  read gate (unreadable private template = not found; a
  private template can never create a public repo), is
  **not** a fork (`fork_of_id` empty, `template_of_id`
  records the source), and substitutes variables in the
  **root README only**: `{{ key }}` placeholders with
  caller-supplied values, unknown placeholders left as
  written and reported, every other file byte-identical
  (proven on a code file carrying the same placeholder).
  A landed substitution is one new commit on the copied
  HEAD, authored by the creator; no match → no commit
  invented, history untouched. `mktree`/`commit-tree`
  joined S-014's allowlist here, with reasons; `run_git_in`
  gained an `env_extra` parameter (the commit's author
  identity). Audited `repo.create` with the template
  source named. Battery `tests/test_repo_templates.py`:
  **6 passed / 0 failed**. Cumulative battery: **446/446**
  (slice battery + affected suites re-run at this slice;
  full recount at the next gate). Next: S-065
  empty-repository state.
- **S-065 DONE (2026-10-30)** — empty-repository state:
  `samverk/empty_repo.py` — emptiness is read from git
  itself (no refs, no HEAD object), never a flag, and the
  state ends the moment a first commit lands
  (`repo_not_empty`). `EmptyStateService.instructions_for`
  generates first-push instructions **per transport** from
  the instance's configured addresses (HTTP base, SSH
  host/user) and the repo's real default branch: clone URL
  plus two copyable command blocks (new local repo /
  existing local repo) with no shell prompts inside the
  blocks. Unconfigured transports produce no guessed
  address — they are named in `unavailable_transports`;
  credential-carrying HTTP bases are refused at
  construction. S-054's read gate applies (a private
  repo's emptiness is private). Battery
  `tests/test_empty_repo.py`: **4 passed / 0 failed**.
  Cumulative battery: **450/450** (full recount at the
  next gate). Next: S-066 repository settings.
- **S-066 DONE (2026-10-30)** — repository settings:
  `samverk/repo_settings.py` + schema migration 29
  (`repo_settings`, `repo_branch_renames`). Description
  and visibility keep their one S-050 writer (this service
  delegates); **website** must pass S-010's `safe_url` and
  be http(s) (`javascript:`/`data:`/`mailto:` refused);
  **topics** are a closed shape (lowercase/digits/hyphens,
  ≤20 × ≤50 chars, normalised and deduped). **Default-
  branch rename** moves the branch itself through S-053's
  atomic rename, follows with HEAD + the S-050 default,
  and **records the rename** so `rename_guidance` hands a
  pre-rename clone the exact copyable steps (`git branch
  -m …`, `git fetch`, `git branch -u …`, `git remote
  set-head origin -a`) — guidance, honestly named, since
  Samverk cannot reach into a clone it does not host. An
  empty repo's rename is metadata + HEAD only. All changes
  owner-only, audited `repo.settings.change`. Battery
  `tests/test_repo_settings.py`: **6 passed / 0 failed**.
  Cumulative battery: **456/456** (full counted run on
  this VM at this slice, verifying the S-064/S-065
  arithmetic too). Next: S-067 server-side hooks seam.
- **S-067 DONE (2026-10-30)** — server-side hooks seam:
  `samverk/hooks.py` — a `HookRunner` with named, ordered
  handlers per phase. **Pre-receive fails closed**: a hook
  returning a string / `False` or raising `HookVeto` vetoes
  the push (chain stops, reason carried for the pusher);
  an exception or a timeout also refuses. **Post-receive
  can never veto**: every hook runs, outcomes are recorded
  (`completed` / `vetoed` / `error` / `timeout`) and the
  runner moves on. **Timeout and kill discipline is
  structural**: each hook runs in a forked child process,
  the parent waits only the runner's budget (default 10 s),
  and an overrunning child is terminated, then killed,
  then reaped — a hung hook costs one refused push, never
  a hung server. This is the seam S-089's protection gate
  and Part XV's scanning hang on. Battery
  `tests/test_hooks.py`: **6 passed / 0 failed**, including
  a 60-second-sleep hook refused in ~the 0.5 s budget.
  Cumulative battery: **462/462** (full recount at the
  next gate). Next: S-068 repository quotas.
- **S-068 DONE (2026-10-30)** — repository quotas:
  `samverk/repo_quotas.py` + schema migration 30
  (`repo_quotas`). A quota is a byte limit enforced **at
  receive time**: `enforce_receive` is the gate the receive
  path calls before accepting objects, and a push that
  would exceed the limit is refused with a plain message
  naming what the repo holds, its limit, and what the push
  adds — nothing half-lands. Usage is S-058's measured walk
  (the number enforced is the number displayed). Two
  explicit levels only: a per-repo quota (owner or site
  admin) wins over an admin-set instance default in
  `settings`; neither set means unlimited — a limit is
  never invented. `check_receive` returns the decision
  object for surfaces; changes audit `repo.settings.change`.
  Battery `tests/test_repo_quotas.py`: **5 passed /
  0 failed**, including the literal refusal message checked
  number by number. Cumulative battery: **467/467**
  (full recount at the next gate). Next: S-069 import by
  clone URL.
- **S-069 DONE (2026-10-30)** — import by clone URL:
  `samverk/repo_import.py` + the dedicated seams in
  `samverk/proc.py` (`validate_remote_url`,
  `run_git_clone_remote`, and `run_git_fetch_from` landed
  here for S-070). Generic `clone` stays refused under
  S-014 — the import seam validates the address itself
  (remote schemes https/http/git/ssh only, a real host, no
  whitespace/controls, no leading dash, no fragment, and
  **no credentials inside the URL**), takes the destination
  as a trusted S-013 `Path`, and builds its argv itself.
  Creation is S-049's all-or-nothing shape: clone first,
  row after (default branch read from the clone's HEAD),
  a failed clone leaves neither directory nor row. **The
  token is never logged**: a private import's token travels
  only in the child process's environment, answered to
  git's prompts by an askpass script that contains variable
  names, never the secret; audit and error messages name
  only the source host. Battery `tests/test_repo_import.py`:
  **6 passed / 0 failed**, including a real `git daemon`
  round-trip (import → refs resolve to the source commit),
  the URL-law battery, cleanup after a failed clone, and a
  DB-file + audit sweep proving the token appears nowhere.
  Cumulative battery: **473/473** (full recount at the
  next gate). Next: S-070 mirror storage layout.
- **S-070 DONE (2026-10-30)** — mirror storage layout:
  `samverk/mirrors.py` + schema migration 31
  (`repo_mirrors`). A mirror is an **ordinary bare repo
  plus a mirror record** — same S-013 path, same
  `repositories` row, same S-058 measurement and S-051/52
  reads, no second storage engine; the record holds only
  the source (a validated S-069 URL or an absolute local
  path to an existing repo) and the sync outcome.
  `create_mirror` makes the ordinary repo + record;
  `attach_mirror` / `detach_mirror` mark/unmark an existing
  repo (owner-only, one source at a time, detaching never
  touches content). `sync_mirror` converges the mirror
  through the dedicated fetch seam (`run_git_fetch_from`,
  landed with S-069 — generic `fetch` stays refused under
  S-014) and **records success and failure alike**
  (`last_sync_at` / `last_status` / `last_detail`); a
  failed sync leaves existing content untouched and
  readable. Battery `tests/test_mirrors.py`: **6 passed /
  0 failed**, including local-source convergence across a
  second commit and a `git daemon` URL sync. Cumulative
  battery: **479/479** — full counted run on this VM at
  this slice, verifying the whole run's arithmetic
  (S-067…S-070). Next: S-071 consistency checker.
- **S-071 DONE (2026-10-30)** — consistency checker:
  `samverk/consistency.py` — a read-only fsck-style sweep
  reconciling rows ↔ disk ↔ LFS objects: a row whose bare
  repo is missing or not bare is named, a disk repo with no
  row is named (never adopted), dangling fork/template
  lineage and orphan mirror records are named, and every
  LFS object is checked for its fan-out path and re-hashed
  against its oid. **Drift is reported, never silently
  fixed** — the battery plants stray + corrupt drift,
  snapshots the repos tree, and proves the sweep changes
  nothing. Battery `tests/test_consistency.py`: **6 passed /
  0 failed**. Cumulative battery: **485/485** (full recount
  at the S-076 gate). Next: S-072 commit graph caches.
- **S-072 DONE (2026-10-30)** — commit graph caches:
  `samverk/graph_cache.py` + schema migration 32
  (`repo_graph_cache`). Derived data (commit count,
  contributor list, branch/tag counts) is computed only in
  `refresh` — the off-path entry, walking `git log --all`
  once — and served by `cached_stats`, which never walks:
  it compares the stored **refs fingerprint** (SHA-256 over
  every ref name + oid) against the live refs and answers
  None when stale, exactly as when absent. `invalidate` is
  the push path's explicit drop. An empty repo refreshes to
  an honest zero. Battery `tests/test_graph_cache.py`:
  **5 passed / 0 failed**, including a push moving a ref
  making the cache stale by fingerprint alone. Cumulative
  battery: **490/490** (full recount at the S-076 gate).
  Next: S-073 large-repository budgets.
- **S-073 DONE (2026-10-30)** — large-repository budgets:
  `samverk/repo_budgets.py` — the reference repo shape is
  defined in code (1,000 commits / 2,000 blobs), clone
  budgets are stated per hardware class, and
  `measure_local_clone` times a clone through the S-055
  seam against the budget of the class it ran on. Measured
  on this VM (x86-64): the full reference clone lands
  inside its 30 s budget (battery-fast in practice).
  **Pi-class is NOT PROVEN** — its 60 s budget is stated,
  and Part XXI/XXII own running this measurement there.
  **Flaw found by this slice's work and fixed in-slice:**
  git's local clone hardlinks object files by default, so
  a clone shared inodes with its source — S-055's fork
  independence and this slice's measurement both require a
  real copy; `run_git_clone_local` now passes
  `--no-hardlinks` (fork/template/proc batteries re-run
  green after the fix). Battery
  `tests/test_repo_budgets.py`: **3 passed / 0 failed**.
  Cumulative battery: **493/493** (full recount at the
  S-076 gate). Next: S-074 repository backup primitive.
- **S-074 DONE (2026-10-30)** — repository backup primitive:
  `samverk/repo_backup.py` — a single-repo export is a
  `git bundle` file (`--all`, verified with `bundle verify`
  after creation; an unverifiable bundle is deleted, never
  reported) plus a metadata JSON (`samverk-repo-export/1`:
  row fields, refs, measured size, bundle SHA-256 + bytes).
  Owner-or-admin only; an existing export is never
  overwritten silently. `bundle` (and `fsck`, for S-075)
  joined S-014's allowlist with reasons. **Battery-found
  behaviour, handled in-slice:** git refuses an empty
  bundle, so an empty repo is refused by name
  (`repo_empty`) instead of faking a backup that restores
  to nothing. Battery `tests/test_repo_backup.py`:
  **5 passed / 0 failed**, including a stock-git clone from
  the bundle restoring HEAD exactly. Cumulative battery:
  **498/498** (full recount at the S-076 gate). Next:
  S-075 corruption behaviour.
- **S-075 DONE (2026-10-30)** — corruption behaviour:
  `samverk/repo_health.py` — the one health seam.
  `assess_repository` answers missing / not_a_repository /
  empty / healthy / damaged as distinct verdicts (empty is
  a sound repo waiting for a first push, never a synonym
  for damage); damage is proven by `git fsck --full`
  (admitted to S-014's allowlist for this slice) plus ref
  listing, and the report carries fsck's own first line.
  `ensure_readable` raises `RepoDamagedError` for callers
  that need the exception shape. Nothing here repairs —
  repair is restore-from-backup (S-074), a deliberate act.
  Battery `tests/test_repo_health.py`: **6 passed /
  0 failed**, including the literal acceptance —
  corruption injection (bit-flipped and truncated loose
  objects, a damaged HEAD) reads damaged at this seam and
  errors at the S-051 object seam, never empty content.
  Cumulative battery: **504/504** (full recount at the
  gate below). Next: S-076 Part III gate.
- **S-076 DONE (2026-10-30) — PART III GATE.** Gate battery
  `tests/test_git_core_battery.py`: **6 passed / 0 failed**,
  striking the *assembled* Part III system: stock-git
  plumbing interop (rev-parse / clone agree with S-051/52's
  seams), the 10-thread atomic-ref race at gate scale
  (exactly one winner), S-051's 10k-object acceptance
  re-verified (10,000 batch reads), corruption named by
  every seam, and the cross-slice agreement test
  (consistency ↔ health ↔ graph cache ↔ backup on one
  instance; an unregistered-but-sound repo is drift *and*
  empty, not damaged). Full counted run at the gate on
  this VM: `python3 -m unittest discover -s tests` →
  **510 passed / 0 failed**. **Open findings, named:**
  (1) Pi-class / laptop clone budgets (S-073) are stated
  but **NOT PROVEN** on those classes — Part XXI/XXII own
  their proof; (2) transports (HTTP/SSH wire) are Part IV —
  the gate proves plumbing interop locally, not yet over
  the wire; (3) everything banked sits on local `main`
  only — **no GitHub push**: pushes stay gated on
  Volmarr's explicit word. **Part III is complete.**
  Next: Part IV — Git Transports, opening at S-077 smart
  HTTP advertisement.
- The classified inventory of Volmarr's original repos (the mirror
  fixture for Part XVII) lives at `~/workspace/forgejo-backup/` — kept
  outside this repo; its 17 UNCERTAIN-classified repos each need
  Volmarr's word before mirroring.

## Session log

- **2026-10-29** — Founding. Repo created by Volmarr (LICENSE + stub
  README with his approved description). By Yrsa: research scaffold
  (44 empty files + INDEX), tentative README developed from his stub
  (his title and description preserved verbatim at the head), massive
  roadmap authored after public-source study of GitHub's feature
  surface (docs.github.com product/security documentation; git protocol
  references), and this map seeded. All pushed and remote-verified.
- **2026-10-29 (later)** — Two founding amendments by Volmarr's word:
  cross-platform as founding law (research file 45, roadmap virtue 6,
  new Part XXII, S-405–S-416 — roadmap now 416 slices / 22 parts) and
  the Cyber-Viking design law (research file 46; Part XX binds the
  design warband by office and the Book XIV ship gate as acceptance;
  README and this map carry the plain statement). Corpus now 46 study
  files. Pushed and remote-verified.
- **2026-10-29 (campaign opens)** — Volmarr's go-ahead ~21:39 EDT.
  Part I studies 31/35/42/07 completed as genuine clean-room studies;
  **S-001 DONE** (threat model ratified). Work proceeds on branch
  `yrsa/samverk-part1`; banking to main is the coordinator's step,
  verified by ls-remote.
- **2026-10-29 (opening run)** — S-002…S-008 built and banked in one
  run, each with its counted battery green (cumulative 56 passed /
  0 failed on Linux x86-64, this VM): skeleton + platform seam,
  secrets law + SQLite factory, scrypt password hashing, constant-time
  compare + login throttle, session tokens, audit hash chain +
  verifier + CLI, taxonomy v1 enforced at the emitter. README never
  touched. Platform proof cells beyond this machine remain
  **NOT PROVEN** (Part XXII). Next slice: S-009.
- **2026-10-30 (keeper run)** — No live worker was found (last commit
  ~3 h old, no Samverk process, worktrees clean at a9490e2), so the
  keeper resumed the campaign itself per the keeper law: baseline
  re-verified from the tree (56/56), then **S-009 DONE** and banked
  locally on `yrsa/samverk-part1` (73/73 cumulative). GitHub push
  NOT done — pushes stay gated on Volmarr's explicit word per the
  keeper's binding laws. The same keeper run continued slice after
  slice: **S-010 DONE** (85/85 cumulative), then **S-011 DONE**
  (96/96 cumulative), then **S-012 DONE** (106/106 cumulative) —
  see their entries above. Campaign position at this run's end:
  S-001…S-012 DONE, next slice S-013. Integration note: the four
  slices banked in this run sit on `yrsa/samverk-part1` and were
  fast-forwarded to local `main` in the same run (the campaign's
  established pattern); no GitHub push was made.
- **2026-10-30 (keeper run, Part I closed)** — No live worker was
  found (previous run's last commit ~11 min old, no Samverk
  process, clean tree), so the keeper resumed from S-013 and
  built slice after slice to the end of Part I: **S-013**
  (116/116), **S-014** (124/124), **S-015** (133/133), **S-016**
  (138/138), **S-017** (143/143), **S-018** (150/150), **S-019**
  (157/157), **S-020** (165/165), **S-021** (173/173), **S-022**
  (182/182), **S-023** (claims register), the S-015 TLS
  end-to-end hardening (4ee3b61), and the **S-024 Part I gate**
  at a fresh counted **187 passed / 0 failed** with open
  findings named in the gate entry above. Four flaws were
  found by batteries and fixed inside their own slices (the
  rev-parse `--git-dir` query distinction, the `csrf_token`
  log-redaction leak, the `a@.com` empty-label parse, and the
  previously unexercised TLS wrap). All work banked locally on
  `yrsa/samverk-part1` and fast-forwarded to local `main`
  (first banked as 08ec155; amended once for this log); **no GitHub push** — pushes stay
  gated on Volmarr's word. (Head note: the gate commit was
  amended once to carry this log entry, so its hash differs
  from the one first printed here; tree content is unchanged.)
  Next: Part II, S-025 registration.
- **2026-10-30 (keeper run, Part II opened)** — Previous keeper
  run had closed Part I at 01:37 EDT (head a44bc79, clean tree,
  its session log written, no process live), so this run
  resumed from the map's named next slice and built four Part
  II slices in the established pattern: **S-025** registration
  (199/199), **S-026** email verification — token road +
  operator road, taxonomy append-only +2 events (209/209),
  **S-027** login/logout (216/216; the battery found
  `SessionStore.revoke` double-counting an already-revoked
  token — fixed in the S-006 seam in-slice), and **S-028**
  password change/reset (226/226). All banked locally on
  `yrsa/samverk-part1` and fast-forwarded to local `main`;
  **no GitHub push** — pushes stay gated on Volmarr's word.
  Next slice: S-029 profiles.
- **2026-10-30 (keeper run)** — Previous run had banked S-028
  at 01:47 EDT (head ce69f92, clean tree, no process live), so
  this run resumed at the map's named next slice and built
  **S-029** profiles (236/236) and **S-030** SSH keys (244/244)
  in the established pattern. Taxonomy append-only +1 event
  (auth.profile.update, 40 total). All banked locally on
  `main`; **no GitHub push** — pushes stay gated on Volmarr's
  word. Next slice: S-032 personal access tokens.
- **2026-10-30 (keeper run)** — Previous run had banked S-031
  at 01:55 EDT (clean tree, no process live), so this run
  resumed at the map's named next slice and built **S-032**
  personal access tokens (260/260), then **S-033** fine-grained
  tokens (269/269), then **S-034** token management UI
  (276/276), all in the same run. Banked locally on `main`;
  **no GitHub push** — pushes stay gated on Volmarr's word.
  Next slice: S-035 two-factor TOTP enrolment.
- **2026-10-30 (keeper run)** — Previous run had banked S-034
  at 02:12 EDT (clean tree, no process live), so this run
  resumed at the map's named next slice and built **S-035**
  TOTP enrolment (286/286), **S-036** sudo mode (292/292),
  **S-037** recovery codes (298/298; taxonomy append-only
  +2 events, 42 total), and **S-038** two-factor enforcement
  policy (305/305), each with its counted battery green and
  the full suite re-counted at this run's end: **305 passed /
  0 failed**. All banked locally on `main`; **no GitHub
  push** — pushes stay gated on Volmarr's word. Next slice:
  S-039 passkeys/WebAuthn.
- **2026-10-30 (keeper run)** — Previous run had banked S-038
  at 02:24 EDT and its run record closed at 02:25 EDT (clean
  tree, no process live), so this run resumed at the map's
  named next slice and built **S-039** passkeys/WebAuthn
  (318/318; taxonomy append-only +3 events, 45 total),
  **S-040** session management (325/325), **S-041**
  new-sign-in notification (331/331; taxonomy +1, 46 total),
  and **S-042** account rename with tombstones (338/338;
  taxonomy +1, 47 total) — each with its counted battery
  green and the full suite re-counted at this run's end:
  **338 passed / 0 failed**. All banked locally on `main`;
  **no GitHub push** — pushes stay gated on Volmarr's word.
  Next slice: S-043 account deletion.
- **2026-10-30 (keeper run, Part III continued)** — Previous
  run had banked S-054 at 03:06 EDT (clean tree, no process
  live), so this run resumed at the map's named next slice
  and built **S-055** forking (400/400), **S-056** repository
  deletion (404/404), **S-057** repository transfer (408/408),
  and **S-058** size accounting (412/412) — taxonomy
  append-only +1 event (55 total, `repo.fork`). One flaw was
  caught by a battery mid-banking (the S-056 execution path
  referenced S-057's table before that slice's migration
  existed) and was fixed in-slice, with the cleanup correctly
  sequenced into S-057. Full suite re-counted fresh at this
  run's end: **412 passed / 0 failed**. All banked locally on
  `main`; **no GitHub push** — pushes stay gated on
  Volmarr's word. Next slice: S-059 GC scheduling.
- **2026-10-30 (keeper run, Part II closed)** — Previous run
  had banked S-042 at 02:41 EDT (clean tree, no process
  live), so this run resumed at the map's named next slice
  and built **S-043** deletion (342/342), **S-044**
  suspension (345/345), **S-045** identity-linking shape
  (350/350), **S-046** lookalike defence (355/355; two
  battery-found flaws fixed in-slice), **S-047** login
  history (360/360), and the **S-048 Part II gate**
  (368/368) — taxonomy append-only +7 events across the
  run (54 total). Full suite re-counted fresh at the gate:
  **368 passed / 0 failed**. All banked locally on `main`;
  **no GitHub push** — pushes stay gated on Volmarr's word.
  Next: Part III, S-049 bare repository creation.
- **2026-10-30 (keeper run, LFS block)** — Previous run had
  banked S-058 + the fork-clone fix at 03:25 EDT (clean tree,
  no process live), so this run resumed at the map's named
  next slice and built **S-059** GC scheduling (416/416),
  **S-060** LFS object store (422/422), **S-061** LFS batch
  API (428/428), and **S-062** LFS locking (434/434) — each
  with its counted battery green and the full suite
  re-counted at every slice. The git-lfs client interop
  acceptances of S-061/S-062 were proven for real against
  stock git-lfs 3.6.1 (push/pull round-trip; lock/locks/
  unlock), with the client binary kept at
  `~/workspace/.tools/git-lfs` because this VM's system
  layer does not persist apt installs between sessions.
  All banked locally on `main`; **no GitHub push** —
  pushes stay gated on Volmarr's word. Next slice: S-063
  archive downloads.
- **2026-10-30 (keeper run, Part III continued)** — Previous
  run had closed its session log at 03:45 EDT (head 5be20b2,
  clean tree, no process live), so this run resumed at the
  map's named next slice and built **S-063** archive
  downloads (440/440), **S-064** repository templates
  (446), **S-065** empty-repository state (450), and
  **S-066** repository settings (456/456) — each with its
  counted battery green and a full counted run at the
  run's end: **456 passed / 0 failed**. S-014's allowlist
  grew by `archive`, `mktree`, and `commit-tree`, each
  with its reason recorded in `samverk/proc.py`, and
  `proc` gained the streamed-spawn and `env_extra` seams
  those slices needed. All banked locally on `main`;
  **no GitHub push** — pushes stay gated on Volmarr's
  word. Next slice: S-067 server-side hooks seam.
- **2026-10-30 (keeper run, Part III continued)** — Previous
  run had banked S-066 at 03:59 EDT (clean tree, no process
  live), so this run resumed at the map's named next slice
  and built **S-067** hooks seam (462), **S-068**
  repository quotas (467), **S-069** import by clone URL
  (473), and **S-070** mirror storage layout (479) — each
  with its counted battery green and a full counted run at
  the run's end: **479 passed / 0 failed**. S-014's law
  grew the dedicated clone-remote and fetch seams (generic
  `clone`/`fetch` stay refused, per its battery), with the
  import token carried only in an askpass environment and
  proven absent from the DB file and audit log. All banked
  locally on `main`; **no GitHub push** — pushes stay
  gated on Volmarr's word. Next slice: S-071 consistency
  checker.
