# Single sign-on over the seam (S-363)

A signed-in Samtal session may enter Samverk without a
second password (`samverk/seam_sso.py`), under the frozen
S-361 contract and standing on S-362's link.

## The exchange

1. The principal must already hold a standing S-362 link;
   SSO creates neither accounts nor links (`link_required`).
2. Samtal mints an exchange token: signed assertion with
   purpose `sso`, audience `samverk`, life at most 120
   seconds, single-use nonce (HMAC-SHA256, S-249's road).
3. `SeamSsoService.exchange` verifies the signature in
   constant time, judges the claims (expired, over-long,
   and replayed tokens refused with named reasons),
   resolves the principal through the S-045 link, checks
   the account is active, and mints a **real** Samverk
   session through the standing `SessionStore` — same
   lifetime, same revocation, same session list, with the
   device label `Samtal seam (SSO)` so the holder can see
   and revoke it like any other session.

## What SSO is not

- Not a way around account state: a non-active account is
  refused (`account_not_active`), exactly the login
  road's posture.
- Not a second login system: Samverk's own password login
  is untouched and remains for standalone use; with the
  seam disabled every exchange refuses `seam_disabled`.
- Not durable: exchange tokens are single-use and die in
  at most 120 seconds; the session they mint is the
  ordinary, revocable kind.

Used nonces are in-process, as in S-362, with the shorter
120-second cap bounding the restart window.
