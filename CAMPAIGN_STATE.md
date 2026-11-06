# CAMPAIGN_STATE — team-01
Slice: S-153 (see WAVE_PLAN.md in ~/samverk-forge for title + banking rules)
State: BUILT + TESTED 2026-11-06 — ready for the coordinator to bank.

## What was built
Merge: merge commit — PR title/body as the default message,
editable, closing keywords executed on landing.
New module samverk/pull_request_merge.py (PullRequestMergeStore:
preview_merge / merge_pull_request, default_message, renderers);
migration 58 (pull_request_merges); taxonomy +1
(repo.pull_request.merge, 111 events: 29 auth, 70 repo, 12 admin);
proc.py allowlist +merge-tree; docs/AUDIT_TAXONOMY.md updated;
battery tests/test_pull_request_merge.py (17 tests).

## Counts (read back from the log files)
- Battery + taxonomy: 23 tests OK (17 merge + 6 taxonomy),
  hidden_files/s153-battery.log
- Full suite: Ran 1075 tests — 1070 passed, 1 skipped
  (S-095's named real-sshd cell, the tolerated skip), 0 failed,
  4 errors — hidden_files/s153-fullsuite.log
- The 4 errors are PRE-EXISTING on the pristine S-152 base,
  proven two ways: (1) identical 4 errors with this slice
  stashed whole; (2) team-02's independent full-suite run on
  their own base showed the same 4 errors. Root cause: the
  corruption tests write into git object files, but git
  creates loose objects read-only (mode 444) on this
  machine, so the test's own write gets PermissionError.
  They are NOT caused by S-153 and are recorded here as
  campaign-level next work for the coordinator (the fix
  belongs to those old batteries / the environment, e.g.
  chmod the object writable inside the tests).

## Bug found and fixed in-slice
First battery run caught a real defect: the merge commit
carried the HEAD tree, so a diverged-but-clean merge would
have silently dropped the base side's changes. Fixed: the
plan now captures the tree git merge-tree --write-tree
computes, and the merge commit carries exactly that tree.
Regression test: test_diverged_but_clean_merge_combines_both_sides.

## Team note
Four of six spawned workers (3 builders + tester) died at
spawn on an inference-proxy 429. The designer delivered its
design (hidden_files/s153-design.md, 29,323 bytes,
sha-verified on device); the scout's report, all building,
and all testing were completed by the lead
(hidden_files/s153-scout-lead.md).
