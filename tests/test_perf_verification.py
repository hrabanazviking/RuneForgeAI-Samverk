"""S-395 acceptance battery: performance verification.

Acceptance (roadmap S-395): clone/search/browse budgets
(S-073, S-217) re-measured on Pi-class hardware and
published with the numbers.

This battery proves the verification machinery on the
hardware it runs on and claims only that class: the
publication carries the run's raw clone seconds, search
p95s and browse p95 against their stated budgets, marks
every unmeasured class NOT PROVEN, and refuses to blend
classes or to publish nothing. The Pi-class numbers
themselves are the verification run's, published in
docs/perf-verification-s395.md — measured there, not
asserted here (the S-073 honesty law).

Counted with: python3 -m unittest tests.test_perf_verification
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.code_indexing import CodeIndexer
from samverk.code_search import CodeSearch
from samverk.file_browser import BrowseError, FileBrowser
from samverk.perf_verification import (
    BROWSE_BUDGETS_MS, PerfError, browse_budget_for, measure_browse,
    publication, render_perf_page)
from samverk.repo_budgets import CloneMeasurement, hardware_class, measure_local_clone
from samverk.repositories import RepositoryStore
from samverk.search_budgets import (
    LatencySummary, QueryMeasurement, measure_searches, summarise)
from test_repo_home import GIT_ENV, run_git

PW = "correct horse battery"


def make_world(root: Path) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    accounts = AccountStore(conn)
    owner = accounts.register("volmarr", PW)
    stranger = accounts.register("mallory", PW)
    repos = RepositoryStore(conn, root, accounts)
    indexer = CodeIndexer(conn, repos)
    files = [("src/a.py", "# samverk alpha\n"),
             ("src/b.py", "# samverk beta quixotic-anvil-7\n"),
             ("src/c.py", "# samverk gamma\n")]
    repos.create_repository(owner.id, "volmarr", "mirror-00",
                            visibility="public", description="ref")
    bare = repos.path_for("volmarr", "mirror-00")
    work = root / "work-mirror"; work.mkdir()
    run_git(work, "init", "-b", "main")
    for name, text in files:
        p = work / name; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    run_git(work, "add", "-A")
    env = dict(os.environ); env.update(GIT_ENV)
    out = subprocess.run(["git", "commit", "-m", "corpus"], cwd=work,
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr.decode()
    run_git(work, "push", str(bare), "main")
    indexer.index_repository("volmarr", "mirror-00")
    repos.create_repository(owner.id, "volmarr", "vault",
                            visibility="private", description="priv")
    bare = repos.path_for("volmarr", "vault")
    work = root / "work-vault"; work.mkdir()
    run_git(work, "init", "-b", "main")
    (work / "secret.py").write_text("# samverk secret\n", encoding="utf-8")
    run_git(work, "add", "-A")
    out = subprocess.run(["git", "commit", "-m", "secret"], cwd=work,
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr.decode()
    run_git(work, "push", str(bare), "main")
    indexer.index_repository("volmarr", "vault")
    return SimpleNamespace(conn=conn, owner=owner, stranger=stranger,
                           repos=repos, search=CodeSearch(conn, repos),
                           browser=FileBrowser(repos))


def fake_clone(cls="server_x86_64", within=True):
    return CloneMeasurement(
        source="s", dest="d", seconds=1.5, total_bytes=100,
        file_count=3, hardware_class=cls, machine="x86_64",
        budget_seconds=30.0, within_budget=within)


def fake_search(cls="server_x86_64"):
    return QueryMeasurement(
        kind="substring", pattern="samverk", total_files=3,
        total_matches=3, summary=summarise([1.0, 2.0, 3.0]),
        hardware_class=cls, machine="x86_64", budget_ms=1000.0,
        within_budget=True)


class PureLawTests(unittest.TestCase):
    def test_browse_budgets_stated_per_class(self):
        for cls in ("server_x86_64", "laptop_x86_64", "pi_class_arm"):
            self.assertEqual(browse_budget_for(cls), BROWSE_BUDGETS_MS[cls])
            self.assertGreater(BROWSE_BUDGETS_MS[cls], 0)

    def test_browse_budget_unknown_class_refused(self):
        with self.assertRaises(PerfError) as ctx:
            browse_budget_for("quantum_class")
        self.assertEqual(ctx.exception.reason, "budget_unknown")

    def test_publication_empty_refused(self):
        with self.assertRaises(PerfError) as ctx:
            publication()
        self.assertEqual(ctx.exception.reason, "measurements_empty")

    def test_publication_class_mismatch_refused(self):
        with self.assertRaises(PerfError) as ctx:
            publication(clone=fake_clone(),
                        searches=(fake_search(cls="pi_class_arm"),))
        self.assertEqual(ctx.exception.reason, "class_mismatch")

    def test_publication_marks_other_classes_unmeasured(self):
        pub = publication(clone=fake_clone(), searches=(fake_search(),))
        self.assertEqual(pub["hardware_class"], "server_x86_64")
        self.assertEqual(pub["classes"]["server_x86_64"]["status"], "measured")
        self.assertTrue(pub["classes"]["server_x86_64"]["within_budget"])
        for other in ("laptop_x86_64", "pi_class_arm"):
            self.assertEqual(pub["classes"][other]["status"], "unmeasured")
            self.assertIsNone(pub["classes"][other]["within_budget"])
        kinds = [e["kind"] for e in pub["entries"]]
        self.assertEqual(kinds, ["clone", "search"])

    def test_render_publishes_numbers_and_not_proven(self):
        pub = publication(clone=fake_clone(), searches=(fake_search(),))
        page = render_perf_page(pub)
        self.assertIn("1.50 s", page)
        self.assertIn("NOT PROVEN", page)
        self.assertIn("within budget", page)

    def test_render_escapes_values(self):
        m = QueryMeasurement(
            kind="substring", pattern="<b>samverk</b>", total_files=1,
            total_matches=1, summary=summarise([1.0]),
            hardware_class="server_x86_64", machine="<x>",
            budget_ms=1000.0, within_budget=True)
        page = render_perf_page(publication(searches=(m,)))
        self.assertNotIn("<b>samverk</b>", page)
        self.assertIn("&lt;b&gt;", page)


class MeasuredTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.world = make_world(Path(self._tmp.name))

    def test_measure_browse_real(self):
        m = measure_browse(self.world.browser, self.world.owner,
                           "volmarr", "mirror-00", repetitions=2)
        self.assertEqual(m.repo, "volmarr/mirror-00")
        self.assertEqual(m.entries, 1)  # root holds only src/
        self.assertEqual(m.hardware_class, hardware_class())
        self.assertEqual(m.summary.count, 2)
        self.assertIsInstance(m.within_budget, bool)

    def test_measure_browse_bad_repetitions_refused(self):
        with self.assertRaises(PerfError) as ctx:
            measure_browse(self.world.browser, self.world.owner,
                           "volmarr", "mirror-00", repetitions=0)
        self.assertEqual(ctx.exception.reason, "repetitions_invalid")

    def test_stranger_browse_of_private_repo_refused_not_timed(self):
        with self.assertRaises(BrowseError):
            measure_browse(self.world.browser, self.world.stranger,
                           "volmarr", "vault", repetitions=1)

    def test_full_publication_from_real_measurements(self):
        searches = measure_searches(self.world.search, self.world.owner,
                                    repetitions=2)
        browse = measure_browse(self.world.browser, self.world.owner,
                                "volmarr", "mirror-00", repetitions=2)
        bare = self.world.repos.path_for("volmarr", "mirror-00")
        clone = measure_local_clone(bare, Path(self._tmp.name) / "clone-out")
        pub = publication(clone=clone, searches=searches, browse=browse)
        self.assertEqual([e["kind"] for e in pub["entries"]],
                         ["clone", "search", "search", "search", "browse"])
        self.assertEqual(pub["classes"][hardware_class()]["status"], "measured")
        page = render_perf_page(pub)
        self.assertIn("clone:", page)
        self.assertIn("browse of volmarr/mirror-00", page)


if __name__ == "__main__":
    unittest.main()
