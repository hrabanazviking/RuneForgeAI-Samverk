"""S-394 -- Battery v1 assembled: battery.

Proves the assembly, not the components (their own batteries
prove them): the manifest names exactly the components the
roadmap requires — build, unit, plumbing interop (S-076),
transports (S-095), security (S-022/S-311), seam (S-374) —
every named module exists, the build leg passes for real,
and the runner's aggregation arithmetic holds.

Counted with: python3 -m unittest tests.test_battery_v1
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from samverk import battery_v1

ROOT = Path(__file__).resolve().parent.parent


class BatteryV1AssemblyTests(unittest.TestCase):
    def test_manifest_covers_exactly_the_required_anchors(self):
        anchors = tuple(a for _n, a, _m in battery_v1.LEGS)
        self.assertEqual(anchors, battery_v1.REQUIRED_ANCHORS)

    def test_every_named_module_exists(self):
        for name in battery_v1.leg_names():
            for mod in battery_v1.leg_modules(name):
                path = ROOT / (mod.replace(".", "/") + ".py")
                self.assertTrue(path.exists(), "%s -> %s" % (name, mod))
                self.assertIsNotNone(importlib.util.find_spec(mod))

    def test_build_leg_passes_for_real(self):
        self.assertEqual(battery_v1.run_build_leg(), [])

    def test_runner_is_wired_to_the_manifest(self):
        runner = (ROOT / "tools" / "run_battery_v1.py").read_text(
            encoding="utf-8")
        self.assertIn("from samverk.battery_v1 import", runner)
        self.assertIn("run_suite_sharded.py", runner)

    def test_summarize_arithmetic(self):
        fake = [dict(ran=10, skipped=1, fails=0, ok=True),
                dict(ran=5, skipped=0, fails=2, ok=False)]
        total = battery_v1.summarize(fake)
        self.assertEqual(total["legs"], 2)
        self.assertEqual(total["ran"], 15)
        self.assertEqual(total["skipped"], 1)
        self.assertEqual(total["fails"], 2)
        self.assertFalse(total["ok"])
        green = battery_v1.summarize(
            [dict(ran=3, skipped=0, fails=0, ok=True)])
        self.assertTrue(green["ok"])


if __name__ == "__main__":
    unittest.main()
