# Samverk Interoperability: Bifröst Immutable Long-Term Memory Journal and Branches

**Owner request:** 2026-11-19  
**Status:** Proposed, optional integration; NOT proof of installed or working Bifröst/Samverk linkage  
**Canonical Bifröst architecture:** [Git-like Journaled Long-Term Memory, Rollback and Branches](https://github.com/hrabanazviking/bifrost-viewer/blob/docs/second-brain-incremental-multimodal-gateway-2026-11-19/docs/roadmaps/SECOND_BRAIN_GITLIKE_JOURNALED_ARCHIVE_2026-11-19.md).

## Why this belongs in Samverk's own project

The Bifröst Second Brain now has three memory tiers: **immutable long-term accepted memory**, **mutable medium-term focus domains**, and **ephemeral short-term conversational/task context** that expires. The owner proposes Git-like journaled history, branches, merges, and rollback on long-term memory.

Samverk already implements a backend of standard Git operations, including `samverk/refs.py` (protected/ref CAS updates), `samverk/objects.py` (commit/tree/blob reading), `samverk/pull_request_merge.py`, `samverk/revert_git.py`, `samverk/event_store.py`, `samverk/lfs_store.py`, and `samverk/repo_backup.py`. These code modules provide useful building blocks, but **their presence is not a verified deployed Samverk HTTP forge**. The November 13 README audit characterized the project as a backend-rich alpha with incomplete browser/API composition; check the newest installed state and tests before claiming service compatibility.

Samverk should remain an independent AGPL-3.0 Git forge; Bifröst Viewer remains an independent MIT-licensed canonical Second Brain over PostgreSQL/pgvector and immutable content-addressed source assets. Nothing in this integration requires Samverk to own Bifröst's canonical records.

## Integration approach: thin, optional, Git-native

- [ ] Define a **versioned manifest exchange format** representing a *commit* as the hash of a source/asset revision manifest, cross-source correction links, selected graph generation, owner approval provenance and parent commit ID(s). Manifest JSON/Markdown can be represented as ordinary Git objects/commits.
- [ ] Support an owner-chosen local Git repository hosted by Samverk **if Samverk's actual deployed protocol is available**, or standard Git CLI without the Samverk service for first implementation. Both consume the same Git export format.
- [ ] Include normal Git branch/tag operations for reference views: `main` approved current knowledge, `research/*` hypotheses, `characters/*` visual-lore variants, `recovery/*` preview snapshots. Branches are references to immutable version manifests, not copies of the entire brain and not user folder hierarchy.
- [ ] Use existing CAS/ref revision checks in Samverk, or stock Git's guarded `update-ref`, for concurrent branch-head updates. Protect accepted main history from silent force rewrite and unexpected concurrent merges.
- [ ] Provide a reviewable diff of added sources, supersession links, category association metadata, approved image/character traits, and model/config changes. The source/visual media remains available by stable protected Bifröst asset references; Git LFS may be used only for explicitly opted-in subsets.
- [ ] On rollback, **create a new revert/restoration commit** pointing the Bifröst *current view* to an older known-good manifest; never rewrite or delete prior immutable source files, corrections or Git history.
- [ ] Make branch merge an explicit owner-approved action that reports conflicting source/version and character canon claims. Never let an AI-generated confidence estimate silently choose a conflict winner.
- [ ] For external character clients, keep the same read-only Bifröst API and universal whole-brain access; don't require characters to connect to Samverk or choose per-character branches. Default published branch should be Bifröst's approved main.
- [ ] Never journal raw short-term session transcripts/temporary prompts or persist them as commits/PR comments. Medium focus changes remain a separate mutable ledger rather than durable long-term knowledge commits.
- [ ] Treat Samverk's event store/audit witness as the record of actions **inside Samverk** only; Bifröst's own append-only journal remains authoritative for knowledge archival actions. Cross-system events include idempotency, actor, commit id, time and failure status, without raw private memory payload.
- [ ] Avoid storing binary images/videos, large embedding arrays, pgvector indexes or PostgreSQL WAL inside ordinary Git objects. Keep canonical assets in Bifröst's content-addressed archive; optional Git LFS support can mirror owner-selected asset subsets.
- [ ] Preserve trust/licensing boundaries: Samverk AGPL-3.0 and Bifröst MIT. Prefer a separately installed, optional service or standard Git CLI adapter, and document the relevant distribution/network license effects before copying modules.
- [ ] Keep Samverk optional: if it is absent/offline, Bifröst archive, journal, rollback, Skry read-only search, Gufo inference and raw-folder ingestion all continue.

## Data integrity and recovery

- Store an export checkpoint with manifest version, branch ref, commit tree hash, Bifröst schema/model identities, per-file object checksums and last verified Bifröst archival event ID.
- Imported Git histories must be reviewed before becoming Bifröst currentness pointers; untrusted Git commits are not proof of canonical source truth.
- Use Git bundle exports or other verified Git backups for the manifest repository. They are NOT equivalent to a full Bifröst backup: also restore PostgreSQL base backup/WAL, protected raw object archive, owner folder association ledger, graph generation manifests and secrets separately.
- Filesystem journaling (ext4 etc.), filesystem snapshots (Btrfs/ZFS) and Git-style history solve different problems. Confirm the actual G14 filesystem before planning snapshots. Coordinate snapshots with PostgreSQL for consistency.
- Authorize exports/imports explicitly; do not automatically push private memories to GitHub or a public Samverk repository. Local-first and private by default.

## Tests and release gates

1. Git export/import of a three-commit synthetic long-term archive reproduces immutable source IDs/versions and source hashes without sending real user data.
2. Separate branches hold competing visual lore interpretations; main stays accepted/unchanged until an owner-approved conflict-aware merge.
3. Revert creates a **new** commit; old and reverted history remain readable; Bifröst currentness matches the intended prior state.
4. Two concurrent updates to the same ref trigger one CAS success and one actionable conflict, never silent lost update.
5. Duplicate content in two RawLibrary folders exports as one immutable asset reference and two location/category associations; a move updates the live path ledger and not original archived bytes.
6. Short-term session sentinel does not appear in Git commits, Samverk audit/comment events, bundle exports, backups or model prompt logs after session ends.
7. With Samverk stopped/removed, Bifröst continues working and can later replay/restore manifest exports idempotently without duplicate canonical source writes.
8. Bifröst restore requires all necessary object/DB/journal files; Git bundle alone never reports "full Second Brain restored".
9. No existing Samverk API, LFS, merge, revert, refs or security regression. Confirm independent test results and actual deployed HTTP status rather than assuming a working UI from repository file presence.

## Work order

Read Samverk's current source and public API surface → coordinate with Bifröst owner architecture → design open manifest exchange with synthetic fixtures → implement an **optional** Git/Samverk adapter independently of the brain data store → verify CAS/review/branch/revert and on/off operation → test recovery and privacy → owner-controlled deployment.

**No changes to actual services, Git runtime config, Bifröst Postgres data, raw media, or running Samverk instance are implied by this roadmap.**
