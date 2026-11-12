"""S-219 acceptance battery: honest limits document.

Acceptance (roadmap S-219): Honest limits document
-- what Samverk search does NOT do (no semantic
ranking claims, regex cost caps) written where
users will find it.

The centre is the audit: the document's stated
caps and no-ranking claims are compared with the
live engines' own constants and hit shapes, so a
document that drifts from the code fails here.
Behavioural cells pin the checkable claims in the
engines themselves (literal substring, Python re,
per-file caps, fail-closed language aliases, the
honest unknown language).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.db import schema_version
import samverk.code_search as code_search_module
from samverk.code_search import build_snippets, find_line_matches, matches_language
from samverk.global_search import render_global_search_page
from samverk.language_detection import detect_language
from samverk.search_limits import (
    DOCUMENTED_CAPS, LIMITS_PATH, SEARCH_LIMITS, SearchLimitsAudit,
    SearchLimitsError, audit_search_limits, get_limit, limit_ids,
    render_search_limits_page)

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "SEARCH_LIMITS.md"

EXPECTED_IDS = (
    "no-semantic-search", "no-relevance-ranking", "regex-cost-caps",
    "pattern-and-result-caps", "index-coverage", "index-freshness",
    "language-limits", "global-and-api-caps", "commit-scan-cap",
    "budgets-per-hardware")


class SearchLimitsTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 118)
        self.assertEqual(db.MIGRATIONS[-1][0], 118)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)

    def test_limits_path_is_the_search_child(self):
        self.assertEqual(LIMITS_PATH, "/search/limits")

    # the document as data
    def test_limit_ids_exact_and_unique(self):
        self.assertEqual(limit_ids(), EXPECTED_IDS)
        self.assertEqual(len(set(limit_ids())), len(EXPECTED_IDS))

    def test_every_limit_has_title_and_statement(self):
        for limit in SEARCH_LIMITS:
            self.assertTrue(limit.title.strip())
            self.assertGreater(len(limit.statement), 80)

    def test_get_limit_roundtrip_and_unknown_refused(self):
        for limit in SEARCH_LIMITS:
            self.assertIs(get_limit(limit.id), limit)
        with self.assertRaises(SearchLimitsError) as ctx:
            get_limit("semantic-ranking")
        self.assertEqual(ctx.exception.reason, "limit_unknown")
        with self.assertRaises(SearchLimitsError):
            get_limit(None)

    def test_no_semantic_limit_names_the_absences(self):
        text = get_limit("no-semantic-search").statement.lower()
        for word in ("embedding", "vector", "synonym", "stemming",
                     "spelling", "expansion"):
            self.assertIn(word, text)

    def test_no_ranking_limit_names_the_orders(self):
        text = get_limit("no-relevance-ranking").statement
        self.assertIn("repository, then path", text)
        self.assertIn("no hit", text.lower())
        self.assertIn("score", text)

    def test_regex_limit_states_no_timeout_plainly(self):
        text = get_limit("regex-cost-caps").statement
        self.assertIn("no timeout", text)
        self.assertIn("no safe-regex", text)
        self.assertIn("500", text)

    # the audit: document vs live code
    def test_documented_caps_match_live_engines(self):
        from samverk import (code_search, commit_search, global_search,
                             index_architecture)
        self.assertEqual(DOCUMENTED_CAPS["code_pattern_max"], code_search.PATTERN_MAX)
        self.assertEqual(DOCUMENTED_CAPS["code_default_limit"], code_search.DEFAULT_LIMIT)
        self.assertEqual(DOCUMENTED_CAPS["code_max_limit"], code_search.MAX_LIMIT)
        self.assertEqual(DOCUMENTED_CAPS["code_max_context"], code_search.MAX_CONTEXT)
        self.assertEqual(DOCUMENTED_CAPS["code_max_snippets_per_file"], code_search.MAX_SNIPPETS_PER_FILE)
        self.assertEqual(DOCUMENTED_CAPS["global_query_max"], global_search.QUERY_MAX)
        self.assertEqual(DOCUMENTED_CAPS["global_default_group_limit"], global_search.DEFAULT_GROUP_LIMIT)
        self.assertEqual(DOCUMENTED_CAPS["global_max_group_limit"], global_search.MAX_GROUP_LIMIT)
        self.assertEqual(DOCUMENTED_CAPS["max_code_blob_bytes"], index_architecture.MAX_CODE_BLOB_BYTES)
        self.assertEqual(DOCUMENTED_CAPS["commit_max_scan_per_repo"], commit_search.MAX_SCAN_PER_REPO)

    def test_audit_honest_on_live_code(self):
        audit = audit_search_limits()
        self.assertTrue(audit.honestly_stated)
        self.assertEqual(audit.caps_checked, len(DOCUMENTED_CAPS))
        self.assertEqual(audit.caps_matching, audit.caps_checked)
        self.assertEqual(audit.cap_mismatches, ())
        self.assertEqual(audit.offending_hit_fields, ())
        self.assertFalse(audit.regex_has_timeout)
        self.assertGreater(audit.hit_fields_scanned, 20)

    def test_audit_catches_a_drifted_cap(self):
        original = code_search_module.PATTERN_MAX
        code_search_module.PATTERN_MAX = original + 1
        try:
            audit = audit_search_limits()
        finally:
            code_search_module.PATTERN_MAX = original
        self.assertFalse(audit.honestly_stated)
        self.assertIn("code_pattern_max", audit.cap_mismatches)
        self.assertTrue(audit_search_limits().honestly_stated)

    def test_no_hit_dataclass_carries_a_score(self):
        import dataclasses
        from samverk.code_search import CodeSearchHit
        from samverk.repository_search import RepositoryHit
        for cls in (CodeSearchHit, RepositoryHit):
            names = [f.name for f in dataclasses.fields(cls)]
            for bad in ("score", "rank", "relevance", "semantic"):
                self.assertNotIn(bad, names)

    # behavioural pins: the claims are true of the engines
    def test_substring_is_literal_not_pattern(self):
        self.assertEqual(find_line_matches("a.b axb", "a.b", "substring"), ((0, 3),))
        self.assertEqual(find_line_matches("axb", "a.b", "substring"), ())

    def test_regex_is_python_re_case_sensitive(self):
        self.assertEqual(find_line_matches("Samverk samverk", "samverk", "regex"), ((8, 15),))
        self.assertEqual(find_line_matches("aaa", "a+", "regex"), ((0, 3),))
        self.assertEqual(find_line_matches("aaa", "(?i)A+", "regex"), ((0, 3),))

    def test_snippet_cap_trims_shown_never_counted(self):
        # matched lines spaced apart, so each is its own
        # block (touching windows merge, by S-208 design)
        lines = []
        for i in range(30):
            lines.append(f"needle line {i}")
            lines.append("filler")
            lines.append("filler")
        text = "\n".join(lines)
        snippets, total, matched = build_snippets(text, "needle", "substring", context=0)
        self.assertEqual(total, 30)
        self.assertEqual(matched, 30)
        self.assertEqual(len(snippets), 20)

    def test_language_alias_fails_closed_in_filter(self):
        self.assertTrue(matches_language("python", "python"))
        self.assertTrue(matches_language("python", "PYTHON"))
        self.assertFalse(matches_language("python", "py"))
        self.assertFalse(matches_language("python", "cobol"))
        self.assertTrue(matches_language("python", ""))

    def test_language_detection_never_guesses(self):
        self.assertEqual(detect_language("mystery.zzz", b"print(1)\n"), "text")
        self.assertEqual(detect_language("plain.txt", b"def f(): pass\n"), "text")
        self.assertEqual(detect_language("tool", b"#!/usr/bin/env python3\n"), "python")

    # where users find it
    def test_global_search_page_links_the_limits(self):
        landing = render_global_search_page("", None)
        self.assertIn(LIMITS_PATH, landing)
        self.assertIn("What search does not do", landing)

    def test_limits_page_renders_every_limit(self):
        page = render_search_limits_page()
        self.assertIn("What search does not do", page)
        for limit in SEARCH_LIMITS:
            self.assertIn(limit.title, page)
            self.assertIn(limit.statement, page)
        self.assertIn("5000", page)
        self.assertIn("1048576", page)

    def test_limits_page_audit_verdict_both_ways(self):
        honest = render_search_limits_page(audit_search_limits())
        self.assertIn("Checked, not just claimed", honest)
        drifted = SearchLimitsAudit(
            caps_checked=10, caps_matching=9,
            cap_mismatches=("code_pattern_max",),
            hit_fields_scanned=31, offending_hit_fields=(),
            regex_has_timeout=False)
        page = render_search_limits_page(drifted)
        self.assertIn("no longer exact", page)
        self.assertIn("code_pattern_max", page)
        lying = SearchLimitsAudit(
            caps_checked=10, caps_matching=10, cap_mismatches=(),
            hit_fields_scanned=31,
            offending_hit_fields=("CodeSearchHit.score",),
            regex_has_timeout=True)
        page = render_search_limits_page(lying)
        self.assertIn("no longer exact", page)
        self.assertIn("CodeSearchHit.score", page)

    def test_docs_file_says_the_same_limits(self):
        text = DOC.read_text(encoding="utf-8").replace("\u2014", "--")
        for limit in SEARCH_LIMITS:
            self.assertIn(limit.title.split(":")[0], text)
        flat = " ".join(text.split())
        for needle in ("no embeddings", "No relevance ranking",
                       "no timeout", "5000", "1048576",
                       "NOT PROVEN", "py"):
            self.assertIn(needle, flat)

    def test_docs_and_module_agree_on_caps(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn(str(DOCUMENTED_CAPS["code_pattern_max"]), text)
        self.assertIn(str(DOCUMENTED_CAPS["commit_max_scan_per_repo"]), text)
        self.assertIn(str(DOCUMENTED_CAPS["max_code_blob_bytes"]), text)


if __name__ == "__main__":
    unittest.main()
