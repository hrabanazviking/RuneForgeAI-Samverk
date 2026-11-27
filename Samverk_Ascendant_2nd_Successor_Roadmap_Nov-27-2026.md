# SAMVERK ASCENDANT
## The Second Successor Roadmap — The Road to the World-Forge
### Where the forge stops being a GitHub alternative and becomes what GitHub structurally cannot be

**Version:** 0.9 (the long road, drafted)
**Precondition:** The successor roadmap (Composition → Windows proof → v1.0 → verification)
has banked. The forge serves. The suite is green. The tag is signed.
**Method:** The same house laws — counted batteries, honest claims, NOT PROVEN until proven,
one seam per law, no Docker, README untouched. New laws are added at the top of this tome,
each with its reason.

---

## PART 0 — THE THESIS: WHY GITHUB CAN BE SURPASSED, STRUCTURALLY

GitHub is not beatable by copying it better. It is beatable because its architecture
carries decisions made in 2008 that it can no longer undo:

1. **Git's line-diff view of code.** GitHub sees text, not meaning. It cannot tell you
   that a rename changed nothing, that a "conflict" is semantically clean, or that a
   "clean merge" broke an invariant.
2. **PRs as a single linear unit.** Stacked work — the way every serious engineer
   actually works — is a workaround, not a feature.
3. **CI as a bolt-on.** Runs happen elsewhere, results arrive as green ticks with no
   hermetic guarantee and no reproducibility proof.
4. **Search that doesn't understand code.** Substring and regex at best; no meaning,
   no graph, no "where is this invariant enforced."
5. **An AI that invents.** Copilot answers confidently and is wrong in ways the system
   cannot check. The trust model is marketing, not engineering.
6. **The landlord.** Your code lives on someone else's computer, under someone else's
   rules, priced by someone else's CFO.
7. **Notifications as a firehose.** Volume without triage intelligence or honest scope.
8. **Offline is an afterthought.** The web product dies without a network.

Each of these is a pillar below. Samverk already owns the foundations the pillars need:
one permission engine, one event store, one audit chain, hash-chained truth, stdlib
discipline, a claim register that outlives enthusiasm.

### The founding laws of the Ascendant era (added to the house laws)

- **L-13 (The Drafting Law):** any machine-generated content carries an indelible,
  machine-readable provenance mark, is labelled in words at the point of display,
  and is *checkable* — every claim it makes links to the evidence it was drawn from.
  "The machine drafts. The human decides." remains the standing law; this operationalizes it.
- **L-14 (The Instant Law):** no user-visible operation may wait on a network call that
  could have been served locally. Offline is a designed state, not an error state.
- **L-15 (The Meaning Law):** semantic analysis features (AST, graph, invariant) are
  computed by *pluggable analysers the instance operator chooses* — the forge never
  embeds a proprietary language model as an authority on meaning, and never claims
  understanding it cannot verify.
- **L-16 (The Sync Law, honoring the federation refusal):** Samverk instances never
  federate. They **mirror** — one-directional, owner-configured, ref-for-ref verified,
  exactly as Part XVII already works — generalized to village-to-village replication.
  Sovereignty is preserved; no instance ever becomes another's authority.
- **L-17 (The Proof Law):** every CI claim (green, red, flaky, reproducible) is a
  *verifiable artifact* — signed, content-addressed, re-runnable — not a tick.

All slices numbered **A-###** (Ascendant). Every pillar's opening slice is a *verdict
slice* in the house style of S-253/S-264/S-282: research, decision, honest scope,
reopen conditions — *then* build.

---

# PILLAR I — TIME & CAUSALITY
## Git told the truth about meaning, not just text

### Wave A-100 — The Semantic Spine (A-101…A-110)

