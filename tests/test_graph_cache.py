"""S-072 acceptance battery: commit graph caches.

Acceptance (roadmap S-072): derived data (counts, contributor
lists) computed off-path and cached with invalidation on push.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.graph_cache import GraphCache
from samverk.repositories import RepositoryStore

def git(repo: Path, *args: str, author="A U Thor <a@e.c>", input_bytes=None) -> str:
    env = dict(os.environ)
    name, _, email = author.partition(" <")
    env.update({"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email.rstrip(">"),
                "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email.rstrip(">")})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

def commit(repo: Path, parent: str | None, text: bytes, author="A U Thor <a@e.c>") -> str:
    blob = git(repo, "hash-object", "-w", "--stdin", input_bytes=text)
    tree = git(repo, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
    args = ["commit-tree", tree] + (["-p", parent] if parent else [])
    c = git(repo, *args, author=author, input_bytes=b"msg\n")
    git(repo, "update-ref", "refs/heads/main", c)
    return c

class GraphCacheTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name) / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.cache = GraphCache(self.conn, self.data_root, self.repos)
        self.repos.create_repository(self.owner.id, "volmarr", "alpha")
        self.path = self.repos.path_for("volmarr", "alpha")

    def test_refresh_computes_counts_and_contributors(self):
        c1 = commit(self.path, None, b"one\n")
        c2 = commit(self.path, c1, b"two\n", author="Second <s@e.c>")
        commit(self.path, c2, b"three\n")
        git(self.path, "update-ref", "refs/tags/v1", c2)
        stats = self.cache.refresh("volmarr", "alpha")
        self.assertEqual(stats.commit_count, 3)
        self.assertEqual(stats.contributors,
                         ("A U Thor <a@e.c>", "Second <s@e.c>"))
        self.assertEqual(stats.branch_count, 1)
        self.assertEqual(stats.tag_count, 1)
        cached = self.cache.cached_stats("volmarr", "alpha")
        self.assertEqual(cached, stats)

    def test_no_cache_until_refresh_and_empty_repo_is_zero(self):
        self.assertIsNone(self.cache.cached_stats("volmarr", "alpha"))
        stats = self.cache.refresh("volmarr", "alpha")
        self.assertEqual(stats.commit_count, 0)
        self.assertEqual(stats.contributors, ())
        self.assertEqual(self.cache.cached_stats("volmarr", "alpha"), stats)

    def test_a_push_makes_the_cache_stale_by_fingerprint(self):
        c1 = commit(self.path, None, b"one\n")
        self.cache.refresh("volmarr", "alpha")
        self.assertIsNotNone(self.cache.cached_stats("volmarr", "alpha"))
        commit(self.path, c1, b"two\n")   # the push: a ref moved
        self.assertIsNone(self.cache.cached_stats("volmarr", "alpha"))
        self.assertTrue(self.cache.is_stale("volmarr", "alpha"))
        refreshed = self.cache.refresh("volmarr", "alpha")
        self.assertEqual(refreshed.commit_count, 2)

    def test_invalidate_drops_the_row_at_once(self):
        commit(self.path, None, b"one\n")
        self.cache.refresh("volmarr", "alpha")
        self.cache.invalidate("volmarr", "alpha")
        self.assertIsNone(self.cache.cached_stats("volmarr", "alpha"))
        row = self.conn.execute(
            "SELECT COUNT(*) c FROM repo_graph_cache").fetchone()
        self.assertEqual(row["c"], 0)

    def test_branches_and_tags_are_counted_separately(self):
        c1 = commit(self.path, None, b"one\n")
        git(self.path, "update-ref", "refs/heads/dev", c1)
        git(self.path, "update-ref", "refs/tags/v1", c1)
        git(self.path, "update-ref", "refs/tags/v2", c1)
        stats = self.cache.refresh("volmarr", "alpha")
        self.assertEqual((stats.branch_count, stats.tag_count), (2, 2))
        # The same commit reachable from many refs counts once.
        self.assertEqual(stats.commit_count, 1)

if __name__ == "__main__":
    unittest.main()
