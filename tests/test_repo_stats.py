"""S-106 acceptance battery: contributors and counts.

Acceptance (roadmap S-106): commits/branches/tags/
contributors summary from cached derivations.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.graph_cache import GraphCache
from samverk.repo_stats import RepoStatsError, RepoStatsService, render_summary_page
from samverk.repositories import RepositoryStore
from test_repo_home import run_git
from test_blame_view import run_as

class RepoStatsTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk", visibility="private")
        cache = GraphCache(self.conn, self.root, self.repos)
        self.service = RepoStatsService(self.repos, cache)
        bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "a.txt").write_text("1\n", encoding="utf-8")
        run_as(work, "Alice A", "alice@example.com", "2024-01-01T00:00:00Z", "add", ".")
        run_as(work, "Alice A", "alice@example.com", "2024-01-01T00:00:00Z",
               "commit", "-m", "one")
        (work / "a.txt").write_text("2\n", encoding="utf-8")
        run_as(work, "Alice A", "alice@example.com", "2024-01-02T00:00:00Z", "add", ".")
        run_as(work, "Alice A", "alice@example.com", "2024-01-02T00:00:00Z",
               "commit", "-m", "two")
        (work / "a.txt").write_text("3\n", encoding="utf-8")
        run_as(work, "Bob B", "bob@example.com", "2024-01-03T00:00:00Z", "add", ".")
        run_as(work, "Bob B", "bob@example.com", "2024-01-03T00:00:00Z",
               "commit", "-m", "three")
        run_git(work, "tag", "v1")
        run_git(work, "branch", "side")
        run_git(work, "push", str(bare), "main", "side", "v1")

    def test_summary_counts_from_derivations(self):
        summary = self.service.summary(self.owner, "volmarr", "samverk")
        self.assertEqual(summary.commit_count, 3)
        self.assertEqual(summary.branch_count, 2)
        self.assertEqual(summary.tag_count, 1)
        self.assertFalse(summary.from_cache)  # first read computes
        counts = {c.identity: c.commits for c in summary.contributors}
        self.assertEqual(counts, {"Alice A <alice@example.com>": 2,
                                  "Bob B <bob@example.com>": 1})
        self.assertEqual(summary.contributors[0].identity,
                         "Alice A <alice@example.com>")
        page = render_summary_page(summary)
        self.assertIn("3 commits", page); self.assertIn("Alice A", page)

    def test_second_read_is_served_from_cache(self):
        first = self.service.summary(self.owner, "volmarr", "samverk")
        second = self.service.summary(self.owner, "volmarr", "samverk")
        self.assertTrue(second.from_cache)
        self.assertEqual(second.computed_at, first.computed_at)
        self.assertEqual(second.commit_count, 3)

    def test_permission_law(self):
        with self.assertRaises(RepoStatsError) as caught:
            self.service.summary(self.stranger, "volmarr", "samverk")
        self.assertEqual(caught.exception.reason, "repo_not_found")

if __name__ == "__main__":
    unittest.main()
