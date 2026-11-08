"""S-155 acceptance battery: pull request rebase landing.

Acceptance (roadmap S-155): Merge: rebase — head commits
replayed onto base; refused loudly when conflicts would
result (no silent half-states).

Written against DESIGN_S155 (invariants I1-I6): the store
is PullRequestRebaseStore.rebase_pull_request, returning a
RebaseReport; refusals are PullRequestError with reasons
rebase_conflict / pull_request_closed / pull_request_draft
/ permission_denied / pull_request_not_found.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.issues import IssueStore
from samverk.pull_request_rebase import (
    PullRequestRebaseStore, render_rebase_report)
from samverk.pull_requests import PullRequestError, PullRequestStore
from samverk.repositories import RepositoryStore


def git(repo, *args, input_bytes=None, env_extra=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    if env_extra:
        env.update(env_extra)
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


def _ident(author=None, committer=None, when=None):
    env = {}
    if author is not None:
        env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = author
    if committer is not None:
        env["GIT_COMMITTER_NAME"], env["GIT_COMMITTER_EMAIL"] = committer
    if when is not None:
        env["GIT_AUTHOR_DATE"] = f"{when} +0000"
        env["GIT_COMMITTER_DATE"] = f"{when} +0000"
    return env


def make_commit(repo, parent, files, message, author=None,
                committer=None, when=None):
    tree = make_tree(repo, files)
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode(),
               env_extra=_ident(author, committer, when))


def make_merge_commit(repo, parent1, parent2, files, message,
                      when=None):
    tree = make_tree(repo, files)
    return git(repo, "commit-tree", tree, "-p", parent1, "-p", parent2,
               input_bytes=(message + "\n").encode(),
               env_extra=_ident(when=when))


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class PullRequestRebaseTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self._when = 1_600_000_000
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.third = self.accounts.register("tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.rebase = PullRequestRebaseStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")

    # -- helpers ---------------------------------------------------------
    def _tick(self):
        self._when += 100
        return self._when

    def _scenario(self, *, name="pub", visibility="public",
                  root_files, steps, advance=None, draft=False):
        """Root on main, a chain of head commits on feature,
        a pull request, then (optionally) main advances.
        steps/advance carry FULL tree snapshots, S-152 style."""
        if name != "pub":
            self.repos.create_repository(
                self.owner.id, "volmarr", name, visibility=visibility)
        path = self.repos.path_for("volmarr", name)
        root = make_commit(path, None, root_files, "root commit",
                           when=self._tick())
        git(path, "update-ref", "refs/heads/main", root)
        parent = root
        head_oids = []
        for step in steps:
            oid = make_commit(
                path, parent, step["files"], step["message"],
                author=step.get("author"),
                committer=step.get("committer"),
                when=step.get("when") or self._tick())
            head_oids.append(oid)
            parent = oid
        git(path, "update-ref", "refs/heads/feature", parent)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", name,
            base_branch="main", head_branch="feature", draft=draft)
        advanced = None
        if advance is not None:
            advanced = make_commit(
                path, root, advance["files"],
                advance.get("message", "base advances"),
                when=self._tick())
            git(path, "update-ref", "refs/heads/main", advanced)
        return pr, path, root, head_oids, advanced

    def _two_step_scenario(self, **kw):
        return self._scenario(
            root_files={"a.txt": "alpha\n", "b.txt": "bee\n"},
            steps=[
                {"files": {"a.txt": "alpha\n", "b.txt": "bee\none\n"},
                 "message": "step one"},
                {"files": {"a.txt": "alpha\n", "b.txt": "bee\none\ntwo\n",
                           "c.txt": "see\n"},
                 "message": "step two"},
            ],
            advance={"files": {"a.txt": "alpha\nfour\n",
                               "b.txt": "bee\n"},
                     "message": "base advances"},
            **kw)

    def _conflict_scenario(self, **kw):
        return self._scenario(
            root_files={"a.txt": "one\ntwo\nthree\n"},
            steps=[{"files": {"a.txt": "one\nFEATURE\nthree\n"},
                    "message": "feature edits line two"}],
            advance={"files": {"a.txt": "one\nBASE\nthree\n"},
                     "message": "base edits line two"},
            **kw)

    def _snapshot(self, pr, path, name="pub"):
        base = git(path, "rev-parse", "refs/heads/main")
        head = git(path, "rev-parse", "refs/heads/feature")
        pr_now = self.prs.get_pull_request(
            self.owner, "volmarr", name, pr.number)
        raw_pr = tuple(self.conn.execute(
            "SELECT * FROM pull_requests WHERE issue_id = ?",
            (pr.row_id,)).fetchone())
        raw_issue = tuple(self.conn.execute(
            "SELECT * FROM issues WHERE id = ?",
            (pr.row_id,)).fetchone())
        return base, head, pr_now, raw_pr, raw_issue

    def _audit_count(self, action):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = ?",
            (action,)).fetchone()
        return int(row["c"])

    def _audit_rows(self, action):
        return self.conn.execute(
            "SELECT target_id, outcome, detail FROM audit_log"
            " WHERE action = ? ORDER BY seq", (action,)).fetchall()

    def _show(self, repo, oid, fmt):
        return git(repo, "show", "-s", f"--format={fmt}", oid)

    def _file(self, repo, oid, path):
        return git(repo, "show", f"{oid}:{path}")

    def _words(self, report):
        words = getattr(report, "words")
        return words() if callable(words) else words

    # -- clean landings (I1, I2, I4) --------------------------------------
    def test_clean_rebase_two_commits_onto_advanced_base(self):
        pr, path, _root, heads, advanced = self._two_step_scenario()
        report = self.rebase.rebase_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(report.up_to_date)
        self.assertEqual(report.full_name, "volmarr/pub")
        self.assertEqual(report.number, pr.number)
        self.assertEqual(report.base_branch, "main")
        self.assertEqual(report.head_branch, "feature")
        # Every head commit replayed exactly once, in order.
        self.assertEqual([old for old, _new in report.replayed], heads)
        new_oids = [new for _old, new in report.replayed]
        self.assertNotEqual(new_oids, heads)
        self.assertEqual(report.base_before, advanced)
        self.assertEqual(report.base_after, new_oids[-1])
        self.assertEqual(report.head_oid, heads[-1])
        # The base ref lands on the replayed tip.
        self.assertEqual(git(path, "rev-parse", "refs/heads/main"),
                         new_oids[-1])
        # History is linear from the old base: single parents,
        # no merges, the old base an ancestor of the new tip.
        self.assertEqual(self._show(path, new_oids[0], "%P"), advanced)
        self.assertEqual(self._show(path, new_oids[1], "%P"), new_oids[0])
        self.assertEqual(
            git(path, "merge-base", advanced, new_oids[-1]), advanced)
        self.assertEqual(
            git(path, "rev-list", "--merges",
                f"{advanced}..{new_oids[-1]}"), "")
        self.assertEqual(
            git(path, "rev-list", "--reverse",
                f"{advanced}..{new_oids[-1]}").splitlines(), new_oids)
        # Both sides' non-conflicting changes are in the tree.
        self.assertEqual(self._file(path, new_oids[-1], "a.txt"),
                         "alpha\nfour")
        self.assertEqual(self._file(path, new_oids[-1], "b.txt"),
                         "bee\none\ntwo")
        self.assertEqual(self._file(path, new_oids[-1], "c.txt"), "see")

    def test_message_and_author_preserved_on_replay(self):
        author = ("Head Author", "head@example.com")
        committer = ("Commit Person", "commit@example.com")
        when = self._tick()
        pr, path, _root, heads, _adv = self._scenario(
            root_files={"a.txt": "alpha\n"},
            steps=[{"files": {"a.txt": "alpha\nbeta\n"},
                    "message": "feature work\n\nwith a body line",
                    "author": author, "committer": committer,
                    "when": when}],
            advance={"files": {"a.txt": "alpha\n", "b.txt": "bee\n"},
                     "message": "base advances"})
        report = self.rebase.rebase_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        (old, new), = report.replayed
        self.assertEqual(old, heads[0])
        for fmt in ("%an", "%ae", "%at", "%cn", "%ce", "%B"):
            self.assertEqual(self._show(path, new, fmt),
                             self._show(path, old, fmt), msg=fmt)
        self.assertEqual(self._show(path, new, "%an"), "Head Author")
        self.assertEqual(self._show(path, new, "%ae"), "head@example.com")
        # Committer date is the store clock's now, per DESIGN.
        self.assertEqual(self._show(path, new, "%ct"),
                         str(self.clock.now))

    def test_single_commit_head_rebases(self):
        pr, path, _root, heads, advanced = self._scenario(
            root_files={"a.txt": "alpha\n"},
            steps=[{"files": {"a.txt": "alpha\nbeta\n"},
                    "message": "only step"}],
            advance={"files": {"a.txt": "alpha\n", "b.txt": "bee\n"},
                     "message": "base advances"})
        report = self.rebase.rebase_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(report.up_to_date)
        self.assertEqual([old for old, _n in report.replayed], heads)
        self.assertEqual(report.base_before, advanced)
        self.assertEqual(git(path, "rev-parse", "refs/heads/main"),
                         report.base_after)
        self.assertEqual(self._file(path, report.base_after, "a.txt"),
                         "alpha\nbeta")
        self.assertEqual(self._file(path, report.base_after, "b.txt"),
                         "bee")

    def test_head_with_merge_commit_replays_by_first_parent(self):
        # DESIGN A3: a merge commit in the head history is
        # replayed by its first-parent diff and flattened.
        path = self.path
        root = make_commit(path, None,
                           {"a.txt": "alpha\n", "b.txt": "bee\n"},
                           "root commit", when=self._tick())
        git(path, "update-ref", "refs/heads/main", root)
        side = make_commit(path, root,
                           {"a.txt": "alpha\n", "b.txt": "bee\nside\n"},
                           "side work", when=self._tick())
        first = make_commit(
            path, root,
            {"a.txt": "alpha\n", "b.txt": "bee\n", "c.txt": "see\n"},
            "feature start", when=self._tick())
        merge = make_merge_commit(
            path, first, side,
            {"a.txt": "alpha\n", "b.txt": "bee\nside\n",
             "c.txt": "see\n"},
            "merge side in", when=self._tick())
        git(path, "update-ref", "refs/heads/feature", merge)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub",
            base_branch="main", head_branch="feature")
        advanced = make_commit(
            path, root, {"a.txt": "alpha\nfour\n", "b.txt": "bee\n"},
            "base advances", when=self._tick())
        git(path, "update-ref", "refs/heads/main", advanced)
        report = self.rebase.rebase_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(report.up_to_date)
        self.assertEqual([old for old, _n in report.replayed],
                         [side, first, merge])
        subjects = [self._show(path, new, "%s")
                    for _o, new in report.replayed]
        self.assertEqual(subjects,
                         ["side work", "feature start", "merge side in"])
        # The landed history is linear: the merge is flattened.
        for _o, new in report.replayed:
            self.assertEqual(len(self._show(path, new, "%P").split()), 1)
        self.assertEqual(
            git(path, "rev-list", "--merges",
                f"{advanced}..{report.base_after}"), "")
        self.assertEqual(self._file(path, report.base_after, "a.txt"),
                         "alpha\nfour")
        self.assertEqual(self._file(path, report.base_after, "b.txt"),
                         "bee\nside")
        self.assertEqual(self._file(path, report.base_after, "c.txt"),
                         "see")

    def test_head_branch_never_moves_on_success(self):
        pr, path, _root, heads, _adv = self._two_step_scenario()
        before = git(path, "rev-parse", "refs/heads/feature")
        report = self.rebase.rebase_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(git(path, "rev-parse", "refs/heads/feature"),
                         before)
        self.assertEqual(before, heads[-1])
        self.assertEqual(report.head_oid, before)

    # -- up to date (I6 and the no-op roads) ------------------------------
    def test_already_up_to_date_when_head_stands_on_current_base(self):
        pr, path, _root, _heads, _adv = self._scenario(
            root_files={"a.txt": "alpha\n"},
            steps=[{"files": {"a.txt": "alpha\nbeta\n"},
                    "message": "feature work"}])
        before = self._snapshot(pr, path)
        report = self.rebase.rebase_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(report.up_to_date)
        self.assertEqual(report.replayed, ())
        self.assertEqual(report.base_before, report.base_after)
        self.assertEqual(report.base_after, before[0])
        self.assertIn("up to date", self._words(report).lower())
        self.assertEqual(self._snapshot(pr, path), before)
        self.assertEqual(self._audit_count("repo.pull_request.rebase"), 0)

    def test_nothing_to_replay_is_up_to_date(self):
        pr, path, _root, heads, _adv = self._scenario(
            root_files={"a.txt": "alpha\n"},
            steps=[{"files": {"a.txt": "alpha\nbeta\n"},
                    "message": "feature work"}])
        # The head's work already stands on main (landed by
        # some other road): the replay range is empty.
        git(path, "update-ref", "refs/heads/main", heads[-1])
        before = self._snapshot(pr, path)
        report = self.rebase.rebase_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(report.up_to_date)
        self.assertEqual(report.base_after, heads[-1])
        self.assertEqual(self._snapshot(pr, path), before)
        self.assertEqual(self._audit_count("repo.pull_request.rebase"), 0)

    def test_second_call_after_landing_reports_up_to_date(self):
        pr, path, _root, _heads, _adv = self._two_step_scenario()
        first = self.rebase.rebase_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(first.up_to_date)
        before = self._snapshot(pr, path)
        second = self.rebase.rebase_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(second.up_to_date)
        self.assertEqual(second.base_before, first.base_after)
        self.assertEqual(second.base_after, first.base_after)
        self.assertEqual(self._snapshot(pr, path), before)
        self.assertEqual(self._audit_count("repo.pull_request.rebase"), 1)

    # -- the loud refusal and no half-states (I3) -------------------------
    def test_conflict_refused_loudly(self):
        pr, path, _root, heads, _adv = self._conflict_scenario()
        with self.assertRaises(PullRequestError) as caught:
            self.rebase.rebase_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        err = caught.exception
        self.assertEqual(err.reason, "rebase_conflict")
        message = str(err)
        self.assertIn("feature edits line two", message)
        self.assertIn(heads[-1][:7], message)
        self.assertIn("a.txt", message)
        self.assertEqual(self._audit_count("repo.pull_request.rebase"), 0)

    def test_conflict_leaves_no_half_state(self):
        pr, path, _root, _heads, _adv = self._conflict_scenario()
        before = self._snapshot(pr, path)
        with self.assertRaises(PullRequestError) as caught:
            self.rebase.rebase_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, "rebase_conflict")
        # Base ref, head ref and the PR row identical.
        self.assertEqual(self._snapshot(pr, path), before)
        self.assertEqual(self._audit_count("repo.pull_request.rebase"), 0)

    def test_second_commit_conflict_leaves_no_half_state(self):
        # I3: the FIRST head commit replays cleanly and the
        # SECOND conflicts — still nothing may have moved.
        pr, path, _root, heads, _adv = self._scenario(
            root_files={"a.txt": "one\ntwo\nthree\n",
                        "b.txt": "bee\n"},
            steps=[
                {"files": {"a.txt": "one\ntwo\nthree\n",
                           "b.txt": "bee\nclean\n"},
                 "message": "clean step"},
                {"files": {"a.txt": "one\nFEAT\nthree\n",
                           "b.txt": "bee\nclean\n"},
                 "message": "clashing step"},
            ],
            advance={"files": {"a.txt": "one\nBASE\nthree\n",
                               "b.txt": "bee\n"},
                     "message": "base clash"})
        before = self._snapshot(pr, path)
        with self.assertRaises(PullRequestError) as caught:
            self.rebase.rebase_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        err = caught.exception
        self.assertEqual(err.reason, "rebase_conflict")
        message = str(err)
        self.assertIn("clashing step", message)
        self.assertIn(heads[1][:7], message)
        self.assertIn("a.txt", message)
        self.assertEqual(self._snapshot(pr, path), before)
        self.assertEqual(self._audit_count("repo.pull_request.rebase"), 0)

    # -- permission and readiness fire first (I5) -------------------------
    def test_private_repo_stranger_gets_pull_request_not_found(self):
        pr, path, _root, _heads, _adv = self._scenario(
            name="priv", visibility="private",
            root_files={"s.txt": "s\n"},
            steps=[{"files": {"s.txt": "s\nmore\n"},
                    "message": "feature work"}],
            advance={"files": {"s.txt": "s\n", "t.txt": "t\n"},
                     "message": "base advances"})
        before = self._snapshot(pr, path, name="priv")
        with self.assertRaises(PullRequestError) as caught:
            self.rebase.rebase_pull_request(
                self.reader, "volmarr", "priv", pr.number)
        self.assertEqual(caught.exception.reason,
                         "pull_request_not_found")
        self.assertEqual(self._snapshot(pr, path, name="priv"), before)
        self.assertEqual(self._audit_count("repo.pull_request.rebase"), 0)

    def test_public_repo_non_writer_non_author_gets_permission_denied(self):
        pr, path, _root, _heads, _adv = self._two_step_scenario()
        before = self._snapshot(pr, path)
        with self.assertRaises(PullRequestError) as caught:
            self.rebase.rebase_pull_request(
                self.third, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertIn("permission_denied", str(caught.exception))
        self.assertEqual(self._snapshot(pr, path), before)
        self.assertEqual(self._audit_count("repo.pull_request.rebase"), 0)

    def test_closed_pull_request_refused_before_landing(self):
        pr, path, _root, _heads, _adv = self._two_step_scenario()
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE id = ?",
                (pr.row_id,))
        before = self._snapshot(pr, path)
        with self.assertRaises(PullRequestError) as caught:
            self.rebase.rebase_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, "pull_request_closed")
        self.assertIn("closed", str(caught.exception))
        self.assertEqual(self._snapshot(pr, path), before)
        self.assertEqual(self._audit_count("repo.pull_request.rebase"), 0)

    def test_draft_pull_request_refused_before_landing(self):
        pr, path, _root, _heads, _adv = self._two_step_scenario(
            draft=True)
        before = self._snapshot(pr, path)
        with self.assertRaises(PullRequestError) as caught:
            self.rebase.rebase_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, "pull_request_draft")
        self.assertIn("draft", str(caught.exception))
        self.assertEqual(self._snapshot(pr, path), before)
        self.assertEqual(self._audit_count("repo.pull_request.rebase"), 0)

    def test_readiness_refusal_precedes_conflict_check(self):
        pr, path, _root, _heads, _adv = self._conflict_scenario(
            draft=True)
        before = self._snapshot(pr, path)
        with self.assertRaises(PullRequestError) as caught:
            self.rebase.rebase_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, "pull_request_draft")
        self.assertEqual(self._snapshot(pr, path), before)

    def test_permission_refusal_precedes_conflict_check(self):
        pr, path, _root, _heads, _adv = self._conflict_scenario()
        before = self._snapshot(pr, path)
        with self.assertRaises(PullRequestError) as caught:
            self.rebase.rebase_pull_request(
                self.third, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertEqual(self._snapshot(pr, path), before)

    # -- audit and render ---------------------------------------------------
    def test_audit_records_exactly_one_rebase_event_with_detail(self):
        pr, path, _root, _heads, advanced = self._two_step_scenario()
        report = self.rebase.rebase_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        rows = self._audit_rows("repo.pull_request.rebase")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["target_id"], f"volmarr/pub#{pr.number}")
        self.assertEqual(row["outcome"], "success")
        detail = json.loads(row["detail"])
        self.assertEqual(detail["number"], pr.number)
        self.assertEqual(detail["replayed"], 2)
        self.assertEqual(detail["base_before"], advanced)
        self.assertEqual(detail["base_after"], report.base_after)

    def test_render_says_the_outcome_in_words(self):
        pr, path, _root, _heads, _adv = self._two_step_scenario()
        report = self.rebase.rebase_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        words = self._words(report)
        self.assertIn("rebas", words.lower())
        text = render_rebase_report(report)
        self.assertIsInstance(text, str)
        self.assertIn(words, text)
        self.assertIn("rebas", text.lower())

    def test_schema_and_taxonomy_counts(self):
        self.assertEqual(db.schema_version(self.conn), 88)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 127)
        self.assertIn("repo.pull_request.rebase", taxonomy.AUDIT_EVENTS)


if __name__ == "__main__":
    unittest.main()
