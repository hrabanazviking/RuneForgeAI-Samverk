# Study 35 — Audit Log

*Study question (from `research/INDEX.md`): What belongs in an audit
log — actor, action, target, IP, timestamp — how is it tamper-evident,
and who may read it at instance, org, and repo level?*

*Status: complete 2026-10-29. Feeds **S-007** (audit log core) and
**S-008** (event taxonomy v1), and is cited by every later slice that
emits an event. Method: clean-room — public behaviour of large forges
(GitHub's publicly documented audit log for organizations and
enterprises; similar public features elsewhere), public guidance on
security logging (OWASP's logging cheat sheet principles), and our own
design decisions, all in our own words.*

---

## 1. What an audit log is — and is not

An audit log is the forge's **witness**: an append-only record of
security-relevant actions, kept so that after something goes wrong —
or right before a court of one's own conscience — the question "who
did what to what, when, from where" has an answer that does not depend
on anyone's memory.

It is **not**:

- an activity feed (those are for people browsing; they may be pruned,
  re-shaped, and are optimistically written — study 21);
- an application/debug log (those serve developers, rotate freely, and
  must never contain the secrets an audit log also must never contain —
  study under S-018);
- a backup (it records *that* things happened, not the data needed to
  undo them).

Public behaviour worth learning from: GitHub's organization and
enterprise audit logs record events with an actor, an action verb in a
namespaced form (e.g. an event *category.action*), the affected
repository/organization/user, a timestamp, and — only when the owner
explicitly enables IP disclosure — the actor's source IP address.
Owners can search and export the log. Two lessons we take as our own:

1. **Namespaced, machine-readable action names** make a log searchable
   years later; free-text log lines rot.
2. **IP addresses are sensitive.** GitHub hides them by default and
   makes showing them an owner decision with legal weight. For a
   sovereign instance the operator *is* the owner, but the principle
   stands: IPs are recorded (they are the point of the witness) and
   their *display* is a deliberate, itself-audited act.

## 2. What belongs in an event (the record shape)

Every audit event in Samverk carries, at minimum:

| Field | Meaning | Notes |
|---|---|---|
| `seq` | Monotonic sequence number | Makes gaps (deleted rows) visible even before hashes are checked. |
| `ts` | UTC timestamp, stored as integer epoch + rendered ISO-8601 | Server clock; render in the reader's timezone, store in UTC. |
| `actor_kind` | `user`, `token`, `ssh_key`, `system`, `anonymous` | *How* the actor authenticated matters as much as who. |
| `actor_id` | The user/principal id, when known | Null only for genuinely anonymous events (e.g. failed login for an unknown username — see §4). |
| `action` | Namespaced verb from the taxonomy (S-008) | e.g. `auth.login.success`, `repo.push`, `admin.user.disable` — defined in the taxonomy doc, never invented ad hoc at a call site. |
| `target_kind` / `target_id` | What was acted on | Repository, user, org, token, instance. |
| `source_ip` | The connecting IP as the server saw it | Recorded always; displayed per §5. Proxy headers are trusted only from configured proxies (see threat model TB1). |
| `outcome` | `success`, `failure`, `denied` | Failed and denied attempts are first-class events — they are how attacks become visible. |
| `detail` | Small structured JSON of safe specifics | e.g. which ref, old/new oid prefixes, which permission changed from what to what. **Never** secrets, tokens, passwords, or full request bodies (S-018 redaction applies *before* this field is written). |
| `prev_hash` / `entry_hash` | The tamper-evidence chain | §3. |

And explicitly **never**: passwords (not even wrong ones typed at a
login form — recording them turns the log into a credential store),
session or API token values, private keys, webhook secrets, recovery
codes, or the content of uploaded files.

## 3. Tamper evidence (the chain)

Decision (ours, designed for S-007): the log is a **hash chain**.

- Each entry's `entry_hash` = SHA-256 over the canonical serialisation
  of the entry's fields *including the previous entry's hash*
  (`prev_hash`). The genesis entry chains from a fixed, published
  constant.
- The table is append-only in the application: no UPDATE or DELETE of
  audit rows exists in any code path; corrections are new entries that
  reference the entry they correct.
- A **verifier** (`samverk audit verify`) recomputes the chain from
  genesis and reports the first broken link, if any. This is S-007's
  acceptance shape: tampering with a row is detected.
- The chain proves the log was not edited *after the fact* by anyone
  who lacks the ability to rewrite the whole chain — and rewriting the
  whole chain is itself detectable the moment any external anchor
  exists. Anchoring: the instance can periodically write the current
  head hash somewhere else (operator's file, another machine, the
  Samtal seam in time) — the anchor cadence is an operator setting;
  the mechanism is designed in Part XVIII. Without an anchor, the
  honest claim is *"tamper-evident against row-level edits and
  truncation of the tail is detectable by sequence gaps"*, and the
  claims register (S-023) must say exactly that, no more.
- Hashing is over a **canonical serialisation** we define once (fixed
  field order, UTF-8, unambiguous separators), because a chain that
  depends on incidental JSON formatting is a chain that breaks when a
  library changes its mind.

## 4. Which events (taxonomy sketch; S-008 owns the full list)

Version 1 covers three families, mirroring the roadmap:

- **auth** — login success/failure, logout, password change, token
  created/revoked, SSH key added/removed, 2FA enrol/reset, session
  revoked, signup (and signup denied by throttle).
- **repo** — create, delete, visibility change, transfer; push
  (per ref update: ref name, old/new oid); branch protection change;
  collaborator added/removed/role-changed; release published; settings
  changes that affect security (webhooks added/removed count double:
  they are both an integration and an exfiltration path).
- **admin** — user created/disabled/deleted, role changes, instance
  settings changes (each recording old → new for the changed key),
  plaintext-HTTP override armed (S-015), audit IP-display enabled,
  audit export taken, key rotation (S-020).

Failed logins record the *attempted username string* in `detail` —
attackers' dictionaries are intelligence, not credentials — but if the
attempted string happens to equal an existing user's actual password,
that is a coincidence the redactor cannot detect; the field is kept
short, access-controlled, and excluded from exports by default. (This
trade-off is named here honestly rather than discovered later.)

## 5. Who may read it (the three scopes)

- **Instance scope** — site administrators only. The whole chain,
  including auth events and admin events. Reading or exporting the
  instance log is itself an admin event (`admin.audit.export`).
- **Organization scope** — org owners see events whose target belongs
  to their org (their repos, their members' org actions), never other
  orgs' events, never instance admin events. (Model lands in Part IX;
  the *filter rule* is fixed here: org scope = target-ownership
  filter over the one instance chain, not a separate log.)
- **Repository scope** — repo admins see the repo's own events (pushes,
  protection changes, collaborator changes). No auth events, no IPs at
  this scope.
