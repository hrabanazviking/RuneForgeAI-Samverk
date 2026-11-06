# Samverk research 37 — Mirror freshness, GitHub migration and restore-proofed backups

**Research dossier • 2026-11-06 • Design recommendations / NOT PROVEN until tested.** This is a clean-room synthesis of public specifications and practices. Roadmap **S-070, S-074, S-329–S-344**.

## Technology and observed constraints

- A pull mirror is a local copy of remote Git refs/objects, but not automatically of issues, releases, wiki, LFS or credentials. Backups must name what they cover.
- Git `bundle` makes a portable content/refs export but still requires independent metadata snapshots for full forge recovery.
- A synced mirror is not a proven backup until restoration into an isolated instance succeeds and expected data is compared.

## Recommended implementation approach

- Classify each source repo as approved public, approved private, uncertain or excluded; do not mirror uncertain repos without owner's decision.
- Use scheduled jobs with jitter, bounded retries, backoff, checkpoint, last-attempt/success timestamps and safe missing-credential reporting.
- Plan whole-instance exports using SQLite online backup, a stable ref snapshot, LFS assets, config and key custody under a manifest with hashes. Scrub tokens and separate sensitive secrets.
- Protect against force-push and source deletion by optionally retaining separate recovery refs/snapshots, with retention/storage costs explicit.

## Threats, edge cases and operational limits

- Remote disappeared, network partially transferred, nested submodule credentials, source repo renamed, LFS omitted, DB snapshot and Git refs captured at different times.

## Acceptance checks

- Restore one public and one private fixture into scratch instance; clone refs, sign in, inspect issues, validate LFS and compare manifest.
- Simulate 72-hour mirror failure; status must be stale, not green. Retry after recovery without data loss.
- Inspect inventory for privacy and key exposure before any export is sent to another host.

## How to use this study

Before implementation, map each recommendation to current `samverk/` code and tests; identify new versus pre-existing functionality. Every public claim needs a testable scope, a real entry point, and a recorded host. A green unit test does not prove the browser application or real Git transport. Record accepted, deferred and rejected designs and keep `docs/CLAIMS_REGISTER.md` and `PROJECT_MEMORY_MAP.md` consistent. Any unverified security assertion remains NOT PROVEN.

## Primary public references

1. https://git-scm.com/docs/git-bundle
2. https://sqlite.org/backup.html
3. https://git-scm.com/docs/git-remote
