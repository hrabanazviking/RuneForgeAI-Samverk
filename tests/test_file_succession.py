"""S-366 battery — file-sharing succession (keep in Samverk)."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.file_succession import FileSuccessionError, FileSuccessionService, SharedFile, render_message_link
from samverk.gists import GistStore

ON = {"seam.samtal.enabled": True}
PW = "a long enough passphrase"

class FileSuccessionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "s.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.uploader = self.accounts.register("sharer", PW)
        self.other = self.accounts.register("bystander", PW)
        self.svc = FileSuccessionService(self.conn, self.root, self.accounts, settings=ON, audit=self.audit, time_fn=lambda: 5000)
        self.gists = GistStore(self.conn, self.root, self.accounts, audit=self.audit, time_fn=lambda: 5000)
        self.shared = SharedFile(message_id="msg-42", uploader_id=self.uploader.id, filename="notes.txt", content="the hall notes\nsecond line\n")
    def tearDown(self):
        self.conn.close(); self._td.cleanup()
    def _reason(self, fn, *a, **k):
        with self.assertRaises(FileSuccessionError) as ctx: fn(*a, **k)
        return ctx.exception.reason
    def test_keep_creates_gist_with_file_content(self):
        kept = self.svc.keep_in_samverk(self.uploader, self.shared)
        self.assertFalse(kept.already_kept)
        files = self.gists.list_files(self.uploader, kept.gist_id)
        self.assertEqual([f.name for f in files], ["notes.txt"])
        gist = self.gists.get_gist(self.uploader, kept.gist_id)
        self.assertEqual(gist.owner_id, self.uploader.id)
    def test_old_file_stays_readable_source_untouched(self):
        before = (self.shared.filename, self.shared.content)
        self.svc.keep_in_samverk(self.uploader, self.shared)
        self.assertEqual((self.shared.filename, self.shared.content), before)
        self.assertEqual(self.shared.content, "the hall notes\nsecond line\n")
    def test_message_links_to_kept_gist(self):
        kept = self.svc.keep_in_samverk(self.uploader, self.shared)
        link = self.svc.link_for("msg-42")
        self.assertEqual(link.gist_id, kept.gist_id)
        html = render_message_link(kept)
        self.assertIn(f"/gists/{kept.gist_id}", html)
        self.assertIn("notes.txt", html)
    def test_second_keep_returns_standing_link_no_duplicate(self):
        first = self.svc.keep_in_samverk(self.uploader, self.shared)
        second = self.svc.keep_in_samverk(self.uploader, self.shared)
        self.assertTrue(second.already_kept)
        self.assertEqual(second.gist_id, first.gist_id)
    def test_stranger_cannot_keep_anothers_file(self):
        self.assertEqual(self._reason(self.svc.keep_in_samverk, self.other, self.shared), "not_file_owner")
    def test_seam_disabled_refused(self):
        off = FileSuccessionService(self.conn, self.root, self.accounts, settings={}, audit=self.audit, time_fn=lambda: 5000)
        self.assertEqual(self._reason(off.keep_in_samverk, self.uploader, self.shared), "seam_disabled")
    def test_unkept_message_has_no_link(self):
        self.assertIsNone(self.svc.link_for("msg-99"))

if __name__ == "__main__":
    unittest.main()