- **IP display** — source IPs are shown at instance scope by default
  (the operator is the data controller of their own instance) and at
  org/repo scope **only** if the operator enables disclosure for that
  scope — mirroring, in our own design, the public lesson of §1 that
  IPs are personal data with legal weight in many jurisdictions.
- A user may always see **their own security history** (their logins,
  their tokens, their keys) — "sign-ins to your account" is a feature
  users of large forges rely on to spot theft, and it costs us only a
  filtered view of the same chain.

There is **one chain per instance**. Separate per-org logs would make
cross-scope incidents unprovable; the one-truth rule (roadmap
architecture stance: one event store under audit, feeds, notifications,
webhooks) starts here.

## 6. Retention, export, and failure behaviour

- **Retention:** audit rows are never rotated away by the application.
  An operator may archive a *prefix* of the chain to a file (the
  archive keeps the head hash of the archived prefix so the remaining
  chain still verifies against its anchor). Deleting audit history
  wholesale is an operator act performed on the host, outside the app,
  and is therefore outside what the app can prevent — named honestly
  in the claims register.
- **Export:** JSON lines, one event per line, for instance and org
  scopes; export events are audited (§5).
- **Failure behaviour:** if an audit write fails, the action it was
  witnessing **fails closed for security-relevant mutations** (an
  unauditable admin change must not silently succeed) and the failure
  is surfaced loudly to the operator. Read-only user actions may
  proceed with the audit failure itself logged at the first
  opportunity — this asymmetry is deliberate: availability for readers,
  strictness for power.

## 7. Design decisions taken

1. One append-only, hash-chained table; canonical serialisation fixed
   in S-007's implementation and documented there.
2. Taxonomy is a versioned document (S-008); emitters may only use
   names from it.
3. Record always, display deliberately (IPs §5); redact before write
   (S-018 applies at the emitter).
4. One chain, three read scopes, filtered views — never separate logs.
5. The verifier is a first-class operator command, run in the Part I
   gate (S-024) and available in Part XVIII's runbooks.

## 8. Slices this study feeds

S-007 (core: table, chain, verifier), S-008 (taxonomy v1 + emitter
tests), S-018 (redaction at write), S-023/S-024 (claims + gate), and
every later slice that performs a security-relevant action — which in
Samverk means: if it mutates, it audits.
