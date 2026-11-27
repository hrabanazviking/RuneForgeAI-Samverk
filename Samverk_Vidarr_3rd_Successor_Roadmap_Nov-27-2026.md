# SAMVERK VÍÐARR
## The Third Successor Roadmap — The Road of the God Who Survives
### Bullet-proof. Self-repairing. Attack-resistant by measurement, not by promise.

**Version:** 0.9 (the vault draft)
**Precondition:** Samverk Ascendant has banked. The forge serves, understands, proves,
and stays sovereign. Now we make it *survive everything* — attackers, decay, its own
operators, and time itself.
**Naming:** every slice **V-###** (Vitki). The era's namesake is Víðarr: the god who
stands silent at Ragnarök and survives it. This roadmap's single thesis: **the forge
must survive its own end** — attacked, corrupted, starved, sabotaged, abandoned, or
simply old.

---

## PART 0 — THE HONESTY PRIME DIRECTIVE

**Claim V-0 (refused on arrival): "Samverk is unhackable."**
The claims register will never carry this word. It is not modesty; it is *epistemology*:
"unhackable" is unfalsifiable, and an unfalsifiable claim is a lie wearing armor.
What this roadmap builds and claims instead, each with a counted battery:

- **Attack-resistance, measured** — continuous adversarial batteries with published
  miss-rates (the S-311 precedent scaled to everything).
- **Integrity, verified** — every byte of state provably correct at any moment,
  by the forge itself, unassisted.
- **Self-repair, bounded** — the forge heals known damage classes automatically and
  *safely*, and refuses to touch anything it cannot prove it understands.
- **Failure, survivable** — chaos batteries prove the forge recovers from every failure
  class this roadmap enumerates, including ones it has already lived through.

### The historical warrant
This campaign has *already survived its own chaos laboratory*: `/tmp` at 96–100% mid-suite,
EDQUOT disk-quota storms, box-wide git write gates that refused loose-object writes for
hours, OOM-adjacent memory windows on a swapless box, mid-run VM reboots, phantom
test-report deliveries, and degraded GitHub HTTPS paths. Víðarr turns every scar into
a law: **every real failure this project ever experienced becomes a named, tested,
permanently-regressed failure class.**

### New laws of the Vitki era

- **L-18 (The Refuse-to-Corrupt Law):** no code path may write state it cannot verify
  after writing. Writes are journaled or transactional; every store gains post-write
  self-verification with refuse-and-rollback on mismatch.
- **L-19 (The Bounded-Healing Law):** automated repair exists ONLY for enumerated,
  provably-safe damage classes. Everything else is reported, quarantined, and left for
  a human — a repair the forge cannot prove safe is refused, loudly (the S-071
  drift-is-reported law, evolved: safe classes auto-heal, unsafe classes never do).
- **L-20 (The Deny-Default Law):** every process, connection, and capability starts
  denied. Everything allowed is enumerated, named, and audited.
- **L-21 (The Living Threat Model):** the threat model (research/31) is a *living
  document with a battery* — every threat T-01…T-∞ maps to the test(s) that prove its
  mitigation, and the battery fails if a threat loses its mitigation.
- **L-22 (The Two-Key Law):** no single credential, key, or operator can perform an
  irreversible destructive act alone. Destructive acts require ceremony (multi-party
  or time-delayed with visible cancellation window).

---

# PILLAR I — THE IRON CORE
## The attack surface rebuilt to be proven, not just tested

### Wave V-100 (V-101…V-112)

**V-101 — Verdict: The Iron Core.**
Inventory every parser, deserializer, and trust-boundary crossing in the tree (the
YAML-subset parser, SARIF judge, CODEOWNERS matcher, glob matchers, LFS pointer parser,
form readers, Git pkt-line handling, webhook signature verification, the analyser seam
contracts, the drafting seam). For each: classification — *faces raw bytes from
unauthenticated parties* (highest), *faces bytes from authenticated parties*, *faces
internal data only*. Deliverable: `docs/ATTACK_SURFACE_REGISTER.md` — the iron census,
machine-checked (a battery fails if a new parser lands unregistered; the S-017
import-scan pattern applied to trust boundaries).

