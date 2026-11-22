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
| C-09 | An unmodified git client clones, pushes, and pulls (SSH and smart HTTP) | PROVEN (scoped: stock-git smart-HTTP and SSH forced-command harnesses counted green; the real-sshd cell is still skipped on the proving host and remains NOT PROVEN, owned by Part XXII) | tests/test_transport_battery.py, tests/test_part_iv_gate.py; re-judged at S-399 (F-01) |
| C-10 | The server runs on Windows and macOS, and on ARM down to a Raspberry Pi | NOT PROVEN (Linux x86-64 proven; Pi-class performance budgets MEASURED on a Raspberry Pi 5 at S-395, docs/perf-verification-s395.md; Windows, macOS and the full matrix unproven) | Part XXII (cross-platform proof matrix, S-405..S-416) owns this proof; re-judged at S-399 (F-02) |
| C-11 | The face is designed under the Cyber-Viking Visual Design Lawbook and passes its ship gate | PROVEN (scoped: the Book XIV ship gate counted PASSED at the Part XX gate, S-392, over the finished UI machinery S-381..S-391; serving that face end-to-end waits on the live composition, F-10) | tests/test_part_xx_gate.py; re-judged at S-399 (F-03), document: docs/PART_XX_GATE.md |
| C-12 | Samverk mirrors Volmarr's original repositories onto his own machines and keeps them current | PROVEN (scoped: mirroring machinery, freshness law and restore proof counted green at the Part XVII gate, S-344; a continuously running live fleet is an operational state, not a test result) | tests/test_part_xvii_gate.py; re-judged at S-399 (F-04), document: docs/PART_XVII_GATE.md |

## Part XV claims (S-312 extension)

Part XV (security scanning & assurance, S-289..S-311)
made its own claims as it landed. The register extends
over every one of them here, in the same law: PROVEN
only with the slice's own counted battery named, and
the Part XV gate battery (tests/test_part_xv_gate.py)
re-checks these rows mechanically on every run.

| ID | Claim (Part XV, in substance) | Status | Evidence / owner |
|---|---|---|---|
| C-13 | Secret scanning patterns v1 (S-289): the major public token formats are detected by shape, from public documentation of their shapes | PROVEN | tests/test_secret_scanning.py |
| C-14 | Generic secret detection (S-290): unshaped secrets are judged by entropy and context, with a measured false-positive rate published from a labelled corpus, not vibes | PROVEN | tests/test_generic_secret_detection.py |
| C-15 | Scan on push (S-291): every accepted push is scanned across its full introduced history and findings create alerts | PROVEN | tests/test_push_scanning.py |
| C-16 | Push protection (S-292): a push containing a detected secret is refused at the receive gate, naming the file and pattern class, never echoing the secret | PROVEN | tests/test_push_protection.py |
| C-17 | Push-protection bypass (S-293): permitted roles may bypass only with a stated reason, and the bypass is an alert plus an audit event visible to owners | PROVEN | tests/test_push_protection_bypass.py |
| C-18 | Secret alert lifecycle (S-294): an alert resolves as revoked, false positive or used-in-test with resolver and reason recorded, and can reopen | PROVEN | tests/test_secret_alert_lifecycle.py |
| C-19 | Custom patterns (S-295): org and instance patterns take a dry-run against history before activation | PROVEN | tests/test_custom_patterns.py |
| C-20 | Validity checks seam (S-296): a secret's validity defaults to unknown offline and is displayed as unknown | PROVEN | tests/test_secret_validity.py |
| C-21 | Dependency graph (S-297): manifests are parsed on push into a dependency table per repository | PROVEN | tests/test_dependency_graph.py |
| C-22 | Advisory data (S-298): vulnerability data is a bundled dated snapshot and its age is displayed wherever alerts are shown | PROVEN | tests/test_advisory_data.py |
| C-23 | Dependency alerts (S-299): graph crossed with advisory data gives alerts with severity, affected range, and a fixed version when known | PROVEN | tests/test_dependency_alerts.py |
| C-24 | Advisory refresh (S-300): the snapshot updates by operator action or scheduled fetch where the instance has network, and offline staleness is shown honestly | PROVEN | tests/test_advisory_refresh.py |
| C-25 | Dependency review on PRs (S-301): a pull request's manifest changes are summarised with new vulnerabilities flagged, as a check branch rules can require | PROVEN | tests/test_dependency_review.py |
| C-26 | Code scanning ingestion (S-302): SARIF uploads are validated against the SARIF schema and stored per commit | PROVEN | tests/test_code_scanning.py |
| C-27 | SARIF fingerprinting and dedup (S-303): the same finding across runs is one alert, with new and fixed transitions computed per branch | PROVEN | tests/test_code_scanning_alerts.py |
| C-28 | Code scanning alerts UI (S-304): the alert list and detail show rule help, locations and dismissal reasons, with PR annotations for findings on changed lines | PROVEN | tests/test_code_scanning_ui.py |
| C-29 | Signed-commit verification (S-305): GPG and SSH signatures are verified on ingest and display, and badges say verified, partial or unverified in words, with the signer shown, never a bare green tick | PROVEN | tests/test_commit_signatures.py |
| C-30 | Vigil mode (S-306): an account under vigil has a commit claiming its identity but signed by another key displayed as unverified, loudly | PROVEN | tests/test_vigil_mode.py |
| C-31 | Security tab (S-307): each repository has one security home for its secret, dependency and code-scanning alerts with counts and states | PROVEN | tests/test_security_tab.py |
| C-32 | Security overview (S-308): the org and instance rollup shows open alerts by severity and repositories affected, counts only, no code content | PROVEN | tests/test_security_overview.py |
| C-33 | Audit log UI (S-309): repo, org and instance views over the audit chain are filterable and exportable, with chain verification status shown | PROVEN | tests/test_audit_log_ui.py |
| C-34 | Security advisories (S-310): maintainers draft an advisory in private, coordinate a fix, then publish it with the alert linkage | PROVEN | tests/test_security_advisories.py |
| C-35 | Adversarial battery (S-311): the suite attacks the scanners, the SARIF judge and the signature checks, and reports its misses honestly | PROVEN | tests/test_adversarial_battery.py |