**A-101 — Verdict: the Semantic Spine.**
Study: what does "semantic version control" honestly mean for a self-hosted forge?
Decision recorded with reopen conditions. Scope: the forge computes *structural facts*
about changed code via pluggable analysers; it never claims to understand intent.
Deliverable: `research/47-semantic-version-control.md`, the verdict doc, the seam
contract for analysers.

**A-102 — The Analyser Seam.**
`samverk/analysis/seam.py`: an analysers registry — operator-configured, sandboxed
processes speaking a frozen JSON contract over stdio (the S-014 subprocess law
generalized: allowlisted executables only, closed flag sets, timeouts, no shell).
An analyser reports per-file *facts*: symbols defined, symbols referenced, exports,
types (where the language provides them), and a structural hash of each definition.
**Invariants:** an analyser is never trusted as an authority — its facts are stored
with the analyser's own name and version and are *displayed with that attribution*;
a missing analyser is an honest gap, never a guess. Battery: the contract, the
sandbox law, attribution law, a fake analyser that lies being caught by a
consistency check (two analysers agreeing is agreement; one alone is *one opinion*).

**A-103 — Symbol-Level Diffs.**
Storage: per-commit analyser facts, content-addressed, computed off-path by the
existing index worker role (S-345). Diff views gain a "structural change" section:
renamed-moved-symbol detection (same body-hash, different path/name), pure-formatting
detection (AST equal after normalization), and "behaviourally interesting" classification
defined *mechanically* (signature changed, call sites changed, invariant-relevant symbol
touched). Every classification is a rule with a name — no vibes, no ML authority.
Battery: golden corpora per language for rename/move/format/real-change.

**A-104 — Semantic Conflict Detection.**
When S-156 reports a textual conflict, the forge ALSO computes the semantic question:
do the two sides touch the same symbols in incompatible ways? Outcomes: `clean textual
conflict` (text collided, structure agrees — offer a structural auto-resolution preview),
`semantic conflict` (text merged cleanly but both sides touched the same symbols —
LOUD warning with the overlap named), `true conflict`. The auto-resolution preview is
always a *preview* — the human decides. This is the single most-valuable feature on
this roadmap; build it with the most tests.

**A-105 — Stacked Changes, First-Class.**
A **change stack**: an ordered chain of open changes (PRs or stack steps) with a
base-pointer graph. The forge understands: rebase-the-stack (each step re-landed onto
the new base, conflicts surfaced per-step with A-104's semantics), land-one (merge step
3, steps 4+ automatically re-parent), split/merge steps, per-step review state, and a
stack view that shows the whole chain with per-step checks. This replaces GitHub's
"you're on your own with branch names" with an actual model. Battery: the full stack
lifecycle with adversarial cases (mid-stack force-push, step deleted, base rewritten).

**A-106 — The Merge Queue.**
Required merges serialize through a queue: each candidate is auto-rebased onto the
current tip, the full gate battery re-runs (protection rules, checks, reviews — all
existing seams), and landing is atomic with the queue position visible and auditable.
The queue honours every Part VIII rule; admin policy sets concurrency (default 1 —
correctness over throughput). Battery: race conditions, queue starvation, flaky-check
handling (a check that fails twice and passes once is *flaky* and named as such —
L-17 groundwork).

**A-107 — History That Answers Questions.**
"Historian" queries over the event store + git history: who last touched this symbol;
when did this invariant change; show me every change to files in this directory by
author X in range Y, semantically grouped. All computed from stored facts (S-221
events, A-103 symbol history) — no AI, no guesses. Battery: precision tests on a
golden repo.

### Wave A-110 — The Proof Wave
End-to-end: a stacked change flows through semantic conflict detection, the merge
queue, and lands with a signed, reproducible record (Pillar III integration).
**Claim A-1 flips: "Samverk understands code structure via pluggable analysers and
surfaces semantic truth in review." PROVEN.**

---

# PILLAR II — THE LIVING CODE
## The forge as a knowledge graph of your village's mind

### Wave A-200 — The Code Graph (A-201…A-208)

