"""S-213 acceptance battery: global search UI.

Acceptance (roadmap S-213): Global search UI — one
box, typed result groups, keyboard-first, recent
searches per user.

The planted secret is deliberate bait, in the S-209
shape: a private repository (`vault`) whose
description, only commit, only code file, and only
issue all carry the unique word `zorblax`, so any
leak channel — a group executed without its S-209
filtering, a count tallied across groups, a recent
search read across users — moves a string or a
number this battery watches. The centre is the
equivalence proof: a stranger's per-group hits and
counts over a world WITH the private repository
equal, exactly, the same search over a world where
it was never created.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.code_indexing import CodeIndexer
from samverk.db import schema_version
from samverk.global_search import (
    GROUP_ORDER, GlobalSearch, GlobalSearchError, RecentSearchStore,
    keyboard_focus_order, parse_global_query, render_global_search_box,
    render_global_search_page, render_recent_searches)
from samverk.index_architecture import SearchIndexStore
from samverk.issue_pr_search import IssuePRSearch
from samverk.issues import IssueStore
from samverk.organizations import OrganizationStore
from samverk.repositories import RepositoryStore
from test_repo_home import GIT_ENV, run_git

PW = "correct horse battery"
THOR = ("A U Thor", "a@example.com")
SIGRUN = ("Sigrun Halvorsen", "sigrun@example.com")
KEEPER = ("Zorblax Keeper", "keeper@example.com")


def commit(work, filename, text, subject, body, author, when):
    path = work / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    run_git(work, "add", "-A")
    env = dict(os.environ); env.update(GIT_ENV)
    env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = author
    env["GIT_COMMITTER_NAME"], env["GIT_COMMITTER_EMAIL"] = author
    env["GIT_AUTHOR_DATE"] = str(when)
    env["GIT_COMMITTER_DATE"] = str(when)
    out = subprocess.run(
        ["git", "commit", "-m", subject, "-m", body],
        cwd=work, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return run_git(work, "rev-parse", "HEAD")


class Clock:
    def __init__(self):
        self.t = 1000

    def __call__(self):
        self.t += 1
        return self.t


def make_world(root: Path, with_secret: bool) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    accounts = AccountStore(conn)
    orgs = OrganizationStore(conn, accounts)
    owner = accounts.register("volmarr", PW)
    other = accounts.register("sigrun", PW)
    stranger = accounts.register("mallory", PW)
    repos = RepositoryStore(conn, root, accounts)
    audit = AuditLog(conn)
    issues = IssueStore(conn, repos, accounts, audit=audit)
    indexer = CodeIndexer(conn, repos)
    clock = Clock()
    recents = RecentSearchStore(conn, time_fn=clock)
    w = SimpleNamespace(
        conn=conn, accounts=accounts, orgs=orgs, owner=owner,
        other=other, stranger=stranger, repos=repos, issues=issues,
        recents=recents, clock=clock,
        search=GlobalSearch(conn, repos, orgs, recents=recents))

    def profile(user, display, bio):
        conn.execute(
            "INSERT INTO profiles (user_id, display_name, bio,"
            " updated_at) VALUES (?, ?, ?, 0)",
            (user.id, display, bio))
        conn.commit()

    profile(owner, "Volmarr Wyrd", "Forge keeper and hall skald")
    profile(other, "Sigrun Halvorsen", "Weaver of the great hall")
    profile(stranger, "Mallory Quinn", "Wandering cartographer")
    orgs.create_organization(
        owner.id, "ForgeGuild", display_name="The Forge Guild",
        bio="Smiths and builders of the hall")

    def workdir(name):
        d = root / ("work-" + name); d.mkdir()
        run_git(d, "init", "-b", "main")
        return d

    repos.create_repository(
        owner.id, "volmarr", "anvil", visibility="public",
        description="Forge tools for the hall")
    bare = repos.path_for("volmarr", "anvil")
    work = workdir("anvil")
    commit(work, "main.py", "print('forge one')\nforge again\n",
           "Forge the anvil frame", "Hammer work begins",
           THOR, 1700000100)
    commit(work, "lib.py", "VALUE = 'forge'\n",
           "Forge the bellows", "Air for the forge",
           SIGRUN, 1700000200)
    run_git(work, "push", str(bare), "main")
    indexer.index_repository("volmarr", "anvil")
    issues.create_issue(owner, "volmarr", "anvil",
                        "Forge door sticks", "the forge door drags")
    issues.create_issue(owner, "volmarr", "anvil",
                        "Forge <b>markup</b> check", "escape me")

    if with_secret:
        repos.create_repository(
            owner.id, "volmarr", "vault", visibility="private",
            description="zorblax vault plans")
        bare = repos.path_for("volmarr", "vault")
        work = workdir("vault")
        commit(work, "secret.py", "zorblax = 'zorblax'\n",
               "zorblax secret plans", "hidden zorblax body",
               KEEPER, 1700000500)
        run_git(work, "push", str(bare), "main")
        indexer.index_repository("volmarr", "vault")
        issues.create_issue(owner, "volmarr", "vault",
                            "Zorblax master plan", "zorblax secrets")

    backend = IssuePRSearch(conn, repos, SearchIndexStore(conn, repos))
    backend.index_all()
    return w


def signature(results):
    """Per-group identity + totals, for the leakage
    equivalence proof: groups in order, each group's
    hit identities and its own total — never summed."""
    out = []
    for group in results.groups:
        if group.kind == "repositories":
            ids = [h.full_name for h in group.hits]
        elif group.kind == "people":
            ids = [(h.kind, h.handle) for h in group.hits]
        elif group.kind == "commits":
            ids = [(h.full_name, h.subject) for h in group.hits]
        elif group.kind == "code":
            ids = [(h.full_name, h.path) for h in group.hits]
        else:
            ids = [(h.full_name, h.number, h.title)
                   for h in group.hits]
        out.append((group.kind, ids, group.total,
                    group.total_matches, group.total_matched_lines))
    return out


class PureLawTests(unittest.TestCase):
    def test_parse_terms_and_type(self):
        q = parse_global_query("forge type:code")
        self.assertEqual(q.terms, ("forge",))
        self.assertEqual(q.types, ("code",))
        self.assertEqual(q.groups, ("code",))
        self.assertFalse(q.is_empty)

    def test_parse_aliases_and_group_order(self):
        q = parse_global_query("forge type:pr type:repo type:users")
        self.assertEqual(q.groups, ("repositories", "people", "issues"))

    def test_parse_negation_and_default_all(self):
        q = parse_global_query("forge -type:code")
        self.assertEqual(
            q.groups, ("repositories", "people", "commits", "issues"))
        q = parse_global_query("forge")
        self.assertEqual(q.groups, GROUP_ORDER)

    def test_parse_quoted_phrase_is_one_term(self):
        q = parse_global_query('"anvil frame" type:commits')
        self.assertEqual(q.terms, ("anvil frame",))
        self.assertEqual(q.groups, ("commits",))

    def test_parse_empty_shapes(self):
        self.assertTrue(parse_global_query("").is_empty)
        self.assertTrue(parse_global_query(None).is_empty)
        self.assertTrue(parse_global_query("   ").is_empty)

    def test_parse_unknown_qualifier_refused_by_name(self):
        for bad, name in (("forge author:thor", "author"),
                          ("forge label:bug", "label"),
                          ("forge path:src", "path"),
                          ("forge sort:newest", "sort")):
            with self.assertRaises(GlobalSearchError) as ctx:
                parse_global_query(bad)
            self.assertEqual(ctx.exception.reason, "query_invalid", bad)
            self.assertIn(name, str(ctx.exception), bad)

    def test_parse_bad_type_values_refused(self):
        for bad in ("forge type:", "forge type:wiki",
                    "forge type:repositoryy", "-forge",
                    '"unterminated'):
            with self.assertRaises(GlobalSearchError) as ctx:
                parse_global_query(bad)
            self.assertEqual(ctx.exception.reason, "query_invalid", bad)

    def test_parse_overlong_control_and_nonstr_refused(self):
        for bad in ("x" * 501, "a\x01b", 42):
            with self.assertRaises(GlobalSearchError) as ctx:
                parse_global_query(bad)
            self.assertEqual(ctx.exception.reason, "query_invalid")

    def test_focus_order_is_box_then_groups(self):
        self.assertEqual(
            keyboard_focus_order(),
            ("search-box", "group-repositories", "group-people",
             "group-commits", "group-code", "group-issues"))
        self.assertEqual(
            keyboard_focus_order(("code",), has_recents=True),
            ("search-box", "recent-searches", "group-code"))


class GlobalSearchTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.a = make_world(Path(self._td.name), with_secret=True)
        self.addCleanup(self.a.conn.close)

    def test_pins_schema_92_taxonomy_127(self):
        self.assertEqual(schema_version(self.a.conn), 92)
        self.assertEqual(db.MIGRATIONS[-1][0], 92)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 127)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 31)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 83)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    def test_one_query_searches_every_group_in_order(self):
        results = self.a.search.search(self.a.owner, "forge")
        self.assertEqual(results.kinds, GROUP_ORDER)
        for kind in GROUP_ORDER:
            self.assertGreater(
                results.group(kind).total, 0, kind)

    def test_group_hits_are_the_backends_own(self):
        w = self.a
        results = w.search.search(w.owner, "forge")
        repos = results.group("repositories")
        self.assertEqual([h.full_name for h in repos.hits],
                         ["volmarr/anvil"])
        people = results.group("people")
        self.assertEqual(
            sorted((h.kind, h.handle) for h in people.hits),
            [("org", "ForgeGuild"), ("user", "volmarr")])
        commits = results.group("commits")
        self.assertEqual(
            sorted(h.subject for h in commits.hits),
            ["Forge the anvil frame", "Forge the bellows"])
        code = results.group("code")
        self.assertEqual(code.total, 2)
        self.assertEqual(
            sorted(h.path for h in code.hits), ["lib.py", "main.py"])
        issues = results.group("issues")
        self.assertEqual(issues.total, 2)

    def test_type_qualifier_narrows_groups(self):
        results = self.a.search.search(
            self.a.owner, "forge type:code")
        self.assertEqual(results.kinds, ("code",))
        results = self.a.search.search(
            self.a.owner, "forge -type:code -type:commits")
        self.assertEqual(
            results.kinds, ("repositories", "people", "issues"))

    def test_explicit_types_replace_text_selection(self):
        results = self.a.search.search(
            self.a.owner, "forge type:code", types=("people",))
        self.assertEqual(results.kinds, ("people",))
        with self.assertRaises(GlobalSearchError) as ctx:
            self.a.search.search(
                self.a.owner, "forge", types=("wiki",))
        self.assertEqual(ctx.exception.reason, "query_invalid")
        with self.assertRaises(GlobalSearchError) as ctx:
            self.a.search.search(self.a.owner, "forge", types=())
        self.assertEqual(ctx.exception.reason, "query_invalid")

    def test_selection_naming_no_group_refused(self):
        with self.assertRaises(GlobalSearchError) as ctx:
            self.a.search.search(
                self.a.owner, "forge type:code -type:code")
        self.assertEqual(ctx.exception.reason, "query_invalid")

    def test_empty_query_is_the_landing(self):
        results = self.a.search.search(self.a.owner, "")
        self.assertEqual(results.groups, ())
        self.assertEqual(results.query, "")
        results = self.a.search.search(self.a.owner, "   ")
        self.assertEqual(results.groups, ())

    def test_type_only_query_refused(self):
        with self.assertRaises(GlobalSearchError) as ctx:
            self.a.search.search(self.a.owner, "type:code")
        self.assertEqual(ctx.exception.reason, "query_invalid")
        self.assertIn("words", str(ctx.exception))

    def test_per_group_limit_caps_hits_not_total(self):
        results = self.a.search.search(
            self.a.owner, "forge", per_group_limit=1)
        commits = results.group("commits")
        self.assertEqual(len(commits.hits), 1)
        self.assertEqual(commits.total, 2)
        for bad in (0, 101, "5", True):
            with self.assertRaises(GlobalSearchError) as ctx:
                self.a.search.search(
                    self.a.owner, "forge", per_group_limit=bad)
            self.assertEqual(ctx.exception.reason, "query_invalid")

    def test_phrase_search_reaches_groups_as_phrase(self):
        results = self.a.search.search(
            self.a.owner, '"anvil frame" type:commits')
        self.assertEqual(
            [h.subject for h in results.group("commits").hits],
            ["Forge the anvil frame"])


class LeakageTests(unittest.TestCase):
    def setUp(self):
        self._tds = [tempfile.TemporaryDirectory(),
                     tempfile.TemporaryDirectory()]
        for td in self._tds:
            self.addCleanup(td.cleanup)
        self.a = make_world(Path(self._tds[0].name), with_secret=True)
        self.b = make_world(Path(self._tds[1].name), with_secret=False)
        self.addCleanup(self.a.conn.close)
        self.addCleanup(self.b.conn.close)

    def test_secret_word_invisible_to_stranger_everywhere(self):
        for viewer_world in ((self.a.stranger, self.a), (None, self.a)):
            viewer, world = viewer_world
            results = world.search.search(viewer, "zorblax")
            self.assertEqual(results.kinds, GROUP_ORDER)
            for group in results.groups:
                self.assertEqual(group.hits, (), group.kind)
                self.assertEqual(group.total, 0, group.kind)
                self.assertEqual(group.total_matches, 0, group.kind)

    def test_stranger_equivalence_with_and_without_secret(self):
        for query in ("zorblax", "forge"):
            left = signature(
                self.a.search.search(self.a.stranger, query))
            right = signature(
                self.b.search.search(self.b.stranger, query))
            self.assertEqual(left, right, query)

    def test_owner_finds_the_secret_in_its_groups(self):
        results = self.a.search.search(self.a.owner, "zorblax")
        self.assertEqual(
            [h.full_name for h in results.group("repositories").hits],
            ["volmarr/vault"])
        self.assertEqual(
            [h.subject for h in results.group("commits").hits],
            ["zorblax secret plans"])
        self.assertEqual(
            [h.path for h in results.group("code").hits],
            ["secret.py"])
        self.assertEqual(
            [h.title for h in results.group("issues").hits],
            ["Zorblax master plan"])
        self.assertEqual(results.group("people").total, 0)

    def test_page_never_renders_the_secret_to_a_stranger(self):
        results = self.a.search.search(self.a.stranger, "zorblax")
        page = render_global_search_page("zorblax", results)
        self.assertNotIn("vault", page)
        self.assertNotIn("Zorblax Keeper", page)
        self.assertNotIn("master plan", page)


class RecentSearchTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.a = make_world(Path(self._td.name), with_secret=True)
        self.addCleanup(self.a.conn.close)

    def queries(self, user):
        return [r.query for r in self.a.recents.list_recent(user)]

    def test_record_and_list_most_recent_first(self):
        store, owner = self.a.recents, self.a.owner
        store.record(owner, "forge")
        store.record(owner, "anvil")
        store.record(owner, "bellows")
        self.assertEqual(self.queries(owner),
                         ["bellows", "anvil", "forge"])

    def test_rerecord_moves_to_front_with_latest_case(self):
        store, owner = self.a.recents, self.a.owner
        store.record(owner, "forge")
        store.record(owner, "anvil")
        saved = store.record(owner, "FORGE")
        self.assertEqual(saved.query, "FORGE")
        self.assertEqual(self.queries(owner), ["FORGE", "anvil"])

    def test_cap_prunes_oldest(self):
        store, owner = self.a.recents, self.a.owner
        for i in range(12):
            store.record(owner, f"query-{i}")
        listed = self.queries(owner)
        self.assertEqual(len(listed), 10)
        self.assertEqual(listed[0], "query-11")
        self.assertNotIn("query-0", listed)
        self.assertNotIn("query-1", listed)

    def test_recents_are_per_user(self):
        store = self.a.recents
        store.record(self.a.owner, "forge")
        store.record(self.a.stranger, "anvil")
        self.assertEqual(self.queries(self.a.owner), ["forge"])
        self.assertEqual(self.queries(self.a.stranger), ["anvil"])
        store.clear(self.a.owner)
        self.assertEqual(self.queries(self.a.owner), [])
        self.assertEqual(self.queries(self.a.stranger), ["anvil"])

    def test_remove_one_and_missing_refused(self):
        store, owner = self.a.recents, self.a.owner
        store.record(owner, "forge")
        store.record(owner, "anvil")
        store.remove(owner, "FORGE")
        self.assertEqual(self.queries(owner), ["anvil"])
        with self.assertRaises(GlobalSearchError) as ctx:
            store.remove(owner, "forge")
        self.assertEqual(ctx.exception.reason, "recent_not_found")
        # Another user's identical text is a different row.
        with self.assertRaises(GlobalSearchError) as ctx:
            store.remove(self.a.stranger, "anvil")
        self.assertEqual(ctx.exception.reason, "recent_not_found")

    def test_store_refusals(self):
        store, owner = self.a.recents, self.a.owner
        with self.assertRaises(GlobalSearchError) as ctx:
            store.record(None, "forge")
        self.assertEqual(ctx.exception.reason, "auth_required")
        with self.assertRaises(GlobalSearchError) as ctx:
            store.list_recent(None)
        self.assertEqual(ctx.exception.reason, "auth_required")
        for bad in ("", "   ", "x" * 501, "a\x01b", 42):
            with self.assertRaises(GlobalSearchError) as ctx:
                store.record(owner, bad)
            self.assertEqual(ctx.exception.reason, "query_invalid", bad)
        with self.assertRaises(GlobalSearchError) as ctx:
            store.list_recent(owner, limit=0)
        self.assertEqual(ctx.exception.reason, "query_invalid")

    def test_search_records_for_signed_in_only(self):
        w = self.a
        w.search.search(w.owner, "forge")
        w.search.search(w.owner, "Forge type:code")
        self.assertEqual(self.queries(w.owner),
                         ["Forge type:code", "forge"])
        w.search.search(None, "forge")
        w.search.search(w.stranger, "anvil")
        self.assertEqual(self.queries(w.stranger), ["anvil"])
        rows = w.conn.execute(
            "SELECT COUNT(*) AS n FROM recent_searches").fetchone()
        self.assertEqual(rows["n"], 3)

    def test_empty_and_invalid_searches_record_nothing(self):
        w = self.a
        w.search.search(w.owner, "")
        with self.assertRaises(GlobalSearchError):
            w.search.search(w.owner, "forge author:thor")
        with self.assertRaises(GlobalSearchError):
            w.search.search(w.owner, "type:code")
        self.assertEqual(self.queries(w.owner), [])


class RenderTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.a = make_world(Path(self._td.name), with_secret=True)
        self.addCleanup(self.a.conn.close)

    def test_page_has_one_box_and_groups_in_order(self):
        results = self.a.search.search(self.a.owner, "forge")
        page = render_global_search_page("forge", results)
        self.assertEqual(page.count("<form"), 1)
        self.assertEqual(page.count('type="search"'), 1)
        self.assertIn('id="q"', page)
        self.assertIn("autofocus", page)
        positions = [page.index(f'id="group-{kind}"')
                     for kind in GROUP_ORDER]
        self.assertEqual(positions, sorted(positions))
        links = [page.index(f'href="#group-{kind}"')
                 for kind in GROUP_ORDER]
        self.assertEqual(links, sorted(links))
        self.assertLess(max(links), min(positions))

    def test_keyboard_section_renders_the_registry(self):
        page = render_global_search_page("forge", None)
        self.assertIn("<kbd>/</kbd>", page)
        self.assertIn("<kbd>Escape</kbd>", page)
        self.assertIn("<kbd>?</kbd>", page)
        self.assertIn("keyboard-first", page)
        self.assertIn("the search box", page)
        self.assertNotIn("<script", page)

    def test_box_is_the_one_box(self):
        box = render_global_search_box("forge")
        self.assertEqual(box.count("<form"), 1)
        self.assertIn('action="/search"', box)
        self.assertIn('value="forge"', box)
        self.assertIn("<kbd>/</kbd>", box)

    def test_page_escapes_query_and_hit_markup(self):
        results = self.a.search.search(self.a.owner, "forge")
        page = render_global_search_page(
            '"><script>alert(1)</script>', results)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&quot;&gt;&lt;script&gt;", page)
        self.assertIn("Forge &lt;b&gt;markup&lt;/b&gt; check", page)
        self.assertNotIn("Forge <b>markup</b> check", page)

    def test_recents_render_as_escaped_rerun_links(self):
        store, owner = self.a.recents, self.a.owner
        store.record(owner, "forge")
        store.record(owner, 'a <b> query')
        html = render_recent_searches(store.list_recent(owner))
        self.assertIn('href="/search?q=a+%3Cb%3E+query"', html)
        self.assertIn("a &lt;b&gt; query", html)
        self.assertNotIn("a <b> query", html)
        self.assertLess(html.index("a &lt;b&gt; query"),
                        html.index("forge"))
        self.assertIn("No recent searches yet",
                      render_recent_searches([]))

    def test_landing_page_claims_no_results(self):
        page = render_global_search_page("", None, recents=[])
        self.assertIn("Recent searches", page)
        self.assertNotIn('class="search-group"', page)
        results = self.a.search.search(self.a.owner, "forge")
        recents = self.a.recents.list_recent(self.a.owner)
        page = render_global_search_page("forge", results, recents)
        self.assertIn('href="/search?q=forge"', page)


if __name__ == "__main__":
    unittest.main()
