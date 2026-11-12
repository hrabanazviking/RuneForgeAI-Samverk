"""S-226 acceptance battery: mention routing.

Acceptance (roadmap S-226): @user and @org/team
mentions create notifications once, never
duplicated by cross-reference echoes.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.cross_references import CrossReferenceStore
from samverk.db import schema_version
from samverk.issues import IssueError, IssueStore
from samverk.mention_routing import (
    MentionRoutingStore, decide_mention_recipients,
    parse_mention_tokens, parse_user_mentions,
    render_mention_deliveries, render_mention_delivery)
from samverk.notification_reasons import NotificationStore
from samverk.organizations import OrganizationStore
from samverk.organization_members import OrgMembershipStore
from samverk.repositories import RepositoryStore
from samverk.teams import TeamStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class MentionRoutingTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.volmarr = self.accounts.register("volmarr", "correct horse battery")
        self.yrsa = self.accounts.register("yrsa", "correct horse battery", "yrsa@example.com")
        self.bryn = self.accounts.register("brynhild", "correct horse battery", "bryn@example.com")
        self.freya = self.accounts.register("freya", "correct horse battery")
        self.mallory = self.accounts.register("mallory", "correct horse battery")
        self.orgs = OrganizationStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.org = self.orgs.create_organization(self.volmarr.id, "crew")
        self.members = OrgMembershipStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.members.add_member(self.volmarr.id, self.org.id, self.yrsa.id)
        self.members.add_member(self.volmarr.id, self.org.id, self.bryn.id)
        self.teams = TeamStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.forge = self.teams.create_team(self.volmarr.id, self.org.id, "Forge")
        self.teams.add_member(self.volmarr.id, self.org.id, self.forge.id, self.yrsa.id)
        self.anvil_crew = self.teams.create_team(
            self.volmarr.id, self.org.id, "Anvil Crew", parent_team_id=self.forge.id)
        self.teams.add_member(self.volmarr.id, self.org.id, self.anvil_crew.id, self.bryn.id)
        self.wardens = self.teams.create_team(
            self.volmarr.id, self.org.id, "Wardens", privacy="secret")
        self.teams.add_member(self.volmarr.id, self.org.id, self.wardens.id, self.yrsa.id)
        self.anvil_id = self._repo("crew", "anvil", "public")
        self.vault_id = self._repo("crew", "vault", "private")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)
        self.router = MentionRoutingStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.inbox = NotificationStore(self.conn, self.accounts, time_fn=self.clock)

    # -- fixtures -------------------------------------------------
    def _repo(self, owner, name, visibility):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                (owner, owner.lower(), name, name.lower(), self.volmarr.id, 1_700_000_000, visibility))
        return int(cur.lastrowid)

    def _issue(self, author, repo_name, title, body):
        return self.issues.create_issue(author, "crew", repo_name, title, body)

    def _raw_issue(self, repo_id, number, author_id, body, kind="issue"):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO issues (repo_id, number, kind, author_id, title, body, state, created_at, updated_at) VALUES (?, ?, ?, ?, 'Vault work', ?, 'open', ?, ?)",
                (repo_id, number, kind, author_id, body, 1_700_000_000, 1_700_000_000))
        return int(cur.lastrowid)

    def _comment(self, issue_id, author_id, body, deleted=False):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO issue_comments (issue_id, author_id, body, created_at, updated_at, deleted_at, deleted_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (issue_id, author_id, body, 1_700_000_000, 1_700_000_000,
                 1_700_000_100 if deleted else None,
                 author_id if deleted else None))
        return int(cur.lastrowid)

    def _set_body(self, issue_row_id, body):
        with self.conn:
            self.conn.execute("UPDATE issues SET body = ? WHERE id = ?", (body, issue_row_id))

    def _notes(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM notifications").fetchone()["n"]

    def _deliveries(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM mention_deliveries").fetchone()["n"]

    def _for(self, user):
        return self.inbox.list_for_recipient(user)

    # -- pins -------------------------------------------------------
    def test_pins_schema_99_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 119)
        self.assertEqual(db.MIGRATIONS[-1][0], 119)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 88)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("mention_deliveries", tables)
        self.assertIn("notifications", tables)

    def test_fresh_database_migrates_to_93(self):
        path = self.root / "fresh.db"
        conn = db.connect(path); self.addCleanup(conn.close)
        self.assertEqual(db.migrate(conn), 119)
        self.assertEqual(db.schema_version(conn), 119)

    # -- pure law -----------------------------------------------------
    def test_parse_tokens_order_dedup_and_kinds(self):
        tokens = parse_mention_tokens("hi @Yrsa and @crew/forge, cc @yrsa @ghost")
        self.assertEqual([(t.kind, t.text) for t in tokens],
                         [("user", "@yrsa"), ("team", "@crew/forge"), ("user", "@ghost")])
        self.assertEqual(parse_user_mentions("hi @Yrsa and @crew/forge"), ["yrsa"])

    def test_parse_tokens_code_email_and_paths_are_not_mentions(self):
        self.assertEqual(parse_mention_tokens("mail volmarr@crew/forge now"), [])
        self.assertEqual(parse_mention_tokens("see x/@yrsa in the path"), [])
        self.assertEqual(parse_mention_tokens("```\n@yrsa\n```"), [])
        self.assertEqual(parse_mention_tokens("quote `@yrsa` inline"), [])
        self.assertEqual(parse_mention_tokens(""), [])
        self.assertEqual(parse_mention_tokens(None), [])
        self.assertEqual(parse_mention_tokens(42), [])

    def test_decide_recipients_dedups_and_removes_actor(self):
        self.assertEqual(decide_mention_recipients([3, 1, 3, 2, 1], 2), (3, 1))
        self.assertEqual(decide_mention_recipients([], 1), ())
        self.assertEqual(decide_mention_recipients([1, 1], None), (1,))

    # -- direct mentions ------------------------------------------------
    def test_direct_mention_creates_one_s223_notification(self):
        issue = self._issue(self.volmarr, "anvil", "Look", "hey @yrsa please look")
        self.assertEqual(self.router.sync_issue("crew", "anvil", issue.number), 1)
        notes = self._for(self.yrsa)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].reason, "mention")
        self.assertEqual(notes[0].actor, "volmarr")
        self.assertEqual(notes[0].target_id, f"crew/anvil#{issue.number}")
        self.assertEqual(notes[0].detail["repo"], "crew/anvil")
        self.assertEqual(notes[0].detail["via"], ["@yrsa"])
        deliveries = self.router.deliveries_for(self.yrsa)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0].via, ("@yrsa",))
        self.assertEqual(deliveries[0].notification_id, notes[0].id)
        self.assertIn("you were mentioned", deliveries[0].words)

    def test_unknown_user_and_unproven_team_notify_nobody(self):
        issue = self._issue(self.volmarr, "anvil", "Look", "hey @ghost and @crew/nope")
        self.assertEqual(self.router.sync_issue("crew", "anvil", issue.number), 0)
        self.assertEqual(self._notes(), 0)
        self.assertEqual(self._deliveries(), 0)

    def test_self_mention_and_code_only_mention_notify_nobody(self):
        issue = self._issue(self.volmarr, "anvil", "Look", "note to @volmarr self")
        self.assertEqual(self.router.sync_issue("crew", "anvil", issue.number), 0)
        fenced = self._issue(self.volmarr, "anvil", "Code", "```\n@yrsa\n```")
        self.assertEqual(self.router.sync_issue("crew", "anvil", fenced.number), 0)
        self.assertEqual(self._notes(), 0)

    def test_duplicate_tokens_notify_once(self):
        issue = self._issue(self.volmarr, "anvil", "Look", "@yrsa @yrsa @Yrsa")
        self.assertEqual(self.router.sync_issue("crew", "anvil", issue.number), 1)
        self.assertEqual(len(self._for(self.yrsa)), 1)

    # -- team mentions ----------------------------------------------------
    def test_team_mention_expands_effective_members_once_each(self):
        issue = self._issue(self.volmarr, "anvil", "Look", "ping @crew/anvil-crew")
        # Effective members: bryn (direct) + volmarr, yrsa (Forge ancestors);
        # the author volmarr is removed.
        self.assertEqual(self.router.sync_issue("crew", "anvil", issue.number), 2)
        self.assertEqual(len(self._for(self.yrsa)), 1)
        self.assertEqual(len(self._for(self.bryn)), 1)
        self.assertEqual(self.router.deliveries_for(self.bryn)[0].via, ("@crew/anvil-crew",))

    def test_direct_and_team_overlap_is_one_notification_with_both_paths(self):
        issue = self._issue(self.volmarr, "anvil", "Look", "@yrsa see @crew/forge")
        self.router.sync_issue("crew", "anvil", issue.number)
        notes = self._for(self.yrsa)
        self.assertEqual(len(notes), 1)
        delivery = self.router.deliveries_for(self.yrsa)[0]
        self.assertEqual(set(delivery.via), {"@yrsa", "@crew/forge"})
        self.assertEqual(self._deliveries(), 1)

    def test_two_teams_reaching_same_person_still_one_notification(self):
        issue = self._issue(self.volmarr, "anvil", "Look", "@crew/forge and @crew/anvil-crew")
        self.router.sync_issue("crew", "anvil", issue.number)
        self.assertEqual(len(self._for(self.yrsa)), 1)
        self.assertEqual(len(self.router.deliveries_for(self.bryn)), 1)

    def test_secret_team_mention_by_outsider_resolves_to_nothing(self):
        self._raw_issue(self.anvil_id, 77, self.freya.id, "ping @crew/wardens")
        self.assertEqual(self.router.sync_issue("crew", "anvil", 77), 0)
        self.assertEqual(self._notes(), 0)

    def test_secret_team_mention_by_member_routes(self):
        self._raw_issue(self.anvil_id, 78, self.yrsa.id, "ping @crew/wardens")
        self.router.sync_issue("crew", "anvil", 78)
        self.assertEqual(len(self._for(self.volmarr)), 1)
        self.assertEqual(len(self._for(self.yrsa)), 0)  # author removed

    # -- exactly once: resync, edits, comments ------------------------------
    def test_resync_never_duplicates_and_preserves_read_state(self):
        issue = self._issue(self.volmarr, "anvil", "Look", "hey @yrsa")
        self.router.sync_issue("crew", "anvil", issue.number)
        first = self._for(self.yrsa)[0]
        self.assertTrue(self.inbox.mark_read(self.yrsa, first.id))
        self.router.sync_issue("crew", "anvil", issue.number)
        self.router.sync_issue("crew", "anvil", issue.number)
        notes = self._for(self.yrsa)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].id, first.id)
        self.assertFalse(notes[0].unread)
        self.assertEqual(self._deliveries(), 1)

    def test_edit_removing_mention_withdraws_and_adding_delivers(self):
        issue = self._issue(self.volmarr, "anvil", "Look", "hey @yrsa")
        self.router.sync_issue("crew", "anvil", issue.number)
        self.assertEqual(self._notes(), 1)
        self._set_body(issue.id, "hey @brynhild instead")
        self.router.sync_issue("crew", "anvil", issue.number)
        self.assertEqual(len(self._for(self.yrsa)), 0)
        self.assertEqual(len(self._for(self.bryn)), 1)
        self.assertEqual(self._notes(), 1)
        self.assertEqual(self._deliveries(), 1)

    def test_comment_mentions_route_and_tombstone_withdraws(self):
        issue = self._issue(self.volmarr, "anvil", "Look", "plain body")
        self.assertEqual(self.router.sync_issue("crew", "anvil", issue.number), 0)
        cid = self._comment(issue.id, self.volmarr.id, "cc @brynhild")
        self.assertEqual(self.router.sync_issue("crew", "anvil", issue.number), 1)
        delivery = self.router.deliveries_for(self.bryn)[0]
        self.assertEqual(delivery.source_kind, "comment")
        self.assertEqual(delivery.comment_id, cid)
        with self.conn:
            self.conn.execute(
                "UPDATE issue_comments SET deleted_at = ?, deleted_by = ? WHERE id = ?",
                (1_700_000_200, self.volmarr.id, cid))
        self.assertEqual(self.router.sync_issue("crew", "anvil", issue.number), 0)
        self.assertEqual(self._notes(), 0)
        self.assertEqual(self._deliveries(), 0)

    def test_pull_request_body_routes_with_pull_request_kind(self):
        claimed = self.issues.claim_number("crew", "anvil", "pull_request", self.volmarr.id)
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET title = 'PR', body = 'review @yrsa please' WHERE id = ?",
                (claimed.row_id,))
        self.assertEqual(self.router.sync_issue("crew", "anvil", claimed.number), 1)
        delivery = self.router.deliveries_for(self.yrsa)[0]
        self.assertEqual(delivery.source_kind, "pull_request")

    # -- cross-reference echoes ----------------------------------------------
    def test_cross_reference_echo_never_duplicates(self):
        target = self._issue(self.volmarr, "anvil", "Target", "plain target body")
        source = self._issue(self.volmarr, "anvil", "Source",
                             f"see #{target.number} -- @yrsa please look")
        self.assertEqual(self.router.sync_issue("crew", "anvil", source.number), 1)
        self.assertEqual(self._notes(), 1)
        xrefs = CrossReferenceStore(self.conn, self.repos, self.accounts,
                                    self.issues, time_fn=self.clock)
        recorded = xrefs.sync_issue_references(self.volmarr, "crew", "anvil", source.number)
        self.assertEqual(len(recorded), 1)  # the back-reference exists
        backs = xrefs.references_to(self.volmarr, "crew", "anvil", target.number)
        self.assertEqual(len(backs), 1)
        # Routing the target thread: the echo is not a source.
        self.assertEqual(self.router.sync_issue("crew", "anvil", target.number), 0)
        # Re-routing the source after the echo: still exactly once.
        self.assertEqual(self.router.sync_issue("crew", "anvil", source.number), 1)
        self.assertEqual(self._notes(), 1)
        self.assertEqual(self.router.mentions_in(
            self.volmarr, "crew", "anvil", target.number), [])

    # -- permission and mute ---------------------------------------------------
    def test_private_repo_mention_reaches_only_readers(self):
        # An org-owned private repo no account here can read:
        # a mention inside it reaches nobody at all.
        self._raw_issue(self.vault_id, 1, self.yrsa.id,
                        "hey @volmarr and @mallory")
        self.router.sync_issue("crew", "vault", 1)
        self.assertEqual(self._deliveries(), 0)
        # A personally owned private repo: the owner reads it,
        # a stranger does not -- the owner is reached, the
        # stranger is not.
        self.repos.create_repository(self.volmarr.id, "volmarr", "priv", visibility="private")
        priv_id = self.conn.execute(
            "SELECT id FROM repositories WHERE owner_lower = 'volmarr' AND name_lower = 'priv'"
        ).fetchone()["id"]
        self._raw_issue(priv_id, 1, self.yrsa.id, "hey @volmarr and @mallory")
        self.router.sync_issue("volmarr", "priv", 1)
        self.assertEqual(len(self.router.deliveries_for(self.volmarr)), 1)
        self.assertEqual(len(self.router.deliveries_for(self.mallory)), 0)

    def test_muted_thread_suppresses_until_unmuted(self):
        issue = self._issue(self.volmarr, "anvil", "Look", "hey @yrsa")
        with self.conn:
            self.conn.execute(
                "INSERT INTO thread_overrides (user_id, repo_id, thread_kind, thread_number, state, created_at, updated_at) VALUES (?, ?, 'issue', ?, 'muted', ?, ?)",
                (self.yrsa.id, self.anvil_id, issue.number, 1_700_000_000, 1_700_000_000))
        self.assertEqual(self.router.sync_issue("crew", "anvil", issue.number), 0)
        with self.conn:
            self.conn.execute(
                "DELETE FROM thread_overrides WHERE user_id = ? AND repo_id = ?",
                (self.yrsa.id, self.anvil_id))
        self.assertEqual(self.router.sync_issue("crew", "anvil", issue.number), 1)
        self.assertEqual(len(self._for(self.yrsa)), 1)

    # -- reads -------------------------------------------------------------------
    def test_deliveries_for_is_recipient_scoped(self):
        issue = self._issue(self.volmarr, "anvil", "Look", "hey @yrsa and @brynhild")
        self.router.sync_issue("crew", "anvil", issue.number)
        self.assertEqual(len(self.router.deliveries_for(self.yrsa)), 1)
        self.assertEqual(len(self.router.deliveries_for(self.bryn)), 1)
        self.assertEqual(self.router.deliveries_for(None), [])
        self.assertEqual(self.router.deliveries_for(self.freya), [])

    def test_mentions_in_gates_on_repository_read(self):
        row_id = self._raw_issue(self.vault_id, 1, self.volmarr.id, "hey @yrsa")
        self.router.sync_issue("crew", "vault", 1)
        with self.assertRaises(IssueError) as cm:
            self.router.mentions_in(self.freya, "crew", "vault", 1)
        self.assertEqual(cm.exception.reason, "issue_not_found")
        with self.assertRaises(IssueError) as cm:
            self.router.sync_issue("crew", "nope", 1)
        self.assertEqual(cm.exception.reason, "repo_not_found")

    def test_routing_audits_nothing(self):
        before = self.conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        issue = self._issue(self.volmarr, "anvil", "Look", "hey @yrsa @crew/forge")
        after_create = self.conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.router.sync_issue("crew", "anvil", issue.number)
        after_sync = self.conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.assertEqual(after_sync, after_create)
        self.assertGreaterEqual(after_create, before)

    # -- rendering ------------------------------------------------------------------
    def test_renderers_say_reason_and_escape(self):
        issue = self._issue(self.volmarr, "anvil", "Look", "hey @yrsa")
        self.router.sync_issue("crew", "anvil", issue.number)
        delivery = self.router.deliveries_for(self.yrsa)[0]
        html = render_mention_delivery(delivery)
        self.assertIn("you were mentioned", html)
        self.assertIn("@yrsa", html)
        page = render_mention_deliveries([delivery])
        self.assertIn("mention-deliveries", page)
        empty = render_mention_deliveries([])
        self.assertIn("No mention has reached you yet", empty)


if __name__ == "__main__":
    unittest.main()
