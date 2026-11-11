# Storage accounting (S-268)

S-058 measured a repository's bare directory -- git objects,
LFS objects, and everything else -- and S-068 put a quota on
that number at receive time. Release assets (S-259) and CI
artifacts (S-266) live outside the bare directory, under
`release-assets/` and `ci-artifacts/` in the data root, so
they stood outside both the accounting and the quota. This
slice joins them: `samverk/storage_accounting.py`
(`StorageAccounting`). No migration (schema 105 stands); no
new taxonomy event (133 stand: 33 auth / 87 repo / 13 admin).

## The joined account

One repository's storage is S-058's walk -- read from
`samverk.repo_size.measure_path`, never re-walked here --
plus the release-asset bytes plus the CI-artifact bytes.
The upload stores are counted from their standing rows:
each row's `size` is the measured size `inspect_upload`
proved at promotion (S-012), so every number is measured,
never estimated.

Bytes are content-addressed, and each store is counted at
its own disk layout. CI artifacts share one file per digest
within a repository, so a digest is counted once however
many rows name it. Release assets share one file per digest
within a release, so a digest is counted once per release
that holds it -- the same bytes standing in two releases
are two files on disk and count twice. The report
(`StorageReport`, also `storage_to_dict` and the plain-words
`storage_words` / `render_storage_page`) keeps every
category separate -- git objects, LFS, other, release
assets, artifacts, with standing row counts and shared-file
counts beside the joined stores -- and the categories
always sum to the total.

Standing rows are the account: an artifact past its
retention stamp still counts until S-267's sweep removes
its row and its bytes together, and a deleted asset or
artifact stops counting the moment its row goes. Nothing
is cached; every report reads the walk and the rows as
they stand. Reading is shown to owners and site admins
only (S-058's law): anyone else is refused
`permission_denied`, and reading appends no audit entry.

## S-068-style quotas

The quota is S-068's and no other -- the per-repository
quota wins, the instance default applies next, otherwise
the repository is unlimited, judged by
`QuotaService.effective_quota`; no second quota store
stands here. What this slice adds is the usage judged
against it: `check_upload` / `enforce_upload` judge an
incoming release-asset or artifact upload against the
*joined* total, as a decision object first
(`StorageDecision`, S-068's `ReceiveDecision` shape) and
an exception second (`StorageError` with reason
`quota_exceeded`), with a refusal message that says in
plain numbers how much the repository holds, what its
limit is, and how much the upload tried to add. At the
limit exactly is allowed; one byte over is refused. The
report also states the quota, the headroom left under it
(never negative), and whether the repository already
stands over quota.

S-068's own receive-time gate is untouched -- it still
guards pushes with the S-058 number it has always used.
Per-user and per-repo quota surfaces are S-354.
