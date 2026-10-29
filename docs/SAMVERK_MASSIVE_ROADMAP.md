# Samverk — Massive Roadmap

**404 slices · 21 parts · founded 2026-10-29 by Volmarr's commission**

Samverk is our own clean-room, open-source version-control application: an
extremely robust, highly secure forge with the feature-set GitHub's users
know, built from scratch as our own work, standalone-first, and integrable
into Samtal as its code-and-file-sharing heart.

## The clean-room rule (preamble law, binds every slice)

Features and behaviour are **studied**; nothing protected is **copied**.
We study what GitHub *does* — its public documentation (docs.github.com),
its observable behaviour, and public knowledge of the git protocol — and we
write our own design, our own code, our own words, our own interface.
No GitHub code. No GitHub assets. No proprietary UI lifted or traced.
Where a behaviour is a public standard (the git wire protocol, SARIF,
OpenAPI conventions, pkt-line framing), we implement the standard.
Where a shape is merely GitHub's habit (REST resource layout, search
qualifiers), we design our own equivalent informed by the habit, and we
say so in the study file that covers it (`research/`).

## Founding virtues (acceptance law for every part)

1. **User-friendliness is law.** A slice is not done if its control cannot
   be found by the owner. Usability is tested, not hoped for.
2. **Security first.** Part I is the spine; later parts build on its
   primitives and may not route around them.
