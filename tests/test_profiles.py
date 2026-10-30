"""S-029 acceptance battery: profiles.

Acceptance (roadmap S-029): display name, bio, avatar upload
under S-012 law, profile page; every image carries alt text.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.profiles import (
    ProfileError,
    ProfileStore,
    render_profile_page,
)
from samverk.uploads import UploadRejected

GOOD_PW = "a long enough passphrase"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
SCRIPT_BYTES = b"#!/bin/sh\nrm -rf / # totally an image\n"
PDF_BYTES = b"%PDF-1.7\n" + b"%\x00" * 8
ALT = "Portrait of Volmarr in a black cloak"


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.profiles = ProfileStore(
            self.conn, self.accounts, audit=self.audit)
        self.user = self.accounts.register("volmarr", GOOD_PW)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_default_profile_is_empty_and_falls_back_to_username(self):
        profile = self.profiles.get_profile(self.user.id)
        self.assertIsNone(profile.display_name)
        self.assertIsNone(profile.avatar_sha256)
        page = render_profile_page("volmarr", profile)
        self.assertIn("volmarr", page)
        self.assertNotIn("<img", page)

    def test_update_display_name_and_bio(self):
        profile = self.profiles.update_profile(
            self.user.id, display_name="Volmarr Wyrd",
            bio="Viking.\nAuthor.")
        self.assertEqual(profile.display_name, "Volmarr Wyrd")
        self.assertEqual(profile.bio, "Viking.\nAuthor.")
        page = render_profile_page("volmarr", profile)
        self.assertIn("Volmarr Wyrd", page)
        self.assertIn("Viking.<br>", page)

    def test_display_name_limits_and_controls_refused(self):
        with self.assertRaises(ProfileError) as ctx:
            self.profiles.update_profile(
                self.user.id, display_name="x" * 51)
        self.assertEqual(ctx.exception.reason, "display_name_too_long")
        with self.assertRaises(ProfileError):
            self.profiles.update_profile(
                self.user.id, display_name="bad\x01name")
        with self.assertRaises(ProfileError) as ctx:
            self.profiles.update_profile(
                self.user.id, bio="y" * 501)
        self.assertEqual(ctx.exception.reason, "bio_too_long")

    def test_avatar_upload_promotes_and_records_alt(self):
        profile = self.profiles.set_avatar(
            self.user.id, PNG_BYTES, data_root=self.root,
            declared_type="image/png", alt_text=ALT)
        self.assertEqual(profile.avatar_content_type, "image/png")
        self.assertEqual(profile.avatar_alt, ALT)
        promoted = self.root / "avatars" / profile.avatar_filename
        self.assertTrue(promoted.exists())
        self.assertEqual(promoted.read_bytes(), PNG_BYTES)
        # Quarantine-first: the S-012 copy exists too.
        self.assertTrue(
            (self.root / "quarantine" / profile.avatar_filename).exists())

    def test_avatar_without_alt_text_is_refused_and_stores_nothing(self):
        for bad_alt in (None, "", "   "):
            with self.assertRaises(ProfileError) as ctx:
                self.profiles.set_avatar(
                    self.user.id, PNG_BYTES, data_root=self.root,
                    declared_type="image/png", alt_text=bad_alt)
            self.assertEqual(ctx.exception.reason, "avatar_alt_required")
        self.assertIsNone(
            self.profiles.get_profile(self.user.id).avatar_sha256)
        self.assertFalse((self.root / "avatars").exists())

    def test_disguised_and_non_image_uploads_are_refused(self):
        with self.assertRaises(UploadRejected):
            self.profiles.set_avatar(
                self.user.id, SCRIPT_BYTES, data_root=self.root,
                declared_type="image/png", alt_text=ALT)
        with self.assertRaises(UploadRejected):
            self.profiles.set_avatar(
                self.user.id, PDF_BYTES, data_root=self.root,
                declared_type="application/pdf", alt_text=ALT)
        self.assertIsNone(
            self.profiles.get_profile(self.user.id).avatar_sha256)

    def test_oversize_avatar_is_refused(self):
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (2 * 1024 * 1024)
        with self.assertRaises(UploadRejected) as ctx:
            self.profiles.set_avatar(
                self.user.id, big, data_root=self.root,
                declared_type="image/png", alt_text=ALT)
        self.assertEqual(ctx.exception.reason, "too_large")

    def test_profile_page_carries_alt_and_escapes_everything(self):
        self.profiles.update_profile(
            self.user.id, display_name="<script>alert(1)</script>",
            bio="<b>not bold</b>")
        self.profiles.set_avatar(
            self.user.id, PNG_BYTES, data_root=self.root,
            declared_type="image/png",
            alt_text='A "quoted" <portrait>')
        profile = self.profiles.get_profile(self.user.id)
        page = render_profile_page("volmarr", profile)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&lt;b&gt;not bold&lt;/b&gt;", page)
        self.assertIn("<img", page)
        self.assertIn('alt="A &quot;quoted&quot; &lt;portrait&gt;"', page)

    def test_unknown_user_is_refused(self):
        with self.assertRaises(ProfileError):
            self.profiles.update_profile(9999, display_name="Ghost")
        with self.assertRaises(ProfileError):
            self.profiles.get_profile(9999)

    def test_profile_updates_are_audited(self):
        self.profiles.update_profile(
            self.user.id, display_name="Volmarr Wyrd")
        self.profiles.set_avatar(
            self.user.id, PNG_BYTES, data_root=self.root,
            declared_type="image/png", alt_text=ALT)
        rows = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action='auth.profile.update' ORDER BY seq").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertIn('"fields":"text"', rows[0]["detail"])
        self.assertIn('"fields":"avatar"', rows[1]["detail"])
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, msg=f"chain broken at {bad}")


if __name__ == "__main__":
    unittest.main()
