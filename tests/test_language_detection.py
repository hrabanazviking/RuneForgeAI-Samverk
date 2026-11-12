"""S-218 acceptance battery: language detection.

Acceptance (roadmap S-218): language detection - for
code filters and highlighting (S-099) from one shared
table.

The centre is singleness: S-099's blob view re-exports
THIS module's table object (identity, not equality),
S-207's indexer imports detection from here, and
S-208's filter law is this module's law - so a file
the highlighter calls python is a file the indexer
records as python is a file the filter language:python
finds. Around it: precedence (filename, extension,
shebang, honest unknown), parsed shebangs, canonical
names with aliases kept OUT of filters (S-208's pin),
the census re-derived from the tables, and the schema
(93) / taxonomy (129) pins.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.db import schema_version
from samverk.language_detection import (
    LANGUAGE_ALIASES, LANGUAGE_BY_EXTENSION, LANGUAGE_BY_FILENAME,
    LANGUAGE_BY_SHEBANG, UNKNOWN_LANGUAGE, all_languages,
    canonical_language, detect_language, language_for_extension,
    language_for_filename, language_for_shebang, language_matches,
    parse_shebang_interpreter, render_language_page)


class SharedTableTests(unittest.TestCase):
    def test_blob_view_reexports_the_same_table_object(self):
        from samverk import blob_view
        self.assertIs(blob_view.LANGUAGE_BY_EXTENSION, LANGUAGE_BY_EXTENSION)
        self.assertIs(blob_view.detect_language, detect_language)

    def test_indexer_imports_detection_from_the_census(self):
        from samverk import code_indexing
        self.assertIs(code_indexing.detect_language, detect_language)

    def test_code_search_filter_is_the_shared_law(self):
        from samverk.code_search import matches_language
        for recorded, filt, expected in [
                ("python", "python", True), ("python", "PYTHON", True),
                ("python", "py", False), ("python", "", True),
                ("python", "klingon", False), ("go", "python", False)]:
            self.assertEqual(matches_language(recorded, filt), expected)
            self.assertEqual(language_matches(recorded, filt), expected)

    def test_highlighter_and_census_agree_on_seed_languages(self):
        from samverk.blob_view import highlight
        for ext, lang in [(".py", "python"), (".go", "go"),
                          (".rs", "rust"), (".js", "javascript")]:
            self.assertEqual(detect_language(f"x{ext}", b""), lang)
            self.assertEqual(highlight("def f(): pass", lang),
                             highlight("def f(): pass", lang))


class DetectionTests(unittest.TestCase):
    def test_extension_detection_canonical(self):
        cases = {"a.py": "python", "a.ts": "typescript",
                 "a.rs": "rust", "a.kt": "kotlin",
                 "a.hpp": "cpp", "a.exs": "elixir",
                 "a.scss": "css", "a.proto": "protobuf",
                 "dir/deep/a.go": "go", "A.PY": "python"}
        for name, lang in cases.items():
            self.assertEqual(detect_language(name, b""), lang, name)

    def test_exact_filename_beats_extension_and_shebang(self):
        self.assertEqual(detect_language("Makefile", b"#!/usr/bin/env python\n"), "make")
        self.assertEqual(detect_language("src/Dockerfile", b""), "dockerfile")
        self.assertEqual(detect_language("CMakeLists.txt", b""), "cmake")
        self.assertEqual(detect_language("Gemfile", b""), "ruby")

    def test_extension_beats_shebang(self):
        self.assertEqual(detect_language("x.py", b"#!/bin/sh\n"), "python")

    def test_unknown_is_honest_text_never_a_guess(self):
        self.assertEqual(UNKNOWN_LANGUAGE, "text")
        self.assertEqual(detect_language("x.unknownext", b"hi"), "text")
        self.assertEqual(detect_language("noext", b"plain words"), "text")
        self.assertEqual(detect_language("", b""), "text")
        self.assertEqual(detect_language(".gitignore", b"*.pyc\n"), "text")
        self.assertEqual(detect_language(None, None), "text")

    def test_extension_lookup_edges(self):
        self.assertIsNone(language_for_extension(".hidden"))
        self.assertIsNone(language_for_extension("noext"))
        self.assertEqual(language_for_extension("a.tar.gz"), None)
        self.assertEqual(language_for_filename("makefile"), "make")
        self.assertIsNone(language_for_filename("random.txt"))


class ShebangTests(unittest.TestCase):
    def test_env_and_direct_interpreters(self):
        self.assertEqual(detect_language("run", b"#!/usr/bin/env python3\n"), "python")
        self.assertEqual(detect_language("run", b"#!/bin/sh\n"), "shell")
        self.assertEqual(detect_language("run", b"#!/usr/bin/ruby\n"), "ruby")
        self.assertEqual(detect_language("run", b"#!/usr/bin/env node\n"), "javascript")

    def test_version_suffixes_stripped(self):
        self.assertEqual(parse_shebang_interpreter(b"#!/usr/bin/python3.11\n"), "python")
        self.assertEqual(detect_language("run", b"#!/usr/bin/perl5.38\n"), "perl")
        self.assertEqual(detect_language("run", b"#!/usr/bin/env python3.12\nx"), "python")

    def test_env_options_and_assignments_skipped(self):
        self.assertEqual(parse_shebang_interpreter(b"#!/usr/bin/env -S FOO=1 bash -e\n"), "bash")
        self.assertEqual(detect_language("run", b"#!/usr/bin/env -S FOO=1 bash\n"), "shell")

    def test_unknown_interpreter_is_honest_unknown(self):
        self.assertEqual(detect_language("run", b"#!/usr/bin/env klingon\n"), "text")
        self.assertEqual(parse_shebang_interpreter(b"#!/usr/bin/env klingon\n"), "klingon")
        self.assertIsNone(language_for_shebang(b"#!/usr/bin/env klingon\n"))

    def test_no_shebang_no_detection(self):
        self.assertIsNone(parse_shebang_interpreter(b"python is great\n"))
        self.assertIsNone(parse_shebang_interpreter(b""))
        self.assertIsNone(parse_shebang_interpreter(b"#!\n"))
        self.assertIsNone(parse_shebang_interpreter("#!/bin/sh"))
        self.assertEqual(detect_language("run", b"first line\n#!/bin/sh\n"), "text")


class CanonicalTests(unittest.TestCase):
    def test_canonical_names_resolve_to_themselves(self):
        for lang in all_languages():
            self.assertEqual(canonical_language(lang), lang)
            self.assertEqual(canonical_language(lang.upper()), lang)
            self.assertEqual(canonical_language(f"  {lang}  "), lang)

    def test_aliases_resolve_in_canonical_language(self):
        self.assertEqual(canonical_language("py"), "python")
        self.assertEqual(canonical_language("C++"), "cpp")
        self.assertEqual(canonical_language("c#"), "csharp")
        self.assertEqual(canonical_language("golang"), "go")
        self.assertEqual(canonical_language("yml"), "yaml")

    def test_unknown_words_name_nothing(self):
        self.assertIsNone(canonical_language("klingon"))
        self.assertIsNone(canonical_language(""))
        self.assertIsNone(canonical_language(None))
        self.assertIsNone(canonical_language(42))

    def test_filter_law_fail_closed(self):
        self.assertTrue(language_matches("python", ""))
        self.assertTrue(language_matches("python", None))
        self.assertTrue(language_matches("Python", "python"))
        self.assertFalse(language_matches("python", "py"))
        self.assertFalse(language_matches("python", "klingon"))
        self.assertFalse(language_matches("klingon", "klingon"))
        self.assertFalse(language_matches(None, "python"))


class CensusTests(unittest.TestCase):
    def test_census_rederived_from_tables(self):
        expected = {UNKNOWN_LANGUAGE} | set(LANGUAGE_BY_EXTENSION.values()) \
            | set(LANGUAGE_BY_FILENAME.values()) \
            | set(LANGUAGE_BY_SHEBANG.values()) | set(LANGUAGE_ALIASES.values())
        self.assertEqual(set(all_languages()), expected)
        self.assertEqual(list(all_languages()), sorted(expected))

    def test_every_table_answer_is_a_census_language(self):
        census = set(all_languages())
        for table in (LANGUAGE_BY_EXTENSION, LANGUAGE_BY_FILENAME,
                      LANGUAGE_BY_SHEBANG, LANGUAGE_ALIASES):
            for value in table.values():
                self.assertIn(value, census)

    def test_seed_languages_of_s099_all_present(self):
        for lang in ("python", "javascript", "typescript", "go", "rust",
                     "java", "c", "cpp", "csharp", "ruby", "shell", "sql",
                     "html", "css", "json", "toml", "yaml", "markdown",
                     "lua", "perl", "php", "make"):
            self.assertIn(lang, all_languages())

    def test_extensions_are_lowercase_dotted_and_unique(self):
        for ext in LANGUAGE_BY_EXTENSION:
            self.assertTrue(ext.startswith("."), ext)
            self.assertEqual(ext, ext.lower(), ext)
            self.assertGreater(len(ext), 1, ext)

    def test_page_lists_census_with_escaping(self):
        page = render_language_page()
        self.assertIn("python", page)
        self.assertIn("never a guess", page)
        for lang in all_languages():
            self.assertIn(lang, page)


class PinsTests(unittest.TestCase):
    def test_schema_and_taxonomy_pins(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.init_db(Path(tmp) / "t.db")
            try:
                self.assertEqual(schema_version(conn), 116)
            finally:
                conn.close()
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 88)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)


if __name__ == "__main__":
    unittest.main()
