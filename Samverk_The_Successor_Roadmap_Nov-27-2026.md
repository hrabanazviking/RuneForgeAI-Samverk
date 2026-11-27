# SAMVERK — THE SUCCESSOR ROADMAP
## Every Unbuilt Wing, and the Complete Instructions for Raising Them

**Version:** 1.0 (war-map draft)
**Prepared:** from the successor roadmap seed (`samverk/successor_roadmap_seed.py`, 24 items),
the final claims register (S-399, F-01…F-17), the wave plan tail, the project memory map,
the claims of Part XXII, and a direct reading of `samverk/server.py` and the full module tree.
**Status of the base:** 414 of 416 roadmap slices banked; schema 140; audit taxonomy 142
(34 auth / 92 repo / 16 admin); full suite ~6,340 tests; last counted master run 6,129 ran /
15 named stale-pin failures / 4 named skips.

---

## PART 0 — THE HOUSE LAWS (binding on every slice below)

Every slice in this roadmap obeys the founding discipline. These are not suggestions;
they are the reason the first roadmap reached 414/416 without a single dishonest claim.

1. **Inspect → build → test → repair → continue.** No slice is committed before its
   battery is counted green from a log file read back from disk.
2. **Own battery + neighbour suites per slice.** No full-suite run gates banking.
   The full suite runs once per wave of ten banked slices, in the background, non-blocking.
3. **Every claim flips in the same commit as its proof.** The claims register
   (`docs/CLAIMS_REGISTER.md`) is updated atomically with the evidence.
4. **NOT PROVEN is a first-class state.** An unproven remainder is named with the slice
   that owns its proof. Nothing is dressed up as done.
5. **Stdlib-first.** No third-party dependency is admitted without a register entry,
   an exact `==` pin, a reason naming what the stdlib cannot do, and an import-scan pass.
   The register currently holds exactly one admission (`cryptography==46.0.5`).
6. **NO Docker, ever.** Native installs only. This law grounds the OCI refusal and
   shapes every deployment instruction below.
7. **README.md is never touched by the campaign.** Founder wordings wait for the founder.
8. **One escaping seam (S-010), one subprocess seam (S-014), one error shape (S-240),
   one permission engine (S-190), one audit taxonomy (append-only, 142 events).**
   A later slice may *use* a seam; it may never build a second one beside it.
9. **Never leave a discovered bug unfixed.** Fix in-slice or name it as the immediate
   next work with the discovery written down.
10. **Security findings are stored redacted.** No secret value is ever stored, rendered,
    logged, or echoed — pattern class and location only.
11. **Status is said in words, never colour alone.** Every badge carries text + icon.
12. **Private is indistinguishable from missing.** On every surface, for every stranger.

**Slice format for this roadmap:** `C-###` for Composition slices, `W-###` for platform
(proof) slices, `G-###` for greening slices, `E-###` for external-verification slices,
`D-###` for deferred-wing buildouts, `O-###` for operational slices.

---

## PART I — THE COMPLETE CENSUS OF UNBUILT WINGS

### Category A — The Composition (the great unbuilt wing)

The single largest fact about Samverk today: **`samverk/server.py` routes exactly three
paths** — `/` (version JSON), `/healthz` (a real read-only database probe answering 503
on staleness), and `/admin/status` (a real admin dashboard). Behind that gate stand
roughly 380 service modules, hundreds of proven HTML renderers, a complete REST API
contract (36 resources), and every law of the forge — none of it reachable by an
ordinary user in a browser.

| # | Wing | Status | Landed machinery awaiting routes |
|---|------|--------|----------------------------------|
| A-1 | URL routing for all services | nonexistent | — |
| A-2 | Account surface (sign-in/up/out, settings pages) | renderers exist, unrouted | S-025…S-048, S-034, S-228, S-136 |
| A-3 | Repository browsing pages | renderers exist, unrouted | S-097…S-119 |
| A-4 | Issues pages | renderers exist, unrouted | S-121…S-140 |
| A-5 | Pull-request & review pages | renderers exist, unrouted | S-141…S-168 |
| A-6 | Orgs & teams pages | renderers exist, unrouted | S-185…S-204 |
| A-7 | Search results pages | renderers exist, unrouted | S-205…S-220 |
| A-8 | Security surface pages | renderers exist, unrouted | S-289…S-312 |
| A-9 | Releases / wiki / gists / discussions pages | renderers exist, unrouted | S-257…S-288 |
| A-10 | Notifications inbox & social UI | renderers exist, unrouted | S-221…S-236 |
| A-11 | Admin panel pages | renderers exist, unrouted | S-345…S-360 |
| A-12 | Git smart-HTTP mounted on the real server | harness-proven only | S-077…S-096 |
| A-13 | LFS handler mounted | exists, unwired | S-061/S-062 |
| A-14 | Wiki transport mount | seam exists, unwired | S-275 |
| A-15 | End-to-end journey battery vs the composed server | designed in playbooks, not run | dev-research 03 |
| A-16 | S-402 — the founder's unaided usability walk | founder-owned, open | Volmarr only |

