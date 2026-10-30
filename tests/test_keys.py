"""S-020 acceptance battery: operator key custody.

Acceptance (roadmap S-020): instance keys generated at install,
backed up per runbook, rotatable — *rotation drill on a scratch
instance.* The drill below is that acceptance, end to end.

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

from samverk.audit import AuditLog, verify_chain
from samverk.cli import main as cli_main
from samverk.db import init_db
from samverk.keys import (
    KeyCustodyError,
    current_key,
    ensure_instance_key,
    list_key_versions,
    load_key,
    rotate_key,
)


class GenerationTests(unittest.TestCase):
    def test_ensure_generates_once_and_never_replaces(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = ensure_instance_key(root)
            self.assertEqual(first.version, 1)
            self.assertEqual(len(load_key(root)), 32)
            if os.name == "posix":
                mode = stat.S_IMODE(first.path.stat().st_mode)
                self.assertEqual(mode, 0o600)
            again = ensure_instance_key(root)
            self.assertEqual(again, first)
            self.assertEqual(load_key(root), load_key(root, version=1))

    def test_unlawful_purposes_are_refused(self):
        with tempfile.TemporaryDirectory() as td:
            for purpose in ("", "Signing", "../evil", "a b", "x" * 40):
                with self.assertRaises(KeyCustodyError, msg=purpose):
                    ensure_instance_key(Path(td), purpose)


class RotationDrillTests(unittest.TestCase):
    def test_rotation_drill_on_a_scratch_instance(self):
        """The acceptance in its literal form: generate, rotate
        twice, and prove every version still loads, the current
        pointer moved each time, and material never repeats."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            v1 = ensure_instance_key(root)
            v2 = rotate_key(root)
            v3 = rotate_key(root)
            self.assertEqual([r.version for r in list_key_versions(root)],
                             [1, 2, 3])
            self.assertEqual(current_key(root), v3)
            materials = {load_key(root, version=v) for v in (1, 2, 3)}
            self.assertEqual(len(materials), 3)  # all distinct
            self.assertEqual(load_key(root), load_key(root, version=3))
            self.assertEqual(
                {v1.fingerprint, v2.fingerprint, v3.fingerprint},
                {r.fingerprint for r in list_key_versions(root)})

    def test_rotation_is_audit_logged_with_fingerprints_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ensure_instance_key(root)
            conn = init_db(root / "samverk.db")
            try:
                record = rotate_key(root, audit=AuditLog(conn))
                rows = conn.execute(
                    "SELECT action, detail FROM audit_log").fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["action"], "admin.key.rotate")
                self.assertIn(record.fingerprint, rows[0]["detail"])
                ok, bad, _ = verify_chain(conn)
                self.assertTrue(ok, msg=f"chain broken at {bad}")
                material_hex = load_key(root, version=1).hex()
            finally:
                conn.close()
            self.assertNotIn(material_hex, rows[0]["detail"])

    def test_key_material_never_enters_the_database(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ensure_instance_key(root)
            rotate_key(root)
            conn = init_db(root / "samverk.db")
            conn.close()
            db_bytes = (root / "samverk.db").read_bytes()
            for version in (1, 2):
                material = load_key(root, version=version)
                self.assertNotIn(material, db_bytes)
                self.assertNotIn(material.hex().encode(), db_bytes)


class CustodyRefusalTests(unittest.TestCase):
    def test_loosely_permissioned_key_file_is_refused(self):
        if os.name != "posix":
            self.skipTest("POSIX permission semantics")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            record = ensure_instance_key(root)
            record.path.chmod(0o644)
            with self.assertRaises(KeyCustodyError):
                load_key(root)

    def test_corrupt_key_file_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            record = ensure_instance_key(root)
            record.path.write_text("not-hex-at-all\n", encoding="ascii")
            with self.assertRaises(KeyCustodyError):
                load_key(root)


class CliDrillTests(unittest.TestCase):
    def test_cli_ensure_status_rotate(self):
        with tempfile.TemporaryDirectory() as td:
            ini = Path(td) / "samverk.ini"
            ini.write_text(
                f"[samverk]\ndata_root = {td}\n", encoding="utf-8")
            argv = lambda *a: ["keys", *a, "--config", str(ini)]
            self.assertEqual(cli_main(argv("ensure")), 0)
            self.assertEqual(cli_main(argv("status")), 0)
            self.assertEqual(cli_main(argv("rotate")), 0)
            self.assertEqual(
                [r.version for r in list_key_versions(Path(td))], [1, 2])


if __name__ == "__main__":
    unittest.main()
