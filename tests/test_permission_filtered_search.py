"""S-209 acceptance battery: permission-filtered results.

Acceptance (roadmap S-209): Permission-filtered
results — search never reveals a title, snippet,
or count from a repo the searcher cannot read;
leakage battery included.

The planted secret is deliberate bait: a private
repository whose code and issue carry unique
tokens (`zorblax`) plus extra `quill` matches, so
any post-hoc filtering — hits removed after
counting, snippets trimmed after reading — moves
a number or a string this battery watches. The
centre of the battery is the equivalence proof: a
stranger's hits and counts over a world WITH the
private repository equal, exactly, the same
search over a world where it was never created.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.code_indexing import CodeIndexer
from samverk.code_search import (
    CodeSearch, CodeSearchError, render_code_search_page)
from samverk.db import schema_version
from samverk.index_architecture import SearchIndexStore
from samverk.issue_pr_search import (
    IssuePRSearch, SearchBackendError, render_backend_search_page)
from samverk.issues import IssueStore
from samverk.repositories import RepositoryStore
from samverk.search_permissions import (
    may_read, tally_code_hits, visible_repositories)
from test_repo_home import run_git

PUB_CODE = b"quill one\nquill two quill\nplain\n"
SECRET_CODE = b"zorblax quill\nzorblax zorblax\n"

def make_world(root: Path, with_secret: bool) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    accounts = AccountStore(conn)
    owner = accounts.register("volmarr", "correct horse battery")
    stranger = accounts.register("mallory", "correct horse battery")
    repos = RepositoryStore(conn, root, accounts)
    audit = AuditLog(conn)
    issues = IssueStore(conn, repos, accounts, audit=audit)
    indexer = CodeIndexer(conn, repos)
    w = SimpleNamespace(
        conn=conn, accounts=accounts, owner=owner, stranger=stranger,
        repos=repos, issues=issues, indexer=indexer,
        code=CodeSearch(conn, repos),
        backend=IssuePRSearch(conn, repos, SearchIndexStore(conn, repos)))
    repos.create_repository(owner.id, "volmarr", "anvil",
                            visibility="public")
    _fill_code(w, root, "anvil", {"pub.py": PUB_CODE,
                                  "other.py": b"nothing here\n"})
    issues.create_issue(owner, "volmarr", "anvil",
                        "Quill failure", "the quill broke")
    if with_secret:
        repos.create_repository(owner.id, "volmarr", "vault",
                                visibility="private")
        _fill_code(w, root, "vault", {"secret.py": SECRET_CODE})
        issues.create_issue(owner, "volmarr", "vault",
                            "Zorblax master plan", "zorblax quill secrets")
    w.backend.index_all()
    return w


def _fill_code(w, root: Path, name: str, files: dict):
    bare = w.repos.path_for("volmarr", name)
    work = root / f"work-{name}"
    work.mkdir()
    run_git(work, "init", "-b", "main")
    for rel, data in files.items():
        (work / rel).write_bytes(data)
    run_git(work, "add", "-A")
    run_git(work, "commit", "-m", f"seed {name}")
    run_git(work, "push", str(bare), "main")
    w.indexer.index_repository("volmarr", name)

class LeakageBatteryTests(unittest.TestCase):
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

    # -- the one resolution -----------------------------------
    def test_visible_repositories_per_viewer(self):
        names = lambda v, w: [r.name for r in visible_repositories(w.conn, w.repos, v)]
        self.assertEqual(names(self.a.owner, self.a), ["anvil", "vault"])
        self.assertEqual(names(self.a.stranger, self.a), ["anvil"])
        self.assertEqual(names(None, self.a), ["anvil"])

    def test_may_read_truth_table(self):
        pub = self.a.repos.get_repository("volmarr", "anvil")
        priv = self.a.repos.get_repository("volmarr", "vault")
        self.assertTrue(may_read(self.a.owner, priv))
        self.assertTrue(may_read(self.a.stranger, pub))
        self.assertTrue(may_read(None, pub))
        self.assertFalse(may_read(self.a.stranger, priv))
        self.assertFalse(may_read(None, priv))

    def test_tally_code_hits_pure(self):
        fake = [SimpleNamespace(match_count=3, matched_lines=2),
                SimpleNamespace(match_count=4, matched_lines=1)]
        tally = tally_code_hits(fake)
        self.assertEqual((tally.files, tally.matches, tally.matched_lines), (2, 7, 3))
        empty = tally_code_hits([])
        self.assertEqual((empty.files, empty.matches, empty.matched_lines), (0, 0, 0))

    # -- code search: titles, snippets, counts -----------------
    def test_code_secret_token_invisible_to_stranger_and_anon(self):
        for viewer in (self.a.stranger, None):
            self.assertEqual(self.a.code.search(viewer, "zorblax"), [])
            res = self.a.code.search_counted(viewer, "zorblax")
            self.assertEqual(res.hits, ())
            self.assertEqual(
                (res.total_files, res.total_matches, res.total_matched_lines),
                (0, 0, 0))
            self.assertEqual(
                self.a.code.search(viewer, "zorb", mode="regex"), [])

    def test_code_counts_exclude_the_unreadable_repo(self):
        res = self.a.code.search_counted(self.a.stranger, "quill")
        self.assertEqual(
            (res.total_files, res.total_matches, res.total_matched_lines),
            (1, 3, 2))
        owner = self.a.code.search_counted(self.a.owner, "quill")
        self.assertEqual(
            (owner.total_files, owner.total_matches,
             owner.total_matched_lines), (2, 4, 3))
        secret = self.a.code.search_counted(self.a.owner, "zorblax")
        self.assertEqual(
            (secret.total_files, secret.total_matches,
             secret.total_matched_lines), (1, 3, 2))

    def test_code_equivalence_with_and_without_secret_repo(self):
        for pattern in ("quill", "zorblax"):
            ha = self.a.code.search_counted(self.a.stranger, pattern)
            hb = self.b.code.search_counted(self.b.stranger, pattern)
            key = lambda r: [(h.full_name, h.path, h.match_count,
                              h.matched_lines) for h in r.hits]
            self.assertEqual(key(ha), key(hb))
            self.assertEqual(
                (ha.total_files, ha.total_matches, ha.total_matched_lines),
                (hb.total_files, hb.total_matches, hb.total_matched_lines))

    def test_code_limit_caps_display_never_the_visible_count(self):
        res = self.a.code.search_counted(self.a.owner, "quill", limit=1)
        self.assertEqual(len(res.hits), 1)
        self.assertEqual(res.total_files, 2)
        res = self.a.code.search_counted(self.a.stranger, "quill", limit=1)
        self.assertEqual(len(res.hits), 1)
        self.assertEqual(res.total_files, 1)
        self.assertEqual(res.total_matches, 3)

    def test_code_counted_hits_match_plain_search(self):
        plain = self.a.code.search(self.a.stranger, "quill")
        counted = self.a.code.search_counted(self.a.stranger, "quill")
        self.assertEqual(list(counted.hits), plain)

    def test_code_scoped_unreadable_is_uniform_not_found(self):
        def attempt(owner, repo):
            try:
                self.a.code.search_repository(
                    self.a.stranger, owner, repo, "quill")
            except CodeSearchError as exc:
                return (exc.reason, str(exc))
            return None
        self.assertEqual(attempt("volmarr", "vault"),
                         attempt("volmarr", "ghost"))
        self.assertEqual(attempt("volmarr", "vault")[0], "repo_not_found")

    def test_code_rendered_page_carries_no_secret(self):
        hits = self.a.code.search(self.a.stranger, "quill")
        page = render_code_search_page("quill", hits)
        self.assertNotIn("zorblax", page)
        self.assertNotIn("vault", page)
        self.assertNotIn("secret.py", page)
        owner_page = render_code_search_page(
            "zorblax", self.a.code.search(self.a.owner, "zorblax"))
        self.assertIn("zorblax", owner_page)

    # -- issue/PR backend: titles and counts -------------------
    def test_backend_secret_title_invisible_and_uncounted(self):
        for viewer in (self.a.stranger, None):
            self.assertEqual(self.a.backend.search(viewer, "zorblax"), [])
            self.assertEqual(self.a.backend.count(viewer, "zorblax"), 0)
            res = self.a.backend.search_counted(viewer, "zorblax")
            self.assertEqual((res.hits, res.total), ((), 0))
        self.assertEqual(self.a.backend.count(self.a.owner, "zorblax"), 1)

    def test_backend_counts_exclude_the_unreadable_repo(self):
        self.assertEqual(self.a.backend.count(self.a.stranger, "quill"), 1)
        self.assertEqual(self.a.backend.count(self.a.owner, "quill"), 2)
        res = self.a.backend.search_counted(self.a.stranger, "quill")
        self.assertEqual(res.total, len(res.hits))
        self.assertEqual([h.title for h in res.hits], ["Quill failure"])

    def test_backend_equivalence_with_and_without_secret_repo(self):
        for query in ("quill", "zorblax"):
            ka = [(h.full_name, h.number, h.title)
                  for h in self.a.backend.search(self.a.stranger, query)]
            kb = [(h.full_name, h.number, h.title)
                  for h in self.b.backend.search(self.b.stranger, query)]
            self.assertEqual(ka, kb)
            self.assertEqual(self.a.backend.count(self.a.stranger, query),
                             self.b.backend.count(self.b.stranger, query))

    def test_backend_scoped_unreadable_is_uniform_not_found(self):
        def attempt(owner, repo):
            try:
                self.a.backend.search_repository(
                    self.a.stranger, owner, repo, "quill")
            except SearchBackendError as exc:
                return (exc.reason, str(exc))
            return None
        self.assertEqual(attempt("volmarr", "vault"),
                         attempt("volmarr", "ghost"))
        self.assertEqual(attempt("volmarr", "vault")[0], "repo_not_found")

    def test_backend_rendered_page_carries_no_secret(self):
        hits = self.a.backend.search(self.a.stranger, "quill")
        page = render_backend_search_page("quill", hits)
        self.assertNotIn("Zorblax", page)
        self.assertNotIn("vault", page)
        owner_page = render_backend_search_page(
            "zorblax", self.a.backend.search(self.a.owner, "zorblax"))
        self.assertIn("Zorblax master plan", owner_page)

    def test_backend_counted_faces_agree(self):
        res = self.a.backend.search_counted(self.a.owner, "quill")
        self.assertEqual(list(res.hits),
                         self.a.backend.search(self.a.owner, "quill"))
        self.assertEqual(res.total, 2)

    # -- searching writes nothing -------------------------------
    def test_filtered_searches_write_nothing(self):
        w = self.a
        before = (
            w.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"],
            w.conn.execute("SELECT COUNT(*) c FROM code_fts").fetchone()["c"],
            w.conn.execute("SELECT COUNT(*) c FROM issue_pr_fts").fetchone()["c"])
        w.code.search_counted(w.stranger, "quill")
        w.code.search_counted(w.owner, "zorblax")
        w.backend.search_counted(w.stranger, "quill")
        w.backend.count(None, "zorblax")
        after = (
            w.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"],
            w.conn.execute("SELECT COUNT(*) c FROM code_fts").fetchone()["c"],
            w.conn.execute("SELECT COUNT(*) c FROM issue_pr_fts").fetchone()["c"])
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