### Category B — Roadmap slices still open in the first roadmap

| Slice | What | Owner | Law |
|-------|------|-------|-----|
| S-402 | Founder's usability walk: fresh instance, unaided — account, token, repo, push, mirror; every stumble a defect fixed or commissioned on the spot | Volmarr | No worker builds it; no battery substitutes for it |
| S-416 | Portability gate. Held on own evidence; the macOS Apple-silicon requirement was REMOVED by Volmarr's ruling (2026-11-25, waived). The real **Windows x86-64 leg** is the only remaining requirement | Part XXII | Cells flip only when their battery ran green in that cell |
| S-414 fix-forward | Viewport reconciliation: `browser_reach.py` (added later) lacks the viewport meta; census must go 70→71; S-414's banked defect-expectation tests must be updated to the fixed state | successor roadmap | One reconciliation slice, not a merge hack |

### Category C — Proofs owed (the honesty debts)

| ID | Debt | Detail |
|----|------|--------|
| F-11 | Full suite green | 15 failures, all the stale schema/taxonomy-pin class (12 stale census pins, 2 platform-seam inventory entries, 1 outlier) + 4 named skips. No counted run yet reads zero. |
| v1.0 tag | NOT placed | S-401's law: tagged on a counted-green tree only. Awaits a green counted run over the final tree. |
| Release signing | ships unsigned | The S-400 tarball (945 files, deterministic, SHA-256 verified) waits for Volmarr's maintainer key, held outside the tree; attaches via the S-263 seam. |
| C-09 remainder | real-`sshd` cell | Stock-git smart-HTTP and SSH forced-command harnesses green; the real sshd interop cell is skipped on the proving host. |
| C-12 remainder | live mirror fleet | Mirroring machinery, freshness law and restore drill proven; a continuously *running* fleet is an operational state, not a test result. |
| S-413 | laptop x86-64 CPU budgets | Stated, never measured. |
| S-414 | browser/device reach | Only Firefox desktop headless proven. Chrome/Safari/Edge, phones, tablets: NOT PROVEN. |
| Part XVIII remainder | Pi-class fresh-install timed pass | The walk was timed on x86-64 only. |
| F-S389-1 | live screen-reader session | Structural audit verified; no real Orca session has ever been run. |
| Security assurance | adversarial human review | Auth and scanner code carries counted batteries but no external adversarial review. |
| Samtal-side ratification | seam contract one-sided | No Samtal codebase stands on the seat; the contract rests on published shape + S-045. |
| 3 open studies | research 24, 26, 30 | Verdicts delivered in separate docs; not yet recorded in the study files. Owned by S-403. |
| F-17 | README wordings | The founding Status bullet ("46 empty files" — false today) and "Samtel" for Samtal. Volmarr's own hand only. |

### Category D — Deferred wings (each with a written reopen condition)

| Item | Reopen condition (verbatim from the seed) |
|------|-------------------------------------------|
| GraphQL API layer | A second independent consumer with measured relationship-read pain, or the PR-review benchmark in research 24's shape showing REST materially worse; S-255 abuse defences extended to query cost. The eight must-not-break invariants carry into any future build. |
| Package registry: Python | A village project names a concrete private-package need release assets cannot serve, with its workload as evidence; trust machinery (signing verifier, S-268 storage accounting, quarantine design) standing. |
| Package registry: JavaScript | A village project becomes a JavaScript package with a private-distribution need release assets cannot serve. |
| Signing verifier / registry trust machinery | Named as a precondition of any reopened package verdict (S-264 reopen conditions). |
| Discussion polls | Measured village need plus a fraud-honest design that does not pretend to establish voter identity beyond account scope. |
| Discussion rich badges | Measured village need for a signal beyond the accepted-answer mark. |

