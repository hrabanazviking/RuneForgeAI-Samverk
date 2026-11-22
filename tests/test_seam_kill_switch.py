"""S-372 battery — kill switch."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.link_unfurl import LinkUnfurlError, LinkUnfurlService
from samverk.notification_reasons import NotificationStore
from samverk.repositories import RepositoryStore
from samverk.seam_kill_switch import SeamKillSwitchError, SeamKillSwitchService

PW = "a long enough passphrase"

class SeamKillSwitchTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "s.db")
        self.audit = AuditLog(self.conn, time_fn=lambda: 5000)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        raw_admin = self.accounts.register("volmarr", PW)
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (raw_admin.id,))
        self.admin = self.accounts.get_by_id(raw_admin.id)
        self.member = self.accounts.register("yrsa", PW)
        self.settings = {"seam.samtal.enabled": True}
        self.svc = SeamKillSwitchService(self.conn, self.accounts, settings=self.settings, audit=self.audit, time_fn=lambda: 5000)
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.notes = NotificationStore(self.conn, self.accounts, time_fn=lambda: 5000)
    def tearDown(self):
        self.conn.close(); self._td.cleanup()
    def _reason(self, fn, *a, **k):
        with self.assertRaises(SeamKillSwitchError) as ctx: fn(*a, **k)
        return ctx.exception.reason
    def test_disable_from_samtal_side_flips_the_one_switch(self):
        record = self.svc.disable(self.admin, side="samtal")
        self.assertFalse(record.enabled)
        self.assertEqual(record.side, "samtal")
        self.assertIs(self.settings["seam.samtal.enabled"], False)
    def test_disable_from_samverk_side_also_works(self):
        record = self.svc.disable(self.admin, side="samverk")
        self.assertEqual(record.side, "samverk")
        self.assertFalse(self.settings["seam.samtal.enabled"])
    def test_disablement_is_audit_logged_on_both_sides(self):
        record = self.svc.disable(self.admin, side="samtal")
        self.assertIsNotNone(record.samverk_audit_seq)
        row = self.conn.execute("SELECT action, target_id, detail FROM audit_log WHERE seq = ?", (record.samverk_audit_seq,)).fetchone()
        self.assertEqual(row["action"], "admin.settings.change")
        self.assertEqual(row["target_id"], "seam")
        self.assertIn('"samtal"', row["detail"])
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok)
        log = self.svc.samtal_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["side"], "samtal")
        self.assertFalse(log[0]["enabled"])
        self.assertEqual(self.svc.standing()["side"], "samtal")
    def test_seam_doors_close_cleanly_and_standalone_stays_whole(self):
        self.repos.create_repository(self.admin.id, "volmarr", "pub", visibility="public")
        unfurl = LinkUnfurlService(self.conn, self.root, self.accounts, settings=self.settings, audit=self.audit, time_fn=lambda: 5000)
        self.assertEqual(unfurl.unfurl(self.member, "/volmarr/pub").kind, "repo")
        self.svc.disable(self.admin, side="samverk")
        with self.assertRaises(LinkUnfurlError) as ctx:
            unfurl.unfurl(self.member, "/volmarr/pub")
        self.assertEqual(ctx.exception.reason, "seam_disabled")
        # Samverk standalone continues whole: repos and notifications work.
        self.repos.create_repository(self.admin.id, "volmarr", "after", visibility="private")
        note = self.notes.notify(self.member, self.admin, "mention", target_kind="issue", target_id="volmarr/pub#1")
        self.assertEqual(self.notes.unread_count(self.member), 1)
        self.assertEqual(note.reason, "mention")
    def test_non_admin_and_bad_side_refused(self):
        self.assertEqual(self._reason(self.svc.disable, self.member, side="samtal"), "permission_denied")
        self.assertEqual(self._reason(self.svc.disable, None, side="samtal"), "permission_denied")
        self.assertEqual(self._reason(self.svc.disable, self.admin, side="third"), "side_invalid")
        self.assertIs(self.settings["seam.samtal.enabled"], True)
    def test_double_disable_refused_and_enable_restores_logged(self):
        self.svc.disable(self.admin, side="samtal")
        self.assertEqual(self._reason(self.svc.disable, self.admin, side="samverk"), "already_disabled")
        record = self.svc.enable(self.admin, side="samverk")
        self.assertTrue(record.enabled)
        self.assertIs(self.settings["seam.samtal.enabled"], True)
        self.assertEqual(self._reason(self.svc.enable, self.admin, side="samtal"), "already_enabled")
        self.assertEqual(len(self.svc.samtal_log()), 2)
        rows = self.conn.execute("SELECT COUNT(*) AS n FROM audit_log WHERE action = 'admin.settings.change' AND target_id = 'seam'").fetchone()
        self.assertEqual(rows["n"], 2)

if __name__ == "__main__":
    unittest.main()
