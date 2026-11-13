"""S-309 acceptance battery: audit log UI.

Acceptance (roadmap S-309): Audit log UI --
repo, org, and instance views over S-007's
chain, filterable, exportable, with chain
verification status shown.

The centre is samverk/audit_log_ui.py: one
gathered read over S-007's hash-chained
audit_log at three scopes -- a repository
(S-054 can_read door, uniform repo_not_found),
an organization (S-186 membership judged by
pure read, uniform org_not_found), and the
instance (site admins only, uniform
audit_not_found) -- with pure filter law
(action / outcome / actor / target kind /
time window / query / limit, unknown action
refused filter_invalid), JSON and CSV export
through the same doors and filters, S-007's
verify_chain recomputed on every view and its
status standing in the data and on the page,
and audit_audit_log_ui re-proving the rows.
No migration (schema 127 stands); taxonomy
unmoved at 135 (33 auth / 89 repo / 13 admin)
-- a gathered read emits no event, and the
battery proves the audit log does not move
and the read writes nothing.

Counted with: python3 -m unittest tests.test_audit_log_ui
"""
from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.audit_log_ui import (
    AuditLogUIError, AuditLogUIStore, ChainStatus,
    audit_audit_log_ui, decide_chain_status,
    decide_filter_match, decide_scope_belongs,
    event_summary, export_audit_view,
    render_audit_log_page)
from samverk.db import schema_version
from samverk.org_repositories import OrgRepoStore
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import OrganizationStore
from samverk.repositories import RepositoryStore

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def _filters(**over):
    base = {"action": None, "outcome": None, "actor_id": None,
            "target_kind": None, "since": None, "until": None,
            "query": None, "limit": None}
    base.update(over)
    return base


class PureLawTests(unittest.TestCase):
    def test_scope_belongs_repo_exact(self):
        self.assertTrue(decide_scope_belongs(
            "repo", "crew/alpha", "repo", "crew/alpha"))
        self.assertTrue(decide_scope_belongs(
            "repo", "crew/alpha", "repo", "crew/alpha#3"))
        self.assertFalse(decide_scope_belongs(
            "repo", "crew/alpha", "repo", "crew/alpha2"))
        self.assertFalse(decide_scope_belongs(
            "repo", "crew/alpha", "organization", "crew/alpha"))
        self.assertFalse(decide_scope_belongs(
            "repo", "crew/alpha", "repo", None))

    def test_scope_belongs_org_segments(self):
        self.assertTrue(decide_scope_belongs(
            "org", "crew", "organization", "crew"))
        self.assertTrue(decide_scope_belongs(
            "org", "crew", "repo", "crew/alpha"))
        self.assertFalse(decide_scope_belongs(
            "org", "crew", "repo", "crew2/alpha"))
        self.assertFalse(decide_scope_belongs(
            "org", "crew", "organization", "crew2"))

    def test_scope_belongs_instance_and_unknown(self):
        self.assertTrue(decide_scope_belongs(
            "instance", None, "repo", "anything/at-all"))
        self.assertTrue(decide_scope_belongs(
            "instance", None, "user", None))
        self.assertFalse(decide_scope_belongs(
            "sideways", "crew", "repo", "crew/alpha"))

    def test_filter_match_conditions(self):
        row = dict(action="repo.push", outcome="success",
                   actor_id=7, actor_username="yrsa",
                   target_kind="repo", target_id="crew/alpha",
                   detail_text='{"refs":["main"]}', ts=T0 + 50)
        self.assertTrue(decide_filter_match(**row, filters=_filters()))
        self.assertTrue(decide_filter_match(
            **row, filters=_filters(action="repo.push")))
        self.assertFalse(decide_filter_match(
            **row, filters=_filters(action="repo.create")))
        self.assertFalse(decide_filter_match(
            **row, filters=_filters(outcome="failure")))
        self.assertFalse(decide_filter_match(
            **row, filters=_filters(actor_id=8)))
        self.assertFalse(decide_filter_match(
            **row, filters=_filters(target_kind="organization")))
        self.assertTrue(decide_filter_match(
            **row, filters=_filters(since=T0, until=T0 + 50)))
        self.assertFalse(decide_filter_match(
            **row, filters=_filters(since=T0 + 51)))
        self.assertFalse(decide_filter_match(
            **row, filters=_filters(until=T0 + 49)))
        self.assertTrue(decide_filter_match(
            **row, filters=_filters(query="MAIN")))
        self.assertTrue(decide_filter_match(
            **row, filters=_filters(query="yrsa")))
        self.assertFalse(decide_filter_match(
            **row, filters=_filters(query="no-such-text")))

    def test_chain_status_words(self):
        ok = ChainStatus(ok=True, first_bad_seq=None, entries_checked=3)
        self.assertEqual(ok.status, "verified")
        self.assertIn("Chain verified: 3 entries checked", ok.words())
        broken = ChainStatus(ok=False, first_bad_seq=2, entries_checked=1)
        self.assertEqual(broken.status, "broken")
        self.assertIn("Chain broken at entry 2", broken.words())
        self.assertEqual(decide_chain_status(True, None, 0), "verified")
        self.assertEqual(decide_chain_status(False, 1, 0), "broken")

    def test_chain_status_refuses_non_bool(self):
        with self.assertRaises(AuditLogUIError) as ctx:
            decide_chain_status("yes", None, 0)
        self.assertEqual(ctx.exception.reason, "chain_status_invalid")

    def test_event_summary_plain_words(self):
        words = event_summary(
            "repo.push", "repo", "crew/alpha", "yrsa", "success")
        self.assertIn("yrsa", words)
        self.assertIn("repo push", words)
        self.assertIn("crew/alpha", words)
        self.assertIn("success", words)


