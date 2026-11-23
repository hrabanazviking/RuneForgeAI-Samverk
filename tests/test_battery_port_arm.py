"""S-415 -- Battery port: Linux on ARM: battery.

Proves the register's honesty, not the Pi run itself (the
counted run recorded in samverk.battery_port_arm is the Pi
evidence): the cell identity matches the S-405 matrix cell,
PROVEN is reachable only by a complete green aarch64 run,
cross-cell claims are refused by name, and any recorded run
must be internally consistent.

Counted with: python3 -m unittest tests.test_battery_port_arm
"""
from __future__ import annotations

import unittest
from pathlib import Path

from samverk import battery_port_arm as bp

ROOT = Path(__file__).resolve().parent.parent

GREEN = {"host": "pi", "arch": "aarch64", "date": "2026-11-22",
         "wall_seconds": 1.0, "log_dir": "hidden_files/x",
         "legs": ({"name": "build", "ran": 1, "skipped": 0,
                   "fails": 0, "ok": True},),
         "ran": 1, "skipped": 0, "fails": 0, "ok": True}


class BatteryPortArmTests(unittest.TestCase):
    def test_cell_identity(self):
        self.assertEqual(bp.CELL_ID, "linux-arm64-pi5")
        self.assertEqual((bp.CELL_OS, bp.CELL_CPU), ("Linux", "ARM64"))
        self.assertEqual(bp.BATTERY_ANCHOR, "S-394")

    def test_no_run_is_not_proven(self):
        self.assertEqual(bp.cell_status(None), "not_proven")
        self.assertIn("no counted run", bp.status_reasons(None)[0])

    def test_green_arm_run_proves(self):
        self.assertEqual(bp.cell_status(GREEN), "proven")
        self.assertEqual(bp.record_consistency(GREEN), ())

    def test_failing_run_never_proves(self):
        bad = dict(GREEN, fails=2, ok=False,
                   legs=({"name": "unit", "ran": 5, "skipped": 0,
                          "fails": 2, "ok": False},), ran=5)
        self.assertEqual(bp.cell_status(bad), "not_proven")

    def test_wrong_arch_never_proves(self):
        self.assertEqual(bp.cell_status(dict(GREEN, arch="x86_64")),
                         "not_proven")

    def test_cross_cell_claim_refused(self):
        with self.assertRaises(bp.BatteryPortRefusal) as cm:
            bp.cross_cell_verdict("windows-x86-64", GREEN)
        self.assertEqual(cm.exception.reason, "cross_cell_claim")
        self.assertEqual(bp.cross_cell_verdict(bp.CELL_ID, GREEN),
                         "proven")

    def test_recorded_run_is_consistent(self):
        self.assertEqual(bp.record_consistency(), ())
        if bp.COUNTED_RUN is not None:
            self.assertEqual(bp.COUNTED_RUN["arch"], "aarch64")
            self.assertTrue(bp.COUNTED_RUN["legs"])

    def test_docs_and_runner_exist(self):
        self.assertTrue((ROOT / "docs" / "BATTERY_PORT_ARM.md").exists())
        runner = (ROOT / "tools" / "run_battery_port_arm.py").read_text(
            encoding="utf-8")
        self.assertIn("battery_port_arm", runner)


if __name__ == "__main__":
    unittest.main()