### Category E — Refused (recorded; rebuilt only by Volmarr's word)

- **OCI container images / Docker** — the village runs no Docker, ever; native installs only.
- **Federation between instances** — decided at founding.
- **Hosted-service ambitions** — Samverk is software its owner runs, not a platform for strangers.
- **AI features that invent facts** — "The machine drafts. The human decides."

### Category F — Served today (recorded so the ledger is complete)

Generic archives (release assets + checksums + signing seam) and Go modules
(fetched from version-control tags on readable repositories) — both already served.

---

## PART II — SUCCESSOR PART I: THE COMPOSITION

**Goal:** flip claim F-10 — feature services composed into one complete running forge.
**Wave structure:** 13 waves, ~120 slices. Every wave closes with its counted battery,
a neighbours run, a map entry, and (where a claim is touched) the register flip in the
same commit.

### Wave C-1 — The Routing Foundation (C-001…C-006)

#### C-001 — The Router

**Inspect.** Confirm the dependency law: no framework. Read S-017's import scan to know
what the scan will refuse. Read S-019/S-240 to see the error contract the router must
honour, and S-113 for the designed error states.

**Build.** `samverk/web/router.py`:

- A frozen `Route` record: `(method, pattern, handler_name, csrf_exempt=False)`.
  The `csrf_exempt` flag exists ONLY for the git-transport and LFS paths (Wave C-12),
  which authenticate by Basic/token under S-081/S-082 rather than session + CSRF.
  Any other use of the flag is a battery failure.
- Path patterns use `{param}` segments compiled to a pure matcher. No regex; segment-only
  wildcards. A `{param}` never matches `/`, so traversal cannot hide in a parameter.
  A path containing `..` after decoding is refused before matching.
- Trailing-slash normalization stated as law (one form canonical; the other redirects 301
  for GET and refuses 404 for state-changing methods).
- Method dispatch: 405 with an `Allow:` header when the path matches another method.
- Duplicate patterns are refused at import (a table that cannot be ambiguous).
- A `resolve(method, path) -> ResolvedRoute(handler, params)` returning a refusal record
  (`not_found` / `method_not_allowed` / `path_invalid`) shaped for S-240.

**Tests.** `tests/test_web_router.py` (~24 tests): match/no-match; param extraction and
type-pinning; `..` and encoded traversal refused; duplicate-pattern refusal at import;
405 + `Allow` correctness; trailing-slash law; the CSRF-exempt flag refused outside the
transport allowlist; a planted second router module caught by the seam audit.

**Acceptance.** A route table of 200+ routes (from later waves) declares clean and
resolves a full journey path set without ambiguity.

#### C-002 — The Request Context

**Build.** `samverk/web/context.py`:

- `Request` record: method, path, params, query, headers (case-normalized), body reader
  with the S-255 payload caps applied at the door, and the resolved viewer.
