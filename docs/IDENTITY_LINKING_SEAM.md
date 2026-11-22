# Identity linking over the seam (S-362)

A Samtal principal links to a Samverk account by mutual
proof, under the frozen S-361 contract (`samverk/
seam_contract.py`); the machinery is `samverk/
seam_identity.py` over S-045's link shape.

## The exchange

1. The account holder, signed in to Samverk, starts or
   confirms the link for their own account.
2. Samtal mints a signed assertion token
   (`mint_link_token`): claims are the contract's —
   provider `samtal`, audience `samverk`, consent true,
   the principal id, issued/expiry inside the 300-second
   cap, and a single-use nonce — signed HMAC-SHA256 over
   the exact claim bytes (S-249's road), with the seam's
   shared secret.
3. Samverk verifies the signature in constant time,
   judges the claims through S-361's
   `validate_link_assertion` (wrong audience, missing
   consent, expiry, over-long life, and replayed nonces
   are all refused with named reasons), and writes the
   S-045 link. The audit record is S-045's own
   `auth.identity.link`.

A link token is not a session and not a login; it confers
no authentication power. Sign-on over a standing link is
S-363, built separately.

## Unlinking — one click, either side

- In Samverk: `unlink_from_samverk(account)`.
- In Samtal: `unlink_from_samtal(principal)` — Samverk
  resolves the principal and unlinks the same record.

Both land on S-045's unlink and its `auth.identity.unlink`
audit verb. Unlinking cascades nothing: the Samverk
account, its repositories, and its own login stand whole.

## Honest bounds

- The seam must be enabled (`seam.samtal.enabled`, S-361);
  every door refuses `seam_disabled` otherwise.
- Used nonces are remembered in-process by the service
  instance. The 300-second assertion cap bounds the
  replay window a restart could reopen; a multi-process
  deployment should share the nonce set — that sharing is
  named here, not built in this slice.
- The shared secret's custody is the operator's (S-020's
  key-custody runbook is the standing pattern); it is
  never stored in the database by this slice.
