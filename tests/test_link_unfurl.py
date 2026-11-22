"""S-370 battery — code in conversation (link unfurl)."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.issues import IssueStore
from samverk.link_unfurl import LinkUnfurlError, LinkUnfurlService, parse_samverk_link, render_card
from samverk.pull_requests import PullRequestStore
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

ON = {"seam.samtal.enabled": True}
PW = "a long enough passphrase"

class LinkUnfurlTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "s.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.owner = self.accounts.register("volmarr", PW)
        self.reader = self.accounts.register("yrsa", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public", description="The public hall repo")
        self.repos.create_repository(self.owner.id, "volmarr", "secret", visibility="private", description="Hidden workings")
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
        issues.create_issue(self.owner, "volmarr", "pub", "The gate sticks")
        prs = PullRequestStore(self.conn, self.repos, self.accounts, issues, audit=self.audit)
        prs.create_pull_request(self.owner, "volmarr", "pub", base_branch="main", head_branch="feature", title="Add the feature")
        self.svc = LinkUnfurlService(self.conn, self.root, self.accounts, settings=ON, audit=self.audit, time_fn=lambda: 5000)
    def tearDown(self):
        self.conn.close(); self._td.cleanup()
    def _reason(self, fn, *a, **k):
        with self.assertRaises(LinkUnfurlError) as ctx: fn(*a, **k)
        return ctx.exception.reason
    def test_repo_link_unfurls_for_any_reader(self):
        card = self.svc.unfurl(self.reader, "/volmarr/pub")
        self.assertEqual(card.kind, "repo")
        self.assertEqual(card.title, "volmarr/pub")
        self.assertEqual(card.summary, "The public hall repo")
        self.assertEqual(card.decided_by, "samverk")
    def test_full_url_and_file_link_unfurl(self):
        card = self.svc.unfurl(self.reader, "https://samverk.example/volmarr/pub/blob/main/a.txt")
        self.assertEqual(card.kind, "file")
        self.assertEqual(card.title, "a.txt")
        self.assertEqual(card.link_path, "/volmarr/pub/blob/main/a.txt")
    def test_issue_and_pr_links_carry_real_titles(self):
        issue = self.svc.unfurl(self.reader, "/volmarr/pub/issues/1")
        self.assertEqual(issue.title, "The gate sticks")
        pr = self.svc.unfurl(self.reader, "/volmarr/pub/pulls/2")
        self.assertEqual(pr.title, "Add the feature")
    def test_private_repo_denied_to_stranger_without_leak(self):
        err = None
        try:
            self.svc.unfurl(self.stranger, "/volmarr/secret/issues/1")
        except LinkUnfurlError as e:
            err = e
        self.assertIsNotNone(err)
        self.assertEqual(err.reason, "permission_denied")
        self.assertNotIn("Hidden workings", str(err))
    def test_owner_still_unfurls_private_repo(self):
        card = self.svc.unfurl(self.owner, "/volmarr/secret")
        self.assertEqual(card.summary, "Hidden workings")
    def test_unknown_link_and_missing_targets(self):
        self.assertEqual(self._reason(parse_samverk_link, "not a link at all"), "link_unknown")
        self.assertEqual(self._reason(self.svc.unfurl, self.reader, "/volmarr/nope"), "not_found")
        self.assertEqual(self._reason(self.svc.unfurl, self.reader, "/volmarr/pub/issues/99"), "not_found")
    def test_seam_disabled_refuses(self):
        off = LinkUnfurlService(self.conn, self.root, self.accounts, settings={}, audit=self.audit, time_fn=lambda: 5000)
        self.assertEqual(self._reason(off.unfurl, self.reader, "/volmarr/pub"), "seam_disabled")
    def test_payload_and_renderer_draw_only_the_card(self):
        payload = self.svc.payload_for(self.reader, "/volmarr/pub")
        self.assertEqual(payload["decided_by"], "samverk")
        html = render_card(self.svc.unfurl(self.reader, "/volmarr/pub"))
        self.assertIn("volmarr/pub", html)
        self.assertIn('data-kind="repo"', html)

if __name__ == "__main__":
    unittest.main()
