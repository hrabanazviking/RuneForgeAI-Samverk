"""S-160 acceptance battery (git layer): revert mechanics.

Acceptance (roadmap S-160): revert — one-click PR that
reverts a merged PR, linked both ways. This battery
covers the git-mechanics layer (`samverk/revert_git.py`):
the inverse change is computed by git's own merge
machinery and landed as one commit on a fresh branch;
conflicts and empty reverts are clean refusals that
move nothing. The pull-request / link layer has its
own battery.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk.revert_git import (
    RevertError, build_revert_commit, compute_revert_tree,
    create_revert_branch, default_revert_branch_name,
    default_revert_message, describe_merged_change,
    describe_merged_range, land_revert, samverk_identity)


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


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


def make_commit(repo, parents, files, message):
    tree = make_tree(repo, files)
    args = ["commit-tree", tree]
    for parent in parents:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


BASE = {"a.txt": "alpha\nbeta\n", "keep.txt": "keep\n",
        "d.txt": "doomed\n"}
FEATURE = {"a.txt": "alpha\nBETA\n", "keep.txt": "keep\n",
           "b.txt": "new file\n"}


class RevertGitTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = Path(self._td.name) / "repo.git"
        subprocess.run(["git", "init", "--bare", "-q", str(self.repo)],
                       check=True, capture_output=True)
        self.base = make_commit(self.repo, [], BASE, "base")
        self.feature = make_commit(
            self.repo, [self.base], FEATURE, "feature work")
        self.merge = make_commit(
            self.repo, [self.base, self.feature], FEATURE,
            "Merge pull request #7")
        git(self.repo, "update-ref", "refs/heads/main", self.merge)

    # -- helpers -----------------------------------------------------
    def _show(self, oid, path):
        return git(self.repo, "show", f"{oid}:{path}")

    def _tree_files(self, oid):
        out = git(self.repo, "ls-tree", "-r", "--name-only", oid)
        return out.splitlines() if out else []

    def _ref(self, branch):
        out = subprocess.run(
            ["git", f"--git-dir={self.repo}", "rev-parse", "--verify",
             "--quiet", f"refs/heads/{branch}"], capture_output=True)
        return out.stdout.decode().strip() if out.returncode == 0 else None

    def _land(self, **overrides):
        kwargs = dict(
            base_branch="main", merged_oid=self.merge,
            branch_name="revert-7-feature",
            author_name="volmarr",
            author_email="volmarr@samverk.invalid",
            message=default_revert_message(7, "Feature", self.merge))
        kwargs.update(overrides)
        return land_revert(self.repo, **kwargs)

    # -- describing the landed change --------------------------------
    def test_describe_merge_commit(self):
        change = describe_merged_change(self.repo, self.merge)
        self.assertEqual(change.kind, "merge")
        self.assertEqual(change.pre_merge_oid, self.base)
        self.assertEqual(change.head_oid, self.feature)
        self.assertEqual(change.merged_oid, self.merge)

    def test_describe_squash_single_and_explicit_pre(self):
        squash = make_commit(self.repo, [self.base], FEATURE, "squashed")
        change = describe_merged_change(self.repo, squash)
        self.assertEqual(change.kind, "single")
        self.assertEqual(change.pre_merge_oid, self.base)
        self.assertEqual(change.head_oid, "")
        explicit = describe_merged_change(
            self.repo, self.feature, self.base)
        self.assertEqual(explicit.pre_merge_oid, self.base)

    def test_describe_range(self):
        r1 = make_commit(self.repo, [self.base],
                         {**BASE, "a.txt": "alpha\nMID\n"}, "r1")
        r2 = make_commit(self.repo, [r1], FEATURE, "r2")
        change = describe_merged_range(self.repo, r1, r2)
        self.assertEqual(change.kind, "range")
        self.assertEqual(change.pre_merge_oid, self.base)
        landed = self._land(merged_oid=r2, first_landed_oid=r1)
        self.assertEqual(self._show(landed.commit_oid, "a.txt"),
                         "alpha\nbeta")

    def test_describe_refusals(self):
        with self.assertRaises(RevertError) as caught:
            describe_merged_change(self.repo, "not-an-oid")
        self.assertEqual(caught.exception.reason, "merged_invalid")
        with self.assertRaises(RevertError) as caught:
            describe_merged_change(self.repo, "a" * 40)
        self.assertEqual(caught.exception.reason, "merged_not_found")
        with self.assertRaises(RevertError) as caught:
            describe_merged_change(self.repo, self.base)
        self.assertEqual(caught.exception.reason, "no_parent")

    # -- computing the inverse ---------------------------------------
    def test_compute_clean_at_merge_tip(self):
        plan = compute_revert_tree(
            self.repo, current_oid=self.merge,
            merged_oid=self.merge, pre_merge_oid=self.base)
        self.assertTrue(plan.is_clean)
        self.assertFalse(plan.is_empty)
        base_tree = git(self.repo, "rev-parse", f"{self.base}^{{tree}}")
        self.assertEqual(plan.tree_oid, base_tree)

    def test_compute_conflict_names_paths(self):
        later = make_commit(
            self.repo, [self.merge],
            {**FEATURE, "a.txt": "alpha\nGAMMA\n"}, "later")
        plan = compute_revert_tree(
            self.repo, current_oid=later,
            merged_oid=self.merge, pre_merge_oid=self.base)
        self.assertFalse(plan.is_clean)
        self.assertEqual(plan.conflicted_paths, ("a.txt",))
        self.assertIn("a.txt", plan.words)

    # -- landing -------------------------------------------------------
    def test_land_clean_revert(self):
        landed = self._land()
        self.assertEqual(landed.branch, "revert-7-feature")
        self.assertEqual(self._ref("revert-7-feature"),
                         landed.commit_oid)
        self.assertEqual(self._ref("main"), self.merge)
        parent = git(self.repo, "rev-parse", f"{landed.commit_oid}^")
        self.assertEqual(parent, self.merge)
        self.assertEqual(self._show(landed.commit_oid, "a.txt"),
                         "alpha\nbeta")
        self.assertEqual(self._show(landed.commit_oid, "d.txt"), "doomed")
        self.assertNotIn("b.txt", self._tree_files(landed.commit_oid))
        message = git(self.repo, "log", "--format=%B", "-1",
                      landed.commit_oid)
        self.assertIn('#7', message)
        self.assertIn(self.merge, message)

    def test_land_keeps_later_work(self):
        later_files = {**FEATURE, "keep.txt": "keep v2\n",
                       "g.txt": "later\n"}
        later = make_commit(self.repo, [self.merge], later_files, "later")
        git(self.repo, "update-ref", "refs/heads/main", later)
        landed = self._land()
        self.assertEqual(self._show(landed.commit_oid, "a.txt"),
                         "alpha\nbeta")
        self.assertEqual(self._show(landed.commit_oid, "keep.txt"),
                         "keep v2")
        self.assertEqual(self._show(landed.commit_oid, "g.txt"), "later")

    def test_land_line_level_neighbour_change(self):
        wide_base = {"w.txt": "l1\nl2\nl3\nl4\nl5\n"}
        wide_feat = {"w.txt": "l1\nL2\nl3\nl4\nl5\n"}
        base2 = make_commit(self.repo, [], wide_base, "wide base")
        feat2 = make_commit(self.repo, [base2], wide_feat, "wide feat")
        merge2 = make_commit(self.repo, [base2, feat2], wide_feat, "merge2")
        later = make_commit(
            self.repo, [merge2],
            {"w.txt": "l1\nL2\nl3\nl4\nL5\n"}, "later")
        git(self.repo, "update-ref", "refs/heads/main", later)
        landed = self._land(merged_oid=merge2)
        self.assertEqual(self._show(landed.commit_oid, "w.txt"),
                         "l1\nl2\nl3\nl4\nL5")

    def test_conflict_refuses_and_creates_nothing(self):
        later = make_commit(
            self.repo, [self.merge],
            {**FEATURE, "a.txt": "alpha\nGAMMA\n"}, "later")
        git(self.repo, "update-ref", "refs/heads/main", later)
        with self.assertRaises(RevertError) as caught:
            self._land()
        self.assertEqual(caught.exception.reason, "revert_conflict")
        self.assertEqual(caught.exception.paths, ("a.txt",))
        self.assertIn("a.txt", str(caught.exception))
        self.assertIsNone(self._ref("revert-7-feature"))
        self.assertEqual(self._ref("main"), later)

    def test_empty_revert_refused(self):
        undone = make_commit(self.repo, [self.merge], BASE, "manual undo")
        git(self.repo, "update-ref", "refs/heads/main", undone)
        plan = compute_revert_tree(
            self.repo, current_oid=undone,
            merged_oid=self.merge, pre_merge_oid=self.base)
        self.assertTrue(plan.is_empty)
        with self.assertRaises(RevertError) as caught:
            self._land()
        self.assertEqual(caught.exception.reason, "revert_empty")
        self.assertIsNone(self._ref("revert-7-feature"))

    def test_branch_taken_refused(self):
        self._land()
        with self.assertRaises(RevertError) as caught:
            self._land()
        self.assertEqual(caught.exception.reason, "branch_taken")
        with self.assertRaises(RevertError) as caught:
            create_revert_branch(self.repo, "main", self.merge)
        self.assertEqual(caught.exception.reason, "branch_taken")

    def test_base_not_found(self):
        with self.assertRaises(RevertError) as caught:
            self._land(base_branch="missing")
        self.assertEqual(caught.exception.reason, "base_not_found")

    def test_rename_reverts(self):
        renamed = {"renamed.txt": "alpha\nBETA\n",
                   "keep.txt": "keep\n", "d.txt": "doomed\n"}
        feat = make_commit(self.repo, [self.base], renamed, "rename")
        merge = make_commit(self.repo, [self.base, feat], renamed, "merge")
        git(self.repo, "update-ref", "refs/heads/main", merge)
        landed = self._land(merged_oid=merge)
        names = self._tree_files(landed.commit_oid)
        self.assertIn("a.txt", names)
        self.assertNotIn("renamed.txt", names)

    # -- naming, message, identity ------------------------------------
    def test_branch_name_derivation(self):
        self.assertEqual(default_revert_branch_name(7, "feature"),
                         "revert-7-feature")
        self.assertEqual(
            default_revert_branch_name(12, "feat/some thing"),
            "revert-12-feat/some-thing")
        long_name = default_revert_branch_name(3, "x" * 200)
        self.assertLessEqual(len(long_name), 100)
        self.assertTrue(long_name.startswith("revert-3-"))

    def test_message_and_identity(self):
        message = default_revert_message(7, "Feature work", self.merge)
        self.assertIn("Feature work", message)
        self.assertIn("#7", message)
        self.assertIn(self.merge, message)

        class FakeUser:
            username = "Volmarr"
            username_lower = "volmarr"
        self.assertEqual(samverk_identity(FakeUser()),
                         ("Volmarr", "volmarr@samverk.invalid"))

    def test_build_commit_direct(self):
        commit = build_revert_commit(
            self.repo, current_oid=self.merge, merged_oid=self.merge,
            pre_merge_oid=self.base, author_name="volmarr",
            author_email="volmarr@samverk.invalid",
            message="Revert x\n")
        self.assertEqual(commit.parent_oid, self.merge)
        author = git(self.repo, "log", "--format=%an <%ae>", "-1",
                     commit.commit_oid)
        self.assertEqual(author, "volmarr <volmarr@samverk.invalid>")


if __name__ == "__main__":
    unittest.main()
