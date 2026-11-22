# Wiki mirror (S-339)

Roadmap S-339: a source repo's wiki (S-273 form)
mirrors alongside its code repo.

## What stands

- `samverk/wiki_mirror.py` — `WikiMirrorService`
  mirrors the wiki of an S-070/S-329 mirror repository
  into the S-273 wiki standing beside it
  (`<repo>.wiki`), and records every outcome in the
  standing run log (`first_pass_mirror_runs`, phase
  `wiki`).
- The wiki source is derived, never stored (pure
  `wiki_source_for`): a local code source
  `<name>.git` derives `<name>.wiki`; a remote code
  source `<name>.git` derives `<name>.wiki.git`. No
  second source is recorded, so a wiki can never
  drift to a different origin than its code.
- No wiki is an honest answer (pure `decide_wiki_sync`
  + `state_from_run`): a source with no wiki — no
  local wiki repository, an unlistable remote wiki,
  or a wiki advertising no refs — records state
  `no_wiki` in plain words, creates nothing, fetches
  nothing, and never reports verified.
- The same cadence, the same credential gate: the
  wiki sync resolves the mirror's S-330 credential
  exactly as the code sync does (a named but unloaded
  secret refuses before any fetch; the token travels
  only through the S-014 fetch seam and recorded
  detail is scrubbed of it). `sync_alongside_code`
  runs the code sync and then the wiki sync as one
  act; `sync_owner_wikis` runs every mirror one owner
  holds, in name order, one outcome never hiding
  another's.
- Verified ref-for-ref, as S-336 verifies code: the
  wiki source's advertised heads and tags (S-014
  ls-remote seam) must stand in the local wiki at the
  same object ids, nothing missing, extra, or
  diverged. A completed fetch that does not verify is
  a failed run. A drifted local wiki path (standing
  but not a bare git repository) is likewise a failed
  run, never silently adopted.
- `status_for` reads the standing facts without
  syncing or creating anything, and
  `render_wiki_mirror_page` states each wiki's state
  in words, never colour-only.

## Deliberate non-changes

No migration and no new audit event: the schema
stands at 138 and the taxonomy stands at 138. This
slice reuses the seams and tables its predecessors
built (S-013 paths, S-014 ls-remote/fetch, S-070
mirror records, S-273 wiki form, S-330 credentials,
S-336 run log and ref comparison), on purpose.
