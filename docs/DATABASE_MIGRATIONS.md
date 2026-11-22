# Database migrations (S-358)

Roadmap S-358: numbered, transactional where SQLite allows,
each with a down-path or an explicit one-way warning.

## The law, and where it lives

- **Numbered, in order.** `samverk/db.py` `MIGRATIONS` is
  numbered 1..139 with no gaps; `migrate()` applies pending
  migrations in number order and stamps `schema_meta` with
  each landed version. Append-only: never edit a shipped
  migration; add the next number.
- **Transactional.** Each migration lands in ONE transaction
  via `db.apply_migration` over `db.migration_transaction` —
  a SAVEPOINT, deliberately not `with conn:`. Python's sqlite3
  only opens an implicit transaction before DML, so a
  DDL-first migration under `with conn:` autocommitted its
  CREATE TABLE before a later statement could fail, leaving a
  half-migrated database at the old version stamp. The S-358
  battery caught that bug in the standing machinery and this
  slice fixed it: a rehearsed failing migration on a scratch
  database now leaves schema version AND content exactly at
  the prior state, partial DDL included. SQLite makes DDL
  transactional, and the savepoint makes the transaction real.
- **Down-path or one-way warning, for every migration.**
  `samverk/database_migrations.py` `REGISTER` carries one
  entry per standing migration: what it does, and either a
  down-path or an explicit one-way warning — never neither,
  never both, judged purely by `validate_register`.

## The honest register: all 139 are one-way

No shipped migration carried a down-path, and this slice does
not invent any: a written-after-the-fact "down" for a CREATE
TABLE migration means dropping the table and every row written
into it since, which is data destruction dressed as a feature.
So every standing entry is marked one-way, and every warning
says the same plain thing in so many words: there is no safe
automatic way back; the way back is to restore a backup of the
database taken before upgrading past that version.

The machinery is not one-way-only. Where a future migration's
author can honestly write a down-path, the entry carries
`down_statements` instead of a warning and `apply_down` runs
them plus the version re-stamp in the same savepoint
transaction. The battery round-trips a rehearsed reversible
migration (up to a scratch 140, back down to 139) to prove
that road, and proves a failing down-path also rolls back
whole. `apply_down` on a one-way entry refuses by name and
leaves the database untouched.

## The operator surface

Before upgrading, read the warnings the upgrade would cross:

    python3 -m samverk migrations warnings --from-version 138
    python3 -m samverk migrations check

`warnings` prints, in plain words, every one-way migration
above the given version with its warning and the standing
instruction: take a backup first; restoring it is the only
way back. `check` validates the register against `MIGRATIONS`
and reports the count (139 migrations, numbered 1..139, 139
one-way, 0 reversible at this slice).

## No migration of this slice's own

The schema stands at 139 and the taxonomy stands at 138.
This slice changed the machinery around migrations, not the
schema.

## The register (generated from `REGISTER`)

