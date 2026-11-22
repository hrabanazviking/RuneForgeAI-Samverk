# Counted master run (S-393) — the full suite, reported as it is

Executed on the banked tree at 392/416 (base commit
d7940f418b03266157e0f4c7566ca62d54f4b1b8, origin/main verified by
git ls-remote before the run), on purplelongship, 2026-11-22,
with the sharded runner (tools/run_suite_sharded.py --workers 8,
disk-backed TMPDIR per shard). Logs: team-02 hidden_files/
shards-s393/ (per-shard) and hidden_files/s393-runner.log
(aggregate). This run also serves as the wave 381-390 counted
run. Wall: 2445.3s for the slowest shard.

Counted: Ran 6129 / Passed 6110 / Failed 15 / Skipped 4

## Per-shard counts

| Shard | Modules | Ran | Skipped | Failed |
| --- | --- | --- | --- | --- |
| 00 | 50 | 783 | 1 | 2 |
| 01 | 50 | 810 | 0 | 3 |
| 02 | 49 | 796 | 0 | 0 |
| 03 | 49 | 765 | 2 | 3 |
| 04 | 49 | 698 | 1 | 2 |
| 05 | 49 | 727 | 0 | 3 |
| 06 | 49 | 799 | 0 | 2 |
| 07 | 49 | 751 | 0 | 0 |

Shards 02 and 07 ran clean (unittest exit 0, OK in their logs);
the runner's tail-line check marked them FAILED only because a
test's own usage output follows the OK line in those logs. Their
fail counts are 0 and are counted as 0 here.

## Failures — all 15 named

Every failure is the known stale schema/taxonomy-pin class:
fourteen pin tests expect the taxonomy families
{auth: 33, repo: 92, admin: 13} while the tree's taxonomy stands
at {auth: 34, repo: 92, admin: 16}, and one expects 138 audited
verbs while the tree carries 142. No failure is outside this
class; no code defect is indicated by this run. The pins are
reported stale, as they are — not silently rewritten by this
slice, and not hidden.

- tests.test_api_abuse.PinTests.test_schema_and_taxonomy_pins
- tests.test_api_versioning.ApiVersioningTests.test_schema_and_taxonomy_pins
- tests.test_code_scanning.PinsTests.test_webhook_taxonomy_carries_the_new_verb
- tests.test_discussion_answers.AnswerMarkingTests.test_schema_and_taxonomy_stand
- tests.test_discussion_conversion.ConversionTests.test_schema_taxonomy_and_verdict_stand
- tests.test_discussion_polls.DiscussionPollsTests.test_schema_and_taxonomy_pins
- tests.test_discussions.DiscussionTests.test_schema_and_taxonomy_stand
- tests.test_discussions_verdict.DiscussionsVerdictTests.test_schema_and_taxonomy_pins
- tests.test_graphql_verdict.GraphQLVerdictTests.test_schema_and_taxonomy_pins
- tests.test_package_verdict.PackageVerdictTests.test_schema_and_taxonomy_pins
- tests.test_registry_core.RegistryCoreTests.test_schema_and_taxonomy_pins
- tests.test_webhook_delivery_log.PinTests.test_pins_schema_99_taxonomy_133
- tests.test_webhook_ping.PinTests.test_pins_schema_99_taxonomy_133
- tests.test_workflow_format.WorkflowFormatTests.test_schema_and_taxonomy_pins
- tests.test_workflow_jobs.PinsAndAuditTests.test_schema_and_taxonomy_pins

## Skips — all 4 named

- S-095 real-sshd cell (tests.test_transport_battery):
  NOT PROVEN on this host — no sshd binary installed; the cell
  is owned by a host with sshd (Part XXII line).
- S-159 GC environment skip (tests.test_branch_housekeeping):
  the deleted object survived gc --prune=now in this
  environment, so oid_unavailable cannot be exercised here.
- S-292 no-detector-layer guard 1 (tests.test_push_protection):
  a detector layer is present on this base, so the
  no-detector path is not exercised.
- S-292 no-detector-layer guard 2 (tests.test_push_protection):
  same guard, second door — same reason.

## Verdict

The master run is counted and reported as what it is:
6129 ran, 6110 passed, 15 failed (all stale-pin class, named
above), 4 skipped (all named above). It is NOT a 0-failed run
and is not recorded as one. The stale pins stand named as the
honest remainder for the pin-refresh work; nothing in this run
blocks S-394 onward, which bank on battery + neighbours under
the 2026-11-22 banking law.
