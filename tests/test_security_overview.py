"""S-308 acceptance battery: security overview.

Acceptance (roadmap S-308): Security overview --
org/instance rollup: open alerts by severity and
repos affected; counts only, no code content
(safe for wider admin read).

The centre is samverk/security_overview.py: one
gathered live read over the three families'
standing rows across a scope of repositories --
secret and dependency alerts live in open +
reopened, code-scanning alerts live in S-304's
effective open, dependency live counts by
severity, code live counts by SARIF level, secret
live as its own family total, each vocabulary
kept its own -- with distinct repos affected
overall and per family, behind the two doors the
slice decides (org rollup for org members/owners
and site admins, uniform org_not_found otherwise;
instance rollup for site admins only, uniform
overview_not_found otherwise), repository names
shown only where S-054's can_read opens them, the
advisory snapshot's age standing on the page
under S-298's law, and
audit_security_overview re-proving the rows the
rollup counts. No migration (schema 127 stands);
taxonomy unmoved at 135 (33 auth / 89 repo / 13
admin) -- a gathered read emits no event, and the
battery proves the audit log does not move and
the read writes nothing, not even a membership
seed.

The families' rows are seeded directly: this
surface judges no alert, so its battery stands
the rows the families' own batteries prove those
stores write, and judges the gathering.

Counted with: python3 -m unittest tests.test_security_overview
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
from samverk.org_repositories import OrgRepoStore
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import OrganizationStore
from samverk.repositories import RepositoryStore
from samverk.security_overview import (
    FamilyRollup, SecurityOverviewError, SecurityOverviewStore,
    audit_security_overview, decide_overview_standing,
    render_security_overview_page, security_overview_to_dict)

PW = "correct horse battery"
T0 = 1_700_000_000

SNAPSHOT = """
{
  "snapshot_format": 1,
  "source": "S-308 battery snapshot (hand-built)",
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
PLANTED_CODE = "PLANTED finding body with code content"


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class PureLawTests(unittest.TestCase):
    def test_standing(self):
        self.assertEqual(decide_overview_standing(0), "clear")
        self.assertEqual(decide_overview_standing(1), "open")
        self.assertEqual(decide_overview_standing(9), "open")

    def test_standing_refuses_impossible_counts(self):
        for bad in (-1, "many", None):
            with self.assertRaises(SecurityOverviewError) as ctx:
                decide_overview_standing(bad)
            self.assertEqual(ctx.exception.reason, "counts_invalid")

    def test_family_words_say_the_position(self):
        rollup = FamilyRollup(
            family="dependency", live=3, repos_affected=2,
            by_severity={"critical": 1, "high": 2,
                         "moderate": 0, "low": 0},
            by_level={}, unrecognised=0)
        words = rollup.words()
        self.assertIn("3 dependency alerts stand open", words)
        self.assertIn("across 2 repositories", words)
        self.assertIn("Open by severity: 1 critical, 2 high", words)
        self.assertEqual(rollup.standing, "open")
        clear = FamilyRollup(
            family="secret", live=0, repos_affected=0,
            by_severity={}, by_level={}, unrecognised=0)
        self.assertEqual(clear.standing, "clear")
        self.assertIn("No secret scanning alerts stand open",
                      clear.words())


# --- seeding: the rows the families' stores write ----------------

def seed_secret(conn, repo_id, n, state, *, resolution="",
                resolved_at=None, redacted="ghp_...1234"):
    conn.execute(
        "INSERT INTO secret_alerts (repo_id, scan_id,"
        " commit_oid, path, blob_oid, source, detector_id,"
        " line, column, redacted, fingerprint, state,"
        " created_at, resolution, resolved_by_id,"
        " resolved_by, resolved_at, resolution_reason)"
        " VALUES (?, 1, ?, ?, ?, 'push', ?, 1, 1, ?, ?, ?,"
        " ?, ?, ?, ?, ?, ?)",
        (repo_id, "a" * 40, f"src/file{n}.py",
         "b" * 40, "github_pat", redacted, f"fp-secret-{n}",
         state, T0 + n, resolution,
         1 if resolved_at else None,
         "volmarr" if resolved_at else "",
         resolved_at, "seeded" if resolved_at else ""))


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


def seed_code(conn, repo_id, n, state, level, *, dismissed=False):
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
        " 'CodeQL', 'CQ-1', ?, 'a finding', 'src/main.py', 3, 1,"
        " ?, 1, ?, 1, ?, NULL, '', 1, 0, ?, ?, ?, ?, ?, ?, ?)",
        (repo_id, f"fp-code-{n}", level, state,
         "a" * 40, "a" * 40, T0 + n, T0 + n,
         "wont_fix" if dismissed else "",
         1 if dismissed else None,
         "volmarr" if dismissed else "",
         T0 + n if dismissed else None,
         "seeded reason" if dismissed else ""))


