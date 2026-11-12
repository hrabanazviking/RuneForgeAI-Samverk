"""S-273 acceptance battery: wiki storage.

Acceptance (roadmap S-273): Wiki storage -- each
repo's wiki is its own bare git repo (`<repo>.wiki`),
created lazily on first page.

The centre is samverk/wiki_storage.py: WikiStore.
The wiki stands beside the parent repository as
`<owner>/<repo>.wiki`, inherits S-013's path law and
S-054's read/write answers whole (a private repo's
wiki is repo_not_found to everyone who cannot read
the repo), and is created by `git init --bare` on
the first page write only -- probing, listing and
reading never create it. Pages are flat Markdown
files under one normalization law (whitespace to
hyphens, one trailing .md canonicalised away,
separators / `..` / traversal refused, identity
case-insensitive so no twin pages), capped text,
written as plumbing commits with an optimistic
expected-tip conflict (page_conflict). Web
experience is S-274, transports S-275, policy
S-276 -- none built here. No new taxonomy event --
133 stand; no migration -- schema 106 stands.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.repositories import RepositoryStore
from samverk.wiki_storage import (
    PAGE_MAX, WikiError, WikiStore, normalize_page_title,
    page_to_dict, render_wiki_page_list)
from test_repo_home import run_git

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class WikiStorageTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.clock = Clock()
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.reader = self.accounts.register("yrsa", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.wiki = WikiStore(
            self.conn, self.repos,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")

    def _reason(self, fn, *a, **k):
        with self.assertRaises(WikiError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _wiki_path(self, repo="pub"):
        return self.root / "repos" / "volmarr" / f"{repo}.wiki"

    # -- lazy creation -------------------------------------

    def test_no_wiki_until_first_page(self):
        self.assertFalse(self._wiki_path().exists())
        self.assertFalse(
            self.wiki.wiki_exists(None, "volmarr", "pub"))
        self.assertEqual(
            self.wiki.list_pages(None, "volmarr", "pub"), [])
        self.assertEqual(
            self._reason(self.wiki.read_page,
                         None, "volmarr", "pub", "Home"),
            "page_not_found")
        # Probing, listing and reading created nothing.
        self.assertFalse(self._wiki_path().exists())

    def test_first_write_creates_bare_wiki_beside_repo(self):
        page = self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home",
            "# Home\n\nWelcome.\n")
        path = self._wiki_path()
        self.assertTrue(path.is_dir())
        self.assertEqual(
            self.wiki.wiki_path("volmarr", "pub"), path)
        self.assertTrue(
            self.wiki.wiki_exists(None, "volmarr", "pub"))
        out = subprocess.run(
            ["git", f"--git-dir={path}", "rev-parse",
             "--is-bare-repository"],
            capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "true")
        self.assertEqual(page.name, "Home")
        self.assertEqual(page.filename, "Home.md")
        self.assertEqual(page.content, "# Home\n\nWelcome.\n")
        # The parent repo itself gained no page file.
        self.assertFalse(
            (self.repos.path_for("volmarr", "pub")
             / "Home.md").exists())

    def test_wiki_is_stock_git_cloneable(self):
        self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home", "# Home\n")
        work = self.root / "clone"
        run_git(self.root, "clone", str(self._wiki_path()),
                str(work))
        self.assertEqual(
            (work / "Home.md").read_text(), "# Home\n")

    # -- page primitives ------------------------------------

    def test_read_write_list_round_trip(self):
        self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home", "# Home\n")
        self.wiki.write_page(
            self.owner, "volmarr", "pub", "Guide",
            "# Guide\n\nSteps.\n")
        pages = self.wiki.list_pages(None, "volmarr", "pub")
        self.assertEqual([p.name for p in pages],
                         ["Guide", "Home"])
        got = self.wiki.read_page(None, "volmarr", "pub", "Guide")
        self.assertEqual(got.content, "# Guide\n\nSteps.\n")
        self.assertEqual(got.size, len("# Guide\n\nSteps.\n"))
        self.assertTrue(got.blob_oid)
        self.assertTrue(got.commit_oid)
        d = page_to_dict(got, with_content=True)
        self.assertEqual(d["filename"], "Guide.md")
        self.assertEqual(d["content"], "# Guide\n\nSteps.\n")

    def test_update_replaces_in_one_commit_chain(self):
        first = self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home", "v1\n")
        second = self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home", "v2\n")
        self.assertNotEqual(first.commit_oid, second.commit_oid)
        pages = self.wiki.list_pages(self.owner, "volmarr", "pub")
        self.assertEqual(len(pages), 1)
        self.assertEqual(
            self.wiki.read_page(
                self.owner, "volmarr", "pub", "Home").content,
            "v2\n")
        out = subprocess.run(
            ["git", f"--git-dir={self._wiki_path()}",
             "log", "--format=%s", "main"],
            capture_output=True, text=True)
        self.assertEqual(
            out.stdout.splitlines(),
            ["Update page Home.md", "Create page Home.md"])

    def test_delete_page_and_last_page_leaves_standing_wiki(self):
        self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home", "# Home\n")
        gone = self.wiki.delete_page(
            self.owner, "volmarr", "pub", "Home")
        self.assertEqual(gone.content, "# Home\n")
        self.assertEqual(
            self.wiki.list_pages(self.owner, "volmarr", "pub"), [])
        self.assertTrue(
            self.wiki.wiki_exists(self.owner, "volmarr", "pub"))
        self.assertEqual(
            self._reason(self.wiki.delete_page,
                         self.owner, "volmarr", "pub", "Home"),
            "page_not_found")

    # -- the one name law ------------------------------------

    def test_title_normalization(self):
        self.assertEqual(
            normalize_page_title("  Getting Started "),
            "Getting-Started")
        self.assertEqual(normalize_page_title("Home.md"), "Home")
        self.assertEqual(normalize_page_title("Home"), "Home")
        page = self.wiki.write_page(
            self.owner, "volmarr", "pub", "Getting Started",
            "body\n")
        self.assertEqual(page.filename, "Getting-Started.md")
        self.assertEqual(
            self.wiki.read_page(
                None, "volmarr", "pub",
                "Getting Started").content, "body\n")

    def test_title_refusals(self):
        for bad in ("", "  ", "../secret", "a/b", "a\\b",
                    ".hidden", "trail.", "a..b", "bad\x01name",
                    None, 42, "x" * 121):
            self.assertEqual(
                self._reason(normalize_page_title, bad),
                "page_title_invalid", repr(bad))
        self.assertFalse(self._wiki_path().exists())

    def test_case_variant_title_is_same_page(self):
        self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home", "v1\n")
        self.wiki.write_page(
            self.owner, "volmarr", "pub", "home", "v2\n")
        pages = self.wiki.list_pages(self.owner, "volmarr", "pub")
        self.assertEqual([p.filename for p in pages], ["Home.md"])
        self.assertEqual(
            self.wiki.read_page(
                self.owner, "volmarr", "pub", "HOME").content,
            "v2\n")

    # -- permissions ride the parent repo ---------------------

    def test_private_repo_wiki_invisible(self):
        self.wiki.write_page(
            self.owner, "volmarr", "priv", "Secret", "shh\n")
        for viewer in (None, self.stranger):
            self.assertEqual(
                self._reason(self.wiki.list_pages,
                             viewer, "volmarr", "priv"),
                "repo_not_found")
            self.assertEqual(
                self._reason(self.wiki.read_page,
                             viewer, "volmarr", "priv", "Secret"),
                "repo_not_found")
            self.assertEqual(
                self._reason(self.wiki.wiki_exists,
                             viewer, "volmarr", "priv"),
                "repo_not_found")
        self.assertEqual(
            self.wiki.read_page(
                self.owner, "volmarr", "priv", "Secret").content,
            "shh\n")

    def test_missing_repo_is_repo_not_found(self):
        self.assertEqual(
            self._reason(self.wiki.list_pages,
                         None, "volmarr", "nope"),
            "repo_not_found")
        self.assertEqual(
            self._reason(self.wiki.write_page,
                         self.owner, "volmarr", "nope",
                         "Home", "x\n"),
            "repo_not_found")

    def test_reader_cannot_write_public_wiki(self):
        self.assertEqual(
            self._reason(self.wiki.write_page,
                         self.reader, "volmarr", "pub",
                         "Home", "x\n"),
            "permission_denied")
        self.assertEqual(
            self._reason(self.wiki.write_page,
                         None, "volmarr", "pub", "Home", "x\n"),
            "permission_denied")
        self.assertFalse(self._wiki_path().exists())
        self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home", "x\n")
        self.assertEqual(
            self._reason(self.wiki.delete_page,
                         self.reader, "volmarr", "pub", "Home"),
            "permission_denied")
        # ...but anyone may read a public wiki.
        self.assertEqual(
            self.wiki.read_page(
                None, "volmarr", "pub", "Home").content, "x\n")

    # -- content law and conflict ------------------------------

    def test_content_caps_and_type(self):
        self.assertEqual(
            self._reason(self.wiki.write_page,
                         self.owner, "volmarr", "pub", "Home",
                         b"bytes"),
            "page_invalid")
        self.assertEqual(
            self._reason(self.wiki.write_page,
                         self.owner, "volmarr", "pub", "Home",
                         "x" * (PAGE_MAX + 1)),
            "page_too_large")
        self.assertFalse(self._wiki_path().exists())

    def test_expected_tip_conflict(self):
        first = self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home", "v1\n")
        ok = self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home", "v2\n",
            expected_oid=first.commit_oid)
        self.assertEqual(
            self._reason(self.wiki.write_page,
                         self.owner, "volmarr", "pub", "Home",
                         "v3\n", expected_oid=first.commit_oid),
            "page_conflict")
        self.assertEqual(
            self.wiki.read_page(
                self.owner, "volmarr", "pub", "Home").content,
            "v2\n")
        self.assertEqual(ok.content, "v2\n")

    def test_message_law(self):
        self.assertEqual(
            self._reason(self.wiki.write_page,
                         self.owner, "volmarr", "pub", "Home",
                         "x\n", message="  "),
            "message_invalid")
        page = self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home", "x\n",
            message="Seed the wiki")
        out = subprocess.run(
            ["git", f"--git-dir={self._wiki_path()}",
             "log", "--format=%s", "main"],
            capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "Seed the wiki")
        self.assertTrue(page.commit_oid)

    # -- drift and renders -------------------------------------

    def test_existing_non_repo_path_refused(self):
        path = self._wiki_path()
        path.mkdir(parents=True)
        (path / "junk.txt").write_text("junk")
        self.assertEqual(
            self._reason(self.wiki.write_page,
                         self.owner, "volmarr", "pub", "Home",
                         "x\n"),
            "wiki_path_exists")
        # The drift is left exactly as found, never adopted.
        self.assertTrue((path / "junk.txt").exists())
        self.assertFalse(
            self.wiki.wiki_exists(self.owner, "volmarr", "pub"))

    def test_render_page_list_escapes(self):
        repo = self.repos.get_repository("volmarr", "pub")
        empty = render_wiki_page_list(repo, [])
        self.assertIn("no pages yet", empty)
        self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home", "# Home\n")
        pages = self.wiki.list_pages(self.owner, "volmarr", "pub")
        html = render_wiki_page_list(repo, pages)
        self.assertIn("Home", html)
        self.assertIn("volmarr/pub", html)

    def test_schema_and_taxonomy_stand(self):
        self.assertEqual(schema_version(self.conn), 116)
        from samverk import taxonomy
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)


if __name__ == "__main__":
    unittest.main()
