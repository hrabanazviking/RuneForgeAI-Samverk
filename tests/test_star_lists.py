"""S-233 acceptance battery: star lists.

Acceptance (roadmap S-233): a user's stars
browsable as a reading list; stars are public
signals and are labelled as such. The list is a
read model over S-222's repo_stars rows: no new
storage, no new audit event, and S-209's privacy
rule -- an entry shows exactly when the viewer
may read the repository.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.repositories import RepositoryStore
from samverk.star_lists import (
    STAR_LIST_SCOPE, STAR_SIGNAL_LABEL, STAR_SIGNAL_WORDS,
    StarListError, StarListStore, render_profile_stars_section,
    render_star_list_entry, render_star_list_page,
    star_list_empty_words)
from samverk.watch_star import WatchStarStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now
    def tick(self, step=10):
        self.now += step


class StarListTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.subject = self.accounts.register("yrsa", "correct horse battery")
        self.other = self.accounts.register("tess", "correct horse battery")
        self.stranger = self.accounts.register("mallory", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts, audit=self.audit)
        self.ws = WatchStarStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)
        self.lists = StarListStore(self.conn, self.repos, self.accounts, self.ws)
        self.repos.create_repository(self.owner.id, "volmarr", "vpub",
                                     description="The owner's public forge",
                                     visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "vpriv",
                                     visibility="private")
        self.repos.create_repository(self.subject.id, "yrsa", "ypub",
                                     description="The subject's reader",
                                     visibility="public")
        self.repos.create_repository(self.subject.id, "yrsa", "ypriv",
                                     visibility="private")

    def _star_three(self):
        # oldest -> newest: vpub, ypub, ypriv
        self.ws.star(self.subject, "volmarr", "vpub")
        self.clock.tick()
        self.ws.star(self.subject, "yrsa", "ypub")
        self.clock.tick()
        self.ws.star(self.subject, "yrsa", "ypriv")

    def _audit_count(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    # -- pins -------------------------------------------------
    def test_pins_schema_99_taxonomy_133_no_new_storage(self):
        self.assertEqual(schema_version(self.conn), 115)
        self.assertEqual(db.MIGRATIONS[-1][0], 115)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        for verb in ("repo.star", "repo.unstar"):
            self.assertIn(verb, taxonomy.AUDIT_EVENTS)

    # -- empty ------------------------------------------------
    def test_empty_list_for_user_with_no_stars(self):
        lst = self.lists.star_list(self.stranger, "yrsa")
        self.assertEqual(lst.subject, "yrsa")
        self.assertEqual(lst.entries, ())
        self.assertEqual(lst.total, 0)
        self.assertEqual(lst.count, 0)
        self.assertEqual(self.lists.starred_count(self.stranger, "yrsa"), 0)

    def test_empty_state_teaches_and_labels_public_signal(self):
        words = star_list_empty_words("yrsa")
        self.assertIn("has not starred", words)
        self.assertIn("bookmark", words)
        self.assertIn(STAR_SIGNAL_WORDS, words)
        page = render_star_list_page(self.lists.star_list(None, "yrsa"))
        self.assertIn("Stars — yrsa", page)
        self.assertIn("public signal", page)
        self.assertIn("has not starred", page)

    # -- the list ---------------------------------------------
    def test_order_most_recent_first_and_entry_fields(self):
        self._star_three()
        lst = self.lists.star_list(self.subject, "yrsa")
        self.assertEqual([e.full_name for e in lst.entries],
                         ["yrsa/ypriv", "yrsa/ypub", "volmarr/vpub"])
        self.assertEqual(lst.total, 3)
        self.assertEqual(lst.count, 3)
        newest = lst.entries[0]
        self.assertEqual(newest.visibility, "private")
        self.assertEqual(newest.starred_at, 1_700_000_020)
        mid = lst.entries[1]
        self.assertEqual(mid.description, "The subject's reader")
        self.assertEqual(mid.visibility, "public")
        self.assertEqual(mid.star_count, 1)
        self.assertEqual(lst.entries[2].description, "The owner's public forge")

    def test_entry_star_counts_are_live(self):
        self._star_three()
        self.ws.star(self.other, "volmarr", "vpub")
        self.ws.star(self.stranger, "volmarr", "vpub")
        lst = self.lists.star_list(self.subject, "yrsa")
        by_name = {e.full_name: e for e in lst.entries}
        self.assertEqual(by_name["volmarr/vpub"].star_count, 3)
        self.assertEqual(by_name["yrsa/ypub"].star_count, 1)

    def test_public_signal_labelled_on_page_and_every_entry(self):
        self._star_three()
        lst = self.lists.star_list(self.subject, "yrsa")
        self.assertEqual(STAR_SIGNAL_LABEL, "public signal")
        for entry in lst.entries:
            self.assertEqual(entry.signal_label, "public signal")
            self.assertIn("public signal", entry.words)
            self.assertIn("public signal", render_star_list_entry(entry))
        page = render_star_list_page(lst)
        self.assertIn(STAR_SIGNAL_WORDS, page)
        self.assertIn("Most recently starred first", page)
        self.assertEqual(lst.scope, STAR_LIST_SCOPE)

    def test_starred_words_format(self):
        self._star_three()
        lst = self.lists.star_list(self.subject, "yrsa")
        expect = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(1_700_000_020))
        self.assertEqual(lst.entries[0].starred_words, expect)
        self.assertIn(expect, lst.entries[0].words)

    def test_words_singular_and_plural(self):
        self.ws.star(self.subject, "volmarr", "vpub")
        lst = self.lists.star_list(self.subject, "yrsa")
        self.assertIn("has starred 1 repository.", lst.words)
        self.clock.tick()
        self.ws.star(self.subject, "yrsa", "ypub")
        lst = self.lists.star_list(self.subject, "yrsa")
        self.assertIn("has starred 2 repositories.", lst.words)

    # -- privacy (S-209's rule) --------------------------------
    def test_private_star_invisible_to_stranger_no_leak(self):
        self._star_three()
        lst = self.lists.star_list(self.stranger, "yrsa")
        self.assertEqual([e.full_name for e in lst.entries],
                         ["yrsa/ypub", "volmarr/vpub"])
        self.assertEqual(lst.total, 2)
        self.assertEqual(self.lists.starred_count(self.stranger, "yrsa"), 2)
        page = render_star_list_page(lst)
        self.assertNotIn("ypriv", page)
        self.assertNotIn("has starred 3", page)

    def test_anonymous_sees_public_entries_only(self):
        self._star_three()
        lst = self.lists.star_list(None, "yrsa")
        self.assertEqual([e.full_name for e in lst.entries],
                         ["yrsa/ypub", "volmarr/vpub"])
        self.assertEqual(lst.total, 2)

    def test_owner_of_private_repo_sees_the_entry_labelled_private(self):
        # the subject's own private repo is readable by the
        # subject, and its entry is honestly labelled private
        self._star_three()
        lst = self.lists.star_list(self.subject, "yrsa")
        priv = [e for e in lst.entries if e.full_name == "yrsa/ypriv"]
        self.assertEqual(len(priv), 1)
        self.assertIn("private repository", priv[0].words)

    def test_consistent_with_s222_name_list(self):
        self._star_three()
        for viewer in (self.subject, self.stranger, None):
            with self.subTest(viewer=viewer):
                mine = {e.full_name for e in
                        self.lists.star_list(viewer, "yrsa").entries}
                theirs = set(self.ws.list_starred_repos(viewer, "yrsa"))
                self.assertEqual(mine, theirs)

    # -- change over time ---------------------------------------
    def test_unstar_removes_and_restar_stands_at_front(self):
        self._star_three()
        self.ws.unstar(self.subject, "yrsa", "ypub")
        lst = self.lists.star_list(self.subject, "yrsa")
        self.assertEqual([e.full_name for e in lst.entries],
                         ["yrsa/ypriv", "volmarr/vpub"])
        self.clock.tick(100)
        self.ws.star(self.subject, "yrsa", "ypub")
        lst = self.lists.star_list(self.subject, "yrsa")
        self.assertEqual(lst.entries[0].full_name, "yrsa/ypub")
        self.assertEqual(lst.entries[0].starred_at, 1_700_000_120)
        self.assertEqual(lst.total, 3)

    def test_reading_the_list_witnesses_nothing(self):
        self._star_three()
        before = self._audit_count()
        self.lists.star_list(self.subject, "yrsa")
        self.lists.star_list(None, "yrsa")
        self.lists.starred_count(self.stranger, "yrsa")
        render_star_list_page(self.lists.star_list(self.subject, "yrsa"))
        self.assertEqual(self._audit_count(), before)

    # -- browsing ------------------------------------------------
    def test_limit_caps_entries_but_total_stays_visible_total(self):
        self._star_three()
        lst = self.lists.star_list(self.subject, "yrsa", limit=2)
        self.assertEqual(lst.count, 2)
        self.assertEqual(lst.total, 3)
        self.assertEqual([e.full_name for e in lst.entries],
                         ["yrsa/ypriv", "yrsa/ypub"])
        self.assertIn("Showing the 2 most recent.", lst.words)
        lst = self.lists.star_list(self.subject, "yrsa", limit=0)
        self.assertEqual(lst.count, 1)
        lst = self.lists.star_list(self.subject, "yrsa", limit=9999)
        self.assertEqual(lst.count, 3)

    # -- subject resolution ---------------------------------------
    def test_subject_forms_agree(self):
        self._star_three()
        by_name = self.lists.star_list(self.stranger, "yrsa")
        by_user = self.lists.star_list(self.stranger, self.subject)
        by_id = self.lists.star_list(self.stranger, self.subject.id)
        self.assertEqual(by_name.entries, by_user.entries)
        self.assertEqual(by_name.entries, by_id.entries)

    def test_unknown_subject_refused_on_every_face(self):
        for bad in ("ghost", 999999, None, True, 1.5):
            with self.subTest(bad=bad):
                with self.assertRaises(StarListError) as cm:
                    self.lists.star_list(self.stranger, bad)
                self.assertEqual(cm.exception.reason, "no_such_user")
                with self.assertRaises(StarListError) as cm:
                    self.lists.starred_count(self.stranger, bad)
                self.assertEqual(cm.exception.reason, "no_such_user")

    # -- renders ---------------------------------------------------
    def test_profile_section_render(self):
        self._star_three()
        html = render_profile_stars_section(
            self.lists.star_list(self.subject, "yrsa"))
        self.assertIn('<section class="profile-stars">', html)
        self.assertIn("Stars — yrsa", html)
        self.assertIn("volmarr/vpub", html)
        self.assertIn("public signal", html)

    def test_render_escapes_description_and_names(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "evil",
            description='<script>alert("x")</script> & <b>bold</b>',
            visibility="public")
        self.ws.star(self.subject, "volmarr", "evil")
        page = render_star_list_page(self.lists.star_list(self.subject, "yrsa"))
        self.assertNotIn("<script>", page)
        self.assertNotIn("<b>bold</b>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&amp;", page)


if __name__ == "__main__":
    unittest.main()
