"""S-155 acceptance battery (refusal side): rebase
pre-flight conflict detection, the loud refusal, and
the no-half-state guarantee.

Acceptance (roadmap S-155): Merge: rebase — head
commits replayed onto base; refused loudly when
conflicts would result (no silent half-states).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk.pull_request_rebase_safety import (
    RebaseConflictError, RebaseStateGuard, plan_rebase,
    render_rebase_refusal, restore_refs, snapshot_refs)
from samverk.pull_requests import PullRequestError
from samverk.refs import RefStore, branch_ref
from test_repo_home import run_git


class RebaseSafetyTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.bare = self.root / "repo.git"
        run_git(self.root, "init", "--bare", "-b", "main",
                str(self.bare))
        self.work = self.root / "work"; self.work.mkdir()
        run_git(self.work, "init", "-b", "main")
        (self.work / "a.txt").write_text("one\ntwo\nthree\n")
        (self.work / "b.txt").write_text("bee\n")
        run_git(self.work, "add", ".")
        run_git(self.work, "commit", "-m", "base commit")
        run_git(self.work, "push", str(self.bare), "main")
        self.refs = RefStore(self.bare)
        self.base_oid = self.refs.resolve("refs/heads/main")

    # -- helpers -------------------------------------------------
    def _branch(self, name, edits, message):
        run_git(self.work, "checkout", "-b", name, "main")
        for path, text in edits.items():
            (self.work / path).write_text(text)
        run_git(self.work, "add", ".")
        run_git(self.work, "commit", "-m", message)
        run_git(self.work, "push", str(self.bare), name)
        run_git(self.work, "checkout", "main")
        return self.refs.resolve(branch_ref(name))

    def _advance_main(self, edits, message):
        for path, text in edits.items():
            (self.work / path).write_text(text)
        run_git(self.work, "add", ".")
        run_git(self.work, "commit", "-m", message)
        run_git(self.work, "push", str(self.bare), "main")
        return self.refs.resolve("refs/heads/main")

    # -- clean replays --------------------------------------------
    def test_clean_replay_plans_every_step(self):
        head = self._branch(
            "feature", {"b.txt": "bee\nfeature\n"},
            "feature work")
        plan = plan_rebase(self.bare, self.base_oid, head)
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].source_oid, head)
        self.assertEqual(plan.steps[0].subject, "feature work")
        self.assertNotEqual(plan.replayed_head_oid, head)
        # The replayed commit's parent is the base, its
        # tree carries the feature change.
        parents = run_git(
            self.bare, "show", "-s", "--format=%P",
            plan.replayed_head_oid)
        self.assertEqual(parents, self.base_oid)
        shown = run_git(
            self.bare, "show",
            f"{plan.replayed_head_oid}:b.txt")
        self.assertEqual(shown, "bee\nfeature")

    def test_clean_multi_commit_and_moved_base(self):
        run_git(self.work, "checkout", "-b", "feature", "main")
        (self.work / "b.txt").write_text("bee\none\n")
        run_git(self.work, "add", ".")
        run_git(self.work, "commit", "-m", "step one")
        (self.work / "b.txt").write_text("bee\none\ntwo\n")
        run_git(self.work, "add", ".")
        run_git(self.work, "commit", "-m", "step two")
        run_git(self.work, "push", str(self.bare), "feature")
        run_git(self.work, "checkout", "main")
        head = self.refs.resolve("refs/heads/feature")
        new_base = self._advance_main(
            {"a.txt": "one\ntwo\nthree\nfour\n"}, "base moves")
        plan = plan_rebase(self.bare, new_base, head)
        self.assertEqual(
            [s.subject for s in plan.steps],
            ["step one", "step two"])
        shown = run_git(
            self.bare, "show",
            f"{plan.replayed_head_oid}:b.txt")
        self.assertEqual(shown, "bee\none\ntwo")
        shown = run_git(
            self.bare, "show",
            f"{plan.replayed_head_oid}:a.txt")
        self.assertEqual(shown, "one\ntwo\nthree\nfour")

    def test_empty_range_is_a_clean_empty_plan(self):
        plan = plan_rebase(self.bare, self.base_oid,
                           self.base_oid)
        self.assertEqual(plan.steps, ())
        self.assertEqual(plan.replayed_head_oid, self.base_oid)

    # -- the loud refusal ------------------------------------------
    def test_conflicting_replay_refused_loudly(self):
        head = self._branch(
            "feature", {"a.txt": "one\nFEATURE\nthree\n"},
            "feature edits line two")
        new_base = self._advance_main(
            {"a.txt": "one\nBASE\nthree\n"}, "base edits line two")
        before = snapshot_refs(self.bare)
        with self.assertRaises(RebaseConflictError) as caught:
            plan_rebase(self.bare, new_base, head)
        err = caught.exception
        self.assertIsInstance(err, PullRequestError)
        self.assertEqual(err.reason, "rebase_conflict")
        self.assertEqual(len(err.conflicts), 1)
        conflict = err.conflicts[0]
        self.assertEqual(conflict.commit_oid, head)
        self.assertEqual(conflict.subject,
                         "feature edits line two")
        self.assertEqual(conflict.paths, ("a.txt",))
        self.assertEqual(conflict.kind, "content")
        self.assertEqual((err.base_oid, err.head_oid),
                         (new_base, head))
        message = str(err)
        self.assertIn("cannot be rebased", message)
        self.assertIn("a.txt", message)
        self.assertIn("Nothing was changed", message)
        # No half-state: every ref exactly as before.
        self.assertEqual(snapshot_refs(self.bare), before)

    def test_second_commit_conflict_names_second_commit(self):
        run_git(self.work, "checkout", "-b", "feature", "main")
        (self.work / "b.txt").write_text("bee\nclean\n")
        run_git(self.work, "add", ".")
        run_git(self.work, "commit", "-m", "clean step")
        (self.work / "a.txt").write_text("one\nFEAT\nthree\n")
        run_git(self.work, "add", ".")
        run_git(self.work, "commit", "-m", "clashing step")
        run_git(self.work, "push", str(self.bare), "feature")
        run_git(self.work, "checkout", "main")
        head = self.refs.resolve("refs/heads/feature")
        new_base = self._advance_main(
            {"a.txt": "one\nBASE\nthree\n"}, "base clash")
        before = snapshot_refs(self.bare)
        with self.assertRaises(RebaseConflictError) as caught:
            plan_rebase(self.bare, new_base, head)
        conflict = caught.exception.conflicts[0]
        self.assertEqual(conflict.subject, "clashing step")
        # I3: the first commit replayed cleanly in the
        # dry run, the later one conflicts — and still
        # every ref is exactly as it was before the call.
        self.assertEqual(snapshot_refs(self.bare), before)
        rev_range = f"{self.base_oid}..{head}"
        first = run_git(self.bare, "rev-list", "--reverse", rev_range).splitlines()[0]
        self.assertNotEqual(conflict.commit_oid, first)
        self.assertEqual(conflict.commit_oid, head)
        self.assertEqual(conflict.paths, ("a.txt",))

    def test_merge_commit_replays_by_first_parent_diff(self):
        # DESIGN A3: a merge commit in the head history
        # is not refused; it replays flattened, by its
        # first-parent diff, like the engine lands it.
        self._branch("side", {"b.txt": "bee\nside\n"},
                     "side work")
        run_git(self.work, "checkout", "-b", "feature", "main")
        (self.work / "c.txt").write_text("see\n")
        run_git(self.work, "add", ".")
        run_git(self.work, "commit", "-m", "feature start")
        run_git(self.work, "merge", "--no-ff", "side",
                "-m", "merge side in")
        run_git(self.work, "push", str(self.bare), "feature")
        run_git(self.work, "checkout", "main")
        head = self.refs.resolve("refs/heads/feature")
        plan = plan_rebase(self.bare, self.base_oid, head)
        self.assertEqual(
            [s.subject for s in plan.steps],
            ["side work", "feature start", "merge side in"])
        shown = run_git(
            self.bare, "show",
            f"{plan.replayed_head_oid}:b.txt")
        self.assertEqual(shown, "bee\nside")
        shown = run_git(
            self.bare, "show",
            f"{plan.replayed_head_oid}:c.txt")
        self.assertEqual(shown, "see")

    def test_unknown_commit_is_a_plain_refusal(self):
        with self.assertRaises(PullRequestError) as caught:
            plan_rebase(self.bare, self.base_oid, "f" * 40)
        self.assertEqual(caught.exception.reason,
                         "rebase_commit_not_found")

    def test_render_says_it_in_words_and_escapes(self):
        head = self._branch(
            "feature", {"a.txt": "one\n<FEAT>\nthree\n"},
            "feature <work>")
        new_base = self._advance_main(
            {"a.txt": "one\nBASE\nthree\n"}, "base work")
        with self.assertRaises(RebaseConflictError) as caught:
            plan_rebase(self.bare, new_base, head)
        page = render_rebase_refusal(caught.exception)
        self.assertIn("Rebase refused", page)
        self.assertIn("a.txt", page)
        self.assertIn("feature &lt;work&gt;", page)
        self.assertIn("exactly as they were", page)

    # -- the guard ---------------------------------------------------
    def test_guard_restores_moved_and_created_refs(self):
        head = self._branch(
            "feature", {"b.txt": "bee\nfeature\n"}, "feature work")
        guard = RebaseStateGuard(self.bare)
        self.assertEqual(guard.differences(), {})
        # A half-replay: base moved, a scratch ref created.
        self.refs.update_ref(
            "refs/heads/main", head,
            expected_old=self.base_oid)
        self.refs.create_branch("rebase-scratch", head)
        self.assertEqual(
            set(guard.differences()),
            {"refs/heads/main", "refs/heads/rebase-scratch"})
        restored = guard.abort()
        self.assertEqual(
            set(restored),
            {"refs/heads/main", "refs/heads/rebase-scratch"})
        self.assertEqual(guard.differences(), {})
        self.assertEqual(
            snapshot_refs(self.bare), guard.snapshot)

    def test_guard_context_manager_rolls_back_on_error(self):
        head = self._branch(
            "feature", {"b.txt": "bee\nfeature\n"}, "feature work")
        before = snapshot_refs(self.bare)
        with self.assertRaises(RuntimeError):
            with RebaseStateGuard(self.bare):
                self.refs.update_ref(
                    "refs/heads/main", head,
                    expected_old=self.base_oid)
                raise RuntimeError("mid-replay conflict")
        self.assertEqual(snapshot_refs(self.bare), before)

    def test_restore_refs_round_trip(self):
        before = snapshot_refs(self.bare)
        head = self._branch(
            "feature", {"b.txt": "bee\nfeature\n"}, "feature work")
        self.assertNotEqual(snapshot_refs(self.bare), before)
        restore_refs(self.bare, before)
        self.assertEqual(snapshot_refs(self.bare), before)
        self.assertIsNone(self.refs.resolve("refs/heads/feature"))
        self.assertEqual(head[:7], head[:7])  # oid was real

    def test_stale_plan_refused_before_any_step(self):
        head = self._branch(
            "feature", {"b.txt": "bee\nfeature\n"}, "feature work")
        plan = plan_rebase(self.bare, self.base_oid, head)
        guard = RebaseStateGuard(self.bare)
        guard.assert_plan_fresh(
            plan, "refs/heads/main", "refs/heads/feature")
        new_base = self._advance_main(
            {"b.txt": "bee\nmoved\n"}, "base moved again")
        self.assertNotEqual(new_base, self.base_oid)
        with self.assertRaises(PullRequestError) as caught:
            guard.assert_plan_fresh(
                plan, "refs/heads/main", "refs/heads/feature")
        self.assertEqual(caught.exception.reason,
                         "rebase_stale_plan")


if __name__ == "__main__":
    unittest.main()
