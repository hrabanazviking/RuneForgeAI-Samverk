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
