"""S-358 acceptance battery: database migrations.

Acceptance (roadmap S-358): numbered, transactional where
SQLite allows, each with a down-path or an explicit one-way
warning.

Counted with: python3 -m unittest tests.test_database_migrations
"""
from __future__ import annotations
import io, sqlite3, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.cli import main as cli_main
from samverk.database_migrations import (
    REGISTER, MigrationEntry, MigrationRegisterError, apply_down,
    pending_one_way, register_entry, render_upgrade_warnings,
    validate_register)
from samverk.db import MIGRATIONS, schema_version


class RegisterTests(unittest.TestCase):
    def test_register_covers_every_migration_exactly(self):
        self.assertEqual(len(REGISTER), 140)
        self.assertEqual([e.version for e in REGISTER], list(range(1, 141)))
        self.assertEqual(validate_register(MIGRATIONS, REGISTER), [])

    def test_schema_pin_140_and_migrations_numbered_in_order(self):
        self.assertEqual([v for v, _ in MIGRATIONS], list(range(1, 141)))
        self.assertEqual(MIGRATIONS[-1][0], 140)

    def test_every_entry_exactly_one_of_down_or_warning(self):
        for e in REGISTER:
            self.assertTrue((e.down_statements is None) != (e.one_way_warning is None),
                            f"migration {e.version}")
            self.assertTrue(e.summary.strip())

    def test_standing_register_is_honestly_all_one_way(self):
        # No shipped migration carried a down-path; the register
        # must not invent any. Every warning names the backup road.
        for e in REGISTER:
            self.assertFalse(e.reversible, f"migration {e.version}")
            self.assertIn("ONE-WAY", e.one_way_warning)
            self.assertIn("backup", e.one_way_warning)
            self.assertIn(str(e.version), e.one_way_warning)

    def test_validate_names_each_defect(self):
        migs = [(1, ["x"]), (2, ["y"]), (3, ["z"])]
        bad = (MigrationEntry(1, "a", ("d",), "w"),
               MigrationEntry(1, "a", None, "w"),
               MigrationEntry(3, "a", None, None),
               MigrationEntry(9, "a", (), None))
        problems = validate_register(migs, bad)
        text = "\n".join(problems)
        self.assertIn("migration 2: no register entry", text)
        self.assertIn("duplicate", text)
        self.assertIn("both a down-path", text)
        self.assertIn("neither a down-path", text)
        self.assertIn("down-path is empty", text)
        self.assertIn("no migration", text)

    def test_register_entry_lookup_and_unknown(self):
        self.assertEqual(register_entry(139).version, 139)
        with self.assertRaises(MigrationRegisterError) as cm:
            register_entry(141)
        self.assertEqual(cm.exception.reason, "unknown_migration")


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "scratch.db")
        self.addCleanup(self.conn.close)

    def _table_names(self):
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {r[0] for r in rows}

    def test_fresh_database_migrates_to_140(self):
        self.assertEqual(schema_version(self.conn), 140)

    def test_failing_migration_rolls_back_whole(self):
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES ('sentinel', 'keep-me')")
        failing = (141, ["CREATE TABLE rehearsal_partial (id INTEGER)",
                         "INSERT INTO no_such_table VALUES (1)"])
        MIGRATIONS.append(failing)
        try:
            with self.assertRaises(sqlite3.Error):
                db.migrate(self.conn)
        finally:
            MIGRATIONS.pop()
        # Prior version stamped, partial DDL gone, content intact.
        self.assertEqual(schema_version(self.conn), 140)
        self.assertNotIn("rehearsal_partial", self._table_names())
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key='sentinel'").fetchone()
        self.assertEqual(row[0], "keep-me")

    def test_good_migration_and_down_path_round_trip(self):
        entry = MigrationEntry(
            141, "creates table rehearsal_roundtrip",
            ("DROP TABLE rehearsal_roundtrip",), None)
        db.apply_migration(self.conn, 141, [
            "CREATE TABLE rehearsal_roundtrip (id INTEGER PRIMARY KEY, note TEXT)",
            "INSERT INTO rehearsal_roundtrip (note) VALUES ('hello')"])
        self.assertEqual(schema_version(self.conn), 141)
        self.assertIn("rehearsal_roundtrip", self._table_names())
        apply_down(self.conn, entry, 140)
        self.assertEqual(schema_version(self.conn), 140)
        self.assertNotIn("rehearsal_roundtrip", self._table_names())

    def test_failing_down_path_rolls_back_whole(self):
        db.apply_migration(self.conn, 141, [
            "CREATE TABLE rehearsal_downfail (id INTEGER PRIMARY KEY)"])
        entry = MigrationEntry(
            141, "creates table rehearsal_downfail",
            ("DROP TABLE rehearsal_downfail", "INSERT INTO no_such_table VALUES (1)"),
            None)
        with self.assertRaises(sqlite3.Error):
            apply_down(self.conn, entry, 140)
        self.assertEqual(schema_version(self.conn), 141)
        self.assertIn("rehearsal_downfail", self._table_names())

    def test_one_way_down_refused_and_database_untouched(self):
        entry = register_entry(139)
        with self.assertRaises(MigrationRegisterError) as cm:
            apply_down(self.conn, entry, 138)
        self.assertEqual(cm.exception.reason, "one_way_migration")
        self.assertIn("ONE-WAY", str(cm.exception))
        self.assertEqual(schema_version(self.conn), 140)
        self.assertIn("metadata_imports", self._table_names())


class WarningSurfaceTests(unittest.TestCase):
    def test_pending_one_way_counts(self):
        self.assertEqual(len(pending_one_way(REGISTER, 0)), 140)
        self.assertEqual([e.version for e in pending_one_way(REGISTER, 138)], [139, 140])
        self.assertEqual([e.version for e in pending_one_way(REGISTER, 139)], [140])
        self.assertEqual(pending_one_way(REGISTER, 140), [])

    def test_rendered_warnings_are_plain_operator_words(self):
        text = render_upgrade_warnings(REGISTER, 138)
        self.assertIn("ONE-WAY", text)
        self.assertIn("backup", text)
        self.assertIn("Migration 139", text)
        self.assertNotIn("Migration 138", text)
        done = render_upgrade_warnings(REGISTER, 140)
        self.assertIn("no one-way migrations", done)

    def test_cli_check_and_warnings(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli_main(["migrations", "check"])
        self.assertEqual(rc, 0)
        self.assertIn("140 migrations", out.getvalue())
        self.assertIn("1..140", out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli_main(["migrations", "warnings", "--from-version", "138"])
        self.assertEqual(rc, 0)
        self.assertIn("Migration 139", out.getvalue())


if __name__ == "__main__":
    unittest.main()