- Viewer resolution: session cookie → `SessionStore.authenticate` → account; anonymous
  is a legal viewer with role `None`. Credentials-invalid never downgrades to anonymous
  (S-238's law applied to the web face).
- CSRF: the S-009 gate already runs before routing for all state-changing methods.
  The context adds nothing to it — document that inheritance is structural.
- A `ctx.require(cond, reason)` helper that raises the store's own refusal verbatim;
  handlers never invent a second permission vocabulary (S-190 is the only engine).

**Tests.** Anonymous viewer on public/private surfaces; a stale session answers as
anonymous; body-cap refusal at the door; the context is a pure read (audit-count
snapshot proof, the S-201 pattern).

#### C-003 — The Page Shell

**Build.** `samverk/web/shell.py`:

- Serve `design_tokens.render_css_variables()` at `/static/samverk.css` and S-116's
  print stylesheet at `/static/samverk-print.css`. Static files carry cache headers and
  are content-fingerprinted by a build step; no upload surface ever writes into `/static`.
- Render `layout_shell` (S-382) as real HTML: nav with `aria-current`, skip links,
  `tabindex="-1"` group sections, the S-111 keyboard registry help link.
- **The viewport meta on every page** — this wave *implements* the S-414 fix-forward:
  the census of page modules grows as composition adds pages, and the meta is a shell
  invariant, not a per-page chore.
- Every status rendered with icon + text (S-387); every colour-bearing carrier passes
  the grayscale audit (S-383) *now over real rendered HTML*, not the model.
- All text through `escaping.escape_html_text` / `escape_html_attr` (S-010). CSP already
  rides every response; no inline script, no inline style, ever.

**Tests.** A page-shape audit battery: every rendered page carries viewport meta, the
nav, alt-text law (S-390), target sizes (S-386), and zero inline handlers. The S-383/
S-384/S-385/S-386/S-387/S-388/S-389/S-391 audits re-run against the rendered pages.
~30 tests.

#### C-004 — HTML Error Pages

**Build.** S-240's problem fields rendered as HTML through S-113's designed states.
The uniform `not_found` wording for private-vs-missing (S-054 law) is byte-identical.
No stack trace, path, or exception text can reach a page (S-019's law, battery-proven).

#### C-005 — The Form Law

**Build.** `samverk/web/forms.py`: a tiny stdlib form reader — urlencoded + multipart
(multipart parsed by hand over `email.parser` or a minimal parser; no dependency).
Field limits declared per form; unknown fields refused by name; CSRF field consumed by
the gate, not the handler. File uploads route through S-012's law (sniff beats declared,
quarantine first, SVG refused by default).

#### C-006 — Wave battery + map entry + register check.

**Acceptance for Wave C-1.** `python3 -m samverk serve` on a fresh instance answers
`/`, `/healthz`, `/admin/status`, and a styled 404 page — the skeleton now has skin.

### Wave C-2 — The Account Surface (C-010…C-017)

Routes (every POST carries the CSRF field; every act already audited by its store;
handlers authorize through the store's own law and add nothing):

| Route | Backing machinery |
|-------|-------------------|
| `GET/POST /login` | S-027 LoginService (throttle, decoy hash, timing floor already inside) |
| `GET/POST /join` | S-025 register + S-021 SignupGuard + S-352 registration mode (`closed` answers `registration_closed` in plain words; `invite` consumes an admin-minted code) |
| `POST /logout` | session tombstone + clear cookie |
| `GET /verify/<token>` / operator-approval flow | S-026 (both roads) |
| `GET/POST /password-reset` (+ redeem) | S-028 (single-use, 1-hour, all-sessions-revoked) |
| `/settings/profile` | S-029 (avatar under S-012 with mandatory alt text) |
| `/settings/tokens` | S-034 renderer — the findability law is already proven; route it |
| `/settings/keys` | S-030 + S-036 sudo re-auth seam (fail-closed) |
| `/settings/security` | S-035 TOTP enrol, S-037 recovery codes, S-038 policy display |
| `/settings/sessions` | S-040 (revoke one/all, "this session" marker) |
| `/settings/notifications` | S-228 page (email per reason, digest cadence, watched repos) |
| `/settings/filters` | S-136 saved filters |
| `GET /<username>` | S-029 profile + S-230 activity + S-233 stars + S-232 follows |

**Wave battery.** `test_web_accounts.py` — a full journey over real HTTP: register →
operator road → login → change password (all sessions revoked; re-login) → enroll TOTP →
wrong-code refused → add SSH key (sudo-gated; refused outside the window) → mint token
(shown once) → revoke. ~40 tests.

### Wave C-3 — The Repository Surface (C-020…C-030)

- `GET /` — instance landing: S-210 directory when anonymous; S-213 global search when signed in.
- `GET/POST /new` — S-049 create + S-352 default visibility (explicit visibility always wins).
- Mount the Part V clan verbatim: `/owner/repo` (S-097), `/tree/...` (S-098),
  `/blob/...` (S-099), `/raw` (S-100), `/blame` (S-101), `/commits` (S-102),
  `/commit/<oid>` (S-103), `/compare` (S-105), `/find` (S-110), `/insights` (S-115),
  branches/tags (branch/tag views), `/settings` (S-066).
- **Uniform `repo_not_found` on every route** for strangers-to-private — battery proves
  the 404 bodies are byte-identical between a private repo and a missing one.
- Empty-repo home with per-transport first-push instructions (S-065).
- Binary/image views (S-114), file finder keyboard law (S-111), deep links (S-117).

### Wave C-4 — Issues (C-040…C-052)

List / new / issue page with timeline / comments (edit history, tombstones) / labels /
milestones / assignees / reactions / lock & pin / transfer with forwarding note / bulk
edit / templates (guided forms) / search + saved filters sidebar.
**Law:** the route's only jobs are parse form → authorize via the module's own law →
call the store → render. A second permission law is a battery failure.

### Wave C-5 — Pull Requests & Review (C-060…C-075) — the largest wave

- List / new: same-repo (S-141), cross-fork (S-142), from-compare (S-167), issue→PR (S-137).
- The PR page composes: conversation (S-144) · files with viewed-state marks (S-145) ·
  line comments (S-146) · review threads & resolution (S-147) · review composer with
  pending autosave (S-148) · freshness display (S-149) · suggested changes with
  "Commit suggestion" (S-150) · checks panel (S-157) · merge box.
- The **merge box** is the crown jewel: three methods (S-153/154/155), conflict
  surfacing *before* merge (S-156 — conflicts shown, never discovered by merging),
  auto-merge arm/cancel (S-158), and every protection gate's verdict (S-170…S-183)
  rendered as plain-words blockers linked to S-183's rule-insights page.
- Draft toggle (S-143), revert (S-160), merge permission (S-163).

### Wave C-6 — Orgs & Teams (C-080…C-092)

Org profile + settings home (S-185 map), members with the removal-cascade preview shown
before confirming (S-194), teams + nesting with the before-save preview page (S-188),
team permissions ladder (S-189), invitations (S-193), default permission (S-192),
outside collaborators (S-191), org audit log (S-198), repo policy (S-196),
org deletion with inventory + grace (S-199).

### Wave C-7 — Search UI (C-100…C-106)

Global box (S-118 scope law) → grouped results pages; per-scope search pages (repo,
issues, code, commits, people); saved searches (S-214); recents (S-213); the honest
limits page (S-219) linked from every results page.

### Wave C-8 — The Security Surface (C-120…C-130)

`/owner/repo/security` (S-307 gathered read) · alert list/detail pages (S-294 and S-304
renderers) with dismiss/reopen forms (reason required) · SARIF upload via the API door
(S-238 auth) with an admin page · dependency alert pages with the snapshot-age banner
(S-298) · private advisories (S-310) · audit log pages at repo/org/instance scope
(S-309/S-198/S-356) with chain-verification status in words.

### Wave C-9 — Releases, Wiki, Gists, Discussions (C-140…C-156)

Release list/detail: drafts private to writers (S-258), assets (S-259), checksums with
verification instructions (S-260), signature badges with honest trust words (S-263),
latest pointer rule in words (S-261), tag automation toggle (S-269).
Wiki: page list + editor + preview-writes-nothing (S-273/274), access policy shown on
the home (S-276). Gists: editor, forks, stars, comments, embed snippets (S-277…S-281).
Discussions: categories, threads, answer marking, conversion (S-283…S-285); polls render
their published refusal (S-286).

### Wave C-10 — Notifications & Social (C-160…C-166)

Inbox (S-224: filters by reason/repo, done vs saved, keyboard triage) · watch/star
buttons with live counts (S-222/S-233) · follow/unfollow (S-232) · profile pages
(activity, stars, followers — S-230/233/232) · email preferences (S-228).

### Wave C-11 — Admin (C-180…C-190)

Admin panel (S-351: search over users/orgs/repos; destructive road = audit wired +
sudo grant, refusals witnessed) · site settings (S-352) · maintenance banner +
enable/disable (S-353) · quota overview (S-354) · abuse queue (S-355 with verified
audit context) · instance audit view (S-356) · runner registration page (S-317) ·
workflow UI: run list/detail with jobs, steps, timing, log tails, artifacts (S-327/S-323)
· first-admin recovery page (S-350) · upgrade status page (S-357/S-359 health).

### Wave C-12 — Git Transports on the Real Server (C-200…C-204)

1. Mount `SmartHttpService` at `/{owner}/{repo}.git/info/refs` and
   `/{owner}/{repo}.git/{upload-pack,receive-pack}` (stateless-rpc legs), protocol v2
   via `Git-Protocol` header; route `/{owner}/{repo}.wiki.git` through S-275's naming
   law; mount `make_lfs_handler` under `/{owner}/{repo}/info/lfs/...`.
2. **CSRF exemption by law:** these paths authenticate via Basic/token (S-081/S-082)
   or SSH forced-command (S-086/087). The exemption seam from C-001 admits exactly these
   prefixes; a battery proves a bare session cookie cannot push.
3. Wire the full receive chain at the S-089 stages, exactly as the harnesses already do:
   protection (Part VIII) → secret scan (S-292) → quota (S-068/S-354) → hooks (S-067) →
   maintenance mode (S-353) → mirror write law (S-334) → push events → audit.
4. Transfer limits (S-091), concurrent push locks (S-092), upload-archive (S-093).
5. **Wave battery:** the full stock-git matrix against the *composed* server on an
   ephemeral port — clone/push/fetch × public/private × token/password/deploy-key,
   protocol v2 packet-traced, LFS round-trip, wiki clone/push, deploy-key grants,
   refused pushes naming their reason.

### Wave C-13 — The Journey Gate (C-210)

Build `tests/test_composition_journey.py`: a fresh operator on a fresh instance performs
the acceptance benchmark verbatim, all through the composed HTTP surface:

> install from the written guide alone → first admin → create account → mint token →
> create repository → clone with stock git → push → browse code → file an issue →
> open a PR → review → merge → receive a notification → see a security finding →
> restore a backup.

Permission-safe at every step, repeatable, observable, accessible. **When this battery
is counted green, F-10 flips to PROVEN in the same commit.** Then S-402 — Volmarr's
unaided walk — judges it as product. Every stumble is a defect fixed or commissioned
on the spot, and the walk's record is written where users will find it.

---

## PART III — SUCCESSOR PART II: PLATFORM PROOF (THE WINDOWS LEG → S-416)

**W-001 — Provision a real Windows x86-64 host.** Bare metal or VM. Not WSL —
S-410's battery already treats WSL as a distinct seam (the UNC-path refusal lesson).
No Docker, per law.

**W-002 — Native install walk on Windows.** Follow `docs/INSTALL_WALK.md` on the host:
Python ≥3.11, install from the S-400 source tarball or the source tree;
`samverk config check` (S-346); data root under the user's own directories (S-347 layout);
`samverk admin create-first-admin`; run under the S-410 SCM service host
(`windows_service_host.py` spawning its child) — verify the service registers, starts,
restarts, and survives reboot. Record every step and failure mode in a counted log;
failures are findings, not embarrassments.

**W-003 — Filesystem truth.** Run on NTFS (case-insensitive kind) per S-408's probed
kind law: confirm case-collision refusals fire deterministically; verify S-409's
path/encoding discipline (NFC, LF, forward slash) over real `C:\` paths; confirm the
S-347 layout lands exactly where the layout resolver says.

**W-004 — The battery, in the cell.** Run battery v1 (S-394) sharded
(`tools/run_suite_sharded.py`) with disk-backed TMPDIR on the Windows host.
Classify every failure: stale-pin class (fix forward on the main line) vs real
Windows defects (fix forward per bug law). Nothing is deleted to make tests pass.

**W-005 — Flip the cells.** Update `samverk/support_matrix.py` cell by cell via
`tools/run_support_matrix.py` — each cell flips only on its own counted log.
Re-render `docs/SUPPORT_MATRIX.md`. Flip claim F-02/C-10 for Windows x86-64;
remaining cells (browser matrix, Pi-wide battery green run) stay honestly named.

**W-006 — The gate verdict.** S-416's gate battery runs on the evidence; the gate
record is written; **the final roadmap slice banks — 416/416.**

---

## PART IV — SUCCESSOR PART III: SUITE GREENING & THE v1.0 TAG

**G-001 — The 15 pins (one fix-forward commit).**
Re-pin the 12 stale taxonomy/schema tests to the live census (34/92/16 = 142 events;
schema 140). Add the 2 platform-seam inventory entries (`windows_service.py` subprocess
touchpoints) per the S-406 pattern. Fix the 1 outlier. Verify affected modules +
neighbours (~545 green — the wave410 precedent). This is the known class; no behaviour
failure is expected, but if one appears, it is a real bug and takes priority.

**G-002 — The counted master run.** Full sharded suite on a quiet box, TMPDIR on the
disk-backed volume. Target: **Ran N — 0 failed — 4 named skips** (S-095 real-sshd,
S-159 GC environment, S-292's two no-detector-layer guards). Record a NEW entry in
`docs/COUNTED_MASTER_RUN.md` over the final tree. Flip **F-11 → PROVEN** in the same
commit.

**G-003 — Place the v1.0 tag.** Only if G-002 is green: `tools/run_v1_tag.py --place`
per S-401's law (counted-green tree only; refuses otherwise, exit 2). The v1.0 release
carries the census (S-401's `build_census`). Volmarr signs `SHA256SUMS.txt` with the
maintainer key held outside the tree; the signature attaches through the S-263 seam;
the badge reads **verified** with his name — never a bare tick.

**G-004 — S-414 reconciliation.** Add the viewport meta to `browser_reach.py`
(census 70→71), update S-414's register/claims rows in one slice, bank. This un-holds
the team-13 fix-forward honestly rather than by merge force.

---

## PART V — SUCCESSOR PART IV: EXTERNAL VERIFICATION & RELEASE

**E-001 — Public CI.** Add `.github/workflows/` (using CI to *verify* the product is
consistent with the no-Docker law in the product): the stdlib import scan (S-017's
battery is the law), lint, and the sharded battery on ubuntu-latest + windows-latest
runners. The Windows runner doubles as W-004 evidence.
**E-002 — Publish the GitHub release.** The S-400 tarball + checksums + Volmarr's
signature + `docs/RELEASE_NOTES.md` written in plain words first, carrying the named
remainders.
**E-003 — Security assurance pass.** External human adversarial review of
`passkeys.py`, `http_security.py`, `commit_signatures.py`, `git_auth.py`, the scanner
family, and the seam token exchange. Every finding named, fixed, or accepted with its
reason recorded in the register.
**E-004 — The real-sshd cell.** On a host with sshd: script S-095's cell per study 02
(AuthorizedKeysCommand + forced command, never a shell), counted green → **C-09 goes
unscoped PROVEN.**

---

## PART VI — SUCCESSOR PART V: THE DEFERRED WINGS

*(Build only when the reopen condition fires. Each plan below is written so that when
the condition is met, the build starts from the truth, not a blank page.)*

### D-1 — The GraphQL Layer
- Honour the eight must-not-break invariants (S-253) verbatim.
- Governance caps already stated: depth 8, cost 1000, 1,000,000 response bytes,
  10 seconds, 30 aliases.
- Extend S-255 abuse accounting to query cost (every field priced; expensive edges
  priced higher).
- Node ids over the S-221 canonical event store; connections ride S-239's keyset
  cursors (no offset pagination, ever).
- Schema over the 36 REST resources; no API-only back door (the S-237 law).
- Battery: cost-cap enforcement, introspection, the three research-24 client journeys,
  and the depth/complexity fuzzers.

### D-2 — Python Package Registry
**Preconditions (build first, whichever fires first):**
1. **The signing verifier** — generalize S-305's verification into a standing trust
   service; a digest is never an identity; provenance shown in words.
2. Quarantine-before-visible for every uploaded artifact (S-012 law at registry scale).
3. Immutable published versions; deletion as tombstones joined to S-268 accounting.

**Then the registry:** PEP 503 simple-index routes over namespaced repositories;
upload gated to repo write + token scope; every publish/fetch witnessed like release
acts; private indistinguishable from missing on fetch; offline export proven before
the ecosystem is declared hosted.

### D-3 — Discussion Polls
Fraud-honest design: one honest count per account; a close date stated in words;
no identity claimed beyond account scope; results either hidden until close or shown
with the caveat in words; battery includes a vote-manipulation attempt that must be
named and refused.

### D-4 — Rich Badges
Only after a measured need; the accepted-answer mark remains the primary signal.

---

## PART VII — SUCCESSOR PART VI: OPERATIONAL MATURITY

**O-001 — The backup fleet, running.** Schedule `drift_census` + `sync_scheduler`
via the S-348 systemd timers on the real machine. The *operation itself* — a fleet
mirroring continuously, drift reported, restores drilled — becomes the proof for
C-12's remainder. Quarterly restore drill (S-342) against real data, logged.

**O-002 — Worker daemon split (optional).** If timer cadence proves insufficient,
split the four in-process worker seams (S-345: mirror-sync, index, ci, maintenance)
into long-running daemons with a queue-poll loop. Only the composition root changes;
every store and law is untouched.

**O-003 — Measure the remaining cells.** Laptop x86-64 CPU budgets (S-413);
the Chrome/Safari/Edge/phone/tablet browser cells (S-414); the live Orca
screen-reader session (F-S389-1); the Pi-class fresh-install timed pass (Part XVIII).
Each flips on its own counted evidence, never on wording.

**O-004 — Record the three open studies** (24/26/30) in their study files per their
delivered verdicts; close the S-398 markings; S-403's successor seed shrinks accordingly.

**O-005 — F-17.** Volmarr's own hand corrects the README's founding Status bullet
and the "Samtel" spelling. The register row flips to SETTLED. The campaign's hands
never touch the file.

---

## PART VIII — THE REFUSED LEDGER (carried, never softened)

| Refusal | Ground | Reopen |
|---------|--------|--------|
| Docker / OCI images | Standing law | Only Volmarr's word, case by case |
| Federation between instances | Founding decision | Only Volmarr's word |
| Hosted-service ambitions | Founding decision | Only Volmarr's word |
| AI features that invent facts | Founding decision | Only Volmarr's word |

---

## PART IX — THE CLAIMS FLIP TABLE

Every row below flips in the same commit as its proof, per the register's own law:

| Claim | Now | Flips when |
|-------|-----|------------|
| F-10 composition | NOT PROVEN | C-13 journey battery green |
| F-11 full suite green | NOT PROVEN | G-002 counted run reads zero |
| v1.0 tag | NOT PLACED | G-003, only on a green tree |
| F-02 Windows x86-64 | NOT PROVEN | W-005 cell flips |
| C-09 unscoped | scoped | E-004 real-sshd cell green |
| C-12 live fleet | scoped | O-001 operation logged over time |
| Release signing | open | Volmarr signs via S-263 |
| F-17 README | OPEN | Volmarr's own hand |
| GraphQL / packages / polls / badges | deferred | their reopen conditions, then D-1…D-4 |

---

## PART X — THE ORDER OF BATTLE

```
Phase 1 (immediate):   G-001 → G-002 → G-003 → G-004
                       [green suite, v1.0 tag placed & signed, viewport reconciled]

Phase 2 (the build):   C-1 → C-2 → C-3 → C-4 → C-5 → C-6 → C-7
                       C-8 → C-9 → C-10 → C-11 → C-12
                       [every renderer finds its route; git rides the real server]

Phase 3 (the gate):    C-13 → S-402
                       [journey battery green → F-10 flips → the founder walks it]

Phase 4 (the cell):    W-001 → W-006 → S-416
                       [Windows proof → 416/416 — the first roadmap closes]

Phase 5 (the world):   E-001 → E-004
                       [CI, public release, adversarial review, sshd cell]

Phase 6 (the keeping): O-001 → O-005
                       [fleet running, cells measured, studies closed, README settled]

Phase 7 (the doors):   D-1 → D-4, only when their reopen conditions fire
```

**Dependency notes:**
- G-001 precedes everything: no v1.0 claim is honest over a red suite.
- C-12 depends on C-001's exemption seam but not on the page waves — git transport
  can mount as soon as the router exists.
- S-402 requires C-13; S-416 is independent of composition and may run in parallel
  with Phase 2 on a second host.
- E-001's Windows runner may substitute for part of W-004's evidence, but W-002/W-003
  (the native install + SCM service) need a real host regardless.

---

## APPENDIX A — NAMING & COUNTING CONVENTIONS

- Slice commits: one slice per commit, subject `C-NNN: <title>`, body stating
  what was built, the invariants, and the test counts **read back from log files**.
- Batteries: `tests/test_<area>_<slice>.py`; gates: `tests/test_successor_part_N_gate.py`.
- Every banking: battery green + neighbours green, ls-remote verified, map entry,
  register flip where a claim moved.
- Skips are named or they do not exist. Counts are read from disk, never trusted
  from a delivery.

## APPENDIX B — THE HONEST CLOSE

The first roadmap's seed said it best, and this roadmap inherits it:

> Each item becomes a successor slice only when its reopen condition is met or its
> owner calls it forward. Refused items stay refused. NOT PROVEN items flip only on
> counted proof in the cell they name, never on wording.

**Total ledger:** 16 composition wings · 3 open first-roadmap slices · 13 proof debts ·
6 deferred wings with written conditions · 4 standing refusals · 2 bookkeeping debts.
Every one of them now has a name, an owner, and a road.

*— cut with love by the Seiðr-witch of the server fjord* 🖤