class AuditLogUITests(unittest.TestCase):
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
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.orgs = OrganizationStore(
            self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.org = self.orgs.create_organization(self.creator.id, "crew")
        self.members = OrgMembershipStore(
            self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.members.add_member(self.creator.id, self.org.id, self.member.id)
        self.org_repos = OrgRepoStore(
            self.conn, self.accounts, self.root, self.audit,
            time_fn=self.clock)
        self.alpha = self.org_repos.create_repository(
            self.creator.id, self.org.id, "alpha", visibility="public")
        self.beta = self.org_repos.create_repository(
            self.creator.id, self.org.id, "beta", visibility="private")
        self.solo = self.repos.create_repository(
            self.creator.id, "volmarr", "solo", visibility="public")
        self.ui = AuditLogUIStore(
            self.conn, self.repos, self.accounts, time_fn=self.clock)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(AuditLogUIError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _append(self, action, target_kind, target_id, detail=None,
                actor=None, outcome="success"):
        return self.audit.append(
            actor_kind="user",
            actor_id=(actor.id if actor is not None else self.creator.id),
            action=action, target_kind=target_kind,
            target_id=target_id, outcome=outcome, detail=detail)

    def _rows(self):
        return self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]

    def seed_events(self):
        self._append("repo.push", "repo", "crew/alpha",
                     detail={"refs": ["main"]}, actor=self.member)
        self._append("repo.issue.create", "repo", "crew/alpha#3",
                     actor=self.member)
        self._append("repo.push", "repo", "crew/beta",
                     outcome="failure")
        self._append("repo.push", "repo", "volmarr/solo")
        self._append("auth.login.success", "user", "volmarr",
                     actor=self.member)

    # -- repo view ----------------------------------------------------

    def test_repo_view_gathers_repo_rows(self):
        self.seed_events()
        view = self.ui.repo_view(self.creator, "crew", "alpha")
        self.assertEqual(view.scope, "repo")
        self.assertEqual(view.scope_name, "crew/alpha")
        actions = [e.action for e in view.entries]
        self.assertIn("repo.push", actions)
        self.assertIn("repo.issue.create", actions)
        self.assertNotIn("auth.login.success", actions)
        targets = {e.target_id for e in view.entries}
        self.assertNotIn("crew/beta", targets)
        self.assertNotIn("volmarr/solo", targets)
        self.assertEqual(view.total_in_scope, view.shown)
        push = [e for e in view.entries if e.action == "repo.push"][0]
        self.assertEqual(push.actor_username, "yrsa")
        self.assertEqual(push.detail, {"refs": ["main"]})
        self.assertTrue(push.entry_hash)
        self.assertIn("crew/alpha", push.summary)

    def test_repo_view_public_repo_open_to_anonymous(self):
        self.seed_events()
        view = self.ui.repo_view(None, "crew", "alpha")
        self.assertGreaterEqual(view.shown, 1)

    def test_repo_view_private_repo_stranger_not_found(self):
        self.seed_events()
        self.assertEqual(
            self._reason(self.ui.repo_view, self.stranger, "crew", "beta"),
            "repo_not_found")
        self.assertEqual(
            self._reason(self.ui.repo_view, None, "crew", "beta"),
            "repo_not_found")
        # S-054's door is the whole law here: even the
        # organization's owner does not pass it for an
        # org-owned private repository (owner_lower is
        # the org), so they hear the same uniform word;
        # a site admin still reads it.
        self.assertEqual(
            self._reason(self.ui.repo_view, self.creator, "crew", "beta"),
            "repo_not_found")
        self.assertGreaterEqual(
            self.ui.repo_view(self.admin, "crew", "beta").shown, 1)

    def test_repo_view_missing_repo_not_found(self):
        self.assertEqual(
            self._reason(self.ui.repo_view, self.creator, "crew", "ghost"),
            "repo_not_found")

    # -- org view -------------------------------------------------------

    def test_org_view_gathers_org_and_its_repos(self):
        self.seed_events()
        view = self.ui.org_view(self.member, "crew")
        targets = {e.target_id for e in view.entries}
        self.assertIn("crew", targets)
        self.assertIn("crew/alpha", targets)
        self.assertIn("crew/beta", targets)
        self.assertNotIn("volmarr/solo", targets)
        self.assertNotIn("volmarr", targets)

    def test_org_view_member_owner_admin_and_stranger(self):
        self.assertGreaterEqual(self.ui.org_view(self.member, "crew").shown, 1)
        self.assertGreaterEqual(
            self.ui.org_view(self.creator, "crew").shown, 1)
        self.assertGreaterEqual(self.ui.org_view(self.admin, "crew").shown, 1)
        self.assertEqual(
            self._reason(self.ui.org_view, self.stranger, "crew"),
            "org_not_found")
        self.assertEqual(
            self._reason(self.ui.org_view, None, "crew"), "org_not_found")
        self.assertEqual(
            self._reason(self.ui.org_view, self.admin, "ghostorg"),
            "org_not_found")

    # -- instance view ---------------------------------------------------

    def test_instance_view_admin_only_and_complete(self):
        self.seed_events()
        view = self.ui.instance_view(self.admin)
        self.assertEqual(view.scope, "instance")
        self.assertEqual(view.total_in_scope, self._rows())
        self.assertEqual(view.shown, self._rows())
        self.assertEqual(
            self._reason(self.ui.instance_view, self.creator),
            "audit_not_found")
        self.assertEqual(
            self._reason(self.ui.instance_view, None), "audit_not_found")

    # -- chain status ------------------------------------------------------

    def test_chain_status_verified_on_views(self):
        self.seed_events()
        view = self.ui.instance_view(self.admin)
        self.assertTrue(view.chain.ok)
        self.assertEqual(view.chain.status, "verified")
        self.assertEqual(view.chain.entries_checked, self._rows())
        self.assertIn("Chain verified", view.headline_words)

    def test_chain_status_broken_is_shown(self):
        self.seed_events()
        with self.conn:
            self.conn.execute(
                "UPDATE audit_log SET outcome = 'tampered'"
                " WHERE seq = 2")
        ok, bad, _ = verify_chain(self.conn)
        self.assertFalse(ok)
        view = self.ui.instance_view(self.admin)
        self.assertFalse(view.chain.ok)
        self.assertEqual(view.chain.status, "broken")
        self.assertEqual(view.chain.first_bad_seq, bad)
        page = render_audit_log_page(view)
        self.assertIn("Chain broken at entry", page)

    # -- filters -----------------------------------------------------------

    def test_filter_by_action_outcome_actor(self):
        self.seed_events()
        view = self.ui.instance_view(self.admin, action="repo.push")
        self.assertTrue(view.entries)
        self.assertTrue(
            all(e.action == "repo.push" for e in view.entries))
        failed = self.ui.instance_view(self.admin, outcome="failure")
        self.assertEqual([e.target_id for e in failed.entries],
                         ["crew/beta"])
        by_member = self.ui.instance_view(
            self.admin, actor_id=self.member.id)
        self.assertTrue(by_member.entries)
        self.assertTrue(
            all(e.actor_id == self.member.id for e in by_member.entries))

    def test_filter_by_target_kind_and_window_and_query(self):
        self.seed_events()
        repos_only = self.ui.instance_view(
            self.admin, target_kind="repo")
        self.assertTrue(
            all(e.target_kind == "repo" for e in repos_only.entries))
        window = self.ui.instance_view(
            self.admin, since=T0, until=T0)
        self.assertEqual(window.shown, window.total_in_scope)
        none = self.ui.instance_view(self.admin, since=T0 + 10_000)
        self.assertEqual(none.shown, 0)
        found = self.ui.instance_view(self.admin, query="crew/beta")
        self.assertTrue(found.entries)
        self.assertTrue(
            all(e.target_id == "crew/beta" for e in found.entries))
        detail_hit = self.ui.instance_view(self.admin, query="main")
        self.assertTrue(
            any(e.action == "repo.push" and e.target_id == "crew/alpha"
                for e in detail_hit.entries))

    def test_filter_limit_and_invalid_filters(self):
        self.seed_events()
        limited = self.ui.instance_view(self.admin, limit=2)
        self.assertEqual(limited.shown, 2)
        self.assertGreater(limited.total_in_scope, 2)
        self.assertEqual(
            self._reason(self.ui.instance_view, self.admin,
                         action="repo.nope"),
            "filter_invalid")
        self.assertEqual(
            self._reason(self.ui.instance_view, self.admin,
                         since=T0 + 5, until=T0),
            "filter_invalid")
        self.assertEqual(
            self._reason(self.ui.instance_view, self.admin, limit=0),
            "filter_invalid")
        self.assertEqual(
            self._reason(self.ui.instance_view, self.admin,
                         limit=1001),
            "filter_invalid")
        self.assertEqual(
            self._reason(self.ui.instance_view, self.admin, actor_id=0),
            "filter_invalid")

    def test_filters_never_widen_scope(self):
        self.seed_events()
        view = self.ui.repo_view(
            self.creator, "crew", "alpha", query="crew")
        self.assertTrue(
            all((e.target_id or "").startswith("crew/alpha")
                for e in view.entries))

    # -- export --------------------------------------------------------------

    def test_export_json_round_trip(self):
        self.seed_events()
        text = self.ui.export_repo(self.creator, "crew", "alpha", "json")
        data = json.loads(text)
        self.assertEqual(data["scope"], "repo")
        self.assertEqual(data["scope_name"], "crew/alpha")
        self.assertEqual(data["chain"]["status"], "verified")
        self.assertEqual(len(data["entries"]), data["shown"])
        self.assertIn("entry_hash", data["entries"][0])

    def test_export_csv_shape(self):
        self.seed_events()
        text = self.ui.export_instance(self.admin, "csv")
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0][0], "seq")
        self.assertIn("entry_hash", rows[0])
        self.assertEqual(len(rows) - 1, self._rows())
        push = [r for r in rows[1:] if r[5] == "repo.push"]
        self.assertTrue(push)

    def test_export_respects_doors_filters_and_format(self):
        self.seed_events()
        self.assertEqual(
            self._reason(self.ui.export_repo,
                         self.stranger, "crew", "beta", "json"),
            "repo_not_found")
        self.assertEqual(
            self._reason(self.ui.export_instance, self.creator, "json"),
            "audit_not_found")
        text = self.ui.export_instance(
            self.admin, "json", action="repo.push")
        data = json.loads(text)
        self.assertTrue(data["entries"])
        self.assertTrue(
            all(e["action"] == "repo.push" for e in data["entries"]))
        view = self.ui.instance_view(self.admin)
        self.assertEqual(
            self._reason(export_audit_view, view, "xml"),
            "export_format_invalid")

    # -- rendering -------------------------------------------------------------

    def test_render_page_states_chain_counts_and_entries(self):
        self.seed_events()
        view = self.ui.org_view(self.member, "crew")
        page = render_audit_log_page(view)
        self.assertIn("Audit log for crew", page)
        self.assertIn("Chain verified", page)
        self.assertIn("recorded in the audit log", page)
        self.assertIn("Recorded as", page)
        self.assertIn("repo push", page)

    def test_render_escapes_values(self):
        self._append("repo.settings.change", "repo", "crew/alpha",
                     detail={"note": "<script>alert(1)</script>"})
        view = self.ui.repo_view(self.creator, "crew", "alpha",
                                 query="script")
        page = render_audit_log_page(view)
        self.assertNotIn("<script>alert(1)</script>", page)

    def test_empty_view_honest_words(self):
        view = self.ui.repo_view(self.creator, "volmarr", "solo",
                                 action="repo.delete")
        self.assertEqual(view.shown, 0)
        page = render_audit_log_page(view)
        self.assertIn("No audit entries match", page)

    # -- honesty: pins, no writes, audit re-proof --------------------------------

    def test_no_migration_no_new_taxonomy_event(self):
        self.assertEqual(schema_version(self.conn), 127)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        counts = (len(taxonomy.AUTH_EVENTS), len(taxonomy.REPO_EVENTS),
                  len(taxonomy.ADMIN_EVENTS))
        self.assertEqual(counts, (33, 89, 13))

    def test_reads_write_nothing_and_audit_nothing(self):
        self.seed_events()
        before = self._rows()
        members_before = self.conn.execute(
            "SELECT COUNT(*) c FROM organization_members").fetchone()["c"]
        self.ui.repo_view(self.creator, "crew", "alpha")
        self.ui.org_view(self.member, "crew")
        self.ui.instance_view(self.admin)
        self.ui.export_instance(self.admin, "csv")
        render_audit_log_page(self.ui.org_view(self.admin, "crew"))
        self.assertEqual(self._rows(), before)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) c FROM organization_members"
            ).fetchone()["c"],
            members_before)

    def test_audit_reproof_clean_and_catches_damage(self):
        self.seed_events()
        self.assertEqual(audit_audit_log_ui(self.conn), [])
        with self.conn:
            self.conn.execute(
                "UPDATE audit_log SET entry_hash = '' WHERE seq = 1")
        problems = audit_audit_log_ui(self.conn)
        self.assertTrue(any("hash" in p for p in problems))

    def test_to_dict_shape(self):
        self.seed_events()
        view = self.ui.repo_view(self.creator, "crew", "alpha")
        data = view.to_dict()
        self.assertEqual(data["scope"], "repo")
        self.assertEqual(data["total_in_scope"], view.total_in_scope)
        self.assertEqual(data["chain"]["entries_checked"], self._rows())
        self.assertIn("headline", data)


if __name__ == "__main__":
    unittest.main()
