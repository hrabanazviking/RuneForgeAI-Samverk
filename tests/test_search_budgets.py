"""S-217 acceptance battery: performance budget.

Acceptance (roadmap S-217): reference corpus (the
instance's own mirrored repos, Part XVII) searched
within the stated latency budget on Pi-class
hardware; measured, not asserted.

The measurement is taken on the hardware it runs
on and claims only that class: the Pi-class cell is
NOT PROVEN here — it is stated in the code, marked
unmeasured in the report and on the page, and
S-395/S-413 own its proof (the S-073 honesty law).

The planted secret is deliberate bait, in the S-209
shape: a private repository (`vault`) whose only
code file carries both planted needles, so any
leak channel — a timed search reading past the
permission filter — moves a count this battery
watches. The centre is the equivalence: a
stranger's measured totals over a world WITH the
private repository equal the totals over the
reference corpus alone.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.code_indexing import CodeIndexer
from samverk.code_search import CodeSearch
from samverk.db import schema_version
from samverk.repositories import RepositoryStore
from samverk.search_budgets import (
    HARDWARE_CLASSES, MEASURED_QUERIES, NEEDLE_COMMON, NEEDLE_RARE,
    QUERY_KINDS, REFERENCE_FILES_PER_REPO, REFERENCE_REPOS,
    SEARCH_BUDGETS_MS, SearchBudgetError, budget_for, budget_report,
    corpus_files, corpus_spec, judge, measure_searches, percentile,
    render_search_budget_page, summarise)
from test_repo_home import GIT_ENV, run_git

PW = "correct horse battery"


def commit(work, files, author, when):
    for name, text in files:
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    run_git(work, "add", "-A")
    env = dict(os.environ); env.update(GIT_ENV)
    env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = author
    env["GIT_COMMITTER_NAME"], env["GIT_COMMITTER_EMAIL"] = author
    env["GIT_AUTHOR_DATE"] = str(when)
    env["GIT_COMMITTER_DATE"] = str(when)
    out = subprocess.run(
        ["git", "commit", "-m", "mirror corpus", "-m", "reference"],
        cwd=work, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return run_git(work, "rev-parse", "HEAD")


def make_world(root: Path) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    accounts = AccountStore(conn)
    owner = accounts.register("volmarr", PW)
    stranger = accounts.register("mallory", PW)
    repos = RepositoryStore(conn, root, accounts)
    indexer = CodeIndexer(conn, repos)
    search = CodeSearch(conn, repos)
    by_repo = {}
    for repo, path, text in corpus_files():
        by_repo.setdefault(repo, []).append((path, text))
    author = ("A U Thor", "a@example.com")
    for repo, files in sorted(by_repo.items()):
        repos.create_repository(
            owner.id, "volmarr", repo, visibility="public",
            description=f"Mirror corpus {repo}")
        bare = repos.path_for("volmarr", repo)
        work = root / ("work-" + repo); work.mkdir()
        run_git(work, "init", "-b", "main")
        commit(work, files, author, 1700000100)
        run_git(work, "push", str(bare), "main")
        indexer.index_repository("volmarr", repo)
    # The planted secret: a private mirror whose only file
    # carries both needles, so a leak moves a count.
    repos.create_repository(
        owner.id, "volmarr", "vault", visibility="private",
        description="private mirror")
    bare = repos.path_for("volmarr", "vault")
    work = root / "work-vault"; work.mkdir()
    run_git(work, "init", "-b", "main")
    commit(work, [("secret.py",
                   f"# {NEEDLE_COMMON} secret {NEEDLE_RARE}\n")],
           author, 1700000200)
    run_git(work, "push", str(bare), "main")
    indexer.index_repository("volmarr", "vault")
    return SimpleNamespace(
        conn=conn, accounts=accounts, owner=owner, stranger=stranger,
        repos=repos, search=search)


class PureLawTests(unittest.TestCase):
    def test_corpus_spec_is_the_stated_shape(self):
        spec = corpus_spec()
        self.assertEqual(spec.repos, REFERENCE_REPOS)
        self.assertEqual(spec.files,
                         REFERENCE_REPOS * REFERENCE_FILES_PER_REPO)
        self.assertEqual(spec.common_files, spec.files)
        self.assertEqual(spec.rare_files, 1)
        self.assertGreater(spec.total_bytes, 0)
        self.assertGreater(spec.lines, 0)

    def test_corpus_generation_is_deterministic(self):
        self.assertEqual(corpus_files(), corpus_files())
        rare = [(r, p) for r, p, t in corpus_files()
                if NEEDLE_RARE in t]
        self.assertEqual(rare, [("mirror-00", "src/module_000.py")])

    def test_budgets_stated_for_every_class_and_kind(self):
        for cls in HARDWARE_CLASSES:
            self.assertIn(cls, SEARCH_BUDGETS_MS)
            for kind in QUERY_KINDS:
                self.assertGreater(budget_for(cls, kind), 0)

    def test_budget_for_refuses_unknown_class_and_kind(self):
        with self.assertRaises(SearchBudgetError) as caught:
            budget_for("quantum", "substring")
        self.assertEqual(caught.exception.reason, "budget_unknown")
        with self.assertRaises(SearchBudgetError) as caught:
            budget_for("pi_class_arm", "semantic")
        self.assertEqual(caught.exception.reason,
                         "query_kind_unknown")

    def test_percentile_nearest_rank_law(self):
        samples = [10.0, 20.0, 30.0, 40.0, 100.0]
        self.assertEqual(percentile(samples, 0), 10.0)
        self.assertEqual(percentile(samples, 50), 30.0)
        self.assertEqual(percentile(samples, 95), 100.0)
        self.assertEqual(percentile(samples, 100), 100.0)

    def test_percentile_and_summarise_refuse_empty(self):
        for fn in (lambda: percentile([], 50), lambda: summarise([])):
            with self.assertRaises(SearchBudgetError) as caught:
                fn()
            self.assertEqual(caught.exception.reason, "samples_empty")

    def test_summarise_reports_the_raw_truth(self):
        summary = summarise([10.0, 20.0, 30.0, 40.0, 100.0])
        self.assertEqual(summary.count, 5)
        self.assertEqual(summary.minimum_ms, 10.0)
        self.assertEqual(summary.mean_ms, 40.0)
        self.assertEqual(summary.p50_ms, 30.0)
        self.assertEqual(summary.p95_ms, 100.0)
        self.assertEqual(summary.maximum_ms, 100.0)

    def test_judge_is_p95_against_the_stated_budget(self):
        summary = summarise([10.0, 20.0, 30.0, 40.0, 100.0])
        self.assertTrue(judge(summary, 100.0))
        self.assertFalse(judge(summary, 99.0))
        with self.assertRaises(SearchBudgetError) as caught:
            judge(summary, 0.0)
        self.assertEqual(caught.exception.reason, "budget_unknown")

    def test_measure_refuses_bad_repetitions(self):
        with self.assertRaises(SearchBudgetError) as caught:
            measure_searches(None, None, repetitions=0)
        self.assertEqual(caught.exception.reason,
                         "repetitions_invalid")


class MeasuredBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.w = make_world(Path(cls._tmp.name))
        cls.spec = corpus_spec()
        cls.owner_measurements = measure_searches(
            cls.w.search, cls.w.owner, repetitions=5)
        cls.stranger_measurements = measure_searches(
            cls.w.search, cls.w.stranger, repetitions=5)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _by_pattern(self, measurements, pattern):
        for m in measurements:
            if m.pattern == pattern:
                return m
        self.fail(f"no measurement for {pattern!r}")

    # -- pins ------------------------------------------------
    def test_pins_schema_99_taxonomy_133(self):
        self.assertEqual(schema_version(self.w.conn), 115)
        self.assertEqual(db.MIGRATIONS[-1][0], 115)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    # -- the measurement itself --------------------------
    def test_every_measured_query_was_timed(self):
        self.assertEqual(
            [(m.kind, m.pattern) for m in self.owner_measurements],
            list(MEASURED_QUERIES))
        for m in self.owner_measurements:
            self.assertEqual(m.summary.count, 5)
            self.assertGreater(m.summary.maximum_ms, 0)
            self.assertEqual(m.budget_ms,
                             budget_for(m.hardware_class, m.kind))

    def test_substring_common_within_budget_here(self):
        m = self._by_pattern(self.owner_measurements, NEEDLE_COMMON)
        self.assertTrue(m.within_budget, m)
        self.assertLessEqual(m.summary.p95_ms, m.budget_ms)
        # Owner sees the corpus plus the private vault file.
        self.assertEqual(m.total_files, self.spec.files + 1)

    def test_substring_rare_within_budget_here(self):
        m = self._by_pattern(self.owner_measurements, NEEDLE_RARE)
        self.assertTrue(m.within_budget, m)
        self.assertEqual(m.total_files, 2)  # corpus file + vault

    def test_regex_within_budget_here(self):
        regex = [m for m in self.owner_measurements
                 if m.kind == "regex"]
        self.assertEqual(len(regex), 1)
        self.assertTrue(regex[0].within_budget, regex[0])
        self.assertEqual(regex[0].total_files, 2)

    # -- permission at speed -----------------------------
    def test_stranger_totals_equal_the_corpus_alone(self):
        common = self._by_pattern(
            self.stranger_measurements, NEEDLE_COMMON)
        self.assertEqual(common.total_files, self.spec.files)
        rare = self._by_pattern(
            self.stranger_measurements, NEEDLE_RARE)
        self.assertEqual(rare.total_files, self.spec.rare_files)
        self.assertTrue(common.within_budget, common)

    # -- the report and the page -------------------------
    def test_report_marks_only_the_measured_class(self):
        report = budget_report(self.owner_measurements, self.spec)
        measured = self.owner_measurements[0].hardware_class
        for cls in HARDWARE_CLASSES:
            entry = report["classes"][cls]
            if cls == measured:
                self.assertEqual(entry["status"], "measured")
                self.assertTrue(entry["within_budget"])
            else:
                self.assertEqual(entry["status"], "unmeasured")
                self.assertIsNone(entry["within_budget"])
        if measured != "pi_class_arm":
            self.assertEqual(report["classes"]["pi_class_arm"]["status"],
                             "unmeasured")
        self.assertEqual(report["corpus"]["files"], self.spec.files)
        self.assertEqual(len(report["queries"]), len(MEASURED_QUERIES))
        text = json.dumps(report)
        self.assertEqual(json.loads(text), report)

    def test_page_states_corpus_verdicts_and_unproven(self):
        report = budget_report(self.owner_measurements, self.spec)
        page = render_search_budget_page(report)
        self.assertIn("Reference corpus", page)
        self.assertIn(str(self.spec.files), page)
        self.assertIn("within budget", page)
        self.assertIn("NOT PROVEN", page)
        self.assertIn("pi_class_arm", page)

    def test_page_escapes_a_hostile_pattern(self):
        report = budget_report(self.owner_measurements, self.spec)
        report["queries"][0]["pattern"] = "<script>alert(1)</script>"
        page = render_search_budget_page(report)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)


if __name__ == "__main__":
    unittest.main()