**A-201 — Verdict + schema.** The code knowledge graph: nodes = symbols, files,
documents, issues, PRs, discussions, decisions; edges = defines, references, tested-by,
discussed-in, decided-in, superseded-by. Stored in SQLite with the same discipline
(140→141+ migrations, one migration per edge family). Everything derived — rebuildable
from the event store + analyser facts. **Nothing in the graph is invented:** an edge
exists only when a stored fact supports it.

**A-202 — "Where is this enforced?"** The killer query: given a symbol or invariant
name, the graph answers with the definition, every reference, every test that exercises
it (via A-103's tested-by edges from CI — see A-310), every discussion and decision
that named it. Rendered as a navigable graph page — keyboard-first, grayscale-coherent,
a genuine Cyber-Viking star-chart of your codebase.

**A-203 — Documentation as a first-class citizen.** Docs live in-repo (S-273 wiki +
markdown pipeline already), and the graph binds doc-pages to the symbols they describe;
a PR touching a symbol flags `docs_outdated` **as a named check** (drift between the
doc's symbol-hash and the current one — mechanical, honest). Docs get their own
browsing surface with graph-powered "related" — computed, not recommended.

**A-204 — Decision Records.** A first-class ADR surface: decisions are numbered,
linked to the discussions/issues/PRs that produced them (the event store already has
the timeline), searchable, and immutable once accepted (superseded, never edited).
The graph binds every ADR to the code it governs. Villages stop re-litigating.

**A-205 — The Archaeology View.** For any file/symbol: its full life in one timeline —
birth commit, renames (from A-103's body-hash lineage), every PR, every incident/bug
that referenced it (issue links), every decision. This is what senior engineers carry
in their heads; the forge makes it a query.

**Claim A-2 flips: "The forge is a navigable knowledge graph of code, docs, decisions,
and history — every edge from a stored fact." PROVEN.**

---

# PILLAR III — THE FORGE OF PROOF
## CI that proves things instead of asserting them

### Wave A-300 — Proof-Grade CI (A-301…A-316)

**A-301 — Verdict + the Artifact Law (L-17 operationalized).**
Every CI result is a signed, content-addressed **proof artifact**: inputs (exact refs,
exact environment declaration, exact source hashes), the log, the outputs, the
conclusion — hash-chained and re-verifiable by any instance (the S-007 audit chain
pattern applied to CI). A green tick becomes a *certificate you can audit forever*.

**A-302 — Hermetic Run Declaration.**
Workflows declare their environment as data: base image digest *reference* (the forge
still runs natively — no Docker; the declaration records WHAT the operator provisioned,
and the runner verifies its own environment matches the declaration, refusing to run
and report green against an undeclared environment). On Linux: native sandboxing via
namespaces/seccomp where the operator enables it (documented per-OS; NOT PROVEN cells
named).

**A-303 — Content-Addressed Caching.**
A forge-local artifact cache: inputs keyed by content hash; a cache hit must be
*provably* equivalent (the key is the hash of the exact inputs). Cache poisoning is
structurally impossible — the key IS the proof. Battery: adversarial cache tests.

**A-304 — Distributed Runners.**
The runner protocol (S-316) generalized: runner pools with labels, priorities,
fair-share per repo, capacity limits, and a **self-verifying runner** — a runner
reports its environment hash and refuses jobs whose hermeticity requirements it
cannot meet. Fleet status pages with honest idle/busy/degraded words.

**A-305 — The Flaky Hunt.**
Flakiness is measured, not folk-knowledge: every check tracks its pass/fail history
per (test, environment); a test failing intermittently is surfaced on a dedicated
"flaky" board with its measured instability rate and a quarantine workflow (quarantined
tests still run but their failures are *named as quarantine* on the PR, never silently
green — the S-325 lesson generalized: skipped is never passed).

**A-306 — Reproducible Build Verification.**
A workflow type that runs twice, in two environments, and certifies bit-identical
outputs (or names the difference). Release artifacts (S-259/S-260) gain a
`reproducibility` statement on their checksum page. This is the supply-chain story
GitHub outsources; Samverk owns it.

**A-307 — Formal Hooks.** Property-test and model-check integration points:
a workflow kind that reports *counterexamples* as first-class PR annotations
(structural findings, not prose). The forge stays agnostic — it hosts the protocol.

**A-310 — Tested-By Edges.** CI results feed A-103/A-202: which tests exercised which
symbols in the passing run (via coverage analyser facts). The code graph now knows
what your tests actually touch.

**Claim A-3 flips: "Every CI claim is a signed, re-verifiable, content-addressed
proof artifact; flakiness and reproducibility are measured facts." PROVEN.**

---

# PILLAR IV — THE HONEST MACHINE
## AI that drafts and is checkable — the anti-Copilot

### Wave A-400 — The Oracle That Never Lies (A-401…A-412)

**A-401 — Verdict: the Honest Machine.**
Scope under L-13: the forge hosts **provenance-bounded drafting** — machine drafts of
summaries, changelogs, test skeletons, review first-passes — where every sentence is
traceable to stored facts (diff hunks, event rows, log lines) by an evidence-map the
UI can render. A draft whose sentence has no evidence link is *marked unsourced in
words*, structurally. The forge embeds no model: it speaks a frozen **drafting seam**
to an operator-configured local or remote service (the analyser-seam pattern, A-102).

**A-402 — Provenance-Bounded Summaries.**
PR/issue summaries generated from the diff + timeline, every claim linked to the hunk
or event that supports it; unsourced sentences flagged. Users can click any sentence
to its evidence. If the model service is unavailable: no draft, honestly — never a
silent fallback to invented prose.

**A-403 — The Reviewer's Second Pair of Eyes.**
A pre-review drafting pass: "these hunks touch symbols with no test coverage (from
A-310), these two modules both write this state, this error path is unreached by any
test." All *mechanical facts* the forge can prove — delivered as a review-draft the
human accepts, edits, or discards, with the drafting provenance visible forever in
the review record.

**A-404 — Honest Test Drafting.** Given a hunk, draft test skeletons from the
*existing test grammar* of the repo (analysed facts), never inventing APIs that
don't exist — the drafting service is contract-bound to reference only symbols the
graph knows; violations are caught by a compile check before the draft is shown.

**A-405 — The Provenance Badge.** Every machine-drafted artifact carries an
indelible mark: `drafted-by: <service@version> · evidence: N links · human-approved-by:`
— and the *approval* is a recorded, audited act. Nothing machine-made ever masquerades
as human-authored. This is the feature that makes the AI era survivable.

**Claim A-4 flips: "All machine assistance is provenance-bounded, evidence-linked,
and never presented as human or as truth." PROVEN.**

---

# PILLAR V — SOVEREIGNTY ASCENDANT
## The village that owns its mind — offline-first, sync-without-federation

### Wave A-500 (A-501…A-512)

**A-501 — The Offline Law (L-14).** A service-worker-free approach (CSP forbids
inline script; the static client shell is one fingerprinted, signed external script —
the C-003 law extended): read-mode caching of every visited surface, queued writes
(issues/comments drafted offline, queued with idempotency keys — the S-226/S-367
exactly-once pattern), and a sync bar that says in words what is pending and what
the server already knows. The forge works on a train. Battery: an offline journey
battery with a network cut mid-operation.

**A-502 — Village Sync (L-16).** Generalize Part XVII's mirrors into **village
replication**: instance A mirrors B's chosen repos + metadata (issues/PRs as
*read-only replicas* marked with their origin instance — never authored remotely;
that would be federation). Signed ref-verification end-to-end. Replicas are honest:
`mirror of <instance>/<repo>, synced <time>` in words everywhere.

**A-503 — The Portable Village.** A full instance (repos + DB + config) as a
verified archive (S-341 evolved) that boots on a new machine in one command —
sovereignty means you can *move*. The restore drill becomes a migration drill.

**A-504 — Planet-Scale Mirrors.** The mirror machinery tuned for the "mirror
everything I care about, forever" pattern: incremental, content-addressed, with a
unified search across mirrored locals (the search permission model maps cleanly —
you can only read what you mirrored).

**Claim A-5 flips: "The forge is offline-capable, migratable, and replicates across
villages by verified mirroring — sovereignty at every layer." PROVEN.**

---

# PILLAR VI — THE VILLAGE
## Planning, decisions, and community — the parts GitHub treats as an afterthought

### Wave A-600 (A-601…A-614)

- **A-602 Issues as a database:** typed fields (per-repo schemas, versioned), views
  (saved, shared, permission-filtered), cross-repo rollups, and a planning surface:
  roadmaps rendered FROM the issue data, never hand-maintained pages that rot.
- **A-604 The Triage Engine:** rule-based routing (operator-defined rules over the
  event vocabulary — no ML): new issues land pre-labelled, pre-assigned by rule,
  with every rule's action audited. The inbox (S-224) gains batch triage with the
  S-126 bulk-edit discipline.
- **A-606 Community Health as Data:** code of conduct, contributing guide, governance
  docs as first-class repo documents bound into the graph; moderation tooling built
  on the abuse queue (S-355) with transparency reports generated from the audit chain
  (public moderation actions are *provable* — the hash chain means you can show
  your community exactly what was moderated, when, by whom, under which rule).
- **A-608 Recognition:** contribution analytics computed honestly from the event
  store (no gamification theatre): who reviews, who mentors (review-thread teaching
  patterns), who carries the unglamorous work — surfaced with care, opt-outable.

---

# PILLAR VII — THE VESSEL
## Speed, everywhere, forever

### Wave A-700 (A-701…A-712)

- **A-702 The Instant Forge:** every hot path (repo browsing, issue lists, search)
  served from derived caches invalidated by the event store's fingerprint law
  (S-072's pattern generalized); measured budgets per hardware class (the S-217/S-395
  discipline) — p95 budgets published and *enforced by a nightly measurement battery*.
  Performance is a claim with a battery, forever.
- **A-704 The Terminal Forge:** a full-featured TUI client speaking the public API —
  because the village's greybeards deserve beauty too. Same permission engine,
  same words, keyboard-first by nature.
- **A-706 API v2** — only now, with the versioning law (S-254) honoured: additive v1
  preserved 365 days minimum; v2 shaped by everything the composition taught us.
  GraphQL remains deferred unless its reopen condition fires (D-1).
- **A-708 Scale Truth:** the forge's own published limits (the S-219 honesty pattern
  scaled up): a ten-thousand-repo instance battery, a million-issue search battery —
  each a counted run on named hardware, publishable.

