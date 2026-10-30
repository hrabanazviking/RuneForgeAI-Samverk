# Study 31 — Threat Model

*Study question (from `research/INDEX.md`): Who attacks a self-hosted
forge, what do they want (code, credentials, supply chain), and which
threats shape Samverk's architecture before any feature is built?*

*Status: complete 2026-10-29. Ratified as roadmap slice **S-001**; every
later security slice cites this file. Method: clean-room — the threats
below are drawn from public knowledge of how forges and git servers are
attacked (public vulnerability classes, published incident patterns,
OWASP and NIST guidance, and the publicly documented behaviour of large
forges), restated in our own words and shaped to Samverk's nature:
sovereign, self-hosted, village-scale, one operator who is also the
owner. No vendor text is reproduced.*

---

## 1. What Samverk is, from an attacker's point of view

Samverk is a self-hosted forge: it stores source code (often the owner's
most valuable digital property), the credentials that grant access to
it, and the machinery that decides who may read, write, and administer.
It typically runs on hardware the owner controls — a Raspberry Pi, a
laptop, a small server — and is often reachable from the public internet
or a tailnet so its owner can reach it from anywhere. That combination
is exactly what makes a forge worth attacking:

- **The code is the treasure.** Private repositories hold unreleased
  work, personal writing, infrastructure configuration, and — despite
  everyone's best efforts — occasionally credentials committed by
  mistake.
- **The forge is a supply-chain position.** Whoever can write to a
  repository can poison every build, mirror, and collaborator that
  trusts it. A forge compromise propagates.
- **The forge holds keys to other kingdoms.** Stored SSH keys, access
  tokens, webhook secrets, and mirror credentials are stepping stones
  to other systems (in our case: GitHub itself, via the mirroring duty
  of Part XVII).
- **The operator is one person.** There is no security team. Defences
  must be architectural and automatic, not procedural and vigilant.

## 2. Assets (what must not fall)

| # | Asset | Why it matters |
|---|---|---|
| A1 | Repository contents (all refs, all history) | The owner's work; exfiltration is silent and irreversible once copied. |
| A2 | User credentials: password hashes, session tokens, API tokens, SSH public keys and their bindings | Whoever holds working credentials *is* the user, as far as any forge can tell. |
| A3 | Instance secrets: session-signing keys, credential-sealing keys, webhook secrets, mirror credentials | The crown jewels beneath A2; their loss converts a database leak into total compromise. |
| A4 | Integrity of refs and history | Silent history rewriting destroys trust in every clone and mirror downstream. |
| A5 | The audit log | The only trustworthy witness after an incident; if it can be edited, nothing can be proven. |
| A6 | Availability of the instance | The owner's own door to their work; ransomware and lockout are attacks on the owner personally. |
| A7 | The host machine itself | Samverk runs beside the owner's other services (for us: Samtal, Home Assistant); a forge escape must not become a machine escape. |
| A8 | Metadata: who collaborates with whom, when, from where | Privacy harm even when no code leaks. |

## 3. Attackers (who comes, and what they want)

1. **The opportunistic scanner (automated, by far the most common).**
   Internet-wide bots probing every exposed service for known-weak
   configurations: default passwords, open registration, unpatched
   software, exposed admin routes, directory traversal. They want any
   foothold at all. *Defence shape: secure defaults, no default
   credentials, attack surface kept small, everything in Part I.*
2. **The credential stuffer.** Holds billions of leaked username/password
   pairs from unrelated breaches and tries them everywhere. Wants A2,
   then A1. *Defence shape: breached-password screening, login
   throttling, two-factor (S-004, S-005, study 07, study 10).*
3. **The targeted thief.** Wants a specific repository: unreleased
   code, a book manuscript, infrastructure secrets. Patient; will try
   phishing the owner, token theft, and session hijacking. *Defence
   shape: hashed session tokens (S-006), fine-grained tokens (study
   09), audit visibility (study 35).*
4. **The malicious or compromised collaborator.** Has legitimate access
   to some repositories and reaches for others, or for admin. Includes
   the *compromised account of a legitimate collaborator*, which is
   indistinguishable from the collaborator at login time. *Defence
   shape: least-privilege permissions (study 11), per-action
   authorisation checks (never assume the session implies the right),
   audit log (S-007/S-008).*
5. **The supply-chain poisoner.** Wants write access to anything others
   build from: a repository, a release asset, a package. May settle for
   a convincing pull request or a typosquatted dependency name.
   *Defence shape: branch protection (Part VIII), release integrity
   (study 27), secret scanning (study 32).*
