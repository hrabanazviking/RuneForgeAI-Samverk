"""S-185 acceptance battery: organizations.

Acceptance (roadmap S-185): Organizations — create,
profile (name, bio, avatar with alt text, website),
settings home where every control is findable.

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
from samverk.organizations import (
    OrganizationError, OrganizationStore, render_org_page,
    render_settings_home, settings_areas, validate_website)
from samverk.uploads import UploadRejected

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
ALT = "A black longship under a red sail"


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class OrganizationTests(unittest.TestCase):
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
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.admin = self.accounts.register("sitemod", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.store = OrganizationStore(self.conn, self.accounts, self.audit, time_fn=self.clock)

    def _audit_count(self, action):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action = ?", (action,)).fetchone()["c"]

    # creation
    def test_create_happy(self):
        org = self.store.create_organization(self.creator.id, "Longship-Works", display_name="Longship Works", bio="We build things.", website="https://example.org/crew")
        self.assertEqual(org.name, "Longship-Works")
        self.assertEqual(org.name_lower, "longship-works")
        self.assertEqual(org.display_name, "Longship Works")
        self.assertEqual(org.bio, "We build things.")
        self.assertEqual(org.website, "https://example.org/crew")
        self.assertEqual(org.created_by, self.creator.id)
        self.assertIsNone(org.avatar_sha256)

    def test_create_audits_once(self):
        self.store.create_organization(self.creator.id, "crew")
        self.assertEqual(self._audit_count("auth.organization.create"), 1)

    def test_create_case_insensitive_unique(self):
        self.store.create_organization(self.creator.id, "Crew")
        with self.assertRaises(OrganizationError) as ctx:
            self.store.create_organization(self.other.id, "CREW")
        self.assertEqual(ctx.exception.reason, "org_taken")

    def test_create_refuses_user_name(self):
        with self.assertRaises(OrganizationError) as ctx:
            self.store.create_organization(self.creator.id, "YRSA")
        self.assertEqual(ctx.exception.reason, "org_name_is_user")

    def test_create_refuses_reserved(self):
        with self.assertRaises(OrganizationError) as ctx:
            self.store.create_organization(self.creator.id, "admin")
        self.assertEqual(ctx.exception.reason, "org_reserved")

    def test_create_refuses_invalid_name(self):
        for bad in ("bad name", "a/b", "..", "x" * 40):
            with self.assertRaises(OrganizationError) as ctx:
                self.store.create_organization(self.creator.id, bad)
            self.assertEqual(ctx.exception.reason, "org_invalid", bad)

    def test_create_refuses_unknown_actor(self):
        with self.assertRaises(OrganizationError) as ctx:
            self.store.create_organization(999999, "crew")
        self.assertEqual(ctx.exception.reason, "no_such_user")

    def test_create_refusal_writes_nothing(self):
        with self.assertRaises(OrganizationError):
            self.store.create_organization(self.creator.id, "admin")
        self.assertEqual(self.store.list_organizations(), [])
        self.assertEqual(self._audit_count("auth.organization.create"), 0)

    # lookups
    def test_get_by_name_case_insensitive(self):
        made = self.store.create_organization(self.creator.id, "Crew")
        self.assertEqual(self.store.get_by_name("cReW").id, made.id)
        self.assertEqual(self.store.get_by_id(made.id).name, "Crew")
        self.assertIsNone(self.store.get_by_name("nope"))
        self.assertIsNone(self.store.get_by_name(None))

    def test_list_ordered(self):
        self.store.create_organization(self.creator.id, "beta")
        self.store.create_organization(self.creator.id, "Alpha")
        names = [o.name for o in self.store.list_organizations()]
        self.assertEqual(names, ["Alpha", "beta"])

    # profile updates
    def test_update_profile_by_steward(self):
        org = self.store.create_organization(self.creator.id, "crew")
        self.clock.now += 60
        updated = self.store.update_profile(self.creator.id, org.id, display_name="The Crew", bio="Line one\nLine two", website="http://crew.example")
        self.assertEqual(updated.display_name, "The Crew")
        self.assertEqual(updated.bio, "Line one\nLine two")
        self.assertEqual(updated.website, "http://crew.example")
        self.assertEqual(updated.updated_at, org.updated_at + 60)
        self.assertEqual(self._audit_count("auth.organization.update"), 1)

    def test_update_profile_by_site_admin(self):
        org = self.store.create_organization(self.creator.id, "crew")
        updated = self.store.update_profile(self.admin.id, org.id, display_name="By admin", bio=None, website=None)
        self.assertEqual(updated.display_name, "By admin")

    def test_update_profile_refused_for_other_user(self):
        org = self.store.create_organization(self.creator.id, "crew")
        with self.assertRaises(OrganizationError) as ctx:
            self.store.update_profile(self.other.id, org.id, display_name="Hijack", bio=None, website=None)
        self.assertEqual(ctx.exception.reason, "not_org_steward")
        self.assertIsNone(self.store.get_by_id(org.id).display_name)

    def test_update_unknown_org(self):
        with self.assertRaises(OrganizationError) as ctx:
            self.store.update_profile(self.creator.id, 424242, display_name="X", bio=None, website=None)
        self.assertEqual(ctx.exception.reason, "org_not_found")

    def test_profile_text_caps_and_controls(self):
        with self.assertRaises(OrganizationError) as ctx:
            self.store.create_organization(self.creator.id, "crew", display_name="x" * 51)
        self.assertEqual(ctx.exception.reason, "display_name_too_long")
        with self.assertRaises(OrganizationError) as ctx:
            self.store.create_organization(self.creator.id, "crew", bio="x" * 501)
        self.assertEqual(ctx.exception.reason, "bio_too_long")
        with self.assertRaises(OrganizationError) as ctx:
            self.store.create_organization(self.creator.id, "crew", bio="bad\x01bio")
        self.assertEqual(ctx.exception.reason, "bio_invalid")

    def test_empty_fields_clear(self):
        org = self.store.create_organization(self.creator.id, "crew", display_name="Named", bio="Bio", website="https://a.example")
        cleared = self.store.update_profile(self.creator.id, org.id, display_name="", bio="  ", website="")
        self.assertIsNone(cleared.display_name)
        self.assertIsNone(cleared.bio)
        self.assertIsNone(cleared.website)
        self.assertEqual(cleared.effective_display_name(), "crew")

    # website law (pure)
    def test_website_validation(self):
        self.assertEqual(validate_website(" https://example.org/x "), "https://example.org/x")
        self.assertIsNone(validate_website(""))
        self.assertIsNone(validate_website(None))
        for bad in ("example.org", "ftp://example.org", "https://", "https://exa mple.org", "x" * 201):
            with self.assertRaises(OrganizationError) as ctx:
                validate_website(bad)
            self.assertEqual(ctx.exception.reason, "website_invalid", bad)

    # avatar
    def test_set_avatar_happy(self):
        org = self.store.create_organization(self.creator.id, "crew")
        updated = self.store.set_avatar(self.creator.id, org.id, PNG_BYTES, data_root=self.root, declared_type="image/png", alt_text=ALT)
        self.assertEqual(updated.avatar_content_type, "image/png")
        self.assertEqual(updated.avatar_alt, ALT)
        promoted = self.root / "avatars" / updated.avatar_filename
        self.assertTrue(promoted.exists())
        self.assertEqual(promoted.read_bytes(), PNG_BYTES)
        self.assertEqual(self._audit_count("auth.organization.update"), 1)

    def test_avatar_requires_alt_text(self):
        org = self.store.create_organization(self.creator.id, "crew")
        for bad in (None, "", "   "):
            with self.assertRaises(OrganizationError) as ctx:
                self.store.set_avatar(self.creator.id, org.id, PNG_BYTES, data_root=self.root, declared_type="image/png", alt_text=bad)
            self.assertEqual(ctx.exception.reason, "avatar_alt_required")
        self.assertIsNone(self.store.get_by_id(org.id).avatar_sha256)

    def test_avatar_refuses_disguised_payload(self):
        org = self.store.create_organization(self.creator.id, "crew")
        with self.assertRaises(UploadRejected):
            self.store.set_avatar(self.creator.id, org.id, b"<html>not an image</html>", data_root=self.root, declared_type="image/png", alt_text=ALT)
        self.assertIsNone(self.store.get_by_id(org.id).avatar_sha256)

    def test_avatar_refused_for_other_user(self):
        org = self.store.create_organization(self.creator.id, "crew")
        with self.assertRaises(OrganizationError) as ctx:
            self.store.set_avatar(self.other.id, org.id, PNG_BYTES, data_root=self.root, declared_type="image/png", alt_text=ALT)
        self.assertEqual(ctx.exception.reason, "not_org_steward")

    # pages
    def test_render_page_escapes_and_alt(self):
        org = self.store.create_organization(self.creator.id, "crew", display_name="Crew <b>Bold</b>", bio="We <script> sail", website="https://example.org/?a=1&b=2")
        org = self.store.set_avatar(self.creator.id, org.id, PNG_BYTES, data_root=self.root, declared_type="image/png", alt_text=ALT)
        html = render_org_page(org)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn(f'alt="{ALT}"', html)
        self.assertIn("https://example.org/?a=1&amp;b=2", html)

    def test_render_page_without_avatar_has_no_img(self):
        org = self.store.create_organization(self.creator.id, "crew")
        self.assertNotIn("<img", render_org_page(org))

    # settings home
    def test_settings_areas_complete_map(self):
        areas = settings_areas()
        keys = [a["key"] for a in areas]
        self.assertEqual(keys, ["profile", "avatar", "members", "teams", "team_permissions", "repositories", "audit_log", "billing", "danger"])
        by_key = {a["key"]: a for a in areas}
        self.assertTrue(by_key["profile"]["available"])
        self.assertTrue(by_key["avatar"]["available"])
        self.assertTrue(by_key["members"]["available"])
        self.assertTrue(by_key["repositories"]["available"])
        self.assertEqual(by_key["repositories"]["slice"], "S-196")
        self.assertEqual(by_key["members"]["slice"], "S-186")
        self.assertEqual(by_key["danger"]["slice"], "S-199")

    def test_settings_home_renders_findable(self):
        org = self.store.create_organization(self.creator.id, "crew")
        html = render_settings_home(org)
        self.assertIn("/orgs/crew/settings/profile", html)
        self.assertIn("/orgs/crew/settings/avatar", html)
        self.assertIn("/orgs/crew/settings/members", html)
        self.assertIn("Members", html)
        self.assertNotIn("Not yet built", html)
        self.assertIn("/orgs/crew/settings/danger", html)
        self.assertIn("/orgs/crew/settings/team_permissions", html)
        self.assertIn("/orgs/crew/settings/repositories", html)
        self.assertIn("/orgs/crew/settings/audit_log", html)
        self.assertIn("/orgs/crew/settings/teams", html)

    # pins
    def test_migration_69_and_taxonomy_123(self):
        self.assertEqual(schema_version(self.conn), 123)
        self.assertEqual(db.MIGRATIONS[-1][0], 123)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertIn("auth.organization.create", taxonomy.AUDIT_EVENTS)
        self.assertIn("auth.organization.update", taxonomy.AUDIT_EVENTS)
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(organizations)").fetchall()]
        for col in ("id", "name", "name_lower", "display_name", "bio", "website", "avatar_sha256", "avatar_content_type", "avatar_alt", "created_by", "created_at", "updated_at"):
            self.assertIn(col, cols)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for version, statements in db.MIGRATIONS:
                if version > 68:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)", (str(version),))
            conn.close()
            conn = db.init_db(path)
            self.assertEqual(db.schema_version(conn), 123)
            names = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'organizations'").fetchall()]
            self.assertEqual(names, ["organizations"])
            member_tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'organization_members'").fetchall()]
            self.assertEqual(member_tables, ["organization_members"])
            conn.close()


if __name__ == "__main__":
    unittest.main()
