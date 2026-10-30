"""S-007 acceptance battery: audit log core.

Acceptance (roadmap S-007): append-only table with hash chain —
*tampering with a row is detected by the verifier.*

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import audit, db
from samverk.audit import AuditLog, verify_chain


def _event(log: AuditLog, action: str = "auth.login.success") -> int:
    return log.append(
        actor_kind="user", actor_id=7, action=action,
        target_kind="user", target_id="7", source_ip="127.0.0.1",
        outcome="success", detail={"method": "password"})


class AuditTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.db_path = Path(self._td.name) / "samverk.db"
        self.conn = db.init_db(self.db_path)
        self.log = AuditLog(self.conn)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_append_and_verify_clean_chain(self):
        _event(self.log)
        _event(self.log, "repo.push")
        _event(self.log, "admin.user.disable")
        ok, bad, count = verify_chain(self.conn)
        self.assertTrue(ok)
        self.assertIsNone(bad)
        self.assertEqual(count, 3)

    def test_chain_links_and_genesis(self):
        _event(self.log)
        _event(self.log, "repo.push")
        rows = self.conn.execute(
            "SELECT prev_hash, entry_hash FROM audit_log ORDER BY seq"
        ).fetchall()
        self.assertEqual(rows[0]["prev_hash"], audit.GENESIS_HASH)
        self.assertEqual(rows[1]["prev_hash"], rows[0]["entry_hash"])

    def test_tampered_row_is_detected(self):
        _event(self.log)
        _event(self.log, "repo.push")
        _event(self.log, "admin.user.disable")
        with self.conn:  # the attacker edits history directly
            self.conn.execute(
                "UPDATE audit_log SET action = 'auth.login.success' WHERE seq = 2")
        ok, bad, _ = verify_chain(self.conn)
        self.assertFalse(ok)
        self.assertEqual(bad, 2)

    def test_deleted_row_is_detected(self):
        _event(self.log)
        _event(self.log, "repo.push")
        _event(self.log, "admin.user.disable")
        with self.conn:
            self.conn.execute("DELETE FROM audit_log WHERE seq = 2")
        ok, bad, _ = verify_chain(self.conn)
        self.assertFalse(ok)
        self.assertEqual(bad, 2)

    def test_no_update_or_delete_api(self):
        self.assertFalse(hasattr(self.log, "update"))
        self.assertFalse(hasattr(self.log, "delete"))
        self.assertFalse(hasattr(self.log, "remove"))


class AuditCliTests(unittest.TestCase):
    def _run_verify(self, data_root: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["SAMVERK_DATA_ROOT"] = data_root
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
        return subprocess.run(
            [sys.executable, "-m", "samverk", "audit", "verify"],
            capture_output=True, text=True, env=env, timeout=30)

    def test_cli_verify_ok_then_broken(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "samverk.db")
            log = AuditLog(conn)
            _event(log)
            _event(log, "repo.push")
            conn.close()

            result = self._run_verify(td)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("OK", result.stdout)

            conn = db.init_db(Path(td) / "samverk.db")
            with conn:
                conn.execute("UPDATE audit_log SET outcome = 'failure' WHERE seq = 1")
            conn.close()

            result = self._run_verify(td)
            self.assertEqual(result.returncode, 1)
            self.assertIn("BROKEN at seq 1", result.stdout)


if __name__ == "__main__":
    unittest.main()
