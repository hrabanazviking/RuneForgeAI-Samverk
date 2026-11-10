"""S-202 acceptance battery: billing-shaped hole.

Acceptance (roadmap S-202): Billing-shaped hole,
honestly empty — Samverk is free software on your own
machines; no seat/billing concepts exist, and the docs
say why.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.billing_hole import (
    BILLING_ACTIONS, FORBIDDEN_TERMS, LICENSE_NAME, WHY_FREE,
    BillingAudit, BillingHole, BillingStatement,
    decide_billing_request, forbidden_terms_in,
    render_billing_page)
from samverk.db import schema_version
from samverk.organizations import (
    OrganizationError, OrganizationStore, render_settings_home,
    settings_areas)
from samverk.organization_members import OrgMembershipStore

ROOT = Path(__file__).resolve().parent.parent


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class BillingHoleTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.creator = self.accounts.register("volmarr", "correct horse battery")
        self.yrsa = self.accounts.register("yrsa", "correct horse battery")
        self.bryn = self.accounts.register("brynhild", "correct horse battery")
        self.orgs = OrganizationStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.org = self.orgs.create_organization(self.creator.id, "crew")
        self.members = OrgMembershipStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        self.members.add_member(self.creator.id, self.org.id, self.bryn.id)
        self.hole = BillingHole(self.conn, self.accounts)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _counts(self):
        tables = ("users", "organizations", "organization_members",
                  "audit_log")
        return {t: self.conn.execute(
            f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            for t in tables}

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 96)
        self.assertEqual(db.MIGRATIONS[-1][0], 96)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertFalse(any("billing" in e for e in taxonomy.AUDIT_EVENTS))

    def test_no_billing_tables_exist(self):
        audit = self.hole.audit_surface()
        self.assertEqual(audit.offending_tables, ())
        tables = [r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")]
        self.assertNotIn("billing", tables)
        self.assertFalse(any("seat" in t for t in tables))

    # pure judgements
    def test_forbidden_terms_pure(self):
        self.assertEqual(forbidden_terms_in("billing_seats"), ("billing", "seat"))
        self.assertEqual(forbidden_terms_in("PLAN_TIER"), ("plan", "tier"))
        self.assertEqual(forbidden_terms_in("repositories"), ())
        self.assertEqual(forbidden_terms_in("repo_quotas"), ())
        self.assertEqual(forbidden_terms_in("quota_bytes"), ())
        self.assertEqual(forbidden_terms_in(None), ())
        self.assertEqual(forbidden_terms_in(42), ())
        self.assertNotIn("quota", FORBIDDEN_TERMS)

    def test_decide_billing_request_pure(self):
        for action in BILLING_ACTIONS:
            self.assertEqual(decide_billing_request(action), "no_billing")
        self.assertEqual(decide_billing_request("anything_at_all"), "no_billing")
        self.assertEqual(decide_billing_request(""), "billing_action_invalid")
        self.assertEqual(decide_billing_request("   "), "billing_action_invalid")
        self.assertEqual(decide_billing_request(None), "billing_action_invalid")

    # the surface audit: emptiness proven, planting caught
    def test_audit_surface_honestly_empty(self):
        audit = self.hole.audit_surface()
        self.assertTrue(audit.honestly_empty)
        self.assertEqual(audit.offending_columns, ())
        self.assertEqual(audit.offending_events, ())
        self.assertEqual(audit.events_scanned, 131)
        self.assertGreater(audit.tables_scanned, 50)
        self.assertGreater(audit.columns_scanned, 400)

    def test_audit_catches_a_planted_billing_table(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE billing_seats (org_id INTEGER,"
                " seat_count INTEGER, plan_tier TEXT)")
        audit = self.hole.audit_surface()
        self.assertFalse(audit.honestly_empty)
        self.assertIn("billing_seats", audit.offending_tables)
        self.assertIn("billing_seats.seat_count", audit.offending_columns)
        self.assertIn("billing_seats.plan_tier", audit.offending_columns)

    def test_audit_catches_a_planted_invoice_column(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE innocuous (id INTEGER, last_invoice_id TEXT)")
        audit = self.hole.audit_surface()
        self.assertFalse(audit.honestly_empty)
        self.assertEqual(audit.offending_tables, ())
        self.assertIn("innocuous.last_invoice_id", audit.offending_columns)

    # statements
    def test_org_statement_is_empty_and_counted(self):
        got = self.hole.statement_for_organization(self.org.id)
        self.assertEqual(got.scope, "organization")
        self.assertEqual(got.subject, "crew")
        self.assertEqual(got.license_name, "AGPL-3.0")
        self.assertEqual(got.license_name, LICENSE_NAME)
        self.assertEqual(got.member_count, 3)
        self.assertEqual(got.reasons, WHY_FREE)
        self.assertFalse(got.has_billing)
        self.assertFalse(got.has_seats)
        self.assertFalse(got.has_plans)
        self.assertFalse(got.has_charges)

    def test_org_statement_by_name_and_object(self):
        by_name = self.hole.statement_for_organization("CREW")
        by_obj = self.hole.statement_for_organization(self.org)
        self.assertEqual(by_name.subject, "crew")
        self.assertEqual(by_name.member_count, by_obj.member_count)

    def test_unknown_org_refused(self):
        self.assertEqual(self._reason(
            self.hole.statement_for_organization, 999999), "org_not_found")
        self.assertEqual(self._reason(
            self.hole.statement_for_organization, "nosuchorg"), "org_not_found")
        self.assertEqual(self._reason(
            self.hole.statement_for_organization, None), "org_not_found")

    def test_instance_statement_is_empty(self):
        got = self.hole.instance_statement()
        self.assertEqual(got.scope, "instance")
        self.assertIsNone(got.member_count)
        self.assertFalse(got.has_billing)
        self.assertEqual(got.license_name, "AGPL-3.0")

    # the one refusal
    def test_every_billing_action_refused_no_billing(self):
        for action in BILLING_ACTIONS:
            self.assertEqual(self._reason(
                self.hole.attempt_billing_action, action), "no_billing")

    def test_shapeless_billing_action_refused_invalid(self):
        self.assertEqual(self._reason(
            self.hole.attempt_billing_action, ""), "billing_action_invalid")
        self.assertEqual(self._reason(
            self.hole.attempt_billing_action, None), "billing_action_invalid")

    def test_refusal_writes_nothing_and_audits_nothing(self):
        before = self._counts()
        self._reason(self.hole.attempt_billing_action, "subscribe")
        self.hole.statement_for_organization(self.org.id)
        self.hole.instance_statement()
        self.hole.audit_surface()
        self.hole.organization_page(self.org.id)
        self.hole.instance_page()
        self.assertEqual(self._counts(), before)

    # the settings map: the hole where people look for it
    def test_settings_map_has_billing_built_by_s202(self):
        by_key = {a["key"]: a for a in settings_areas()}
        self.assertIn("billing", by_key)
        self.assertTrue(by_key["billing"]["available"])
        self.assertEqual(by_key["billing"]["slice"], "S-202")
        self.assertIn("no billing", by_key["billing"]["description"].lower())

    def test_settings_home_links_billing(self):
        html = render_settings_home(self.org)
        self.assertIn("/orgs/crew/settings/billing", html)
        self.assertIn("Billing", html)
        self.assertNotIn("Not yet built", html)

    # the pages
    def test_org_page_says_it_plainly(self):
        page = self.hole.organization_page(self.org.id)
        self.assertIn("Billing — crew", page)
        self.assertIn("There is no billing for crew", page)
        self.assertIn("no seats", page)
        self.assertIn("no plans", page)
        self.assertIn("no charges", page)
        self.assertIn("AGPL-3.0", page)
        self.assertIn("3 members", page)
        self.assertIn("never counted for billing", page)
        self.assertIn("Checked, not just claimed", page)
        self.assertIn("docs/BILLING.md", page)

    def test_instance_page_says_it_plainly(self):
        page = self.hole.instance_page()
        self.assertIn("There is no billing on this instance", page)
        self.assertIn("free software on your own machines", page)
        self.assertIn("Checked, not just claimed", page)

    def test_page_names_reasons(self):
        page = self.hole.organization_page(self.org.id)
        self.assertIn("People are not seats", page)
        self.assertIn("no payment rail", page)
        self.assertIn("your own machines", page)

    def test_page_reports_a_planted_defect_honestly(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE billing_seats (seat_count INTEGER)")
        page = self.hole.organization_page(self.org.id)
        self.assertIn("not empty", page)
        self.assertIn("billing_seats", page)
        self.assertIn("defect against S-202", page)

    def test_page_escapes_every_value(self):
        evil = BillingStatement(
            scope="organization",
            subject="<script>alert(1)</script>",
            subject_lower="x", license_name="AGPL-3.0",
            member_count=1, reasons=("<img src=x>",))
        page = render_billing_page(evil)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn("<img src=x>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("1 member", page)
        audit = BillingAudit(
            tables_scanned=1, columns_scanned=1, events_scanned=1,
            offending_tables=("<b>billing</b>",),
            offending_columns=(), offending_events=())
        page2 = render_billing_page(evil, audit)
        self.assertNotIn("<b>billing</b>", page2)
        self.assertIn("&lt;b&gt;billing", page2)

    # the docs say why
    def test_docs_say_why(self):
        doc = (ROOT / "docs" / "BILLING.md").read_text(encoding="utf-8")
        self.assertIn("free software", doc)
        self.assertIn("AGPL", doc)
        self.assertIn("no seats", doc.lower())
        self.assertIn("own machines", doc)
        self.assertIn("S-202", doc)


if __name__ == "__main__":
    unittest.main()
