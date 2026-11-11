"""S-232 acceptance battery: following.

Acceptance (roadmap S-232): follow users to see
their public activity; follower lists on profiles;
no algorithmic ranking, chronological truth only.
The feed carries a followed person's actions
exactly when S-230's is_profile_public judgement
calls them genuinely public.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.following import (
    FOLLOWING_FEED_SCOPE, FOLLOWING_SCOPE, FollowLists,
    FollowState, FollowingError, FollowingStore, decide_follow,
    following_empty_words, render_follow_lists,
    render_follow_state, render_following_feed_page,
    render_profile_follows_section)
from samverk.issue_comments import IssueCommentStore
from samverk.issues import IssueStore
from samverk.organizations import OrganizationStore
from samverk.repositories import RepositoryStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now
    def tick(self, step=10):
        self.now += step


class PureLawTests(unittest.TestCase):
    def test_decide_follow_truth_table(self):
        self.assertTrue(decide_follow(False, True))
        self.assertTrue(decide_follow(True, False))
        self.assertFalse(decide_follow(True, True))
        self.assertFalse(decide_follow(False, False))


class FollowingTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=self.clock)
        self.viewer = self.accounts.register("volmarr", "correct horse battery")
        self.yrsa = self.accounts.register("yrsa", "correct horse battery")
        self.tess = self.accounts.register("tess", "correct horse battery")
        self.stranger = self.accounts.register("mallory", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.viewer.id,))
        self.admin = self.accounts.get_by_id(self.viewer.id)
        self.repos = RepositoryStore(self.conn, self.root, self.accounts, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit)
        self.comments = IssueCommentStore(self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.follows = FollowingStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)
        for who in (self.yrsa, self.tess):
            self.repos.create_repository(who.id, who.username, "pub", visibility="public")
            self.repos.create_repository(who.id, who.username, "priv", visibility="private")
            self.repos.create_repository(who.id, who.username, "int", visibility="internal")

    def _audit_count(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    def _audit_actions(self):
        rows = self.conn.execute("SELECT action FROM audit_log ORDER BY seq").fetchall()
        return [r["action"] for r in rows]

    def _row_count(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM user_follows").fetchone()["n"]

    def _mutate(self, who):
        self.clock.tick()
        self.issues.create_issue(who, who.username, "pub", "Crash on startup")
        self.clock.tick()
        self.comments.add_comment(who, who.username, "pub", 1, "Looking now")
        self.clock.tick()
        self.issues.create_issue(who, who.username, "priv", "Secret plans")
        self.clock.tick()
        self.issues.create_issue(who, who.username, "int", "Crew notes")

    # -- follow / unfollow ---------------------------------------
    def test_follow_and_unfollow_round_trip(self):
        state = self.follows.follow(self.viewer, "yrsa")
        self.assertTrue(state.following)
        self.assertEqual(state.subject, "yrsa")
        self.assertEqual(state.follower_count, 1)
        self.assertTrue(self.follows.is_following(self.viewer, "yrsa"))
        state = self.follows.unfollow(self.viewer, "yrsa")
        self.assertFalse(state.following)
        self.assertEqual(state.follower_count, 0)
        self.assertFalse(self.follows.is_following(self.viewer, "yrsa"))
        self.assertEqual(self._row_count(), 0)

    def test_subject_forms_resolve_to_one_follow(self):
        self.follows.follow(self.viewer, self.yrsa)
        self.follows.follow(self.viewer, self.yrsa.id)
        self.follows.follow(self.viewer, "yrsa")
        self.assertEqual(self._row_count(), 1)
        self.assertEqual(self.follows.follower_count("yrsa"), 1)

    def test_self_follow_refused_and_stores_nothing(self):
        before = self._audit_count()
        with self.assertRaises(FollowingError) as caught:
            self.follows.follow(self.viewer, "volmarr")
        self.assertEqual(caught.exception.reason, "self_follow")
        with self.assertRaises(FollowingError) as caught:
            self.follows.follow(self.viewer, self.viewer)
        self.assertEqual(caught.exception.reason, "self_follow")
        self.assertEqual(self._row_count(), 0)
        self.assertEqual(self._audit_count(), before)

    def test_unknown_user_refused_on_every_face(self):
        faces = (
            lambda: self.follows.follow(self.viewer, "ghost"),
            lambda: self.follows.unfollow(self.viewer, "ghost"),
            lambda: self.follows.is_following(self.viewer, "ghost"),
            lambda: self.follows.follow_state(None, "ghost"),
            lambda: self.follows.followers("ghost"),
            lambda: self.follows.following_of(99999),
            lambda: self.follows.follower_count("ghost"),
            lambda: self.follows.follow_lists("ghost"),
        )
        for face in faces:
            with self.assertRaises(FollowingError) as caught:
                face()
            self.assertEqual(caught.exception.reason, "no_such_user")
        self.assertEqual(self._row_count(), 0)

    def test_anonymous_refused_for_mutations_and_feed(self):
        for face in (lambda: self.follows.follow(None, "yrsa"),
                     lambda: self.follows.unfollow(None, "yrsa"),
                     lambda: self.follows.following_feed(None)):
            with self.assertRaises(FollowingError) as caught:
                face()
            self.assertEqual(caught.exception.reason, "login_required")
        self.assertEqual(self._row_count(), 0)
        self.assertFalse(self.follows.is_following(None, "yrsa"))
        self.assertFalse(self.follows.follow_state(None, "yrsa").following)

    def test_follow_is_idempotent_one_row_one_witness(self):
        before = self._audit_count()
        self.follows.follow(self.viewer, "yrsa")
        self.follows.follow(self.viewer, "yrsa")
        self.follows.follow(self.viewer, "yrsa")
        self.assertEqual(self._row_count(), 1)
        self.assertEqual(self._audit_count(), before + 1)
        self.assertEqual(self._audit_actions().count("auth.follow"), 1)

    def test_unfollow_never_followed_is_quiet_noop(self):
        before = self._audit_count()
        state = self.follows.unfollow(self.viewer, "yrsa")
        self.assertFalse(state.following)
        self.assertEqual(self._audit_count(), before)
        self.assertNotIn("auth.unfollow", self._audit_actions())

    def test_only_real_changes_are_witnessed(self):
        self.follows.follow(self.viewer, "yrsa")
        self.follows.unfollow(self.viewer, "yrsa")
        self.follows.unfollow(self.viewer, "yrsa")
        actions = self._audit_actions()
        self.assertEqual(actions.count("auth.follow"), 1)
        self.assertEqual(actions.count("auth.unfollow"), 1)

    def test_no_seam_removes_another_accounts_follow(self):
        self.follows.follow(self.stranger, "yrsa")
        self.follows.unfollow(self.viewer, "yrsa")
        self.assertTrue(self.follows.is_following(self.stranger, "yrsa"))
        self.assertEqual(self.follows.follower_count("yrsa"), 1)

    # -- profile lists ---------------------------------------------
    def test_follower_and_following_lists_in_begin_order(self):
        self.clock.tick(); self.follows.follow(self.viewer, "yrsa")
        self.clock.tick(); self.follows.follow(self.stranger, "yrsa")
        self.clock.tick(); self.follows.follow(self.tess, "yrsa")
        self.clock.tick(); self.follows.follow(self.viewer, "tess")
        self.assertEqual(self.follows.followers("yrsa"), ("volmarr", "mallory", "tess"))
        self.assertEqual(self.follows.following_of("volmarr"), ("yrsa", "tess"))
        lists = self.follows.follow_lists("yrsa")
        self.assertEqual(lists.follower_count, 3)
        self.assertEqual(lists.following_count, 0)
        self.assertEqual(self.follows.follower_count("yrsa"), 3)
        self.assertEqual(self.follows.following_count("volmarr"), 2)

    def test_lists_are_public_facts_readable_by_anyone(self):
        self.follows.follow(self.viewer, "yrsa")
        lists = self.follows.follow_lists("yrsa")
        self.assertEqual(lists.followers, ("volmarr",))
        page = render_follow_lists(lists)
        self.assertIn("volmarr", page)
        self.assertIn("1 followers", page)

    def test_counts_are_live_after_unfollow(self):
        self.follows.follow(self.viewer, "yrsa")
        self.follows.follow(self.stranger, "yrsa")
        self.assertEqual(self.follows.follower_count("yrsa"), 2)
        self.follows.unfollow(self.stranger, "yrsa")
        self.assertEqual(self.follows.follower_count("yrsa"), 1)
        self.assertEqual(self.follows.followers("yrsa"), ("volmarr",))

    def test_follow_state_words_and_panel(self):
        self.follows.follow(self.viewer, "yrsa")
        state = self.follows.follow_state(self.viewer, "yrsa")
        self.assertIsInstance(state, FollowState)
        self.assertIn("followed by you", state.words)
        self.assertIn("1 followers", state.words)
        panel = render_follow_state(state)
        self.assertIn("followed by you", panel)
        other = self.follows.follow_state(self.stranger, "yrsa")
        self.assertIn("not followed by you", other.words)

    def test_lists_render_empty_states_and_order(self):
        page = render_profile_follows_section(self.follows.follow_lists("yrsa"))
        self.assertIn("No followers yet", page)
        self.assertIn("Not following anyone yet", page)
        self.clock.tick(); self.follows.follow(self.viewer, "yrsa")
        self.clock.tick(); self.follows.follow(self.stranger, "yrsa")
        page = render_follow_lists(self.follows.follow_lists("yrsa"))
        self.assertIn("2 followers, in the order they began following", page)
        self.assertLess(page.index("volmarr"), page.index("mallory"))

    # -- the following feed ------------------------------------------
    def test_feed_shows_followed_public_activity_newest_first(self):
        self.follows.follow(self.viewer, "yrsa")
        self._mutate(self.yrsa)
        feed = self.follows.following_feed(self.viewer)
        self.assertTrue(feed.events)
        self.assertTrue(all(e.actor_id == self.yrsa.id for e in feed.events))
        self.assertTrue(all((e.repository or "").startswith("yrsa/pub") for e in feed.events))
        self.assertEqual(feed.events[0].verb, "repo.issue.comment")
        self.assertIn("repo.issue.create", [e.verb for e in feed.events])

    def test_feed_excludes_unfollowed_and_never_followed(self):
        self.follows.follow(self.viewer, "yrsa")
        self._mutate(self.yrsa)
        self._mutate(self.tess)
        feed = self.follows.following_feed(self.viewer)
        self.assertTrue(feed.events)
        self.assertFalse(any(e.actor_id == self.tess.id for e in feed.events))
        page = render_following_feed_page(feed)
        self.assertNotIn("tess/priv", page)
        self.assertNotIn("tess/pub", page)

    def test_feed_is_chronological_truth_merged_across_people(self):
        self.follows.follow(self.viewer, "yrsa")
        self.follows.follow(self.viewer, "tess")
        self.clock.tick(); self.issues.create_issue(self.yrsa, "yrsa", "pub", "First")
        self.clock.tick(); self.issues.create_issue(self.tess, "tess", "pub", "Second")
        self.clock.tick(); self.issues.create_issue(self.yrsa, "yrsa", "pub", "Third")
        feed = self.follows.following_feed(self.viewer)
        shown = [e for e in feed.events if e.verb == "repo.issue.create"]
        actors = [e.actor for e in shown]
        self.assertEqual(actors[:3], ["yrsa", "tess", "yrsa"])
        ids = [e.id for e in feed.events]
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertEqual(len(ids), len(set(ids)))
        stamps = [e.created_at for e in feed.events]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_feed_never_shows_private_or_internal_for_anyone(self):
        self.follows.follow(self.viewer, "yrsa")
        self.follows.follow(self.admin, "yrsa")
        self._mutate(self.yrsa)
        for reader in (self.viewer, self.admin):
            feed = self.follows.following_feed(reader)
            targets = [e.target_id or "" for e in feed.events]
            self.assertFalse(any("priv" in t for t in targets), targets)
            self.assertFalse(any("/int" in t for t in targets), targets)
            self.assertFalse(any(e.repository in ("yrsa/priv", "yrsa/int") for e in feed.events))
            page = render_following_feed_page(feed)
            self.assertNotIn("Secret plans", page)
            self.assertNotIn("Crew notes", page)
        own = self.follows.following_feed(self.yrsa)
        self.assertFalse(any(e.repository in ("yrsa/priv", "yrsa/int") for e in own.events))

    def test_feed_excludes_non_public_non_repo_actions(self):
        self.follows.follow(self.viewer, "yrsa")
        feed = self.follows.following_feed(self.viewer)
        self.assertFalse(any(e.verb.startswith("auth.signup") for e in feed.events))
        self.assertFalse(any(e.verb in ("auth.follow", "auth.unfollow") for e in feed.events))

    def test_feed_includes_followed_org_actions(self):
        orgs = OrganizationStore(self.conn, self.accounts, audit=self.audit)
        self.follows.follow(self.viewer, "yrsa")
        orgs.create_organization(self.yrsa.id, "crew")
        feed = self.follows.following_feed(self.viewer)
        self.assertIn("auth.organization.create", [e.verb for e in feed.events])

    def test_unfollow_removes_the_person_from_the_feed(self):
        self.follows.follow(self.viewer, "yrsa")
        self._mutate(self.yrsa)
        self.assertTrue(self.follows.following_feed(self.viewer).events)
        self.follows.unfollow(self.viewer, "yrsa")
        feed = self.follows.following_feed(self.viewer)
        self.assertEqual(feed.events, ())
        self.assertEqual(feed.count, 0)

    def test_feed_counts_count_only_what_is_shown(self):
        self.follows.follow(self.viewer, "yrsa")
        self._mutate(self.yrsa)
        feed = self.follows.following_feed(self.viewer)
        self.assertEqual(feed.count, len(feed.events))
        page = render_following_feed_page(feed)
        self.assertIn(f"{feed.count} events", page)
        self.assertNotIn("yrsa/priv", page)
        self.assertNotIn("yrsa/int", page)

    def test_feed_limit_is_honoured(self):
        self.follows.follow(self.viewer, "yrsa")
        self._mutate(self.yrsa)
        feed = self.follows.following_feed(self.viewer, limit=1)
        self.assertEqual(feed.count, 1)
        self.assertEqual(feed.events[0].verb, "repo.issue.comment")

    def test_feed_empty_states(self):
        feed = self.follows.following_feed(self.stranger)
        self.assertEqual(feed.events, ())
        page = render_following_feed_page(feed)
        self.assertIn("No followed activity yet", page)
        self.assertIn(following_empty_words("mallory"), page)
        self.follows.follow(self.viewer, "tess")
        feed = self.follows.following_feed(self.viewer)
        self.assertFalse(any(e.repository == "tess/priv" for e in feed.events))

    def test_feed_page_labels_chronology_and_no_ranking(self):
        self.follows.follow(self.viewer, "yrsa")
        self._mutate(self.yrsa)
        page = render_following_feed_page(self.follows.following_feed(self.viewer))
        self.assertIn("no algorithmic ranking", page)
        self.assertIn("newest first", page.lower())
        self.assertIn("private and internal", page)
        self.assertIn(FOLLOWING_SCOPE.split(". ")[0], page)
        self.assertIn(FOLLOWING_FEED_SCOPE[:20], page)

    def test_reads_write_and_audit_nothing(self):
        self.follows.follow(self.viewer, "yrsa")
        self._mutate(self.yrsa)
        before = self._audit_count()
        rows_before = self._row_count()
        self.follows.follow_lists("yrsa")
        self.follows.follow_state(self.viewer, "yrsa")
        self.follows.following_feed(self.viewer)
        self.assertEqual(self._audit_count(), before)
        self.assertEqual(self._row_count(), rows_before)

    # -- rendering ---------------------------------------------------
    def test_render_escapes_user_text(self):
        lists = FollowLists(subject="<u>yrsa</u>", followers=("<script>alert(1)</script>",), following=())
        page = render_follow_lists(lists)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;u&gt;yrsa&lt;/u&gt;", page)
        self.assertNotIn("<u>yrsa</u>", page)

    def test_pins_schema_and_taxonomy(self):
        self.assertEqual(schema_version(self.conn), 109)
        self.assertEqual(db.MIGRATIONS[-1][0], 109)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertIn("auth.follow", taxonomy.AUDIT_EVENTS)
        self.assertIn("auth.unfollow", taxonomy.AUDIT_EVENTS)


if __name__ == "__main__":
    unittest.main()
