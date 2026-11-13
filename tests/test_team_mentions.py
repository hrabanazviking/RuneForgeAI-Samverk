"""S-195 acceptance battery: team mentions.

Acceptance (roadmap S-195): Team mentions —
`@org/team` notifies the team (Part XI), usable in
issues, PRs, and review requests.

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
from samverk.issues import IssueError, IssueStore
from samverk.organizations import OrganizationStore
from samverk.organization_members import OrgMembershipStore
from samverk.repositories import RepositoryStore
from samverk.team_mentions import (
    TeamMentionStore, decide_recipients, parse_team_mentions,
    render_team_mentions_page)
from samverk.teams import TeamStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class TeamMentionTests(unittest.TestCase):
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
        self.teams = TeamStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        # Forge: creator (auto) + yrsa. Anvil Crew: child
        # of Forge, bryn direct — its effective members
        # are bryn + Forge's (inheritance flows down).
        self.forge = self.teams.create_team(self.creator.id, self.org.id, "Forge")
        self.teams.add_member(self.creator.id, self.org.id, self.forge.id, self.yrsa.id)
        self.anvil_crew = self.teams.create_team(
            self.creator.id, self.org.id, "Anvil Crew", parent_team_id=self.forge.id)
        self.teams.add_member(self.creator.id, self.org.id, self.anvil_crew.id, self.bryn.id)
        # Wardens: a secret team of creator + yrsa.
        self.wardens = self.teams.create_team(
            self.creator.id, self.org.id, "Wardens", privacy="secret")
        self.teams.add_member(self.creator.id, self.org.id, self.wardens.id, self.yrsa.id)
        self.mentions = TeamMentionStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.anvil = self._repo("crew", "anvil", "public")
        self.vault = self._repo("crew", "vault", "private")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)

    def _repo(self, owner, name, visibility):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                (owner, owner.lower(), name, name.lower(), self.creator.id, 1_700_000_000, visibility))
        return int(cur.lastrowid)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(IssueError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _issue(self, author, repo_name, title, body):
        return self.issues.create_issue(author, "crew", repo_name, title, body)

    def _raw_issue(self, repo_id, number, author_id, body):
        """An issue row in the landed shape, for the
        org-owned private vault: S-054 gives no account
        a creation door there (the org creator is not a
        writer on an org-owned repo — S-194's note)."""
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO issues (repo_id, number, kind, author_id, title, body, state, created_at, updated_at) VALUES (?, ?, 'issue', ?, 'Vault work', ?, 'open', ?, ?)",
                (repo_id, number, author_id, body, 1_700_000_000, 1_700_000_000))
        return int(cur.lastrowid)

    def _comment(self, issue_id, author_id, body, deleted=False):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO issue_comments (issue_id, author_id, body, created_at, updated_at, deleted_at, deleted_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (issue_id, author_id, body, 1_700_000_000, 1_700_000_000,
                 1_700_000_100 if deleted else None,
                 author_id if deleted else None))
        return int(cur.lastrowid)

    def _pr_with_requests(self, tokens):
        """A pull request fixture in the landed shapes,
        with one review-request row per (token, state)."""
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO issues (repo_id, number, kind, author_id, title, body, state, created_at, updated_at) VALUES (?, 90, 'pull_request', ?, 'Bryn work', 'Please look, @crew/forge', 'open', ?, ?)",
                (self.anvil, self.bryn.id, 1_700_000_000, 1_700_000_000))
            issue_id = int(cur.lastrowid)
            cur = self.conn.execute(
                "INSERT INTO pull_requests (issue_id, repo_id, base_branch, head_branch, created_at, updated_at) VALUES (?, ?, 'main', 'feature', ?, ?)",
                (issue_id, self.anvil, 1_700_000_000, 1_700_000_000))
            pr_id = int(cur.lastrowid)
            for token, state in tokens:
                self.conn.execute(
                    "INSERT INTO pull_request_review_requests (pull_request_id, owner_ref, user_id, source, head_oid, created_at, state) VALUES (?, ?, NULL, 'manual', 'abc', ?, ?)",
                    (pr_id, token, 1_700_000_000, state))
        return pr_id

    def _rows(self):
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM team_mention_notifications").fetchone()["n"]

    def _audit_rows(self):
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    # -- pins and pure laws --------------------------------
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 124)
        self.assertEqual(db.MIGRATIONS[-1][0], 124)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("team_mention_notifications", tables)

    def test_parse_shapes(self):
        self.assertEqual(parse_team_mentions("ask @crew/forge please"),
                         [("crew", "forge")])
        self.assertEqual(
            parse_team_mentions("@Crew/Forge, @crew/forge and @crew/anvil-crew"),
            [("crew", "forge"), ("crew", "anvil-crew")])
        self.assertEqual(parse_team_mentions("mail volmarr@crew/forge"), [])
        self.assertEqual(parse_team_mentions("see x/@crew/forge"), [])
        self.assertEqual(parse_team_mentions("just @yrsa"), [])
        self.assertEqual(parse_team_mentions("`@crew/forge`"), [])
        self.assertEqual(
            parse_team_mentions("```\n@crew/forge\n```\nbut @crew/forge"),
            [("crew", "forge")])
        self.assertEqual(parse_team_mentions(None), [])
        self.assertEqual(parse_team_mentions(""), [])

    def test_pure_decide_recipients(self):
        self.assertEqual(decide_recipients([3, 1, 3, 2], 1), (3, 2))
        self.assertEqual(decide_recipients([1, 2], None), (1, 2))
        self.assertEqual(decide_recipients([], 9), ())

    # -- prose mentions in issues ---------------------------
    def test_issue_body_mention_notifies_the_team(self):
        issue = self._issue(self.bryn, "anvil", "Sharpen the edge",
                            "Could @crew/forge look at this?")
        self.assertEqual(self.mentions.sync_issue("crew", "anvil", issue.number), 2)
        yrsa_inbox = self.mentions.inbox(self.yrsa)
        self.assertEqual(len(yrsa_inbox), 1)
        note = yrsa_inbox[0]
        self.assertEqual(note.mention, "@crew/forge")
        self.assertEqual(note.reason, "mention")
        self.assertEqual(note.source_kind, "issue")
        self.assertEqual(note.actor, "brynhild")
        self.assertEqual(note.repository, "crew/anvil")
        self.assertIn("mentioned @crew/forge", note.words)
        self.assertIn("member of Forge", note.words)
        creator_inbox = self.mentions.inbox(self.creator)
        self.assertEqual(len(creator_inbox), 1)
        self.assertEqual(self.mentions.inbox(self.bryn), [])
        self.assertEqual(self.mentions.inbox(self.outsider), [])

    def test_author_is_never_notified(self):
        issue = self._issue(self.yrsa, "anvil", "My own ask",
                            "@crew/forge — noting for the team")
        self.mentions.sync_issue("crew", "anvil", issue.number)
        self.assertEqual(self.mentions.inbox(self.yrsa), [])
        self.assertEqual(len(self.mentions.inbox(self.creator)), 1)

    def test_child_team_mention_includes_ancestors(self):
        issue = self._issue(self.outsider, "anvil", "Anvil work",
                            "@crew/anvil-crew to the anvil")
        self.assertEqual(self.mentions.sync_issue("crew", "anvil", issue.number), 3)
        for user in (self.bryn, self.yrsa, self.creator):
            self.assertEqual(len(self.mentions.inbox(user)), 1)

    def test_parent_mention_excludes_child_only_members(self):
        issue = self._issue(self.outsider, "anvil", "Forge work",
                            "@crew/forge to the forge")
        self.mentions.sync_issue("crew", "anvil", issue.number)
        self.assertEqual(self.mentions.inbox(self.bryn), [])
        self.assertEqual(len(self.mentions.inbox(self.yrsa)), 1)

    def test_unknown_org_or_team_notifies_nobody(self):
        issue = self._issue(self.bryn, "anvil", "Ghosts",
                            "@crew/ghost and @nope/forge, anyone?")
        self.assertEqual(self.mentions.sync_issue("crew", "anvil", issue.number), 0)
        self.assertEqual(self._rows(), 0)
        self.assertEqual(self.mentions.preview_mentions("@crew/ghost", self.bryn.id), [])

    def test_secret_team_mention_needs_an_author_who_can_see_it(self):
        issue = self._issue(self.outsider, "anvil", "Wardens?",
                            "@crew/wardens, show yourselves")
        self.assertEqual(self.mentions.sync_issue("crew", "anvil", issue.number), 0)
        own = self._issue(self.yrsa, "anvil", "Wardens, to me",
                          "@crew/wardens — eyes on this")
        self.assertEqual(self.mentions.sync_issue("crew", "anvil", own.number), 1)
        self.assertEqual(len(self.mentions.inbox(self.creator)), 1)
        self.assertEqual(self.mentions.inbox(self.creator)[0].team_name, "Wardens")

    def test_private_repository_gates_recipients(self):
        self._raw_issue(self.vault, 7, self.creator.id,
                        "@crew/forge inside the vault")
        # S-054: an org-owned private repository is
        # readable by no account here, so the mention
        # stands in prose and notifies nobody.
        self.assertEqual(self.mentions.sync_issue("crew", "vault", 7), 0)
        self.assertEqual(self._rows(), 0)

    def test_record_follows_the_text(self):
        issue = self._issue(self.bryn, "anvil", "Changing ask",
                            "@crew/forge first")
        self.assertEqual(self.mentions.sync_issue("crew", "anvil", issue.number), 2)
        self.assertEqual(self.mentions.sync_issue("crew", "anvil", issue.number), 2)
        self.assertEqual(self._rows(), 2)  # syncing twice doubles nobody
        with self.conn:
            self.conn.execute("UPDATE issues SET body = 'no mention now' WHERE id = ?", (issue.id,))
        self.assertEqual(self.mentions.sync_issue("crew", "anvil", issue.number), 0)
        self.assertEqual(self._rows(), 0)

    def test_comment_mentions_and_tombstones(self):
        issue = self._issue(self.creator, "anvil", "Plain start", "nothing here")
        self.assertEqual(self.mentions.sync_issue("crew", "anvil", issue.number), 0)
        comment_id = self._comment(issue.id, self.yrsa.id, "@crew/forge — agreed")
        self.assertEqual(self.mentions.sync_issue("crew", "anvil", issue.number), 1)
        note = self.mentions.inbox(self.creator)[0]
        self.assertEqual(note.source_kind, "comment")
        self.assertEqual(note.comment_id, comment_id)
        with self.conn:
            self.conn.execute(
                "UPDATE issue_comments SET deleted_at = ?, deleted_by = ? WHERE id = ?",
                (1_700_000_200, self.yrsa.id, comment_id))
        self.assertEqual(self.mentions.sync_issue("crew", "anvil", issue.number), 0)
        self.assertEqual(self._rows(), 0)

    def test_preview_writes_and_audits_nothing(self):
        before_rows, before_audit = self._rows(), self._audit_rows()
        found = self.mentions.preview_mentions("@crew/forge, assemble", self.bryn.id)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].recipients, ("volmarr", "yrsa"))
        self.assertIn("would notify volmarr, yrsa", found[0].words)
        self.assertEqual(self._rows(), before_rows)
        issue = self._issue(self.bryn, "anvil", "Quiet sync", "@crew/forge")
        audit_after_issue = self._audit_rows()
        self.mentions.sync_issue("crew", "anvil", issue.number)
        self.assertEqual(self._audit_rows(), audit_after_issue)
        self.assertGreater(self._rows(), before_rows)

    # -- PR bodies and review requests ----------------------
    def test_pull_request_body_mention(self):
        self._pr_with_requests([])
        self.assertEqual(self.mentions.sync_issue("crew", "anvil", 90), 2)
        notes = self.mentions.mentions_in(None, "crew", "anvil", 90)
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0].source_kind, "pull_request")
        self.assertEqual({n.recipient for n in notes}, {"volmarr", "yrsa"})

    def test_review_request_expands_the_team(self):
        self._pr_with_requests([
            ("@crew/forge", "requested"),
            ("@yrsa", "requested"),          # a person: S-165's ground
            ("@crew/anvil-crew", "dismissed"),  # dismissed: nobody
            ("@crew/ghost", "requested"),    # unproven: nobody
        ])
        self.assertEqual(self.mentions.sync_review_requests("crew", "anvil", 90), 2)
        for user in (self.creator, self.yrsa):
            inbox = self.mentions.inbox(user)
            self.assertEqual(len(inbox), 1)
            self.assertEqual(inbox[0].reason, "review-requested")
            self.assertEqual(inbox[0].source_kind, "review_request")
            self.assertIn("asked @crew/forge to review", inbox[0].words)
        self.assertEqual(self.mentions.inbox(self.bryn), [])
        # Dismissal ends the notification on re-sync.
        with self.conn:
            self.conn.execute(
                "UPDATE pull_request_review_requests SET state = 'dismissed' WHERE owner_ref = '@crew/forge'")
        self.assertEqual(self.mentions.sync_review_requests("crew", "anvil", 90), 0)
        self.assertEqual(self._rows(), 0)

    def test_review_requests_on_an_issue_raise(self):
        issue = self._issue(self.bryn, "anvil", "Not a PR", "body")
        self.assertEqual(
            self._reason(self.mentions.sync_review_requests,
                         "crew", "anvil", issue.number),
            "issue_not_found")

    # -- reads, refusals, rendering ---------------------------
    def test_unknown_repo_and_issue_raise_uniformly(self):
        self.assertEqual(
            self._reason(self.mentions.sync_issue, "crew", "nope", 1),
            "repo_not_found")
        self.assertEqual(
            self._reason(self.mentions.sync_issue, "crew", "anvil", 999),
            "issue_not_found")
        self.assertEqual(
            self._reason(self.mentions.mentions_in, None, "crew", "anvil", 999),
            "issue_not_found")

    def test_mentions_in_hides_private_repositories(self):
        self._raw_issue(self.vault, 7, self.creator.id, "@crew/forge")
        self.mentions.sync_issue("crew", "vault", 7)
        self.assertEqual(
            self._reason(self.mentions.mentions_in,
                         self.outsider, "crew", "vault", 7),
            "issue_not_found")

    def test_inbox_is_the_recipients_own(self):
        issue = self._issue(self.bryn, "anvil", "Inbox law", "@crew/forge")
        self.mentions.sync_issue("crew", "anvil", issue.number)
        self.assertEqual(self.mentions.inbox(None), [])
        self.assertEqual(
            {n.recipient for n in self.mentions.inbox(self.yrsa)}, {"yrsa"})

    def test_page_renders_words_and_escapes(self):
        sharp = self.teams.create_team(self.creator.id, self.org.id, "Forge <i>")
        self.teams.add_member(self.creator.id, self.org.id, sharp.id, self.yrsa.id)
        issue = self._issue(self.bryn, "anvil", "Sharp team", "@crew/forge-i — over here")
        self.mentions.sync_issue("crew", "anvil", issue.number)
        page = render_team_mentions_page("yrsa", self.mentions.inbox(self.yrsa))
        self.assertIn("Forge &lt;i&gt;", page)
        self.assertNotIn("Forge <i>", page)
        self.assertIn("mentioned @crew/forge-i", page)
        empty = render_team_mentions_page("freya", [])
        self.assertIn("No team has mentioned you yet.", empty)
