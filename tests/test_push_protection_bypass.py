"""S-293 acceptance battery: push-protection bypass.

Acceptance (roadmap S-293): permitted roles may
bypass push protection with a stated reason; the
bypass is an alert + audit event, visible to
owners (GitHub's honest pattern, adopted openly).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.db import schema_version
from samverk.hooks import RefUpdate
from samverk.outside_collaborators import OutsideCollaboratorStore
from samverk.push_protection_bypass import (
    BYPASS_AUDIT_REQUIRED, BYPASS_EVENT, BYPASS_NOT_NEEDED,
    BYPASS_NOT_PERMITTED, BYPASS_NOT_VISIBLE,
    BYPASS_REASON_REQUIRED, BYPASS_REASON_TOO_LONG,
    MAX_REASON_CHARS, PERMITTED_ROLES, PROTECTION_UNAVAILABLE,
    BypassError, PushProtectionBypassStore, decide_bypass,
    normalise_decision, normalise_finding, protection_available,
    render_bypass_list_page, render_bypass_page, validate_reason)
from samverk.repositories import RepositoryStore
from samverk.webhook_events import get_webhook_event

PLANTED = "ghp_PLANTEDSECRETVALUE0123456789abcdef"
ZERO = "0" * 40
ONE = "1" * 40
TWO = "2" * 40


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


def refused_decision(**over):
    decision = {
        "allowed": False,
        "reason": ("push refused: config.txt contains a "
                   "detected secret (GitHub classic personal "
                   "access token) at line 3; remove it and "
                   "push again"),
        "findings": [{
            "path": "config.txt", "commit": ONE, "blob": TWO,
            "source": "pattern", "detector_id": "github_pat_classic",
            "pattern_class": "GitHub classic personal access token",
            "line": 3, "column": 9, "redacted": "ghp_...cdef",
            "fingerprint": "ab" * 32,
            "secret": PLANTED, "matched_text": PLANTED,
        }],
    }
    decision.update(over)
    return decision


class PushProtectionBypassTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register(
            "volmarr", "correct horse battery")
        self.maintainer = self.accounts.register(
            "yrsa", "correct horse battery")
        self.writer = self.accounts.register(
            "tess", "correct horse battery")
        self.stranger = self.accounts.register(
            "mallory", "correct horse battery")
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.store = PushProtectionBypassStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.pub = self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.priv = self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        grants = OutsideCollaboratorStore(
            self.conn, self.accounts, audit=self.audit,
            time_fn=self.clock)
        grants.grant(self.owner.id, self.pub.id,
                     "yrsa", "maintain")
        grants.grant(self.owner.id, self.pub.id,
                     "tess", "write")
        grants.grant(self.owner.id, self.priv.id,
                     "yrsa", "maintain")

    # -- helpers -----------------------------------------------------

    def _audit_rows(self):
        return self.conn.execute(
            "SELECT seq, actor_id, target_id, detail"
            " FROM audit_log WHERE action = ? ORDER BY seq",
            (BYPASS_EVENT,)).fetchall()

    def _alert_rows(self):
        return self.conn.execute(
            "SELECT * FROM push_protection_bypasses"
            " ORDER BY id").fetchall()

    def _bypass(self, actor=None, repo="pub", **kw):
        kw.setdefault("reason", "Fixture token, already revoked.")
        kw.setdefault("decision", refused_decision())
        return self.store.bypass_push(
            self.owner if actor is None else actor,
            "volmarr", repo, **kw)

    # -- pins -----------------------------------------------------------

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 128)
        self.assertEqual(db.MIGRATIONS[-1][0], 128)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertIn(BYPASS_EVENT, taxonomy.REPO_EVENTS)
        spec = get_webhook_event(BYPASS_EVENT)
        self.assertEqual(spec.scope, "repository")
        self.assertEqual(spec.category, "push")
        self.assertEqual(
            spec.detail_fields,
            ("repository", "actor", "role", "role_source",
             "reason", "findings", "refs"))
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'table'")}
        self.assertIn("push_protection_bypasses", tables)

    def test_protection_seam_is_lazy(self):
        # The seam is lazy by construction: this slice's
        # module imports S-292's face only through the
        # call-time probe, never at load. S-292 stands
        # on the banked line (banked before S-293 in
        # roadmap order), so the probe finds it.
        self.assertTrue(protection_available())

    # -- the pure judgement ----------------------------------------------

    def test_decide_bypass_roles(self):
        for role in ("admin", "maintain"):
            decision = decide_bypass(
                role=role, actor="volmarr",
                full_name="volmarr/pub", reason="Revoked.")
            self.assertTrue(decision.may_bypass, role)
            self.assertEqual(decision.code, "")
            self.assertIn("alert and an audit event",
                          decision.words)
        self.assertEqual(PERMITTED_ROLES,
                         frozenset({"admin", "maintain"}))
        for role in ("write", "triage", "read", None):
            decision = decide_bypass(
                role=role, actor="tess",
                full_name="volmarr/pub", reason="Revoked.")
            self.assertFalse(decision.may_bypass, role)
            self.assertEqual(decision.code, BYPASS_NOT_PERMITTED)
            self.assertIn("volmarr/pub", decision.reason)
            self.assertIn("permitted roles", decision.reason)

    def test_decide_bypass_needs_a_reason(self):
        for bad in ("", "   ", None, 42):
            decision = decide_bypass(
                role="admin", actor="volmarr",
                full_name="volmarr/pub", reason=bad)
            self.assertFalse(decision.may_bypass, bad)
            self.assertEqual(decision.code,
                             BYPASS_REASON_REQUIRED)

    def test_validate_reason(self):
        self.assertEqual(validate_reason("  Revoked.  "),
                         "Revoked.")
        for bad in ("", "  ", None, 42):
            with self.assertRaises(BypassError) as cm:
                validate_reason(bad)
            self.assertEqual(cm.exception.reason,
                             BYPASS_REASON_REQUIRED)
        with self.assertRaises(BypassError) as cm:
            validate_reason("x" * (MAX_REASON_CHARS + 1))
        self.assertEqual(cm.exception.reason,
                         BYPASS_REASON_TOO_LONG)
        self.assertEqual(
            validate_reason("x" * MAX_REASON_CHARS),
            "x" * MAX_REASON_CHARS)

    def test_normalise_finding_drops_the_secret(self):
        finding = normalise_finding(refused_decision()["findings"][0])
        self.assertEqual(finding.path, "config.txt")
        self.assertEqual(finding.commit_oid, ONE)
        self.assertEqual(finding.blob_oid, TWO)
        self.assertEqual(finding.pattern_class,
                         "GitHub classic personal access token")
        blob = json.dumps(finding.to_dict())
        blob += json.dumps(finding.audit_dict())
        self.assertNotIn(PLANTED, blob)
        self.assertNotIn("secret", finding.to_dict())
        self.assertNotIn("matched_text", finding.to_dict())

    def test_normalise_decision_shapes(self):
        view = normalise_decision(refused_decision())
        self.assertFalse(view.allowed)
        self.assertEqual(len(view.findings), 1)

        class Obj:
            allowed = True
            reason = ""
            findings = ()
        self.assertTrue(normalise_decision(Obj()).allowed)

    # -- the use ---------------------------------------------------------

    def test_owner_bypass_leaves_alert_and_audit(self):
        record = self._bypass(updates=(
            RefUpdate("refs/heads/main", ZERO, ONE),))
        self.assertEqual(record.full_name, "volmarr/pub")
        self.assertEqual(record.actor_username, "volmarr")
        self.assertEqual(record.role, "admin")
        self.assertEqual(record.role_source, "owner")
        self.assertEqual(record.state, "open")
        self.assertEqual(record.reason,
                         "Fixture token, already revoked.")
        self.assertEqual(len(record.findings), 1)
        self.assertEqual(record.refs, ({
            "ref": "refs/heads/main", "old": ZERO, "new": ONE},))
        rows = self._audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["seq"], record.audit_seq)
        self.assertEqual(rows[0]["actor_id"], self.owner.id)
        self.assertEqual(rows[0]["target_id"], "volmarr/pub")
        detail = json.loads(rows[0]["detail"])
        self.assertEqual(detail["actor"], "volmarr")
        self.assertEqual(detail["role"], "admin")
        self.assertEqual(detail["reason"],
                         "Fixture token, already revoked.")
        self.assertEqual(detail["findings"][0]["path"],
                         "config.txt")
        self.assertEqual(len(self._alert_rows()), 1)
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, bad)

    def test_maintainer_may_bypass(self):
        record = self._bypass(actor=self.maintainer)
        self.assertEqual(record.role, "maintain")
        self.assertEqual(record.actor_username, "yrsa")

    def test_writer_may_not_bypass(self):
        with self.assertRaises(BypassError) as cm:
            self._bypass(actor=self.writer)
        self.assertEqual(cm.exception.reason,
                         BYPASS_NOT_PERMITTED)
        self.assertIn("'tess'", str(cm.exception))
        self.assertIn("Write", str(cm.exception))
        self.assertEqual(self._alert_rows(), [])
        self.assertEqual(self._audit_rows(), [])

    def test_bypass_without_reason_is_refused(self):
        for bad in ("", "   ", None):
            with self.assertRaises(BypassError) as cm:
                self._bypass(reason=bad)
            self.assertEqual(cm.exception.reason,
                             BYPASS_REASON_REQUIRED, bad)
        self.assertEqual(self._alert_rows(), [])
        self.assertEqual(self._audit_rows(), [])

    def test_bypass_reason_too_long_is_refused(self):
        with self.assertRaises(BypassError) as cm:
            self._bypass(reason="x" * (MAX_REASON_CHARS + 1))
        self.assertEqual(cm.exception.reason,
                         BYPASS_REASON_TOO_LONG)
        self.assertEqual(self._alert_rows(), [])

    def test_allowed_push_has_nothing_to_bypass(self):
        with self.assertRaises(BypassError) as cm:
            self._bypass(decision={"allowed": True,
                                   "reason": "", "findings": []})
        self.assertEqual(cm.exception.reason, BYPASS_NOT_NEEDED)
        self.assertEqual(self._alert_rows(), [])
        self.assertEqual(self._audit_rows(), [])

    def test_unjudged_push_cannot_be_bypassed(self):
        # No judge anywhere: S-292 stands on the banked
        # line, so hide its face from the lazy probe for
        # this one judgement (a None sys.modules entry
        # makes the probe's import fail, as on a base
        # without the face). The named refusal stands.
        face = sys.modules.pop("samverk.push_protection", None)
        sys.modules["samverk.push_protection"] = None
        try:
            with self.assertRaises(BypassError) as cm:
                self.store.bypass_push(
                    self.owner, "volmarr", "pub",
                    reason="Revoked.",
                    updates=(RefUpdate("refs/heads/main", ZERO, ONE),))
        finally:
            if face is not None:
                sys.modules["samverk.push_protection"] = face
            else:
                sys.modules.pop("samverk.push_protection", None)
        self.assertEqual(cm.exception.reason,
                         PROTECTION_UNAVAILABLE)

    def test_injected_protection_judges(self):
        def judge(owner, repo, updates, *, history, prior_tips):
            return refused_decision()
        store = PushProtectionBypassStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, protection=judge,
            time_fn=self.clock)
        record = store.bypass_push(
            self.owner, "volmarr", "pub", reason="Revoked.",
            updates=(RefUpdate("refs/heads/main", ZERO, ONE),))
        self.assertEqual(record.state, "open")

        class Face:
            def check_push(self, owner, repo, updates, *,
                           history=None, prior_tips=()):
                return {"allowed": True, "reason": "",
                        "findings": []}
        store2 = PushProtectionBypassStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, protection=Face(),
            time_fn=self.clock)
        with self.assertRaises(BypassError) as cm:
            store2.bypass_push(
                self.owner, "volmarr", "pub", reason="Revoked.",
                updates=(RefUpdate("refs/heads/main", ZERO, ONE),))
        self.assertEqual(cm.exception.reason, BYPASS_NOT_NEEDED)

    def test_no_audit_log_no_bypass(self):
        store = PushProtectionBypassStore(
            self.conn, self.repos, self.accounts,
            audit=None, time_fn=self.clock)
        with self.assertRaises(BypassError) as cm:
            store.bypass_push(
                self.owner, "volmarr", "pub",
                reason="Revoked.", decision=refused_decision())
        self.assertEqual(cm.exception.reason,
                         BYPASS_AUDIT_REQUIRED)
        self.assertEqual(self._alert_rows(), [])

    def test_anonymous_and_stranger_roads(self):
        with self.assertRaises(BypassError) as cm:
            self.store.bypass_push(
                None, "volmarr", "pub",
                reason="Revoked.", decision=refused_decision())
        self.assertEqual(cm.exception.reason,
                         BYPASS_NOT_PERMITTED)
        for actor in (None, self.stranger):
            with self.assertRaises(BypassError) as cm:
                self.store.bypass_push(
                    actor, "volmarr", "priv",
                    reason="Revoked.", decision=refused_decision())
            self.assertEqual(cm.exception.reason,
                             "repo_not_found", actor)
        with self.assertRaises(BypassError) as cm:
            self.store.bypass_push(
                self.owner, "volmarr", "missing",
                reason="Revoked.", decision=refused_decision())
        self.assertEqual(cm.exception.reason, "repo_not_found")

    def test_capped_refusal_can_be_bypassed(self):
        record = self._bypass(decision={
            "allowed": False,
            "reason": ("push refused: the push introduces "
                       "more history than push protection "
                       "can scan"),
            "findings": []})
        self.assertEqual(record.findings, ())
        page = render_bypass_page(record)
        self.assertIn("cut short before it could be proven clean", page)

    def test_judge_is_a_pure_read(self):
        decision = self.store.judge(
            self.writer, "volmarr", "pub", reason="Revoked.")
        self.assertFalse(decision.may_bypass)
        decision = self.store.judge(
            self.maintainer, "volmarr", "pub", reason="Revoked.")
        self.assertTrue(decision.may_bypass)
        self.assertEqual(self._alert_rows(), [])
        self.assertEqual(self._audit_rows(), [])

    # -- the owners' read --------------------------------------------------

    def test_alerts_visible_to_owners_only(self):
        first = self._bypass()
        second = self._bypass(reason="Second incident.")
        seen = self.store.list_bypasses(
            self.owner, "volmarr", "pub")
        self.assertEqual([r.id for r in seen],
                         [first.id, second.id])
        self.assertEqual(
            self.store.get_bypass(
                self.owner, "volmarr", "pub", second.id).reason,
            "Second incident.")
        for viewer in (self.maintainer, self.writer, None):
            with self.assertRaises(BypassError) as cm:
                self.store.list_bypasses(viewer, "volmarr", "pub")
            self.assertEqual(cm.exception.reason,
                             BYPASS_NOT_VISIBLE, viewer)
        with self.assertRaises(BypassError) as cm:
            self.store.list_bypasses(
                self.stranger, "volmarr", "priv")
        self.assertEqual(cm.exception.reason, "repo_not_found")
        with self.assertRaises(BypassError) as cm:
            self.store.get_bypass(
                self.owner, "volmarr", "pub", 9999)
        self.assertEqual(cm.exception.reason, "bypass_not_found")

    # -- the secret on no surface -------------------------------------------

    def test_secret_is_never_echoed(self):
        record = self._bypass(updates=(
            RefUpdate("refs/heads/main", ZERO, ONE),))
        surfaces = [
            json.dumps(record.to_dict()),
            render_bypass_page(record),
            render_bypass_list_page([record], "volmarr/pub"),
            self._alert_rows()[0]["findings"],
            self._alert_rows()[0]["reason"],
            self._audit_rows()[0]["detail"],
        ]
        for surface in surfaces:
            self.assertNotIn(PLANTED, surface)
        # ...while the shape is still named, in words.
        page = render_bypass_page(record)
        self.assertIn("config.txt", page)
        self.assertIn("GitHub classic personal access token",
                      page)
        self.assertIn("Fixture token, already revoked.", page)
        detail = json.loads(self._audit_rows()[0]["detail"])
        self.assertEqual(detail["findings"][0]["fingerprint"],
                         "ab" * 32)

    def test_pages_escape_user_text(self):
        record = self._bypass(
            reason="Revoked <script>alert(1)</script> token.")
        page = render_bypass_page(record)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)


if __name__ == "__main__":
    unittest.main()
