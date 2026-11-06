# Samverk research 36 — Git commit signatures, verification and trust presentation

**Research dossier • 2026-11-06 • Design recommendations / NOT PROVEN until tested.** This is a clean-room synthesis of public specifications and practices. Roadmap **S-293–S-312, S-175**.

## Technology and observed constraints

- A commit may carry an embedded GPG/SSH signature. That signature supports an integrity/authorship statement about certain content when checked against a trusted key, not a universal guarantee the code is safe.
- Git distinguishes author and committer metadata from the signer; UI badges should not conflate those identities.
- Verified identity depends on key ownership, revocation/expiry policy and time context, especially after key rotation.

## Recommended implementation approach

- Use stock Git's `verify-commit`/`verify-tag` where supported; capture a structured result with signer fingerprint, reason, verification time and trust policy revision.
- Provide verified/unverified/unknown/error statuses in text, each with accessible explanation; never infer verified from presence of `gpgsig` alone.
- Bind account key registration to an authenticated principal and provenance audit; display key type, fingerprint, state and last verified use.
- Keep protected-branch signature rule policy separate from casual UI badge. Fail closed where required and state exactly which commit failed.

## Threats, edge cases and operational limits

- Signer key revoked after commit, invalid signature, unsigned merge commit, signed tag points to unsigned commit, email mismatch, SSH allowed signers file injection.

## Acceptance checks

- Verify known signed fixtures with GPG and SSH signatures, altered commit bytes and revoked keys.
- Test a required-signatures branch under push and merge, not only UI indicator.

## How to use this study

Before implementation, map each recommendation to current `samverk/` code and tests; identify new versus pre-existing functionality. Every public claim needs a testable scope, a real entry point, and a recorded host. A green unit test does not prove the browser application or real Git transport. Record accepted, deferred and rejected designs and keep `docs/CLAIMS_REGISTER.md` and `PROJECT_MEMORY_MAP.md` consistent. Any unverified security assertion remains NOT PROVEN.

## Primary public references

1. https://git-scm.com/docs/git-verify-commit
2. https://git-scm.com/docs/git-verify-tag
3. https://git-scm.com/docs/gitformat-signature
