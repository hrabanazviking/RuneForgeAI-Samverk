"""S-312 — PART XV GATE battery: security scanning & assurance, assembled.

The whole Part XV system struck at once, in the house
gate shape of S-204/S-220/S-236/S-256/S-272/S-288 — no
new production code, only the battery that walks the
landed S-289..S-311 machinery end to end through its
public seams, at the things the gate names: **claims
register (S-023) extended over every Part XV claim;
counted scanning battery green.**

- **The register extension (S-023 over Part XV)** —
  docs/CLAIMS_REGISTER.md gains one row per Part XV
  slice, C-13..C-35 for S-289..S-311: every row PROVEN,
  every row naming the slice's own counted battery as
  its evidence, and this battery re-checks the rows
  mechanically (ids, slice coverage, evidence files
  real, evidence batteries naming their own slice).
- **The counted scanning battery** — the pattern layer
  (S-289) catches a shaped token and never echoes it;
  the generic layer (S-290) re-measures its labelled
  corpus at the published rates; the combined push
  seam (S-291) judges a blob once across both layers;
  push protection's refusal law (S-292) is the gate's
  veto the seam feeds; custom patterns (S-295) judge
  under the same overlap and redaction law; validity
  (S-296) defaults to unknown, displayed as such.
- **Dependencies & code scanning** — manifests parse
  (S-297) against the bundled dated advisory snapshot
  whose age is displayed (S-298); SARIF is judged
  whole (S-302), fingerprinted so one finding across
  runs is one alert with per-branch transitions
  (S-303).
- **Signatures & surfaces** — an unsigned commit
  extracts as unsigned (S-305); vigil mode (S-306)
  holds a foreign-key verified badge down to
  unverified and never lifts one up; the adversarial
  battery (S-311) runs whole and names its misses.

The gate claims no migration and no taxonomy event:
the assembled system stands at schema 128 with 135
audit events (33 auth / 89 repo / 13 admin), and the
battery proves both pins.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.adversarial_battery import run_full_battery
from samverk.advisory_data import AdvisoryStore
from samverk.code_scanning import sarif_problems
from samverk.code_scanning_alerts import (
    compute_transitions, extract_findings, fingerprint_finding)
from samverk.commit_signatures import extract_signature
from samverk.custom_patterns import scan_text_custom
from samverk.db import schema_version
from samverk.dependency_graph import parse_manifest
from samverk.generic_secret_detection import (
    PUBLISHED_CORPUS_SIZE, PUBLISHED_FALSE_POSITIVE_RATE,
    PUBLISHED_PRECISION, PUBLISHED_RECALL, evaluate_corpus,
    scan_generic)
from samverk.push_scanning import scan_blob_text
from samverk.secret_scanning import list_detectors, scan_text
from samverk.secret_validity import decide_validity
from samverk.vigil_mode import decide_vigil_display

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "docs" / "CLAIMS_REGISTER.md"
TOKEN = "ghp_" + "B" * 36
GENERIC = "Kx9Qm2Zv8Lp4Rt7Wn3Hs6Yd1Fj5Bc0"

# The Part XV claims, slice by slice: the register row
# for S-NNN must carry id C-(13 + NNN - 289), the slice's
# own battery as evidence, and the anchor phrase below.
PART_XV_CLAIMS = {
    289: ("test_secret_scanning.py", "major public token formats"),
    290: ("test_generic_secret_detection.py", "measured false-positive rate"),
    291: ("test_push_scanning.py", "full introduced history"),
    292: ("test_push_protection.py", "never echoing the secret"),
    293: ("test_push_protection_bypass.py", "stated reason"),
    294: ("test_secret_alert_lifecycle.py", "can reopen"),
    295: ("test_custom_patterns.py", "dry-run against history"),
    296: ("test_secret_validity.py", "unknown offline"),
    297: ("test_dependency_graph.py", "dependency table per repository"),
    298: ("test_advisory_data.py", "age is displayed"),
    299: ("test_dependency_alerts.py", "fixed version when known"),
    300: ("test_advisory_refresh.py", "staleness is shown honestly"),
    301: ("test_dependency_review.py", "new vulnerabilities flagged"),
    302: ("test_code_scanning.py", "stored per commit"),
    303: ("test_code_scanning_alerts.py", "is one alert"),
    304: ("test_code_scanning_ui.py", "dismissal reasons"),
    305: ("test_commit_signatures.py", "in words, with the signer shown"),
    306: ("test_vigil_mode.py", "loudly"),
    307: ("test_security_tab.py", "counts and states"),
    308: ("test_security_overview.py", "counts only, no code content"),
    309: ("test_audit_log_ui.py", "chain verification status"),
    310: ("test_security_advisories.py", "draft an advisory in private"),
    311: ("test_adversarial_battery.py", "reports its misses honestly"),
}


def _rows():
    rows = []
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if re.match(r"^\| C-\d+ \|", line):
            rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


def _part_xv_rows():
    out = {}
    for row in _rows():
        m = re.search(r"\(S-(\d+)\)", row[1])
        if m and 289 <= int(m.group(1)) <= 311:
            out[int(m.group(1))] = row
    return out


class PinsTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def test_pins_schema_128_taxonomy_135(self):
        self.assertEqual(schema_version(self.conn), 128)
        self.assertEqual(db.MIGRATIONS[-1][0], 128)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    def test_part_xv_events_stand(self):
        self.assertIn("repo.push_protection.bypass",
                      taxonomy.REPO_EVENTS)
        self.assertIn("repo.code_scanning.upload",
                      taxonomy.REPO_EVENTS)

    def test_part_xv_tables_stand(self):
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("push_scans", "push_scan_updates",
                      "secret_alerts", "secret_alert_events",
                      "custom_patterns", "secret_validity_checks",
                      "repo_dependencies", "dependency_alerts",
                      "code_scanning_uploads", "code_scanning_alerts",
                      "signing_keys", "commit_verifications",
                      "vigil_settings", "security_advisories"):
            self.assertIn(table, tables, msg=table)


class ClaimsRegisterTests(unittest.TestCase):
    def test_register_covers_every_part_xv_slice(self):
        rows = _part_xv_rows()
        self.assertEqual(sorted(rows), list(range(289, 312)))

    def test_part_xv_ids_run_c13_to_c35_in_slice_order(self):
        rows = _part_xv_rows()
        for n, row in rows.items():
            self.assertEqual(row[0], f"C-{13 + n - 289:02d}",
                             msg=f"S-{n}")

    def test_every_part_xv_claim_is_proven(self):
        for n, row in _part_xv_rows().items():
            self.assertTrue(row[2].startswith("PROVEN"),
                            msg=f"S-{n}: {row[2]!r}")

    def test_part_xv_evidence_is_the_slices_own_battery(self):
        for n, (battery, _anchor) in PART_XV_CLAIMS.items():
            row = _part_xv_rows()[n]
            self.assertIn(f"tests/{battery}", row[3], msg=f"S-{n}")
            path = ROOT / "tests" / battery
            self.assertTrue(path.is_file(), msg=battery)
            head = path.read_text(encoding="utf-8")[:600]
            self.assertIn(f"S-{n}", head, msg=battery)

    def test_register_carries_every_part_xv_anchor(self):
        text = REGISTER.read_text(encoding="utf-8")
        for n, (_battery, anchor) in PART_XV_CLAIMS.items():
            self.assertIn(anchor, text, msg=f"S-{n}: {anchor}")

    def test_part_i_rows_still_stand_untouched(self):
        rows = _rows()
        self.assertEqual(len(rows), 12 + 23)
        ids = [r[0] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[:12],
                         [f"C-{i:02d}" for i in range(1, 13)])


def _sarif_doc():
    return {
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "GateTool", "rules": [
                {"id": "G-1", "shortDescription": {"text": "g"}}]}},
            "results": [{
                "ruleId": "G-1", "level": "error",
                "message": {"text": "a finding"},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": "src/a.py"},
                    "region": {"startLine": 7}}}]},
            ],
        }],
    }


class ScanningTests(unittest.TestCase):
    def test_pattern_layer_catches_shaped_token(self):
        findings = scan_text(f"token = \"{TOKEN}\"\n")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].detector_id,
                         "github_pat_classic")
        self.assertEqual(findings[0].line, 1)
        self.assertTrue(list_detectors())

    def test_findings_never_carry_the_secret(self):
        for surface in (scan_text(f"{TOKEN}\n"),
                        scan_generic(f"api_key = \"{GENERIC}\"\n")):
            self.assertTrue(surface)
            for finding in surface:
                self.assertNotIn(TOKEN, str(finding.to_dict()))
                self.assertNotIn(GENERIC, str(finding.to_dict()))
                self.assertEqual(len(finding.fingerprint), 64)

    def test_generic_corpus_matches_published_rates(self):
        report = evaluate_corpus()
        self.assertEqual(report.total, PUBLISHED_CORPUS_SIZE)
        self.assertEqual(report.false_positive_rate,
                         PUBLISHED_FALSE_POSITIVE_RATE)
        self.assertEqual(report.precision, PUBLISHED_PRECISION)
        self.assertEqual(report.recall, PUBLISHED_RECALL)

    def test_combined_seam_judges_a_blob_once(self):
        findings, p_ok, g_ok = scan_blob_text(f"k = \"{TOKEN}\"\n")
        self.assertTrue(p_ok)
        self.assertTrue(g_ok)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].source, "pattern")
        findings, _p, _g = scan_blob_text(
            f"api_key = \"{GENERIC}\"\n")
        self.assertTrue(any(f.source == "generic" for f in findings))

    def test_counted_push_walk(self):
        blobs = ["clean prose, nothing to see\n",
                 f"token = \"{TOKEN}\"\n",
                 f"api_key = \"{GENERIC}\"\n"]
        counts = [len(scan_blob_text(b)[0]) for b in blobs]
        self.assertEqual(counts, [0, 1, 1])
        self.assertEqual(sum(counts), 2)

    def test_custom_pattern_judges_and_redacts(self):
        pat = SimpleNamespace(id=1, name="Acme", scope="instance",
                              regex=r"ACME-SECRET-\d+")
        findings = scan_text_custom("x ACME-SECRET-1234 y\n", [pat])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].pattern_id, 1)
        self.assertNotIn("ACME-SECRET-1234", findings[0].redacted)

    def test_validity_defaults_to_unknown(self):
        verdict = decide_validity("github_pat_classic", secret=TOKEN)
        self.assertEqual(verdict.validity, "unknown")
        self.assertEqual(verdict.words, "unknown")


class DependencyAndCodeScanningTests(unittest.TestCase):
    def test_manifest_parses_into_dependencies(self):
        parsed = parse_manifest(
            "requirements.txt", "requests==2.31.0\nflask>=3\n")
        names = {d.name for d in parsed.dependencies}
        self.assertEqual(names, {"requests", "flask"})

    def test_advisory_snapshot_is_dated_and_shows_age(self):
        store = AdvisoryStore.bundled()
        info = store.snapshot_info()
        self.assertTrue(store.all_advisories())
        self.assertTrue(info.age_words)
        self.assertIn(str(info.snapshot_date.year), str(info.snapshot_date))

    def test_sarif_judged_whole(self):
        self.assertEqual(sarif_problems(_sarif_doc()), ())
        self.assertTrue(sarif_problems({"version": "1.0.0"}))
        self.assertTrue(sarif_problems([1, 2]))

    def test_same_finding_across_runs_is_one_alert(self):
        first = extract_findings(_sarif_doc())
        second = extract_findings(_sarif_doc())
        self.assertEqual(len(first), 1)
        self.assertEqual(fingerprint_finding(first[0][0]),
                         fingerprint_finding(second[0][0]))
        out = compute_transitions({"a", "b"}, {"b", "c"})
        self.assertEqual(out, {"appeared": ["c"],
                               "still_open": ["b"], "fixed": ["a"]})


class SignatureAndAdversarialTests(unittest.TestCase):
    def test_unsigned_commit_extracts_as_unsigned(self):
        raw = (b"tree " + b"0" * 40 + b"\n"
               b"author Volmarr <v@example.org> 1700000000 +0000\n"
               b"committer Volmarr <v@example.org> 1700000000 +0000\n"
               b"\nan unsigned commit\n")
        found = extract_signature(raw)
        self.assertEqual(found.kind, "")

    def test_vigil_holds_foreign_key_down_never_lifts(self):
        self.assertEqual(
            decide_vigil_display("verified", "mallory", "fp-x",
                                 "volmarr", True, ("fp-own",)),
            ("unverified", True, False))
        self.assertEqual(
            decide_vigil_display("verified", "volmarr", "fp-own",
                                 "volmarr", True, ("fp-own",)),
            ("verified", True, True))
        self.assertEqual(
            decide_vigil_display("unverified", "mallory", "fp-x",
                                 "volmarr", True, ("fp-own",)),
            ("unverified", True, False))
        self.assertEqual(
            decide_vigil_display("verified", "mallory", "fp-x",
                                 "volmarr", False, ()),
            ("verified", False, False))

    def test_adversarial_battery_reports_honestly(self):
        report = run_full_battery()
        self.assertEqual(len(report.results), 54)
        self.assertEqual(sum(report.counts().values()), 54)
        gaps = report.honest_gaps()
        self.assertEqual(len(gaps), 16)
        for family in ("scanner_evasion", "sarif_fuzzing",
                       "signature_spoofing"):
            self.assertTrue(report.family_results(family), family)


if __name__ == "__main__":
    unittest.main()
