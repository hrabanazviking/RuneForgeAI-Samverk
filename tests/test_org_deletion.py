"""S-199 acceptance battery: org deletion.

Acceptance (roadmap S-199): Org deletion -- owner-only,
sudo mode, inventory + grace as S-043; repos must be
transferred or deleted explicitly first.

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
from samverk.org_audit_log import OrgAuditLogStore
from samverk.org_deletion import (
    GRACE_SECONDS, OrgDeletionStore, decide_execution,
    decide_request, render_org_deletion_page)
from samverk.org_repositories import OrgRepoStore
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import (
    OrganizationError, OrganizationStore, settings_areas)


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class OrgDeletionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.creator = self.accounts.register(
            "volmarr", "correct horse battery")
        self.member = self.accounts.register(
            "yrsa", "correct horse battery")
        self.outsider = self.accounts.register(
            "freya", "correct horse battery")
        self.admin = self.accounts.register(
            "sitemod", "correct horse battery")
        with self.conn:
            self.conn.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?",
                (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.orgs = OrganizationStore(
            self.conn, self.accounts, self.audit,
            time_fn=self.clock)
        self.org = self.orgs.create_organization(
            self.creator.id, "crew")
        self.members = OrgMembershipStore(
            self.conn, self.accounts, self.audit,
            time_fn=self.clock)
        self.members.add_member(
            self.creator.id, self.org.id, self.member.id)
        self.repos = OrgRepoStore(
            self.conn, self.accounts, self.root,
            self.audit, time_fn=self.clock)
        self.deletion = OrgDeletionStore(
            self.conn, self.accounts, self.audit,
            time_fn=self.clock)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _yes(self, user_id):
        return True

    def _no(self, user_id):
        return False

    def _audit_rows(self, action=None):
        if action is None:
            return self.conn.execute(
                "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        return self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE action = ?",
            (action,)).fetchone()["c"]

    def _danger_actions(self):
        rows = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action = 'auth.organization.update'"
            " ORDER BY seq").fetchall()
        import json
        out = []
        for row in rows:
            try:
                detail = json.loads(row["detail"] or "{}")
            except ValueError:
                continue
            if detail.get("fields") == "danger":
                out.append(detail.get("action"))
        return out

    def _request(self, **kwargs):
        kwargs.setdefault("typed_confirmation", "crew")
        kwargs.setdefault("reauth_verifier", self._yes)
        return self.deletion.request(
            self.creator.id, self.org.id, **kwargs)

    # pure decision functions
    def test_decide_request_order(self):
        self.assertEqual(
            decide_request("member", False, 0, True, True),
            "not_org_owner")
        self.assertEqual(
            decide_request(None, False, 0, True, True),
            "not_org_owner")
        self.assertEqual(
            decide_request("owner", True, 0, True, True),
            "already_pending")
        self.assertEqual(
            decide_request("owner", False, 2, True, True),
            "repos_remaining")
        self.assertEqual(
            decide_request("owner", False, 0, False, True),
            "confirmation_mismatch")
        self.assertEqual(
            decide_request("owner", False, 0, True, False),
            "sudo_required")
        self.assertIsNone(
            decide_request("owner", False, 0, True, True))

    def test_decide_execution_pure(self):
        self.assertFalse(decide_execution(False, 10, None, 0))
        self.assertFalse(decide_execution(True, 9, 10, 0))
        self.assertFalse(decide_execution(True, 10, 10, 1))
        self.assertTrue(decide_execution(True, 10, 10, 0))
        self.assertTrue(decide_execution(True, 11, 10, 0))

    # inventory
    def test_inventory_empty_org(self):
        inv = self.deletion.inventory(self.org.id)
        self.assertEqual(inv.org_name, "crew")
        self.assertEqual(inv.repositories, 0)
        self.assertEqual(inv.repository_names, ())
        self.assertEqual(inv.counts["organization_members"], 2)
        self.assertEqual(inv.owners, 1)
        self.assertEqual(inv.counts["teams"], 0)
        self.assertEqual(inv.pending_invitations, 0)
        self.assertEqual(inv.total, 2)

    def test_inventory_counts_everything(self):
        repo = self.repos.create_repository(
            self.creator.id, self.org.id, "anvil")
        self.repos.create_repository(
            self.creator.id, self.org.id, "forge")
        now = int(self.clock())
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO teams (org_id, name, name_lower,"
                " description, privacy, created_by, created_at,"
                " updated_at) VALUES (?, 'Core', 'core', NULL,"
                " 'visible', ?, ?, ?)",
                (self.org.id, self.creator.id, now, now))
            team_id = int(cur.lastrowid)
            self.conn.execute(
                "INSERT INTO team_members (team_id, user_id,"
                " added_by, created_at) VALUES (?, ?, ?, ?)",
                (team_id, self.member.id, self.creator.id, now))
            self.conn.execute(
                "INSERT INTO team_repositories (team_id, repo_id,"
                " added_by, created_at, permission)"
                " VALUES (?, ?, ?, ?, 'read')",
                (team_id, repo.id, self.creator.id, now))
            self.conn.execute(
                "INSERT INTO outside_collaborators (repo_id,"
                " user_id, role, granted_by, created_at,"
                " updated_at) VALUES (?, ?, 'read', ?, ?, ?)",
                (repo.id, self.outsider.id,
                 self.creator.id, now, now))
            self.conn.execute(
                "INSERT INTO org_invitations (org_id,"
                " invitee_user_id, invitee_email,"
                " invitee_email_lower, role, invited_by,"
                " status, created_at, expires_at, resolved_at)"
                " VALUES (?, ?, NULL, NULL, 'member', ?,"
                " 'pending', ?, ?, NULL)",
                (self.org.id, self.outsider.id,
                 self.creator.id, now, now + 1000))
            self.conn.execute(
                "INSERT INTO org_repo_policies (org_id,"
                " who_may_create, allowed_visibilities, set_by,"
                " created_at, updated_at) VALUES (?, 'owners',"
                " 'public,private', ?, ?, ?)",
                (self.org.id, self.creator.id, now, now))
        inv = self.deletion.inventory(self.org.id)
        self.assertEqual(inv.repositories, 2)
        self.assertEqual(inv.repository_names, ("anvil", "forge"))
        self.assertEqual(inv.counts["teams"], 1)
        self.assertEqual(inv.counts["team_members"], 1)
        self.assertEqual(inv.counts["team_repositories"], 1)
        self.assertEqual(inv.counts["outside_collaborators"], 1)
        self.assertEqual(inv.counts["org_invitations"], 1)
        self.assertEqual(inv.pending_invitations, 1)
        self.assertEqual(inv.counts["org_repo_policies"], 1)

    def test_inventory_unknown_org(self):
        self.assertEqual(
            self._reason(self.deletion.inventory, 424242),
            "org_not_found")

    # request guards
    def test_request_happy_schedules_grace(self):
        pending = self._request()
        self.assertEqual(pending.org_id, self.org.id)
        self.assertEqual(pending.requested_by, self.creator.id)
        self.assertEqual(pending.requested_at, int(self.clock()))
        self.assertEqual(
            pending.scheduled_at,
            int(self.clock()) + GRACE_SECONDS)
        self.assertEqual(GRACE_SECONDS, 7 * 24 * 3600)
        self.assertTrue(self.deletion.is_pending(self.org.id))
        # Nothing is destroyed inside grace.
        self.assertIsNotNone(self.orgs.get_by_id(self.org.id))
        self.assertEqual(self._danger_actions(), ["request_deletion"])

    def test_request_owner_only(self):
        for actor in (self.member.id, self.outsider.id,
                      self.admin.id):
            self.assertEqual(
                self._reason(
                    self.deletion.request, actor, self.org.id,
                    "crew", self._yes),
                "not_org_owner", actor)
        self.assertFalse(self.deletion.is_pending(self.org.id))

    def test_request_unknown_actor_and_org(self):
        self.assertEqual(
            self._reason(
                self.deletion.request, 999999, self.org.id,
                "crew", self._yes),
            "no_such_user")
        self.assertEqual(
            self._reason(
                self.deletion.request, self.creator.id, 424242,
                "crew", self._yes),
            "org_not_found")

    def test_request_blocked_by_repos(self):
        self.repos.create_repository(
            self.creator.id, self.org.id, "anvil")
        before = self._audit_rows()
        with self.assertRaises(OrganizationError) as ctx:
            self._request()
        self.assertEqual(ctx.exception.reason, "repos_remaining")
        self.assertIn("anvil", str(ctx.exception))
        self.assertIn("explicitly", str(ctx.exception))
        self.assertFalse(self.deletion.is_pending(self.org.id))
        self.assertEqual(self._audit_rows(), before)

    def test_request_unblocked_after_repo_removed(self):
        repo = self.repos.create_repository(
            self.creator.id, self.org.id, "anvil")
        self.assertEqual(
            self._reason(self._request), "repos_remaining")
        # The repository's own explicit end state (S-056/S-057
        # are its processes): its row is gone.
        with self.conn:
            self.conn.execute(
                "DELETE FROM repositories WHERE id = ?",
                (repo.id,))
        pending = self._request()
        self.assertEqual(pending.org_id, self.org.id)

    def test_request_confirmation_mismatch(self):
        for bad in ("cre", "crew2", "", None, 42):
            self.assertEqual(
                self._reason(
                    self.deletion.request, self.creator.id,
                    self.org.id, bad, self._yes),
                "confirmation_mismatch", bad)
        self.assertFalse(self.deletion.is_pending(self.org.id))
        # Case and surrounding space do not matter (S-043 law).
        pending = self.deletion.request(
            self.creator.id, self.org.id, "  CREW ", self._yes)
        self.assertEqual(pending.org_id, self.org.id)

    def test_request_sudo_required(self):
        self.assertEqual(
            self._reason(
                self.deletion.request, self.creator.id,
                self.org.id, "crew", None),
            "sudo_required")
        self.assertEqual(
            self._reason(
                self.deletion.request, self.creator.id,
                self.org.id, "crew", self._no),
            "sudo_required")
        self.assertFalse(self.deletion.is_pending(self.org.id))

    def test_request_already_pending(self):
        self._request()
        self.assertEqual(
            self._reason(self._request), "already_pending")

    def test_request_uses_real_sudo_verifier(self):
        # The S-036 seam fulfilled: a fresh SudoMode grant is
        # the verifier, exactly as S-030/S-035 consume it.
        from samverk.sudo_mode import SudoMode
        sudo = SudoMode(
            self.conn, self.accounts, time_fn=self.clock)
        sudo.grant(
            self.creator.id, "correct horse battery", "sess-1")
        pending = self.deletion.request(
            self.creator.id, self.org.id, "crew",
            sudo.as_verifier("sess-1"))
        self.assertEqual(pending.org_id, self.org.id)
        self.assertEqual(
            self._reason(
                self.deletion.request, self.creator.id,
                self.org.id, "crew", sudo.as_verifier("other")),
            "already_pending")

    # cancel
    def test_cancel_restores_whole(self):
        self._request()
        self.assertTrue(
            self.deletion.cancel(self.creator.id, self.org.id))
        self.assertFalse(self.deletion.is_pending(self.org.id))
        self.assertIsNotNone(self.orgs.get_by_id(self.org.id))
        self.assertEqual(
            self._danger_actions(),
            ["request_deletion", "cancel_deletion"])
        # A fresh request may be made after a cancel.
        self._request()
        self.assertTrue(self.deletion.is_pending(self.org.id))

    def test_cancel_without_pending_is_false(self):
        self.assertFalse(
            self.deletion.cancel(self.creator.id, self.org.id))

    def test_cancel_owner_only(self):
        self._request()
        self.assertEqual(
            self._reason(
                self.deletion.cancel, self.member.id, self.org.id),
            "not_org_owner")
        self.assertTrue(self.deletion.is_pending(self.org.id))

    # execution
    def test_finalize_before_grace_destroys_nothing(self):
        self._request()
        self.assertFalse(self.deletion.finalize(self.org.id))
        self.assertIsNotNone(self.orgs.get_by_id(self.org.id))
        self.assertEqual(self.deletion.execute_due(), [])

    def test_finalize_after_grace_deletes_cascade(self):
        now = int(self.clock())
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO teams (org_id, name, name_lower,"
                " description, privacy, created_by, created_at,"
                " updated_at) VALUES (?, 'Core', 'core', NULL,"
                " 'visible', ?, ?, ?)",
                (self.org.id, self.creator.id, now, now))
            team_id = int(cur.lastrowid)
            self.conn.execute(
                "INSERT INTO team_members (team_id, user_id,"
                " added_by, created_at) VALUES (?, ?, ?, ?)",
                (team_id, self.member.id, self.creator.id, now))
            self.conn.execute(
                "INSERT INTO org_invitations (org_id,"
                " invitee_user_id, invitee_email,"
                " invitee_email_lower, role, invited_by,"
                " status, created_at, expires_at, resolved_at)"
                " VALUES (?, ?, NULL, NULL, 'member', ?,"
                " 'pending', ?, ?, NULL)",
                (self.org.id, self.outsider.id,
                 self.creator.id, now, now + 1000))
            self.conn.execute(
                "INSERT INTO team_mention_notifications (org_id,"
                " team_id, mention, recipient_id, actor_id,"
                " source_kind, repo_id, number, comment_id,"
                " pull_request_id, reason, created_at) VALUES"
                " (?, ?, '@crew/core', ?, ?, 'issue', 1, 1, 0,"
                " 0, 'mention', ?)",
                (self.org.id, team_id, self.member.id,
                 self.creator.id, now))
            self.conn.execute(
                "INSERT INTO org_default_permissions (org_id,"
                " role, set_by, created_at, updated_at)"
                " VALUES (?, 'read', ?, ?, ?)",
                (self.org.id, self.creator.id, now, now))
        audit_before = self._audit_rows()
        self._request()
        self.clock.now += GRACE_SECONDS
        self.assertEqual(
            self.deletion.execute_due(), [self.org.id])
        self.assertIsNone(self.orgs.get_by_id(self.org.id))
        self.assertFalse(self.deletion.is_pending(self.org.id))
        for table in (
                "organization_members", "teams", "team_members",
                "org_invitations", "team_mention_notifications",
                "org_default_permissions", "org_deletions"):
            count = self.conn.execute(
                f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
            self.assertEqual(count, 0, table)
        # The audit log survives: it is the witness.
        self.assertGreater(self._audit_rows(), audit_before)
        self.assertEqual(
            self._danger_actions(),
            ["request_deletion", "execute_deletion"])
        # The name is free again after execution.
        again = self.orgs.create_organization(
            self.creator.id, "crew")
        self.assertEqual(again.name_lower, "crew")

    def test_finalize_blocked_by_repo_arriving_in_grace(self):
        self._request()
        self.repos.create_repository(
            self.creator.id, self.org.id, "late")
        self.clock.now += GRACE_SECONDS
        self.assertFalse(self.deletion.finalize(self.org.id))
        self.assertEqual(self.deletion.execute_due(), [])
        self.assertIsNotNone(self.orgs.get_by_id(self.org.id))
        self.assertTrue(self.deletion.is_pending(self.org.id))

    def test_execute_due_only_due_orgs(self):
        other = self.orgs.create_organization(
            self.creator.id, "fleet")
        self._request()
        self.deletion.request(
            self.creator.id, other.id, "fleet", self._yes)
        self.clock.now += GRACE_SECONDS - 10
        self.assertEqual(self.deletion.execute_due(), [])
        self.clock.now += 10
        self.assertEqual(
            sorted(self.deletion.execute_due()),
            sorted([self.org.id, other.id]))

    # page and settings home
    def test_render_page_inventory_and_block(self):
        self.repos.create_repository(
            self.creator.id, self.org.id, "anvil")
        inv = self.deletion.inventory(self.org.id)
        html = render_org_deletion_page(
            self.orgs.get_by_id(self.org.id), inv)
        self.assertIn("Delete crew", html)
        self.assertIn("1 repository", html)
        self.assertIn("anvil", html)
        self.assertIn("explicitly first", html)
        self.assertIn("7-day grace", html)

    def test_render_page_escapes_and_pending(self):
        org = self.orgs.create_organization(
            self.creator.id, "fleet",
            display_name="Fleet <b>Bold</b>")
        pending = self.deletion.request(
            self.creator.id, org.id, "fleet", self._yes)
        inv = self.deletion.inventory(org.id)
        html = render_org_deletion_page(org, inv, pending)
        self.assertNotIn("<b>Bold</b>", html)
        self.assertIn("&lt;b&gt;", html)
        self.assertIn("Deletion is scheduled for", html)
        self.assertIn("cancel it whole", html)

    def test_settings_home_marks_danger_built(self):
        by_key = {a["key"]: a for a in settings_areas()}
        self.assertTrue(by_key["danger"]["available"])
        self.assertEqual(by_key["danger"]["slice"], "S-199")

    def test_org_audit_log_reads_danger_events(self):
        self._request()
        self.deletion.cancel(self.creator.id, self.org.id)
        log = OrgAuditLogStore(
            self.conn, self.accounts, self.audit,
            time_fn=self.clock)
        entries = log.list_events(self.creator.id, self.org.id)
        danger = [e for e in entries
                  if e.detail.get("fields") == "danger"]
        self.assertEqual(len(danger), 2)
        self.assertTrue(
            all(e.category == "organization" for e in danger))

    # pins
    def test_pins_schema_80_taxonomy_123(self):
        self.assertEqual(schema_version(self.conn), 116)
        self.assertEqual(db.MIGRATIONS[-1][0], 116)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 88)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        cols = [r["name"] for r in self.conn.execute(
            "PRAGMA table_info(org_deletions)").fetchall()]
        self.assertEqual(
            cols, ["org_id", "requested_by", "requested_at",
                   "scheduled_at"])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for version, statements in db.MIGRATIONS:
                if version > 77:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_meta"
                        " (key, value) VALUES ('version', ?)",
                        (str(version),))
            conn.close()
            conn = db.init_db(path)
            self.assertEqual(db.schema_version(conn), 116)
            names = [r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type = 'table'"
                " AND name = 'org_deletions'").fetchall()]
            self.assertEqual(names, ["org_deletions"])
            conn.close()


if __name__ == "__main__":
    unittest.main()
