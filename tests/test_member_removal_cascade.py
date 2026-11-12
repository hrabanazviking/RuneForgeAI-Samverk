"""S-194 acceptance battery: member removal cascade.

Acceptance (roadmap S-194): Member removal cascade —
what happens to assignments, reviews, and ownerships
on removal is computed and shown *before* confirming.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.assignees import AssigneeStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.default_permissions import DefaultPermissionStore
from samverk.invitations import InvitationStore
from samverk.issues import IssueStore
from samverk.member_removal_cascade import (
    CascadeStore, decide_cascade, render_removal_cascade_page)
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import OrganizationError, OrganizationStore
from samverk.repositories import RepositoryStore
from samverk.teams import TeamStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class RemovalCascadeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.creator = self.accounts.register("volmarr", "correct horse battery")
        self.yrsa = self.accounts.register("yrsa", "correct horse battery", "yrsa@example.com")
        self.bryn = self.accounts.register("brynhild", "correct horse battery", "bryn@example.com")
        self.outsider = self.accounts.register("freya", "correct horse battery")
        self.orgs = OrganizationStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.org = self.orgs.create_organization(self.creator.id, "crew")
        self.members = OrgMembershipStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        self.members.add_member(self.creator.id, self.org.id, self.bryn.id)
        self.cascade = CascadeStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.anvil = self._repo("crew", "anvil", "public")
        self.secret = self._repo("crew", "secret", "private")
        self.own = self._repo("yrsa", "own", "private")

    def _repo(self, owner, name, visibility):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                (owner, owner.lower(), name, name.lower(), self.creator.id, 1_700_000_000, visibility))
        return int(cur.lastrowid)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _rich_fixture(self):
        """yrsa tied to the org every way the cascade reads."""
        teams = TeamStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        forge = teams.create_team(self.creator.id, self.org.id, "Forge")
        teams.add_member(self.creator.id, self.org.id, forge.id, self.yrsa.id)
        child = teams.create_team(self.creator.id, self.org.id, "Anvil Crew",
                                  parent_team_id=forge.id)
        teams.link_repo(self.creator.id, self.org.id, forge.id, self.anvil)
        defaults = DefaultPermissionStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        defaults.set_default(self.creator.id, self.org.id, "read")
        repos = RepositoryStore(self.conn, self.root, self.accounts)
        issues = IssueStore(self.conn, repos, self.accounts, audit=self.audit, time_fn=self.clock)
        assignees = AssigneeStore(self.conn, repos, self.accounts, issues, audit=self.audit, time_fn=self.clock)
        issue = issues.create_issue(self.creator, "crew", "anvil", "Sharpen the edge")
        assignees.assign(self.yrsa, "crew", "anvil", issue.number, "yrsa")
        authored = issues.create_issue(self.yrsa, "crew", "anvil", "Yrsa's own <task>")
        # A pull request by bryn, with yrsa requested,
        # reviewed and drafting — fixture rows in the
        # landed S-148/S-151 shapes (the git plumbing
        # behind a real PR is those slices' batteries).
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO issues (repo_id, number, kind, author_id, title, body, state, created_at, updated_at) VALUES (?, ?, 'pull_request', ?, 'Bryn work', '', 'open', ?, ?)",
                (self.anvil, 90, self.bryn.id, 1_700_000_000, 1_700_000_000))
            pr_issue_id = int(cur.lastrowid)
            cur = self.conn.execute(
                "INSERT INTO pull_requests (issue_id, repo_id, base_branch, head_branch, created_at, updated_at) VALUES (?, ?, 'main', 'feature', ?, ?)",
                (pr_issue_id, self.anvil, 1_700_000_000, 1_700_000_000))
            pr_id = int(cur.lastrowid)
            self.conn.execute(
                "INSERT INTO pull_request_review_requests (pull_request_id, owner_ref, user_id, source, head_oid, created_at, state) VALUES (?, '@yrsa', ?, 'manual', 'abc', ?, 'requested')",
                (pr_id, self.yrsa.id, 1_700_000_000))
            self.conn.execute(
                "INSERT INTO pull_request_review_requests (pull_request_id, owner_ref, user_id, source, head_oid, created_at, state) VALUES (?, '@yrsa', ?, 'codeowners', 'abc', ?, 'dismissed')",
                (pr_id, self.yrsa.id, 1_700_000_000))
            self.conn.execute(
                "INSERT INTO pull_request_reviews (pull_request_id, reviewer_id, verdict, summary, head_oid, submitted_at) VALUES (?, ?, 'approved', 'Fine work.', 'abc', ?)",
                (pr_id, self.yrsa.id, 1_700_000_000))
            self.conn.execute(
                "INSERT INTO pull_request_pending_reviews (pull_request_id, reviewer_id, verdict, summary, created_at, updated_at) VALUES (?, ?, '', '', ?, ?)",
                (pr_id, self.yrsa.id, 1_700_000_000, 1_700_000_000))
            # A leftover outside grant in an org repo: a
            # member needs none, so the cascade must
            # surface the row rather than hide it.
            self.conn.execute(
                "INSERT INTO outside_collaborators (repo_id, user_id, role, granted_by, created_at, updated_at) VALUES (?, ?, 'write', ?, ?, ?)",
                (self.anvil, self.yrsa.id, self.creator.id, 1_700_000_000, 1_700_000_000))
        return forge, child, issue, authored

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 118)
        self.assertEqual(db.MIGRATIONS[-1][0], 118)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)

    # pure law
    def test_pure_decide_cascade(self):
        self.assertEqual(decide_cascade(None, 3), "not_a_member")
        self.assertEqual(decide_cascade("owner", 1), "last_owner")
        self.assertIsNone(decide_cascade("owner", 2))
        self.assertIsNone(decide_cascade("member", 1))
        self.assertIsNone(decide_cascade("member", 0))

    # the full cascade
    def test_full_cascade_for_a_tied_member(self):
        forge, child, issue, authored = self._rich_fixture()
        got = self.cascade.preview_removal(self.org.id, self.yrsa.id)
        self.assertTrue(got.allowed)
        self.assertIsNone(got.reason)
        self.assertTrue(got.is_member)
        self.assertEqual(got.role, "member")
        self.assertEqual(got.owner_count, 1)
        self.assertFalse(got.is_org_creator)
        self.assertEqual(got.default_permission, "read")
        self.assertEqual([t.name for t in got.direct_teams], ["Forge"])
        self.assertEqual([t.name for t in got.inherited_teams], ["Anvil Crew"])
        self.assertEqual([(r.repo, r.permission) for r in got.team_repos],
                         [("crew/anvil", "read")])
        self.assertEqual([(a.repo, a.number, a.kind) for a in got.assignments],
                         [("crew/anvil", issue.number, "issue")])
        self.assertEqual(len(got.review_requests), 2)
        self.assertEqual(len(got.standing_review_requests), 1)
        self.assertEqual(got.standing_review_requests[0].source, "manual")
        self.assertEqual([(r.number, r.verdict) for r in got.submitted_reviews],
                         [(90, "approved")])
        self.assertEqual(len(got.pending_reviews), 1)
        self.assertEqual([(g.repo, g.role) for g in got.collaborator_grants],
                         [("crew/anvil", "write")])
        self.assertEqual([r.full_name for r in got.org_repositories],
                         ["crew/anvil", "crew/secret"])
        self.assertEqual([r.full_name for r in got.personal_repositories],
                         ["yrsa/own"])
        self.assertEqual([i.number for i in got.authored_open], [authored.number])
        self.assertEqual(got.invitations_sent, ())
        self.assertIn("yrsa", got.summary())

    def test_target_by_username_matches_by_id(self):
        self._rich_fixture()
        by_id = self.cascade.preview_removal(self.org.id, self.yrsa.id)
        by_name = self.cascade.preview_removal(self.org.id, "YRSA")
        self.assertEqual(by_id.assignments, by_name.assignments)
        self.assertEqual(by_id.direct_teams, by_name.direct_teams)

    def test_empty_cascade_for_an_untied_member(self):
        self.members.add_member(self.creator.id, self.org.id, self.outsider.id)
        got = self.cascade.preview_removal(self.org.id, self.outsider.id)
        self.assertTrue(got.allowed)
        self.assertEqual(got.ending_count, 0)
        for field in (got.direct_teams, got.inherited_teams, got.team_repos,
                      got.assignments, got.review_requests,
                      got.submitted_reviews, got.pending_reviews,
                      got.collaborator_grants, got.invitations_sent,
                      got.authored_open, got.personal_repositories):
            self.assertEqual(field, ())
        self.assertIn("would end nothing else", got.summary())
        self.assertEqual(got.default_permission, "none")

    def test_pending_invitations_sent_are_named(self):
        self.members.set_role(self.creator.id, self.org.id, self.bryn.id, "owner")
        invites = InvitationStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        invites.invite(self.bryn.id, self.org.id, username="freya")
        got = self.cascade.preview_removal(self.org.id, self.bryn.id)
        self.assertEqual(got.role, "owner")
        self.assertEqual(got.owner_count, 2)
        self.assertTrue(got.allowed)
        self.assertEqual([(i.target, i.role) for i in got.invitations_sent],
                         [("freya", "member")])

    # refusals, reported not raised
    def test_last_owner_is_refused_in_the_preview(self):
        solo = self.orgs.create_organization(self.creator.id, "solo-crew")
        got = self.cascade.preview_removal(solo.id, self.creator.id)
        self.assertFalse(got.allowed)
        self.assertEqual(got.reason, "last_owner")
        self.assertTrue(got.is_last_owner)
        self.assertEqual(got.role, "owner")
        self.assertTrue(got.is_org_creator)
        self.assertIn("last owner", got.message)
        self.assertIn("refused", got.summary())

    def test_non_member_is_reported_not_raised(self):
        got = self.cascade.preview_removal(self.org.id, self.outsider.id)
        self.assertFalse(got.allowed)
        self.assertEqual(got.reason, "not_a_member")
        self.assertFalse(got.is_member)
        self.assertIsNone(got.role)
        self.assertEqual(got.ending_count, 0)
        self.assertIn("not a member", got.summary())

    def test_unknown_org_and_user_raise(self):
        self.assertEqual(self._reason(self.cascade.preview_removal, 9999, self.yrsa.id), "org_not_found")
        self.assertEqual(self._reason(self.cascade.preview_removal, self.org.id, 9999), "no_such_user")
        self.assertEqual(self._reason(self.cascade.preview_removal, self.org.id, "ghost"), "no_such_user")

    # purity: the preview changes nothing
    def _snapshot(self):
        tables = ("organization_members", "team_members", "issue_assignees",
                  "pull_request_review_requests", "pull_request_reviews",
                  "pull_request_pending_reviews", "outside_collaborators",
                  "org_invitations", "audit_log")
        return {t: self.conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] for t in tables}

    def test_preview_writes_and_audits_nothing(self):
        self._rich_fixture()
        before = self._snapshot()
        self.cascade.preview_removal(self.org.id, self.yrsa.id)
        self.cascade.preview_removal(self.org.id, self.creator.id)
        self.cascade.preview_removal(self.org.id, self.outsider.id)
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self.members.role_for(self.yrsa.id, self.org.id), "member")

    def test_removal_still_happens_through_the_s186_door(self):
        self._rich_fixture()
        self.cascade.preview_removal(self.org.id, self.yrsa.id)
        self.assertEqual(self.members.role_for(self.yrsa.id, self.org.id), "member")
        self.members.remove_member(self.creator.id, self.org.id, self.yrsa.id)
        after = self.cascade.preview_removal(self.org.id, self.yrsa.id)
        self.assertEqual(after.reason, "not_a_member")

    # the page
    def test_page_shows_the_cascade_before_confirming(self):
        self._rich_fixture()
        got = self.cascade.preview_removal(self.org.id, self.yrsa.id)
        page = render_removal_cascade_page(self.org, got)
        for needle in ("Before you remove yrsa", "Forge", "Anvil Crew",
                       "crew/anvil", "Sharpen the edge",
                       "Nothing has been removed yet"):
            self.assertIn(needle, page)
        # An authored title carrying markup arrives escaped, never raw.
        self.assertIn("&lt;task&gt;", page)
        self.assertNotIn("<task>", page)

    def test_page_states_the_last_owner_refusal(self):
        solo = self.orgs.create_organization(self.creator.id, "solo-crew")
        solo_org = self.orgs.get_by_id(solo.id)
        got = self.cascade.preview_removal(solo.id, self.creator.id)
        page = render_removal_cascade_page(solo_org, got)
        self.assertIn("last owner", page)
        self.assertIn("refused", page)


if __name__ == "__main__":
    unittest.main()