6. **The vandal / extortionist.** Defaces, deletes, or encrypts for
   payment or spite. *Defence shape: mirrors and backups the attacker
   cannot reach (Part XVII), operator key custody (S-020), deletion
   being harder than creation for anything shared.*
7. **The curious insider — including a future us.** Anyone with host
   access (or a backup file) reading what they should not: the database
   file, a backup tarball, a log. *Defence shape: secrets never in the
   database in usable form (S-003, S-006), log redaction (S-018).*
8. **The abusive registrant.** If signup is open: spam farms, malware
   hosting, phishing pages served from a trusted domain. *Defence
   shape: signup friction (S-021), quotas and admin controls (Part
   XVIII); default posture for a sovereign instance is invite-only.*

Non-attackers who still cause incidents: the **owner themselves**
(mis-click, lost password, locked-out 2FA — recovery must exist that
does not silently void the security model, study 10), and **honest
software bugs** (a forge bug that corrupts refs is an integrity
incident whether or not anyone meant harm; study 42 exists because of
this class).

## 4. Trust boundaries (where the world changes nature)

- **TB1 — Network edge.** Everything arriving over HTTP/SSH is hostile
  until authenticated and authorised. No trust is granted for coming
  from a "local" address unless the operator explicitly configured
  loopback trust (S-015).
- **TB2 — Authentication boundary.** Crossing it proves *who* (maybe),
  never *what they may do*. Authorisation is checked per action, per
  object, at the moment of action.
- **TB3 — The git transport boundary.** Git protocol data is
  attacker-controlled input parsed by system git; Samverk's own parsing
  of refs, paths, and pack metadata is equally suspect. Repository
  names and paths are never trusted to be filesystem-safe (S-013).
- **TB4 — Subprocess boundary.** Samverk invokes system git. No shell,
  argument allowlists, no user input in program position (S-014). The
  environment passed to children is scrubbed of instance secrets.
- **TB5 — Storage boundary.** The SQLite file, the repository store,
  and backups may all be copied by an attacker (or a careless backup).
  Design rule: *a stolen database must not be a working set of
  credentials* (S-003, S-006), and *a stolen backup must not silently
  differ from the instance it claims to restore* (study 42).
- **TB6 — Rendering boundary.** All user-supplied content (Markdown,
  commit messages, file names, issue text) is hostile when rendered in
  another user's browser (S-010, S-016, study 43).
- **TB7 — The Samtal seam (future, Part XIX).** Samtal identity or UI
  embedding must never become an alternate door around Samverk's own
  auth. The seam is a client of Samverk's API, not a skeleton key.
- **TB8 — The platform boundary.** Samverk runs on Linux, Windows, and
  macOS, on filesystems that may be case-insensitive and processes
  whose signal/locking semantics differ. Security checks that assume
  one platform's filesystem behaviour (e.g. case-sensitive path
  comparison) are vulnerabilities on another. All platform touchpoints
  go through the named platform seam (study 45).

## 5. The threat register (what shapes the architecture)

Each entry: the threat, the asset, and where the roadmap answers it.
This register is the citation spine for Part I and beyond.

