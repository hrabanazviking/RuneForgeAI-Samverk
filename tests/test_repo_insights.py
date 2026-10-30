"""S-115 acceptance battery: repository insights-lite.

Acceptance (roadmap S-115): traffic-free honest stats —
clone counts are NOT tracked for anonymous reads; what
we show is what we truly know (honesty law).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.graph_cache import GraphCache
from samverk.push_events import PushEventStore, RefUpdate
from samverk.repo_insights import (NOT_TRACKED, InsightsError,
                                   RepoInsightsService, render_insights_page)
from samverk.repo_stats import RepoStatsService
from samverk.repositories import RepositoryStore
from samverk.transport_audit import TransportAuditor
from test_repo_home import run_git

ZERO = "0" * 40
ONE = "1" * 40

class RepoInsightsTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        stats = RepoStatsService(self.repos, GraphCache(self.conn, self.root, self.repos))
        self.pushes = PushEventStore(self.conn, self.repos)
        self.service = RepoInsightsService(self.conn, self.repos, stats, self.pushes)
        self.auditor = TransportAuditor(AuditLog(self.conn))
        for name in ("priv", "pub"):
            bare = self.repos.path_for("volmarr", name)
            work = self.root / ("work-" + name); work.mkdir()
            run_git(work, "init", "-b", "main")
            (work / "a.txt").write_text("1\n", encoding="utf-8")
            run_git(work, "add", "."); run_git(work, "commit", "-m", "one")
            run_git(work, "push", str(bare), "main")

    def _push_event(self, repo):
        return self.pushes.record_push(
            "volmarr", repo, actor_kind="user", actor_id=self.owner.id,
            transport="http",
            updates=[RefUpdate("refs/heads/main", ZERO, ONE)])

    def test_known_numbers_come_from_their_stores(self):
        self._push_event("priv"); self._push_event("priv")
        insights = self.service.insights(self.owner, "volmarr", "priv")
        self.assertEqual(insights.summary.commit_count, 1)
        self.assertEqual(insights.summary.branch_count, 1)
        self.assertEqual(len(insights.summary.contributors), 1)
        self.assertEqual(insights.push_count, 2)
        self.assertIsNotNone(insights.last_push_at)
        self.assertGreater(insights.size_bytes, 0)
        page = render_insights_page(insights)
        self.assertIn("Accepted pushes recorded: 2", page)
        self.assertIn("Size on disk:", page)

    def test_private_fetches_counted_public_reads_not_applicable(self):
        self.auditor.record_read(actor_kind="user", actor_id=self.owner.id,
                                 full_name="volmarr/priv", visibility="private",
                                 transport="http", service="upload-pack")
        self.auditor.record_read(actor_kind="anonymous", actor_id=None,
                                 full_name="volmarr/pub", visibility="public",
                                 transport="http", service="upload-pack")
        priv = self.service.insights(self.owner, "volmarr", "priv")
        self.assertEqual(priv.recorded_private_fetches, 1)
        pub = self.service.insights(self.owner, "volmarr", "pub")
        self.assertIsNone(pub.recorded_private_fetches)  # never dressed as 0
        page = render_insights_page(pub)
        self.assertIn("not applicable", page)
        self.assertIn("reads of public repositories are not recorded", page)

    def test_no_clone_count_exists_and_untracked_is_named(self):
        insights = self.service.insights(self.owner, "volmarr", "pub")
        self.assertFalse(hasattr(insights, "clone_count"))
        names = [name for name, _ in NOT_TRACKED]
        self.assertTrue(any("Clone counts" in n for n in names))
        page = render_insights_page(insights)
        self.assertIn("Not tracked", page)
        self.assertIn("never zero", page)
        self.assertNotIn("Clones:", page)

    def test_empty_repo_and_permission_law(self):
        self.repos.create_repository(self.owner.id, "volmarr", "fresh", visibility="private")
        insights = self.service.insights(self.owner, "volmarr", "fresh")
        self.assertEqual(insights.summary.commit_count, 0)
        self.assertEqual(insights.push_count, 0)
        self.assertIsNone(insights.last_push_at)
        self.assertIn("no pushes recorded yet", render_insights_page(insights))
        with self.assertRaises(InsightsError) as caught:
            self.service.insights(self.stranger, "volmarr", "priv")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(InsightsError):
            self.service.insights(None, "volmarr", "priv")
        anon_pub = self.service.insights(None, "volmarr", "pub")
        self.assertEqual(anon_pub.summary.commit_count, 1)

if __name__ == "__main__":
    unittest.main()
