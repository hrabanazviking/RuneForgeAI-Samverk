"""S-207 acceptance battery: code indexing.

Acceptance (roadmap S-207): Code indexing — on push,
changed blobs extracted to the index within the
size/language budgets; LFS pointers indexed as
pointers, honestly.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.code_indexing import (
    POINTER_LANGUAGE, CodeIndexer, CodeIndexError, TreeBlob,
    diff_snapshots, is_binary_data, is_ignored_path, judge_blob,
    parse_gitignore, render_code_index_page)
from samverk.db import schema_version
from samverk.hooks import RefUpdate
from samverk.index_architecture import (
    MAX_CODE_BLOB_BYTES, SearchIndexStore)
from samverk.lfs_store import make_pointer, oid_for
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

ZERO = "0" * 40
POINTEE = b"pretend large file contents, never in git\n"
POINTER = make_pointer(oid_for(POINTEE), len(POINTEE))


class CodeIndexingTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register(
            "volmarr", "correct horse battery")
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.repos.create_repository(
            self.owner.id, "volmarr", "anvil", visibility="public")
        self.bare = self.repos.path_for("volmarr", "anvil")
        self.registry = SearchIndexStore(self.conn, self.repos)
        self.indexer = CodeIndexer(self.conn, self.repos)
        self.work = self.root / "work"
        self.work.mkdir()
        run_git(self.work, "init", "-b", "main")
        self._write("main.py", b"print('hello world')\n")
        self._write("src/lib.py", b"VALUE = 42\n")
        self._write("notes.txt", b"plain notes\n")
        self._write("run.sh", b"#!/bin/sh\necho hi\n")
        os.chmod(self.work / "run.sh", 0o755)
        self._write(".gitignore", b"*.log\n")
        self._write("debug.log", b"a log line\n")
        self._write("logo.bin", b"\x89PNG\x00\x01\x02binary")
        self._write("empty.txt", b"")
        self._write("big.py", b"a" * (MAX_CODE_BLOB_BYTES + 100))
        self._write("asset.bin", POINTER)
        self.c1 = self._commit("first", force=("debug.log",))

    # -- fixture helpers ------------------------------------
    def _write(self, rel, data):
        path = self.work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _commit(self, message, force=()):
        for rel in force:
            run_git(self.work, "add", "-f", rel)
        run_git(self.work, "add", "-A")
        run_git(self.work, "commit", "-m", message)
        run_git(self.work, "push", str(self.bare), "main")
        return run_git(self.work, "rev-parse", "HEAD")

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(CodeIndexError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _audit_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]

    def _file_outcome(self, report, path):
        for outcome in report.outcomes:
            if outcome.path == path:
                return outcome
        raise AssertionError(f"no outcome for {path}: {report.outcomes}")

    # -- pins -------------------------------------------------
    def test_pins_schema_99_taxonomy_131(self):
        self.assertEqual(schema_version(self.conn), 101)
        self.assertEqual(db.MIGRATIONS[-1][0], 101)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 85)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("code_fts", tables)
        self.assertIn("issue_pr_fts", tables)
        self.assertIn("index_documents", tables)

    def test_fresh_database_migrates_to_93(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "fresh.db")
            self.assertEqual(db.schema_version(conn), 101)
            conn.close()

    def test_upgrade_from_81_creates_code_fts(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for target, statements in db.MIGRATIONS:
                if target > 81:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_meta"
                        " (key, value) VALUES ('version', ?)",
                        (str(target),))
            self.assertEqual(db.schema_version(conn), 81)
            self.assertEqual(db.migrate(conn), 101)
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertIn("code_fts", names)
            conn.close()

    # -- pure law ---------------------------------------------
    def test_diff_snapshots_pure(self):
        old = {
            "keep.py": TreeBlob("keep.py", "100644", "a" * 40),
            "move.py": TreeBlob("move.py", "100644", "b" * 40),
            "mode.py": TreeBlob("mode.py", "100644", "c" * 40),
            "gone.py": TreeBlob("gone.py", "100644", "d" * 40),
        }
        new = {
            "keep.py": TreeBlob("keep.py", "100644", "a" * 40),
            "move.py": TreeBlob("move.py", "100644", "e" * 40),
            "mode.py": TreeBlob("mode.py", "100755", "c" * 40),
            "born.py": TreeBlob("born.py", "100644", "f" * 40),
        }
        changed, deleted, unchanged = diff_snapshots(old, new)
        self.assertEqual(changed, ("born.py", "mode.py", "move.py"))
        self.assertEqual(deleted, ("gone.py",))
        self.assertEqual(unchanged, ("keep.py",))
        self.assertEqual(diff_snapshots({}, {}), ((), (), ()))
        self.assertEqual(
            diff_snapshots(new, new),
            ((), (), tuple(sorted(new))))

    def test_gitignore_parsing_and_matching(self):
        patterns = parse_gitignore(
            "# a comment\n\n*.log\nbuild/\n/root.txt\n"
            "!keep.log\ndocs/*.md\n")
        self.assertEqual(
            patterns,
            ((False, "*.log"), (False, "build/"),
             (False, "/root.txt"), (True, "keep.log"),
             (False, "docs/*.md")))
        self.assertTrue(is_ignored_path("debug.log", patterns))
        self.assertTrue(is_ignored_path("src/debug.log", patterns))
        self.assertFalse(is_ignored_path("keep.log", patterns))
        self.assertTrue(is_ignored_path("build/out.py", patterns))
        self.assertTrue(is_ignored_path("src/build/out.py", patterns))
        self.assertTrue(is_ignored_path("root.txt", patterns))
        self.assertFalse(is_ignored_path("src/root.txt", patterns))
        self.assertTrue(is_ignored_path("docs/guide.md", patterns))
        self.assertFalse(is_ignored_path("src/guide.md", patterns))
        self.assertFalse(is_ignored_path("main.py", patterns))
        self.assertFalse(is_ignored_path("main.py", ()))

    def test_is_binary_data_probe(self):
        self.assertFalse(is_binary_data(b""))
        self.assertFalse(is_binary_data(b"plain text\n"))
        self.assertTrue(is_binary_data(b"a\x00b"))
        self.assertTrue(is_binary_data(b"x" * 8191 + b"\x00"))
        self.assertFalse(is_binary_data(b"x" * 8192 + b"\x00"))

    def test_judge_blob_verdicts(self):
        sub = judge_blob(path="vendor/lib", mode="160000", data=None)
        self.assertEqual((sub.disposition, sub.reason),
                         ("skip", "submodule"))
        ptr = judge_blob(path="asset.bin", mode="100644", data=POINTER)
        self.assertEqual((ptr.disposition, ptr.reason),
                         ("index_pointer", "lfs_pointer"))
        self.assertEqual(ptr.language, POINTER_LANGUAGE)
        self.assertEqual(ptr.text, POINTER.decode())
        self.assertEqual(ptr.lfs_oid, oid_for(POINTEE))
        self.assertEqual(ptr.lfs_size, len(POINTEE))
        # A pointer is judged before the ignore rule (S-205's order).
        ptr2 = judge_blob(path="asset.bin", mode="100644", data=POINTER,
                          patterns=((False, "asset.bin"),))
        self.assertEqual(ptr2.disposition, "index_pointer")
        ign = judge_blob(path="debug.log", mode="100644",
                         data=b"a log line\n",
                         patterns=((False, "*.log"),))
        self.assertEqual((ign.disposition, ign.reason),
                         ("skip", "ignored"))
        binary = judge_blob(path="logo.bin", mode="100644",
                            data=b"a\x00b")
        self.assertEqual((binary.disposition, binary.reason),
                         ("skip", "binary"))
        big = judge_blob(path="big.py", mode="100644",
                         data=b"a" * (MAX_CODE_BLOB_BYTES + 1))
        self.assertEqual((big.disposition, big.reason),
                         ("skip", "oversized"))
        at_budget = judge_blob(path="ok.py", mode="100644",
                               data=b"a" * MAX_CODE_BLOB_BYTES)
        self.assertEqual(at_budget.disposition, "index")
        empty = judge_blob(path="e.txt", mode="100644", data=b"")
        self.assertEqual((empty.disposition, empty.reason),
                         ("skip", "empty"))

    def test_judge_blob_language_and_plain_fallback(self):
        py = judge_blob(path="a/b.py", mode="100644", data=b"x = 1\n")
        self.assertEqual((py.disposition, py.language, py.text),
                         ("index", "python", "x = 1\n"))
        plain = judge_blob(path="data.zzz", mode="100644",
                           data=b"stuff\n")
        self.assertEqual((plain.disposition, plain.language),
                         ("index", "text"))
        # A file at an LFS-looking path that is not a valid
        # pointer is judged on its own bytes.
        fake = judge_blob(path="asset.bin", mode="100644",
                          data=b"not a pointer\n")
        self.assertEqual(fake.disposition, "index")
        self.assertNotEqual(fake.language, POINTER_LANGUAGE)

    # -- first index -------------------------------------------
    def test_first_index_verdicts_documents_and_registry(self):
        report = self.indexer.index_tip("volmarr", "anvil", self.c1)
        self.assertEqual(report.commit_oid, self.c1)
        self.assertEqual(report.previous_oid, "")
        self.assertEqual(report.indexed, 5)
        self.assertEqual(report.pointers, 1)
        self.assertEqual(report.skipped, 4)
        self.assertEqual(report.removed, 0)
        self.assertEqual(report.unchanged, 0)
        self.assertEqual(
            self._file_outcome(report, "logo.bin").reason, "binary")
        self.assertEqual(
            self._file_outcome(report, "empty.txt").reason, "empty")
        self.assertEqual(
            self._file_outcome(report, "big.py").reason, "oversized")
        self.assertEqual(
            self._file_outcome(report, "debug.log").reason, "ignored")
        docs = self.indexer.documents_for("volmarr", "anvil")
        self.assertEqual(
            [d.path for d in docs],
            [".gitignore", "asset.bin", "main.py", "notes.txt",
             "run.sh", "src/lib.py"])
        snap = self.indexer.snapshot("volmarr", "anvil", self.c1)
        main = self.indexer.document_for("volmarr", "anvil", "main.py")
        self.assertEqual(main.text, "print('hello world')\n")
        self.assertEqual(main.language, "python")
        self.assertEqual(main.commit_oid, self.c1)
        self.assertEqual(main.digest, snap["main.py"].oid)
        self.assertEqual(main.disposition, "index")
        self.assertFalse(main.is_pointer)
        run = self.indexer.document_for("volmarr", "anvil", "run.sh")
        self.assertEqual(run.language, "shell")
        self.assertIsNone(
            self.indexer.document_for("volmarr", "anvil", "logo.bin"))
        registered = self.registry.documents_for(
            "volmarr", "anvil", kind="code")
        self.assertEqual(
            [d.doc_key for d in registered],
            [f"code:{p}" for p in
             [".gitignore", "asset.bin", "main.py", "notes.txt",
              "run.sh", "src/lib.py"]])
        by_key = {d.doc_key: d for d in registered}
        self.assertEqual(by_key["code:main.py"].digest, main.digest)
        self.assertEqual(by_key["code:main.py"].commit_oid, self.c1)
        rows = self.conn.execute(
            "SELECT path FROM code_fts WHERE code_fts MATCH ?",
            ("hello",)).fetchall()
        self.assertEqual([r["path"] for r in rows], ["main.py"])

    def test_lfs_pointer_indexed_as_pointer_honestly(self):
        self.indexer.index_tip("volmarr", "anvil", self.c1)
        doc = self.indexer.document_for("volmarr", "anvil", "asset.bin")
        self.assertTrue(doc.is_pointer)
        self.assertEqual(doc.disposition, "index_pointer")
        self.assertEqual(doc.language, POINTER_LANGUAGE)
        self.assertEqual(doc.text, POINTER.decode())
        self.assertEqual(doc.lfs_oid, oid_for(POINTEE))
        self.assertEqual(doc.lfs_size, len(POINTEE))
        self.assertEqual(doc.blob_size, len(POINTER))
        self.assertNotIn("pretend large file", doc.text)
        snap = self.indexer.snapshot("volmarr", "anvil", self.c1)
        self.assertEqual(doc.digest, snap["asset.bin"].oid)

    def test_snapshot_modes_and_nesting(self):
        snap = self.indexer.snapshot("volmarr", "anvil", self.c1)
        self.assertEqual(snap["src/lib.py"].mode, "100644")
        self.assertEqual(snap["run.sh"].mode, "100755")
        self.assertIn("asset.bin", snap)
        self.assertEqual(len(snap), 10)

    # -- delta law ----------------------------------------------
    def test_delta_indexes_only_changed_blobs(self):
        self.indexer.index_tip("volmarr", "anvil", self.c1)
        self._write("main.py", b"print('hello again')\n")
        self._write("new.py", b"NEW = 1\n")
        (self.work / "notes.txt").unlink()
        c2 = self._commit("second")
        report = self.indexer.index_tip("volmarr", "anvil", c2)
        self.assertEqual(report.previous_oid, self.c1)
        self.assertEqual(
            [o.path for o in report.outcomes],
            ["main.py", "new.py", "notes.txt"])
        self.assertEqual(report.indexed, 2)
        self.assertEqual(report.removed, 1)
        self.assertEqual(
            self._file_outcome(report, "notes.txt").reason, "deleted")
        self.assertEqual(report.unchanged, 8)
        self.assertIsNone(
            self.indexer.document_for("volmarr", "anvil", "notes.txt"))
        lib = self.indexer.document_for(
            "volmarr", "anvil", "src/lib.py")
        self.assertEqual(lib.commit_oid, self.c1)
        main = self.indexer.document_for("volmarr", "anvil", "main.py")
        self.assertEqual(main.text, "print('hello again')\n")
        self.assertEqual(main.commit_oid, c2)
        self.assertEqual(
            len(self.indexer.documents_for("volmarr", "anvil")), 6)

    def test_same_tip_reindex_is_a_noop(self):
        self.indexer.index_tip("volmarr", "anvil", self.c1)
        again = self.indexer.index_tip("volmarr", "anvil", self.c1)
        self.assertEqual(again.outcomes, ())
        self.assertEqual(again.unchanged, 10)
        self.assertEqual(
            len(self.indexer.documents_for("volmarr", "anvil")), 6)

    def test_changed_to_binary_drops_the_old_row(self):
        self.indexer.index_tip("volmarr", "anvil", self.c1)
        self._write("main.py", b"\x00\x01now binary")
        (self.work / "src" / "lib.py").unlink()
        c2 = self._commit("third")
        report = self.indexer.index_tip("volmarr", "anvil", c2)
        outcome = self._file_outcome(report, "main.py")
        self.assertEqual((outcome.disposition, outcome.reason),
                         ("skip", "binary"))
        self.assertEqual(
            self._file_outcome(report, "src/lib.py").disposition, "removed")
        self.assertIsNone(
            self.indexer.document_for("volmarr", "anvil", "main.py"))
        self.assertIsNone(
            self.indexer.document_for("volmarr", "anvil", "src/lib.py"))
        registered = self.registry.documents_for(
            "volmarr", "anvil", kind="code")
        self.assertNotIn("code:main.py",
                         [d.doc_key for d in registered])

    def test_gitignore_change_rejudges_the_snapshot(self):
        self.indexer.index_tip("volmarr", "anvil", self.c1)
        self._write(".gitignore", b"*.log\nnotes.txt\n")
        c2 = self._commit("ignore notes")
        report = self.indexer.index_tip("volmarr", "anvil", c2)
        self.assertEqual(report.unchanged, 0)
        outcome = self._file_outcome(report, "notes.txt")
        self.assertEqual((outcome.disposition, outcome.reason),
                         ("skip", "ignored"))
        self.assertIsNone(
            self.indexer.document_for("volmarr", "anvil", "notes.txt"))
        self.assertIsNotNone(
            self.indexer.document_for("volmarr", "anvil", "main.py"))

    def test_submodule_gitlink_is_skipped(self):
        run_git(self.work, "update-index", "--add", "--cacheinfo",
                f"160000,{self.c1},vendor/lib")
        run_git(self.work, "commit", "-m", "add submodule")
        run_git(self.work, "push", str(self.bare), "main")
        c2 = run_git(self.work, "rev-parse", "HEAD")
        snap = self.indexer.snapshot("volmarr", "anvil", c2)
        self.assertEqual(snap["vendor/lib"].mode, "160000")
        self.assertTrue(snap["vendor/lib"].is_submodule)
        report = self.indexer.index_repository("volmarr", "anvil")
        outcome = self._file_outcome(report, "vendor/lib")
        self.assertEqual((outcome.disposition, outcome.reason),
                         ("skip", "submodule"))
        self.assertIsNone(self.indexer.document_for(
            "volmarr", "anvil", "vendor/lib"))

    def test_symlink_indexes_its_target_text(self):
        os.symlink("main.py", self.work / "link.txt")
        c2 = self._commit("link")
        snap = self.indexer.snapshot("volmarr", "anvil", c2)
        self.assertEqual(snap["link.txt"].mode, "120000")
        self.indexer.index_tip("volmarr", "anvil", c2)
        doc = self.indexer.document_for("volmarr", "anvil", "link.txt")
        self.assertIsNotNone(doc)
        self.assertEqual(doc.text, "main.py")

    # -- push trigger ---------------------------------------------
    def test_index_push_only_default_branch_moves(self):
        topic = RefUpdate(ref="refs/heads/topic",
                          old_oid=ZERO, new_oid=self.c1)
        self.assertIsNone(
            self.indexer.index_push("volmarr", "anvil", [topic]))
        self.assertEqual(
            self.indexer.documents_for("volmarr", "anvil"), ())
        create = RefUpdate(ref="refs/heads/main",
                           old_oid=ZERO, new_oid=self.c1)
        report = self.indexer.index_push("volmarr", "anvil", [create])
        self.assertIsNotNone(report)
        self.assertEqual(report.indexed, 5)
        self.assertEqual(report.pointers, 1)
        delete = RefUpdate(ref="refs/heads/main",
                           old_oid=self.c1, new_oid=ZERO)
        cleared = self.indexer.index_push("volmarr", "anvil", [delete])
        self.assertEqual(cleared.removed, 6)
        self.assertEqual(cleared.commit_oid, "")
        self.assertEqual(
            self.indexer.documents_for("volmarr", "anvil"), ())
        self.assertEqual(self.registry.documents_for(
            "volmarr", "anvil", kind="code"), ())

    # -- rebuild --------------------------------------------------
    def test_rebuild_converges_and_drops_stale_rows(self):
        first = self.indexer.index_repository("volmarr", "anvil")
        self.assertEqual(first.commit_oid, self.c1)
        self.assertEqual(first.indexed, 5)
        before = self.indexer.documents_for("volmarr", "anvil")
        with self.conn:
            self.conn.execute(
                "INSERT INTO code_fts (path, text, repo_id,"
                " commit_oid, digest, language, disposition,"
                " lfs_oid, lfs_size, blob_size)"
                " VALUES ('ghost.py', 'ghost', ?, ?, 'x', 'python',"
                " 'index', '', 0, 5)",
                (before[0].repo_id, self.c1))
        self.registry.put_document(
            "volmarr", "anvil", kind="code", doc_key="code:ghost.py",
            commit_oid=self.c1, path="ghost.py", digest="x")
        rebuilt = self.indexer.rebuild_repository("volmarr", "anvil")
        self.assertEqual(
            self._file_outcome(rebuilt, "ghost.py").disposition, "removed")
        after = self.indexer.documents_for("volmarr", "anvil")
        self.assertEqual(after, before)
        self.assertIsNone(self.indexer.document_for(
            "volmarr", "anvil", "ghost.py"))
        self.assertNotIn("code:ghost.py", [d.doc_key for d in
                         self.registry.documents_for(
                             "volmarr", "anvil", kind="code")])
        again = self.indexer.rebuild_repository("volmarr", "anvil")
        self.assertEqual(
            self.indexer.documents_for("volmarr", "anvil"), before)
        self.assertEqual(again.removed, 0)

    def test_remove_repository_purges_rows_and_registry(self):
        self.indexer.index_tip("volmarr", "anvil", self.c1)
        self.assertEqual(
            self.indexer.remove_repository("volmarr", "anvil"), 6)
        self.assertEqual(
            self.indexer.documents_for("volmarr", "anvil"), ())
        self.assertEqual(self.registry.documents_for(
            "volmarr", "anvil", kind="code"), ())

    # -- refusal law ------------------------------------------------
    def test_damaged_repository_refuses_loudly_index_untouched(self):
        self.indexer.index_tip("volmarr", "anvil", self.c1)
        before = self.indexer.documents_for("volmarr", "anvil")
        self.assertEqual(
            self._reason(self.indexer.index_tip,
                         "volmarr", "anvil", "f" * 40),
            "object_not_found")
        self.assertEqual(
            self._reason(self.indexer.index_tip,
                         "volmarr", "anvil", "not-an-oid"),
            "oid_invalid")
        self.assertEqual(
            self._reason(self.indexer.index_tip,
                         "volmarr", "anvil", ""),
            "commit_not_found")
        self.assertEqual(
            self._reason(self.indexer.documents_for,
                         "volmarr", "nope"),
            "repo_not_found")
        self.assertEqual(
            self.indexer.documents_for("volmarr", "anvil"), before)

    def test_empty_repository_has_no_snapshot_to_index(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "empty", visibility="public")
        self.assertEqual(
            self._reason(self.indexer.index_repository,
                         "volmarr", "empty"),
            "commit_not_found")

    def test_indexing_writes_no_audit_event(self):
        before = self._audit_count()
        self.indexer.index_tip("volmarr", "anvil", self.c1)
        self.indexer.rebuild_repository("volmarr", "anvil")
        self.assertEqual(self._audit_count(), before)

    # -- rendering ---------------------------------------------------
    def test_render_page_says_verdicts_in_words(self):
        report = self.indexer.index_tip("volmarr", "anvil", self.c1)
        page = render_code_index_page(report)
        self.assertIn("Code index — volmarr/anvil", page)
        self.assertIn("5 files indexed", page)
        self.assertIn("1 LFS pointers indexed as pointers", page)
        self.assertIn("indexed as an LFS pointer", page)
        self.assertIn("skipped (binary)", page)
        self.assertIn("skipped (oversized)", page)
        self.assertIn("skipped (ignored)", page)
        self.assertIn("skipped (empty)", page)

    def test_render_page_escapes_paths(self):
        self._write("x<y>.txt", b"angle\n")
        c2 = self._commit("angle")
        report = self.indexer.index_tip("volmarr", "anvil", c2)
        page = render_code_index_page(report)
        self.assertIn("x&lt;y&gt;.txt", page)
        self.assertNotIn("x<y>.txt", page)


if __name__ == "__main__":
    unittest.main()
