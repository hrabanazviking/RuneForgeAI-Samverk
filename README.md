# RuneForgeAI-Samverk

Samverk is the together-work, your own forge that stands alone yet can nestle inside Samtel. It speaks the old Git tongue, opens its doors to your hand, and lets your village's talk become work—soft, yours to reshape, whether it lives by itself or beside the longhouse fire.

# Samverk — the together-work, in founding

**Samverk** (Old Norse *samverk*: work done together, joint labour) is a
**clean-room, open-source version-control application**: an extremely robust,
highly secure forge with the feature-set GitHub's users know — repositories,
issues, pull requests, code review, organizations, search, releases, and the
rest — studied from GitHub's *public behaviour and documentation* and built
from scratch as our own work. It copies **no** GitHub code, **no** assets,
**no** proprietary design. What GitHub *does* is public fact; how Samverk
does it is Samverk's own engineering.

Named by the Skald of Mythic Engineering and chosen by Volmarr, 2026-10-29 —
*Samtal* is the together-talk, *Samkoma* is the together-gathering, and
*Samverk* is the together-work: the place where the village's talk becomes
the village's work.

---

![https://github.com/hrabanazviking/RuneForgeAI-Samverk/blob/main/Lets_Build_Our_Own_App_1.png](https://github.com/hrabanazviking/RuneForgeAI-Samverk/blob/main/Lets_Build_Our_Own_App_1.png)

---

## Why it exists

Volmarr tried the self-hosted forges on offer and was fought at every door —
a forge whose own admin could not find the control to mint a token is a
forge that has failed its founding duty. Samverk's founding virtues are the
answer to that failure:

1. **User-friendliness is law.** Every everyday control must be findable by
   its owner without a manual, a forum post, or a prayer. If Volmarr cannot
   find it, it does not exist — however clever the code beneath it.
2. **Security is the spine, not a coat of paint.** The threat model is
   written before the features; credentials are stored so a database leak is
   not a credential leak; every security claim is proven by a test or
   honestly marked **NOT PROVEN**.
3. **Sovereignty.** Samverk runs on its owner's own machines, natively —
   **no Docker, ever** — under a systemd unit, with its data in the owner's
   own directories. No account on anyone else's computer, no landlord.
4. **Standard git, standard habits.** An unmodified git client clones,
   pushes, and pulls against Samverk (SSH and smart HTTP). Workflows shaped
   like the ones GitHub taught the world carry over, so nobody relearns
   their craft to come home.
5. **Standalone first, Samtal-hearted.** Samverk is a complete application
   on its own. It can *also* be woven into **Samtal** (Volmarr's sovereign
   village chat) as the village's code-and-file-sharing heart — but the seam
   is a seam: Samverk never requires Samtal, and Samtal never swallows it.
6. **Cross-platform, completely.** Samverk works on all operating systems
   and all kinds of hardware: the server runs on Linux, Windows, and
   macOS, on x86-64 and ARM down to a Raspberry Pi — and the web face is
   reachable from any modern browser on any device. Portability is a
   founding law, proven platform by platform, never assumed.

Samverk's face is designed under Volmarr's Cyber-Viking Visual Design
Lawbook — *really nice* is a founding requirement, not a garnish.

Samverk also inherits a standing duty: **the backup of Volmarr's own work.**
It mirrors his original repositories from GitHub onto his own machines and
keeps them current, so his creations never live only under a landlord's roof.

## Status

**Founding phase (2026-10-29).** This repository currently holds:

- the AGPL-3.0 `LICENSE` (placed by Volmarr at the founding),
- `research/` — the clean-room research corpus: 46 study areas, each an
  empty file awaiting its study, with `research/INDEX.md` naming the
  question each must answer,
- `docs/SAMVERK_MASSIVE_ROADMAP.md` — the massive slice roadmap for the
  whole build,
- `PROJECT_MEMORY_MAP.md` — the living map of this project, per the Forge
  Protocol,
- the `samverk/` package and its counted test batteries — Part I of the
  roadmap (the security spine, S-001 onward) is built and proven slice
  by slice; see the project map for the current position,
- `docs/CLAIMS_REGISTER.md` — every security claim in this README,
  mapped to the battery that proves it or honestly marked NOT PROVEN
  with the roadmap part that owns its proof.

What is proven will be counted; what is not proven will be named
NOT PROVEN, in this README and everywhere else.

## Engineering progress update — 2026-11-06

> **Dated inspection of `main` before this documentation change:** [`421db0ef`](https://github.com/hrabanazviking/RuneForgeAI-Samverk/commit/421db0ef53d7aa9b56ba8f934b660ee84e15ded4), committed 2026-11-03 UTC. This section updates the founding-era **Status** snapshot above without erasing that historical record. It distinguishes code present, tests reported, and production readiness.

### At a glance

| Indicator | Verified repository state |
|---|---|
| Development phase | **Part VII — Pull Requests & Code Review**, active; roadmap slices through **S-152** are committed. The next planned slice is **S-153 (merge commit)**. |
| Roadmap position | **152 of 416 numbered slices** (about **36.5% by slice count**) across 22 parts. Slice count is **not** a measure of feature completeness, effort remaining, or readiness to deploy. |
| Completed part gates | Parts **I–VI**, covering security foundations, identity, Git core, transports, repository reading, and issues. Part VII's gate is **S-168** and has **not** landed. |
| Code and tests | The inspected default-branch tree contains **135 files in `samverk/`** and **150 files in `tests/`** (including package markers); `pyproject.toml` declares **Python >=3.11**, version **0.1.0**, and **no third-party runtime dependencies**. |
| Last recorded full-suite result | The **S-152 commit reports 1,057 passed, 1 skipped, 0 failed** (plus five passing subtests), verified by the development keeper from its test log. The skipped cell is **S-095 real-`sshd` interoperability**. This README review did **not** rerun the suite or independently certify that result. |
| Public project activity | At inspection: **no repository issues, pull requests, GitHub Actions workflow runs, or published releases**. There is no checked-in `.github/workflows/` directory. These facts describe GitHub-hosted tracking, not the amount of development done through direct commits. |
| Maturity | **Substantial modular backend implementation, not a production-ready hosted forge.** The executable HTTP server still only exposes `/` and `/healthz`; most feature services and HTML-rendering helpers are not yet routed into a complete user-facing web application. |

### What is implemented in the source tree

The following describes **code and focused test coverage** present on `main`. A module and its battery do not, by themselves, prove a fully integrated production feature.

| Workstream | Present implementation and supporting evidence |
|---|---|
| Security, accounts, and identity | SQLite-backed accounts, password/session handling, token types, SSH keys, TOTP/recovery, passkey/WebAuthn logic, login controls, CSRF/CSP/TLS policies, rate limits, audit chaining, redaction, and permission checks. See `samverk/accounts.py`, `sessions.py`, `passkeys.py`, `http_security.py`, `audit.py` and their corresponding tests. Security claims are **scoped**, not an independent security certification. |
| Git core and storage | Bare-repository creation and metadata, Git object reading, refs and compare-and-swap updates, history/diffs, checks and consistency tools, repository quotas, import, backup exports, mirror primitives, and LFS storage. The code delegates Git object and pack operations to stock Git plumbing. See `samverk/repositories.py`, `objects.py`, `refs.py`, `repo_backup.py`, `mirrors.py`, and `lfs_store.py`. |
| Git transport | Modular smart-HTTP upload/receive services, protocol-v2 handling, SSH forced-command routing and key resolution, HTTP token authentication, push receive gates, hooks, transport events/auditing, and LFS APIs. Stock-Git test harnesses exercise meaningful transport paths (`tests/test_transport_battery.py`, `test_part_iv_gate.py`); the real-`sshd` cell remains skipped on the reported host. **Do not interpret these as proof of an installed, fully routed public server.** |
| Repository browsing | Repo home/tree/blob views, commit lists and details, blame, compare and diffs, markdown/media rendering, searching within repository scope, and associated rendering functions. See `samverk/repo_home.py`, `file_browser.py`, `blob_view.py`, `commit_list.py`, `diff_engine.py`, and `markdown_pipeline.py`. These are primarily **service/rendering components** rather than finished HTTP pages served from `samverk/server.py`. |
| Issues and collaboration | Shared issue/PR numbering, issue creation and transitions, comments, labels, assignees, milestones, reactions, templates and forms, search qualifiers, timeline events, moderation, transfers, and cross-references, with focused batteries in `tests/`. Part VI's gate is recorded complete. |
| Pull requests and review | Same-repository and cross-fork PR creation, draft/conversation models, changed-file views, line comments, threads and resolution, submitted reviews, freshness policies, and suggested-change patches that can create commits. See `samverk/pull_requests.py` and the `pull_request_*.py` modules. **Merge implementations and the Part VII gate remain ahead.** |

### Latest development events: S-151 and S-152

- **S-151 — CODEOWNERS** ([commit](https://github.com/hrabanazviking/RuneForgeAI-Samverk/commit/e086990009c28891f2d3a89333f318a9b9a6cadd)): a parser and base-branch matching rules identify review owners; an optional on-open hook and explicit re-sync seam add appropriate reviewers without duplicating requests. Self-requests, closed PRs, invalid owner tokens and private-repository visibility are tested. The commit reports **14 focused tests** and a keeper-verified full-suite tally of **1,041 passed / 1 skipped / 0 failed**.
- **S-152 — manual review assignment** ([commit](https://github.com/hrabanazviking/RuneForgeAI-Samverk/commit/421db0ef53d7aa9b56ba8f934b660ee84e15ded4)): individuals and team tokens may be requested as reviewers; permission checks, all-or-nothing invalid batches, dismissal history, re-requests, duplicate no-ops, audit events, and CODEOWNERS interaction are implemented. The commit reports **16 focused tests**, **175 passing tests in a combined affected-suites run**, and the **1,057 / 1 skipped / 0 failed** full-suite tally.
- **Data evolution:** these two slices introduce/extend the review-request persistence model through **SQLite migrations 56 and 57**. The documented audit-event vocabulary reaches **110 event names** after S-152.
- **Build-environment note:** preceding keeper entries describe repeated low-memory/high-load conditions and intermittent **EDQUOT** write failures, which delayed full recounts. The two later development commits explicitly report verified staging-suite results before they were pushed. Those historical host conditions are **not** evidence of a current GitHub outage or a known product-runtime failure.

### What is not finished or not yet proven

1. **The usable web application remains an integration milestone.** `samverk/server.py` has the basic health/service handlers and foundational request guards, but does not currently mount the many repository, account, issue, or PR feature services as complete HTTP routes. A module's HTML renderer is not the same as a navigable, finished browser interface. The promised Cyber-Viking UI is a later design-and-accessibility workstream.
2. **PR merge workflows are still planned.** The roadmap's next slices are **S-153 merge commit**, **S-154 squash**, **S-155 rebase**, **S-156 conflict surfacing**, **S-157 checks**, **S-158 auto-merge**, followed by branch lifecycle, permissions, review requirements and the **S-168 Part VII gate**. Do not describe these as shipped.
3. **End-to-end transport proof is incomplete.** The source contains stock-Git transport tests and an SSH routing seam, but the explicit **real `sshd`** matrix cell remains skipped. `docs/CLAIMS_REGISTER.md` still marks the broad unmodified-Git-over-SSH-and-HTTP claim **C-09 NOT PROVEN**.
4. **Cross-platform production claims are not proven.** Linux-based evidence does not establish Windows, macOS, ARM, or Raspberry Pi support. The roadmap reserves the platform matrix for **Part XXII (S-405–S-416)**, and claim **C-10** is **NOT PROVEN**.
5. **Full visual, backup-fleet and security assurance are future gates.** The Cyber-Viking design gate (**C-11**) and continuous mirroring of the owner's GitHub repositories (**C-12**) remain **NOT PROVEN** in the claims register. A tested mirror/export primitive is not proof of an installed, continuously scheduled recovery system. The presence of security tests and custom authentication/cryptographic code is not a substitute for adversarial review or deployment hardening.
6. **Public release and continuous verification are not present.** There are no published releases or GitHub Actions runs at inspection. A reproducible CI matrix, installation/deployment walkthroughs, real-host smoke tests, accessibility checks, and operational recovery exercises remain important release-readiness work.

### Documentation and verification housekeeping

- `PROJECT_MEMORY_MAP.md` presently narrates development through **S-150** in its milestone sequence, while the **`main` branch already contains S-151 and S-152**. Reconcile that living map with the later commit evidence; do not rewrite its old keeper observations as though they happened today.
- The founding **Status** statement above describes all 46 numbered research studies as empty. The inspected `research/` tree actually has **7 populated studies** (`01`, `02`, `07`, `19`, `31`, `35`, `42`) and **39 still-empty studies**. The index and roadmap remain the research agenda, not proof that every study is complete.
- `docs/CLAIMS_REGISTER.md` remains the authority for exact **PROVEN (scoped)** versus **NOT PROVEN** wording. Keep it synchronized whenever a public assertion changes; do not promote a test or promise into a blanket guarantee.
- To reproduce the stdlib `unittest` batteries on a compatible host with **Python 3.11+** and Git installed, start with `python3 -m unittest discover -s tests -v`. The test run, its actual environment, and any skips must be reported from fresh output, not inferred from an earlier commit message. The current minimal service can be inspected with `python3 -m samverk serve` and `GET /healthz`; this is **not** a full forge deployment test.

### Practical next checkpoint

**Finish and test S-153 first**, then progress through merge strategies, conflict checks and review gates toward **S-168**. In parallel, track the HTTP route-assembly gap, real-`sshd` matrix proof, reproducible CI, platform portability, design work and genuine backup automation as **separate acceptance gates**. Success means an ordinary user can install, sign in, clone, push, browse, open an issue/PR, review and merge from one coherent interface, with documented security boundaries and recoverable data. Until that end-to-end demonstration exists, Samverk should be presented as an ambitious, actively developed forge backend rather than a completed GitHub alternative.


## Development research library (2026-11-06)

Samverk's research shelf now contains **46 nonempty numbered clean-room studies** covering Git internals, authentication, permissions, collaboration, security, data storage, recovery, portability and Cyber-Viking design. An additional **18 focused implementation playbooks** translate that research into live HTTP integration, stock-Git interoperability, merge transactions, end-to-end tests, native CI, low-resource operation, deployment and release gates.

- **[Browse all 46 foundational research studies](research/INDEX.md)**.
- **[Open the 18-guide Development Research and Implementation Index](docs/development-research/INDEX.md)**.
- Start implementation with [live HTTP integration](docs/development-research/01-live-http-routing-and-composition-blueprint.md), [PR merge atomicity](docs/development-research/05-pr-merge-engine-and-atomicity-plan.md), [real user journey tests](docs/development-research/03-complete-user-journey-test-battery.md), and the [Mythic Engineering agent handoff protocol](docs/development-research/15-mythic-engineering-agent-handoff-and-proof-protocol.md).

These are **research documents and development recommendations**, not evidence that every researched capability is shipped or verified. Read the [claims register](docs/CLAIMS_REGISTER.md) for test-proven versus NOT PROVEN statements.

## Engineering progress update — 2026-11-13

> **Current dated inspection of the default `main` branch, before this README-only change:** [`cd7ff594c523`](https://github.com/hrabanazviking/RuneForgeAI-Samverk/commit/cd7ff594c523733c0f6794860d5c8c81118e1169), the keeper's **"S-304 banked — 304 of 416"** commit (2026-11-13 08:48 UTC). This **additive** snapshot supersedes the *current-position statements* in the 2026-11-06 progress section above, but preserves that earlier section as historical evidence. Findings below distinguish **code checked in**, **tests described in commits**, **publicly routed behavior**, and **release-level proof**.

### Executive status: rapid implementation, substantial integration work still ahead

| Indicator | State at the inspected commit |
|---|---|
| Roadmap position | **S-304 of S-416 banked**; **304/416 = 73.1% by numbered slice count**, with **112 slices remaining**. This is *not* a percentage of total engineering effort, user-visible completeness, test coverage, or production readiness. Some completed slices deliberately record **deferrals/refusals**, rather than shipped services. |
| Active workstream | **Part XV: Security Scanning & Assurance**. S-289–S-304 have landed; the next numbered slice is **S-305: signed-commit verification**. The Part XV completion gate, **S-312**, is not yet banked. |
| Part gates | The keeper's sequence and checked-in gate batteries place **Parts I–XIV** through their corresponding gate slices, most recently **S-288** (wiki, gists, discussions). Parts XV–XXII remain on the roadmap. These are *component/roadmap gates*, not a production deployment certificate. |
| Repository size | **683 recursive Git tree entries**; **280 tracked files in `samverk/`** (279 Python files plus one data snapshot); **307 Python test files in `tests/`**. Counts include package markers, are taken from `main`, and are not lines-of-code or coverage claims. |
| Runtime/build | `pyproject.toml`: **Python >=3.11**, package version **0.1.0**, CLI `samverk`, **zero declared third-party runtime dependencies**. The normal build backend is setuptools; git operations use the system Git executable. The project remains native-install-first and forbids Docker. |
| Latest recorded full-suite run | The **S-304 implementation commit** [`b7b4d8b`](https://github.com/hrabanazviking/RuneForgeAI-Samverk/commit/b7b4d8b5910f00acd39a4c668db85d61cc4d6690) reports **4,661 tests run; OK; 4 skipped; 0 failures**, plus **19/19 focused S-304 tests** and **112/112 neighboring tests**. This is a **commit-reported local run**, not a fresh independent execution during this documentation audit. |
| Recorded skip reasons | **S-095** real-`sshd` interoperability, **S-159** garbage-collection environment case, and **two S-292** no-detector-layer guards. The four skips must remain visible in any claim of test success. |
| Data and audit vocabulary | Latest documented database migration is **125** (code-scanning dismissal/events); documented audit taxonomy is **135 event names**: **33 auth / 89 repository / 13 administration**. See `samverk/db.py` and `docs/AUDIT_TAXONOMY.md`. |
| GitHub-hosted activity | This repository has **no GitHub issues, no GitHub pull requests, no published GitHub releases, no GitHub Actions runs**, and no checked-in `.github/workflows/` on the inspected snapshot. Development has instead progressed rapidly by direct slice commits and keeper banking. Those counts concern **this GitHub repository**, not whether Samverk implements issue/PR/release features internally. |
| Research shelf | **46 populated numbered clean-room studies** in `research/` and **18 implementation playbooks** in `docs/development-research/`. Both shelves describe engineering knowledge and proposed acceptance conditions, not independently verified deployments. |
| Operational posture | **Backend-rich alpha/development project; NOT a finished public/self-hosted forge.** `samverk/server.py` still routes only **`GET /`** and **`GET /healthz`**. Its state-changing HTTP methods pass through a CSRF guard but terminate in **404** after the guard. Service objects, API façades, HTML renderers and standalone Git transport harnesses are **not yet composed into one complete running forge**. |

### What changed since the 2026-11-06 snapshot

The previous README inspection stopped at **S-152 (manual reviewer assignment)** and correctly described **S-153 (merge commit)** as its next *then-current* step. The keeper has since banked **152 more numbered slices**, reaching **S-304**. Accordingly, the earlier wording "Part VII active," "merge implementations still ahead," "S-153 next," and the old file/test counts are **historical**, not today's project position.

| Roadmap section | Banked range and concrete work now present in the source tree |
|---|---|
| **Part VII: PRs and code review** | **S-153–S-168**: real merge commits, squash and rebase merge paths, conflict/mergeability inspection, status checks, auto-merge seams, branch lifecycle, merge authorization, review freshness, revert operations, and a **Part VII lifecycle gate** (`tests/test_part_vii_gate.py`). This advances the earlier PR-opening/review-only backend into tested **merge-capable service modules**; it does **not** by itself provide a deployed browser-to-server workflow. |
| **Part VIII: branch/tag protection** | **S-169–S-184**: branch rules, PR/review/code-owner/check requirements, signed-commit *rule seam*, linear-history and force-push restrictions, role-based bypass, rulesets, tag protections and rule-insights diagnostics. **S-175's policy shape must not be confused with the later S-305 signature-verification implementation.** Gate battery: `tests/test_part_viii_gate.py`. |
| **Part IX: organizations and permissions** | **S-185–S-204**: organizations, invitations, nested teams, outside collaborators, role inheritance, an instance/repository permission resolution engine, internal visibility, ownership safeguards and permission preview. Gate battery: `tests/test_part_ix_gate.py`. |
| **Part X: search** | **S-205–S-220**: code and metadata indexing, permission-filtered issue/PR/code/commit/repository/person search, saved searches, index health, API sharing and documented limitations. Gate battery: `tests/test_part_x_gate.py`. Search scopes and visibility must still be verified through the actual deployed HTTP surface. |
| **Part XI: events and notifications** | **S-221–S-236**: event storage, watching/starring, subscriptions, mention routing, notification inbox/preferences, SMTP/digest seams, activity feeds, following and push feeds. Gate battery: `tests/test_part_xi_gate.py`. A tested worker/store is not proof a production scheduler or SMTP host has been configured. |
| **Part XII: APIs and webhooks** | **S-237–S-256**: designed REST v1 contracts and service API classes, token authentication, pagination, typed errors, rate limits, repositories/issues/PRs/orgs/search/checks operations, signed webhook subscriptions, delivery queue, retries, logs and test events. Gate battery: `tests/test_part_xii_gate.py`. **GraphQL was deliberately deferred** at S-253 (`docs/GRAPHQL_VERDICT.md`); the presence of API classes does **not** mean `samverk/server.py` publicly mounts them. |
| **Part XIII: releases and artifacts** | **S-257–S-272**: release/tag models, drafts/prereleases, assets and SHA-256 checksums, release notifications/signature seams, CI-artifact storage, expiry, accounting and download integrity. Gate battery: `tests/test_part_xiii_gate.py`. **An integrated package registry is NOT implemented**: S-264 deferred it and S-265 records the refusal, with Python a possible later candidate and OCI containers explicitly refused (`docs/PACKAGE_VERDICT.md`, `docs/REGISTRY_CORE.md`). No release of *Samverk itself* is published on GitHub. |
| **Part XIV: wiki, gists, discussions** | **S-273–S-288**: per-repository Git wiki storage and Git-transport seams, wiki edit/history/access policy, Git-backed multi-file gists with edit/fork/star/comments/embedding, discussion categories/threads, answers, issue↔discussion conversions and permission-filtered discovery. **S-288's gate battery** (`tests/test_part_xiv_gate.py`) explicitly exercises stock-Git wiki smart-HTTP clone/push harnesses and gist/discussion lifecycles. **Discussion polls are deferred**, with an explicit refusal at S-286 (`docs/DISCUSSION_POLLS.md`); rich badges remain deferred. |
| **Part XV: security scanning (in progress)** | **S-289–S-304**: secret and generic detection, push scanning/protection/bypass, alert lifecycle, user-defined patterns, credential-validity seam, dependency and advisory data, PR dependency review, SARIF ingestion/fingerprinting, and HTML alert views. Details and boundaries immediately below. |

All workstream descriptions above refer to **tracked implementations plus their focused gate batteries**. The gate tests are integration exercises *inside the Python code/test harnesses*; they do not independently establish complete running public HTTP endpoints, a polished browser UI, Windows/macOS/ARM operation, or a securely operated internet-facing deployment.

### Detailed current implementation: Part XV, S-289–S-304

**Secret protection and alert handling (S-289–S-296).** The tree includes `samverk/secret_scanning.py` for provider-pattern detection, `generic_secret_detection.py` for entropy/context heuristics, `push_scanning.py` for introduced-commit/blob inspection, `push_protection.py` for pre-receive decisions, and `push_protection_bypass.py` for permissioned, reason-recorded overrides. `secret_alert_lifecycle.py`, `custom_patterns.py` and `secret_validity.py` implement alert state, custom-pattern evaluation/dry runs, and an intentionally cautious validity-check seam. Scanner findings and the guarded refusal record must not disclose the secret value. **Detection is not comprehensive by default**: unknown token formats, heuristics, classifier coverage and untested adversarial inputs cannot be called fully caught. The S-292 detector-absence skip cells remain visible.

**Dependencies and vulnerability advisory work (S-297–S-301).** `dependency_graph.py` parses supported manifests (including Python requirements, npm `package.json`, Go `go.mod`, and Rust `Cargo.toml`), records skips/limitations, and stores a per-repository derived graph. `advisory_data.py` supplies a bundled **dated** advisory snapshot; `dependency_alerts.py` compares dependencies against advisory ranges with alert state and explainable version handling; `advisory_refresh.py` models operator/scheduled refresh, history and snapshot freshness. `dependency_review.py` compares PR base/head manifests and can publish a **`dependency-review` check** to the existing checks store. The [S-301 commit](https://github.com/hrabanazviking/RuneForgeAI-Samverk/commit/ca58d4427a187957e375ee31f3224ce9651b0faf) specifically reports a **4,585-test** full-suite run with four skips. A bundled or stale advisory set does **not** mean live, complete vulnerability intelligence; skipped/ambiguous manifests and unfetchable references must remain **incomplete**, not marked clean.

**SARIF code scanning (S-302–S-304).** Three substantive Python modules now exist, not just roadmap entries:

- **S-302, `code_scanning.py`:** bounded, schema-checked **SARIF 2.1.0** upload/storage with per-commit metadata, API authentication/permission checks, retrieval, a repository audit event and webhook event. Its initial full-suite pin failure was corrected within the slice; the [implementation commit](https://github.com/hrabanazviking/RuneForgeAI-Samverk/commit/893a7ea8d3b75d41892bfe468598c1b1d2dccc9f) records a **4,618-test** successful rerun (four skips).
- **S-303, `code_scanning_alerts.py`:** tool/rule-scoped SARIF fingerprinting, de-duplication within uploads, per-branch **new/open/fixed/reopened** transitions, stale-upload rejection, and differentiated scanner-supplied versus structural fingerprints. The structural fallback can treat a moved-line result as a fixed old finding plus a new finding; the module explicitly documents that limit. Migration **124** introduces the alert/head state.
- **S-304, `code_scanning_ui.py`:** escaped HTML **alert list/detail renderers** with tool rule help, finding locations, history, filters and textual status; permission-checked **dismiss/reopen** using explicit reasons and a transactionally recorded alert event; PR annotations for findings on **changed head-side lines only**. Migration **125** supplies dismissal fields and event history. The [S-304 source-and-test commit](https://github.com/hrabanazviking/RuneForgeAI-Samverk/commit/b7b4d8b5910f00acd39a4c668db85d61cc4d6690) reports **19 focused tests**, **112 neighbor tests**, and **4,661 total tests run** with the four named skips.

**Critical terminology:** an HTML *renderer* in `code_scanning_ui.py` is **not** a mounted, navigable HTTP page in the current `server.py`. An authenticated *API class* in `code_scanning.py` is **not** proof an external client can reach a documented URL on the running process. The module and local acceptance batteries are progress; the full web/API composition remains an explicit release blocker.

### Verification and event chronology

1. **Latest banked state:** [`cd7ff594`](https://github.com/hrabanazviking/RuneForgeAI-Samverk/commit/cd7ff594c523733c0f6794860d5c8c81118e1169) records S-304/416. The implementation was introduced by [S-304 `b7b4d8b`](https://github.com/hrabanazviking/RuneForgeAI-Samverk/commit/b7b4d8b5910f00acd39a4c668db85d61cc4d6690), merged/banked, and then entered into the project map.
2. **Immediately prior:** S-301 dependency review; S-302 SARIF ingestion; S-303 alert identity/lifecycle; S-304 alert presentation/dismissal. Their commit records include test results, schema changes and in-slice pin repairs, and identify cases where a first run failed before a subsequent green rerun. These are useful engineering records and should not be flattened into "nothing ever failed."
3. **Last completed major part:** [S-288, Part XIV gate](https://github.com/hrabanazviking/RuneForgeAI-Samverk/commit/97f8cb0726e41653c895ab0cd15ee546ee5b2ba4), with a checked-in stock-Git/wiki and gist/discussion integration battery.
4. **How the work is organized:** commits show feature branches/parallel team contributions, merges into `main`, and **keeper "Map: S-### banked"** commits. Their tracked chronology is evidence of rapid local/agent-team development, not a substitute for automated external CI. The `main` HEAD is the reproducible snapshot; not every branch's unmerged work is a banked feature.
5. **What this audit verified directly:** repository tree, README, roadmap, claims register, dependency register, research indices, part-gate/test source, representative implementation modules, `pyproject.toml`, minimal server route table, commit history, GitHub issues/PRs/releases and Actions run records. **It did not execute the 4,661-test suite, audit all possible code paths, run a networked service or penetration-test cryptography.** The suite figures here are accurately attributed to the commits.

### What remains NOT PROVEN or not assembled for production

- **Complete live HTTP/web/API composition:** `samverk/server.py` remains the clearest end-to-end bottleneck, exposing only root/health. Assemble authentication, repository UI, issues, PR review/merge, REST APIs, Git smart HTTP, LFS, webhooks, search, wiki, releases and scanning views into one actual, hardened server; prove each via realistic client journeys. Do **not** silently bypass existing CSRF, bearer-token, authorization, or streaming transport rules to make routes appear to work.
- **Full interoperability and operational security:** `docs/CLAIMS_REGISTER.md` still marks **C-09 standard Git interoperability across SSH and HTTP NOT PROVEN**. There are meaningful stock-Git transport harnesses, but **S-095's real-`sshd` cell is skipped**; extend to real remote SSH/HTTPS clients and varied Git versions. Authentication and scanner code should receive adversarial review, threat-model updates and externally reproducible security tests before any broad security assurance.
- **Real native deployment and recovery:** the roadmap's **Part XVII** scheduled GitHub mirroring, private-repo credentials, restore drills and full-instance backup duty are **not banked**; **Part XVIII** native installation, first-admin journey, service units, upgrades and maintenance are also ahead. S-074 export primitives or existing Git mirror functions are **not** evidence an unattended backup fleet is operating. The claims register's **C-12 remains NOT PROVEN**.
- **Accessible Cyber-Viking UI:** substantial strings/HTML/rendering seams exist, but **Part XX** still owns the end-user design lawbook, information architecture, keyboard and scaling checks, and founder findability walks. **C-11 remains NOT PROVEN**. The actual on-screen workflow must be usable without a developer operating stores by hand.
- **Samtal integration:** **Part XIX** remains future work. Standalone-first must continue to hold; Samtal integration must be additive, optional and separately authorization-tested.
- **Cross-platform evidence:** **Part XXII** has not supplied real Windows, macOS and ARM/Raspberry Pi matrix results. **C-10 remains NOT PROVEN**, regardless of the stdlib-only architecture.
- **Release and CI gate:** **Parts XVI and XXI** still need runnable workflow/runner infrastructure, externally visible repeatable tests, packaging, reproducible installation, end-to-end smoke runs, signing/provenance, upgrade/rollback proof, release notes and an explicit v1.0 acceptance decision. The absence of GitHub Actions and GitHub releases means there is currently **no public CI/release result to cite** as independent confirmation.
- **Dated documentation drift:** the older **2026-11-06 README summary**, research playbook introduction and the roadmap's **2026-11-06 priority overlay** still refer to S-152/S-153. They remain useful time-stamped historical guidance but must not be read as the current feature frontier. The same applies to the founding-era claim that all research files are empty. This dated section corrects present-tense interpretations without deleting earlier records.

**Claims status is intentionally unchanged:** `docs/CLAIMS_REGISTER.md` continues to scope **C-01–C-08** to the stated tested evidence and marks **C-09, C-10, C-11 and C-12 NOT PROVEN**. Landing more code does not automatically upgrade those proof labels.

### Next engineering checkpoints, in roadmap order and in operational priority

**Immediate banked-line continuation:** implement **S-305 signed-commit verification** (GPG/SSH evidence and readable trust states), **S-306 vigil mode**, **S-307 repository security tab**, **S-308 security overview**, **S-309 audit log UI**, **S-310 private advisories**, **S-311 adversarial scanner battery**, and **S-312 Part XV claims-and-tests gate**. Each banked slice needs a focused battery, neighbor regression battery, countable full suite, explicit skips, migration/taxonomy review, and project-map entry.

**Parallel priority, without miscounting the 416 slices:** complete the **live server and user-journey integration** already highlighted in the [routing blueprint](docs/development-research/01-live-http-routing-and-composition-blueprint.md), [stock-Git interoperability lab](docs/development-research/04-stock-git-http-ssh-lfs-interop-lab.md), [complete user journey battery](docs/development-research/03-complete-user-journey-test-battery.md), [native CI guidance](docs/development-research/08-project-ci-and-quality-gates.md), and [native install/portability guide](docs/development-research/10-native-install-upgrade-and-platform-profiles.md). Avoid postponing the only ordinary-user access path until every backend feature exists.

**Subsequent roadmap fronts:** **Part XVI S-313–S-328** native CI/runner; **Part XVII S-329–S-344** mirrors, backup and restore; **Part XVIII S-345–S-360** deployment/administration; **Part XIX S-361–S-380** optional Samtal seam; **Part XX S-381–S-393** UI/accessibility; **Part XXI S-394–S-404** v1.0 proof; **Part XXII S-405–S-416** genuine platform testing. Preserve deliberate deferral decisions on GraphQL, package registry and discussion polls unless new evidence warrants revisiting them.

**Acceptance benchmark:** a fresh operator on documented, supported hardware can install without Docker, create/administer an account, create a repository and token, clone and push with stock Git, browse changes, file an issue, open/review/merge a PR, receive events, inspect security findings and restore a backup using the running interface/API. The full journey must be permission-safe, repeatable, observable, accessible and supported by published test logs. **Until that benchmark and the claims register's open items are met, Samverk should be described as an ambitious, fast-moving, modular forge implementation, not a finished drop-in GitHub replacement.**

## Licence

**GNU Affero General Public License v3.0** (AGPL-3.0) — see `LICENSE`.
Samverk is free software: run it, study it, reshape it; if you offer your
reshaped version to others over a network, offer them the same freedom in
return. That reciprocity is why the AGPL was chosen: the together-work
stays together.
