"""S-193 acceptance battery: organization invitations.

Acceptance (roadmap S-193): Invitations — invite by
username or email, expiring, rescindable; acceptance
creates membership and audit events on both sides.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.invitations import (
    INVITATION_TTL_SECONDS, InvitationStore,
    decide_invitation_state, render_invitations_page,
    state_word)
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import OrganizationError, OrganizationStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class InvitationTests(unittest.TestCase):
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
        self.admin = self.accounts.register("sitemod", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.orgs = OrganizationStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.org = self.orgs.create_organization(self.creator.id, "crew")
        self.members = OrgMembershipStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        self.invites = InvitationStore(self.conn, self.accounts, self.audit, time_fn=self.clock)

    def _updates(self):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action = 'auth.organization.update'").fetchone()["c"]

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 107)
        self.assertEqual(db.MIGRATIONS[-1][0], 107)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertIn("auth.organization.update", taxonomy.AUDIT_EVENTS)
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(org_invitations)").fetchall()]
        self.assertEqual(cols, ["id", "org_id", "invitee_user_id", "invitee_email", "invitee_email_lower", "role", "invited_by", "status", "created_at", "expires_at", "resolved_at"])

    def test_migration_75_creates_the_table(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for version, statements in db.MIGRATIONS:
                if version > 74:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)", (str(version),))
            self.assertEqual(db.schema_version(conn), 74)
            conn.close()
            conn = db.init_db(path)
            self.assertEqual(db.schema_version(conn), 107)
            tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()]
            self.assertIn("org_invitations", tables)
            conn.close()

    # pure judgements
    def test_pure_state_judgements(self):
        self.assertEqual(decide_invitation_state("pending", 200, 100), "pending")
        self.assertEqual(decide_invitation_state("pending", 200, 200), "expired")
        self.assertEqual(decide_invitation_state("pending", 200, 300), "expired")
        self.assertEqual(decide_invitation_state("accepted", 200, 300), "accepted")
        self.assertEqual(decide_invitation_state("rescinded", 200, 100), "rescinded")
        self.assertEqual(state_word("pending"), "Pending")
        self.assertEqual(state_word("expired"), "Expired")
        self.assertEqual(state_word("accepted"), "Accepted")
        self.assertEqual(state_word("rescinded"), "Rescinded")
        self.assertEqual(INVITATION_TTL_SECONDS, 7 * 24 * 3600)

    # inviting
    def test_invite_by_username(self):
        before = self._updates()
        inv = self.invites.invite(self.creator.id, self.org.id, username="freya")
        self.assertEqual(inv.invitee_user_id, self.outsider.id)
        self.assertEqual(inv.invitee_username, "freya")
        self.assertIsNone(inv.invitee_email)
        self.assertEqual(inv.role, "member")
        self.assertEqual(inv.status, "pending")
        self.assertEqual(inv.invited_by, self.creator.id)
        self.assertEqual(inv.expires_at, inv.created_at + INVITATION_TTL_SECONDS)
        self.assertIsNone(inv.resolved_at)
        self.assertEqual(self._updates(), before + 1)
        row = self.conn.execute("SELECT target_kind, target_id, detail FROM audit_log WHERE action = 'auth.organization.update' ORDER BY rowid DESC LIMIT 1").fetchone()
        self.assertEqual(row["target_kind"], "organization")
        self.assertEqual(row["target_id"], "crew")
        self.assertIn("invitations", row["detail"])
        self.assertIn("invite", row["detail"])
        self.assertIn("freya", row["detail"])

    def test_invite_by_email_matching_existing_account(self):
        inv = self.invites.invite(self.creator.id, self.org.id, email="Bryn@Example.com")
        self.assertEqual(inv.invitee_user_id, self.bryn.id)
        self.assertEqual(inv.invitee_email_lower, "bryn@example.com")
        got = self.invites.accept(self.bryn.id, inv.id)
        self.assertEqual(got.status, "accepted")
        self.assertEqual(self.members.role_for(self.bryn.id, self.org.id), "member")

    def test_invite_by_email_no_account_then_register_and_accept(self):
        inv = self.invites.invite(self.creator.id, self.org.id, email="Hire@Example.COM", role="owner")
        self.assertIsNone(inv.invitee_user_id)
        self.assertEqual(inv.invitee_email_lower, "hire@example.com")
        newhire = self.accounts.register("newhire", "correct horse battery", "hire@example.com")
        found = self.invites.list_for_user(newhire.id)
        self.assertEqual([i.id for i in found], [inv.id])
        got = self.invites.accept(newhire.id, inv.id)
        self.assertEqual(got.status, "accepted")
        self.assertIsNotNone(got.resolved_at)
        membership = self.members.get_membership(newhire.id, self.org.id)
        self.assertEqual(membership.role, "owner")
        self.assertEqual(membership.added_by, self.creator.id)

    def test_duplicate_live_invite_refused(self):
        self.invites.invite(self.creator.id, self.org.id, username="freya")
        self.assertEqual(self._reason(self.invites.invite, self.creator.id, self.org.id, username="freya"), "already_invited")
        self.invites.invite(self.creator.id, self.org.id, username="brynhild")
        self.assertEqual(self._reason(self.invites.invite, self.creator.id, self.org.id, email="bryn@example.com"), "already_invited")

    def test_already_member_refused(self):
        self.assertEqual(self._reason(self.invites.invite, self.creator.id, self.org.id, username="yrsa"), "already_member")
        self.assertEqual(self._reason(self.invites.invite, self.creator.id, self.org.id, email="yrsa@example.com"), "already_member")
        self.assertEqual(self._reason(self.invites.invite, self.creator.id, self.org.id, username="volmarr"), "already_member")

    def test_invite_is_owner_or_admin_only(self):
        self.assertEqual(self._reason(self.invites.invite, self.yrsa.id, self.org.id, username="freya"), "not_org_owner")
        self.assertEqual(self._reason(self.invites.invite, 9999, self.org.id, username="freya"), "no_such_user")
        inv = self.invites.invite(self.admin.id, self.org.id, username="freya")
        self.assertEqual(inv.invited_by, self.admin.id)

    def test_invite_refusals(self):
        self.assertEqual(self._reason(self.invites.invite, self.creator.id, 9999, username="freya"), "org_not_found")
        self.assertEqual(self._reason(self.invites.invite, self.creator.id, self.org.id, username="ghost"), "no_such_user")
        self.assertEqual(self._reason(self.invites.invite, self.creator.id, self.org.id, email="not-an-email"), "email_invalid")
        self.assertEqual(self._reason(self.invites.invite, self.creator.id, self.org.id, username="freya", email="bryn@example.com"), "invitation_target_invalid")
        self.assertEqual(self._reason(self.invites.invite, self.creator.id, self.org.id), "invitation_target_invalid")
        self.assertEqual(self._reason(self.invites.invite, self.creator.id, self.org.id, username="freya", role="superuser"), "role_invalid")

    def test_refusals_write_and_audit_nothing(self):
        rows_before = self.conn.execute("SELECT COUNT(*) c FROM org_invitations").fetchone()["c"]
        audit_before = self._updates()
        self._reason(self.invites.invite, self.yrsa.id, self.org.id, username="freya")
        self._reason(self.invites.invite, self.creator.id, self.org.id, username="ghost")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM org_invitations").fetchone()["c"], rows_before)
        self.assertEqual(self._updates(), audit_before)

    # rescind and accept
    def test_rescind(self):
        inv = self.invites.invite(self.creator.id, self.org.id, username="freya")
        before = self._updates()
        got = self.invites.rescind(self.creator.id, inv.id)
        self.assertEqual(got.status, "rescinded")
        self.assertIsNotNone(got.resolved_at)
        self.assertEqual(self._updates(), before + 1)
        self.assertEqual(self._reason(self.invites.accept, self.outsider.id, inv.id), "invitation_not_pending")
        self.assertEqual(self.invites.list_for_user(self.outsider.id), [])

    def test_rescind_guards(self):
        inv = self.invites.invite(self.creator.id, self.org.id, username="freya")
        self.assertEqual(self._reason(self.invites.rescind, self.yrsa.id, inv.id), "not_org_owner")
        self.assertEqual(self._reason(self.invites.rescind, self.creator.id, 9999), "invitation_not_found")
        self.invites.accept(self.outsider.id, inv.id)
        self.assertEqual(self._reason(self.invites.rescind, self.creator.id, inv.id), "invitation_not_pending")

    def test_accept_creates_membership_and_audits_both_sides(self):
        inv = self.invites.invite(self.creator.id, self.org.id, username="freya", role="owner")
        before = self._updates()
        got = self.invites.accept(self.outsider.id, inv.id)
        self.assertEqual(got.status, "accepted")
        self.assertIsNotNone(got.resolved_at)
        membership = self.members.get_membership(self.outsider.id, self.org.id)
        self.assertEqual(membership.role, "owner")
        self.assertEqual(membership.added_by, self.creator.id)
        self.assertEqual(self._updates(), before + 2)
        rows = self.conn.execute("SELECT target_kind, target_id, actor_id, detail FROM audit_log WHERE action = 'auth.organization.update' ORDER BY rowid DESC LIMIT 2").fetchall()
        pairs = {(r["target_kind"], r["target_id"]) for r in rows}
        self.assertEqual(pairs, {("organization", "crew"), ("user", "freya")})
        for r in rows:
            self.assertEqual(r["actor_id"], self.outsider.id)
            self.assertIn("invitations", r["detail"])
            self.assertIn("accept", r["detail"])
        org_row = [r for r in rows if r["target_kind"] == "organization"][0]
        user_row = [r for r in rows if r["target_kind"] == "user"][0]
        self.assertIn("freya", org_row["detail"])
        self.assertIn("crew", user_row["detail"])

    def test_accept_by_wrong_user_refused(self):
        inv = self.invites.invite(self.creator.id, self.org.id, username="freya")
        self.assertEqual(self._reason(self.invites.accept, self.bryn.id, inv.id), "invitation_not_for_you")
        self.assertIsNone(self.members.get_membership(self.bryn.id, self.org.id))
        self.assertEqual(self.invites.get_invitation(inv.id).status, "pending")

    def test_accept_email_invitation_by_nonmatching_email_refused(self):
        inv = self.invites.invite(self.creator.id, self.org.id, email="ghost@example.com")
        self.assertEqual(self._reason(self.invites.accept, self.bryn.id, inv.id), "invitation_not_for_you")
        self.assertEqual(self._reason(self.invites.accept, self.outsider.id, inv.id), "invitation_not_for_you")

    def test_accept_unknown_and_resolved_refused(self):
        self.assertEqual(self._reason(self.invites.accept, self.outsider.id, 9999), "invitation_not_found")
        inv = self.invites.invite(self.creator.id, self.org.id, username="freya")
        self.invites.accept(self.outsider.id, inv.id)
        self.assertEqual(self._reason(self.invites.accept, self.outsider.id, inv.id), "invitation_not_pending")

    # expiry
    def test_expiry_judged_and_reinvite_allowed(self):
        inv = self.invites.invite(self.creator.id, self.org.id, username="freya")
        self.clock.now += INVITATION_TTL_SECONDS + 1
        stored = self.invites.get_invitation(inv.id)
        self.assertEqual(stored.status, "pending")
        self.assertEqual(stored.state(self.clock.now), "expired")
        self.assertEqual(self._reason(self.invites.accept, self.outsider.id, inv.id), "invitation_expired")
        self.assertEqual(self._reason(self.invites.rescind, self.creator.id, inv.id), "invitation_expired")
        page = render_invitations_page(self.invites.list_invitations(self.org.id), self.clock.now)
        self.assertIn("Expired", page)
        self.assertEqual(self.invites.list_for_user(self.outsider.id), [])
        fresh = self.invites.invite(self.creator.id, self.org.id, username="freya")
        self.assertEqual(fresh.status, "pending")
        self.assertNotEqual(fresh.id, inv.id)

    # reads and page
    def test_list_invitations_in_creation_order(self):
        first = self.invites.invite(self.creator.id, self.org.id, username="freya")
        second = self.invites.invite(self.creator.id, self.org.id, email="ghost@example.com")
        listed = self.invites.list_invitations(self.org.id)
        self.assertEqual([i.id for i in listed], [first.id, second.id])
        self.assertEqual(self._reason(self.invites.list_invitations, 9999), "org_not_found")

    def test_list_for_user_finds_username_and_email_invitations(self):
        by_name = self.invites.invite(self.creator.id, self.org.id, username="freya")
        by_email = self.invites.invite(self.creator.id, self.org.id, email="bryn@example.com")
        self.assertEqual([i.id for i in self.invites.list_for_user(self.outsider.id)], [by_name.id])
        self.assertEqual([i.id for i in self.invites.list_for_user(self.bryn.id)], [by_email.id])
        self.assertEqual(self.invites.list_for_user(self.yrsa.id), [])
        self.assertEqual(self._reason(self.invites.list_for_user, 9999), "no_such_user")

    def test_page_states_states_in_words(self):
        inv = self.invites.invite(self.creator.id, self.org.id, username="freya", role="owner")
        page = render_invitations_page(self.invites.list_invitations(self.org.id), self.clock.now)
        self.assertIn("Pending", page)
        self.assertIn("freya", page)
        self.assertIn("Owner", page)
        self.assertIn("crew", page)
        self.invites.accept(self.outsider.id, inv.id)
        page = render_invitations_page(self.invites.list_invitations(self.org.id), self.clock.now)
        self.assertIn("Accepted", page)


if __name__ == "__main__":
    unittest.main()
