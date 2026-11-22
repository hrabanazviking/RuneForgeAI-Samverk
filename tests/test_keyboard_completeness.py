"""S-388 battery -- keyboard completeness.

Counted with: python3 -m unittest tests.test_keyboard_completeness
"""
from __future__ import annotations

import unittest

from samverk import keyboard_completeness as kb
from samverk.layout_shell import FINDABILITY_TASKS, SURFACES


class AuditTests(unittest.TestCase):
    def test_standing_keyboard_map_is_complete(self):
        self.assertEqual(kb.audit_keyboard(), [])
        self.assertTrue(kb.keyboard_passed())

    def test_every_surface_has_an_order_ending_in_exit(self):
        for surface in SURFACES:
            self.assertIn(surface, kb.FOCUS_ORDER)
            self.assertEqual(kb.FOCUS_ORDER[surface][-1], "exit_to_nav")

    def test_trap_is_named(self):
        focus = dict(kb.FOCUS_ORDER)
        focus["admin"] = ("nav_home",)
        self.assertIn("keyboard_trap:admin", kb.audit_keyboard(focus))

    def test_unreachable_action_is_named(self):
        acts = dict(kb.ACTIONS)
        acts["bogus"] = ("home", "no_such_control")
        self.assertIn("action_unreachable:bogus", kb.audit_keyboard(actions=acts))

    def test_every_action_has_a_route_ending_at_its_control(self):
        for action, (surface, control) in kb.ACTIONS.items():
            route = kb.keyboard_route(action)
            self.assertIsNotNone(route, action)
            self.assertEqual(route[-1], control)

    def test_all_focusables_have_visible_focus(self):
        for name, px in kb.FOCUS_OUTLINE.items():
            self.assertGreaterEqual(px, kb.FOCUS_OUTLINE_MIN, name)


class WalkTests(unittest.TestCase):
    def test_all_core_flows_walk_keyboard_only(self):
        for task in FINDABILITY_TASKS:
            result = kb.walk_flow(task)
            self.assertTrue(result["ok"], task)
            self.assertEqual(result["surfaces"][0], "home")
            self.assertEqual(result["surfaces"][-1],
                             FINDABILITY_TASKS[task])


if __name__ == "__main__":
    unittest.main()
