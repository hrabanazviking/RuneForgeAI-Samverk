# Study 07 — Passwords and Sessions

*Study question (from `research/INDEX.md`): What does a modern
password + session system owe its users — hashing, login throttling,
session lifetime, revocation, remembered devices — and how does
GitHub's observable behaviour compare?*

*Status: complete 2026-10-29. Feeds **S-004** (password hashing),
**S-005** (constant-time comparison + throttling), **S-006** (session
tokens), **S-009** (cookie baseline). Method: clean-room — public
standards (NIST SP 800-63B), public guidance (OWASP cheat sheets), and
publicly documented forge behaviour (GitHub's docs on passwords and
sessions), restated in our own words; every Samverk choice is our own
and is labelled as a decision.*

---

## 1. What the public standards say a password system owes

NIST SP 800-63B — the most widely cited public standard for digital
authentication — sets the shape that modern systems, ours included,
follow:

- **Length over theatre.** Verifiers must allow long passwords (at
  least 64 characters) and should require a minimum of 8; composition
  rules ("one uppercase, one symbol…") are *not* recommended — they
  push users toward predictable patterns.
- **Screen against the known-bad.** New passwords are checked against
  lists of breached, common, and context-specific passwords (the
  username, the instance name) and rejected if matched.
- **No forced periodic rotation.** Passwords change on evidence of
  compromise, not on a calendar; forced rotation measurably produces
  weaker passwords.
- **Salted, memory-hard storage.** Passwords are stored only as the
  output of a salted, computationally expensive, preferably
  memory-hard key-derivation function, with a unique salt per
  password.
- **Throttled online guessing.** The verifier rate-limits consecutive
  failed attempts per account.
- **No hints, no knowledge-based "security questions"** — both are
  public-information lookups wearing a costume.

OWASP's public cheat sheets add the operational layer: generic error
messages that do not reveal whether the username or the password was
wrong, logging of authentication events (to the audit log — study 35),
and secure session handling after login (below).

## 2. What GitHub's observable behaviour shows

From GitHub's public documentation (checked 2026-10-29):

- A password must be **at least 8 characters including a number and a
  lowercase letter, or at least 15 characters of any kind** — a
  length-first policy with a light composition alternative, close in
  spirit to NIST's direction.
- Passwords are **screened against weak-password datasets** (their
  docs name HaveIBeenPwned-style breach corpora).
- **Passwords authenticate only the browser.** Every other door —
  command-line git, API — uses a different credential (SSH keys,
  personal access tokens). This separation is one of the strongest
  ideas in the modern forge model, and Samverk adopts it wholesale:
  a password is a *web* credential, full stop (studies 08/09 cover
  the others).
- Signed-in users can **see and revoke their active sessions**,
  and sensitive actions (changing email/password, managing keys) sit
  behind a **re-authentication step** ("sudo mode" in their terms) —
  a recent-password proof that decays after a few hours.
- Login failures trigger progressive friction, and 2FA (study 10) is
  required across their hosted service.

## 3. Samverk's password design (decisions)

1. **Hashing (S-004).** Argon2id is the first choice (memory-hard,
   the current public consensus recommendation); scrypt is the
   fallback where Argon2 is unavailable — Python's stdlib `hashlib`
   ships scrypt, which matters for our stdlib-first stance: an
   admitted `argon2-cffi` dependency is justified in the S-017
   register *or* scrypt carries v1 with parameters recorded. Either
   way: unique per-password salt (≥128-bit, from the OS CSPRNG), the
   full parameter set stored beside the hash in a self-describing
   string (algorithm + params + salt + digest), so cost can rise over
   time without invalidating old rows.
2. **Hash upgrade on login.** When a user logs in successfully and
   their stored hash uses outdated parameters or algorithm, it is
   rehashed transparently at the current parameters. This is the only
   painless migration path that exists; S-004's acceptance includes
   it.
3. **Policy.** Minimum 10 characters, maximum at least 128, any
   characters including spaces and Unicode. Screened against a
   bundled common-password list plus the username and instance name
   (an offline corpus — a sovereign instance must not phone a breach
   API with its users' candidate passwords; operators may point the
   checker at a local copy of a larger corpus). No composition rules,
   no rotation schedule.
