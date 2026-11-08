"""S-221 acceptance battery: event store completion.

Acceptance (roadmap S-221): the canonical event
record (actor, verb, target, refs, timestamp)
written by every mutation in Parts III-X.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.event_store import (
    CanonicalEvent, EventStore, EventStoreError, derive_refs,
    event_payload, event_visible_to, payload_json,
    render_events_page, repository_of)
from samverk.hooks import RefUpdate
from samverk.index_architecture import SearchIndexStore
from samverk.index_health import IndexHealth
from samverk.issue_comments import IssueCommentStore
from samverk.issues import IssueStore
from samverk.organizations import OrganizationStore
from samverk.protection_rulesets import RulesetStore
from samverk.pull_requests import PullRequestStore
from samverk.push_events import PushEventStore
from samverk.repositories import RepositoryError, RepositoryStore
from samverk.transport_audit import TransportAuditor
from test_repo_home import run_git

ZERO = "0" * 40
OID_A = "a" * 40


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class EventStoreTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.stranger = self.accounts.register("mallory", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.owner.id,))
        self.admin = self.accounts.get_by_id(self.owner.id)
        self.repos = RepositoryStore(self.conn, self.root, self.accounts, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit)
        self.comments = IssueCommentStore(self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.events = EventStore(self.conn, self.repos, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")

    # -- helpers ------------------------------------------------
    def _audit_count(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    def _event_count(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]

    def _all_verbs(self):
        self.events.sync_all()
        rows = self.conn.execute("SELECT verb FROM events ORDER BY id").fetchall()
        return [r["verb"] for r in rows]

    def _mutate_issues(self):
        self.issues.create_issue(self.reader, "volmarr", "pub", "Crash on startup")
        self.comments.add_comment(self.owner, "volmarr", "pub", 1, "Looking now")
        self.issues.close_issue(self.owner, "volmarr", "pub", 1)

    # -- the canonical record ------------------------------------
    def test_canonical_record_shape(self):
        self._mutate_issues()
        events = self.events.list_for_repo(self.owner, "volmarr", "pub")
        created = [e for e in events if e.verb == "repo.issue.create"][0]
        self.assertEqual(created.actor, "yrsa")
        self.assertEqual(created.actor_kind, "user")
        self.assertEqual(created.actor_id, self.reader.id)
        self.assertEqual(created.action, "create")
        self.assertEqual(created.target_kind, "repo")
        self.assertEqual(created.target_id, "volmarr/pub#1")
        self.assertEqual(created.repository, "volmarr/pub")
        self.assertEqual(created.number, 1)
        self.assertEqual(created.refs, ("repo:volmarr/pub", "number:1"))
        self.assertEqual(created.outcome, "success")
        self.assertEqual(created.created_at, 1_700_000_000)
        self.assertIsInstance(created.detail, dict)
        row = self.conn.execute(
            "SELECT seq FROM audit_log WHERE action = 'repo.issue.create'").fetchone()
        self.assertEqual(created.audit_seq, int(row["seq"]))

    def test_every_witnessed_mutation_is_an_event(self):
        # Completeness by construction: the events table is the
        # audit log, materialised -- same rows, same order.
        self._mutate_issues()
        self.events.sync_all()
        self.assertEqual(self._event_count(), self._audit_count())
        audit_seqs = [r["seq"] for r in self.conn.execute(
            "SELECT seq FROM audit_log ORDER BY seq").fetchall()]
        event_seqs = [r["audit_seq"] for r in self.conn.execute(
            "SELECT audit_seq FROM events ORDER BY id").fetchall()]
        self.assertEqual(event_seqs, audit_seqs)

    def test_exactly_once_resync(self):
        self._mutate_issues()
        first = self.events.sync_all()
        self.assertGreater(first, 0)
        self.assertEqual(self.events.sync_all(), 0)
        self.assertEqual(self.events.sync_repo("volmarr", "pub"), 0)
        count = self._event_count()
        self.events.list_for_repo(self.owner, "volmarr", "pub")
        self.events.list_public()
        self.assertEqual(self._event_count(), count)

    def test_sync_repo_is_scoped_then_sync_all_completes(self):
        self._mutate_issues()
        emitted = self.events.sync_repo("volmarr", "pub")
        verbs = [r["verb"] for r in self.conn.execute(
            "SELECT verb FROM events ORDER BY id").fetchall()]
        self.assertEqual(emitted, len(verbs))
        self.assertIn("repo.create", verbs)  # pub's own creation
        self.assertIn("repo.issue.create", verbs)
        self.assertNotIn("auth.signup.success", verbs)
        rest = self.events.sync_all()
        self.assertGreater(rest, 0)
        self.assertEqual(self._event_count(), self._audit_count())
        with self.assertRaises(EventStoreError) as caught:
            self.events.sync_repo("volmarr", "missing")
        self.assertEqual(caught.exception.reason, "repo_not_found")

    def test_mutations_across_parts_write_events(self):
        verbs = set(self._all_verbs())
        # Part III (accounts) and Part IV/V (repositories) from setUp.
        self.assertIn("auth.signup.success", verbs)
        self.assertIn("repo.create", verbs)
        # Part VI (issues).
        self._mutate_issues()
        # Part IX (organizations).
        orgs = OrganizationStore(self.conn, self.accounts, audit=self.audit)
        orgs.create_organization(self.owner.id, "crew")
        # Part VIII (protection): a ruleset change.
        rulesets = RulesetStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)
        rulesets.create_ruleset(self.admin, "Baseline", repo_patterns=["volmarr/*"], branch_patterns=["main"])
        # Part X (search operations): an admin index rebuild.
        index = SearchIndexStore(self.conn, self.repos, time_fn=self.clock)
        health = IndexHealth(self.conn, self.accounts, index, self.audit, time_fn=self.clock)
        health.request_rebuild(self.admin.id, "volmarr", "pub")
        # Push (S-090/S-094): the witness row and the family store agree.
        auditor = TransportAuditor(self.audit)
        auditor.record_push(actor_kind="user", actor_id=self.owner.id,
                            full_name="volmarr/pub", transport="http",
                            refs=("refs/heads/main",))
        pushes = PushEventStore(self.conn, self.repos, time_fn=self.clock)
        pushes.record_push("volmarr", "pub", actor_kind="user",
                           actor_id=self.owner.id, transport="http",
                           updates=(RefUpdate(ref="refs/heads/main", old_oid=ZERO, new_oid=OID_A),))
        verbs = set(self._all_verbs())
        for verb in ("repo.issue.create", "repo.issue.comment",
                     "repo.issue.close", "auth.organization.create",
                     "repo.protection.change", "admin.index.rebuild",
                     "repo.push"):
            self.assertIn(verb, verbs)
        push = [e for e in self.events.list_for_repo(self.owner, "volmarr", "pub")
                if e.verb == "repo.push"][0]
        self.assertEqual(push.refs, ("repo:volmarr/pub", "refs/heads/main"))
        self.assertEqual(push.detail.get("transport"), "http")

    def test_pull_request_creation_writes_event(self):
        # Part VII (pull requests), with real branches.
        bare = self.repos.path_for("volmarr", "pub")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "a.txt").write_text("base\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "base commit")
        run_git(work, "checkout", "-b", "feature")
        (work / "a.txt").write_text("base\nfeature\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "feature work")
        run_git(work, "push", str(bare), "main", "feature")
        prs = PullRequestStore(self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        prs.create_pull_request(self.owner, "volmarr", "pub", base_branch="main", head_branch="feature")
        events = self.events.list_for_repo(self.owner, "volmarr", "pub")
        created = [e for e in events if e.verb == "repo.pull_request.create"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].number, 1)
        self.assertEqual(created[0].refs, ("repo:volmarr/pub", "number:1"))

    def test_refusals_and_quiet_retries_emit_nothing(self):
        self._mutate_issues()
        self.events.sync_all()
        before = self._event_count()
        audit_before = self._audit_count()
        # A no-op close is quiet in the witness (S-130's law).
        self.issues.close_issue(self.owner, "volmarr", "pub", 1)
        # A refused creation never reaches the witness.
        with self.assertRaises(RepositoryError):
            self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        # A refused ruleset (non-admin) never reaches the witness.
        rulesets = RulesetStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)
        with self.assertRaises(Exception):
            rulesets.create_ruleset(self.reader, "Nope", repo_patterns=["volmarr/*"], branch_patterns=["main"])
        self.assertEqual(self._audit_count(), audit_before)
        self.assertEqual(self.events.sync_all(), 0)
        self.assertEqual(self._event_count(), before)

    def test_reads_sync_first_never_stale(self):
        first = self.events.list_for_repo(self.owner, "volmarr", "pub")
        self.assertEqual([e.verb for e in first], ["repo.create"])
        self.issues.create_issue(self.owner, "volmarr", "pub", "Fresh")
        second = self.events.list_for_repo(self.owner, "volmarr", "pub")
        self.assertEqual(second[0].verb, "repo.issue.create")  # newest first
        self.assertEqual(len(second), 2)

    def test_repo_reads_follow_the_gate(self):
        self.issues.create_issue(self.owner, "volmarr", "priv", "Secret work")
        with self.assertRaises(EventStoreError) as caught:
            self.events.list_for_repo(self.stranger, "volmarr", "priv")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(EventStoreError):
            self.events.list_for_repo(None, "volmarr", "priv")
        self.assertEqual(self.events.count_for_repo(self.owner, "volmarr", "priv"), 2)
        # Public repos are readable by anyone, even anonymously.
        self.assertEqual(self.events.count_for_repo(None, "volmarr", "pub"), 1)
        self.assertEqual(self.events.count_for_repo(self.stranger, "volmarr", "pub"), 1)
        # Repositories do not share events; the verb filter holds.
        self._mutate_issues()
        pub = self.events.list_for_repo(self.owner, "volmarr", "pub", verb_prefix="repo.issue.")
        self.assertEqual({e.verb for e in pub},
                         {"repo.issue.create", "repo.issue.comment", "repo.issue.close"})
        self.assertTrue(all(e.repository == "volmarr/pub" for e in pub))

    def test_actor_feed_filters_what_the_viewer_cannot_read(self):
        self.issues.create_issue(self.owner, "volmarr", "pub", "Open work")
        self.issues.create_issue(self.owner, "volmarr", "priv", "Secret work")
        own = self.events.list_for_actor(self.owner, "volmarr")
        self.assertIn("volmarr/priv#1", [e.target_id for e in own])
        seen_by_stranger = self.events.list_for_actor(self.stranger, self.owner)
        targets = [e.target_id for e in seen_by_stranger]
        self.assertIn("volmarr/pub#1", targets)
        self.assertNotIn("volmarr/priv#1", targets)
        self.assertNotIn("volmarr/priv", targets)
        # The owner's signup is an account fact: not a stranger's reading.
        self.assertNotIn("auth.signup.success", [e.verb for e in seen_by_stranger])
        anon = self.events.list_for_actor(None, "volmarr")
        self.assertEqual([e.target_id for e in anon], ["volmarr/pub#1", "volmarr/pub"])
        with self.assertRaises(EventStoreError) as caught:
            self.events.list_for_actor(self.owner, "nobody")
        self.assertEqual(caught.exception.reason, "no_such_user")

    def test_public_feed_is_public_repos_only(self):
        self._mutate_issues()
        self.issues.create_issue(self.owner, "volmarr", "priv", "Secret work")
        feed = self.events.list_public()
        self.assertTrue(feed)
        self.assertTrue(all(e.repository == "volmarr/pub" for e in feed))
        priv = [e for e in feed if e.target_id and "priv" in e.target_id]
        self.assertEqual(priv, [])

    def test_get_event_under_the_same_law(self):
        self.issues.create_issue(self.owner, "volmarr", "priv", "Secret work")
        event = self.events.list_for_repo(self.owner, "volmarr", "priv")[0]
        self.assertEqual(self.events.get_event(self.owner, event.id).id, event.id)
        with self.assertRaises(EventStoreError) as caught:
            self.events.get_event(self.stranger, event.id)
        self.assertEqual(caught.exception.reason, "event_not_found")
        with self.assertRaises(EventStoreError):
            self.events.get_event(self.owner, 999999)
        with self.assertRaises(EventStoreError):
            self.events.get_event(self.owner, "1")

    def test_organization_events_are_public_facts(self):
        orgs = OrganizationStore(self.conn, self.accounts, audit=self.audit)
        orgs.create_organization(self.owner.id, "crew")
        feed = self.events.list_for_actor(None, "volmarr")
        org_events = [e for e in feed if e.verb == "auth.organization.create"]
        self.assertEqual(len(org_events), 1)
        self.assertEqual(org_events[0].target_id, "crew")
        self.assertEqual(org_events[0].refs, ())

    def test_pure_refs_and_repository_laws(self):
        self.assertEqual(repository_of("volmarr/pub#3"), "volmarr/pub")
        self.assertEqual(repository_of("volmarr/pub"), "volmarr/pub")
        self.assertIsNone(repository_of("volmarr"))
        self.assertIsNone(repository_of("a/b/c"))
        self.assertIsNone(repository_of(None))
        self.assertIsNone(repository_of(""))
        self.assertEqual(derive_refs("repo.issue.create", "repo", "volmarr/pub#3", {}),
                         ("repo:volmarr/pub", "number:3"))
        self.assertEqual(derive_refs("repo.push", "repository", "volmarr/pub",
                                     {"transport": "http", "refs": ["refs/heads/main"]}),
                         ("repo:volmarr/pub", "refs/heads/main"))
        self.assertEqual(derive_refs("repo.pull_request.create", "repo", "volmarr/pub#2",
                                     {"number": 2}),
                         ("repo:volmarr/pub", "number:2"))
        self.assertEqual(derive_refs("auth.signup.success", "user", "7", None), ())
        self.assertEqual(derive_refs("repo.issue.update", "repo", "volmarr/pub",
                                     {"number": "NaN"}), ("repo:volmarr/pub",))

    def test_pure_visibility_law(self):
        pub = self.repos.get_repository("volmarr", "pub")
        priv = self.repos.get_repository("volmarr", "priv")
        base = dict(id=1, audit_seq=1, actor_kind="user", actor_id=self.owner.id,
                    actor="volmarr", refs=(), detail={},
                    outcome="success", created_at=1)
        pub_event = CanonicalEvent(verb="repo.issue.create", target_kind="repo",
                                   target_id="volmarr/pub", **base)
        priv_event = CanonicalEvent(verb="repo.issue.create", target_kind="repo",
                                    target_id="volmarr/priv", **base)
        self.assertTrue(event_visible_to(None, pub_event, pub))
        self.assertFalse(event_visible_to(None, priv_event, priv))
        self.assertTrue(event_visible_to(self.stranger, pub_event, pub))
        self.assertFalse(event_visible_to(self.stranger, priv_event, priv))
        self.assertTrue(event_visible_to(self.admin, priv_event, priv))
        acct = CanonicalEvent(verb="auth.signup.success", target_kind="user",
                              target_id=str(self.owner.id), **base)
        self.assertFalse(event_visible_to(self.stranger, acct, None))
        self.assertTrue(event_visible_to(self.owner, acct, None))

    def test_payload_shape(self):
        self._mutate_issues()
        event = [e for e in self.events.list_for_repo(self.owner, "volmarr", "pub")
                 if e.verb == "repo.issue.create"][0]
        payload = event_payload(event)
        self.assertEqual(payload["delivery_id"], f"evt-{event.id}")
        self.assertEqual(payload["event"], "repo.issue.create")
        self.assertEqual(payload["action"], "create")
        self.assertEqual(payload["actor"], "yrsa")
        self.assertEqual(payload["repository"], "volmarr/pub")
        self.assertEqual(payload["number"], 1)
        self.assertEqual(payload["refs"], ["repo:volmarr/pub", "number:1"])
        self.assertEqual(payload["occurred_at"], event.created_at)
        self.assertEqual(json.loads(payload_json(event)), payload)

    def test_render_escapes_and_teaches_empty(self):
        evil = CanonicalEvent(
            id=1, audit_seq=1, actor_kind="user", actor_id=9,
            actor="<script>alert(1)</script>", verb="repo.issue.create",
            target_kind="repo", target_id="volmarr/<b>pub</b>",
            refs=("repo:volmarr/<b>pub</b>",), detail={},
            outcome="success", created_at=5)
        page = render_events_page([evil])
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("1 event(s).", page)
        empty = render_events_page([])
        self.assertIn("No activity yet.", empty)
        self.assertIn("0 event(s).", empty)

    def test_pins_schema_91_taxonomy_127(self):
        self.assertEqual(schema_version(self.conn), 91)
        self.assertEqual(db.MIGRATIONS[-1][0], 91)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 127)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 31)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 83)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
        self.assertIn("events", tables)


if __name__ == "__main__":
    unittest.main()
