"""S-229 acceptance battery: activity feeds.

Acceptance (roadmap S-229): activity feeds -- user
feed (own actions), repo feed, and the instance's
public-activity feed for public repos only.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.activity_feeds import (
    FEED_KINDS, PUBLIC_FEED_SCOPE, ActivityFeed, ActivityFeedError,
    ActivityFeedStore, empty_words, feed_scope, in_public_feed,
    render_feed_entry, render_public_feed_page, render_repo_feed_page,
    render_user_feed_page)
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.event_store import CanonicalEvent, EventStore
from samverk.issue_comments import IssueCommentStore
from samverk.issues import IssueStore
from samverk.organizations import OrganizationStore
from samverk.repositories import RepositoryStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class ActivityFeedTests(unittest.TestCase):
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
        self.feeds = ActivityFeedStore(self.conn, self.repos, self.accounts, events=self.events)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.repos.create_repository(self.owner.id, "volmarr", "int", visibility="internal")

    # -- helpers ------------------------------------------------
    def _audit_count(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    def _mutate_pub(self):
        self.issues.create_issue(self.reader, "volmarr", "pub", "Crash on startup")
        self.comments.add_comment(self.owner, "volmarr", "pub", 1, "Looking now")
        self.issues.close_issue(self.owner, "volmarr", "pub", 1)

    def _mutate_priv(self):
        self.issues.create_issue(self.owner, "volmarr", "priv", "Secret plans")

    def _mutate_int(self):
        self.issues.create_issue(self.owner, "volmarr", "int", "Crew notes")

    # -- the user feed -------------------------------------------
    def test_user_feed_shows_only_own_actions(self):
        self._mutate_pub()
        feed = self.feeds.user_feed(self.reader, self.reader)
        self.assertEqual(feed.kind, "user")
        self.assertEqual(feed.subject, "yrsa")
        self.assertTrue(feed.events)
        self.assertTrue(all(e.actor_id == self.reader.id for e in feed.events))
        verbs = [e.verb for e in feed.events]
        self.assertIn("repo.issue.create", verbs)
        # The owner's comment on the same issue is not her action.
        self.assertNotIn("repo.issue.comment", verbs)

    def test_user_feed_newest_first_chronological(self):
        self._mutate_pub()
        feed = self.feeds.user_feed(self.admin, self.admin)
        ids = [e.id for e in feed.events]
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertEqual(len(ids), len(set(ids)))
        # The owner's latest pub action (the close) leads his feed.
        self.assertEqual(feed.events[0].verb, "repo.issue.close")
        stamps = [e.created_at for e in feed.events]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_user_feed_self_sees_own_private_actions(self):
        self._mutate_priv()
        feed = self.feeds.user_feed(self.owner, self.owner)
        targets = [e.target_id for e in feed.events]
        self.assertIn("volmarr/priv#1", targets)

    def test_user_feed_stranger_hides_private(self):
        self._mutate_pub(); self._mutate_priv(); self._mutate_int()
        feed = self.feeds.user_feed(self.stranger, self.owner)
        targets = [e.target_id or "" for e in feed.events]
        self.assertTrue(any(t.startswith("volmarr/pub") for t in targets))
        # Internal (personal repo): a signed-in member may read it.
        self.assertTrue(any(t.startswith("volmarr/int") for t in targets))
        self.assertFalse(any("priv" in t for t in targets))

    def test_user_feed_anonymous_sees_public_only(self):
        self._mutate_pub(); self._mutate_priv(); self._mutate_int()
        feed = self.feeds.user_feed(None, self.owner)
        targets = [e.target_id or "" for e in feed.events]
        self.assertTrue(any(t.startswith("volmarr/pub") for t in targets))
        self.assertFalse(any("priv" in t or "/int" in t for t in targets))

    def test_user_feed_org_events_are_public_facts(self):
        orgs = OrganizationStore(self.conn, self.accounts, audit=self.audit)
        orgs.create_organization(self.owner.id, "crew")
        feed = self.feeds.user_feed(self.stranger, self.owner)
        self.assertIn("auth.organization.create", [e.verb for e in feed.events])

    def test_unknown_actor_refused(self):
        for actor in ("ghost", 99999):
            with self.assertRaises(ActivityFeedError) as caught:
                self.feeds.user_feed(self.owner, actor)
            self.assertEqual(caught.exception.reason, "no_such_user")

    # -- the repository feed --------------------------------------
    def test_repo_feed_shows_repo_actions_in_order(self):
        self._mutate_pub(); self._mutate_priv()
        feed = self.feeds.repo_feed(self.stranger, "volmarr", "pub")
        self.assertEqual(feed.kind, "repository")
        self.assertEqual(feed.subject, "volmarr/pub")
        self.assertTrue(all(e.repository == "volmarr/pub" for e in feed.events))
        self.assertEqual(
            [e.verb for e in feed.events],
            ["repo.issue.close", "repo.issue.comment",
             "repo.issue.create", "repo.create"])

    def test_repo_feed_private_denied_uniformly(self):
        self._mutate_priv()
        for viewer in (self.stranger, self.reader, None):
            with self.assertRaises(ActivityFeedError) as caught:
                self.feeds.repo_feed(viewer, "volmarr", "priv")
            self.assertEqual(caught.exception.reason, "repo_not_found")
        # A missing repository answers identically: no enumeration.
        with self.assertRaises(ActivityFeedError) as caught:
            self.feeds.repo_feed(self.owner, "volmarr", "missing")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        # The owner reads it whole.
        feed = self.feeds.repo_feed(self.owner, "volmarr", "priv")
        self.assertIn("repo.issue.create", [e.verb for e in feed.events])

    def test_repo_feed_internal_member_reads_anonymous_denied(self):
        self._mutate_int()
        feed = self.feeds.repo_feed(self.stranger, "volmarr", "int")
        self.assertIn("repo.issue.create", [e.verb for e in feed.events])
        with self.assertRaises(ActivityFeedError) as caught:
            self.feeds.repo_feed(None, "volmarr", "int")
        self.assertEqual(caught.exception.reason, "repo_not_found")

    # -- the instance public feed ----------------------------------
    def test_public_feed_includes_public_actions(self):
        self._mutate_pub()
        feed = self.feeds.public_feed()
        self.assertEqual(feed.kind, "public")
        self.assertTrue(all(e.repository == "volmarr/pub" for e in feed.events))
        self.assertIn("repo.issue.create", [e.verb for e in feed.events])

    def test_public_feed_excludes_private_even_for_admin(self):
        self._mutate_pub(); self._mutate_priv()
        feed = self.feeds.public_feed(viewer=self.admin)
        self.assertFalse(any("priv" in (e.target_id or "") for e in feed.events))
        self.assertNotIn("volmarr/priv", render_public_feed_page(feed))

    def test_public_feed_excludes_internal_even_for_admin(self):
        self._mutate_int()
        feed = self.feeds.public_feed(viewer=self.admin)
        self.assertFalse(any("/int" in (e.target_id or "") for e in feed.events))
        self.assertNotIn("volmarr/int", render_public_feed_page(feed))

    def test_public_feed_same_for_admin_anonymous_and_actor(self):
        self._mutate_pub(); self._mutate_priv(); self._mutate_int()
        seen = []
        for viewer in (self.admin, None, self.reader):
            feed = self.feeds.public_feed(viewer=viewer)
            seen.append([(e.verb, e.target_id) for e in feed.events])
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(seen[0], seen[2])

    def test_public_feed_excludes_non_repo_events(self):
        self._mutate_pub()
        orgs = OrganizationStore(self.conn, self.accounts, audit=self.audit)
        orgs.create_organization(self.owner.id, "crew")
        feed = self.feeds.public_feed()
        self.assertTrue(all(e.repository is not None for e in feed.events))
        self.assertNotIn("auth.organization.create", [e.verb for e in feed.events])
        self.assertNotIn("auth.signup.success", [e.verb for e in feed.events])

    def test_in_public_feed_pure_law(self):
        pub = self.repos.get_repository("volmarr", "pub")
        priv = self.repos.get_repository("volmarr", "priv")
        internal = self.repos.get_repository("volmarr", "int")
        self.assertTrue(in_public_feed(pub))
        self.assertFalse(in_public_feed(priv))
        self.assertFalse(in_public_feed(internal))
        self.assertFalse(in_public_feed(None))
        self.assertEqual(feed_scope("public", "public"), PUBLIC_FEED_SCOPE)
        self.assertIn("not even for site administrators", PUBLIC_FEED_SCOPE)
        self.assertEqual(FEED_KINDS, ("user", "repository", "public"))

    # -- the leakage law across every face --------------------------
    def test_no_feed_leaks_unreadable_repo_to_stranger(self):
        self._mutate_pub(); self._mutate_priv()
        user = self.feeds.user_feed(self.stranger, self.owner)
        public = self.feeds.public_feed(viewer=self.stranger)
        for feed in (user, public):
            self.assertFalse(any("priv" in (e.target_id or "") for e in feed.events))
        self.assertNotIn("volmarr/priv", render_user_feed_page(user))
        self.assertNotIn("volmarr/priv", render_public_feed_page(public))
        with self.assertRaises(ActivityFeedError):
            self.feeds.repo_feed(self.stranger, "volmarr", "priv")

    def test_counts_count_only_shown(self):
        self._mutate_pub(); self._mutate_priv()
        own = self.feeds.user_feed(self.owner, self.owner)
        stranger = self.feeds.user_feed(self.stranger, self.owner)
        self.assertEqual(own.count, len(own.events))
        self.assertEqual(stranger.count, len(stranger.events))
        self.assertLess(stranger.count, own.count)
        self.assertIn(f"{stranger.count} event", stranger.words)

    def test_limit_clamps(self):
        self._mutate_pub(); self._mutate_priv()
        full = self.feeds.user_feed(self.owner, self.owner, limit=500)
        two = self.feeds.user_feed(self.owner, self.owner, limit=2)
        self.assertEqual(two.count, 2)
        self.assertEqual([e.id for e in two.events],
                         [e.id for e in full.events[:2]])
        one = self.feeds.public_feed(limit=0)
        self.assertEqual(one.count, 1)

    # -- the read model itself ---------------------------------------
    def test_feed_is_read_model_over_event_store(self):
        self._mutate_pub()
        feed = self.feeds.repo_feed(self.owner, "volmarr", "pub")
        stored = {r["id"] for r in self.conn.execute("SELECT id FROM events").fetchall()}
        self.assertTrue(feed.events)
        self.assertTrue(all(isinstance(e, CanonicalEvent) for e in feed.events))
        self.assertTrue(all(e.id in stored for e in feed.events))

    def test_feed_reads_are_never_stale(self):
        before = self.feeds.repo_feed(self.owner, "volmarr", "pub")
        self.assertNotIn("repo.issue.create", [e.verb for e in before.events])
        self.issues.create_issue(self.owner, "volmarr", "pub", "Fresh")
        after = self.feeds.repo_feed(self.owner, "volmarr", "pub")
        self.assertIn("repo.issue.create", [e.verb for e in after.events])

    def test_feeds_write_nothing(self):
        self._mutate_pub(); self._mutate_priv()
        self.feeds.public_feed()  # materialise once
        audits = self._audit_count()
        rows = self.conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        self.feeds.user_feed(self.stranger, self.owner)
        self.feeds.repo_feed(self.owner, "volmarr", "pub")
        self.feeds.public_feed(viewer=self.admin)
        self.assertEqual(self._audit_count(), audits)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"], rows)

    def test_pins_schema_and_taxonomy(self):
        self.assertEqual(schema_version(self.conn), 105)
        self.assertEqual(db.MIGRATIONS[-1][0], 105)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)

    # -- rendering -----------------------------------------------------
    def test_render_pages_label_and_count(self):
        self._mutate_pub(); self._mutate_priv()
        user_page = render_user_feed_page(self.feeds.user_feed(self.owner, self.owner))
        self.assertIn("Activity — volmarr", user_page)
        self.assertIn("newest first", user_page)
        self.assertIn("repo.issue.create", user_page)
        repo_page = render_repo_feed_page(self.feeds.repo_feed(self.owner, "volmarr", "pub"))
        self.assertIn("volmarr/pub", repo_page)
        self.assertIn("only to people who can read", repo_page)
        public_page = render_public_feed_page(self.feeds.public_feed(viewer=self.admin))
        self.assertIn("Public activity", public_page)
        self.assertIn("public repositories", public_page)
        self.assertIn("not even for site administrators", public_page)

    def test_render_escapes_user_text(self):
        event = CanonicalEvent(
            id=1, audit_seq=1, actor_kind="user", actor_id=1,
            actor="<script>alert(1)</script>", verb="repo.issue.create",
            target_kind="repo", target_id="x/<b>bold</b>",
            refs=("<i>ref</i>",), detail={}, outcome="success", created_at=1)
        entry = render_feed_entry(event)
        self.assertIn("&lt;script&gt;", entry)
        self.assertNotIn("<script>", entry)
        feed = ActivityFeed(kind="user", subject="<u>mallory</u>",
                            scope="scope", events=(event,))
        page = render_user_feed_page(feed)
        self.assertIn("&lt;u&gt;mallory&lt;/u&gt;", page)
        self.assertNotIn("<u>mallory</u>", page)

    def test_empty_user_feed_for_stranger_viewing_new_user(self):
        newbie = self.accounts.register("newbie", "correct horse battery")
        feed = self.feeds.user_feed(self.stranger, newbie)
        self.assertEqual(feed.events, ())
        self.assertEqual(feed.count, 0)
        page = render_user_feed_page(feed)
        self.assertIn("No activity by newbie", page)

    def test_empty_renders_for_each_kind(self):
        for kind, subject, needle in (
                ("user", "yrsa", "No activity by yrsa"),
                ("repository", "volmarr/pub", "No activity in volmarr/pub yet"),
                ("public", "public", "No public activity yet")):
            feed = ActivityFeed(kind=kind, subject=subject,
                                scope=feed_scope(kind, subject), events=())
            page = render_user_feed_page(feed)
            self.assertIn(needle, page)
            self.assertIn(escape_needle(empty_words(kind, subject)), page)


def escape_needle(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class EmptyPublicFeedTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.owner.id,))
        self.admin = self.accounts.get_by_id(self.owner.id)
        self.repos = RepositoryStore(self.conn, self.root, self.accounts, audit=self.audit)
        self.feeds = ActivityFeedStore(self.conn, self.repos, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")

    def test_public_feed_empty_and_render(self):
        feed = self.feeds.public_feed(viewer=self.admin)
        self.assertEqual(feed.events, ())
        page = render_public_feed_page(feed)
        self.assertIn("No public activity yet", page)
        self.assertIn("private and internal repositories never do", page)


if __name__ == "__main__":
    unittest.main()
