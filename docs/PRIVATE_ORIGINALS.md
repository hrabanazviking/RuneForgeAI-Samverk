# Private originals (S-337)

Roadmap S-337: with a read-scoped GitHub credential in
place, the private originals mirror too, landing as
*private* mirrors always.

## What stands

- `samverk/private_originals.py` —
  `PrivateOriginalsService` runs one owner's defined
  private originals (census classification
  `original-private`, state `defined`, S-335) in name
  order. Public originals are S-336's pass and held
  uncertain entries are never auto-mirrored; the run
  counts both as skipped and touches neither.
- The credential gate (pure `decide_credential`): a
  private original syncs only when its mirror names an
  S-330 credential (an S-003 instance-secret name,
  never a value), that secret is loaded, and the
  operator-declared scope is read-only. A declared
  scope naming any write/admin power, an undeclared
  scope, an unloaded secret, or a missing credential
  refuses the sync before any fetch, in plain words,
  and the refusal is recorded — never a silent skip.
- Private always (pure `landing_is_private`): before
  any sync, a mirror that does not stand `private`
  is set `private` through the owner's audited
  visibility road (S-050), and the repair is written
  into the run's detail. After the sync the landing
  is checked again; a mirror not standing private is
  a failed run however the fetch went.
- Proof, again: each synced mirror is verified
  ref-for-ref against its source as in S-336, with
  the S-014 ls-remote seam carrying the resolved
  token so a private source can answer. Sync rides
  S-330's credential-resolving sync, which scrubs
  the token from recorded detail.
- Every run — verified, failed, or refused at the
  gate — is recorded in the standing run log
  (`first_pass_mirror_runs`, phase `private`).
  `render_private_originals_page` states each verdict
  in words, never colour-only.

## Deliberate non-changes

No migration and no new audit event: the schema
stands at 138 and the taxonomy stands at 138. This
slice reuses the seams and tables its predecessors
built (S-003 secrets, S-014 ls-remote, S-329 pull
mirrors, S-330 credentials, S-335 census, S-336 run
log), on purpose.
