"""S-119 acceptance battery: repository header summary.

Acceptance (roadmap S-119): visibility badge, fork
parent, mirror badge, watch/star/fork counts with real
actions (Part XI wires the actions).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.forks import ForkStore
from samverk.mirrors import MirrorService
from samverk.repo_header import (HeaderError, RepoHeaderService,
                                 render_repo_header)
from samverk.repositories import RepositoryStore

class RepoHeaderTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.forks = ForkStore(self.conn, self.root, self.accounts, self.repos)
        self.mirrors = MirrorService(self.conn, self.root, self.accounts, self.repos)
        self.headers = RepoHeaderService(self.conn, self.repos, self.mirrors)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public",
            description="A public thing")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")

    def test_visibility_badge_is_words_with_meaning(self):
        pub = self.headers.header(None, "volmarr", "pub")
        self.assertEqual(pub.visibility_word, "Public")
        self.assertIn("anyone can read", pub.visibility_note)
        self.assertFalse(pub.is_fork); self.assertFalse(pub.is_mirror)
        self.assertEqual(pub.fork_count, 0)
        html = render_repo_header(pub)
        self.assertIn("Public — anyone can read this repository", html)
        self.assertIn("A public thing", html)
        self.assertNotIn("badge-fork", html); self.assertNotIn("badge-mirror", html)
        priv = self.headers.header(self.owner, "volmarr", "priv")
        self.assertEqual(priv.visibility_word, "Private")
        self.assertIn("Private — only people with access",
                      render_repo_header(priv))

    def test_watch_and_star_are_named_missing_never_zero(self):
        header = self.headers.header(None, "volmarr", "pub")
        self.assertIsNone(header.watch_count); self.assertIsNone(header.star_count)
        html = render_repo_header(header)
        self.assertIn("Watchers: not available yet", html)
        self.assertIn("Stars: not available yet", html)
        self.assertIn("Part XI", html)
        self.assertNotIn("Watchers: 0", html); self.assertNotIn("Stars: 0", html)
        self.assertIn("Forks: 0", html)  # forks are real: zero is a fact

    def test_fork_parent_named_and_fork_count_real(self):
        self.forks.fork(self.other.id, "volmarr", "pub")
        self.forks.fork(self.owner.id, "volmarr", "pub", "pub2")
        upstream = self.headers.header(None, "volmarr", "pub")
        self.assertEqual(upstream.fork_count, 2)
        fork = self.headers.header(None, "yrsa", "pub")
        self.assertTrue(fork.is_fork)
        self.assertEqual(fork.fork_parent, "volmarr/pub")
        self.assertFalse(fork.fork_parent_missing)
        html = render_repo_header(fork)
        self.assertIn('Fork of <a href="/volmarr/pub">volmarr/pub</a>', html)

    def test_dangling_fork_parent_is_named_not_linked(self):
        fork = self.forks.fork(self.other.id, "volmarr", "pub")
        with self.conn:
            self.conn.execute(
                "UPDATE repositories SET fork_of_id = 99999 WHERE id = ?",
                (fork.id,))
        header = self.headers.header(None, "yrsa", "pub")
        self.assertTrue(header.is_fork); self.assertTrue(header.fork_parent_missing)
        self.assertIsNone(header.fork_parent)
        html = render_repo_header(header)
        self.assertIn("no longer exists", html)
        self.assertNotIn('href="/volmarr/pub"', html)

    def test_mirror_badge_words_without_source_path(self):
        source_path = self.repos.path_for("volmarr", "pub")
        self.repos.create_repository(self.owner.id, "volmarr", "mir")
        self.mirrors.attach_mirror(
            self.owner.id, "volmarr", "mir", source_path)
        header = self.headers.header(self.owner, "volmarr", "mir")
        self.assertTrue(header.is_mirror)
        self.assertIn("another repository on this instance",
                      header.mirror_kind_word)
        self.assertEqual(header.mirror_sync_word, "never synced")
        html = render_repo_header(header)
        self.assertIn("Mirror — mirrored from another repository", html)
        self.assertNotIn(str(source_path), html)
        self.assertNotIn(str(self.root), html)

    def test_counter_seam_makes_watch_and_star_real(self):
        wired = RepoHeaderService(
            self.conn, self.repos, self.mirrors,
            watch_counter=lambda repo: 3, star_counter=lambda repo: 5)
        header = wired.header(None, "volmarr", "pub")
        self.assertEqual(header.watch_count, 3); self.assertEqual(header.star_count, 5)
        html = render_repo_header(header)
        self.assertIn("Watchers: 3", html); self.assertIn("Stars: 5", html)
        broken = RepoHeaderService(
            self.conn, self.repos, watch_counter=lambda repo: -1)
        with self.assertRaises(HeaderError) as caught:
            broken.header(None, "volmarr", "pub")
        self.assertEqual(caught.exception.reason, "count_invalid")

    def test_permission_law_and_escaping(self):
        for viewer, name in ((self.other, "priv"), (None, "priv"),
                             (self.owner, "missing")):
            with self.assertRaises(HeaderError) as caught:
                self.headers.header(viewer, "volmarr", name)
            self.assertEqual(caught.exception.reason, "repo_not_found")
        self.repos.update_metadata(
            self.owner.id, "volmarr", "pub",
            description='"><script>alert(1)</script>')
        html = render_repo_header(self.headers.header(None, "volmarr", "pub"))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

if __name__ == "__main__":
    unittest.main()
