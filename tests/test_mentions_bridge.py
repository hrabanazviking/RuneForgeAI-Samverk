"""S-369 battery — mentions bridge."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.identity_linking import IdentityLinkStore
from samverk.mentions_bridge import MentionsBridgeError, MentionsBridgeService
from samverk.notification_reasons import NotificationStore

ON = {"seam.samtal.enabled": True}
PW = "a long enough passphrase"

class MentionsBridgeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "s.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.author = self.accounts.register("author", PW)
        self.mentioned = self.accounts.register("mentioned", PW)
        self.links = IdentityLinkStore(self.conn, self.accounts, audit=self.audit, time_fn=lambda: 5000)
        self.links.link(self.mentioned.id, "samtal", "principal-mention")
        self.notes = NotificationStore(self.conn, self.accounts, time_fn=lambda: 5000)
        self.svc = MentionsBridgeService(self.conn, self.accounts, settings=ON,
                                         audit=self.audit, time_fn=lambda: 5000)
    def tearDown(self):
        self.conn.close(); self._td.cleanup()
    def _reason(self, fn, *a, **k):
        with self.assertRaises(MentionsBridgeError) as ctx: fn(*a, **k)
        return ctx.exception.reason
    def _bridge(self, **over):
        call = dict(source_key="issue:volmarr/pub#1", recipient=self.mentioned,
                    actor=self.author, target_kind="issue",
                    target_id="volmarr/pub#1")
        call.update(over)
        return self.svc.bridge_mention(**call)
    def test_bridged_mention_is_one_notification_two_doors(self):
        delivery = self._bridge()
        self.assertFalse(delivery.already_delivered)
        self.assertEqual(delivery.doors, ("samverk", "samtal"))
        self.assertEqual(delivery.principal, "principal-mention")
        rows = self.notes.list_for_recipient(self.mentioned)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].id, delivery.notification_id)
        self.assertEqual(rows[0].reason, "mention")
    def test_rebridge_same_source_creates_nothing(self):
        first = self._bridge()
        second = self._bridge()
        self.assertTrue(second.already_delivered)
        self.assertEqual(second.notification_id, first.notification_id)
        self.assertEqual(len(self.notes.list_for_recipient(self.mentioned)), 1)
        self.assertEqual(self.notes.unread_count(self.mentioned), 1)
    def test_different_source_is_a_new_notification(self):
        self._bridge()
        other = self._bridge(source_key="issue:volmarr/pub#2",
                             target_id="volmarr/pub#2")
        self.assertFalse(other.already_delivered)
        self.assertEqual(len(self.notes.list_for_recipient(self.mentioned)), 2)
    def test_unlinked_recipient_gets_samverk_door_only(self):
        delivery = self._bridge(recipient=self.author, actor=self.mentioned)
        self.assertIsNone(delivery.principal)
        self.assertEqual(delivery.doors, ("samverk",))
        self.assertEqual(len(self.notes.list_for_recipient(self.author)), 1)
    def test_self_mention_refused(self):
        self.assertEqual(self._reason(self._bridge, recipient=self.author,
                                      actor=self.author), "self_mention")
    def test_seam_disabled_and_source_required(self):
        off = MentionsBridgeService(self.conn, self.accounts, settings={},
                                    audit=self.audit, time_fn=lambda: 5000)
        self.assertEqual(self._reason(off.bridge_mention, source_key="s",
                                      recipient=self.mentioned, actor=self.author),
                         "seam_disabled")
        self.assertEqual(self._reason(self._bridge, source_key=" "), "source_required")
    def test_delivery_for_reads_standing_record(self):
        delivery = self._bridge()
        standing = self.svc.delivery_for("issue:volmarr/pub#1", self.mentioned.id)
        self.assertEqual(standing.notification_id, delivery.notification_id)
        self.assertIsNone(self.svc.delivery_for("issue:nope#9", self.mentioned.id))

if __name__ == "__main__":
    unittest.main()
