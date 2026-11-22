"""S-364 battery — agent parity (equal seats, provenance shown, never rank)."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore
from samverk.agent_parity import AgentParityError, AgentParityService, render_seat_page
from samverk.audit import AuditLog
from samverk.identity_linking import IdentityLinkStore
from samverk.ssh_keys import SshKeyStore, parse_public_key
import base64, os

ON = {"seam.samtal.enabled": True}
PW = "a long enough passphrase"

def key_line(seed: bytes) -> str:
    import struct
    mat = seed.ljust(32, b"\0")[:32]
    blob = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", len(mat)) + mat
    return "ssh-ed25519 " + base64.b64encode(blob).decode()

class AgentParityTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "s.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.links = IdentityLinkStore(self.conn, self.accounts, audit=self.audit, time_fn=lambda: 5000)
        self.keys = SshKeyStore(self.conn, self.accounts, audit=self.audit, reauth_verifier=lambda uid: True, time_fn=lambda: 5000)
        self.tokens = AccessTokenStore(self.conn, self.accounts, audit=self.audit, time_fn=lambda: 5000)
        self.svc = AgentParityService(self.accounts, self.links, self.keys, self.tokens, settings=ON)
        self.human = self.accounts.register("volmarr", PW)
    def tearDown(self):
        self.conn.close(); self._td.cleanup()
    def test_agent_seated_through_same_door(self):
        agent = self.svc.provision_agent("astrid-seat", "astrid-agent", PW)
        self.assertEqual(agent.status, self.human.status)
        self.assertEqual(agent.is_admin, self.human.is_admin)
        self.assertEqual(self.accounts.get_by_username("astrid-agent").id, agent.id)
    def test_provenance_shown_for_agent_human_for_human(self):
        agent = self.svc.provision_agent("astrid-seat", "astrid-agent", PW)
        self.assertEqual(self.svc.provenance_for(agent.id).kind, "agent")
        self.assertEqual(self.svc.provenance_for(agent.id).principal, "astrid-seat")
        self.assertEqual(self.svc.provenance_for(self.human.id).kind, "human")
    def test_agent_holds_key_and_token_exactly_as_human(self):
        agent = self.svc.provision_agent("astrid-seat", "astrid-agent", PW)
        ak = self.svc.add_key(agent.id, "agent key", key_line(b"a"))
        hk = self.keys.add_key(self.human.id, "human key", key_line(b"h"))
        self.assertEqual(ak.key_type, hk.key_type)
        atok, araw = self.svc.create_token(agent.id, "agent tok", ["repo:read"], 9000)
        htok, hraw = self.tokens.create_token(self.human.id, "human tok", ["repo:read"], 9000)
        self.assertEqual(self.tokens.authenticate(araw).id, atok.id)
        self.assertEqual(self.tokens.authenticate(hraw).id, htok.id)
        self.assertEqual(self.svc.seat_parity(agent.id).ssh_key_count, 1)
        self.assertEqual(self.svc.seat_parity(agent.id).token_count, 1)
    def test_token_revocation_equal(self):
        agent = self.svc.provision_agent("astrid-seat", "astrid-agent", PW)
        tok, raw = self.svc.create_token(agent.id, "t", ["repo:read"], 9000)
        self.tokens.revoke_token(agent.id, tok.id)
        self.assertIsNone(self.tokens.authenticate(raw))
    def test_duplicate_principal_refused(self):
        self.svc.provision_agent("astrid-seat", "astrid-agent", PW)
        with self.assertRaises(AgentParityError) as cm:
            self.svc.provision_agent("astrid-seat", "astrid-two", PW)
        self.assertEqual(cm.exception.reason, "principal_already_linked")
    def test_seam_disabled_refused(self):
        off = AgentParityService(self.accounts, self.links, self.keys, self.tokens, settings={})
        with self.assertRaises(AgentParityError) as cm:
            off.provision_agent("x-seat", "some-agent", PW)
        self.assertEqual(cm.exception.reason, "seam_disabled")
    def test_username_law_applies_to_agents(self):
        with self.assertRaises(Exception):
            self.svc.provision_agent("x-seat", "admin", PW)
    def test_seat_page_shows_provenance_never_rank(self):
        agent = self.svc.provision_agent("astrid-seat", "astrid-agent", PW)
        page = render_seat_page(agent, self.svc.seat_parity(agent.id))
        self.assertIn("Agent — Samtal principal astrid-seat", page)
        for banned in ("rank", "tier", "score", "level"):
            self.assertNotIn(banned, page.lower())
    def test_unknown_seat_refused(self):
        with self.assertRaises(AgentParityError) as cm:
            self.svc.seat_parity(99999)
        self.assertEqual(cm.exception.reason, "no_such_user")

if __name__ == "__main__":
    unittest.main()
