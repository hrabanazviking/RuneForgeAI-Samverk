"""S-254 acceptance battery: API versioning policy.

Acceptance (roadmap S-254): API versioning policy --
what may change within v1, how v2 would be
introduced, deprecation notices in headers.

The policy here is data with a pure judgement:
fifteen kinds of change classified allowed-in-v1 or
requires-v2, the v2 introduction road stated step
by step, and deprecation announced in three named
headers with a 180-day floor the validator enforces.
The centre is the audit: the policy is checked
against the live contract -- it still ratifies, the
served base is /api/v1, and no resource claims a
future version's base -- and the battery plants a
v2-claiming resource to prove the audit catches one.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.db import schema_version
from samverk.api_contract import get_rule
import samverk.api_versioning as versioning_module
from samverk.api_versioning import (
    ALLOWED_IN_V1, BREAKING, CHANGES, CURRENT_VERSION,
    HEADER_SPECS, MIN_DEPRECATION_NOTICE_DAYS,
    MIN_V1_OVERLAP_DAYS, V2_BASE, V2_INTRODUCTION,
    ApiVersioningError, DeprecationNotice, VersioningAudit,
    audit_api_versioning, decide_change,
    deprecation_headers, get_change, get_header_spec,
    render_api_versioning_page, validate_deprecation_notice)

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_ALLOWED_IDS = (
    "add-endpoint", "add-response-field",
    "add-optional-request-field", "add-optional-header",
    "add-refusal-for-new-case", "widen-accepted-input",
    "raise-a-limit")
EXPECTED_BREAKING_IDS = (
    "remove-endpoint", "remove-or-rename-field",
    "change-field-meaning-or-type",
    "require-previously-optional",
    "change-existing-refusal",
    "change-pagination-or-ordering", "lower-a-limit",
    "change-permission-semantics")
EXPECTED_HEADER_IDS = (
    "deprecation-date", "sunset-date", "deprecation-link")


class ApiVersioningTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(
            Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(ApiVersioningError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _notice(self, **overrides):
        values = {
            "surface": "repository",
            "deprecated_on": date(2026, 11, 10),
            "sunset_on": date(2026, 11, 10) + timedelta(
                days=MIN_DEPRECATION_NOTICE_DAYS),
            "notice_url": "/api/versioning#repository",
        }
        values.update(overrides)
        return DeprecationNotice(**values)

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 126)
        self.assertEqual(db.MIGRATIONS[-1][0], 126)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 89, "admin": 13})

    # the current version
    def test_current_version_is_v1_under_its_base(self):
        self.assertEqual(CURRENT_VERSION, "v1")
        self.assertEqual(V2_BASE, "/api/v2")
        from samverk.api_contract import API_BASE
        self.assertEqual(API_BASE, "/api/v1")

    # the classification
    def test_change_ids_exact_in_policy_order(self):
        self.assertEqual(
            tuple(c.id for c in CHANGES),
            EXPECTED_ALLOWED_IDS + EXPECTED_BREAKING_IDS)
        for change in CHANGES:
            self.assertTrue(change.title.strip(), change.id)
            self.assertGreater(len(change.detail), 150, change.id)
            self.assertIs(get_change(change.id), change)

    def test_every_allowed_kind_is_additive(self):
        allowed = tuple(
            c.id for c in CHANGES if c.verdict == ALLOWED_IN_V1)
        self.assertEqual(allowed, EXPECTED_ALLOWED_IDS)

    def test_every_breaking_kind_requires_v2(self):
        breaking = tuple(
            c.id for c in CHANGES if c.verdict == BREAKING)
        self.assertEqual(breaking, EXPECTED_BREAKING_IDS)
        for change_id in EXPECTED_BREAKING_IDS:
            self.assertEqual(decide_change(change_id), BREAKING)

    def test_decide_change_pure(self):
        self.assertEqual(
            decide_change("add-endpoint"), ALLOWED_IN_V1)
        self.assertEqual(
            decide_change("remove-endpoint"), BREAKING)
        self.assertEqual(
            decide_change("rename-everything"),
            "change_kind_invalid")
        self.assertEqual(decide_change(""), "change_kind_invalid")
        self.assertEqual(decide_change("   "), "change_kind_invalid")
        self.assertEqual(decide_change(None), "change_kind_invalid")

    def test_get_change_unknown_refused(self):
        self.assertEqual(
            self._reason(get_change, "anything-goes"),
            "change_unknown")
        self.assertEqual(
            self._reason(get_change, None), "change_unknown")

    def test_mirror_kinds_classify_oppositely(self):
        # The pairs a hurried builder most often
        # confuses: each additive kind's breaking
        # mirror is classified the other way.
        self.assertEqual(decide_change("raise-a-limit"), ALLOWED_IN_V1)
        self.assertEqual(decide_change("lower-a-limit"), BREAKING)
        self.assertEqual(
            decide_change("add-response-field"), ALLOWED_IN_V1)
        self.assertEqual(
            decide_change("remove-or-rename-field"), BREAKING)
        self.assertEqual(
            decide_change("add-optional-request-field"),
            ALLOWED_IN_V1)
        self.assertEqual(
            decide_change("require-previously-optional"), BREAKING)

    # the road to v2
    def test_v2_introduction_states_the_whole_road(self):
        self.assertEqual(len(V2_INTRODUCTION), 6)
        joined = " ".join(V2_INTRODUCTION)
        for token in ("/api/v2", "/api/v1", "365",
                      "migration guide", "Deprecation",
                      "Sunset", "180", "redirected"):
            self.assertIn(token, joined)
        self.assertIn(str(MIN_V1_OVERLAP_DAYS), joined)
        self.assertIn(str(MIN_DEPRECATION_NOTICE_DAYS), joined)

    def test_floors_are_the_stated_values(self):
        self.assertEqual(MIN_DEPRECATION_NOTICE_DAYS, 180)
        self.assertEqual(MIN_V1_OVERLAP_DAYS, 365)

    def test_rest_contract_records_the_policy(self):
        rule = get_rule("versioned-base")
        self.assertIn("S-254", rule.title + rule.statement)
        for token in ("additive", "Deprecation", "Sunset",
                      "/api/v2", "180"):
            self.assertIn(token, rule.statement)

    # deprecation headers, specified
    def test_header_spec_ids_and_names_exact(self):
        self.assertEqual(
            tuple(s.id for s in HEADER_SPECS), EXPECTED_HEADER_IDS)
        self.assertEqual(
            tuple(s.name for s in HEADER_SPECS),
            ("Deprecation", "Sunset", "Link"))
        for spec in HEADER_SPECS:
            self.assertIs(get_header_spec(spec.id), spec)
            self.assertTrue(spec.shape.strip(), spec.id)
            self.assertTrue(spec.carried_when.strip(), spec.id)
        self.assertEqual(
            self._reason(get_header_spec, "warning"),
            "header_spec_unknown")

    def test_header_specs_carry_the_standards_and_floor(self):
        by_id = {s.id: s for s in HEADER_SPECS}
        self.assertIn("9745", by_id["deprecation-date"].shape)
        self.assertIn("8594", by_id["sunset-date"].shape)
        self.assertIn("180", by_id["sunset-date"].shape)
        self.assertIn(
            'rel="deprecation"', by_id["deprecation-link"].shape)

    # deprecation notices, judged and built
    def test_a_lawful_notice_validates_clean(self):
        self.assertEqual(
            validate_deprecation_notice(self._notice()), ())

    def test_a_short_runway_is_refused_in_words(self):
        short = self._notice(
            sunset_on=date(2026, 11, 10) + timedelta(days=179))
        self.assertEqual(
            validate_deprecation_notice(short),
            ("notice_period_too_short",))

    def test_sunset_must_follow_deprecation(self):
        same_day = self._notice(sunset_on=date(2026, 11, 10))
        self.assertIn(
            "sunset_not_after_deprecation",
            validate_deprecation_notice(same_day))
        nameless = self._notice(surface=" ", notice_url="")
        problems = validate_deprecation_notice(nameless)
        self.assertIn("surface_missing", problems)
        self.assertIn("notice_url_missing", problems)
        self.assertEqual(
            validate_deprecation_notice("not a notice"),
            ("notice_invalid",))

    def test_deprecation_headers_are_exact(self):
        headers = deprecation_headers(self._notice())
        self.assertEqual(
            tuple(headers), ("Deprecation", "Sunset", "Link"))
        self.assertEqual(
            headers["Deprecation"], "Tue, 10 Nov 2026 00:00:00 GMT")
        self.assertEqual(
            headers["Link"],
            '</api/versioning#repository>; rel="deprecation"')
        sunset = headers["Sunset"]
        self.assertTrue(sunset.endswith(" GMT"), sunset)

    def test_unlawful_notice_builds_no_headers(self):
        short = self._notice(
            sunset_on=date(2026, 11, 10) + timedelta(days=30))
        self.assertEqual(
            self._reason(deprecation_headers, short),
            "deprecation_notice_invalid")

    def test_policy_writes_nothing(self):
        before = {
            t: self.conn.execute(
                f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            for t in ("users", "audit_log")}
        decide_change("add-endpoint")
        deprecation_headers(self._notice())
        audit_api_versioning()
        render_api_versioning_page()
        after = {
            t: self.conn.execute(
                f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            for t in ("users", "audit_log")}
        self.assertEqual(before, after)

    # the audit: policy proven, planting caught
    def test_audit_policy_holds(self):
        audit = audit_api_versioning()
        self.assertTrue(audit.policy_holds, audit)
        self.assertEqual(audit.current_version, "v1")
        self.assertEqual(audit.served_base, "/api/v1")
        self.assertTrue(audit.rest_ratified)
        self.assertTrue(audit.rule_ok)
        self.assertEqual(audit.future_version_resources, ())
        self.assertGreater(audit.rest_resources_checked, 30)

    def test_audit_catches_a_planted_v2_resource(self):
        from samverk.api_contract import API_RESOURCES
        planted = API_RESOURCES + (
            API_RESOURCES[1].__class__(
                id="future-repositories", path="/api/v2/repos",
                methods=("GET",), summary="A v2 arriving early.",
                fields=("id",), standing="contracted",
                slice="S-254"),)
        with mock.patch.object(
                versioning_module, "API_RESOURCES", planted):
            audit = audit_api_versioning()
        self.assertFalse(audit.policy_holds)
        self.assertIn(
            "future-repositories", audit.future_version_resources)

    # the page
    def test_page_states_the_policy_plainly(self):
        page = render_api_versioning_page(audit_api_versioning())
        self.assertIn("API versioning policy (S-254)", page)
        self.assertIn("Current version: <strong>v1</strong>", page)
        self.assertIn("Checked, not just claimed", page)
        for change in CHANGES:
            self.assertIn(change.title, page)
            self.assertIn(change.verdict, page)
        for spec in HEADER_SPECS:
            self.assertIn(spec.name, page)
        self.assertIn("docs/API_VERSIONING.md", page)

    def test_page_without_audit_states_no_verdict(self):
        page = render_api_versioning_page()
        self.assertNotIn("Checked, not just claimed", page)
        self.assertNotIn("not clean", page)

    def test_page_reports_a_failed_audit_honestly(self):
        audit = VersioningAudit(
            current_version="v1", served_base="/api/v1",
            rest_ratified=True, rule_ok=True,
            rest_resources_checked=1,
            future_version_resources=("<b>v2</b>",))
        page = render_api_versioning_page(audit)
        self.assertIn("not clean", page)
        self.assertIn("defect against S-254", page)
        self.assertNotIn("<b>v2</b>", page)
        self.assertIn("&lt;b&gt;v2", page)

    # the docs say it too
    def test_docs_record_the_policy(self):
        doc = (ROOT / "docs" / "API_VERSIONING.md").read_text(
            encoding="utf-8")
        self.assertIn("S-254", doc)
        self.assertIn("/api/v1", doc)
        self.assertIn("/api/v2", doc)
        for change in CHANGES:
            self.assertIn(change.id, doc, change.id)
        for spec in HEADER_SPECS:
            self.assertIn(spec.id, doc, spec.id)
            self.assertIn(spec.name, doc, spec.id)
        contract = (ROOT / "docs" / "API_CONTRACT.md").read_text(
            encoding="utf-8")
        self.assertIn("versioned-base", contract)
        self.assertIn("API_VERSIONING.md", contract)
        for change in CHANGES:
            self.assertIn(change.id, contract, change.id)


if __name__ == "__main__":
    unittest.main()
