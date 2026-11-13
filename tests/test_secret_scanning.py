"""S-289 acceptance battery: secret scanning patterns v1.

Acceptance (roadmap S-289): Secret scanning patterns
v1 — detector set for the major public token formats,
written from public documentation of their shapes.

Every example token here is synthetic: a published
prefix plus repeated filler characters, assembled to
the provider's documented shape. No real credential
appears in this battery, and none is needed — the
slice judges shapes, which are public.

The battery's centre laws: each detector fires on its
own shape and stays silent on a near-miss (wrong
length, wrong character set, prefix alone); a finding
never carries the matched text (redaction, rendering
and repr are all checked against the full token); and
overlap resolves to exactly one finding per span.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import hashlib, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.db import schema_version
from samverk.secret_scanning import (
    DETECTORS, DETECTOR_IDS, Finding, SecretScanningError,
    detector_by_id, list_detectors, redact_match, scan_lines,
    scan_text, render_secret_scanning_page)
from samverk.taxonomy import ADMIN_EVENTS, AUDIT_EVENTS, AUTH_EVENTS, REPO_EVENTS

TOKENS = {
    "github_fine_grained_pat": "github_pat_" + "A" * 82,
    "github_pat_classic": "ghp_" + "B" * 36,
    "github_oauth_token": "gho_" + "C" * 36,
    "github_user_to_server": "ghu_" + "D" * 36,
    "github_server_to_server": "ghs_" + "E" * 36,
    "github_refresh_token": "ghr_" + "F" * 76,
    "gitlab_pat": "glpat-" + "G" * 20,
    "aws_access_key_id": "AKIA" + "H" * 16,
    "google_api_key": "AIza" + "I" * 35,
    "google_oauth_client_secret": "GOCSPX-" + "J" * 28,
    "slack_token": "xoxb-1234567890-abcdefghij",
    "slack_webhook": ("https://hooks.slack.com/services/"
                      "T" + "K" * 8 + "/B" + "L" * 8 + "/" + "M" * 24),
    "stripe_secret_key": "sk_live_" + "N" * 24,
    "stripe_webhook_secret": "whsec_" + "O" * 32,
    "sendgrid_api_key": "SG." + "P" * 22 + "." + "Q" * 43,
    "twilio_api_key": "SK" + "0123456789abcdef" * 2,
    "npm_token": "npm_" + "R" * 36,
    "pypi_token": "pypi-" + "S" * 30,
    "digitalocean_token": "dop_v1_" + "a" * 64,
    "square_access_token": "sq0atp-" + "T" * 22,
    "mailchimp_api_key": "0123456789abcdef" * 2 + "-us7",
    "jwt_compact": "eyJ" + "a" * 10 + ".eyJ" + "b" * 10 + "." + "c" * 10,
    "private_key_block": "-----BEGIN RSA PRIVATE KEY-----",
}


class RegistryTests(unittest.TestCase):
    def test_registry_covers_the_v1_set(self):
        self.assertEqual(len(DETECTORS), 23)
        self.assertEqual(len(set(DETECTOR_IDS)), 23)
        self.assertEqual(set(TOKENS), set(DETECTOR_IDS))
        for det in DETECTORS:
            self.assertTrue(det.provider)
            self.assertTrue(det.label)
            self.assertTrue(det.shape)

    def test_detector_by_id_and_unknown_refusal(self):
        self.assertEqual(detector_by_id("github_pat_classic").provider,
                         "GitHub")
        self.assertEqual(list_detectors(), DETECTORS)
        with self.assertRaises(SecretScanningError) as cm:
            detector_by_id("nope")
        self.assertEqual(cm.exception.code, "detector_unknown")
        with self.assertRaises(SecretScanningError) as cm:
            scan_text("x", detector_ids=["nope"])
        self.assertEqual(cm.exception.code, "detector_unknown")


class DetectorShapeTests(unittest.TestCase):
    def test_each_detector_fires_on_its_own_shape(self):
        for det_id, token in TOKENS.items():
            with self.subTest(detector=det_id):
                found = scan_text("prefix " + token + " suffix")
                hits = [f for f in found if f.detector_id == det_id]
                self.assertEqual(len(hits), 1, found)
                self.assertEqual(hits[0].provider,
                                 detector_by_id(det_id).provider)

    def test_near_misses_stay_silent(self):
        misses = [
            "ghp_" + "B" * 35,
            "ghp_" + "B" * 35 + "-",
            "gho_" + "C" * 10,
            "glpat-" + "G" * 19,
            "AKIA" + "h" * 16,
            "AKIA" + "H" * 15,
            "AIza" + "I" * 34,
            "GOCSPX-" + "J" * 27,
            "npm_" + "R" * 35,
            "dop_v1_" + "a" * 63,
            "dop_v1_" + "g" * 64,
            "whsec_" + "O" * 10,
            "-----BEGIN CERTIFICATE-----",
            "-----BEGIN PUBLIC KEY-----",
            "the ghp_ prefix alone is not a token",
            "an ordinary sentence with no secrets at all",
            "",
        ]
        for text in misses:
            with self.subTest(text=text[:24]):
                self.assertEqual(scan_text(text), [], text)

    def test_aws_variants_and_stripe_restricted_key(self):
        for head in ("AKIA", "ASIA", "ABIA", "ACCA"):
            found = scan_text(head + "Z" * 16)
            self.assertEqual([f.detector_id for f in found],
                             ["aws_access_key_id"])
        found = scan_text("rk_test_" + "U" * 24)
        self.assertEqual([f.detector_id for f in found],
                         ["stripe_secret_key"])
        found = scan_text("-----BEGIN PRIVATE KEY-----")
        self.assertEqual([f.detector_id for f in found],
                         ["private_key_block"])
        found = scan_text("-----BEGIN OPENSSH PRIVATE KEY-----")
        self.assertEqual([f.detector_id for f in found],
                         ["private_key_block"])


class FindingLawTests(unittest.TestCase):
    def test_span_line_and_column(self):
        token = TOKENS["github_pat_classic"]
        text = "first line\nab " + token + " tail\nthird"
        found = scan_text(text)
        self.assertEqual(len(found), 1)
        f = found[0]
        self.assertEqual((f.start, f.end), (14, 14 + len(token)))
        self.assertEqual(f.line, 2)
        self.assertEqual(f.column, 4)
        self.assertEqual(text[f.start:f.end], token)

    def test_findings_return_in_span_order(self):
        text = (TOKENS["npm_token"] + " then "
                + TOKENS["gitlab_pat"] + " then "
                + TOKENS["aws_access_key_id"])
        found = scan_text(text)
        self.assertEqual([f.detector_id for f in found],
                         ["npm_token", "gitlab_pat", "aws_access_key_id"])
        self.assertEqual([f.start for f in found],
                         sorted(f.start for f in found))

    def test_overlap_yields_one_finding_per_span(self):
        token = TOKENS["github_fine_grained_pat"]
        found = scan_text(token)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].detector_id,
                         "github_fine_grained_pat")

    def test_detector_filter_narrows_the_set(self):
        text = TOKENS["npm_token"] + " " + TOKENS["gitlab_pat"]
        found = scan_text(text, detector_ids=["gitlab_pat"])
        self.assertEqual([f.detector_id for f in found], ["gitlab_pat"])

    def test_finding_never_carries_the_secret(self):
        token = TOKENS["stripe_secret_key"]
        found = scan_text("key = " + token)
        f = found[0]
        self.assertEqual(
            f.fingerprint,
            hashlib.sha256(token.encode("utf-8")).hexdigest())
        self.assertNotIn(token, f.redacted)
        self.assertNotIn(token, repr(f))
        self.assertNotIn(token, str(f.to_dict()))
        self.assertIn("sk_", f.redacted)
        self.assertIn(str(len(token)), f.redacted)
        page = render_secret_scanning_page(found)
        self.assertNotIn(token, page)
        self.assertIn("Stripe", page)
        self.assertIn(f.redacted, page)

    def test_redact_match_keeps_only_prefix_and_length(self):
        det = detector_by_id("aws_access_key_id")
        token = TOKENS["aws_access_key_id"]
        out = redact_match(det, token)
        self.assertNotIn(token, out)
        self.assertTrue(out.startswith("AKIA"))
        self.assertIn(str(len(token)), out)

    def test_scan_lines_numbers_from_one(self):
        token = TOKENS["gitlab_pat"]
        found = scan_lines(["clean", "x " + token, "also clean"])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].line, 2)
        self.assertEqual(found[0].column, 3)

    def test_render_empty_and_escaped(self):
        page = render_secret_scanning_page([], title="<b>Scan</b>")
        self.assertIn("No secret shapes found.", page)
        self.assertNotIn("<b>Scan</b>", page)
        self.assertIn("&lt;b&gt;", page)


class StandingPinTests(unittest.TestCase):
    def test_no_migration_and_no_new_taxonomy_event(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "samverk.db")
            self.assertEqual(schema_version(conn), 126)
            conn.close()
        self.assertEqual(len(AUDIT_EVENTS), 135)
        self.assertEqual(len(AUTH_EVENTS), 33)
        self.assertEqual(len(REPO_EVENTS), 89)
        self.assertEqual(len(ADMIN_EVENTS), 13)


if __name__ == "__main__":
    unittest.main()
