"""S-299 acceptance battery: dependency alerts.

Acceptance (roadmap S-299): Dependency alerts --
graph x advisory data -> alerts with severity,
affected range, and fixed version when known;
alert lifecycle as S-294.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.advisory_data import AdvisoryStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.dependency_alerts import (
    BASIS_PINNED, BASIS_RANGE, DependencyAlertError,
    DependencyAlertStore, PERMITTED_ROLES, RESOLUTIONS,
    compare_versions, decide_transition, judge_dependency,
    parse_version, render_alert_page, render_alerts_page,
    resolution_word, version_in_range)
from samverk.dependency_graph import DependencyGraphStore
from samverk.outside_collaborators import OutsideCollaboratorStore
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

T0 = 1_700_000_000
PW = "correct horse battery"

SNAPSHOT = """
{
  "snapshot_format": 1,
  "source": "S-299 battery snapshot (hand-built)",
  "snapshot_date": "2026-11-10",
  "advisories": [
    {"id": "CVE-B-0001", "ecosystem": "python",
     "package": "PyYAML", "severity": "high",
     "affected": "<5.4", "fixed_version": "5.4",
     "summary": "PyYAML loads arbitrary objects.",
     "published": "2020-07-27", "references": []},
    {"id": "CVE-B-0002", "ecosystem": "python",
     "package": "urllib3", "severity": "moderate",
     "affected": "<1.26.5", "fixed_version": "1.26.5",
     "summary": "urllib3 backtracking denial of service.",
     "published": "2021-06-29", "references": []},
    {"id": "CVE-B-0003", "ecosystem": "npm",
     "package": "minimist", "severity": "critical",
     "affected": "<1.2.6", "fixed_version": "1.2.6",
     "summary": "minimist prototype pollution.",
     "published": "2022-03-18", "references": []},
    {"id": "CVE-B-0004", "ecosystem": "npm",
     "package": "lodash", "severity": "high",
     "affected": "<4.17.19", "fixed_version": "4.17.19",
     "summary": "lodash prototype pollution.",
     "published": "2020-07-15", "references": []},
    {"id": "CVE-B-0005", "ecosystem": "go",
     "package": "github.com/dgrijalva/jwt-go",
     "severity": "high", "affected": "<=3.2.0",
     "fixed_version": null,
     "summary": "jwt-go audience confusion; <b>no fix</b> stands.",
     "published": "2020-09-30", "references": []},
    {"id": "CVE-B-0006", "ecosystem": "rust",
     "package": "regex", "severity": "low",
     "affected": "<1.5.5", "fixed_version": "1.5.5",
     "summary": "regex exponential matching.",
     "published": "2022-03-08", "references": []}
  ]
}
"""

REQ = (
    "PyYAML==5.3.1\n"
    "urllib3>=1.0\n"
    "requests==2.31.0\n"
    "mystery @ https://example.com/mystery-1.0.tar.gz\n")

PKG = (
    '{"name": "demo", "version": "1.0.0",'
    ' "dependencies": {"minimist": "1.2.5",'
    ' "lodash": "^4.17.20"}}')

GOMOD = (
    "module example.com/demo\n\n"
    "go 1.21\n\n"
    "require github.com/dgrijalva/jwt-go v3.2.0\n")

CARGO = (
    '[dependencies]\n'
    'regex = "1.5.4"\n')


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class PureLawTests(unittest.TestCase):
    def test_parse_and_compare_versions(self):
        self.assertIsNotNone(parse_version("1.2.3"))
        self.assertIsNotNone(parse_version("v0.3.7"))
        self.assertIsNotNone(parse_version("1.0.0-rc.1+build"))
        self.assertIsNone(parse_version("notaversion"))
        self.assertIsNone(parse_version(""))
        self.assertIsNone(parse_version(None))
        self.assertEqual(compare_versions("1.2", "1.2.0"), 0)
        self.assertEqual(compare_versions("v1.2.3", "1.2.3"), 0)
        self.assertEqual(compare_versions("1.2.3", "1.10.0"), -1)
        self.assertEqual(compare_versions("2.0.0", "1.9.9"), 1)
        self.assertEqual(compare_versions("1.0.0-rc.1", "1.0.0"), -1)
        self.assertIsNone(compare_versions("x", "1.0.0"))

    def test_version_in_range(self):
        self.assertTrue(version_in_range("5.3.1", "<5.4"))
        self.assertFalse(version_in_range("5.4", "<5.4"))
        self.assertTrue(version_in_range("3.2.0", "<=3.2.0"))
        self.assertTrue(version_in_range("1.5.0", ">=1.0,<2.0"))
        self.assertFalse(version_in_range("2.0.0", ">=1.0,<2.0"))
        self.assertIsNone(version_in_range("junk", "<5.4"))
        self.assertIsNone(version_in_range("1.0.0", "whenever"))

    def test_judge_pinned(self):
        verdict = judge_dependency("python", "==5.3.1", "<5.4")
        self.assertTrue(verdict.matched)
        self.assertEqual(verdict.basis, BASIS_PINNED)
        self.assertEqual(verdict.pinned_version, "5.3.1")
        verdict = judge_dependency("python", "==5.4.1", "<5.4")
        self.assertFalse(verdict.matched)
        self.assertFalse(verdict.unjudged)
        verdict = judge_dependency("go", "v3.2.0", "<=3.2.0")
        self.assertTrue(verdict.matched)
        self.assertEqual(verdict.basis, BASIS_PINNED)
        verdict = judge_dependency("rust", "=0.6.13", "<0.6.14")
        self.assertTrue(verdict.matched)

    def test_judge_ranges(self):
        verdict = judge_dependency("python", ">=1.0", "<1.26.5")
        self.assertTrue(verdict.matched)
        self.assertEqual(verdict.basis, BASIS_RANGE)
        verdict = judge_dependency("npm", "^4.17.20", "<4.17.19")
        self.assertFalse(verdict.matched)
        verdict = judge_dependency("npm", "^4.17.20", "<5.0.0")
        self.assertTrue(verdict.matched)
        verdict = judge_dependency("rust", "1.5.4", "<1.5.5")
        self.assertTrue(verdict.matched)
        self.assertEqual(verdict.basis, BASIS_RANGE)
        verdict = judge_dependency("rust", "1.5.4", "<1.5.4")
        self.assertFalse(verdict.matched)
        verdict = judge_dependency("npm", "~1.2.3", "<1.2.6")
        self.assertTrue(verdict.matched)
        verdict = judge_dependency("python", "~=1.4.5", "<1.4.0")
        self.assertFalse(verdict.matched)

    def test_judge_unjudged_and_unbounded(self):
        verdict = judge_dependency(
            "python", "@ https://example.com/x.tar.gz", "<5.4")
        self.assertTrue(verdict.unjudged)
        self.assertFalse(verdict.matched)
        verdict = judge_dependency(
            "rust", '{ git = "https://x/y" }', "<1.0")
        self.assertTrue(verdict.unjudged)
        verdict = judge_dependency("npm", "*", "<1.2.6")
        self.assertTrue(verdict.matched)
        self.assertEqual(verdict.basis, BASIS_RANGE)

    def test_resolution_vocabulary(self):
        self.assertEqual(
            RESOLUTIONS,
            frozenset({"fixed", "false_positive", "risk_accepted"}))
        self.assertEqual(resolution_word("fixed"), "fixed")
        self.assertEqual(
            resolution_word("false_positive"), "false positive")
        self.assertEqual(
            resolution_word("risk_accepted"), "risk accepted")
        self.assertEqual(PERMITTED_ROLES,
                         frozenset({"admin", "maintain"}))
        with self.assertRaises(DependencyAlertError) as ctx:
            resolution_word("revoked")
        self.assertEqual(ctx.exception.reason, "resolution_invalid")

    def test_pure_decision_judges_state_before_role(self):
        decision = decide_transition(
            action="resolve", role="write", actor="tess",
            full_name="volmarr/anvil", alert_state="resolved",
            resolution="fixed", reason="done")
        self.assertFalse(decision.may_move)
        self.assertEqual(decision.code, "alert_already_resolved")
        decision = decide_transition(
            action="reopen", role="admin", actor="volmarr",
            full_name="volmarr/anvil", alert_state="open",
            reason="still here")
        self.assertFalse(decision.may_move)
        self.assertEqual(decision.code, "alert_not_resolved")
        decision = decide_transition(
            action="resolve", role="admin", actor="volmarr",
            full_name="volmarr/anvil", alert_state="open",
            resolution="fixed", reason="Updated past the range.")
        self.assertTrue(decision.may_move)


class AlertTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
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
        self.graph = DependencyGraphStore(
            self.conn, self.repos, self.accounts,
            time_fn=self.clock)
        self.advisories = AdvisoryStore.from_text(
            SNAPSHOT, now="2026-11-12")
        self.alerts = DependencyAlertStore(
            self.conn, self.repos, self.accounts,
            self.advisories, time_fn=self.clock)
        self._seq = 0

    # -- fixture helpers ------------------------------------

    def _repo_with_files(self, name, files, visibility="public",
                         grants=True):
        self._seq += 1
        repo = self.repos.create_repository(
            self.owner.id, "volmarr", name, visibility=visibility)
        if grants:
            store = OutsideCollaboratorStore(
                self.conn, self.accounts, audit=self.audit,
                time_fn=self.clock)
            store.grant(self.owner.id, repo.id, "yrsa", "maintain")
            store.grant(self.owner.id, repo.id, "tess", "write")
            store.grant(self.owner.id, repo.id, "runa", "read")
        bare = self.repos.path_for("volmarr", name)
        work = self.root / f"work{self._seq}"
        work.mkdir()
        self._fill(work, files)
        run_git(work, "push", str(bare), "main")
        return work, run_git(work, "rev-parse", "HEAD")

    def _fill(self, work, files):
        run_git(work, "init", "-b", "main")
        for rel, data in files.items():
            path = work / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data)
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "files")

    def _push_more(self, work, files):
        for rel, data in files.items():
            path = work / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data)
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "more")
        bare = self.repos.path_for("volmarr", "anvil")
        run_git(work, "push", str(bare), "main")
        return run_git(work, "rev-parse", "HEAD")

    def _full_files(self, req=REQ):
        return {"requirements.txt": req, "package.json": PKG,
                "go.mod": GOMOD, "Cargo.toml": CARGO}

    def _graphed(self, name="anvil", files=None, **kw):
        work, tip = self._repo_with_files(
            name, files or self._full_files(), **kw)
        self.graph.graph_tip("volmarr", name, tip)
        return work, tip

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(DependencyAlertError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _audit_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    def _alert_for(self, advisory_id, repo="anvil", viewer=None):
        for alert in self.alerts.list_alerts(
                viewer or self.owner, "volmarr", repo, limit=500):
            if alert.advisory_id == advisory_id:
                return alert
        raise AssertionError(f"no alert for {advisory_id}")

    # -- pins -------------------------------------------------

    def test_pins_schema_121_taxonomy_134(self):
        self.assertEqual(schema_version(self.conn), 126)
        self.assertEqual(db.MIGRATIONS[-1][0], 126)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("dependency_alerts", tables)
        self.assertIn("dependency_alert_events", tables)

    def test_fresh_database_migrates_to_121(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "fresh.db")
            self.assertEqual(db.schema_version(conn), 126)
            conn.close()

    def test_upgrade_from_120_creates_tables(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for target, statements in db.MIGRATIONS:
                if target > 120:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_meta"
                        " (key, value) VALUES ('version', ?)",
                        (str(target),))
            self.assertEqual(db.schema_version(conn), 120)
            self.assertEqual(db.migrate(conn), 126)
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type = 'table'")}
            self.assertIn("dependency_alerts", names)
            conn.close()

    # -- the join ----------------------------------------------

    def test_refresh_creates_alerts_with_advisory_facts(self):
        self._graphed()
        before = self._audit_count()
        report = self.alerts.refresh_alerts(
            self.owner, "volmarr", "anvil")
        self.assertEqual(report.created, 5)
        self.assertEqual(report.matches, 5)
        self.assertEqual(report.standing_live, 5)
        self.assertEqual(report.snapshot_date, "2026-11-10")
        self.assertIn("2026-11-10", report.age_words)
        self.assertEqual(self._audit_count(), before)
        pyyaml = self._alert_for("CVE-B-0001")
        self.assertEqual(pyyaml.package, "PyYAML")
        self.assertEqual(pyyaml.severity, "high")
        self.assertEqual(pyyaml.affected, "<5.4")
        self.assertEqual(pyyaml.fixed_version, "5.4")
        self.assertEqual(pyyaml.fixed_words, "fixed in 5.4")
        self.assertEqual(pyyaml.basis, BASIS_PINNED)
        self.assertEqual(pyyaml.pinned_version, "5.3.1")
        self.assertEqual(pyyaml.state, "open")
        self.assertEqual(pyyaml.snapshot_date, "2026-11-10")
        self.assertEqual(pyyaml.manifest_path, "requirements.txt")
        urllib3 = self._alert_for("CVE-B-0002")
        self.assertEqual(urllib3.basis, BASIS_RANGE)
        self.assertEqual(urllib3.severity, "moderate")
        minimist = self._alert_for("CVE-B-0003")
        self.assertEqual(minimist.severity, "critical")
        jwt = self._alert_for("CVE-B-0005")
        self.assertIsNone(jwt.fixed_version)
        self.assertEqual(jwt.fixed_words, "fix unknown")
        regex = self._alert_for("CVE-B-0006")
        self.assertEqual(regex.basis, BASIS_RANGE)
        # lodash ^4.17.20 does not reach <4.17.19: no alert.
        self.assertEqual(
            self.alerts.count_alerts(
                self.owner, "volmarr", "anvil"), 5)

    def test_refresh_counts_unjudged_out_loud(self):
        self._graphed()
        report = self.alerts.refresh_alerts(
            self.owner, "volmarr", "anvil")
        # The mystery direct-URL dependency names a
        # package with no advisory, so it is not the
        # unjudged one here; urllib3's range is
        # judged. Build a repo whose only advisory
        # package arrives by URL instead.
        self.assertEqual(report.unjudged, 0)
        files = {"requirements.txt":
                 "PyYAML @ https://example.com/PyYAML-5.3.1.tar.gz\n"}
        self._graphed("urlrepo", files)
        report = self.alerts.refresh_alerts(
            self.owner, "volmarr", "urlrepo")
        self.assertEqual(report.unjudged, 1)
        self.assertEqual(report.created, 0)
        self.assertEqual(
            self.alerts.count_alerts(
                self.owner, "volmarr", "urlrepo"), 0)

    def test_refresh_is_idempotent(self):
        self._graphed()
        first = self.alerts.refresh_alerts(
            self.owner, "volmarr", "anvil")
        self.clock.now += 5000
        second = self.alerts.refresh_alerts(
            self.owner, "volmarr", "anvil")
        self.assertEqual(first.created, 5)
        self.assertEqual(second.created, 0)
        self.assertEqual(second.auto_resolved, 0)
        self.assertEqual(second.matches, 5)
        self.assertEqual(
            self.alerts.count_alerts(
                self.owner, "volmarr", "anvil"), 5)

    def test_refresh_auto_resolves_vanished_match_honestly(self):
        work, _tip = self._graphed()
        self.alerts.refresh_alerts(self.owner, "volmarr", "anvil")
        alert = self._alert_for("CVE-B-0001")
        tip = self._push_more(
            work, {"requirements.txt":
                   REQ.replace("PyYAML==5.3.1", "PyYAML==5.4.1")})
        self.graph.graph_tip("volmarr", "anvil", tip)
        report = self.alerts.refresh_alerts(
            self.owner, "volmarr", "anvil")
        self.assertEqual(report.auto_resolved, 1)
        self.assertEqual(report.created, 0)
        done = self.alerts.get_alert(
            self.owner, "volmarr", "anvil", alert.id)
        self.assertEqual(done.state, "resolved")
        self.assertEqual(done.resolution, "fixed")
        self.assertEqual(done.resolved_by, "")
        self.assertIsNone(done.resolved_by_id)
        self.assertIn("automatically by refresh",
                      done.resolution_words())
        events = self.alerts.list_events(
            self.owner, "volmarr", "anvil", alert.id)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "auto_resolve")
        self.assertEqual(events[0].actor_username, "samverk")
        self.assertIsNone(events[0].actor_id)
        self.assertEqual(events[0].role_source, "system")

    def test_refresh_never_moves_a_resolved_alert(self):
        work, _tip = self._graphed()
        self.alerts.refresh_alerts(self.owner, "volmarr", "anvil")
        alert = self._alert_for("CVE-B-0001")
        self.alerts.resolve_alert(
            self.owner, "volmarr", "anvil", alert.id,
            resolution="risk_accepted",
            reason="Internal tool only; risk carried.")
        tip = self._push_more(
            work, {"requirements.txt":
                   REQ.replace("PyYAML==5.3.1", "PyYAML==5.4.1")})
        self.graph.graph_tip("volmarr", "anvil", tip)
        report = self.alerts.refresh_alerts(
            self.owner, "volmarr", "anvil")
        self.assertEqual(report.auto_resolved, 0)
        done = self.alerts.get_alert(
            self.owner, "volmarr", "anvil", alert.id)
        self.assertEqual(done.state, "resolved")
        self.assertEqual(done.resolution, "risk_accepted")
        self.assertEqual(done.resolved_by, "volmarr")
        self.assertEqual(
            len(self.alerts.list_events(
                self.owner, "volmarr", "anvil", alert.id)), 1)

    def test_bundled_snapshot_end_to_end(self):
        store = DependencyAlertStore(
            self.conn, self.repos, self.accounts,
            AdvisoryStore.bundled(now="2026-11-12"),
            time_fn=self.clock)
        self._graphed()
        report = store.refresh_alerts(
            self.owner, "volmarr", "anvil")
        self.assertGreaterEqual(report.created, 4)
        ids = {a.advisory_id for a in store.list_alerts(
            self.owner, "volmarr", "anvil", limit=500)}
        self.assertIn("CVE-2020-14343", ids)   # PyYAML
        self.assertIn("CVE-2021-44906", ids)   # minimist
        self.assertIn("CVE-2020-26160", ids)   # jwt-go, fix unknown

    # -- the lifecycle ------------------------------------------

    def _refreshed_alert(self, advisory_id="CVE-B-0001"):
        self._graphed()
        self.alerts.refresh_alerts(self.owner, "volmarr", "anvil")
        return self._alert_for(advisory_id)

    def test_resolve_records_resolver_and_reason(self):
        alert = self._refreshed_alert()
        before = self._audit_count()
        done = self.alerts.resolve_alert(
            self.owner, "volmarr", "anvil", alert.id,
            resolution="fixed",
            reason="Updated PyYAML past the range.")
        self.assertEqual(done.state, "resolved")
        self.assertEqual(done.resolution, "fixed")
        self.assertEqual(done.resolved_by, "volmarr")
        self.assertEqual(done.resolved_by_id, self.owner.id)
        self.assertEqual(done.resolved_at, T0)
        self.assertEqual(
            done.resolution_reason, "Updated PyYAML past the range.")
        self.assertTrue(done.is_resolved)
        self.assertIn("resolved as fixed by volmarr",
                      done.resolution_words())
        self.assertEqual(self._audit_count(), before)
        events = self.alerts.list_events(
            self.owner, "volmarr", "anvil", alert.id)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "resolve")
        self.assertEqual(events[0].role, "admin")
        self.assertEqual(events[0].from_state, "open")
        self.assertEqual(events[0].to_state, "resolved")

    def test_maintainer_may_resolve_writer_and_reader_may_not(self):
        alert = self._refreshed_alert()
        done = self.alerts.resolve_alert(
            self.maintainer, "volmarr", "anvil", alert.id,
            resolution="false_positive",
            reason="The graph misnames this package.")
        self.assertEqual(done.resolved_by, "yrsa")
        events = self.alerts.list_events(
            self.owner, "volmarr", "anvil", alert.id)
        self.assertEqual(events[0].role, "maintain")
        other = self._alert_for("CVE-B-0002")
        self.assertEqual(
            self._reason(
                self.alerts.resolve_alert, self.writer,
                "volmarr", "anvil", other.id,
                resolution="fixed", reason="Let me."),
            "lifecycle_not_permitted")
        self.assertEqual(
            self._reason(
                self.alerts.reopen_alert, self.reader,
                "volmarr", "anvil", alert.id,
                reason="Let me."),
            "lifecycle_not_permitted")
        self.assertEqual(
            self._reason(
                self.alerts.resolve_alert, None,
                "volmarr", "anvil", other.id,
                resolution="fixed", reason="Anon."),
            "lifecycle_not_permitted")

    def test_reopen_clears_resolution_and_reresolve_stands(self):
        alert = self._refreshed_alert()
        self.alerts.resolve_alert(
            self.owner, "volmarr", "anvil", alert.id,
            resolution="fixed", reason="Updated.")
        back = self.alerts.reopen_alert(
            self.maintainer, "volmarr", "anvil", alert.id,
            reason="The update was reverted.")
        self.assertEqual(back.state, "reopened")
        self.assertEqual(back.resolution, "")
        self.assertEqual(back.resolved_by, "")
        self.assertIsNone(back.resolved_at)
        self.assertIn("reopened", back.resolution_words())
        again = self.alerts.resolve_alert(
            self.owner, "volmarr", "anvil", alert.id,
            resolution="risk_accepted",
            reason="Pinned by a vendor tool; carried.")
        self.assertEqual(again.state, "resolved")
        self.assertEqual(again.resolution, "risk_accepted")
        events = self.alerts.list_events(
            self.owner, "volmarr", "anvil", alert.id)
        self.assertEqual([e.action for e in events],
                         ["resolve", "reopen", "resolve"])

    def test_lifecycle_refusals_are_named(self):
        alert = self._refreshed_alert()
        self.assertEqual(
            self._reason(
                self.alerts.resolve_alert, self.owner,
                "volmarr", "anvil", alert.id,
                resolution="revoked", reason="Wrong shelf."),
            "resolution_invalid")
        self.assertEqual(
            self._reason(
                self.alerts.resolve_alert, self.owner,
                "volmarr", "anvil", alert.id,
                resolution="fixed", reason="  "),
            "reason_required")
        self.assertEqual(
            self._reason(
                self.alerts.resolve_alert, self.owner,
                "volmarr", "anvil", alert.id,
                resolution="fixed", reason="x" * 501),
            "reason_too_long")
        self.assertEqual(
            self._reason(
                self.alerts.reopen_alert, self.owner,
                "volmarr", "anvil", alert.id, reason="Early."),
            "alert_not_resolved")
        self.assertEqual(
            self._reason(
                self.alerts.get_alert, self.owner,
                "volmarr", "anvil", 99999),
            "alert_not_found")
        self.alerts.resolve_alert(
            self.owner, "volmarr", "anvil", alert.id,
            resolution="fixed", reason="Updated.")
        self.assertEqual(
            self._reason(
                self.alerts.resolve_alert, self.owner,
                "volmarr", "anvil", alert.id,
                resolution="fixed", reason="Again."),
            "alert_already_resolved")

    def test_judge_is_pure(self):
        alert = self._refreshed_alert()
        decision = self.alerts.judge(
            self.writer, "volmarr", "anvil", alert.id,
            action="resolve", resolution="fixed",
            reason="Checking only.")
        self.assertFalse(decision.may_move)
        self.assertEqual(decision.code, "lifecycle_not_permitted")
        standing = self.alerts.get_alert(
            self.owner, "volmarr", "anvil", alert.id)
        self.assertEqual(standing.state, "open")
        self.assertEqual(
            self.alerts.list_events(
                self.owner, "volmarr", "anvil", alert.id), ())

    # -- reads ----------------------------------------------------

    def test_reads_follow_the_repository(self):
        self._graphed("priv", visibility="private")
        self.alerts.refresh_alerts(self.owner, "volmarr", "priv")
        self.assertEqual(
            self.alerts.count_alerts(
                self.reader, "volmarr", "priv"), 5)
        self.assertEqual(
            self._reason(
                self.alerts.list_alerts, self.stranger,
                "volmarr", "priv"),
            "repo_not_found")
        self.assertEqual(
            self._reason(
                self.alerts.list_alerts, None,
                "volmarr", "priv"),
            "repo_not_found")
        self.assertEqual(
            self._reason(
                self.alerts.list_alerts, self.owner,
                "volmarr", "ghost"),
            "repo_not_found")

    def test_filters_and_severity_counts(self):
        self._refreshed_alert()
        self.assertEqual(
            self.alerts.count_alerts(
                self.owner, "volmarr", "anvil",
                severity="critical"), 1)
        counts = self.alerts.counts_by_severity(
            self.owner, "volmarr", "anvil")
        self.assertEqual(
            counts, {"critical": 1, "high": 2,
                     "moderate": 1, "low": 1})
        live = self.alerts.list_alerts(
            self.owner, "volmarr", "anvil", state="open")
        self.assertEqual(len(live), 5)
        self.assertEqual(live[0].severity, "critical")
        self.assertEqual(
            self._reason(
                self.alerts.list_alerts, self.owner,
                "volmarr", "anvil", state="limbo"),
            "state_invalid")
        self.assertEqual(
            self._reason(
                self.alerts.list_alerts, self.owner,
                "volmarr", "anvil", severity="severe"),
            "severity_invalid")

    def test_pages_carry_banner_age_and_escape(self):
        alert = self._refreshed_alert("CVE-B-0005")
        info = self.alerts.snapshot_info(now="2026-11-12")
        page = render_alert_page(alert, (), info)
        self.assertIn("2026-11-10", page)
        self.assertIn("2 days old", page)
        self.assertIn("fix unknown", page)
        self.assertIn("CVE-B-0005", page)
        self.assertNotIn("<b>no fix</b>", page)
        self.assertIn("&lt;b&gt;no fix&lt;/b&gt;", page)
        listing = render_alerts_page(
            self.alerts.list_alerts(
                self.owner, "volmarr", "anvil"),
            "volmarr/anvil", info)
        self.assertIn("Dependency alerts", listing)
        self.assertIn("minimist", listing)
        self.assertIn("critical", listing)


if __name__ == "__main__":
    unittest.main()
