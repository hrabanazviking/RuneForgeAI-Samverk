"""S-108 acceptance battery: repo-relative links.

Acceptance (roadmap S-108): relative links and images in repo
Markdown resolve against the current ref, as users expect.

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
from samverk.repo_home import RepoHomeService
from samverk.repo_links import make_link_resolver, resolve_repo_link
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

OID = "a" * 40
CTX = dict(owner="volmarr", name="samverk", ref=OID)


class RepoLinkTests(unittest.TestCase):
    def test_relative_links_resolve_from_the_files_directory(self):
        self.assertEqual(
            resolve_repo_link("docs/guide.md", "link", **CTX),
            f"/volmarr/samverk/blob/{OID}/docs/guide.md")
        self.assertEqual(
            resolve_repo_link("../other.md", "link", base_dir="docs/deep",
                              **CTX),
            f"/volmarr/samverk/blob/{OID}/docs/other.md")
        self.assertEqual(
            resolve_repo_link("./same.md", "link", base_dir="docs", **CTX),
            f"/volmarr/samverk/blob/{OID}/docs/same.md")
        self.assertEqual(
            resolve_repo_link("sub/page.md#install", "link",
                              base_dir="docs", **CTX),
            f"/volmarr/samverk/blob/{OID}/docs/sub/page.md#install")

    def test_images_go_to_the_raw_view(self):
        self.assertEqual(
            resolve_repo_link("img/my flow.png", "image", **CTX),
            f"/volmarr/samverk/raw/{OID}/img/my%20flow.png")

    def test_absolute_anchor_and_root_links_pass_through(self):
        for url in ("https://example.com/x", "mailto:a@example.com",
                    "#local-anchor", "/instance/path", "?q=1"):
            self.assertEqual(resolve_repo_link(url, "link", **CTX), url)

    def test_unsafe_and_escaping_links_are_refused(self):
        for url in ("javascript:alert(1)", "data:text/html,x",
                    "//evil.example/x", "&#106;avascript:alert(1)"):
            self.assertIsNone(resolve_repo_link(url, "link", **CTX), url)
        self.assertIsNone(
            resolve_repo_link("../../outside.md", "link",
                              base_dir="docs", **CTX))
        self.assertIsNone(resolve_repo_link("..", "link", **CTX))
        # Refused links degrade to visible text in the pipeline.
        html = render_markdown(
            "[out](../../outside.md)",
            link_resolver=make_link_resolver(base_dir="docs", **CTX))
        self.assertEqual(html, "<p>out</p>")

    def test_home_readme_links_resolve_against_the_pinned_commit(self):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        root = Path(td.name)
        conn = db.init_db(root / "samverk.db"); self.addCleanup(conn.close)
        accounts = AccountStore(conn)
        owner = accounts.register("volmarr", "correct horse battery")
        repos = RepositoryStore(conn, root, accounts)
        repos.create_repository(owner.id, "volmarr", "samverk",
                                visibility="private")
        bare = repos.path_for("volmarr", "samverk")
        work = root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "README.md").write_text(
            "# Home\n\nSee the [guide](docs/guide.md) and "
            "![logo](logo.png).\n", encoding="utf-8")
        (work / "docs").mkdir()
        (work / "docs" / "guide.md").write_text("g\n", encoding="utf-8")
        (work / "logo.png").write_bytes(b"\x89PNG")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "seed")
        run_git(work, "push", str(bare), "main")
        commit = run_git(work, "rev-parse", "main")
        home = RepoHomeService(repos).home_for(owner, "volmarr", "samverk")
        self.assertIn(
            f'href="/volmarr/samverk/blob/{commit}/docs/guide.md"',
            home.readme.html)
        self.assertIn(
            f'src="/volmarr/samverk/raw/{commit}/logo.png"',
            home.readme.html)


if __name__ == "__main__":
    unittest.main()
