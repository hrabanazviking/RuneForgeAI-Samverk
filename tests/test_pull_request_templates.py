"""S-162 acceptance battery: pull request templates.

Acceptance (roadmap S-162): PR templates — single
and per-directory templates; template picker on
creation.

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
from samverk.pull_request_forks import (
    ForkPullRequestStore, render_cross_fork_page)
from samverk.pull_requests import (
    PullRequestError, PullRequestStore, render_creation_page)
from samverk.pull_request_templates import (
    PullRequestTemplateError, PullRequestTemplateStore,
    render_template_picker)
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


class TemplateStoreTests(unittest.TestCase):
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
        self.templates = PullRequestTemplateStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")

    # -- helpers ---------------------------------------------------------
    def _seed(self, base_files, head_files, *, name="pub"):
        if name != "pub":
            self.repos.create_repository(
                self.owner.id, "volmarr", name, visibility="public")
        path = self.repos.path_for("volmarr", name)
        base_oid = make_commit(path, None, base_files, "base")
        git(path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(path, base_oid, head_files, "feature work")
        git(path, "update-ref", "refs/heads/feature", head_oid)
        return path, base_oid, head_oid

    def _audit_detail(self, action="repo.pull_request.create"):
        row = self.conn.execute(
            "SELECT detail FROM audit_log WHERE action = ?"
            " ORDER BY seq DESC LIMIT 1",
            (action,)).fetchone()
        return row["detail"] if row else ""

    # -- discovery ---------------------------------------------------------
    def test_no_templates_means_blank_start_and_no_new_state(self):
        self.assertEqual(db.schema_version(self.conn), 88)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 127)
        self._seed({"a.txt": "alpha\n"}, {"a.txt": "alpha\nbeta\n"})
        choice = self.templates.list_templates(
            self.owner, "volmarr", "pub", base_branch="main")
        self.assertEqual(choice.mode, "none")
        self.assertEqual(choice.templates, ())
        self.assertIsNone(choice.single)
        self.assertEqual(choice.default_body, "")
        self.assertEqual(
            self.templates.body_for(self.owner, "volmarr", "pub",
                                    base_branch="main"), "")
        html = render_template_picker(choice)
        self.assertIn("No pull request templates", html)
        self.assertIn("description starts blank", html)

    def test_single_root_template_auto_fills_on_create(self):
        self._seed(
            {"pull_request_template.md": "## What\n\nDescribe it.\n",
             "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"})
        choice = self.templates.list_templates(
            self.owner, "volmarr", "pub", base_branch="main")
        self.assertEqual(choice.mode, "single")
        self.assertEqual(choice.single.path,
                         "pull_request_template.md")
        self.assertEqual(choice.single.name, "pull_request_template")
        pr = self.templates.create_pull_request(
            self.owner, "volmarr", "pub",
            base_branch="main", head_branch="feature")
        self.assertEqual(pr.body, "## What\n\nDescribe it.\n")
        self.assertIn("pull_request_template", self._audit_detail())
        self.assertNotIn("Describe it.", self._audit_detail())

    def test_single_fallback_locations_and_first_hit_wins(self):
        self._seed(
            {"docs/pull_request_template.md": "docs template\n",
             "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"}, name="docs")
        choice = self.templates.list_templates(
            self.owner, "volmarr", "docs", base_branch="main")
        self.assertEqual(choice.single.path,
                         "docs/pull_request_template.md")
        self.assertEqual(choice.single.body, "docs template\n")
        self._seed(
            {"pull_request_template.md": "root wins\n",
             "docs/pull_request_template.md": "docs loses\n",
             "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"}, name="root")
        choice = self.templates.list_templates(
            self.owner, "volmarr", "root", base_branch="main")
        self.assertEqual(choice.single.path,
                         "pull_request_template.md")
        self.assertEqual(choice.single.body, "root wins\n")
        self._seed(
            {".github/pull_request_template.md": "github dir\n",
             "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"}, name="gh")
        choice = self.templates.list_templates(
            self.owner, "volmarr", "gh", base_branch="main")
        self.assertEqual(
            choice.single.path, ".github/pull_request_template.md")

    def test_directory_templates_listed_sorted_by_name(self):
        self._seed(
            {"PULL_REQUEST_TEMPLATE/feature.md": "feature body\n",
             "PULL_REQUEST_TEMPLATE/bug.md": "bug body\n",
             "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"})
        choice = self.templates.list_templates(
            self.owner, "volmarr", "pub", base_branch="main")
        self.assertEqual(choice.mode, "multiple")
        self.assertEqual([t.name for t in choice.templates],
                         ["bug", "feature"])
        self.assertEqual(choice.directory, "PULL_REQUEST_TEMPLATE")
        self.assertEqual(choice.default_body, "")
        self.assertIn("2 pull request templates", choice.words)

    def test_directory_template_chosen_case_insensitively(self):
        self._seed(
            {"PULL_REQUEST_TEMPLATE/Bug.md": "bug body\n",
             "PULL_REQUEST_TEMPLATE/feature.md": "feature body\n",
             "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"})
        pr = self.templates.create_pull_request(
            self.owner, "volmarr", "pub",
            base_branch="main", head_branch="feature",
            template_name="bug")
        self.assertEqual(pr.body, "bug body\n")
        self.assertIn('"template":"Bug"', self._audit_detail())
        got = self.templates.get_template(
            self.owner, "volmarr", "pub", "FEATURE",
            base_branch="main")
        self.assertEqual(got.body, "feature body\n")

    def test_unknown_template_refused_and_burns_nothing(self):
        self._seed(
            {"PULL_REQUEST_TEMPLATE/bug.md": "bug body\n",
             "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"})
        with self.assertRaises(PullRequestTemplateError) as caught:
            self.templates.create_pull_request(
                self.owner, "volmarr", "pub",
                base_branch="main", head_branch="feature",
                template_name="nope")
        self.assertEqual(caught.exception.reason,
                         "template_not_found")
        self.assertEqual(self.prs.list_pull_requests(
            self.owner, "volmarr", "pub"), [])
        pr = self.templates.create_pull_request(
            self.owner, "volmarr", "pub",
            base_branch="main", head_branch="feature")
        self.assertEqual(pr.number, 1)

    def test_explicit_body_wins_over_template(self):
        self._seed(
            {"pull_request_template.md": "template body\n",
             "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"})
        pr = self.templates.create_pull_request(
            self.owner, "volmarr", "pub",
            base_branch="main", head_branch="feature",
            template_name="pull_request_template",
            body="my own words\n")
        self.assertEqual(pr.body, "my own words\n")
        self.assertNotIn("pull_request_template", self._audit_detail())

    def test_templates_come_from_base_branch_not_head(self):
        self._seed(
            {"pull_request_template.md": "base template\n",
             "a.txt": "alpha\n"},
            {"pull_request_template.md": "head template\n",
             "a.txt": "alpha\nbeta\n"})
        pr = self.templates.create_pull_request(
            self.owner, "volmarr", "pub",
            base_branch="main", head_branch="feature")
        self.assertEqual(pr.body, "base template\n")

    # -- picker + pages ---------------------------------------------------
    def test_picker_render_lists_directory_templates(self):
        self._seed(
            {"PULL_REQUEST_TEMPLATE/bug.md": "bug body\n",
             "PULL_REQUEST_TEMPLATE/feature.md": "feature body\n",
             "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"})
        choice = self.templates.list_templates(
            self.owner, "volmarr", "pub", base_branch="main")
        html = render_template_picker(choice)
        self.assertIn("?template=bug", html)
        self.assertIn("?template=feature", html)
        self.assertIn("blank description", html)
        self.assertIn("PULL_REQUEST_TEMPLATE/bug.md", html)

    def test_creation_page_prefills_body_for_single_template(self):
        self._seed(
            {"pull_request_template.md": "## What\n\nSay it.\n",
             "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"})
        preview, choice = self.templates.picker_for_creation(
            self.owner, "volmarr", "pub", "main", "feature")
        self.assertTrue(preview.can_open)
        html = render_creation_page(preview, templates=choice)
        self.assertIn('<textarea name="body"', html)
        self.assertIn("## What", html)
        self.assertIn("Say it.", html)
        legacy = render_creation_page(preview)
        self.assertNotIn('<textarea name="body"', legacy)

    def test_creation_page_picker_for_multiple_templates(self):
        self._seed(
            {"PULL_REQUEST_TEMPLATE/bug.md": "bug body\n",
             "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"})
        preview, choice = self.templates.picker_for_creation(
            self.owner, "volmarr", "pub", "main", "feature")
        html = render_creation_page(preview, templates=choice)
        self.assertIn("?template=bug", html)
        self.assertIn('<textarea name="body"', html)
        self.assertNotIn("bug body", html)

    # -- standing + cross-fork --------------------------------------------
    def test_private_repository_answers_a_stranger_uniformly(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        priv_path = self.repos.path_for("volmarr", "priv")
        priv_base = make_commit(
            priv_path, None,
            {"pull_request_template.md": "secret\n", "s.txt": "s\n"},
            "one")
        git(priv_path, "update-ref", "refs/heads/main", priv_base)
        with self.assertRaises(PullRequestTemplateError) as caught:
            self.templates.list_templates(self.reader, "volmarr", "priv")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(PullRequestTemplateError) as caught:
            self.templates.get_template(
                self.reader, "volmarr", "priv", "pull_request_template")
        self.assertEqual(caught.exception.reason, "repo_not_found")

    def test_reader_may_look_but_not_create(self):
        self._seed(
            {"pull_request_template.md": "template body\n",
             "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"})
        choice = self.templates.list_templates(
            self.reader, "volmarr", "pub", base_branch="main")
        self.assertEqual(choice.mode, "single")
        with self.assertRaises(PullRequestError) as caught:
            self.templates.create_pull_request(
                self.reader, "volmarr", "pub",
                base_branch="main", head_branch="feature")
        self.assertEqual(caught.exception.reason, "permission_denied")

    def test_cross_fork_create_uses_base_repo_template(self):
        base_oid = make_commit(
            self.path, None,
            {"pull_request_template.md": "base template\n",
             "a.txt": "alpha\n"}, "base")
        git(self.path, "update-ref", "refs/heads/main", base_oid)
        self.forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fork_head = make_commit(
            fork_path, base_oid,
            {"pull_request_template.md": "fork template\n",
             "a.txt": "alpha\nfrom the fork\n"},
            "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        created = self.templates.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub", head_branch="feature")
        self.assertEqual(created.pull_request.body, "base template\n")
        self.assertIn('"template":"pull_request_template"',
                      self._audit_detail())

    def test_directory_ignores_non_markdown_subdirs_and_binary(self):
        self._seed(
            {"PULL_REQUEST_TEMPLATE/notes.txt": "not a template\n",
             "PULL_REQUEST_TEMPLATE/sub/inner.md": "nested\n",
             "PULL_REQUEST_TEMPLATE/bad.md": "bi\x00nary\n",
             "PULL_REQUEST_TEMPLATE/good.md": "good body\n",
             "a.txt": "alpha\n"},
            {"a.txt": "alpha\nbeta\n"})
        choice = self.templates.list_templates(
            self.owner, "volmarr", "pub", base_branch="main")
        self.assertEqual([t.name for t in choice.templates], ["good"])
        self.assertEqual(
            self.templates.get_template(
                self.owner, "volmarr", "pub", "good",
                base_branch="main").body, "good body\n")


if __name__ == "__main__":
    unittest.main()
