"""Database migrations register (S-358).

Roadmap S-358: **numbered, transactional where SQLite allows,
each with a down-path or an explicit one-way warning.**

What already stood in ``samverk/db.py`` and still stands:
``MIGRATIONS`` is numbered 1..140 with no gaps, applied in
order by ``migrate()``, and each migration runs in its own
transaction (``apply_migration``) so a failure rolls the whole
migration back and leaves the prior schema version stamped.

What this slice adds is the honest register and its proofs:

- ``REGISTER`` carries one entry for EVERY standing migration.
  Each entry names what the migration does and carries either
  a down-path (``down_statements``) or an explicit one-way
  warning — never neither, never both. The standing truth is
  that all 140 shipped migrations are one-way: none shipped
  with a down-path, and inventing one now would mean dropping
  tables and the data written into them since. Each warning
  says so in plain words and names the real way back: restore
  a backup taken before upgrading past that version. That
  honesty is the deliverable, not a defect.
- The machinery still supports real down-paths where one is
  honestly writable: ``apply_down`` runs an entry's down
  statements and the version re-stamp in one transaction, and
  refuses — by name, leaving the database untouched — for a
  one-way entry. The battery round-trips a rehearsed
  reversible migration on a scratch database to prove it.
- ``validate_register`` is the pure judgement: register
  against a migration list, every gap, duplicate, stray,
  both-ways or neither-way entry named. An empty list is the
  only pass.
- ``render_upgrade_warnings`` is the operator surface in pure
  form: the plain-words warnings for every one-way migration
  above a given version, printed by
  ``samverk migrations warnings`` before an upgrade.

No migration of this slice's own: the schema stands at 140
and the taxonomy stands at 142 (coordinator pin sweep at
S-358 banking: S-355 landed migration 140 and four taxonomy
events after this slice was built; entry 140 was added to
the register by the same sweep).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .db import MIGRATIONS, migration_transaction, schema_version


class MigrationRegisterError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class MigrationEntry:
    version: int
    summary: str
    down_statements: tuple[str, ...] | None
    one_way_warning: str | None

    @property
    def reversible(self) -> bool:
        return self.down_statements is not None


REGISTER: tuple[MigrationEntry, ...] = (
    MigrationEntry(1, "creates table schema_meta; creates table settings", None,
        "ONE-WAY: migration 1 shipped without a down-path (creates table schema_meta; creates table settings). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 1."),
    MigrationEntry(2, "creates table sessions; creates index idx_sessions_user", None,
        "ONE-WAY: migration 2 shipped without a down-path (creates table sessions; creates index idx_sessions_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 2."),
    MigrationEntry(3, "creates table audit_log", None,
        "ONE-WAY: migration 3 shipped without a down-path (creates table audit_log). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 3."),
    MigrationEntry(4, "creates table users", None,
        "ONE-WAY: migration 4 shipped without a down-path (creates table users). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 4."),
    MigrationEntry(5, "creates table email_verification_tokens; creates index idx_email_verification_user", None,
        "ONE-WAY: migration 5 shipped without a down-path (creates table email_verification_tokens; creates index idx_email_verification_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 5."),
    MigrationEntry(6, "creates table password_reset_tokens; creates index idx_password_reset_user", None,
        "ONE-WAY: migration 6 shipped without a down-path (creates table password_reset_tokens; creates index idx_password_reset_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 6."),
    MigrationEntry(7, "creates table profiles", None,
        "ONE-WAY: migration 7 shipped without a down-path (creates table profiles). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 7."),
    MigrationEntry(8, "creates table ssh_keys; creates index idx_ssh_keys_user", None,
        "ONE-WAY: migration 8 shipped without a down-path (creates table ssh_keys; creates index idx_ssh_keys_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 8."),
    MigrationEntry(9, "creates table deploy_keys; creates index idx_deploy_keys_repo", None,
        "ONE-WAY: migration 9 shipped without a down-path (creates table deploy_keys; creates index idx_deploy_keys_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 9."),
    MigrationEntry(10, "creates table access_tokens; creates index idx_access_tokens_user", None,
        "ONE-WAY: migration 10 shipped without a down-path (creates table access_tokens; creates index idx_access_tokens_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 10."),
    MigrationEntry(11, "creates table fine_grained_tokens; creates index idx_fine_tokens_user; creates index idx_fine_tokens_repo", None,
        "ONE-WAY: migration 11 shipped without a down-path (creates table fine_grained_tokens; creates index idx_fine_tokens_user; creates index idx_fine_tokens_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 11."),
    MigrationEntry(12, "creates table totp_credentials", None,
        "ONE-WAY: migration 12 shipped without a down-path (creates table totp_credentials). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 12."),
    MigrationEntry(13, "creates table sudo_grants", None,
        "ONE-WAY: migration 13 shipped without a down-path (creates table sudo_grants). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 13."),
    MigrationEntry(14, "creates table recovery_codes; creates index idx_recovery_codes_user", None,
        "ONE-WAY: migration 14 shipped without a down-path (creates table recovery_codes; creates index idx_recovery_codes_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 14."),
    MigrationEntry(15, "creates table passkey_challenges; creates table passkey_credentials; creates index idx_passkey_credentials_user", None,
        "ONE-WAY: migration 15 shipped without a down-path (creates table passkey_challenges; creates table passkey_credentials; creates index idx_passkey_credentials_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 15."),
    MigrationEntry(16, "alters table sessions", None,
        "ONE-WAY: migration 16 shipped without a down-path (alters table sessions). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 16."),
    MigrationEntry(17, "creates table known_devices; creates table signin_notifications; creates index idx_signin_notifications_user", None,
        "ONE-WAY: migration 17 shipped without a down-path (creates table known_devices; creates table signin_notifications; creates index idx_signin_notifications_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 17."),
    MigrationEntry(18, "creates table username_tombstones", None,
        "ONE-WAY: migration 18 shipped without a down-path (creates table username_tombstones). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 18."),
    MigrationEntry(19, "creates table account_deletions", None,
        "ONE-WAY: migration 19 shipped without a down-path (creates table account_deletions). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 19."),
    MigrationEntry(20, "creates table account_suspensions; creates index idx_suspensions_user", None,
        "ONE-WAY: migration 20 shipped without a down-path (creates table account_suspensions; creates index idx_suspensions_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 20."),
    MigrationEntry(21, "creates table external_identities; creates index idx_external_identities_user", None,
        "ONE-WAY: migration 21 shipped without a down-path (creates table external_identities; creates index idx_external_identities_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 21."),
    MigrationEntry(22, "creates table repositories; creates index idx_repositories_owner", None,
        "ONE-WAY: migration 22 shipped without a down-path (creates table repositories; creates index idx_repositories_owner). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 22."),
    MigrationEntry(23, "alters table repositories; creates index idx_repositories_fork_of", None,
        "ONE-WAY: migration 23 shipped without a down-path (alters table repositories; creates index idx_repositories_fork_of). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 23."),
    MigrationEntry(24, "creates table repo_deletions", None,
        "ONE-WAY: migration 24 shipped without a down-path (creates table repo_deletions). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 24."),
    MigrationEntry(25, "creates table repo_transfers; creates table repo_redirects", None,
        "ONE-WAY: migration 25 shipped without a down-path (creates table repo_transfers; creates table repo_redirects). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 25."),
    MigrationEntry(26, "creates table repo_gc_state", None,
        "ONE-WAY: migration 26 shipped without a down-path (creates table repo_gc_state). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 26."),
    MigrationEntry(27, "creates table lfs_locks; creates index idx_lfs_locks_repo", None,
        "ONE-WAY: migration 27 shipped without a down-path (creates table lfs_locks; creates index idx_lfs_locks_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 27."),
    MigrationEntry(28, "alters table repositories", None,
        "ONE-WAY: migration 28 shipped without a down-path (alters table repositories). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 28."),
    MigrationEntry(29, "creates table repo_settings; creates table repo_branch_renames", None,
        "ONE-WAY: migration 29 shipped without a down-path (creates table repo_settings; creates table repo_branch_renames). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 29."),
    MigrationEntry(30, "creates table repo_quotas", None,
        "ONE-WAY: migration 30 shipped without a down-path (creates table repo_quotas). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 30."),
    MigrationEntry(31, "creates table repo_mirrors", None,
        "ONE-WAY: migration 31 shipped without a down-path (creates table repo_mirrors). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 31."),
    MigrationEntry(32, "creates table repo_graph_cache", None,
        "ONE-WAY: migration 32 shipped without a down-path (creates table repo_graph_cache). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 32."),
    MigrationEntry(33, "creates table push_events; creates index push_events_repo_idx", None,
        "ONE-WAY: migration 33 shipped without a down-path (creates table push_events; creates index push_events_repo_idx). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 33."),
    MigrationEntry(34, "creates table repo_counters; creates table issues; creates index idx_issues_repo; creates index idx_issues_repo_state", None,
        "ONE-WAY: migration 34 shipped without a down-path (creates table repo_counters; creates table issues; creates index idx_issues_repo; creates index idx_issues_repo_state). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 34."),
    MigrationEntry(35, "creates table issue_comments; creates index idx_issue_comments_issue; creates table issue_comment_edits; creates index idx_issue_comment_edits_comment", None,
        "ONE-WAY: migration 35 shipped without a down-path (creates table issue_comments; creates index idx_issue_comments_issue; creates table issue_comment_edits; creates index idx_issue_comment_edits_comment). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 35."),
    MigrationEntry(36, "creates table labels; creates index idx_labels_repo; creates table issue_labels; creates index idx_issue_labels_label", None,
        "ONE-WAY: migration 36 shipped without a down-path (creates table labels; creates index idx_labels_repo; creates table issue_labels; creates index idx_issue_labels_label). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 36."),
    MigrationEntry(37, "creates table milestones; creates index idx_milestones_repo; alters table issues; creates index idx_issues_milestone", None,
        "ONE-WAY: migration 37 shipped without a down-path (creates table milestones; creates index idx_milestones_repo; alters table issues; creates index idx_issues_milestone). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 37."),
    MigrationEntry(38, "creates table issue_assignees; creates index idx_issue_assignees_user", None,
        "ONE-WAY: migration 38 shipped without a down-path (creates table issue_assignees; creates index idx_issue_assignees_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 38."),
    MigrationEntry(39, "creates table cross_references; creates index idx_xrefs_target; creates index idx_xrefs_target_sha; creates index idx_xrefs_source", None,
        "ONE-WAY: migration 39 shipped without a down-path (creates table cross_references; creates index idx_xrefs_target; creates index idx_xrefs_target_sha; creates index idx_xrefs_source). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 39."),
    MigrationEntry(40, "creates table reactions; creates index idx_reactions_target", None,
        "ONE-WAY: migration 40 shipped without a down-path (creates table reactions; creates index idx_reactions_target). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 40."),
    MigrationEntry(41, "creates table issue_templates; creates index idx_issue_templates_repo; creates table repo_issue_options", None,
        "ONE-WAY: migration 41 shipped without a down-path (creates table issue_templates; creates index idx_issue_templates_repo; creates table repo_issue_options). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 41."),
    MigrationEntry(42, "alters table issues; creates table issue_events; creates index idx_issue_events_issue", None,
        "ONE-WAY: migration 42 shipped without a down-path (alters table issues; creates table issue_events; creates index idx_issue_events_issue). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 42."),
    MigrationEntry(43, "alters table issues; creates table issue_pins; creates index idx_issue_pins_repo", None,
        "ONE-WAY: migration 43 shipped without a down-path (alters table issues; creates table issue_pins; creates index idx_issue_pins_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 43."),
    MigrationEntry(44, "creates table issue_transfers; creates index idx_issue_transfers_dest", None,
        "ONE-WAY: migration 44 shipped without a down-path (creates table issue_transfers; creates index idx_issue_transfers_dest). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 44."),
    MigrationEntry(45, "creates table saved_filters; creates index idx_saved_filters_user", None,
        "ONE-WAY: migration 45 shipped without a down-path (creates table saved_filters; creates index idx_saved_filters_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 45."),
    MigrationEntry(46, "creates table pull_requests; creates index idx_pull_requests_repo", None,
        "ONE-WAY: migration 46 shipped without a down-path (creates table pull_requests; creates index idx_pull_requests_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 46."),
    MigrationEntry(47, "alters table issue_comments", None,
        "ONE-WAY: migration 47 shipped without a down-path (alters table issue_comments). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 47."),
    MigrationEntry(48, "creates table issue_event_outbox; creates index idx_issue_event_outbox_repo", None,
        "ONE-WAY: migration 48 shipped without a down-path (creates table issue_event_outbox; creates index idx_issue_event_outbox_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 48."),
    MigrationEntry(49, "creates table pull_request_forks; creates index idx_pull_request_forks_head", None,
        "ONE-WAY: migration 49 shipped without a down-path (creates table pull_request_forks; creates index idx_pull_request_forks_head). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 49."),
    MigrationEntry(50, "creates table pull_request_file_views; creates index idx_pr_file_views_pr_user", None,
        "ONE-WAY: migration 50 shipped without a down-path (creates table pull_request_file_views; creates index idx_pr_file_views_pr_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 50."),
    MigrationEntry(51, "creates table pull_request_line_comments; creates index idx_pr_line_comments_pr; creates table pull_request_line_comment_edits; creates index idx_pr_line_comment_edits_comment", None,
        "ONE-WAY: migration 51 shipped without a down-path (creates table pull_request_line_comments; creates index idx_pr_line_comments_pr; creates table pull_request_line_comment_edits; creates index idx_pr_line_comment_edits_comment). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 51."),
    MigrationEntry(52, "creates table pull_request_review_threads; creates table pull_request_line_replies; creates index idx_pr_line_replies_comment; creates table pull_request_line_reply_edits; creates index idx_pr_line_reply_edits_reply", None,
        "ONE-WAY: migration 52 shipped without a down-path (creates table pull_request_review_threads; creates table pull_request_line_replies; creates index idx_pr_line_replies_comment; creates table pull_request_line_reply_edits; creates index idx_pr_line_reply_edits_reply). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 52."),
    MigrationEntry(53, "creates table pull_request_reviews; creates index idx_pr_reviews_pr; creates table pull_request_pending_reviews", None,
        "ONE-WAY: migration 53 shipped without a down-path (creates table pull_request_reviews; creates index idx_pr_reviews_pr; creates table pull_request_pending_reviews). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 53."),
    MigrationEntry(54, "creates table repo_review_freshness_policies", None,
        "ONE-WAY: migration 54 shipped without a down-path (creates table repo_review_freshness_policies). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 54."),
    MigrationEntry(55, "creates table pull_request_suggestions; creates index idx_pr_suggestions_pr", None,
        "ONE-WAY: migration 55 shipped without a down-path (creates table pull_request_suggestions; creates index idx_pr_suggestions_pr). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 55."),
    MigrationEntry(56, "creates table pull_request_review_requests; creates index idx_pr_review_requests_pr", None,
        "ONE-WAY: migration 56 shipped without a down-path (creates table pull_request_review_requests; creates index idx_pr_review_requests_pr). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 56."),
    MigrationEntry(57, "alters table pull_request_review_requests; creates table pull_request_review_request_events; creates index idx_pr_review_request_events_request", None,
        "ONE-WAY: migration 57 shipped without a down-path (alters table pull_request_review_requests; creates table pull_request_review_request_events; creates index idx_pr_review_request_events_request). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 57."),
    MigrationEntry(58, "creates table pull_request_merges; creates index idx_pr_merges_repo", None,
        "ONE-WAY: migration 58 shipped without a down-path (creates table pull_request_merges; creates index idx_pr_merges_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 58."),
    MigrationEntry(59, "creates table pull_request_merges_unified; inserts into pull_request_merges_unified; drops table pull_request_merges; alters table pull_request_merges_unified; creates index idx_pr_merges_repo; creates table pull_request_merge_closings; creates index idx_pr_merge_closings_pr", None,
        "ONE-WAY: migration 59 shipped without a down-path (creates table pull_request_merges_unified; inserts into pull_request_merges_unified; drops table pull_request_merges; alters table pull_request_merges_unified; creates index idx_pr_merges_repo; creates table pull_request_merge_closings; creates index idx_pr_merge_closings_pr). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 59."),
    MigrationEntry(60, "creates table commit_checks; creates index idx_commit_checks_repo_head", None,
        "ONE-WAY: migration 60 shipped without a down-path (creates table commit_checks; creates index idx_commit_checks_repo_head). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 60."),
    MigrationEntry(61, "creates table pull_request_auto_merges; creates index idx_pr_auto_merges_repo; creates table pull_request_auto_merge_events; creates index idx_pr_auto_merge_events_pr", None,
        "ONE-WAY: migration 61 shipped without a down-path (creates table pull_request_auto_merges; creates index idx_pr_auto_merges_repo; creates table pull_request_auto_merge_events; creates index idx_pr_auto_merge_events_pr). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 61."),
    MigrationEntry(62, "alters table repo_settings; creates table deleted_branches; creates index idx_deleted_branches_repo; creates index idx_deleted_branches_pr", None,
        "ONE-WAY: migration 62 shipped without a down-path (alters table repo_settings; creates table deleted_branches; creates index idx_deleted_branches_repo; creates index idx_deleted_branches_pr). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 62."),
    MigrationEntry(63, "creates table pull_request_reverts; creates index idx_pr_reverts_original", None,
        "ONE-WAY: migration 63 shipped without a down-path (creates table pull_request_reverts; creates index idx_pr_reverts_original). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 63."),
    MigrationEntry(64, "creates table pull_request_review_notifications; creates index idx_pr_review_notifications_recipient; creates index idx_pr_review_notifications_pr", None,
        "ONE-WAY: migration 64 shipped without a down-path (creates table pull_request_review_notifications; creates index idx_pr_review_notifications_recipient; creates index idx_pr_review_notifications_pr). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 64."),
    MigrationEntry(65, "creates table protection_rules; creates index idx_protection_rules_repo", None,
        "ONE-WAY: migration 65 shipped without a down-path (creates table protection_rules; creates index idx_protection_rules_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 65."),
    MigrationEntry(66, "alters table protection_rules", None,
        "ONE-WAY: migration 66 shipped without a down-path (alters table protection_rules). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 66."),
    MigrationEntry(67, "creates table protection_rulesets; creates index idx_protection_rulesets_name", None,
        "ONE-WAY: migration 67 shipped without a down-path (creates table protection_rulesets; creates index idx_protection_rulesets_name). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 67."),
    MigrationEntry(68, "creates table organizations; creates index idx_organizations_name", None,
        "ONE-WAY: migration 68 shipped without a down-path (creates table organizations; creates index idx_organizations_name). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 68."),
    MigrationEntry(69, "creates table organization_members; creates index idx_organization_members_org", None,
        "ONE-WAY: migration 69 shipped without a down-path (creates table organization_members; creates index idx_organization_members_org). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 69."),
    MigrationEntry(70, "creates table teams; creates index idx_teams_org; creates table team_members; creates index idx_team_members_team; creates table team_repositories; creates index idx_team_repositories_team; creates index idx_team_repositories_repo", None,
        "ONE-WAY: migration 70 shipped without a down-path (creates table teams; creates index idx_teams_org; creates table team_members; creates index idx_team_members_team; creates table team_repositories; creates index idx_team_repositories_team; creates index idx_team_repositories_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 70."),
    MigrationEntry(71, "alters table teams; creates index idx_teams_parent", None,
        "ONE-WAY: migration 71 shipped without a down-path (alters table teams; creates index idx_teams_parent). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 71."),
    MigrationEntry(72, "alters table team_repositories", None,
        "ONE-WAY: migration 72 shipped without a down-path (alters table team_repositories). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 72."),
    MigrationEntry(73, "creates table outside_collaborators; creates index idx_outside_collaborators_repo; creates index idx_outside_collaborators_user", None,
        "ONE-WAY: migration 73 shipped without a down-path (creates table outside_collaborators; creates index idx_outside_collaborators_repo; creates index idx_outside_collaborators_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 73."),
    MigrationEntry(74, "creates table org_default_permissions", None,
        "ONE-WAY: migration 74 shipped without a down-path (creates table org_default_permissions). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 74."),
    MigrationEntry(75, "creates table org_invitations; creates index idx_org_invitations_org; creates index idx_org_invitations_user; creates index idx_org_invitations_email", None,
        "ONE-WAY: migration 75 shipped without a down-path (creates table org_invitations; creates index idx_org_invitations_org; creates index idx_org_invitations_user; creates index idx_org_invitations_email). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 75."),
    MigrationEntry(76, "creates table team_mention_notifications; creates index idx_team_mentions_recipient; creates index idx_team_mentions_item; creates index idx_team_mentions_team", None,
        "ONE-WAY: migration 76 shipped without a down-path (creates table team_mention_notifications; creates index idx_team_mentions_recipient; creates index idx_team_mentions_item; creates index idx_team_mentions_team). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 76."),
    MigrationEntry(77, "creates table org_repo_policies", None,
        "ONE-WAY: migration 77 shipped without a down-path (creates table org_repo_policies). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 77."),
    MigrationEntry(78, "creates table org_deletions", None,
        "ONE-WAY: migration 78 shipped without a down-path (creates table org_deletions). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 78."),
    MigrationEntry(79, "creates table instance_groups; creates table instance_group_members; creates index idx_instance_group_members_group; creates index idx_instance_group_members_user; creates table instance_group_repositories; creates index idx_instance_group_repos_group; creates index idx_instance_group_repos_repo", None,
        "ONE-WAY: migration 79 shipped without a down-path (creates table instance_groups; creates table instance_group_members; creates index idx_instance_group_members_group; creates index idx_instance_group_members_user; creates table instance_group_repositories; creates index idx_instance_group_repos_group; creates index idx_instance_group_repos_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 79."),
    MigrationEntry(80, "creates table index_jobs; creates index idx_index_jobs_pending; creates index idx_index_jobs_repo; creates table index_state; creates table index_documents; creates index idx_index_documents_repo", None,
        "ONE-WAY: migration 80 shipped without a down-path (creates table index_jobs; creates index idx_index_jobs_pending; creates index idx_index_jobs_repo; creates table index_state; creates table index_documents; creates index idx_index_documents_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 80."),
    MigrationEntry(81, "CREATE VIRTUAL TABLE issue_pr_fts USING fts5( title, body, r", None,
        "ONE-WAY: migration 81 shipped without a down-path (CREATE VIRTUAL TABLE issue_pr_fts USING fts5( title, body, r). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 81."),
    MigrationEntry(82, "CREATE VIRTUAL TABLE code_fts USING fts5( path, text, repo_i", None,
        "ONE-WAY: migration 82 shipped without a down-path (CREATE VIRTUAL TABLE code_fts USING fts5( path, text, repo_i). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 82."),
    MigrationEntry(83, "creates table recent_searches; creates index idx_recent_searches_user_query; creates index idx_recent_searches_user_recent", None,
        "ONE-WAY: migration 83 shipped without a down-path (creates table recent_searches; creates index idx_recent_searches_user_query; creates index idx_recent_searches_user_recent). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 83."),
    MigrationEntry(84, "creates table saved_searches; creates index idx_saved_searches_user", None,
        "ONE-WAY: migration 84 shipped without a down-path (creates table saved_searches; creates index idx_saved_searches_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 84."),
    MigrationEntry(85, "creates table events; creates index idx_events_actor; creates index idx_events_verb", None,
        "ONE-WAY: migration 85 shipped without a down-path (creates table events; creates index idx_events_actor; creates index idx_events_verb). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 85."),
    MigrationEntry(86, "creates table repo_watches; creates index idx_repo_watches_repo; creates table repo_stars; creates index idx_repo_stars_repo; creates index idx_repo_stars_user", None,
        "ONE-WAY: migration 86 shipped without a down-path (creates table repo_watches; creates index idx_repo_watches_repo; creates table repo_stars; creates index idx_repo_stars_repo; creates index idx_repo_stars_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 86."),
    MigrationEntry(87, "creates table notifications; creates index idx_notifications_recipient; creates index idx_notifications_reason", None,
        "ONE-WAY: migration 87 shipped without a down-path (creates table notifications; creates index idx_notifications_recipient; creates index idx_notifications_reason). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 87."),
    MigrationEntry(88, "creates table inbox_triage; creates index idx_inbox_triage_saved", None,
        "ONE-WAY: migration 88 shipped without a down-path (creates table inbox_triage; creates index idx_inbox_triage_saved). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 88."),
    MigrationEntry(89, "creates table thread_overrides; creates index idx_thread_overrides_user; creates index idx_thread_overrides_repo", None,
        "ONE-WAY: migration 89 shipped without a down-path (creates table thread_overrides; creates index idx_thread_overrides_user; creates index idx_thread_overrides_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 89."),
    MigrationEntry(90, "creates table mention_deliveries; creates index idx_mention_deliveries_recipient; creates index idx_mention_deliveries_item", None,
        "ONE-WAY: migration 90 shipped without a down-path (creates table mention_deliveries; creates index idx_mention_deliveries_recipient; creates index idx_mention_deliveries_item). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 90."),
    MigrationEntry(91, "creates table email_deliveries; creates index idx_email_deliveries_recipient; creates index idx_email_deliveries_status; creates table email_optouts; creates index idx_email_optouts_user", None,
        "ONE-WAY: migration 91 shipped without a down-path (creates table email_deliveries; creates index idx_email_deliveries_recipient; creates index idx_email_deliveries_status; creates table email_optouts; creates index idx_email_optouts_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 91."),
    MigrationEntry(92, "creates table notification_preferences", None,
        "ONE-WAY: migration 92 shipped without a down-path (creates table notification_preferences). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 92."),
    MigrationEntry(93, "creates table user_follows; creates index idx_user_follows_followed; creates index idx_user_follows_follower", None,
        "ONE-WAY: migration 93 shipped without a down-path (creates table user_follows; creates index idx_user_follows_followed; creates index idx_user_follows_follower). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 93."),
    MigrationEntry(94, "creates table weekly_digests; creates index idx_weekly_digests_user; creates index idx_weekly_digests_status", None,
        "ONE-WAY: migration 94 shipped without a down-path (creates table weekly_digests; creates index idx_weekly_digests_user; creates index idx_weekly_digests_status). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 94."),
    MigrationEntry(95, "alters table commit_checks; creates table check_runs; creates index idx_check_runs_repo_head", None,
        "ONE-WAY: migration 95 shipped without a down-path (alters table commit_checks; creates table check_runs; creates index idx_check_runs_repo_head). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 95."),
    MigrationEntry(96, "creates table webhooks; creates index idx_webhooks_repo; creates index idx_webhooks_org", None,
        "ONE-WAY: migration 96 shipped without a down-path (creates table webhooks; creates index idx_webhooks_repo; creates index idx_webhooks_org). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 96."),
    MigrationEntry(97, "creates table webhook_deliveries; creates index idx_webhook_deliveries_once; creates index idx_webhook_deliveries_due; creates index idx_webhook_deliveries_hook; creates table webhook_delivery_attempts; creates index idx_webhook_delivery_attempts_delivery", None,
        "ONE-WAY: migration 97 shipped without a down-path (creates table webhook_deliveries; creates index idx_webhook_deliveries_once; creates index idx_webhook_deliveries_due; creates index idx_webhook_deliveries_hook; creates table webhook_delivery_attempts; creates index idx_webhook_delivery_attempts_delivery). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 97."),
    MigrationEntry(98, "alters table webhook_deliveries; DROP INDEX idx_webhook_deliveries_once; creates index idx_webhook_deliveries_once; creates index idx_webhook_deliveries_redelivery", None,
        "ONE-WAY: migration 98 shipped without a down-path (alters table webhook_deliveries; DROP INDEX idx_webhook_deliveries_once; creates index idx_webhook_deliveries_once; creates index idx_webhook_deliveries_redelivery). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 98."),
    MigrationEntry(99, "creates table webhook_pings; creates index idx_webhook_pings_hook; creates index idx_webhook_pings_delivery", None,
        "ONE-WAY: migration 99 shipped without a down-path (creates table webhook_pings; creates index idx_webhook_pings_hook; creates index idx_webhook_pings_delivery). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 99."),
    MigrationEntry(100, "creates table releases; creates index idx_releases_repo", None,
        "ONE-WAY: migration 100 shipped without a down-path (creates table releases; creates index idx_releases_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 100."),
    MigrationEntry(101, "alters table releases", None,
        "ONE-WAY: migration 101 shipped without a down-path (alters table releases). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 101."),
    MigrationEntry(102, "creates table release_assets; creates index idx_release_assets_release; creates table release_upload_sessions", None,
        "ONE-WAY: migration 102 shipped without a down-path (creates table release_assets; creates index idx_release_assets_release; creates table release_upload_sessions). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 102."),
    MigrationEntry(103, "creates table release_notification_deliveries; creates index idx_release_notif_deliv_recipient; creates index idx_release_notif_deliv_release", None,
        "ONE-WAY: migration 103 shipped without a down-path (creates table release_notification_deliveries; creates index idx_release_notif_deliv_recipient; creates index idx_release_notif_deliv_release). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 103."),
    MigrationEntry(104, "creates table release_signatures; creates index idx_release_signatures_release", None,
        "ONE-WAY: migration 104 shipped without a down-path (creates table release_signatures; creates index idx_release_signatures_release). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 104."),
    MigrationEntry(105, "creates table ci_artifacts; creates index idx_ci_artifacts_repo_head; creates index idx_ci_artifacts_run; creates index idx_ci_artifacts_expiry; creates table ci_artifact_upload_sessions", None,
        "ONE-WAY: migration 105 shipped without a down-path (creates table ci_artifacts; creates index idx_ci_artifacts_repo_head; creates index idx_ci_artifacts_run; creates index idx_ci_artifacts_expiry; creates table ci_artifact_upload_sessions). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 105."),
    MigrationEntry(106, "creates table release_tag_automation", None,
        "ONE-WAY: migration 106 shipped without a down-path (creates table release_tag_automation). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 106."),
    MigrationEntry(107, "creates table wiki_access_policies", None,
        "ONE-WAY: migration 107 shipped without a down-path (creates table wiki_access_policies). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 107."),
    MigrationEntry(108, "creates table gists; creates index idx_gists_owner", None,
        "ONE-WAY: migration 108 shipped without a down-path (creates table gists; creates index idx_gists_owner). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 108."),
    MigrationEntry(109, "alters table gists", None,
        "ONE-WAY: migration 109 shipped without a down-path (alters table gists). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 109."),
    MigrationEntry(110, "alters table gists; creates index idx_gists_fork_of; creates table gist_stars; creates index idx_gist_stars_gist; creates index idx_gist_stars_user", None,
        "ONE-WAY: migration 110 shipped without a down-path (alters table gists; creates index idx_gists_fork_of; creates table gist_stars; creates index idx_gist_stars_gist; creates index idx_gist_stars_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 110."),
    MigrationEntry(111, "creates table gist_comments; creates index idx_gist_comments_gist; creates table gist_comment_edits; creates index idx_gist_comment_edits_comment", None,
        "ONE-WAY: migration 111 shipped without a down-path (creates table gist_comments; creates index idx_gist_comments_gist; creates table gist_comment_edits; creates index idx_gist_comment_edits_comment). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 111."),
    MigrationEntry(112, "creates table discussion_categories; creates index idx_discussion_categories_repo; creates table discussion_threads; creates index idx_discussion_threads_repo; creates index idx_discussion_threads_category; creates table discussion_counters; creates table discussion_replies; creates index idx_discussion_replies_thread; creates table discussion_reply_edits; creates index idx_discussion_reply_edits_reply; creates table discussion_events; creates index idx_discussion_events_thread", None,
        "ONE-WAY: migration 112 shipped without a down-path (creates table discussion_categories; creates index idx_discussion_categories_repo; creates table discussion_threads; creates index idx_discussion_threads_repo; creates index idx_discussion_threads_category; creates table discussion_counters; creates table discussion_replies; creates index idx_discussion_replies_thread; creates table discussion_reply_edits; creates index idx_discussion_reply_edits_reply; creates table discussion_events; creates index idx_discussion_events_thread). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 112."),
    MigrationEntry(113, "alters table discussion_threads", None,
        "ONE-WAY: migration 113 shipped without a down-path (alters table discussion_threads). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 113."),
    MigrationEntry(114, "creates table discussion_conversions; creates index idx_discussion_conversions_repo", None,
        "ONE-WAY: migration 114 shipped without a down-path (creates table discussion_conversions; creates index idx_discussion_conversions_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 114."),
    MigrationEntry(115, "creates table push_scans; creates index idx_push_scans_repo; creates table push_scan_updates; creates index idx_push_scan_updates_scan; creates table secret_alerts; creates index idx_secret_alerts_repo; creates index idx_secret_alerts_scan", None,
        "ONE-WAY: migration 115 shipped without a down-path (creates table push_scans; creates index idx_push_scans_repo; creates table push_scan_updates; creates index idx_push_scan_updates_scan; creates table secret_alerts; creates index idx_secret_alerts_repo; creates index idx_secret_alerts_scan). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 115."),
    MigrationEntry(116, "creates table push_protection_bypasses; creates index idx_push_protection_bypasses_repo", None,
        "ONE-WAY: migration 116 shipped without a down-path (creates table push_protection_bypasses; creates index idx_push_protection_bypasses_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 116."),
    MigrationEntry(117, "alters table secret_alerts; creates table secret_alert_events; creates index idx_secret_alert_events_alert; creates index idx_secret_alert_events_repo", None,
        "ONE-WAY: migration 117 shipped without a down-path (alters table secret_alerts; creates table secret_alert_events; creates index idx_secret_alert_events_alert; creates index idx_secret_alert_events_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 117."),
    MigrationEntry(118, "creates table custom_patterns; creates index idx_custom_patterns_scope; creates table custom_pattern_dry_runs; creates index idx_custom_pattern_dry_runs_pattern; creates table custom_pattern_dry_run_matches; creates index idx_custom_pattern_dry_run_matches_run", None,
        "ONE-WAY: migration 118 shipped without a down-path (creates table custom_patterns; creates index idx_custom_patterns_scope; creates table custom_pattern_dry_runs; creates index idx_custom_pattern_dry_runs_pattern; creates table custom_pattern_dry_run_matches; creates index idx_custom_pattern_dry_run_matches_run). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 118."),
    MigrationEntry(119, "alters table secret_alerts; creates table secret_validity_checks; creates index idx_secret_validity_checks_alert; creates index idx_secret_validity_checks_repo", None,
        "ONE-WAY: migration 119 shipped without a down-path (alters table secret_alerts; creates table secret_validity_checks; creates index idx_secret_validity_checks_alert; creates index idx_secret_validity_checks_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 119."),
    MigrationEntry(120, "creates table dependency_graph_states; creates table dependency_manifests; creates index idx_dependency_manifests_repo; creates table repo_dependencies; creates index idx_repo_dependencies_repo; creates index idx_repo_dependencies_name", None,
        "ONE-WAY: migration 120 shipped without a down-path (creates table dependency_graph_states; creates table dependency_manifests; creates index idx_dependency_manifests_repo; creates table repo_dependencies; creates index idx_repo_dependencies_repo; creates index idx_repo_dependencies_name). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 120."),
    MigrationEntry(121, "creates table dependency_alerts; creates index idx_dependency_alerts_repo; creates index idx_dependency_alerts_advisory; creates table dependency_alert_events; creates index idx_dependency_alert_events_alert; creates index idx_dependency_alert_events_repo", None,
        "ONE-WAY: migration 121 shipped without a down-path (creates table dependency_alerts; creates index idx_dependency_alerts_repo; creates index idx_dependency_alerts_advisory; creates table dependency_alert_events; creates index idx_dependency_alert_events_alert; creates index idx_dependency_alert_events_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 121."),
    MigrationEntry(122, "creates table advisory_snapshot_state; creates table advisory_refreshes; creates index idx_advisory_refreshes_id", None,
        "ONE-WAY: migration 122 shipped without a down-path (creates table advisory_snapshot_state; creates table advisory_refreshes; creates index idx_advisory_refreshes_id). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 122."),
    MigrationEntry(123, "creates table code_scanning_uploads; creates index idx_code_scanning_uploads_repo_commit; creates index idx_code_scanning_uploads_repo", None,
        "ONE-WAY: migration 123 shipped without a down-path (creates table code_scanning_uploads; creates index idx_code_scanning_uploads_repo_commit; creates index idx_code_scanning_uploads_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 123."),
    MigrationEntry(124, "creates table code_scanning_alerts; creates index idx_code_scanning_alerts_repo_branch; creates table code_scanning_branch_heads", None,
        "ONE-WAY: migration 124 shipped without a down-path (creates table code_scanning_alerts; creates index idx_code_scanning_alerts_repo_branch; creates table code_scanning_branch_heads). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 124."),
    MigrationEntry(125, "alters table code_scanning_alerts; creates table code_scanning_alert_events; creates index idx_code_scanning_alert_events_alert; creates index idx_code_scanning_alert_events_repo", None,
        "ONE-WAY: migration 125 shipped without a down-path (alters table code_scanning_alerts; creates table code_scanning_alert_events; creates index idx_code_scanning_alert_events_alert; creates index idx_code_scanning_alert_events_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 125."),
    MigrationEntry(126, "creates table signing_keys; creates index idx_signing_keys_kind_fingerprint; creates index idx_signing_keys_user; creates table commit_verifications; creates index idx_commit_verifications_repo_oid", None,
        "ONE-WAY: migration 126 shipped without a down-path (creates table signing_keys; creates index idx_signing_keys_kind_fingerprint; creates index idx_signing_keys_user; creates table commit_verifications; creates index idx_commit_verifications_repo_oid). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 126."),
    MigrationEntry(127, "creates table vigil_settings; creates index idx_vigil_settings_user", None,
        "ONE-WAY: migration 127 shipped without a down-path (creates table vigil_settings; creates index idx_vigil_settings_user). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 127."),
    MigrationEntry(128, "creates table security_advisories; creates index idx_security_advisories_key; creates index idx_security_advisories_repo; creates table security_advisory_alerts; creates index idx_security_advisory_alerts_adv; creates table security_advisory_events; creates index idx_security_advisory_events_adv; creates index idx_security_advisory_events_repo", None,
        "ONE-WAY: migration 128 shipped without a down-path (creates table security_advisories; creates index idx_security_advisories_key; creates index idx_security_advisories_repo; creates table security_advisory_alerts; creates index idx_security_advisory_alerts_adv; creates table security_advisory_events; creates index idx_security_advisory_events_adv; creates index idx_security_advisory_events_repo). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 128."),
    MigrationEntry(129, "creates table runner_registration_tokens; creates index idx_runner_tokens_hash; creates index idx_runner_tokens_scope; creates table runners; creates index idx_runners_scope", None,
        "ONE-WAY: migration 129 shipped without a down-path (creates table runner_registration_tokens; creates index idx_runner_tokens_hash; creates index idx_runner_tokens_scope; creates table runners; creates index idx_runners_scope). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 129."),
    MigrationEntry(130, "creates table ci_secrets; creates index idx_ci_secrets_scope_name; creates index idx_ci_secrets_scope", None,
        "ONE-WAY: migration 130 shipped without a down-path (creates table ci_secrets; creates index idx_ci_secrets_scope_name; creates index idx_ci_secrets_scope). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 130."),
    MigrationEntry(131, "creates table ci_logs; creates index idx_ci_logs_repo_run; creates index idx_ci_logs_expiry", None,
        "ONE-WAY: migration 131 shipped without a down-path (creates table ci_logs; creates index idx_ci_logs_repo_run; creates index idx_ci_logs_expiry). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 131."),
    MigrationEntry(132, "creates table ci_run_actions; creates index idx_ci_run_actions_repo_run", None,
        "ONE-WAY: migration 132 shipped without a down-path (creates table ci_run_actions; creates index idx_ci_run_actions_repo_run). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 132."),
    MigrationEntry(133, "alters table repo_mirrors", None,
        "ONE-WAY: migration 133 shipped without a down-path (alters table repo_mirrors). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 133."),
    MigrationEntry(134, "alters table repo_mirrors", None,
        "ONE-WAY: migration 134 shipped without a down-path (alters table repo_mirrors). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 134."),
    MigrationEntry(135, "alters table repo_mirrors", None,
        "ONE-WAY: migration 135 shipped without a down-path (alters table repo_mirrors). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 135."),
    MigrationEntry(136, "creates table repo_push_mirrors", None,
        "ONE-WAY: migration 136 shipped without a down-path (creates table repo_push_mirrors). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 136."),
    MigrationEntry(137, "creates table census_fixture_entries", None,
        "ONE-WAY: migration 137 shipped without a down-path (creates table census_fixture_entries). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 137."),
    MigrationEntry(138, "creates table first_pass_mirror_runs", None,
        "ONE-WAY: migration 138 shipped without a down-path (creates table first_pass_mirror_runs). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 138."),
    MigrationEntry(139, "creates table metadata_imports; creates table metadata_import_runs", None,
        "ONE-WAY: migration 139 shipped without a down-path (creates table metadata_imports; creates table metadata_import_runs). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 139."),
    MigrationEntry(140, "creates table abuse_reports; creates index idx_abuse_reports_state; creates index idx_abuse_reports_reporter", None,
        "ONE-WAY: migration 140 shipped without a down-path (creates table abuse_reports; creates index idx_abuse_reports_state; creates index idx_abuse_reports_reporter). There is no safe automatic way back: reversing it would mean dropping or undoing the objects above and any data written into them since. The way back is to restore a backup of the database taken before upgrading past version 140."),
)


def validate_register(migrations, register) -> list[str]:
    """Judge a register against a migration list. Pure.

    Every problem is named: a migration with no entry, an entry
    with no migration, a duplicate, entries out of order, an
    entry with both a down-path and a one-way warning, an entry
    with neither, an empty warning, an empty down-path. An
    empty list is the only pass."""
    problems: list[str] = []
    versions = [v for v, _ in migrations]
    seen: set[int] = set()
    previous = 0
    for entry in register:
        if entry.version in seen:
            problems.append(f"migration {entry.version}: duplicate register entry")
        seen.add(entry.version)
        if entry.version <= previous:
            problems.append(f"migration {entry.version}: register entry out of order")
        previous = entry.version
        if entry.down_statements is not None and entry.one_way_warning is not None:
            problems.append(f"migration {entry.version}: carries both a down-path "
                            "and a one-way warning; it must carry exactly one")
        if entry.down_statements is None and entry.one_way_warning is None:
            problems.append(f"migration {entry.version}: carries neither a down-path "
                            "nor a one-way warning")
        if entry.one_way_warning is not None and not entry.one_way_warning.strip():
            problems.append(f"migration {entry.version}: one-way warning is empty")
        if entry.down_statements is not None and not entry.down_statements:
            problems.append(f"migration {entry.version}: down-path is empty")
    for v in versions:
        if v not in seen:
            problems.append(f"migration {v}: no register entry")
    for entry in register:
        if entry.version not in versions:
            problems.append(f"migration {entry.version}: register entry with no migration")
    return problems


def register_entry(version: int, register=REGISTER) -> MigrationEntry:
    for entry in register:
        if entry.version == version:
            return entry
    raise MigrationRegisterError(
        "unknown_migration", f"no register entry for migration {version}")


def pending_one_way(register, from_version: int) -> list[MigrationEntry]:
    """The one-way entries an upgrade from ``from_version`` crosses. Pure."""
    return [e for e in register
            if e.version > from_version and not e.reversible]


def render_upgrade_warnings(register, from_version: int) -> str:
    """Plain words an operator reads before upgrading. Pure.

    Names every one-way migration the upgrade would cross and
    the standing instruction that goes with all of them: take
    a backup first, because there is no down-path back."""
    pending = pending_one_way(register, from_version)
    if not pending:
        return (f"Upgrade warnings from schema version {from_version}: "
                "no one-way migrations are crossed by this upgrade.")
    lines = [f"Before upgrading from schema version {from_version}, read this:",
             f"{len(pending)} of the migrations ahead are ONE-WAY. "
             "Once applied there is no down-path back. Take a backup of "
             "the database before upgrading; restoring that backup is "
             "the only way back.", ""]
    for e in pending:
        lines.append(f"- Migration {e.version} ({e.summary}): {e.one_way_warning}")
    return "\n".join(lines)


def apply_down(conn: sqlite3.Connection, entry: MigrationEntry,
               previous_version: int) -> None:
    """Run one entry's down-path in a single transaction.

    The down statements and the version re-stamp land together
    or not at all. A one-way entry is refused by name and the
    database is left exactly as it was."""
    if entry.down_statements is None:
        raise MigrationRegisterError(
            "one_way_migration",
            f"migration {entry.version} is one-way: {entry.one_way_warning}")
    with migration_transaction(conn):  # one transaction, whole down-path
        for stmt in entry.down_statements:
            conn.execute(stmt)
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) "
            "VALUES ('version', ?)",
            (str(previous_version),),
        )
