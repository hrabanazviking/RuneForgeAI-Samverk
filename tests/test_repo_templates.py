"""S-064 acceptance battery: repository templates.

Acceptance (roadmap S-064): create from a template repo
with variable substitution in the README only, honestly
scoped.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.repo_templates import TemplateError, TemplateStore, substitute_readme
from samverk.repositories import RepositoryStore

GIT_ENV = {
    "GIT_AUTHOR_NAME": "A U Thor", "GIT_AUTHOR_EMAIL": "a@example.com",
    "GIT_COMMITTER_NAME": "A U Thor", "GIT_COMMITTER_EMAIL": "a@example.com",
    "GIT_AUTHOR_DATE": "2020-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z",
}

def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = dict(os.environ); env.update(GIT_ENV)
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

def seed_template(repos, owner, accounts):
    repos.create_repository(owner.id, "volmarr", "tmpl", visibility="public")
    path = repos.path_for("volmarr", "tmpl")
    blobs = {}
    for name, data in (
            ("README.md", b"# {{project}}\nBy {{ author }}. License: {{license}}.\n"),
            ("code.py", b"NAME = '{{project}}'\n"),
            ("notes.txt", b"plain\n")):
        blobs[name] = git(path, "hash-object", "-w", "--stdin", input_bytes=data)
    tree_input = "".join(f"100644 blob {blobs[n]}\t{n}\n" for n in sorted(blobs)).encode()
    tree = git(path, "mktree", input_bytes=tree_input)
    commit = git(path, "commit-tree", tree, input_bytes=b"template v1\n")
    git(path, "update-ref", "refs/heads/main", commit)
    return path, commit

class TemplateTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.tmpl_path, self.tmpl_commit = seed_template(self.repos, self.owner, self.accounts)
        self.templates = TemplateStore(self.conn, self.data_root, self.accounts, self.repos)

    def test_substitute_readme_pure_function(self):
        new, used, left = substitute_readme("Hi {{ name }}, {{missing}}", {"name": "Sam"})
        self.assertEqual(new, "Hi Sam, {{missing}}")
        self.assertEqual(used, ["name"]); self.assertEqual(left, ["missing"])

    def test_marking_is_owner_only(self):
        with self.assertRaises(TemplateError) as caught:
            self.templates.set_template(self.other.id, "volmarr", "tmpl", True)
        self.assertEqual(caught.exception.reason, "not_repo_owner")
        marked = self.templates.set_template(self.owner.id, "volmarr", "tmpl", True)
        self.assertTrue(marked.is_template)
        self.assertTrue(self.templates.is_template("volmarr", "tmpl"))

    def test_unmarked_repo_is_not_a_template(self):
        with self.assertRaises(TemplateError) as caught:
            self.templates.create_from_template(self.other.id, "volmarr", "tmpl", "copy")
        self.assertEqual(caught.exception.reason, "not_a_template")

    def test_creation_substitutes_readme_only(self):
        self.templates.set_template(self.owner.id, "volmarr", "tmpl", True)
        result = self.templates.create_from_template(
            self.other.id, "volmarr", "tmpl", "myproj",
            variables={"project": "MyProj", "author": "Yrsa"})
        repo = result.repository
        self.assertEqual(repo.full_name, "yrsa/myproj")
        self.assertIsNone(repo.fork_of_id)
        self.assertIsNotNone(repo.template_of_id)
        self.assertTrue(result.readme_changed)
        self.assertEqual(result.substituted_keys, ("author", "project"))
        self.assertEqual(result.placeholders_left, ("license",))
        path = self.repos.path_for("yrsa", "myproj")
        readme = git(path, "show", "HEAD:README.md")
        self.assertEqual(readme, "# MyProj\nBy Yrsa. License: {{license}}.")
        code = git(path, "show", "HEAD:code.py")
        self.assertEqual(code, "NAME = '{{project}}'")
        parent = git(path, "rev-parse", "HEAD^")
        self.assertEqual(parent, self.tmpl_commit)
        subject = git(path, "log", "-1", "--format=%s", "HEAD")
        self.assertIn("Initialize from template volmarr/tmpl", subject)

    def test_no_variables_copies_history_untouched(self):
        self.templates.set_template(self.owner.id, "volmarr", "tmpl", True)
        result = self.templates.create_from_template(self.other.id, "volmarr", "tmpl", "plain")
        self.assertFalse(result.readme_changed)
        self.assertEqual(result.placeholders_left, ("author", "license", "project"))
        path = self.repos.path_for("yrsa", "plain")
        self.assertEqual(git(path, "rev-parse", "HEAD"), self.tmpl_commit)

    def test_private_template_hidden_and_no_public_escalation(self):
        self.repos.update_metadata(self.owner.id, "volmarr", "tmpl", visibility="private")
        self.templates.set_template(self.owner.id, "volmarr", "tmpl", True)
        with self.assertRaises(TemplateError) as caught:
            self.templates.create_from_template(self.other.id, "volmarr", "tmpl", "x1")
        self.assertEqual(caught.exception.reason, "no_such_repo")
        with self.assertRaises(TemplateError) as caught:
            self.templates.create_from_template(
                self.owner.id, "volmarr", "tmpl", "x2", visibility="public")
        self.assertEqual(caught.exception.reason, "template_visibility_escalation")
        with self.assertRaises(TemplateError):
            self.templates.create_from_template(
                self.owner.id, "volmarr", "tmpl", "x3", variables={"bad key": "v"})

if __name__ == "__main__":
    unittest.main()
