"""S-197 acceptance battery: internal visibility.

Acceptance (roadmap S-197): Internal visibility —
repos visible to all org/instance members, distinct
from public and private, enforced by S-190.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.internal_visibility import (
    InternalVisibilityStore, decide_internal_read, is_internal,
    render_internal_page)
from samverk.org_repositories import OrgRepoStore
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import OrganizationStore
from samverk.permission_engine import (
    PermissionEngine, build_contributions, decide_permission)
from samverk.repositories import RepositoryStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class InternalVisibilityTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.data_root = self.root / "data"
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.creator = self.accounts.register("volmarr", "correct horse battery")
        self.yrsa = self.accounts.register("yrsa", "correct horse battery")
        self.outsider = self.accounts.register("freya", "correct horse battery")
        self.admin = self.accounts.register("sitemod", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.orgs = OrganizationStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.org = self.orgs.create_organization(self.creator.id, "crew")
        self.members = OrgMembershipStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        self.org_repos = OrgRepoStore(self.conn, self.accounts, self.data_root, self.audit, time_fn=self.clock)
        # The org opts in to internal through its S-196 policy.
        self.org_repos.set_policy(
            self.creator.id, self.org.id, who_may_create="owners",
            allowed_visibilities=("public", "internal", "private"))
        self.repo = self.org_repos.create_repository(
            self.creator.id, self.org.id, "longhouse", visibility="internal")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts, self.audit, time_fn=self.clock)
        self.engine = PermissionEngine(self.conn, self.accounts, time_fn=self.clock)
        self.store = InternalVisibilityStore(self.conn, self.accounts, self.audit, time_fn=self.clock)

    # -- the vocabulary --------------------------------
    def test_internal_is_a_visibility(self):
        self.assertEqual(self.repo.visibility, "internal")
        self.assertTrue(is_internal("internal"))
        self.assertFalse(is_internal("public"))
        self.assertFalse(is_internal("private"))

    def test_visibility_change_to_internal(self):
        other = self.repos.create_repository(
            self.creator.id, "volmarr", "boathouse", visibility="private")
        changed = self.repos.update_metadata(
            self.creator.id, "volmarr", "boathouse", visibility="internal")
        self.assertEqual(changed.visibility, "internal")
        self.assertEqual(other.visibility, "private")

    # -- the pure judge --------------------------------
    def test_pure_judge_member_and_stranger(self):
        yes = decide_internal_read(visibility="internal", is_member=True)
        self.assertTrue(yes.allowed)
        self.assertEqual(yes.reason, "member")
        no = decide_internal_read(visibility="internal", is_member=False)
        self.assertFalse(no.allowed)
        self.assertEqual(no.reason, "not_a_member")
        self.assertIn("not found", no.detail)

    def test_pure_judge_speaks_only_for_internal(self):
        for vis in ("public", "private"):
            d = decide_internal_read(visibility=vis, is_member=True)
            self.assertFalse(d.allowed)
            self.assertEqual(d.reason, "not_internal")

    def test_pure_judge_instance_scope(self):
        d = decide_internal_read(
            visibility="internal", is_member=True, scope="instance")
        self.assertTrue(d.allowed)
        self.assertIn("instance", d.detail)

    # -- enforcement through S-190 ---------------------
    def test_org_member_reads_internal(self):
        res = self.engine.resolve(self.yrsa, self.repo)
        self.assertEqual(res.role, "read")
        self.assertEqual(res.source, "internal")
        self.assertTrue(self.store.can_read(self.yrsa, self.repo))

    def test_org_owner_and_site_admin_hold_admin(self):
        self.assertEqual(self.engine.resolve(self.creator, self.repo).role, "admin")
        self.assertEqual(self.engine.resolve(self.admin, self.repo).role, "admin")

    def test_non_member_gets_no_access(self):
        res = self.engine.resolve(self.outsider, self.repo)
        self.assertIsNone(res.role)
        self.assertEqual(res.source, "none")
        self.assertIn("internal", res.detail)
        self.assertFalse(self.store.can_read(self.outsider, self.repo))

    def test_anonymous_gets_no_access(self):
        res = self.engine.resolve(None, self.repo)
        self.assertIsNone(res.role)
        self.assertFalse(self.store.can_read(None, self.repo))

    def test_internal_floor_grants_read_only(self):
        # A member reads but does not write on the floor alone.
        self.assertFalse(self.engine.can(self.yrsa, self.repo, "write"))
        self.assertTrue(self.engine.can(self.yrsa, self.repo, "read"))

    def test_internal_distinct_from_public_and_private(self):
        pub = self.org_repos.create_repository(
            self.creator.id, self.org.id, "market", visibility="public")
        priv = self.org_repos.create_repository(
            self.creator.id, self.org.id, "vault", visibility="private")
        # Public: everyone, even anonymous. Private: not even members.
        self.assertEqual(self.engine.resolve(None, pub).role, "read")
        self.assertIsNone(self.engine.resolve(self.yrsa, priv).role)
        self.assertIsNone(self.engine.resolve(None, self.repo).role)
        self.assertEqual(self.engine.resolve(self.yrsa, self.repo).role, "read")

    def test_personal_internal_readable_by_signed_in_only(self):
        mine = self.repos.create_repository(
            self.creator.id, "volmarr", "diary", visibility="internal")
        self.assertEqual(self.engine.resolve(self.outsider, mine).role, "read")
        self.assertEqual(
            self.engine.resolve(self.outsider, mine).source, "internal")
        self.assertIsNone(self.engine.resolve(None, mine).role)
        self.assertEqual(self.engine.resolve(self.creator, mine).role, "admin")

    # -- pure/engine agreement -------------------------
    def test_pure_and_engine_agree(self):
        facts = build_contributions(
            visibility="internal", internal_member=True)
        self.assertEqual(decide_permission(facts).role, "read")
        self.assertEqual(decide_permission(facts).source, "internal")
        facts = build_contributions(
            visibility="internal", internal_member=False)
        self.assertIsNone(decide_permission(facts).role)
        facts = build_contributions(
            visibility="private", internal_member=True)
        self.assertIsNone(decide_permission(facts).role)

    # -- the storefront --------------------------------
    def test_store_lists_for_members_only(self):
        self.assertEqual(
            [r.name for r in self.store.internal_repositories("crew")],
            ["longhouse"])
        self.assertEqual(
            [r.name for r in self.store.readable_internal_repositories(self.yrsa, "crew")],
            ["longhouse"])
        self.assertEqual(
            self.store.readable_internal_repositories(self.outsider, "crew"), [])
        self.assertEqual(
            self.store.readable_internal_repositories(None, "crew"), [])

    def test_page_states_the_law_and_escapes(self):
        page = render_internal_page("crew", [self.repo])
        self.assertIn("readable by every member", page)
        self.assertIn("crew/longhouse", page)
        self.assertIn("Internal", page)
        evil = render_internal_page("<script>", [])
        self.assertNotIn("<script>", evil)
        self.assertIn("No internal repositories.", evil)


if __name__ == "__main__":
    unittest.main()
