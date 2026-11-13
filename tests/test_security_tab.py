"""S-307 acceptance battery: security tab.

Acceptance (roadmap S-307): Security tab --
per-repo home for secret/dependency/code-scanning
alerts with counts and states (the surface
S-297--S-304 report into).

The centre is samverk/security_tab.py: one gathered
read over the three families' standing rows --
secret alerts in their S-294 lifecycle states,
dependency alerts in theirs plus live counts by
severity (the shape S-299 promised this tab),
code-scanning alerts in S-304's effective states
(dismissed while a dismissal stands, else the
scanner state) plus live counts by SARIF level --
behind the S-054 `can_read` display door (a
stranger to a private repository gets the uniform
repo_not_found), with the advisory snapshot's age
standing on the tab under S-298's law, the recent
alerts shown in their non-secret faces only, and
audit_security_tab re-proving the rows the tab
counts. No migration (schema 127 stands); taxonomy
unmoved at 135 (33 auth / 89 repo / 13 admin) -- a
gathered read emits no event, and the battery
proves the audit log does not move.

The families' rows are seeded directly: this
surface judges no alert, so its battery stands the
rows the families' own batteries prove those
stores write, and judges the gathering.

Counted with: python3 -m unittest tests.test_security_tab
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.advisory_data import AdvisoryStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.repositories import RepositoryStore
from samverk.security_tab import (
    FamilySummary, SecurityTabError, SecurityTabStore,
    audit_security_tab, decide_family_standing,
    decide_headline, render_security_tab_page,
    security_tab_to_dict)

PW = "correct horse battery"
T0 = 1_700_000_000

SNAPSHOT = """
{
  "snapshot_format": 1,
  "source": "S-307 battery snapshot (hand-built)",
  "snapshot_date": "2023-11-10",
  "advisories": [
    {"id": "CVE-T-0001", "ecosystem": "python",
     "package": "PyYAML", "severity": "high",
     "affected": "<5.4", "fixed_version": "5.4",
     "summary": "PyYAML loads arbitrary objects.",
     "published": "2020-07-27", "references": []}
  ]
}
"""

STALE_SNAPSHOT = SNAPSHOT.replace(
    '"snapshot_date": "2023-11-10"',
    '"snapshot_date": "2023-09-01"')

PLANTED_SECRET = "ghp_PLANTEDSECRETVALUE1234567890"


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class PureLawTests(unittest.TestCase):
    def test_family_standing(self):
        self.assertEqual(decide_family_standing(0, 0), "clear")
        self.assertEqual(decide_family_standing(3, 0), "answered")
        self.assertEqual(decide_family_standing(3, 1), "open")
        self.assertEqual(decide_family_standing(3, 3), "open")

    def test_family_standing_refuses_impossible_counts(self):
        for total, live in ((2, 3), (-1, 0), (1, -1)):
            with self.assertRaises(SecurityTabError) as ctx:
                decide_family_standing(total, live)
            self.assertEqual(ctx.exception.reason, "counts_invalid")
        with self.assertRaises(SecurityTabError) as ctx:
            decide_family_standing("many", 0)
        self.assertEqual(ctx.exception.reason, "counts_invalid")

    def test_headline(self):
        self.assertEqual(decide_headline(0, 0, 0), (0, ""))
        self.assertEqual(
            decide_headline(2, 5, 1), (8, "dependency"))
        self.assertEqual(
            decide_headline(0, 0, 4), (4, "code_scanning"))
        # Ties break in tab order: secret, dependency, code.
        self.assertEqual(decide_headline(3, 3, 2), (8, "secret"))
        self.assertEqual(
            decide_headline(0, 2, 2), (4, "dependency"))

    def test_family_words_say_the_position(self):
        summary = FamilySummary(
            family="dependency", total=5, live=3,
            by_state={"open": 2, "reopened": 1, "resolved": 2},
            by_severity={"critical": 1, "high": 2,
                         "moderate": 0, "low": 0},
            by_level={}, unrecognised=0)
        words = summary.words()
        self.assertIn("3 of 5", words)
        self.assertIn("2 open", words)
        self.assertIn("1 reopened", words)
        self.assertIn("Live by severity: 1 critical, 2 high", words)
        clear = FamilySummary(
            family="secret", total=0, live=0,
            by_state={"open": 0, "reopened": 0, "resolved": 0},
            by_severity={}, by_level={}, unrecognised=0)
        self.assertEqual(clear.standing, "clear")
        self.assertIn("No secret scanning alerts stand",
                      clear.words())


# --- seeding: the rows the families' stores write ----------------

def seed_secret(conn, repo_id, n, state, *, path=None,
                detector="github_pat", resolution="",
                resolved_at=None, redacted="ghp_...1234"):
    conn.execute(
        "INSERT INTO secret_alerts (repo_id, scan_id,"
        " commit_oid, path, blob_oid, source, detector_id,"
        " line, column, redacted, fingerprint, state,"
        " created_at, resolution, resolved_by_id,"
        " resolved_by, resolved_at, resolution_reason)"
        " VALUES (?, 1, ?, ?, ?, 'push', ?, 1, 1, ?, ?, ?,"
        " ?, ?, ?, ?, ?, ?)",
        (repo_id, "a" * 40, path or f"src/file{n}.py",
         "b" * 40, detector, redacted, f"fp-secret-{n}",
         state, T0 + n, resolution,
         1 if resolved_at else None,
         "volmarr" if resolved_at else "",
         resolved_at, "seeded" if resolved_at else ""))
    return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def seed_dependency(conn, repo_id, n, state, severity, *,
                    resolution="", resolved_at=None):
    conn.execute(
        "INSERT INTO dependency_alerts (repo_id,"
        " dependency_id, ecosystem, dependency_name,"
        " name_key, manifest_path, specifier, basis,"
        " pinned_version, advisory_id, severity, affected,"
        " fixed_version, summary, snapshot_date, state,"
        " created_at, updated_at, resolution,"
        " resolved_by_id, resolved_by, resolved_at,"
        " resolution_reason) VALUES (?, NULL, 'python',"
        " ?, ?, 'requirements.txt', '==1.0', 'pinned',"
        " '1.0', ?, ?, '<2.0', '2.0', 'seeded summary',"
        " '2023-11-10', ?, ?, ?, ?, ?, ?, ?, ?)",
        (repo_id, f"pkg{n}", f"pkg{n}", f"CVE-T-{n:04d}",
         severity, state, T0 + n, T0 + n, resolution,
         1 if resolved_at else None,
         "volmarr" if resolved_at else "",
         resolved_at, "seeded" if resolved_at else ""))
    return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def seed_code(conn, repo_id, n, state, level, *,
              dismissed=False, rule="CQ-1"):
    conn.execute(
        "INSERT INTO code_scanning_alerts (repo_id, branch,"
        " fingerprint, basis, tool_name, rule_id, level,"
        " message, artifact_uri, start_line, start_column,"
        " state, first_seen_upload_id, first_seen_oid,"
        " last_seen_upload_id, last_seen_oid,"
        " fixed_upload_id, fixed_oid, times_seen,"
        " times_fixed, created_at, updated_at, dismissal,"
        " dismissed_by_id, dismissed_by, dismissed_at,"
        " dismissal_reason) VALUES (?, 'main', ?, 'fingerprint',"
        " 'CodeQL', ?, ?, 'a finding', 'src/main.py', 3, 1,"
        " ?, 1, ?, 1, ?, NULL, '', 1, 0, ?, ?, ?, ?, ?, ?, ?)",
        (repo_id, f"fp-code-{n}", rule, level, state,
         "a" * 40, "a" * 40, T0 + n, T0 + n,
         "wont_fix" if dismissed else "",
         1 if dismissed else None,
         "volmarr" if dismissed else "",
         T0 + n if dismissed else None,
         "seeded reason" if dismissed else ""))
    return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def seed_standing_world(conn, repo_id):
    """The standing world most tests read: secret
    5 (3 live), dependency 5 (3 live), code 4 (2 live)."""
    seed_secret(conn, repo_id, 1, "open")
    seed_secret(conn, repo_id, 2, "open")
    seed_secret(conn, repo_id, 3, "reopened")
    seed_secret(conn, repo_id, 4, "resolved",
                resolution="revoked", resolved_at=T0)
    seed_secret(conn, repo_id, 5, "resolved",
                resolution="false_positive", resolved_at=T0)
    seed_dependency(conn, repo_id, 1, "open", "critical")
    seed_dependency(conn, repo_id, 2, "open", "high")
    seed_dependency(conn, repo_id, 3, "reopened", "high")
    seed_dependency(conn, repo_id, 4, "resolved", "moderate",
                    resolution="fixed", resolved_at=T0)
    seed_dependency(conn, repo_id, 5, "resolved", "critical",
                    resolution="risk_accepted", resolved_at=T0)
    seed_code(conn, repo_id, 1, "open", "error")
    seed_code(conn, repo_id, 2, "open", "error")
    seed_code(conn, repo_id, 3, "fixed", "warning")
    seed_code(conn, repo_id, 4, "open", "note", dismissed=True)
    conn.commit()


class SecurityTabTests(unittest.TestCase):
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
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.pub = self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.priv = self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.advisories = AdvisoryStore.from_text(
            SNAPSHOT, now=T0)
        self.tab = SecurityTabStore(
            self.conn, self.repos, self.accounts,
            advisories=self.advisories, time_fn=self.clock)

    # -- counts and states ------------------------------------------

    def test_counts_and_states(self):
        seed_standing_world(self.conn, self.pub.id)
        tab = self.tab.security_tab(self.owner, "volmarr", "pub")
        self.assertEqual(tab.full_name, "volmarr/pub")
        secret = tab.family("secret")
        self.assertEqual(secret.total, 5)
        self.assertEqual(secret.live, 3)
        self.assertEqual(
            secret.by_state,
            {"open": 2, "reopened": 1, "resolved": 2})
        self.assertEqual(secret.standing, "open")
        self.assertEqual(secret.unrecognised, 0)
        dep = tab.family("dependency")
        self.assertEqual(dep.total, 5)
        self.assertEqual(dep.live, 3)
        self.assertEqual(
            dep.by_state,
            {"open": 2, "reopened": 1, "resolved": 2})
        code = tab.family("code_scanning")
        self.assertEqual(code.total, 4)
        self.assertEqual(code.live, 2)
        self.assertEqual(
            code.by_state,
            {"open": 2, "fixed": 1, "dismissed": 1})
        self.assertEqual(tab.open_total, 8)
        self.assertEqual(tab.total, 14)
        self.assertEqual(tab.lead_family, "secret")
        self.assertIn("8 security alerts stand open",
                      tab.headline_words)

    def test_dependency_severity_counts_live_only(self):
        seed_standing_world(self.conn, self.pub.id)
        dep = self.tab.security_tab(
            self.owner, "volmarr", "pub").family("dependency")
        # The resolved critical alert (risk accepted) is
        # answered: it must not stand in the live counts.
        self.assertEqual(
            dep.by_severity,
            {"critical": 1, "high": 2, "moderate": 0, "low": 0})

    def test_code_levels_count_live_only(self):
        seed_standing_world(self.conn, self.pub.id)
        code = self.tab.security_tab(
            self.owner, "volmarr", "pub").family("code_scanning")
        # The fixed warning and the dismissed note are not
        # live; only the two open errors stand by level.
        self.assertEqual(
            code.by_level,
            {"error": 2, "warning": 0, "note": 0, "none": 0})

    def test_dismissed_counts_once_as_dismissed(self):
        seed_standing_world(self.conn, self.pub.id)
        code = self.tab.security_tab(
            self.owner, "volmarr", "pub").family("code_scanning")
        self.assertEqual(code.by_state["dismissed"], 1)
        self.assertEqual(code.by_state["open"], 2)
        self.assertEqual(
            sum(code.by_state.values()), code.total)

    def test_counts_method(self):
        seed_standing_world(self.conn, self.pub.id)
        counts = self.tab.counts(self.owner, "volmarr", "pub")
        self.assertEqual(
            set(counts), {"secret", "dependency", "code_scanning"})
        self.assertEqual(counts["secret"]["live"], 3)
        self.assertEqual(counts["secret"]["total"], 5)
        self.assertEqual(counts["code_scanning"]["standing"], "open")
        self.assertEqual(
            counts["dependency"]["by_severity"]["high"], 2)

    def test_empty_repository_stands_clear(self):
        tab = self.tab.security_tab(self.owner, "volmarr", "pub")
        self.assertEqual(tab.total, 0)
        self.assertEqual(tab.open_total, 0)
        self.assertEqual(tab.lead_family, "")
        for family in tab.families:
            self.assertEqual(family.standing, "clear")
        self.assertIn("No security alerts stand in volmarr/pub",
                      tab.headline_words)

    def test_answered_repository(self):
        seed_secret(self.conn, self.pub.id, 1, "resolved",
                    resolution="revoked", resolved_at=T0)
        seed_dependency(self.conn, self.pub.id, 1, "resolved",
                        "low", resolution="fixed", resolved_at=T0)
        seed_code(self.conn, self.pub.id, 1, "fixed", "warning")
        self.conn.commit()
        tab = self.tab.security_tab(self.owner, "volmarr", "pub")
        self.assertEqual(tab.open_total, 0)
        self.assertEqual(tab.total, 3)
        for family in tab.families:
            self.assertEqual(family.standing, "answered")
        self.assertIn("stand answered", tab.headline_words)

    # -- the door ------------------------------------------------------

    def test_private_repo_stranger_gets_repo_not_found(self):
        seed_standing_world(self.conn, self.priv.id)
        for viewer in (self.stranger, None):
            with self.assertRaises(SecurityTabError) as ctx:
                self.tab.security_tab(viewer, "volmarr", "priv")
            self.assertEqual(ctx.exception.reason, "repo_not_found")
        tab = self.tab.security_tab(self.owner, "volmarr", "priv")
        self.assertEqual(tab.total, 14)

    def test_public_repo_readable_by_anyone(self):
        seed_standing_world(self.conn, self.pub.id)
        for viewer in (self.stranger, None, self.owner):
            tab = self.tab.security_tab(viewer, "volmarr", "pub")
            self.assertEqual(tab.open_total, 8)

    def test_missing_repo_is_repo_not_found(self):
        with self.assertRaises(SecurityTabError) as ctx:
            self.tab.security_tab(self.owner, "volmarr", "nope")
        self.assertEqual(ctx.exception.reason, "repo_not_found")

    # -- the snapshot's age ---------------------------------------------

    def test_snapshot_age_stands_on_the_tab(self):
        tab = self.tab.security_tab(self.owner, "volmarr", "pub")
        self.assertEqual(tab.snapshot.freshness, "current")
        self.assertEqual(tab.snapshot.age_days, 4)
        self.assertIn("2023-11-10", tab.snapshot.age_words)
        page = render_security_tab_page(tab)
        self.assertIn("2023-11-10", page)
        self.assertIn("advisory snapshot dated", page)

    def test_stale_snapshot_says_stale(self):
        stale = SecurityTabStore(
            self.conn, self.repos, self.accounts,
            advisories=AdvisoryStore.from_text(
                STALE_SNAPSHOT, now=T0),
            time_fn=self.clock)
        tab = stale.security_tab(self.owner, "volmarr", "pub")
        self.assertEqual(tab.snapshot.freshness, "stale")
        self.assertIn("stale", tab.snapshot.age_words)
        self.assertIn("stale", render_security_tab_page(tab))

    def test_bundled_snapshot_at_an_old_clock_is_unknown(self):
        # The bundled snapshot is dated long after this
        # battery's clock: no honest age exists, and the
        # tab says unknown rather than dressing it fresh.
        default = SecurityTabStore(
            self.conn, self.repos, self.accounts,
            time_fn=self.clock)
        tab = default.security_tab(self.owner, "volmarr", "pub")
        self.assertEqual(tab.snapshot.freshness, "unknown")
        self.assertEqual(tab.snapshot.age_words,
                         "advisory snapshot age unknown")

    # -- recent alerts: non-secret faces only ----------------------------

    def test_recent_alerts_and_no_secret_text(self):
        seed_secret(self.conn, self.pub.id, 1, "open",
                    path="src/keys.py", redacted=PLANTED_SECRET)
        seed_dependency(self.conn, self.pub.id, 1, "open", "high")
        seed_code(self.conn, self.pub.id, 1, "open", "error")
        self.conn.commit()
        tab = self.tab.security_tab(self.owner, "volmarr", "pub")
        self.assertEqual(len(tab.recent), 3)
        secret = [r for r in tab.recent if r.family == "secret"][0]
        self.assertEqual(secret.title, "src/keys.py")
        self.assertIn("github_pat", secret.detail)
        page = render_security_tab_page(tab)
        blob = page + json.dumps(security_tab_to_dict(tab))
        self.assertNotIn(PLANTED_SECRET, blob)
        self.assertNotIn("ghp_", blob)

    def test_recent_limit_clamps_per_family(self):
        seed_standing_world(self.conn, self.pub.id)
        tab = self.tab.security_tab(
            self.owner, "volmarr", "pub", recent_limit=2)
        self.assertEqual(len(tab.recent), 6)
        tab = self.tab.security_tab(
            self.owner, "volmarr", "pub", recent_limit=0)
        self.assertEqual(tab.recent, ())
        tab = self.tab.security_tab(self.owner, "volmarr", "pub")
        self.assertEqual(len(tab.recent), 14)

    def test_render_escapes_stored_text(self):
        seed_secret(self.conn, self.pub.id, 1, "open",
                    path="src/<script>alert(1)</script>.py")
        seed_code(self.conn, self.pub.id, 1, "open", "error",
                  rule='CQ-<b onmouseover="x">')
        self.conn.commit()
        page = render_security_tab_page(
            self.tab.security_tab(self.owner, "volmarr", "pub"))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn('<b onmouseover="x">', page)
        self.assertIn("CQ-&lt;b", page)

    def test_to_dict_shape(self):
        seed_standing_world(self.conn, self.pub.id)
        data = security_tab_to_dict(
            self.tab.security_tab(self.owner, "volmarr", "pub"))
        self.assertEqual(data["repository"], "volmarr/pub")
        self.assertEqual(data["open_total"], 8)
        self.assertEqual(data["total"], 14)
        self.assertEqual(data["lead_family"], "secret")
        self.assertEqual(
            [f["family"] for f in data["families"]],
            ["secret", "dependency", "code_scanning"])
        self.assertEqual(
            data["advisory_snapshot"]["snapshot_date"],
            "2023-11-10")
        json.dumps(data)  # the whole shape is data, serialisable

    # -- unrecognised values and the audit re-proof ----------------------

    def test_unrecognised_state_named_not_folded(self):
        seed_secret(self.conn, self.pub.id, 1, "open")
        seed_secret(self.conn, self.pub.id, 2, "weird-state")
        self.conn.commit()
        secret = self.tab.security_tab(
            self.owner, "volmarr", "pub").family("secret")
        self.assertEqual(secret.total, 2)
        self.assertEqual(secret.live, 1)
        self.assertEqual(secret.unrecognised, 1)
        self.assertEqual(secret.by_state["open"], 1)
        self.assertIn("outside this family's vocabulary",
                      secret.words())

    def test_audit_clean_world(self):
        seed_standing_world(self.conn, self.pub.id)
        seed_standing_world(self.conn, self.priv.id)
        self.assertEqual(audit_security_tab(self.conn), [])

    def test_audit_flags_corrupt_rows(self):
        repo = self.pub.id
        seed_secret(self.conn, repo, 1, "resolved",
                    resolution="revoked", resolved_at=None)
        seed_dependency(self.conn, repo, 1, "open", "dire")
        seed_code(self.conn, repo, 1, "open", "error",
                  dismissed=True)
        # A dismissal with its reason blanked cannot stand.
        self.conn.execute(
            "UPDATE code_scanning_alerts SET dismissal_reason = ''")
        seed_secret(self.conn, 99999, 9, "open")
        self.conn.commit()
        problems = audit_security_tab(self.conn)
        text = "\n".join(problems)
        self.assertIn("no resolution time", text)
        self.assertIn("'dire'", text)
        self.assertIn("no dismisser or no stated reason", text)
        self.assertIn("does not stand", text)
        self.assertGreaterEqual(len(problems), 4)

    # -- honesty pins -------------------------------------------------------

    def test_read_moves_no_audit_log(self):
        seed_standing_world(self.conn, self.pub.id)
        before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        tab = self.tab.security_tab(self.owner, "volmarr", "pub")
        render_security_tab_page(tab)
        self.tab.counts(self.owner, "volmarr", "pub")
        after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.assertEqual(before, after)

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 127)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)


if __name__ == "__main__":
    unittest.main()