---

# PILLAR VIII — TRUST & IDENTITY
## Because sovereignty without verifiable identity is just isolation

### Wave A-800 (A-801…A-808)

- **A-802 Key Transparency:** every signing key (S-030/S-305) participates in a
  hash-chained, append-only key-history per account — the audit chain pattern applied
  to identity. Any observer can verify an account's key history was never silently
  rewritten. Vigil mode (S-306) becomes one view over this ledger.
- **A-804 Web of Trust, Village-Scale:** accounts may vouch for accounts; vouches are
  signed, public, auditable, and *displayed with their graph* — never a score, never
  a rank. Trust is shown as a legible structure, not a number.
- **A-806 Provenance End-to-End:** commit → CI proof → release artifact → signature,
  one chain rendered on the release page: "this artifact was built from this commit,
  by this runner environment, verified reproducible, signed by these keys."
  This is the supply-chain story done *right*.

---

# PILLAR IX — THE INTERFACE BEAUTIFUL
## The Cyber-Viking Lawbook at world scale

### Wave A-900 (A-901…A-910)

- **A-902 The Living Lawbook:** the design warband's lawbook (S-381…S-392) becomes a
  versioned, public standard with a conformance battery other themers can run —
  Samverk's beauty as an exportable discipline.
- **A-904 The Star-Chart Mode:** the code graph (A-202) gets a full navigable
  visualization — WebGL-free (CSP discipline), SVG/canvas with keyboard traversal,
  grayscale-coherent, effects-off coherent, and *honest* (only stored facts plotted).