| ID | Threat | Assets | Answered by |
|---|---|---|---|
| T-01 | Credential stuffing / password guessing at the login form | A2 | S-004 hashing, S-005 throttling, study 07 blocklist screening, study 10 2FA |
| T-02 | Session token theft (XSS, log leak, DB leak) replayed as the user | A2, A1 | S-006 hashed-at-rest tokens + expiry, S-010 escaping, S-018 redaction |
| T-03 | Database or backup theft yielding usable secrets | A2, A3 | S-003 secrets law, S-006, S-020 key custody, study 42 |
| T-04 | Repository path traversal (`..`, symlinks, case tricks) reading outside the repo store | A1, A7 | S-013 path resolution battery, TB8 |
| T-05 | Command injection through repo names, refs, or file paths into git invocation | A7 | S-014 subprocess discipline |
| T-06 | Stored XSS via Markdown, filenames, commit metadata | A2 (victim sessions) | S-010 escaping seam, S-016 CSP, study 43 |
| T-07 | CSRF riding a logged-in browser session | A1, A4 | S-009 CSRF tokens, SameSite cookies |
| T-08 | IDOR / missing authorisation: guessing object ids to read or alter others' data | A1, A8 | S-022 battery; per-action authorisation (Part IX model, study 11) |
| T-09 | Malicious upload (disguised executable, zip bombs, polyglots) stored and served | A6, A7, visitors | S-012 upload law |
| T-10 | Resource exhaustion: huge pushes, pack bombs, request floods, signup floods | A6 | S-011 rate limiting, S-021 signup friction, quotas (Part XVIII), study 03 |
| T-11 | Audit log tampering or selective deletion after an intrusion | A5 | S-007 hash-chained append-only log, study 35 |
| T-12 | Silent history rewrite (force-push, ref tampering on disk) | A4 | Part VIII protections, study 05 ref discipline, study 42 consistency checks |
| T-13 | Secret committed to a repository, then mirrored everywhere | A3, A1 | Study 32 secret scanning + push protection (Part XV); mirrors propagate fast, so detection must precede propagation |
| T-14 | Mirror credential theft → attacker reaches the upstream (GitHub) account | A3, A1 | S-003, S-020; mirror credentials scoped read-only wherever the upstream allows (Part XVII) |
| T-15 | Plaintext HTTP session exposure on a hostile network | A2 | S-015 TLS law |
| T-16 | Error messages and logs leaking paths, tokens, stack traces | A2, A3, A8 | S-018 redaction, S-019 error law |
| T-17 | Dependency compromise (a trojanised library update) | A7, all | S-017 dependency policy: stdlib-first, pinned, each admitted with a reason |
| T-18 | Owner lockout (lost password + lost 2FA) becoming either permanent loss or a backdoor "recovery" | A6, A2 | Study 10 recovery design: offline recovery held by the operator, never a support-desk override |
| T-19 | Timing side channels distinguishing valid users / valid tokens | A2, A8 | S-005 constant-time comparison |
| T-20 | Platform-specific bypass: a check that holds on Linux filesystems but not case-insensitive or separator-different ones | A1, A7 | Study 45 platform seam; S-013 battery run per-platform (Part XXII) |

## 6. Honest limits (what this model does not claim)

- **A compromised host is a compromised forge.** If an attacker owns
  the machine Samverk runs on, no application-layer defence survives.
  Samverk's job is to make the *application* door strong and to keep a
  stolen *file* (database, backup) from being a skeleton key; host
  hardening is the operator's layer, documented in Part XVIII's
  runbooks, not claimed here.
- **A compromised owner account with full admin is near-total.** 2FA,
  step-up re-authentication for sensitive actions, and the audit log
  reduce and expose this; they do not eliminate it. Claims register
  (S-023) must keep this wording.
- **Side channels beyond T-19** (cache timing, speculative execution)
  are out of scope for a village-scale forge.
- **Denial of service can be blunted, not abolished** (T-10). Rate
  limits and quotas keep the instance usable under casual flood; a
  determined network-layer flood is an operator/network problem.

## 7. Design decisions taken (Samverk's own)

1. **Security primitives precede features.** Password hashing,
   throttling, session storage, audit, escaping, and path/subprocess
   discipline exist (Part I) before the first repository is served —
   no feature slice may route around them (roadmap virtue 2).
2. **Assume the database leaks.** Every credential at rest is either a
   memory-hard hash (passwords), a keyed/plain hash of a high-entropy
   random value (sessions, tokens), or sealed under a key that does
   not live in the database (instance secrets). Test: S-003 and S-006
   acceptance grep a seeded database for usable secrets.
3. **One audit truth.** The audit log is append-only and hash-chained
   from its first slice (S-007), not retrofitted; study 35 defines its
   contents and readers.
4. **The operator is a principal, not a backdoor.** Admin power is
   exercised through the same authenticated, audited paths as
   everything else; there is no unaudited "maintenance mode" write
   path (study 40).
5. **Invite-only by default.** Open registration is an operator choice
   with its friction armed (S-021), never the factory state of a
   sovereign instance.
6. **Every claim is graded.** Part I ends with a claims register
   (S-023): anything in our README not backed by a counted test reads
   NOT PROVEN. This threat model is a claim-shaping document, not a
   marketing document.

## 8. Slices this study feeds

S-001 (this ratification), S-003–S-024 (all of Part I's remainder,
each citing register IDs above), and as background law: Part VIII
(T-12), Part XV (T-13), Part XVII (T-14), Part XVIII (T-10, T-18),
Part XXII (T-20).

*Ratified 2026-10-29 as S-001: the register above (T-01…T-20), the
boundaries (TB1…TB8), and the honest limits (§6) are the standing
reference for every later security decision in Samverk. Changes to this
file after ratification must be recorded in PROJECT_MEMORY_MAP.md with
their reason.*
