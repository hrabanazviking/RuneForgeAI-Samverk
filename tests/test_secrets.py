"""S-003 acceptance battery: secrets law.

Acceptance (roadmap S-003): instance secrets load from env or a
mode-600 file, never plaintext in the database — *grep of a seeded DB
finds no secret.*

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db, platform_seam
from samverk.config import Config
from samverk.secrets import SecretError, load_secrets

FILE_SECRET = "file-secret-value-7f3a9c"
ENV_SECRET = "env-secret-value-51bd02"


def _cfg(td: str, **kw) -> Config:
    return Config(data_root=Path(td), **kw)


class LoadTests(unittest.TestCase):
    def test_env_secret_loads(self):
        with tempfile.TemporaryDirectory() as td:
            s = load_secrets(_cfg(td), env={"SAMVERK_SECRET_INSTANCE_KEY": ENV_SECRET})
            self.assertEqual(s.require("INSTANCE_KEY"), ENV_SECRET)
            self.assertIn("INSTANCE_KEY", s)

    def test_repr_never_shows_values(self):
        with tempfile.TemporaryDirectory() as td:
            s = load_secrets(_cfg(td), env={"SAMVERK_SECRET_INSTANCE_KEY": ENV_SECRET})
            self.assertNotIn(ENV_SECRET, repr(s))

    def test_missing_secret(self):
        with tempfile.TemporaryDirectory() as td:
            s = load_secrets(_cfg(td), env={})
            self.assertIsNone(s.get("INSTANCE_KEY"))
            with self.assertRaises(SecretError):
                s.require("INSTANCE_KEY")

    def test_file_secret_loads_at_600(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "secrets.env"
            f.write_text(f"INSTANCE_KEY={FILE_SECRET}\n", encoding="utf-8")
            os.chmod(f, 0o600)
            s = load_secrets(_cfg(td, secret_file=f), env={})
            self.assertEqual(s.require("INSTANCE_KEY"), FILE_SECRET)

    @unittest.skipIf(platform_seam.os_name() == "windows",
                     "POSIX permission bits do not exist on Windows")
    def test_loose_file_is_refused_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "secrets.env"
            f.write_text(f"INSTANCE_KEY={FILE_SECRET}\n", encoding="utf-8")
            os.chmod(f, 0o644)
            with self.assertRaises(SecretError):
                load_secrets(_cfg(td, secret_file=f), env={})

    def test_env_beats_file(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "secrets.env"
            f.write_text("INSTANCE_KEY=from-file\n", encoding="utf-8")
            os.chmod(f, 0o600)
            s = load_secrets(_cfg(td, secret_file=f),
                             env={"SAMVERK_SECRET_INSTANCE_KEY": "from-env"})
            self.assertEqual(s.require("INSTANCE_KEY"), "from-env")


class DatabaseTests(unittest.TestCase):
    def test_factory_pragmas(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "samverk.db")
            try:
                self.assertEqual(
                    conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                self.assertEqual(
                    conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                # synchronous: 2 == FULL
                self.assertEqual(
                    conn.execute("PRAGMA synchronous").fetchone()[0], 2)
                self.assertEqual(
                    conn.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
            finally:
                conn.close()

    def test_migrations_are_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "samverk.db"
            conn = db.init_db(path)
            self.assertEqual(db.schema_version(conn), 1)
            conn.close()
            conn = db.init_db(path)  # second open: no error, same version
            self.assertEqual(db.schema_version(conn), 1)
            conn.close()

    def test_seeded_db_grep_finds_no_secret(self):
        """The S-003 acceptance in its literal form."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            secret_file = root / "secrets.env"
            secret_file.write_text(f"INSTANCE_KEY={FILE_SECRET}\n", encoding="utf-8")
            os.chmod(secret_file, 0o600)
            secrets = load_secrets(
                _cfg(td, secret_file=secret_file),
                env={"SAMVERK_SECRET_WEBHOOK_KEY": ENV_SECRET},
            )
            self.assertEqual(secrets.names(), ["INSTANCE_KEY", "WEBHOOK_KEY"])

            conn = db.init_db(root / "samverk.db")
            with conn:
                # Ordinary settings, including a *reference* to a secret
                # by name — the only form a secret may take in the DB.
                conn.execute("INSERT INTO settings VALUES ('site_name', 'Samverk')")
                conn.execute(
                    "INSERT INTO settings VALUES ('webhook_key_ref', 'secret:WEBHOOK_KEY')")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()

            for artifact in (root / "samverk.db", root / "samverk.db-wal"):
                if artifact.exists():
                    blob = artifact.read_bytes()
                    self.assertNotIn(FILE_SECRET.encode(), blob,
                                     f"file secret leaked into {artifact.name}")
                    self.assertNotIn(ENV_SECRET.encode(), blob,
                                     f"env secret leaked into {artifact.name}")


if __name__ == "__main__":
    unittest.main()
