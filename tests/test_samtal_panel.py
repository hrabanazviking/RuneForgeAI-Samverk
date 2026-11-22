"""S-368 battery — Samverk surface in Samtal."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.issues import IssueStore
from samverk.notification_reasons import NotificationStore
from samverk.pull_requests import PullRequestStore
from samverk.repositories import RepositoryStore
from samverk.samtal_panel import SamtalPanelError, SamtalPanelService, render_panel
from test_repo_home import run_git

ON = {"seam.samtal.enabled": True}
PW = "a long enough passphrase"

class SamtalPanelTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "s.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.owner = self.accounts.register("volmarr", PW)
        self.reader = self.accounts.register("yrsa", PW)
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        bare = self.repos.path_for("volmarr", "pub")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "a.txt").write_text("base\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "base commit")
        run_git(work, "checkout", "-b", "feature")
        (work / "a.txt").write_text("base\nfeature\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "feature work")
        run_git(work, "push", str(bare), "main", "feature")
        issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit)
        self.prs = PullRequestStore(self.conn, self.repos, self.accounts, issues, audit=self.audit)
        self.prs.create_pull_request(self.owner, "volmarr", "pub",
                                     base_branch="main", head_branch="feature",
                                     title="Add the feature")
        self.notes = NotificationStore(self.conn, self.accounts, time_fn=lambda: 5000)
        self.notes.notify(self.owner, self.reader, "mention",
                          target_kind="issue", target_id="volmarr/pub#1")
        self.svc = SamtalPanelService(self.conn, self.root, self.accounts,
                                      settings=ON, audit=self.audit, time_fn=lambda: 5000)
    def tearDown(self):
        self.conn.close(); self._td.cleanup()
    def _reason(self, fn, *a, **k):
        with self.assertRaises(SamtalPanelError) as ctx: fn(*a, **k)
        return ctx.exception.reason
    def test_panel_lists_viewers_repos(self):
        panel = self.svc.panel_for(self.owner)
        self.assertEqual([r.full_name for r in panel.repos], ["volmarr/pub"])
    def test_panel_lists_open_pull_requests_with_links(self):
        panel = self.svc.panel_for(self.owner)
        self.assertEqual(panel.open_pull_count, 1)
        pull = panel.open_pulls[0]
        self.assertEqual(pull.title, "Add the feature")
        self.assertEqual(pull.link_path, "/volmarr/pub/pulls/1")
    def test_panel_counts_unread_inbox(self):
        self.assertEqual(self.svc.panel_for(self.owner).inbox_unread, 1)
        self.assertEqual(self.svc.panel_for(self.reader).inbox_unread, 0)
    def test_payload_is_samverk_decided(self):
        payload = self.svc.payload_for(self.owner)
        self.assertEqual(payload["decided_by"], "samverk")
        self.assertEqual(payload["rendered_by"], "samtal")
        self.assertEqual(payload["inbox_unread"], 1)
        self.assertEqual(payload["open_pull_requests"][0]["title"], "Add the feature")
    def test_other_viewer_sees_only_their_own_panel(self):
        panel = self.svc.panel_for(self.reader)
        self.assertEqual(panel.repos, ())
        self.assertEqual(panel.open_pulls, ())
    def test_render_shows_repos_pulls_and_inbox(self):
        html = render_panel(self.svc.panel_for(self.owner))
        self.assertIn("volmarr/pub", html)
        self.assertIn("Add the feature", html)
        self.assertIn("Inbox: 1 unread", html)
    def test_seam_disabled_and_anonymous_refused(self):
        off = SamtalPanelService(self.conn, self.root, self.accounts,
                                 settings={}, audit=self.audit, time_fn=lambda: 5000)
        self.assertEqual(self._reason(off.panel_for, self.owner), "seam_disabled")
        self.assertEqual(self._reason(self.svc.panel_for, None), "actor_required")

if __name__ == "__main__":
    unittest.main()
