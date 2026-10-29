# Samverk — Clean-Room Research Corpus

This folder is the study shelf for **Samverk**, our own clean-room
version-control application. Each file below is **one study area**, and each
starts **empty** by Volmarr's founding instruction (2026-10-29): the scaffold
comes first; the words land only as the research is actually done.

**Clean-room discipline (standing law for every study here):** we study
*features, behaviour, and public documentation* — what GitHub does, what its
users can observe, what its public docs describe. We copy **no** GitHub code,
**no** assets, **no** proprietary interface design. Every finding is written
in our own words and shaped to Samverk's own nature: sovereign, secure,
user-friendly, standalone-first, Samtal-integrable.

When a study is complete, its file records: the feature's observable
behaviour, the design questions it raises for Samverk, the decision taken,
and the roadmap slices it feeds (see `docs/SAMVERK_MASSIVE_ROADMAP.md`).

## The shelf

### Transports and the git core

| File | Study question |
|---|---|
| `01-git-protocol-smart-http.md` | How does the git smart HTTP protocol (v0/v2) carry clone, fetch, and push — info/refs, upload-pack, receive-pack — and what must Samverk's HTTP endpoint do to serve an unmodified git client? |
| `02-git-protocol-ssh.md` | How is git-over-SSH authenticated and routed to the right repository, and how do we bind SSH keys to accounts without ever running a general shell? |
| `03-pack-negotiation-and-transfers.md` | How do pack negotiation, thin packs, deltas, and resumable/interrupted transfers behave, and where does the server spend its CPU and bandwidth? |
| `04-repository-object-model.md` | How are git objects (blobs, trees, commits, tags) stored and read in a bare repository, and which operations belong to git plumbing vs. our own code? |
| `05-refs-and-refspecs.md` | How do refs, symbolic refs, packed-refs, and refspecs work, and how do we make ref updates atomic and race-free under concurrent pushes? |
| `06-git-lfs.md` | How does Git LFS move large files outside the object store (pointer files, batch API, locks), and what does Samverk need to store and serve them safely? |

### Identity, auth, and permission

| File | Study question |
|---|---|
| `07-auth-passwords-and-sessions.md` | What does a modern password + session system owe its users — hashing, login throttling, session lifetime, revocation, remembered devices — and how does GitHub's observable behaviour compare? |
| `08-auth-ssh-keys.md` | How are SSH keys registered, fingerprinted, scoped, and revoked, and how do deploy keys differ from personal keys in rights and risk? |
| `09-auth-tokens.md` | What token shapes exist (personal access tokens, fine-grained tokens, installation/app tokens), how are scopes expressed, and how are tokens stored so a database leak is not a credential leak? |
| `10-auth-two-factor.md` | How do TOTP, recovery codes, and passkeys/WebAuthn enrolment and enforcement work, and what recovery path keeps a locked-out owner sovereign rather than stranded? |
| `11-permissions-model.md` | What is the smallest permission model that still expresses GitHub's observable behaviour — repo roles, write/admin boundaries, visibility (public/private/internal) — without inheriting its historical tangles? |
| `12-organizations-and-teams.md` | How do organizations, nested teams, team permissions, and outside collaborators compose, and what invariants keep an owner from locking themselves out? |

### Collaboration surfaces

| File | Study question |
|---|---|
| `13-issues.md` | What makes an issue system complete — labels, milestones, assignees, templates, reactions, timelines, cross-references — and which behaviours are load-bearing vs. garnish? |
| `14-pull-requests.md` | How does a pull request live — fork vs. branch, draft state, merge methods (merge/squash/rebase), conflict surfacing, auto-merge — and what state machine describes it honestly? |
| `15-code-review.md` | How do line comments, review threads, approvals, change requests, and suggested changes work, and how is review state kept consistent with new pushes? |
| `16-branches-and-protection-rules.md` | What do branch protection rules actually enforce — required reviews, required status checks, signed commits, push restrictions, linear history — and in what order are they checked on a push or merge? |
| `17-commits-history-blame.md` | How are commit lists, diffs, blame, and history graphs computed and paginated, and what caching keeps them fast on large histories? |

### Finding things, hearing things

| File | Study question |
|---|---|
| `18-code-search.md` | What does code search owe a user — indexing strategy, symbol awareness, regex, path filters — and what can a SQLite-and-git-native design honestly deliver? |
| `19-issue-search-and-queries.md` | What query language do issue/PR searches speak (qualifiers like `is:`, `label:`, `author:`), and how do saved searches and filters compose? |
| `20-notifications.md` | How do watch/star/subscribe, mention routing, notification reasons, and inbox triage work, and how do we keep notification volume honest and user-controlled? |
| `21-activity-feeds-and-events.md` | What event model underlies activity feeds, profile timelines, and repository history — and how are events stored so feeds, audit, and webhooks can share one truth? |

### Machines talking to machines

