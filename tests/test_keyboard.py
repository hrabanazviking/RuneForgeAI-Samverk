"""S-111 acceptance battery: keyboard baseline.

Acceptance (roadmap S-111): global shortcuts for
navigation and search, documented on one help page,
never trapping keyboard users.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk.keyboard import (SHORTCUTS, render_keyboard_help_page,
                              shortcut_manifest, shortcuts_for)

class KeyboardTests(unittest.TestCase):
    def test_no_shortcut_fires_while_typing(self):
        for s in SHORTCUTS:
            self.assertFalse(s.active_when_typing, s)
        for row in shortcut_manifest():
            self.assertFalse(row["active_when_typing"], row)

    def test_registry_has_no_duplicate_bindings(self):
        seen = [(s.context, s.keys) for s in SHORTCUTS]
        self.assertEqual(len(seen), len(set(seen)))
        actions = [s.action for s in SHORTCUTS]
        self.assertEqual(len(actions), len(set(actions)))

    def test_core_bindings_exist(self):
        by_action = {s.action: s for s in SHORTCUTS}
        self.assertEqual(by_action["open_file_finder"].keys, "t")
        self.assertEqual(by_action["open_file_finder"].context, "repository")
        self.assertEqual(by_action["focus_search"].keys, "/")
        self.assertEqual(by_action["open_keyboard_help"].keys, "?")
        self.assertEqual(by_action["release_focus"].keys, "Escape")

    def test_help_page_lists_every_binding(self):
        page = render_keyboard_help_page()
        for s in SHORTCUTS:
            self.assertIn(s.description, page)
        self.assertIn("not typing in a text", page)
        self.assertIn("<kbd>Escape</kbd>", page)
        self.assertNotIn("<script", page)

    def test_context_filter_keeps_globals(self):
        repo = shortcuts_for("repository")
        actions = {s.action for s in repo}
        self.assertIn("open_file_finder", actions)
        self.assertIn("focus_search", actions)  # global rides along
        global_only = shortcuts_for("global")
        self.assertNotIn("open_file_finder", {s.action for s in global_only})

if __name__ == "__main__":
    unittest.main()