| Version | What it does | Reversible? |
|---|---|---|
| 1 | creates table schema_meta; creates table settings | no — one-way, see warning |
| 2 | creates table sessions; creates index idx_sessions_user | no — one-way, see warning |
| 3 | creates table audit_log | no — one-way, see warning |
| 4 | creates table users | no — one-way, see warning |
| 5 | creates table email_verification_tokens; creates index idx_email_verification_user | no — one-way, see warning |
| 6 | creates table password_reset_tokens; creates index idx_password_reset_user | no — one-way, see warning |
| 7 | creates table profiles | no — one-way, see warning |
| 8 | creates table ssh_keys; creates index idx_ssh_keys_user | no — one-way, see warning |
| 9 | creates table deploy_keys; creates index idx_deploy_keys_repo | no — one-way, see warning |
| 10 | creates table access_tokens; creates index idx_access_tokens_user | no — one-way, see warning |
| 11 | creates table fine_grained_tokens; creates index idx_fine_tokens_user; creates index idx_fine_tokens_repo | no — one-way, see warning |
| 12 | creates table totp_credentials | no — one-way, see warning |
| 13 | creates table sudo_grants | no — one-way, see warning |
| 14 | creates table recovery_codes; creates index idx_recovery_codes_user | no — one-way, see warning |
| 15 | creates table passkey_challenges; creates table passkey_credentials; creates index idx_passkey_credentials_user | no — one-way, see warning |
| 16 | alters table sessions | no — one-way, see warning |
| 17 | creates table known_devices; creates table signin_notifications; creates index idx_signin_notifications_user | no — one-way, see warning |
| 18 | creates table username_tombstones | no — one-way, see warning |
| 19 | creates table account_deletions | no — one-way, see warning |
| 20 | creates table account_suspensions; creates index idx_suspensions_user | no — one-way, see warning |
| 21 | creates table external_identities; creates index idx_external_identities_user | no — one-way, see warning |
| 22 | creates table repositories; creates index idx_repositories_owner | no — one-way, see warning |
| 23 | alters table repositories; creates index idx_repositories_fork_of | no — one-way, see warning |
| 24 | creates table repo_deletions | no — one-way, see warning |
| 25 | creates table repo_transfers; creates table repo_redirects | no — one-way, see warning |
| 26 | creates table repo_gc_state | no — one-way, see warning |
| 27 | creates table lfs_locks; creates index idx_lfs_locks_repo | no — one-way, see warning |
| 28 | alters table repositories | no — one-way, see warning |
| 29 | creates table repo_settings; creates table repo_branch_renames | no — one-way, see warning |
| 30 | creates table repo_quotas | no — one-way, see warning |
| 31 | creates table repo_mirrors | no — one-way, see warning |
| 32 | creates table repo_graph_cache | no — one-way, see warning |
| 33 | creates table push_events; creates index push_events_repo_idx | no — one-way, see warning |
| 34 | creates table repo_counters; creates table issues; creates index idx_issues_repo; creates index idx_issues_repo_state | no — one-way, see warning |
| 35 | creates table issue_comments; creates index idx_issue_comments_issue; creates table issue_comment_edits; creates index idx_issue_comment_edits_comment | no — one-way, see warning |
| 36 | creates table labels; creates index idx_labels_repo; creates table issue_labels; creates index idx_issue_labels_label | no — one-way, see warning |
| 37 | creates table milestones; creates index idx_milestones_repo; alters table issues; creates index idx_issues_milestone | no — one-way, see warning |
| 38 | creates table issue_assignees; creates index idx_issue_assignees_user | no — one-way, see warning |
| 39 | creates table cross_references; creates index idx_xrefs_target; creates index idx_xrefs_target_sha; creates index idx_xrefs_source | no — one-way, see warning |
| 40 | creates table reactions; creates index idx_reactions_target | no — one-way, see warning |
| 41 | creates table issue_templates; creates index idx_issue_templates_repo; creates table repo_issue_options | no — one-way, see warning |
| 42 | alters table issues; creates table issue_events; creates index idx_issue_events_issue | no — one-way, see warning |
| 43 | alters table issues; creates table issue_pins; creates index idx_issue_pins_repo | no — one-way, see warning |
| 44 | creates table issue_transfers; creates index idx_issue_transfers_dest | no — one-way, see warning |
| 45 | creates table saved_filters; creates index idx_saved_filters_user | no — one-way, see warning |
| 46 | creates table pull_requests; creates index idx_pull_requests_repo | no — one-way, see warning |
| 47 | alters table issue_comments | no — one-way, see warning |
| 48 | creates table issue_event_outbox; creates index idx_issue_event_outbox_repo | no — one-way, see warning |
| 49 | creates table pull_request_forks; creates index idx_pull_request_forks_head | no — one-way, see warning |
| 50 | creates table pull_request_file_views; creates index idx_pr_file_views_pr_user | no — one-way, see warning |
| 51 | creates table pull_request_line_comments; creates index idx_pr_line_comments_pr; creates table pull_request_line_comment_edits; creates index idx_pr_line_comment_edits_comment | no — one-way, see warning |
| 52 | creates table pull_request_review_threads; creates table pull_request_line_replies; creates index idx_pr_line_replies_comment; creates table pull_request_line_reply_edits; creates index idx_pr_line_reply_edits_reply | no — one-way, see warning |
| 53 | creates table pull_request_reviews; creates index idx_pr_reviews_pr; creates table pull_request_pending_reviews | no — one-way, see warning |
| 54 | creates table repo_review_freshness_policies | no — one-way, see warning |
| 55 | creates table pull_request_suggestions; creates index idx_pr_suggestions_pr | no — one-way, see warning |
| 56 | creates table pull_request_review_requests; creates index idx_pr_review_requests_pr | no — one-way, see warning |
| 57 | alters table pull_request_review_requests; creates table pull_request_review_request_events; creates index idx_pr_review_request_events_request | no — one-way, see warning |
| 58 | creates table pull_request_merges; creates index idx_pr_merges_repo | no — one-way, see warning |
| 59 | creates table pull_request_merges_unified; inserts into pull_request_merges_unified; drops table pull_request_merges; alters table pull_request_merges_unified; creates index idx_pr_merges_repo; creates table pull_request_merge_closings; creates index idx_pr_merge_closings_pr | no — one-way, see warning |
| 60 | creates table commit_checks; creates index idx_commit_checks_repo_head | no — one-way, see warning |
| 61 | creates table pull_request_auto_merges; creates index idx_pr_auto_merges_repo; creates table pull_request_auto_merge_events; creates index idx_pr_auto_merge_events_pr | no — one-way, see warning |
| 62 | alters table repo_settings; creates table deleted_branches; creates index idx_deleted_branches_repo; creates index idx_deleted_branches_pr | no — one-way, see warning |
| 63 | creates table pull_request_reverts; creates index idx_pr_reverts_original | no — one-way, see warning |
| 64 | creates table pull_request_review_notifications; creates index idx_pr_review_notifications_recipient; creates index idx_pr_review_notifications_pr | no — one-way, see warning |
| 65 | creates table protection_rules; creates index idx_protection_rules_repo | no — one-way, see warning |
| 66 | alters table protection_rules | no — one-way, see warning |
| 67 | creates table protection_rulesets; creates index idx_protection_rulesets_name | no — one-way, see warning |
| 68 | creates table organizations; creates index idx_organizations_name | no — one-way, see warning |
| 69 | creates table organization_members; creates index idx_organization_members_org | no — one-way, see warning |
| 70 | creates table teams; creates index idx_teams_org; creates table team_members; creates index idx_team_members_team; creates table team_repositories; creates index idx_team_repositories_team; creates index idx_team_repositories_repo | no — one-way, see warning |
| 71 | alters table teams; creates index idx_teams_parent | no — one-way, see warning |
| 72 | alters table team_repositories | no — one-way, see warning |
| 73 | creates table outside_collaborators; creates index idx_outside_collaborators_repo; creates index idx_outside_collaborators_user | no — one-way, see warning |
| 74 | creates table org_default_permissions | no — one-way, see warning |
| 75 | creates table org_invitations; creates index idx_org_invitations_org; creates index idx_org_invitations_user; creates index idx_org_invitations_email | no — one-way, see warning |
| 76 | creates table team_mention_notifications; creates index idx_team_mentions_recipient; creates index idx_team_mentions_item; creates index idx_team_mentions_team | no — one-way, see warning |
| 77 | creates table org_repo_policies | no — one-way, see warning |
| 78 | creates table org_deletions | no — one-way, see warning |
| 79 | creates table instance_groups; creates table instance_group_members; creates index idx_instance_group_members_group; creates index idx_instance_group_members_user; creates table instance_group_repositories; creates index idx_instance_group_repos_group; creates index idx_instance_group_repos_repo | no — one-way, see warning |
| 80 | creates table index_jobs; creates index idx_index_jobs_pending; creates index idx_index_jobs_repo; creates table index_state; creates table index_documents; creates index idx_index_documents_repo | no — one-way, see warning |
| 81 | CREATE VIRTUAL TABLE issue_pr_fts USING fts5( title, body, r | no — one-way, see warning |
| 82 | CREATE VIRTUAL TABLE code_fts USING fts5( path, text, repo_i | no — one-way, see warning |
| 83 | creates table recent_searches; creates index idx_recent_searches_user_query; creates index idx_recent_searches_user_recent | no — one-way, see warning |
| 84 | creates table saved_searches; creates index idx_saved_searches_user | no — one-way, see warning |
| 85 | creates table events; creates index idx_events_actor; creates index idx_events_verb | no — one-way, see warning |
| 86 | creates table repo_watches; creates index idx_repo_watches_repo; creates table repo_stars; creates index idx_repo_stars_repo; creates index idx_repo_stars_user | no — one-way, see warning |
| 87 | creates table notifications; creates index idx_notifications_recipient; creates index idx_notifications_reason | no — one-way, see warning |
| 88 | creates table inbox_triage; creates index idx_inbox_triage_saved | no — one-way, see warning |
| 89 | creates table thread_overrides; creates index idx_thread_overrides_user; creates index idx_thread_overrides_repo | no — one-way, see warning |
| 90 | creates table mention_deliveries; creates index idx_mention_deliveries_recipient; creates index idx_mention_deliveries_item | no — one-way, see warning |
| 91 | creates table email_deliveries; creates index idx_email_deliveries_recipient; creates index idx_email_deliveries_status; creates table email_optouts; creates index idx_email_optouts_user | no — one-way, see warning |
| 92 | creates table notification_preferences | no — one-way, see warning |
| 93 | creates table user_follows; creates index idx_user_follows_followed; creates index idx_user_follows_follower | no — one-way, see warning |
| 94 | creates table weekly_digests; creates index idx_weekly_digests_user; creates index idx_weekly_digests_status | no — one-way, see warning |
| 95 | alters table commit_checks; creates table check_runs; creates index idx_check_runs_repo_head | no — one-way, see warning |
| 96 | creates table webhooks; creates index idx_webhooks_repo; creates index idx_webhooks_org | no — one-way, see warning |
| 97 | creates table webhook_deliveries; creates index idx_webhook_deliveries_once; creates index idx_webhook_deliveries_due; creates index idx_webhook_deliveries_hook; creates table webhook_delivery_attempts; creates index idx_webhook_delivery_attempts_delivery | no — one-way, see warning |
| 98 | alters table webhook_deliveries; DROP INDEX idx_webhook_deliveries_once; creates index idx_webhook_deliveries_once; creates index idx_webhook_deliveries_redelivery | no — one-way, see warning |
| 99 | creates table webhook_pings; creates index idx_webhook_pings_hook; creates index idx_webhook_pings_delivery | no — one-way, see warning |
| 100 | creates table releases; creates index idx_releases_repo | no — one-way, see warning |
| 101 | alters table releases | no — one-way, see warning |
| 102 | creates table release_assets; creates index idx_release_assets_release; creates table release_upload_sessions | no — one-way, see warning |
| 103 | creates table release_notification_deliveries; creates index idx_release_notif_deliv_recipient; creates index idx_release_notif_deliv_release | no — one-way, see warning |
| 104 | creates table release_signatures; creates index idx_release_signatures_release | no — one-way, see warning |
| 105 | creates table ci_artifacts; creates index idx_ci_artifacts_repo_head; creates index idx_ci_artifacts_run; creates index idx_ci_artifacts_expiry; creates table ci_artifact_upload_sessions | no — one-way, see warning |
| 106 | creates table release_tag_automation | no — one-way, see warning |
| 107 | creates table wiki_access_policies | no — one-way, see warning |
| 108 | creates table gists; creates index idx_gists_owner | no — one-way, see warning |
| 109 | alters table gists | no — one-way, see warning |
| 110 | alters table gists; creates index idx_gists_fork_of; creates table gist_stars; creates index idx_gist_stars_gist; creates index idx_gist_stars_user | no — one-way, see warning |
| 111 | creates table gist_comments; creates index idx_gist_comments_gist; creates table gist_comment_edits; creates index idx_gist_comment_edits_comment | no — one-way, see warning |
| 112 | creates table discussion_categories; creates index idx_discussion_categories_repo; creates table discussion_threads; creates index idx_discussion_threads_repo; creates index idx_discussion_threads_category; creates table discussion_counters; creates table discussion_replies; creates index idx_discussion_replies_thread; creates table discussion_reply_edits; creates index idx_discussion_reply_edits_reply; creates table discussion_events; creates index idx_discussion_events_thread | no — one-way, see warning |
| 113 | alters table discussion_threads | no — one-way, see warning |
| 114 | creates table discussion_conversions; creates index idx_discussion_conversions_repo | no — one-way, see warning |
| 115 | creates table push_scans; creates index idx_push_scans_repo; creates table push_scan_updates; creates index idx_push_scan_updates_scan; creates table secret_alerts; creates index idx_secret_alerts_repo; creates index idx_secret_alerts_scan | no — one-way, see warning |
| 116 | creates table push_protection_bypasses; creates index idx_push_protection_bypasses_repo | no — one-way, see warning |
| 117 | alters table secret_alerts; creates table secret_alert_events; creates index idx_secret_alert_events_alert; creates index idx_secret_alert_events_repo | no — one-way, see warning |
| 118 | creates table custom_patterns; creates index idx_custom_patterns_scope; creates table custom_pattern_dry_runs; creates index idx_custom_pattern_dry_runs_pattern; creates table custom_pattern_dry_run_matches; creates index idx_custom_pattern_dry_run_matches_run | no — one-way, see warning |
| 119 | alters table secret_alerts; creates table secret_validity_checks; creates index idx_secret_validity_checks_alert; creates index idx_secret_validity_checks_repo | no — one-way, see warning |
| 120 | creates table dependency_graph_states; creates table dependency_manifests; creates index idx_dependency_manifests_repo; creates table repo_dependencies; creates index idx_repo_dependencies_repo; creates index idx_repo_dependencies_name | no — one-way, see warning |
| 121 | creates table dependency_alerts; creates index idx_dependency_alerts_repo; creates index idx_dependency_alerts_advisory; creates table dependency_alert_events; creates index idx_dependency_alert_events_alert; creates index idx_dependency_alert_events_repo | no — one-way, see warning |
| 122 | creates table advisory_snapshot_state; creates table advisory_refreshes; creates index idx_advisory_refreshes_id | no — one-way, see warning |
| 123 | creates table code_scanning_uploads; creates index idx_code_scanning_uploads_repo_commit; creates index idx_code_scanning_uploads_repo | no — one-way, see warning |
| 124 | creates table code_scanning_alerts; creates index idx_code_scanning_alerts_repo_branch; creates table code_scanning_branch_heads | no — one-way, see warning |
| 125 | alters table code_scanning_alerts; creates table code_scanning_alert_events; creates index idx_code_scanning_alert_events_alert; creates index idx_code_scanning_alert_events_repo | no — one-way, see warning |
| 126 | creates table signing_keys; creates index idx_signing_keys_kind_fingerprint; creates index idx_signing_keys_user; creates table commit_verifications; creates index idx_commit_verifications_repo_oid | no — one-way, see warning |
| 127 | creates table vigil_settings; creates index idx_vigil_settings_user | no — one-way, see warning |
| 128 | creates table security_advisories; creates index idx_security_advisories_key; creates index idx_security_advisories_repo; creates table security_advisory_alerts; creates index idx_security_advisory_alerts_adv; creates table security_advisory_events; creates index idx_security_advisory_events_adv; creates index idx_security_advisory_events_repo | no — one-way, see warning |
| 129 | creates table runner_registration_tokens; creates index idx_runner_tokens_hash; creates index idx_runner_tokens_scope; creates table runners; creates index idx_runners_scope | no — one-way, see warning |
| 130 | creates table ci_secrets; creates index idx_ci_secrets_scope_name; creates index idx_ci_secrets_scope | no — one-way, see warning |
| 131 | creates table ci_logs; creates index idx_ci_logs_repo_run; creates index idx_ci_logs_expiry | no — one-way, see warning |
| 132 | creates table ci_run_actions; creates index idx_ci_run_actions_repo_run | no — one-way, see warning |
| 133 | alters table repo_mirrors | no — one-way, see warning |
| 134 | alters table repo_mirrors | no — one-way, see warning |
| 135 | alters table repo_mirrors | no — one-way, see warning |
| 136 | creates table repo_push_mirrors | no — one-way, see warning |
| 137 | creates table census_fixture_entries | no — one-way, see warning |
| 138 | creates table first_pass_mirror_runs | no — one-way, see warning |
| 139 | creates table metadata_imports; creates table metadata_import_runs | no — one-way, see warning |

Every one-way warning reads, in full for migration N: "ONE-WAY:
migration N shipped without a down-path (<what it does>). There
is no safe automatic way back: reversing it would mean dropping
or undoing the objects above and any data written into them
since. The way back is to restore a backup of the database
taken before upgrading past version N." The exact per-migration
text is in `REGISTER` and is what
`samverk migrations warnings` prints.
