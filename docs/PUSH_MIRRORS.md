# Push mirrors (S-333)

Samverk mirrors its own repos **onward** — to a second machine's
Samverk or to a plain git remote — with the same status honesty
S-332 gave pull syncing.

## The shape

- A repository names **push targets** in `repo_push_mirrors`
  (migration 136, schema 135 → 136). A target is either a remote
  URL validated by S-014's seam (credentials inside a URL are
  refused there, so a stored target can never hold a secret) or
  an absolute local path naming an existing repository
  directory on this instance's disk.
- Only the repository's owner adds or removes targets (S-070's
  owner law for mirror records). Naming a target pushes
  nothing; the first push is its own act.
- A push runs through the dedicated seam `run_git_push_to`
  in `samverk/proc.py` — every head and tag, pruned, so the
  target converges to this repository — and its outcome is
  recorded, never hidden, exactly as S-070 records a fetch.

## Status honesty

Each target record carries `last_attempt_at`,
`last_success_at` (moved by successes only), `last_status`,
`last_detail`, and `last_objects_moved` — the objects the
attempt carried into the target, counted around the push when
the target is a local repository. For a remote URL target the
count cannot be read back, so it is recorded as *not recorded*,
never guessed.

A target is **healthy only when its last attempt succeeded**.
A failed push never looks healthy, however well an older push
went; the failure reason is spoken in plain words beside the
raw recorded detail (`plain_push_failure_reason` in
`samverk/push_mirrors.py`), and the repo page renders every
target's state in words, never colour-only.

## Taxonomy

S-333 added no audit event: 138 stand. A push outcome is
product data in the target record — the state the repo page
reads — exactly as S-070/S-332 kept sync outcomes.
