# The Samtal seam contract — ratified and frozen (S-361)

Part XIX joins two sovereignties; it merges neither. This
document freezes the seam contract designed in research
file 39 (`research/39-samtal-integration-seam.md`) after
review against the landed Samverk codebase. The contract
as code is `samverk/seam_contract.py` (contract version 1);
S-362..S-380 implement against it. Changing a frozen name,
number, or rule is a contract change and must be named as
such wherever it lands.

## Review against the codebases

Samverk side — PROVEN on this seat, each anchor re-checked
by the S-361 battery (`tests/test_seam_contract.py`):

- Identity link rests on S-045's shape
  (`samverk/identity_linking.py`: provider `samtal`, one
  link per (account, provider), one account per (provider,
  external id), external id is an identifier, never a
  credential) and S-249's HMAC signing road
  (`samverk/webhook_signing.py`).
- The embed contract rests on S-277's gist embed
  (`samverk/gist_embed.py`) and the versioned API contract
  (`samverk/api_contract.py`): Samverk serves, Samverk
  decides.
- The event bridge rests on S-247's webhook events
  (`samverk/webhook_events.py`) and the inbox's
  exactly-once rule (S-226, `samverk/inbox.py`).
- Sovereignty rests on Samverk's own login
  (`samverk/login.py`) and whole-instance export S-341
  (`samverk/whole_instance_export.py`): standalone never
  depended on the seam, and does not start now.

Samtal side — **NOT PROVEN**: no Samtal codebase stands on
this seat, so the Samtal-side review (its principal ids,
its hall model, its render surface) could not be re-run
here. The contract is written only against Samtal's
published shape in research file 39 and S-045; the
Samtal-side ratification remains owed and is not claimed.

## The frozen contract

1. **Identity link.** Mutual proof by signed token
   exchange: a short-lived (at most 300 seconds),
   audience-bound (`samverk`) assertion, replay refused by
   nonce, explicit consent required. Unlinking is one
   action on either side; no destructive cascade follows
   automatically from either app's deletion or revocation.
2. **Embed contract.** Embed kinds are frozen: repo, file,
   pull_request, issue, gist, release. Every embed or
   unfurl is judged at request time against the *viewer's*
   Samverk rights; the embed confers no access.
3. **Event bridge.** Event kinds are frozen: push,
   pull_request, issue, release. Delivery is
   idempotency-keyed and exactly-once at the seam; halls
   opt in and may mute; a private repository's event never
   enters a hall not restricted to members with rights.
4. **Sovereignty.** The seam is optional and disabled by
   default (`seam.samtal.enabled`). Direct login, Git
   transports, and admin recovery work with Samtal absent
   or dead; killing Samtal mid-push loses no Git data and
   no audit event. Federation between villages is refused
   permanently. The kill switch is S-372.

No migration (schema 140 stands) and no new taxonomy
event (142 stand) — ratification freezes words and pure
judgements; S-362 builds the first machinery.
