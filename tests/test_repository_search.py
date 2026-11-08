"""S-210 acceptance battery: repository search.

Acceptance (roadmap S-210): Repository search —
by name, description, topics, owner; the instance
directory page.

The planted secret is deliberate bait, in the
S-209 shape: a private repository (`vault`) whose
name-adjacent token, description, and topic all
carry the unique word `zorblax`, so any post-hoc
filtering — hits removed after counting, topics
read before filtering — moves a string or a
number this battery watches. The centre is the
equivalence proof: a stranger's hits and counts
over a world WITH the private repository equal,
exactly, the same search over a world where it
was never created.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import itertools, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.db import schema_version
from samverk.repo_settings import RepoSettingsService
from samverk.repositories import RepositoryStore
from samverk.repository_search import (
    RepositorySearch, RepositorySearchError, matched_fields,
    parse_repository_query, render_directory_page,
    render_repository_search_page, repo_matches_query)


def make_world(root: Path, with_secret: bool) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    accounts = AccountStore(conn)
    owner = accounts.register("volmarr", "correct horse battery")
    other = accounts.register("sigrun", "correct horse battery")
    stranger = accounts.register("mallory", "correct horse battery")
    admin = accounts.register("admina", "correct horse battery")
    conn.execute(
        "UPDATE users SET is_admin = 1 WHERE username_lower = 'admina'")
    conn.commit()
    admin = accounts.get_by_id(admin.id)
    clock = itertools.count(1010, 10)
    repos = RepositoryStore(
        conn, root, accounts, time_fn=lambda: float(next(clock)))
    settings = RepoSettingsService(conn, root, accounts, repos)
    w = SimpleNamespace(
        conn=conn, accounts=accounts, owner=owner, other=other,
        stranger=stranger, admin=admin, repos=repos, settings=settings,
        search=RepositorySearch(conn, repos))

    def add(actor, owner_name, name, description, visibility, topics):
        repos.create_repository(
            actor.id, owner_name, name,
            description=description, visibility=visibility)
        if topics:
            settings.update_settings(
                actor.id, owner_name, name, topics=list(topics))

    add(owner, "volmarr", "anvil",
        "A sturdy build forge for hammers", "public", ("build", "ci"))
    add(owner, "volmarr", "quill-notes",
        "Notes on quill pens and ink", "public", ("writing", "quill"))
    if with_secret:
        add(owner, "volmarr", "vault",
            "zorblax secret plans", "private", ("zorblax",))
    add(other, "sigrun", "anvil-rest",
        "REST client for the forge services", "public", ("api", "build"))
    add(other, "sigrun", "loom",
        "Weaving patterns for the hall", "internal", ("weaving",))
    add(owner, "volmarr", "attic",
        "Old maps and charts", "private", ("maps",))
    return w


def names(hits):
    return [h.full_name for h in hits]


class PureLawTests(unittest.TestCase):
    def test_parse_terms_and_qualifiers(self):
        q = parse_repository_query(
            "hammer owner:Volmarr topic:build visibility:public")
        self.assertEqual(q.terms, ("hammer",))
        self.assertEqual(q.owners, ("volmarr",))
        self.assertEqual(q.topics, ("build",))
        self.assertEqual(q.visibilities, ("public",))
        self.assertEqual(q.sort, "name-asc")
        self.assertFalse(q.is_empty)

    def test_parse_quoted_phrase_is_one_term(self):
        q = parse_repository_query('"quill pens" topic:quill')
        self.assertEqual(q.terms, ("quill pens",))
        self.assertEqual(q.topics, ("quill",))

    def test_parse_negation_and_is_alias_and_sort(self):
        q = parse_repository_query("-topic:build is:private sort:created-desc")
        self.assertEqual(q.not_topics, ("build",))
        self.assertEqual(q.visibilities, ("private",))
        self.assertEqual(q.sort, "created-desc")

    def test_parse_empty_is_the_directory_query(self):
        self.assertTrue(parse_repository_query("").is_empty)
        self.assertTrue(parse_repository_query(None).is_empty)

    def test_parse_unknown_qualifier_refused_by_name(self):
        with self.assertRaises(RepositorySearchError) as ctx:
            parse_repository_query("hello language:python")
        self.assertEqual(ctx.exception.reason, "query_invalid")
        self.assertIn("language", str(ctx.exception))

    def test_parse_bad_values_refused(self):
        for bad in ("visibility:purple", "sort:size", "owner:",
                    "topic:", '"unterminated', "-sort:name-asc",
                    "sort:name-asc sort:name-desc"):
            with self.assertRaises(RepositorySearchError) as ctx:
                parse_repository_query(bad)
            self.assertEqual(ctx.exception.reason, "query_invalid", bad)

    def test_parse_overlong_and_control_refused(self):
        for bad in ("x" * 501, "a\x01b"):
            with self.assertRaises(RepositorySearchError) as ctx:
                parse_repository_query(bad)
            self.assertEqual(ctx.exception.reason, "query_invalid")

    def test_matches_and_fields_pure(self):
        repo = SimpleNamespace(
            name_lower="anvil", owner_lower="volmarr",
            description="A sturdy build forge", visibility="public")
        hit = parse_repository_query("build")
        self.assertTrue(repo_matches_query(repo, ("build", "ci"), hit))
        self.assertEqual(
            matched_fields(repo, ("build", "ci"), hit),
            ("description", "topics"))
        self.assertTrue(repo_matches_query(
            repo, ("build", "ci"), parse_repository_query("volmarr")))
        self.assertFalse(repo_matches_query(
            repo, ("build", "ci"), parse_repository_query("sigrun")))
        self.assertFalse(repo_matches_query(
            repo, ("build", "ci"),
            parse_repository_query("topic:build topic:api")))
        self.assertFalse(repo_matches_query(
            repo, ("build", "ci"), parse_repository_query("-topic:ci")))
        self.assertFalse(repo_matches_query(
            repo, ("build", "ci"),
            parse_repository_query("visibility:public visibility:private")))


class RepositorySearchTests(unittest.TestCase):
    def setUp(self):
        self._tds = [tempfile.TemporaryDirectory(),
                     tempfile.TemporaryDirectory()]
        for td in self._tds:
            self.addCleanup(td.cleanup)
        self.a = make_world(Path(self._tds[0].name), with_secret=True)
        self.b = make_world(Path(self._tds[1].name), with_secret=False)
        self.addCleanup(self.a.conn.close)
        self.addCleanup(self.b.conn.close)

    # -- pins -------------------------------------------------
    def test_pins_schema_86_taxonomy_127(self):
        self.assertEqual(schema_version(self.a.conn), 86)
        self.assertEqual(db.MIGRATIONS[-1][0], 86)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 127)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 31)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 83)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    # -- the four fields ---------------------------------------
    def test_search_by_name(self):
        hits = self.a.search.search(self.a.owner, "anvil")
        self.assertEqual(names(hits), ["sigrun/anvil-rest", "volmarr/anvil"])
        self.assertEqual(hits[1].matched_fields, ("name",))

    def test_search_by_description(self):
        hits = self.a.search.search(self.a.owner, "hammers")
        self.assertEqual(names(hits), ["volmarr/anvil"])
        self.assertEqual(hits[0].matched_fields, ("description",))
        hits = self.a.search.search(self.a.owner, '"quill pens"')
        self.assertEqual(names(hits), ["volmarr/quill-notes"])

    def test_search_by_topics(self):
        hits = self.a.search.search(self.a.owner, "build")
        self.assertEqual(names(hits), ["sigrun/anvil-rest", "volmarr/anvil"])
        hits = self.a.search.search(self.a.owner, "topic:build")
        self.assertEqual(names(hits), ["sigrun/anvil-rest", "volmarr/anvil"])
        hits = self.a.search.search(self.a.owner, "topic:build topic:ci")
        self.assertEqual(names(hits), ["volmarr/anvil"])
        hit = self.a.search.search(self.a.owner, "quill")[0]
        self.assertEqual(hit.topics, ("writing", "quill"))
        self.assertEqual(
            hit.matched_fields, ("name", "description", "topics"))

    def test_search_by_owner(self):
        hits = self.a.search.search(self.a.other, "sigrun")
        self.assertEqual(names(hits), ["sigrun/anvil-rest", "sigrun/loom"])
        for hit in hits:
            self.assertEqual(hit.matched_fields, ("owner",))
        hits = self.a.search.search(self.a.owner, "owner:sigrun")
        self.assertEqual(names(hits), ["sigrun/anvil-rest"])

    def test_terms_compose_by_and_across_fields(self):
        hits = self.a.search.search(self.a.owner, "anvil build")
        self.assertEqual(names(hits), ["sigrun/anvil-rest", "volmarr/anvil"])
        hits = self.a.search.search(self.a.owner, "anvil quill")
        self.assertEqual(hits, [])

    def test_unknown_owner_or_topic_matches_nothing_not_error(self):
        self.assertEqual(self.a.search.search(self.a.owner, "owner:ghost"), [])
        self.assertEqual(self.a.search.search(self.a.owner, "topic:nope"), [])

    # -- qualifiers, sorts, keywords ----------------------------
    def test_visibility_qualifier_never_widens(self):
        hits = self.a.search.search(self.a.owner, "visibility:private")
        self.assertEqual(names(hits), ["volmarr/attic", "volmarr/vault"])
        self.assertEqual(
            self.a.search.search(self.a.stranger, "visibility:private"), [])
        hits = self.a.search.search(self.a.owner, "-visibility:public")
        self.assertEqual(names(hits), ["volmarr/attic", "volmarr/vault"])

    def test_negated_topic_qualifier(self):
        hits = self.a.search.search(self.a.owner, "-topic:build")
        self.assertEqual(
            names(hits),
            ["volmarr/attic", "volmarr/quill-notes", "volmarr/vault"])

    def test_sorts(self):
        w = self.a
        self.assertEqual(
            names(w.search.search(w.admin, "", sort="created-asc")),
            ["volmarr/anvil", "volmarr/quill-notes", "volmarr/vault",
             "sigrun/anvil-rest", "sigrun/loom", "volmarr/attic"])
        self.assertEqual(
            names(w.search.search(w.admin, "sort:created-desc")),
            ["volmarr/attic", "sigrun/loom", "sigrun/anvil-rest",
             "volmarr/vault", "volmarr/quill-notes", "volmarr/anvil"])
        self.assertEqual(
            names(w.search.search(w.admin, "", sort="name-desc")),
            ["volmarr/vault", "volmarr/quill-notes", "volmarr/attic",
             "volmarr/anvil", "sigrun/loom", "sigrun/anvil-rest"])

    def test_explicit_keywords_and_with_text(self):
        w = self.a
        self.assertEqual(
            names(w.search.search(w.owner, "", topic="build")),
            ["sigrun/anvil-rest", "volmarr/anvil"])
        self.assertEqual(
            names(w.search.search(w.owner, "anvil", owner="volmarr")),
            ["volmarr/anvil"])
        self.assertEqual(
            names(w.search.search(w.owner, "", visibility="public")),
            ["sigrun/anvil-rest", "volmarr/anvil", "volmarr/quill-notes"])
        self.assertEqual(
            names(w.search.search(
                w.owner, "sort:name-asc", sort="created-desc")),
            ["volmarr/attic", "sigrun/anvil-rest", "volmarr/vault",
             "volmarr/quill-notes", "volmarr/anvil"])

    def test_bad_limit_and_bad_keyword_refused(self):
        for kwargs in ({"limit": 0}, {"limit": 501},
                       {"visibility": "purple"}, {"sort": "size"}):
            with self.assertRaises(RepositorySearchError) as ctx:
                self.a.search.search(self.a.owner, "", **kwargs)
            self.assertEqual(ctx.exception.reason, "query_invalid")

    # -- counts --------------------------------------------------
    def test_limit_caps_display_never_the_visible_count(self):
        res = self.a.search.search_counted(self.a.owner, "", limit=2)
        self.assertEqual(len(res.hits), 2)
        self.assertEqual(res.total, 5)
        res = self.a.search.search_counted(self.a.stranger, "", limit=2)
        self.assertEqual(len(res.hits), 2)
        self.assertEqual(res.total, 3)

    def test_counted_faces_agree(self):
        w = self.a
        plain = w.search.search(w.owner, "build")
        counted = w.search.search_counted(w.owner, "build")
        self.assertEqual(list(counted.hits), plain)
        self.assertEqual(counted.total, 2)
        self.assertEqual(w.search.count(w.owner, "build"), 2)
        self.assertEqual(w.search.count(w.stranger, "zorblax"), 0)

    # -- the directory --------------------------------------------
    def test_directory_lists_exactly_what_each_viewer_reads(self):
        w = self.a
        public_three = ["sigrun/anvil-rest", "volmarr/anvil",
                        "volmarr/quill-notes"]
        self.assertEqual(names(w.search.directory(None)), public_three)
        self.assertEqual(names(w.search.directory(w.stranger)), public_three)
        self.assertEqual(
            names(w.search.directory(w.owner)),
            ["sigrun/anvil-rest", "volmarr/anvil", "volmarr/attic",
             "volmarr/quill-notes", "volmarr/vault"])
        self.assertEqual(
            names(w.search.directory(w.other)),
            ["sigrun/anvil-rest", "sigrun/loom", "volmarr/anvil",
             "volmarr/quill-notes"])
        self.assertEqual(w.search.directory_counted(w.stranger).total, 3)
        self.assertEqual(w.search.directory_counted(w.admin).total, 6)

    def test_internal_repo_follows_the_s054_gate(self):
        w = self.a
        self.assertEqual(names(w.search.search(w.other, "loom")),
                         ["sigrun/loom"])
        self.assertEqual(w.search.search(w.owner, "loom"), [])
        self.assertEqual(w.search.search(w.stranger, "weaving"), [])
        self.assertEqual(names(w.search.search(w.admin, "loom")),
                         ["sigrun/loom"])

    # -- leakage (S-209 law) ---------------------------------------
    def test_secret_invisible_to_stranger_and_anon(self):
        for viewer in (self.a.stranger, None):
            for query in ("zorblax", "secret", "vault"):
                self.assertEqual(self.a.search.search(viewer, query), [])
                self.assertEqual(self.a.search.count(viewer, query), 0)

    def test_equivalence_with_and_without_secret_repo(self):
        for query in ("", "zorblax", "quill", "secret", "maps", "anvil"):
            for viewer_a, viewer_b in (
                    (self.a.stranger, self.b.stranger), (None, None)):
                ha = self.a.search.search_counted(viewer_a, query)
                hb = self.b.search.search_counted(viewer_b, query)
                self.assertEqual(names(ha.hits), names(hb.hits), query)
                self.assertEqual(ha.total, hb.total, query)
        owner = self.a.search.search_counted(self.a.owner, "zorblax")
        self.assertEqual((names(owner.hits), owner.total),
                         (["volmarr/vault"], 1))

    def test_rendered_pages_carry_no_secret(self):
        w = self.a
        page = render_repository_search_page(
            "quill", w.search.search(w.stranger, "quill"),
            total=w.search.count(w.stranger, "quill"))
        self.assertNotIn("zorblax", page)
        self.assertNotIn("vault", page)
        directory = render_directory_page(
            w.search.directory(w.stranger),
            total=w.search.directory_counted(w.stranger).total)
        self.assertNotIn("zorblax", directory)
        self.assertNotIn("vault", directory)
        self.assertNotIn("attic", directory)
        self.assertIn("3 repositories shown.", directory)
        owner_page = render_repository_search_page(
            "zorblax", w.search.search(w.owner, "zorblax"))
        self.assertIn("volmarr/vault", owner_page)
        self.assertIn("zorblax", owner_page)

    # -- rendering and escaping --------------------------------------
    def test_pages_say_the_facts_in_words(self):
        w = self.a
        page = render_repository_search_page(
            "build", w.search.search(w.owner, "build"), total=2)
        self.assertIn("volmarr/anvil", page)
        self.assertIn("Public", page)
        self.assertIn("Topics: build, ci", page)
        self.assertIn("2 repositories match", page)
        empty = render_repository_search_page(
            "zzzz", w.search.search(w.owner, "zzzz"), total=0)
        self.assertIn("No repositories match.", empty)

    def test_stored_markup_renders_as_text(self):
        w = self.a
        w.repos.create_repository(
            w.owner.id, "volmarr", "evil",
            description="<script>alert(1)</script>", visibility="public")
        hits = w.search.search(w.stranger, "alert")
        self.assertEqual(names(hits), ["volmarr/evil"])
        for page in (render_repository_search_page("alert", hits),
                     render_directory_page(w.search.directory(w.stranger))):
            self.assertNotIn("<script>alert(1)</script>", page)
            self.assertIn("&lt;script&gt;", page)

    # -- searching writes nothing --------------------------------------
    def test_searches_write_nothing(self):
        w = self.a
        before = (
            w.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"],
            w.conn.execute("SELECT COUNT(*) c FROM repositories").fetchone()["c"],
            w.conn.execute("SELECT COUNT(*) c FROM repo_settings").fetchone()["c"])
        w.search.search_counted(w.owner, "build")
        w.search.directory(w.stranger)
        w.search.count(None, "zorblax")
        after = (
            w.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"],
            w.conn.execute("SELECT COUNT(*) c FROM repositories").fetchone()["c"],
            w.conn.execute("SELECT COUNT(*) c FROM repo_settings").fetchone()["c"])
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
