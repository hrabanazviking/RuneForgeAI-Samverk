"""S-288 — PART XIV GATE battery: wiki, gists & discussions, assembled.

The whole Part XIV system struck at once, in the house
gate shape of S-204/S-220/S-236/S-256/S-272 — no new
production code, only the battery that walks the landed
S-273..S-287 machinery end to end through its public
seams, at the things the gate names: **wiki clone/push
interop with stock git, gist lifecycle battery**.

- **Wiki storage & web (S-273/S-274)** — each repo's
  wiki is its own bare git repo, created lazily on the
  first page; pages round-trip under one title law with
  an optimistic tip check; the web face lists ordinary
  pages apart from sidebar/footer, renders beside them,
  previews without writing, and reads history from the
  wiki repo's own log.
- **Wiki transports & access (S-275/S-276)** — the wiki
  clones and pushes with STOCK git over HTTP through
  the Parts IV machinery (anonymous clone of a public
  wiki, owner push landing a new page, reader push and
  private leaks refused), the SSH door routes both pack
  legs onto the wiki path, and the access policy is the
  owner's choice — collaborators by default, all readers
  when chosen, never widening a private wiki.
- **Gist lifecycle (S-277..S-281)** — a gist is a
  mini-repository: create with many files, full revision
  history, whole-set edits in one revision, the honest
  public/secret law (secret is unlisted-but-linkable,
  never called private), the web editor, forks copying
  history and then diverging, stars, comments reusing
  S-123's machinery, and a script-free embed.
- **Discussions (S-282..S-286)** — the verdict is
  BUILD and its audit is clean; categories and threads
  with kinds, pinned posts, answer marking as an event,
  conversion both ways with forwarding notes, and polls
  honestly DEFERRED — every poll door refused, writing
  nothing.
- **Search (S-287)** — wiki pages and gists are found
  under the same permission filtering: public found by
  anyone, private wikis and secret gists invisible to
  strangers, visible to their owners.

The gate claims no migration and no taxonomy event:
the assembled system stands at schema 114 with 133
audit events (33 auth / 87 repo / 13 admin), and the
battery proves both pins.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.discussion_conversion import (
    ConversionError, DiscussionConversionStore)
from samverk.discussion_polls import DiscussionPolls, PollError
from samverk.discussions import (
    DiscussionError, DiscussionStore, render_board_page,
    render_thread_page)
from samverk.discussions_verdict import (
    VERDICT, audit_discussions_verdict,
    decide_discussion_request, get_feature)
from samverk.gist_comments import GistCommentStore
from samverk.gist_embed import GistEmbedStore
from samverk.gist_web import GistWeb
from samverk.gists import (
    GistError, GistStore, gist_to_dict, validate_visibility,
    visibility_words)
from samverk.git_http import SmartHttpService
from samverk.issues import IssueStore
from samverk.push_events import PushEventStore
from samverk.repositories import RepositoryStore
from samverk.wiki_gist_search import WikiGistSearch
from samverk.wiki_storage import WikiError, WikiStore, wiki_path_for
from samverk.wiki_storage import wiki_policy_words
from samverk.wiki_transports import (
    WikiTransports, audit_wiki_transports, is_wiki_repo_name,
    render_wiki_transports_page, split_wiki_repo_name,
    wiki_repo_name)
from samverk.wiki_web import WikiWeb
from test_git_http_receive import make_full_harness
from test_git_http_upload import GIT_ENV, cross_thread_service, seed_commit
from test_repo_home import run_git
from test_ssh_upload_routing import FakeRunner, make_world, serve

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def client_env(home: Path) -> dict:
    env = dict(os.environ)
    env.update(GIT_ENV)
    env["HOME"] = str(home)
    return env


class PartXIVGateTests(unittest.TestCase):
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
            self.conn, self.repos, audit=self.audit,
            time_fn=self.clock)
        self.wiki_web = WikiWeb(
            self.conn, self.repos, wiki=self.wiki,
            audit=self.audit, time_fn=self.clock)
        self.gists = GistStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.gist_web = GistWeb(
            self.conn, self.root, self.accounts, gists=self.gists,
            audit=self.audit, time_fn=self.clock)
        self.comments = GistCommentStore(
            self.conn, self.root, self.accounts, gists=self.gists,
            audit=self.audit, time_fn=self.clock)
        self.embeds = GistEmbedStore(
            self.conn, self.root, self.accounts, gists=self.gists,
            audit=self.audit, time_fn=self.clock)
        self.searcher = WikiGistSearch(
            self.conn, self.repos, wiki=self.wiki, gists=self.gists)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.board = DiscussionStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.polls = DiscussionPolls(
            self.conn, self.repos, self.accounts, self.board,
            audit=self.audit, time_fn=self.clock)
        self.conversions = DiscussionConversionStore(
            self.conn, self.repos, self.accounts, self.issues,
            self.board, audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.pub_code = seed_commit(self.repos, "volmarr", "pub")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        seed_commit(self.repos, "volmarr", "priv")
        self.repos.create_repository(
            self.owner.id, "volmarr", "empty", visibility="public")
        self.home = self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home",
            "# Home\n\nWelcome to the anvil wiki.\n")
        self.wiki.write_page(
            self.owner, "volmarr", "pub", "Sidebar", "- Home\n- Guide\n")
        self.wiki.write_page(
            self.owner, "volmarr", "pub", "Footer", "Forged in the north.\n")
        self.wiki.write_page(
            self.owner, "volmarr", "priv", "Secret", "# Secret\n\nShh.\n")
        self.questions = self.board.create_category(
            self.owner, "volmarr", "pub", "Questions", "question",
            "Ask the village")
        self.general = self.board.create_category(
            self.owner, "volmarr", "pub", "General", "discussion")

    # -- helpers -----------------------------------------
    def _reason(self, exc_type, fn, *a, **k):
        with self.assertRaises(exc_type) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _gist(self, description="anvil demo gist", files=None, **kw):
        return self.gists.create_gist(
            self.owner, description,
            files if files is not None else {
                "hello.py": "print('hi')\n", "notes.md": "# Notes\n"}, **kw)

    # -- pins --------------------------------------------
    def test_pins_schema_114_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 124)
        self.assertEqual(db.MIGRATIONS[-1][0], 124)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertFalse(any(
            "discussion" in e or "gist" in e or "wiki" in e
            for e in taxonomy.AUDIT_EVENTS))
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("gists", "gist_comments", "gist_comment_edits",
                      "gist_stars", "wiki_access_policies",
                      "discussion_categories", "discussion_threads",
                      "discussion_replies", "discussion_events",
                      "discussion_conversions"):
            self.assertIn(table, tables)
        self.assertNotIn("discussion_polls", tables)
        self.assertNotIn("polls", tables)

    # -- wiki storage (S-273) ------------------------------
    def test_wiki_lazy_creation_and_round_trip(self):
        path = self.wiki.wiki_path("volmarr", "empty")
        self.assertFalse(self.wiki.wiki_exists(None, "volmarr", "empty"))
        self.assertEqual(self.wiki.list_pages(None, "volmarr", "empty"), [])
        self.assertFalse(path.exists())
        page = self.wiki.write_page(
            self.owner, "volmarr", "empty", "First", "# First\n")
        self.assertTrue(path.is_dir())
        out = subprocess.run(
            ["git", f"--git-dir={path}", "rev-parse",
             "--is-bare-repository"], capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "true")
        self.assertTrue(self.wiki.wiki_exists(None, "volmarr", "empty"))
        got = self.wiki.read_page(None, "volmarr", "empty", "First")
        self.assertEqual(got.content, "# First\n")
        self.assertEqual(got.commit_oid, page.commit_oid)
        newer = self.wiki.write_page(
            self.owner, "volmarr", "empty", "First", "# First, again\n")
        self.assertNotEqual(newer.commit_oid, page.commit_oid)
        self.wiki.delete_page(self.owner, "volmarr", "empty", "First")
        self.assertEqual(self.wiki.list_pages(None, "volmarr", "empty"), [])
        self.assertTrue(path.is_dir())  # last page leaves a standing wiki

    def test_wiki_title_law_conflict_and_stock_clone(self):
        page = self.wiki.write_page(
            self.owner, "volmarr", "pub", "My Guide", "# Guide\n")
        self.assertEqual(page.name, "My-Guide")
        twin = self.wiki.read_page(None, "volmarr", "pub", "my guide")
        self.assertEqual(twin.commit_oid, page.commit_oid)
        for bad in ("../escape", "a/b", ""):
            self.assertIn(
                self._reason(WikiError, self.wiki.write_page,
                             self.owner, "volmarr", "pub", bad, "x"),
                ("page_invalid", "page_title_invalid", "page_not_found"))
        self.assertEqual(
            self._reason(WikiError, self.wiki.write_page,
                         self.owner, "volmarr", "pub", "Home", "moved\n",
                         expected_oid="0" * 40),
            "page_conflict")
        work = self.root / "wiki-clone"
        run_git(self.root, "clone",
                str(self.wiki.wiki_path("volmarr", "pub")), str(work))
        self.assertEqual(
            (work / "Home.md").read_text(),
            "# Home\n\nWelcome to the anvil wiki.\n")
        self.assertEqual((work / "My-Guide.md").read_text(), "# Guide\n")

    def test_wiki_private_repo_uniform(self):
        for viewer in (None, self.stranger):
            self.assertEqual(
                self._reason(WikiError, self.wiki.list_pages,
                             viewer, "volmarr", "priv"),
                "repo_not_found")
            self.assertEqual(
                self._reason(WikiError, self.wiki.read_page,
                             viewer, "volmarr", "priv", "Secret"),
                "repo_not_found")
        self.assertEqual(
            self.wiki.read_page(
                self.owner, "volmarr", "priv", "Secret").content,
            "# Secret\n\nShh.\n")

    # -- wiki web (S-274) ----------------------------------
    def test_wiki_web_experience(self):
        index = self.wiki_web.index(None, "volmarr", "pub")
        self.assertEqual([p.name for p in index.pages], ["Home"])
        self.assertEqual(index.sidebar.name, "Sidebar")
        self.assertEqual(index.footer.name, "Footer")
        view = self.wiki_web.view_page(None, "volmarr", "pub")
        self.assertEqual(view.page.name, "Home")
        self.assertIn("anvil wiki", view.body_html)
        self.assertIn("Home", view.sidebar_html)
        self.assertIn("Forged", view.footer_html)
        tip_before = self.wiki.read_page(
            self.owner, "volmarr", "pub", "Home").commit_oid
        preview = self.wiki_web.preview_page(
            self.owner, "volmarr", "pub", "Draft", "# Draft\n")
        self.assertIn("Draft", preview.body_html)
        self.assertEqual(
            [p.name for p in self.wiki.list_pages(None, "volmarr", "pub")],
            ["Footer", "Home", "Sidebar"])
        self.assertEqual(
            self.wiki.read_page(
                self.owner, "volmarr", "pub", "Home").commit_oid,
            tip_before)
        saved = self.wiki_web.save_page(
            self.owner, "volmarr", "pub", "Guide", "# Guide\n")
        self.assertEqual(saved.name, "Guide")
        history = self.wiki_web.history(None, "volmarr", "pub")
        self.assertEqual(history.total_commits, 4)
        self.assertEqual(history.entries[0].pages, ("Guide",))
        filtered = self.wiki_web.history(
            None, "volmarr", "pub", title="Home")
        self.assertTrue(all(
            "Home" in e.pages for e in filtered.entries))
        self.assertEqual(
            self._reason(Exception, self.wiki_web.view_page,
                         self.stranger, "volmarr", "priv"),
            "repo_not_found")

    # -- wiki access policy (S-276) -------------------------
    def test_wiki_access_policy_law(self):
        access = self.wiki.access_policy(None, "volmarr", "pub")
        self.assertEqual(access.policy, "collaborators")
        self.assertTrue(access.is_default)
        self.assertFalse(self.wiki.can_edit_wiki(self.reader, "volmarr", "pub"))
        self.assertEqual(
            self._reason(WikiError, self.wiki.write_page,
                         self.reader, "volmarr", "pub", "Sneak", "x\n"),
            "permission_denied")
        self.assertEqual(
            self._reason(WikiError, self.wiki.set_access_policy,
                         self.reader, "volmarr", "pub", "readers"),
            "permission_denied")
        chosen = self.wiki.set_access_policy(
            self.owner, "volmarr", "pub", "readers")
        self.assertEqual(chosen.policy, "readers")
        self.assertIn("reader", wiki_policy_words("readers").lower())
        self.assertTrue(self.wiki.can_edit_wiki(self.reader, "volmarr", "pub"))
        self.wiki.write_page(
            self.reader, "volmarr", "pub", "Reader Page", "# By a reader\n")
        self.wiki.delete_page(self.reader, "volmarr", "pub", "Reader Page")
        self.assertFalse(self.wiki.can_edit_wiki(None, "volmarr", "pub"))
        self.wiki.set_access_policy(
            self.owner, "volmarr", "priv", "readers")
        self.assertEqual(
            self._reason(WikiError, self.wiki.list_pages,
                         self.stranger, "volmarr", "priv"),
            "repo_not_found")
        self.wiki.set_access_policy(
            self.owner, "volmarr", "pub", "collaborators")
        self.assertFalse(self.wiki.can_edit_wiki(self.reader, "volmarr", "pub"))

    # -- wiki transports (S-275): naming + audit ------------
    def test_wiki_transports_naming_and_audit(self):
        self.assertEqual(wiki_repo_name("pub"), "pub.wiki")
        self.assertEqual(split_wiki_repo_name("pub.wiki"), "pub")
        self.assertEqual(split_wiki_repo_name("pub.wiki.git"), "pub")
        self.assertIsNone(split_wiki_repo_name("pub"))
        self.assertTrue(is_wiki_repo_name("pub.wiki.git"))
        self.assertFalse(is_wiki_repo_name("pub.git"))
        before = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log").fetchone()[0]
        audit = audit_wiki_transports(self.repos, None, "volmarr", "pub.wiki")
        self.assertEqual(audit.full_name, "volmarr/pub")
        self.assertTrue(audit.wiki_standing)
        self.assertEqual(audit.transports, ("http", "ssh"))
        unborn = audit_wiki_transports(
            self.repos, None, "volmarr", "empty.wiki")
        self.assertFalse(unborn.wiki_standing)
        self.assertFalse(self.wiki.wiki_path("volmarr", "empty").exists())
        after = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log").fetchone()[0]
        self.assertEqual(before, after)
        html = render_wiki_transports_page(audit)
        self.assertIn("/volmarr/pub.wiki.git", html)
        self.assertIn("git@samverk:volmarr/pub.wiki.git", html)
        seam = WikiTransports(self.conn, self.repos, audit=self.audit)
        self.assertEqual(
            seam.parent_for("volmarr", "pub.wiki").full_name, "volmarr/pub")
        from samverk.wiki_transports import WikiTransportError
        self.assertEqual(
            self._reason(WikiTransportError, audit_wiki_transports,
                         self.repos, self.stranger, "volmarr", "priv.wiki"),
            "repo_not_found")

    # -- wiki transports: STOCK GIT over HTTP ----------------
    def _harness(self, viewer, **service_kw):
        service = cross_thread_service(self.root)
        if service_kw:
            service = SmartHttpService(
                service._conn, self.root, service._accounts,
                service._repos, **service_kw)
        server = make_full_harness(service, viewer)
        self.addCleanup(server.shutdown)
        return server

    def _clone_http(self, server, name, dest, expect=0):
        port = server.server_address[1]
        out = subprocess.run(
            ["git", "clone",
             f"http://127.0.0.1:{port}/volmarr/{name}", str(dest)],
            capture_output=True, env=client_env(self.root))
        self.assertEqual(out.returncode, expect, out.stderr.decode())
        return out

    def _git_in(self, dest, *args):
        out = subprocess.run(
            ["git", "-C", str(dest), *args],
            capture_output=True, env=client_env(self.root))
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        return out

    def test_stock_git_clones_public_wiki_anonymously(self):
        server = self._harness(None)
        dest = self.root / "clone-pub-wiki"
        self._clone_http(server, "pub.wiki.git", dest)
        self.assertEqual(
            (dest / "Home.md").read_text(),
            "# Home\n\nWelcome to the anvil wiki.\n")
        head = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True, text=True, env=client_env(self.root))
        tip = subprocess.run(
            ["git", f"--git-dir={self.wiki.wiki_path('volmarr', 'pub')}",
             "rev-parse", "refs/heads/main"],
            capture_output=True, text=True)
        self.assertEqual(head.stdout.strip(), tip.stdout.strip())
        self.assertNotEqual(head.stdout.strip(), self.pub_code)

    def test_stock_git_pushes_a_new_page_over_http(self):
        base = cross_thread_service(self.root)
        events = PushEventStore(base._conn, base._repos)
        server = make_full_harness(
            SmartHttpService(base._conn, self.root, base._accounts,
                             base._repos, push_events=events,
                             audit=AuditLog(base._conn)),
            self.owner)
        self.addCleanup(server.shutdown)
        dest = self.root / "push-wiki"
        self._clone_http(server, "pub.wiki.git", dest)
        (dest / "Guide.md").write_text("# Guide\n\nNew page.\n")
        for args in (["add", "Guide.md"], ["commit", "-m", "Add the guide"],
                     ["push", "origin", "main"]):
            self._git_in(dest, *args)
        pages = self.wiki.list_pages(self.owner, "volmarr", "pub")
        self.assertIn("Guide", [p.name for p in pages])
        self.assertEqual(
            self.wiki.read_page(None, "volmarr", "pub", "Guide").content,
            "# Guide\n\nNew page.\n")
        code_tip = run_git(
            self.repos.path_for("volmarr", "pub"),
            "rev-parse", "refs/heads/main").strip()
        self.assertEqual(code_tip, self.pub_code)
        landed = events.list_for_repo("volmarr", "pub")
        self.assertEqual(len(landed), 1)
        self.assertEqual(landed[0].transport, "http")

    def test_stock_git_http_private_and_reader_push_refused(self):
        owner_server = self._harness(self.owner)
        dest = self.root / "clone-priv-wiki"
        self._clone_http(owner_server, "priv.wiki.git", dest)
        self.assertEqual((dest / "Secret.md").read_text(), "# Secret\n\nShh.\n")
        stranger_server = self._harness(self.stranger)
        self._clone_http(stranger_server, "priv.wiki.git",
                         self.root / "clone-priv-denied", expect=128)
        reader_server = self._harness(self.reader)
        clone = self.root / "reader-clone"
        self._clone_http(reader_server, "pub.wiki.git", clone)
        (clone / "Sneak.md").write_text("# Sneak\n")
        self._git_in(clone, "add", "Sneak.md")
        self._git_in(clone, "commit", "-m", "sneak")
        out = subprocess.run(
            ["git", "-C", str(clone), "push", "origin", "main"],
            capture_output=True, env=client_env(self.root))
        self.assertNotEqual(out.returncode, 0)
        self.assertNotIn(
            "Sneak",
            [p.name for p in self.wiki.list_pages(
                self.owner, "volmarr", "pub")])


class SshWikiGateTests(unittest.TestCase):
    """The SSH door routes both pack legs onto the wiki path."""

    def setUp(self):
        self.runner = FakeRunner()
        self.w = make_world(self, runner=self.runner)
        self.wiki = WikiStore(self.w["conn"], self.w["repos"])
        self.wiki.write_page(
            self.w["owner"], "volmarr", "open", "Home", "# Open wiki\n")
        self.wiki.write_page(
            self.w["owner"], "volmarr", "samverk", "Home", "# Private\n")

    def test_ssh_door_routes_wiki_packs_with_parent_law(self):
        root = self.w["root"]
        rc, out, _ = serve(
            self.w, self.w["owner_fp"], "git-upload-pack 'volmarr/open.wiki'")
        self.assertEqual((rc, out), (0, b"PACK-OK"))
        self.assertEqual(
            self.runner.calls[-1][0],
            root / "repos" / "volmarr" / "open.wiki")
        rc, _, _ = serve(
            self.w, self.w["owner_fp"],
            "git-receive-pack 'volmarr/open.wiki'")
        self.assertEqual(rc, 0)
        self.assertEqual(self.runner.calls[-1][1], "receive-pack")
        calls = len(self.runner.calls)
        rc, _, err = serve(
            self.w, self.w["other_fp"],
            "git-upload-pack 'volmarr/samverk.wiki'")
        self.assertEqual(rc, 128)
        rc2, _, err2 = serve(
            self.w, self.w["other_fp"],
            "git-upload-pack 'volmarr/nope.wiki'")
        self.assertEqual(rc2, 128)
        self.assertEqual(err, err2)  # existence never leaks
        rc, _, err = serve(
            self.w, self.w["other_fp"],
            "git-receive-pack 'volmarr/open.wiki'")
        self.assertEqual(rc, 128)
        self.assertIn(b"write permission", err)
        self.assertEqual(len(self.runner.calls), calls)


class PartXIVGistDiscussionGateTests(unittest.TestCase):
    """Gists, discussions and search, in one standing world."""

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
            self.conn, self.repos, audit=self.audit,
            time_fn=self.clock)
        self.gists = GistStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.gist_web = GistWeb(
            self.conn, self.root, self.accounts, gists=self.gists,
            audit=self.audit, time_fn=self.clock)
        self.comments = GistCommentStore(
            self.conn, self.root, self.accounts, gists=self.gists,
            audit=self.audit, time_fn=self.clock)
        self.embeds = GistEmbedStore(
            self.conn, self.root, self.accounts, gists=self.gists,
            audit=self.audit, time_fn=self.clock)
        self.searcher = WikiGistSearch(
            self.conn, self.repos, wiki=self.wiki, gists=self.gists)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.board = DiscussionStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.polls = DiscussionPolls(
            self.conn, self.repos, self.accounts, self.board,
            audit=self.audit, time_fn=self.clock)
        self.conversions = DiscussionConversionStore(
            self.conn, self.repos, self.accounts, self.issues,
            self.board, audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home",
            "# Home\n\nThe quixotic anvil rings here.\n")
        self.wiki.write_page(
            self.owner, "volmarr", "priv", "Secret",
            "# Secret\n\nThe quixotic anvil hides.\n")
        self.questions = self.board.create_category(
            self.owner, "volmarr", "pub", "Questions", "question",
            "Ask the village")
        self.general = self.board.create_category(
            self.owner, "volmarr", "pub", "General", "discussion")

    def _reason(self, exc_type, fn, *a, **k):
        with self.assertRaises(exc_type) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _gist(self, description="anvil demo gist", files=None, **kw):
        return self.gists.create_gist(
            self.owner, description,
            files if files is not None else {
                "hello.py": "print('hi')\n", "notes.md": "# Notes\n"}, **kw)

    # -- gist lifecycle (S-277/S-278) -----------------------
    def test_gist_lifecycle_end_to_end(self):
        gist = self._gist()
        path = self.gists.gist_path(gist.id)
        self.assertTrue(path.is_dir())
        self.assertEqual(gist.revision_count, 1)
        work = self.root / "gist-clone"
        run_git(self.root, "clone", str(path), str(work))
        self.assertEqual((work / "hello.py").read_text(), "print('hi')\n")
        updated = self.gists.update_gist(
            self.owner, gist.id,
            files={"hello.py": "print('ho')\n", "new.txt": "fresh\n"},
            expected_oid=gist.head_oid)
        self.assertEqual(updated.revision_count, 2)
        self.assertEqual(
            [f.name for f in self.gists.list_files(self.owner, gist.id)],
            ["hello.py", "new.txt"])
        revisions = self.gists.list_revisions(self.owner, gist.id)
        self.assertEqual(len(revisions), 2)
        past = self.gists.read_file(
            self.owner, gist.id, "notes.md", revision=revisions[-1].oid)
        self.assertEqual(past.content, "# Notes\n")
        self.assertEqual(
            self._reason(GistError, self.gists.update_gist,
                         self.owner, gist.id,
                         files={"a.txt": "a"}, expected_oid=gist.head_oid),
            "gist_conflict")
        self.assertEqual(
            gist_to_dict(self.gists.get_gist(None, gist.id))["description"],
            "anvil demo gist")
        self.gists.delete_gist(self.owner, gist.id)
        self.assertFalse(path.exists())
        self.assertEqual(
            self._reason(GistError, self.gists.get_gist,
                         self.owner, gist.id),
            "gist_not_found")

    def test_gist_visibility_honest_law(self):
        public = self._gist("public one")
        secret = self._gist("secret one", visibility="secret")
        self.assertEqual(secret.visibility, "secret")
        words = visibility_words("secret").lower()
        self.assertIn("unlisted", words)
        self.assertIn("link", words)  # linkable, honestly never "private"
        self.assertEqual(
            self._reason(GistError, validate_visibility, "private"),
            "visibility_invalid")
        self.assertEqual(
            [g.id for g in self.gists.list_gists(None, "volmarr")],
            [public.id])
        self.assertEqual(
            [g.id for g in self.gists.list_gists(self.stranger, "volmarr")],
            [public.id])
        self.assertEqual(
            {g.id for g in self.gists.list_gists(self.owner, "volmarr")},
            {public.id, secret.id})
        by_link = self.gists.get_gist(self.stranger, secret.id)
        self.assertEqual(by_link.id, secret.id)  # linkable, not private
        changed = self.gists.update_gist(
            self.owner, secret.id, visibility="public")
        self.assertEqual(changed.revision_count, secret.revision_count)
        self.assertIn(
            secret.id,
            [g.id for g in self.gists.list_gists(None, "volmarr")])

    def test_gist_editor_web_round_trip(self):
        made = self.gist_web.create_gist(
            self.owner, "web made", "public",
            [("a.py", "print(1)\n"), ("b.md", "# B\n")])
        view = self.gist_web.view_gist(None, made.id)
        self.assertEqual(view.gist.id, made.id)
        self.assertEqual([f.name for f in view.files], ["a.py", "b.md"])
        edit = self.gist_web.edit_view(self.owner, made.id)
        self.assertEqual(edit.expected_oid, made.head_oid)
        self.assertEqual(
            self._reason(Exception, self.gist_web.edit_view,
                         self.reader, made.id),
            "permission_denied")
        saved = self.gist_web.save_gist(
            self.owner, made.id, pairs=[("a.py", "print(2)\n")],
            expected_oid=edit.expected_oid)
        self.assertEqual(saved.revision_count, 2)
        self.assertEqual(
            [f.name for f in self.gists.list_files(self.owner, made.id)],
            ["a.py"])
        self.assertEqual(
            self._reason(Exception, self.gist_web.save_gist,
                         self.owner, made.id,
                         pairs=[("a.py", "print(3)\n")],
                         expected_oid=made.head_oid),
            "gist_conflict")
        self.assertEqual(
            self.gists.read_file(self.owner, made.id, "a.py").content,
            "print(2)\n")

    # -- gist fork & star (S-279) ----------------------------
    def test_gist_fork_copies_history_and_diverges(self):
        source = self._gist("fork me")
        source = self.gists.update_gist(
            self.owner, source.id,
            files={"hello.py": "print('v2')\n", "notes.md": "# Notes\n"})
        fork = self.gists.fork_gist(self.reader, source.id)
        self.assertEqual(fork.owner, "yrsa")
        self.assertEqual(fork.revision_count, 2)
        self.assertEqual(fork.head_oid, source.head_oid)
        self.assertEqual(self.gists.fork_count(source.id), 1)
        self.assertEqual(
            self.gists.fork_source(self.reader, fork.id).id, source.id)
        self.gists.update_gist(
            self.reader, fork.id, files={"hello.py": "print('fork')\n"})
        self.assertEqual(
            self.gists.read_file(self.owner, source.id, "hello.py").content,
            "print('v2')\n")
        self.assertEqual(self.gists.get_gist(self.owner, source.id).revision_count, 2)

    def test_gist_star_lifecycle(self):
        gist = self._gist("star me")
        self.assertEqual(self.gists.star_count(gist), 0)
        self.gists.star(self.reader, gist.id)
        self.gists.star(self.reader, gist.id)  # retry is a quiet no-op
        self.gists.star(self.stranger, gist.id)
        self.assertEqual(self.gists.star_count(gist), 2)
        self.assertTrue(self.gists.is_starred(self.reader, gist.id))
        self.assertEqual(
            [g.id for g in self.gists.list_starred_gists(self.reader, "yrsa")],
            [gist.id])
        self.gists.unstar(self.reader, gist.id)
        self.assertEqual(self.gists.star_count(gist), 1)
        self.gists.delete_gist(self.owner, gist.id)
        self.assertEqual(
            self.gists.list_starred_gists(self.stranger, "mallory"), [])

    # -- gist comments & embed (S-280/S-281) ------------------
    def test_gist_comments_lifecycle(self):
        gist = self._gist("talk about me")
        first = self.comments.add_comment(self.reader, gist.id, "First word.")
        second = self.comments.add_comment(self.owner, gist.id, "Second word.")
        listed = self.comments.list_comments(None, gist.id)
        self.assertEqual([c.id for c in listed], [first.id, second.id])
        self.comments.edit_comment(
            self.reader, gist.id, first.id, "First word, amended.")
        edits = self.comments.edits_for(None, gist.id, first.id)
        self.assertEqual(len(edits), 1)
        self.assertEqual(
            self._reason(GistError, self.comments.edit_comment,
                         self.stranger, gist.id, first.id, "hijack"),
            "permission_denied")
        self.comments.delete_comment(self.reader, gist.id, first.id)
        gone = self.comments.get_comment(None, gist.id, first.id)
        self.assertTrue(gone.is_deleted)
        fork = self.gists.fork_gist(self.reader, gist.id)
        self.assertEqual(self.comments.comment_count(None, fork.id), 0)
        self.gists.delete_gist(self.owner, gist.id)
        self.assertEqual(
            self._reason(GistError, self.comments.list_comments,
                         None, gist.id),
            "gist_not_found")

    def test_gist_embed_script_free_and_pinned(self):
        gist = self._gist(
            "embed <script>alert(1)</script> me",
            files={"x.py": "print('x')\n"})
        snippet = self.embeds.snippet(None, gist.id)
        self.assertNotIn("<script", snippet)
        self.assertNotIn("<iframe", snippet)
        self.assertNotIn("<script>alert", snippet)
        markdown = self.embeds.snippet(None, gist.id, form="markdown")
        self.assertIn("print('x')", markdown)
        self.gists.update_gist(
            self.owner, gist.id, files={"x.py": "print('y')\n"})
        pinned = self.embeds.snippet(None, gist.id, revision=gist.head_oid)
        self.assertIn("print('x')", pinned)
        self.assertNotIn("print('y')", pinned)
        document = self.embeds.embed_document(None, gist.id)
        self.assertIn("print('y')", document)

    # -- search (S-287) ---------------------------------------
    def test_search_permission_filtering(self):
        public = self._gist("quixotic public gist")
        secret = self._gist("quixotic secret gist", visibility="secret")
        anon = self.searcher.search(None, "quixotic")
        self.assertEqual(anon.wiki.total, 1)
        self.assertEqual(anon.wiki.hits[0].page_name, "Home")
        self.assertGreater(anon.wiki.hits[0].matched_lines, 0)
        self.assertEqual(anon.gists.total, 1)
        self.assertEqual(anon.gists.hits[0].gist_id, public.id)
        stranger = self.searcher.search(self.stranger, "quixotic")
        self.assertEqual(stranger.gists.total, 1)
        own = self.searcher.search(self.owner, "quixotic")
        self.assertEqual(own.wiki.total, 2)
        self.assertEqual(own.gists.total, 2)
        narrowed = self.searcher.search(None, "type:gist quixotic")
        self.assertIsNone(narrowed.wiki)
        self.assertEqual(narrowed.gists.total, 1)
        from samverk.wiki_gist_search import WikiGistSearchError
        self.assertEqual(
            self._reason(WikiGistSearchError,
                         self.searcher.search_repository,
                         self.stranger, "volmarr", "priv", "quixotic"),
            "repo_not_found")
        scoped = self.searcher.search_repository(
            self.owner, "volmarr", "priv", "quixotic")
        self.assertEqual(scoped.total, 1)

    # -- discussions verdict (S-282) ---------------------------
    def test_discussions_verdict_build_and_polls_deferred(self):
        self.assertEqual(VERDICT, "build")
        audit = audit_discussions_verdict(self.conn)
        self.assertTrue(audit.build_queued_cleanly, audit)
        self.assertEqual(audit.events_scanned, 135)
        self.assertEqual(get_feature("polls").judgement, "deferred")
        self.assertEqual(decide_discussion_request("polls"), "discussions_deferred")

    # -- discussions (S-283/S-284) ------------------------------
    def test_discussion_thread_lifecycle(self):
        thread = self.board.create_thread(
            self.owner, "volmarr", "pub", self.general.id,
            "Hall hours", "When does the hall open?")
        self.assertEqual(thread.number, 1)
        reply = self.board.add_reply(
            self.reader, "volmarr", "pub", thread.number, "At dawn.")
        self.assertEqual(self.board.reply_count(
            None, "volmarr", "pub", thread.number), 1)
        self.board.pin_thread(self.owner, "volmarr", "pub", thread.number)
        pinned = self.board.list_threads(
            None, "volmarr", "pub", pinned=True)
        self.assertEqual([t.number for t in pinned], [thread.number])
        self.board.close_thread(self.owner, "volmarr", "pub", thread.number)
        self.assertEqual(
            self._reason(DiscussionError, self.board.add_reply,
                         self.reader, "volmarr", "pub", thread.number,
                         "Too late."),
            "discussion_closed")
        self.board.reopen_thread(self.owner, "volmarr", "pub", thread.number)
        self.board.add_reply(
            self.reader, "volmarr", "pub", thread.number, "Back again.")
        kinds = [e.event.kind for e in self.board.timeline(
            None, "volmarr", "pub", thread.number) if not e.is_reply]
        for kind in ("created", "pinned", "closed", "reopened"):
            self.assertIn(kind, kinds)
        page = render_thread_page(
            self.board.get_thread(None, "volmarr", "pub", thread.number),
            self.general,
            self.board.timeline(None, "volmarr", "pub", thread.number))
        self.assertIn("Hall hours", page)

    def test_discussion_answer_marking(self):
        thread = self.board.create_thread(
            self.owner, "volmarr", "pub", self.questions.id,
            "Why is the sky grey?", "Asking for the village.")
        answer = self.board.add_reply(
            self.reader, "volmarr", "pub", thread.number,
            "Because winter is honest.")
        other = self.board.add_reply(
            self.stranger, "volmarr", "pub", thread.number, "Magic.")
        self.assertEqual(
            self._reason(DiscussionError, self.board.mark_answer,
                         self.stranger, "volmarr", "pub", thread.number,
                         other.id),
            "permission_denied")
        marked = self.board.mark_answer(
            self.owner, "volmarr", "pub", thread.number, answer.id)
        self.assertTrue(marked.is_answered)
        self.assertEqual(
            self.board.accepted_answer(
                None, "volmarr", "pub", thread.number).id, answer.id)
        answered = self.board.list_threads(
            None, "volmarr", "pub", answered=True)
        self.assertEqual([t.number for t in answered], [thread.number])
        self.board.mark_answer(
            self.owner, "volmarr", "pub", thread.number, other.id)
        self.assertEqual(
            self.board.accepted_answer(
                None, "volmarr", "pub", thread.number).id, other.id)
        self.board.unmark_answer(
            self.owner, "volmarr", "pub", thread.number)
        self.assertIsNone(self.board.accepted_answer(
            None, "volmarr", "pub", thread.number))
        self.board.mark_answer(
            self.owner, "volmarr", "pub", thread.number, answer.id)
        self.board.delete_reply(
            self.reader, "volmarr", "pub", thread.number, answer.id)
        self.assertIsNone(self.board.accepted_answer(
            None, "volmarr", "pub", thread.number))

    def test_private_discussion_board_missing(self):
        self.board.create_category(
            self.owner, "volmarr", "priv", "Hidden", "discussion")
        for viewer in (None, self.stranger):
            self.assertEqual(
                self._reason(DiscussionError, self.board.list_categories,
                             viewer, "volmarr", "priv"),
                "repo_not_found")
            self.assertEqual(
                self._reason(DiscussionError, self.board.get_thread,
                             viewer, "volmarr", "priv", 1),
                "discussion_not_found")

    # -- conversion (S-285) --------------------------------------
    def test_discussion_conversion_both_ways(self):
        issue = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Gate sticks", "It sticks.")
        link = self.conversions.convert_issue_to_discussion(
            self.owner, "volmarr", "pub", issue.number, self.general.id)
        self.assertEqual(link.issue_number, issue.number)
        thread = self.board.get_thread(
            None, "volmarr", "pub", link.discussion_number)
        self.assertEqual(thread.title, "Gate sticks")
        back = self.conversions.conversion_for_issue(
            None, "volmarr", "pub", issue.number)
        self.assertEqual(back.id, link.id)
        self.assertEqual(
            self._reason(ConversionError,
                         self.conversions.convert_issue_to_discussion,
                         self.owner, "volmarr", "pub", issue.number,
                         self.general.id),
            "already_converted")
        second = self.board.create_thread(
            self.owner, "volmarr", "pub", self.general.id,
            "Well depth", "How deep is the well?")
        link2 = self.conversions.convert_discussion_to_issue(
            self.owner, "volmarr", "pub", second.number)
        made = self.issues.get_issue(
            None, "volmarr", "pub", link2.issue_number)
        self.assertEqual(made.title, "Well depth")
        self.assertEqual(
            self._reason(ConversionError,
                         self.conversions.convert_discussion_to_issue,
                         self.owner, "volmarr", "pub", second.number),
            "already_converted")

    # -- polls (S-286): deferred, refused, clean -------------------
    def test_discussion_polls_refused_cleanly(self):
        thread = self.board.create_thread(
            self.owner, "volmarr", "pub", self.general.id,
            "Feast day", "Pick a day.")
        before_audit = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log").fetchone()[0]
        before_replies = self.board.reply_count(
            None, "volmarr", "pub", thread.number)
        self.assertEqual(
            self._reason(PollError, self.polls.create_poll,
                         self.owner, "volmarr", "pub", thread.number,
                         "Which day?", ["Friday", "Saturday"], T0 + 86400),
            "discussions_deferred")
        self.assertEqual(
            self._reason(PollError, self.polls.vote,
                         self.reader, "volmarr", "pub", thread.number, 0),
            "discussions_deferred")
        self.assertEqual(
            self._reason(PollError, self.polls.results,
                         None, "volmarr", "pub", thread.number),
            "discussions_deferred")
        after_audit = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log").fetchone()[0]
        self.assertEqual(before_audit, after_audit)
        self.assertEqual(
            self.board.reply_count(None, "volmarr", "pub", thread.number),
            before_replies)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(any("poll" in t for t in tables))

    # -- one Part XIV day, end to end -------------------------------
    def test_one_part_xiv_day_end_to_end(self):
        gist = self._gist(
            "quixotic field notes",
            files={"field.md": "The quixotic anvil, observed.\n"})
        self.gists.star(self.reader, gist.id)
        self.comments.add_comment(self.reader, gist.id, "Seen at dawn.")
        fork = self.gists.fork_gist(self.stranger, gist.id)
        self.assertEqual(self.gists.fork_count(gist.id), 1)
        found = self.searcher.search(self.stranger, "quixotic")
        self.assertEqual(found.wiki.total, 1)
        self.assertGreaterEqual(found.gists.total, 1)
        thread = self.board.create_thread(
            self.owner, "volmarr", "pub", self.questions.id,
            "What did the field notes say?", "Settle it here.")
        reply = self.board.add_reply(
            self.reader, "volmarr", "pub", thread.number,
            "That the anvil rings at dawn.")
        self.board.mark_answer(
            self.owner, "volmarr", "pub", thread.number, reply.id)
        board_page = render_board_page(
            self.board.list_categories(None, "volmarr", "pub"),
            self.board.list_threads(None, "volmarr", "pub"))
        self.assertIn("Questions", board_page)
        view = self.gist_web.view_gist(self.stranger, gist.id)
        self.assertEqual(view.comment_count, 1)
        self.assertEqual(view.fork_count, 1)
        self.assertEqual(view.star_count, 1)
        self.assertEqual(fork.owner, "mallory")


if __name__ == "__main__":
    unittest.main()
