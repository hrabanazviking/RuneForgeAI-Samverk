"""S-113 acceptance battery: empty and error states.

Acceptance (roadmap S-113): every list and page has a
designed empty state that says what to do next
(user-friendliness law).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk.errors import ERROR_CODES
from samverk.page_states import (EMPTY_SURFACES, PageState, PageStateError,
                                 empty_state, error_state, render_state_page)

class PageStateTests(unittest.TestCase):
    def test_every_surface_has_a_complete_state(self):
        expected = {"repo_home", "file_browser", "commit_list", "compare",
                    "contributors", "file_finder", "blob", "blame"}
        self.assertEqual(set(EMPTY_SURFACES), expected)
        for surface in sorted(EMPTY_SURFACES):
            state = empty_state(surface, base="/volmarr/samverk")
            self.assertEqual(state.kind, "empty")
            self.assertTrue(state.title)
            self.assertTrue(state.message)
            self.assertTrue(state.next_step)  # says what to do next
            self.assertTrue(state.action_label)
            self.assertTrue(state.action_href.startswith("/volmarr/samverk"))

    def test_unknown_surface_is_a_programming_error(self):
        with self.assertRaises(PageStateError) as caught:
            empty_state("wiki")
        self.assertEqual(caught.exception.reason, "surface_unknown")
        with self.assertRaises(PageStateError):
            empty_state(None)

    def test_incomplete_state_cannot_be_constructed(self):
        with self.assertRaises(PageStateError):
            PageState(surface="x", kind="empty", title="T", message="M",
                      next_step="", action_label="Go", action_href="/")
        with self.assertRaises(PageStateError):
            PageState(surface="x", kind="empty", title="T", message="M",
                      next_step="Do it.", action_label="", action_href="")

    def test_every_public_error_code_has_a_plain_state(self):
        for code in sorted(ERROR_CODES):
            state = error_state(code)
            self.assertEqual(state.kind, "error")
            self.assertEqual(state.surface, code)
            self.assertTrue(state.title and state.message and state.next_step)
            self.assertTrue(state.action_href)
        with self.assertRaises(PageStateError) as caught:
            error_state("stack_trace_please")
        self.assertEqual(caught.exception.reason, "error_code_unknown")

    def test_not_found_never_distinguishes_missing_from_private(self):
        state = error_state("not_found")
        self.assertIn("may not exist", state.message)
        self.assertIn("permission", state.message)
        page = render_state_page(state)
        self.assertIn("could not be found", page)

    def test_error_id_is_the_only_extra_detail_shown(self):
        state = error_state("internal", error_id="0123456789abcdef")
        self.assertIn("0123456789abcdef", state.message)
        self.assertIn("quote this id", state.message)
        page = render_state_page(state)
        self.assertIn("0123456789abcdef", page)
        for forbidden in ("Traceback", "/home/", "Exception", ".py\", line"):
            self.assertNotIn(forbidden, page)
        self.assertNotIn("<script", page)

    def test_rendering_escapes_and_offers_the_action(self):
        state = empty_state("file_finder", base="/volmarr/samverk")
        page = render_state_page(state)
        self.assertIn('data-surface="file_finder"', page)
        self.assertIn("What to do next:", page)
        self.assertIn('href="/volmarr/samverk"', page)
        self.assertNotIn("<script", page)

if __name__ == "__main__":
    unittest.main()
