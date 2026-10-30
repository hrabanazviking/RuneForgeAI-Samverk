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

- **Phase: Part II underway** (Part I gate passed 2026-10-30).
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
