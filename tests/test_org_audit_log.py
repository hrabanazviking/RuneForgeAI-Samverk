"""S-198 acceptance battery: org audit log.

Acceptance (roadmap S-198): Org audit log \u2014
membership, permission, and repo events for the
org, readable by owners (storage is S-007's log).

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
from samverk.db import schema_version
from samverk.org_audit_log import (
    CATEGORIES, OrgAuditLogStore, classify_event,
    event_summary, render_org_audit_page)
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import (
    OrganizationError, OrganizationStore, settings_areas)


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class OrgAuditLogTests(unittest.TestCase):
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
        self.member = self.accounts.register("yrsa", "correct horse battery")
        self.outsider = self.accounts.register("freya", "correct horse battery")
        self.admin = self.accounts.register("sitemod", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.orgs = OrganizationStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.org = self.orgs.create_organization(self.creator.id, "crew")
        self.members = OrgMembershipStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.members.add_member(self.creator.id, self.org.id, self.member.id)
        self.log = OrgAuditLogStore(self.conn, self.accounts, self.audit, time_fn=self.clock)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _append(self, action, target_kind, target_id, detail=None, actor=None, outcome="success"):
        return self.audit.append(
            actor_kind="user",
            actor_id=(actor.id if actor is not None else self.creator.id),
            action=action, target_kind=target_kind,
            target_id=target_id, outcome=outcome, detail=detail)

    def _audit_rows(self):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]

    def _crew(self, **kwargs):
        return self.log.list_events(self.creator.id, self.org.id, **kwargs)

    # belonging: org-targeted rows
    def test_org_create_and_membership_events_appear(self):
        entries = self._crew()
        actions = [e.action for e in entries]
        self.assertIn("auth.organization.create", actions)
        create = [e for e in entries if e.action == "auth.organization.create"][0]
        self.assertEqual(create.category, "organization")
        self.assertEqual(create.target_id, "crew")
        adds = [e for e in entries if e.detail.get("fields") == "members"]
        self.assertTrue(adds)
        self.assertTrue(all(e.category == "membership" for e in adds))
        self.assertIn("yrsa", adds[0].summary)

    def test_seq_order_ascending(self):
        self._append("repo.create", "repo", "crew/anvil")
        self._append("repo.push", "repo", "crew/anvil")
        seqs = [e.seq for e in self._crew()]
        self.assertEqual(seqs, sorted(seqs))

    def test_other_org_events_do_not_appear(self):
        other = self.orgs.create_organization(self.creator.id, "fleet")
        crew_targets = {e.target_id for e in self._crew()}
        self.assertNotIn("fleet", crew_targets)
        fleet_entries = self.log.list_events(self.creator.id, other.id)
        self.assertEqual([e.target_id for e in fleet_entries], ["fleet"])
        self.assertEqual(fleet_entries[0].action, "auth.organization.create")

    # belonging: repo rows and the prefix trap
    def test_org_repo_events_appear(self):
        self._append("repo.create", "repo", "crew/anvil")
        self._append("repo.push", "repo", "Crew/Anvil")
        entries = self._crew()
        repo_entries = [e for e in entries if e.target_kind == "repo"]
        self.assertEqual(len(repo_entries), 2)
        self.assertTrue(all(e.category == "repository" for e in repo_entries))
        self.assertIn("crew/anvil", repo_entries[0].summary)

    def test_personal_and_other_org_repo_events_do_not(self):
        self._append("repo.create", "repo", "yrsa/own")
        self._append("repo.create", "repo", "fleet/thing")
        self._append("repo.create", "repo", "crew/anvil")
        targets = [e.target_id for e in self._crew() if e.target_kind == "repo"]
        self.assertEqual(targets, ["crew/anvil"])

    def test_prefix_trap_crew_vs_crew2(self):
        self.orgs.create_organization(self.member.id, "crew2")
        self._append("repo.create", "repo", "crew2/repo")
        self._append("repo.push", "repo", "crew2/repo")
        self._append("repo.create", "repo", "crew/repo")
        targets = [e.target_id for e in self._crew()]
        self.assertIn("crew/repo", targets)
        self.assertNotIn("crew2/repo", targets)
        self.assertNotIn("crew2", targets)

    # classification, pure and through the store
    def test_classify_event_pure(self):
        cases = [
            (("auth.organization.create", "organization", {"org": "crew"}), "organization"),
            (("auth.organization.update", "organization", {"fields": "text"}), "organization"),
            (("auth.organization.update", "organization", {"fields": "avatar"}), "organization"),
            (("auth.organization.update", "organization", {"fields": "members", "action": "add"}), "membership"),
            (("auth.organization.update", "organization", {"fields": "invitations", "action": "invite"}), "membership"),
            (("auth.organization.update", "organization", {"fields": "teams", "action": "create"}), "membership"),
            (("auth.organization.update", "organization", {"fields": "teams", "action": "set_permission"}), "permission"),
            (("auth.organization.update", "organization", {"fields": "team_permissions"}), "permission"),
            (("auth.organization.update", "organization", {"fields": "default_permission", "action": "set_default"}), "permission"),
            (("auth.organization.update", "organization", {"fields": "default_permissions"}), "permission"),
            (("auth.organization.update", "organization", {"fields": "repositories", "action": "set_policy"}), "permission"),
            (("repo.protection.change", "repo", None), "permission"),
            (("repo.protection.bypass", "repo", {}), "permission"),
            (("repo.collaborator.add", "repo", None), "permission"),
            (("repo.create", "repo", None), "repository"),
            (("repo.push", "repo", {}), "repository"),
            (("auth.organization.update", "organization", None), "organization"),
            (("auth.organization.update", "organization", {}), "organization"),
        ]
        for (action, kind, detail), expected in cases:
            self.assertEqual(classify_event(action, kind, detail), expected, (action, kind, detail))
        self.assertEqual(set(CATEGORIES), {"membership", "permission", "repository", "organization"})

    def test_event_summary_plain_words(self):
        self.assertIn("crew", event_summary("auth.organization.create", "organization", "crew", {"org": "crew"}))
        self.assertIn("yrsa", event_summary("auth.organization.update", "organization", "crew", {"fields": "members", "action": "add", "target": "yrsa"}))
        self.assertIn("crew/anvil", event_summary("repo.protection.change", "repo", "crew/anvil", None))
        self.assertIn("crew/anvil", event_summary("repo.create", "repo", "crew/anvil", None))

    def test_categories_via_store_and_filter(self):
        self._append("repo.protection.change", "repo", "crew/anvil", detail={"branch": "main"})
        self._append("repo.create", "repo", "crew/anvil")
        everything = self._crew()
        by_cat = {}
        for e in everything:
            by_cat.setdefault(e.category, []).append(e)
        self.assertIn("permission", by_cat)
        self.assertIn("repository", by_cat)
        self.assertIn("membership", by_cat)
        self.assertIn("organization", by_cat)
        only_perm = self._crew(category="permission")
        self.assertTrue(only_perm)
        self.assertTrue(all(e.category == "permission" for e in only_perm))
        self.assertEqual([e.action for e in only_perm], ["repo.protection.change"])
        only_member = self._crew(category="membership")
        self.assertTrue(all(e.category == "membership" for e in only_member))
        prot = [e for e in everything if e.action == "repo.protection.change"][0]
        self.assertEqual(prot.detail, {"branch": "main"})

    def test_invalid_category_refused(self):
        self.assertEqual(self._reason(self.log.list_events, self.creator.id, self.org.id, "bogus"), "category_invalid")
        self.assertEqual(self._reason(self.log.list_events, self.creator.id, self.org.id, "Members"), "category_invalid")

    # the guard: owners (and the site steward) only
    def test_plain_member_refused(self):
        self.assertEqual(self._reason(self.log.list_events, self.member.id, self.org.id), "not_org_owner")

    def test_non_member_refused(self):
        self.assertEqual(self._reason(self.log.list_events, self.outsider.id, self.org.id), "not_org_owner")

    def test_site_admin_may_read(self):
        entries = self.log.list_events(self.admin.id, self.org.id)
        self.assertTrue(entries)
        self.assertEqual(entries[0].action, "auth.organization.create")

    def test_unknown_org_refused(self):
        self.assertEqual(self._reason(self.log.list_events, self.creator.id, 424242), "org_not_found")

    def test_unknown_viewer_refused(self):
        self.assertEqual(self._reason(self.log.list_events, 999999, self.org.id), "no_such_user")

    # purity and resolution
    def test_reading_is_pure_read(self):
        before = self._audit_rows()
        first = self._crew()
        second = self._crew(category="membership")
        render_org_audit_page(self.org, first)
        self.assertEqual(self._audit_rows(), before)
        self.assertEqual([e.seq for e in first], [e.seq for e in self._crew()])
        self.assertTrue(second)

    def test_actor_username_resolved(self):
        entries = self._crew()
        create = [e for e in entries if e.action == "auth.organization.create"][0]
        self.assertEqual(create.actor_id, self.creator.id)
        self.assertEqual(create.actor_username, "volmarr")
        self.audit.append(actor_kind="system", action="repo.push", target_kind="repo", target_id="crew/anvil", outcome="success")
        anon = [e for e in self._crew() if e.action == "repo.push"][0]
        self.assertIsNone(anon.actor_id)
        self.assertIsNone(anon.actor_username)

    # the page
    def test_page_escapes_and_states_counts(self):
        self._append("repo.create", "repo", "crew/<script>alert</script>")
        entries = self._crew()
        html = render_org_audit_page(self.org, entries)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("cannot appear here", html)
        self.assertIn("membership", html)
        self.assertIn("permission", html)
        self.assertIn("repository", html)
        self.assertIn("organization", html)
        self.assertIn("repo.create", html)
        total = len(entries)
        self.assertIn(f"{total} events", html)

    def test_page_empty_log_states_zero(self):
        html = render_org_audit_page(self.org, [])
        self.assertIn("0 events", html)
        self.assertIn("cannot appear here", html)

    # settings map + pins
    def test_settings_area_audit_log_available(self):
        by_key = {a["key"]: a for a in settings_areas()}
        self.assertTrue(by_key["audit_log"]["available"])
        self.assertEqual(by_key["audit_log"]["slice"], "S-198")
        self.assertTrue(by_key["danger"]["available"])

    def test_pins_schema_80_taxonomy_123(self):
        self.assertEqual(schema_version(self.conn), 92)
        self.assertEqual(db.MIGRATIONS[-1][0], 92)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 127)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 31)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 83)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)


if __name__ == "__main__":
    unittest.main()