| File | Study question |
|---|---|
| `22-webhooks.md` | How are webhooks subscribed, signed, delivered, retried, and debugged — and what delivery guarantees can we honestly claim? |
| `23-rest-api-shape.md` | What is the observable shape of GitHub's REST API — resources, pagination, conditional requests, rate-limit headers, error shapes — and what is Samverk's own clean-room equivalent? |
| `24-graphql-api-shape.md` | What does a GraphQL API buy a forge (node ids, connections, field selection), what does it cost, and does Samverk need one at v1 or later? |
| `25-ci-actions-concepts.md` | What is the CI concept surface — workflows, jobs, runners, secrets, status checks reporting back to PRs — and where is the honest seam between Samverk and an external runner? |

### Shelves and side-rooms

| File | Study question |
|---|---|
| `26-packages-and-registry.md` | What does a package registry attached to a forge do — namespacing, versioning, access control per ecosystem — and which ecosystems (if any) belong in Samverk's scope? |
| `27-releases-and-artifacts.md` | How do releases bind tags, notes, and binary assets; how are assets stored, counted, and served; and what makes a release trustworthy (checksums, signatures)? |
| `28-wiki.md` | How is a wiki best modelled — a git repository of its own, pages, sidebars, access equal to the repo — and how does it stay simple? |
| `29-gists-and-snippets.md` | What is a gist — a mini-repository with files, revisions, comments, secret-vs-public visibility — and what is the smallest faithful version for Samverk? |
| `30-discussions.md` | How do discussions differ from issues — categories, answers, polls, conversion between the two — and does a village-scale forge want them in v1? |

### Security — the spine

| File | Study question |
|---|---|
| `31-threat-model.md` | Who attacks a self-hosted forge, what do they want (code, credentials, supply chain), and which threats shape Samverk's architecture before any feature is built? |
| `32-secret-scanning.md` | How does secret scanning detect committed credentials — patterns, entropy, partner formats — and what push-protection behaviour stops a secret before it lands? |
| `33-dependency-alerts.md` | How do dependency graphs and vulnerability alerts work when manifests are parsed from repos, and what data sources can a sovereign instance honestly use offline? |
| `34-code-scanning.md` | How do code-scanning results (SARIF) get ingested, deduplicated, and surfaced as alerts on PRs and in a security tab, without Samverk itself running the analysers? |
| `35-audit-log.md` | What belongs in an audit log — actor, action, target, IP, timestamp — how is it tamper-evident, and who may read it at instance, org, and repo level? |
| `36-signed-commits.md` | How do GPG/SSH commit signing and verification badges work, what is a vigil mode, and how do we display trust without overstating it? |

### Standing on its own feet

| File | Study question |
|---|---|
| `37-mirroring-and-backup.md` | How do pull/push mirrors behave — scheduling, credential handling, conflict and failure reporting — and how does Samverk discharge its duty of mirroring Volmarr's original repos from GitHub onto his own machines? |
| `38-standalone-deployment.md` | What does a native, no-Docker installation owe its operator — one binary/process model, systemd unit, config file, data directory, upgrades, and uninstall — on a Raspberry Pi and a laptop alike? |
| `39-samtal-integration-seam.md` | Where exactly is the seam between Samverk and Samtal — shared identity, embedded UI, village repositories, file-sharing — such that Samverk stays complete without Samtal and Samtal gains a code heart without swallowing it? |
| `40-admin-and-site-settings.md` | What must a site admin be able to do — user management, instance settings, maintenance mode, storage quotas, abuse handling — and what must be impossible even for an admin? |
| `41-accessibility-and-ui-principles.md` | How do Volmarr's Visual Design Lawbook laws land in a forge UI — grayscale coherence, 125–200% text scaling, effects-off coherence, targets ≥44px, no colour-only status — and what does Forgejo's failure teach about findability of everyday controls? |
| `42-data-model-and-storage.md` | What lives in SQLite, what lives in the filesystem object store, and what lives in git itself — and how do the three stay consistent under crash and concurrent load? |
| `43-markdown-and-rendering.md` | How is Markdown rendered safely — sanitisation, syntax highlighting, mentions, task lists, Mermaid-like diagrams, relative links in repos — without XSS ever riding along? |
| `44-migration-and-import.md` | How does a repository (and its issues/wiki) move from GitHub to Samverk — git-level clone is easy; what about metadata — and what does an honest importer promise and refuse to promise? |

### The founding laws, studied

| File | Study question |
|---|---|
| `45-cross-platform-architecture.md` | How does Samverk stay one program across Linux, Windows, and macOS, on x86-64 and ARM down to Raspberry Pi-class hardware — which platform seams (paths, processes, signals, file locking, service managers, filesystem case rules) must exist from the first slice so portability is architecture, not apology — and what is the honest OS × CPU proof matrix? |
| `46-visual-design-cyber-viking.md` | How does Volmarr's Cyber-Viking Visual Design Lawbook land on a code-hosting UI — tokens, composition, colour and light, typography and verified runes, under the summoned design warband (Hallveig, Rannveig, Solveig, Ljósbera, Rúnhildr, Tove) — so the forge is *really nice* with a measurable job for every themed element, and passes the Book XIV ship gate: coherent in grayscale, at 125–200% scaling, and with effects off? (Kin to file 41, which studies accessibility and findability; this file studies beauty and doctrine.) |