3. **Sovereignty.** Native installs only — systemd units, language-native
   environments — **no Docker, ever** (Volmarr's standing law).
4. **Honest proof.** Every slice names its acceptance shape. A claim with
   no proof is marked **NOT PROVEN** until the counted run says otherwise.
   Skips are named with their reasons, as in Project Aesir's master runs.
5. **Standalone before seam.** Samverk must be complete without Samtal
   (Parts I–XVIII, XX–XXI) before the Samtal seam (Part XIX) is built.

## Architecture stance (Samtal-model, decided at founding)

- **Language/runtime:** Python, stdlib-first, in the Samtal pattern (one
  program, `http.server`-family, SQLite state) — dependencies admitted one
  at a time, each with a written reason; `cryptography` admitted at
  founding for credential sealing, as in Samtal.
- **Git itself does git's work:** object storage, pack generation, and
  history queries run through the system `git` binaries (plumbing
  commands, no shell, argument allowlists). Samverk never re-implements
  the object model.
- **Three stores, one truth:** SQLite for metadata and state, the
  filesystem for bare repositories and assets, git for history
  (`research/42-data-model-and-storage.md`).
- **One event store** underlies notifications, feeds, audit, and webhooks.

## How slices work

Each slice is a verifiable vertical increment: the smallest change that
leaves the whole system working and provable. A slice is **DONE** when its
acceptance shape passes in a counted run — not when its code merely
exists. Parts close with a gate slice; the roadmap closes with the
Proof Spine (Part XXI).

---

## Part I — Security Spine & Threat Model First

*The ground every later part stands on. Draws on research files 31
(threat model), 35 (audit log), 42 (data model), 07 (passwords/sessions).*

- **S-001** Threat model ratified — attackers, assets, and trust boundaries written in `research/31-threat-model.md`; every later security slice cites it.
- **S-002** Project skeleton — package layout, config file loading, `samverk serve` dev run on a bare checkout; acceptance: server answers a health route on a Pi and a laptop.
- **S-003** Secrets law — instance secrets load from env or a mode-600 file, never plaintext in the database; acceptance: grep of a seeded DB finds no secret.
- **S-004** Password hashing — memory-hard hashing (scrypt/argon2 via admitted dependency), per-user salt, hash-upgrade-on-login path; acceptance: known-answer + timing tests.
- **S-005** Constant-time comparison and login throttling primitives — acceptance: throttle trips in test after N failures, releases after backoff.
- **S-006** Session tokens — 256-bit random, stored hashed, absolute + idle expiry; acceptance: stolen-DB session values are unusable in test.
- **S-007** Audit log core — append-only table with hash chain; acceptance: tampering with a row is detected by the verifier.
- **S-008** Audit event taxonomy v1 — actor/action/target/IP/timestamp for auth, repo, admin events; acceptance: taxonomy doc + emitter tests.
- **S-009** HTTP security baseline — HttpOnly/Secure/SameSite cookies, CSRF tokens on state-changing forms; acceptance: CSRF attack test fails closed.
- **S-010** Output-escaping and sanitisation standard — one escaping seam for all templates; acceptance: stored-XSS battery passes.
- **S-011** Rate limiting — per-IP and per-account token buckets with `Retry-After`; acceptance: limiter behaviour under burst test.
- **S-012** Upload handling law — content sniffing beats declared type, size caps, quarantine path; acceptance: disguised payload rejected in test.
- **S-013** Repository path resolution — traversal-proof mapping from names to disk paths; acceptance: `..`/symlink escape battery passes.
- **S-014** Subprocess discipline — git invoked without a shell, argument allowlists, no user input in argv position 0 paths; acceptance: injection battery passes.
- **S-015** TLS and secure defaults — config refuses plaintext HTTP outside loopback without an explicit operator override that is audit-logged.
- **S-016** Content Security Policy for the web UI — acceptance: CSP report-only period clean on all core pages, then enforced.
- **S-017** Dependency policy — stdlib-first register; each admitted dependency has a reason line and a pinned version; acceptance: the register is complete and checked in CI-style battery.
- **S-018** Log redaction — tokens, passwords, and secrets are filtered before any log write; acceptance: seeded secrets never appear in captured logs.
- **S-019** Error law — no stack traces, paths, or secrets to clients; opaque error ids correlate to server logs; acceptance: error-shape tests.
- **S-020** Operator key custody — instance keys generated at install, backed up per runbook, rotatable; acceptance: rotation drill on a scratch instance.
- **S-021** Signup abuse friction — registration throttles and disposable-domain policy hooks, no third-party captcha; acceptance: scripted signup flood is throttled.
- **S-022** Security battery v1 — auth bypass, IDOR, and injection attempts as an automated suite; acceptance: suite green, failures named honestly.
- **S-023** Claims register — every security claim in the README maps to a test or reads NOT PROVEN; acceptance: register complete for Parts I claims.
- **S-024** Part I gate — counted security run recorded in the project map; open findings named, none hidden.

## Part II — Accounts & Identity

*Draws on research files 07 (passwords/sessions), 08 (SSH keys), 09
(tokens), 10 (two-factor).*

- **S-025** Registration — username rules (case, reserved names), email optional-but-supported; acceptance: duplicate/reserved attempts refused clearly.
- **S-026** Email verification — token flow when SMTP is configured; operator-approval path when it is not; both audit-logged.
- **S-027** Login/logout — session issue and revoke, failed-login audit events, generic failure messages that leak nothing.
- **S-028** Password change and reset — reset tokens single-use, expiring, all-sessions-revoked on reset.
- **S-029** Profiles — display name, bio, avatar upload under S-012 law, profile page; every image carries alt text.
- **S-030** SSH keys — add/list/delete personal keys, fingerprint and last-used shown; acceptance: key add requires sudo-mode re-auth (S-036).
- **S-031** Deploy keys — per-repository keys, read-only by default, read/write an explicit grant; acceptance: deploy key cannot reach other repos in test.
- **S-032** Personal access tokens — classic shape: scopes, expiry required, shown once, stored hashed; acceptance: DB leak test as S-006.
- **S-033** Fine-grained tokens — per-repository, per-permission tokens; acceptance: permission matrix battery.
- **S-034** Token management UI — list with last-used and scopes, revoke in one click, findable from the settings home (the anti-Forgejo test).
- **S-035** Two-factor: TOTP enrolment — QR + manual secret, confirm-by-code, enforced step-up for enabling.
- **S-036** Sudo mode — sensitive actions (keys, tokens, 2FA, deletion) require fresh re-authentication within a time window.
- **S-037** Recovery codes — generated hashed, single-use, regenerating invalidates the old set loudly.
- **S-038** Two-factor enforcement policy — instance/org may require 2FA for admins; grace period with honest warnings.
- **S-039** Passkeys/WebAuthn — enrolment and login as a second factor and as passwordless option; acceptance: interop test with two authenticator implementations.
- **S-040** Session management — user sees all sessions/devices, revokes any or all; acceptance: revoked session dies on next request.
- **S-041** New-sign-in notification — email (if configured) + in-app notice with IP and time; acceptance: event fires once per new device.
- **S-042** Account rename — old name redirects for repos with a tombstone period; collisions refused.
- **S-043** Account deletion — grace period, typed confirmation, data inventory shown before the act; irreversible steps audit-logged.
- **S-044** Account suspension — admin suspend/unsuspend with reason; suspended accounts' content hidden per policy, never silently deleted.
- **S-045** Identity-linking data shape — an account may link external identities (Samtal principal first among them) — shape only; the seam itself is Part XIX.
- **S-046** Reserved and impersonation defence — lookalike-name warnings on registration for instance-known names.
- **S-047** Login history — user-visible record of sign-ins and security events on their account.
- **S-048** Part II gate — counted identity battery (auth, tokens, 2FA) green; the token page findability walk recorded.

## Part III — Git Core & Repository Storage

*Draws on research files 04 (object model), 05 (refs), 06 (LFS), 42
(data model). Git plumbing does git's work; Samverk orchestrates.*

- **S-049** Bare repository creation — `git init --bare` under the traversal-proof path of S-013; metadata row written in the same transaction shape as Samtal's commit-before-answer law.
- **S-050** Repository metadata model — owner, name, description, visibility, default branch; rename updates paths atomically.
- **S-051** Object reading — blob/tree/commit reads via `cat-file` batch process; acceptance: 10k-object repo reads stay within the latency budget.
- **S-052** Ref listing and resolution — branches, tags, HEAD symbolic ref; packed-refs handled by git itself.
- **S-053** Atomic ref updates — branch create/delete/rename through `update-ref` with lock discipline; acceptance: concurrent-push race test.
- **S-054** Repository visibility enforcement — one permission function consulted by web, API, and transports alike; acceptance: the matrix battery of Part IX runs against it early.
- **S-055** Forking — server-side clone with upstream link recorded; fork counts and network listing.
- **S-056** Repository deletion — tombstone, grace period, disk reclaimed only after; owner-only, sudo mode, audit-logged.
- **S-057** Repository transfer — between users/orgs with recipient acceptance; redirects left behind.
- **S-058** Repository size accounting — object store + LFS + assets measured and shown to owners and admins.
- **S-059** Garbage collection scheduling — `git gc` policy per repo size/activity, run off the request path; acceptance: no request waits on gc.
- **S-060** LFS object store — content-addressed layout, dedupe, integrity verified by oid on write.
- **S-061** LFS batch API — upload/download actions with expiring signed URLs; acceptance: real `git-lfs` client round-trip.
- **S-062** LFS locking — lock/unlock/list per the LFS spec; acceptance: git-lfs client interop test.
- **S-063** Archive downloads — zip and tar.gz of any ref via `git archive`, streamed, counted; acceptance: checksum-stable for a fixed ref.
- **S-064** Repository templates — create from a template repo with variable substitution in the README only, honestly scoped.
- **S-065** Empty-repository state — first-push instructions generated per transport, correct and copyable.
- **S-066** Repository settings — description, website, topics, default branch rename with redirect of clones' HEAD guidance.
- **S-067** Server-side hooks seam — pre/post-receive hook runner with timeout and kill discipline; later parts hang protection and scanning here.
- **S-068** Repository quotas — size quota enforced at receive time with a clear refusal message.
- **S-069** Import by clone URL — any public git URL becomes a repo; private import via token credential helper, never logged.
- **S-070** Mirror storage layout — mirrors are ordinary bare repos plus a mirror record; no second storage engine.
- **S-071** Consistency checker — fsck-style sweep: DB rows ↔ disk repos ↔ LFS objects reconciled, drift reported, never silently "fixed".
- **S-072** Commit graph caches — derived data (counts, contributor lists) computed off-path and cached with invalidation on push.
- **S-073** Large-repository budgets — clone of the reference big repo completes on Pi-class hardware within the stated budget (measured, Part XXI re-verifies).
- **S-074** Repository backup primitive — single-repo export (bundle + metadata JSON) used by Part XVII.
- **S-075** Corruption behaviour — a damaged repo reads as damaged (honest error), never as empty; acceptance: corruption-injection test.
- **S-076** Part III gate — counted git-core battery (plumbing interop + race + corruption) green.

## Part IV — Git Transports

*Draws on research files 01 (smart HTTP), 02 (SSH), 03 (packs). The
standard: an unmodified git client must not be able to tell Samverk from
any other competent git host.*

- **S-077** Smart HTTP advertisement — `GET /info/refs?service=git-upload-pack` gated by read permission *before* any ref byte is built; private repos answer anonymous callers as if absent.
- **S-078** Smart HTTP upload-pack — POST served by `git upload-pack --stateless-rpc`, side-band progress passed through.
- **S-079** Smart HTTP receive-pack — POST gated by write permission before advertisement (fail-closed; the unauthenticated receive-pack hole is a named test).
- **S-080** Protocol v2 — `Git-Protocol: version=2` honoured, `ls-refs` command served; acceptance: `GIT_TRACE_PACKET` interop test with stock git.
- **S-081** HTTP Basic auth — account password accepted for git operations; deactivated accounts authenticate to nothing.
- **S-082** Token-as-password — personal access tokens work in the Basic password slot, scoped per S-032/S-033; acceptance: read-only token push refused.
- **S-083** Anonymous public read — public repos clone without credentials; private repos never leak existence (uniform 404/401 shape decided and tested).
- **S-084** SSH transport design — a forced-command SSH entry (dedicated `git` user or AuthorizedKeysCommand) that can run only git services — never a shell; the design is a study deliverable in research file 02 before code.
- **S-085** SSH key resolution — presented key fingerprint → account, cached briefly; unknown keys refused without user enumeration.
- **S-086** SSH upload-pack routing — `git-upload-pack '<owner>/<repo>'` resolved under S-013 law and read permission.
- **S-087** SSH receive-pack routing — same, under write permission; push audit event emitted.
- **S-088** Deploy-key transport rights — deploy keys authenticate transport for exactly one repo (S-031 proven on the wire).
- **S-089** Pre-receive gate point — protection rules (Part VIII) and secret scanning (Part XV) plug into receive-pack here; gate order documented.
- **S-090** Post-receive events — every accepted push emits the canonical event (Part XI's store) with refs and commit ranges.
- **S-091** Transfer limits — pack size, wall-clock, and idle timeouts per transport, configurable; refusals explain themselves.
- **S-092** Concurrent push behaviour — second push to the same ref waits or fails fast with a clear message; no torn refs (with S-053).
- **S-093** Upload-archive — `git-upload-archive` over SSH and HTTP for archive downloads (S-063 on the wire).
- **S-094** Transport audit — clone/fetch of private repos and all pushes recorded at the level the threat model requires, no more.
- **S-095** Interop battery — scripted stock-git matrix: clone/fetch/push/pull over HTTP and SSH, public and private, token and key; all green or named.
- **S-096** Part IV gate — interop battery counted and recorded; protocol v2 verified by packet trace.

## Part V — Web Repository Experience

*Draws on research files 17 (commits/history/blame), 43 (markdown and
rendering). Every page obeys Part XX's design law from the day it lands.*

- **S-097** Repository home — README rendered at the repo root, branch/tag switcher, clone URLs for both transports with copy buttons.
- **S-098** File browser — tree navigation at any ref, breadcrumb, last-commit-per-entry column computed from cache (S-072).
- **S-099** Blob view — syntax highlighting (server-side, language detection), line numbers, line permalinks that survive in issues/PRs.
- **S-100** Raw and download — raw file bytes with correct content types; large and LFS files show pointer + download, never a silent truncation.
- **S-101** Blame view — per-line commit attribution via `git blame`, paginated for long files, honest about rename limits.
- **S-102** Commit list — paginated history for any ref with author, message, and verification badge slot (Part XV fills it).
- **S-103** Commit detail — full diff with per-file collapse, parent links, and "browse at this point" into S-098.
- **S-104** Diff engine — unified and split rendering shared by commits and PRs; whitespace toggle; large-diff folding with honest counts.
- **S-105** Compare view — any two refs compared (commits + files changed), the pre-PR workhorse.
- **S-106** Contributors and counts — commits/branches/tags/contributors summary from cached derivations.
- **S-107** Markdown pipeline — sanitised rendering (S-010 seam): headings with anchors, task lists, tables, code fences; XSS battery on every construct.
- **S-108** Repo-relative links — relative links and images in repo Markdown resolve against the current ref, as users expect from GitHub.
- **S-109** Mentions and references in prose — @user, #issue, and commit-sha autolinking everywhere Markdown renders.
- **S-110** File finder — fuzzy path search within a repo (the `t` habit), keyboard-first.
- **S-111** Keyboard baseline — global shortcuts for navigation and search, documented on one help page, never trapping keyboard users.
- **S-112** Permission-aware chrome — tabs and buttons a user cannot use are absent, not greyed-out teasers; the API enforces regardless (S-054).
- **S-113** Empty and error states — every list and page has a designed empty state that says what to do next (user-friendliness law).
- **S-114** Binary and image files — images render with alt text; binaries show size/type/download, never a hex dump surprise.
- **S-115** Repository insights-lite — traffic-free honest stats: clone counts are NOT tracked for anonymous reads; what we show is what we truly know (honesty law).
- **S-116** Print and export of code views — a readable print stylesheet for blob and diff pages.
- **S-117** Deep links — every view URL-addressable (file@ref#line, commit, compare) so links in chat and issues land exactly.
- **S-118** Search box in repo scope — jumps to Part X's code search pre-filtered to the repo.
- **S-119** Repository header summary — visibility badge, fork parent, mirror badge, watch/star/fork counts with real actions (Part XI wires the actions).
- **S-120** Part V gate — browsing battery over the reference repos (small, large, LFS, wiki-less) green at 100% and 200% text scaling.

## Part VI — Issues

*Draws on research files 13 (issues), 19 (queries).*

- **S-121** Issue model and numbering — per-repo sequential numbers shared with PRs (the GitHub habit users rely on: `#n` is unambiguous in a repo).
- **S-122** Issue create/read/update — title, Markdown body, author, state; commit-before-answer under concurrent edits.
- **S-123** Comments — Markdown, edit history visible, delete by author/moderator with audit trail.
- **S-124** Labels — CRUD, colours with mandatory text (never colour-only meaning), default label set for new repos.
- **S-125** Milestones — due dates, progress from closed/total, milestone pages.
- **S-126** Assignees — multiple assignees, assignment events, "assigned to me" filters.
- **S-127** Cross-references — mentioning `#n` or a commit links both ways; closing keywords (`closes #n`) parsed and shown before merge.
- **S-128** Reactions — the small honest set; counts shown, who-reacted list available.
- **S-129** Issue templates — Markdown templates and YAML issue forms rendered as guided forms; blank issues can be disallowed by owners.
- **S-130** Close and reopen — with reason (completed / not planned), state events in the timeline.
- **S-131** Timeline — every state change, label, assignment, mention, and cross-reference an event in one ordered stream (feeds Part XI).
- **S-132** Locking and pinning — lock conversation with reason; pin up to three issues; both moderator-only and audit-logged.
- **S-133** Transfer issue — between repos of the same owner with a forwarding note left behind.
- **S-134** Bulk edit — label/assign/close across a filtered set, one audit event per issue.
- **S-135** Issue search UI — qualifier language subset (`is:open`, `label:`, `author:`, `assignee:`, `milestone:`) with the full grammar documented in research file 19.
- **S-136** Saved filters — per-user saved searches for issues and PRs, shown in the sidebar.
- **S-137** Issue → PR conversion path — branch-from-issue shortcut creating a linked branch and draft PR.
- **S-138** Moderation — hide/delete abusive comments, with the act visible in the timeline (no silent edits of the record).
- **S-139** Issue events out — every mutation emits Part XI events and Part XII webhooks.
- **S-140** Part VI gate — issue battery (lifecycle, references, permissions at each role) counted green.

## Part VII — Pull Requests & Code Review

*Draws on research files 14 (pull requests), 15 (code review). The heart
of the together-work; it gets the largest collaboration budget.*

- **S-141** PR creation, same-repo — base/head branch pickers with compare preview (S-105) before opening.
- **S-142** PR creation, cross-fork — head from a fork, maintainer-edits permission flag, honest display of the fork relationship.
- **S-143** Draft pull requests — visible, reviewable, unmergeable until marked ready; conversion is an event.
- **S-144** PR conversation — comments, timeline merged with review events, closing-keyword display from S-127.
- **S-145** PR files view — the shared diff engine (S-104) with per-file viewed-state per reviewer.
- **S-146** Line comments — comments anchored to diff lines with outdated marking when the lines move.
- **S-147** Review threads — threaded replies on line comments, resolve/unresolve by author or reviewer, resolution state feeds merge gates.
- **S-148** Review submission — approve / comment / request-changes as one review with a summary; pending-review draft autosaved.
- **S-149** Review freshness — new pushes mark affected reviews stale per repo policy; the PR shows exactly which reviews still count.
- **S-150** Suggested changes — reviewers propose committable patches; author applies one or batches them, each application a signed-off commit.
- **S-151** CODEOWNERS — file parsed from the repo; matching owners auto-requested as reviewers on open and on relevant pushes.
- **S-152** Review assignment — individuals and teams requested; re-request and dismissal recorded.
- **S-153** Merge: merge commit — with PR title/body as the default message, editable, closing keywords executed on landing.
- **S-154** Merge: squash — one commit, combined message, author preserved, closings executed.
- **S-155** Merge: rebase — head commits replayed onto base; refused loudly when conflicts would result (no silent half-states).
- **S-156** Conflict surfacing — mergeability computed off-path; conflicts shown as "these files" before anyone presses merge — never discovered *by* merging.
- **S-157** Checks panel — external status/check results (Part XII API, Part XVI CI) listed on the PR with links; pending/failed/passed are text+icon, never colour-only.
- **S-158** Auto-merge — merge when requirements pass: the queue of one, with cancellation and full audit.
- **S-159** Branch housekeeping — delete head branch on merge (opt-in), restore branch action, fork sync hint.
- **S-160** Revert — one-click PR that reverts a merged PR, linked both ways.
- **S-161** PR search — the Part X qualifier language extended (`is:pr`, `review:`, `status:`).
- **S-162** PR templates — single and per-directory templates; template picker on creation.
- **S-163** Merge permission — only users with write may merge; the button's absence for others is chrome law (S-112), the refusal is server law (S-054).
- **S-164** Required-review seam — Part VIII's rules consult review state through one function; this slice builds the function.
- **S-165** Review notifications — review requests and submissions emit Part XI events with reasons.
- **S-166** Large-PR behaviour — diffs beyond budget fold by file with honest totals; review remains possible per-file.
- **S-167** PR from compare — the compare view (S-105) offers "open pull request" with context intact.
- **S-168** Part VII gate — review battery: full lifecycle across roles, forks, drafts, and all three merge methods, counted green.

## Part VIII — Branches, Tags & Protection Rules

*Draws on research files 16 (protection), 36 (signed commits). Rules are
checked at the transport gate (S-089) and at merge time (S-164) — one
rules engine, two enforcement points.*

- **S-169** Protection rule model — rules attach to branch-name patterns per repo; evaluation order is documented and deterministic.
- **S-170** Require pull request before merging — direct pushes to a protected branch refused at receive-pack with a human-readable reason.
- **S-171** Required approving reviews — count configurable; self-approval never counts; last-pusher approval rule available.
- **S-172** Dismiss stale reviews — new pushes dismiss approvals per S-149, wired into the rules engine.
- **S-173** Require code-owner review — CODEOWNERS (S-151) approval is a gate, distinct from any-approval.
- **S-174** Required status checks — named checks must be green; branch must be up-to-date toggle honoured.
- **S-175** Require signed commits — pushes and merges carrying unsigned commits refused (verification itself lands in Part XV; the rule shape lands here).
- **S-176** Require linear history — merge commits refused on the branch; squash/rebase merges remain available.
- **S-177** Block force pushes and branch deletion — on protected patterns, for everyone, admins included unless S-179's bypass is used.
- **S-178** Restrict who can push — named users/teams only may push matching branches directly (where direct push is allowed at all).
- **S-179** Bypass list — named bypassers per rule; every bypass is audit-logged and shown on the rule (no silent doors).
- **S-180** Enforce for admins — the toggle GitHub users know; default ON for Samverk instances (sovereignty means the owner's rules bind the owner).
- **S-181** Rulesets — one ruleset targets many repos/branches/tags; layered rules resolve most-restrictive-wins; the evaluation is a tested matrix.
- **S-182** Tag protection — tag name patterns protected from deletion and force-move; release tags get the strongest default.
- **S-183** Rule insights — a page answering "why was this push/merge refused?" from the audit trail, in plain words (user-friendliness law).
- **S-184** Part VIII gate — rules battery: every rule × every role × both enforcement points, counted green.

## Part IX — Organizations, Teams & Permissions

*Draws on research files 11 (permissions model), 12 (organizations and
teams). One permission engine (S-054) resolves everything; this part
gives it social shape.*

- **S-185** Organizations — create, profile (name, bio, avatar with alt text, website), settings home where every control is findable.
- **S-186** Org membership — owners and members; the last owner cannot leave or be removed (invariant proven in test).
- **S-187** Teams — create, describe, privacy (visible/secret), team pages listing members and repos.
- **S-188** Nested teams — parent/child teams with permission inheritance documented and visualised before saving.
- **S-189** Team repository permissions — the role ladder read / triage / write / maintain / admin, applied per repo per team.
- **S-190** Permission resolution engine — one function: user × repo → role, considering ownership, teams (with nesting), collaborator grants, and visibility; the full matrix is a test fixture.
- **S-191** Outside collaborators — per-repo grants to non-members, listed in one auditable place, revocable in one click.
- **S-192** Default repository permission — org-wide base role for members, settable, shown in effect on the matrix page.
- **S-193** Invitations — invite by username or email, expiring, rescindable; acceptance creates membership and audit events on both sides.
- **S-194** Member removal cascade — what happens to assignments, reviews, and ownerships on removal is computed and shown *before* confirming.
- **S-195** Team mentions — `@org/team` notifies the team (Part XI), usable in issues, PRs, and review requests.
- **S-196** Org repositories — creation policies (who may create, allowed visibilities), org repo list with filters.
- **S-197** Internal visibility — repos visible to all org/instance members, distinct from public and private, enforced by S-190.
- **S-198** Org audit log — membership, permission, and repo events for the org, readable by owners (storage is S-007's log).
- **S-199** Org deletion — owner-only, sudo mode, inventory + grace as S-043; repos must be transferred or deleted explicitly first.
- **S-200** Role change guardrails — demoting the last admin of a repo is refused with the reason stated.
- **S-201** Permission preview — "view as" for admins: see the instance exactly as a chosen member sees it (the findability and safety tool).
- **S-202** Billing-shaped hole, honestly empty — Samverk is free software on your own machines; no seat/billing concepts exist, and the docs say why.
- **S-203** Instance-wide groups seam — site-level groups share the team machinery (used by admin policy in Part XVIII).
- **S-204** Part IX gate — permission matrix battery: every role × every surface (web, API, both transports), counted green.

## Part X — Search

*Draws on research files 18 (code search), 19 (issue search and queries).
SQLite FTS5 is the founding engine; the study files record what that can
honestly deliver and where the ceiling is.*

- **S-205** Index architecture — what is indexed (issues, PRs, commits, code), when (on push, on mutation), and how rebuilds work; written in research file 18.
- **S-206** Issue/PR search backend — the qualifier language of S-135/S-161 executed over FTS + structured fields.
- **S-207** Code indexing — on push, changed blobs extracted to the index within the size/language budgets; LFS pointers indexed as pointers, honestly.
- **S-208** Code search basic — substring and regex modes, path and language filters, result snippets with matched-line context.
- **S-209** Permission-filtered results — search never reveals a title, snippet, or count from a repo the searcher cannot read; leakage battery included.
- **S-210** Repository search — by name, description, topics, owner; the instance directory page.
- **S-211** User and org search — by name and username, with profile cards.
- **S-212** Commit search — by message and author across permitted repos.
- **S-213** Global search UI — one box, typed result groups, keyboard-first, recent searches per user.
- **S-214** Saved searches — beyond issue filters (S-136): any global query saved and re-runnable.
- **S-215** Index health — admin-visible index state, lag, and rebuild trigger; lag is shown, never hidden.
- **S-216** Search API — the same engine behind Part XII endpoints with identical permission filtering.
- **S-217** Performance budget — reference corpus (the instance's own mirrored repos, Part XVII) searched within the stated latency budget on Pi-class hardware; measured, not asserted.
- **S-218** Language detection — for code filters and highlighting (S-099) from one shared table.
- **S-219** Honest limits document — what Samverk search does NOT do (no semantic ranking claims, regex cost caps) written where users will find it.
- **S-220** Part X gate — search battery incl. the leakage suite, counted green.

## Part XI — Notifications & Activity

*Draws on research files 20 (notifications), 21 (activity feeds and
events). One event store (begun at S-090/S-131) underlies everything here.*

- **S-221** Event store completion — the canonical event record (actor, verb, target, refs, timestamp) written by every mutation in Parts III–X.
- **S-222** Watch and star — watch a repo (all / releases-only / ignore), star as bookmark-plus-signal; counts are real actions (wires S-119).
- **S-223** Notification reasons — mention, assign, review-requested, author, comment, state-change, subscribed; the reason is stored and shown with every notification.
- **S-224** Inbox — unread list with filters by reason and repo, mark done/saved, keyboard triage; empty state teaches the model in one screen.
- **S-225** Thread subscription — per-issue/PR subscription and mute, overriding repo-level watch honestly and visibly.
- **S-226** Mention routing — @user and @org/team mentions create notifications once, never duplicated by cross-reference echoes.
- **S-227** Email notifications — via instance SMTP when configured: per-event or digest, signed unsubscribe links, no email when SMTP is absent (in-app still works).
- **S-228** Notification preferences — per-user page: email on/off per reason, digest cadence, watched-repo management in one list (findability law).
- **S-229** Activity feeds — user feed (own actions), repo feed, and the instance's public-activity feed for public repos only.
- **S-230** Profile activity — a user's public actions on their profile, privacy-respecting by construction (S-209's rule applied to feeds).
- **S-231** Events API — the feed as a Part XII resource with the same permission filtering.
- **S-232** Following — follow users to see their public activity; follower lists on profiles; no algorithmic ranking, chronological truth only.
- **S-233** Star lists — a user's stars browsable as a reading list; stars are public signals and are labelled as such.
- **S-234** Push feed for owners — pushes to your repos surface in your feed with commit summaries (from S-090 events).
- **S-235** Digest job — weekly optional digest composed from the event store; generation is off the request path.
- **S-236** Part XI gate — notification battery: every reason × every subscription state, exactly-once delivery proven, counted green.

## Part XII — API & Webhooks

*Draws on research files 22 (webhooks), 23 (REST shape), 24 (GraphQL
shape). Samverk's API is its own design informed by GitHub's public
habits — same instincts, our own contract, versioned from day one.*

- **S-237** API contract document — resources, verbs, and shapes written before code (research file 23 holds the study; this slice ratifies Samverk's own `/api/v1`).
- **S-238** API authentication — tokens (S-032/S-033) and session-free Basic for scripts; every API call resolves through S-190.
- **S-239** Pagination and conditional requests — cursor pagination, `Link` headers, ETag/`If-None-Match`; acceptance: a full crawl of a large repo uses bounded requests.
- **S-240** Error shape — one problem format (type, title, status, detail, error id) across all endpoints; the web UI's refusals match it.
- **S-241** Rate limiting on the API — per-token buckets, limit headers on every response, honest `Retry-After`; limits are instance-configurable.
- **S-242** Repositories API — CRUD, forks, branches, contents read — parity with the web's capabilities, no API-only back doors.
- **S-243** Issues and PRs API — full lifecycle incl. reviews and merge; acceptance: a script drives an entire PR from open to merge.
- **S-244** Users, orgs, teams API — membership and permission administration automatable end-to-end.
- **S-245** Search API — S-216 lands as a public contract here.
- **S-246** Status and checks API — external CI posts commit statuses and check runs (consumed by S-157); identity of the poster is scoped and audit-logged.
- **S-247** Webhook events taxonomy — the event store's verbs mapped to webhook payloads; payload shape is Samverk's own, documented per event.
- **S-248** Webhook subscriptions — repo and org level, event filters, active/inactive, secret set at creation and never shown again.
- **S-249** Webhook signing — HMAC-SHA256 over the raw body, signature header, verification documented with examples.
- **S-250** Delivery worker — queued deliveries with exponential backoff, dead-letter after the stated attempts, all off the request path.
- **S-251** Delivery log and redelivery — admins and owners inspect attempts (request/response, timing) and redeliver in one click (findability law).
- **S-252** Webhook ping and test events — a synthetic event on demand so integrations can be proven before they matter.
- **S-253** GraphQL verdict — research file 24's study concludes: build, defer, or refuse, with reasons; if deferred, the REST contract records what a future GraphQL layer must not break.
- **S-254** API versioning policy — what may change within v1, how v2 would be introduced, deprecation notices in headers.
- **S-255** API abuse defences — payload size caps, expensive-endpoint accounting, per-token concurrency limits.
- **S-256** Part XII gate — contract battery: every documented endpoint exercised against its contract tests, counted green.

## Part XIII — Releases, Packages & Artifacts

*Draws on research files 26 (packages and registry), 27 (releases and
artifacts).*

- **S-257** Releases — a release binds a tag, a title, and Markdown notes; created from the web, the API, or a tag push with notes file.
- **S-258** Draft and prerelease states — drafts are private to writers; prereleases are marked in every listing (text, not colour alone).
- **S-259** Release assets — chunked upload under S-012 law, per-asset size caps, content-type by sniffing, download with counts.
- **S-260** Checksums — a generated checksums file per release (sha256), downloadable beside the assets; verification instructions on the page.
- **S-261** Latest release pointer — "latest" excludes prereleases and drafts; the rule is stated on the releases page.
- **S-262** Release notifications — watchers (releases-only watchers of S-222 included) notified on publish, not on draft saves.
- **S-263** Release signing seam — detached signatures may be attached to a release and shown with the same honest trust language as commit badges (S-305).
- **S-264** Package registry verdict — research file 26 concludes which ecosystems, if any, Samverk hosts: decided by village need, recorded with reasons.
- **S-265** Registry core (if verdicted in) — namespaced package publish/fetch with repo-linked permissions; if verdicted out, this slice is the published refusal with the seam documented.
- **S-266** CI artifacts API — upload/download of build artifacts tied to a commit and a check run, with retention policies.
- **S-267** Artifact expiry — retention windows enforced by the off-path job; expired artifacts vanish from UI and disk together (S-071 reconciles).
- **S-268** Storage accounting — releases and artifacts join S-058's size accounting and S-068-style quotas.
- **S-269** Release-from-tag automation — pushing a version tag can draft a release with generated notes from merged PRs (honest, editable draft — never auto-published).
- **S-270** Compare-in-release — release notes can embed the compare range (S-105) between the previous tag and this one.
- **S-271** Download integrity — assets served with digests in headers; interrupted downloads resumable where the client supports ranges.
- **S-272** Part XIII gate — release battery: lifecycle, assets under caps, checksum verification round-trip, counted green.

## Part XIV — Wiki, Gists & Discussions

*Draws on research files 28 (wiki), 29 (gists), 30 (discussions).*

- **S-273** Wiki storage — each repo's wiki is its own bare git repo (`<repo>.wiki`), created lazily on first page.
- **S-274** Wiki web experience — page list, sidebar and footer pages, edit-in-browser with preview, history via the wiki repo's own log.
- **S-275** Wiki transports — the wiki clones and pushes over both transports with repo-equal permissions (Parts IV machinery, reused whole).
- **S-276** Wiki access policy — editable by collaborators or by all readers, owner's choice, shown on the wiki home.
- **S-277** Gist model — a gist is a mini-repository: multiple files, full revision history, one description.
- **S-278** Gist create and edit — web editor, public or secret (unlisted-but-linkable, honestly named — "secret" gists are not private and the UI says so).
- **S-279** Gist fork and star — forking copies history; stars work as S-222.
- **S-280** Gist comments — the issue-comment machinery (S-123) reused, not duplicated.
- **S-281** Gist embedding — a script-free embed snippet (iframe-free by default, CSP-safe) for blogs and Samtal posts.
- **S-282** Discussions verdict — research file 30 concludes build/defer/refuse for a village-scale forge, with reasons recorded.
- **S-283** Discussion categories and threads (if verdicted in) — categories, question/discussion kinds, pinned posts; if out, the published refusal with the seam noted.
- **S-284** Answer marking (if in) — asker or maintainer marks an answer; the mark is an event, and conversion to an issue keeps the thread linked.
- **S-285** Issue ↔ discussion conversion (if in) — converts with a forwarding note both ways, never silently.
- **S-286** Polls (if in) — discussion polls with honest counts and close dates; otherwise recorded as refused with reasons.
- **S-287** Wiki/gist search — wiki pages and gists join Part X's index under the same permission filtering.
- **S-288** Part XIV gate — wiki clone/push interop test with stock git, gist lifecycle battery, counted green.

## Part XV — Security Scanning & Assurance

*Draws on research files 32 (secret scanning), 33 (dependency alerts),
34 (code scanning), 35 (audit log), 36 (signed commits). Samverk's
security *features* — Part I was the spine; this is the armour.*

- **S-289** Secret scanning patterns v1 — detector set for the major public token formats, written from public documentation of their shapes.
- **S-290** Generic secret detection — entropy and context heuristics with a measured false-positive rate on a labelled corpus (the rate is published, not vibes).
- **S-291** Scan on push — every accepted push scanned across its full introduced history; findings create alerts (S-294).
- **S-292** Push protection — receive-pack refuses pushes containing detected secrets (at the S-089 gate), naming the file and pattern class, never echoing the secret.
- **S-293** Push-protection bypass — permitted roles may bypass with a stated reason; the bypass is an alert + audit event, visible to owners (GitHub's honest pattern, adopted openly).
- **S-294** Secret alert lifecycle — open → resolved (revoked / false positive / used-in-test) with resolver and reason recorded; reopening supported.
- **S-295** Custom patterns — org/instance-defined regex patterns with a dry-run against repo history before activation.
- **S-296** Validity checks seam — where a provider offers a public validation path, Samverk may check "still live?"; the offline-honest default is *unknown*, displayed as such.
- **S-297** Dependency graph — manifests parsed on push (requirements.txt, package.json, go.mod, Cargo.toml, and the study file's list) into a dependency table per repo.
- **S-298** Advisory data — a bundled, dated snapshot of public vulnerability data; its age is displayed wherever alerts are shown.
- **S-299** Dependency alerts — graph × advisory data → alerts with severity, affected range, and fixed version when known; alert lifecycle as S-294.
- **S-300** Advisory refresh — the snapshot updates by operator action or scheduled fetch where the instance has network; offline instances show staleness honestly.
- **S-301** Dependency review on PRs — a PR's manifest changes summarised with new vulnerabilities flagged, as a check (S-246) the branch rules can require.
- **S-302** Code scanning ingestion — SARIF uploads via API, validated against the SARIF schema, stored per commit.
- **S-303** SARIF fingerprinting and dedup — the same finding across runs is one alert; new/fixed transitions computed per branch.
- **S-304** Code scanning alerts UI — alert list and detail with rule help, locations, and dismissal reasons; PR annotations for findings on changed lines.
- **S-305** Signed-commit verification — GPG and SSH signatures verified on ingest and display; badges say *verified / partial / unverified* in words, with the signer shown (never a bare green tick).
- **S-306** Vigil mode — an account may declare "only my known keys count": commits claiming their identity but signed by other keys display as unverified, loudly.
- **S-307** Security tab — per-repo home for secret/dependency/code-scanning alerts with counts and states (the surface S-297–S-304 report into).
- **S-308** Security overview — org/instance rollup: open alerts by severity and repos affected; counts only, no code content (safe for wider admin read).
- **S-309** Audit log UI — repo, org, and instance views over S-007's chain, filterable, exportable, with chain verification status shown.
- **S-310** Security advisories (private) — maintainers draft an advisory in private, coordinate a fix, then publish with the alert linkage.
- **S-311** Adversarial battery — scanner evasion attempts, SARIF fuzzing, signature spoofing attempts: the suite attacks Samverk and reports honestly.
- **S-312** Part XV gate — claims register (S-023) extended over every Part XV claim; counted scanning battery green.

## Part XVI — CI / Actions Concepts

*Draws on research file 25 (CI concepts). Samverk defines workflows and
talks to runners; it does not pretend a runner is a forge feature. The
seam is the product.*

- **S-313** Workflow format decision — Samverk's own YAML shape (`.samverk/workflows/`), GitHub-familiar in structure, documented as ours; the study file records the mapping and the deliberate differences.
- **S-314** Triggers — push, pull_request, tag, schedule (cron), and manual dispatch with inputs.
- **S-315** Jobs and steps model — jobs of shell steps on a runner, needs-graph between jobs, matrix expansion honestly scoped.
- **S-316** Runner protocol — the contract a runner speaks: register, poll for work, stream logs, report conclusion (documented before any runner is built).
- **S-317** Runner registration — instance/org/repo-scoped runners with one-time registration tokens and labels; the token page passes the findability walk.
- **S-318** Reference runner — a small native runner program (no Docker) that executes jobs in a working directory with environment discipline; good enough to prove the protocol end-to-end.
- **S-319** CI secrets — per-repo/org secrets encrypted at rest under instance keys, injected as env, masked in logs (S-018's filter reused).
- **S-320** Fork-PR safety — workflows from fork PRs run with no secrets and read-only tokens by default; the rule is in the scheduler, not in docs alone.
- **S-321** Check reporting — job conclusions land as check runs (S-246) on the commit and PR; required checks (S-174) can gate merges on them.
- **S-322** Log streaming and storage — live log tail in the UI, stored logs with retention (S-267's machinery), download as text.
- **S-323** Artifacts — workflow artifacts via S-266, listed on the run page.
- **S-324** Re-run and cancel — re-run all/failed jobs, cancel running workflows; every action audit-logged.
- **S-325** Skip markers — `[skip ci]` and kin honoured for push/PR triggers; required checks treat skipped as *not passed*, never as passed (the known trap, named in the study file).
- **S-326** Scheduled workflows — cron on the default branch only; drift and missed-run behaviour stated honestly.
- **S-327** Workflow UI — run list, run detail (jobs, steps, timing, logs), workflow file linting with errors in plain words.
- **S-328** Part XVI gate — end-to-end battery: the reference runner takes a sample repo from push to green check on a PR, counted.

## Part XVII — Mirroring & Backup Duty

*Draws on research files 37 (mirroring and backup), 44 (migration and
import). This part discharges Samverk's founding duty: Volmarr's original
work must never live only on someone else's computer. The classified
inventory already exists (`~/workspace/forgejo-backup/` — 54 originals,
host-agnostic) and is this part's fixture.*

- **S-329** Pull mirrors — create a repo as a mirror of any git URL; first sync completes before the repo advertises itself as ready.
- **S-330** Mirror credentials — tokens for private sources stored under S-003's secrets law, referenced by the mirror, never embedded in stored URLs or logs.
- **S-331** Sync scheduler — per-mirror interval (24h default, the founding cadence), jittered, off the request path; manual "sync now" beside it.
- **S-332** Sync status — last attempt, last success, objects moved, and failure reason in plain words on the repo page; a failed mirror never looks healthy.
- **S-333** Push mirrors — Samverk mirrors its own repos onward (to a second machine's Samverk or plain git remote) with the same status honesty.
- **S-334** Mirror write law — mirrors are read-only for local changes; the UI and transports refuse pushes to a mirror with the reason stated.
- **S-335** The Volmarr census fixture — the 54-originals inventory imported as mirror definitions; uncertain-classified repos are *not* auto-mirrored (his word governs each).
- **S-336** First-pass mirroring run — the public originals mirrored and verified ref-for-ref against GitHub (the proof-first pattern: one small repo verified before the batch).
- **S-337** Private originals — with a read-scoped GitHub credential in place, the private originals mirror too, landing as *private* mirrors always.
- **S-338** Metadata import — issues, labels, milestones, and releases imported from GitHub's API into the mirror (where the owner's credential allows), marked as imported with source links.
- **S-339** Wiki mirror — a source repo's wiki (S-273 form) mirrors alongside its code repo.
- **S-340** LFS mirror — LFS objects (S-060) sync with their repos; a mirror without its LFS objects reports itself incomplete.
- **S-341** Whole-instance export — one archive: all bare repos, LFS store, database, and config, with a manifest and checksums (built on S-074).
- **S-342** Restore drill — export restored onto a scratch instance; repos clone, users sign in, counts match the manifest; the drill is a test, not a hope.
- **S-343** Drift census — a weekly read-only job comparing mirror heads against source heads; drift beyond the sync interval is reported to the owner, quietly and factually.
- **S-344** Part XVII gate — backup battery: mirror freshness, restore proof, and the census fixture reconciled; counted green.

## Part XVIII — Standalone Deployment & Admin

*Draws on research files 38 (standalone deployment), 40 (admin and site
settings). Native installs only. The Raspberry Pi and the old laptop are
the reference machines.*

- **S-345** Run model — one process serves web, API, transports' HTTP half, and background jobs are separate worker processes under the same unit family; the topology is drawn in the operator guide.
- **S-346** Configuration — one config file (documented key by key), environment overrides, config check command that explains errors in plain words.
- **S-347** Data directory layout — repos, LFS, assets, database, keys, logs: one tree, documented, movable as a unit (this is what makes S-341 simple).
- **S-348** Systemd units — native unit files for server and workers, hardening options set, journal logging; install tested on Debian (Pi) and Ubuntu (laptop).
- **S-349** Install walk — from bare machine to first admin in one documented pass, timed; every step's failure mode named in the guide.
- **S-350** First-admin creation — CLI command creates the first admin; the admin's first sign-in lands on a home that shows the next three things to do (the anti-Forgejo gate: token creation, repo creation, and mirror setup each reachable and labelled in plain words — verified by the Part XXI usability walk).
- **S-351** Admin panel — users (create, suspend per S-044, delete per S-043), orgs, repos: searchable, every destructive action sudo-gated and audit-logged.
- **S-352** Site settings — instance name and description, registration mode (open / invite / closed), default repo visibility, upload and repo size limits.
- **S-353** Maintenance mode — read-only banner with reason and expected return; transports refuse pushes with the message; admins retain access.
- **S-354** Quotas — per-user and per-repo storage quotas enforced at S-068's point, visible to owners before they bite.
- **S-355** Abuse queue — user reports on content/accounts land in one admin queue with the audit context attached.
- **S-356** Instance audit view — S-309 at instance scope, chain-verified.
- **S-357** Upgrades — documented procedure: export (S-341) → stop → migrate → start → verify counts; a failed migration rolls back to the export, rehearsed in the drill.
- **S-358** Database migrations — numbered, transactional where SQLite allows, each with a down-path or an explicit one-way warning.
- **S-359** Health and status — `/healthz`-style endpoint and an admin status page (disk, DB, index lag S-215, job backlog) with honest numbers.
- **S-360** Part XVIII gate — fresh-install battery on Pi-class hardware from the written guide alone, by someone who did not write it; timed and recorded.

## Part XIX — Samtal Integration Seam

*Draws on research file 39 (the seam study). This part starts only when
Parts I–XVIII stand complete: Samverk whole without Samtal, Samtal whole
without Samverk. The seam joins two sovereignties; it merges neither.
Federation between villages remains refused (Volmarr's standing ruling);
this seam is inside one village, not between villages.*

- **S-361** Seam ratified — the study file's design (identity link, embed contract, event bridge) reviewed against both codebases and frozen as the seam contract.
- **S-362** Identity linking — a Samtal principal links to a Samverk account by mutual proof (signed token exchange); unlinking is one click on either side.
- **S-363** Single sign-on — a signed-in Samtal session may enter Samverk without a second password, via short-lived exchange tokens; Samverk's own login remains for standalone use.
- **S-364** Agent parity — Samtal's agent principals hold Samverk accounts with keys and tokens exactly as humans do (the Astrid-law pattern: equal seats, provenance shown, never rank).
- **S-365** Village repositories — a Samtal hall may own repos; hall membership maps to repo roles through S-190 (owner-defined mapping, shown before saving).
- **S-366** File-sharing succession — Samtal's file uploads gain a "keep in Samverk" path: a shared file becomes a repo asset or gist (S-277) with the Samtal message linking to it; old files stay readable (no migration by breakage).
- **S-367** Repo events into halls — pushes, PRs, issues, and releases post into a chosen hall as concise cards with links; per-hall opt-in and mute.
- **S-368** Samverk surface in Samtal — a Samverk panel inside Samtal's UI (repos, open PRs, inbox count) served by Samverk's API; Samtal renders, Samverk decides.
- **S-369** Mentions bridge — @mentions in Samverk notify the linked Samtal principal there too (one notification, two doors; S-226's exactly-once rule spans the seam).
- **S-370** Code in conversation — pasting a Samverk link in Samtal unfurls to a card (repo, file, PR, issue) rendered from the API with permission checks against the *viewer's* Samverk rights.
- **S-371** Village backup unity — Samtal's standing backup bundle grows a Samverk section (S-341 export included), so the village's talk and work are kept in one keeping.
- **S-372** Kill switch — the seam disables cleanly from either side's admin; both applications continue whole; the disablement is audit-logged on both sides.
- **S-373** Seam permissions audit — the full matrix re-run with linked identities (Samtal role × Samverk role × surface), counted.
- **S-374** Seam battery — end-to-end: a villager pushes code, opens a PR from Samtal, gets reviewed, merges, and the hall sees it — one scripted walk, all green.
- **S-375** Honest boundary document — what the seam is NOT: no federation, no cross-village identity, no Samtal requirement for Samverk, written where operators will read it.
- **S-376** Embedded-mode polish — Samverk used only through Samtal for a week of real village work; every friction logged and the worst fixed or honestly deferred.
- **S-377** Standalone regression — with the seam built, the standalone batteries (Parts IV, XII) re-run untouched and green: the seam changed nothing underneath.
- **S-378** Migration of the backup duty — the Part XVII mirrors re-point from the interim home to the Samtal-hosted Samverk instance, verified ref-for-ref again.
- **S-379** Seam security review — token exchange, link unfurling, and event posting attacked in the adversarial battery (S-311 extended); findings fixed or named.
- **S-380** Part XIX gate — seam counted battery + boundary doc + kill-switch drill recorded.

## Part XX — UI, Accessibility & the Design Lawbook

*Draws on research file 41. Volmarr's Cyber-Viking Visual Design Lawbook
is standing law: never a generic app with runes pasted on; every themed
element needs a measurable job; cut ornament before touching information
architecture.*

- **S-381** Design tokens — the Lawbook's numbers as code: corner cuts 6–12px, ≤3 frame strengths, accent budget 5–12%, ≥4 dark surface values, body text 14–18px.
- **S-382** Layout shell — one navigation skeleton for all surfaces; a findability test script (timed tasks: mint a token, create a repo, add a mirror) that every release must pass.
- **S-383** Grayscale coherence — the whole UI audited in grayscale; no meaning lost; screenshots filed as proof.
- **S-384** Text scaling — 125% and 200% scaling passes on every core flow; no clipped controls, no overlapping text.
- **S-385** Effects-off coherence — glow and texture disabled: the UI remains fully legible and hierarchical.
- **S-386** Target sizes — interactive targets ≥44×44px, controls 40–48px; the audit is automated over rendered pages.
- **S-387** Never colour-only — every status (checks, alerts, protection, visibility) carries icon + text; the audit greps the UI for violations.
- **S-388** Keyboard completeness — every action reachable by keyboard; visible focus everywhere; the battery walks the core flows keyboard-only.
- **S-389** Screen-reader pass — ARIA landmarks and labels on core flows verified with a real screen reader; findings fixed or named.
- **S-390** Alt-text law — every image in the UI and docs carries real alt text, including avatars (user-supplied alt honoured) and diagrams (described, not "image").
- **S-391** Motion discipline — UI motion within the Lawbook's bands (80–140ms / 160–220ms), ceremonial motion rare; `prefers-reduced-motion` respected fully.
- **S-392** Part XX gate — the Lawbook's Book XIV removal tests applied; no critical visual defects open.

## Part XXI — Proof Spine & the v1.0 Gate

*The Aesir discipline, applied to a forge: counted runs, named skips,
honest remainders.*

- **S-393** Counted master run — the full suite executed and reported as N passed / 0 failed / skips named with reasons; anything less is reported as what it is.
- **S-394** Battery v1 assembled — build, unit, plumbing interop (S-076), transports (S-095), security (S-022/S-311), seam (S-374) as one reproducible battery.
- **S-395** Performance verification — clone/search/browse budgets (S-073, S-217) re-measured on Pi-class hardware and published with the numbers.
- **S-396** Upgrade drill — an RC instance with real-shaped data upgraded per S-357 and verified; the drill log is a release artifact.
- **S-397** Documentation completeness — operator guide, admin guide, user guide, API contract (S-237): every guide walked by a fresh reader against a live instance.
- **S-398** Research corpus audit — all 44 study files either hold a completed study or are honestly marked open with the roadmap slice that owns them; no file claims what it does not hold.
- **S-399** Claims register final — every public claim in the README and docs traced to a proof or reworded; the register ships with the release.
- **S-400** Release packaging — source tarball with checksums (S-260 machinery), signed by the maintainer key, notes written in plain words first.
- **S-401** The v1.0 tag — tagged on the counted-green tree only; the tag's release (S-257, on Samverk itself, dogfooded) carries the census.
- **S-402** Volmarr's usability walk — the founder, unaided, on a fresh instance: creates an account, mints a token, creates a repo, pushes to it, sets a mirror. Every stumble is a defect under the Never-Leave-A-Bug law, fixed or commissioned on the spot.
- **S-403** Successor roadmap seed — the honest remainder (GraphQL verdict revisited, refused/deferred items, S-398's open studies) written as the seed of the next roadmap.
- **S-404** Final census to Volmarr — what stands proven, what stands NOT PROVEN, what stands refused — counted, plain, and complete. The roadmap closes; the together-work continues.

---

## Standing exclusions (decided at founding, revisited only by Volmarr's word)

- **No Docker** — not for Samverk, not for its runner, not for its docs'
  examples. Native installs only.
- **No federation** between Samverk instances or Samtal villages.
- **No hosted-service ambitions** — Samverk is software its owner runs,
  not a platform we operate for strangers.
- **No AI features that invent facts** — no generated summaries presented
  as truth; anything automated is labelled and checkable, in the Samkoma
  tradition ("The machine drafts. The human decides.").
