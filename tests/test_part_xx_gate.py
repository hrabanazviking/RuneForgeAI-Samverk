"""S-392 -- Part XX gate battery.

The Lawbook's Book XIV ship gate, counted: every Part XX
audit (S-381..S-391) re-run on the finished UI, removal
tests applied, and the critical-defect list read aloud.
Tove's veto is recorded in docs/PART_XX_GATE.md -- the
gate's counted battery is what this file proves; formal
closure awaits her explicit pass, named there.

Counted with: python3 -m unittest tests.test_part_xx_gate
"""
from __future__ import annotations

import unittest

from samverk import (alt_text_law, design_tokens, effects_off,
                     grayscale_coherence, keyboard_completeness,
                     layout_shell, motion_discipline,
                     never_colour_only, screen_reader_pass,
                     target_sizes, text_scaling)


class PartXXGateTests(unittest.TestCase):
    def test_s381_tokens_registry_valid(self):
        self.assertEqual(design_tokens.validate_registry(), [])

    def test_s382_shell_coherent_and_findable(self):
        self.assertEqual(layout_shell.audit_shell(), [])
        self.assertTrue(layout_shell.findability_passed())

    def test_s383_grayscale_proof_rerun(self):
        self.assertEqual(grayscale_coherence.audit_grayscale(), [])

    def test_s384_scaling_proof_rerun(self):
        self.assertEqual(text_scaling.audit_scaling(), [])

    def test_s385_effects_off_proof_rerun_removal_test(self):
        # Removal test: strip every effect; hierarchy must stand.
        self.assertEqual(effects_off.audit_effects_off(), [])
        stripped = tuple(r[:6] + ((),) + r[7:]
                         for r in effects_off.ELEMENTS)
        self.assertEqual(effects_off.audit_effects_off(stripped), [])

    def test_s386_targets_pass(self):
        self.assertTrue(target_sizes.targets_passed())

    def test_s387_never_colour_only(self):
        self.assertTrue(never_colour_only.colour_only_passed())

    def test_s388_keyboard_complete(self):
        self.assertTrue(keyboard_completeness.keyboard_passed())

    def test_s389_reader_structure_passes(self):
        self.assertTrue(screen_reader_pass.screen_reader_passed())

    def test_s390_alt_text_law_holds(self):
        self.assertTrue(alt_text_law.alt_text_passed())

    def test_s391_motion_disciplined(self):
        self.assertTrue(motion_discipline.motion_passed())

    def test_no_critical_visual_defects_open(self):
        # The named remainder F-S389-1 (live reader session) is a
        # verification remainder, not a visual defect; every
        # visual audit above stands at zero problems.
        problems = (
            grayscale_coherence.audit_grayscale()
            + text_scaling.audit_scaling()
            + effects_off.audit_effects_off()
            + target_sizes.audit_targets()
            + never_colour_only.audit_statuses()
            + motion_discipline.audit_motion())
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
