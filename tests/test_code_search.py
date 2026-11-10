"""S-208 acceptance battery: code search basic.

Acceptance (roadmap S-208): Code search basic —
substring and regex modes, path and language
filters, result snippets with matched-line context.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.code_indexing import CodeIndexer
from samverk.code_search import (
    CodeSearch, CodeSearchError, build_snippets, find_line_matches,
    matches_language, matches_path, parse_code_query,
    render_code_search_page)
from samverk.db import schema_version
from samverk.repositories import RepositoryStore
from test_repo_home import run_git


class PureLawTests(unittest.TestCase):
    def test_parse_lifts_qualifiers_keeps_pattern_spaces(self):
        q = parse_code_query("hello world path:src language:python")
        self.assertEqual(q.pattern, "hello world")
        self.assertEqual(q.path, "src")
        self.assertEqual(q.language, "python")
        self.assertEqual(q.mode, "substring")
        self.assertIsNone(q.repo_scope)

    def test_parse_mode_and_lang_alias_and_repo_scope(self):
        q = parse_code_query("repo:Volmarr/Anvil mode:regex lang:Rust fn\\s+main")
        self.assertEqual(q.mode, "regex")
        self.assertEqual(q.language, "rust")
        self.assertEqual(q.repo_scope, ("volmarr", "anvil"))
        self.assertEqual(q.pattern, "fn\\s+main")

    def test_parse_unknown_qualifier_refused_by_name(self):
        with self.assertRaises(CodeSearchError) as ctx:
            parse_code_query("hello author:bob")
        self.assertEqual(ctx.exception.reason, "query_invalid")
        self.assertIn("author", str(ctx.exception))

    def test_parse_bad_mode_and_empty_value_refused(self):
        for bad in ("hello mode:fuzzy", "hello path:", "hello mode:"):
            with self.assertRaises(CodeSearchError) as ctx:
                parse_code_query(bad)
            self.assertEqual(ctx.exception.reason, "query_invalid")

    def test_parse_malformed_repo_scope_refused(self):
        with self.assertRaises(CodeSearchError) as ctx:
            parse_code_query("repo:justname hello")
        self.assertEqual(ctx.exception.reason, "query_invalid")

    def test_matches_path_shapes(self):
        self.assertTrue(matches_path("src/lib.py", ""))
        self.assertTrue(matches_path("src/lib.py", "src"))
        self.assertTrue(matches_path("src/lib.py", "src/"))
        self.assertTrue(matches_path("src/lib.py", "src/lib.py"))
        self.assertFalse(matches_path("src/lib.py", "sr"))
        self.assertFalse(matches_path("lib.py", "src"))
        self.assertTrue(matches_path("src/lib.py", "*.py"))
        self.assertFalse(matches_path("src/lib.py", "lib.py"))
        self.assertFalse(matches_path("src/lib.py", "*.rs"))

    def test_matches_language_exact_case_insensitive(self):
        self.assertTrue(matches_language("python", "Python"))
        self.assertTrue(matches_language("python", ""))
        self.assertFalse(matches_language("python", "py"))

    def test_find_line_matches_substring_case_insensitive(self):
        self.assertEqual(
            find_line_matches("Hello hello HELLO", "hello", "substring"),
            ((0, 5), (6, 11), (12, 17)))
        self.assertEqual(
            find_line_matches("a+b a+b", "a+b", "substring"),
            ((0, 3), (4, 7)))
        self.assertEqual(find_line_matches("nothing", "zzz", "substring"), ())

    def test_find_line_matches_regex_spans_and_zero_width(self):
        self.assertEqual(
            find_line_matches("a1 b22 c333", r"\d+", "regex"),
            ((1, 2), (4, 6), (8, 11)))
        spans = find_line_matches("bbb", "a*", "regex")
        self.assertTrue(spans)
        self.assertTrue(all(s == e for s, e in spans))

    def test_build_snippets_context_and_merge(self):
        text = "one\ntwo MATCH\nthree\nfour\nfive\nsix MATCH seven\neight\n"
        snippets, total, matched = build_snippets(text, "match", "substring", context=1)
        self.assertEqual(total, 2)
        self.assertEqual(matched, 2)
        self.assertEqual(len(snippets), 2)
        self.assertEqual(snippets[0].start_line, 1)
        self.assertEqual([l.number for l in snippets[0].lines], [1, 2, 3])
        self.assertEqual(snippets[0].match_numbers, (2,))
        self.assertEqual([l.number for l in snippets[1].lines], [5, 6, 7])

    def test_build_snippets_merges_touching_windows(self):
        text = "MATCH\nx\nMATCH\n"
        snippets, total, matched = build_snippets(text, "match", "substring", context=1)
        self.assertEqual(len(snippets), 1)
        self.assertEqual(snippets[0].match_numbers, (1, 3))

    def test_build_snippets_cap_keeps_true_counts(self):
        text = "\n".join(f"MATCH {i}" + "\nx\ny\nz" for i in range(30))
        snippets, total, matched = build_snippets(text, "match", "substring", context=0)
        self.assertEqual(total, 30)
        self.assertEqual(matched, 30)
        self.assertEqual(len(snippets), 20)


class CodeSearchTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("mallory", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "anvil", visibility="public")
        self.bare = self.repos.path_for("volmarr", "anvil")
        self.indexer = CodeIndexer(self.conn, self.repos)
        self.search = CodeSearch(self.conn, self.repos)
        self.work = self.root / "work"
        self.work.mkdir()
        run_git(self.work, "init", "-b", "main")
        self._write("main.py", b"print('hello world')\nHello again\nlast line\n")
        self._write("src/lib.py", b"VALUE = 42\nhello_value = compute()\n")
        self._write("notes.txt", b"hello from notes\nsecond hello here\n")
        self._write("run.sh", b"#!/bin/sh\necho hello\n")
        self._write("evil.py", b"x = '<script>alert(1)</script>'  # hello\n")
        self._commit("first")
        self.indexer.index_repository("volmarr", "anvil")

    def _write(self, rel, data):
        path = self.work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _commit(self, message):
        run_git(self.work, "add", "-A")
        run_git(self.work, "commit", "-m", message)
        run_git(self.work, "push", str(self.bare), "main")
        return run_git(self.work, "rev-parse", "HEAD")

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(CodeSearchError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _paths(self, hits):
        return [h.path for h in hits]

    # -- pins -------------------------------------------------
    def test_pins_schema_97_taxonomy_131(self):
        self.assertEqual(schema_version(self.conn), 97)
        self.assertEqual(db.MIGRATIONS[-1][0], 97)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 85)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    # -- modes ------------------------------------------------
    def test_substring_search_finds_files_case_insensitively(self):
        hits = self.search.search(self.owner, "HELLO")
        self.assertEqual(self._paths(hits), ["evil.py", "main.py", "notes.txt", "run.sh", "src/lib.py"])
        main = next(h for h in hits if h.path == "main.py")
        self.assertEqual(main.match_count, 2)
        self.assertEqual(main.matched_lines, 2)
        self.assertEqual(main.language, "python")
        self.assertEqual(main.full_name, "volmarr/anvil")

    def test_substring_is_literal_not_regex(self):
        hits = self.search.search(self.owner, "hello.*")
        self.assertEqual(hits, [])
        hits = self.search.search(self.owner, "hello.*", mode="regex")
        self.assertTrue(hits)

    def test_regex_mode(self):
        hits = self.search.search(self.owner, r"hello\s+world", mode="regex")
        self.assertEqual(self._paths(hits), ["main.py"])
        hits = self.search.search(self.owner, "mode:regex ^VALUE")
        self.assertEqual(self._paths(hits), ["src/lib.py"])

    def test_bad_regex_refused_query_invalid(self):
        self.assertEqual(self._reason(self.search.search, self.owner, "(", mode="regex"), "query_invalid")
        hits = self.search.search(self.owner, "([")
        self.assertEqual(hits, [])
        hits = self.search.search(self.owner, "(")
        self.assertTrue(hits)

    def test_empty_pattern_refused(self):
        self.assertEqual(self._reason(self.search.search, self.owner, ""), "query_invalid")
        self.assertEqual(self._reason(self.search.search, self.owner, "path:src"), "query_invalid")
        self.assertEqual(self._reason(self.search.search, self.owner, "hello", limit=0), "query_invalid")
        self.assertEqual(self._reason(self.search.search, self.owner, "hello", context=9), "query_invalid")

    # -- filters ----------------------------------------------
    def test_path_filter_forms(self):
        self.assertEqual(self._paths(self.search.search(self.owner, "hello", path="src")), ["src/lib.py"])
        self.assertEqual(self._paths(self.search.search(self.owner, "hello path:src/")), ["src/lib.py"])
        self.assertEqual(self._paths(self.search.search(self.owner, "hello", path="*.py")), ["evil.py", "main.py", "src/lib.py"])
        self.assertEqual(self._paths(self.search.search(self.owner, "hello", path="notes.txt")), ["notes.txt"])

    def test_path_filter_absolute_and_dotdot_refused(self):
        self.assertEqual(self._reason(self.search.search, self.owner, "hello", path="/etc"), "query_invalid")
        self.assertEqual(self._reason(self.search.search, self.owner, "hello", path="../secret"), "query_invalid")

    def test_language_filter(self):
        self.assertEqual(self._paths(self.search.search(self.owner, "hello", language="python")), ["evil.py", "main.py", "src/lib.py"])
        self.assertEqual(self._paths(self.search.search(self.owner, "hello language:Shell")), ["run.sh"])
        self.assertEqual(self._paths(self.search.search(self.owner, "hello", language="text")), ["notes.txt"])
        self.assertEqual(self.search.search(self.owner, "hello", language="rust"), [])

    def test_explicit_pattern_bypasses_qualifier_parsing(self):
        hits = self.search.search(self.owner, "", pattern="hello_value")
        self.assertEqual(self._paths(hits), ["src/lib.py"])

    # -- snippets ---------------------------------------------
    def test_snippets_carry_matched_line_context(self):
        hits = self.search.search_repository(self.owner, "volmarr", "anvil", "hello", context=1)
        main = next(h for h in hits if h.path == "main.py")
        self.assertEqual(len(main.snippets), 1)
        lines = main.snippets[0].lines
        self.assertEqual([l.number for l in lines], [1, 2, 3])
        self.assertEqual([l.is_match for l in lines], [True, True, False])
        self.assertEqual(lines[0].spans, ((7, 12),))
        hits0 = self.search.search(self.owner, "hello", context=0)
        main0 = next(h for h in hits0 if h.path == "main.py")
        self.assertTrue(all(l.is_match for s in main0.snippets for l in s.lines))

    # -- scope and permission ---------------------------------
    def test_repo_scope_qualifier_and_scoped_face(self):
        hits = self.search.search(self.owner, "repo:volmarr/anvil hello")
        self.assertTrue(hits)
        self.assertTrue(all(h.full_name == "volmarr/anvil" for h in hits))
        self.assertEqual(self._reason(self.search.search, self.owner, "repo:volmarr/ghost hello"), "repo_not_found")

    def test_private_repo_hidden_from_stranger(self):
        self.repos.create_repository(self.owner.id, "volmarr", "secret", visibility="private")
        bare2 = self.repos.path_for("volmarr", "secret")
        work2 = self.root / "work2"
        work2.mkdir()
        run_git(work2, "init", "-b", "main")
        (work2 / "hidden.py").write_bytes(b"hello secret\n")
        run_git(work2, "add", "-A")
        run_git(work2, "commit", "-m", "secret")
        run_git(work2, "push", str(bare2), "main")
        self.indexer.index_repository("volmarr", "secret")
        hits = self.search.search(self.stranger, "hello")
        self.assertTrue(all(h.repo != "secret" for h in hits))
        self.assertEqual(self._reason(self.search.search_repository, self.stranger, "volmarr", "secret", "hello"), "repo_not_found")
        owner_hits = self.search.search(self.owner, "hello")
        self.assertIn("hidden.py", self._paths(owner_hits))
        anon_hits = self.search.search(None, "hello")
        self.assertTrue(all(h.repo != "secret" for h in anon_hits))

    def test_limit_caps_files_in_order(self):
        hits = self.search.search(self.owner, "hello", limit=2)
        self.assertEqual(self._paths(hits), ["evil.py", "main.py"])

    def test_search_writes_nothing(self):
        before_audit = self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        before_rows = self.conn.execute("SELECT COUNT(*) c FROM code_fts").fetchone()["c"]
        self.search.search(self.owner, "hello")
        self.search.search(self.owner, "mode:regex h.llo")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"], before_audit)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM code_fts").fetchone()["c"], before_rows)

    # -- rendering --------------------------------------------
    def test_render_page_marks_matches_and_escapes_code(self):
        hits = self.search.search(self.owner, "hello")
        page = render_code_search_page("hello", hits, mode="substring")
        self.assertIn("<mark>hello</mark>", page)
        self.assertIn("matched line", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("src/lib.py", page)

    def test_render_page_empty_state(self):
        page = render_code_search_page("zzz", [], mode="substring")
        self.assertIn("No indexed code matches", page)


if __name__ == "__main__":
    unittest.main()
