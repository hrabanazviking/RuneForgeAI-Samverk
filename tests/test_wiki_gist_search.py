"""S-287 acceptance battery: wiki/gist search.

Acceptance (roadmap S-287): Wiki/gist search —
wikipages and gists join Part X's index under the
same permission filtering.

The planted secrets are deliberate bait, in the
S-209 battery's shape: a private repository whose
wiki page carries the unique token `zorblax` plus
extra `quill` matches, and a secret gist carrying
the same tokens in its description and a file — so
any post-hoc filtering (hits removed after
counting, content read before the visibility
judgement) moves a number or a string this battery
watches. The centre is the equivalence proof, per
kind: a stranger's hits and counts over a world
WITH the planted secrets equal, exactly, the same
search over a world where they were never created.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.gists import GistStore
from samverk.global_search import GlobalSearch
from samverk.organizations import OrganizationStore
from samverk.repositories import RepositoryStore
from samverk.search_api import hit_to_dict
from samverk.taxonomy import ADMIN_EVENTS, AUDIT_EVENTS, AUTH_EVENTS, REPO_EVENTS
from samverk.wiki_gist_search import (
    WikiGistSearch, WikiGistSearchError, build_term_snippets,
    gist_matches, parse_wiki_gist_query, render_wiki_gist_search_page,
    wiki_page_matches)
from samverk.wiki_storage import WikiStore

PW = "correct horse battery"


def make_world(root: Path, with_secret: bool) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    accounts = AccountStore(conn)
    orgs = OrganizationStore(conn, accounts)
    owner = accounts.register("volmarr", PW)
    other = accounts.register("yrsa", PW)
    stranger = accounts.register("mallory", PW)
    boss = accounts.register("odin", PW)
    conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (boss.id,))
    conn.commit()
    admin = accounts.get_by_id(boss.id)
    repos = RepositoryStore(conn, root, accounts)
    audit = AuditLog(conn)
    wiki = WikiStore(conn, repos, audit=audit)
    gists = GistStore(conn, root, accounts, audit=audit)
    w = SimpleNamespace(
        conn=conn, accounts=accounts, orgs=orgs, owner=owner,
        other=other, stranger=stranger, admin=admin, repos=repos,
        wiki=wiki, gists=gists,
        search=WikiGistSearch(conn, repos, wiki=wiki, gists=gists),
        global_search=GlobalSearch(conn, repos, orgs))
    repos.create_repository(owner.id, "volmarr", "anvil",
                            visibility="public")
    wiki.write_page(owner, "volmarr", "anvil", "Home",
                    "# Home\n\nThe quill rests here.\n")
    wiki.write_page(owner, "volmarr", "anvil", "Forging",
                    "Hammer work.\nSecond quill line.\n")
    gists.create_gist(owner, "quill scratchpad",
                      {"notes.md": "quill notes\nplain\n",
                       "run.py": "print('hi')\n"})
    gists.create_gist(other, "weaver patterns",
                      {"weave.md": "loom and quill\n"})
    if with_secret:
        repos.create_repository(owner.id, "volmarr", "vault",
                                visibility="private")
        wiki.write_page(owner, "volmarr", "vault", "Secrets",
                        "zorblax quill hoard\nmore quill\n")
        gists.create_gist(owner, "zorblax quill diary",
                          {"diary.md": "zorblax quill entry\n"},
                          visibility="secret")
    return w


class ParseTests(unittest.TestCase):
    def test_terms_phrase_and_case(self):
        q = parse_wiki_gist_query('Quill "rests here"')
        self.assertEqual(q.terms, ("quill", "rests here"))
        self.assertEqual(q.kinds, ("wiki", "gists"))
        self.assertFalse(q.is_empty)

    def test_type_qualifiers_and_aliases(self):
        self.assertEqual(
            parse_wiki_gist_query("quill type:wiki").kinds, ("wiki",))
        self.assertEqual(
            parse_wiki_gist_query("quill type:gist").kinds, ("gists",))
        self.assertEqual(
            parse_wiki_gist_query("quill -type:gists").kinds, ("wiki",))
        self.assertEqual(
            parse_wiki_gist_query("quill type:wikis").kinds, ("wiki",))

    def test_refusals(self):
        for bad in ("quill repo:volmarr/anvil", "quill type:code",
                    'quill "unterminated', "quill -plain", "type:"):
            with self.assertRaises(WikiGistSearchError) as ctx:
                parse_wiki_gist_query(bad)
            self.assertEqual(ctx.exception.reason, "query_invalid", bad)
        with self.assertRaises(WikiGistSearchError) as ctx:
            parse_wiki_gist_query("quill repo:volmarr/anvil")
        self.assertIn("repo", str(ctx.exception))

    def test_control_and_overlong_refused(self):
        for bad in ("quill\x01", "x" * 501, 42):
            with self.assertRaises(WikiGistSearchError) as ctx:
                parse_wiki_gist_query(bad)
            self.assertEqual(ctx.exception.reason, "query_invalid")


class MatchingTests(unittest.TestCase):
    def test_wiki_page_matches_fields(self):
        q = parse_wiki_gist_query("quill")
        self.assertEqual(
            wiki_page_matches("Quill", "plain body", q), ("title",))
        self.assertEqual(
            wiki_page_matches("Home", "the quill rests", q),
            ("content",))
        self.assertEqual(
            wiki_page_matches("Quill", "quill body", q),
            ("title", "content"))
        self.assertIsNone(wiki_page_matches("Home", "plain", q))

    def test_wiki_and_across_terms(self):
        q = parse_wiki_gist_query("quill hammer")
        self.assertIsNone(
            wiki_page_matches("Home", "quill only", q))
        self.assertEqual(
            wiki_page_matches("Hammer", "quill body", q),
            ("title", "content"))

    def test_gist_matches_fields_and_files(self):
        q = parse_wiki_gist_query("quill")
        matched, files = gist_matches(
            "scratchpad", (("notes.md", "quill notes"),
                            ("run.py", "print(1)")), q)
        self.assertEqual(matched, ("content",))
        self.assertEqual(files, ("notes.md",))
        matched, files = gist_matches(
            "quill pad", (("notes.md", "plain"),), q)
        self.assertEqual(matched, ("description",))
        self.assertEqual(files, ())
        matched, files = gist_matches(
            "pad", (("quill.md", "plain"),), q)
        self.assertEqual(matched, ("filename",))
        self.assertEqual(files, ("quill.md",))
        self.assertIsNone(gist_matches("pad", (("a.md", "b"),), q))

    def test_snippets_counts_and_spans(self):
        snippets, lines = build_term_snippets(
            "one\nquill two quill\nthree\nfour quill\n", ("quill",))
        self.assertEqual(lines, 2)
        self.assertEqual(len(snippets), 1)
        first = snippets[0]
        self.assertEqual(first.start_line, 1)
        self.assertEqual(first.match_numbers, (2, 4))
        self.assertEqual(
            first.lines[1].spans, ((0, 5), (10, 15)))
        empty, zero = build_term_snippets("plain\n", ("quill",))
        self.assertEqual((empty, zero), ((), 0))


class WikiSearchTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name), with_secret=True)
        self.addCleanup(self.w.conn.close)

    def test_finds_page_by_content_with_snippet(self):
        found = self.w.search.search_wiki_counted(self.w.stranger, "rests")
        self.assertEqual(found.total, 1)
        hit = found.hits[0]
        self.assertEqual(hit.full_name, "volmarr/anvil")
        self.assertEqual(hit.page_name, "Home")
        self.assertEqual(hit.matched_fields, ("content",))
        self.assertEqual(hit.matched_lines, 1)
        self.assertTrue(hit.snippets)
        self.assertIn("quill rests", hit.snippets[0].lines[1].text.lower())

    def test_finds_page_by_title(self):
        found = self.w.search.search_wiki_counted(None, "forging")
        self.assertEqual(found.total, 1)
        self.assertEqual(found.hits[0].matched_fields, ("title",))

    def test_anonymous_reads_public_wiki(self):
        found = self.w.search.search_wiki_counted(None, "quill")
        self.assertEqual(found.total, 2)
        self.assertEqual(
            [h.page_name for h in found.hits], ["Forging", "Home"])

    def test_owner_finds_private_wiki(self):
        found = self.w.search.search_wiki_counted(self.w.owner, "zorblax")
        self.assertEqual(found.total, 1)
        self.assertEqual(found.hits[0].full_name, "volmarr/vault")

    def test_private_wiki_equivalence_for_stranger(self):
        with tempfile.TemporaryDirectory() as td:
            clean = make_world(Path(td), with_secret=False)
            try:
                for viewer in (self.w.stranger, None):
                    mine = self.w.search.search_wiki_counted(viewer, "quill")
                    plain = clean.search.search_wiki_counted(viewer, "quill")
                    self.assertEqual(mine.total, plain.total)
                    self.assertEqual(
                        [(h.full_name, h.page_name) for h in mine.hits],
                        [(h.full_name, h.page_name) for h in plain.hits])
                    secret = self.w.search.search_wiki_counted(
                        viewer, "zorblax")
                    self.assertEqual(secret.total, 0)
                    self.assertEqual(secret.hits, ())
            finally:
                clean.conn.close()

    def test_count_before_cap(self):
        found = self.w.search.search_wiki_counted(
            self.w.owner, "quill", limit=1)
        self.assertEqual(found.total, 3)
        self.assertEqual(len(found.hits), 1)

    def test_scoped_face_and_uniform_not_found(self):
        found = self.w.search.search_repository(
            self.w.stranger, "volmarr", "anvil", "quill")
        self.assertEqual(found.total, 2)
        for owner_name, repo_name in (("volmarr", "vault"),
                                      ("volmarr", "missing")):
            with self.assertRaises(WikiGistSearchError) as ctx:
                self.w.search.search_repository(
                    self.w.stranger, owner_name, repo_name, "quill")
            self.assertEqual(ctx.exception.reason, "repo_not_found")

    def test_words_less_refused(self):
        for bad in ("", "type:wiki"):
            with self.assertRaises(WikiGistSearchError) as ctx:
                self.w.search.search_wiki_counted(self.w.owner, bad)
            self.assertEqual(ctx.exception.reason, "query_invalid")


class GistSearchTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name), with_secret=True)
        self.addCleanup(self.w.conn.close)

    def test_public_gist_found_by_each_field(self):
        by_desc = self.w.search.search_gists_counted(
            self.w.stranger, "scratchpad")
        self.assertEqual(by_desc.total, 1)
        self.assertEqual(by_desc.hits[0].matched_fields, ("description",))
        by_name = self.w.search.search_gists_counted(None, "notes.md")
        self.assertEqual(by_name.total, 1)
        self.assertEqual(by_name.hits[0].matched_fields, ("filename",))
        by_body = self.w.search.search_gists_counted(None, "loom")
        self.assertEqual(by_body.total, 1)
        hit = by_body.hits[0]
        self.assertEqual(hit.owner, "yrsa")
        self.assertEqual(hit.matched_fields, ("content",))
        self.assertEqual(hit.matched_files, ("weave.md",))
        self.assertEqual(hit.snippet_file, "weave.md")
        self.assertTrue(hit.snippets)

    def test_one_hit_per_gist(self):
        found = self.w.search.search_gists_counted(None, "quill")
        ids = [h.gist_id for h in found.hits]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(found.total, 2)

    def test_secret_gist_equivalence_for_stranger(self):
        with tempfile.TemporaryDirectory() as td:
            clean = make_world(Path(td), with_secret=False)
            try:
                for viewer in (self.w.stranger, None, self.w.other):
                    mine = self.w.search.search_gists_counted(viewer, "quill")
                    plain = clean.search.search_gists_counted(viewer, "quill")
                    self.assertEqual(mine.total, plain.total)
                    self.assertEqual(
                        [h.gist_id for h in mine.hits],
                        [h.gist_id for h in plain.hits])
                    secret = self.w.search.search_gists_counted(
                        viewer, "zorblax")
                    self.assertEqual(secret.total, 0)
                    self.assertEqual(secret.hits, ())
            finally:
                clean.conn.close()

    def test_secret_gist_found_by_owner_and_admin(self):
        for viewer in (self.w.owner, self.w.admin):
            found = self.w.search.search_gists_counted(viewer, "zorblax")
            self.assertEqual(found.total, 1)
            hit = found.hits[0]
            self.assertEqual(hit.visibility, "secret")
            self.assertEqual(
                hit.matched_fields, ("description", "content"))
            self.assertEqual(hit.matched_files, ("diary.md",))

    def test_count_before_cap(self):
        found = self.w.search.search_gists_counted(
            self.w.owner, "quill", limit=1)
        self.assertEqual(found.total, 3)
        self.assertEqual(len(found.hits), 1)


class CombinedAndGlobalTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name), with_secret=True)
        self.addCleanup(self.w.conn.close)

    def test_search_both_kinds_and_type_narrowing(self):
        both = self.w.search.search(None, "quill")
        self.assertEqual(both.wiki.total, 2)
        self.assertEqual(both.gists.total, 2)
        wiki_only = self.w.search.search(None, "quill type:wiki")
        self.assertIsNotNone(wiki_only.wiki)
        self.assertIsNone(wiki_only.gists)
        gist_only = self.w.search.search(None, "quill type:gists")
        self.assertIsNone(gist_only.wiki)
        self.assertIsNotNone(gist_only.gists)

    def test_global_search_groups(self):
        results = self.w.global_search.search(None, "quill")
        self.assertEqual(
            results.kinds[-2:], ("wiki", "gists"))
        self.assertEqual(results.group("wiki").total, 2)
        self.assertEqual(results.group("gists").total, 2)
        narrowed = self.w.global_search.search(
            None, "quill", types=("wiki",))
        self.assertEqual(narrowed.kinds, ("wiki",))
        typed = self.w.global_search.search(None, "quill type:gists")
        self.assertEqual(typed.kinds, ("gists",))

    def test_global_gist_group_keeps_secret_from_stranger(self):
        results = self.w.global_search.search(self.w.stranger, "zorblax")
        self.assertEqual(results.group("gists").total, 0)
        self.assertEqual(results.group("wiki").total, 0)
        owned = self.w.global_search.search(self.w.owner, "zorblax")
        self.assertEqual(owned.group("gists").total, 1)
        self.assertEqual(owned.group("wiki").total, 1)

    def test_search_api_serialises_new_groups(self):
        wiki = self.w.search.search_wiki_counted(None, "rests").hits[0]
        payload = hit_to_dict("wiki", wiki)
        self.assertEqual(payload["repository"], "volmarr/anvil")
        self.assertEqual(payload["page_name"], "Home")
        self.assertEqual(payload["matched_fields"], ["content"])
        gist = self.w.search.search_gists_counted(None, "loom").hits[0]
        payload = hit_to_dict("gists", gist)
        self.assertEqual(payload["owner"], "yrsa")
        self.assertEqual(payload["visibility"], "public")
        self.assertEqual(payload["matched_files"], ["weave.md"])

    def test_rendering_states_law_and_escapes(self):
        self.w.gists.create_gist(
            self.w.owner, "<script>alert(1)</script> loom",
            {"x.md": "loom\n"})
        results = self.w.search.search(None, "loom")
        page = render_wiki_gist_search_page("loom", results)
        self.assertIn("Wiki pages", page)
        self.assertIn("Gists", page)
        self.assertIn("repositories you can read", page)
        self.assertIn("secret gists for their owner", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        landing = render_wiki_gist_search_page("")
        self.assertIn("Wiki and gist search", landing)

    def test_schema_and_taxonomy_stand(self):
        self.assertEqual(schema_version(self.w.conn), 118)
        self.assertEqual(len(AUTH_EVENTS), 33)
        self.assertEqual(len(REPO_EVENTS), 88)
        self.assertEqual(len(ADMIN_EVENTS), 13)
        self.assertEqual(len(AUDIT_EVENTS), 134)


if __name__ == "__main__":
    unittest.main()
