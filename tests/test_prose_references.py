"""S-109 acceptance battery: mentions and references in prose.

Acceptance (roadmap S-109): @user, #issue, and commit-sha
autolinking everywhere Markdown renders — confirmed against
the stores, never guessed.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.markdown_pipeline import render_markdown
from samverk.prose_references import make_reference_resolver
from samverk.repo_home import RepoHomeService
from samverk.repositories import RepositoryStore
from test_repo_home import run_git


class ProseReferenceTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk",
                                      visibility="private")
        self.bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "a.txt").write_text("a\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "seed")
        run_git(work, "push", str(self.bare), "main")
        self.commit = run_git(work, "rev-parse", "main")
        self.resolver = make_reference_resolver(
            accounts=self.accounts, owner="volmarr", name="samverk",
            repo_path=self.bare)

    def test_mentions_link_only_registered_accounts(self):
        self.assertEqual(self.resolver("mention", "volmarr"), "/volmarr")
        self.assertEqual(self.resolver("mention", "VOLMARR"), "/volmarr")
        self.assertIsNone(self.resolver("mention", "nobody-here"))
        html = render_markdown("Thanks @volmarr and @nobody-here.",
                               reference_resolver=self.resolver)
        self.assertIn('<a href="/volmarr">@volmarr</a>', html)
        self.assertIn("and @nobody-here.", html)

    def test_commit_shas_link_only_real_commits(self):
        short = self.commit[:7]
        self.assertEqual(self.resolver("commit", short),
                         f"/volmarr/samverk/commit/{self.commit}")
        self.assertEqual(self.resolver("commit", self.commit),
                         f"/volmarr/samverk/commit/{self.commit}")
        self.assertIsNone(self.resolver("commit", "deadbeef"))
        self.assertIsNone(self.resolver("commit", "1234567"))
        html = render_markdown(f"Fixed in {short}, not deadbeef.",
                               reference_resolver=self.resolver)
        self.assertIn(
            f'<a href="/volmarr/samverk/commit/{self.commit}">{short}</a>',
            html)
        self.assertIn("not deadbeef.", html)

    def test_issues_stay_text_until_the_store_is_wired(self):
        # Part VI has not built the issue store: with no
        # issue_exists callable a #number is honestly plain.
        self.assertIsNone(self.resolver("issue", "42"))
        wired = make_reference_resolver(
            accounts=self.accounts, owner="volmarr", name="samverk",
            repo_path=self.bare, issue_exists=lambda n: n in (1, 2))
        self.assertEqual(wired("issue", "2"), "/volmarr/samverk/issues/2")
        self.assertIsNone(wired("issue", "42"))
        self.assertIsNone(wired("issue", "0"))
        html = render_markdown("See #2 and #42",
                               reference_resolver=wired)
        self.assertIn('<a href="/volmarr/samverk/issues/2">#2</a>', html)
        self.assertIn("and #42", html)

    def test_references_never_fire_in_code_or_addresses(self):
        html = render_markdown(
            f"Mail a@volmarr.example, code `@{self.commit[:7]}` and "
            f"`@volmarr`, plain {self.commit[:7]}.",
            reference_resolver=self.resolver)
        self.assertIn(f"<code>@{self.commit[:7]}</code>", html)
        self.assertIn("<code>@volmarr</code>", html)
        self.assertEqual(html.count("<a href="), 1)  # only the plain sha

    def test_home_readme_prose_references_resolve(self):
        work = self.root / "work2"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "README.md").write_text(
            f"# Home\n\nBy @volmarr, seed {self.commit[:8]}, "
            "thanks @ghost-user, see #9.\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "readme")
        self.repos.create_repository(self.owner.id, "volmarr", "prose",
                                      visibility="private")
        bare2 = self.repos.path_for("volmarr", "prose")
        run_git(work, "push", str(bare2), "main")
        home = RepoHomeService(self.repos).home_for(
            self.owner, "volmarr", "prose")
        # The prose repo has its own seed commit; the sha from
        # the other repo must NOT link inside this one.
        self.assertIn('<a href="/volmarr">@volmarr</a>', home.readme.html)
        self.assertIn("@ghost-user", home.readme.html)
        self.assertNotIn("/commit/", home.readme.html)
        self.assertIn("see #9.", home.readme.html)


if __name__ == "__main__":
    unittest.main()
