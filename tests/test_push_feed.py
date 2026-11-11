"""S-234 acceptance battery: push feed for owners.

Acceptance (roadmap S-234): pushes to your repos
surface in your feed with commit summaries (from
S-090 events). The feed is a read model over
S-090's push_events rows, gathered by repository
ownership, summarised live from each repository's
history: no new storage, no new audit event.

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
from samverk.hooks import RefUpdate
from samverk.push_events import PushEventStore
from samverk.push_feed import (
    PUSH_FEED_SCOPE, SUBJECT_LIMIT, PushFeedError, PushFeedStore,
    push_feed_empty_words, range_revspec, render_push_feed_entry,
    render_push_feed_page, short_ref, summarise_update)
from samverk.repositories import RepositoryStore
from test_git_http_upload import seed_commit

ZERO = "0" * 40


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now
    def tick(self, step=10):
        self.now += step


class PushFeedTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts, audit=self.audit)
        self.pushes = PushEventStore(self.conn, self.repos, time_fn=self.clock)
        self.feed = PushFeedStore(self.conn, self.repos, self.accounts, self.pushes)
        self.repos.create_repository(self.owner.id, "volmarr", "forge",
                                     visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "vault",
                                     visibility="private")
        self.repos.create_repository(self.other.id, "yrsa", "reader",
                                     visibility="public")

    def _audit_count(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    def _two_commits(self, repo="forge", owner="volmarr"):
        first = seed_commit(self.repos, owner, repo,
                            text=b"one\n", message=b"first commit\n")
        second = seed_commit(self.repos, owner, repo,
                             text=b"two\n", parent=first,
                             message=b"second commit\n")
        return first, second

    def _push(self, owner, repo, updates, **kw):
        kw.setdefault("actor_kind", "user")
        kw.setdefault("actor_id", self.owner.id)
        kw.setdefault("transport", "http")
        return self.pushes.record_push(owner, repo, updates=updates, **kw)

    # -- pins -------------------------------------------------
    def test_pins_schema_99_taxonomy_133_no_new_storage(self):
        self.assertEqual(schema_version(self.conn), 108)
        self.assertEqual(db.MIGRATIONS[-1][0], 108)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertIn("repo.push", taxonomy.AUDIT_EVENTS)

    def test_reading_the_feed_writes_and_witnesses_nothing(self):
        first, second = self._two_commits()
        self._push("volmarr", "forge",
                   (RefUpdate("refs/heads/main", first, second),))
        before = self._audit_count()
        self.feed.push_feed(self.owner)
        self.feed.push_count(self.owner)
        self.assertEqual(self._audit_count(), before)

    # -- the gate ----------------------------------------------
    def test_anonymous_is_refused(self):
        with self.assertRaises(PushFeedError) as caught:
            self.feed.push_feed(None)
        self.assertEqual(caught.exception.reason, "authentication_required")
        with self.assertRaises(PushFeedError):
            self.feed.push_count(None)
        with self.assertRaises(PushFeedError):
            self.feed.push_feed(99999)

    def test_empty_feed_and_its_teaching_words(self):
        feed = self.feed.push_feed(self.owner)
        self.assertEqual(feed.owner, "volmarr")
        self.assertEqual(feed.entries, ())
        self.assertEqual(feed.total, 0)
        self.assertEqual(feed.count, 0)
        self.assertEqual(self.feed.push_count(self.owner), 0)
        self.assertIn(PUSH_FEED_SCOPE, feed.words)
        words = push_feed_empty_words("volmarr")
        self.assertIn("No pushes to volmarr's repositories yet", words)
        self.assertIn("commits", words)
        page = render_push_feed_page(feed)
        self.assertIn("Pushes to your repositories", page)
        self.assertIn("No pushes", page)

    # -- surfacing ----------------------------------------------
    def test_push_to_own_repo_surfaces_with_commit_summary(self):
        first, second = self._two_commits()
        self._push("volmarr", "forge",
                   (RefUpdate("refs/heads/main", first, second),))
        feed = self.feed.push_feed(self.owner)
        self.assertEqual(feed.total, 1)
        entry = feed.entries[0]
        self.assertEqual(entry.full_name, "volmarr/forge")
        self.assertEqual(entry.actor_label, "volmarr")
        self.assertEqual(entry.transport, "http")
        summary = entry.summaries[0]
        self.assertEqual(summary.kind, "updated")
        self.assertEqual(summary.name, "main")
        self.assertTrue(summary.available)
        self.assertEqual(summary.commit_count, 1)
        self.assertEqual(summary.subjects, ("second commit",))
        self.assertIn("second commit", entry.words)

    def test_creation_push_counts_every_landed_commit(self):
        first, second = self._two_commits()
        self._push("volmarr", "forge",
                   (RefUpdate("refs/heads/main", ZERO, second),))
        entry = self.feed.push_feed(self.owner).entries[0]
        summary = entry.summaries[0]
        self.assertEqual(summary.kind, "created")
        self.assertEqual(summary.commit_count, 2)
        self.assertEqual(set(summary.subjects),
                         {"first commit", "second commit"})

    def test_pushes_to_other_peoples_repos_never_surface(self):
        first, second = self._two_commits("reader", "yrsa")
        self._push("yrsa", "reader",
                   (RefUpdate("refs/heads/main", first, second),),
                   actor_id=self.other.id)
        mine = self.feed.push_feed(self.owner)
        self.assertEqual(mine.total, 0)
        self.assertEqual(mine.entries, ())
        theirs = self.feed.push_feed(self.other)
        self.assertEqual(theirs.total, 1)
        self.assertEqual(theirs.entries[0].full_name, "yrsa/reader")

    def test_push_to_own_private_repo_surfaces_for_owner(self):
        first, second = self._two_commits("vault")
        self._push("volmarr", "vault",
                   (RefUpdate("refs/heads/main", first, second),),
                   transport="ssh")
        feed = self.feed.push_feed(self.owner)
        self.assertEqual(feed.total, 1)
        self.assertEqual(feed.entries[0].full_name, "volmarr/vault")
        self.assertEqual(feed.entries[0].transport, "ssh")

    def test_another_accounts_push_to_my_repo_surfaces(self):
        first, second = self._two_commits()
        self._push("volmarr", "forge",
                   (RefUpdate("refs/heads/main", first, second),),
                   actor_id=self.other.id)
        entry = self.feed.push_feed(self.owner).entries[0]
        self.assertEqual(entry.actor_label, "yrsa")
        self.assertIn("yrsa pushed to volmarr/forge", entry.words)

    def test_deploy_key_and_system_actors_are_named_in_words(self):
        first, second = self._two_commits()
        self._push("volmarr", "forge",
                   (RefUpdate("refs/heads/main", first, second),),
                   actor_kind="deploy_key", actor_id=None)
        self.clock.tick()
        third = seed_commit(self.repos, "volmarr", "forge",
                            text=b"three\n", parent=second,
                            message=b"third commit\n")
        self._push("volmarr", "forge",
                   (RefUpdate("refs/heads/main", second, third),),
                   actor_kind="system", actor_id=None)
        labels = [e.actor_label for e in self.feed.push_feed(self.owner).entries]
        self.assertEqual(labels, ["the system", "a deploy key"])

    def test_newest_push_first(self):
        first, second = self._two_commits()
        older = self._push("volmarr", "forge",
                           (RefUpdate("refs/heads/main", first, second),))
        self.clock.tick()
        third = seed_commit(self.repos, "volmarr", "forge",
                            text=b"three\n", parent=second,
                            message=b"third commit\n")
        newer = self._push("volmarr", "forge",
                           (RefUpdate("refs/heads/main", second, third),))
        ids = [e.event_id for e in self.feed.push_feed(self.owner).entries]
        self.assertEqual(ids, [newer.id, older.id])

    def test_one_push_with_two_refs_is_one_entry_two_summaries(self):
        first, second = self._two_commits()
        self._push("volmarr", "forge",
                   (RefUpdate("refs/heads/main", first, second),
                    RefUpdate("refs/heads/dev", ZERO, first)))
        feed = self.feed.push_feed(self.owner)
        self.assertEqual(feed.total, 1)
        entry = feed.entries[0]
        self.assertEqual(len(entry.summaries), 2)
        by_name = {s.name: s for s in entry.summaries}
        self.assertEqual(by_name["main"].commit_count, 1)
        self.assertEqual(by_name["dev"].kind, "created")

    def test_deleted_ref_summary_lands_no_commits(self):
        first, second = self._two_commits()
        self._push("volmarr", "forge",
                   (RefUpdate("refs/heads/old", second, ZERO),))
        summary = self.feed.push_feed(self.owner).entries[0].summaries[0]
        self.assertEqual(summary.kind, "deleted")
        self.assertEqual(summary.commit_count, 0)
        self.assertEqual(summary.subjects, ())
        self.assertIn("deleted", summary.words)

    def test_unreadable_range_degrades_honestly(self):
        self._push("volmarr", "forge",
                   (RefUpdate("refs/heads/main", "a" * 40, "b" * 40),))
        feed = self.feed.push_feed(self.owner)
        self.assertEqual(feed.total, 1)
        summary = feed.entries[0].summaries[0]
        self.assertFalse(summary.available)
        self.assertIsNone(summary.commit_count)
        self.assertEqual(summary.subjects, ())
        self.assertIn("could not be read", summary.words)

    def test_subject_cap_counts_the_remainder(self):
        parent = None
        oids = []
        for i in range(SUBJECT_LIMIT + 2):
            parent = seed_commit(
                self.repos, "volmarr", "forge",
                text=f"c{i}\n".encode(), parent=parent,
                message=f"commit {i}\n".encode())
            oids.append(parent)
        self._push("volmarr", "forge",
                   (RefUpdate("refs/heads/main", ZERO, oids[-1]),))
        summary = self.feed.push_feed(self.owner).entries[0].summaries[0]
        self.assertEqual(summary.commit_count, SUBJECT_LIMIT + 2)
        self.assertEqual(len(summary.subjects), SUBJECT_LIMIT)
        self.assertEqual(summary.more_count, 2)
        self.assertIn("and 2 more", summary.words)

    def test_limit_caps_entries_but_total_is_whole(self):
        first, second = self._two_commits()
        self._push("volmarr", "forge",
                   (RefUpdate("refs/heads/main", ZERO, first),))
        self._push("volmarr", "forge",
                   (RefUpdate("refs/heads/main", first, second),))
        feed = self.feed.push_feed(self.owner, limit=1)
        self.assertEqual(feed.count, 1)
        self.assertEqual(feed.total, 2)
        self.assertEqual(self.feed.push_count(self.owner), 2)
        self.assertIn("Showing the 1 most recent", feed.words)

    # -- pure helpers --------------------------------------------
    def test_pure_ref_helpers(self):
        self.assertEqual(short_ref("refs/heads/main"), "main")
        self.assertEqual(short_ref("refs/tags/v1.0"), "v1.0")
        self.assertEqual(short_ref("refs/notes/x"), "refs/notes/x")
        self.assertIsNone(range_revspec(RefUpdate("refs/heads/a", "a" * 40, ZERO)))
        self.assertEqual(
            range_revspec(RefUpdate("refs/heads/a", ZERO, "b" * 40)), "b" * 40)
        self.assertEqual(
            range_revspec(RefUpdate("refs/heads/a", "a" * 40, "b" * 40)),
            "a" * 40 + ".." + "b" * 40)

    def test_summarise_update_direct(self):
        first, second = self._two_commits()
        path = self.repos.path_for("volmarr", "forge")
        summary = summarise_update(
            path, RefUpdate("refs/heads/main", first, second))
        self.assertEqual(summary.commit_count, 1)
        self.assertEqual(summary.subjects, ("second commit",))

    # -- renders ---------------------------------------------------
    def test_render_escapes_commit_subjects(self):
        evil = seed_commit(self.repos, "volmarr", "forge",
                           text=b"x\n", message=b"<script>x</script>\n")
        self._push("volmarr", "forge",
                   (RefUpdate("refs/heads/main", ZERO, evil),))
        page = render_push_feed_page(self.feed.push_feed(self.owner))
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("&lt;script&gt;", page)
        entry_html = render_push_feed_entry(
            self.feed.push_feed(self.owner).entries[0])
        self.assertIn("volmarr/forge", entry_html)


if __name__ == "__main__":
    unittest.main()
