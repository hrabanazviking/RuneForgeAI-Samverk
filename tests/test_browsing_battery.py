"""S-120 — PART V GATE battery: browsing over the reference repos.

The assembled Part V web experience, walked end to end
over four reference repositories chosen to stress
different surfaces:

- **small** — a README, one source file, two commits;
  the full walk: home, tree, blob, blame, commits,
  commit detail, compare, contributors, finder, header,
  search box, deep links.
- **large** — sixty files in nested directories and a
  longer history; pagination and the finder stay
  honest (true totals, caps named).
- **LFS** — a file that is only an LFS pointer: every
  surface reports the pointer as a pointer and never
  serves the pointer text as the file.
- **wiki-less** — a code-only repository with no
  README and no wiki (Samverk has no wiki surface in
  Part V): no built page links to or invents a wiki.

Plus the gate's cross-cutting strikes: a private
repository answers every Part V surface with the same
uniform `repo_not_found` for strangers, and the
rendered pages carry no inline styles — text scaling
is the reader's browser at work, and nothing in these
pages fights it with fixed inline styling. The
browser-rendered 100%/200% scaling proof itself is a
Part XX cell (S-384) and is NOT PROVEN by this
battery; the gate records it as an open finding, in
the shape of the Part I and Part II gates before it.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.blame_view import BlameViewer
from samverk.blob_view import BlobViewer, render_blob_page
from samverk.commit_detail import CommitDetailService
from samverk.commit_list import CommitLister, render_commit_list_page
from samverk.compare_view import CompareService
from samverk.deep_links import blob_url, parse_deep_link
from samverk.file_browser import FileBrowser
from samverk.file_finder import FileFinder
from samverk.graph_cache import GraphCache
from samverk.mirrors import MirrorService
from samverk.raw_download import RawDownloadService, render_pointer_page
from samverk.repo_chrome import chrome_for_names, render_repo_chrome
from samverk.repo_header import RepoHeaderService, render_repo_header
from samverk.repo_home import RepoHomeService, render_repo_home_page
from samverk.repo_search import search_box_for
from samverk.repo_stats import RepoStatsService
from samverk.repositories import RepositoryStore
from test_blame_view import run_as
from test_repo_home import run_git

LFS_POINTER = (
    "version https://git-lfs.github.com/spec/v1\n"
    "oid sha256:" + "ab" * 32 + "\n"
    "size 12345\n")


class BrowsingBatteryTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.home = RepoHomeService(self.repos)
        self.browser = FileBrowser(self.repos)
        self.blobs = BlobViewer(self.repos)
        self.blame = BlameViewer(self.repos)
        self.commits = CommitLister(self.repos)
        self.detail = CommitDetailService(self.repos)
        self.compare = CompareService(self.repos)
        self.finder = FileFinder(self.repos)
        self.raw = RawDownloadService(self.repos)
        self.stats = RepoStatsService(
            self.repos, GraphCache(self.conn, self.root, self.repos))
        self.headers = RepoHeaderService(
            self.conn, self.repos,
            MirrorService(self.conn, self.root, self.accounts, self.repos))

    # -- reference-repo seeding --------------------------------
    def seed(self, name, files, *, visibility="public", extra_versions=0):
        self.repos.create_repository(
            self.owner.id, "volmarr", name, visibility=visibility)
        bare = self.repos.path_for("volmarr", name)
        work = self.root / f"work-{name}"; work.mkdir()
        run_git(work, "init", "-b", "main")
        for rel, text in files.items():
            target = work / rel; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        run_as(work, "Alice A", "alice@example.com",
               "2024-01-01T00:00:00Z", "add", ".")
        run_as(work, "Alice A", "alice@example.com",
               "2024-01-01T00:00:00Z", "commit", "-m", "first")
        for i in range(extra_versions):
            marker = work / "notes.txt"
            marker.write_text(f"version {i + 2}\n", encoding="utf-8")
            run_as(work, "Alice A", "alice@example.com",
                   f"2024-01-0{i + 2}T00:00:00Z", "add", ".")
            run_as(work, "Alice A", "alice@example.com",
                   f"2024-01-0{i + 2}T00:00:00Z", "commit", "-m",
                   f"version {i + 2}")
        run_git(work, "push", str(bare), "main")
        return work

    def seed_small(self):
        self.seed("small", {
            "README.md": "# Small\n\nA small reference repo.\n",
            "src/hello.py": "print('hello')\nprint('world')\n",
            "notes.txt": "version 1\n"}, extra_versions=1)

    # -- the gate walks ------------------------------------------
    def test_small_repo_full_browsing_walk(self):
        self.seed_small()
        home = self.home.home_for(None, "volmarr", "small")
        self.assertFalse(home.is_empty)
        self.assertIsNotNone(home.readme)
        self.assertIn("Small", render_repo_home_page(home))
        tree = self.browser.browse(None, "volmarr", "small", path="src")
        self.assertEqual([e.name for e in tree.entries], ["hello.py"])
        blob = self.blobs.view(None, "volmarr", "small", path="src/hello.py")
        self.assertEqual(len(blob.lines), 2)
        self.assertFalse(blob.is_lfs_pointer)
        blame = self.blame.blame(None, "volmarr", "small", path="src/hello.py")
        self.assertEqual(len(blame.lines), 2)
        listing = self.commits.list(None, "volmarr", "small")
        self.assertEqual(listing.total_commits, 2)
        newest = listing.commits[0]
        detail = self.detail.detail(None, "volmarr", "small", newest.oid)
        self.assertEqual(detail.oid, newest.oid)
        compared = self.compare.compare(
            None, "volmarr", "small", listing.commits[1].oid, newest.oid)
        self.assertEqual(compared.ahead, 1)
        summary = self.stats.summary(None, "volmarr", "small")
        self.assertEqual(summary.commit_count, 2)
        found = self.finder.find(None, "volmarr", "small", "hello")
        self.assertEqual(found.total_matches, 1)
        header = self.headers.header(None, "volmarr", "small")
        self.assertEqual(header.visibility_word, "Public")
        self.assertIn("repo:volmarr/small",
                      search_box_for(self.repos, None, "volmarr", "small"))
        url = blob_url("volmarr", "small", "main", "src/hello.py", line=2)
        parsed = parse_deep_link(url)
        self.assertEqual(parsed.path, "src/hello.py")
        self.assertEqual(parsed.line_start, 2)

    def test_large_repo_pagination_and_finder_totals(self):
        files = {"README.md": "# Large\n", "notes.txt": "version 1\n"}
        for i in range(60):
            files[f"pkg/mod{i:02d}/file{i:02d}.py"] = f"# module {i}\n"
        self.seed("large", files, extra_versions=4)
        listing = self.commits.list(None, "volmarr", "large",
                                    page=1, per_page=2)
        self.assertEqual(listing.total_commits, 5)
        self.assertTrue(listing.has_next)
        found = self.finder.find(None, "volmarr", "large", "file")
        self.assertEqual(found.total_matches, 60)
        blob = self.blobs.view(None, "volmarr", "large",
                               path="pkg/mod42/file42.py")
        self.assertIn("module 42", blob.lines[0].text)
        home = self.home.home_for(None, "volmarr", "large")
        self.assertIn("pkg", [e.name for e in home.entries])

    def test_lfs_repo_reports_the_pointer_everywhere(self):
        self.seed("lfsrepo", {
            "README.md": "# LFS\n", "model.bin": LFS_POINTER,
            "notes.txt": "version 1\n"})
        blob = self.blobs.view(None, "volmarr", "lfsrepo", path="model.bin")
        self.assertTrue(blob.is_lfs_pointer)
        self.assertEqual(blob.lfs_size, 12345)
        raw = self.raw.raw(None, "volmarr", "lfsrepo", path="model.bin")
        self.assertFalse(raw.download_available)
        self.assertIn("pointer", render_pointer_page(raw).lower())
        home = self.home.home_for(None, "volmarr", "lfsrepo")
        self.assertIn("model.bin", [e.name for e in home.entries])

    def test_wikiless_repo_invents_no_wiki(self):
        self.seed("plain", {"code.py": "x = 1\n", "notes.txt": "version 1\n"})
        home = self.home.home_for(None, "volmarr", "plain")
        self.assertIsNone(home.readme)  # no README: the honest empty state
        pages = [
            render_repo_home_page(home),
            render_repo_chrome(chrome_for_names(self.repos, None,
                                                "volmarr", "plain")),
            render_repo_header(self.headers.header(None, "volmarr", "plain")),
            render_commit_list_page(self.commits.list(None, "volmarr", "plain")),
            render_blob_page(self.blobs.view(None, "volmarr", "plain",
                                             path="code.py")),
        ]
        for page in pages:
            self.assertNotIn("wiki", page.lower())

    def test_private_repo_uniform_not_found_on_every_surface(self):
        self.seed("small", {"README.md": "# Secret\n", "notes.txt": "v1\n"},
                  visibility="private")
        attempts = [
            lambda v: self.home.home_for(v, "volmarr", "small"),
            lambda v: self.browser.browse(v, "volmarr", "small"),
            lambda v: self.blobs.view(v, "volmarr", "small", path="README.md"),
            lambda v: self.commits.list(v, "volmarr", "small"),
            lambda v: self.finder.find(v, "volmarr", "small", "read"),
            lambda v: self.raw.raw(v, "volmarr", "small", path="README.md"),
            lambda v: self.headers.header(v, "volmarr", "small"),
            lambda v: self.stats.summary(v, "volmarr", "small"),
        ]
        for viewer in (self.stranger, None):
            for attempt in attempts:
                with self.assertRaises(ValueError) as caught:
                    attempt(viewer)
                self.assertEqual(caught.exception.reason, "repo_not_found")
        # And the owner walks it fine — the shape is permission, not breakage.
        self.assertEqual(
            self.home.home_for(self.owner, "volmarr", "small").full_name,
            "volmarr/small")

    def test_rendered_pages_carry_no_inline_styles(self):
        # Text scaling belongs to the reader's browser; Part V
        # pages must not fight it with fixed inline styling.
        # (The browser-rendered scaling proof is S-384's cell,
        # named NOT PROVEN in the gate entry — not claimed here.)
        self.seed_small()
        pages = [
            render_repo_home_page(self.home.home_for(None, "volmarr", "small")),
            render_blob_page(self.blobs.view(None, "volmarr", "small",
                                             path="src/hello.py")),
            render_commit_list_page(self.commits.list(None, "volmarr", "small")),
            render_repo_header(self.headers.header(None, "volmarr", "small")),
        ]
        for page in pages:
            self.assertNotIn(' style="', page)
            self.assertNotIn("<style", page)

if __name__ == "__main__":
    unittest.main()
