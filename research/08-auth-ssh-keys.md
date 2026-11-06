# Samverk research 08 — SSH key custody, forced commands, and deploy-key scopes

**Research and engineering brief | 2026-11-06 | Status: proposed design guidance, not a shipped-feature claim.**

This study fills the originally empty numbered research shelf. It uses public standards and observable Git behavior, not GitHub proprietary code or assets. Apply it under Samverk's clean-room, AGPL, no-Docker, security-first and standalone-first laws. Relevant roadmap: **S-030–S-031, S-085–S-088, S-095**.

## Protocol facts and engineering implications

- SSH authenticates a connection with a public/private keypair; the forge should receive only the public key, fingerprint and tightly scoped identity binding. A private SSH key must not be uploaded to the server as routine setup.
- A personal key represents an account; a deploy key represents an explicit repository grant. These are different rights and must not be silently interchangeable.
- An SSH forced-command pattern restricts authenticated key holders to Git-specific commands, rather than exposing a general shell. Real `sshd` behavior still needs testing even if a Python router passes simulated tests.

## Recommended Samverk architecture and contracts

- Bind a canonical key fingerprint to a principal with current account state checked on every authorization. Remove access immediately after key revoke, account suspension or repository-grant change; invalidate caches predictably.
- Parse `SSH_ORIGINAL_COMMAND` with a constrained grammar for permitted Git operations; reject shells, control characters, path traversal and unrecognized options. Invoke Git directly without `shell=True`.
- Permit deploy keys only for their named repo; default read-only. Display fingerprint, origin, last-used, rights and how to revoke next to each key.
- Document host key verification and rotation separately from user keys. Never suggest disabling StrictHostKeyChecking as a permanent repair.

## Failure modes and less-obvious cases

- Duplicate public key across accounts, revoked deploy key that remains in an old authorized_keys snapshot, username rename, missing forced-command environment, first-connect host key warning.
- SSH key types and algorithms have changing ecosystem support; test Ed25519 and RSA/SHA-2 compatibility against installed OpenSSH, not speculative constants.

## Testable acceptance work

- Use a real OpenSSH daemon in an isolated host to clone/push with personal and deploy keys, verify denied cross-repo access, and ensure `ssh host sh` cannot open a shell.
- Test concurrent key revocation while an auth cache is live and confirm the next connection fails.
- Record the real-sshd test as NOT PROVEN when daemon access is unavailable; never count a mocked subprocess as this matrix cell.

## Evidence and decision discipline

- Compare each recommendation against current implementations and tests before coding. Existing modules are **evidence of implementation**, not proof they are wired to the live `samverk/server.py` HTTP surface.
- Record decisions (accepted/deferred/rejected), exact test command and host, passing/failing/skipped counts, and any changes to `docs/CLAIMS_REGISTER.md` and `PROJECT_MEMORY_MAP.md`.
- Do not promote interoperability, security or portability to PROVEN without a fresh end-to-end run in the specified environment.

## Public technical references

1. https://man.openbsd.org/sshd
2. https://man.openbsd.org/authorized_keys
3. https://git-scm.com/docs/gitprotocol-v2
4. https://cheatsheetseries.owasp.org/
