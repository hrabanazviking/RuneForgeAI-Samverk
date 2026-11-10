"""S-253 acceptance battery: GraphQL verdict.

Acceptance (roadmap S-253): GraphQL verdict --
research file 24's study concludes: build, defer,
or refuse, with reasons; if deferred, the REST
contract records what a future GraphQL layer must
not break.

The verdict here is DEFER. The centre is the
audit: the deferral is checked against the live
instance -- the REST contract still ratifies, no
contract resource claims GraphQL, and no table,
column or audit event carries the word -- and the
battery plants a GraphQL-shaped table to prove
the audit would catch one.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.db import schema_version
from samverk.api_contract import (
    API_RESOURCES, CONTRACT_RULES, get_resource, get_rule)
from samverk.graphql_verdict import (
    CLIENTS, GOVERNANCE_CAPS, MUST_NOT_BREAK, REASONS,
    REOPEN_CONDITIONS, VERDICT, GraphQLVerdictAudit,
    GraphQLVerdictError, audit_graphql_verdict,
    decide_graphql_request, get_client, get_invariant,
    get_reason, render_graphql_verdict_page)
import samverk.graphql_verdict as verdict_module
from samverk.graphql_verdict import attempt_graphql_action

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_REASON_IDS = (
    "rest-meets-measured-needs", "one-in-house-consumer",
    "a-second-permanent-surface", "a-new-abuse-class",
    "village-scale-simplicity")
EXPECTED_CLIENT_IDS = (
    "issue-board", "pr-review-page",
    "organization-administration")
EXPECTED_INVARIANT_IDS = (
    "permission-parity-per-field",
    "private-is-missing-by-node-id",
    "rest-shapes-are-the-source-of-truth",
    "connections-keep-list-honesty",
    "errors-stay-typed-and-shared",
    "cost-governance-from-day-one",
    "mutations-share-stores-and-witness",
    "schema-from-resources-not-tables")


class GraphQLVerdictTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(
            Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(GraphQLVerdictError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 100)
        self.assertEqual(db.MIGRATIONS[-1][0], 100)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 85, "admin": 13})
        self.assertFalse(
            any("graphql" in e for e in taxonomy.AUDIT_EVENTS))

    # the verdict and its reasons
    def test_verdict_is_deferred(self):
        self.assertEqual(VERDICT, "deferred")

    def test_reason_ids_exact_and_each_reason_substantive(self):
        self.assertEqual(
            tuple(r.id for r in REASONS), EXPECTED_REASON_IDS)
        for reason in REASONS:
            self.assertTrue(reason.title.strip(), reason.id)
            self.assertGreater(len(reason.detail), 200, reason.id)
            self.assertIs(get_reason(reason.id), reason)

    def test_get_reason_unknown_refused(self):
        self.assertEqual(
            self._reason(get_reason, "build-now"), "reason_unknown")
        self.assertEqual(
            self._reason(get_reason, None), "reason_unknown")

    # research 24's three clients
    def test_client_ids_exact_and_judged(self):
        self.assertEqual(
            tuple(c.id for c in CLIENTS), EXPECTED_CLIENT_IDS)
        for client in CLIENTS:
            self.assertIs(get_client(client.id), client)
            self.assertIn("rest-suffices", client.judgement)
            self.assertTrue(client.need.strip(), client.id)
            self.assertTrue(client.rest_today.strip(), client.id)
            self.assertTrue(client.graphql_gain.strip(), client.id)
        self.assertEqual(
            self._reason(get_client, "mobile-app"), "client_unknown")

    def test_pr_review_is_the_strongest_future_case(self):
        client = get_client("pr-review-page")
        self.assertIn("strongest future case", client.graphql_gain)
        joined = " ".join(REOPEN_CONDITIONS)
        self.assertIn("PR review", joined)

    # the must-not-break invariants
    def test_invariant_ids_exact(self):
        self.assertEqual(
            tuple(i.id for i in MUST_NOT_BREAK),
            EXPECTED_INVARIANT_IDS)
        for invariant in MUST_NOT_BREAK:
            self.assertIs(
                get_invariant(invariant.id), invariant)
            self.assertGreater(
                len(invariant.statement), 150, invariant.id)
        self.assertEqual(
            self._reason(get_invariant, "anything-goes"),
            "invariant_unknown")

    def test_every_invariant_hangs_from_a_standing_rule(self):
        rule_ids = {rule.id for rule in CONTRACT_RULES}
        for invariant in MUST_NOT_BREAK:
            self.assertIn(invariant.contract_rule, rule_ids)

    def test_rest_contract_records_the_verdict(self):
        rule = get_rule("graphql-deferred")
        self.assertIn("S-253", rule.title)
        self.assertIn("deferred", rule.statement.lower())
        for token in ("S-190", "S-239", "S-240", "S-241",
                      "additive", "one-to-one", "idempotent"):
            self.assertIn(token, rule.statement)

    def test_no_graphql_resource_is_ratified(self):
        for resource in API_RESOURCES:
            self.assertNotIn("graphql", resource.id.lower())
            self.assertNotIn("graphql", resource.path.lower())
        self.assertEqual(
            self._reason_contract(), "resource_unknown")

    def _reason_contract(self):
        from samverk.api_contract import ApiContractError
        with self.assertRaises(ApiContractError) as ctx:
            get_resource("graphql")
        return ctx.exception.reason

    # governance caps and reopen conditions
    def test_governance_caps_exact(self):
        by_id = {cap.id: cap for cap in GOVERNANCE_CAPS}
        self.assertEqual(by_id["max-depth"].value, 8)
        self.assertEqual(by_id["max-cost"].value, 1000)
        self.assertEqual(
            by_id["max-response-bytes"].value, 1_000_000)
        self.assertEqual(
            by_id["max-execution-seconds"].value, 10)
        self.assertEqual(by_id["max-aliases"].value, 30)
        self.assertEqual(
            by_id["max-depth"].value,
            verdict_module.MAX_QUERY_DEPTH)

    def test_reopen_conditions_name_the_successor(self):
        self.assertEqual(len(REOPEN_CONDITIONS), 4)
        joined = " ".join(REOPEN_CONDITIONS)
        self.assertIn("S-403", joined)
        self.assertIn("S-255", joined)
        self.assertIn("second, independent consumer", joined)

    # the pure refusal
    def test_decide_graphql_request_pure(self):
        self.assertEqual(
            decide_graphql_request("query"), "graphql_deferred")
        self.assertEqual(
            decide_graphql_request("mutation"), "graphql_deferred")
        self.assertEqual(
            decide_graphql_request(""), "graphql_action_invalid")
        self.assertEqual(
            decide_graphql_request("   "), "graphql_action_invalid")
        self.assertEqual(
            decide_graphql_request(None), "graphql_action_invalid")

    def test_every_graphql_action_refused_deferred(self):
        self.assertEqual(
            self._reason(attempt_graphql_action, "query"),
            "graphql_deferred")
        self.assertEqual(
            self._reason(attempt_graphql_action, ""),
            "graphql_action_invalid")

    def test_refusal_writes_nothing(self):
        before = {
            t: self.conn.execute(
                f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            for t in ("users", "audit_log")}
        self._reason(attempt_graphql_action, "query")
        audit_graphql_verdict(self.conn)
        render_graphql_verdict_page()
        after = {
            t: self.conn.execute(
                f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            for t in ("users", "audit_log")}
        self.assertEqual(before, after)

    # the audit: deferral proven, planting caught
    def test_audit_is_deferred_cleanly(self):
        audit = audit_graphql_verdict(self.conn)
        self.assertTrue(audit.deferred_cleanly, audit)
        self.assertEqual(audit.verdict, "deferred")
        self.assertTrue(audit.rest_ratified)
        self.assertTrue(audit.invariant_rules_ok)
        self.assertEqual(audit.graphql_contract_resources, ())
        self.assertEqual(audit.offending_tables, ())
        self.assertEqual(audit.offending_columns, ())
        self.assertEqual(audit.offending_events, ())
        self.assertEqual(audit.events_scanned, 131)
        self.assertGreater(audit.tables_scanned, 50)
        self.assertGreater(audit.columns_scanned, 400)

    def test_audit_catches_a_planted_graphql_table(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE graphql_cache (id INTEGER,"
                " graphql_query TEXT)")
        audit = audit_graphql_verdict(self.conn)
        self.assertFalse(audit.deferred_cleanly)
        self.assertIn("graphql_cache", audit.offending_tables)
        self.assertIn(
            "graphql_cache.graphql_query",
            audit.offending_columns)

    # the page
    def test_page_says_deferred_plainly(self):
        page = render_graphql_verdict_page(
            audit_graphql_verdict(self.conn))
        self.assertIn("GraphQL -- deferred (S-253)", page)
        self.assertIn("deferred", page)
        self.assertIn("no GraphQL endpoint", page)
        self.assertIn("Checked, not just claimed", page)
        for reason in REASONS:
            self.assertIn(reason.title, page)
        for client in CLIENTS:
            self.assertIn(client.title, page)
        for invariant in MUST_NOT_BREAK:
            self.assertIn(invariant.title, page)
        self.assertIn("S-403", page)
        self.assertIn("docs/GRAPHQL_VERDICT.md", page)

    def test_page_without_audit_states_no_verdict(self):
        page = render_graphql_verdict_page()
        self.assertNotIn("Checked, not just claimed", page)
        self.assertNotIn("not clean", page)

    def test_page_reports_a_planted_defect_honestly(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE graphql_cache (id INTEGER)")
        page = render_graphql_verdict_page(
            audit_graphql_verdict(self.conn))
        self.assertIn("not clean", page)
        self.assertIn("graphql_cache", page)
        self.assertIn("defect against S-253", page)

    def test_page_escapes_every_value(self):
        audit = GraphQLVerdictAudit(
            verdict="deferred", rest_ratified=False,
            invariant_rules_ok=True,
            rest_resources_checked=1,
            graphql_contract_resources=("<b>graphql</b>",),
            tables_scanned=1, columns_scanned=1,
            events_scanned=1, offending_tables=(),
            offending_columns=(), offending_events=())
        page = render_graphql_verdict_page(audit)
        self.assertNotIn("<b>graphql</b>", page)
        self.assertIn("&lt;b&gt;graphql", page)

    # the docs say it too
    def test_docs_record_the_verdict_and_invariants(self):
        doc = (ROOT / "docs" / "GRAPHQL_VERDICT.md").read_text(
            encoding="utf-8")
        self.assertIn("deferred", doc.lower())
        self.assertIn("S-253", doc)
        self.assertIn("research file 24", doc)
        for invariant in MUST_NOT_BREAK:
            self.assertIn(invariant.id, doc, invariant.id)
        for reason in REASONS:
            self.assertIn(reason.id, doc, reason.id)
        contract = (ROOT / "docs" / "API_CONTRACT.md").read_text(
            encoding="utf-8")
        self.assertIn("graphql-deferred", contract)
        self.assertIn("GRAPHQL_VERDICT.md", contract)
        for invariant in MUST_NOT_BREAK:
            self.assertIn(invariant.id, contract, invariant.id)


if __name__ == "__main__":
    unittest.main()
