"""S-390 battery -- alt-text law.

Counted with: python3 -m unittest tests.test_alt_text_law
"""
from __future__ import annotations

import unittest

from samverk import alt_text_law as al
from samverk.markdown_pipeline import render_markdown


class JudgeTests(unittest.TestCase):
    def test_real_alt_passes(self):
        self.assertEqual(al.judge_alt("A cat asleep on the wall"), [])

    def test_missing_and_generic_and_filename_refused(self):
        self.assertEqual(al.judge_alt(""), ["alt_missing"])
        self.assertEqual(al.judge_alt(None), ["alt_missing"])
        self.assertEqual(al.judge_alt("image"), ["alt_generic"])
        self.assertEqual(al.judge_alt("cat.png"), ["alt_is_filename"])

    def test_diagram_must_be_described_not_named(self):
        self.assertIn("alt_diagram_too_thin",
                      al.judge_alt("Flow diagram", "diagram"))
        self.assertEqual(al.judge_alt(
            "Flow from login through token minting to first repo",
            "diagram"), [])


class DecideTests(unittest.TestCase):
    def test_user_supplied_alt_is_honoured(self):
        self.assertEqual(al.decide_alt("Authored words", "My own words"),
                         "My own words")

    def test_failing_user_alt_falls_back_to_authored(self):
        self.assertEqual(al.decide_alt("Authored words", "image"),
                         "Authored words")

    def test_no_real_alt_anywhere_is_refused(self):
        self.assertIsNone(al.decide_alt("", "photo"))


class RenderedTests(unittest.TestCase):
    def test_markdown_images_never_render_alt_less(self):
        for source in ("![](cat.png)", "![image](cat.png)",
                       "![A cat asleep](cat.png)"):
            self.assertEqual(al.audit_rendered(render_markdown(source)), [],
                             source)

    def test_docs_tree_is_clean(self):
        self.assertEqual(al.audit_docs(), [])
        self.assertTrue(al.alt_text_passed())

    def test_planted_bad_img_is_named(self):
        problems = al.audit_rendered('<p><img src="x.png" alt=""></p>')
        self.assertTrue(any(p.startswith("alt_missing") for p in problems))


if __name__ == "__main__":
    unittest.main()
