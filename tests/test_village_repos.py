"""S-365 battery — village repositories (hall-owned repos, mapped roles)."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import OrganizationStore
from samverk.village_repos import VillageRepoError, VillageRepoService, render_mapping_preview

ON = {"seam.samtal.enabled": True}
PW = "a long enough passphrase"

class VillageRepoTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "s.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.orgs = OrganizationStore(self.conn, self.accounts, audit=self.audit, time_fn=lambda: 5000)
        self.members = OrgMembershipStore(self.conn, self.accounts, audit=self.audit, time_fn=lambda: 5000)
        self.owner = self.accounts.register("hallowner", PW)
        self.member = self.accounts.register("hallmember", PW)
        self.outsider = self.accounts.register("outsider1", PW)
        self.org = self.orgs.create_organization(self.owner.id, "longhouse")
        self.members.add_member(self.owner.id, self.org.id, self.member.id)
        with self.conn:
            self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES ('longhouse','longhouse','anvil','anvil',?,5000,'','private')",
                (self.owner.id,))
        self.svc = VillageRepoService(self.conn, self.accounts, settings=ON, audit=self.audit, time_fn=lambda: 5000)
    def tearDown(self):
        self.conn.close(); self._td.cleanup()
    def _reason(self, fn, *a, **k):
        with self.assertRaises(VillageRepoError) as ctx: fn(*a, **k)
        return ctx.exception.reason
    def test_preview_shows_exact_effect_and_token(self):
        p = self.svc.preview_mapping(self.owner, "longhouse", "anvil", {"member": "write", "owner": "admin"})
        text = p.text()
        self.assertIn("Hall members get the write role", text)
        self.assertIn("Hall owners get the admin role", text)
        self.assertIn(p.token, render_mapping_preview(p))
    def test_save_without_preview_refused(self):
        self.assertEqual(self._reason(self.svc.save_mapping, self.owner, "longhouse", "anvil", {"member": "write"}, "bogus-token"), "mapping_not_previewed")
    def test_saved_mapping_resolves_through_s190(self):
        p = self.svc.preview_mapping(self.owner, "longhouse", "anvil", {"member": "write", "owner": "admin"})
        self.svc.save_mapping(self.owner, "longhouse", "anvil", {"member": "write", "owner": "admin"}, p.token)
        self.assertEqual(self.svc.role_for(self.member, "longhouse", "anvil"), "write")
        self.assertIsNone(self.svc.role_for(self.outsider, "longhouse", "anvil"))
        self.assertEqual(self.svc.saved_mapping("longhouse", "anvil"), {"member": "write", "owner": "admin"})
    def test_none_role_grants_nothing(self):
        p = self.svc.preview_mapping(self.owner, "longhouse", "anvil", {"member": "none", "owner": "maintain"})
        self.svc.save_mapping(self.owner, "longhouse", "anvil", {"member": "none", "owner": "maintain"}, p.token)
        self.assertIsNone(self.svc.role_for(self.member, "longhouse", "anvil"))
    def test_non_owner_cannot_save(self):
        self.assertEqual(self._reason(self.svc.preview_mapping, self.member, "longhouse", "anvil", {"member": "write"}), "not_hall_owner")
    def test_unknown_roles_refused(self):
        self.assertEqual(self._reason(self.svc.preview_mapping, self.owner, "longhouse", "anvil", {"elder": "write"}), "unknown_hall_role")
        self.assertEqual(self._reason(self.svc.preview_mapping, self.owner, "longhouse", "anvil", {"member": "superuser"}), "unknown_repo_role")
    def test_seam_disabled_refused(self):
        off = VillageRepoService(self.conn, self.accounts, settings={}, audit=self.audit, time_fn=lambda: 5000)
        self.assertEqual(self._reason(off.preview_mapping, self.owner, "longhouse", "anvil", {"member": "write"}), "seam_disabled")
    def test_new_member_synced_into_mapped_role(self):
        p = self.svc.preview_mapping(self.owner, "longhouse", "anvil", {"member": "read"})
        self.svc.save_mapping(self.owner, "longhouse", "anvil", {"member": "read"}, p.token)
        late = self.accounts.register("latejoiner", PW)
        self.members.add_member(self.owner.id, self.org.id, late.id)
        self.svc.sync_hall(self.owner, "longhouse")
        self.assertEqual(self.svc.role_for(late, "longhouse", "anvil"), "read")
    def test_foreign_repo_refused(self):
        self.assertEqual(self._reason(self.svc.preview_mapping, self.owner, "longhouse", "nosuchrepo", {"member": "read"}), "no_such_repo")

if __name__ == "__main__":
    unittest.main()