4. **Verification discipline.** Comparison of digests is constant-time
   (S-005); a login attempt for a nonexistent user performs a dummy
   hash verification against a fixed decoy hash so response timing
   does not enumerate accounts; error messages are identical for
   "no such user" and "wrong password".
5. **Throttling (S-005).** Two independent brakes: per-account
   (failures slow that account's attempts with exponential backoff,
   and past a threshold require the backoff to elapse) and per-source
   (per-IP token bucket, shared with S-011). Brakes *delay*, they do
   not permanently lock — a lockout an attacker can trigger against
   the owner is a denial-of-service feature, not a security feature
   (threat model T-01/T-10, T-18). Every throttle trip is audited.
6. **Password change & reset.** Change requires the current password
   (or a fresh re-auth proof, §5) and **revokes all other sessions**
   — the standard "someone may be in my account" remedy must actually
   evict them. Reset by email link where mail is configured: single-
   use, short-lived (≤1 hour), hashed at rest like a session token;
   where mail is not configured, the operator's host-side reset
   command is the path (study 38/40), and it is audited as an admin
   event. A completed reset also revokes all sessions.

## 4. Samverk's session design (decisions)

A session is the thing a password *buys*; it deserves equal care.

1. **Token shape (S-006).** 256 bits from the OS CSPRNG, encoded for
   the cookie; **only its SHA-256 hash is stored**. A stolen database
   therefore contains no usable session (the S-006 acceptance test:
   values lifted from a seeded DB are presented and rejected).
   Why a plain hash suffices here while passwords need scrypt: the
   token is high-entropy random, not human-chosen — there is no
   dictionary to slow down. (This asymmetry is the single most
   commonly missed point in home-grown auth; we write it down so it
   is never "fixed" in the wrong direction.)
2. **Two clocks.** **Absolute expiry** (default 30 days) caps a
   session's total life no matter how active; **idle expiry**
   (default 7 days without a request) ends abandoned ones. Both are
   operator settings within sane bounds, shown to the user on their
   sessions page in plain words.
3. **Rotation on privilege change.** Login, password change, 2FA
   enrolment, and any elevation issue a *new* session token and kill
   the old one (session-fixation and stale-token defence).
4. **Cookie baseline (S-009).** `HttpOnly` always; `Secure` whenever
   the connection is HTTPS (and S-015 makes HTTPS the default);
   `SameSite=Lax` as the default posture; cookie name carries no
   framework advertising; path scoped to the instance root.
5. **Visibility and revocation.** Users see their sessions (device
   hint from user-agent, source IP, created/last-seen) and can revoke
   any or all — the list GitHub's users rely on (§2) is load-bearing,
   not garnish. Revocation is a tombstone in SQLite: instant, total,
   auditable.
6. **Remembered devices.** "Remember this device" for skipping 2FA
   prompts is a *separate* long-lived token with its own hashed
   storage, its own revocation list, and a 30-day cap; it never
   substitutes for the password, only for the second factor, and it
   dies with any password change (study 10 owns its full design).
7. **Re-authentication for sensitive actions.** Following the public
   "sudo mode" pattern (§2): changing password/email, managing SSH
   keys and tokens, and all admin actions require a password proof
   fresher than 3 hours; the proof is a timestamp on the session, not
   a second session.

## 5. What we deliberately do not build

- No security questions, no password hints (NIST is blunt; so are we).
- No "keep me logged in forever" option — absolute expiry is a
  promise, not a preference.
- No password authentication for git or API transports, ever (§2) —
  the password's blast radius is the browser session, and sessions
  are revocable.
- No third-party captcha or breach-API calls in the auth path
  (sovereignty; S-021 covers signup friction without them).

## 6. Slices this study feeds

S-004 (hashing + upgrade-on-login), S-005 (constant-time compare,
throttling primitives), S-006 (session tokens: shape, storage, clocks,
revocation), S-009 (cookie flags + CSRF interplay), S-011 (per-source
buckets shared with login), S-015 (Secure cookie depends on TLS law),
S-021 (signup screening corpus), S-022 (auth-bypass battery targets
every decision above).
