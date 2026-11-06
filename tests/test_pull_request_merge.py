"""S-153 acceptance battery: pull request merge (merge commit).

Acceptance (roadmap S-153): merge: merge commit — with PR
title/body as the default message, editable, closing keywords
executed on landing.

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
from samverk.db import schema_version
from samverk.forks import ForkStore
from samverk.issues import IssueStore
from samverk.pull_request_drafts import PullRequestDraftStore
from samverk.pull_request_merge import (
    PullRequestMergeStore, default_message, render_merge,
    render_merge_preview)
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


def git_rc(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    return out.returncode


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


def make_commit(repo, parent, files, message, parents=()):
    tree = make_tree(repo, files)
    args = ["commit-tree", tree]
    for p in ((parent,) if parent else ()) + tuple(parents):
        args += ["-p", p]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class MergeTests(unittest.TestCase):
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
        self.drafts = PullRequestDraftStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.merge = PullRequestMergeStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")

    # -- helpers ---------------------------------------------------------
    def _open(self, *, title=None, body="", base_files=None,
              head_files=None, draft=False, repo="pub",
              actor=None):
        actor = actor or self.owner
        if repo != "pub":
            self.repos.create_repository(
                self.owner.id, "volmarr", repo, visibility="public")
        path = self.repos.path_for("volmarr", repo)
        base_files = base_files or {"a.txt": "alpha\n"}
        head_files = head_files if head_files is not None \
            else {"a.txt": "alpha\nbeta\n"}
        base_oid = make_commit(path, None, base_files, "base")
        git(path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(path, base_oid, head_files,
                               "feature work")
        git(path, "update-ref", "refs/heads/feature", head_oid)
        pr = self.prs.create_pull_request(
            actor, "volmarr", repo, base_branch="main",
            head_branch="feature", title=title, body=body,
            draft=draft)
        return pr, path, base_oid, head_oid

    def _issue(self, title="A bug", body="", repo="pub"):
        return self.issues.create_issue(
            self.owner, "volmarr", repo, title, body)

    def _audit_count(self, action):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = ?",
            (action,)).fetchone()
        return int(row["c"])

    def _parents(self, path, oid):
        out = git(path, "show", "-s", "--format=%P", oid)
        return out.split() if out else []

    def _tip(self, path, branch="main"):
        return git(path, "rev-parse", f"refs/heads/{branch}")

    # -- the default message ---------------------------------------------
    def test_default_message_is_title_then_body(self):
        pr, _p, _b, _h = self._open(title="Fix the thing",
                                    body="Because it was broken.")
        self.assertEqual(default_message(pr),
                         "Fix the thing\n\nBecause it was broken.")
        pr2, _p2, _b2, _h2 = self._open(title="Solo title",
                                        repo="pub2")
        self.assertEqual(default_message(pr2), "Solo title")

    def test_merge_lands_with_default_message_and_two_parents(self):
        pr, path, base_oid, head_oid = self._open(
            title="Fix the thing", body="Because it was broken.")
        result = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(result.pull_request.state, "closed")
        self.assertEqual(result.message,
                         "Fix the thing\n\nBecause it was broken.")
        self.assertEqual(self._tip(path), result.merge_commit_oid)
        self.assertEqual(self._parents(path, result.merge_commit_oid),
                         [base_oid, head_oid])
        self.assertEqual(
            git(path, "show", "-s", "--format=%T",
                result.merge_commit_oid),
            git(path, "show", "-s", "--format=%T", head_oid))
        self.assertEqual(
            git(path, "show", "-s", "--format=%B",
                result.merge_commit_oid),
            "Fix the thing\n\nBecause it was broken.")
        author = git(path, "show", "-s", "--format=%an <%ae>",
                     result.merge_commit_oid)
        self.assertEqual(author, "volmarr <volmarr@samverk.invalid>")
        row = self.conn.execute(
            "SELECT * FROM pull_request_merges"
            " WHERE pull_request_id = ?", (pr.id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["merge_commit_oid"],
                         result.merge_commit_oid)
        self.assertEqual(row["message"], result.message)
        self.assertEqual(row["merged_by"], self.owner.id)
        self.assertEqual(
            self._audit_count("repo.pull_request.merge"), 1)
        self.assertIn("Merged", result.words)

    def test_edited_message_replaces_the_default_whole(self):
        pr, path, _b, _h = self._open(title="Fix the thing",
                                      body="Long body.")
        result = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number,
            message="Land it: the short version")
        self.assertEqual(
            git(path, "show", "-s", "--format=%B",
                result.merge_commit_oid),
            "Land it: the short version")
        self.assertEqual(result.message, "Land it: the short version")

    def test_preview_says_the_plan_in_words(self):
        bug = self._issue("Crash on save")
        pr, _p, base_oid, head_oid = self._open(
            title="Fix the crash", body=f"Fixes #{bug.number}")
        preview = self.merge.preview_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(preview.can_merge)
        self.assertEqual(preview.blockers, ())
        self.assertEqual(preview.base_oid, base_oid)
        self.assertEqual(preview.head_oid, head_oid)
        self.assertEqual(preview.ahead, 1)
        self.assertEqual(preview.behind, 0)
        self.assertEqual(preview.default_message,
                         f"Fix the crash\n\nFixes #{bug.number}")
        self.assertEqual(len(preview.closings), 1)
        self.assertTrue(preview.closings[0].will_close)
        self.assertIn(f"Will close volmarr/pub#{bug.number}",
                      preview.closings[0].notice)
        html = render_merge_preview(preview)
        self.assertIn("Ready to merge", html)

    # -- closing keywords executed on landing ------------------------------
    def test_closing_keywords_execute_on_landing(self):
        bug = self._issue("Crash on save")
        other = self._issue("Mentioned only")
        pr, _p, _b, _h = self._open(
            title="Fix the crash",
            body=(f"Fixes #{bug.number}. "
                  f"See also #{other.number}."))
        result = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        closed = self.issues.get_issue(
            self.owner, "volmarr", "pub", bug.number)
        self.assertEqual(closed.state, "closed")
        self.assertEqual(closed.state_reason, "completed")
        untouched = self.issues.get_issue(
            self.owner, "volmarr", "pub", other.number)
        self.assertEqual(untouched.state, "open")
        self.assertEqual(result.closed_issues,
                         (f"volmarr/pub#{bug.number}",))
        events = self.issues.state_events_for(
            self.owner, "volmarr", "pub", bug.number)
        self.assertEqual([e.kind for e in events], ["closed"])
        self.assertIn(f"Closed on landing: volmarr/pub#{bug.number}",
                      result.words)
        self.assertIn("merge", render_merge(result))

    def test_closing_keyword_in_a_comment_executes_too(self):
        bug = self._issue("Crash on save")
        pr, _p, _b, _h = self._open(title="Fix the crash")
        from samverk.pull_request_conversation import (
            PullRequestConversationStore)
        convo = PullRequestConversationStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        convo.add_comment(self.owner, "volmarr", "pub", pr.number,
                          f"This resolves #{bug.number} as well.")
        result = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(result.closed_issues,
                         (f"volmarr/pub#{bug.number}",))
        self.assertEqual(self.issues.get_issue(
            self.owner, "volmarr", "pub", bug.number).state,
            "closed")

    def test_already_closed_issue_is_not_closed_twice(self):
        bug = self._issue("Crash on save")
        self.issues.close_issue(self.owner, "volmarr", "pub",
                                bug.number)
        pr, _p, _b, _h = self._open(
            title="Fix the crash", body=f"Fixes #{bug.number}")
        preview = self.merge.preview_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(len(preview.closings), 1)
        self.assertFalse(preview.closings[0].will_close)
        result = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(result.closed_issues, ())
        events = self.issues.state_events_for(
            self.owner, "volmarr", "pub", bug.number)
        self.assertEqual([e.kind for e in events], ["closed"])

    def test_cross_repository_closing_executes(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "lib", visibility="public")
        lib_path = self.repos.path_for("volmarr", "lib")
        lib_base = make_commit(lib_path, None, {"l.txt": "lib\n"},
                               "lib base")
        git(lib_path, "update-ref", "refs/heads/main", lib_base)
        bug = self.issues.create_issue(
            self.owner, "volmarr", "lib", "Lib bug")
        pr, _p, _b, _h = self._open(
            title="Fix across repos",
            body=f"Fixes volmarr/lib#{bug.number}")
        result = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(result.closed_issues,
                         (f"volmarr/lib#{bug.number}",))
        self.assertEqual(self.issues.get_issue(
            self.owner, "volmarr", "lib", bug.number).state,
            "closed")

    # -- refusals burn nothing ---------------------------------------------
    def test_draft_cannot_merge_until_marked_ready(self):
        pr, path, base_oid, _h = self._open(draft=True)
        with self.assertRaises(PullRequestError) as caught:
            self.merge.merge_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason,
                         "pull_request_draft")
        self.assertEqual(self._tip(path), base_oid)
        self.assertEqual(
            self._audit_count("repo.pull_request.merge"), 0)
        self.drafts.mark_ready(self.owner, "volmarr", "pub",
                               pr.number)
        result = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(result.pull_request.state, "closed")

    def test_closed_pull_request_refused_and_remerge_refused(self):
        pr, path, _b, _h = self._open()
        self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        with self.assertRaises(PullRequestError) as caught:
            self.merge.merge_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason,
                         "pull_request_closed")
        rows = self.conn.execute(
            "SELECT COUNT(*) AS c FROM pull_request_merges"
            ).fetchone()
        self.assertEqual(int(rows["c"]), 1)

    def test_conflicting_branches_refused_loudly(self):
        base_files = {"a.txt": "alpha\n"}
        base_oid = make_commit(self.path, None, base_files, "base")
        git(self.path, "update-ref", "refs/heads/main", base_oid)
        main2 = make_commit(self.path, base_oid,
                            {"a.txt": "alpha main\n"}, "main moves")
        git(self.path, "update-ref", "refs/heads/main", main2)
        head_oid = make_commit(self.path, base_oid,
                               {"a.txt": "alpha feature\n"},
                               "feature work")
        git(self.path, "update-ref", "refs/heads/feature", head_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature")
        preview = self.merge.preview_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(preview.can_merge)
        self.assertTrue(preview.conflicts)
        with self.assertRaises(PullRequestError) as caught:
            self.merge.merge_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, "merge_conflict")
        self.assertEqual(self._tip(self.path), main2)
        self.assertEqual(
            self.prs.get_pull_request(
                self.owner, "volmarr", "pub", pr.number).state,
            "open")

    def test_head_already_contained_is_already_merged(self):
        pr, path, base_oid, head_oid = self._open()
        git(path, "update-ref", "refs/heads/main", head_oid)
        with self.assertRaises(PullRequestError) as caught:
            self.merge.merge_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, "already_merged")
        self.assertEqual(
            self.prs.get_pull_request(
                self.owner, "volmarr", "pub", pr.number).state,
            "open")

    def test_mere_reader_cannot_merge(self):
        pr, path, base_oid, _h = self._open()
        with self.assertRaises(PullRequestError) as caught:
            self.merge.merge_pull_request(
                self.reader, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason,
                         "permission_denied")
        self.assertEqual(self._tip(path), base_oid)
        preview = self.merge.preview_merge(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(preview.can_merge)

    def test_blank_edited_message_refused(self):
        pr, path, base_oid, _h = self._open()
        for bad in ("", "   \n  ", 42):
            with self.assertRaises(PullRequestError) as caught:
                self.merge.merge_pull_request(
                    self.owner, "volmarr", "pub", pr.number,
                    message=bad)
            self.assertEqual(caught.exception.reason,
                             "message_invalid", msg=repr(bad))
        self.assertEqual(self._tip(path), base_oid)

    def test_diverged_but_clean_merge_combines_both_sides(self):
        base_files = {"a.txt": "alpha\n"}
        base_oid = make_commit(self.path, None, base_files, "base")
        git(self.path, "update-ref", "refs/heads/main", base_oid)
        main2 = make_commit(
            self.path, base_oid,
            {"a.txt": "alpha\n", "b.txt": "from main\n"},
            "main moves")
        git(self.path, "update-ref", "refs/heads/main", main2)
        head_oid = make_commit(
            self.path, base_oid,
            {"a.txt": "alpha\n", "c.txt": "from feature\n"},
            "feature work")
        git(self.path, "update-ref", "refs/heads/feature", head_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature", title="Combine us")
        result = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(self._parents(self.path,
                                       result.merge_commit_oid),
                         [main2, head_oid])
        merged_tree = git(self.path, "ls-tree", "--name-only",
                          result.merge_commit_oid)
        self.assertEqual(merged_tree.split(),
                         ["a.txt", "b.txt", "c.txt"])

    def test_cross_fork_merge_fetches_and_lands(self):
        from samverk.pull_request_forks import ForkPullRequestStore
        base_oid = make_commit(self.path, None,
                               {"a.txt": "alpha\n"}, "base")
        git(self.path, "update-ref", "refs/heads/main", base_oid)
        self.forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fork_head = make_commit(
            fork_path, base_oid, {"a.txt": "alpha\nfrom the fork\n"},
            "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        opened = xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub",
            head_branch="feature", title="From the fork")
        result = self.merge.merge_pull_request(
            self.owner, "volmarr", "pub", opened.number)
        self.assertEqual(self._tip(self.path),
                         result.merge_commit_oid)
        self.assertEqual(self._parents(self.path,
                                       result.merge_commit_oid),
                         [base_oid, fork_head])
        self.assertEqual(
            git_rc(self.path, "rev-parse", "--verify", "--quiet",
                   "refs/samverk-merge/head"), 1)
        row = self.conn.execute(
            "SELECT * FROM pull_request_merges"
            " WHERE merge_commit_oid = ?",
            (result.merge_commit_oid,)).fetchone()
        self.assertEqual(row["head_oid"], fork_head)

    def test_merge_event_is_in_the_taxonomy(self):
        self.assertIn("repo.pull_request.merge", taxonomy.AUDIT_EVENTS)
        self.assertEqual(schema_version(self.conn), 65)


if __name__ == "__main__":
    unittest.main()