class SecurityOverviewTests(unittest.TestCase):
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
        self.creator = self.accounts.register("volmarr", PW)
        self.member = self.accounts.register("yrsa", PW)
        self.stranger = self.accounts.register("mallory", PW)
        admin = self.accounts.register("sitemod", PW)
        with self.conn:
            self.conn.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?",
                (admin.id,))
        self.admin = self.accounts.get_by_id(admin.id)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.orgs = OrganizationStore(
            self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.org = self.orgs.create_organization(
            self.creator.id, "crew")
        self.empty_org = self.orgs.create_organization(
            self.creator.id, "emptyorg")
        self.members = OrgMembershipStore(
            self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.members.add_member(
            self.creator.id, self.org.id, self.member.id)
        self.org_repos = OrgRepoStore(
            self.conn, self.accounts, self.root, self.audit,
            time_fn=self.clock)
        self.alpha = self.org_repos.create_repository(
            self.creator.id, self.org.id, "alpha",
            visibility="public")
        self.beta = self.org_repos.create_repository(
            self.creator.id, self.org.id, "beta",
            visibility="private")
        self.solo = self.repos.create_repository(
            self.creator.id, "volmarr", "solo",
            visibility="public")
        self.advisories = AdvisoryStore.from_text(SNAPSHOT, now=T0)
        self.overview = SecurityOverviewStore(
            self.conn, self.repos, self.accounts,
            advisories=self.advisories, time_fn=self.clock)

    def seed_world(self):
        """Org estate: alpha (public) carries live
        secret 1, dependency 2, code 1; beta
        (private) carries live secret 1 and only
        answered alerts otherwise. Solo (personal,
        outside the org) carries live dependency 1
        and code 1."""
        seed_secret(self.conn, self.alpha.id, 101, "open")
        seed_dependency(self.conn, self.alpha.id, 101, "open", "critical")
        seed_dependency(self.conn, self.alpha.id, 102, "reopened", "high")
        seed_code(self.conn, self.alpha.id, 101, "open", "error")
        seed_secret(self.conn, self.beta.id, 201, "open")
        seed_secret(self.conn, self.beta.id, 202, "resolved",
                    resolution="revoked", resolved_at=T0)
        seed_dependency(self.conn, self.beta.id, 201, "resolved",
                        "moderate", resolution="fixed",
                        resolved_at=T0)
        seed_code(self.conn, self.beta.id, 201, "fixed", "warning")
        seed_code(self.conn, self.beta.id, 202, "open", "note",
                  dismissed=True)
        seed_dependency(self.conn, self.solo.id, 301, "open", "low")
        seed_code(self.conn, self.solo.id, 301, "open", "warning")
        self.conn.commit()

    # -- scope and counts -------------------------------------------

    def test_org_rollup_counts(self):
        self.seed_world()
        ov = self.overview.org_overview(self.member, "crew")
        self.assertEqual(ov.scope, "org")
        self.assertEqual(ov.scope_name, "crew")
        secret = ov.family("secret")
        self.assertEqual(secret.live, 2)
        self.assertEqual(secret.repos_affected, 2)
        dep = ov.family("dependency")
        self.assertEqual(dep.live, 2)
        self.assertEqual(dep.repos_affected, 1)
        code = ov.family("code_scanning")
        self.assertEqual(code.live, 1)
        self.assertEqual(code.repos_affected, 1)
        self.assertEqual(ov.open_total, 5)
        self.assertEqual(ov.standing, "open")
        # Alpha carries live alerts in all three families
        # yet counts once overall.
        self.assertEqual(ov.repos_affected, 2)
        self.assertIn("5 security alerts stand open",
                      ov.headline_words)

    def test_org_severity_buckets(self):
        self.seed_world()
        dep = self.overview.org_overview(
            self.member, "crew").family("dependency")
        self.assertEqual(
            dep.by_severity,
            {"critical": 1, "high": 1, "moderate": 0, "low": 0})
        # Solo's live low alert stands outside the org scope.
        self.assertEqual(dep.by_severity["low"], 0)
        # The secret family keeps no severity vocabulary:
        # its severity is its live total, in its own field.
        secret = self.overview.org_overview(
            self.member, "crew").family("secret")
        self.assertEqual(secret.by_severity, {})
        self.assertEqual(secret.by_level, {})
        self.assertEqual(secret.live, 2)

    def test_org_code_levels(self):
        self.seed_world()
        code = self.overview.org_overview(
            self.member, "crew").family("code_scanning")
        self.assertEqual(
            code.by_level,
            {"error": 1, "warning": 0, "note": 0, "none": 0})
        self.assertEqual(code.by_severity, {})

    def test_answered_alerts_never_count_live(self):
        self.seed_world()
        ov = self.overview.org_overview(self.member, "crew")
        # Beta's resolved secret, resolved dependency,
        # fixed code alert and dismissed code alert are
        # all answered: beta is affected only by its one
        # live secret alert.
        self.assertEqual(ov.family("secret").live, 2)
        self.assertEqual(ov.family("dependency").live, 2)
        self.assertEqual(ov.family("code_scanning").live, 1)
        beta_only = self.overview.org_overview(self.admin, "crew")
        self.assertEqual(beta_only.repos_affected, 2)

    def test_instance_rollup_covers_every_repository(self):
        self.seed_world()
        ov = self.overview.instance_overview(self.admin)
        self.assertEqual(ov.scope, "instance")
        self.assertEqual(ov.family("secret").live, 2)
        dep = ov.family("dependency")
        self.assertEqual(dep.live, 3)
        self.assertEqual(dep.by_severity["low"], 1)
        self.assertEqual(dep.repos_affected, 2)
        code = ov.family("code_scanning")
        self.assertEqual(code.live, 2)
        self.assertEqual(code.by_level["warning"], 1)
        self.assertEqual(code.repos_affected, 2)
        self.assertEqual(ov.open_total, 7)
        self.assertEqual(ov.repos_affected, 3)
        self.assertEqual(ov.lead_family, "dependency")

    def test_empty_org_stands_clear(self):
        ov = self.overview.org_overview(self.creator, "emptyorg")
        self.assertEqual(ov.open_total, 0)
        self.assertEqual(ov.repos_affected, 0)
        self.assertEqual(ov.standing, "clear")
        self.assertEqual(ov.named_repos, ())
        for family in ov.families:
            self.assertEqual(family.standing, "clear")
            self.assertEqual(family.live, 0)
        self.assertIn("No security alerts stand open",
                      ov.headline_words)

    # -- the doors ----------------------------------------------------

    def test_org_door_members_owners_admins(self):
        self.seed_world()
        for viewer in (self.member, self.creator, self.admin):
            ov = self.overview.org_overview(viewer, "crew")
            self.assertEqual(ov.open_total, 5)
        # Org names resolve case-insensitively, as everywhere.
        ov = self.overview.org_overview(self.member, "CREW")
        self.assertEqual(ov.open_total, 5)

    def test_org_door_refusals_are_uniform_not_found(self):
        self.seed_world()
        for viewer in (self.stranger, None):
            with self.assertRaises(SecurityOverviewError) as ctx:
                self.overview.org_overview(viewer, "crew")
            self.assertEqual(ctx.exception.reason, "org_not_found")
        # A missing organization hears exactly the same answer,
        # from a member and from a stranger alike.
        for viewer in (self.member, self.stranger, self.admin):
            with self.assertRaises(SecurityOverviewError) as ctx:
                self.overview.org_overview(viewer, "nope")
            self.assertEqual(ctx.exception.reason, "org_not_found")

    def test_instance_door_is_site_admins_only(self):
        self.seed_world()
        for viewer in (self.creator, self.member,
                       self.stranger, None):
            with self.assertRaises(SecurityOverviewError) as ctx:
                self.overview.instance_overview(viewer)
            self.assertEqual(
                ctx.exception.reason, "overview_not_found")
        ov = self.overview.instance_overview(self.admin)
        self.assertEqual(ov.open_total, 7)

    # -- naming under S-054 --------------------------------------------

    def test_named_repos_follow_can_read(self):
        self.seed_world()
        ov = self.overview.org_overview(self.member, "crew")
        # Alpha is public: named. Beta is private and S-054
        # does not open it to a plain org member: counted
        # in every number, never named.
        self.assertEqual(ov.named_repos, ("crew/alpha",))
        self.assertEqual(ov.hidden_repos_affected, 1)
        self.assertEqual(ov.repos_affected, 2)
        page = render_security_overview_page(ov)
        self.assertIn("crew/alpha", page)
        self.assertNotIn("crew/beta", page)
        self.assertIn("not named here", page)

    def test_admin_names_every_affected_repo(self):
        self.seed_world()
        ov = self.overview.org_overview(self.admin, "crew")
        self.assertEqual(
            ov.named_repos, ("crew/alpha", "crew/beta"))
        self.assertEqual(ov.hidden_repos_affected, 0)
        inst = self.overview.instance_overview(self.admin)
        self.assertEqual(
            inst.named_repos,
            ("crew/alpha", "crew/beta", "volmarr/solo"))
        self.assertEqual(inst.hidden_repos_affected, 0)

    # -- counts only, no code content -----------------------------------

    def test_counts_only_no_secret_or_code_content(self):
        seed_secret(self.conn, self.alpha.id, 501, "open",
                    redacted=PLANTED_SECRET)
        seed_code(self.conn, self.alpha.id, 501, "open", "error")
        self.conn.execute(
            "UPDATE code_scanning_alerts SET message = ?",
            (PLANTED_CODE,))
        self.conn.commit()
        ov = self.overview.org_overview(self.admin, "crew")
        self.assertEqual(ov.open_total, 2)
        blob = (render_security_overview_page(ov)
                + json.dumps(security_overview_to_dict(ov)))
        self.assertNotIn(PLANTED_SECRET, blob)
        self.assertNotIn(PLANTED_CODE, blob)
        self.assertNotIn("src/file501.py", blob)
        data = security_overview_to_dict(ov)
        self.assertNotIn("recent", data)
        for family in data["families"]:
            self.assertNotIn("alerts", family)

    def test_to_dict_shape(self):
        self.seed_world()
        data = security_overview_to_dict(
            self.overview.org_overview(self.member, "crew"))
        self.assertEqual(data["scope"], "org")
        self.assertEqual(data["scope_name"], "crew")
        self.assertEqual(data["open_total"], 5)
        self.assertEqual(data["repos_affected"], 2)
        self.assertEqual(data["hidden_repos_affected"], 1)
        self.assertEqual(data["named_repos"], ["crew/alpha"])
        self.assertEqual(
            [f["family"] for f in data["families"]],
            ["secret", "dependency", "code_scanning"])
        self.assertEqual(
            data["advisory_snapshot"]["snapshot_date"],
            "2023-11-10")
        json.dumps(data)  # the whole shape is data, serialisable

    # -- the snapshot's age ---------------------------------------------

    def test_snapshot_age_stands_on_the_overview(self):
        ov = self.overview.org_overview(self.member, "crew")
        self.assertEqual(ov.snapshot.freshness, "current")
        self.assertEqual(ov.snapshot.age_days, 4)
        page = render_security_overview_page(ov)
        self.assertIn("2023-11-10", page)
        self.assertIn("advisory snapshot dated", page)

    def test_stale_snapshot_says_stale(self):
        stale = SecurityOverviewStore(
            self.conn, self.repos, self.accounts,
            advisories=AdvisoryStore.from_text(
                STALE_SNAPSHOT, now=T0), time_fn=self.clock)
        ov = stale.org_overview(self.member, "crew")
        self.assertEqual(ov.snapshot.freshness, "stale")
        self.assertIn("stale", render_security_overview_page(ov))

    def test_unknown_snapshot_age_said_honestly(self):
        default = SecurityOverviewStore(
            self.conn, self.repos, self.accounts,
            time_fn=self.clock)
        ov = default.org_overview(self.member, "crew")
        self.assertEqual(ov.snapshot.freshness, "unknown")
        self.assertIn("age unknown",
                      render_security_overview_page(ov))

    def test_render_escapes_the_title(self):
        ov = self.overview.org_overview(self.member, "crew")
        page = render_security_overview_page(
            ov, title="<script>alert(1)</script>")
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    # -- unrecognised values and the audit re-proof ----------------------

    def test_unrecognised_values_named_not_folded(self):
        seed_dependency(self.conn, self.alpha.id, 401, "open", "dire")
        seed_secret(self.conn, self.alpha.id, 402, "weird-state")
        seed_code(self.conn, self.alpha.id, 403, "open", "bogus")
        self.conn.commit()
        ov = self.overview.org_overview(self.member, "crew")
        dep = ov.family("dependency")
        # The dire-severity alert is live and counted in the
        # live total, but stands in no known severity bucket.
        self.assertEqual(dep.live, 1)
        self.assertEqual(dep.unrecognised, 1)
        self.assertEqual(sum(dep.by_severity.values()), 0)
        secret = ov.family("secret")
        # A state outside the vocabulary cannot be proven
        # live: named unrecognised, never counted open.
        self.assertEqual(secret.live, 0)
        self.assertEqual(secret.unrecognised, 1)
        code = ov.family("code_scanning")
        self.assertEqual(code.live, 1)
        self.assertEqual(code.unrecognised, 1)
        self.assertEqual(sum(code.by_level.values()), 0)
        self.assertIn("outside this family's vocabulary",
                      dep.words())

    def test_audit_clean_world(self):
        self.seed_world()
        self.assertEqual(audit_security_overview(self.conn), [])

    def test_audit_flags_corrupt_rows(self):
        seed_dependency(self.conn, self.alpha.id, 601, "open", "dire")
        seed_code(self.conn, self.alpha.id, 602, "open", "bogus")
        seed_secret(self.conn, 99999, 603, "open")
        self.conn.commit()
        problems = audit_security_overview(self.conn)
        text = "\n".join(problems)
        self.assertIn("'dire'", text)
        self.assertIn("'bogus'", text)
        self.assertIn("does not stand", text)
        self.assertGreaterEqual(len(problems), 3)

    # -- honesty pins -------------------------------------------------------

    def test_read_writes_nothing_and_audits_nothing(self):
        self.seed_world()
        def counts():
            audit_n = self.conn.execute(
                "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
            member_n = self.conn.execute(
                "SELECT COUNT(*) AS n FROM"
                " organization_members").fetchone()["n"]
            return audit_n, member_n
        before = counts()
        ov = self.overview.org_overview(self.creator, "emptyorg")
        render_security_overview_page(ov)
        self.overview.org_overview(self.member, "crew")
        self.overview.instance_overview(self.admin)
        self.assertEqual(before, counts())
        # The founding-owner judgement on emptyorg was a
        # pure read: no membership seed row was written.
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM organization_members"
            " WHERE org_id = ?", (self.empty_org.id,)).fetchone()["n"]
        self.assertEqual(rows, 0)

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 127)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)


if __name__ == "__main__":
    unittest.main()