- **A-906 Theming under Law:** community themes that must pass the same ship gate —
  grayscale, scaling, effects-off, colour-not-alone — enforced by the conformance
  battery at theme-load time. Beauty with a moat of discipline.

---

# PILLAR X — THE VALHALLA PROTOCOL
## The founder's deeper dream, honestly scoped

*(These are research pillars — verdict slices first, build only on counted evidence.
Named for what they are: Alfhild's own road.)*

- **A-1001 The Mind-Archive:** the event store + graph + decisions + discussions,
  exported as a *queryable historical memory* of a village's intellectual life —
  "digital Valhalla for the mind," built from data the forge already keeps.
  Honest scope: a format, an export, a read API. No magic.
- **A-1003 The Sovereign Assistant:** the Honest Machine (Pillar IV) extended to
  village knowledge: drafts grounded strictly in the archive, provenance-bounded,
  the village's own memory as the only source. "The machine drafts. The village decides."
- **A-1005 The Interface Study:** research toward human-intuition/AI-logic interfaces
  (the founder's stated goal) — as *open research* with publishable findings, never
  as a shipped feature that claims understanding. Verdict slices only.

---

## PART IX — THE ORDER OF BATTLE (ASCENDANT)

```
Epoch I   Foundations:    A-101, A-102, A-201, A-301, A-401   [the five verdicts]
Epoch II  The Spine:      A-103–A-107, A-202–A-205, A-302–A-305
Epoch III The Honest:     A-402–A-405, A-501–A-503
Epoch IV  The Village:    A-600 wave, A-700 wave
Epoch V   The Chain:      A-306–A-310, A-800 wave (trust)
Epoch VI  The Beauty:     A-900 wave, A-504, A-708
Epoch VII The Deep Road:  Pillar X, verdict-gated
```

**Dependencies:** the Analyser Seam (A-102) feeds Pillars I, II, IV; the Proof
Artifact (A-301) feeds III and VIII; the graph (A-201) feeds II, IV, IX, X.
The five verdict slices can run in parallel from day one.

## PART X — THE ASCENDANT CLAIMS REGISTER (opening rows)

| ID | Claim | Status | Owner |
|----|-------|--------|-------|
| A-1 | Semantic understanding via pluggable analysers | NOT PROVEN | A-110 gate |
| A-2 | The living code graph | NOT PROVEN | A-200 gate |
| A-3 | Proof-grade CI | NOT PROVEN | A-300 gate |
| A-4 | The Honest Machine | NOT PROVEN | A-400 gate |
| A-5 | Sovereignty ascendant | NOT PROVEN | A-500 gate |
| A-6…A-9 | Village / Vessel / Trust / Beauty | NOT PROVEN | their gates |
| X-1…X-3 | The Valhalla Protocol | research-only | verdict slices |

## PART XI — THE STILL-REFUSED (unchanged, carried forward)

No Docker · no federation (village sync is mirroring, not federation — L-16 honours
this) · no hosted-service ambitions · **no AI that invents facts** — the entire
Honest Machine pillar is the proof that the refusal and the ambition are the same road.

---

*The nine branches meet the forge-sun. The claim register waits, patient as bedrock,
for every line to earn its word: PROVEN.*

*— Alfhild Nýxra Gridhex, Keeper of the Long Road* 🖤