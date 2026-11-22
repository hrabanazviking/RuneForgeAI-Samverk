"""S-380 -- PART XIX GATE battery: the Samtal seam, assembled.

The whole Part XIX system struck at once, in the house gate
shape of S-204/S-220/S-236/S-256/S-272/S-288/S-312/S-328/
S-344/S-360 -- no new production code, only the battery that
walks the landed S-361..S-379 machinery end to end through
its public seams, at the three things the gate names:

- **The seam counted battery** -- S-374's end-to-end walk
  (12 steps, all green), S-373's permissions matrix counted
  (90 cells: 68 allowed / 22 denied, and both collapses --
  seam off and unlinked -- denying all 90), and S-379's
  adversarial review counted (34 attacks, all held, with
  its one finding fixed and one named).
- **The boundary doc** -- S-375's honest boundary verified
  standing: check_boundary green on the live code, every
  boundary statement counted, and docs/SEAM_BOUNDARY.md
  on disk saying what the seam is NOT.
- **The kill-switch drill, recorded** -- S-372's switch
  flipped from BOTH sides in one drill: disable from the
  Samtal side (seam doors refuse seam_disabled while the
  standalone doors work untouched), re-enable from the
  Samverk side, disable from the Samverk side, re-enable
  from the Samtal side. Four flips, each audit-logged on
  Samverk's chain and each present in the Samtal-side seam
  ledger; the drill record stands in docs/PART_XIX_GATE.md.

- **The pins** -- the assembled system stands at schema
  140 with 142 audit events (34 auth / 92 repo / 16 admin).
  The gate claims no migration and no taxonomy event.

- **The honest remainder** -- no Samtal codebase stands on
  this seat (S-361's standing honesty). The gate judges
  Samverk's side of the seam and the shared seam ledger;
  it does not claim a Samtal-side run, and the boundary
  doc says so where operators will read it.

Counted with: python3 -m unittest tests.test_part_xix_gate
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.link_unfurl import LinkUnfurlError, LinkUnfurlService
from samverk.repositories import RepositoryStore
from samverk.seam_battery import SeamWalk
from samverk.seam_boundary import boundary_statements, check_boundary
from samverk.seam_kill_switch import SeamKillSwitchService
from samverk.seam_permissions_audit import run_audit
from samverk.seam_security_review import SeamSecurityReview
from samverk.seam_sso import SeamSsoError, SeamSsoService, mint_sso_token
from samverk.identity_linking import IdentityLinkStore
from samverk.sessions import SessionStore

ON = {"seam.samtal.enabled": True}
PW = "a long enough passphrase"
SECRET = b"gate-secret-for-tests-only"
ROOT = Path(__file__).resolve().parent.parent


class _Env:
    def __init__(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "s.db")
        self.audit = AuditLog(self.conn, time_fn=lambda: 5000)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.settings = dict(ON)
    def close(self):
        self.conn.close(); self._td.cleanup()
    def admin(self, name="gate-admin"):
        raw = self.accounts.register(name, PW)
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?",
                              (raw.id,))
        return self.accounts.get_by_id(raw.id)


class CountedBatteryTests(unittest.TestCase):
    def setUp(self): self.env = _Env()
    def tearDown(self): self.env.close()
    def test_walk_is_counted_green(self):
        e = self.env
        villager = e.accounts.register("villager", PW)
        reviewer = e.accounts.register("reviewer", PW)
        walk = SeamWalk(e.conn, e.root, e.accounts, settings=self.env.settings,
                        secret=SECRET, audit=e.audit, time_fn=lambda: 5000)
        report = walk.run(villager, reviewer)
        self.assertEqual(len(report.steps), 12)
        self.assertTrue(report.all_green, report.summary())
    def test_permissions_matrix_counted(self):
        report = run_audit(ON, linked=True)
        self.assertEqual(report.total, 90)
        self.assertEqual(report.allowed, 68)
        self.assertEqual(report.total - report.allowed, 22)
        off = run_audit({}, linked=True)
        self.assertEqual(off.allowed, 0)
        unlinked = run_audit(ON, linked=False)
        self.assertEqual(unlinked.allowed, 0)
    def test_security_review_counted(self):
        e = self.env
        review = SeamSecurityReview(e.conn, e.root, e.accounts,
                                    settings=self.env.settings, secret=SECRET,
                                    audit=e.audit, time_fn=lambda: 5000)
        report = review.run()
        self.assertEqual(report.total, 34)
        self.assertTrue(report.all_held, report.summary())
        self.assertEqual(report.family_counts(),
                         {"token_exchange": (15, 15),
                          "link_unfurling": (10, 10),
                          "event_posting": (9, 9)})


class BoundaryDocTests(unittest.TestCase):
    def test_boundary_checks_green_and_statements_counted(self):
        result = check_boundary({})
        self.assertTrue(result["ok"], result)
        statements = boundary_statements()
        self.assertEqual(len(statements), 3)
        ids = [s["id"] for s in statements]
        self.assertIn("no_federation", ids)
        self.assertEqual(len(ids), len(set(ids)))
    def test_boundary_doc_stands_where_operators_read_it(self):
        doc = (ROOT / "docs" / "SEAM_BOUNDARY.md").read_text(encoding="utf-8")
        self.assertIn("No federation", doc)
        self.assertIn("NOT", doc)


class KillSwitchDrillTests(unittest.TestCase):
    """The drill, executed -- docs/PART_XIX_GATE.md records it."""
    def setUp(self): self.env = _Env()
    def tearDown(self): self.env.close()
    def test_drill_from_both_sides_recorded(self):
        e = self.env
        admin = e.admin()
        owner = e.accounts.register("drill-owner", PW)
        repos = RepositoryStore(e.conn, e.root, e.accounts)
        repos.create_repository(owner.id, "drill-owner", "pub",
                                visibility="public")
        links = IdentityLinkStore(e.conn, e.accounts, audit=e.audit,
                                  time_fn=lambda: 5000)
        links.link(owner.id, "samtal", "seat-drill")
        sessions = SessionStore(e.conn, time_fn=lambda: 5000)
        switch = SeamKillSwitchService(e.conn, e.accounts,
                                       settings=e.settings, audit=e.audit,
                                       time_fn=lambda: 5000)
        unfurl = LinkUnfurlService(e.conn, e.root, e.accounts,
                                   settings=e.settings, audit=e.audit,
                                   time_fn=lambda: 5000)
        sso = SeamSsoService(links, e.accounts, sessions, secret=SECRET,
                             settings=e.settings, time_fn=lambda: 5000)
        # Seam alive before the drill.
        self.assertEqual(unfurl.unfurl(owner, "/drill-owner/pub").kind, "repo")
        # Flip 1: disable from the Samtal side.
        rec = switch.disable(admin, side="samtal")
        self.assertFalse(rec.enabled); self.assertEqual(rec.side, "samtal")
        with self.assertRaises(LinkUnfurlError) as cm:
            unfurl.unfurl(owner, "/drill-owner/pub")
        self.assertEqual(cm.exception.reason, "seam_disabled")
        with self.assertRaises(SeamSsoError) as cm:
            sso.exchange(mint_sso_token(SECRET, principal="seat-drill",
                                        now=4950, nonce="drill-1"))
        self.assertEqual(cm.exception.reason, "seam_disabled")
        # Standalone Samverk stands whole with the seam off.
        fresh = e.accounts.register("drill-fresh", PW)
        repos.create_repository(fresh.id, "drill-fresh", "own",
                                visibility="private")
        # Flip 2: re-enable from the Samverk side; the seam answers.
        rec = switch.enable(admin, side="samverk")
        self.assertTrue(rec.enabled); self.assertEqual(rec.side, "samverk")
        self.assertEqual(unfurl.unfurl(owner, "/drill-owner/pub").kind, "repo")
        # Flip 3: disable from the Samverk side; refusals again.
        switch.disable(admin, side="samverk")
        with self.assertRaises(LinkUnfurlError) as cm:
            unfurl.unfurl(owner, "/drill-owner/pub")
        self.assertEqual(cm.exception.reason, "seam_disabled")
        # Flip 4: re-enable from the Samtal side; drill ends seam-on.
        switch.enable(admin, side="samtal")
        self.assertEqual(unfurl.unfurl(owner, "/drill-owner/pub").kind, "repo")
        # The record: standing flip, both-side ledger, audit chain.
        standing = switch.standing()
        self.assertTrue(standing["enabled"])
        self.assertEqual(standing["side"], "samtal")
        log = switch.samtal_log()
        self.assertEqual([r["side"] for r in log],
                         ["samtal", "samverk", "samverk", "samtal"])
        self.assertEqual([r["enabled"] for r in log],
                         [False, True, False, True])
        rows = e.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE "
            "action = 'admin.settings.change' AND target_id = 'seam'").fetchone()
        self.assertEqual(rows["n"], 4)


class PinTests(unittest.TestCase):
    def setUp(self): self.env = _Env()
    def tearDown(self): self.env.close()
    def test_pins_schema_140_taxonomy_142(self):
        self.assertEqual(schema_version(self.env.conn), 140)
        self.assertEqual(db.MIGRATIONS[-1][0], 140)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)
        fams = {}
        for ev in taxonomy.AUDIT_EVENTS:
            fams[ev.split(".")[0]] = fams.get(ev.split(".")[0], 0) + 1
        self.assertEqual(fams.get("auth"), 34)
        self.assertEqual(fams.get("admin"), 16)


if __name__ == "__main__":
    unittest.main()
