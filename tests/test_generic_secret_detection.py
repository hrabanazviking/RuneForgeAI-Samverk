"""S-290 acceptance battery: generic secret detection.

Acceptance (roadmap S-290): Generic secret detection
— entropy and context heuristics with a measured
false-positive rate on a labelled corpus (the rate is
published, not vibes).

Every secret-shaped string here is synthetic and
hand-assembled; no real credential appears in this
battery. The centre laws: the detector catches
unshaped secrets in secret contexts and bare, stays
silent on the labelled benign world (hashes, UUIDs,
prose, placeholders, encoded ordinary text), never
carries the matched text in a finding, and the
published rates equal the rates re-measured from the
labelled corpus on every run.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import hashlib, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.db import schema_version
from samverk.generic_secret_detection import (
    DEFAULT_CONFIG, PUBLISHED_CORPUS_SIZE,
    PUBLISHED_FALSE_POSITIVE_RATE, PUBLISHED_PRECISION,
    PUBLISHED_RECALL, DetectionConfig, GenericFinding,
    GenericSecretError, assess_candidate,
    build_labelled_corpus, combined_scan, evaluate_corpus,
    extract_candidates, pattern_layer_available,
    redact_candidate, render_generic_detection_page,
    scan_generic, shannon_entropy)
from samverk.taxonomy import ADMIN_EVENTS, AUDIT_EVENTS, AUTH_EVENTS, REPO_EVENTS

SECRET = "xK9mQ2vR8nB4wZ7pL3sD6fG1hJ5kM0"


class EntropyTests(unittest.TestCase):
    def test_entropy_known_values(self):
        self.assertEqual(shannon_entropy(""), 0.0)
        self.assertEqual(shannon_entropy("aaaaaaaa"), 0.0)
        self.assertAlmostEqual(shannon_entropy("ab"), 1.0)
        self.assertAlmostEqual(shannon_entropy("abcd"), 2.0)
        self.assertGreater(shannon_entropy(SECRET),
                           shannon_entropy("the the the the"))

    def test_config_validation_refuses_nonsense(self):
        with self.assertRaises(GenericSecretError) as cm:
            scan_generic("x", DetectionConfig(min_length=2))
        self.assertEqual(cm.exception.code, "config_invalid")
        with self.assertRaises(GenericSecretError):
            extract_candidates("x", DetectionConfig(flag_score=0))
        with self.assertRaises(GenericSecretError):
            extract_candidates("x", DetectionConfig(entropy_floor=9.0))


class DetectionTests(unittest.TestCase):
    def test_assigned_secret_is_flagged_with_context(self):
        found = scan_generic('api_key = "' + SECRET + '"')
        self.assertEqual(len(found), 1)
        f = found[0]
        self.assertEqual(f.context, "secret-named assignment")
        self.assertGreaterEqual(f.entropy, 4.2)
        self.assertGreaterEqual(f.score, DEFAULT_CONFIG.flag_score)

    def test_bare_high_entropy_blob_is_flagged(self):
        found = scan_generic(
            "dump: aT3kQ9wZ8xB2nM7vL4sD6fG9hJ1kM5pR8uW0yA3cE6gH end")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].context, "bare high-entropy")

    def test_span_line_and_column(self):
        text = "first line\nab " + SECRET + " tail"
        found = scan_generic('api_key = "' + text + '"')
        self.assertTrue(found)
        f = scan_generic("xx\napi_key = \"" + SECRET + "\"")[0]
        self.assertEqual(f.line, 2)
        self.assertEqual(f.column, 12)

    def test_hex_secret_in_secret_context_is_flagged(self):
        found = scan_generic(
            'client_secret = "9f2c4a7e1b8d0f3a5c6e7d8b9a0f1c2e"')
        self.assertEqual(len(found), 1)

    def test_dsn_password_position_is_flagged(self):
        found = scan_generic(
            "dsn = postgres://svc:Kx9mQ2vR8nB4wZ7p@db.internal/app")
        self.assertEqual(len(found), 1)

    def test_findings_return_in_span_order(self):
        text = ('token = "Q7vR8nB4wZ2pL9sD6fG1hJ3k" then '
                'api_key = "' + SECRET + '"')
        found = scan_generic(text)
        self.assertEqual(len(found), 2)
        self.assertEqual([f.start for f in found],
                         sorted(f.start for f in found))


class BenignSilenceTests(unittest.TestCase):
    def test_hashes_and_digests_stay_silent(self):
        for text in (
            "commit = 9f2c4a7e1b8d0f3a5c6e7d8b9a0f1c2e3d4b5a69",
            "9f2c4a7e1b8d0f3a5c6e7d8b9a0f1c2e3d4b5a69",
            "sha256 = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            'etag = "5d41402abc4b2a76b9719d911017c592"',
        ):
            with self.subTest(text=text[:20]):
                self.assertEqual(scan_generic(text), [], text)

    def test_uuids_placeholders_and_prose_stay_silent(self):
        for text in (
            "550e8400-e29b-41d4-a716-446655440000",
            'api_key = "your_api_key_here_example"',
            'password = "changeme123456789"',
            "The quick brown fox jumps over the lazy dog.",
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "remote = https://volmarr@example.org/samverk.git",
        ):
            with self.subTest(text=text[:20]):
                self.assertEqual(scan_generic(text), [], text)

    def test_encoded_ordinary_text_stays_silent(self):
        self.assertEqual(
            scan_generic("greeting = aGVsbG8gd29ybGQgdGhpcyBpcyBhIHRlc3Q"), [])
        cands = extract_candidates(
            "greeting = aGVsbG8gd29ybGQgdGhpcyBpcyBhIHRlc3Q")
        verdicts = [assess_candidate(c) for c in cands]
        self.assertTrue(any(v.suppressed == "encoded_prose"
                            for v in verdicts))

    def test_encoded_assets_stay_silent(self):
        self.assertEqual(scan_generic(
            "icon = data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"), [])

    def test_empty_and_ordinary_text(self):
        self.assertEqual(scan_generic(""), [])
        self.assertEqual(scan_generic("hello world"), [])


class CorpusMeasurementTests(unittest.TestCase):
    def test_corpus_is_labelled_and_balanced(self):
        corpus = build_labelled_corpus()
        self.assertEqual(len(corpus), PUBLISHED_CORPUS_SIZE)
        self.assertGreaterEqual(
            sum(1 for c in corpus if c.is_secret), 10)
        self.assertGreaterEqual(
            sum(1 for c in corpus if not c.is_secret), 10)
        self.assertTrue(all(c.category for c in corpus))

    def test_published_rates_are_the_measured_rates(self):
        report = evaluate_corpus()
        self.assertEqual(report.total, PUBLISHED_CORPUS_SIZE)
        self.assertEqual(report.false_positive_rate,
                         PUBLISHED_FALSE_POSITIVE_RATE)
        self.assertEqual(report.precision, PUBLISHED_PRECISION)
        self.assertEqual(report.recall, PUBLISHED_RECALL)

    def test_measured_rates_meet_the_published_bar(self):
        report = evaluate_corpus()
        self.assertLessEqual(report.false_positive_rate, 0.05)
        self.assertGreaterEqual(report.recall, 0.9)
        self.assertEqual(report.false_negatives, 0)
        self.assertEqual(report.false_positives, 0)
        d = report.to_dict()
        self.assertEqual(d["true_positives"] + d["false_negatives"],
                         d["secret_cases"])
        self.assertEqual(d["false_positives"] + d["true_negatives"],
                         d["benign_cases"])

    def test_every_corpus_case_is_judged_as_labelled(self):
        for case in build_labelled_corpus():
            with self.subTest(category=case.category):
                self.assertEqual(bool(scan_generic(case.text)),
                                 case.is_secret, case.text)


class FindingLawTests(unittest.TestCase):
    def test_finding_never_carries_the_secret(self):
        found = scan_generic('api_key = "' + SECRET + '"')
        f = found[0]
        self.assertEqual(f.fingerprint, hashlib.sha256(
            SECRET.encode("utf-8")).hexdigest())
        self.assertNotIn(SECRET, f.redacted)
        self.assertNotIn(SECRET, repr(f))
        self.assertNotIn(SECRET, str(f.to_dict()))
        self.assertIn(str(len(SECRET)), f.redacted)
        page = render_generic_detection_page(found)
        self.assertNotIn(SECRET, page)
        self.assertIn(f.redacted, page)

    def test_redact_candidate_is_length_only(self):
        out = redact_candidate(SECRET)
        self.assertNotIn(SECRET[:8], out)
        self.assertIn(str(len(SECRET)), out)

    def test_render_empty_and_escaped(self):
        page = render_generic_detection_page([], title="<b>Scan</b>")
        self.assertIn("No generic secrets found.", page)
        self.assertNotIn("<b>Scan</b>", page)
        self.assertIn("&lt;b&gt;", page)


class SeamTests(unittest.TestCase):
    def test_combined_scan_stands_alone_without_s289(self):
        out = combined_scan('api_key = "' + SECRET + '"')
        self.assertEqual(len(out["generic"]), 1)
        self.assertEqual(out["pattern_available"],
                         pattern_layer_available())
        if not pattern_layer_available():
            self.assertIsNone(out["patterns"])


class StandingPinTests(unittest.TestCase):
    def test_no_migration_and_no_new_taxonomy_event(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "samverk.db")
            self.assertEqual(schema_version(conn), 121)
            conn.close()
        self.assertEqual(len(AUDIT_EVENTS), 134)
        self.assertEqual(len(AUTH_EVENTS), 33)
        self.assertEqual(len(REPO_EVENTS), 88)
        self.assertEqual(len(ADMIN_EVENTS), 13)


if __name__ == "__main__":
    unittest.main()
