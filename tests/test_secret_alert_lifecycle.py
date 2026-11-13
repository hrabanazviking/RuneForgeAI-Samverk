"""S-294 acceptance battery: secret alert lifecycle.

Acceptance (roadmap S-294): Secret alert lifecycle
-- open -> resolved (revoked / false positive /
used-in-test) with resolver and reason recorded;
reopening supported.

The lifecycle lives in
samverk/secret_alert_lifecycle.py over migration
117's resolution columns on S-291's secret_alerts
plus the secret_alert_events record (schema
116 -> 117 on the banked line; renumbered from
116 at banking, S-293's migration 116 for its
bypass table banking first in roadmap order). A resolve answers a live
(open or reopened) alert under exactly one of the
three named kinds, with the resolver and a stated
reason recorded on the alert row and the
transition standing as a row on the alert's own
events record, written in the same transaction. A
reopen answers only a resolved alert, clears the
standing resolution whole, and is recorded the
same way. Acts are judged by S-190's permission
engine: only the admin and maintain rungs may
move an alert (the rungs S-293 trusts); every
other rung, no access and anonymity are refused
lifecycle_not_permitted. No new taxonomy event --
134 stand (33 auth / 88 repo / 13 admin); the
battery proves the audit log does not move.

Alerts are born through S-291's real scan road
(an injected scanner over an in-memory history),
so the lifecycle is proven against the rows it
will actually govern.

Counted with: python3 -m unittest tests.test_secret_alert_lifecycle
"""
from __future__ import annotations
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.hooks import RefUpdate
from samverk.outside_collaborators import OutsideCollaboratorStore
from samverk.push_scanning import PushScanStore, ScanFinding
from samverk.repositories import RepositoryStore
from samverk.secret_alert_lifecycle import (
    ALERT_ALREADY_RESOLVED, ALERT_NOT_FOUND,
    ALERT_NOT_RESOLVED, LIFECYCLE_NOT_PERMITTED,
    MAX_REASON_CHARS, PERMITTED_ROLES, REASON_REQUIRED,
    REASON_TOO_LONG, RESOLUTIONS, RESOLUTION_INVALID,
    LifecycleError, SecretAlertLifecycleStore,
    decide_transition, render_alert_page, render_alerts_page,
    resolution_word, validate_reason, validate_resolution)

PW = "correct horse battery"
T0 = 1_700_000_000
ZERO = "0" * 40
SECRET = "hunter2-is-the-planted-secret"


def oid(n: int) -> str:
    return f"{n:040x}"


def fake_scanner(text: str):
    out = []
    for i, line in enumerate(text.splitlines(), start=1):
        if SECRET in line:
            out.append(ScanFinding(
                source="injected", detector_id="planted_secret",
                line=i, column=line.index(SECRET) + 1,
                redacted="planted...[redacted]",
                fingerprint=hashlib.sha256(
                    SECRET.encode()).hexdigest()))
    return out


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class FakeHistory:
    def __init__(self):
        self.parents: dict = {}
        self.trees: dict = {}
        self.blobs: dict = {}
        self._next = 1000

    def add_blob(self, data: bytes) -> str:
        self._next += 1
        b = oid(self._next)
        self.blobs[b] = data
        return b

    def add_commit(self, parents=(), files=None) -> str:
        self._next += 1
        c = oid(self._next)
        tree = {}
        for path, data in (files or {}).items():
            tree[path] = ("100644", self.add_blob(data))
        self.parents[c] = tuple(parents)
        self.trees[c] = tree
        return c

    def commit_parents(self, o):
        return self.parents[o]

    def commit_tree(self, o):
        return o

    def flatten_tree(self, t):
        return dict(self.trees[t])

    def read_blob(self, o):
        return self.blobs[o]


class SecretAlertLifecycleTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.clock = Clock()
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.maintainer = self.accounts.register("yrsa", PW)
        self.writer = self.accounts.register("tess", PW)
        self.reader = self.accounts.register("runa", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.pub = self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.priv = self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        grants = OutsideCollaboratorStore(
            self.conn, self.accounts, audit=self.audit,
            time_fn=self.clock)
        for repo in (self.pub, self.priv):
            grants.grant(self.owner.id, repo.id, "yrsa", "maintain")
            grants.grant(self.owner.id, repo.id, "tess", "write")
            grants.grant(self.owner.id, repo.id, "runa", "read")
        self.scans = PushScanStore(
            self.conn, self.repos, time_fn=self.clock)
        self.life = SecretAlertLifecycleStore(
            self.conn, self.repos, self.accounts,
            time_fn=self.clock)

    # -- helpers -------------------------------------------------

    def make_alert(self, repo="pub"):
        # Distinct path per alert: S-291 alert identity is
        # (repo, commit, path, detector, fingerprint), and
        # this fake's oids repeat per history, so a second
        # identical (path, secret) pair is one alert, not two.
        self._alert_n = getattr(self, "_alert_n", 0) + 1
        path = f"app{self._alert_n}.py"
        hist = FakeHistory()
        hist._next = 1000 + self._alert_n * 100
        c = hist.add_commit(
            parents=(), files={path: f"{SECRET}\n".encode()})
        scan = self.scans.scan_push(
            "volmarr", repo,
            updates=[RefUpdate("refs/heads/main", ZERO, c)],
            history=hist, scanner=fake_scanner)
        self.assertEqual(scan.alerts_created, 1)
        return self.scans.alerts_for_scan(scan.id)[0]

    def resolve(self, alert, actor=None, repo="pub", **kw):
        kw.setdefault("resolution", "revoked")
        kw.setdefault("reason", "Rotated at the provider.")
        return self.life.resolve_alert(
            self.owner if actor is None else actor,
            "volmarr", repo, alert.id, **kw)

    def audit_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    # -- pins ------------------------------------------------------

    def test_schema_stands_at_117(self):
        self.assertEqual(schema_version(self.conn), 125)
        self.assertEqual(db.MIGRATIONS[-1][0], 125)

    def test_taxonomy_still_134(self):
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    def test_resolution_vocabulary_is_the_roadmaps_three(self):
        self.assertEqual(
            RESOLUTIONS,
            frozenset({"revoked", "false_positive", "used_in_test"}))
        self.assertEqual(resolution_word("revoked"), "revoked")
        self.assertEqual(
            resolution_word("false_positive"), "false positive")
        self.assertEqual(
            resolution_word("used_in_test"), "used in test")
        self.assertEqual(PERMITTED_ROLES,
                         frozenset({"admin", "maintain"}))

    # -- the resolve ------------------------------------------------

    def test_resolve_revoked_records_resolver_and_reason(self):
        alert = self.make_alert()
        done = self.resolve(alert)
        self.assertEqual(done.state, "resolved")
        self.assertEqual(done.resolution, "revoked")
        self.assertEqual(done.resolved_by, "volmarr")
        self.assertEqual(done.resolved_by_id, self.owner.id)
        self.assertEqual(done.resolved_at, T0)
        self.assertEqual(done.resolution_reason,
                         "Rotated at the provider.")
        self.assertTrue(done.is_resolved)
        self.assertIn("resolved as revoked by volmarr",
                      done.resolution_words())
        events = self.life.list_events(
            self.owner, "volmarr", "pub", alert.id)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.action, "resolve")
        self.assertEqual(ev.from_state, "open")
        self.assertEqual(ev.to_state, "resolved")
        self.assertEqual(ev.resolution, "revoked")
        self.assertEqual(ev.actor_username, "volmarr")
        self.assertEqual(ev.role, "admin")
        self.assertEqual(ev.reason, "Rotated at the provider.")
        self.assertEqual(ev.created_at, T0)

    def test_each_named_kind_resolves(self):
        for kind in ("revoked", "false_positive", "used_in_test"):
            alert = self.make_alert()
            done = self.resolve(
                alert, resolution=kind,
                reason=f"Recorded as {kind}.")
            self.assertEqual(done.resolution, kind)
            self.assertEqual(done.state, "resolved")

    def test_maintainer_may_resolve(self):
        alert = self.make_alert()
        done = self.life.resolve_alert(
            self.maintainer, "volmarr", "pub", alert.id,
            resolution="false_positive",
            reason="It is a published example value.")
        self.assertEqual(done.resolved_by, "yrsa")
        events = self.life.list_events(
            self.owner, "volmarr", "pub", alert.id)
        self.assertEqual(events[0].role, "maintain")

    def test_unknown_kind_is_refused_and_alert_stands_open(self):
        alert = self.make_alert()
        for bad in ("wontfix", "", None, 7):
            with self.assertRaises(LifecycleError) as ctx:
                self.resolve(alert, resolution=bad)
            self.assertEqual(ctx.exception.reason, RESOLUTION_INVALID)
        standing = self.life.get_alert(
            self.owner, "volmarr", "pub", alert.id)
        self.assertEqual(standing.state, "open")
        self.assertEqual(
            self.life.list_events(
                self.owner, "volmarr", "pub", alert.id), ())

    def test_reason_is_required_and_capped(self):
        alert = self.make_alert()
        for bad in ("", "   ", None, 7):
            with self.assertRaises(LifecycleError) as ctx:
                self.resolve(alert, reason=bad)
            self.assertEqual(ctx.exception.reason, REASON_REQUIRED)
        with self.assertRaises(LifecycleError) as ctx:
            self.resolve(alert, reason="x" * (MAX_REASON_CHARS + 1))
        self.assertEqual(ctx.exception.reason, REASON_TOO_LONG)
        done = self.resolve(alert, reason="x" * MAX_REASON_CHARS)
        self.assertEqual(done.state, "resolved")
        self.assertEqual(validate_reason("  tidy  "), "tidy")
        self.assertEqual(validate_resolution("revoked"), "revoked")

    def test_double_resolve_is_refused(self):
        alert = self.make_alert()
        self.resolve(alert)
        with self.assertRaises(LifecycleError) as ctx:
            self.resolve(alert, resolution="false_positive",
                         reason="Second thoughts.")
        self.assertEqual(ctx.exception.reason, ALERT_ALREADY_RESOLVED)
        standing = self.life.get_alert(
            self.owner, "volmarr", "pub", alert.id)
        self.assertEqual(standing.resolution, "revoked")
        self.assertEqual(
            len(self.life.list_events(
                self.owner, "volmarr", "pub", alert.id)), 1)

    # -- permission ----------------------------------------------------

    def test_writer_reader_and_stranger_may_not_resolve(self):
        alert = self.make_alert()
        for actor in (self.writer, self.reader, self.stranger):
            with self.assertRaises(LifecycleError) as ctx:
                self.life.resolve_alert(
                    actor, "volmarr", "pub", alert.id,
                    resolution="revoked", reason="Trying.")
            self.assertEqual(
                ctx.exception.reason, LIFECYCLE_NOT_PERMITTED)
        with self.assertRaises(LifecycleError) as ctx:
            self.life.resolve_alert(
                None, "volmarr", "pub", alert.id,
                resolution="revoked", reason="Trying.")
        self.assertEqual(ctx.exception.reason, LIFECYCLE_NOT_PERMITTED)
        self.assertEqual(
            self.life.get_alert(
                self.owner, "volmarr", "pub", alert.id).state, "open")

    def test_stranger_to_private_repo_gets_repo_not_found(self):
        alert = self.make_alert(repo="priv")
        with self.assertRaises(LifecycleError) as ctx:
            self.life.resolve_alert(
                self.stranger, "volmarr", "priv", alert.id,
                resolution="revoked", reason="Trying.")
        self.assertEqual(ctx.exception.reason, "repo_not_found")
        with self.assertRaises(LifecycleError) as ctx:
            self.life.get_alert(
                self.stranger, "volmarr", "priv", alert.id)
        self.assertEqual(ctx.exception.reason, "repo_not_found")

    def test_missing_repo_and_alert_are_named(self):
        alert = self.make_alert()
        with self.assertRaises(LifecycleError) as ctx:
            self.life.resolve_alert(
                self.owner, "volmarr", "nope", alert.id,
                resolution="revoked", reason="Trying.")
        self.assertEqual(ctx.exception.reason, "repo_not_found")
        with self.assertRaises(LifecycleError) as ctx:
            self.life.resolve_alert(
                self.owner, "volmarr", "pub", 999999,
                resolution="revoked", reason="Trying.")
        self.assertEqual(ctx.exception.reason, ALERT_NOT_FOUND)
        other = self.make_alert(repo="priv")
        with self.assertRaises(LifecycleError) as ctx:
            self.life.resolve_alert(
                self.owner, "volmarr", "pub", other.id,
                resolution="revoked", reason="Wrong repo.")
        self.assertEqual(ctx.exception.reason, ALERT_NOT_FOUND)

    def test_judge_is_pure(self):
        alert = self.make_alert()
        yes = self.life.judge(
            self.owner, "volmarr", "pub", alert.id,
            action="resolve", resolution="revoked",
            reason="Rotated at the provider.")
        self.assertTrue(yes.may_move)
        no = self.life.judge(
            self.writer, "volmarr", "pub", alert.id,
            action="resolve", resolution="revoked",
            reason="Rotated at the provider.")
        self.assertFalse(no.may_move)
        self.assertEqual(no.code, LIFECYCLE_NOT_PERMITTED)
        self.assertEqual(
            self.life.get_alert(
                self.owner, "volmarr", "pub", alert.id).state, "open")
        self.assertEqual(
            self.life.list_events(
                self.owner, "volmarr", "pub", alert.id), ())

    def test_pure_decision_judges_state_before_role(self):
        d = decide_transition(
            action="resolve", role="write", actor="tess",
            full_name="volmarr/pub", alert_state="resolved",
            resolution="revoked", reason="Again.")
        self.assertFalse(d.may_move)
        self.assertEqual(d.code, ALERT_ALREADY_RESOLVED)
        d = decide_transition(
            action="reopen", role="admin", actor="volmarr",
            full_name="volmarr/pub", alert_state="open",
            reason="Back again.")
        self.assertEqual(d.code, ALERT_NOT_RESOLVED)

    # -- the reopen ------------------------------------------------------

    def test_reopen_clears_resolution_and_records_reason(self):
        alert = self.make_alert()
        self.resolve(alert)
        self.clock.now = T0 + 60
        back = self.life.reopen_alert(
            self.maintainer, "volmarr", "pub", alert.id,
            reason="The token still authenticates.")
        self.assertEqual(back.state, "reopened")
        self.assertEqual(back.resolution, "")
        self.assertIsNone(back.resolved_by_id)
        self.assertEqual(back.resolved_by, "")
        self.assertIsNone(back.resolved_at)
        self.assertEqual(back.resolution_reason, "")
        self.assertIn("reopened", back.resolution_words())
        events = self.life.list_events(
            self.owner, "volmarr", "pub", alert.id)
        self.assertEqual([e.action for e in events],
                         ["resolve", "reopen"])
        ev = events[1]
        self.assertEqual(ev.from_state, "resolved")
        self.assertEqual(ev.to_state, "reopened")
        self.assertEqual(ev.resolution, "")
        self.assertEqual(ev.actor_username, "yrsa")
        self.assertEqual(ev.reason, "The token still authenticates.")
        self.assertEqual(ev.created_at, T0 + 60)

    def test_reopen_needs_a_resolved_alert_and_a_reason(self):
        alert = self.make_alert()
        with self.assertRaises(LifecycleError) as ctx:
            self.life.reopen_alert(
                self.owner, "volmarr", "pub", alert.id,
                reason="Too soon.")
        self.assertEqual(ctx.exception.reason, ALERT_NOT_RESOLVED)
        self.resolve(alert)
        with self.assertRaises(LifecycleError) as ctx:
            self.life.reopen_alert(
                self.owner, "volmarr", "pub", alert.id, reason="")
        self.assertEqual(ctx.exception.reason, REASON_REQUIRED)
        self.life.reopen_alert(
            self.owner, "volmarr", "pub", alert.id,
            reason="Still live.")
        with self.assertRaises(LifecycleError) as ctx:
            self.life.reopen_alert(
                self.owner, "volmarr", "pub", alert.id,
                reason="Twice.")
        self.assertEqual(ctx.exception.reason, ALERT_NOT_RESOLVED)

    def test_full_cycle_resolve_reopen_reresolve(self):
        alert = self.make_alert()
        self.resolve(alert, resolution="used_in_test",
                      reason="A fixture value.")
        self.life.reopen_alert(
            self.owner, "volmarr", "pub", alert.id,
            reason="Copied into real config.")
        done = self.resolve(alert, resolution="revoked",
                             reason="Now rotated for real.")
        self.assertEqual(done.state, "resolved")
        self.assertEqual(done.resolution, "revoked")
        self.assertEqual(done.resolution_reason,
                         "Now rotated for real.")
        events = self.life.list_events(
            self.owner, "volmarr", "pub", alert.id)
        self.assertEqual(
            [(e.action, e.from_state, e.to_state) for e in events],
            [("resolve", "open", "resolved"),
             ("reopen", "resolved", "reopened"),
             ("resolve", "reopened", "resolved")])
        # S-291's own read surface shows the same standing state.
        standing = self.scans.list_alerts("volmarr", "pub")
        self.assertEqual(standing[0].state, "resolved")

    # -- witnessing and surfaces ------------------------------------------

    def test_lifecycle_is_unwitnessed_in_the_audit_log(self):
        alert = self.make_alert()
        before = self.audit_count()
        self.resolve(alert)
        self.life.reopen_alert(
            self.owner, "volmarr", "pub", alert.id,
            reason="Still live.")
        self.resolve(alert, reason="Rotated now.")
        self.assertEqual(self.audit_count(), before)

    def test_secret_never_surfaces(self):
        alert = self.make_alert()
        done = self.resolve(alert)
        events = self.life.list_events(
            self.owner, "volmarr", "pub", alert.id)
        surfaces = (
            str(done.to_dict()),
            str([e.to_dict() for e in events]),
            render_alert_page(done, events),
            render_alerts_page([done]))
        for surface in surfaces:
            self.assertNotIn(SECRET, surface)
        row = self.conn.execute(
            "SELECT * FROM secret_alert_events").fetchone()
        self.assertNotIn(SECRET, str(dict(row)))

    def test_pages_say_the_lifecycle_in_words(self):
        alert = self.make_alert()
        done = self.resolve(
            alert, resolution="false_positive",
            reason="A documented example value.")
        page = render_alert_page(
            done, self.life.list_events(
                self.owner, "volmarr", "pub", alert.id))
        self.assertIn("resolved as false positive by volmarr", page)
        self.assertIn("app1.py", page)
        listing = render_alerts_page([done])
        self.assertIn("false positive", listing)

    # -- the reads ------------------------------------------------------------

    def test_reads_and_counts_follow_the_lifecycle(self):
        a1 = self.make_alert()
        a2 = self.make_alert()
        self.assertEqual(
            self.life.count_alerts(self.owner, "volmarr", "pub"), 2)
        self.assertEqual(
            self.life.count_alerts(
                self.owner, "volmarr", "pub", state="open"), 2)
        self.resolve(a1)
        self.assertEqual(
            self.life.count_alerts(
                self.owner, "volmarr", "pub", state="resolved"), 1)
        self.assertEqual(
            self.life.count_alerts(
                self.owner, "volmarr", "pub", state="open"), 1)
        self.assertEqual(
            len(self.life.list_alerts(
                self.reader, "volmarr", "pub", state="resolved")), 1)
        self.life.reopen_alert(
            self.owner, "volmarr", "pub", a1.id, reason="Live.")
        self.assertEqual(
            self.life.count_alerts(
                self.owner, "volmarr", "pub", state="reopened"), 1)
        with self.assertRaises(LifecycleError) as ctx:
            self.life.list_alerts(
                self.owner, "volmarr", "pub", state="bogus")
        self.assertEqual(ctx.exception.reason, "state_invalid")
        with self.assertRaises(LifecycleError) as ctx:
            self.life.list_events(
                self.owner, "volmarr", "pub", 999999)
        self.assertEqual(ctx.exception.reason, ALERT_NOT_FOUND)
        self.assertEqual(a2.state, "open")


if __name__ == "__main__":
    unittest.main()
