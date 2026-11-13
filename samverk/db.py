"""SQLite access — the connection factory and schema migrations.

Study 42's discipline, made code: this factory is the *only* way
application code obtains a connection, so the durability pragmas can
never be forgotten at a call site:

    WAL journal mode + synchronous=FULL   (a returned commit survives
                                           a power cut)
    foreign_keys=ON                       (always, no exceptions)
    busy_timeout=5000                     (writer contention resolves
                                           instead of erroring)

Migrations are numbered, transactional, and boring: each runs in one
transaction; a failure leaves the previous schema version intact.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .platform_seam import ensure_dir

BUSY_TIMEOUT_MS = 5000

# Each migration is (version, [statements]). Append-only: never edit a
# shipped migration; add the next number.
MIGRATIONS: list[tuple[int, list[str]]] = [
    (1, [
        "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    ]),
    # S-006: sessions. user_id has no FK yet — the users table arrives
    # in Part II, which adds the constraint story then; the value is
    # the principal's integer id throughout.
    (2, [
        "CREATE TABLE sessions ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  token_hash TEXT NOT NULL UNIQUE,"
        "  created_at INTEGER NOT NULL,"
        "  last_seen_at INTEGER NOT NULL,"
        "  absolute_expires_at INTEGER NOT NULL,"
        "  revoked INTEGER NOT NULL DEFAULT 0"
        ")",
        "CREATE INDEX idx_sessions_user ON sessions (user_id)",
    ]),
    # S-007: the audit chain (study 35). Append-only by discipline:
    # no code path UPDATEs or DELETEs from this table.
    (3, [
        "CREATE TABLE audit_log ("
        "  seq INTEGER PRIMARY KEY,"
        "  ts INTEGER NOT NULL,"
        "  actor_kind TEXT NOT NULL,"
        "  actor_id INTEGER,"
        "  action TEXT NOT NULL,"
        "  target_kind TEXT NOT NULL,"
        "  target_id TEXT,"
        "  source_ip TEXT,"
        "  outcome TEXT NOT NULL,"
        "  detail TEXT,"
        "  prev_hash TEXT NOT NULL,"
        "  entry_hash TEXT NOT NULL"
        ")",
    ]),
    # S-025: users. username_lower / email_lower are the canonical
    # case-insensitive uniqueness keys; display case is preserved in
    # username / email. Email is optional: NULLs never collide under
    # UNIQUE, which is exactly the optional-but-supported law.
    (4, [
        "CREATE TABLE users ("
        "  id INTEGER PRIMARY KEY,"
        "  username TEXT NOT NULL,"
        "  username_lower TEXT NOT NULL UNIQUE,"
        "  email TEXT,"
        "  email_lower TEXT UNIQUE,"
        "  password_hash TEXT NOT NULL,"
        "  email_verified INTEGER NOT NULL DEFAULT 0,"
        "  status TEXT NOT NULL DEFAULT 'active',"
        "  is_admin INTEGER NOT NULL DEFAULT 0,"
        "  created_at INTEGER NOT NULL"
        ")",
    ]),
    # S-026: email verification tokens — only SHA-256 hashes are
    # stored (the S-006 law), single-use via used_at, expiring.
    (5, [
        "CREATE TABLE email_verification_tokens ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  token_hash TEXT NOT NULL UNIQUE,"
        "  created_at INTEGER NOT NULL,"
        "  expires_at INTEGER NOT NULL,"
        "  used_at INTEGER"
        ")",
        "CREATE INDEX idx_email_verification_user"
        " ON email_verification_tokens (user_id)",
    ]),
    # S-028: password reset tokens — same law as S-026's tokens
    # (hashes only, single-use, expiring); `via` records whether
    # the token was minted for the email road or the operator road.
    (6, [
        "CREATE TABLE password_reset_tokens ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  token_hash TEXT NOT NULL UNIQUE,"
        "  via TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  expires_at INTEGER NOT NULL,"
        "  used_at INTEGER"
        ")",
        "CREATE INDEX idx_password_reset_user"
        " ON password_reset_tokens (user_id)",
    ]),
    # S-029: profiles — one row per account; avatar facts are the
    # S-012-proven ones (content SHA-256 + sniffed type) plus the
    # mandatory alt text (image-accessibility law).
    (7, [
        "CREATE TABLE profiles ("
        "  user_id INTEGER PRIMARY KEY,"
        "  display_name TEXT,"
        "  bio TEXT,"
        "  avatar_sha256 TEXT,"
        "  avatar_content_type TEXT,"
        "  avatar_alt TEXT,"
        "  updated_at INTEGER NOT NULL DEFAULT 0"
        ")",
    ]),
    # S-030: personal SSH keys. The fingerprint is globally
    # UNIQUE — one key, one account (attribution law, S-030).
    (8, [
        "CREATE TABLE ssh_keys ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  title TEXT NOT NULL,"
        "  key_type TEXT NOT NULL,"
        "  key_blob TEXT NOT NULL,"
        "  fingerprint TEXT NOT NULL UNIQUE,"
        "  created_at INTEGER NOT NULL,"
        "  last_used_at INTEGER"
        ")",
        "CREATE INDEX idx_ssh_keys_user ON ssh_keys (user_id)",
    ]),
    # S-031: deploy keys — bound to exactly one repository by
    # canonical owner/repo; can_write is the explicit grant
    # (default read-only). Fingerprint UNIQUE, as S-030.
    (9, [
        "CREATE TABLE deploy_keys ("
        "  id INTEGER PRIMARY KEY,"
        "  owner TEXT NOT NULL,"
        "  repo TEXT NOT NULL,"
        "  title TEXT NOT NULL,"
        "  key_type TEXT NOT NULL,"
        "  key_blob TEXT NOT NULL,"
        "  fingerprint TEXT NOT NULL UNIQUE,"
        "  can_write INTEGER NOT NULL DEFAULT 0,"
        "  created_at INTEGER NOT NULL,"
        "  last_used_at INTEGER"
        ")",
        "CREATE INDEX idx_deploy_keys_repo ON deploy_keys (owner, repo)",
    ]),
    # S-032: classic personal access tokens — only SHA-256
    # hashes are stored (the S-006 law); prefix identifies a
    # token in lists, scopes is the comma-joined closed set.
    (10, [
        "CREATE TABLE access_tokens ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  title TEXT NOT NULL,"
        "  token_hash TEXT NOT NULL UNIQUE,"
        "  prefix TEXT NOT NULL,"
        "  scopes TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  expires_at INTEGER NOT NULL,"
        "  last_used_at INTEGER,"
        "  revoked INTEGER NOT NULL DEFAULT 0"
        ")",
        "CREATE INDEX idx_access_tokens_user ON access_tokens (user_id)",
    ]),
    # S-033: fine-grained tokens — one repository (canonical
    # owner/repo, S-031's binding shape) + a per-resource
    # permission set; hashes only, as S-032.
    (11, [
        "CREATE TABLE fine_grained_tokens ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  owner TEXT NOT NULL,"
        "  repo TEXT NOT NULL,"
        "  title TEXT NOT NULL,"
        "  token_hash TEXT NOT NULL UNIQUE,"
        "  prefix TEXT NOT NULL,"
        "  permissions TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  expires_at INTEGER NOT NULL,"
        "  last_used_at INTEGER,"
        "  revoked INTEGER NOT NULL DEFAULT 0"
        ")",
        "CREATE INDEX idx_fine_tokens_user ON fine_grained_tokens (user_id)",
        "CREATE INDEX idx_fine_tokens_repo"
        " ON fine_grained_tokens (owner, repo)",
    ]),
    # S-035: TOTP credentials — secret stored encrypted under an
    # instance key (see totp.py), never plain, never hashed;
    # last_counter is the replay law (a spent counter is dead).
    (12, [
        "CREATE TABLE totp_credentials ("
        "  user_id INTEGER PRIMARY KEY,"
        "  secret_enc TEXT NOT NULL,"
        "  confirmed INTEGER NOT NULL DEFAULT 0,"
        "  created_at INTEGER NOT NULL,"
        "  confirmed_at INTEGER,"
        "  last_counter INTEGER NOT NULL DEFAULT -1"
        ")",
    ]),
    # S-036: sudo-mode grants — bound to one session by the
    # session token's SHA-256 (never the raw token, S-006 law).
    (13, [
        "CREATE TABLE sudo_grants ("
        "  user_id INTEGER NOT NULL,"
        "  session_hash TEXT NOT NULL,"
        "  granted_at INTEGER NOT NULL,"
        "  expires_at INTEGER NOT NULL,"
        "  PRIMARY KEY (user_id, session_hash)"
        ")",
    ]),
    # S-037: recovery codes — only SHA-256 hashes stored
    # (the S-006 law); used_at is the single-use stamp.
    (14, [
        "CREATE TABLE recovery_codes ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  code_hash TEXT NOT NULL UNIQUE,"
        "  created_at INTEGER NOT NULL,"
        "  used_at INTEGER"
        ")",
        "CREATE INDEX idx_recovery_codes_user"
        " ON recovery_codes (user_id)",
    ]),
    # S-039: passkeys. Challenges are stored hashed only
    # (the S-006 law), single-use, expiring. Credentials hold
    # the COSE public key bytes — passkeys carry no secret
    # material to this server, by design; credential_id is
    # globally UNIQUE (one passkey, one account).
    (15, [
        "CREATE TABLE passkey_challenges ("
        "  id INTEGER PRIMARY KEY,"
        "  challenge_hash TEXT NOT NULL UNIQUE,"
        "  user_id INTEGER,"
        "  purpose TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  expires_at INTEGER NOT NULL,"
        "  used_at INTEGER"
        ")",
        "CREATE TABLE passkey_credentials ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  credential_id TEXT NOT NULL UNIQUE,"
        "  public_key BLOB NOT NULL,"
        "  sign_count INTEGER NOT NULL DEFAULT 0,"
        "  aaguid TEXT NOT NULL,"
        "  nickname TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  last_used_at INTEGER"
        ")",
        "CREATE INDEX idx_passkey_credentials_user"
        " ON passkey_credentials (user_id)",
    ]),
    # S-040: sessions learn what device and address they came
    # from, so the owner can recognise them in the session
    # list (labels are user-facing text, never trusted input).
    (16, [
        "ALTER TABLE sessions ADD COLUMN device_label TEXT",
        "ALTER TABLE sessions ADD COLUMN source_ip TEXT",
    ]),
    # S-041: new-sign-in notification. known_devices is the
    # "have we seen this device before" memory (keyed by a
    # hash of label + address, so the table holds no raw
    # fingerprint material beyond what the owner sees);
    # signin_notifications is the in-app notice inbox.
    (17, [
        "CREATE TABLE known_devices ("
        "  user_id INTEGER NOT NULL,"
        "  device_key TEXT NOT NULL,"
        "  device_label TEXT,"
        "  source_ip TEXT,"
        "  first_seen_at INTEGER NOT NULL,"
        "  last_seen_at INTEGER NOT NULL,"
        "  PRIMARY KEY (user_id, device_key)"
        ")",
        "CREATE TABLE signin_notifications ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  device_label TEXT,"
        "  source_ip TEXT,"
        "  created_at INTEGER NOT NULL,"
        "  read_at INTEGER"
        ")",
        "CREATE INDEX idx_signin_notifications_user"
        " ON signin_notifications (user_id)",
    ]),
    # S-042: username tombstones — when an account renames,
    # its old canonical name is held for a tombstone period:
    # it redirects to the account's new name and cannot be
    # registered or taken by anyone else until it lapses.
    (18, [
        "CREATE TABLE username_tombstones ("
        "  old_lower TEXT PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  old_display TEXT NOT NULL,"
        "  renamed_at INTEGER NOT NULL,"
        "  expires_at INTEGER NOT NULL"
        ")",
    ]),
    # S-043: account deletion requests — the grace-period
    # record. One pending request per account; execution
    # after scheduled_at is the irreversible step.
    (19, [
        "CREATE TABLE account_deletions ("
        "  user_id INTEGER PRIMARY KEY,"
        "  requested_at INTEGER NOT NULL,"
        "  scheduled_at INTEGER NOT NULL"
        ")",
    ]),
    # S-044: suspension history — every suspend/unsuspend
    # with its reason and the acting admin, so a suspension
    # is never silent and never a deletion in disguise.
    (20, [
        "CREATE TABLE account_suspensions ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  action TEXT NOT NULL,"
        "  reason TEXT,"
        "  actor_id INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_suspensions_user"
        " ON account_suspensions (user_id)",
    ]),
    # S-045: external identities — the data shape for linking
    # an account to an external principal (Samtal first).
    # Shape only: no seam, no sync, no federation lives here.
    (21, [
        "CREATE TABLE external_identities ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  provider TEXT NOT NULL,"
        "  external_id TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (provider, external_id),"
        "  UNIQUE (user_id, provider)"
        ")",
        "CREATE INDEX idx_external_identities_user"
        " ON external_identities (user_id)",
    ]),
    # S-049: repositories — the metadata row for a bare repo on
    # disk (bytes are git's, S-013 path law); identity is the
    # canonical lowercase owner/name pair, display case kept.
    (22, [
        "CREATE TABLE repositories ("
        "  id INTEGER PRIMARY KEY,"
        "  owner TEXT NOT NULL,"
        "  owner_lower TEXT NOT NULL,"
        "  name TEXT NOT NULL,"
        "  name_lower TEXT NOT NULL,"
        "  created_by INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  description TEXT NOT NULL DEFAULT '',"
        "  visibility TEXT NOT NULL DEFAULT 'private',"
        "  default_branch TEXT NOT NULL DEFAULT 'main',"
        "  UNIQUE (owner_lower, name_lower)"
        ")",
        "CREATE INDEX idx_repositories_owner"
        " ON repositories (owner_lower)",
    ]),
    # S-055: forks — a fork row points at its direct upstream
    # repository (NULL for a network root). The fork's git bytes
    # are its own server-side clone, so the link is lineage only.
    (23, [
        "ALTER TABLE repositories ADD COLUMN fork_of_id INTEGER",
        "CREATE INDEX idx_repositories_fork_of"
        " ON repositories (fork_of_id)",
    ]),
    # S-056: repository deletion requests — the grace-period
    # record. One pending request per repository; the disk is
    # reclaimed only when execution runs after scheduled_at.
    (24, [
        "CREATE TABLE repo_deletions ("
        "  repo_id INTEGER PRIMARY KEY,"
        "  requested_by INTEGER NOT NULL,"
        "  requested_at INTEGER NOT NULL,"
        "  scheduled_at INTEGER NOT NULL"
        ")",
    ]),
    # S-057: repository transfers — a pending offer the recipient
    # must accept, and the redirects an accepted transfer leaves
    # behind (old canonical name -> new canonical name, expiring).
    (25, [
        "CREATE TABLE repo_transfers ("
        "  repo_id INTEGER PRIMARY KEY,"
        "  from_owner_lower TEXT NOT NULL,"
        "  to_owner_lower TEXT NOT NULL,"
        "  requested_by INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE TABLE repo_redirects ("
        "  old_owner_lower TEXT NOT NULL,"
        "  old_name_lower TEXT NOT NULL,"
        "  new_owner_lower TEXT NOT NULL,"
        "  new_name_lower TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  expires_at INTEGER NOT NULL,"
        "  PRIMARY KEY (old_owner_lower, old_name_lower)"
        ")",
    ]),
    # S-059: garbage-collection scheduling — one row per repo:
    # when gc is next due, when it last ran, how it ended. The
    # scheduler records; only the off-path runner spawns git gc.
    (26, [
        "CREATE TABLE repo_gc_state ("
        "  repo_id INTEGER PRIMARY KEY,"
        "  last_run_at INTEGER,"
        "  last_status TEXT,"
        "  next_due_at INTEGER NOT NULL DEFAULT 0,"
        "  runs INTEGER NOT NULL DEFAULT 0"
        ")",
    ]),
    # S-062: LFS locks — one lock per (repo, path); the lock
    # names a file path, its holding account, and when it was
    # taken. Ids are random hex minted by the locking module.
    (27, [
        "CREATE TABLE lfs_locks ("
        "  id TEXT PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  path TEXT NOT NULL,"
        "  owner_user_id INTEGER NOT NULL,"
        "  owner_name TEXT NOT NULL,"
        "  locked_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, path)"
        ")",
        "CREATE INDEX idx_lfs_locks_repo ON lfs_locks (repo_id)",
    ]),
    # S-064: repository templates — a repo may be marked as a
    # template; a repo created from one records its source in
    # template_of_id (lineage only, like fork_of_id, but a
    # template creation is not a fork).
    (28, [
        "ALTER TABLE repositories ADD COLUMN is_template"
        " INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE repositories ADD COLUMN template_of_id INTEGER",
    ]),
    # S-066: repository settings beyond the S-050 row —
    # website + topics per repo, and a branch-rename record
    # so clones of a renamed default branch can be guided.
    (29, [
        "CREATE TABLE repo_settings ("
        "  repo_id INTEGER PRIMARY KEY,"
        "  website TEXT NOT NULL DEFAULT '',"
        "  topics TEXT NOT NULL DEFAULT '[]'"
        ")",
        "CREATE TABLE repo_branch_renames ("
        "  repo_id INTEGER NOT NULL,"
        "  old_branch TEXT NOT NULL,"
        "  new_branch TEXT NOT NULL,"
        "  renamed_at INTEGER NOT NULL,"
        "  PRIMARY KEY (repo_id, old_branch)"
        ")",
    ]),
    # S-068: repository quotas — an explicit per-repo byte
    # limit; the instance default (when set) lives in the
    # settings table under repo_quota_default_bytes. Absence
    # of both means no quota: a limit exists only when an
    # operator or owner has actually set one.
    (30, [
        "CREATE TABLE repo_quotas ("
        "  repo_id INTEGER PRIMARY KEY,"
        "  quota_bytes INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL"
        ")",
    ]),
    # S-070: mirrors — a mirror is an ordinary repository
    # row + bare repo (no second storage engine) plus this
    # record: where it mirrors from and how the last sync
    # ended. Source is a validated remote URL or an absolute
    # local path; credentials never appear in either (S-069
    # law forbids them inside URLs).
    (31, [
        "CREATE TABLE repo_mirrors ("
        "  repo_id INTEGER PRIMARY KEY,"
        "  source TEXT NOT NULL,"
        "  source_kind TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  last_sync_at INTEGER,"
        "  last_status TEXT,"
        "  last_detail TEXT"
        ")",
    ]),
    # S-072: commit graph cache — derived data (counts,
    # contributors) keyed by the refs fingerprint it was
    # computed from; a fingerprint mismatch is staleness,
    # proven on read, never a stale answer.
    (32, [
        "CREATE TABLE repo_graph_cache ("
        "  repo_id INTEGER PRIMARY KEY,"
        "  fingerprint TEXT NOT NULL,"
        "  commit_count INTEGER NOT NULL,"
        "  contributors TEXT NOT NULL,"
        "  branch_count INTEGER NOT NULL,"
        "  tag_count INTEGER NOT NULL,"
        "  computed_at INTEGER NOT NULL"
        ")",
    ]),
    # S-090: push events — the canonical product record of
    # every accepted push (actor, transport, ref ranges as
    # JSON), the seed of Part XI's event store. The audit log
    # stays the tamper-evident witness; this is ordinary,
    # queryable product data.
    (33, [
        "CREATE TABLE push_events ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  actor_kind TEXT NOT NULL,"
        "  actor_id INTEGER,"
        "  transport TEXT NOT NULL,"
        "  refs TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX push_events_repo_idx"
        " ON push_events (repo_id, id)",
    ]),
    # S-121: the shared issue/PR numbering sequence and the
    # numbered-items table. repo_counters.last_number only
    # ever moves forward (a number is never reused); every
    # claimed number has exactly one issues row carrying its
    # kind, so #n is unambiguous in a repository. Title/body/
    # state/version columns are S-122's create/read/update
    # surface, placed here so no second migration is needed.
    (34, [
        "CREATE TABLE repo_counters ("
        "  repo_id INTEGER PRIMARY KEY,"
        "  last_number INTEGER NOT NULL DEFAULT 0"
        ")",
        "CREATE TABLE issues ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  number INTEGER NOT NULL,"
        "  kind TEXT NOT NULL DEFAULT 'issue',"
        "  author_id INTEGER NOT NULL,"
        "  title TEXT NOT NULL DEFAULT '',"
        "  body TEXT NOT NULL DEFAULT '',"
        "  state TEXT NOT NULL DEFAULT 'open',"
        "  version INTEGER NOT NULL DEFAULT 1,"
        "  created_at INTEGER NOT NULL DEFAULT 0,"
        "  updated_at INTEGER NOT NULL DEFAULT 0,"
        "  UNIQUE (repo_id, number)"
        ")",
        "CREATE INDEX idx_issues_repo ON issues (repo_id, number)",
        "CREATE INDEX idx_issues_repo_state ON issues (repo_id, state)",
    ]),
    # S-123: issue comments and their visible edit history.
    # Deletion is a tombstone on the comment row (body
    # cleared, deleted_at/deleted_by stamped); every edit
    # first records the previous body in issue_comment_edits.
    (35, [
        "CREATE TABLE issue_comments ("
        "  id INTEGER PRIMARY KEY,"
        "  issue_id INTEGER NOT NULL,"
        "  author_id INTEGER NOT NULL,"
        "  body TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  edited_at INTEGER,"
        "  deleted_at INTEGER,"
        "  deleted_by INTEGER"
        ")",
        "CREATE INDEX idx_issue_comments_issue"
        " ON issue_comments (issue_id, id)",
        "CREATE TABLE issue_comment_edits ("
        "  id INTEGER PRIMARY KEY,"
        "  comment_id INTEGER NOT NULL,"
        "  editor_id INTEGER NOT NULL,"
        "  previous_body TEXT NOT NULL,"
        "  edited_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_issue_comment_edits_comment"
        " ON issue_comment_edits (comment_id, id)",
    ]),
    # S-124: labels — one row per (repository, canonical
    # name); the name is mandatory text, the colour a strict
    # '#rrggbb' decoration beside it, never the meaning
    # alone. issue_labels carries assignments; both die
    # together when a label is deleted.
    (36, [
        "CREATE TABLE labels ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  name TEXT NOT NULL,"
        "  name_lower TEXT NOT NULL,"
        "  colour TEXT NOT NULL,"
        "  description TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, name_lower)"
        ")",
        "CREATE INDEX idx_labels_repo ON labels (repo_id, name_lower)",
        "CREATE TABLE issue_labels ("
        "  issue_id INTEGER NOT NULL,"
        "  label_id INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  PRIMARY KEY (issue_id, label_id)"
        ")",
        "CREATE INDEX idx_issue_labels_label"
        " ON issue_labels (label_id, issue_id)",
    ]),
    # S-125: milestones — one row per (repository,
    # canonical title); due_on is a real YYYY-MM-DD date
    # or NULL. Issues carry their milestone as a column
    # (NULL = none); deleting a milestone nulls it.
    (37, [
        "CREATE TABLE milestones ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  title TEXT NOT NULL,"
        "  title_lower TEXT NOT NULL,"
        "  description TEXT NOT NULL DEFAULT '',"
        "  due_on TEXT,"
        "  state TEXT NOT NULL DEFAULT 'open',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, title_lower)"
        ")",
        "CREATE INDEX idx_milestones_repo"
        " ON milestones (repo_id, title_lower)",
        "ALTER TABLE issues ADD COLUMN milestone_id INTEGER",
        "CREATE INDEX idx_issues_milestone"
        " ON issues (milestone_id, state)",
    ]),
    # S-126: assignees — many accounts per issue, each
    # row an assignment (who, by whom, when); the audit
    # log carries the assign/unassign event record.
    (38, [
        "CREATE TABLE issue_assignees ("
        "  issue_id INTEGER NOT NULL,"
        "  user_id INTEGER NOT NULL,"
        "  assigned_by INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  PRIMARY KEY (issue_id, user_id)"
        ")",
        "CREATE INDEX idx_issue_assignees_user"
        " ON issue_assignees (user_id, issue_id)",
    ]),
    # S-127: cross-references — the both-ways link record
    # derived from prose (issue/PR bodies, comments, commit
    # messages). Sentinel defaults (0 / '') stand in for
    # absent parts so the UNIQUE key dedupes in SQLite,
    # where NULLs never collide. A row names its source
    # (a numbered item, one of its comments, or a commit)
    # and its proven target (a numbered item in this or
    # another repository, or a resolver-confirmed commit).
    (39, [
        "CREATE TABLE cross_references ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  source_kind TEXT NOT NULL,"
        "  source_number INTEGER NOT NULL DEFAULT 0,"
        "  source_comment_id INTEGER NOT NULL DEFAULT 0,"
        "  source_sha TEXT NOT NULL DEFAULT '',"
        "  source_author_id INTEGER,"
        "  target_repo_id INTEGER NOT NULL DEFAULT 0,"
        "  target_number INTEGER NOT NULL DEFAULT 0,"
        "  target_sha TEXT NOT NULL DEFAULT '',"
        "  is_closing INTEGER NOT NULL DEFAULT 0,"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, source_kind, source_number,"
        "  source_comment_id, source_sha, target_repo_id,"
        "  target_number, target_sha)"
        ")",
        "CREATE INDEX idx_xrefs_target"
        " ON cross_references (target_repo_id, target_number)",
        "CREATE INDEX idx_xrefs_target_sha"
        " ON cross_references (target_sha)",
        "CREATE INDEX idx_xrefs_source"
        " ON cross_references (repo_id, source_number)",
    ]),
    # S-128: reactions — one row per (target, account,
    # reaction); the target is an issue (comment_id = 0)
    # or one of its comments. Removing your reaction
    # deletes your row; counts are counted live from
    # these rows, never cached.
    (40, [
        "CREATE TABLE reactions ("
        "  id INTEGER PRIMARY KEY,"
        "  issue_id INTEGER NOT NULL,"
        "  comment_id INTEGER NOT NULL DEFAULT 0,"
        "  user_id INTEGER NOT NULL,"
        "  reaction TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (issue_id, comment_id, user_id, reaction)"
        ")",
        "CREATE INDEX idx_reactions_target"
        " ON reactions (issue_id, comment_id, reaction)",
    ]),
    # S-129: issue templates — one row per (repository,
    # canonical name); a form template's parsed fields ride
    # as JSON beside the YAML source as given. The options
    # row carries the owner's blank-issue toggle (absent =
    # blank issues allowed, the birth default).
    (41, [
        "CREATE TABLE issue_templates ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  name TEXT NOT NULL,"
        "  name_lower TEXT NOT NULL,"
        "  kind TEXT NOT NULL,"
        "  description TEXT NOT NULL DEFAULT '',"
        "  title TEXT NOT NULL DEFAULT '',"
        "  body TEXT NOT NULL DEFAULT '',"
        "  fields_json TEXT NOT NULL DEFAULT '[]',"
        "  labels_json TEXT NOT NULL DEFAULT '[]',"
        "  source TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, name_lower)"
        ")",
        "CREATE INDEX idx_issue_templates_repo"
        " ON issue_templates (repo_id, name_lower)",
        "CREATE TABLE repo_issue_options ("
        "  repo_id INTEGER PRIMARY KEY,"
        "  allow_blank_issues INTEGER NOT NULL DEFAULT 1"
        ")",
    ]),
    # S-130: close/reopen — the issue row carries its
    # closing reason ('completed' / 'not_planned' / ''
    # while open), and every real state transition is an
    # issue_events row: the state-change stream S-131's
    # timeline reads, in order, with its actor and reason.
    (42, [
        "ALTER TABLE issues ADD COLUMN"
        " state_reason TEXT NOT NULL DEFAULT ''",
        "CREATE TABLE issue_events ("
        "  id INTEGER PRIMARY KEY,"
        "  issue_id INTEGER NOT NULL,"
        "  actor_id INTEGER NOT NULL,"
        "  kind TEXT NOT NULL,"
        "  reason TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_issue_events_issue"
        " ON issue_events (issue_id, id)",
    ]),
    # S-132: locking and pinning — the issue row carries
    # its lock (locked / reason in the S-132 vocabulary /
    # by whom / when; unlocked is locked = 0 with the rest
    # cleared), and issue_pins holds each repository's
    # pinned set (at most three, enforced by the store;
    # the table's shape makes a fourth row representable
    # only through the seam that refuses it).
    (43, [
        "ALTER TABLE issues ADD COLUMN"
        " locked INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE issues ADD COLUMN"
        " lock_reason TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE issues ADD COLUMN locked_by INTEGER",
        "ALTER TABLE issues ADD COLUMN locked_at INTEGER",
        "CREATE TABLE issue_pins ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  issue_id INTEGER NOT NULL UNIQUE,"
        "  pinned_by INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_issue_pins_repo"
        " ON issue_pins (repo_id, created_at, issue_id)",
    ]),
    # S-133: issue transfer — the forwarding record left
    # behind at the vacated (repository, number). The issue
    # row itself moves (its id, and everything keyed by it,
    # travels); this table is the note at the old address:
    # where it went, who moved it, and when. A vacated
    # number is never reused (S-121), so one row per
    # (source_repo_id, source_number) is the whole story.
    (44, [
        "CREATE TABLE issue_transfers ("
        "  id INTEGER PRIMARY KEY,"
        "  issue_id INTEGER NOT NULL,"
        "  source_repo_id INTEGER NOT NULL,"
        "  source_number INTEGER NOT NULL,"
        "  dest_repo_id INTEGER NOT NULL,"
        "  dest_number INTEGER NOT NULL,"
        "  actor_id INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (source_repo_id, source_number)"
        ")",
        "CREATE INDEX idx_issue_transfers_dest"
        " ON issue_transfers (dest_repo_id, dest_number)",
    ]),
    # S-136: saved filters — a user's own named searches
    # over one repository's issues / pull requests. The
    # query text is stored as typed; S-135's parser is the
    # validation seam at save time and at run time.
    (45, [
        "CREATE TABLE saved_filters ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  target TEXT NOT NULL DEFAULT 'issues',"
        "  name TEXT NOT NULL,"
        "  name_lower TEXT NOT NULL,"
        "  query TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (user_id, repo_id, name_lower)"
        ")",
        "CREATE INDEX idx_saved_filters_user"
        " ON saved_filters (user_id, repo_id, name_lower)",
    ]),
    # S-137: pull requests — the branch pair and draft
    # state for a numbered item whose kind is
    # 'pull_request' (its title/body/state live on the
    # shared issues row, S-121). source_issue_id links a
    # PR born from an issue (S-137) to that issue's row;
    # PRs created directly in Part VII leave it NULL.
    # One conversion PR per source issue (UNIQUE).
    (46, [
        "CREATE TABLE pull_requests ("
        "  id INTEGER PRIMARY KEY,"
        "  issue_id INTEGER NOT NULL UNIQUE,"
        "  repo_id INTEGER NOT NULL,"
        "  source_issue_id INTEGER UNIQUE,"
        "  base_branch TEXT NOT NULL,"
        "  head_branch TEXT NOT NULL,"
        "  base_oid TEXT NOT NULL DEFAULT '',"
        "  head_oid TEXT NOT NULL DEFAULT '',"
        "  is_draft INTEGER NOT NULL DEFAULT 1,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_pull_requests_repo"
        " ON pull_requests (repo_id, issue_id)",
    ]),
    # S-138: comment moderation — a hidden comment carries
    # when it was hidden, by whom, and the reason in the
    # S-138 vocabulary ('' while visible). Deletion stays
    # S-123's tombstone columns; moderation removal is a
    # distinct audited act over the same tombstone.
    (47, [
        "ALTER TABLE issue_comments ADD COLUMN hidden_at INTEGER",
        "ALTER TABLE issue_comments ADD COLUMN hidden_by INTEGER",
        "ALTER TABLE issue_comments ADD COLUMN"
        " hide_reason TEXT NOT NULL DEFAULT ''",
    ]),
    # S-139: the issue event outbox — one outbound row per
    # audited issue mutation, keyed by its audit seq
    # (UNIQUE, so materialising is exactly-once). Part XI's
    # feeds and Part XII's webhook worker consume this
    # store; the audit log remains the witness it derives
    # from.
    (48, [
        "CREATE TABLE issue_event_outbox ("
        "  id INTEGER PRIMARY KEY,"
        "  audit_seq INTEGER NOT NULL UNIQUE,"
        "  repo_id INTEGER NOT NULL,"
        "  actor_id INTEGER,"
        "  verb TEXT NOT NULL,"
        "  target_id TEXT NOT NULL,"
        "  detail_json TEXT NOT NULL DEFAULT '{}',"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_issue_event_outbox_repo"
        " ON issue_event_outbox (repo_id, id)",
    ]),
    # S-142: cross-fork pull requests — a PR whose head
    # branch lives in another repository (a fork of the
    # base repository) carries one row here naming the
    # head repository and the maintainer-edits permission
    # flag the author chose at opening. The PR's own row
    # (migration 46) keeps the branch pair and the oids
    # compared at opening; same-repository PRs have no
    # row here, so presence of a row IS the cross-fork
    # fact, never a flag that can disagree with it.
    (49, [
        "CREATE TABLE pull_request_forks ("
        "  pull_request_id INTEGER PRIMARY KEY,"
        "  head_repo_id INTEGER NOT NULL,"
        "  maintainer_can_edit INTEGER NOT NULL DEFAULT 1,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_pull_request_forks_head"
        " ON pull_request_forks (head_repo_id, pull_request_id)",
    ]),
    # S-145: per-reviewer viewed state for the PR files
    # view — one row per (pull request, reviewer, file)
    # recording the patch hash the reviewer actually saw.
    # A later push that changes that file's patch changes
    # its hash, so the stored row no longer vouches for
    # the current patch (the file reads as changed since
    # viewed, never silently as still viewed).
    (50, [
        "CREATE TABLE pull_request_file_views ("
        "  id INTEGER PRIMARY KEY,"
        "  pull_request_id INTEGER NOT NULL,"
        "  user_id INTEGER NOT NULL,"
        "  file_path TEXT NOT NULL,"
        "  head_oid TEXT NOT NULL,"
        "  patch_hash TEXT NOT NULL,"
        "  viewed_at INTEGER NOT NULL,"
        "  UNIQUE (pull_request_id, user_id, file_path)"
        ")",
        "CREATE INDEX idx_pr_file_views_pr_user"
        " ON pull_request_file_views (pull_request_id, user_id)",
    ]),
    # S-146: line comments — a comment anchored to one
    # line of a pull request's diff (file, side, line
    # number, the line's text, and the head oid it was
    # written against). The stored text + anchor are
    # what outdated marking is judged from on every
    # read: if the current diff no longer carries that
    # exact line at that exact place, the comment is
    # outdated — the record is never moved silently.
    # Edits keep their previous bodies, deletion is a
    # tombstone, exactly as S-123's comment record.
    (51, [
        "CREATE TABLE pull_request_line_comments ("
        "  id INTEGER PRIMARY KEY,"
        "  pull_request_id INTEGER NOT NULL,"
        "  author_id INTEGER NOT NULL,"
        "  file_path TEXT NOT NULL,"
        "  side TEXT NOT NULL,"
        "  line_number INTEGER NOT NULL,"
        "  line_text TEXT NOT NULL,"
        "  head_oid TEXT NOT NULL,"
        "  body TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  edited_at INTEGER,"
        "  deleted_at INTEGER,"
        "  deleted_by INTEGER"
        ")",
        "CREATE INDEX idx_pr_line_comments_pr"
        " ON pull_request_line_comments (pull_request_id, id)",
        "CREATE TABLE pull_request_line_comment_edits ("
        "  id INTEGER PRIMARY KEY,"
        "  comment_id INTEGER NOT NULL,"
        "  editor_id INTEGER NOT NULL,"
        "  previous_body TEXT NOT NULL,"
        "  edited_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_pr_line_comment_edits_comment"
        " ON pull_request_line_comment_edits (comment_id, id)",
    ]),
    # S-147: review threads — replies on a line comment
    # and the thread's resolution state. A thread's
    # root is its S-146 line comment; the resolution
    # record exists only while the thread is resolved
    # (unresolving removes it — the audit log keeps
    # the history of both acts). Replies carry S-123's
    # honest record: edit history + tombstone deletion.
    (52, [
        "CREATE TABLE pull_request_review_threads ("
        "  comment_id INTEGER PRIMARY KEY,"
        "  resolved_by INTEGER NOT NULL,"
        "  resolved_at INTEGER NOT NULL"
        ")",
        "CREATE TABLE pull_request_line_replies ("
        "  id INTEGER PRIMARY KEY,"
        "  comment_id INTEGER NOT NULL,"
        "  author_id INTEGER NOT NULL,"
        "  body TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  edited_at INTEGER,"
        "  deleted_at INTEGER,"
        "  deleted_by INTEGER"
        ")",
        "CREATE INDEX idx_pr_line_replies_comment"
        " ON pull_request_line_replies (comment_id, id)",
        "CREATE TABLE pull_request_line_reply_edits ("
        "  id INTEGER PRIMARY KEY,"
        "  reply_id INTEGER NOT NULL,"
        "  editor_id INTEGER NOT NULL,"
        "  previous_body TEXT NOT NULL,"
        "  edited_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_pr_line_reply_edits_reply"
        " ON pull_request_line_reply_edits (reply_id, id)",
    ]),
    # S-148: review submission — a submitted review is
    # one row carrying its verdict, its summary, and the
    # head oid as it stood at submission (S-149's
    # freshness judgment reads it). A pending review is
    # the composer's autosaved draft: one row per (pull
    # request, reviewer), replaced whole on every save,
    # removed in the transaction that submits it.
    (53, [
        "CREATE TABLE pull_request_reviews ("
        "  id INTEGER PRIMARY KEY,"
        "  pull_request_id INTEGER NOT NULL,"
        "  reviewer_id INTEGER NOT NULL,"
        "  verdict TEXT NOT NULL,"
        "  summary TEXT NOT NULL DEFAULT '',"
        "  head_oid TEXT NOT NULL DEFAULT '',"
        "  submitted_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_pr_reviews_pr"
        " ON pull_request_reviews (pull_request_id, id)",
        "CREATE TABLE pull_request_pending_reviews ("
        "  pull_request_id INTEGER NOT NULL,"
        "  reviewer_id INTEGER NOT NULL,"
        "  verdict TEXT NOT NULL DEFAULT '',"
        "  summary TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  PRIMARY KEY (pull_request_id, reviewer_id)"
        ")",
    ]),
    # S-149: review freshness policy — one row per
    # repository naming how new pushes affect reviews
    # submitted against an older head (never / approvals
    # / verdicts). No row means the default, 'never':
    # reviews keep counting however the head moves.
    # Freshness itself is judged on read (a review's
    # stored head_oid against the current head), never
    # stored, so no per-review table is needed.
    (54, [
        "CREATE TABLE repo_review_freshness_policies ("
        "  repo_id INTEGER PRIMARY KEY,"
        "  mode TEXT NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  updated_by INTEGER"
        ")",
    ]),
    # S-150: suggested changes — one row per proposed
    # committable patch: its anchor (file + new-side
    # line range), the exact lines it replaces, the
    # replacement, and the head it was proposed
    # against. State is pending until an application
    # lands it, whose commit oid is recorded on the
    # row; outdated is judged on read, never stored.
    (55, [
        "CREATE TABLE pull_request_suggestions ("
        "  id INTEGER PRIMARY KEY,"
        "  pull_request_id INTEGER NOT NULL,"
        "  proposer_id INTEGER NOT NULL,"
        "  file_path TEXT NOT NULL,"
        "  start_line INTEGER NOT NULL,"
        "  end_line INTEGER NOT NULL,"
        "  original_text TEXT NOT NULL DEFAULT '',"
        "  replacement_text TEXT NOT NULL DEFAULT '',"
        "  body TEXT NOT NULL DEFAULT '',"
        "  head_oid TEXT NOT NULL DEFAULT '',"
        "  state TEXT NOT NULL DEFAULT 'pending',"
        "  applied_commit_oid TEXT NOT NULL DEFAULT '',"
        "  applied_by INTEGER,"
        "  created_at INTEGER NOT NULL,"
        "  applied_at INTEGER"
        ")",
        "CREATE INDEX idx_pr_suggestions_pr"
        " ON pull_request_suggestions (pull_request_id, id)",
    ]),
    # S-151: CODEOWNERS review requests — one row per
    # (pull request, owner token, source): the token
    # verbatim, the account it resolves to when it is a
    # plain @username that exists (NULL otherwise), and
    # the head oid the request was computed against.
    # S-152's manual requests ride the same table with
    # source='manual'.
    (56, [
        "CREATE TABLE pull_request_review_requests ("
        "  id INTEGER PRIMARY KEY,"
        "  pull_request_id INTEGER NOT NULL,"
        "  owner_ref TEXT NOT NULL,"
        "  user_id INTEGER,"
        "  source TEXT NOT NULL,"
        "  head_oid TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (pull_request_id, owner_ref, source)"
        ")",
        "CREATE INDEX idx_pr_review_requests_pr"
        " ON pull_request_review_requests (pull_request_id, id)",
    ]),
    # S-152: review assignment — dismissal and re-request
    # state on the S-151 request rows (a dismissal is a
    # recorded act, never a deletion: state, who, and
    # when ride the row), the re-request count, and the
    # per-act event record that keeps the whole history
    # provable after a re-request clears the stamp.
    (57, [
        "ALTER TABLE pull_request_review_requests ADD COLUMN"
        " state TEXT NOT NULL DEFAULT 'requested'",
        "ALTER TABLE pull_request_review_requests ADD COLUMN"
        " dismissed_by INTEGER",
        "ALTER TABLE pull_request_review_requests ADD COLUMN"
        " dismissed_at INTEGER",
        "ALTER TABLE pull_request_review_requests ADD COLUMN"
        " rerequest_count INTEGER NOT NULL DEFAULT 0",
        "CREATE TABLE pull_request_review_request_events ("
        "  id INTEGER PRIMARY KEY,"
        "  review_request_id INTEGER NOT NULL,"
        "  pull_request_id INTEGER NOT NULL,"
        "  owner_ref TEXT NOT NULL,"
        "  source TEXT NOT NULL,"
        "  kind TEXT NOT NULL,"
        "  actor_id INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_pr_review_request_events_request"
        " ON pull_request_review_request_events"
        " (review_request_id, id)",
    ]),
    # S-153: the merge record — one row per landing: the
    # merge commit, the branch pair, both parents as they
    # stood when it landed, the message verbatim, and who
    # merged. A pull request lands once (UNIQUE), in the
    # record as in git.
    (58, [
        "CREATE TABLE pull_request_merges ("
        "  id INTEGER PRIMARY KEY,"
        "  pull_request_id INTEGER NOT NULL UNIQUE,"
        "  repo_id INTEGER NOT NULL,"
        "  merge_commit_oid TEXT NOT NULL,"
        "  base_branch TEXT NOT NULL,"
        "  head_branch TEXT NOT NULL,"
        "  base_oid TEXT NOT NULL,"
        "  head_oid TEXT NOT NULL,"
        "  message TEXT NOT NULL,"
        "  merged_by INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_pr_merges_repo"
        " ON pull_request_merges (repo_id, pull_request_id)",
    ]),
    # S-154 (banking reconciliation, keeper): the squash
    # record extends the merges table S-153 created.
    # Migration 58 landed with the merge-commit shape;
    # the squash shape also needs strategy, merged_at
    # and message_edited, and its inserts omit repo_id
    # and message. SQLite cannot relax a column in
    # place, so the table is rebuilt in the unified
    # shape and every row copied across (merge-commit
    # rows gain strategy 'merge_commit', merged_at =
    # created_at, message_edited 0). The closings
    # table below is S-154's own, as designed.
    (59, [
        "CREATE TABLE pull_request_merges_unified ("
        "  id INTEGER PRIMARY KEY,"
        "  pull_request_id INTEGER NOT NULL UNIQUE,"
        "  repo_id INTEGER,"
        "  strategy TEXT NOT NULL DEFAULT 'merge_commit',"
        "  merge_commit_oid TEXT NOT NULL,"
        "  base_branch TEXT NOT NULL,"
        "  head_branch TEXT NOT NULL,"
        "  base_oid TEXT NOT NULL,"
        "  head_oid TEXT NOT NULL,"
        "  message TEXT,"
        "  merged_by INTEGER NOT NULL,"
        "  created_at INTEGER,"
        "  merged_at INTEGER,"
        "  message_edited INTEGER NOT NULL DEFAULT 0"
        ")",
        "INSERT INTO pull_request_merges_unified"
        " (id, pull_request_id, repo_id, strategy,"
        " merge_commit_oid, base_branch, head_branch,"
        " base_oid, head_oid, message, merged_by,"
        " created_at, merged_at, message_edited)"
        " SELECT id, pull_request_id, repo_id,"
        " 'merge_commit', merge_commit_oid, base_branch,"
        " head_branch, base_oid, head_oid, message,"
        " merged_by, created_at, created_at, 0"
        " FROM pull_request_merges",
        "DROP TABLE pull_request_merges",
        "ALTER TABLE pull_request_merges_unified"
        " RENAME TO pull_request_merges",
        "CREATE INDEX idx_pr_merges_repo"
        " ON pull_request_merges (repo_id, pull_request_id)",
        "CREATE TABLE IF NOT EXISTS"
        " pull_request_merge_closings ("
        "  id INTEGER PRIMARY KEY,"
        "  pull_request_id INTEGER NOT NULL,"
        "  target_repo_id INTEGER NOT NULL,"
        "  target_number INTEGER NOT NULL,"
        "  outcome TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX IF NOT EXISTS idx_pr_merge_closings_pr"
        " ON pull_request_merge_closings (pull_request_id, id)",
    ]),
    # S-157: checks panel — one row per external check
    # result reported against a commit: the repository
    # it was recorded against, the check's name verbatim,
    # its state in the roadmap's three words, the
    # external details link and a one-line description,
    # with the stamps of first landing and last change.
    # Unique per (repository, commit, context): a
    # re-report updates the row, never duplicates it.
    (60, [
        "CREATE TABLE commit_checks ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  head_oid TEXT NOT NULL,"
        "  context TEXT NOT NULL,"
        "  state TEXT NOT NULL DEFAULT 'pending',"
        "  target_url TEXT NOT NULL DEFAULT '',"
        "  description TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, head_oid, context)"
        ")",
        "CREATE INDEX idx_commit_checks_repo_head"
        " ON commit_checks (repo_id, head_oid, id)",
    ]),
    # S-158: the auto-merge record — the queue of one per
    # pull request (UNIQUE): its state, the strategy the
    # landing will use, the check contexts that must
    # pass, who armed it against which head, and the
    # stamps of every later act; plus its events table,
    # one row per act, so the whole history stays
    # provable after any later cycle re-arms the row.
    (61, [
        "CREATE TABLE pull_request_auto_merges ("
        "  id INTEGER PRIMARY KEY,"
        "  pull_request_id INTEGER NOT NULL UNIQUE,"
        "  repo_id INTEGER NOT NULL,"
        "  state TEXT NOT NULL DEFAULT 'armed',"
        "  strategy TEXT NOT NULL DEFAULT 'merge',"
        "  required_checks TEXT NOT NULL DEFAULT '[]',"
        "  armed_by INTEGER NOT NULL,"
        "  armed_at INTEGER NOT NULL,"
        "  head_oid TEXT NOT NULL,"
        "  cancelled_by INTEGER,"
        "  cancelled_at INTEGER,"
        "  fired_at INTEGER,"
        "  merge_commit_oid TEXT NOT NULL DEFAULT '',"
        "  last_evaluated_at INTEGER,"
        "  last_blockers TEXT NOT NULL DEFAULT '[]',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_pr_auto_merges_repo"
        " ON pull_request_auto_merges (repo_id, pull_request_id)",
        "CREATE TABLE pull_request_auto_merge_events ("
        "  id INTEGER PRIMARY KEY,"
        "  auto_merge_id INTEGER NOT NULL,"
        "  pull_request_id INTEGER NOT NULL,"
        "  kind TEXT NOT NULL,"
        "  actor_id INTEGER,"
        "  detail TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_pr_auto_merge_events_pr"
        " ON pull_request_auto_merge_events"
        " (pull_request_id, id)",
    ]),
    # S-159: branch housekeeping — the
    # delete-head-branch-on-merge opt-in rides the
    # S-066 settings row (default 0: an opt-in deletes
    # nothing until it is switched on), and the
    # deleted-branch tombstone a restore acts on: one
    # row per merge-born deletion naming the branch,
    # the oid it pointed at when deleted, the pull
    # request and merge that caused it; restoring
    # stamps restored_at / restored_by on the row,
    # never deletes it.
    (62, [
        "ALTER TABLE repo_settings ADD COLUMN"
        " delete_branch_on_merge INTEGER NOT NULL DEFAULT 0",
        "CREATE TABLE deleted_branches ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  branch_name TEXT NOT NULL,"
        "  head_oid TEXT NOT NULL,"
        "  deleted_at INTEGER NOT NULL,"
        "  deleted_by INTEGER NOT NULL,"
        "  pull_request_id INTEGER NOT NULL,"
        "  pr_number INTEGER NOT NULL,"
        "  merge_oid TEXT NOT NULL DEFAULT '',"
        "  restored_at INTEGER,"
        "  restored_by INTEGER"
        ")",
        "CREATE INDEX idx_deleted_branches_repo"
        " ON deleted_branches (repo_id, id)",
        "CREATE INDEX idx_deleted_branches_pr"
        " ON deleted_branches (pull_request_id)",
    ]),
    # S-160: pull request reverts — one row per revert PR
    # linking it both ways to the merged PR it reverts: the
    # revert PR's own row id, the original's row id, the
    # landing pair the revert undid (merged_oid /
    # pre_merge_oid, as resolved by the PR layer), the
    # revert commit and branch, and who made it. Presence
    # of a row IS the link; one link per revert PR
    # (UNIQUE on pull_request_id).
    (63, [
        "CREATE TABLE pull_request_reverts ("
        "  id INTEGER PRIMARY KEY,"
        "  pull_request_id INTEGER NOT NULL UNIQUE,"
        "  original_pull_request_id INTEGER NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  merged_oid TEXT NOT NULL DEFAULT '',"
        "  pre_merge_oid TEXT NOT NULL DEFAULT '',"
        "  revert_commit_oid TEXT NOT NULL DEFAULT '',"
        "  revert_branch TEXT NOT NULL DEFAULT '',"
        "  base_branch TEXT NOT NULL DEFAULT '',"
        "  created_by INTEGER,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_pr_reverts_original"
        " ON pull_request_reverts (original_pull_request_id, id)",
    ]),
    # S-165: review notifications — one addressed row per
    # (audited review act, recipient): the Part XI
    # notification S-151/S-152's review requests and
    # S-148's submissions emit, keyed by its audit seq
    # and recipient under a UNIQUE pair (materialising
    # is exactly-once per recipient). The S-223 reason
    # is stored on the row; the audit detail rides along
    # unchanged. The audit log remains the witness this
    # store derives from.
    (64, [
        "CREATE TABLE pull_request_review_notifications ("
        "  id INTEGER PRIMARY KEY,"
        "  audit_seq INTEGER NOT NULL,"
        "  recipient_id INTEGER NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  pull_request_id INTEGER,"
        "  number INTEGER,"
        "  actor_id INTEGER,"
        "  verb TEXT NOT NULL,"
        "  reason TEXT NOT NULL,"
        "  detail_json TEXT NOT NULL DEFAULT '{}',"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (audit_seq, recipient_id)"
        ")",
        "CREATE INDEX idx_pr_review_notifications_recipient"
        " ON pull_request_review_notifications (recipient_id, id)",
        "CREATE INDEX idx_pr_review_notifications_pr"
        " ON pull_request_review_notifications (pull_request_id, id)",
    ]),
    # S-169: protection rules — one row per (repository,
    # branch-name pattern): the pattern the rule attaches
    # to and the whole Part VIII policy shape it carries
    # (S-170..S-180 each wire one field to its refusal
    # point; the model, the matching, and the documented
    # deterministic evaluation order live in
    # samverk/protection_rules.py). UNIQUE (repo_id,
    # pattern): a pattern names at most one rule per
    # repository, so rules are updated, never shadowed.
    (65, [
        "CREATE TABLE protection_rules ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  pattern TEXT NOT NULL,"
        "  enabled INTEGER NOT NULL DEFAULT 1,"
        "  require_pull_request INTEGER NOT NULL DEFAULT 0,"
        "  required_approvals INTEGER NOT NULL DEFAULT 0,"
        "  dismiss_stale_reviews INTEGER NOT NULL DEFAULT 0,"
        "  require_code_owner_review INTEGER NOT NULL DEFAULT 0,"
        "  required_status_checks TEXT NOT NULL DEFAULT '[]',"
        "  require_branch_up_to_date INTEGER NOT NULL DEFAULT 0,"
        "  require_signed_commits INTEGER NOT NULL DEFAULT 0,"
        "  require_linear_history INTEGER NOT NULL DEFAULT 0,"
        "  block_force_pushes INTEGER NOT NULL DEFAULT 1,"
        "  block_branch_deletion INTEGER NOT NULL DEFAULT 1,"
        "  enforce_admins INTEGER NOT NULL DEFAULT 1,"
        "  allowed_push_actors TEXT NOT NULL DEFAULT '[]',"
        "  bypass_actors TEXT NOT NULL DEFAULT '[]',"
        "  created_by INTEGER,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, pattern)"
        ")",
        "CREATE INDEX idx_protection_rules_repo"
        " ON protection_rules (repo_id, id)",
    ]),
    # S-171: required approving reviews — the last-pusher
    # approval toggle joins the protection rule shape the
    # S-169 model stores (the approval count itself has
    # lived there since migration 65). Default off: a
    # rule opts in, and S-171's gate then refuses to
    # count an approval from the most recent pusher of
    # the pull request's head branch.
    (66, [
        "ALTER TABLE protection_rules ADD COLUMN"
        " require_last_pusher_approval INTEGER NOT NULL DEFAULT 0",
    ]),
    # S-181: rulesets — one row per ruleset: its name
    # (unique across the instance, case-insensitively,
    # via name_lower), its target (branch / tag / all),
    # the repository / branch / tag name patterns it
    # aims at (JSON lists, judged by S-169's glob), and
    # the whole Part VIII policy shape it carries — the
    # same columns migration 65 gave protection_rules,
    # because a ruleset generalises a rule and layers
    # over per-repository rules with S-169's own
    # most-restrictive-wins fold (the model, targeting,
    # ordering, and layered evaluation live in
    # samverk/protection_rulesets.py).
    (67, [
        "CREATE TABLE protection_rulesets ("
        "  id INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  name_lower TEXT NOT NULL UNIQUE,"
        "  target TEXT NOT NULL DEFAULT 'branch',"
        "  repo_patterns TEXT NOT NULL DEFAULT '[]',"
        "  branch_patterns TEXT NOT NULL DEFAULT '[]',"
        "  tag_patterns TEXT NOT NULL DEFAULT '[]',"
        "  enabled INTEGER NOT NULL DEFAULT 1,"
        "  require_pull_request INTEGER NOT NULL DEFAULT 0,"
        "  required_approvals INTEGER NOT NULL DEFAULT 0,"
        "  require_last_pusher_approval INTEGER NOT NULL DEFAULT 0,"
        "  dismiss_stale_reviews INTEGER NOT NULL DEFAULT 0,"
        "  require_code_owner_review INTEGER NOT NULL DEFAULT 0,"
        "  required_status_checks TEXT NOT NULL DEFAULT '[]',"
        "  require_branch_up_to_date INTEGER NOT NULL DEFAULT 0,"
        "  require_signed_commits INTEGER NOT NULL DEFAULT 0,"
        "  require_linear_history INTEGER NOT NULL DEFAULT 0,"
        "  block_force_pushes INTEGER NOT NULL DEFAULT 1,"
        "  block_branch_deletion INTEGER NOT NULL DEFAULT 1,"
        "  enforce_admins INTEGER NOT NULL DEFAULT 1,"
        "  allowed_push_actors TEXT NOT NULL DEFAULT '[]',"
        "  bypass_actors TEXT NOT NULL DEFAULT '[]',"
        "  created_by INTEGER,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_protection_rulesets_name"
        " ON protection_rulesets (name_lower, id)",
    ]),
    # S-185: organizations — one row per organization:
    # its name (unique case-insensitively via
    # name_lower, in the same owner namespace as user
    # accounts), its profile (display name, bio,
    # website, and the S-012 avatar facts plus the
    # mandatory alt text), and its recorded creator —
    # the steward until S-186's membership lands (the
    # model lives in samverk/organizations.py).
    (68, [
        "CREATE TABLE organizations ("
        "  id INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  name_lower TEXT NOT NULL UNIQUE,"
        "  display_name TEXT,"
        "  bio TEXT,"
        "  website TEXT,"
        "  avatar_sha256 TEXT,"
        "  avatar_content_type TEXT,"
        "  avatar_alt TEXT,"
        "  created_by INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_organizations_name"
        " ON organizations (name_lower, id)",
    ]),
    # S-186: organization membership — one row per
    # (organization, user) pair: the member's role
    # (owner or member), who added them, and the
    # row's timestamps. The last-owner invariant
    # itself lives in
    # samverk/organization_members.py; this table
    # only stores the facts it judges.
    (69, [
        "CREATE TABLE organization_members ("
        "  org_id INTEGER NOT NULL,"
        "  user_id INTEGER NOT NULL,"
        "  role TEXT NOT NULL,"
        "  added_by INTEGER,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  PRIMARY KEY (org_id, user_id)"
        ")",
        "CREATE INDEX idx_organization_members_org"
        " ON organization_members (org_id)",
    ]),
    # S-187: teams — one row per team inside an
    # organization (name unique inside the org via
    # (org_id, name_lower) slug), its members (org
    # members only, judged in samverk/teams.py), and
    # its linked repositories (what a team may do in
    # a linked repo — the permission ladder — is
    # S-189; this table only stores the linkage).
    (70, [
        "CREATE TABLE teams ("
        "  id INTEGER PRIMARY KEY,"
        "  org_id INTEGER NOT NULL,"
        "  name TEXT NOT NULL,"
        "  name_lower TEXT NOT NULL,"
        "  description TEXT,"
        "  privacy TEXT NOT NULL DEFAULT 'visible',"
        "  created_by INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (org_id, name_lower)"
        ")",
        "CREATE INDEX idx_teams_org"
        " ON teams (org_id, id)",
        "CREATE TABLE team_members ("
        "  team_id INTEGER NOT NULL,"
        "  user_id INTEGER NOT NULL,"
        "  added_by INTEGER,"
        "  created_at INTEGER NOT NULL,"
        "  PRIMARY KEY (team_id, user_id)"
        ")",
        "CREATE INDEX idx_team_members_team"
        " ON team_members (team_id)",
        "CREATE TABLE team_repositories ("
        "  team_id INTEGER NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  added_by INTEGER,"
        "  created_at INTEGER NOT NULL,"
        "  PRIMARY KEY (team_id, repo_id)"
        ")",
        "CREATE INDEX idx_team_repositories_team"
        " ON team_repositories (team_id)",
        "CREATE INDEX idx_team_repositories_repo"
        " ON team_repositories (repo_id)",
    ]),
    # S-188: nested teams — a team may name one parent
    # team in the same organization (NULL = a root).
    # Inheritance is judged in samverk/team_nesting.py.
    (71, [
        "ALTER TABLE teams ADD COLUMN parent_team_id INTEGER",
        "CREATE INDEX idx_teams_parent"
        " ON teams (parent_team_id)",
    ]),
    # S-189: team repository permissions — the ladder
    # role a team holds in a linked repository, stored
    # on S-187's link itself. Existing links start at
    # the ladder's foot, read. The ladder is judged in
    # samverk/team_permissions.py.
    (72, [
        "ALTER TABLE team_repositories"
        " ADD COLUMN permission TEXT NOT NULL DEFAULT 'read'",
    ]),
    # S-191: outside collaborators — per-repo grants
    # to non-members, one row per (repository, person)
    # pair with its S-189 ladder role, its granter and
    # its times. Judged in
    # samverk/outside_collaborators.py.
    (73, [
        "CREATE TABLE outside_collaborators ("
        "  repo_id INTEGER NOT NULL,"
        "  user_id INTEGER NOT NULL,"
        "  role TEXT NOT NULL,"
        "  granted_by INTEGER,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  PRIMARY KEY (repo_id, user_id)"
        ")",
        "CREATE INDEX idx_outside_collaborators_repo"
        " ON outside_collaborators (repo_id)",
        "CREATE INDEX idx_outside_collaborators_user"
        " ON outside_collaborators (user_id)",
    ]),
    # S-192: default repository permission — the
    # org-wide base ladder role for members, one
    # row per organization that has set one; no
    # row means none. Judged in
    # samverk/default_permissions.py.
    (74, [
        "CREATE TABLE org_default_permissions ("
        "  org_id INTEGER NOT NULL PRIMARY KEY,"
        "  role TEXT NOT NULL,"
        "  set_by INTEGER,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL"
        ")",
    ]),
    # S-193: organization invitations — invite by
    # username or email, expiring, rescindable; one
    # row per invitation with its target, role,
    # inviter, status and times. Judged in
    # samverk/invitations.py.
    (75, [
        "CREATE TABLE org_invitations ("
        "  id INTEGER PRIMARY KEY,"
        "  org_id INTEGER NOT NULL,"
        "  invitee_user_id INTEGER,"
        "  invitee_email TEXT,"
        "  invitee_email_lower TEXT,"
        "  role TEXT NOT NULL,"
        "  invited_by INTEGER NOT NULL,"
        "  status TEXT NOT NULL DEFAULT 'pending',"
        "  created_at INTEGER NOT NULL,"
        "  expires_at INTEGER NOT NULL,"
        "  resolved_at INTEGER"
        ")",
        "CREATE INDEX idx_org_invitations_org"
        " ON org_invitations (org_id)",
        "CREATE INDEX idx_org_invitations_user"
        " ON org_invitations (invitee_user_id)",
        "CREATE INDEX idx_org_invitations_email"
        " ON org_invitations (invitee_email_lower)",
    ]),
    # S-195: team mentions — one addressed notification
    # row per (source, team, recipient): a prose mention
    # in an issue/PR body or comment, or a standing team
    # review request, expanded to the team's S-188
    # effective members. Judged in samverk/team_mentions.py.
    (76, [
        "CREATE TABLE team_mention_notifications ("
        "  id INTEGER PRIMARY KEY,"
        "  org_id INTEGER NOT NULL,"
        "  team_id INTEGER NOT NULL,"
        "  mention TEXT NOT NULL,"
        "  recipient_id INTEGER NOT NULL,"
        "  actor_id INTEGER,"
        "  source_kind TEXT NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  number INTEGER NOT NULL,"
        "  comment_id INTEGER NOT NULL DEFAULT 0,"
        "  pull_request_id INTEGER NOT NULL DEFAULT 0,"
        "  reason TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (source_kind, repo_id, number, comment_id,"
        "          pull_request_id, team_id, recipient_id)"
        ")",
        "CREATE INDEX idx_team_mentions_recipient"
        " ON team_mention_notifications (recipient_id, id)",
        "CREATE INDEX idx_team_mentions_item"
        " ON team_mention_notifications (repo_id, number, id)",
        "CREATE INDEX idx_team_mentions_team"
        " ON team_mention_notifications (team_id, id)",
    ]),
    # S-196: org repository creation policies — who
    # may create and which visibilities are allowed,
    # one row per organization that has set a policy;
    # no row means the default (owners; public and
    # private). Judged in samverk/org_repositories.py.
    (77, [
        "CREATE TABLE org_repo_policies ("
        "  org_id INTEGER NOT NULL PRIMARY KEY,"
        "  who_may_create TEXT NOT NULL,"
        "  allowed_visibilities TEXT NOT NULL,"
        "  set_by INTEGER,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL"
        ")",
    ]),
    # S-199: org deletion requests — the grace-period
    # record. One pending request per organization;
    # execution after scheduled_at is the irreversible
    # step. Judged in samverk/org_deletion.py.
    (78, [
        "CREATE TABLE org_deletions ("
        "  org_id INTEGER PRIMARY KEY,"
        "  requested_by INTEGER NOT NULL,"
        "  requested_at INTEGER NOT NULL,"
        "  scheduled_at INTEGER NOT NULL"
        ")",
    ]),
    # S-203: instance-wide groups — site-level groups
    # shaped exactly like S-187's teams, minus the
    # organization: one row per group (slug unique
    # across the whole instance), its members (any
    # account on the instance), its linked
    # repositories (any repository, carrying S-189's
    # ladder permission), and one parent group for
    # S-188-shaped nesting. Judged in
    # samverk/instance_groups.py.
    (79, [
        "CREATE TABLE instance_groups ("
        "  id INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  name_lower TEXT NOT NULL UNIQUE,"
        "  description TEXT,"
        "  privacy TEXT NOT NULL DEFAULT 'visible',"
        "  parent_group_id INTEGER,"
        "  created_by INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL"
        ")",
        "CREATE TABLE instance_group_members ("
        "  group_id INTEGER NOT NULL,"
        "  user_id INTEGER NOT NULL,"
        "  added_by INTEGER,"
        "  created_at INTEGER NOT NULL,"
        "  PRIMARY KEY (group_id, user_id)"
        ")",
        "CREATE INDEX idx_instance_group_members_group"
        " ON instance_group_members (group_id)",
        "CREATE INDEX idx_instance_group_members_user"
        " ON instance_group_members (user_id)",
        "CREATE TABLE instance_group_repositories ("
        "  group_id INTEGER NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  permission TEXT NOT NULL DEFAULT 'read',"
        "  added_by INTEGER,"
        "  created_at INTEGER NOT NULL,"
        "  PRIMARY KEY (group_id, repo_id)"
        ")",
        "CREATE INDEX idx_instance_group_repos_group"
        " ON instance_group_repositories (group_id)",
        "CREATE INDEX idx_instance_group_repos_repo"
        " ON instance_group_repositories (repo_id)",
    ]),
    # S-205: search index architecture — the background
    # index queue (one row per pending/running/finished
    # unit of indexing work, coalesced by dedupe_key),
    # the per-(repository, kind) index state (status,
    # generation, high-water mark), and the document
    # registry later Part X slices write their indexed
    # documents into (keyed by generation, so a rebuild
    # never serves stale-generation rows). Judged in
    # samverk/index_architecture.py.
    (80, [
        "CREATE TABLE index_jobs ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  kind TEXT NOT NULL,"
        "  trigger_kind TEXT NOT NULL,"
        "  target TEXT NOT NULL DEFAULT '',"
        "  dedupe_key TEXT NOT NULL UNIQUE,"
        "  status TEXT NOT NULL DEFAULT 'pending',"
        "  attempts INTEGER NOT NULL DEFAULT 0,"
        "  generation INTEGER NOT NULL DEFAULT 0,"
        "  enqueued_at INTEGER NOT NULL,"
        "  started_at INTEGER,"
        "  finished_at INTEGER,"
        "  last_error TEXT NOT NULL DEFAULT ''"
        ")",
        "CREATE INDEX idx_index_jobs_pending"
        " ON index_jobs (status, id)",
        "CREATE INDEX idx_index_jobs_repo"
        " ON index_jobs (repo_id, kind, id)",
        "CREATE TABLE index_state ("
        "  repo_id INTEGER NOT NULL,"
        "  kind TEXT NOT NULL,"
        "  status TEXT NOT NULL DEFAULT 'never',"
        "  generation INTEGER NOT NULL DEFAULT 0,"
        "  high_water TEXT NOT NULL DEFAULT '',"
        "  updated_at INTEGER NOT NULL DEFAULT 0,"
        "  last_error TEXT NOT NULL DEFAULT '',"
        "  PRIMARY KEY (repo_id, kind)"
        ")",
        "CREATE TABLE index_documents ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  kind TEXT NOT NULL,"
        "  doc_key TEXT NOT NULL,"
        "  commit_oid TEXT NOT NULL DEFAULT '',"
        "  path TEXT NOT NULL DEFAULT '',"
        "  digest TEXT NOT NULL DEFAULT '',"
        "  generation INTEGER NOT NULL DEFAULT 0,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, kind, doc_key)"
        ")",
        "CREATE INDEX idx_index_documents_repo"
        " ON index_documents (repo_id, kind, generation)",
    ]),
    # S-206: issue/PR search backend — the FTS5 index
    # the unified qualifier language executes over.
    # One row per numbered item (rowid is the shared
    # issues row id): title and body are the indexed
    # text; every other column is a structured field
    # denormalised at index time (repository, number,
    # kind, state, author, labels, assignees,
    # milestone, draft and branch pair for pull
    # requests, the latest review position, and the
    # created/updated/comment facts the date and
    # sort qualifiers judge). Judged in
    # samverk/issue_pr_search.py.
    (81, [
        "CREATE VIRTUAL TABLE issue_pr_fts USING fts5("
        "  title, body,"
        "  repo_id UNINDEXED, number UNINDEXED,"
        "  kind UNINDEXED, state UNINDEXED,"
        "  author_lower UNINDEXED, labels_lower UNINDEXED,"
        "  assignees_lower UNINDEXED,"
        "  milestone_lower UNINDEXED, is_draft UNINDEXED,"
        "  base_branch UNINDEXED, head_branch UNINDEXED,"
        "  reviews_latest UNINDEXED,"
        "  reviews_total UNINDEXED,"
        "  review_requested UNINDEXED,"
        "  created_at UNINDEXED, updated_at UNINDEXED,"
        "  comment_count UNINDEXED"
        ")",
    ]),
    # S-207: code indexing — the FTS5 index the push-time
    # extractor fills. One row per indexed file of the
    # default branch's tip snapshot: path and text are
    # the indexed text; repository, snapshot commit,
    # content digest (the blob oid), language,
    # disposition, and the LFS pointer facts (target oid
    # and size, recorded as claims about the LFS store —
    # never the pointee's bytes) ride as structured
    # fields. Judged in samverk/code_indexing.py.
    (82, [
        "CREATE VIRTUAL TABLE code_fts USING fts5("
        "  path, text,"
        "  repo_id UNINDEXED, commit_oid UNINDEXED,"
        "  digest UNINDEXED, language UNINDEXED,"
        "  disposition UNINDEXED, lfs_oid UNINDEXED,"
        "  lfs_size UNINDEXED, blob_size UNINDEXED"
        ")",
    ]),
    # S-213: global search UI -- per-user recent
    # searches for the one box. One row per (user,
    # query): the query as typed for display, its
    # trimmed lowercased dedup key, and when it was
    # last searched. Judged in
    # samverk/global_search.py (RecentSearchStore).
    (83, [
        "CREATE TABLE recent_searches ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  query TEXT NOT NULL,"
        "  query_lower TEXT NOT NULL,"
        "  searched_at INTEGER NOT NULL"
        ")",
        "CREATE UNIQUE INDEX idx_recent_searches_user_query"
        " ON recent_searches (user_id, query_lower)",
        "CREATE INDEX idx_recent_searches_user_recent"
        " ON recent_searches (user_id, searched_at DESC, id DESC)",
    ]),
    # S-214: saved searches -- a user's own named global
    # searches (any S-213 query), beyond S-136's per-repo
    # issue filters. One row per (user, name): the name
    # as typed, its lowercased uniqueness key, and the
    # query text as typed. Only the query text is stored
    # -- results are never cached; S-213's parser is the
    # validation seam at save time and GlobalSearch
    # executes the query again at run time. Judged in
    # samverk/saved_searches.py (SavedSearchStore).
    (84, [
        "CREATE TABLE saved_searches ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  name TEXT NOT NULL,"
        "  name_lower TEXT NOT NULL,"
        "  query TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (user_id, name_lower)"
        ")",
        "CREATE INDEX idx_saved_searches_user"
        " ON saved_searches (user_id, name_lower)",
    ]),
    # S-221: the canonical event store -- one row per
    # witnessed mutation (keyed by its audit seq,
    # UNIQUE, so materialising is exactly-once): the
    # actor, the verb, the target, the derived refs
    # and the safe detail as JSON, the outcome, and
    # the witness's own timestamp. Part XI's feeds,
    # notifications and events API read here; the
    # audit log remains the witness it derives from.
    # Judged in samverk/event_store.py (EventStore).
    (85, [
        "CREATE TABLE events ("
        "  id INTEGER PRIMARY KEY,"
        "  audit_seq INTEGER NOT NULL UNIQUE,"
        "  actor_kind TEXT NOT NULL,"
        "  actor_id INTEGER,"
        "  verb TEXT NOT NULL,"
        "  target_kind TEXT NOT NULL,"
        "  target_id TEXT,"
        "  refs_json TEXT NOT NULL DEFAULT '[]',"
        "  detail_json TEXT NOT NULL DEFAULT '{}',"
        "  outcome TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_events_actor"
        " ON events (actor_id, id)",
        "CREATE INDEX idx_events_verb"
        " ON events (verb, id)",
    ]),
    # S-222: watch and star -- one watch row per
    # (repository, account) carrying its mode (all /
    # releases_only / ignore), and one star row per
    # (repository, account). Removing the act deletes
    # the row; counts are counted live from these rows,
    # never cached. Judged in samverk/watch_star.py
    # (WatchStarStore).
    (86, [
        "CREATE TABLE repo_watches ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  user_id INTEGER NOT NULL,"
        "  mode TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, user_id)"
        ")",
        "CREATE INDEX idx_repo_watches_repo"
        " ON repo_watches (repo_id, mode)",
        "CREATE TABLE repo_stars ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  user_id INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, user_id)"
        ")",
        "CREATE INDEX idx_repo_stars_repo"
        " ON repo_stars (repo_id, id)",
        "CREATE INDEX idx_repo_stars_user"
        " ON repo_stars (user_id, id)",
    ]),
    # S-223: notification reasons -- one notification
    # row per delivery, carrying its reason (one of
    # the seven in samverk/notification_reasons.py)
    # stored at creation and shown with the row.
    (87, [
        "CREATE TABLE notifications ("
        "  id INTEGER PRIMARY KEY,"
        "  recipient_id INTEGER NOT NULL,"
        "  actor_id INTEGER,"
        "  reason TEXT NOT NULL,"
        "  verb TEXT NOT NULL DEFAULT '',"
        "  target_kind TEXT NOT NULL DEFAULT '',"
        "  target_id TEXT NOT NULL DEFAULT '',"
        "  detail_json TEXT NOT NULL DEFAULT '{}',"
        "  created_at INTEGER NOT NULL,"
        "  read_at INTEGER"
        ")",
        "CREATE INDEX idx_notifications_recipient"
        " ON notifications (recipient_id, id)",
        "CREATE INDEX idx_notifications_reason"
        " ON notifications (recipient_id, reason, id)",
    ]),
    # S-224: inbox triage -- one row per notification
    # carrying its done and saved flags, kept distinct
    # from each other and from S-223's read_at; the
    # notification row itself is S-223's, untouched
    # except that done/reopen move read_at with them.
    (88, [
        "CREATE TABLE inbox_triage ("
        "  notification_id INTEGER PRIMARY KEY,"
        "  done_at INTEGER,"
        "  saved_at INTEGER"
        ")",
        "CREATE INDEX idx_inbox_triage_saved"
        " ON inbox_triage (saved_at)",
    ]),
    # S-225: thread subscriptions -- one override row
    # per (account, repository, thread kind, thread
    # number) carrying its state (subscribed / muted);
    # no row is inherit. Judged in
    # samverk/thread_subscriptions.py
    # (ThreadSubscriptionStore).
    (89, [
        "CREATE TABLE thread_overrides ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  thread_kind TEXT NOT NULL,"
        "  thread_number INTEGER NOT NULL,"
        "  state TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (user_id, repo_id, thread_kind, thread_number)"
        ")",
        "CREATE INDEX idx_thread_overrides_user"
        " ON thread_overrides (user_id, id)",
        "CREATE INDEX idx_thread_overrides_repo"
        " ON thread_overrides (repo_id, thread_kind, thread_number)",
    ]),
    # S-226: mention deliveries -- the exactly-once
    # ledger: one row per (source, recipient) for a
    # routed @user / @org/team mention, pointing at
    # the S-223 notification it delivered (reason
    # `mention`). Judged in
    # samverk/mention_routing.py (MentionRoutingStore).
    (90, [
        "CREATE TABLE mention_deliveries ("
        "  id INTEGER PRIMARY KEY,"
        "  notification_id INTEGER NOT NULL UNIQUE,"
        "  recipient_id INTEGER NOT NULL,"
        "  actor_id INTEGER,"
        "  source_kind TEXT NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  number INTEGER NOT NULL,"
        "  comment_id INTEGER NOT NULL DEFAULT 0,"
        "  via_json TEXT NOT NULL DEFAULT '[]',"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (source_kind, repo_id, number, comment_id,"
        "          recipient_id)"
        ")",
        "CREATE INDEX idx_mention_deliveries_recipient"
        " ON mention_deliveries (recipient_id, id)",
        "CREATE INDEX idx_mention_deliveries_item"
        " ON mention_deliveries (repo_id, number, id)",
    ]),
    # S-227: email notifications -- one delivery row
    # per S-223 notification (UNIQUE, the exactly-once
    # enforcement) carrying the decision that was made
    # for it, and the opt-out rows signed unsubscribe
    # links write (one per account + scope, scope being
    # a reason or `all`). Judged in
    # samverk/email_notifications.py
    # (EmailNotificationStore).
    (91, [
        "CREATE TABLE email_deliveries ("
        "  id INTEGER PRIMARY KEY,"
        "  notification_id INTEGER NOT NULL UNIQUE,"
        "  recipient_id INTEGER NOT NULL,"
        "  email_address TEXT NOT NULL DEFAULT '',"
        "  mode TEXT NOT NULL,"
        "  status TEXT NOT NULL,"
        "  why TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  sent_at INTEGER"
        ")",
        "CREATE INDEX idx_email_deliveries_recipient"
        " ON email_deliveries (recipient_id, id)",
        "CREATE INDEX idx_email_deliveries_status"
        " ON email_deliveries (status, id)",
        "CREATE TABLE email_optouts ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  scope TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (user_id, scope)"
        ")",
        "CREATE INDEX idx_email_optouts_user"
        " ON email_optouts (user_id, id)",
    ]),
    # S-228: notification preferences -- one row per
    # account carrying the digest cadence the person
    # chose (immediate / daily / weekly); no row is
    # the immediate default. Email on/off lives in
    # S-227's email_optouts and watches in S-222's
    # repo_watches -- this slice adds no second
    # record of either. Judged in
    # samverk/notification_preferences.py
    # (NotificationPreferencesStore).
    (92, [
        "CREATE TABLE notification_preferences ("
        "  user_id INTEGER PRIMARY KEY,"
        "  digest_cadence TEXT NOT NULL,"
        "  updated_at INTEGER NOT NULL"
        ")",
    ]),
    # S-232: following -- one follow row per
    # (follower, followed) account pair; removing
    # the act deletes the row; counts are counted
    # live from these rows, never cached. Judged in
    # samverk/following.py (FollowingStore).
    (93, [
        "CREATE TABLE user_follows ("
        "  id INTEGER PRIMARY KEY,"
        "  follower_id INTEGER NOT NULL,"
        "  followed_id INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (follower_id, followed_id)"
        ")",
        "CREATE INDEX idx_user_follows_followed"
        " ON user_follows (followed_id, id)",
        "CREATE INDEX idx_user_follows_follower"
        " ON user_follows (follower_id, id)",
    ]),
    # S-235: weekly digests -- one composed digest
    # per account per week (UNIQUE, the job's
    # exactly-once law), carrying the letter as
    # composed from S-221's event store at compose
    # time: its window, its standing (composed /
    # empty / sent), the event ids it gathered,
    # the event payloads, and the subject and body
    # word for word. Judged in
    # samverk/digest_job.py (DigestJobStore).
    (94, [
        "CREATE TABLE weekly_digests ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  week_start INTEGER NOT NULL,"
        "  week_end INTEGER NOT NULL,"
        "  status TEXT NOT NULL,"
        "  event_ids_json TEXT NOT NULL DEFAULT '[]',"
        "  events_json TEXT NOT NULL DEFAULT '[]',"
        "  subject TEXT NOT NULL DEFAULT '',"
        "  body TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  sent_at INTEGER,"
        "  UNIQUE (user_id, week_start)"
        ")",
        "CREATE INDEX idx_weekly_digests_user"
        " ON weekly_digests (user_id, week_start)",
        "CREATE INDEX idx_weekly_digests_status"
        " ON weekly_digests (status, id)",
    ]),
    # S-246: status and checks API -- the poster's
    # name carried on S-157's one record, and the
    # check runs' own table: one row per run per
    # (repository, commit, name), in the run
    # vocabulary (status + conclusion), with its
    # poster and stamps; a re-post updates the row.
    # Judged in samverk/api_checks.py
    # (StatusChecksAPI); the fold onto commit_checks
    # is that face's law.
    (95, [
        "ALTER TABLE commit_checks"
        " ADD COLUMN poster TEXT NOT NULL DEFAULT ''",
        "CREATE TABLE check_runs ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  head_oid TEXT NOT NULL,"
        "  name TEXT NOT NULL,"
        "  status TEXT NOT NULL DEFAULT 'queued',"
        "  conclusion TEXT NOT NULL DEFAULT '',"
        "  poster TEXT NOT NULL DEFAULT '',"
        "  target_url TEXT NOT NULL DEFAULT '',"
        "  description TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, head_oid, name)"
        ")",
        "CREATE INDEX idx_check_runs_repo_head"
        " ON check_runs (repo_id, head_oid, id)",
    ]),
    # S-248: webhook subscriptions -- one row per
    # subscription at repository or organization
    # level (exactly one parent id set), carrying
    # the delivery address and its host, the filter
    # as chosen (S-247 verbs and categories, as
    # JSON), the active standing, and the secret's
    # SHA-256 digest only -- the secret itself is
    # never stored. The table is named webhooks,
    # not webhook_subscriptions, because S-202's
    # billing audit forbids billing-shaped names
    # for tables -- and a webhook subscription is
    # not a billing subscription (S-225's law).
    # Judged in
    # samverk/webhook_subscriptions.py
    # (WebhookSubscriptionStore).
    (96, [
        "CREATE TABLE webhooks ("
        "  id INTEGER PRIMARY KEY,"
        "  level TEXT NOT NULL,"
        "  repo_id INTEGER,"
        "  org_id INTEGER,"
        "  parent_name TEXT NOT NULL,"
        "  parent_key TEXT NOT NULL,"
        "  url TEXT NOT NULL,"
        "  host TEXT NOT NULL,"
        "  events_json TEXT NOT NULL DEFAULT '[]',"
        "  categories_json TEXT NOT NULL DEFAULT '[]',"
        "  active INTEGER NOT NULL DEFAULT 1,"
        "  secret_digest TEXT NOT NULL DEFAULT '',"
        "  created_by INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_webhooks_repo"
        " ON webhooks (repo_id, id)",
        "CREATE INDEX idx_webhooks_org"
        " ON webhooks (org_id, id)",
    ]),
    # S-250: webhook deliveries -- the delivery
    # worker's outbox: one row per subscription x
    # event (UNIQUE, so enqueueing is exactly-once),
    # carrying the payload frozen at enqueue, the
    # delivery address snapshotted at enqueue, the
    # standing (queued / retrying / delivered /
    # dead), the attempt count, when the next
    # attempt falls due, and the last attempt's
    # redacted outcome (a status code and a reason,
    # never a response body). Attempts themselves
    # are rows of their own, so S-251's delivery log
    # reads history, not a summary. Judged in
    # samverk/webhook_delivery.py
    # (WebhookDeliveryStore).
    (97, [
        "CREATE TABLE webhook_deliveries ("
        "  id INTEGER PRIMARY KEY,"
        "  webhook_id INTEGER NOT NULL,"
        "  event_id INTEGER NOT NULL,"
        "  verb TEXT NOT NULL,"
        "  delivery_key TEXT NOT NULL,"
        "  url TEXT NOT NULL,"
        "  host TEXT NOT NULL,"
        "  payload_json TEXT NOT NULL,"
        "  status TEXT NOT NULL DEFAULT 'queued',"
        "  attempts INTEGER NOT NULL DEFAULT 0,"
        "  next_attempt_at INTEGER NOT NULL,"
        "  last_status_code INTEGER,"
        "  last_error TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  delivered_at INTEGER,"
        "  dead_at INTEGER"
        ")",
        "CREATE UNIQUE INDEX idx_webhook_deliveries_once"
        " ON webhook_deliveries (webhook_id, event_id)",
        "CREATE INDEX idx_webhook_deliveries_due"
        " ON webhook_deliveries (status, next_attempt_at, id)",
        "CREATE INDEX idx_webhook_deliveries_hook"
        " ON webhook_deliveries (webhook_id, id)",
        "CREATE TABLE webhook_delivery_attempts ("
        "  id INTEGER PRIMARY KEY,"
        "  delivery_id INTEGER NOT NULL,"
        "  attempt_number INTEGER NOT NULL,"
        "  status_code INTEGER,"
        "  error TEXT NOT NULL DEFAULT '',"
        "  duration_ms INTEGER NOT NULL DEFAULT 0,"
        "  started_at INTEGER NOT NULL,"
        "  finished_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_webhook_delivery_attempts_delivery"
        " ON webhook_delivery_attempts (delivery_id, id)",
    ]),
    # S-251: delivery log and redelivery -- a
    # redelivery is a NEW delivery of the same
    # subscription x event, so the outbox gains its
    # lineage: redelivery_of names the delivery a
    # row redelivers (NULL for an original enqueue)
    # and redelivery_number counts copies of the
    # pair (0 for the original). The exactly-once
    # index widens to the triple, so S-250's
    # original enqueue stays exactly-once at
    # number 0 while each redelivery takes the
    # next number. Judged in
    # samverk/webhook_delivery_log.py
    # (DeliveryLogStore).
    (98, [
        "ALTER TABLE webhook_deliveries"
        " ADD COLUMN redelivery_of INTEGER",
        "ALTER TABLE webhook_deliveries"
        " ADD COLUMN redelivery_number"
        " INTEGER NOT NULL DEFAULT 0",
        "DROP INDEX idx_webhook_deliveries_once",
        "CREATE UNIQUE INDEX idx_webhook_deliveries_once"
        " ON webhook_deliveries"
        " (webhook_id, event_id, redelivery_number)",
        "CREATE INDEX idx_webhook_deliveries_redelivery"
        " ON webhook_deliveries (redelivery_of, id)",
    ]),
    # S-252: webhook ping and test events -- the
    # synthetic-send ledger. One row per on-demand
    # send (a liveness ping under the event name
    # ping, or a sample test event under a real
    # S-247 verb), naming the subscription it was
    # sent to, the kind, the event name carried,
    # the outbox row it queued (delivery_id) and
    # that row's delivery key, and who sent it.
    # The payload bytes themselves live frozen on
    # the outbox row (S-250); this ledger is the
    # provenance that says the send was synthetic,
    # so a ping is never mistaken for a real event
    # and never deduped against one. Judged in
    # samverk/webhook_ping.py (WebhookPingStore).
    (99, [
        "CREATE TABLE webhook_pings ("
        "  id INTEGER PRIMARY KEY,"
        "  webhook_id INTEGER NOT NULL,"
        "  kind TEXT NOT NULL,"
        "  verb TEXT NOT NULL,"
        "  delivery_id INTEGER NOT NULL DEFAULT 0,"
        "  delivery_key TEXT NOT NULL,"
        "  actor_id INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_webhook_pings_hook"
        " ON webhook_pings (webhook_id, id)",
        "CREATE INDEX idx_webhook_pings_delivery"
        " ON webhook_pings (delivery_id)",
    ]),
    # S-257: releases — one row per (repository, tag):
    # the binding of a tag that stands in git to a title
    # and Markdown notes, with the tag's target commit
    # captured at creation and the door it came through
    # (web / api / tag_push) recorded as provenance.
    (100, [
        "CREATE TABLE releases ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  tag TEXT NOT NULL,"
        "  title TEXT NOT NULL,"
        "  notes TEXT NOT NULL DEFAULT '',"
        "  target_oid TEXT NOT NULL,"
        "  author_id INTEGER NOT NULL,"
        "  source TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, tag)"
        ")",
        "CREATE INDEX idx_releases_repo ON releases (repo_id, created_at)",
    ]),
    # S-258: release states — a draft flag (drafts are
    # private to repository writers) and a prerelease flag
    # (prereleases are marked in every listing) on the
    # S-257 releases row. Standing rows take the defaults:
    # published, not a prerelease — exactly what they were.
    (101, [
        "ALTER TABLE releases ADD COLUMN draft"
        " INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE releases ADD COLUMN prerelease"
        " INTEGER NOT NULL DEFAULT 0",
    ]),
    # S-259: release assets — one row per promoted asset
    # (its download count lives on the row) and one row
    # per open chunked-upload session, whose staged bytes
    # wait in quarantine until promotion judges them
    # under S-012. Staging files are named by session id.
    (102, [
        "CREATE TABLE release_assets ("
        "  id INTEGER PRIMARY KEY,"
        "  release_id INTEGER NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  name TEXT NOT NULL,"
        "  size INTEGER NOT NULL,"
        "  sha256 TEXT NOT NULL,"
        "  content_type TEXT NOT NULL,"
        "  download_count INTEGER NOT NULL DEFAULT 0,"
        "  uploader_id INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (release_id, name)"
        ")",
        "CREATE INDEX idx_release_assets_release"
        " ON release_assets (release_id, created_at)",
        "CREATE TABLE release_upload_sessions ("
        "  id INTEGER PRIMARY KEY,"
        "  release_id INTEGER NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  name TEXT NOT NULL,"
        "  declared_type TEXT,"
        "  expected_size INTEGER,"
        "  received INTEGER NOT NULL DEFAULT 0,"
        "  chunks INTEGER NOT NULL DEFAULT 0,"
        "  uploader_id INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  state TEXT NOT NULL DEFAULT 'open'"
        ")",
    ]),
    # S-262: release notification deliveries -- one
    # ledger row per (publication audit row, recipient),
    # materialised from the standing repo.release.publish
    # witness into an S-223 notification; the UNIQUE pair
    # is the exactly-once enforcement, and the stored tag
    # keeps a delivery honest if its release is later
    # deleted.
    (103, [
        "CREATE TABLE release_notification_deliveries ("
        "  id INTEGER PRIMARY KEY,"
        "  notification_id INTEGER NOT NULL UNIQUE,"
        "  audit_seq INTEGER NOT NULL,"
        "  recipient_id INTEGER NOT NULL,"
        "  actor_id INTEGER,"
        "  repo_id INTEGER NOT NULL,"
        "  release_id INTEGER,"
        "  tag TEXT NOT NULL,"
        "  watch_mode TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (audit_seq, recipient_id)"
        ")",
        "CREATE INDEX idx_release_notif_deliv_recipient"
        " ON release_notification_deliveries (recipient_id, id)",
        "CREATE INDEX idx_release_notif_deliv_release"
        " ON release_notification_deliveries (repo_id, release_id, id)",
    ]),
    # S-263: release signatures -- one row per detached
    # signature attached to a release: what it claims to
    # sign (the release, its checksums file, or one named
    # asset, whose name is kept on the row), the claimed
    # signer, the armoured text stored verbatim, and the
    # trust it stands in -- unverified until S-305's
    # verifier records what a check earned. The UNIQUE
    # row is the one-signature-per-signer-kind-target law.
    (104, [
        "CREATE TABLE release_signatures ("
        "  id INTEGER PRIMARY KEY,"
        "  release_id INTEGER NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  target_kind TEXT NOT NULL,"
        "  asset_id INTEGER,"
        "  asset_name TEXT NOT NULL DEFAULT '',"
        "  signer TEXT NOT NULL,"
        "  kind TEXT NOT NULL,"
        "  fingerprint TEXT NOT NULL DEFAULT '',"
        "  signature TEXT NOT NULL,"
        "  trust TEXT NOT NULL DEFAULT 'unverified',"
        "  verified_signer TEXT NOT NULL DEFAULT '',"
        "  attached_by INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (release_id, target_kind, asset_name, signer, kind)"
        ")",
        "CREATE INDEX idx_release_signatures_release"
        " ON release_signatures (release_id, created_at)",
    ]),
    # S-266: CI artifacts -- one row per promoted
    # artifact, tied to its commit (head_oid) and to
    # the standing S-246 check run that produced it
    # (check_run_id + the run's name kept verbatim),
    # carrying its sniffed type, digest, download
    # count, and its retention policy as data: the
    # chosen window (retention_days; 0 keeps forever)
    # and the expires_at stamp it computes (NULL when
    # forever) for S-267's off-path sweep to enforce.
    # One row per open chunked-upload session, whose
    # staged bytes wait in quarantine. Judged in
    # samverk/ci_artifacts.py (CIArtifactsAPI).
    (105, [
        "CREATE TABLE ci_artifacts ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  check_run_id INTEGER NOT NULL,"
        "  head_oid TEXT NOT NULL,"
        "  check_run TEXT NOT NULL,"
        "  name TEXT NOT NULL,"
        "  size INTEGER NOT NULL,"
        "  sha256 TEXT NOT NULL,"
        "  content_type TEXT NOT NULL,"
        "  download_count INTEGER NOT NULL DEFAULT 0,"
        "  retention_days INTEGER NOT NULL,"
        "  expires_at INTEGER,"
        "  uploader_id INTEGER NOT NULL,"
        "  poster TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (check_run_id, name)"
        ")",
        "CREATE INDEX idx_ci_artifacts_repo_head"
        " ON ci_artifacts (repo_id, head_oid, id)",
        "CREATE INDEX idx_ci_artifacts_run"
        " ON ci_artifacts (check_run_id, id)",
        "CREATE INDEX idx_ci_artifacts_expiry"
        " ON ci_artifacts (expires_at, id)",
        "CREATE TABLE ci_artifact_upload_sessions ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  check_run_id INTEGER NOT NULL,"
        "  head_oid TEXT NOT NULL,"
        "  check_run TEXT NOT NULL,"
        "  name TEXT NOT NULL,"
        "  declared_type TEXT,"
        "  expected_size INTEGER,"
        "  retention_days INTEGER NOT NULL,"
        "  received INTEGER NOT NULL DEFAULT 0,"
        "  chunks INTEGER NOT NULL DEFAULT 0,"
        "  uploader_id INTEGER NOT NULL,"
        "  poster TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  state TEXT NOT NULL DEFAULT 'open'"
        ")",
    ]),
    # S-269: release-from-tag automation -- one row
    # per repository holding the switch: enabled is
    # the whole setting (no row means off, the
    # honest default), updated_by / updated_at name
    # the writer who last flipped it. The drafts the
    # automation creates are ordinary S-257 release
    # rows in S-258's draft state; the generated
    # notes live on the release row itself.
    (106, [
        "CREATE TABLE release_tag_automation ("
        "  repo_id INTEGER PRIMARY KEY,"
        "  enabled INTEGER NOT NULL DEFAULT 0,"
        "  updated_by INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL"
        ")",
    ]),
    # S-276: wiki access policy -- one row per
    # repository holding the owner's choice:
    # 'collaborators' (only repository writers edit)
    # or 'readers' (every reader edits). No row means
    # the default, 'collaborators' -- the law as it
    # stood before the choice existed.
    (107, [
        "CREATE TABLE wiki_access_policies ("
        "  repo_id INTEGER PRIMARY KEY,"
        "  policy TEXT NOT NULL,"
        "  updated_by INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL"
        ")",
    ]),
    # S-277: gist model -- one row per gist holding
    # the metadata git cannot: the owner, the one
    # description, and the creation/update stamps.
    # The files and their full revision history live
    # in the gist's own bare git repository, never
    # duplicated into tables.
    (108, [
        "CREATE TABLE gists ("
        "  id INTEGER PRIMARY KEY,"
        "  owner_id INTEGER NOT NULL,"
        "  description TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_gists_owner ON gists (owner_id)",
    ]),
    # S-278: gist visibility -- the public/secret
    # choice. Rows that stand from S-277 (owner-only
    # reads, no choice ever offered) default to
    # 'secret': the narrower of the two new readings
    # (unlisted, readable only by link), never
    # silently made public.
    (109, [
        "ALTER TABLE gists ADD COLUMN visibility"
        " TEXT NOT NULL DEFAULT 'secret'",
    ]),
    # S-279: gist fork and star -- provenance and
    # stars. `fork_of_id` on the gist row points at
    # its direct source gist (NULL for an original),
    # lineage only, exactly as S-055's fork_of_id is
    # for repositories: the fork's git bytes are its
    # own clone and never depend on the source row.
    # `gist_stars` holds one row per star, shaped as
    # migration 86's `repo_stars` (S-222): counts are
    # COUNT(*) over these rows at read time.
    (110, [
        "ALTER TABLE gists ADD COLUMN fork_of_id INTEGER",
        "CREATE INDEX idx_gists_fork_of"
        " ON gists (fork_of_id)",
        "CREATE TABLE gist_stars ("
        "  id INTEGER PRIMARY KEY,"
        "  gist_id INTEGER NOT NULL,"
        "  user_id INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (gist_id, user_id)"
        ")",
        "CREATE INDEX idx_gist_stars_gist"
        " ON gist_stars (gist_id, id)",
        "CREATE INDEX idx_gist_stars_user"
        " ON gist_stars (user_id, id)",
    ]),
    # S-280: gist comments -- migration 35's
    # issue_comments / issue_comment_edits shape
    # carried whole, one column renamed: gist_id
    # for issue_id. Deletion is a tombstone on the
    # comment row (body cleared, deleted_at /
    # deleted_by stamped); every edit first records
    # the previous body in gist_comment_edits.
    (111, [
        "CREATE TABLE gist_comments ("
        "  id INTEGER PRIMARY KEY,"
        "  gist_id INTEGER NOT NULL,"
        "  author_id INTEGER NOT NULL,"
        "  body TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  edited_at INTEGER,"
        "  deleted_at INTEGER,"
        "  deleted_by INTEGER"
        ")",
        "CREATE INDEX idx_gist_comments_gist"
        " ON gist_comments (gist_id, id)",
        "CREATE TABLE gist_comment_edits ("
        "  id INTEGER PRIMARY KEY,"
        "  comment_id INTEGER NOT NULL,"
        "  editor_id INTEGER NOT NULL,"
        "  previous_body TEXT NOT NULL,"
        "  edited_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_gist_comment_edits_comment"
        " ON gist_comment_edits (comment_id, id)",
    ]),
    # S-283: discussion categories and threads --
    # the per-repository board verdicted in by
    # S-282. Categories carry a name unique per
    # repository case-insensitively (name_lower)
    # and a declared kind; threads are numbered
    # per repository from discussion_counters and
    # never reused; replies carry S-123's
    # tombstone (body cleared, deleted_at /
    # deleted_by stamped) with every edit's
    # previous body in discussion_reply_edits;
    # discussion_events is the thread's one
    # timeline of happenings.
    (112, [
        "CREATE TABLE discussion_categories ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  name TEXT NOT NULL,"
        "  name_lower TEXT NOT NULL,"
        "  kind TEXT NOT NULL,"
        "  description TEXT NOT NULL DEFAULT '',"
        "  created_by INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, name_lower)"
        ")",
        "CREATE INDEX idx_discussion_categories_repo"
        " ON discussion_categories (repo_id, id)",
        "CREATE TABLE discussion_threads ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  category_id INTEGER NOT NULL,"
        "  number INTEGER NOT NULL,"
        "  author_id INTEGER NOT NULL,"
        "  title TEXT NOT NULL,"
        "  body TEXT NOT NULL DEFAULT '',"
        "  state TEXT NOT NULL DEFAULT 'open',"
        "  pinned INTEGER NOT NULL DEFAULT 0,"
        "  locked INTEGER NOT NULL DEFAULT 0,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  edited_at INTEGER,"
        "  UNIQUE (repo_id, number)"
        ")",
        "CREATE INDEX idx_discussion_threads_repo"
        " ON discussion_threads (repo_id, id)",
        "CREATE INDEX idx_discussion_threads_category"
        " ON discussion_threads (category_id, id)",
        "CREATE TABLE discussion_counters ("
        "  repo_id INTEGER PRIMARY KEY,"
        "  last_number INTEGER NOT NULL"
        ")",
        "CREATE TABLE discussion_replies ("
        "  id INTEGER PRIMARY KEY,"
        "  thread_id INTEGER NOT NULL,"
        "  author_id INTEGER NOT NULL,"
        "  body TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  edited_at INTEGER,"
        "  deleted_at INTEGER,"
        "  deleted_by INTEGER"
        ")",
        "CREATE INDEX idx_discussion_replies_thread"
        " ON discussion_replies (thread_id, id)",
        "CREATE TABLE discussion_reply_edits ("
        "  id INTEGER PRIMARY KEY,"
        "  reply_id INTEGER NOT NULL,"
        "  editor_id INTEGER NOT NULL,"
        "  previous_body TEXT NOT NULL,"
        "  edited_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_discussion_reply_edits_reply"
        " ON discussion_reply_edits (reply_id, id)",
        "CREATE TABLE discussion_events ("
        "  id INTEGER PRIMARY KEY,"
        "  thread_id INTEGER NOT NULL,"
        "  actor_id INTEGER NOT NULL,"
        "  kind TEXT NOT NULL,"
        "  detail TEXT NOT NULL DEFAULT '',"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_discussion_events_thread"
        " ON discussion_events (thread_id, id)",
    ]),
    # S-284: answer marking -- the standing mark on
    # a question thread: which reply is the answer,
    # who marked it, and when. The mark's history
    # lives on the thread's own timeline as
    # discussion_events rows (answer_marked /
    # answer_unmarked); these columns hold only the
    # standing mark, exactly one per thread.
    (113, [
        "ALTER TABLE discussion_threads"
        " ADD COLUMN accepted_reply_id INTEGER",
        "ALTER TABLE discussion_threads"
        " ADD COLUMN accepted_by INTEGER",
        "ALTER TABLE discussion_threads"
        " ADD COLUMN accepted_at INTEGER",
    ]),
    # S-285: issue <-> discussion conversion --
    # the durable link both ways: which issue and
    # which discussion stand converted into each
    # other, the direction the conversion ran, who
    # converted, and when. UNIQUE (issue_id) and
    # UNIQUE (discussion_id) are the exactly-once
    # backstop: an object stands on at most one
    # side of one conversion, ever.
    (114, [
        "CREATE TABLE discussion_conversions ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  issue_id INTEGER NOT NULL,"
        "  issue_number INTEGER NOT NULL,"
        "  discussion_id INTEGER NOT NULL,"
        "  discussion_number INTEGER NOT NULL,"
        "  direction TEXT NOT NULL,"
        "  converted_by INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (issue_id),"
        "  UNIQUE (discussion_id)"
        ")",
        "CREATE INDEX idx_discussion_conversions_repo"
        " ON discussion_conversions (repo_id, id)",
    ]),
    # S-291: scan on push -- one row per scanned
    # accepted push (exactly-once on (repo_id,
    # push_key)), its ref updates, and the secret
    # alerts its findings created (S-294's lifecycle
    # governs them from here). An alert never carries
    # the secret: detector, place, redacted preview
    # and fingerprint only. Alert identity is unique
    # per (repo, commit, path, detector, fingerprint).
    (115, [
        "CREATE TABLE push_scans ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  push_key TEXT NOT NULL,"
        "  actor_kind TEXT NOT NULL,"
        "  actor_id INTEGER,"
        "  transport TEXT NOT NULL,"
        "  status TEXT NOT NULL,"
        "  partial_reason TEXT NOT NULL DEFAULT '',"
        "  commits_scanned INTEGER NOT NULL,"
        "  blobs_scanned INTEGER NOT NULL,"
        "  blobs_skipped INTEGER NOT NULL,"
        "  findings_count INTEGER NOT NULL,"
        "  alerts_created INTEGER NOT NULL,"
        "  pattern_available INTEGER NOT NULL,"
        "  generic_available INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, push_key)"
        ")",
        "CREATE INDEX idx_push_scans_repo"
        " ON push_scans (repo_id, id)",
        "CREATE TABLE push_scan_updates ("
        "  id INTEGER PRIMARY KEY,"
        "  scan_id INTEGER NOT NULL,"
        "  ref TEXT NOT NULL,"
        "  old_oid TEXT NOT NULL,"
        "  new_oid TEXT NOT NULL"
        ")",
        "CREATE INDEX idx_push_scan_updates_scan"
        " ON push_scan_updates (scan_id, id)",
        "CREATE TABLE secret_alerts ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  scan_id INTEGER NOT NULL,"
        "  commit_oid TEXT NOT NULL,"
        "  path TEXT NOT NULL,"
        "  blob_oid TEXT NOT NULL,"
        "  source TEXT NOT NULL,"
        "  detector_id TEXT NOT NULL,"
        "  line INTEGER NOT NULL,"
        "  column INTEGER NOT NULL,"
        "  redacted TEXT NOT NULL,"
        "  fingerprint TEXT NOT NULL,"
        "  state TEXT NOT NULL DEFAULT 'open',"
        "  created_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, commit_oid, path,"
        " detector_id, fingerprint)"
        ")",
        "CREATE INDEX idx_secret_alerts_repo"
        " ON secret_alerts (repo_id, id)",
        "CREATE INDEX idx_secret_alerts_scan"
        " ON secret_alerts (scan_id, id)",
    ]),
    # S-293: push-protection bypass -- one standing
    # alert per used bypass: who bypassed S-292
    # refusal, under which role and its source,
    # the stated reason, the findings (never the
    # secret) and refs as JSON, the audit sequence
    # of its witness row, and its standing state.
    (116, [
        "CREATE TABLE push_protection_bypasses ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  actor_id INTEGER NOT NULL,"
        "  actor_username TEXT NOT NULL,"
        "  role TEXT NOT NULL,"
        "  role_source TEXT NOT NULL,"
        "  reason TEXT NOT NULL,"
        "  findings TEXT NOT NULL,"
        "  refs TEXT NOT NULL,"
        "  audit_seq INTEGER NOT NULL,"
        "  state TEXT NOT NULL DEFAULT 'open',"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_push_protection_bypasses_repo"
        " ON push_protection_bypasses (repo_id, id)",
    ]),
    # S-294: secret alert lifecycle -- an alert's
    # standing resolution lives on the alert row
    # itself (kind, resolver, reason, when; all
    # empty while the alert stands open or
    # reopened), and every transition stands as a
    # row in secret_alert_events, the alert's own
    # lifecycle record, written in the same
    # transaction as the transition it records.
    # (Renumbered 116 -> 117 at banking: S-293's
    # migration 116 for push_protection_bypasses
    # banks first, in roadmap order.)
    (117, [
        "ALTER TABLE secret_alerts ADD COLUMN"
        " resolution TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE secret_alerts ADD COLUMN"
        " resolved_by_id INTEGER",
        "ALTER TABLE secret_alerts ADD COLUMN"
        " resolved_by TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE secret_alerts ADD COLUMN"
        " resolved_at INTEGER",
        "ALTER TABLE secret_alerts ADD COLUMN"
        " resolution_reason TEXT NOT NULL DEFAULT ''",
        "CREATE TABLE secret_alert_events ("
        "  id INTEGER PRIMARY KEY,"
        "  alert_id INTEGER NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  action TEXT NOT NULL,"
        "  from_state TEXT NOT NULL,"
        "  to_state TEXT NOT NULL,"
        "  resolution TEXT NOT NULL DEFAULT '',"
        "  actor_id INTEGER NOT NULL,"
        "  actor_username TEXT NOT NULL,"
        "  role TEXT NOT NULL,"
        "  role_source TEXT NOT NULL,"
        "  reason TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_secret_alert_events_alert"
        " ON secret_alert_events (alert_id, id)",
        "CREATE INDEX idx_secret_alert_events_repo"
        " ON secret_alert_events (repo_id, id)",
    ]),
    # S-295: custom patterns -- org/instance-defined
    # regex patterns, their dry-runs against repo
    # history, and the dry-runs' matches. A pattern
    # stands draft until a complete dry-run of its
    # current text stands behind it; activation is
    # recorded on the pattern row itself. A match
    # never carries the matched text: place, redacted
    # preview and fingerprint only.
    # (Renumbered 116 -> 118 at banking: S-293's
    # migration 116 and S-294's migration 117
    # bank first, in roadmap order.)
    (118, [
        "CREATE TABLE custom_patterns ("
        "  id INTEGER PRIMARY KEY,"
        "  scope TEXT NOT NULL,"
        "  org_id INTEGER,"
        "  org_name TEXT,"
        "  org_name_lower TEXT,"
        "  name TEXT NOT NULL,"
        "  name_lower TEXT NOT NULL,"
        "  description TEXT NOT NULL DEFAULT '',"
        "  regex TEXT NOT NULL,"
        "  regex_sha TEXT NOT NULL,"
        "  state TEXT NOT NULL DEFAULT 'draft',"
        "  created_by INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  activated_by INTEGER,"
        "  activated_at INTEGER"
        ")",
        "CREATE INDEX idx_custom_patterns_scope"
        " ON custom_patterns (scope, org_id, state)",
        "CREATE TABLE custom_pattern_dry_runs ("
        "  id INTEGER PRIMARY KEY,"
        "  pattern_id INTEGER NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  repo_full_name TEXT NOT NULL,"
        "  pattern_sha TEXT NOT NULL,"
        "  status TEXT NOT NULL,"
        "  partial_reason TEXT NOT NULL DEFAULT '',"
        "  commits_scanned INTEGER NOT NULL,"
        "  blobs_scanned INTEGER NOT NULL,"
        "  blobs_skipped INTEGER NOT NULL,"
        "  matches_count INTEGER NOT NULL,"
        "  matches_stored INTEGER NOT NULL,"
        "  created_by INTEGER NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_custom_pattern_dry_runs_pattern"
        " ON custom_pattern_dry_runs (pattern_id, id)",
        "CREATE TABLE custom_pattern_dry_run_matches ("
        "  id INTEGER PRIMARY KEY,"
        "  dry_run_id INTEGER NOT NULL,"
        "  commit_oid TEXT NOT NULL,"
        "  path TEXT NOT NULL,"
        "  blob_oid TEXT NOT NULL,"
        "  line INTEGER NOT NULL,"
        "  column INTEGER NOT NULL,"
        "  redacted TEXT NOT NULL,"
        "  fingerprint TEXT NOT NULL"
        ")",
        "CREATE INDEX idx_custom_pattern_dry_run_matches_run"
        " ON custom_pattern_dry_run_matches (dry_run_id, id)",
    ]),
    # S-296: validity checks seam -- the standing
    # validity of a secret alert (unknown until a
    # check through a provider's public validation
    # path answers otherwise) and the alert's own
    # check record: one row per performed check,
    # naming the answer, why it stands, the checker,
    # who asked, their role and its source, and
    # when. The secret is never a column anywhere.
    # (Renumbered 116 -> 119 at banking: S-293's
    # migration 116, S-294's migration 117 and
    # S-295's migration 118 bank first, in
    # roadmap order.)
    (119, [
        "ALTER TABLE secret_alerts"
        " ADD COLUMN validity TEXT NOT NULL"
        " DEFAULT 'unknown'",
        "ALTER TABLE secret_alerts"
        " ADD COLUMN validity_checked_at INTEGER",
        "ALTER TABLE secret_alerts"
        " ADD COLUMN validity_checker TEXT NOT NULL"
        " DEFAULT ''",
        "ALTER TABLE secret_alerts"
        " ADD COLUMN validity_detail TEXT NOT NULL"
        " DEFAULT ''",
        "CREATE TABLE secret_validity_checks ("
        "  id INTEGER PRIMARY KEY,"
        "  alert_id INTEGER NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  detector_id TEXT NOT NULL,"
        "  validity TEXT NOT NULL,"
        "  checker TEXT NOT NULL DEFAULT '',"
        "  detail TEXT NOT NULL DEFAULT '',"
        "  checked_by_id INTEGER NOT NULL,"
        "  checked_by TEXT NOT NULL,"
        "  role TEXT NOT NULL,"
        "  role_source TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_secret_validity_checks_alert"
        " ON secret_validity_checks (alert_id, id)",
        "CREATE INDEX idx_secret_validity_checks_repo"
        " ON secret_validity_checks (repo_id, id)",
    ]),
    # S-297: dependency graph -- where a repo graph
    # stands, its manifests with their standing, and
    # the dependency table parsed from them on push.
    # (Renumbered 117 -> 120 at banking: S-294's
    # migration 117, S-295's migration 118 and
    # S-296's migration 119 bank first, in
    # roadmap order.)
    (120, [
        "CREATE TABLE dependency_graph_states ("
        "  repo_id INTEGER PRIMARY KEY,"
        "  commit_oid TEXT NOT NULL,"
        "  manifests_count INTEGER NOT NULL,"
        "  dependencies_count INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL"
        ")",
        "CREATE TABLE dependency_manifests ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  path TEXT NOT NULL,"
        "  ecosystem TEXT NOT NULL,"
        "  kind TEXT NOT NULL,"
        "  status TEXT NOT NULL,"
        "  reason TEXT NOT NULL DEFAULT '',"
        "  dependencies_count INTEGER NOT NULL,"
        "  blob_oid TEXT NOT NULL,"
        "  UNIQUE (repo_id, path)"
        ")",
        "CREATE INDEX idx_dependency_manifests_repo"
        " ON dependency_manifests (repo_id, id)",
        "CREATE TABLE repo_dependencies ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  manifest_path TEXT NOT NULL,"
        "  ecosystem TEXT NOT NULL,"
        "  kind TEXT NOT NULL,"
        "  name TEXT NOT NULL,"
        "  name_key TEXT NOT NULL,"
        "  specifier TEXT NOT NULL,"
        "  extras TEXT NOT NULL DEFAULT '',"
        "  scope TEXT NOT NULL,"
        "  resolved INTEGER NOT NULL,"
        "  marker TEXT NOT NULL DEFAULT '',"
        "  UNIQUE (repo_id, manifest_path, name_key, scope)"
        ")",
        "CREATE INDEX idx_repo_dependencies_repo"
        " ON repo_dependencies (repo_id, ecosystem, name_key)",
        "CREATE INDEX idx_repo_dependencies_name"
        " ON repo_dependencies (name_key, ecosystem)",
    ]),
    # S-299: dependency alerts -- the join of
    # S-297's graph and S-298's advisory snapshot
    # as standing alert rows, with S-294's
    # lifecycle (standing resolution on the row,
    # every transition on the alert's own events
    # table). fixed_version is NULL where the
    # snapshot knows no fix: fix unknown, never
    # invented. The name column is dependency_name:
    # S-264/S-265's registry audit refuses any
    # schema name carrying the registry's own
    # words, and an alert is not a registry.
    # (Schema 120 -> 121 on this base;
    # the keeper renumbers at banking if later
    # slices land first.)
    (121, [
        "CREATE TABLE dependency_alerts ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  dependency_id INTEGER,"
        "  ecosystem TEXT NOT NULL,"
        "  dependency_name TEXT NOT NULL,"
        "  name_key TEXT NOT NULL,"
        "  manifest_path TEXT NOT NULL,"
        "  specifier TEXT NOT NULL,"
        "  basis TEXT NOT NULL,"
        "  pinned_version TEXT NOT NULL DEFAULT '',"
        "  advisory_id TEXT NOT NULL,"
        "  severity TEXT NOT NULL,"
        "  affected TEXT NOT NULL,"
        "  fixed_version TEXT,"
        "  summary TEXT NOT NULL,"
        "  snapshot_date TEXT NOT NULL,"
        "  state TEXT NOT NULL DEFAULT 'open',"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  resolution TEXT NOT NULL DEFAULT '',"
        "  resolved_by_id INTEGER,"
        "  resolved_by TEXT NOT NULL DEFAULT '',"
        "  resolved_at INTEGER,"
        "  resolution_reason TEXT NOT NULL DEFAULT '',"
        "  UNIQUE (repo_id, ecosystem, name_key,"
        "  manifest_path, advisory_id)"
        ")",
        "CREATE INDEX idx_dependency_alerts_repo"
        " ON dependency_alerts (repo_id, state, id)",
        "CREATE INDEX idx_dependency_alerts_advisory"
        " ON dependency_alerts (advisory_id, repo_id)",
        "CREATE TABLE dependency_alert_events ("
        "  id INTEGER PRIMARY KEY,"
        "  alert_id INTEGER NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  action TEXT NOT NULL,"
        "  from_state TEXT NOT NULL,"
        "  to_state TEXT NOT NULL,"
        "  resolution TEXT NOT NULL DEFAULT '',"
        "  actor_id INTEGER,"
        "  actor_username TEXT NOT NULL,"
        "  role TEXT NOT NULL DEFAULT '',"
        "  role_source TEXT NOT NULL DEFAULT '',"
        "  reason TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_dependency_alert_events_alert"
        " ON dependency_alert_events (alert_id, id)",
        "CREATE INDEX idx_dependency_alert_events_repo"
        " ON dependency_alert_events (repo_id, id)",
    ]),
    # S-300: advisory refresh -- the standing
    # refreshed snapshot (a singleton row, landed
    # only through S-298 parse_snapshot's own
    # validation, atomically with its provenance
    # row) and the provenance record of every
    # refresh attempt: when, by whom, by what
    # trigger, the standing date before, the
    # candidate's date where one was validated,
    # the result and the named reason where it
    # did not land. Where no state row stands,
    # the standing snapshot is the bundled one.
    (122, [
        "CREATE TABLE advisory_snapshot_state ("
        "  id INTEGER PRIMARY KEY CHECK (id = 1),"
        "  snapshot_text TEXT NOT NULL,"
        "  snapshot_date TEXT NOT NULL,"
        "  source TEXT NOT NULL,"
        "  advisory_count INTEGER NOT NULL,"
        "  refreshed_at INTEGER NOT NULL,"
        "  trigger TEXT NOT NULL,"
        "  actor TEXT NOT NULL"
        ")",
        "CREATE TABLE advisory_refreshes ("
        "  id INTEGER PRIMARY KEY,"
        "  trigger TEXT NOT NULL,"
        "  actor TEXT NOT NULL,"
        "  old_snapshot_date TEXT NOT NULL,"
        "  new_snapshot_date TEXT NOT NULL,"
        "  result TEXT NOT NULL,"
        "  reason TEXT NOT NULL DEFAULT '',"
        "  detail TEXT NOT NULL DEFAULT '',"
        "  advisory_count INTEGER,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_advisory_refreshes_id"
        " ON advisory_refreshes (id)",
    ]),
    # S-302: code scanning ingestion -- one row
    # per accepted SARIF upload, keyed by the
    # commit it was computed against: the
    # canonical document text, the summary its
    # validation judged it with (tool names, run
    # and result counts, results by level), the
    # poster and when it landed. A re-upload is
    # a new row beside the old; no row is ever
    # updated in place.
    (123, [
        "CREATE TABLE code_scanning_uploads ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  commit_oid TEXT NOT NULL,"
        "  ref TEXT NOT NULL DEFAULT '',"
        "  sarif_text TEXT NOT NULL,"
        "  tool_names TEXT NOT NULL DEFAULT '[]',"
        "  run_count INTEGER NOT NULL,"
        "  result_count INTEGER NOT NULL,"
        "  level_counts TEXT NOT NULL DEFAULT '{}',"
        "  poster TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_code_scanning_uploads_repo_commit"
        " ON code_scanning_uploads (repo_id, commit_oid, id)",
        "CREATE INDEX idx_code_scanning_uploads_repo"
        " ON code_scanning_uploads (repo_id, id)",
    ]),
    # S-303: code scanning alerts -- one alert
    # per (repo, branch, fingerprint): the
    # standing facts of the run that most
    # recently reported the finding, its state
    # (open / fixed), and the uploads that
    # first reported it, most recently reported
    # it, and first stopped reporting it; plus
    # the branch heads -- the newest upload
    # processed per (repo, branch), so an older
    # upload's transitions can never rewrite a
    # newer run's verdicts.
    (124, [
        "CREATE TABLE code_scanning_alerts ("
        "  id INTEGER PRIMARY KEY,"
        "  repo_id INTEGER NOT NULL,"
        "  branch TEXT NOT NULL DEFAULT '',"
        "  fingerprint TEXT NOT NULL,"
        "  basis TEXT NOT NULL,"
        "  tool_name TEXT NOT NULL DEFAULT '',"
        "  rule_id TEXT NOT NULL DEFAULT '',"
        "  level TEXT NOT NULL DEFAULT 'warning',"
        "  message TEXT NOT NULL DEFAULT '',"
        "  artifact_uri TEXT NOT NULL DEFAULT '',"
        "  start_line INTEGER NOT NULL DEFAULT 0,"
        "  start_column INTEGER NOT NULL DEFAULT 0,"
        "  state TEXT NOT NULL DEFAULT 'open',"
        "  first_seen_upload_id INTEGER NOT NULL,"
        "  first_seen_oid TEXT NOT NULL,"
        "  last_seen_upload_id INTEGER NOT NULL,"
        "  last_seen_oid TEXT NOT NULL,"
        "  fixed_upload_id INTEGER,"
        "  fixed_oid TEXT NOT NULL DEFAULT '',"
        "  times_seen INTEGER NOT NULL DEFAULT 1,"
        "  times_fixed INTEGER NOT NULL DEFAULT 0,"
        "  created_at INTEGER NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  UNIQUE (repo_id, branch, fingerprint)"
        ")",
        "CREATE INDEX idx_code_scanning_alerts_repo_branch"
        " ON code_scanning_alerts"
        " (repo_id, branch, state, id)",
        "CREATE TABLE code_scanning_branch_heads ("
        "  repo_id INTEGER NOT NULL,"
        "  branch TEXT NOT NULL DEFAULT '',"
        "  upload_id INTEGER NOT NULL,"
        "  oid TEXT NOT NULL,"
        "  updated_at INTEGER NOT NULL,"
        "  PRIMARY KEY (repo_id, branch)"
        ")",
    ]),
    # S-304: code scanning alerts UI -- the
    # dismissal standing on S-303's alert rows:
    # the kind, the dismisser and the stated
    # reason, cleared whole on a reopen; plus the
    # alert's own dismissal record -- one row per
    # transition, written in the same transaction
    # that moves the alert.
    (125, [
        "ALTER TABLE code_scanning_alerts ADD COLUMN"
        " dismissal TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE code_scanning_alerts ADD COLUMN"
        " dismissed_by_id INTEGER",
        "ALTER TABLE code_scanning_alerts ADD COLUMN"
        " dismissed_by TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE code_scanning_alerts ADD COLUMN"
        " dismissed_at INTEGER",
        "ALTER TABLE code_scanning_alerts ADD COLUMN"
        " dismissal_reason TEXT NOT NULL DEFAULT ''",
        "CREATE TABLE code_scanning_alert_events ("
        "  id INTEGER PRIMARY KEY,"
        "  alert_id INTEGER NOT NULL,"
        "  repo_id INTEGER NOT NULL,"
        "  action TEXT NOT NULL,"
        "  from_state TEXT NOT NULL,"
        "  to_state TEXT NOT NULL,"
        "  dismissal TEXT NOT NULL DEFAULT '',"
        "  actor_id INTEGER NOT NULL,"
        "  actor_username TEXT NOT NULL,"
        "  role TEXT NOT NULL,"
        "  role_source TEXT NOT NULL,"
        "  reason TEXT NOT NULL,"
        "  created_at INTEGER NOT NULL"
        ")",
        "CREATE INDEX idx_code_scanning_alert_events_alert"
        " ON code_scanning_alert_events (alert_id, id)",
        "CREATE INDEX idx_code_scanning_alert_events_repo"
        " ON code_scanning_alert_events (repo_id, id)",
    ]),
]


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with Samverk's standing pragmas applied."""
    ensure_dir(db_path.parent)
    conn = sqlite3.connect(str(db_path), timeout=BUSY_TIMEOUT_MS / 1000.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.row_factory = sqlite3.Row
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["value"]) if row else 0


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations, each in its own transaction.

    Returns the resulting schema version. A failing migration rolls
    back whole and raises — the database is never left half-migrated.
    """
    version = schema_version(conn)
    for target, statements in MIGRATIONS:
        if target <= version:
            continue
        with conn:  # one transaction per migration
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) "
                "VALUES ('version', ?)",
                (str(target),),
            )
        version = target
    return version


def init_db(db_path: Path) -> sqlite3.Connection:
    """Connect and migrate; the normal way to open an instance DB."""
    conn = connect(db_path)
    migrate(conn)
    return conn
