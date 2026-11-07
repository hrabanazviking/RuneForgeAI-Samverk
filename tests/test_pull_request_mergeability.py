"""S-156 acceptance battery: conflict surfacing.

Acceptance (roadmap S-156): Conflict surfacing —
mergeability computed off-path; conflicts shown as
"these files" before anyone presses merge — never
discovered by merging.

Finalized from the tester's draft (hidden_files, sha256
178930ee…cf41): the contract landed exactly as drafted
(samverk/pull_request_mergeability.py, MergeabilityStore,
mergeability_for -> report with .mergeable /
.conflicting_files, render_mergeability); the private-repo
test was adapted to build a genuinely private repository
(the draft's helper built it public), and two tests were
added proving the verdict uses git's real merge (edits to
the same file that do not overlap merge cleanly) and the
branches' current tips (a push after opening changes the
answer).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.forks import ForkStore
from samverk.issues import IssueStore
from samverk.pull_request_mergeability import (
    MergeabilityStore, render_mergeability)
from samverk.pull_request_forks import ForkPullRequestStore
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


def git_soft(repo, *args):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, env=env)
    return out.returncode, out.stdout.decode(), out.stderr.decode()


def make_tree(repo, files):
    def build(items):
        entries = []
        dirs = {}
        for path, content in items:
            head, _, rest = path.partition("/")
            if rest:
                dirs.setdefault(head, []).append((rest, content))
            else:
                blob = git(repo, "hash-object", "-w", "--stdin",
                           input_bytes=content.encode())
                entries.append((path, f"100644 blob {blob}\t{path}"))
        for name, sub in dirs.items():
            tree = build(sub)
            entries.append((name + "/", f"040000 tree {tree}\t{name}"))
        entries.sort(key=lambda item: item[0])
        return git(repo, "mktree",
                   input_bytes=("\n".join(
                       line for _key, line in entries) + "\n").encode())
    return build(sorted(files.items()))


def make_commit(repo, parent, files, message):
    tree = make_tree(repo, files)
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class MergeabilityTests(unittest.TestCase):
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
        self.third = self.accounts.register("tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.forks = ForkStore(self.conn, self.root, self.accounts,
                               self.repos, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.merge = MergeabilityStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")

    # -- helpers ---------------------------------------------------------
    def _diverged(self, common, base_files, head_files, *, name="pub",
                  visibility="public"):
        """A PR whose base and head both moved from a common
        ancestor: base_files is the full tree on main,
        head_files the full tree on feature."""
        if name != "pub":
            self.repos.create_repository(
                self.owner.id, "volmarr", name, visibility=visibility)
        path = self.repos.path_for("volmarr", name)
        common_oid = make_commit(path, None, common, "common")
        base_oid = make_commit(path, common_oid, base_files, "base work")
        git(path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(path, common_oid, head_files, "feature work")
        git(path, "update-ref", "refs/heads/feature", head_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", name,
            base_branch="main", head_branch="feature")
        return pr, path, base_oid, head_oid

    def _linear(self):
        base_oid = make_commit(
            self.path, None, {"a.txt": "alpha\n"}, "base")
        git(self.path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(
            self.path, base_oid, {"a.txt": "alpha\nbeta\n"}, "feature work")
        git(self.path, "update-ref", "refs/heads/feature", head_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub",
            base_branch="main", head_branch="feature")
        return pr, self.path, base_oid, head_oid

    def _snapshot(self, path):
        """Everything a merge would touch: HEAD, every ref,
        the object store's file list, the commit census,
        and the database/audit census."""
        _rc, refs, _e = git_soft(path, "show-ref")
        _rc, head_ref, _e = git_soft(path, "symbolic-ref", "HEAD")
        _rc, census, _e = git_soft(path, "rev-list", "--all", "--count")
        objects = sorted(
            str(p.relative_to(path))
            for p in (path / "objects").rglob("*") if p.is_file())
        db_counts = {}
        for table in ("issues", "pull_requests", "audit_log"):
            row = self.conn.execute(
                f"SELECT COUNT(*) AS c FROM {table}").fetchone()
            db_counts[table] = int(row["c"])
        return (refs, head_ref, census, tuple(objects), db_counts)

    def _report(self, number, viewer=None, name="pub"):
        return self.merge.mergeability_for(
            viewer or self.owner, "volmarr", name, number)

    # -- verdict correctness ----------------------------------------------
    def test_clean_diverged_merge_is_mergeable_with_no_conflicts(self):
        pr, _p, _b, _h = self._diverged(
            {"a.txt": "alpha\n", "b.txt": "bravo\n"},
            {"a.txt": "alpha\n", "b.txt": "bravo\nbase\n"},
            {"a.txt": "alpha\nhead\n", "b.txt": "bravo\n"})
        report = self._report(pr.number)
        self.assertTrue(report.mergeable)
        self.assertEqual(report.conflicting_files, ())

    def test_fast_forward_head_is_mergeable_with_no_conflicts(self):
        pr, _p, _b, _h = self._linear()
        report = self._report(pr.number)
        self.assertTrue(report.mergeable)
        self.assertEqual(report.conflicting_files, ())

    def test_content_conflict_is_not_mergeable_and_names_the_file(self):
        pr, _p, _b, _h = self._diverged(
            {"a.txt": "alpha\n"},
            {"a.txt": "base version\n"},
            {"a.txt": "head version\n"})
        report = self._report(pr.number)
        self.assertFalse(report.mergeable)
        self.assertEqual(report.conflicting_files, ("a.txt",))

    def test_conflicting_files_are_exactly_the_conflicting_files(self):
        pr, _p, _b, _h = self._diverged(
            {"a.txt": "a\n", "b.txt": "b\n", "c.txt": "c\n",
             "d.txt": "d\n"},
            {"a.txt": "a base\n", "b.txt": "b\n", "c.txt": "c base\n",
             "d.txt": "d base\n"},
            {"a.txt": "a head\n", "b.txt": "b head\n",
             "c.txt": "c head\n", "d.txt": "d\n"})
        report = self._report(pr.number)
        self.assertFalse(report.mergeable)
        self.assertEqual(
            tuple(sorted(report.conflicting_files)), ("a.txt", "c.txt"))

    def test_the_same_change_on_both_sides_is_mergeable(self):
        pr, _p, _b, _h = self._diverged(
            {"a.txt": "alpha\n"},
            {"a.txt": "same\n"},
            {"a.txt": "same\n"})
        report = self._report(pr.number)
        self.assertTrue(report.mergeable)
        self.assertEqual(report.conflicting_files, ())

    def test_add_add_conflict_names_the_file(self):
        pr, _p, _b, _h = self._diverged(
            {"a.txt": "alpha\n"},
            {"a.txt": "alpha\n", "new.txt": "from base\n"},
            {"a.txt": "alpha\n", "new.txt": "from head\n"})
        report = self._report(pr.number)
        self.assertFalse(report.mergeable)
        self.assertEqual(report.conflicting_files, ("new.txt",))

    def test_modify_delete_conflict_names_the_file(self):
        pr, _p, _b, _h = self._diverged(
            {"a.txt": "alpha\n", "gone.txt": "here\n"},
            {"a.txt": "alpha\n", "gone.txt": "changed\n"},
            {"a.txt": "alpha\n"})
        report = self._report(pr.number)
        self.assertFalse(report.mergeable)
        self.assertEqual(report.conflicting_files, ("gone.txt",))

    def test_report_names_the_branches_and_oids_it_judged(self):
        pr, _p, base_oid, head_oid = self._diverged(
            {"a.txt": "alpha\n"},
            {"a.txt": "base version\n"},
            {"a.txt": "head version\n"})
        report = self._report(pr.number)
        self.assertEqual(report.number, pr.number)
        self.assertEqual(report.base_branch, "main")
        self.assertEqual(report.head_branch, "feature")
        self.assertEqual(report.base_oid, base_oid)
        self.assertEqual(report.head_oid, head_oid)

    def test_non_overlapping_edits_to_one_file_are_mergeable(self):
        # Both sides changed the same file, in places that
        # do not overlap: git's real merge is clean, so the
        # surfacing must say clean — a blob-equality guess
        # would cry conflict here.
        lines = "".join(f"line {i}\n" for i in range(1, 10))
        base_lines = "line 1 base\n" + "".join(
            f"line {i}\n" for i in range(2, 10))
        head_lines = "".join(
            f"line {i}\n" for i in range(1, 9)) + "line 9 head\n"
        pr, _p, _b, _h = self._diverged(
            {"f.txt": lines}, {"f.txt": base_lines},
            {"f.txt": head_lines})
        report = self._report(pr.number)
        self.assertTrue(report.mergeable)
        self.assertEqual(report.conflicting_files, ())

    def test_the_verdict_judges_the_current_tips(self):
        # Opened clean; then both branches move onto the
        # same line. The report must judge the merge that
        # would happen now, not the pair that was opened.
        pr, path, base_oid, head_oid = self._diverged(
            {"a.txt": "alpha\n", "b.txt": "bravo\n"},
            {"a.txt": "alpha\n", "b.txt": "bravo\nbase\n"},
            {"a.txt": "alpha\nhead\n", "b.txt": "bravo\n"})
        self.assertTrue(self._report(pr.number).mergeable)
        new_base = make_commit(
            path, base_oid,
            {"a.txt": "base moved\n", "b.txt": "bravo\nbase\n"},
            "base moves again")
        git(path, "update-ref", "refs/heads/main", new_base)
        new_head = make_commit(
            path, head_oid,
            {"a.txt": "head moved\n", "b.txt": "bravo\n"},
            "head moves again")
        git(path, "update-ref", "refs/heads/feature", new_head)
        report = self._report(pr.number)
        self.assertFalse(report.mergeable)
        self.assertEqual(report.conflicting_files, ("a.txt",))
        self.assertEqual(report.base_oid, new_base)
        self.assertEqual(report.head_oid, new_head)

    # -- zero side effects ---------------------------------------------------
    def test_query_on_a_mergeable_pr_changes_nothing(self):
        pr, path, _b, _h = self._diverged(
            {"a.txt": "alpha\n", "b.txt": "bravo\n"},
            {"a.txt": "alpha\n", "b.txt": "bravo\nbase\n"},
            {"a.txt": "alpha\nhead\n", "b.txt": "bravo\n"})
        before = self._snapshot(path)
        report = self._report(pr.number)
        self.assertTrue(report.mergeable)
        self.assertEqual(self._snapshot(path), before)

    def test_query_on_a_conflicting_pr_changes_nothing(self):
        pr, path, _b, _h = self._diverged(
            {"a.txt": "alpha\n"},
            {"a.txt": "base version\n"},
            {"a.txt": "head version\n"})
        before = self._snapshot(path)
        report = self._report(pr.number)
        self.assertFalse(report.mergeable)
        self.assertEqual(self._snapshot(path), before)

    def test_no_merge_commit_appears_and_refs_do_not_move(self):
        pr, path, base_oid, head_oid = self._diverged(
            {"a.txt": "alpha\n"},
            {"a.txt": "base version\n"},
            {"a.txt": "head version\n"})
        self._report(pr.number)
        self.assertEqual(git(path, "rev-parse", "refs/heads/main"), base_oid)
        self.assertEqual(
            git(path, "rev-parse", "refs/heads/feature"), head_oid)
        _rc, parents, _e = git_soft(
            path, "rev-list", "--all", "--merges", "--count")
        self.assertEqual(parents.strip(), "0")

    def test_repeated_queries_agree_and_change_nothing(self):
        pr, path, _b, _h = self._diverged(
            {"a.txt": "alpha\n"},
            {"a.txt": "base version\n"},
            {"a.txt": "head version\n"})
        before = self._snapshot(path)
        first = self._report(pr.number)
        second = self._report(pr.number)
        self.assertEqual(first.mergeable, second.mergeable)
        self.assertEqual(
            first.conflicting_files, second.conflicting_files)
        self.assertEqual(self._snapshot(path), before)

    # -- edges -----------------------------------------------------------------
    def test_pull_request_not_found(self):
        with self.assertRaises(PullRequestError) as caught:
            self._report(999)
        self.assertEqual(
            caught.exception.reason, "pull_request_not_found")

    def test_a_private_repo_stranger_gets_pull_request_not_found(self):
        pr, _p, _b, _h = self._diverged(
            {"s.txt": "s\n"}, {"s.txt": "s base\n"},
            {"s.txt": "s head\n"}, name="priv2",
            visibility="private")
        with self.assertRaises(PullRequestError) as caught:
            self.merge.mergeability_for(
                self.third, "volmarr", "priv2", pr.number)
        self.assertEqual(
            caught.exception.reason, "pull_request_not_found")

    def test_a_public_repo_reader_can_query(self):
        pr, _p, _b, _h = self._diverged(
            {"a.txt": "alpha\n"},
            {"a.txt": "base version\n"},
            {"a.txt": "head version\n"})
        report = self._report(pr.number, viewer=self.reader)
        self.assertFalse(report.mergeable)
        self.assertEqual(report.conflicting_files, ("a.txt",))

    def test_missing_head_ref_is_an_error_not_a_verdict(self):
        pr, path, _b, _h = self._linear()
        git(path, "update-ref", "-d", "refs/heads/feature")
        with self.assertRaises(PullRequestError):
            self._report(pr.number)

    def test_missing_base_ref_is_an_error_not_a_verdict(self):
        pr, path, _b, _h = self._linear()
        git(path, "update-ref", "-d", "refs/heads/main")
        with self.assertRaises(PullRequestError):
            self._report(pr.number)

    def test_empty_diff_after_base_catches_up(self):
        pr, path, _b, head_oid = self._linear()
        git(path, "update-ref", "refs/heads/main", head_oid)
        report = self._report(pr.number)
        self.assertEqual(report.conflicting_files, ())
        self.assertTrue(report.mergeable)

    # -- words and counts -------------------------------------------------------
    def test_render_says_the_verdict_and_the_files_in_words(self):
        pr, _p, _b, _h = self._diverged(
            {"a.txt": "alpha\n"},
            {"a.txt": "base version\n"},
            {"a.txt": "head version\n"})
        html = render_mergeability(self._report(pr.number))
        self.assertIn("a.txt", html)
        self.assertIn("conflict", html.lower())
        clean, _p2, _b2, _h2 = self._diverged(
            {"a.txt": "alpha\n", "b.txt": "bravo\n"},
            {"a.txt": "alpha\n", "b.txt": "bravo\nbase\n"},
            {"a.txt": "alpha\nhead\n", "b.txt": "bravo\n"},
            name="pub2")
        html = render_mergeability(self._report(clean.number, name="pub2"))
        self.assertIn("merge", html.lower())

    def test_schema_and_taxonomy_counts_unchanged_by_a_read(self):
        # S-156 is a pure read (the S-145 pattern): it adds
        # no migration and no audit event, so both counts
        # stand where S-152 left them, and asking the
        # question moves neither.
        self.assertEqual(db.schema_version(self.conn), 72)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 122)


if __name__ == "__main__":
    unittest.main()
