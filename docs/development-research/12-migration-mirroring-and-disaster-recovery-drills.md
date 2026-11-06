# Mirror/import completeness, backup manifests and recovery rehearsal

**Samverk implementation research, 2026-11-06.** This document provides proposed technical policy and acceptance work, not evidence that a feature has shipped. Existing roadmap references: S-329–S-344; S-341–S-342. Maintain the clean-room rule and no-Docker decision.

## Established context

- Git mirror copies Git refs and object history but does not automatically preserve GitHub issues, wiki, releases, workflows, secrets or all LFS bytes.
- Whole-instance export must cover SQLite, bare repos, LFS, configuration, keys and assets with a consistency protocol.
- A synced mirror is not a verified recovery plan until a separate scratch instance restores and operates correctly.

## Concrete engineering plan

- Inventory source repos as approved public, approved private, uncertain or excluded; do not import uncertain/private accounts without explicit owner approval and minimal credential scope.
- Track mirror last attempted/success timestamps, source ref digest, bytes changed, retry reason, and visible stale state; protect local snapshots from destructive upstream force pushes.
- Import Git and metadata in resumable stages with stable external IDs. Preserve original authors as source attribution, not forged local principals.
- Build export manifest with source snapshot, schema version, Git refs/OIDs, LFS counts and digests, issues/PR/comments counts, omissions, checksums and key custody instructions.
- Use SQLite online backup or equivalent safe snapshot. Never assume copying a live main SQLite file captures WAL state.

## Cases likely to break naive implementations

- Source renamed or deleted mid-import; LFS missing after Git sync; upstream force-push; private PR comments referencing nonexistent local users.
- Cloud-only secrets cannot be reconstructed by ordinary GitHub API export; declare unsupported migration data.
- Interrupted export must remain marked incomplete, not offered as valid backup.

## Counted acceptance evidence required

- Resume interrupted import without double issues/comments; verify source-to-destination ID map and counts.
- Revoke source credential and show actionable error without leaking secret.
- Restore on a different machine with no network to GitHub and test login, clone, issue read, LFS object checksum and audit chain.

## Handoff rule

For every accepted implementation, identify the module and actual server entry point, submit an unauthorized-action test, document schema or migration effects, and verify both success and refusal behavior through the live process where relevant. Record the full test count, the host, and every skip. Update PROJECT_MEMORY_MAP and CLAIMS_REGISTER only with real evidence; do not silently upgrade an untested capability to PROVEN.

## Primary references

1. https://git-scm.com/docs/git-bundle
2. https://sqlite.org/backup.html
3. https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api
