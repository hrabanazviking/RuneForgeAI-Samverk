# CAMPAIGN_STATE — team-05
Slice: S-157 — Checks panel: external status/check results listed on the PR with links; pending/failed/passed are text+icon, never colour-only.
State: BUILT 2026-11-06 — committed on branch yrsa/samverk-team-05, awaiting coordinator banking (teams do not push or merge).

What landed:
- samverk/pull_request_checks.py (new): PullRequestChecksStore + PullRequestCheck + render_pull_request_check / render_pull_request_checks. One row per (repository, head commit, context); a re-report updates the row, never duplicates it. States are only the roadmap's three words (pending / failed / passed); foreign words are refused whole. Target links must be absolute http/https and pass the S-010 sanitiser. Everything renders escaped.
- Migration 58: commit_checks table + idx_commit_checks_repo_head. Schema-version assertions bumped 57 -> 58 in tests/test_pull_request_codeowners.py, tests/test_pull_request_review_assignment.py, tests/test_pull_request_suggestions.py.
- tests/test_pull_request_checks.py (new): 16 tests.
- No audit events added (taxonomy stays 110): recording is the storage seam; the poster's scoped identity and audit row are S-246's law.

Counts (read from the logs in hidden_files/):
- S-157 battery: 16 tests, OK (s157-battery.log).
- Affected suites (codeowners, review assignment, suggestions, pull requests, forks, taxonomy): 72 tests, OK (s157-affected.log).
- Full suite: Ran 1074 — 1069 passed, 1 skipped (S-095 real-sshd, tolerated), 4 errors (s157-fullsuite.log).

Known issue (pre-existing, NOT caused by S-157 — for the coordinator):
- 4 errors in tests that overwrite read-only git object files to fake corruption: test_repo_health (2), test_git_http_advertise (1), test_git_core_battery (1) — PermissionError writing loose objects, which git stores mode 0444 on this laptop. Proven pre-existing by control run: the same three modules against a stashed pristine pre-S-157 tree produce the identical 4 errors (s157-baseline-errcheck.log). The banking environment evidently runs them green (S-152 recorded 1057 passed / 0 failed) and nothing in S-157 touches those modules. A fix belongs to those batteries or the environment (e.g. chmod before overwrite), outside this slice's files.

Bug found and fixed inside the slice:
- First battery run was 15/16: a relative target link passed validation because the S-010 safe_url also allows relative references. Tightened: check links must be absolute http/https AND pass safe_url. Battery then 16/16.

Crew note: the six spawned Mythic Engineering workers all errored at spawn (inference-proxy 429 — 60 agents launching at once); the team lead built the slice directly and sequentially.
