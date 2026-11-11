"""S-151 acceptance battery: pull request CODEOWNERS.

Acceptance (roadmap S-151): CODEOWNERS — file parsed
from the repo; matching owners auto-requested as
reviewers on open and on relevant pushes.

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
from samverk.codeowners import owners_for_path, parse_codeowners
from samverk.forks import ForkStore
from samverk.issues import IssueStore
from samverk.pull_request_codeowners import (
    PullRequestCodeownersStore, render_codeowners_requests)
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


def make_tree(repo, files):
    """A tree oid for a {path: content} mapping, nested
    paths built as real subtrees."""
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


class ParserTests(unittest.TestCase):
    def test_parser_skips_comments_and_blanks_and_keeps_line_numbers(self):
        parsed = parse_codeowners(
            "# a comment\n\n*.py @yrsa\n   \n# another\ndocs/ @tess\n")
        self.assertEqual(parsed.warnings, ())
        self.assertEqual(len(parsed.rules), 2)
        pattern, owners, line_no = parsed.rules[0]
        self.assertEqual((pattern, owners, line_no), ("*.py", ("@yrsa",), 3))
        self.assertEqual(parsed.rules[1].line_no, 6)
        self.assertEqual(parsed.rules[1].owners, ("@tess",))

    def test_parser_unassign_rule_clears_inherited_owners(self):
        parsed = parse_codeowners("* @yrsa\nsecret.txt\n")
        self.assertEqual(parsed.rules[1].owners, ())
        self.assertEqual(owners_for_path(parsed, "secret.txt"), ())
        self.assertEqual(owners_for_path(parsed.rules, "other.txt"),
                         ("@yrsa",))

    def test_last_matching_rule_wins(self):
        parsed = parse_codeowners("*.txt @yrsa\na.txt @tess\n")
        self.assertEqual(owners_for_path(parsed, "a.txt"), ("@tess",))
        self.assertEqual(owners_for_path(parsed, "b.txt"), ("@yrsa",))
        flipped = parse_codeowners("a.txt @tess\n*.txt @yrsa\n")
        self.assertEqual(owners_for_path(flipped, "a.txt"), ("@yrsa",))

    def test_matching_shapes_basename_anchored_dir_and_double_star(self):
        basename = parse_codeowners("*.py @yrsa\n")
        self.assertEqual(owners_for_path(basename, "x.py"), ("@yrsa",))
        self.assertEqual(
            owners_for_path(basename, "src/deep/x.py"), ("@yrsa",))
        self.assertEqual(owners_for_path(basename, "x.txt"), ())
        anchored = parse_codeowners("/docs/guide.md @tess\n")
        self.assertEqual(
            owners_for_path(anchored, "docs/guide.md"), ("@tess",))
        self.assertEqual(
            owners_for_path(anchored, "sub/docs/guide.md"), ())
        rooted = parse_codeowners("src/*.py @tess\n")
        self.assertEqual(owners_for_path(rooted, "src/x.py"), ("@tess",))
        self.assertEqual(owners_for_path(rooted, "src/deep/x.py"), ())
        self.assertEqual(owners_for_path(rooted, "other/x.py"), ())
        directory = parse_codeowners("assets/ @yrsa\n")
        self.assertEqual(
            owners_for_path(directory, "assets/logo.png"), ("@yrsa",))
        self.assertEqual(
            owners_for_path(directory, "src/assets/logo.png"), ("@yrsa",))
        self.assertEqual(
            owners_for_path(directory, "src/assets2/logo.png"), ())
        crossing = parse_codeowners("**/*.rs @tess\n")
        self.assertEqual(owners_for_path(crossing, "c.rs"), ("@tess",))
        self.assertEqual(
            owners_for_path(crossing, "a/b/c.rs"), ("@tess",))
        self.assertEqual(owners_for_path(crossing, "a/b/c.py"), ())

    def test_a_bad_owner_token_warns_verbatim_and_skips_its_line(self):
        parsed = parse_codeowners(
            "good.txt @yrsa\n"
            "bad.txt not-an-owner\n"
            "also-bad.txt @yrsa bogus!\n"
            "team.txt @volmarr/core\n"
            "mail.txt someone@example.com\n")
        self.assertEqual([r.pattern for r in parsed.rules],
                         ["good.txt", "team.txt", "mail.txt"])
        self.assertEqual(len(parsed.warnings), 2)
        self.assertEqual(parsed.warnings[0].token, "not-an-owner")
        self.assertEqual(parsed.warnings[0].line_no, 2)
        self.assertIn("not-an-owner", str(parsed.warnings[0]))
        self.assertEqual(parsed.warnings[1].token, "bogus!")
        self.assertEqual(parsed.warnings[1].line_no, 3)


class CodeownersStoreTests(unittest.TestCase):
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
        self.codeowners = PullRequestCodeownersStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.wired_prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock,
            codeowners_sync=self.codeowners.sync_requests)
        self.wired_xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock,
            codeowners_sync=self.codeowners.sync_requests)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")

    # -- helpers ---------------------------------------------------------
    def _open(self, base_files, head_files, *, name="pub", wired=False,
              author=None):
        if name != "pub":
            self.repos.create_repository(
                self.owner.id, "volmarr", name, visibility="public")
        path = self.repos.path_for("volmarr", name)
        base_oid = make_commit(path, None, base_files, "base")
        git(path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(path, base_oid, head_files, "feature work")
        git(path, "update-ref", "refs/heads/feature", head_oid)
        store = self.wired_prs if wired else self.prs
        pr = store.create_pull_request(
            author or self.owner, "volmarr", name,
            base_branch="main", head_branch="feature")
        return pr, path, base_oid, head_oid

    def _audit_count(self, action="repo.pull_request.codeowners_request"):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = ?",
            (action,)).fetchone()
        return int(row["c"])

    def _refs(self, number, name="pub", viewer=None):
        rows = self.codeowners.requests_for(
            viewer or self.owner, "volmarr", name, number)
        return rows

    # -- the store ---------------------------------------------------------
    def test_no_codeowners_file_means_no_requests(self):
        self.assertEqual(db.schema_version(self.conn), 113)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        pr, _path, _base, _head = self._open(
            {"a.txt": "alpha\n"}, {"a.txt": "alpha\nbeta\n"})
        report = self.codeowners.sync_requests(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(report.matched_owners, ())
        self.assertEqual(report.requested_now, ())
        self.assertIsNone(report.codeowners_source)
        self.assertIsNone(report.source_path)
        self.assertEqual(self._refs(pr.number), [])
        self.assertEqual(self._audit_count(), 0)
        self.assertIn("No CODEOWNERS",
                      render_codeowners_requests(report))

    def test_root_file_comes_from_the_base_branch_and_fires_on_open(self):
        pr, _path, _base, head_oid = self._open(
            {"CODEOWNERS": "a.txt @yrsa\n", "a.txt": "alpha\n"},
            {"CODEOWNERS": "a.txt @tess\n", "a.txt": "alpha\nbeta\n"},
            wired=True)
        # No explicit sync was called: the on-open hook did it,
        # and it read the base branch's file, not the head's copy.
        rows = self._refs(pr.number)
        self.assertEqual([r.owner_ref for r in rows], ["@yrsa"])
        self.assertEqual(rows[0].user_id, self.reader.id)
        self.assertEqual(rows[0].source, "codeowners")
        self.assertEqual(rows[0].head_oid, head_oid)
        report = self.codeowners.sync_requests(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(report.codeowners_source, "CODEOWNERS")
        self.assertEqual(report.requested_now, ())
        self.assertEqual(report.already_requested, ("@yrsa",))

    def test_docs_and_samverk_locations_are_fallbacks(self):
        pr, _p, _b, _h = self._open(
            {"docs/CODEOWNERS": "a.txt @yrsa\n", "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"})
        report = self.codeowners.sync_requests(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(report.codeowners_source, "docs/CODEOWNERS")
        self.assertEqual([r.owner_ref for r in self._refs(pr.number)],
                         ["@yrsa"])
        other, _p2, _b2, _h2 = self._open(
            {".samverk/CODEOWNERS": "a.txt @tess\n", "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"}, name="samv")
        report = self.codeowners.sync_requests(
            self.owner, "volmarr", "samv", other.number)
        self.assertEqual(report.codeowners_source, ".samverk/CODEOWNERS")
        self.assertEqual(
            [r.owner_ref for r in self._refs(other.number, name="samv")],
            ["@tess"])

    def test_author_is_never_self_requested_and_tokens_record_honestly(self):
        names = ["a.txt", "b.txt", "c.txt", "d.txt", "e.txt"]
        base = {"CODEOWNERS": (
            "a.txt @volmarr\n"
            "b.txt @ghost\n"
            "c.txt @volmarr/core\n"
            "d.txt someone@example.com\n"
            "e.txt @yrsa\n")}
        base.update({name: "x\n" for name in names})
        head = {name: "x\ny\n" for name in names}
        pr, _p, _b, _h = self._open(base, head)
        report = self.codeowners.sync_requests(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(report.matched_owners, (
            "@ghost", "@volmarr/core", "someone@example.com", "@yrsa"))
        rows = {r.owner_ref: r for r in self._refs(pr.number)}
        self.assertNotIn("@volmarr", rows)
        self.assertIsNone(rows["@ghost"].user_id)
        self.assertIsNone(rows["@volmarr/core"].user_id)
        self.assertIsNone(rows["someone@example.com"].user_id)
        self.assertEqual(rows["@yrsa"].user_id, self.reader.id)

    def test_sync_is_idempotent_and_audits_once_per_actual_addition(self):
        pr, _p, _b, _h = self._open(
            {"CODEOWNERS": "a.txt @yrsa\nb.txt @tess\n",
             "a.txt": "a\n", "b.txt": "b\n"},
            {"a.txt": "a\nmore\n", "b.txt": "b\nmore\n"})
        first = self.codeowners.sync_requests(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(first.requested_now, ("@yrsa", "@tess"))
        self.assertEqual(self._audit_count(), 1)
        detail = self.conn.execute(
            "SELECT detail FROM audit_log WHERE action = ?",
            ("repo.pull_request.codeowners_request",)).fetchone()["detail"]
        self.assertIn("@yrsa", detail)
        self.assertIn("@tess", detail)
        second = self.codeowners.sync_requests(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(second.requested_now, ())
        self.assertEqual(second.already_requested, ("@yrsa", "@tess"))
        self.assertEqual(self._audit_count(), 1)
        rows = self._refs(pr.number)
        self.assertEqual(len(rows), 2)
        html = render_codeowners_requests(rows)
        self.assertIn("@yrsa", html)
        self.assertIn("Samverk account", html)

    def test_a_push_touching_a_new_owners_file_adds_only_the_new_owner(self):
        pr, path, _base, head_oid = self._open(
            {"CODEOWNERS": "a.txt @yrsa\nb.txt @tess\n",
             "a.txt": "a\n", "b.txt": "b\n"},
            {"a.txt": "a\nmore\n", "b.txt": "b\n"})
        first = self.codeowners.sync_requests(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(first.requested_now, ("@yrsa",))
        pushed = make_commit(
            path, head_oid,
            {"CODEOWNERS": "a.txt @yrsa\nb.txt @tess\n",
             "a.txt": "a\nmore\n", "b.txt": "b\nmore\n"},
            "push")
        git(path, "update-ref", "refs/heads/feature", pushed)
        second = self.codeowners.sync_requests(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(second.requested_now, ("@tess",))
        self.assertEqual(second.already_requested, ("@yrsa",))
        rows = self._refs(pr.number)
        self.assertEqual([r.owner_ref for r in rows], ["@yrsa", "@tess"])
        self.assertEqual(rows[0].head_oid, head_oid)
        self.assertEqual(rows[1].head_oid, pushed)
        self.assertEqual(self._audit_count(), 2)

    def test_a_closed_pull_request_sync_adds_nothing(self):
        pr, _p, _b, _h = self._open(
            {"CODEOWNERS": "a.txt @yrsa\n", "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"})
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE id = ?",
                (pr.row_id,))
        report = self.codeowners.sync_requests(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(report.requested_now, ())
        self.assertEqual(self._refs(pr.number), [])
        self.assertEqual(self._audit_count(), 0)

    def test_a_private_repository_answers_a_stranger_uniformly(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        priv_path = self.repos.path_for("volmarr", "priv")
        priv_base = make_commit(
            priv_path, None,
            {"CODEOWNERS": "s.txt @yrsa\n", "s.txt": "s\n"}, "one")
        git(priv_path, "update-ref", "refs/heads/main", priv_base)
        priv_head = make_commit(
            priv_path, priv_base, {"s.txt": "s\nmore\n"}, "two")
        git(priv_path, "update-ref", "refs/heads/feature", priv_head)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "priv", base_branch="main",
            head_branch="feature")
        with self.assertRaises(PullRequestError) as caught:
            self.codeowners.sync_requests(
                self.reader, "volmarr", "priv", pr.number)
        self.assertEqual(
            caught.exception.reason, "pull_request_not_found")
        with self.assertRaises(PullRequestError) as caught:
            self.codeowners.requests_for(
                self.reader, "volmarr", "priv", pr.number)
        self.assertEqual(
            caught.exception.reason, "pull_request_not_found")

    def test_cross_fork_opening_requests_from_the_base_branch_file(self):
        base_oid = make_commit(
            self.path, None,
            {"CODEOWNERS": "a.txt @tess\n", "a.txt": "alpha\n"}, "base")
        git(self.path, "update-ref", "refs/heads/main", base_oid)
        self.forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fork_head = make_commit(
            fork_path, base_oid,
            {"CODEOWNERS": "a.txt @tess\n",
             "a.txt": "alpha\nfrom the fork\n"},
            "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        created = self.wired_xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub", head_branch="feature")
        rows = self._refs(created.number)
        self.assertEqual([r.owner_ref for r in rows], ["@tess"])
        self.assertEqual(rows[0].user_id, self.third.id)
        self.assertEqual(rows[0].head_oid, fork_head)


if __name__ == "__main__":
    unittest.main()
