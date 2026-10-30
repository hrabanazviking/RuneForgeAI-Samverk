# Samverk — Claims Register (S-023)

Every security claim Samverk makes in public — in the README
first of all — is listed here with its honest state: **PROVEN**,
with the counted battery that proves it, or **NOT PROVEN**, with
the roadmap part that owns its proof. A claim may be *scoped*:
proven for the surface that exists today, with the remainder
named. The battery (`tests/test_claims_register.py`) checks
this register mechanically on every run: every PROVEN row must
name a real test file, every NOT PROVEN row must name its
owning part, and the register must cover each tracked claim
anchor below.

| ID | Claim (README, in substance) | Status | Evidence / owner |
|---|---|---|---|
| C-01 | Credentials are stored so a database leak is not a credential leak | PROVEN (scoped: the credential material Part I stores — passwords, session tokens, instance secrets and keys) | tests/test_passwords.py, tests/test_sessions.py, tests/test_secrets.py, tests/test_keys.py, tests/test_security_battery.py |
| C-02 | The threat model is written before the features | PROVEN | document: research/31-threat-model.md (S-001, ratified before S-002's first code) |
| C-03 | The audit log detects tampering with its history | PROVEN | tests/test_audit.py, tests/test_security_battery.py |
| C-04 | State-changing requests fail closed against cross-site forgery | PROVEN | tests/test_http_security.py, tests/test_security_battery.py |
| C-05 | Stored user content cannot break out as script (output-escaping seam + CSP) | PROVEN (scoped: the seam and the policy; no UI pages exist yet for it to protect) | tests/test_escaping.py, tests/test_csp.py |
| C-06 | Client errors leak no stack traces, paths, or secrets, and correlate to server logs by opaque id | PROVEN | tests/test_errors.py, tests/test_log_redaction.py |
| C-07 | Samverk requires no third-party runtime dependency and no Samtal to run | PROVEN | tests/test_dependencies.py (import scan: stdlib + intra-package only) |
| C-08 | No Docker, ever — native installs only | PROVEN (as construction: no container artifacts exist in this tree; the battery keeps it so) | tests/test_claims_register.py (tree scan) |
| C-09 | An unmodified git client clones, pushes, and pulls (SSH and smart HTTP) | NOT PROVEN | Part III (git core & transport) owns this proof |
| C-10 | The server runs on Windows and macOS, and on ARM down to a Raspberry Pi | NOT PROVEN (proven only on Linux x86-64, this VM) | Part XXII (cross-platform proof matrix) owns this proof |
| C-11 | The face is designed under the Cyber-Viking Visual Design Lawbook and passes its ship gate | NOT PROVEN (no UI exists yet) | Part XX (design warband) owns this proof |
| C-12 | Samverk mirrors Volmarr's original repositories onto his own machines and keeps them current | NOT PROVEN | Part XVII (mirroring) owns this proof |

## Rules of the register

- A claim enters this register the day it is made in public.
- PROVEN requires a counted battery that ran green; a claim
  about a document requires the document to exist and say it.
- A scoped PROVEN names its scope in the row — the unproven
  remainder is part of the claim's honest state, not fine print.
- When a NOT PROVEN claim is proven, its row flips in the same
  commit as the proof, and the project map records it.
