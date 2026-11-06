"""S-160 acceptance battery: pull request revert.

Acceptance (roadmap S-160): revert — one-click PR that
reverts a merged PR, linked both ways.

Merges are simulated honestly, the way S-153 lands
them (that slice is a parallel branch, not in this
base): a real two-parent merge commit minted by
plumbing and moved onto the base branch, the pull
request's row closed, and its recorded base/head oids
refreshed to the tips that landed.

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
from samverk.forks import ForkStore
from samverk.issues import IssueStore
from samverk.pull_request_forks import ForkPullRequestStore
from samverk.pull_request_revert import (
    PullRequestRevertStore, render_revert_links,
    render_revert_preview, render_revert_result)
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


BASE_FILES = {"a.txt": "alpha\nbeta\n", "keep.txt": "keep\n"}
FEATURE_FILES = {"a.txt": "alpha\nBETA\n", "keep.txt": "keep\n",
                 "b.txt": "new file\n"}


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class PullRequestRevertTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register(
            "volmarr", "correct horse battery")
        self.reader = self.accounts.register(
            "yrsa", "correct horse battery")
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.forks = ForkStore(self.conn, self.root, self.accounts,
                               self.repos, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.revert = PullRequestRevertStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")

    # -- helpers ----------------------------------------------------
    def _open(self, name="pub", title="Feature work"):
        path = self.repos.path_for("volmarr", name)
        base_oid = make_commit(path, [], BASE_FILES, "base")
        git(path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(
            path, [base_oid], FEATURE_FILES, "feature work")
        git(path, "update-ref", "refs/heads/feature", head_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", name, base_branch="main",
            head_branch="feature", title=title)
        return pr, path, base_oid, head_oid

    def _merge(self, pr, path, base_oid, head_oid,
               files=FEATURE_FILES):
        """Land a PR the S-153 way: merge commit on the base,
        the PR closed, its recorded oids refreshed."""
        merge_oid = make_commit(
            path, [base_oid, head_oid], files,
            f"Merge pull request #{pr.number}")
        git(path, "update-ref", "refs/heads/main", merge_oid)
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE id = ?",
                (pr.row_id,))
            self.conn.execute(
                "UPDATE pull_requests SET base_oid = ?,"
                " head_oid = ? WHERE issue_id = ?",
                (base_oid, head_oid, pr.row_id))
        return merge_oid

    def _merged(self, name="pub", title="Feature work"):
        pr, path, base_oid, head_oid = self._open(name, title)
        merge_oid = self._merge(pr, path, base_oid, head_oid)
        return pr, path, base_oid, head_oid, merge_oid

    def _close(self, pr):
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE id = ?",
                (pr.row_id,))

    def _ref(self, path, branch):
        out = subprocess.run(
            ["git", f"--git-dir={path}", "rev-parse", "--verify",
             "--quiet", f"refs/heads/{branch}"], capture_output=True)
        return out.stdout.decode().strip() if out.returncode == 0 \
            else None

    def _show(self, path, oid, name):
        return git(path, "show", f"{oid}:{name}")

    def _audit_count(self, action):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = ?",
            (action,)).fetchone()
        return int(row["c"])

    def _link_rows(self):
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM pull_request_reverts"
        ).fetchone()["c"]

    # -- the happy road ---------------------------------------------
    def test_revert_merged_pr_creates_linked_open_pr(self):
        pr, path, base_oid, head_oid, merge_oid = self._merged()
        result = self.revert.revert_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(result.original.number, pr.number)
        self.assertEqual(result.revert.state, "open")
        self.assertEqual(result.branch,
                         f"revert-{pr.number}-feature")
        self.assertEqual(result.merged_oid, merge_oid)
        self.assertEqual(result.pre_merge_oid, base_oid)
        tip = self._ref(path, result.branch)
        self.assertEqual(tip, result.commit_oid)
        # The revert commit undoes the landed change, exactly.
        self.assertEqual(self._show(path, tip, "a.txt"),
                         "alpha\nbeta")
        names = git(path, "ls-tree", "-r", "--name-only", tip)
        self.assertNotIn("b.txt", names.splitlines())
        self.assertIn("reverts pull request", result.words)
        # The link, both ways.
        forward = self.revert.revert_of(
            self.owner, "volmarr", "pub", result.revert.number)
        self.assertIsNotNone(forward)
        self.assertEqual(forward.original_number, pr.number)
        self.assertEqual(forward.revert_commit_oid,
                         result.commit_oid)
        back = self.revert.reverted_by(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual([r.revert_number for r in back],
                         [result.revert.number])
        self.assertIn(f"#{result.revert.number}",
                      render_revert_result(result))

    def test_revert_pr_title_body_and_audit(self):
        pr, _p, _b, _h, merge_oid = self._merged(
            title="Add the new file")
        result = self.revert.revert_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(result.revert.title,
                         'Revert "Add the new file"')
        self.assertIn(f"Reverts #{pr.number}.", result.revert.body)
        self.assertIn(merge_oid, result.revert.body)
        self.assertEqual(
            self._audit_count("repo.pull_request.revert"), 1)
        row = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action = 'repo.pull_request.revert'"
        ).fetchone()
        import json
        detail = json.loads(row["detail"])
        self.assertEqual(detail["revert_number"],
                         result.revert.number)
        self.assertEqual(detail["number"], pr.number)
        self.assertNotIn("Add the new file", row["detail"])

    def test_explicit_pair_reverts_a_squash_landing(self):
        pr, path, base_oid, head_oid = self._open()
        squash = make_commit(path, [base_oid], FEATURE_FILES,
                             "feature work (squashed)")
        git(path, "update-ref", "refs/heads/main", squash)
        self._close(pr)
        result = self.revert.revert_pull_request(
            self.owner, "volmarr", "pub", pr.number,
            merged_oid=squash, pre_merge_oid=base_oid)
        self.assertEqual(result.merged_oid, squash)
        self.assertEqual(
            self._show(path, result.commit_oid, "a.txt"),
            "alpha\nbeta")

    def test_merge_record_pair_is_used_when_table_exists(self):
        pr, path, base_oid, head_oid = self._open()
        squash = make_commit(path, [base_oid], FEATURE_FILES,
                             "feature work (squashed)")
        git(path, "update-ref", "refs/heads/main", squash)
        self._close(pr)
        with self.conn:
            # On the team branch the merges table did not
            # exist yet, so the battery created its shape;
            # at banking (S-160 heal) the real table from
            # migrations 58/59 is already there — create
            # only if missing, and insert with the columns
            # the seam reads, filling the unified table's
            # other NOT NULL columns explicitly.
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS pull_request_merges ("
                " pull_request_id INTEGER,"
                " merge_commit_oid TEXT, base_oid TEXT)")
            self.conn.execute(
                "INSERT INTO pull_request_merges"
                " (pull_request_id, merge_commit_oid, base_oid,"
                " base_branch, head_branch, head_oid, merged_by)"
                " VALUES (?, ?, ?, 'main', 'feature', ?, ?)",
                (pr.id, squash, base_oid, head_oid, self.owner.id))
        result = self.revert.revert_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(result.merged_oid, squash)
        self.assertEqual(result.pre_merge_oid, base_oid)

    # -- merged-only validation ---------------------------------------
    def test_open_pr_is_not_merged(self):
        pr, path, _b, _h = self._open()
        with self.assertRaises(PullRequestError) as caught:
            self.revert.revert_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason,
                         "pull_request_not_merged")
        self.assertIsNone(
            self._ref(path, f"revert-{pr.number}-feature"))
        self.assertEqual(self._link_rows(), 0)

    def test_closed_but_unmerged_pr_is_refused(self):
        pr, path, _b, _h = self._open()
        self._close(pr)
        with self.assertRaises(PullRequestError) as caught:
            self.revert.revert_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason,
                         "pull_request_not_merged")
        self.assertEqual(self._link_rows(), 0)

    def test_reader_cannot_revert(self):
        pr, _p, _b, _h, _m = self._merged()
        with self.assertRaises(PullRequestError) as caught:
            self.revert.revert_pull_request(
                self.reader, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason,
                         "permission_denied")
        self.assertEqual(self._link_rows(), 0)

    def test_stranger_to_private_repo_gets_uniform_not_found(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        pr, _p, _b, _h, _m = self._merged(name="priv")
        with self.assertRaises(PullRequestError) as caught:
            self.revert.revert_pull_request(
                self.reader, "volmarr", "priv", pr.number)
        self.assertEqual(caught.exception.reason,
                         "pull_request_not_found")

    def test_cross_fork_pr_is_refused(self):
        base_oid = make_commit(self.path, [], BASE_FILES, "base")
        git(self.path, "update-ref", "refs/heads/main", base_oid)
        self.forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fork_head = make_commit(
            fork_path, [base_oid], FEATURE_FILES, "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        xpr = self.xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub",
            head_branch="feature")
        self._close(xpr.pull_request)
        with self.assertRaises(PullRequestError) as caught:
            self.revert.revert_pull_request(
                self.owner, "volmarr", "pub", xpr.number)
        self.assertEqual(caught.exception.reason,
                         "revert_cross_fork")
        self.assertEqual(self._link_rows(), 0)

    # -- refusal shapes -------------------------------------------------
    def test_second_revert_while_one_is_open_is_refused(self):
        pr, _p, _b, _h, _m = self._merged()
        first = self.revert.revert_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        with self.assertRaises(PullRequestError) as caught:
            self.revert.revert_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason,
                         "already_reverted")
        self.assertIn(f"#{first.revert.number}",
                      str(caught.exception))
        self.assertEqual(self._link_rows(), 1)

    def test_closed_unmerged_revert_does_not_block_a_fresh_one(self):
        pr, _p, _b, _h, _m = self._merged()
        first = self.revert.revert_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self._close(first.revert)
        second = self.revert.revert_pull_request(
            self.owner, "volmarr", "pub", pr.number,
            branch_name=f"revert-{pr.number}-second")
        self.assertNotEqual(second.revert.number,
                            first.revert.number)
        self.assertEqual(self._link_rows(), 2)
        back = self.revert.reverted_by(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(len(back), 2)

    def test_taken_branch_name_is_refused_and_burns_nothing(self):
        pr, path, _b, _h, _m = self._merged()
        git(path, "update-ref", "refs/heads/taken-name",
            self._ref(path, "main"))
        with self.assertRaises(PullRequestError) as caught:
            self.revert.revert_pull_request(
                self.owner, "volmarr", "pub", pr.number,
                branch_name="taken-name")
        self.assertEqual(caught.exception.reason, "branch_taken")
        self.assertEqual(self._link_rows(), 0)
        self.assertEqual(self.prs.list_pull_requests(
            self.owner, "volmarr", "pub"), [
                p for p in self.prs.list_pull_requests(
                    self.owner, "volmarr", "pub")
                if p.number == pr.number])

    def test_conflicting_revert_names_the_paths(self):
        pr, path, _b, _h, merge_oid = self._merged()
        later = make_commit(
            path, [merge_oid],
            {"a.txt": "alpha\nGAMMA\n", "keep.txt": "keep\n",
             "b.txt": "new file\n"}, "later work on the same line")
        git(path, "update-ref", "refs/heads/main", later)
        with self.assertRaises(PullRequestError) as caught:
            self.revert.revert_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason,
                         "revert_conflict")
        self.assertIn("a.txt", str(caught.exception))
        self.assertEqual(self._link_rows(), 0)
        self.assertEqual(
            self._audit_count("repo.pull_request.revert"), 0)

    def test_empty_revert_is_refused(self):
        pr, path, _b, _h, merge_oid = self._merged()
        undone = make_commit(path, [merge_oid], BASE_FILES,
                             "the change was undone by hand")
        git(path, "update-ref", "refs/heads/main", undone)
        with self.assertRaises(PullRequestError) as caught:
            self.revert.revert_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, "revert_empty")
        self.assertEqual(self._link_rows(), 0)

    # -- preview + rendering ----------------------------------------------
    def test_preview_says_ready_and_writes_nothing(self):
        pr, path, _b, _h, _m = self._merged()
        preview = self.revert.preview_revert(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(preview.can_revert)
        self.assertIn("Ready to revert", preview.words)
        self.assertIn("applies cleanly", preview.plan_words)
        self.assertIsNone(
            self._ref(path, f"revert-{pr.number}-feature"))
        html = render_revert_preview(preview)
        self.assertIn(preview.branch_name, html)
        open_pr, _p2, _b2, _h2 = self._open()
        blocked = self.revert.preview_revert(
            self.owner, "volmarr", "pub", open_pr.number)
        self.assertFalse(blocked.can_revert)
        self.assertIn("has not been merged", blocked.words)

    def test_links_render_both_ways_in_words(self):
        pr, _p, _b, _h, _m = self._merged()
        result = self.revert.revert_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        original_links = self.revert.links_for(
            self.owner, "volmarr", "pub", pr.number)
        html = render_revert_links(original_links)
        self.assertIn(f"was reverted by #{result.revert.number}",
                      html)
        revert_links = self.revert.links_for(
            self.owner, "volmarr", "pub", result.revert.number)
        self.assertIn(f"reverts #{pr.number}",
                      render_revert_links(revert_links))
        plain = self.revert.links_for(
            self.owner, "volmarr", "pub", pr.number)
        self.assertIn("was reverted by", plain.words)

    # -- the chain ----------------------------------------------------------
    def test_reverting_the_revert_reapplies_the_change(self):
        pr, path, base_oid, head_oid, merge_oid = self._merged()
        first = self.revert.revert_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        # Land the revert PR the S-153 way, then revert IT.
        landing = make_commit(
            path, [merge_oid, first.commit_oid], BASE_FILES,
            f"Merge pull request #{first.revert.number}")
        git(path, "update-ref", "refs/heads/main", landing)
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE id = ?",
                (first.revert.row_id,))
            self.conn.execute(
                "UPDATE pull_requests SET base_oid = ?,"
                " head_oid = ? WHERE issue_id = ?",
                (merge_oid, first.commit_oid, first.revert.row_id))
        second = self.revert.revert_pull_request(
            self.owner, "volmarr", "pub", first.revert.number)
        record = self.revert.revert_of(
            self.owner, "volmarr", "pub", second.revert.number)
        self.assertEqual(record.original_number,
                         first.revert.number)
        # The change is back: BETA restored, b.txt present again.
        self.assertEqual(
            self._show(path, second.commit_oid, "a.txt"),
            "alpha\nBETA")
        self.assertEqual(
            self._show(path, second.commit_oid, "b.txt"),
            "new file")

    # -- the record itself ----------------------------------------------------
    def test_migration_63_shape(self):
        self.assertEqual(db.schema_version(self.conn), 66)
        cols = {r["name"] for r in self.conn.execute(
            "PRAGMA table_info(pull_request_reverts)").fetchall()}
        self.assertTrue({
            "pull_request_id", "original_pull_request_id",
            "merged_oid", "pre_merge_oid", "revert_commit_oid",
            "revert_branch", "base_branch", "created_by",
            "created_at"} <= cols)
        pr, _p, _b, _h, _m = self._merged()
        result = self.revert.revert_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        row = self.conn.execute(
            "SELECT * FROM pull_request_reverts").fetchone()
        self.assertEqual(row["pull_request_id"], result.revert.id)
        self.assertEqual(row["original_pull_request_id"], pr.id)
        self.assertEqual(row["created_by"], self.owner.id)
        self.assertGreater(row["created_at"], 0)


if __name__ == "__main__":
    unittest.main()
