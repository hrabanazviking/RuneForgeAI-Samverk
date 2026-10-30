"""S-097 acceptance battery: repository home.

Acceptance (roadmap S-097): README rendered at the repo root,
branch/tag switcher, clone URLs for both transports with
copy buttons.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.repo_home import RepoHomeError, RepoHomeService, render_repo_home_page
from samverk.repositories import RepositoryStore

GIT_ENV = {"GIT_AUTHOR_NAME": "A U Thor", "GIT_AUTHOR_EMAIL": "a@example.com",
           "GIT_COMMITTER_NAME": "A U Thor", "GIT_COMMITTER_EMAIL": "a@example.com",
           "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}

def run_git(cwd: Path, *args: str) -> str:
    env = dict(os.environ); env.update(GIT_ENV)
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

class RepoHomeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk",
                                     visibility="private",
                                     description="Our <forge> & home")
        self.service = RepoHomeService(
            self.repos, http_base="https://forge.example/",
            ssh_host="forge.example")
        self._seed()

    def _seed(self):
        bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "README.md").write_text(
            "# Samverk\n\nA **bold** forge.\n\n- one\n- two\n\n"
            "```\n<script>alert(1)</script>\n```\n", encoding="utf-8")
        (work / "hello.txt").write_text("hello\n", encoding="utf-8")
        (work / "src").mkdir(); (work / "src" / "main.py").write_text("x=1\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "first")
        run_git(work, "tag", "v1")
        run_git(work, "checkout", "-b", "feature")
        (work / "feature.txt").write_text("f\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "feature work")
        run_git(work, "checkout", "main")
        run_git(work, "push", str(bare), "main", "feature", "v1")
        self.work = work

    def test_home_lists_root_readme_branches_tags_and_clones(self):
        home = self.service.home_for(self.owner, "volmarr", "samverk")
        self.assertFalse(home.is_empty)
        self.assertEqual(home.current_ref, "main")
        self.assertTrue(home.commit_oid)
        names = {e.name for e in home.entries}
        self.assertEqual(names, {"README.md", "hello.txt", "src"})
        self.assertIsNotNone(home.readme)
        self.assertEqual(home.readme.name, "README.md")
        self.assertIn("<h1>Samverk</h1>", home.readme.html)
        self.assertIn("<strong>bold</strong>", home.readme.html)
        self.assertIn("<li>one</li>", home.readme.html)
        self.assertEqual(set(home.branches), {"main", "feature"})
        self.assertEqual(home.tags, ("v1",))
        by = {c.transport: c.url for c in home.clone_options}
        self.assertEqual(by, {"https": "https://forge.example/volmarr/samverk.git",
                              "ssh": "ssh://git@forge.example/volmarr/samverk.git"})
        self.assertEqual(home.unavailable_transports, ())

    def test_readme_rendering_never_emits_stored_markup(self):
        home = self.service.home_for(self.owner, "volmarr", "samverk")
        self.assertNotIn("<script>", home.readme.html)
        self.assertIn("&lt;script&gt;", home.readme.html)
        page = render_repo_home_page(home)
        self.assertNotIn("<script>", page)
        self.assertIn("Our &lt;forge&gt; &amp; home", page)

    def test_switcher_refs_the_other_branch(self):
        home = self.service.home_for(self.owner, "volmarr", "samverk", ref="feature")
        self.assertEqual(home.current_ref, "feature")
        self.assertIn("feature.txt", {e.name for e in home.entries})
        tagged = self.service.home_for(self.owner, "volmarr", "samverk", ref="v1")
        self.assertNotIn("feature.txt", {e.name for e in tagged.entries})

    def test_page_has_switcher_and_copy_buttons(self):
        page = render_repo_home_page(self.service.home_for(self.owner, "volmarr", "samverk"))
        self.assertIn('data-copy-target="clone-url-0"', page)
        self.assertIn('data-copy-target="clone-url-1"', page)
        self.assertIn('value="https://forge.example/volmarr/samverk.git"', page)
        self.assertIn('value="ssh://git@forge.example/volmarr/samverk.git"', page)
        self.assertIn("/volmarr/samverk/tree/feature", page)
        self.assertIn("main (current)", page)
        self.assertIn("<h1>Samverk</h1>", page)

    def test_permission_shape_is_uniform_not_found(self):
        for viewer in (self.stranger, None):
            with self.assertRaises(RepoHomeError) as caught:
                self.service.home_for(viewer, "volmarr", "samverk")
            self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(RepoHomeError) as caught:
            self.service.home_for(self.owner, "volmarr", "missing")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        self.repos.create_repository(self.owner.id, "volmarr", "open",
                                      visibility="public")
        # public-but-empty is readable anonymously
        home = RepoHomeService(self.repos).home_for(None, "volmarr", "open")
        self.assertTrue(home.is_empty)

    def test_empty_repo_home_is_honest(self):
        self.repos.create_repository(self.owner.id, "volmarr", "fresh")
        home = self.service.home_for(self.owner, "volmarr", "fresh")
        self.assertTrue(home.is_empty); self.assertEqual(home.entries, ())
        self.assertIsNone(home.readme); self.assertIsNone(home.commit_oid)
        page = render_repo_home_page(home)
        self.assertIn("This repository is empty", page)
        with self.assertRaises(RepoHomeError) as caught:
            self.service.home_for(self.owner, "volmarr", "fresh", ref="main")
        self.assertEqual(caught.exception.reason, "ref_not_found")

    def test_ref_and_transport_honesty(self):
        with self.assertRaises(RepoHomeError) as caught:
            self.service.home_for(self.owner, "volmarr", "samverk", ref="nope")
        self.assertEqual(caught.exception.reason, "ref_not_found")
        with self.assertRaises(RepoHomeError) as caught:
            self.service.home_for(self.owner, "volmarr", "samverk", ref="-evil")
        self.assertEqual(caught.exception.reason, "ref_invalid")
        bare = RepoHomeService(self.repos)
        home = bare.home_for(self.owner, "volmarr", "samverk")
        self.assertEqual(home.clone_options, ())
        self.assertEqual(set(home.unavailable_transports), {"https", "ssh"})
        with self.assertRaises(RepoHomeError):
            RepoHomeService(self.repos, http_base="ftp://x.example")

if __name__ == "__main__":
    unittest.main()
