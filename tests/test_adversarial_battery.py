"""S-311 acceptance battery: adversarial battery.

Acceptance (roadmap S-311): Adversarial battery
-- scanner evasion attempts, SARIF fuzzing,
signature spoofing attempts: the suite attacks
Samverk and reports honestly.

The centre is samverk/adversarial_battery.py: 54
attacks in three families, every verdict computed
by the real defence it attacks (S-289 scan_text,
S-290 scan_generic, S-291 scan_blob_text, S-302
sarif_problems, S-303 extract_findings, S-305
verify_ssh / extract_signature). The battery pins
the measured truth, including the misses: mutated
shaped tokens evade the pattern layer (13 named
misses), context-suppressed and symbol-fragmented
secrets evade the generic layer, and the push-scan
seam still catches a base64 token through the
generic layer. SARIF fuzzing: 16 refused, 3
schema-permitted accepts, dedup holds against a
partial-fingerprint spoof and does not collapse a
moved finding; no judge crashes. Signature
spoofing: every spoof rejected, both controls
accepted. No storage, no audit event, no
migration: taxonomy stands at 135 (33 auth / 89
repo / 13 admin), schema at 128.

Counted with: python3 -m unittest tests.test_adversarial_battery
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.adversarial_battery import (
    FAMILIES, PUBLISHED_ATTACK_COUNT, AttackResult, BatteryReport,
    render_adversarial_battery_page, run_full_battery,
    run_sarif_fuzz_battery, run_scanner_evasion_battery,
    run_signature_spoof_battery)
from samverk.db import schema_version


def _by_name(results):
    return {r.name: r for r in results}


class EvasionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = _by_name(run_scanner_evasion_battery())

    def test_controls_are_caught(self):
        for name in ("control_plain_token", "control_generic_secret",
                     "combined_push_scan_plain"):
            self.assertEqual(self.results[name].outcome, "caught", name)

    def test_mutated_shaped_tokens_are_named_misses(self):
        for name in ("split_across_lines", "split_with_space",
                     "split_with_html_comment", "zero_width_inserted",
                     "base64_encoded", "hex_encoded", "reversed",
                     "prefix_case_mutated", "prefix_underscore_swapped",
                     "dashes_inserted", "fullwidth_homoglyphs",
                     "cyrillic_homoglyph", "quoted_printable_underscore"):
            self.assertEqual(self.results[name].outcome, "missed", name)

    def test_generic_context_gaps_are_named_misses(self):
        for name in ("generic_in_hash_context", "generic_marked_example",
                     "generic_symbol_fragmented"):
            self.assertEqual(self.results[name].outcome, "missed", name)

    def test_push_seam_catches_base64_via_generic_layer(self):
        self.assertEqual(
            self.results["combined_push_scan_base64"].outcome, "caught")
        self.assertEqual(
            self.results["generic_split_across_lines"].outcome, "caught")


class SarifFuzzTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = _by_name(run_sarif_fuzz_battery())

    def test_no_judge_crashes(self):
        for r in self.results.values():
            self.assertNotEqual(r.outcome, "crashed", r.name)

    def test_malformed_documents_are_refused(self):
        for name in ("version_missing", "version_spoofed_trailing_space",
                     "version_wrong_type", "runs_not_an_array",
                     "runs_empty", "runs_over_limit",
                     "level_uppercase_spoof", "level_invented_severity",
                     "message_missing", "message_empty_object",
                     "result_not_an_object", "locations_not_an_array",
                     "tool_name_empty", "document_is_a_list",
                     "document_is_a_string", "document_is_none"):
            self.assertEqual(self.results[name].outcome, "refused", name)

    def test_schema_permitted_documents_are_accepted_and_named(self):
        for name in ("control_valid_document", "message_id_only",
                     "deep_nesting_in_properties"):
            self.assertEqual(self.results[name].outcome, "accepted", name)

    def test_dedup_holds_and_moved_finding_survives(self):
        self.assertEqual(
            self.results["duplicate_results_dedup"].outcome, "deduped")
        self.assertEqual(
            self.results["partial_fingerprint_spoof"].outcome, "deduped")
        self.assertEqual(
            self.results["moved_result_not_deduped"].outcome,
            "not_deduped")


class SignatureSpoofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = _by_name(run_signature_spoof_battery())

    def test_controls_are_accepted(self):
        for name in ("control_valid_signature",
                     "control_uppercase_header_name"):
            self.assertEqual(self.results[name].outcome, "accepted", name)

    def test_every_spoof_is_rejected(self):
        for name in ("wrong_key_spoof", "tampered_payload",
                     "wrong_namespace", "truncated_armour",
                     "garbled_base64_armour", "missing_end_marker",
                     "signature_in_message_body",
                     "valid_signature_behind_bogus_header",
                     "message_tampered_after_signing"):
            self.assertEqual(self.results[name].outcome, "rejected", name)


class ReportHonestyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_full_battery()

    def test_published_count_matches_measured(self):
        self.assertEqual(len(self.report.results), PUBLISHED_ATTACK_COUNT)
        self.assertEqual(PUBLISHED_ATTACK_COUNT, 54)
        for family in FAMILIES:
            self.assertTrue(self.report.family_results(family), family)

    def test_counts_add_up(self):
        self.assertEqual(sum(self.report.counts().values()), 54)

    def test_honest_gaps_name_every_miss(self):
        gaps = {g.name for g in self.report.honest_gaps()}
        self.assertEqual(len(gaps), 16)
        self.assertIn("base64_encoded", gaps)
        self.assertIn("generic_symbol_fragmented", gaps)
        self.assertNotIn("control_plain_token", gaps)
        self.assertNotIn("control_uppercase_header_name", gaps)

    def test_page_escapes_attack_text(self):
        evil = BatteryReport(results=(AttackResult(
            family="x", name="<script>alert(1)</script>",
            target="t", outcome="missed",
            detail="<img src=x onerror=alert(1)>"),))
        page = render_adversarial_battery_page(evil)
        self.assertNotIn("<script>", page)
        self.assertNotIn("<img", page)
        self.assertIn("&lt;script&gt;", page)

    def test_no_storage_no_audit_no_migration(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "samverk.db")
            try:
                self.assertEqual(schema_version(conn), 128)
                self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
