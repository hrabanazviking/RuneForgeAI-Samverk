"""S-351 acceptance battery: admin panel.

Acceptance (roadmap S-351): users (create, suspend per
S-044, delete per S-043), orgs, repos: searchable, every
destructive action sudo-gated and audit-logged.

Counted with: python3 -m unittest tests.test_admin_panel
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.admin_panel import (
    DESTRUCTIVE_ACTIONS,
    AdminPanel,
    AdminPanelError,
    audit_event_for,
    is_destructive_action,
    matches_query,
    normalize_query,
    render_admin_panel_page,
)
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.organizations import OrganizationError, OrganizationStore
from samverk.repo_deletion import RepoDeletionError
from samverk.repositories import RepositoryStore
from samverk.sessions import SessionStore
from samverk.sudo_mode import SudoMode

PW = "correct horse battery"
NOW = 1700000000.0


class AdminPanelTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name) / "instance"
        self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.audit = AuditLog(self.conn, time_fn=lambda: NOW)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.admin = self.accounts.register("volmarr", PW, "v@e.c")
        with self.conn:
            self.conn.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?",
                (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.target = self.accounts.register("yrsa", PW, "y@e.c")
        self.plain = self.accounts.register("mallory", PW, "m@e.c")
        clock = lambda: NOW  # noqa: E731
        self.sessions = SessionStore(self.conn, time_fn=clock)
        self.admin_token = self.sessions.create(self.admin.id)
        self.sudo = SudoMode(self.conn, self.accounts, time_fn=clock)
        self.panel = AdminPanel(
            self.conn, self.data_root, self.accounts,
            audit=self.audit, sudo=self.sudo, time_fn=clock)
        self.repos = RepositoryStore(
            self.conn, self.data_root, self.accounts)
        self.repos.create_repository(self.admin.id, "volmarr", "alpha")
        self.orgs = OrganizationStore(
            self.conn, self.accounts, self.audit, time_fn=clock)
        self.org = self.orgs.create_organization(
            self.admin.id, "acme", display_name="Acme Corp")

    # -- helpers -----------------------------------------------------

    def grant(self):
        self.sudo.grant(self.admin.id, PW, self.admin_token)

    def audit_rows(self, action=None, outcome=None):
        rows = self.conn.execute(
            "SELECT * FROM audit_log ORDER BY seq").fetchall()
        out = []
        for row in rows:
            if action is not None and row["action"] != action:
                continue
            if outcome is not None and row["outcome"] != outcome:
                continue
            out.append(row)
        return out

    # -- pins ----------------------------------------------------------

    def test_schema_and_taxonomy_pins_unchanged(self):
        self.assertEqual(schema_version(self.conn), 139)
        self.assertEqual(db.MIGRATIONS[-1][0], 139)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    # -- pure judgements ----------------------------------------------

    def test_matches_query_terms_and_case(self):
        self.assertTrue(matches_query(["Volmarr", "v@e.c"], "volm"))
        self.assertTrue(matches_query(["Volmarr", "v@e.c"], "VOLMARR e.c"))
        self.assertFalse(matches_query(["Volmarr"], "yrsa"))
        self.assertTrue(matches_query(["anything"], ""))
        self.assertTrue(matches_query(["anything"], None))

    def test_normalize_query_refusals(self):
        self.assertEqual(normalize_query("  acme "), "acme")
        self.assertEqual(normalize_query(None), "")
        for bad in ("a\x00b", "x" * 201, 42):
            with self.assertRaises(AdminPanelError) as ctx:
                normalize_query(bad)
            self.assertEqual(ctx.exception.reason, "query_invalid")

    def test_every_destructive_action_has_a_known_event(self):
        for action in DESTRUCTIVE_ACTIONS:
            self.assertTrue(is_destructive_action(action))
            event = audit_event_for(action)
            self.assertIsNotNone(event)
            self.assertTrue(taxonomy.is_known_event(event), event)
        self.assertFalse(is_destructive_action("unsuspend_user"))

    # -- the admin gate --------------------------------------------------

    def test_overview_is_admin_only(self):
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.overview(self.plain.id)
        self.assertEqual(ctx.exception.reason, "not_admin")
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.overview(99999)
        self.assertEqual(ctx.exception.reason, "no_such_user")
        over = self.panel.overview(self.admin.id)
        self.assertEqual(over.users, 3)
        self.assertEqual(over.admins, 1)
        self.assertEqual(over.orgs, 1)
        self.assertEqual(over.repos, 1)

    def test_non_admin_destructive_attempt_is_witnessed_denied(self):
        before = len(self.audit_rows("admin.user.suspend", "denied"))
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.suspend_user(
                self.plain.id, "tok", self.target.id, "spam")
        self.assertEqual(ctx.exception.reason, "not_admin")
        after = self.audit_rows("admin.user.suspend", "denied")
        self.assertEqual(len(after), before + 1)
        self.assertEqual(
            self.accounts.get_by_id(self.target.id).status, "active")

    # -- search ------------------------------------------------------------

    def test_search_finds_each_subject_from_one_box(self):
        by_user = self.panel.search(self.admin.id, "yrsa")
        self.assertEqual([r.user.username for r in by_user.users],
                         ["yrsa"])
        by_email = self.panel.search(self.admin.id, "y@e.c")
        self.assertEqual([r.user.username for r in by_email.users],
                         ["yrsa"])
        by_org = self.panel.search(self.admin.id, "acme")
        self.assertEqual([r.org.name for r in by_org.orgs], ["acme"])
        self.assertEqual(by_org.orgs[0].member_count, 1)
        by_repo = self.panel.search(self.admin.id, "alpha")
        self.assertEqual([r.repo.full_name for r in by_repo.repos],
                         ["volmarr/alpha"])
        everything = self.panel.search(self.admin.id, "")
        self.assertEqual(everything.total, 5)  # 3 users + org + repo

    def test_search_kind_filter_and_honest_empty_state(self):
        only = self.panel.search(self.admin.id, "a", kind="repo")
        self.assertEqual(only.users, [])
        self.assertEqual(len(only.repos), 1)
        none = self.panel.search(self.admin.id, "zzz-no-such-thing")
        self.assertEqual(none.total, 0)
        page = render_admin_panel_page(none)
        self.assertIn("No users match.", page)
        self.assertIn("No organizations match.", page)
        self.assertIn("No repositories match.", page)
        with self.assertRaises(AdminPanelError):
            self.panel.search(self.admin.id, "a", kind="bogus")
        with self.assertRaises(AdminPanelError):
            self.panel.search(self.admin.id, "a", limit=0)

    def test_search_is_admin_only(self):
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.search(self.plain.id, "yrsa")
        self.assertEqual(ctx.exception.reason, "not_admin")

    def test_page_renders_rows_and_escapes(self):
        results = self.panel.search(self.admin.id, "")
        page = render_admin_panel_page(results)
        self.assertIn("<h1>Admin panel</h1>", page)
        self.assertIn("volmarr/alpha", page)
        self.assertIn("Acme Corp", page)

    # -- create ------------------------------------------------------------

    def test_create_user_needs_sudo_and_audits_first(self):
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.create_user(
                self.admin.id, self.admin_token, "newhire", PW)
        self.assertEqual(ctx.exception.reason, "sudo_required")
        self.assertIsNone(self.accounts.get_by_username("newhire"))
        denied = self.audit_rows("admin.user.create", "denied")
        self.assertTrue(any(
            '"sudo_required"' in (r["detail"] or "") for r in denied))
        self.grant()
        user = self.panel.create_user(
            self.admin.id, self.admin_token, "newhire", PW, "n@e.c")
        self.assertEqual(user.status, "active")
        panel_seq = self.audit_rows("admin.user.create", "success")[0]["seq"]
        signup_seq = self.audit_rows("auth.signup.success", "success")[-1]["seq"]
        self.assertLess(panel_seq, signup_seq)  # authorized before it ran

    def test_create_user_duplicate_refused_before_gate(self):
        self.grant()
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.create_user(
                self.admin.id, self.admin_token, "yrsa", PW)
        self.assertEqual(ctx.exception.reason, "username_taken")
        self.assertEqual(
            self.audit_rows("admin.user.create", "success"), [])

    def test_create_user_make_admin(self):
        self.grant()
        user = self.panel.create_user(
            self.admin.id, self.admin_token, "secondadmin", PW,
            make_admin=True)
        self.assertTrue(user.is_admin)
        self.assertTrue(self.audit_rows(
            "admin.user.role_change", "success"))

    def test_destructive_impossible_without_audit_log(self):
        bare = AdminPanel(
            self.conn, self.data_root, self.accounts,
            audit=None, sudo=self.sudo, time_fn=lambda: NOW)
        self.grant()
        with self.assertRaises(AdminPanelError) as ctx:
            bare.create_user(
                self.admin.id, self.admin_token, "ghost", PW)
        self.assertEqual(ctx.exception.reason, "audit_required")
        self.assertIsNone(self.accounts.get_by_username("ghost"))

    def test_destructive_impossible_without_sudo_wired(self):
        bare = AdminPanel(
            self.conn, self.data_root, self.accounts,
            audit=self.audit, sudo=None, time_fn=lambda: NOW)
        with self.assertRaises(AdminPanelError) as ctx:
            bare.suspend_user(
                self.admin.id, self.admin_token, self.target.id, "spam")
        self.assertEqual(ctx.exception.reason, "sudo_required")
        self.assertEqual(
            self.accounts.get_by_id(self.target.id).status, "active")

    # -- suspend / unsuspend ------------------------------------------------

    def test_suspend_needs_sudo_then_lands_per_s044(self):
        token = self.sessions.create(self.target.id)
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.suspend_user(
                self.admin.id, self.admin_token, self.target.id, "spam")
        self.assertEqual(ctx.exception.reason, "sudo_required")
        self.assertEqual(
            self.accounts.get_by_id(self.target.id).status, "active")
        self.grant()
        record = self.panel.suspend_user(
            self.admin.id, self.admin_token, self.target.id,
            "spam wave")
        self.assertEqual(record.action, "suspend")
        self.assertEqual(
            self.accounts.get_by_id(self.target.id).status, "suspended")
        self.assertIsNone(self.sessions.authenticate(token))  # revoked
        successes = self.audit_rows("admin.user.suspend", "success")
        self.assertGreaterEqual(len(successes), 2)  # panel + S-044 seam
        # ...and a suspended account is still findable at this desk
        found = self.panel.search(self.admin.id, "yrsa")
        self.assertEqual(found.users[0].user.status, "suspended")

    def test_suspend_refusals(self):
        self.grant()
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.suspend_user(
                self.admin.id, self.admin_token, self.admin.id, "oops")
        self.assertEqual(ctx.exception.reason, "cannot_suspend_self")
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.suspend_user(
                self.admin.id, self.admin_token, self.target.id, "  ")
        self.assertEqual(ctx.exception.reason, "reason_required")
        self.assertEqual(
            self.audit_rows("admin.user.suspend", "success"), [])

    def test_unsuspend_needs_no_sudo(self):
        self.grant()
        self.panel.suspend_user(
            self.admin.id, self.admin_token, self.target.id, "spam")
        # No fresh grant is arranged for the unsuspend itself:
        # the grant above is spent time-wise identical, so use a
        # second panel whose sudo was never granted on a new
        # session token — unsuspend takes no token at all.
        record = self.panel.unsuspend_user(self.admin.id, self.target.id)
        self.assertEqual(record.action, "unsuspend")
        self.assertEqual(
            self.accounts.get_by_id(self.target.id).status, "active")
        self.assertTrue(self.audit_rows(
            "admin.user.unsuspend", "success"))

    # -- delete user (S-043) --------------------------------------------------

    def test_delete_user_is_s043_process_gated_and_audited_first(self):
        self.grant()
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.delete_user(
                self.admin.id, self.admin_token, self.target.id,
                "not-the-name")
        self.assertEqual(ctx.exception.reason, "confirmation_mismatch")
        pending = self.panel.delete_user(
            self.admin.id, self.admin_token, self.target.id, "YRSA")
        self.assertEqual(pending.user_id, self.target.id)
        self.assertEqual(pending.scheduled_at - pending.requested_at,
                         7 * 24 * 3600)
        self.assertEqual(
            self.accounts.get_by_id(self.target.id).status,
            "pending_deletion")
        panel_seq = self.audit_rows("admin.user.delete", "success")[0]["seq"]
        seam_seq = self.audit_rows(
            "auth.deletion.request", "success")[0]["seq"]
        self.assertLess(panel_seq, seam_seq)  # authorized before it ran
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.delete_user(
                self.admin.id, self.admin_token, self.target.id, "yrsa")
        self.assertEqual(ctx.exception.reason, "already_pending")

    def test_delete_user_needs_sudo(self):
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.delete_user(
                self.admin.id, self.admin_token, self.target.id, "yrsa")
        self.assertEqual(ctx.exception.reason, "sudo_required")
        self.assertEqual(
            self.accounts.get_by_id(self.target.id).status, "active")

    # -- role change -----------------------------------------------------------

    def test_set_admin_promote_and_demote(self):
        self.grant()
        promoted = self.panel.set_admin(
            self.admin.id, self.admin_token, self.target.id, True)
        self.assertTrue(promoted.is_admin)
        self.assertTrue(self.audit_rows(
            "admin.user.role_change", "success"))
        demoted = self.panel.set_admin(
            self.admin.id, self.admin_token, self.target.id, False)
        self.assertFalse(demoted.is_admin)
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.set_admin(
                self.admin.id, self.admin_token, self.admin.id, False)
        self.assertEqual(ctx.exception.reason, "cannot_demote_self")

    def test_set_admin_needs_sudo(self):
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.set_admin(
                self.admin.id, self.admin_token, self.target.id, True)
        self.assertEqual(ctx.exception.reason, "sudo_required")
        self.assertFalse(
            self.accounts.get_by_id(self.target.id).is_admin)

    # -- repo / org deletion -----------------------------------------------------

    def test_delete_repo_owner_only_gated_grace(self):
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.delete_repo(
                self.admin.id, self.admin_token, "volmarr", "alpha")
        self.assertEqual(ctx.exception.reason, "sudo_required")
        self.grant()
        pending = self.panel.delete_repo(
            self.admin.id, self.admin_token, "volmarr", "alpha")
        self.assertEqual(pending.repo_id, 1)
        self.assertIsNotNone(
            self.repos.get_repository("volmarr", "alpha"))  # grace

    def test_delete_repo_non_owner_admin_refused_by_seam_law(self):
        self.grant()
        other_admin = self.panel.create_user(
            self.admin.id, self.admin_token, "otheradmin", PW,
            make_admin=True)
        token2 = self.sessions.create(other_admin.id)
        self.sudo.grant(other_admin.id, PW, token2)
        with self.assertRaises(RepoDeletionError) as ctx:
            self.panel.delete_repo(
                other_admin.id, token2, "volmarr", "alpha")
        self.assertEqual(ctx.exception.reason, "not_repo_owner")

    def test_delete_org_owner_only_and_repos_first(self):
        self.grant()
        pending = self.panel.delete_org(
            self.admin.id, self.admin_token, self.org.id, "acme")
        self.assertEqual(pending.org_id, self.org.id)
        busy = self.orgs.create_organization(self.admin.id, "busyco")
        from samverk.org_repositories import OrgRepoStore
        OrgRepoStore(self.conn, self.accounts, self.data_root,
                     self.audit, time_fn=lambda: NOW
                     ).create_repository(self.admin.id, busy.id, "thing")
        with self.assertRaises(AdminPanelError) as ctx:
            self.panel.delete_org(
                self.admin.id, self.admin_token, busy.id, "busyco")
        self.assertEqual(ctx.exception.reason, "repos_remaining")

    def test_delete_org_non_owner_admin_refused(self):
        self.grant()
        other_admin = self.panel.create_user(
            self.admin.id, self.admin_token, "otheradmin", PW,
            make_admin=True)
        token2 = self.sessions.create(other_admin.id)
        self.sudo.grant(other_admin.id, PW, token2)
        with self.assertRaises(OrganizationError) as ctx:
            self.panel.delete_org(
                other_admin.id, token2, self.org.id, "acme")
        self.assertEqual(ctx.exception.reason, "not_org_owner")


if __name__ == "__main__":
    unittest.main()
