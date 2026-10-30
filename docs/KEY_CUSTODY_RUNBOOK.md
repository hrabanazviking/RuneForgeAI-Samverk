# Samverk — Key Custody Runbook (S-020)

Instance keys live in `<data_root>/keys/` as
`instance-<purpose>-v<N>.key` (hex, mode 600). Custody of those
files is custody of the instance's signing and encryption
roots. This runbook is the operator's whole duty:

## Back up

1. Stop nothing — keys are read at use, not held open.
2. Copy the **whole `keys/` directory**, preserving permissions
   (`cp -a`, or tar with `-p`), together with the instance
   secrets file (S-003) and a database backup.
3. Store the copy **offline or encrypted**, somewhere that is
   not the same machine and not the same account as the database
   backups' usual home. A backup of the database alone can never
   restore keys — by design (S-003), they are not in it.
4. Record each key's **fingerprint** (`samverk keys status`)
   with the backup. The fingerprint is safe to write anywhere;
   it is how you later prove a restored key is the right key.

## Restore

1. Put the `keys/` files back with mode 600
   (`chmod 600 keys/*.key`) — Samverk refuses to load a
   loosely-permissioned key file.
2. Run `samverk keys status` and compare fingerprints against
   the backup record. A mismatch means the wrong backup; do not
   "fix" it by regenerating — regeneration invalidates every
   signature and ciphertext the old key ever made.

## Rotate

1. `samverk keys rotate --purpose signing` — mints the next
   version, makes it current, and writes `admin.key.rotate` to
   the audit log with old and new fingerprints.
2. Old versions keep loading by version number, so existing
   signatures and ciphertexts keep verifying. **Do not delete
   an old version** until every consumer of it is gone —
   deletion is a manual file act, done deliberately, never a
   Samverk command.
3. Re-run the backup step: a backup without the newest key is
   a restore that loses everything signed since.

## If a key is compromised

Rotate immediately (above), then treat everything the old key
protected as suspect: sessions and tokens signed under it must
be revoked by their owning subsystems, and the incident belongs
in the audit log as an operator note. Deleting the compromised
version's file makes its material unusable by Samverk — and
also makes anything only it could verify unverifiable; that
trade is the operator's call, made knowingly.
