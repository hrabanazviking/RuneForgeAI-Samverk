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
