"""S-385 battery -- effects-off coherence.

Counted with: python3 -m unittest tests.test_effects_off
"""
from __future__ import annotations

import unittest

from samverk import effects_off as eo


class AuditTests(unittest.TestCase):
    def test_standing_ui_survives_effects_off(self):
        self.assertEqual(eo.audit_effects_off(), [])
        self.assertTrue(eo.effects_off_passed())

    def test_glow_only_rank_is_named(self):
        rows = (("top", "g", 2, 16, 400, 0, ("glow",), None, None),
                ("low", "g", 1, 16, 400, 0, (), None, None))
        self.assertIn("effects_only:g:top/low", eo.audit_effects_off(rows))

    def test_structural_rank_passes_without_effects(self):
        rows = (("top", "g", 2, 20, 400, 0, ("glow",), None, None),
                ("low", "g", 1, 16, 400, 0, (), None, None))
        self.assertEqual(eo.audit_effects_off(rows), [])

    def test_low_contrast_text_is_named(self):
        rows = (("dim", "g", 1, 16, 400, 0, (), "#555f6b", "#12151a"),)
        self.assertIn("illegible_without_effects:dim",
                      eo.audit_effects_off(rows))

    def test_every_text_element_clears_contrast(self):
        for row in eo.ELEMENTS:
            if row[7] is not None:
                self.assertGreaterEqual(
                    eo.contrast_ratio(row[7], row[8]), eo.MIN_CONTRAST,
                    row[0])

    def test_effects_in_use_are_only_glow_and_texture(self):
        used = {fx for row in eo.ELEMENTS for fx in row[6]}
        self.assertEqual(used, {"glow", "texture"})
        # Stripping every effect changes no audit outcome.
        stripped = tuple(r[:6] + ((),) + r[7:] for r in eo.ELEMENTS)
        self.assertEqual(eo.audit_effects_off(stripped), [])


if __name__ == "__main__":
    unittest.main()
