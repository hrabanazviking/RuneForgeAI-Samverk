"""S-089 acceptance battery: the pre-receive gate point.

Acceptance (roadmap S-089): protection rules (Part VIII) and
secret scanning (Part XV) plug into receive-pack here; the gate
order is documented (in `samverk/receive_gate.py`) and proven
here — stages run in GATE_ORDER, the first refusal wins, every
stage fails closed, and both transports consult the gate before
any pack byte moves.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.git_http import SmartHttpService, TransportError
from samverk.hooks import HookRunner, RefUpdate
from samverk.receive_gate import GATE_ORDER, GateVeto, ReceiveGate
from samverk.repo_quotas import QuotaService
from samverk.repositories import RepositoryStore
from test_ssh_upload_routing import FakeRunner, make_world, serve

ZERO = "0" * 40
ONE = "1" * 40


def recording(calls, name, result=None):
    def plugin(ctx):
        calls.append(name)
        return result
    return plugin


class GateOrderTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.conn = db.init_db(root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "a long enough passphrase")
        self.repos = RepositoryStore(self.conn, root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk")
        self.quotas = QuotaService(self.conn, root, self.accounts, self.repos)
        self.root = root

    def check(self, gate, **kw):
        kw.setdefault("owner", "volmarr")
        kw.setdefault("repo", "samverk")
        return gate.check(**kw)

    def test_gate_order_is_the_documented_order(self):
        self.assertEqual(
            GATE_ORDER, ("protection", "secret_scan", "quota", "hooks"))

    def test_stages_run_in_order_and_all_allow(self):
        calls = []
        gate = ReceiveGate(quota_service=self.quotas)
        gate.register_protection("p1", recording(calls, "protection"))
        gate.register_secret_scanner("s1", recording(calls, "secret_scan"))
        result = self.check(gate, incoming_bytes=1)
        self.assertTrue(result.allowed)
        self.assertEqual(calls, ["protection", "secret_scan"])
        stages = [o.stage for o in result.outcomes if o.status == "allowed"]
        self.assertEqual(stages, ["protection", "secret_scan", "quota"])

    def test_no_plugins_allows_and_skips_are_named(self):
        result = self.check(ReceiveGate())
        self.assertTrue(result.allowed)
        statuses = {o.stage: o.status for o in result.outcomes}
        self.assertEqual(statuses["protection"], "skipped")
        self.assertEqual(statuses["quota"], "skipped")
        self.assertEqual(statuses["hooks"], "skipped")

    def test_protection_veto_stops_the_chain(self):
        calls = []
        gate = ReceiveGate()
        gate.register_protection(
            "protected-main",
            recording(calls, "protection", "refs/heads/main is protected"))
        gate.register_secret_scanner("scan", recording(calls, "secret_scan"))
        result = self.check(
            gate, updates=(RefUpdate("refs/heads/main", ZERO, ONE),))
        self.assertFalse(result.allowed)
        self.assertEqual(result.refused_stage, "protection")
        self.assertEqual(result.refused_by, "protected-main")
        self.assertIn("protected", result.reason)
        self.assertEqual(calls, ["protection"])  # scanner never ran

    def test_scanner_exception_fails_closed(self):
        def boom(ctx):
            raise RuntimeError("scanner exploded")
        gate = ReceiveGate()
        gate.register_secret_scanner("scan", boom)
        result = self.check(gate)
        self.assertFalse(result.allowed)
        self.assertEqual(result.refused_stage, "secret_scan")
        self.assertIn("scanner exploded", result.reason)

    def test_gate_veto_carries_its_reason(self):
        def veto(ctx):
            raise GateVeto("a secret was found in README.md")
        gate = ReceiveGate()
        gate.register_secret_scanner("scan", veto)
        result = self.check(gate)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "a secret was found in README.md")

    def test_quota_stage_refuses_over_quota(self):
        usage = self.quotas.usage_bytes("volmarr", "samverk")
        self.quotas.set_repo_quota(
            self.owner.id, "volmarr", "samverk", usage + 100)
        gate = ReceiveGate(quota_service=self.quotas)
        result = self.check(gate, incoming_bytes=10_000)
        self.assertFalse(result.allowed)
        self.assertEqual(result.refused_stage, "quota")
        self.assertIn("quota", result.reason.lower())
        ok = self.check(gate, incoming_bytes=1)
        self.assertTrue(ok.allowed)

    def test_hooks_stage_is_last_and_can_veto(self):
        calls = []
        runner = HookRunner(timeout_seconds=5)
        runner.register_pre_receive("operator-hook", lambda ctx: "no pushes today")
        gate = ReceiveGate(hook_runner=runner)
        gate.register_protection("p", recording(calls, "protection"))
        result = self.check(gate)
        self.assertFalse(result.allowed)
        self.assertEqual(result.refused_stage, "hooks")
        self.assertIn("no pushes today", result.reason)
        self.assertEqual(calls, ["protection"])


class TransportWiringTests(unittest.TestCase):
    def test_ssh_receive_consults_the_gate_before_the_pack(self):
        runner = FakeRunner()
        w = make_world(self, runner=runner)
        gate = ReceiveGate()
        gate.register_protection("stop", lambda ctx: "frozen by the operator")
        w["service"]._receive_gate = gate
        rc, _, err = serve(w, w["owner_fp"], "git-receive-pack 'volmarr/samverk'")
        self.assertEqual(rc, 128)
        self.assertIn(b"frozen by the operator", err)
        self.assertEqual(runner.calls, [])  # no pack byte moved
        # Reads are not the gate's business.
        rc, out, _ = serve(w, w["owner_fp"], "git-upload-pack 'volmarr/samverk'")
        self.assertEqual(rc, 0)
        self.assertEqual(out, b"PACK-OK")

    def test_http_receive_consults_the_gate_before_the_pack(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        conn = db.init_db(root / "samverk.db")
        self.addCleanup(conn.close)
        accounts = AccountStore(conn)
        owner = accounts.register("volmarr", "a long enough passphrase")
        repos = RepositoryStore(conn, root, accounts)
        repos.create_repository(owner.id, "volmarr", "samverk")
        gate = ReceiveGate()
        gate.register_secret_scanner("scan", lambda ctx: "secret found")
        service = SmartHttpService(conn, root, accounts, repos, receive_gate=gate)
        with self.assertRaises(TransportError) as caught:
            service.receive_pack(owner, "volmarr", "samverk", b"whatever")
        self.assertEqual(caught.exception.reason, "push_refused")
        self.assertIn("secret found", str(caught.exception))
        # Advertisement (a read-side leg) is unaffected.
        resp = service.advertise(owner, "volmarr", "samverk", "git-upload-pack")
        self.assertIn(b"git-upload-pack", resp.body)


if __name__ == "__main__":
    unittest.main()
