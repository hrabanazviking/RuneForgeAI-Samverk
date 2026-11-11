"""S-237 acceptance battery: API contract document.

Acceptance (roadmap S-237): API contract document
-- resources, verbs, and shapes written before
code (research file 23 holds the study; this slice
ratifies Samverk's own `/api/v1`).

The centre is the audit: the contract's landed
shapes are compared with the live faces' own
serialisers (S-216 search, S-231 events), its
refusal shape with both faces' error_to_dict, and
its route table is checked mechanically -- so a
contract that drifts from the code fails here.
The contracted half is pinned as promise, never
as presence: every contracted resource names a
builder inside Part XII.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.db import schema_version
from samverk.api_contract import (
    API_BASE, API_RESOURCES, CONTRACT_PATH, CONTRACT_RULES,
    CURRENT_ERROR_FIELDS, EVENT_FIELDS, FEED_ENVELOPE_FIELDS,
    PROBLEM_FIELDS, SEARCH_GROUP_FIELDS, SEARCH_RESULT_FIELDS,
    ApiContractError, audit_api_contract, get_resource,
    get_rule, render_api_contract_page, resource_ids, rule_ids)
import samverk.api_contract as contract_module

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "API_CONTRACT.md"

EXPECTED_RESOURCE_IDS = (
    "root", "repositories", "repository",
    "repository-branches", "repository-contents",
    "repository-forks", "issues", "issue",
    "issue-comments", "pulls", "pull", "pull-merge",
    "pull-reviews", "user", "organizations",
    "organization", "organization-members",
    "organization-member", "organization-teams",
    "team", "team-members", "team-member",
    "team-repositories", "team-repository",
    "organization-default-permission",
    "repository-collaborators",
    "repository-collaborator",
    "search", "events", "user-events",
    "repository-events", "event", "statuses",
    "check-runs", "repository-hooks",
    "organization-hooks")
EXPECTED_RULE_IDS = (
    "versioned-base", "permission-parity",
    "uniform-not-found", "json-utf8", "list-envelope",
    "cursor-pagination", "error-shape", "rate-limits",
    "no-back-doors", "graphql-deferred")
LANDED_IDS = (
    "root", "repositories", "repository",
    "repository-branches", "repository-contents",
    "repository-forks", "issues", "issue",
    "issue-comments", "pulls", "pull", "pull-merge",
    "pull-reviews", "user", "organizations",
    "organization", "organization-members",
    "organization-member", "organization-teams",
    "team", "team-members", "team-member",
    "team-repositories", "team-repository",
    "organization-default-permission",
    "repository-collaborators",
    "repository-collaborator",
    "search", "events", "user-events",
    "repository-events", "event", "statuses",
    "check-runs")


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 109)
        self.assertEqual(db.MIGRATIONS[-1][0], 109)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 87, "admin": 13})

    def test_base_and_contract_path(self):
        self.assertEqual(API_BASE, "/api/v1")
        self.assertEqual(CONTRACT_PATH, "/api/contract")

    # the route table as data
    def test_resource_ids_exact_and_unique(self):
        self.assertEqual(resource_ids(), EXPECTED_RESOURCE_IDS)
        self.assertEqual(
            len(set(resource_ids())), len(EXPECTED_RESOURCE_IDS))

    def test_rule_ids_exact_and_unique(self):
        self.assertEqual(rule_ids(), EXPECTED_RULE_IDS)
        self.assertEqual(len(set(rule_ids())), len(EXPECTED_RULE_IDS))

    def test_every_resource_is_well_formed(self):
        for resource in API_RESOURCES:
            self.assertTrue(
                resource.path == API_BASE
                or resource.path.startswith(API_BASE + "/"),
                resource.id)
            self.assertTrue(resource.methods, resource.id)
            for method in resource.methods:
                self.assertIn(
                    method, ("GET", "POST", "PATCH", "DELETE"))
            self.assertTrue(resource.summary.strip(), resource.id)
            self.assertGreater(len(resource.summary), 40, resource.id)
            self.assertTrue(resource.fields, resource.id)
            self.assertIn(
                resource.standing, ("landed", "contracted"),
                resource.id)

    def test_no_method_path_claimed_twice(self):
        seen = set()
        for resource in API_RESOURCES:
            for method in resource.methods:
                key = (method, resource.path)
                self.assertNotIn(key, seen, key)
                seen.add(key)

    def test_get_resource_roundtrip_and_unknown_refused(self):
        for resource in API_RESOURCES:
            self.assertIs(get_resource(resource.id), resource)
        with self.assertRaises(ApiContractError) as ctx:
            get_resource("graphql")
        self.assertEqual(ctx.exception.reason, "resource_unknown")
        with self.assertRaises(ApiContractError):
            get_resource(None)

    def test_get_rule_roundtrip_and_unknown_refused(self):
        for rule in CONTRACT_RULES:
            self.assertIs(get_rule(rule.id), rule)
        with self.assertRaises(ApiContractError) as ctx:
            get_rule("unversioned")
        self.assertEqual(ctx.exception.reason, "rule_unknown")

    # landed vs contracted honesty
    def test_landed_resources_are_exactly_the_banked_faces(self):
        landed = tuple(
            r.id for r in API_RESOURCES if r.standing == "landed")
        self.assertEqual(landed, LANDED_IDS)
        self.assertEqual(get_resource("search").slice, "S-245")
        for rid in ("events", "user-events",
                    "repository-events", "event"):
            self.assertEqual(get_resource(rid).slice, "S-231")
        for rid in ("root", "repositories", "repository",
                    "repository-branches", "repository-contents",
                    "repository-forks"):
            self.assertEqual(get_resource(rid).slice, "S-242")
        for rid in ("issues", "issue", "issue-comments",
                    "pulls", "pull", "pull-merge",
                    "pull-reviews"):
            self.assertEqual(get_resource(rid).slice, "S-243")
        for rid in ("user", "organizations",
                    "organization", "organization-members",
                    "organization-member",
                    "organization-teams", "team",
                    "team-members", "team-member",
                    "team-repositories", "team-repository",
                    "organization-default-permission",
                    "repository-collaborators",
                    "repository-collaborator"):
            self.assertEqual(get_resource(rid).slice, "S-244")

    def test_contracted_resources_name_part_xii_builders(self):
        for resource in API_RESOURCES:
            if resource.standing != "contracted":
                continue
            number = int(resource.slice[2:])
            self.assertTrue(
                238 <= number <= 256,
                (resource.id, resource.slice))

    def test_every_part_xii_family_has_a_builder_row(self):
        builders = {r.slice for r in API_RESOURCES}
        for needed in ("S-242", "S-243", "S-244", "S-246", "S-248"):
            self.assertIn(needed, builders)

    def test_landed_faces_are_read_only(self):
        # The faces landed before S-242 are read-only;
        # S-242's repositories family legitimately
        # carries the contract's writes (POST, PATCH,
        # DELETE), so the read-only pin now names the
        # original five.
        for rid in ("search", "events", "user-events",
                    "repository-events", "event"):
            self.assertEqual(get_resource(rid).methods, ("GET",))

    def test_search_and_events_shapes_are_the_documented_ones(self):
        self.assertEqual(
            get_resource("search").fields, SEARCH_RESULT_FIELDS)
        self.assertEqual(
            get_resource("event").fields, EVENT_FIELDS)
        for rid in ("events", "user-events", "repository-events"):
            self.assertEqual(
                get_resource(rid).fields, FEED_ENVELOPE_FIELDS)

    # the rules carry their slices
    def test_rules_name_their_building_slices(self):
        joined = " ".join(rule.statement for rule in CONTRACT_RULES)
        for token in ("S-190", "S-238", "S-239", "S-240",
                      "S-241", "S-254", "S-255"):
            self.assertIn(token, joined)
        self.assertIn("repo_not_found", joined)
        self.assertIn("event_not_found", joined)

    def test_error_shapes_pinned(self):
        # S-240: the current refusal shape IS the
        # one problem format.
        self.assertEqual(CURRENT_ERROR_FIELDS, PROBLEM_FIELDS)
        self.assertEqual(
            PROBLEM_FIELDS,
            ("type", "title", "status", "detail", "error_id"))

    # the audit
    def test_audit_is_ratified_against_the_live_code(self):
        audit = audit_api_contract()
        self.assertTrue(audit.ratified, audit)
        self.assertEqual(
            audit.resources_checked, len(EXPECTED_RESOURCE_IDS))
        self.assertEqual(audit.route_problems, ())
        self.assertEqual(audit.landed_shapes_checked, 20)
        self.assertEqual(audit.landed_shape_mismatches, ())
        self.assertTrue(audit.error_shape_ok)
        self.assertTrue(audit.permission_engine_present)
        expected_routes = sum(
            len(r.methods) for r in API_RESOURCES)
        self.assertEqual(audit.routes_checked, expected_routes)

    def test_audit_catches_a_drifted_documented_shape(self):
        drifted = tuple(
            (contract_module.dataclasses.replace(
                r, fields=("query", "wrong"))
             if r.id == "search" else r)
            for r in API_RESOURCES)
        with mock.patch.object(
                contract_module, "API_RESOURCES", drifted):
            # the documented search fields ride on the
            # module constant the audit reads for the
            # landed comparison via SEARCH_RESULT_FIELDS;
            # patch that too so the drift is in the data
            # the audit actually compares
            with mock.patch.object(
                    contract_module, "SEARCH_RESULT_FIELDS",
                    ("query", "wrong")):
                audit = audit_api_contract()
        self.assertFalse(audit.ratified)
        self.assertIn(
            "results_to_dict", audit.landed_shape_mismatches)

    def test_audit_catches_a_duplicate_route(self):
        doubled = API_RESOURCES + (API_RESOURCES[1],)
        with mock.patch.object(
                contract_module, "API_RESOURCES", doubled):
            audit = audit_api_contract()
        self.assertFalse(audit.ratified)
        self.assertTrue(
            any("duplicate" in p for p in audit.route_problems),
            audit.route_problems)

    # the page
    def test_page_renders_every_rule_and_resource(self):
        page = render_api_contract_page(audit_api_contract())
        for rule in CONTRACT_RULES:
            self.assertIn(rule.title, page)
        for resource in API_RESOURCES:
            self.assertIn(resource.path, page)
            self.assertIn(resource.slice, page)
        self.assertIn("Checked, not just claimed", page)

    def test_page_says_contracted_aloud(self):
        page = render_api_contract_page()
        self.assertIn("contracted", page)
        self.assertIn("not yet built", page)

    def test_page_without_audit_states_no_verdict(self):
        page = render_api_contract_page()
        self.assertNotIn("Checked, not just claimed", page)
        self.assertNotIn("no longer exact", page)

    # the docs twin says the same words
    def test_docs_carry_every_path_and_rule(self):
        text = DOC.read_text(encoding="utf-8")
        for resource in API_RESOURCES:
            self.assertIn(resource.path, text, resource.id)
        for rule in CONTRACT_RULES:
            self.assertIn(rule.id, text, rule.id)

    def test_docs_name_the_study_and_the_unbuilt_work(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("research file 23", text)
        for token in ("S-238", "S-239", "S-240", "S-241",
                      "S-245", "S-253", "S-254", "S-256"):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
