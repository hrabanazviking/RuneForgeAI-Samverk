"""S-166 acceptance battery: large-PR behaviour.

Acceptance (roadmap S-166): diffs beyond budget fold by
file with honest totals; review remains possible
per-file.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.issues import IssueStore
from samverk.pull_request_files import PullRequestFilesStore
from samverk.pull_request_large import (
    DEFAULT_BUDGET_LINES, PullRequestLargeStore,
    render_large_file_page, render_large_files_page)
from samverk.pull_requests import PullRequestError, PullRequestStore
from samverk.repositories import RepositoryStore


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_commit(repo, parent, files, message):
    lines = []
    for name in sorted(files):
        content = files[name]
        blob = git(repo, "hash-object", "-w", "--stdin",
                   input_bytes=content if isinstance(content, bytes)
                   else content.encode())
        lines.append(f"100644 blob {blob}\t{name}\n")
    tree = git(repo, "mktree", input_bytes="".join(lines).encode())
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


def block(name, count):
    return "".join(f"{name} line {i}\n" for i in range(count))


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class PullRequestLargeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.files = PullRequestFilesStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.large = PullRequestLargeStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.base_path = self.repos.path_for("volmarr", "pub")

    def _pr(self, files, repo="pub", base_files=None):
        path = self.repos.path_for("volmarr", repo)
        base = make_commit(path, None, base_files or {}, "base commit")
        git(path, "update-ref", "refs/heads/main", base)
        head = make_commit(path, base, files, "feature work")
        git(path, "update-ref", "refs/heads/feature", head)
        return self.prs.create_pull_request(
            self.owner, "volmarr", repo, base_branch="main",
            head_branch="feature")

    def _three_file_pr(self):
        # a.txt: 10 added lines, b.txt: 10, c.txt: 10; each
        # patch also carries hunk/header lines, so counts are
        # read from the view itself rather than assumed.
        return self._pr({"a.txt": block("a", 10),
                         "b.txt": block("b", 10),
                         "c.txt": block("c", 10)})

    # -- under budget ------------------------------------------------------
    def test_small_pr_shows_everything(self):
        pr = self._three_file_pr()
        view = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number)
        self.assertFalse(view.is_large)
        self.assertEqual(view.folded_files, 0)
        self.assertEqual(view.shown_files, 3)
        self.assertEqual(view.budget_lines, DEFAULT_BUDGET_LINES)
        self.assertEqual(view.total_patch_lines, view.shown_patch_lines)
        self.assertIn("every file shown in full", view.summary_words)
        for item in view.files:
            self.assertFalse(item.folded)
            self.assertEqual(item.fold_words, "Shown in full")

    def test_totals_match_the_files_view(self):
        pr = self._three_file_pr()
        plain = self.files.files_for(self.reader, "volmarr", "pub", pr.number)
        view = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number, budget_lines=5)
        self.assertEqual(view.additions, plain.additions)
        self.assertEqual(view.deletions, plain.deletions)
        self.assertEqual(view.total_files, plain.total_files)
        self.assertEqual(
            view.total_patch_lines,
            sum(len(f.file.lines) for f in plain.files))

    # -- folding -------------------------------------------------------------
    def test_files_beyond_budget_fold_in_diff_order(self):
        pr = self._three_file_pr()
        probe = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number)
        per_file = probe.files[0].patch_lines
        view = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number,
            budget_lines=per_file)
        self.assertTrue(view.is_large)
        self.assertEqual([f.folded for f in view.files],
                         [False, True, True])
        self.assertEqual(view.shown_files, 1)
        self.assertEqual(view.folded_files, 2)
        self.assertEqual(view.shown_patch_lines, per_file)

    def test_file_landing_exactly_on_budget_still_shows(self):
        pr = self._three_file_pr()
        probe = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number)
        per_file = probe.files[0].patch_lines
        view = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number,
            budget_lines=per_file * 2)
        self.assertEqual([f.folded for f in view.files],
                         [False, False, True])

    def test_single_file_past_budget_folds_on_its_own(self):
        pr = self._pr({"big.txt": block("big", 30)})
        probe = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number)
        lines = probe.files[0].patch_lines
        view = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number,
            budget_lines=lines - 1)
        self.assertEqual([f.folded for f in view.files], [True])
        self.assertEqual(view.shown_patch_lines, 0)
        self.assertEqual(view.total_patch_lines, lines)

    def test_folded_totals_are_the_true_totals(self):
        pr = self._three_file_pr()
        view = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number, budget_lines=1)
        self.assertEqual(view.folded_files, 3)
        self.assertEqual(view.additions, 30)
        self.assertEqual(view.deletions, 0)
        self.assertIn("3 files folded", view.summary_words)
        self.assertIn("count in full", view.summary_words)

    def test_binary_file_is_counted_and_named_not_folded_by_lines(self):
        pr = self._pr({"a.txt": block("a", 10),
                       "bin.dat": b"\x00\x01\x02binary\x00"})
        view = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number)
        by = {f.path: f for f in view.files}
        self.assertTrue(by["bin.dat"].entry.file.is_binary)
        self.assertEqual(by["bin.dat"].patch_lines, 0)
        self.assertFalse(by["bin.dat"].folded)
        page = render_large_files_page(view)
        self.assertIn("Binary file", page)
        # Past the budget a binary file folds like any other,
        # and still counts in the totals at its true zero lines.
        folded = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number, budget_lines=1)
        by = {f.path: f for f in folded.files}
        self.assertTrue(by["bin.dat"].folded)
        self.assertEqual(folded.total_files, 2)
        item = self.large.file_for(
            self.reader, "volmarr", "pub", pr.number, "bin.dat")
        self.assertIn("Binary file", render_large_file_page(folded, item))

    # -- per-file review -----------------------------------------------------
    def test_folded_file_opens_in_full_on_its_own(self):
        pr = self._three_file_pr()
        view = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number, budget_lines=1)
        self.assertTrue(all(f.folded for f in view.files))
        item = self.large.file_for(
            self.reader, "volmarr", "pub", pr.number, "c.txt")
        self.assertFalse(item.folded)
        self.assertEqual(item.patch_lines, view.files[2].patch_lines)
        self.assertEqual(len(item.entry.file.lines), item.patch_lines)
        page = render_large_file_page(view, item)
        self.assertIn("c line 9", page)

    def test_file_for_unknown_path_is_refused(self):
        pr = self._three_file_pr()
        with self.assertRaises(PullRequestError) as ctx:
            self.large.file_for(
                self.reader, "volmarr", "pub", pr.number, "nope.txt")
        self.assertEqual(ctx.exception.reason, "file_not_found")
        with self.assertRaises(PullRequestError):
            self.large.file_for(
                self.reader, "volmarr", "pub", pr.number, "")

    def test_viewed_state_rides_the_large_view(self):
        pr = self._three_file_pr()
        self.files.mark_viewed(self.reader, "volmarr", "pub",
                               pr.number, "b.txt")
        view = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number, budget_lines=1)
        by = {f.path: f for f in view.files}
        self.assertTrue(by["b.txt"].entry.is_viewed)
        self.assertFalse(by["a.txt"].entry.is_viewed)
        item = self.large.file_for(
            self.reader, "volmarr", "pub", pr.number, "b.txt")
        self.assertTrue(item.entry.is_viewed)
        self.assertEqual(item.entry.state_words, "Viewed")

    # -- permissions -----------------------------------------------------------
    def test_private_stranger_gets_uniform_not_found(self):
        pr = self._pr({"a.txt": block("a", 5)}, repo="priv")
        with self.assertRaises(PullRequestError) as ctx:
            self.large.large_files_for(
                self.reader, "volmarr", "priv", pr.number)
        self.assertEqual(ctx.exception.reason, "pull_request_not_found")
        with self.assertRaises(PullRequestError) as ctx:
            self.large.file_for(
                self.reader, "volmarr", "priv", pr.number, "a.txt")
        self.assertEqual(ctx.exception.reason, "pull_request_not_found")

    def test_anonymous_public_reader_sees_the_view(self):
        pr = self._three_file_pr()
        view = self.large.large_files_for(None, "volmarr", "pub", pr.number)
        self.assertEqual(view.total_files, 3)
        for item in view.files:
            self.assertFalse(item.entry.is_viewed)

    # -- budget judgement -------------------------------------------------------
    def test_invalid_budgets_are_refused(self):
        pr = self._three_file_pr()
        for bad in (0, -5, "100", 2.5, True, None):
            with self.assertRaises(PullRequestError) as ctx:
                self.large.large_files_for(
                    self.reader, "volmarr", "pub", pr.number,
                    budget_lines=bad)
            self.assertEqual(ctx.exception.reason, "budget_invalid")

    # -- rendering ----------------------------------------------------------------
    def test_page_hides_folded_patch_but_says_its_counts(self):
        pr = self._three_file_pr()
        probe = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number)
        per_file = probe.files[0].patch_lines
        view = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number,
            budget_lines=per_file)
        page = render_large_files_page(view)
        self.assertIn("a line 0", page)          # shown file's patch
        self.assertNotIn("b line 0", page)       # folded patch hidden
        self.assertNotIn("c line 0", page)
        self.assertIn("folded beyond the", page)
        self.assertIn("Open this file on its own", page)
        self.assertIn(view.summary_words, page)

    def test_page_under_budget_shows_all_patches(self):
        pr = self._three_file_pr()
        view = self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number)
        page = render_large_files_page(view)
        for name in ("a line 0", "b line 0", "c line 0"):
            self.assertIn(name, page)

    def test_no_migration_and_no_audit_row(self):
        pr = self._three_file_pr()
        before = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log").fetchone()[0]
        self.large.large_files_for(
            self.reader, "volmarr", "pub", pr.number, budget_lines=1)
        self.large.file_for(self.reader, "volmarr", "pub", pr.number, "a.txt")
        after = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log").fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(db.schema_version(self.conn), 70)


if __name__ == "__main__":
    unittest.main()
