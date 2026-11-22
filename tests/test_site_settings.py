"""S-352 acceptance battery: site settings.

Acceptance (roadmap S-352): instance name and description,
registration mode (open / invite / closed), default repo
visibility, upload and repo size limits -- taking effect,
not just stored.

Counted with: python3 -m unittest tests.test_site_settings
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore, RegistrationError
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.repo_quotas import QuotaService
from samverk.repositories import RepositoryStore
from samverk.site_settings import (SiteSettings, SiteSettingsError,
    SiteSettingsService, decide_registration, decide_upload_size,
    parse_site_settings, render_site_settings_page)
from samverk.uploads import UploadRejected
PW = "correct horse battery"

class SiteSettingsTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.audit = AuditLog(self.conn)
        plain = AccountStore(self.conn)
        self.admin = plain.register("volmarr", PW)
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.member = plain.register("yrsa", PW)
        self.site = SiteSettingsService(self.conn, plain, audit=self.audit)
        self.accounts = AccountStore(self.conn, audit=self.audit, site_settings=self.site)
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts, site_settings=self.site)
    def test_pins_unchanged(self):
        self.assertEqual(schema_version(self.conn), 139)
        self.assertEqual(db.MIGRATIONS[-1][0], 139)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)
    def test_defaults(self):
        s = self.site.get_settings()
        self.assertEqual(s, SiteSettings())
        self.assertEqual(s.instance_name, "Samverk")
        self.assertEqual(s.registration_mode, "open")
        self.assertEqual(s.default_repo_visibility, "private")
        self.assertEqual(s.upload_max_bytes, 10 * 1024 * 1024)
        self.assertIsNone(s.repo_size_limit_bytes)
    def test_pure_registration_decisions(self):
        self.assertTrue(decide_registration("open", False).allowed)
        self.assertFalse(decide_registration("closed", True).allowed)
        self.assertEqual(decide_registration("closed", False).reason, "registration_closed")
        self.assertFalse(decide_registration("invite", False).allowed)
        self.assertTrue(decide_registration("invite", True).allowed)
        self.assertFalse(decide_registration("bogus", True).allowed)
    def test_pure_upload_decision_plain_words(self):
        self.assertTrue(decide_upload_size(10, 10).allowed)
        over = decide_upload_size(11, 10)
        self.assertFalse(over.allowed); self.assertIn("11", over.message); self.assertIn("10", over.message)
    def test_parse_refuses_corrupt_stored_values(self):
        with self.assertRaises(SiteSettingsError):
            parse_site_settings({"site.registration_mode": "wide-open"})
        with self.assertRaises(SiteSettingsError):
            parse_site_settings({"site.upload_max_bytes": "lots"})
    def test_admin_update_round_trip_and_audit(self):
        s = self.site.update_settings(self.admin.id, instance_name="Wyrd Forge", instance_description="A village forge.", registration_mode="invite", default_repo_visibility="public", upload_max_bytes=2048, repo_size_limit_bytes=999999)
        self.assertEqual(s.instance_name, "Wyrd Forge")
        self.assertEqual(self.site.get_settings(), s)
        rows = self.conn.execute("SELECT action, detail FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
        self.assertEqual(rows["action"], "admin.settings.change")
        self.assertIn("site.registration_mode", rows["detail"])
    def test_non_admin_cannot_change_or_mint(self):
        with self.assertRaises(SiteSettingsError) as c:
            self.site.update_settings(self.member.id, instance_name="Nope")
        self.assertEqual(c.exception.reason, "permission_denied")
        with self.assertRaises(SiteSettingsError):
            self.site.create_invite_code(self.member.id)
        with self.assertRaises(SiteSettingsError) as c2:
            self.site.update_settings(99999, instance_name="Nope")
        self.assertEqual(c2.exception.reason, "no_such_user")
    def test_invalid_values_refused_and_nothing_stored(self):
        for kwargs in ({"registration_mode": "wide"}, {"default_repo_visibility": "secret"}, {"upload_max_bytes": 0}, {"upload_max_bytes": True}, {"instance_name": "  "}, {"instance_name": "x" * 81}, {"repo_size_limit_bytes": -1}):
            with self.assertRaises(SiteSettingsError, msg=str(kwargs)):
                self.site.update_settings(self.admin.id, **kwargs)
        self.assertEqual(self.site.get_settings(), SiteSettings())
    def test_open_registration_works_when_wired(self):
        user = self.accounts.register("sigrun", PW)
        self.assertEqual(user.username, "sigrun")
    def test_closed_mode_gates_real_signup(self):
        self.site.update_settings(self.admin.id, registration_mode="closed")
        with self.assertRaises(RegistrationError) as c:
            self.accounts.register("sigrun", PW)
        self.assertEqual(c.exception.reason, "registration_closed")
        self.assertIn("closed", str(c.exception))
        self.assertIsNone(self.accounts.get_by_username("sigrun"))
    def test_invite_mode_requires_and_consumes_code(self):
        self.site.update_settings(self.admin.id, registration_mode="invite")
        with self.assertRaises(RegistrationError) as c:
            self.accounts.register("sigrun", PW)
        self.assertEqual(c.exception.reason, "registration_invite_required")
        with self.assertRaises(RegistrationError):
            self.accounts.register("sigrun", PW, invite_code="deadbeefdeadbeef")
        code = self.site.create_invite_code(self.admin.id)
        user = self.accounts.register("sigrun", PW, invite_code=code)
        self.assertEqual(user.username, "sigrun")
        with self.assertRaises(RegistrationError):  # single use
            self.accounts.register("freya", PW, invite_code=code)
    def test_default_visibility_applies_to_real_creation(self):
        self.site.update_settings(self.admin.id, default_repo_visibility="public")
        born = self.repos.create_repository(self.member.id, "yrsa", "born-public")
        self.assertEqual(born.visibility, "public")
        named = self.repos.create_repository(self.member.id, "yrsa", "named", visibility="private")
        self.assertEqual(named.visibility, "private")
    def test_default_visibility_defaults_private_unwired(self):
        plain_repos = RepositoryStore(self.conn, self.data_root, AccountStore(self.conn))
        born = plain_repos.create_repository(self.member.id, "yrsa", "plain-born")
        self.assertEqual(born.visibility, "private")
    def test_upload_limit_refuses_oversize_in_plain_words(self):
        self.site.update_settings(self.admin.id, upload_max_bytes=8)
        ok = self.site.enforce_upload(b"hello")
        self.assertEqual(ok.size, 5)
        with self.assertRaises(SiteSettingsError) as c:
            self.site.enforce_upload(b"hello world, too long")
        self.assertEqual(c.exception.reason, "upload_too_large")
        self.assertIn("8 bytes", str(c.exception))
        self.assertEqual(self.site.upload_policy().max_bytes, 8)
    def test_upload_type_law_still_applies_under_site_cap(self):
        with self.assertRaises(UploadRejected):
            self.site.enforce_upload(b"\x00\x01\x02binary")
    def test_repo_size_limit_drives_quota_service(self):
        self.repos.create_repository(self.member.id, "yrsa", "capped")
        quotas = QuotaService(self.conn, self.data_root, self.accounts, self.repos)
        self.assertIsNone(quotas.default_quota())
        self.site.update_settings(self.admin.id, repo_size_limit_bytes=12345)
        self.assertEqual(quotas.default_quota(), 12345)
        self.assertEqual(quotas.effective_quota("yrsa", "capped"), 12345)
        decision = quotas.check_receive("yrsa", "capped", 10**9)
        self.assertFalse(decision.allowed)
        self.site.update_settings(self.admin.id, repo_size_limit_bytes=None)
        self.assertIsNone(quotas.default_quota())
    def test_legacy_quota_default_key_read_as_limit(self):
        quotas = QuotaService(self.conn, self.data_root, self.accounts, self.repos)
        quotas.set_default_quota(self.admin.id, 777)
        self.assertEqual(self.site.get_settings().repo_size_limit_bytes, 777)
    def test_render_escapes_and_shows_all_settings(self):
        self.site.update_settings(self.admin.id, instance_name="<script>x</script>", instance_description="Tom & co")
        page = render_site_settings_page(self.site.get_settings())
        self.assertNotIn("<script>x", page)
        self.assertIn("&lt;script&gt;", page); self.assertIn("Tom &amp; co", page)
        self.assertIn("private", page); self.assertIn("10485760", page)
if __name__ == "__main__":
    unittest.main()
