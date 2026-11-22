# Metadata import (S-338)

Roadmap S-338: issues, labels, milestones, and releases
imported from GitHub's API into the mirror (where the
owner's credential allows), marked as imported with
source links.

## What stands

- `samverk/metadata_import.py` --
  `MetadataImportService.import_metadata` imports one
  mirror's metadata from the GitHub API of the
  repository its source names (pure
  `parse_github_source`). Milestones land first, then
  labels, issues (with label and milestone linkage),
  and releases, in the mirror's own tables.
- The credential gate is S-337's, reused whole (pure
  `decide_credential` over the S-330 credential seam
  and the S-003 secret store): no credential named,
  an unloaded secret, or an undeclared or non-read
  declared scope refuses the import before any fetch
  is attempted, in plain words, and the refusal is
  recorded as a run -- never a silent skip.
- Marked as imported, with source links: every landed
  item is recorded in `metadata_imports` with its
  kind, source key, source link (the item's GitHub
  `html_url`, or the canonical URL built from the
  source identity), and the local row it landed as.
  `render_metadata_import_page` names each item
  *imported* beside its source link.
- Honest shapes: pull requests served by the issues
  API are counted skipped, never imported as issues;
  malformed items are refused and counted; re-import
  is idempotent (already-imported items counted
  skipped, never duplicated; standing local rows are
  linked, not recreated); GitHub issue numbers are
  preserved when unclaimed and the S-121 shared
  counter is advanced past them.
- The fetch rides one seam (`fetch_fn(url, token)`,
  defaulting to a urllib read of `api.github.com`);
  the token rides the Authorization header only --
  never a URL, never a log.

## Deliberate changes

Migration 139 (schema 138 -> 139) adds exactly the
two provenance tables this slice needs --
`metadata_imports` and `metadata_import_runs` --
because no standing table can hold an imported mark
or a source link. No new audit event: the taxonomy
stands at 138.