## Rules of the register

- A claim enters this register the day it is made in public.
- PROVEN requires a counted battery that ran green; a claim
  about a document requires the document to exist and say it.
- A scoped PROVEN names its scope in the row — the unproven
  remainder is part of the claim's honest state, not fine print.
- When a NOT PROVEN claim is proven, its row flips in the same
  commit as the proof, and the project map records it.

## Final register (S-399)

At 398/416 every remaining public claim -- the part gates
XVI-XX, the Part XXI counted artifacts, the cross-cutting
claims, the README's dated snapshots, and the README items
only Volmarr can settle -- was judged against the tree.
The law module is `samverk/claims_register_final.py`; its
battery is `tests/test_claims_register_final.py`; the
counted log ships at `docs/claims-register-final-s399.md`.
Statuses: PROVEN / PROVEN (scoped) rest on the named
counted evidence; NOT PROVEN names its owner; OPEN names
Volmarr (the README is never edited by this campaign);
HISTORICAL marks a dated snapshot read as history.

| ID | Claim (source, in substance) | Status | Evidence / owner |
|---|---|---|---|
| F-01 | C-09 re-judged: unmodified git client over SSH and smart HTTP (README virtue 4) | PROVEN (scoped: real-sshd cell remains NOT PROVEN, Part XXII) | tests/test_transport_battery.py, tests/test_part_iv_gate.py |
| F-02 | C-10 re-judged: Windows, macOS, ARM down to a Raspberry Pi (README virtue 6) | NOT PROVEN | Part XXII (S-405..S-416); Pi-class budgets measured at S-395, docs/perf-verification-s395.md |
| F-03 | C-11 re-judged: Cyber-Viking face passes its ship gate (README) | PROVEN (scoped: gate over the UI machinery; live serving is F-10) | tests/test_part_xx_gate.py, document: docs/PART_XX_GATE.md |
| F-04 | C-12 re-judged: mirrors of Volmarr's originals kept current (README) | PROVEN (scoped: machinery and freshness law; live fleet operation is operational, not a test result) | tests/test_part_xvii_gate.py, document: docs/PART_XVII_GATE.md |
| F-05 | Part XVI: native CI takes a sample repo from push to a green check on a PR | PROVEN | tests/test_part_xvi_gate.py |
| F-06 | Part XVIII: fresh install from the written guide alone reaches a working instance (the gate record itself states the walk ran on x86-64, not Pi) | PROVEN | tests/test_part_xviii_gate.py, document: docs/PART_XVIII_GATE.md |
| F-07 | S-396: an RC instance with real-shaped data upgrades per S-357 and verifies | PROVEN | tests/test_upgrade_drill.py, document: docs/upgrade-drill-s396.md |
| F-08 | Part XIX: the Samtal seam -- linked identity, 90-cell permissions matrix, kill switch | PROVEN | tests/test_part_xix_gate.py, document: docs/PART_XIX_GATE.md |
| F-09 | S-394: the v1.0 acceptance battery is assembled (the v1.0 tag, S-401, is not claimed) | PROVEN | tests/test_battery_v1.py |
| F-10 | The feature services composed into one complete running forge served by samverk/server.py (README 2026-11-13 update, still accurate: only /, /healthz, /admin/status are routed) | NOT PROVEN | S-402 (founder usability walk) and the successor roadmap own this proof |
| F-11 | The full suite is green | NOT PROVEN | Part XXI pin-refresh work (final census S-404); the counted master run stands at 6129 ran / 15 named stale-pin failures / 4 named skips, docs/COUNTED_MASTER_RUN.md |
| F-12 | S-397: operator, admin and user guides walked by a fresh reader against a live instance | PROVEN | tests/test_docs_completeness.py, document: docs/documentation-completeness-s397.md |
| F-13 | S-398: all 46 research studies complete or honestly open (43 complete, 3 open owned by S-403 -- 'all complete' is not claimed) | PROVEN | tests/test_research_corpus_audit.py, document: docs/research-corpus-audit-s398.md |
| F-14 | Sovereignty: native systemd units ship, data in the owner's directories, no Docker (README virtue 3; Linux-scoped) | PROVEN | document: docs/SYSTEMD_UNITS.md; deploy/systemd/ unit files; C-08 tree scan in tests/test_claims_register.py |
| F-15 | Samverk is AGPL-3.0 free software (README licence section) | PROVEN | document: LICENSE |
| F-16 | The README's dated snapshots (founding Status; 2026-11-06 at 152/416; 2026-11-13 at 304/416) read as current position | HISTORICAL | Dated and superseded in place; the current position is 398/416, Parts I-XX through their gates; this register is the current authority |
| F-17 | README wordings only Volmarr can settle: the founding Status bullet ('46 study areas, each an empty file' -- false today, S-398 counted all 46 populated) and the first paragraph's 'Samtel' for Samtal | OPEN | Volmarr -- recorded here, never edited and never silently passed; no Part owns a README edit |