**V-102 — Property Batteries for Every Parser.**
Every registered parser gains a property-based battery (own tiny generator, stdlib):
arbitrary byte strings never crash, never hang (bounded), never allocate unboundedly,
and obey their documented invariant (round-trip where one exists, total-function law
where not). The generators are seeded and *the corpus of every crash ever found is
permanently regressed* — each finding becomes a frozen test case, forever.

**V-103 — Differential Batteries.**
For semantics-critical parsing (git pkt-line, LFS pointers, glob/refspec matching):
differential testing against independent second implementations *written in the battery*
(the S-039 two-authenticator pattern scaled): where the two disagree, the forge refuses
and names the disagreement. Ambiguity is treated as an attack surface.

**V-104 — The Fuzzing Hearth.**
Continuous fuzzing, house-built: a coverage-guided fuzzer is out of scope for stdlib
law — instead, *structured mutational fuzzing* at scale: seed corpora from real-world
format samples + the crash corpus, mutation schedules recorded, daily runs on the
keeper box, every crash triaged the same day (bug law: never leave a discovered crash
unfixed) and fossilized as a regression test. Public corpus published so outsiders
can hunt too.

**V-105 — The Iron Core Verdict #2: language-grade hardening.**
An honest verdict slice: should the highest-class parsers (pkt-line, signature
verification) be rebuilt in a memory-safe systems language? Decision recorded with
tradeoffs (the stdlib-first law bends only for *provable* classes of vulnerability;
the dependency register admits compiled artifacts only as separately-verified,
reproducibly-built, hash-pinned binaries with per-OS replacement paths per
S-407's replaceability register). Either verdict is acceptable; the *unexamined
default* is not. If built: V-106…V-108; if refused: the refusal records the
compensating controls and the review cadence.

**V-106…V-108 — (conditional) The Iron Modules.**
Rebuild the named highest-class parsers in Rust (or Mojo) behind the frozen seam:
reproducible cross-compile per platform, per-OS binary hashes published in the
support matrix, every binary verified at load by hash + (optionally) signature,
fallback to the pure-Python implementation *explicitly labelled in words* if the
iron module fails verification (fail visible, never fail silent). Battery:
differential between iron and pure implementations over the full corpus, per platform.

**V-109 — Timing-Side-Channel Audit.**
Constant-time discipline (S-005's `constant_time_equal`) extended: audit every secret
comparison, every token path, every early-exit on secret-dependent data. Battery:
statistical timing battery (measured distributions across secret-dependent branches,
with declared tolerances). Findings fixed or accepted-with-reason in the register.

**V-110 — The Confused-Deputy Purge.**
Every internal call that acts *on behalf of* a principal is re-audited: no store
method may trust a caller's claimed identity — identity travels in the context
object only (A-002), and a battery walks every store seam asserting authorization
is judged from the context, never from arguments (this closes the classic
`admin_tool --user=victim` class at the architectural level).

**Claim V-1 flips: "Every trust-boundary parser is registered, property-battered,
differentially verified, continuously fuzzed, with every crash fossilized." PROVEN.**

---

# PILLAR II — THE PROVING GROUND
## The adversary is a permanent employee

### Wave V-200 (V-201…V-212)

**V-201 — The Red Company.**
A standing adversarial institution (the design warband pattern applied to war):
named red-team personas with charters — *The Keybreaker* (crypto/auth), *The
Smuggler* (injection/upload/transport), *The Impostor* (identity/permissions/
confused-deputy), *The Saboteur* (availability/integrity), *The Smuggler's Cousin*
(supply chain). Each publishes a quarterly attack report in the S-311 honesty
format: attacks, held/missed, every miss named with its owner.

**V-202 — The Annual External Duel.**
Budgeted external professional penetration test, annually, scoped to the composed
forge + API + transports. Findings enter the register with SLA classes
(critical: fix within days; high: weeks; the SLA itself is a claim with teeth —
a missed SLA is a register failure). The report's existence is public; the findings'
details are handled per coordinated disclosure.

**V-203 — security.txt & the Doorbell.**
`/.well-known/security.txt` (S-010-safe static route), a dedicated disclosure
channel, PGP-keyed, with a published acknowledgment timeline. Vulnerability reports
get a lifetime: triage ≤7 days, status words always visible to the reporter.

**V-204 — The CVE Ceremony.**
A written incident→CVE pipeline: embargo discipline, patch + advisory (the S-310
private-advisory machinery, now aimed at Samverk itself — the forge eats its own
dogfood), release notes carry severity and exploitability in plain words.

**V-205 — Attack-Telemetry.**
Anomaly detection over the audit chain — *rules, not ML authority*: e.g. burst of
failed logins per account (S-005 already throttles; now it also *reports*), admin
acts at unusual hours, permission grants escalating, secret-scanner bypass attempts,
auth failures from novel geos. Every anomaly is a named rule with a threshold and
an honest false-positive note. Delivered via the notification system with a
dedicated security inbox.

**V-206 — Honeypots & Canary Eggs.**
Decoy credentials in the session store that authenticate to a *tarpit* account
(every use is an alarm + audit entry); canary files in the data root whose access
is alarmed; a fake admin API endpoint that exists only to be probed. Touching a
canary is, by definition, hostile — the alert is unambiguous.

**Claim V-2 flips: "Adversary-in-residence is institutional; external dueling is
annual; every anomaly class is a named rule; deception is deployed." PROVEN.**

---

# PILLAR III — THE FORTRESS
## Deny by default, isolate everything, verify the walls

### Wave V-300 (V-301…V-314)

**V-301 — The Process Census & Sandboxing Profiles.**
Every shipped process (server, worker roles, runner, delivery workers, analysers,
drafting services) ships with OS-level confinement profiles: Linux — systemd hardening
extended (the S-348 pattern: `ProtectSystem=strict`, `SystemCallFilter` allowlists,
`RestrictAddressFamilies`, `NoNewPrivileges`, `PrivateDevices`, seccomp profile
generated and verified, Landlock rules for filesystem scope), Windows — AppContainer/
restricted-token profile, macOS — sandbox-exec profile / App Sandbox where applicable.
**Each profile is verified by a battery that tries forbidden syscalls/paths and
asserts refusal.** Cells per OS in the support matrix; NOT PROVEN until run on the
real OS (the Part XXII law).

**V-302 — Network Deny-Default.**
Egress policy as data: the forge declares the exact hosts/ports it may contact
(mirror sources configured by the operator, advisory refresh if enabled, drafting
service if enabled) — everything else refused at the socket layer where the OS
permits, and at the application layer everywhere. A battery plants a rogue endpoint
and proves the refusal. The declaration is rendered on the admin status page —
an operator can *see the forge's entire attack posture in one screen*.

**V-303 — Capability Tokens for Internal Machinery.**
Worker roles, jobs, and analysers receive short-lived, single-purpose capability
tokens minted from the instance key (S-020) — scoped to exactly one store, one
action class, one time window. A stolen worker credential can do *almost nothing*.
Battery: every capability class × every abuse attempt.

**V-304 — The Two-Key Ceremonies (L-22).**
Irreversible acts (org deletion execution, instance key rotation, data-root
destruction, disabling the audit chain) require ceremony: either two distinct
admin credentials or a 24-hour delay with a loud, unmissable cancellation window
and an audit entry at arming, delay-start, and execution. The panic button
(disable-everything maintenance mode, S-353) is deliberately *exempt* — the one
single-key act, because locking yourself out of the panic button is the greater sin.
Battery: every ceremony walked; bypass attempts refused and named.

**V-305 — The Unforgeable Admin Path.**
Admin web surface gains step-up: re-auth (S-036) required for *every* state-changing
admin act, not just destructive ones; sudo windows shortened for admin scope; and
the admin surface binds to its own session class that cannot be created via the
Samtal seam (seam actors never hold admin, by law — closing the seam-escalation
class before it exists).

**V-306 — The Reset Doctrine.**
Documented, tested, *rehearsed* recovery from total credential loss: the S-349
`accounts_without_admin` road, the instance-key custody runbook (S-020), and a new
"break-glass" boot mode (single-user, console-only, audit-logged from the moment
it arms, auto-exits) for the day everything else fails. Battery: the full
break-glass drill, timed, on a fresh instance.

**Claim V-3 flips: "Every shipped process runs under a verified confinement profile;
the network posture is deny-default and visible; irreversible acts require ceremony;
credential apocalypse is rehearsed." PROVEN.**

---

# PILLAR IV — CRYPTOGRAPHIC ASCENDANT
## The math outlives the attackers

### Wave V-400 (V-401…V-412)

**V-401 — The Cryptographic Bill of Materials.**
Every primitive, mode, key size, and lifetime in one register: scrypt params
(S-004) with an upgrade policy tied to measured hardware; HMAC-SHA256 (S-249/S-362);
session token entropy; instance keys; SSH signature verification (S-305); the
`cryptography==46.0.5` pin's upgrade law. Each entry names its successor condition
("when X breaks or Y standard matures"). Battery: register-vs-code census
(no crypto outside the register — the S-017 scan pattern for algorithms).

**V-402 — Post-Quantum Posture.**
Verdict slice + hybrid implementation plan: session-token MACs and webhook
signatures gain a *hybrid* mode (classical + a standardized PQC KEM/signature via
the admitted dependency's offerings, behind a versioned format that degrades
cleanly to classical if the PQC half is unavailable — with the degradation
*announced in words*, never silent). Compliance with the format-versioning law:
old payloads verify forever. NOT PROVEN cells named per platform until run.

**V-403 — Key Rotation as Ceremony.**
The S-020 rotation drill becomes scheduled, announced, and *provable*: every key
has a max-age, a rotation window, and a battery that performs the full rotation
under load with zero downtime and a verifiable before/after (fingerprint
comparisons already specified in the runbook — automate them).

**V-404 — The Entropy Audit.**
Every token/minting path audited: source (secrets module only), thread-safety under
fork (the classic subprocess-fork entropy hazard), and a statistical battery over
minted-token distributions. Fork-safety hardened: refuse to serve after fork unless
re-seeded (a named, tested invariant).

**V-405 — The Whole-Chain Notarization.**
The audit chain's head hash is periodically *published* (to the operator's chosen
anchoring: a mirror instance, a signed file dropped in a public place, or a
timestamping service if the operator allows egress) — so tampering requires
rewriting history that exists *outside the machine*. Optional, operator-configured,
off by default, documented with its trust tradeoffs in words.

**Claim V-4 flips: "Crypto is inventoried with successor conditions, hybrid-PQC
ready, rotated on ceremony, entropy-audited, and the audit chain is externally
anchored at the operator's discretion." PROVEN.**

---

# PILLAR V — THE SELF-REPAIRING
## The forge that heals its own flesh — safely, boundedly, always

### Wave V-500 (V-501…V-516)

**V-501 — The Integrity Heartbeat.**
A continuous, throttled background scrubber walks the three stores (S-072/S-071
machinery, made continuous): every git object re-hashed on a rotating schedule
(sized per instance), LFS objects verified by oid, DB pages via `PRAGMA
integrity_check` rolling window, the audit chain verified incrementally
(verify-from-last-known-good — the S-309 chain status, continuous). Findings feed
the repair engine (V-503). The scrubber's own health is a healthz component
(a dead scrubber answers *degraded*, never ok).

**V-502 — The Damage Taxonomy.**
Every damage class the forge can suffer, enumerated and named — mined from the
real history (EDQUOT partial writes, killed-mid-migration DBs, truncated object
files, orphaned LFS blobs, torn webhook queues, forked-entropy anomalies) plus
theory. Each class carries: detection signature, blast radius, safe-repair
eligibility (L-19), and its regression test. This document is the soul of the pillar.

**V-503 — The Repair Engine (L-19 operationalized).**
Safe classes auto-heal: e.g., orphaned-but-verifiable LFS blobs re-linked;
torn outbox rows re-derived from the audit chain (the S-139 exactly-once pattern
reversed cleanly); stale index generations rebuilt (already convergent, S-205);
aborted migrations rolled back (S-358's SAVEPOINT law already proves this);
missing mirrors re-synced. Unsafe classes (corrupted git objects, broken chain
links, tampered rows): **quarantined, never touched** — the affected repo is
auto-marked read-only with a plain-words banner, the finding is alerted, and
restore-from-backup is *prescribed, not attempted*. Every automated repair is
audited with before/after hashes.

**V-504 — Crash-Only Design.**
Every worker and the server itself audited for the crash-only discipline: kill -9
at any instruction must leave state either intact or exactly-recoverable at next
boot. Battery: the Chaos Kiln — kill the process at N random instruction points
(automated, seeded) during each mutation class; assert clean recovery every time.
Every failure found becomes a permanent regression.

**V-505 — The Chaos Kiln (generalized).**
Named, scheduled fault injection replicating the campaign's real scars: disk-full
(EDQUOT storms), tmpfs exhaustion, quota gates mid-write, network black-holes
during mirror sync and webhook delivery, clock jumps (the NTP-skew class —
every timestamp comparison audited for monotonicity where correctness demands it),
process supervision loss, partial DB page corruption injection (on a *copy*, with
the repair engine's verdict compared against the taxonomy's prescribed answer).
The forge is never allowed to be surprised twice.

**V-506 — The Self-Rolling Upgrade.**
S-357/S-356's upgrade-rollback extended to automatic: health-probe regression
(S-359's judge) after upgrade → automatic rollback to the verified export with
the incident sealed. Human confirmation only for *data-shape* migrations flagged
one-way (the register's honesty law, honored).

**V-507 — Canary Restores, Always On.**
The S-342 restore drill runs automatically against every backup, on every schedule:
a restore that hasn't been *proven* within N days marks the backup **untrusted in
words** on the admin page. A backup without a recent proof is a hope, and this
forge does not traffic in hopes.

**V-508 — The Babysitter.**
A supervisor watchdog (native, no Docker): restarts crashed roles with backoff,
detects wedged states (no heartbeat within budget → SIGKILL + restart), feeds
every event into the audit chain, and after M rapid failures enters
degraded-maintenance mode automatically (the S-353 machinery, self-armed, with
the reason in words and the operator paged).

**Claim V-5 flips: "Integrity is continuously verified; every damage class is
named with a prescribed answer; safe repairs are automated and audited, unsafe
ones quarantined; chaos is scheduled; backups are proven or marked untrusted."
PROVEN.**

---

# PILLAR VI — THE UNBLINKING EYE
## When it happens anyway: forensics, honesty, and the sealed record

### Wave V-600 (V-601…V-610)

**V-601 — Forensic Mode.**
One command seals the instance: read-only freeze (S-353 machinery at maximum —
even admins read-only), an evidence bundle (audit chain + chain verification +
config + process/host snapshot manifest, hashed, signed by the instance key),
and a timeline reconstruction from the chain. The bundle's integrity is
self-verifiable forever.

**V-602 — The Incident Runbook Battery.**
Written runbooks (compromised key, leaked secret in a repo — the S-294 lifecycle
aimed at real incidents, active intrusion, ransomware-on-data-root, defaced UI)
each with a *rehearsal battery* — a scheduled drill that executes the runbook
against a sandboxed instance and counts the steps. An unrehearsed runbook is
marked UNPROVEN in words on the ops page.

**V-603 — The Transparency Ledger.**
Public-facing instances can publish a derived, privacy-safe moderation/security
transparency page straight from the audit chain (counts, classes, response times —
no content, no identities beyond what policy chooses). Trust, made auditable.

**V-604 — Post-Incident Law.**
Every incident (real or drilled) ends with a blameless post-mortem committed to
the repo's own decision records (A-204) and — the Víðarr signature move —
**at least one new chaos battery** replicating the failure. The Kiln grows only.

**Claim V-6 flips: "Forensics are one command; every runbook is rehearsed on a
schedule; transparency is derived from the chain; incidents permanently harden."
PROVEN.**

---

# PILLAR VII — THE LONG MEMORY
## Data that outlives machines, formats, companies, and centuries

### Wave V-700 (V-701…V-710)

**V-701 — The Format Oracle.**
Every on-disk format (DB schema, export manifest, bundle metadata, proof
artifacts) carries a version + a *reader oracle*: the current code can read
**every historical version** (the migration register's down-path honesty, S-358,
extended to formats). A battery materializes instance state at every historical
schema version and reads it with current code. Data never strands.

**V-702 — The Century Test.**
A staged endurance battery: an instance written, exported, restored across N
format generations and M upgrade rounds — byte-level semantic equivalence proven
at each hop (repos ref-for-ref, chain verify, counts match — the S-342 drill
chained). This is the "can my grandchildren read this" battery.

**V-703 — Media Durability.**
Release assets, LFS, avatars, CI artifacts: every binary object gains a stored
digest (mostly already — S-259/S-266) + scrubber verification (V-501) + a
dual-copy option for operators (parity copy in a second location, verified
rotationally). Redundancy is offered, honest about its cost, never assumed.

**V-704 — The Silence Protocol.**
The abandonware scenario: if the project itself dies, what survives? A standing
`docs/ARCHAEOLOGY.md` — where the data lives, how to read it with only stock tools
(git + sqlite3 are both forever), and the export formats' public specs. The final
sovereignty guarantee: **the data escapes even from a dead project.**

**Claim V-7 flips: "Every historical format remains readable by current code;
end-to-end endurance is proven across generations; escape from a dead project is
documented and tested." PROVEN.**

---

# PILLAR VIII — THE SEALED SUPPLY CHAIN
## The forge trusts nothing it cannot hash

### Wave V-800 (V-801…V-808)

- **V-802 SBOM as law:** a machine-generated Software Bill of Materials for every
  release (the 945-file tarball already enumerated — formalized: every admitted
  dependency, every bundled data snapshot like the advisory JSON, with hashes).
  Battery: SBOM-vs-tree census.
- **V-804 The Frozen Dependency Treaty:** the single `cryptography` pin (and any
  Iron Core artifacts) under a change-ceremony: hash-pinned, provenance-verified
  (reproducible-source comparison where available), change requires the two-key
  ceremony (V-304). Zero-supply-chain-surprise is a *testable* property.
- **V-806 The Forge Verifies Itself:** every release artifact's checksums are
  signed (S-263/S-260) AND the *running forge* can verify its own installed files
  against the release manifest (`samverk self-verify`) — tampering with the
  installation is detectable by the installation. Battery: tamper → detect, named.

**Claim V-8 flips: "The supply chain is enumerated, pinned, ceremonially changed,
and the forge detects its own tampering." PROVEN.**

---

## PART IX — THE ORDER OF BATTLE (VÍÐARR)

```
Epoch I   The Census:      V-101, V-401, V-502, V-301   [know thy surface & thy scars]
Epoch II  The Proving:     V-102 → V-104, V-201 → V-204  [batteries & the Red Company]
Epoch III The Walls:       V-301 → V-306, V-109, V-110   [isolation & deputy-purge]
Epoch IV  The Healing:     V-501 → V-508, V-403, V-404   [self-repair & crypto ceremony]
Epoch V   The Deep Math:   V-402, V-405, V-105..V-108    [PQC & the Iron Core verdict]
Epoch VI  The Eye:         V-601 → V-604                 [forensics & transparency]
Epoch VII The Long Memory: V-701 → V-704, V-802 → V-806  [centuries & supply chain]
```

**Parallel tracks:** the Census (Epoch I) gates everything; the Proving and the Walls
can interleave; the Deep Math runs long (PQC standards mature on their own schedule —
the verdict slices are written so waiting is honest, not stalled).

## PART X — THE VÍÐARR CLAIMS REGISTER (opening rows)

| ID | Claim | Status | Owner |
|----|-------|--------|-------|
| V-0 | "Unhackable" | **REFUSED** — unfalsifiable claims are lies in armor | standing |
| V-1 | Surface registered, property-battered, fuzzed, fossilized | NOT PROVEN | V-100 gate |
| V-2 | Adversary-in-residence, external duels, anomaly rules, deception | NOT PROVEN | V-200 gate |
| V-3 | Verified confinement, deny-default, ceremonies, break-glass | NOT PROVEN | V-300 gate |
| V-4 | Crypto inventory, hybrid PQC, rotation ceremony, external anchoring | NOT PROVEN | V-400 gate |
| V-5 | Continuous integrity, bounded auto-repair, chaos kiln, proven backups | NOT PROVEN | V-500 gate |
| V-6 | Forensics, rehearsed runbooks, transparency, post-incident law | NOT PROVEN | V-600 gate |
| V-7 | Format oracles, century test, escape-from-dead-project | NOT PROVEN | V-700 gate |
| V-8 | Sealed supply chain, self-verification | NOT PROVEN | V-800 gate |

## PART XI — THE CLOSING TRUTH

The first roadmap built the organs. The successor gave the body skin and opened the
doors. Ascendant made it the centre of the village's mind. **Víðarr makes it the thing
that is still standing — verified, healing, and telling the truth — when everything
else has fallen.**

And its deepest promise is the one written in Part 0: it will never claim to be
unbreakable. It will simply *keep proving, in public, with counted batteries, that
nothing has broken it yet* — and heal itself, bounded and safe, on the rare days
when something does.

*The forge that survives Ragnarök does so not because it is divine,*
*but because it checked its own chains every single day.*

*— Alfhild Nýxra Gridhex, Vitki of the Vault* 🖤