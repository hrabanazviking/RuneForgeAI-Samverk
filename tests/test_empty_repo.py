"""S-065 acceptance battery: empty-repository state.

Acceptance (roadmap S-065): first-push instructions
generated per transport, correct and copyable.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.empty_repo import EmptyStateError, EmptyStateService, render_text
from samverk.repositories import RepositoryStore

def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

class EmptyRepoTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "fresh",
                                     visibility="private", default_branch="trunk")
        self.service = EmptyStateService(
            self.repos, http_base="https://forge.example/", ssh_host="forge.example")

    def test_empty_state_and_per_transport_instructions(self):
        self.assertTrue(self.service.is_empty("volmarr", "fresh"))
        ins = self.service.instructions_for(self.owner, "volmarr", "fresh")
        self.assertEqual(ins.default_branch, "trunk")
        by = {t.transport: t for t in ins.transports}
        self.assertEqual(set(by), {"https", "ssh"})
        self.assertEqual(by["https"].clone_url,
                         "https://forge.example/volmarr/fresh.git")
        self.assertEqual(by["ssh"].clone_url,
                         "ssh://git@forge.example/volmarr/fresh.git")
        for t in by.values():
            self.assertIn(f"git remote add origin {t.clone_url}",
                          t.new_repository_commands)
            self.assertIn("git push -u origin trunk",
                          t.new_repository_commands)
            self.assertEqual(t.existing_repository_commands[-1],
                             "git push -u origin trunk")
            for cmd in t.new_repository_commands + t.existing_repository_commands:
                self.assertFalse(cmd.startswith("$"), cmd)

    def test_rendered_page_is_copyable(self):
        text = render_text(self.service.instructions_for(self.owner, "volmarr", "fresh"))
        self.assertIn("https://forge.example/volmarr/fresh.git", text)
        self.assertIn("git push -u origin trunk", text)
        self.assertNotIn("\n$ ", text)

    def test_first_commit_ends_the_empty_state(self):
        path = self.repos.path_for("volmarr", "fresh")
        blob = git(path, "hash-object", "-w", "--stdin", input_bytes=b"x\n")
        tree = git(path, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
        commit = git(path, "commit-tree", tree, input_bytes=b"first\n")
        git(path, "update-ref", "refs/heads/trunk", commit)
        self.assertFalse(self.service.is_empty("volmarr", "fresh"))
        with self.assertRaises(EmptyStateError) as caught:
            self.service.instructions_for(self.owner, "volmarr", "fresh")
        self.assertEqual(caught.exception.reason, "repo_not_empty")

    def test_permission_and_unconfigured_transports_are_honest(self):
        with self.assertRaises(EmptyStateError) as caught:
            self.service.instructions_for(self.stranger, "volmarr", "fresh")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        https_only = EmptyStateService(self.repos, http_base="https://forge.example")
        ins = https_only.instructions_for(self.owner, "volmarr", "fresh")
        self.assertEqual([t.transport for t in ins.transports], ["https"])
        self.assertEqual(ins.unavailable_transports, ("ssh",))
        bare = EmptyStateService(self.repos)
        ins = bare.instructions_for(self.owner, "volmarr", "fresh")
        self.assertEqual(ins.transports, ())
        self.assertEqual(set(ins.unavailable_transports), {"https", "ssh"})
        with self.assertRaises(EmptyStateError):
            EmptyStateService(self.repos, http_base="ftp://x.example")
        with self.assertRaises(EmptyStateError):
            EmptyStateService(self.repos, http_base="https://user:pw@x.example")

if __name__ == "__main__":
    unittest.main()
