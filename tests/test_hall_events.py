"""S-367 battery — repo events into halls."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.hall_events import HallEventError, HallEventService, render_card

ON = {"seam.samtal.enabled": True}
PW = "a long enough passphrase"

class HallEventTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "s.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.keeper = self.accounts.register("keeper", PW)
        self.svc = HallEventService(self.conn, settings=ON)
        self.svc.opt_in(self.keeper, "hall-1", "keeper/forge")
    def tearDown(self):
        self.conn.close(); self._td.cleanup()
    def _reason(self, fn, *a, **k):
        with self.assertRaises(HallEventError) as ctx: fn(*a, **k)
        return ctx.exception.reason
    def _push(self, **over):
        call = dict(kind="push", repo="keeper/forge", title="3 commits to main",
                    link_path="/keeper/forge", actor_name="keeper",
                    idempotency_key="push-1")
        call.update(over)
        return self.svc.post_event("hall-1", **call)
    def test_opted_in_push_posts_card_with_link(self):
        card = self._push()
        self.assertFalse(card.already_delivered)
        self.assertEqual([c.title for c in self.svc.cards_for("hall-1")],
                         ["3 commits to main"])
        html = render_card(card)
        self.assertIn("/keeper/forge", html)
        self.assertIn("3 commits to main", html)
    def test_no_opt_in_no_delivery(self):
        self.assertEqual(self._reason(self._push, repo="keeper/other"),
                         "not_opted_in")
    def test_kind_filter_respected(self):
        self.svc.opt_in(self.keeper, "hall-2", "keeper/forge", kinds=["issue"])
        self.assertEqual(
            self._reason(self.svc.post_event, "hall-2", kind="push",
                         repo="keeper/forge", title="x", link_path="/x",
                         idempotency_key="k2"), "not_opted_in")
    def test_mute_blocks_and_unmute_restores(self):
        self.svc.mute(self.keeper, "hall-1", "keeper/forge")
        self.assertEqual(self._reason(self._push), "hall_muted")
        self.svc.unmute(self.keeper, "hall-1", "keeper/forge")
        self.assertEqual(self._push().title, "3 commits to main")
    def test_exactly_once_under_idempotency_key(self):
        first = self._push()
        second = self._push()
        self.assertTrue(second.already_delivered)
        self.assertEqual(second.link_path, first.link_path)
        self.assertEqual(len(self.svc.cards_for("hall-1")), 1)
    def test_private_repo_refused_into_open_hall(self):
        self.assertEqual(self._reason(self._push, repo_private=True),
                         "privacy_leak")
    def test_private_repo_posts_into_restricted_hall(self):
        card = self._push(repo_private=True, hall_restricted=True)
        self.assertEqual(card.kind, "push")
    def test_seam_disabled_refuses(self):
        off = HallEventService(self.conn, settings={})
        self.assertEqual(self._reason(off.opt_in, self.keeper, "h", "a/b"),
                         "seam_disabled")
        self.assertEqual(self._reason(off.post_event, "hall-1", kind="push",
                                      repo="keeper/forge", title="x",
                                      link_path="/x", idempotency_key="k"),
                         "seam_disabled")
    def test_unknown_kind_and_missing_key_refused_by_contract(self):
        self.assertEqual(self._reason(self._push, kind="star"), "event_kind_unknown")
        self.assertEqual(self._reason(self._push, idempotency_key=""),
                         "idempotency_required")
    def test_opt_out_stops_delivery(self):
        self.svc.opt_out(self.keeper, "hall-1", "keeper/forge")
        self.assertEqual(self._reason(self._push), "not_opted_in")

if __name__ == "__main__":
    unittest.main()
